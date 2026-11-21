//! Transaction evidence (BR-FILE-01..06, Tech Spec §10). One optional file per activity, stored in
//! private object storage *after* the financial commit and never inside a financial transaction.
//! A stored file stays `QUARANTINED` until the worker re-reads and re-checks it; only `AVAILABLE`
//! may be downloaded. Removal and replacement keep the object (no permanent deletion in MVP).
use std::time::Duration;

use serde::Serialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use sqlx::{FromRow, MySqlPool};

use crate::{
    crypto,
    financial::{
        Failure,
        model::{Code, Moment, Rejection},
        store,
    },
    storage::{Storage, StorageError},
};

pub const MAX_BYTES: usize = 10 * 1024 * 1024;
const MAX_NAME: usize = 180;
const WORKER_ACTOR: &str = "system:evidence-check";

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum FileType {
    Jpeg,
    Png,
    Webp,
    Pdf,
}

impl FileType {
    pub fn mime(self) -> &'static str {
        match self {
            Self::Jpeg => "image/jpeg",
            Self::Png => "image/png",
            Self::Webp => "image/webp",
            Self::Pdf => "application/pdf",
        }
    }

    fn from_mime(mime: &str) -> Option<Self> {
        [Self::Jpeg, Self::Png, Self::Webp, Self::Pdf]
            .into_iter()
            .find(|kind| kind.mime() == mime)
    }

    fn matches_name(self, name: &str) -> bool {
        let extension = name
            .rsplit_once('.')
            .map(|(_, ext)| ext.to_ascii_lowercase());
        matches!(
            (self, extension.as_deref()),
            (Self::Jpeg, Some("jpg" | "jpeg"))
                | (Self::Png, Some("png"))
                | (Self::Webp, Some("webp"))
                | (Self::Pdf, Some("pdf"))
        )
    }
}

/// Type from the file signature (magic bytes), never from the client's claim.
pub fn sniff(bytes: &[u8]) -> Option<FileType> {
    if bytes.starts_with(&[0xFF, 0xD8, 0xFF]) {
        Some(FileType::Jpeg)
    } else if bytes.starts_with(b"\x89PNG\r\n\x1a\n") {
        Some(FileType::Png)
    } else if bytes.len() >= 12 && &bytes[..4] == b"RIFF" && &bytes[8..12] == b"WEBP" {
        Some(FileType::Webp)
    } else if bytes.starts_with(b"%PDF-") {
        Some(FileType::Pdf)
    } else {
        None
    }
}

/// Structural check beyond the signature: a truncated or padded-out file is refused.
/// shortcut: no pixel decode and no malware scan (Tech Spec §10.1 "bila tersedia"); add a
/// sandboxed decoder/scanner in the worker when one is available on the VPS.
pub fn well_formed(kind: FileType, bytes: &[u8]) -> bool {
    match kind {
        FileType::Jpeg => {
            let end = bytes.iter().rposition(|byte| *byte != 0).unwrap_or(0);
            bytes.len() > 4 && end >= 1 && bytes[end - 1] == 0xFF && bytes[end] == 0xD9
        }
        FileType::Png => png_chunks(bytes),
        FileType::Webp => {
            let declared = u32::from_le_bytes([bytes[4], bytes[5], bytes[6], bytes[7]]) as usize;
            let chunk = bytes.get(12..16);
            declared.checked_add(8) == Some(bytes.len())
                && matches!(chunk, Some(b"VP8 " | b"VP8L" | b"VP8X"))
        }
        FileType::Pdf => {
            let tail = &bytes[bytes.len().saturating_sub(1024)..];
            bytes.len() > 16 && tail.windows(5).any(|window| window == b"%%EOF")
        }
    }
}

/// PNG: IHDR first, every chunk length inside the file, IEND last.
fn png_chunks(bytes: &[u8]) -> bool {
    let mut at = 8;
    let mut first = true;
    while let Some(header) = bytes.get(at..at + 8) {
        let length = u32::from_be_bytes([header[0], header[1], header[2], header[3]]) as usize;
        let name = &header[4..8];
        if first && name != b"IHDR" {
            return false;
        }
        first = false;
        let Some(next) = at.checked_add(12).and_then(|n| n.checked_add(length)) else {
            return false;
        };
        if next > bytes.len() {
            return false;
        }
        if name == b"IEND" {
            return next == bytes.len();
        }
        at = next;
    }
    false
}

