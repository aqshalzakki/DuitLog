use serde_json::{Value, json};
use sqlx::{MySql, Transaction};

use super::{
    Failure, Mutation, changed,
    model::*,
    store::{self, Account},
};
use crate::crypto;

pub struct Applied {
    pub id: Option<String>,
    pub version: Option<i64>,
    pub sequence: Option<i64>,
    pub effective_at: Option<Moment>,
    action: &'static str,
    before: Value,
    after: Value,
    reason: Option<String>,
}

fn resource(
    action: &'static str,
    id: String,
    version: i64,
    before: Value,
    after: Value,
) -> Applied {
    Applied {
        id: Some(id),
        version: Some(version),
        sequence: None,
        effective_at: None,
        action,
        before,
        after,
        reason: None,
    }
}

fn entry(action: &'static str, row: &Activity, before: Value) -> Applied {
    let mut applied = resource(action, row.id.clone(), row.version, before, json!(row));
    applied.sequence = Some(row.sequence);
    applied.effective_at = Some(row.effective_at);
    applied
}

fn increment(value: i64) -> Result<i64, Failure> {
    value.checked_add(1).ok_or(Failure::Internal)
}

fn id() -> Result<String, Failure> {
    crypto::id().map_err(|_| Failure::Internal)
}

fn text(value: &str, limit: usize) -> Result<&str, Failure> {
    let trimmed = value.trim();
    if trimmed.is_empty() || trimmed.chars().count() > limit || trimmed.contains('\0') {
        return Err(Code::ValidationError.into());
    }
    Ok(trimmed)
}

fn optional_text(value: Option<&str>, limit: usize) -> Result<Option<String>, Failure> {
    value
        .filter(|value| !value.trim().is_empty())
        .map(|value| text(value, limit).map(str::to_owned))
        .transpose()
}

fn new_row(state: &mut Account, kind: Kind, at: Moment) -> Result<Activity, Failure> {
    let sequence = state.next_sequence;
    state.next_sequence = increment(sequence)?;
    Ok(Activity {
        id: id()?,
        effective_at: at,
        sequence,
        kind,
        amount: None,
        target_balance: None,
        snapshot_delta: None,
        borrower_id: None,
        category_id: None,
        title: None,
        description: None,
        affect_cash_balance: None,
        depends_on: vec![],
        deleted: false,
        version: 1,
    })
}

async fn activity_values(
    tx: &mut Transaction<'_, MySql>,
    owner: &str,
    row: &mut Activity,
    input: &ActivityInput,
    now: Moment,
) -> Result<(), Failure> {
    if input.kind.snapshot() || input.depends_on.len() > 20 {
        return Err(Code::ValidationError.into());
    }
    if input.amount.0 <= 0 {
        return Err(Code::InvalidAmount.into());
    }
    if input.effective_at > now {
        return Err(Code::InvalidFutureEffectiveTime.into());
    }
    let borrower = input.borrower_id.map(|id| id.to_string());
    let category = input.category_id.map(|id| id.to_string());
    if input.kind.receivable() != borrower.is_some()
        || (!input.kind.receivable() && input.affect_cash_balance.is_some())
    {
        return Err(Code::ValidationError.into());
    }
    if let Some(borrower) = &borrower {
        let reference = store::borrower(tx, owner, borrower).await?;
        if reference.archived && Some(borrower) != row.borrower_id.as_ref() {
            return Err(Code::BorrowerArchived.into());
        }
    }
    if let Some(category) = &category {
        let reference = store::category(tx, owner, category).await?;
        if reference.archived && Some(category) != row.category_id.as_ref() {
            return Err(Code::CategoryArchived.into());
        }
    }
    row.borrower_id = borrower;
    row.kind = input.kind;
    row.category_id = category;
    row.title = optional_text(input.title.as_deref(), 180)?;
    row.description = optional_text(input.description.as_deref(), 2000)?;
    row.affect_cash_balance = input.affect_cash_balance;
    row.depends_on = input.depends_on.iter().map(ToString::to_string).collect();
    row.effective_at = input.effective_at;
    row.amount = Some(input.amount);
    Ok(())
}

