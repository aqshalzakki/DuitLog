//! Partial Sync: each offline item goes through the same `execute` boundary as an online write,
//! in its own transaction, so one conflict never rolls back an independent item.

use serde_json::{Map, Value, json};
use sqlx::MySqlPool;
use uuid::Uuid;

use super::{Failure, Mutation, Outcome, execute, model::*};

/// Proposal: batch size limit, reviewable.
pub const MAX_ITEMS: usize = 50;

pub enum Payload {
    Borrower(BorrowerInput),
    Activity {
        input: ActivityInput,
        borrower_client: Option<Uuid>,
    },
}

pub struct Item {
    pub attempt: Uuid,
    pub client: Uuid,
    /// clientActivityIds of predecessor activities (persisted as `depends_on` once resolved).
    pub after: Vec<Uuid>,
    /// `None` when the item is malformed; it is reported alone and its children block.
    pub payload: Option<Payload>,
}

impl Item {
    /// The envelope needs valid v4 identities to report anything; everything else fails per item.
    pub fn parse(mut fields: Map<String, Value>) -> Option<Self> {
        let mut identity = |name| {
            fields
                .remove(name)
                .and_then(|value| value.as_str().and_then(|text| Uuid::parse_str(text).ok()))
                .filter(|id| id.get_version_num() == 4)
        };
        let (attempt, client) = (identity("attemptId")?, identity("clientActivityId")?);
        let mut ids = |name| -> Option<Vec<Uuid>> {
            match fields.remove(name) {
                None => Some(vec![]),
                Some(value) => serde_json::from_value(value).ok(),
            }
        };
        let after = ids("dependsOn");
        let borrower_client = fields
            .remove("borrowerClientId")
            .map(serde_json::from_value::<Uuid>);
        let kind = fields.remove("type");
        let payload = (|| {
            let after = after.as_ref()?;
            let fields = Value::Object(fields);
            match kind?.as_str()? {
                "BORROWER" if after.is_empty() && borrower_client.is_none() => {
                    Some(Payload::Borrower(serde_json::from_value(fields).ok()?))
                }
                "ACTIVITY" => {
                    let input: ActivityInput = serde_json::from_value(fields).ok()?;
                    let borrower_client = borrower_client.transpose().ok()?;
                    let offline = !matches!(input.kind, Kind::Opening | Kind::Adjustment);
                    let one_borrower = !(borrower_client.is_some() && input.borrower_id.is_some());
                    (offline && one_borrower && input.depends_on.is_empty()).then_some(
                        Payload::Activity {
                            input,
                            borrower_client,
                        },
                    )
                }
                _ => None,
            }
        })();
        let mut after = after.unwrap_or_default();
        if let Some(Payload::Activity {
            borrower_client: Some(id),
            ..
        }) = &payload
        {
            after.push(*id);
        }
        Some(Self {
            attempt,
            client,
            after,
            payload,
        })
    }
}

/// Dependency order, request order between independent items. Items left out sit on a cycle
/// (or depend on one) and are reported as blocked.
pub fn order(items: &[(Uuid, Vec<Uuid>)]) -> Vec<usize> {
    let in_batch = |id: &Uuid| items.iter().any(|(client, _)| client == id);
    let mut placed = vec![false; items.len()];
    let mut sorted = Vec::with_capacity(items.len());
    while let Some(next) = (0..items.len()).find(|&i| {
        !placed[i]
            && items[i].1.iter().all(|dep| {
                !in_batch(dep) || items.iter().zip(&placed).any(|((c, _), p)| c == dep && *p)
            })
    }) {
        placed[next] = true;
        sorted.push(next);
    }
    sorted
}

fn status(item: &Item, status: &str, code: &str) -> Value {
    json!({
        "clientActivityId": item.client, "attemptId": item.attempt, "status": status, "code": code,
    })
}