/// Why an upload was refused; sent as `conflictDetails.reason` so the UI can say what to fix.
#[derive(Clone, Copy, Debug, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Refusal {
    Empty,
    TooLarge,
    Type,
    Name,
    Structure,
}

pub fn refused(reason: Refusal) -> Failure {
    Rejection {
        code: Code::EvidenceRejected,
        conflict_details: Some(json!({ "reason": reason })),
    }
    .into()
}

/// Validates an upload before anything is stored. `claimed` is the browser's MIME type (may be empty).
pub fn validate(name: &str, claimed: &str, bytes: &[u8]) -> Result<FileType, Refusal> {
    if bytes.is_empty() {
        return Err(Refusal::Empty);
    }
    if bytes.len() > MAX_BYTES {
        return Err(Refusal::TooLarge);
    }
    let kind = sniff(bytes).ok_or(Refusal::Type)?;
    if !claimed.is_empty() && FileType::from_mime(claimed) != Some(kind) {
        return Err(Refusal::Type);
    }
    if !kind.matches_name(name) {
        return Err(Refusal::Name);
    }
    if !well_formed(kind, bytes) {
        return Err(Refusal::Structure);
    }
    Ok(kind)
}

/// Display name: trimmed, no control characters, at most 180 characters.
pub fn clean_name(raw: &str) -> Option<String> {
    let name = raw.trim();
    let ok = !name.is_empty()
        && name.chars().count() <= MAX_NAME
        && !name
            .chars()
            .any(|c| c.is_control() || c == '/' || c == '\\');
    ok.then(|| name.to_owned())
}

/// Object key per owner and upload: a retry of the same upload overwrites the same object, and two
/// owners can never collide even if a client reuses another account's upload id.
pub fn object_key(owner: &str, upload: &str) -> String {
    let digest = Sha256::digest(format!("{owner}:{upload}").as_bytes());
    let hex: String = digest.iter().map(|byte| format!("{byte:02x}")).collect();
    format!("ev/{hex}")
}

#[derive(FromRow, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct View {
    pub id: String,
    pub status: String,
    pub file_name: String,
    pub content_type: String,
    pub size: u32,
    #[serde(skip)]
    pub object_key: String,
    #[serde(skip)]
    pub sha256: Vec<u8>,
    #[serde(skip)]
    pub activity_id: String,
    #[serde(serialize_with = "as_moment")]
    pub created_at: i64,
}

fn as_moment<S: serde::Serializer>(micros: &i64, serializer: S) -> Result<S::Ok, S::Error> {
    Moment(*micros).serialize(serializer)
}

/// sqlx only takes literal SQL; `concat!` keeps the shared column list a literal.
macro_rules! view {
    ($where:literal) => {
        concat!(
            "SELECT id,CAST(status AS CHAR) AS status,file_name,content_type,size,object_key,sha256,",
            "activity_id,created_at FROM evidence ",
            $where
        )
    };
}

/// The activity's current evidence: the active one, else the latest refused one (so the user sees
/// why and can replace it). Removed evidence is not shown.
pub async fn current(db: &MySqlPool, owner: &str, activity: &str) -> Result<Option<View>, Failure> {
    Ok(sqlx::query_as(view!(
        "WHERE owner_id=? AND activity_id=? AND status<>'REMOVED'
         ORDER BY status IN ('QUARANTINED','AVAILABLE') DESC, created_at DESC, id LIMIT 1"
    ))
    .bind(owner)
    .bind(activity)
    .fetch_optional(db)
    .await?)
}

pub async fn by_upload(db: &MySqlPool, owner: &str, upload: &str) -> Result<Option<View>, Failure> {
    Ok(sqlx::query_as(view!("WHERE owner_id=? AND id=?"))
        .bind(owner)
        .bind(upload)
        .fetch_optional(db)
        .await?)
}

/// The activity exists for this owner (deleted or not). Another owner's activity reads as not found.
pub async fn owned(db: &MySqlPool, owner: &str, activity: &str) -> Result<(), Failure> {
    let found: Option<i32> =
        sqlx::query_scalar("SELECT 1 FROM activities WHERE owner_id=? AND id=?")
            .bind(owner)
            .bind(activity)
            .fetch_optional(db)
            .await?;
    found.map(|_| ()).ok_or(Code::NotFound.into())
}

