//! Online reports from the confirmed ledger (Tech Spec §11). Read-only: opening and closing figures
//! come from `model::replay` on a ledger prefix, and in-range movements use the same signed-cash rule,
//! so a report can never disagree with the Financial Core about a balance.

use std::collections::BTreeMap;

use jiff::{Timestamp, ToSpan, civil::Date, tz::TimeZone};
use serde_json::{Value, json};

use super::{
    Failure,
    model::{Activity, Code, Kind, Moment, replay},
    store,
};

/// BRD default for a new account.
pub const DEFAULT_ZONE: &str = "Asia/Jakarta";
/// Custom ranges longer than this are refused; daily buckets up to `DAILY_BUCKETS`, monthly beyond.
const MAX_DAYS: i64 = 366 * 5;
const DAILY_BUCKETS: i64 = 92;
const MICROS: i64 = 1_000_000;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Period {
    Day,
    Week,
    Month,
    Year,
    Custom,
}

impl Period {
    pub fn parse(value: &str) -> Option<Self> {
        Some(match value {
            "day" => Self::Day,
            "week" => Self::Week,
            "month" => Self::Month,
            "year" => Self::Year,
            "custom" => Self::Custom,
            _ => return None,
        })
    }

    fn name(self) -> &'static str {
        match self {
            Self::Day => "day",
            Self::Week => "week",
            Self::Month => "month",
            Self::Year => "year",
            Self::Custom => "custom",
        }
    }
}

/// `[start, end)` in microseconds since the epoch.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Window {
    pub start: i64,
    pub end: i64,
}

#[derive(Clone, Debug)]
pub struct Ranges {
    pub period: Period,
    pub current: Window,
    pub previous: Window,
    /// The period has not finished: `current` stops at now and `previous` at the same elapsed point.
    pub running: bool,
    monthly: bool,
    zone: TimeZone,
    zone_name: String,
}

fn invalid<E>(_: E) -> Failure {
    Code::ValidationError.into()
}

/// An IANA zone from the bundled tzdb; `None` for anything else.
pub fn zone(name: &str) -> Option<TimeZone> {
    if name.is_empty() || name.len() > 64 {
        return None;
    }
    TimeZone::get(name).ok()
}

/// First instant of a local day. Where midnight does not exist (a DST gap) this is the first
/// instant after the gap.
fn midnight(date: Date, zone: &TimeZone) -> Result<i64, Failure> {
    Ok(date
        .to_zoned_datetime(zone.clone())
        .map_err(invalid)?
        .timestamp()
        .as_microsecond())
}

fn local_date(micros: i64, zone: &TimeZone) -> Result<Date, Failure> {
    Ok(Timestamp::from_microsecond(micros)
        .map_err(invalid)?
        .to_zoned_datetime(zone.clone())
        .date())
}

/// The local date in `zone` at `micros`; the default for a period with no date given.
pub fn today(micros: i64, zone: &TimeZone) -> Result<Date, Failure> {
    local_date(micros, zone)
}

pub fn parse_date(value: &str) -> Option<Date> {
    let mut parts = value.split('-');
    let (year, month, day) = (parts.next()?, parts.next()?, parts.next()?);
    if parts.next().is_some() || year.len() != 4 || month.len() != 2 || day.len() != 2 {
        return None;
    }
    Date::new(year.parse().ok()?, month.parse().ok()?, day.parse().ok()?).ok()
}

fn label(date: Date) -> String {
    format!("{:04}-{:02}-{:02}", date.year(), date.month(), date.day())
}

fn add_days(date: Date, days: i64) -> Result<Date, Failure> {
    date.checked_add(days.days()).map_err(invalid)
}

fn month_start(date: Date, months_back: i64) -> Result<Date, Failure> {
    date.first_of_month()
        .checked_add((-months_back).months())
        .map_err(invalid)
}

fn year_start(year: i16) -> Result<Date, Failure> {
    Date::new(year, 1, 1).map_err(invalid)
}

