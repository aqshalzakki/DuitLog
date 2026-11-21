use std::{env, process::ExitCode};

use duitlog::financial;
use sqlx::mysql::MySqlPoolOptions;

#[tokio::main(worker_threads = 1)]
async fn main() -> ExitCode {
    match run().await {
        Ok(frozen) => {
            println!("frozen={frozen}");
            ExitCode::SUCCESS
        }
        Err(message) => {
            eprintln!("{message}");
            ExitCode::FAILURE
        }
    }
}

async fn run() -> Result<bool, &'static str> {
    let args: Vec<String> = env::args().skip(1).collect();
    let [action, owner] = args.as_slice() else {
        return Err("Usage: finance_operator <reconcile|unfreeze> <owner-id>");
    };
    let owner = uuid::Uuid::parse_str(owner).map_err(|_| "Invalid owner ID")?;
    let reason = match action.as_str() {
        "reconcile" => None,
        "unfreeze" => {
            let reason = env::var("DUIT_FINANCE_OPERATOR_REASON")
                .map_err(|_| "Set DUIT_FINANCE_OPERATOR_REASON")?;
            if reason.trim().is_empty() || reason.chars().count() > 500 {
                return Err("Operator reason must contain 1 to 500 characters");
            }
            Some(reason)
        }
        _ => return Err("Expected reconcile or unfreeze"),
    };
    let actor =
        env::var("DUIT_FINANCE_OPERATOR_ACTOR").map_err(|_| "Set DUIT_FINANCE_OPERATOR_ACTOR")?;
    let url = env::var("DUIT_FINANCE_OPERATOR_DATABASE_URL")
        .map_err(|_| "Set DUIT_FINANCE_OPERATOR_DATABASE_URL")?;
    let db = MySqlPoolOptions::new()
        .max_connections(1)
        .connect(&url)
        .await
        .map_err(|_| "Database connection failed")?;
    financial::reconcile(&db, owner, &format!("operator:{actor}"), reason.as_deref())
        .await
        .map_err(|_| "Financial reconciliation could not be completed")
}
