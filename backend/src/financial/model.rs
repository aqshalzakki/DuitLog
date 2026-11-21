use std::collections::{BTreeMap, HashSet};

use serde::{Deserialize, Deserializer, Serialize, Serializer, de::Error as _};
use serde_json::{Value, json};
use time::{OffsetDateTime, format_description::well_known::Rfc3339};
use uuid::Uuid;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Money(pub i64);

impl Serialize for Money {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(&self.0.to_string())
    }
}

impl<'de> Deserialize<'de> for Money {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let input = String::deserialize(deserializer)?;
        let value: i64 = input
            .parse()
            .map_err(|_| D::Error::custom("invalid IDR integer"))?;
        if input != value.to_string() {
            return Err(D::Error::custom("non-canonical IDR integer"));
        }
        Ok(Self(value))
    }
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct Moment(pub i64);

impl Moment {
    pub fn now() -> Self {
        let current = OffsetDateTime::now_utc();
        Self(current.unix_timestamp() * 1_000_000 + i64::from(current.microsecond()))
    }
}

impl Serialize for Moment {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let date = OffsetDateTime::from_unix_timestamp_nanos(i128::from(self.0) * 1000)
            .map_err(serde::ser::Error::custom)?;
        serializer.serialize_str(&date.format(&Rfc3339).map_err(serde::ser::Error::custom)?)
    }
}

impl<'de> Deserialize<'de> for Moment {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let value = String::deserialize(deserializer)?;
        let date = OffsetDateTime::parse(&value, &Rfc3339).map_err(D::Error::custom)?;
        if date.nanosecond() % 1000 != 0 {
            return Err(D::Error::custom(
                "effectiveAt exceeds microsecond precision",
            ));
        }
        Ok(Self(
            date.unix_timestamp() * 1_000_000 + i64::from(date.microsecond()),
        ))
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
#[repr(i8)]
pub enum Kind {
    Increase = 1,
    Deduct,
    Loan,
    Repayment,
    Opening,
    Adjustment,
}

impl Kind {
    pub fn from_db(value: i8) -> Option<Self> {
        Some(match value {
            1 => Self::Increase,
            2 => Self::Deduct,
            3 => Self::Loan,
            4 => Self::Repayment,
            5 => Self::Opening,
            6 => Self::Adjustment,
            _ => return None,
        })
    }

    pub fn snapshot(self) -> bool {
        matches!(self, Self::Opening | Self::Adjustment)
    }

    pub fn receivable(self) -> bool {
        matches!(self, Self::Loan | Self::Repayment)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Activity {
    pub id: String,
    pub effective_at: Moment,
    pub sequence: i64,
    pub kind: Kind,
    pub amount: Option<Money>,
    pub target_balance: Option<Money>,
    pub snapshot_delta: Option<Money>,
    pub borrower_id: Option<String>,
    pub category_id: Option<String>,
    pub title: Option<String>,
    pub description: Option<String>,
    pub affect_cash_balance: Option<bool>,
    pub depends_on: Vec<String>,
    pub deleted: bool,
    pub version: i64,
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ActivityInput {
    pub kind: Kind,
    pub amount: Money,
    pub effective_at: Moment,
    pub borrower_id: Option<Uuid>,
    pub category_id: Option<Uuid>,
    pub title: Option<String>,
    pub description: Option<String>,
    pub affect_cash_balance: Option<bool>,
    #[serde(default)]
    pub depends_on: Vec<Uuid>,
}

impl ActivityInput {
    pub fn normalize(&mut self) {
        if self.kind.receivable() {
            self.affect_cash_balance.get_or_insert(true);
        }
        self.depends_on.sort_unstable();
        self.depends_on.dedup();
    }
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BorrowerInput {
    pub name: String,
    pub phone: Option<String>,
    pub notes: Option<String>,
}

#[derive(Debug, Default)]
pub struct Projection {
    pub balance: i64,
    pub receivables: BTreeMap<String, i64>,
    pub snapshot_deltas: BTreeMap<String, i64>,
    pub receivables_total: i64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Code {
    AmountOverflow,
    InvalidAmount,
    InvalidFutureEffectiveTime,
    ValidationError,
    NotFound,
    VersionConflict,
    CategoryArchived,
    BorrowerArchived,
    BorrowerOutstanding,
    ReceivableNegative,
    DependencyBlocked,
    IdempotencyPayloadMismatch,
    AlreadyConfirmedActivity,
    OpeningAlreadyDecided,
    OpeningRequired,
    InvalidActivityState,
    FinancialIntegrityFrozen,
    FinancialRecoveryActive,
    TemporaryFailure,
    OutcomeUnknown,
    SessionOwnerMismatch,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Rejection {
    pub code: Code,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub conflict_details: Option<Value>,
}

impl From<Code> for Rejection {
    fn from(code: Code) -> Self {
        Self {
            code,
            conflict_details: None,
        }
    }
}

impl Rejection {
    pub fn version(id: &str, expected: i64, actual: i64) -> Result<(), Self> {
        if expected <= 0 || expected != actual {
            return Err(Self {
                code: Code::VersionConflict,
                conflict_details: Some(json!({ "resourceId": id, "currentVersion": actual })),
            });
        }
        Ok(())
    }
}

pub fn replay(rows: &mut [Activity]) -> Result<Projection, Rejection> {
    rows.sort_unstable_by_key(|row| (row.effective_at, row.sequence));
    let mut projection = Projection::default();
    let mut active_predecessors = HashSet::with_capacity(rows.len());
    for activity in rows.iter().filter(|row| !row.deleted) {
        if !activity
            .depends_on
            .iter()
            .all(|dependency| active_predecessors.contains(dependency.as_str()))
        {
            return Err(Code::DependencyBlocked.into());
        }
        active_predecessors.insert(activity.id.as_str());
        if activity.kind.snapshot() {
            let target = activity.target_balance.ok_or(Code::ValidationError)?.0;
            let delta = target
                .checked_sub(projection.balance)
                .ok_or(Code::AmountOverflow)?;
            projection
                .snapshot_deltas
                .insert(activity.id.clone(), delta);
            projection.balance = target;
            continue;
        }
        let amount = activity
            .amount
            .filter(|value| value.0 > 0)
            .ok_or(Code::InvalidAmount)?
            .0;
        let cash = match activity.kind {
            Kind::Increase | Kind::Repayment => amount,
            Kind::Deduct | Kind::Loan => -amount,
            _ => return Err(Code::ValidationError.into()),
        };
        if activity.kind.receivable() {
            let borrower = activity.borrower_id.as_ref().ok_or(Code::ValidationError)?;
            let outstanding = projection.receivables.entry(borrower.clone()).or_default();
            *outstanding = outstanding.checked_sub(cash).ok_or(Code::AmountOverflow)?;
            if *outstanding < 0 {
                return Err(Rejection {
                    code: Code::ReceivableNegative,
                    conflict_details: Some(
                        json!({ "borrowerId": borrower, "effectiveAt": activity.effective_at }),
                    ),
                });
            }
        }
        if activity.affect_cash_balance != Some(false) {
            projection.balance = projection
                .balance
                .checked_add(cash)
                .ok_or(Code::AmountOverflow)?;
        }
    }
    for amount in projection.receivables.values() {
        projection.receivables_total = projection
            .receivables_total
            .checked_add(*amount)
            .ok_or(Code::AmountOverflow)?;
    }
    Ok(projection)
}
