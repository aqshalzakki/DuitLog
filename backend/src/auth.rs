use std::sync::Arc;

use serde::Serialize;
use sqlx::{FromRow, MySql, MySqlPool, Transaction};
use time::{OffsetDateTime, format_description::well_known::Rfc3339};
use tokio::sync::Semaphore;

use crate::crypto;

const ACCESS_SECONDS: i64 = 15 * 60;
const SESSION_SECONDS: i64 = 30 * 24 * 60 * 60;
const HOUR: i64 = 60 * 60;

#[derive(Debug)]
pub enum Error {
    Field(&'static str, &'static str),
    InvalidCode,
    Credentials,
    Unauthorized,
    Forbidden,
    NotFound,
    RateLimited,
    Internal,
}

impl From<sqlx::Error> for Error {
    fn from(error: sqlx::Error) -> Self {
        match &error {
            sqlx::Error::Database(db) => {
                let number = db
                    .try_downcast_ref::<sqlx::mysql::MySqlDatabaseError>()
                    .map(|db| db.number());
                eprintln!("Auth database operation failed mysql_number={number:?}");
            }
            sqlx::Error::ColumnDecode { index, .. } => {
                eprintln!("Auth database column decode failed column={index}")
            }
            _ => eprintln!(
                "Auth database operation failed kind={:?}",
                std::mem::discriminant(&error)
            ),
        }
        Self::Internal
    }
}

pub(crate) fn now() -> i64 {
    OffsetDateTime::now_utc().unix_timestamp()
}

fn date(timestamp: i64) -> Result<String, Error> {
    OffsetDateTime::from_unix_timestamp(timestamp)
        .ok()
        .and_then(|date| date.format(&Rfc3339).ok())
        .ok_or(Error::Internal)
}

pub fn email(raw: &str) -> Result<String, Error> {
    let value = raw.trim().to_ascii_lowercase();
    if value.len() > 254 || !value.is_ascii() || !email_address::EmailAddress::is_valid(&value) {
        return Err(Error::Field("email", "Masukkan alamat email yang valid."));
    }
    Ok(value)
}

pub fn new_password(value: &str) -> Result<(), Error> {
    if !(12..=128).contains(&value.chars().count()) || value.len() > 512 {
        return Err(Error::Field("password", "Gunakan 12 sampai 128 karakter."));
    }
    Ok(())
}

fn name(value: &str, field: &'static str) -> Result<String, Error> {
    let value = value.trim();
    if value.is_empty() || value.chars().count() > 100 || value.chars().any(char::is_control) {
        return Err(Error::Field(field, "Gunakan 1 sampai 100 karakter."));
    }
    Ok(value.to_owned())
}

#[derive(Clone)]
pub struct Auth {
    pub db: MySqlPool,
    mail_key: [u8; 32],
    hash_slots: Arc<Semaphore>,
    dummy_hash: Arc<str>,
}

#[derive(FromRow)]
struct Account {
    id: String,
    password_hash: String,
}

#[derive(FromRow)]
pub struct Principal {
    pub owner_id: String,
    pub session_id: String,
    pub verified_at: Option<i64>,
    pub name: String,
    pub email: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Profile<'a> {
    id: &'a str,
    name: &'a str,
    email: &'a str,
    email_verified: bool,
}

impl Principal {
    pub fn profile(&self) -> Profile<'_> {
        Profile {
            id: &self.owner_id,
            name: &self.name,
            email: &self.email,
            email_verified: self.verified_at.is_some(),
        }
    }
}

pub struct Cookies {
    pub access: String,
    pub refresh: String,
    pub access_age: i64,
    pub refresh_age: i64,
}

impl Cookies {
    fn issue(seconds: i64) -> Result<Self, Error> {
        Ok(Self {
            access: crypto::token()?,
            refresh: crypto::token()?,
            access_age: seconds.min(ACCESS_SECONDS),
            refresh_age: seconds,
        })
    }
}