/// Current and comparison windows in the account zone. A running period is compared with the same
/// elapsed time from the start of the previous one (clamped to its end, e.g. 31 March vs February); a
/// finished period with the whole previous one. Custom compares with the equally long range before it.
pub fn ranges(
    period: Period,
    from: Date,
    to: Option<Date>,
    now: i64,
    zone_name: &str,
) -> Result<Ranges, Failure> {
    let zone = self::zone(zone_name).ok_or(Code::ValidationError)?;
    let (start, next, previous) = match period {
        Period::Day => (from, add_days(from, 1)?, add_days(from, -1)?),
        Period::Week => {
            let monday = add_days(from, -i64::from(from.weekday().to_monday_zero_offset()))?;
            (monday, add_days(monday, 7)?, add_days(monday, -7)?)
        }
        Period::Month => (
            month_start(from, 0)?,
            month_start(from, -1)?,
            month_start(from, 1)?,
        ),
        Period::Year => {
            let year = from.year();
            let next = year.checked_add(1).ok_or(Code::ValidationError)?;
            (year_start(year)?, year_start(next)?, year_start(year - 1)?)
        }
        Period::Custom => {
            let to = to.ok_or(Code::ValidationError)?;
            let days = i64::from(from.until(to).map_err(invalid)?.get_days()) + 1;
            if !(1..=MAX_DAYS).contains(&days) {
                return Err(Code::ValidationError.into());
            }
            (from, add_days(to, 1)?, add_days(from, -days)?)
        }
    };
    let start = midnight(start, &zone)?;
    let end = midnight(next, &zone)?;
    let previous_start = midnight(previous, &zone)?;
    if start > now {
        return Err(Code::ValidationError.into()); // nothing confirmed can lie in the future
    }
    let running = now < end;
    let (current_end, previous_end) = if running {
        (now, previous_start.saturating_add(now - start).min(start))
    } else {
        (end, start)
    };
    Ok(Ranges {
        period,
        current: Window {
            start,
            end: current_end,
        },
        previous: Window {
            start: previous_start,
            end: previous_end,
        },
        running,
        monthly: period == Period::Year || (end - start) / (86_400 * MICROS) > DAILY_BUCKETS,
        zone,
        zone_name: zone_name.to_owned(),
    })
}

/// First instant of local day `from` and first instant after local day `to`, either side optional;
/// refused when reversed. History has no length cap: it is paginated.
pub fn days(
    from: Option<Date>,
    to: Option<Date>,
    zone: &TimeZone,
) -> Result<(Option<i64>, Option<i64>), Failure> {
    if let (Some(from), Some(to)) = (from, to)
        && from > to
    {
        return Err(Code::ValidationError.into());
    }
    let start = from.map(|d| midnight(d, zone)).transpose()?;
    let end = to
        .map(|d| add_days(d, 1).and_then(|next| midnight(next, zone)))
        .transpose()?;
    Ok((start, end))
}

fn describe(window: Window, zone: &TimeZone) -> Result<Value, Failure> {
    // The last included day is the one holding the final microsecond of the window.
    let last = if window.end > window.start {
        window.end - 1
    } else {
        window.start
    };
    Ok(json!({
        "from": label(local_date(window.start, zone)?), "to": label(local_date(last, zone)?),
        "start": Moment(window.start), "end": Moment(window.end),
    }))
}

/// Day or month buckets covering the current window, each `[start, end)` clipped to it. A local day
/// may be 23 or 25 hours long across a DST change.
fn buckets(ranges: &Ranges) -> Result<Vec<(String, Window)>, Failure> {
    let Window { start, end } = ranges.current;
    let zone = &ranges.zone;
    let mut list = Vec::new();
    let mut day = local_date(start, zone)?;
    while midnight(day, zone)? < end {
        let next = if ranges.monthly {
            month_start(day, -1)?
        } else {
            add_days(day, 1)?
        };
        let window = Window {
            start: midnight(day, zone)?.max(start),
            end: midnight(next, zone)?.min(end),
        };
        let name = if ranges.monthly {
            label(day)[..7].to_owned()
        } else {
            label(day)
        };
        list.push((name, window));
        day = next;
    }
    Ok(list)
}