async fn snapshot(
    tx: &mut Transaction<'_, MySql>,
    owner: &str,
    state: &mut Account,
    kind: Kind,
    target: Money,
    at: Moment,
) -> Result<Applied, Failure> {
    let mut row = new_row(state, kind, at)?;
    row.target_balance = Some(target);
    store::insert(tx, owner, &row).await?;
    let action = if kind == Kind::Opening {
        "OPENING_BALANCE"
    } else {
        "BALANCE_ADJUSTMENT"
    };
    Ok(entry(action, &row, Value::Null))
}

async fn activity_mutation(
    tx: &mut Transaction<'_, MySql>,
    owner: &str,
    at: Moment,
    state: &mut Account,
    operation: &Mutation,
) -> Result<Applied, Failure> {
    match operation {
        Mutation::Opening { target } => {
            if state.opening != "pending" {
                return Err(Code::OpeningAlreadyDecided.into());
            }
            if let Some(target) = target {
                state.opening = "recorded".into();
                return snapshot(tx, owner, state, Kind::Opening, *target, at).await;
            }
            state.opening = "skipped".into();
            Ok(Applied {
                id: None,
                version: None,
                sequence: None,
                effective_at: None,
                action: "OPENING_SKIPPED",
                before: json!("pending"),
                after: json!("skipped"),
                reason: None,
            })
        }
        Mutation::Adjustment { target } => {
            snapshot(tx, owner, state, Kind::Adjustment, *target, at).await
        }
        Mutation::Create(input) => {
            let mut row = new_row(state, input.kind, at)?;
            activity_values(tx, owner, &mut row, input, at).await?;
            store::insert(tx, owner, &row).await?;
            Ok(entry("ACTIVITY_CREATED", &row, Value::Null))
        }
        Mutation::Edit { id, version, .. }
        | Mutation::Delete { id, version, .. }
        | Mutation::Restore { id, version } => {
            let mut row = store::one(tx, owner, &id.to_string()).await?;
            Rejection::version(&row.id, *version, row.version)?;
            if row.kind.snapshot() {
                return Err(Code::InvalidActivityState.into());
            }
            let before = json!(&row);
            let action;
            let mut reason = None;
            match operation {
                Mutation::Edit { input, .. } if !row.deleted => {
                    activity_values(tx, owner, &mut row, input, at).await?;
                    action = "ACTIVITY_EDITED";
                }
                Mutation::Delete { reason: why, .. } if !row.deleted => {
                    reason = optional_text(why.as_deref(), 500)?;
                    row.deleted = true;
                    action = "ACTIVITY_DELETED";
                }
                Mutation::Restore { .. } if row.deleted => {
                    row.deleted = false;
                    action = "ACTIVITY_RESTORED";
                }
                _ => return Err(Code::InvalidActivityState.into()),
            }
            row.version = increment(row.version)?;
            store::update(tx, owner, &row).await?;
            let mut applied = entry(action, &row, before);
            applied.reason = reason;
            Ok(applied)
        }
        _ => Err(Failure::Internal),
    }
}

