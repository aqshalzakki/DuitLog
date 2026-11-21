use serde::Serialize;
use serde_json::Value;
use sqlx::{FromRow, MySql, MySqlConnection, Transaction, types::Json};

use super::{Failure, model::*};

#[derive(FromRow)]
pub struct Account {
    pub balance: i64,
    pub receivables: i64,
    pub next_sequence: i64,
    pub version: i64,
    pub opening: String,
    pub frozen: bool,
    pub updated_at: Option<i64>,
}

impl Default for Account {
    fn default() -> Self {
        Self {
            balance: 0,
            receivables: 0,
            next_sequence: 1,
            version: 0,
            opening: "pending".into(),
            frozen: false,
            updated_at: None,
        }
    }
}

pub async fn anchor(tx: &mut Transaction<'_, MySql>, owner: &str) -> Result<Account, Failure> {
    sqlx::query("INSERT INTO financial_accounts (owner_id) VALUES (?) ON DUPLICATE KEY UPDATE owner_id=owner_id")
        .bind(owner).execute(&mut **tx).await?;
    Ok(sqlx::query_as(
        "SELECT balance,receivables,next_sequence,version,opening,frozen,updated_at
        FROM financial_accounts WHERE owner_id=? FOR UPDATE",
    )
    .bind(owner)
    .fetch_one(&mut **tx)
    .await?)
}

pub async fn read_account(conn: &mut MySqlConnection, owner: &str) -> Result<Account, Failure> {
    Ok(sqlx::query_as(
        "SELECT balance,receivables,next_sequence,version,opening,frozen,updated_at
        FROM financial_accounts WHERE owner_id=?",
    )
    .bind(owner)
    .fetch_optional(conn)
    .await?
    .unwrap_or_default())
}

#[derive(FromRow)]
pub struct Entry {
    pub id: String,
    pub sequence: i64,
    pub effective_at: i64,
    pub kind: i8,
    pub amount: Option<i64>,
    pub target_balance: Option<i64>,
    pub snapshot_delta: Option<i64>,
    pub borrower_id: Option<String>,
    pub category_id: Option<String>,
    pub title: Option<String>,
    pub description: Option<String>,
    pub affect_cash_balance: Option<bool>,
    pub depends_on: Json<Vec<String>>,
    pub deleted: bool,
    pub version: i64,
}

impl Entry {
    pub fn into_activity(self) -> Result<Activity, Failure> {
        Ok(Activity {
            id: self.id,
            sequence: self.sequence,
            effective_at: Moment(self.effective_at),
            kind: Kind::from_db(self.kind).ok_or(Failure::Internal)?,
            amount: self.amount.map(Money),
            target_balance: self.target_balance.map(Money),
            snapshot_delta: self.snapshot_delta.map(Money),
            borrower_id: self.borrower_id,
            category_id: self.category_id,
            title: self.title,
            description: self.description,
            affect_cash_balance: self.affect_cash_balance,
            depends_on: self.depends_on.0,
            deleted: self.deleted,
            version: self.version,
        })
    }
}

// These projections all use the same owned row and JSON conversion.
macro_rules! entries {
    ($tail:literal) => {
        concat!("SELECT id,sequence,effective_at,kind,amount,target_balance,snapshot_delta,borrower_id,
            category_id,title,description,affect_cash_balance,depends_on,deleted,version FROM activities ", $tail)
    };
}

pub async fn ledger(
    tx: &mut Transaction<'_, MySql>,
    owner: &str,
) -> Result<Vec<Activity>, Failure> {
    let rows: Vec<Entry> =
        sqlx::query_as(entries!("WHERE owner_id=? ORDER BY effective_at,sequence"))
            .bind(owner)
            .fetch_all(&mut **tx)
            .await?;
    rows.into_iter().map(Entry::into_activity).collect()
}

pub async fn one(conn: &mut MySqlConnection, owner: &str, id: &str) -> Result<Activity, Failure> {
    let row: Entry = sqlx::query_as(entries!("WHERE owner_id=? AND id=?"))
        .bind(owner)
        .bind(id)
        .fetch_optional(conn)
        .await?
        .ok_or(Code::NotFound)?;
    row.into_activity()
}

pub async fn history(
    conn: &mut MySqlConnection,
    owner: &str,
    deleted: bool,
    before: Option<i64>,
    borrower: Option<&str>,
) -> Result<Vec<Activity>, Failure> {
    let rows: Vec<Entry> = if let Some(sequence) = before {
        let instant: i64 = sqlx::query_scalar(
            "SELECT effective_at FROM activities WHERE owner_id=? AND sequence=?",
        )
        .bind(owner)
        .bind(sequence)
        .fetch_optional(&mut *conn)
        .await?
        .ok_or(Code::NotFound)?;
        sqlx::query_as(entries!(
            "WHERE owner_id=? AND deleted=? AND (? IS NULL OR borrower_id=?)
            AND (effective_at<? OR (effective_at=? AND sequence<?)) ORDER BY effective_at DESC,sequence DESC LIMIT 51"
        ))
        .bind(owner)
        .bind(deleted)
        .bind(borrower)
        .bind(borrower)
        .bind(instant)
        .bind(instant)
        .bind(sequence)
        .fetch_all(conn)
        .await?
    } else {
        sqlx::query_as(entries!(
            "WHERE owner_id=? AND deleted=? AND (? IS NULL OR borrower_id=?)
            ORDER BY effective_at DESC,sequence DESC LIMIT 51"
        ))
        .bind(owner)
        .bind(deleted)
        .bind(borrower)
        .bind(borrower)
        .fetch_all(conn)
        .await?
    };
    rows.into_iter().map(Entry::into_activity).collect()
}

pub async fn insert(
    tx: &mut Transaction<'_, MySql>,
    owner: &str,
    row: &Activity,
) -> Result<(), Failure> {
    sqlx::query(
        "INSERT INTO activities (owner_id,id,sequence,effective_at,kind,amount,target_balance,
        snapshot_delta,borrower_id,category_id,title,description,affect_cash_balance,depends_on)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
    )
    .bind(owner)
    .bind(&row.id)
    .bind(row.sequence)
    .bind(row.effective_at.0)
    .bind(row.kind as i8)
    .bind(row.amount.map(|amount| amount.0))
    .bind(row.target_balance.map(|target| target.0))
    .bind(row.snapshot_delta.map(|delta| delta.0))
    .bind(&row.borrower_id)
    .bind(&row.category_id)
    .bind(&row.title)
    .bind(&row.description)
    .bind(row.affect_cash_balance)
    .bind(Json(&row.depends_on))
    .execute(&mut **tx)
    .await?;
    Ok(())
}