/// Change against the comparison value. Integer maths, tenths of a percent rounded half away from
/// zero, measured against |previous| so a smaller loss reads as an improvement.
pub fn change(current: i128, previous: i128) -> Value {
    match (previous, current) {
        (0, 0) => json!({ "state": "ZERO" }),
        (0, value) if value > 0 => json!({ "state": "NEW" }),
        (0, _) => json!({ "state": "NO_BASELINE" }),
        _ => {
            let numerator = (current - previous) * 1000;
            let base = previous.abs();
            let tenths = (numerator.abs() * 2 + base) / (base * 2) * numerator.signum();
            let sign = if tenths < 0 { "-" } else { "" };
            json!({ "state": "PERCENT", "percent": format!("{sign}{}.{}", tenths.abs() / 10, tenths.abs() % 10) })
        }
    }
}

fn amount(value: i128) -> String {
    value.to_string()
}

/// The confirmed ledger with the stored-equivalent snapshot deltas from a full replay.
pub struct Ledger {
    rows: Vec<Activity>,
    deltas: BTreeMap<String, i64>,
}

impl Ledger {
    pub fn new(mut rows: Vec<Activity>) -> Result<Self, Failure> {
        let projection = replay(&mut rows)?; // also sorts by (effectiveAt, sequence)
        Ok(Self {
            rows,
            deltas: projection.snapshot_deltas,
        })
    }

    fn live(&self, window: Window) -> impl Iterator<Item = &Activity> {
        self.rows.iter().filter(move |row| {
            !row.deleted && row.effective_at.0 >= window.start && row.effective_at.0 < window.end
        })
    }

    /// Balance and per-borrower receivables just before `instant`, straight from the core replay.
    fn at(&self, instant: i64) -> Result<(i64, BTreeMap<String, i64>), Failure> {
        let mut prefix: Vec<Activity> = self
            .rows
            .iter()
            .filter(|row| row.effective_at.0 < instant)
            .cloned()
            .collect();
        let projection = replay(&mut prefix)?;
        Ok((projection.balance, projection.receivables))
    }

    /// Cash this row moved, as the replay applied it.
    fn cash(&self, row: &Activity) -> Result<i128, Failure> {
        if row.kind.snapshot() {
            return Ok(i128::from(self.deltas.get(&row.id).copied().unwrap_or(0)));
        }
        Ok(if row.moves_cash() {
            i128::from(row.signed_amount()?)
        } else {
            0
        })
    }

    fn income_expense(&self, window: Window) -> (i128, i128) {
        self.live(window).fold((0, 0), |(income, expense), row| {
            match (row.kind, row.amount) {
                (Kind::Increase, Some(value)) => (income + i128::from(value.0), expense),
                (Kind::Deduct, Some(value)) => (income, expense + i128::from(value.0)),
                _ => (income, expense),
            }
        })
    }
}

fn totals(income: i128, expense: i128) -> Value {
    json!({ "income": amount(income), "expense": amount(expense), "net": amount(income - expense) })
}

