use super::model::*;

fn activity(id: &str, time: i64, seq: i64, kind: Kind, amount: i64) -> Activity {
    Activity {
        id: id.into(),
        effective_at: Moment(time),
        sequence: seq,
        kind,
        amount: Some(Money(amount)),
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
    }
}

fn snapshot(id: &str, instant: i64, seq: i64, target: i64) -> Activity {
    let mut row = activity(id, instant, seq, Kind::Adjustment, 0);
    row.amount = None;
    row.target_balance = Some(Money(target));
    row
}

#[test]
fn snapshots_preserve_target_including_zero_and_timestamp_ties() {
    let mut rows = vec![
        activity("later", 4, 5, Kind::Deduct, 5),
        snapshot("adjustment", 3, 3, 30),
        activity("tied", 2, 2, Kind::Increase, 23),
        snapshot("opening", 2, 1, 0),
        activity("backdate", 1, 4, Kind::Deduct, 7),
    ];
    assert_eq!(replay(&mut rows[..]).unwrap().balance, 25);
    let projection = replay(&mut rows[..]).unwrap();
    assert_eq!(projection.snapshot_deltas["opening"], 7);
    assert_eq!(projection.snapshot_deltas["adjustment"], 7);
    let edited = rows.iter_mut().find(|a| a.id == "backdate").unwrap();
    edited.deleted = true;
    let projection = replay(&mut rows).unwrap();
    assert_eq!(projection.balance, 25);
    assert_eq!(projection.snapshot_deltas["opening"], 0);
    assert_eq!(projection.snapshot_deltas["adjustment"], 7);
    assert_eq!(
        replay(&mut [activity("no-opening", 1, 1, Kind::Deduct, 7)])
            .unwrap()
            .balance,
        -7
    );
}

#[test]
fn checks_every_receivable_prefix_and_dependencies() {
    let mut loan = activity("loan", 2, 1, Kind::Loan, 9);
    loan.borrower_id = Some("person".into());
    loan.affect_cash_balance = Some(false);
    let mut repayment = activity("repay", 2, 2, Kind::Repayment, 8);
    repayment.borrower_id = loan.borrower_id.clone();
    repayment.affect_cash_balance = Some(false);
    repayment.depends_on = vec!["loan".into()];
    let result = replay(&mut [repayment.clone(), loan.clone()]).unwrap();
    assert_eq!(result.balance, 0);
    assert_eq!(result.receivables["person"], 1);
    repayment.effective_at = Moment(1);
    assert_eq!(
        replay(&mut [loan.clone(), repayment.clone()])
            .unwrap_err()
            .code,
        Code::DependencyBlocked
    );
    repayment.depends_on.clear();
    assert_eq!(
        replay(&mut [loan, repayment]).unwrap_err().code,
        Code::ReceivableNegative
    );
}

#[test]
fn integers_are_canonical_and_overflow_is_rejected() {
    assert_eq!(
        serde_json::from_str::<Money>(r#""9007199254740993""#).unwrap(),
        Money(9_007_199_254_740_993)
    );
    for invalid in [
        r#""01""#,
        r#""-0""#,
        r#""+1""#,
        r#""1.0""#,
        "1",
        r#""9223372036854775808""#,
    ] {
        assert!(serde_json::from_str::<Money>(invalid).is_err());
    }
    assert_eq!(
        replay(&mut [
            activity("large", 1, 1, Kind::Increase, i64::MAX),
            activity("one", 2, 2, Kind::Increase, 1)
        ])
        .unwrap_err()
        .code,
        Code::AmountOverflow
    );
}

#[test]
fn varied_cash_histories_match_independent_projection() {
    for seed in 1..=500_u64 {
        let mut next = seed;
        let mut expected = 0_i64;
        let mut rows = Vec::new();
        for number in 0..64 {
            next = next.wrapping_mul(6364136223846793005).wrapping_add(1);
            let amount = (next % 200 + 1) as i64;
            let kind = if next >> 63 == 0 {
                Kind::Increase
            } else {
                Kind::Deduct
            };
            let mut row = activity(&number.to_string(), number / 3, number + 1, kind, amount);
            if next % 11 == 0 {
                row = snapshot(&number.to_string(), number / 3, number + 1, -amount);
                expected = -amount;
            } else if next % 7 != 0 {
                expected += if kind == Kind::Increase {
                    amount
                } else {
                    -amount
                };
            } else {
                row.deleted = true;
            }
            rows.push(row);
        }
        rows.reverse();
        assert_eq!(replay(&mut rows).unwrap().balance, expected, "seed {seed}");
    }
}
