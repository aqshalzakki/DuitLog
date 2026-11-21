pub mod model;
pub mod report;
pub(crate) mod store;
pub mod sync;
mod write;

#[cfg(test)]
mod tests;

use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sqlx::{Acquire, FromRow, MySql, MySqlPool, Transaction, types::Json};
use uuid::Uuid;

use crate::crypto;
use model::*;
use store::{Account, Borrower};

#[derive(Debug)]
pub enum Failure {
    Business(Rejection),
    Temporary,
    Unknown,
    Internal,
}

impl From<Code> for Failure {
    fn from(code: Code) -> Self {
        Self::Business(code.into())
    }
}

impl From<Rejection> for Failure {
    fn from(value: Rejection) -> Self {
        Self::Business(value)
    }
}

impl From<sqlx::Error> for Failure {
    fn from(error: sqlx::Error) -> Self {
        match &error {
            sqlx::Error::PoolTimedOut => Self::Temporary,
            sqlx::Error::Database(db) => {
                let number = db
                    .try_downcast_ref::<sqlx::mysql::MySqlDatabaseError>()
                    .map(|db| db.number());
                if matches!(number, Some(1205 | 1213)) {
                    Self::Temporary
                } else {
                    eprintln!("Financial database operation failed mysql_number={number:?}");
                    Self::Internal
                }
            }
            _ => {
                eprintln!(
                    "Financial database operation failed kind={:?}",
                    std::mem::discriminant(&error)
                );
                Self::Internal
            }
        }
    }
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "snake_case", tag = "action")]
pub enum Mutation {
    Opening {
        target: Option<Money>,
    },
    Adjustment {
        target: Money,
    },
    Create(ActivityInput),
    Edit {
        id: Uuid,
        version: i64,
        input: ActivityInput,
    },
    Delete {
        id: Uuid,
        version: i64,
        reason: Option<String>,
    },
    Restore {
        id: Uuid,
        version: i64,
    },
    AddBorrower(BorrowerInput),
    EditBorrower {
        id: Uuid,
        version: i64,
        input: BorrowerInput,
    },
    ArchiveBorrower {
        id: Uuid,
        version: i64,
        archive: bool,
    },
    AddCategory {
        name: String,
    },
    RenameCategory {
        id: Uuid,
        version: i64,
        name: String,
    },
    ArchiveCategory {
        id: Uuid,
        version: i64,
        archive: bool,
    },
}

impl Mutation {
    fn creates(&self) -> bool {
        matches!(
            self,
            Self::Opening { target: Some(_) }
                | Self::Adjustment { .. }
                | Self::Create(_)
                | Self::AddBorrower(_)
                | Self::AddCategory { .. }
        )
    }