/// Confirmed, not deleted, and owned: evidence may be attached. Not-owned reads as not found.
pub async fn attachable(db: &MySqlPool, owner: &str, activity: &str) -> Result<(), Failure> {
    let deleted: Option<bool> =
        sqlx::query_scalar("SELECT deleted FROM activities WHERE owner_id=? AND id=?")
            .bind(owner)
            .bind(activity)
            .fetch_optional(db)
            .await?;
    match deleted {
        None => Err(Code::NotFound.into()),
        Some(true) => Err(Code::InvalidActivityState.into()),
        Some(false) => Ok(()),
    }
}

pub struct Stored {
    pub upload: String,
    pub activity: String,
    pub key: String,
    pub name: String,
    pub kind: FileType,
    pub size: u32,
    pub sha256: Vec<u8>,
}

/// Records an object that is already in storage. Runs after the upload, in a short transaction of its
/// own: the activity row is locked so a concurrent delete or a second upload cannot interleave, the
/// previous active evidence becomes REMOVED, and the audit entry commits with it.
pub async fn record(db: &MySqlPool, owner: &str, file: Stored) -> Result<(), Failure> {
    let mut tx = db.begin().await?;
    let deleted: Option<bool> =
        sqlx::query_scalar("SELECT deleted FROM activities WHERE owner_id=? AND id=? FOR UPDATE")
            .bind(owner)
            .bind(&file.activity)
            .fetch_optional(&mut *tx)
            .await?;
    match deleted {
        None => return Err(Code::NotFound.into()),
        Some(true) => return Err(Code::InvalidActivityState.into()),
        Some(false) => {}
    }
    let at = Moment::now();
    let replaced: Option<String> = sqlx::query_scalar(
        "SELECT id FROM evidence WHERE owner_id=? AND active_activity=? FOR UPDATE",
    )
    .bind(owner)
    .bind(&file.activity)
    .fetch_optional(&mut *tx)
    .await?;
    // The new file supersedes the active one and any earlier refused one still shown to the user.
    sqlx::query(
        "UPDATE evidence SET status='REMOVED',removed_at=?,lease_token=NULL
         WHERE owner_id=? AND activity_id=? AND status<>'REMOVED'",
    )
    .bind(at.0)
    .bind(owner)
    .bind(&file.activity)
    .execute(&mut *tx)
    .await?;
    sqlx::query(
        "INSERT INTO evidence (owner_id,id,activity_id,object_key,file_name,content_type,size,sha256,status,
         created_at,next_run_at) VALUES (?,?,?,?,?,?,?,?,'QUARANTINED',?,?)",
    )
    .bind(owner)
    .bind(&file.upload)
    .bind(&file.activity)
    .bind(&file.key)
    .bind(&file.name)
    .bind(file.kind.mime())
    .bind(file.size)
    .bind(&file.sha256)
    .bind(at.0)
    .bind(at.0)
    .execute(&mut *tx)
    .await?;
    let details = json!({
        "resourceId": file.activity, "evidenceId": file.upload, "fileName": file.name,
        "contentType": file.kind.mime(), "size": file.size, "replaced": replaced,
    });
    store::audit(
        &mut tx,
        owner,
        owner,
        "EVIDENCE_ATTACHED",
        at,
        None,
        details,
    )
    .await?;
    tx.commit().await.map_err(|_| Failure::Unknown)?;
    Ok(())
}

/// Detaches the active evidence (it stays in storage and in the audit trail).
pub async fn remove(db: &MySqlPool, owner: &str, activity: &str) -> Result<(), Failure> {
    let mut tx = db.begin().await?;
    let found: Option<(String, String)> = sqlx::query_as(
        "SELECT e.id,e.file_name FROM activities a JOIN evidence e
         ON e.owner_id=a.owner_id AND e.active_activity=a.id
         WHERE a.owner_id=? AND a.id=? AND a.deleted=FALSE FOR UPDATE",
    )
    .bind(owner)
    .bind(activity)
    .fetch_optional(&mut *tx)
    .await?;
    let Some((id, name)) = found else {
        return Err(Code::NotFound.into());
    };
    let at = Moment::now();
    sqlx::query("UPDATE evidence SET status='REMOVED',removed_at=?,lease_token=NULL WHERE owner_id=? AND id=?")
        .bind(at.0)
        .bind(owner)
        .bind(&id)
        .execute(&mut *tx)
        .await?;
    let details = json!({ "resourceId": activity, "evidenceId": id, "fileName": name });
    store::audit(&mut tx, owner, owner, "EVIDENCE_REMOVED", at, None, details).await?;
    tx.commit().await.map_err(|_| Failure::Unknown)?;
    Ok(())
}

