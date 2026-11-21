mod replay;

use sqlx::{
    Acquire, MySql, MySqlPool, Transaction,
    mysql::{MySqlConnectOptions, MySqlPoolOptions},
};
use std::{
    error::Error,
    time::{Duration, Instant},
};
use tokio::sync::Barrier;

type ProbeResult<T> = Result<T, Box<dyn Error>>;

async fn lock(tx: &mut Transaction<'_, MySql>, owner: i32) -> Result<(i64, i64), sqlx::Error> {
    let row = sqlx::query!(
        "SELECT balance AS `balance!`, next_seq AS `next_seq!` FROM account WHERE id=? FOR UPDATE",
        owner
    )
    .fetch_one(&mut **tx)
    .await?;
    Ok((row.balance, row.next_seq))
}

async fn audit(tx: &mut Transaction<'_, MySql>, owner: i32, seq: i64) -> Result<(), sqlx::Error> {
    sqlx::query("INSERT INTO audit VALUES (?,?)")
        .bind(owner)
        .bind(seq)
        .execute(&mut **tx)
        .await?;
    Ok(())
}

fn mysql_number(error: &sqlx::Error) -> Option<u16> {
    error
        .as_database_error()?
        .try_downcast_ref::<sqlx::mysql::MySqlDatabaseError>()
        .map(|db| db.number())
}

async fn deduct(pool: &MySqlPool, owner: i32, amount: i64, attempt: &str) -> ProbeResult<i64> {
    if amount <= 0 {
        return Err("debit amount must be positive".into());
    }
    let mut tx = pool.begin().await?;
    let (balance, seq) = lock(&mut tx, owner).await?;
    let previous: Option<(i64, i64)> = sqlx::query_as(
        "SELECT o.seq,a.delta FROM outcome o JOIN activity a ON a.owner=o.owner AND a.seq=o.seq WHERE o.owner=? AND o.attempt=?",
    ).bind(owner).bind(attempt).fetch_optional(&mut *tx).await?;
    if let Some((seq, delta)) = previous {
        if delta != -amount {
            return Err("attempt identity reused with a different amount".into());
        }
        tx.commit().await?;
        return Ok(seq);
    }
    let next_balance = balance.checked_sub(amount).ok_or("balance overflow")?;
    let next_seq = seq.checked_add(1).ok_or("sequence overflow")?;
    sqlx::query("INSERT INTO activity VALUES (?,'2026-01-01 12:00:00',?,?,NULL)")
        .bind(owner)
        .bind(seq)
        .bind(-amount)
        .execute(&mut *tx)
        .await?;
    sqlx::query("UPDATE account SET balance=?,next_seq=? WHERE id=?")
        .bind(next_balance)
        .bind(next_seq)
        .bind(owner)
        .execute(&mut *tx)
        .await?;
    audit(&mut tx, owner, seq).await?;
    sqlx::query("INSERT INTO outcome VALUES (?,?,?)")
        .bind(owner)
        .bind(attempt)
        .bind(seq)
        .execute(&mut *tx)
        .await?;
    tx.commit().await?;
    Ok(seq)
}

async fn assert_count(pool: &MySqlPool, query: &'static str, count: i64) -> ProbeResult<()> {
    assert_eq!(
        sqlx::query_scalar::<_, i64>(query).fetch_one(pool).await?,
        count
    );
    Ok(())
}

async fn concurrency(pool: &MySqlPool) -> ProbeResult<()> {
    let (first, second) =
        tokio::join!(deduct(pool, 4, 10, "sqlx-a"), deduct(pool, 4, 20, "sqlx-b"));
    let first = first?;
    let mut sequences = [first, second?];
    sequences.sort_unstable();
    assert_eq!(sequences, [1, 2]);
    assert_eq!(deduct(pool, 4, 10, "sqlx-a").await?, first);
    assert!(deduct(pool, 4, 11, "sqlx-a").await.is_err());
    let row: (i64, i64) = sqlx::query_as("SELECT balance,next_seq FROM account WHERE id=4")
        .fetch_one(pool)
        .await?;
    assert_eq!(row, (9_007_199_254_740_963, 3));
    assert_count(pool, "SELECT COUNT(*) FROM activity WHERE owner=4", 2).await?;
    assert_count(pool, "SELECT COUNT(*) FROM audit WHERE owner=4", 2).await?;
    assert_count(pool, "SELECT COUNT(*) FROM outcome WHERE owner=4", 2).await?;
    println!("SQLx concurrent debit, signed BIGINT and same-attempt replay OK");
    Ok(())
}

async fn isolation(
    pool: &MySqlPool,
    statement: &'static str,
    attempt: &str,
    expected: i64,
) -> ProbeResult<()> {
    let mut connection = pool.acquire().await?;
    sqlx::query(statement).execute(&mut *connection).await?;
    let mut reader = connection.begin().await?;
    let count = "SELECT COUNT(*) FROM activity WHERE owner=5";
    let before: i64 = sqlx::query_scalar(count).fetch_one(&mut *reader).await?;
    deduct(pool, 5, 1, attempt).await?;
    assert_eq!(lock(&mut reader, 5).await?.1, before + 2);
    let after: i64 = sqlx::query_scalar(count).fetch_one(&mut *reader).await?;
    assert_eq!(after - before, expected);
    reader.rollback().await?;
    assert_count(pool, count, before + 1).await
}

