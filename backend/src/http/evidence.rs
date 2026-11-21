//! Evidence endpoints. Upload goes through the API (same origin, size and type enforced while
//! reading); bytes reach object storage before the short database transaction that records them,
//! so no storage I/O happens inside a database transaction and a failed upload never touches the
//! confirmed financial activity (BR-FILE-04, AC-21).
use std::{sync::LazyLock, time::Duration};

use axum::{
    Json, Router,
    body::{Body, to_bytes},
    extract::{DefaultBodyLimit, Path, State},
    http::{HeaderMap, HeaderValue, StatusCode, header},
    response::{IntoResponse, Response},
    routing::{get, put},
};
use percent_encoding::{NON_ALPHANUMERIC, percent_decode_str, utf8_percent_encode};
use sha2::{Digest, Sha256};
use tokio::sync::Semaphore;
use uuid::Uuid;

use super::{
    AppState,
    finance::{Actor, resource_id},
};
use crate::{
    evidence::{self, Refusal, Stored},
    financial::{self, Failure, model::Code},
};

/// Each upload is buffered (at most 10 MB); two at a time bounds memory on a 2 GB VPS.
static UPLOADS: LazyLock<Semaphore> = LazyLock::new(|| Semaphore::new(2));

pub(super) fn routes() -> Router<AppState> {
    Router::new()
        .route("/activities/{id}/evidence", get(show).delete(remove))
        .route("/activities/{id}/evidence/content", get(download))
        .route(
            "/activities/{id}/evidence/{upload}",
            put(upload).layer(DefaultBodyLimit::max(evidence::MAX_BYTES)),
        )
}

async fn show(
    State(state): State<AppState>,
    actor: Actor,
    Path(id): Path<String>,
) -> Result<Response, Failure> {
    let owner = actor.0.owner_id;
    let activity = resource_id(&id)?.to_string();
    evidence::owned(&state.auth.db, &owner, &activity).await?;
    Ok(Json(evidence::current(&state.auth.db, &owner, &activity).await?).into_response())
}

/// `PUT /activities/{id}/evidence/{uploadId}`: the body is the file, `Content-Type` its claimed type
/// and `X-Duit-File-Name` its percent-encoded name (kept out of the URL). Repeating the same
/// upload id returns the recorded result instead of storing a second file.
async fn upload(
    State(state): State<AppState>,
    actor: Actor,
    Path((id, upload)): Path<(String, String)>,
    headers: HeaderMap,
    body: Body,
) -> Result<Response, Failure> {
    let db = &state.auth.db;
    let owner = actor.0.owner_id;
    let activity = resource_id(&id)?.to_string();
    let upload = Uuid::parse_str(&upload)
        .ok()
        .filter(|id| id.get_version_num() == 4)
        .ok_or(Code::ValidationError)?
        .to_string();
    financial::sync_allowed(db, &owner).await?;
    evidence::attachable(db, &owner, &activity).await?;
    if let Some(done) = evidence::by_upload(db, &owner, &upload).await? {
        if done.activity_id != activity {
            return Err(Code::ValidationError.into());
        }
        return Ok(Json(done).into_response());
    }

    let text = |name| {
        headers
            .get(name)
            .and_then(|value: &HeaderValue| value.to_str().ok())
    };
    let name = text("x-duit-file-name")
        .map(|raw| percent_decode_str(raw).decode_utf8_lossy().into_owned())
        .and_then(|raw| evidence::clean_name(&raw))
        .ok_or_else(|| evidence::refused(Refusal::Name))?;
    let claimed = text(header::CONTENT_TYPE.as_str())
        .and_then(|value| value.split(';').next())
        .unwrap_or("")
        .trim()
        .to_ascii_lowercase();
    let declared: Option<usize> =
        text(header::CONTENT_LENGTH.as_str()).and_then(|value| value.parse().ok());
    if declared.is_some_and(|length| length > evidence::MAX_BYTES) {
        return Err(evidence::refused(Refusal::TooLarge));
    }

    let permit = UPLOADS.try_acquire().map_err(|_| Failure::Temporary)?;
    let bytes = tokio::time::timeout(
        Duration::from_secs(60),
        to_bytes(body, evidence::MAX_BYTES + 1),
    )
    .await
    .map_err(|_| Failure::Temporary)?
    .map_err(|_| evidence::refused(Refusal::TooLarge))?;
    let kind = evidence::validate(&name, &claimed, &bytes).map_err(evidence::refused)?;
    let file = Stored {
        key: evidence::reserve_object(db).await?,
        sha256: Sha256::digest(&bytes).to_vec(),
        size: u32::try_from(bytes.len()).map_err(|_| evidence::refused(Refusal::TooLarge))?,
        upload: upload.clone(),
        activity: activity.clone(),
        name,
        kind,
    };
    state
        .storage
        .put(&file.key, bytes.to_vec(), kind.mime())
        .await
        .map_err(|_| Failure::Temporary)?;
    drop(permit);

    if let Err(error) = evidence::record(db, &owner, file).await {
        // A concurrent or earlier attempt with the same upload id may have recorded it already.
        return match evidence::by_upload(db, &owner, &upload).await? {
            Some(done) if done.activity_id == activity => Ok(Json(done).into_response()),
            _ => Err(error),
        };
    }
    let recorded = evidence::by_upload(db, &owner, &upload)
        .await?
        .ok_or(Failure::Internal)?;
    Ok((StatusCode::ACCEPTED, Json(recorded)).into_response())
}

async fn remove(
    State(state): State<AppState>,
    actor: Actor,
    Path(id): Path<String>,
) -> Result<StatusCode, Failure> {
    let owner = actor.0.owner_id;
    let activity = resource_id(&id)?.to_string();
    financial::sync_allowed(&state.auth.db, &owner).await?;
    evidence::remove(&state.auth.db, &owner, &activity).await?;
    Ok(StatusCode::NO_CONTENT)
}

/// Always an attachment with the server-verified type, sandboxed, never cached (the security
/// middleware adds `no-store` and `nosniff`). The page previews it from a blob, not this URL.
async fn download(
    State(state): State<AppState>,
    actor: Actor,
    Path(id): Path<String>,
) -> Result<Response, Failure> {
    let owner = actor.0.owner_id;
    let activity = resource_id(&id)?.to_string();
    let (view, bytes) =
        evidence::content(&state.auth.db, &state.storage, &owner, &activity).await?;
    let extension = view
        .file_name
        .rsplit_once('.')
        .map_or("bin", |(_, ext)| ext);
    let disposition = format!(
        "attachment; filename=\"bukti.{}\"; filename*=UTF-8''{}",
        extension.to_ascii_lowercase(),
        utf8_percent_encode(&view.file_name, NON_ALPHANUMERIC)
    );
    let mut response = Response::new(Body::from(bytes));
    let headers = response.headers_mut();
    headers.insert(
        header::CONTENT_TYPE,
        HeaderValue::from_str(&view.content_type).map_err(|_| Failure::Internal)?,
    );
    headers.insert(
        header::CONTENT_DISPOSITION,
        HeaderValue::from_str(&disposition).map_err(|_| Failure::Internal)?,
    );
    headers.insert(
        header::CONTENT_SECURITY_POLICY,
        HeaderValue::from_static("sandbox; default-src 'none'"),
    );
    Ok(response)
}