/// Server id of a confirmed create, if it is the expected kind and belongs to `owner`.
async fn resolve(
    db: &MySqlPool,
    owner: &str,
    client: Uuid,
    borrower: bool,
) -> Result<Option<Uuid>, Failure> {
    let id: Option<String> = sqlx::query_scalar(
        "SELECT JSON_UNQUOTE(JSON_EXTRACT(o.result,'$.resourceId')) FROM financial_client_creates c
         JOIN financial_operations o ON o.owner_id=c.owner_id AND o.attempt_id=c.attempt_id
         WHERE c.owner_id=? AND c.client_id=?",
    )
    .bind(owner)
    .bind(client.to_string())
    .fetch_optional(db)
    .await?;
    let Some(id) = id.and_then(|id| Uuid::parse_str(&id).ok()) else {
        return Ok(None);
    };
    let sql = if borrower {
        "SELECT EXISTS(SELECT 1 FROM borrowers WHERE owner_id=? AND id=?)"
    } else {
        "SELECT EXISTS(SELECT 1 FROM activities WHERE owner_id=? AND id=? AND kind BETWEEN 1 AND 4)"
    };
    let found: bool = sqlx::query_scalar(sql)
        .bind(owner)
        .bind(id.to_string())
        .fetch_one(db)
        .await?;
    Ok(found.then_some(id))
}

/// Results in request order. Stops at the first failure that is not a business decision: every
/// item shares the account lock, so pressing on would only queue more waits.
pub async fn run(db: MySqlPool, owner: String, mut items: Vec<Item>) -> Vec<Value> {
    let graph: Vec<_> = items.iter().map(|i| (i.client, i.after.clone())).collect();
    let mut results: Vec<Option<Value>> = vec![None; items.len()];
    let mut usable = vec![false; items.len()];
    let mut stopped = false;
    for index in order(&graph) {
        let item = &mut items[index];
        let failed: Vec<Uuid> = item
            .after
            .iter()
            .filter(|dep| {
                graph
                    .iter()
                    .zip(&usable)
                    .any(|((c, _), ok)| c == *dep && !ok)
            })
            .copied()
            .collect();
        if stopped {
            results[index] = Some(status(item, "NOT_PROCESSED", "SYNC_STOPPED"));
            continue;
        }
        if !failed.is_empty() {
            let mut value = status(item, "BLOCKED", "DEPENDENCY_BLOCKED");
            value["blockedBy"] = json!(failed);
            results[index] = Some(value);
            continue;
        }
        let Some(payload) = item.payload.take() else {
            results[index] = Some(status(item, "INVALID", "VALIDATION_ERROR"));
            continue;
        };
        let (value, ok, stop) = match prepare(&db, &owner, item, payload).await {
            Ok(Some(mutation)) => {
                match execute(&db, &owner, item.attempt, item.client, mutation).await {
                    Ok(outcome) => {
                        let ok = match &outcome {
                            Outcome::Confirmed(_) => true,
                            Outcome::Rejected { rejection, .. } => {
                                rejection.code == Code::AlreadyConfirmedActivity
                            }
                        };
                        let mut value = json!(outcome);
                        value["clientActivityId"] = json!(item.client);
                        (value, ok, false)
                    }
                    Err(error) => held(item, error),
                }
            }
            Ok(None) => {
                let mut value = status(item, "BLOCKED", "DEPENDENCY_BLOCKED");
                value["blockedBy"] = json!(item.after);
                (value, false, false)
            }
            Err(error) => held(item, error),
        };
        results[index] = Some(value);
        usable[index] = ok;
        stopped = stop;
    }
    let mut out = Vec::with_capacity(items.len());
    for (item, result) in items.iter().zip(results) {
        // Not placed by `order`: on or behind a dependency cycle.
        out.push(result.unwrap_or_else(|| status(item, "BLOCKED", "DEPENDENCY_CYCLE")));
    }
    out
}

/// Swap client references for server ids. `None` means a reference is not confirmed (yet).
async fn prepare(
    db: &MySqlPool,
    owner: &str,
    item: &Item,
    payload: Payload,
) -> Result<Option<Mutation>, Failure> {
    let (mut input, borrower_client) = match payload {
        Payload::Borrower(input) => return Ok(Some(Mutation::AddBorrower(input))),
        Payload::Activity {
            input,
            borrower_client,
        } => (input, borrower_client),
    };
    if let Some(client) = borrower_client {
        let Some(id) = resolve(db, owner, client, true).await? else {
            return Ok(None);
        };
        input.borrower_id = Some(id);
    }
    for dep in item
        .after
        .iter()
        .filter(|dep| Some(**dep) != borrower_client)
    {
        let Some(id) = resolve(db, owner, *dep, false).await? else {
            return Ok(None);
        };
        input.depends_on.push(id);
    }
    Ok(Some(Mutation::Create(input)))
}