async fn create_deadlock(
    pool: &MySqlPool,
    barrier: &Barrier,
    first: i32,
    second: i32,
) -> Result<(), sqlx::Error> {
    let mut tx = pool.begin().await?;
    lock(&mut tx, first).await?;
    audit(&mut tx, first, 999).await?;
    barrier.wait().await;
    let result = lock(&mut tx, second).await.map(|_| ());
    tx.rollback().await?;
    result
}

async fn failures(pool: &MySqlPool) -> ProbeResult<()> {
    let mut holder = pool.begin().await?;
    lock(&mut holder, 6).await?;
    let mut contender = pool.begin().await?;
    audit(&mut contender, 6, 998).await?;
    let failure = lock(&mut contender, 6)
        .await
        .expect_err("lock must time out");
    assert_eq!(mysql_number(&failure), Some(1205));
    contender.rollback().await?;
    assert_eq!(deduct(pool, 7, 1, "different-owner").await?, 1);

    let mut cancelled = pool.begin().await?;
    audit(&mut cancelled, 6, 997).await?;
    assert!(
        tokio::time::timeout(Duration::from_millis(150), lock(&mut cancelled, 6))
            .await
            .is_err()
    );
    drop(cancelled);
    holder.rollback().await?;
    // Acquire every connection to force SQLx to complete any deferred cleanup before checking.
    let (one, two, three) = tokio::try_join!(pool.acquire(), pool.acquire(), pool.acquire())?;
    drop((one, two, three));

    let barrier = Barrier::new(2);
    let (first, second) = tokio::time::timeout(Duration::from_secs(6), async {
        tokio::join!(
            create_deadlock(pool, &barrier, 6, 7),
            create_deadlock(pool, &barrier, 7, 6)
        )
    })
    .await?;
    let failed = match (first, second) {
        (Err(error), Ok(())) | (Ok(()), Err(error)) => error,
        pair => return Err(format!("expected one deadlock victim, got {pair:?}").into()),
    };
    assert_eq!(mysql_number(&failed), Some(1213));
    assert_count(
        pool,
        "SELECT COUNT(*) FROM audit WHERE seq IN (997,998,999)",
        0,
    )
    .await?;
    assert_eq!(deduct(pool, 6, 1, "after-rollback").await?, 1);
    assert_eq!(deduct(pool, 6, 1, "after-rollback").await?, 1);
    sqlx::query("INSERT INTO audit VALUES (8,1)")
        .execute(pool)
        .await?;
    let failure = deduct(pool, 8, 1, "audit-error")
        .await
        .expect_err("audit must fail");
    let number = failure.downcast_ref::<sqlx::Error>().and_then(mysql_number);
    assert_eq!(number, Some(1062));
    let mut verify = pool.begin().await?;
    assert_eq!(lock(&mut verify, 8).await?, (0, 1));
    verify.rollback().await?;
    assert_count(pool, "SELECT COUNT(*) FROM activity WHERE owner=8", 0).await?;
    assert_count(pool, "SELECT COUNT(*) FROM outcome WHERE owner=8", 0).await?;
    assert_count(pool, "SELECT COUNT(*) FROM audit WHERE owner=8", 1).await?;
    println!(
        "SQLx timeout 1205, cancellation, deadlock 1213, independent owner, retry and audit rollback OK"
    );
    Ok(())
}

#[tokio::main]
async fn main() -> ProbeResult<()> {
    let url = std::env::var("DUIT_PROBE_URL")?;
    let options: MySqlConnectOptions = url.parse()?;
    assert_eq!(options.get_host(), "127.0.0.1");
    assert_eq!(options.get_database(), Some("duit_probe"));
    assert_eq!(options.get_username(), "duit_sqlx");
    let pool = MySqlPoolOptions::new()
        .max_connections(3)
        .acquire_timeout(Duration::from_secs(5))
        .after_connect(|connection, _| {
            Box::pin(async move {
                sqlx::query("SET SESSION innodb_lock_wait_timeout=2")
                    .execute(connection)
                    .await?;
                Ok(())
            })
        })
        .connect_with(options)
        .await?;
    concurrency(&pool).await?;
    isolation(
        &pool,
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ",
        "rr",
        0,
    )
    .await?;
    isolation(
        &pool,
        "SET TRANSACTION ISOLATION LEVEL READ COMMITTED",
        "rc",
        1,
    )
    .await?;
    println!(
        "SQLx Repeatable Read retains a pre-lock snapshot; Read Committed sees the new activity"
    );
    failures(&pool).await?;
    let start = Instant::now();
    let rows: Vec<(i64, i64)> =
        sqlx::query_as("SELECT seq,delta FROM activity WHERE owner=? ORDER BY effective_at,seq")
            .bind(3_i32)
            .fetch_all(&pool)
            .await?;
    assert_eq!(rows.len(), 10_000);
    for (index, (seq, delta)) in rows.into_iter().enumerate() {
        assert_eq!((seq, delta), (index as i64 + 1, 1));
    }
    println!(
        "SQLx reads and validates 10,000 ordered rows in {:.2} ms",
        start.elapsed().as_secs_f64() * 1_000.0
    );
    replay::run();
    pool.close().await;
    Ok(())
}