pub fn income_expense(
    ledger: &Ledger,
    ranges: &Ranges,
    categories: &[store::Category],
) -> Result<Value, Failure> {
    let (income, expense) = ledger.income_expense(ranges.current);
    let (before_income, before_expense) = ledger.income_expense(ranges.previous);
    let mut by_category: BTreeMap<Option<String>, (i128, i128)> = BTreeMap::new();
    for row in ledger.live(ranges.current) {
        let entry = by_category.entry(row.category_id.clone()).or_default();
        match (row.kind, row.amount) {
            (Kind::Increase, Some(value)) => entry.0 += i128::from(value.0),
            (Kind::Deduct, Some(value)) => entry.1 += i128::from(value.0),
            _ => {}
        }
    }
    let categories: Vec<Value> = by_category
        .into_iter()
        .filter(|(_, (income, expense))| *income != 0 || *expense != 0)
        .map(|(id, (income, expense))| {
            let known = id.as_ref().and_then(|id| categories.iter().find(|c| &c.id == id));
            json!({
                "categoryId": id, "name": known.map(|c| c.name.as_str()), "archived": known.is_some_and(|c| c.archived),
                "income": amount(income), "expense": amount(expense),
            })
        })
        .collect();
    let series = buckets(ranges)?
        .into_iter()
        .map(|(name, window)| {
            let (income, expense) = ledger.income_expense(window);
            json!({ "label": name, "income": amount(income), "expense": amount(expense) })
        })
        .collect::<Vec<_>>();
    Ok(json!({
        "range": range(ranges)?, "comparison": describe(ranges.previous, &ranges.zone)?, "timezone": ranges.zone_name,
        "current": totals(income, expense), "previous": totals(before_income, before_expense),
        "change": {
            "income": change(income, before_income), "expense": change(expense, before_expense),
            "net": change(income - expense, before_income - before_expense),
        },
        "categories": categories, "series": series,
    }))
}

pub fn balance_movement(ledger: &Ledger, ranges: &Ranges) -> Result<Value, Failure> {
    let Window { start, end } = ranges.current;
    let opening = i128::from(ledger.at(start)?.0);
    let closing = i128::from(ledger.at(end)?.0);
    let (mut income, mut expense, mut loans, mut repayments, mut snapshots) =
        (0i128, 0i128, 0i128, 0i128, 0i128);
    for row in ledger.live(ranges.current) {
        let cash = ledger.cash(row)?;
        match row.kind {
            Kind::Increase => income += cash,
            Kind::Deduct => expense -= cash,
            Kind::Loan => loans -= cash,
            Kind::Repayment => repayments += cash,
            Kind::Opening | Kind::Adjustment => snapshots += cash,
        }
    }
    // The movement must explain the core's own closing balance exactly; anything else is a defect.
    if opening + income - expense - loans + repayments + snapshots != closing {
        return Err(Failure::Internal);
    }
    let mut running = opening;
    let mut series = Vec::new();
    for (name, window) in buckets(ranges)? {
        for row in ledger.live(window) {
            running += ledger.cash(row)?;
        }
        series.push(json!({ "label": name, "closing": amount(running) }));
    }
    Ok(json!({
        "range": range(ranges)?, "timezone": ranges.zone_name, "opening": amount(opening), "income": amount(income),
        "expense": amount(expense), "loansOut": amount(loans), "repaymentsIn": amount(repayments),
        "snapshotDelta": amount(snapshots), "closing": amount(closing), "series": series,
    }))
}