    fn normalize(&mut self) {
        if let Self::Create(input) | Self::Edit { input, .. } = self {
            input.normalize();
        }
    }
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Confirmed {
    pub attempt_id: Uuid,
    pub resource_id: Option<String>,
    pub version: Option<i64>,
    pub financial_sequence: Option<i64>,
    pub effective_at: Option<Moment>,
    pub financial_state_version: i64,
    pub balance: Money,
    pub receivables: Money,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE", tag = "status")]
pub enum Outcome {
    Confirmed(Confirmed),
    Rejected {
        #[serde(rename = "attemptId")]
        attempt_id: Uuid,
        #[serde(flatten)]
        rejection: Rejection,
    },
}

#[derive(FromRow)]
struct Operation {
    payload_hash: Vec<u8>,
    result: Json<Outcome>,
}

async fn commit(tx: Transaction<'_, MySql>) -> Result<(), Failure> {
    tx.commit().await.map_err(|_| Failure::Unknown)
}

fn changed<T>(result: Result<T, impl std::fmt::Debug>) -> Result<T, Failure> {
    result.map_err(|_| Failure::Internal)
}

pub async fn execute(
    db: &MySqlPool,
    owner: &str,
    attempt: Uuid,
    client: Uuid,
    mut mutation: Mutation,
) -> Result<Outcome, Failure> {
    mutation.normalize();
    let payload = changed(serde_json::to_string(&(client, &mutation)))?;
    let hash = crypto::digest(&payload);
    let first = once(db, owner, attempt, client, &mutation, &hash).await;
    if matches!(first, Err(Failure::Temporary)) {
        tokio::time::sleep(std::time::Duration::from_millis(35)).await;
        return once(db, owner, attempt, client, &mutation, &hash).await;
    }
    first
}

async fn once(
    db: &MySqlPool,
    owner: &str,
    attempt: Uuid,
    client: Uuid,
    mutation: &Mutation,
    hash: &[u8],
) -> Result<Outcome, Failure> {
    let attempt_id = attempt.to_string();
    let client_id = client.to_string();
    let mut tx = db.begin().await?;
    sqlx::query("SET SESSION innodb_lock_wait_timeout=2")
        .execute(&mut *tx)
        .await?;
    let active: bool =
        sqlx::query_scalar("SELECT active FROM financial_recovery WHERE id=1 FOR SHARE")
            .fetch_one(&mut *tx)
            .await?;
    if active {
        return Err(Code::FinancialRecoveryActive.into());
    }
    let mut state = store::anchor(&mut tx, owner).await?;
    if state.frozen {
        return Err(Code::FinancialIntegrityFrozen.into());
    }
    let existing: Option<Operation> = sqlx::query_as(
        "SELECT payload_hash,result FROM financial_operations WHERE owner_id=? AND attempt_id=?",
    )
    .bind(owner)
    .bind(&attempt_id)
    .fetch_optional(&mut *tx)
    .await?;
    if let Some(record) = existing {
        tx.rollback().await?;
        if record.payload_hash != hash {
            return Err(Code::IdempotencyPayloadMismatch.into());
        }
        return Ok(record.result.0);
    }
    let at = Moment::now();
    if let Some(reason) = mismatch(&mut tx, owner, &state).await? {
        freeze(&mut tx, owner, "system", at, reason).await?;
        commit(tx).await?;
        return Err(Code::FinancialIntegrityFrozen.into());
    }
    if mutation.creates() {
        let confirmed: Option<String> = sqlx::query_scalar(
            "SELECT attempt_id FROM financial_client_creates WHERE owner_id=? AND client_id=?",
        )
        .bind(owner)
        .bind(&client_id)
        .fetch_optional(&mut *tx)
        .await?;
        if let Some(confirmed) = confirmed {
            let outcome = Outcome::Rejected {
                attempt_id: attempt,
                rejection: Rejection {
                    code: Code::AlreadyConfirmedActivity,
                    conflict_details: Some(json!({ "confirmedAttemptId": confirmed })),
                },
            };
            record(&mut tx, owner, &attempt_id, hash, &outcome, at).await?;
            commit(tx).await?;
            return Ok(outcome);
        }
    }
    let mut savepoint = tx.begin().await?;
    let changed =
        write::apply_and_project(&mut savepoint, owner, &attempt_id, at, &mut state, mutation)
            .await;
    let outcome = match changed {
        Ok(applied) => {
            savepoint.commit().await?;
            Outcome::Confirmed(Confirmed {
                attempt_id: attempt,
                resource_id: applied.id,
                version: applied.version,
                financial_sequence: applied.sequence,
                effective_at: applied.effective_at,
                financial_state_version: state.version,
                balance: Money(state.balance),
                receivables: Money(state.receivables),
            })
        }
        Err(Failure::Business(rejection)) => {
            savepoint.rollback().await?;
            Outcome::Rejected {
                attempt_id: attempt,
                rejection,
            }
        }
        Err(error) => {
            // MySQL can have already rolled the whole transaction back after a deadlock.
            drop(savepoint);
            let _ = tx.rollback().await;
            return Err(error);
        }
    };
    record(&mut tx, owner, &attempt_id, hash, &outcome, at).await?;
    if mutation.creates() && matches!(outcome, Outcome::Confirmed(_)) {
        sqlx::query(
            "INSERT INTO financial_client_creates (owner_id,client_id,attempt_id) VALUES (?,?,?)",
        )
        .bind(owner)
        .bind(client_id)
        .bind(&attempt_id)
        .execute(&mut *tx)
        .await?;
    }
    commit(tx).await?;
    Ok(outcome)
}

async fn record(
    tx: &mut Transaction<'_, MySql>,
    owner: &str,
    attempt: &str,
    hash: &[u8],
    outcome: &Outcome,
    at: Moment,
) -> Result<(), Failure> {
    sqlx::query("INSERT INTO financial_operations (owner_id,attempt_id,payload_hash,result,action_at) VALUES (?,?,?,?,?)")
        .bind(owner).bind(attempt).bind(hash).bind(Json(outcome)).bind(at.0)
        .execute(&mut **tx).await?;
    Ok(())
}

async fn mismatch(
    tx: &mut Transaction<'_, MySql>,
    owner: &str,
    state: &Account,
) -> Result<Option<&'static str>, Failure> {
    let mut rows = store::ledger(tx, owner).await?;
    let projected = match replay(&mut rows) {
        Ok(result) => result,
        Err(_) => return Ok(Some("INVALID_LEDGER")),
    };
    let max = rows.iter().map(|row| row.sequence).max().unwrap_or(0);
    let openings = rows
        .iter()
        .filter(|row| row.kind == Kind::Opening && !row.deleted)
        .count();
    if state.balance != projected.balance
        || state.receivables != projected.receivables_total
        || max.checked_add(1) != Some(state.next_sequence)
        || !matches!(state.opening.as_str(), "pending" | "skipped" | "recorded")
        || openings != usize::from(state.opening == "recorded")
        || (state.opening == "pending" && !rows.is_empty())
    {
        return Ok(Some("ACCOUNT_PROJECTION_MISMATCH"));
    }
    if rows.iter().any(|row| {
        row.snapshot_delta.map(|item| item.0) != projected.snapshot_deltas.get(&row.id).copied()
    }) {
        return Ok(Some("SNAPSHOT_PROJECTION_MISMATCH"));
    }
    let borrowers = store::borrowers(tx, owner).await?;
    if borrowers.iter().any(|row| {
        row.outstanding != projected.receivables.get(&row.id).copied().unwrap_or(0)
            || (row.archived && row.outstanding != 0)
    }) {
        return Ok(Some("RECEIVABLE_PROJECTION_MISMATCH"));
    }
    Ok(None)
}

async fn freeze(
    tx: &mut Transaction<'_, MySql>,
    owner: &str,
    actor: &str,
    at: Moment,
    reason: &str,
) -> Result<(), Failure> {
    sqlx::query(
        "UPDATE financial_accounts SET frozen=TRUE,version=version+1,updated_at=? WHERE owner_id=?",
    )
    .bind(at.0)
    .bind(owner)
    .execute(&mut **tx)
    .await?;
    store::audit(
        tx,
        owner,
        actor,
        "INTEGRITY_FREEZE",
        at,
        None,
        json!({ "reason": reason }),
    )
    .await
}

pub async fn reconcile(
    db: &MySqlPool,
    owner: Uuid,
    actor: &str,
    unfreeze_reason: Option<&str>,
) -> Result<bool, Failure> {
    if actor.trim().is_empty() || actor.chars().count() > 100 {
        return Err(Code::ValidationError.into());
    }
    let owner = owner.to_string();
    let mut tx = db.begin().await?;
    let state = store::anchor(&mut tx, &owner).await?;
    let mismatch = mismatch(&mut tx, &owner, &state).await?;
    let at = Moment::now();
    let frozen = match (mismatch, state.frozen, unfreeze_reason) {
        (Some(reason), false, _) => {
            freeze(&mut tx, &owner, actor, at, reason).await?;
            true
        }
        (None, true, Some(reason))
            if !reason.trim().is_empty() && reason.chars().count() <= 500 =>
        {
            sqlx::query("UPDATE financial_accounts SET frozen=FALSE,version=version+1,updated_at=? WHERE owner_id=?")
                .bind(at.0).bind(&owner).execute(&mut *tx).await?;
            store::audit(
                &mut tx,
                &owner,
                actor,
                "INTEGRITY_UNFREEZE",
                at,
                None,
                json!({ "reason": reason }),
            )
            .await?;
            false
        }
        _ => state.frozen,
    };
    commit(tx).await?;
    Ok(frozen)
}

pub(crate) async fn view_state(db: &MySqlPool, owner: &str) -> Result<Value, Failure> {
    let mut tx = db.begin().await?;
    let state = store::read_account(&mut tx, owner).await?;
    let active: bool = sqlx::query_scalar("SELECT active FROM financial_recovery WHERE id=1")
        .fetch_one(&mut *tx)
        .await?;
    let timezone = store::timezone(&mut tx, owner).await?;
    tx.rollback().await?;
    Ok(json!({
        "timezone": timezone,
        "balance": Money(state.balance), "receivables": Money(state.receivables),
        "financialStateVersion": state.version, "opening": state.opening,
        "frozen": state.frozen, "recoveryActive": active, "updatedAt": state.updated_at.map(Moment),
    }))
}

/// Account zone for date grouping (BR-RPT-11). Only the zone column changes: stored instants and
/// snapshot targets stay as they are, so reports regroup without any ledger rewrite. Audited with
/// the old and new value under the account lock so two devices cannot interleave unaudited.
/// shortcut: the freeze/recovery check runs before the lock, like whole-sync; a hold that starts in
/// between still lets one zone change through, which never alters a balance.
pub(crate) async fn set_timezone(
    db: &MySqlPool,
    owner: &str,
    name: &str,
) -> Result<Value, Failure> {
    if report::zone(name).is_none() {
        return Err(Code::ValidationError.into());
    }
    // Writes financial_audit, so it waits while an operator verifies this account or the restore.
    sync_allowed(db, owner).await?;
    let mut tx = db.begin().await?;
    store::anchor(&mut tx, owner).await?;
    let before = store::timezone(&mut tx, owner).await?;
    if before != name {
        sqlx::query("UPDATE financial_accounts SET timezone=? WHERE owner_id=?")
            .bind(name)
            .bind(owner)
            .execute(&mut *tx)
            .await?;
        let details = json!({ "before": { "timezone": before }, "after": { "timezone": name } });
        store::audit(
            &mut tx,
            owner,
            owner,
            "TIMEZONE_CHANGED",
            Moment::now(),
            None,
            details,
        )
        .await?;
    }
    commit(tx).await?;
    Ok(json!({ "timezone": name }))
}

/// Whole-sync gate. Each item still rechecks both holds under the account lock in `execute`.
pub(crate) async fn sync_allowed(db: &MySqlPool, owner: &str) -> Result<(), Failure> {
    let mut conn = db.acquire().await?;
    let active: bool = sqlx::query_scalar("SELECT active FROM financial_recovery WHERE id=1")
        .fetch_one(&mut *conn)
        .await?;
    if active {
        return Err(Code::FinancialRecoveryActive.into());
    }
    if store::read_account(&mut conn, owner).await?.frozen {
        return Err(Code::FinancialIntegrityFrozen.into());
    }
    Ok(())
}

/// One report family over one consistent read. Refused while the account is frozen or recovery is
/// active, because a figure from an unverified ledger must not look official.
pub(crate) async fn report(
    db: &MySqlPool,
    owner: &str,
    family: &str,
    period: report::Period,
    from: Option<jiff::civil::Date>,
    to: Option<jiff::civil::Date>,
) -> Result<Value, Failure> {
    sync_allowed(db, owner).await?;
    // InnoDB REPEATABLE READ: zone, ledger, categories and borrowers come from the same snapshot.
    let mut tx = db.begin().await?;
    let zone_name = store::timezone(&mut tx, owner).await?;
    let now = Moment::now().0;
    let zone = report::zone(&zone_name).ok_or(Failure::Internal)?; // stored zones are validated on write
    let from = match from {
        Some(date) => date,
        None => report::today(now, &zone)?,
    };
    let ranges = report::ranges(period, from, to, now, &zone_name)?;
    let rows = store::ledger(&mut tx, owner).await?;
    let categories = store::categories(&mut tx, owner).await?;
    let borrowers = store::borrowers(&mut tx, owner).await?;
    tx.rollback().await?;
    // shortcut: loads and replays the owner's whole ledger per request; add stored period totals
    // or a checkpointed replay once a ledger reaches tens of thousands of rows.
    let ledger = report::Ledger::new(rows)?;
    match family {
        "income-expense" => report::income_expense(&ledger, &ranges, &categories),
        "balance-movement" => report::balance_movement(&ledger, &ranges),
        "receivables" => report::receivables(&ledger, &ranges, &borrowers),
        _ => Err(Code::NotFound.into()),
    }
}

pub(crate) async fn lookup(db: &MySqlPool, owner: &str, id: Uuid) -> Result<Outcome, Failure> {
    let result: Json<Outcome> = sqlx::query_scalar(
        "SELECT result FROM financial_operations WHERE owner_id=? AND attempt_id=?",
    )
    .bind(owner)
    .bind(id.to_string())
    .fetch_optional(db)
    .await?
    .ok_or(Code::NotFound)?;
    Ok(result.0)
}

/// `days` is an inclusive local date range, either side open, read in the account zone of the same snapshot.
pub(crate) async fn history(
    db: &MySqlPool,
    owner: &str,
    mut filter: store::Filter,
    days: (Option<jiff::civil::Date>, Option<jiff::civil::Date>),
) -> Result<Value, Failure> {
    let mut tx = db.begin().await?;
    if days.0.is_some() || days.1.is_some() {
        let zone = store::timezone(&mut tx, owner).await?;
        let zone = report::zone(&zone).ok_or(Failure::Internal)?;
        (filter.start, filter.end) = report::days(days.0, days.1, &zone)?;
    }
    let mut items = store::history(&mut tx, owner, &filter).await?;
    tx.rollback().await?;
    let more = items.len() > 50;
    items.truncate(50);
    let next = items.last().filter(|_| more).map(|row| row.sequence);
    Ok(json!({ "items": items, "nextCursor": next }))
}

pub(crate) async fn borrowers(db: &MySqlPool, owner: &str) -> Result<Vec<Value>, Failure> {
    let mut conn = db.acquire().await?;
    Ok(store::borrowers(&mut conn, owner)
        .await?
        .iter()
        .map(Borrower::view)
        .collect())
}

#[derive(FromRow)]
struct AuditRow {
    id: u64,
    actor: String,
    action: String,
    action_at: i64,
    attempt_id: Option<String>,
    details: Json<Value>,
}

pub(crate) async fn audit_page(
    db: &MySqlPool,
    owner: &str,
    before: Option<u64>,
) -> Result<Value, Failure> {
    let rows: Vec<AuditRow> = sqlx::query_as(
        "SELECT a.id,a.actor,a.action,a.action_at,a.attempt_id,a.details FROM financial_audit a
        WHERE a.owner_id=? AND (? IS NULL OR (a.action_at,a.id) <
          (SELECT b.action_at,b.id FROM financial_audit b WHERE b.owner_id=? AND b.id=?))
        ORDER BY a.action_at DESC,a.id DESC LIMIT 51",
    )
    .bind(owner)
    .bind(before)
    .bind(owner)
    .bind(before)
    .fetch_all(db)
    .await?;
    let next = (rows.len() > 50).then(|| rows[49].id);
    let items: Vec<Value> = rows.into_iter().take(50).map(|row| json!({
        "id": row.id, "actor": row.actor, "action": row.action, "actionAt": Moment(row.action_at),
        "attemptId": row.attempt_id, "details": row.details.0,
    })).collect();
    Ok(json!({ "items": items, "nextCursor": next }))
}
