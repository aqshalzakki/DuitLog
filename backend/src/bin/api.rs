use std::{env, net::SocketAddr, process::ExitCode};

use duitlog::{auth::Auth, database, http, mail_key, origin, shutdown};

#[tokio::main(worker_threads = 2)]
async fn main() -> ExitCode {
    if let Err(error) = run().await {
        eprintln!("{error}");
        return ExitCode::FAILURE;
    }
    ExitCode::SUCCESS
}

async fn run() -> Result<(), &'static str> {
    let mode = env::args().nth(1);
    if mode.as_deref().is_some_and(|mode| mode != "migrate") {
        return Err("Usage: api [migrate]");
    }
    let db = database(4).await?;
    if mode.as_deref() == Some("migrate") {
        sqlx::migrate!()
            .run(&db)
            .await
            .map_err(|_| "Database migration failed")?;
        return Ok(());
    }
    let app = http::router(
        Auth::new(db.clone(), mail_key()?)
            .await
            .map_err(|_| "Auth initialization failed")?,
        origin()?,
    );
    let address: SocketAddr = env::var("DUIT_API_ADDR")
        .unwrap_or_else(|_| "127.0.0.1:3000".into())
        .parse()
        .map_err(|_| "Invalid DUIT_API_ADDR")?;
    let listener = tokio::net::TcpListener::bind(address)
        .await
        .map_err(|_| "API bind failed")?;
    axum::serve(
        listener,
        app.into_make_service_with_connect_info::<SocketAddr>(),
    )
    .with_graceful_shutdown(shutdown())
    .await
    .map_err(|_| "API stopped unexpectedly")?;
    db.close().await;
    Ok(())
}