pub fn receivables(
    ledger: &Ledger,
    ranges: &Ranges,
    borrowers: &[store::Borrower],
) -> Result<Value, Failure> {
    let Window { start, end } = ranges.current;
    let (_, opening) = ledger.at(start)?;
    let (_, closing) = ledger.at(end)?;
    let mut moved: BTreeMap<&str, (i128, i128)> = BTreeMap::new();
    for row in ledger.live(ranges.current) {
        if let (Some(borrower), Some(value)) = (row.borrower_id.as_deref(), row.amount) {
            let entry = moved.entry(borrower).or_default();
            match row.kind {
                Kind::Loan => entry.0 += i128::from(value.0),
                Kind::Repayment => entry.1 += i128::from(value.0),
                _ => {}
            }
        }
    }
    let (mut sum_open, mut sum_loans, mut sum_repaid, mut sum_close) = (0i128, 0i128, 0i128, 0i128);
    let mut list = Vec::new();
    for borrower in borrowers {
        let open = i128::from(opening.get(&borrower.id).copied().unwrap_or(0));
        let close = i128::from(closing.get(&borrower.id).copied().unwrap_or(0));
        let (loans, repaid) = moved.get(borrower.id.as_str()).copied().unwrap_or((0, 0));
        if open + loans - repaid != close {
            return Err(Failure::Internal);
        }
        if open == 0 && close == 0 && loans == 0 && repaid == 0 {
            continue;
        }
        (sum_open, sum_loans, sum_repaid, sum_close) = (
            sum_open + open,
            sum_loans + loans,
            sum_repaid + repaid,
            sum_close + close,
        );
        list.push(json!({
            "borrowerId": borrower.id, "name": borrower.name, "archived": borrower.archived,
            "opening": amount(open), "loans": amount(loans), "repayments": amount(repaid), "closing": amount(close),
        }));
    }
    Ok(json!({
        "range": range(ranges)?, "timezone": ranges.zone_name, "opening": amount(sum_open), "loans": amount(sum_loans),
        "repayments": amount(sum_repaid), "closing": amount(sum_close), "borrowers": list,
    }))
}

fn range(ranges: &Ranges) -> Result<Value, Failure> {
    let mut value = describe(ranges.current, &ranges.zone)?;
    value["period"] = json!(ranges.period.name());
    value["running"] = json!(ranges.running);
    Ok(value)
}

#[cfg(test)]
mod tests {
    use super::*;

    const JAKARTA: &str = "Asia/Jakarta";

    fn jakarta() -> TimeZone {
        zone(JAKARTA).unwrap()
    }

    fn at(date: &str, hour: i64) -> i64 {
        midnight(parse_date(date).unwrap(), &jakarta()).unwrap() + hour * 3600 * MICROS
    }

    fn day(micros: i64) -> String {
        label(local_date(micros, &jakarta()).unwrap())
    }

    fn range(period: Period, from: &str, to: Option<&str>, now: i64) -> Result<Ranges, Failure> {
        ranges(
            period,
            parse_date(from).unwrap(),
            to.and_then(parse_date),
            now,
            JAKARTA,
        )
    }

    #[test]
    fn running_month_compares_the_same_elapsed_part_of_the_previous_month() {
        let now = at("2026-11-21", 14);
        let r = range(Period::Month, "2026-11-05", None, now).unwrap();
        assert!(r.running);
        assert_eq!((r.current.start, r.current.end), (at("2026-11-01", 0), now));
        assert_eq!(
            (r.previous.start, r.previous.end),
            (at("2026-10-01", 0), at("2026-10-21", 14))
        );
    }

    #[test]
    fn running_31_march_is_clamped_to_the_end_of_february() {
        let now = at("2026-03-31", 10);
        let r = range(Period::Month, "2026-03-31", None, now).unwrap();
        assert_eq!(
            (r.previous.start, r.previous.end),
            (at("2026-02-01", 0), at("2026-03-01", 0))
        );
    }

    #[test]
    fn finished_periods_compare_with_the_whole_previous_period() {
        let now = at("2026-11-21", 14);
        let month = range(Period::Month, "2026-02-10", None, now).unwrap();
        assert!(!month.running);
        assert_eq!(
            (month.current.start, month.current.end),
            (at("2026-02-01", 0), at("2026-03-01", 0))
        );
        assert_eq!(
            (month.previous.start, month.previous.end),
            (at("2026-01-01", 0), at("2026-02-01", 0))
        );
        let year = range(Period::Year, "2025-06-01", None, now).unwrap();
        assert_eq!(
            (year.previous.start, year.previous.end),
            (at("2024-01-01", 0), at("2025-01-01", 0))
        );
        assert!(year.monthly);
        // 2026-11-11 is a Wednesday; weeks start on Monday.
        let week = range(Period::Week, "2026-11-11", None, now).unwrap();
        assert_eq!(
            (week.current.start, week.previous.start),
            (at("2026-11-09", 0), at("2026-11-02", 0))
        );
    }