/// Bytes of AVAILABLE evidence, checked against the hash recorded at upload.
pub async fn content(
    db: &MySqlPool,
    storage: &Storage,
    owner: &str,
    activity: &str,
) -> Result<(View, Vec<u8>), Failure> {
    let view = current(db, owner, activity)
        .await?
        .filter(|view| view.status == "AVAILABLE")
        .ok_or(Code::NotFound)?;
    let bytes = storage
        .get(&view.object_key)
        .await
        .map_err(|error| match error {
            StorageError::Unavailable => Failure::Temporary,
            StorageError::Missing => Failure::Internal,
        })?;
    if Sha256::digest(&bytes).as_slice() != view.sha256.as_slice() {
        eprintln!("Evidence content mismatch evidence_id={}", view.id);
        return Err(Failure::Internal);
    }
    Ok((view, bytes))
}

#[derive(FromRow)]
struct Claim {
    owner_id: String,
    id: String,
    attempts: u32,
}

/// Worker loop: verify quarantined evidence until shutdown.
pub async fn run(db: &MySqlPool, storage: &Storage) {
    let mut poll = tokio::time::interval(Duration::from_millis(500));
    poll.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
    let shutdown = crate::shutdown();
    tokio::pin!(shutdown);
    loop {
        tokio::select! {
            _ = &mut shutdown => break,
            _ = poll.tick() => {
                if verify_next(db, storage).await.is_err() {
                    eprintln!("Evidence check failed");
                }
            }
        }
    }
}

/// At-least-once: a crash after the storage read only repeats the read. The lease token fences the
/// final update, and `status='QUARANTINED'` keeps a removal made meanwhile from being undone.
async fn verify_next(db: &MySqlPool, storage: &Storage) -> Result<(), Failure> {
    let micros = Moment::now().0;
    let mut tx = db.begin().await?;
    let claim: Option<Claim> = sqlx::query_as(
        "SELECT owner_id,id,attempts FROM evidence WHERE status='QUARANTINED' AND next_run_at<=?
         AND (lease_until IS NULL OR lease_until<=?) ORDER BY next_run_at,id LIMIT 1 FOR UPDATE SKIP LOCKED",
    )
    .bind(micros)
    .bind(micros)
    .fetch_optional(&mut *tx)
    .await?;
    let Some(claim) = claim else {
        tx.rollback().await?;
        return Ok(());
    };
    let token = crypto::id().map_err(|_| Failure::Internal)?;
    sqlx::query("UPDATE evidence SET attempts=attempts+1,lease_token=?,lease_until=? WHERE owner_id=? AND id=?")
        .bind(&token)
        .bind(micros + 120_000_000)
        .bind(&claim.owner_id)
        .bind(&claim.id)
        .execute(&mut *tx)
        .await?;
    tx.commit().await?;

    let Some(view) = by_upload(db, &claim.owner_id, &claim.id).await? else {
        return Ok(());
    };
    let verdict = match storage.get(&view.object_key).await {
        Ok(bytes) => Some(check_stored(&view, &bytes)),
        Err(StorageError::Missing) => Some(Err("MISSING")),
        Err(StorageError::Unavailable) => None, // try again later; never refuse because storage is down
    };
    let now = Moment::now();
    let mut tx = db.begin().await?;
    let Some(verdict) = verdict else {
        let backoff = 5_000_000_i64 * 2_i64.pow(claim.attempts.min(10));
        sqlx::query(
            "UPDATE evidence SET lease_token=NULL,lease_until=NULL,next_run_at=?
                     WHERE owner_id=? AND id=? AND lease_token=?",
        )
        .bind(now.0 + backoff.min(3_600_000_000))
        .bind(&claim.owner_id)
        .bind(&claim.id)
        .bind(&token)
        .execute(&mut *tx)
        .await?;
        tx.commit().await?;
        return Ok(());
    };
    let (status, action, details): (&str, &str, Value) = match verdict {
        Ok(()) => ("AVAILABLE", "EVIDENCE_VERIFIED", json!({})),
        Err(reason) => ("REJECTED", "EVIDENCE_REJECTED", json!({ "reason": reason })),
    };
    let updated = sqlx::query(
        "UPDATE evidence SET status=?,checked_at=?,lease_token=NULL,lease_until=NULL
         WHERE owner_id=? AND id=? AND lease_token=? AND status='QUARANTINED'",
    )
    .bind(status)
    .bind(now.0)
    .bind(&claim.owner_id)
    .bind(&claim.id)
    .bind(&token)
    .execute(&mut *tx)
    .await?
    .rows_affected();
    if updated == 1 {
        let mut details = details;
        details["resourceId"] = json!(view.activity_id);
        details["evidenceId"] = json!(view.id);
        details["fileName"] = json!(view.file_name);
        store::audit(
            &mut tx,
            &claim.owner_id,
            WORKER_ACTOR,
            action,
            now,
            None,
            details,
        )
        .await?;
    }
    tx.commit().await?;
    Ok(())
}