#[derive(FromRow)]
struct DeviceRow {
    id: String,
    label: String,
    created_at: i64,
    last_seen_at: i64,
    expires_at: i64,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Device {
    id: String,
    label: String,
    created_at: String,
    last_seen_at: String,
    expires_at: String,
    current: bool,
}

#[derive(FromRow)]
struct RefreshRow {
    session_id: String,
    owner_id: String,
    used_at: Option<i64>,
    expires_at: i64,
    revoked_at: Option<i64>,
}

#[derive(FromRow)]
struct Challenge {
    id: String,
    owner_id: String,
    expires_at: i64,
    consumed_at: Option<i64>,
}

impl Auth {
    pub async fn new(db: MySqlPool, mail_key: [u8; 32]) -> Result<Self, Error> {
        let dummy_hash = tokio::task::spawn_blocking(|| crypto::password_hash(&crypto::token()?))
            .await
            .map_err(|_| Error::Internal)??;
        Ok(Self {
            db,
            mail_key,
            hash_slots: Arc::new(Semaphore::new(2)),
            dummy_hash: dummy_hash.into(),
        })
    }

    async fn password_work<T: Send + 'static>(
        &self,
        work: impl FnOnce() -> Result<T, Error> + Send + 'static,
    ) -> Result<T, Error> {
        let slot = self
            .hash_slots
            .clone()
            .try_acquire_owned()
            .map_err(|_| Error::RateLimited)?;
        tokio::task::spawn_blocking(move || {
            let _slot = slot;
            work()
        })
        .await
        .map_err(|_| Error::Internal)?
    }

    pub async fn limit(
        &self,
        action: &str,
        subject: &str,
        maximum: u32,
        window: i64,
    ) -> Result<(), Error> {
        let key = crypto::digest(&format!("{action}:{subject}"));
        let current = now();
        let mut tx = self.db.begin().await?;
        sqlx::query(
            "INSERT INTO auth_rate_limits (rate_key,hits,reset_at) VALUES (?,1,?)
            ON DUPLICATE KEY UPDATE hits=IF(reset_at<=?,1,LEAST(hits,65535)+1),
            reset_at=IF(reset_at<=?, ?, reset_at)",
        )
        .bind(&key)
        .bind(current + window)
        .bind(current)
        .bind(current)
        .bind(current + window)
        .execute(&mut *tx)
        .await?;
        let hits: u32 = sqlx::query_scalar("SELECT hits FROM auth_rate_limits WHERE rate_key=?")
            .bind(key)
            .fetch_one(&mut *tx)
            .await?;
        tx.commit().await?;
        if hits > maximum {
            return Err(Error::RateLimited);
        }
        Ok(())
    }

    pub async fn register(
        &self,
        label: &str,
        address: &str,
        password: String,
    ) -> Result<(), Error> {
        let label = name(label, "name")?;
        new_password(&password)?;
        let hash = self
            .password_work(move || crypto::password_hash(&password))
            .await?;
        let owner = crypto::id()?;
        let mut tx = self.db.begin().await?;
        let result = sqlx::query(
            "INSERT INTO accounts (id,email,name,password_hash,created_at) VALUES (?,?,?,?,?)",
        )
        .bind(&owner)
        .bind(address)
        .bind(label)
        .bind(hash)
        .bind(now())
        .execute(&mut *tx)
        .await;
        if let Err(error) = result {
            if error
                .as_database_error()
                .is_some_and(|error| error.is_unique_violation())
            {
                tx.rollback().await?;
                return Ok(());
            }
            return Err(error.into());
        }
        self.issue_challenge(&mut tx, &owner, "verify", 24 * HOUR)
            .await?;
        tx.commit().await?;
        Ok(())
    }