fn held(item: &Item, error: Failure) -> (Value, bool, bool) {
    let value = match error {
        Failure::Business(rejection) if rejection.code == Code::IdempotencyPayloadMismatch => {
            status(item, "REJECTED", "IDEMPOTENCY_PAYLOAD_MISMATCH")
        }
        Failure::Business(rejection) => {
            let code = serde_json::to_value(rejection.code).unwrap_or(Value::Null);
            let mut value = status(item, "RETRYABLE", "");
            value["code"] = code;
            value
        }
        Failure::Temporary => status(item, "RETRYABLE", "TEMPORARY_FAILURE"),
        Failure::Unknown => status(item, "OUTCOME_UNKNOWN", "OUTCOME_UNKNOWN"),
        Failure::Internal => status(item, "FAILED", "INTERNAL_ERROR"),
    };
    (value, false, true)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ids(n: usize) -> Vec<Uuid> {
        (0..n).map(|_| Uuid::new_v4()).collect()
    }

    #[test]
    fn orders_parents_first_and_keeps_request_order() {
        let id = ids(4);
        // 0 depends on 2, 1 independent, 2 independent, 3 depends on 0 and an outside id.
        let graph = vec![
            (id[0], vec![id[2]]),
            (id[1], vec![]),
            (id[2], vec![]),
            (id[3], vec![id[0], Uuid::new_v4()]),
        ];
        assert_eq!(order(&graph), vec![1, 2, 0, 3]);
    }

    #[test]
    fn leaves_cycles_and_their_children_out() {
        let id = ids(4);
        let graph = vec![
            (id[0], vec![id[1]]),
            (id[1], vec![id[0]]),
            (id[2], vec![id[1]]),
            (id[3], vec![]),
        ];
        assert_eq!(order(&graph), vec![3]);
    }

    fn item(fields: Value) -> Option<Item> {
        let mut base = json!({ "attemptId": Uuid::new_v4(), "clientActivityId": Uuid::new_v4() });
        base.as_object_mut()?.extend(fields.as_object()?.clone());
        Item::parse(base.as_object()?.clone())
    }

    #[test]
    fn parses_offline_kinds_only() {
        let ok = item(json!({"type": "ACTIVITY", "kind": "DEDUCT", "amount": "5",
            "effectiveAt": "2024-01-01T00:00:00Z"}));
        assert!(ok.is_some_and(|i| i.payload.is_some()));
        let adjustment = item(
            json!({"type": "ACTIVITY", "kind": "ADJUSTMENT", "amount": "5",
            "effectiveAt": "2024-01-01T00:00:00Z"}),
        );
        assert!(adjustment.is_some_and(|i| i.payload.is_none()));
        let both = item(json!({"type": "ACTIVITY", "kind": "LOAN", "amount": "5",
            "effectiveAt": "2024-01-01T00:00:00Z", "borrowerId": Uuid::new_v4(),
            "borrowerClientId": Uuid::new_v4()}));
        assert!(both.is_some_and(|i| i.payload.is_none()));
        let borrower_ref = Uuid::new_v4();
        let loan = item(json!({"type": "ACTIVITY", "kind": "LOAN", "amount": "5",
            "effectiveAt": "2024-01-01T00:00:00Z", "borrowerClientId": borrower_ref}));
        assert!(loan.is_some_and(|i| i.payload.is_some() && i.after == vec![borrower_ref]));
        let bad_id = Item::parse(
            json!({"attemptId": "x", "clientActivityId": Uuid::new_v4()})
                .as_object()
                .cloned()
                .unwrap_or_default(),
        );
        assert!(bad_id.is_none());
    }
}
