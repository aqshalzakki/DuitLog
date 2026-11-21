pub mod auth;
mod crypto;
pub mod evidence;
pub mod financial;
pub mod http;
pub mod mail;
pub mod storage;

use base64::{Engine, engine::general_purpose::URL_SAFE_NO_PAD};
use sqlx::mysql::{MySqlPool, MySqlPoolOptions};
use std::{env, time::Duration};

pub async fn database(max_connections: u32) -> Result<MySqlPool, &'static str> {
    let url = env::var("DATABASE_URL").map_err(|_| "Set DATABASE_URL")?;
    MySqlPoolOptions::new()
        .max_connections(max_connections)
        .acquire_timeout(Duration::from_secs(5))
        .connect(&url)
        .await
        .map_err(|_| "Database connection failed")
}

pub fn mail_key() -> Result<[u8; 32], &'static str> {
    URL_SAFE_NO_PAD
        .decode(env::var("DUIT_MAIL_KEY").map_err(|_| "Set DUIT_MAIL_KEY")?)
        .map_err(|_| "Invalid DUIT_MAIL_KEY")?
        .try_into()
        .map_err(|_| "DUIT_MAIL_KEY must encode 32 random bytes")
}

pub fn origin() -> Result<String, &'static str> {
    let origin = env::var("DUIT_APP_ORIGIN").map_err(|_| "Set DUIT_APP_ORIGIN")?;
    let parsed = url::Url::parse(&origin).map_err(|_| "Invalid DUIT_APP_ORIGIN")?;
    if origin != parsed.origin().ascii_serialization()
        || (parsed.scheme() != "https"
            && !(parsed.scheme() == "http" && parsed.host_str() == Some("localhost")))
    {
        return Err("DUIT_APP_ORIGIN must be a canonical HTTPS origin or HTTP localhost");
    }
    Ok(origin)
}

pub async fn shutdown() {
    let ctrl_c = tokio::signal::ctrl_c();
    #[cfg(unix)]
    {
        use tokio::signal::unix::{SignalKind, signal};
        if let Ok(mut terminate) = signal(SignalKind::terminate()) {
            tokio::select! { _ = ctrl_c => {}, _ = terminate.recv() => {} }
            return;
        }
    }
    let _ = ctrl_c.await;
}