    pub async fn login(
        &self,
        address: &str,
        password: String,
        device: Option<&str>,
    ) -> Result<Cookies, Error> {
        let label = name(device.unwrap_or("Browser"), "deviceName")?;
        if password.is_empty() || password.len() > 512 {
            return Err(Error::Credentials);
        }
        let account: Option<Account> =
            sqlx::query_as("SELECT id,password_hash FROM accounts WHERE email=?")
                .bind(address)
                .fetch_optional(&self.db)
                .await?;
        let hash = account
            .as_ref()
            .map(|account| account.password_hash.as_str())
            .unwrap_or(&self.dummy_hash)
            .to_owned();
        if !self
            .password_work(move || crypto::password_matches(&password, &hash))
            .await?
        {
            return Err(Error::Credentials);
        }
        let account = account.ok_or(Error::Credentials)?;
        let mut tx = self.db.begin().await?;
        let current_hash: String =
            sqlx::query_scalar("SELECT password_hash FROM accounts WHERE id=? FOR UPDATE")
                .bind(&account.id)
                .fetch_one(&mut *tx)
                .await?;
        if current_hash != account.password_hash {
            return Err(Error::Credentials);
        }
        let current = now();
        let session = crypto::id()?;
        let cookies = Cookies::issue(SESSION_SECONDS)?;
        sqlx::query(
            "INSERT INTO device_sessions (id,owner_id,label,access_digest,access_expires_at,created_at,last_seen_at,expires_at)
             VALUES (?,?,?,?,?,?,?,?)",
        ).bind(&session).bind(account.id).bind(label).bind(crypto::digest(&cookies.access))
            .bind(current + cookies.access_age).bind(current).bind(current)
            .bind(current + SESSION_SECONDS).execute(&mut *tx).await?;
        insert_refresh(&mut tx, &session, &cookies.refresh).await?;
        tx.commit().await?;
        Ok(cookies)
    }

    pub async fn principal(&self, access: &str) -> Result<Principal, Error> {
        if !crypto::valid_token(access) {
            return Err(Error::Unauthorized);
        }
        let current = now();
        sqlx::query_as(
            "SELECT s.owner_id,s.id AS session_id,a.verified_at,a.name,a.email FROM device_sessions s
             JOIN accounts a ON a.id=s.owner_id WHERE s.access_digest=?
             AND s.revoked_at IS NULL AND s.expires_at>? AND s.access_expires_at>?",
        ).bind(crypto::digest(access)).bind(current).bind(current)
            .fetch_optional(&self.db).await?.ok_or(Error::Unauthorized)
    }

    pub async fn refresh(&self, raw: &str) -> Result<Cookies, Error> {
        if !crypto::valid_token(raw) {
            return Err(Error::Unauthorized);
        }
        let digest = crypto::digest(raw);
        let owner: String = sqlx::query_scalar(
            "SELECT s.owner_id FROM refresh_tokens r JOIN device_sessions s ON s.id=r.session_id WHERE r.digest=?",
        ).bind(&digest).fetch_optional(&self.db).await?.ok_or(Error::Unauthorized)?;
        let mut tx = self.db.begin().await?;
        lock_account(&mut tx, &owner).await?;
        let row: RefreshRow = sqlx::query_as(
            "SELECT r.session_id,r.used_at,s.owner_id,s.expires_at,s.revoked_at
             FROM refresh_tokens r JOIN device_sessions s ON s.id=r.session_id WHERE r.digest=? FOR UPDATE",
        ).bind(&digest).fetch_optional(&mut *tx).await?.ok_or(Error::Unauthorized)?;
        let current = now();
        if row.revoked_at.is_some() || row.expires_at <= current {
            return Err(Error::Unauthorized);
        }
        if row.used_at.is_some() {
            revoke(&mut tx, &row.owner_id, Some(&row.session_id)).await?;
            tx.commit().await?;
            return Err(Error::Unauthorized);
        }
        let cookies = Cookies::issue(row.expires_at - current)?;
        sqlx::query("UPDATE refresh_tokens SET used_at=? WHERE digest=?")
            .bind(current)
            .bind(digest)
            .execute(&mut *tx)
            .await?;
        sqlx::query("UPDATE device_sessions SET access_digest=?,access_expires_at=?,last_seen_at=? WHERE id=? AND owner_id=?")
            .bind(crypto::digest(&cookies.access)).bind(current + cookies.access_age).bind(current)
            .bind(&row.session_id).bind(&row.owner_id).execute(&mut *tx).await?;
        insert_refresh(&mut tx, &row.session_id, &cookies.refresh).await?;
        tx.commit().await?;
        Ok(cookies)
    }