/// The stored object must be exactly what was accepted: same size and hash, same type, well formed.
fn check_stored(view: &View, bytes: &[u8]) -> Result<(), &'static str> {
    if bytes.len() != view.size as usize
        || Sha256::digest(bytes).as_slice() != view.sha256.as_slice()
    {
        return Err("CHANGED");
    }
    match sniff(bytes) {
        Some(kind) if kind.mime() == view.content_type && well_formed(kind, bytes) => Ok(()),
        _ => Err("STRUCTURE"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn png() -> Vec<u8> {
        let mut bytes = b"\x89PNG\r\n\x1a\n".to_vec();
        bytes.extend([0, 0, 0, 13]);
        bytes.extend(b"IHDR");
        bytes.extend([0; 13 + 4]);
        bytes.extend([0, 0, 0, 0]);
        bytes.extend(b"IEND");
        bytes.extend([0xAE, 0x42, 0x60, 0x82]);
        bytes
    }

    #[test]
    fn accepts_well_formed_files_by_signature() {
        assert_eq!(
            validate("struk.png", "image/png", &png()),
            Ok(FileType::Png)
        );
        assert_eq!(validate("struk.PNG", "", &png()), Ok(FileType::Png));
        let jpeg = [0xFF, 0xD8, 0xFF, 0xE0, 1, 2, 3, 0xFF, 0xD9];
        assert_eq!(
            validate("foto.jpeg", "image/jpeg", &jpeg),
            Ok(FileType::Jpeg)
        );
        let pdf = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n";
        assert_eq!(
            validate("nota.pdf", "application/pdf", pdf),
            Ok(FileType::Pdf)
        );
        let mut webp = b"RIFF\0\0\0\0WEBPVP8 ".to_vec();
        webp.extend([0; 8]);
        let size = (webp.len() - 8) as u32;
        webp[4..8].copy_from_slice(&size.to_le_bytes());
        assert_eq!(validate("a.webp", "image/webp", &webp), Ok(FileType::Webp));
    }

    #[test]
    fn refuses_wrong_type_name_size_and_structure() {
        assert_eq!(validate("x.png", "", b""), Err(Refusal::Empty));
        assert_eq!(validate("x.exe", "", b"MZ\x90\0"), Err(Refusal::Type));
        assert_eq!(validate("x.png", "image/jpeg", &png()), Err(Refusal::Type)); // claim disagrees
        assert_eq!(validate("x.jpg", "", &png()), Err(Refusal::Name)); // renamed
        let truncated = &png()[..20];
        assert_eq!(validate("x.png", "", truncated), Err(Refusal::Structure));
        let mut padded = png();
        padded.extend(b"<script>");
        assert_eq!(validate("x.png", "", &padded), Err(Refusal::Structure));
        assert_eq!(
            validate("x.pdf", "", b"%PDF-1.4 no end marker here"),
            Err(Refusal::Structure)
        );
        let big = vec![0xFF; MAX_BYTES + 1];
        assert_eq!(validate("x.jpg", "", &big), Err(Refusal::TooLarge));
    }

    #[test]
    fn names_and_keys() {
        assert_eq!(clean_name("  struk.png "), Some("struk.png".into()));
        assert_eq!(clean_name("a/b.png"), None);
        assert_eq!(clean_name("a\nb.png"), None);
        assert_eq!(clean_name(""), None);
        assert_ne!(object_key("owner-a", "u"), object_key("owner-b", "u"));
        assert_eq!(object_key("o", "u"), object_key("o", "u"));
        assert!(
            object_key("o", "u")
                .bytes()
                .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'/')
        );
    }
}