async fn borrower_mutation(
    tx: &mut Transaction<'_, MySql>,
    owner: &str,
    operation: &Mutation,
) -> Result<Applied, Failure> {
    let (mut borrower, before, action, changes) = match operation {
        Mutation::AddBorrower(input) => (
            store::Borrower {
                id: id()?,
                name: String::new(),
                phone: None,
                notes: None,
                outstanding: 0,
                archived: false,
                version: 1,
            },
            Value::Null,
            "BORROWER_CREATED",
            Some(input),
        ),
        Mutation::EditBorrower { id, version, input } => {
            let mut row = store::borrower(tx, owner, &id.to_string()).await?;
            Rejection::version(&row.id, *version, row.version)?;
            let before = row.view();
            row.version = increment(row.version)?;
            (row, before, "BORROWER_EDITED", Some(input))
        }
        Mutation::ArchiveBorrower {
            id,
            version,
            archive,
        } => {
            let mut row = store::borrower(tx, owner, &id.to_string()).await?;
            Rejection::version(&row.id, *version, row.version)?;
            if *archive && row.outstanding != 0 {
                return Err(Code::BorrowerOutstanding.into());
            }
            let before = row.view();
            row.archived = *archive;
            row.version = increment(row.version)?;
            (
                row,
                before,
                if *archive {
                    "BORROWER_ARCHIVED"
                } else {
                    "BORROWER_REACTIVATED"
                },
                None,
            )
        }
        _ => return Err(Failure::Internal),
    };
    if let Some(input) = changes {
        borrower.name = text(&input.name, 100)?.to_owned();
        borrower.phone = optional_text(input.phone.as_deref(), 40)?;
        borrower.notes = optional_text(input.notes.as_deref(), 1000)?;
    }
    if before.is_null() {
        sqlx::query("INSERT INTO borrowers (owner_id,id,name,phone,notes) VALUES (?,?,?,?,?)")
            .bind(owner)
            .bind(&borrower.id)
            .bind(&borrower.name)
            .bind(&borrower.phone)
            .bind(&borrower.notes)
            .execute(&mut **tx)
            .await?;
    } else {
        sqlx::query("UPDATE borrowers SET name=?,phone=?,notes=?,archived=?,version=? WHERE owner_id=? AND id=?")
            .bind(&borrower.name).bind(&borrower.phone).bind(&borrower.notes).bind(borrower.archived)
            .bind(borrower.version).bind(owner).bind(&borrower.id).execute(&mut **tx).await?;
    }
    Ok(resource(
        action,
        borrower.id.clone(),
        borrower.version,
        before,
        borrower.view(),
    ))
}

async fn category_mutation(
    tx: &mut Transaction<'_, MySql>,
    owner: &str,
    operation: &Mutation,
) -> Result<Applied, Failure> {
    let (row, before, action) = match operation {
        Mutation::AddCategory { name } => (
            store::Category {
                id: id()?,
                name: text(name, 100)?.to_owned(),
                archived: false,
                version: 1,
            },
            Value::Null,
            "CATEGORY_CREATED",
        ),
        Mutation::RenameCategory { id, version, name } => {
            let mut row = store::category(tx, owner, &id.to_string()).await?;
            Rejection::version(&row.id, *version, row.version)?;
            let before = json!(&row);
            row.version = increment(row.version)?;
            row.name = text(name, 100)?.to_owned();
            (row, before, "CATEGORY_RENAMED")
        }
        Mutation::ArchiveCategory {
            id,
            version,
            archive,
        } => {
            let mut row = store::category(tx, owner, &id.to_string()).await?;
            Rejection::version(&row.id, *version, row.version)?;
            let before = json!(&row);
            row.version = increment(row.version)?;
            row.archived = *archive;
            (
                row,
                before,
                if *archive {
                    "CATEGORY_ARCHIVED"
                } else {
                    "CATEGORY_RESTORED"
                },
            )
        }
        _ => return Err(Failure::Internal),
    };
    if before.is_null() {
        sqlx::query("INSERT INTO categories (owner_id,id,name) VALUES (?,?,?)")
            .bind(owner)
            .bind(&row.id)
            .bind(&row.name)
            .execute(&mut **tx)
            .await?;
    } else {
        sqlx::query("UPDATE categories SET name=?,archived=?,version=? WHERE owner_id=? AND id=?")
            .bind(&row.name)
            .bind(row.archived)
            .bind(row.version)
            .bind(owner)
            .bind(&row.id)
            .execute(&mut **tx)
            .await?;
    }
    Ok(resource(
        action,
        row.id.clone(),
        row.version,
        before,
        json!(row),
    ))
}