    pub async fn logout(&self, refresh: &str) -> Result<(), Error> {
        if crypto::valid_token(refresh) {
            sqlx::query(
                "UPDATE device_sessions s JOIN refresh_tokens r ON r.session_id=s.id
                 SET s.revoked_at=? WHERE r.digest=? AND s.revoked_at IS NULL",
            )
            .bind(now())
            .bind(crypto::digest(refresh))
            .execute(&self.db)
            .await?;
        }
        Ok(())
    }

    pub async fn revoke_device(&self, principal: &Principal, id: &str) -> Result<(), Error> {
        let mut tx = self.db.begin().await?;
        lock_account(&mut tx, &principal.owner_id).await?;
        if revoke(&mut tx, &principal.owner_id, Some(id)).await? == 0 {
            return Err(Error::NotFound);
        }
        tx.commit().await?;
        Ok(())
    }

    pub async fn logout_all(&self, principal: &Principal) -> Result<(), Error> {
        let mut tx = self.db.begin().await?;
        lock_account(&mut tx, &principal.owner_id).await?;
        revoke(&mut tx, &principal.owner_id, None).await?;
        tx.commit().await?;
        Ok(())
    }

    pub async fn devices(&self, principal: &Principal) -> Result<Vec<Device>, Error> {
        let rows: Vec<DeviceRow> = sqlx::query_as(
            "SELECT id,label,created_at,last_seen_at,expires_at FROM device_sessions
             WHERE owner_id=? AND revoked_at IS NULL AND expires_at>? ORDER BY created_at DESC,id",
        )
        .bind(&principal.owner_id)
        .bind(now())
        .fetch_all(&self.db)
        .await?;
        rows.into_iter()
            .map(|row| {
                Ok(Device {
                    current: row.id == principal.session_id,
                    id: row.id,
                    label: row.label,
                    created_at: date(row.created_at)?,
                    last_seen_at: date(row.last_seen_at)?,
                    expires_at: date(row.expires_at)?,
                })
            })
            .collect()
    }

    async fn issue_challenge(
        &self,
        tx: &mut Transaction<'_, MySql>,
        owner: &str,
        purpose: &str,
        lifetime: i64,
    ) -> Result<(), Error> {
        let id = crypto::id()?;
        let token = crypto::mail_code(&self.mail_key, purpose, &id)?;
        sqlx::query("INSERT INTO auth_challenges (id,owner_id,purpose,digest,expires_at) VALUES (?,?,?,?,?)")
            .bind(&id).bind(owner).bind(purpose).bind(crypto::digest(&token)).bind(now() + lifetime)
            .execute(&mut **tx).await?;
        sqlx::query("INSERT INTO mail_jobs (challenge_id,next_run_at) VALUES (?,?)")
            .bind(id)
            .bind(now())
            .execute(&mut **tx)
            .await?;
        Ok(())
    }

    pub async fn resend(&self, principal: &Principal) -> Result<(), Error> {
        let mut tx = self.db.begin().await?;
        let verified: Option<i64> =
            sqlx::query_scalar("SELECT verified_at FROM accounts WHERE id=? FOR UPDATE")
                .bind(&principal.owner_id)
                .fetch_one(&mut *tx)
                .await?;
        if verified.is_none() {
            self.issue_challenge(&mut tx, &principal.owner_id, "verify", 24 * HOUR)
                .await?;
        }
        tx.commit().await?;
        Ok(())
    }

    pub async fn forgot_password(&self, address: &str) -> Result<(), Error> {
        let mut tx = self.db.begin().await?;
        let owner: Option<String> =
            sqlx::query_scalar("SELECT id FROM accounts WHERE email=? FOR UPDATE")
                .bind(address)
                .fetch_optional(&mut *tx)
                .await?;
        if let Some(owner) = owner {
            self.issue_challenge(&mut tx, &owner, "reset", 30 * 60)
                .await?;
        }
        tx.commit().await?;
        Ok(())
    }