pub async fn update(
    tx: &mut Transaction<'_, MySql>,
    owner: &str,
    row: &Activity,
) -> Result<(), Failure> {
    sqlx::query("UPDATE activities SET effective_at=?,kind=?,amount=?,borrower_id=?,category_id=?,
        title=?,description=?,affect_cash_balance=?,depends_on=?,deleted=?,version=? WHERE owner_id=? AND id=?")
        .bind(row.effective_at.0).bind(row.kind as i8).bind(row.amount.map(|amount| amount.0)).bind(&row.borrower_id)
        .bind(&row.category_id).bind(&row.title).bind(&row.description).bind(row.affect_cash_balance)
        .bind(Json(&row.depends_on)).bind(row.deleted).bind(row.version).bind(owner).bind(&row.id)
        .execute(&mut **tx).await?;
    Ok(())
}

#[derive(Clone, FromRow)]
pub struct Borrower {
    pub id: String,
    pub name: String,
    pub phone: Option<String>,
    pub notes: Option<String>,
    pub outstanding: i64,
    pub archived: bool,
    pub version: i64,
}

impl Borrower {
    pub fn view(&self) -> Value {
        serde_json::json!({
            "id": self.id, "name": self.name, "phone": self.phone, "notes": self.notes,
            "outstanding": Money(self.outstanding), "archived": self.archived, "version": self.version,
            "status": if self.outstanding == 0 { "PAID" } else { "UNPAID" },
        })
    }
}

pub async fn borrowers(conn: &mut MySqlConnection, owner: &str) -> Result<Vec<Borrower>, Failure> {
    Ok(sqlx::query_as(
        "SELECT id,name,phone,notes,outstanding,archived,version
        FROM borrowers WHERE owner_id=? ORDER BY id",
    )
    .bind(owner)
    .fetch_all(conn)
    .await?)
}

pub async fn borrower(
    conn: &mut MySqlConnection,
    owner: &str,
    id: &str,
) -> Result<Borrower, Failure> {
    Ok(sqlx::query_as(
        "SELECT id,name,phone,notes,outstanding,archived,version
        FROM borrowers WHERE owner_id=? AND id=?",
    )
    .bind(owner)
    .bind(id)
    .fetch_optional(conn)
    .await?
    .ok_or(Code::NotFound)?)
}

#[derive(Clone, FromRow, Serialize)]
pub struct Category {
    pub id: String,
    pub name: String,
    pub archived: bool,
    pub version: i64,
}

pub async fn category(
    conn: &mut MySqlConnection,
    owner: &str,
    id: &str,
) -> Result<Category, Failure> {
    Ok(
        sqlx::query_as("SELECT id,name,archived,version FROM categories WHERE owner_id=? AND id=?")
            .bind(owner)
            .bind(id)
            .fetch_optional(conn)
            .await?
            .ok_or(Code::NotFound)?,
    )
}

pub async fn categories(conn: &mut MySqlConnection, owner: &str) -> Result<Vec<Category>, Failure> {
    Ok(sqlx::query_as(
        "SELECT id,name,archived,version FROM categories WHERE owner_id=? ORDER BY name,id",
    )
    .bind(owner)
    .fetch_all(conn)
    .await?)
}

pub async fn audit(
    tx: &mut Transaction<'_, MySql>,
    owner: &str,
    actor: &str,
    action: &str,
    at: Moment,
    attempt: Option<&str>,
    details: Value,
) -> Result<(), Failure> {
    sqlx::query(
        "INSERT INTO financial_audit (owner_id,actor,action,action_at,attempt_id,details)
        VALUES (?,?,?,?,?,?)",
    )
    .bind(owner)
    .bind(actor)
    .bind(action)
    .bind(at.0)
    .bind(attempt)
    .bind(Json(details))
    .execute(&mut **tx)
    .await?;
    Ok(())
}
