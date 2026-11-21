use axum::{Router, extract::State, http::StatusCode, routing::get};
use rust_xlsxwriter::{Workbook, XlsxError};
use sqlx::{MySqlPool, mysql::MySqlPoolOptions};
use std::{error::Error, future, time::Duration};
use tokio::{net::TcpListener, sync::mpsc, time};

type ProbeResult<T> = Result<T, Box<dyn Error>>;
type Rows = Vec<(u32, i64)>;
const OWNER: u32 = 1;
const EXPORT_PATH: &str = "/tmp/probe.xlsx";

async fn report(State(pool): State<MySqlPool>) -> Result<String, StatusCode> {
    let result = time::timeout(
        Duration::from_secs(2),
        sqlx::query_scalar::<_, i64>("SELECT CAST(COUNT(*) AS SIGNED) FROM ledger WHERE owner=?")
            .bind(OWNER)
            .fetch_one(&pool),
    )
    .await;
    match result {
        Ok(Ok(count)) => Ok(count.to_string()),
        _ => Err(StatusCode::SERVICE_UNAVAILABLE),
    }
}

fn write_xlsx(mut batches: mpsc::Receiver<Rows>) -> Result<u32, XlsxError> {
    let mut workbook = Workbook::new();
    let worksheet = workbook.add_worksheet_with_constant_memory()?;
    worksheet.write_string(0, 0, "Sequence")?;
    worksheet.write_string(0, 1, "IDR")?;
    let mut row = 1;
    while let Some(batch) = batches.blocking_recv() {
        for (sequence, amount) in batch {
            worksheet.write_number(row, 0, sequence)?;
            worksheet.write_string(row, 1, amount.to_string())?;
            row += 1;
        }
    }
    workbook.save(EXPORT_PATH)?;
    Ok(row - 1)
}

async fn export(pool: &MySqlPool) -> ProbeResult<u32> {
    let limit: u32 = sqlx::query_scalar("SELECT MAX(seq) FROM ledger WHERE owner=?")
        .bind(OWNER)
        .fetch_one(pool)
        .await?;
    let (send, receive) = mpsc::channel(2);
    let writer = tokio::task::spawn_blocking(move || write_xlsx(receive));
    let mut after = 0_u32;
    while after < limit {
        let rows: Rows = sqlx::query_as(
            "SELECT seq,amount FROM ledger WHERE owner=? AND seq>? AND seq<=? ORDER BY seq LIMIT 1000",
        )
        .bind(OWNER)
        .bind(after)
        .bind(limit)
        .fetch_all(pool)
        .await?;
        let Some(&(last, _)) = rows.last() else { break };
        after = last;
        send.send(rows).await?;
    }
    drop(send);
    Ok(writer.await??)
}

#[tokio::main(worker_threads = 2)]
async fn main() -> ProbeResult<()> {
    let mode = std::env::args().nth(1).ok_or("expected api or worker")?;
    let connections = match mode.as_str() {
        "api" => 4,
        "worker" => 1,
        _ => return Err("expected api or worker".into()),
    };
    let url = std::env::var("DUIT_RESOURCE_DB_URL")?;
    let pool = MySqlPoolOptions::new()
        .max_connections(connections)
        .acquire_timeout(Duration::from_secs(2))
        .connect(&url)
        .await?;
    if mode == "api" {
        let listener = TcpListener::bind(("0.0.0.0", 8080)).await?;
        let app = Router::new().route("/report", get(report)).with_state(pool);
        axum::serve(listener, app).await?;
    } else {
        tokio::fs::write("/tmp/ready", "").await?;
        while !tokio::fs::try_exists("/tmp/start").await? {
            time::sleep(Duration::from_millis(50)).await;
        }
        let count = export(&pool).await?;
        tokio::fs::write("/tmp/done", count.to_string()).await?;
        // Keep the container alive until the harness samples its cgroup counters.
        future::pending::<()>().await;
    }
    Ok(())
}
