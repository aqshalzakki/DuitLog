use std::{env, time::Duration};

use lettre::{
    AsyncSmtpTransport, AsyncTransport, Message, Tokio1Executor, message::Mailbox,
    transport::smtp::authentication::Credentials,
};
use sqlx::{FromRow, MySqlPool};

use crate::{auth::now, crypto};

const MAX_ATTEMPTS: u32 = 6;

pub struct Mailer {
    sender: Mailbox,
    transport: AsyncSmtpTransport<Tokio1Executor>,
    origin: String,
    key: [u8; 32],
}

#[derive(FromRow)]
struct ClaimRow {
    challenge_id: String,
    attempts: u32,
}

struct Lease {
    challenge_id: String,
    token: String,
    attempts: u32,
}

#[derive(FromRow)]
struct Delivery {
    email: String,
    purpose: String,
}

impl Mailer {
    pub fn from_env(origin: String, key: [u8; 32]) -> Result<Self, &'static str> {
        let sender = env::var("DUIT_MAIL_FROM")
            .map_err(|_| "Set DUIT_MAIL_FROM")?
            .parse()
            .map_err(|_| "Invalid DUIT_MAIL_FROM")?;
        let host = env::var("DUIT_SMTP_HOST").map_err(|_| "Set DUIT_SMTP_HOST")?;
        let local = env::var("DUIT_SMTP_MODE").as_deref() == Ok("local");
        let mut builder = if local {
            if !origin.starts_with("http://localhost") || host != "127.0.0.1" {
                return Err("Local SMTP is limited to loopback development");
            }
            AsyncSmtpTransport::<Tokio1Executor>::builder_dangerous(host)
        } else {
            let username = env::var("DUIT_SMTP_USERNAME").map_err(|_| "Set DUIT_SMTP_USERNAME")?;
            let password = env::var("DUIT_SMTP_PASSWORD").map_err(|_| "Set DUIT_SMTP_PASSWORD")?;
            AsyncSmtpTransport::<Tokio1Executor>::starttls_relay(&host)
                .map_err(|_| "Invalid SMTP relay")?
                .credentials(Credentials::new(username, password))
        };
        let port = env::var("DUIT_SMTP_PORT")
            .map_or(Ok(if local { 1025 } else { 587 }), |port| {
                port.parse().map_err(|_| "Invalid DUIT_SMTP_PORT")
            })?;
        builder = builder.port(port).timeout(Some(Duration::from_secs(15)));
        Ok(Self {
            sender,
            transport: builder.build(),
            origin,
            key,
        })
    }

    pub async fn run(&self, db: &MySqlPool) {
        let mut cleanup = tokio::time::interval(Duration::from_secs(900));
        let mut poll = tokio::time::interval(Duration::from_millis(500));
        poll.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
        let shutdown = crate::shutdown();
        tokio::pin!(shutdown);
        loop {
            tokio::select! {
                _ = &mut shutdown => break,
                _ = cleanup.tick() => {
                    if sqlx::query("DELETE FROM auth_rate_limits WHERE reset_at<=? LIMIT 1000")
                        .bind(now()).execute(db).await.is_err() {
                        eprintln!("Rate-limit cleanup failed");
                    }
                }
                _ = poll.tick() => {
                    if self.deliver_next(db).await.is_err() {
                        eprintln!("Mail job handling failed");
                    }
                }
            }
        }
        let _ = self.transport.shutdown().await;
    }

    async fn deliver_next(&self, db: &MySqlPool) -> Result<(), sqlx::Error> {
        let Some(lease) = claim(db).await? else {
            return Ok(());
        };
        let delivery: Option<Delivery> = sqlx::query_as(
            "SELECT a.email,CAST(c.purpose AS CHAR) AS purpose FROM auth_challenges c
             JOIN accounts a ON a.id=c.owner_id WHERE c.id=? AND c.consumed_at IS NULL AND c.expires_at>?",
        ).bind(&lease.challenge_id).bind(now()).fetch_optional(db).await?;
        let sent = match delivery {
            Some(delivery) => self.send(&lease.challenge_id, delivery).await.is_ok(),
            None => true,
        };
        if !sent {
            eprintln!("Mail delivery deferred");
        }
        let current = now();
        sqlx::query(
            "UPDATE mail_jobs SET completed_at=?,failed_at=?,next_run_at=?,lease_token=NULL,lease_until=NULL
             WHERE challenge_id=? AND lease_token=?",
        ).bind(sent.then_some(current))
            .bind((!sent && lease.attempts >= MAX_ATTEMPTS).then_some(current))
            .bind(current + 30 * 2_i64.pow(lease.attempts.min(MAX_ATTEMPTS)))
            .bind(&lease.challenge_id).bind(&lease.token).execute(db).await?;
        Ok(())
    }

    async fn send(&self, id: &str, delivery: Delivery) -> Result<(), &'static str> {
        let (subject, page) = match delivery.purpose.as_str() {
            "verify" => ("Verifikasi email Duit Log", "/verify-email"),
            "reset" => ("Atur ulang kata sandi Duit Log", "/reset-password"),
            _ => return Err("Invalid mail purpose"),
        };
        let code =
            crypto::mail_code(&self.key, &delivery.purpose, id).map_err(|_| "Mail code failed")?;
        let body = format!(
            "Buka {}{} dan masukkan kode berikut:\n\n{}\n\nAbaikan email ini jika kamu tidak meminta tindakan tersebut.",
            self.origin, page, code
        );
        let domain = self.sender.email.domain();
        let message = Message::builder()
            .from(self.sender.clone())
            .to(delivery
                .email
                .parse()
                .map_err(|_| "Invalid mail recipient")?)
            .message_id(Some(format!("<{id}@{domain}>")))
            .subject(subject)
            .body(body)
            .map_err(|_| "Invalid email message")?;
        tokio::time::timeout(Duration::from_secs(20), self.transport.send(message))
            .await
            .map_err(|_| "Mail delivery timed out")?
            .map_err(|_| "Mail delivery failed")?;
        Ok(())
    }
}

async fn claim(db: &MySqlPool) -> Result<Option<Lease>, sqlx::Error> {
    let mut tx = db.begin().await?;
    let current = now();
    let candidate: Option<ClaimRow> = sqlx::query_as(
        "SELECT challenge_id,attempts FROM mail_jobs WHERE completed_at IS NULL AND failed_at IS NULL
         AND next_run_at<=? AND (lease_until IS NULL OR lease_until<=?)
         ORDER BY next_run_at,challenge_id LIMIT 1 FOR UPDATE SKIP LOCKED",
    ).bind(current).bind(current).fetch_optional(&mut *tx).await?;
    let Some(row) = candidate else {
        tx.rollback().await?;
        return Ok(None);
    };
    if row.attempts >= MAX_ATTEMPTS {
        sqlx::query("UPDATE mail_jobs SET failed_at=?,lease_token=NULL,lease_until=NULL WHERE challenge_id=?")
            .bind(current).bind(row.challenge_id).execute(&mut *tx).await?;
        tx.commit().await?;
        return Ok(None);
    }
    let token =
        crypto::id().map_err(|_| sqlx::Error::Protocol("Lease entropy unavailable".into()))?;
    sqlx::query(
        "UPDATE mail_jobs SET attempts=attempts+1,lease_token=?,lease_until=? WHERE challenge_id=?",
    )
    .bind(&token)
    .bind(current + 90)
    .bind(&row.challenge_id)
    .execute(&mut *tx)
    .await?;
    tx.commit().await?;
    Ok(Some(Lease {
        challenge_id: row.challenge_id,
        token,
        attempts: row.attempts + 1,
    }))
}
