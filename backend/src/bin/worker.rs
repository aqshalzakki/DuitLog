use std::process::ExitCode;

use duitlog::{database, evidence, mail::Mailer, mail_key, origin, storage::Storage};

#[tokio::main(worker_threads = 2)]
async fn main() -> ExitCode {
    if let Err(error) = run().await {
        eprintln!("{error}");
        return ExitCode::FAILURE;
    }
    ExitCode::SUCCESS
}

async fn run() -> Result<(), &'static str> {
    let mail = Mailer::from_env(origin()?, mail_key()?)?;
    let storage = Storage::from_env()?;
    let db = database(2).await?;
    tokio::join!(
        mail.run(&db),
        evidence::run(&db, &storage),
        evidence::run_cleanup(&db, &storage)
    );
    db.close().await;
    Ok(())
}