    async fn select_challenge(&self, token: &str, purpose: &str) -> Result<Challenge, Error> {
        if !crypto::valid_token(token) {
            return Err(Error::InvalidCode);
        }
        let row: Challenge = sqlx::query_as(
            "SELECT id,owner_id,expires_at,consumed_at FROM auth_challenges WHERE digest=? AND purpose=?",
        ).bind(crypto::digest(token)).bind(purpose).fetch_optional(&self.db).await?
            .ok_or(Error::InvalidCode)?;
        if row.expires_at <= now() || row.consumed_at.is_some() {
            return Err(Error::InvalidCode);
        }
        Ok(row)
    }

    pub async fn verify(&self, principal: &Principal, token: &str) -> Result<(), Error> {
        let row = self.select_challenge(token, "verify").await?;
        if row.owner_id != principal.owner_id {
            return Err(Error::InvalidCode);
        }
        let mut tx = self.db.begin().await?;
        lock_account(&mut tx, &row.owner_id).await?;
        consume(&mut tx, &row, "verify").await?;
        sqlx::query("UPDATE accounts SET verified_at=COALESCE(verified_at,?) WHERE id=?")
            .bind(now())
            .bind(row.owner_id)
            .execute(&mut *tx)
            .await?;
        tx.commit().await?;
        Ok(())
    }

    pub async fn reset_password(&self, token: &str, password: String) -> Result<(), Error> {
        new_password(&password)?;
        let row = self.select_challenge(token, "reset").await?;
        let hash = self
            .password_work(move || crypto::password_hash(&password))
            .await?;
        let mut tx = self.db.begin().await?;
        lock_account(&mut tx, &row.owner_id).await?;
        consume(&mut tx, &row, "reset").await?;
        sqlx::query("UPDATE accounts SET password_hash=? WHERE id=?")
            .bind(hash)
            .bind(&row.owner_id)
            .execute(&mut *tx)
            .await?;
        revoke(&mut tx, &row.owner_id, None).await?;
        tx.commit().await?;
        Ok(())
    }
}

async fn lock_account(tx: &mut Transaction<'_, MySql>, owner: &str) -> Result<(), Error> {
    sqlx::query_scalar::<_, String>("SELECT id FROM accounts WHERE id=? FOR UPDATE")
        .bind(owner)
        .fetch_one(&mut **tx)
        .await?;
    Ok(())
}

async fn insert_refresh(
    tx: &mut Transaction<'_, MySql>,
    session: &str,
    raw: &str,
) -> Result<(), Error> {
    sqlx::query("INSERT INTO refresh_tokens (digest,session_id) VALUES (?,?)")
        .bind(crypto::digest(raw))
        .bind(session)
        .execute(&mut **tx)
        .await?;
    Ok(())
}

async fn revoke(
    tx: &mut Transaction<'_, MySql>,
    owner: &str,
    session: Option<&str>,
) -> Result<u64, Error> {
    let current = now();
    let result = if let Some(session) = session {
        sqlx::query("UPDATE device_sessions SET revoked_at=? WHERE owner_id=? AND id=? AND revoked_at IS NULL AND expires_at>?")
            .bind(current).bind(owner).bind(session).bind(current).execute(&mut **tx).await?
    } else {
        sqlx::query(
            "UPDATE device_sessions SET revoked_at=? WHERE owner_id=? AND revoked_at IS NULL",
        )
        .bind(current)
        .bind(owner)
        .execute(&mut **tx)
        .await?
    };
    Ok(result.rows_affected())
}

async fn consume(
    tx: &mut Transaction<'_, MySql>,
    row: &Challenge,
    purpose: &str,
) -> Result<(), Error> {
    let current = now();
    let result = sqlx::query(
        "UPDATE auth_challenges SET consumed_at=? WHERE id=? AND owner_id=? AND purpose=? AND consumed_at IS NULL AND expires_at>?",
    ).bind(current).bind(&row.id).bind(&row.owner_id).bind(purpose).bind(current)
        .execute(&mut **tx).await?;
    if result.rows_affected() != 1 {
        return Err(Error::InvalidCode);
    }
    sqlx::query("UPDATE auth_challenges SET consumed_at=? WHERE owner_id=? AND purpose=? AND consumed_at IS NULL")
        .bind(current).bind(&row.owner_id).bind(purpose).execute(&mut **tx).await?;
    Ok(())
}
