use std::{collections::BTreeMap, time::Instant};

#[derive(Clone, Copy)]
enum Kind {
    Cash(i64),
    Snapshot(i64),
    Receivable { borrower: u64, delta: i64 },
}

#[derive(Clone, Copy)]
struct Event {
    instant: u64,
    seq: u64,
    kind: Kind,
}

#[derive(Debug, Default, PartialEq)]
struct Projection {
    balance: i64,
    snapshot_deltas: BTreeMap<u64, i64>,
    receivables: BTreeMap<u64, i64>,
}

#[derive(Debug, PartialEq)]
enum ReplayError {
    Overflow,
    NegativeReceivable,
}

fn replay(events: &mut [Event]) -> Result<Projection, ReplayError> {
    events.sort_unstable_by_key(|event| (event.instant, event.seq));
    let mut result = Projection::default();
    for event in events {
        match event.kind {
            Kind::Cash(delta) => {
                result.balance = result
                    .balance
                    .checked_add(delta)
                    .ok_or(ReplayError::Overflow)?;
            }
            Kind::Snapshot(target) => {
                let delta = target
                    .checked_sub(result.balance)
                    .ok_or(ReplayError::Overflow)?;
                result.snapshot_deltas.insert(event.seq, delta);
                result.balance = target;
            }
            Kind::Receivable { borrower, delta } => {
                let outstanding = result.receivables.entry(borrower).or_default();
                *outstanding = outstanding
                    .checked_add(delta)
                    .ok_or(ReplayError::Overflow)?;
                if *outstanding < 0 {
                    return Err(ReplayError::NegativeReceivable);
                }
            }
        }
    }
    Ok(result)
}

pub fn run() {
    use Kind::{Cash, Receivable, Snapshot};
    let event = |instant, seq, kind| Event { instant, seq, kind };
    let opening = event(2, 1, Snapshot(0));
    let adjustment = event(3, 3, Snapshot(30));
    let after = event(4, 5, Cash(-5));
    assert_eq!(replay(&mut [event(1, 4, Cash(-7))]).unwrap().balance, -7);
    for (early, tied, expected) in [(-7, 23, 7), (-9, 21, 9)] {
        let projection = replay(&mut [
            after,
            adjustment,
            event(2, 2, Cash(tied)),
            opening,
            event(1, 4, Cash(early)),
        ])
        .unwrap();
        assert_eq!(projection.balance, 25);
        assert_eq!(
            projection.snapshot_deltas,
            BTreeMap::from([(1, expected), (3, expected)])
        );
    }
    let loan = event(
        2,
        1,
        Receivable {
            borrower: 1,
            delta: 9,
        },
    );
    let payment = event(
        2,
        2,
        Receivable {
            borrower: 1,
            delta: -8,
        },
    );
    let result = replay(&mut [payment, loan]).unwrap();
    assert_eq!(result.balance, 0);
    assert_eq!(result.receivables, BTreeMap::from([(1, 1)]));
    assert_eq!(
        replay(&mut [
            Event {
                instant: 1,
                ..payment
            },
            loan
        ]),
        Err(ReplayError::NegativeReceivable)
    );
    assert_eq!(
        replay(&mut [
            loan,
            event(
                3,
                2,
                Receivable {
                    borrower: 2,
                    delta: -8
                }
            )
        ]),
        Err(ReplayError::NegativeReceivable)
    );
    assert_eq!(
        replay(&mut [event(1, 1, Cash(i64::MIN)), opening]),
        Err(ReplayError::Overflow)
    );
    assert_eq!(
        replay(&mut [event(1, 1, Cash(i64::MAX)), event(2, 2, Cash(1))]),
        Err(ReplayError::Overflow)
    );
    for size in [1_000, 10_000, 100_000] {
        let mut events: Vec<_> = (0..size)
            .map(|i| event(i * 37 % size, i + 1, Cash(1)))
            .collect();
        let start = Instant::now();
        assert_eq!(replay(&mut events).unwrap().balance, size as i64);
        println!(
            "Rust replay {size} events: {:.2} ms",
            start.elapsed().as_secs_f64() * 1_000.0
        );
    }
}
