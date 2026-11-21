use std::process::ExitCode;

use duitlog::{database, mail::Mailer, mail_key, origin};

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
    let db = database(1).await?;
    mail.run(&db).await;
    db.close().await;
    Ok(())
}