    #[test]
    fn custom_ranges_compare_with_the_equally_long_range_before_them() {
        let now = at("2026-11-21", 14);
        let r = range(Period::Custom, "2026-10-10", Some("2026-10-19"), now).unwrap();
        assert_eq!(
            (r.current.start, r.current.end),
            (at("2026-10-10", 0), at("2026-10-20", 0))
        );
        assert_eq!(
            (r.previous.start, r.previous.end),
            (at("2026-09-30", 0), at("2026-10-10", 0))
        );
        let today = range(Period::Custom, "2026-11-20", Some("2026-11-21"), now).unwrap();
        assert!(today.running);
        assert_eq!(
            (today.previous.start, today.previous.end),
            (at("2026-11-18", 0), at("2026-11-19", 14))
        );
    }

    #[test]
    fn invalid_ranges_are_refused() {
        let now = at("2026-11-21", 14);
        assert!(range(Period::Custom, "2026-10-10", Some("2026-10-09"), now).is_err());
        assert!(range(Period::Custom, "2026-10-10", None, now).is_err());
        assert!(range(Period::Custom, "2016-01-01", Some("2026-01-01"), now).is_err());
        assert!(range(Period::Day, "2026-11-22", None, now).is_err());
        assert!(
            ranges(
                Period::Day,
                parse_date("2026-11-01").unwrap(),
                None,
                now,
                "Mars/Olympus"
            )
            .is_err()
        );
        assert_eq!(parse_date("2026-2-01"), None);
        assert_eq!(parse_date("2026-02-30"), None);
        assert!(
            zone("").is_none() && zone("Not/AZone").is_none() && zone("America/New_York").is_some()
        );
    }

    #[test]
    fn days_follow_the_account_zone() {
        // 16:59:59.999999Z is still 23:59 WIB; 17:00Z is the next day.
        let before = 1_779_382_799_999_999; // 2026-05-21T16:59:59.999999Z
        assert_eq!(
            (day(before), day(before + 1)),
            ("2026-05-21".to_owned(), "2026-05-22".to_owned())
        );
    }

    #[test]
    fn dst_days_are_23_and_25_hours_long() {
        let york = zone("America/New_York").unwrap();
        let now = midnight(parse_date("2026-12-01").unwrap(), &york).unwrap();
        let day = |date| {
            ranges(
                Period::Day,
                parse_date(date).unwrap(),
                None,
                now,
                "America/New_York",
            )
            .unwrap()
        };
        let (spring, autumn) = (day("2026-03-08"), day("2026-11-01"));
        assert_eq!(
            spring.current.end - spring.current.start,
            23 * 3600 * MICROS
        );
        assert_eq!(
            autumn.current.end - autumn.current.start,
            25 * 3600 * MICROS
        );
        let march = ranges(
            Period::Month,
            parse_date("2026-03-01").unwrap(),
            None,
            now,
            "America/New_York",
        )
        .unwrap();
        let days = buckets(&march).unwrap();
        assert_eq!(
            (days.len(), days[7].1.end - days[7].1.start),
            (31, 23 * 3600 * MICROS)
        );
        assert_eq!(march.zone_name, "America/New_York");
    }

    #[test]
    fn comparison_states_use_integer_rounding() {
        assert_eq!(change(0, 0)["state"], "ZERO");
        assert_eq!(change(5, 0)["state"], "NEW");
        assert_eq!(change(-5, 0)["state"], "NO_BASELINE");
        assert_eq!(change(150, 100)["percent"], "50.0");
        assert_eq!(change(1, 3)["percent"], "-66.7");
        assert_eq!(change(2, 3)["percent"], "-33.3");
        assert_eq!(change(-50, -100)["percent"], "50.0"); // a smaller loss is an improvement
        assert_eq!(change(1_000_001, 1_000_000)["percent"], "0.0");
    }
}