async fn save_borrower_projections(
    tx: &mut Transaction<'_, MySql>,
    owner: &str,
    projection: &Projection,
) -> Result<Vec<Value>, Failure> {
    let mut changes = vec![];
    for mut row in store::borrowers(tx, owner).await? {
        let outstanding = projection.receivables.get(&row.id).copied().unwrap_or(0);
        if row.outstanding == outstanding && (!row.archived || outstanding == 0) {
            continue;
        }
        let before = row.view();
        let reactivated = row.archived && outstanding > 0;
        if reactivated {
            row.archived = false;
            row.version = increment(row.version)?;
        }
        row.outstanding = outstanding;
        sqlx::query(
            "UPDATE borrowers SET outstanding=?,archived=?,version=? WHERE owner_id=? AND id=?",
        )
        .bind(row.outstanding)
        .bind(row.archived)
        .bind(row.version)
        .bind(owner)
        .bind(&row.id)
        .execute(&mut **tx)
        .await?;
        changes.push(json!({ "before": before, "after": row.view(), "automaticallyReactivated": reactivated }));
    }
    Ok(changes)
}

pub async fn apply_and_project(
    tx: &mut Transaction<'_, MySql>,
    owner: &str,
    attempt: &str,
    at: Moment,
    state: &mut Account,
    operation: &Mutation,
) -> Result<Applied, Failure> {
    let state_before = json!({
        "balance": Money(state.balance), "receivables": Money(state.receivables),
        "financialStateVersion": state.version, "opening": state.opening
    });
    let mut applied = match operation {
        Mutation::AddBorrower(_)
        | Mutation::EditBorrower { .. }
        | Mutation::ArchiveBorrower { .. } => borrower_mutation(tx, owner, operation).await?,
        Mutation::AddCategory { .. }
        | Mutation::RenameCategory { .. }
        | Mutation::ArchiveCategory { .. } => category_mutation(tx, owner, operation).await?,
        Mutation::Opening { .. } => activity_mutation(tx, owner, at, state, operation).await?,
        _ if state.opening == "pending" => return Err(Code::OpeningRequired.into()),
        _ => activity_mutation(tx, owner, at, state, operation).await?,
    };
    let mut ledger = store::ledger(tx, owner).await?;
    let projected = replay(&mut ledger)?;
    let mut snapshots = vec![];
    for row in &mut ledger {
        let delta = projected.snapshot_deltas.get(&row.id).copied().map(Money);
        if row.snapshot_delta != delta {
            snapshots.push(json!({ "id": row.id, "targetBalance": row.target_balance,
                "beforeDelta": row.snapshot_delta, "afterDelta": delta }));
            sqlx::query("UPDATE activities SET snapshot_delta=? WHERE owner_id=? AND id=?")
                .bind(delta.map(|delta| delta.0))
                .bind(owner)
                .bind(&row.id)
                .execute(&mut **tx)
                .await?;
            row.snapshot_delta = delta;
        }
        if applied.sequence.is_some() && applied.id.as_ref() == Some(&row.id) {
            applied.after = changed(serde_json::to_value(row))?;
        }
    }
    let borrower_changes = save_borrower_projections(tx, owner, &projected).await?;
    state.version = increment(state.version)?;
    state.balance = projected.balance;
    state.receivables = projected.receivables_total;
    sqlx::query("UPDATE financial_accounts SET balance=?,receivables=?,next_sequence=?,version=?,opening=?,updated_at=?
        WHERE owner_id=?")
        .bind(state.balance).bind(state.receivables).bind(state.next_sequence).bind(state.version)
        .bind(&state.opening).bind(at.0).bind(owner).execute(&mut **tx).await?;
    store::audit(tx, owner, owner, applied.action, at, Some(attempt), json!({
        "resourceId": applied.id, "reason": applied.reason, "before": applied.before, "after": applied.after,
        "snapshotChanges": snapshots, "borrowerChanges": borrower_changes, "stateBefore": state_before,
        "stateAfter": { "balance": Money(state.balance), "receivables": Money(state.receivables),
            "financialStateVersion": state.version, "opening": state.opening },
    })).await?;
    Ok(applied)
}
