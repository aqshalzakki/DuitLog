use axum::{
    Json, Router,
    extract::{DefaultBodyLimit, FromRequestParts, Path, Query, State},
    http::{StatusCode, request::Parts},
    response::{IntoResponse, Response},
    routing::{get, post},
};
use serde::{Deserialize, de::DeserializeOwned};
use serde_json::{Map, Value, json};
use uuid::Uuid;

use super::{AppState, Input, failure};
use crate::{
    auth::{Error, Principal},
    crypto,
    financial::{self, Failure, Mutation, Outcome, model::*, store, sync},
};

pub(super) fn routes() -> Router<AppState> {
    Router::new()
        .route("/financial-state", get(state))
        .route("/onboarding", get(state))
        .route("/integrity-status", get(integrity))
        .route("/onboarding/opening-balance", post(opening))
        .route("/onboarding/skip-opening-balance", post(skip))
        .route("/balance-adjustments", post(adjust))
        .route("/activities", get(history).post(create))
        .route("/activities/{id}", get(activity).patch(edit).delete(delete))
        .route("/activities/{id}/restore", post(restore))
        .route("/borrowers", get(borrowers).post(add_borrower))
        .route("/borrowers/{id}", get(borrower).patch(edit_borrower))
        .route("/borrowers/{id}/{action}", post(borrower_action))
        .route("/categories", get(categories).post(add_category))
        .route("/categories/{id}", axum::routing::patch(edit_category))
        .route("/categories/{id}/{action}", post(category_action))
        .route("/audit", get(audit))
        .route("/operations/{id}", get(lookup))
        .route(
            "/sync/items",
            post(sync_items).layer(DefaultBodyLimit::max(64 * 1024)),
        )
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Batch {
    items: Vec<Map<String, Value>>,
}

async fn sync_items(
    State(state): State<AppState>,
    actor: Actor,
    Input(batch): Input<Batch>,
) -> Result<Response, Failure> {
    if batch.items.is_empty() || batch.items.len() > sync::MAX_ITEMS {
        return Err(Code::ValidationError.into());
    }
    let items: Vec<sync::Item> = batch
        .items
        .into_iter()
        .map(sync::Item::parse)
        .collect::<Option<_>>()
        .ok_or(Code::ValidationError)?;
    let mut seen = std::collections::HashSet::new();
    if !items
        .iter()
        .all(|item| seen.insert(item.client) && seen.insert(item.attempt))
    {
        return Err(Code::ValidationError.into());
    }
    let owner = actor.0.owner_id;
    financial::sync_allowed(&state.auth.db, &owner).await?;
    // Spawned so a dropped client connection cannot cancel the batch between items.
    let results = tokio::spawn(sync::run(state.auth.db.clone(), owner, items))
        .await
        .map_err(|_| Failure::Internal)?;
    Ok(Json(json!({ "results": results })).into_response())
}

struct Actor(Principal);

impl FromRequestParts<AppState> for Actor {
    type Rejection = Error;

    async fn from_request_parts(parts: &mut Parts, state: &AppState) -> Result<Self, Error> {
        let principal = Principal::from_request_parts(parts, state).await?;
        if principal.verified_at.is_none() {
            return Err(Error::Forbidden);
        }
        Ok(Self(principal))
    }
}

fn rejection(reason: &Rejection, attempt: Option<Uuid>) -> Response {
    let (status, message) = match reason.code {
        Code::NotFound => (StatusCode::NOT_FOUND, "Data tidak ditemukan."),
        Code::InvalidAmount | Code::AmountOverflow => (
            StatusCode::UNPROCESSABLE_ENTITY,
            "Nominal IDR berada di luar rentang yang diizinkan.",
        ),
        Code::InvalidFutureEffectiveTime => (
            StatusCode::UNPROCESSABLE_ENTITY,
            "Waktu efektif berada di masa depan.",
        ),
        Code::ValidationError => (StatusCode::UNPROCESSABLE_ENTITY, "Periksa isian transaksi."),
        Code::FinancialIntegrityFrozen => (
            StatusCode::LOCKED,
            "Akun berada dalam pemeriksaan integritas.",
        ),
        Code::FinancialRecoveryActive => (
            StatusCode::SERVICE_UNAVAILABLE,
            "Pemulihan finansial sedang berlangsung.",
        ),
        Code::TemporaryFailure => (
            StatusCode::SERVICE_UNAVAILABLE,
            "Layanan sedang sibuk. Coba ulang percobaan yang sama.",
        ),
        Code::OutcomeUnknown => (
            StatusCode::SERVICE_UNAVAILABLE,
            "Hasil belum diketahui. Periksa status percobaan.",
        ),
        Code::ReceivableNegative => (StatusCode::CONFLICT, "Kronologi membuat piutang negatif."),
        Code::DependencyBlocked => (
            StatusCode::CONFLICT,
            "Aktivitas pendahulu belum valid dalam kronologi.",
        ),
        Code::VersionConflict => (
            StatusCode::CONFLICT,
            "Data telah berubah. Muat ulang versi terbaru.",
        ),
        Code::CategoryArchived => (
            StatusCode::CONFLICT,
            "Pilih kategori aktif atau tanpa kategori.",
        ),
        Code::BorrowerArchived => (
            StatusCode::CONFLICT,
            "Aktifkan kembali peminjam sebelum mencatat aktivitas baru.",
        ),
        Code::BorrowerOutstanding => (StatusCode::CONFLICT, "Peminjam masih memiliki piutang."),
        Code::OpeningRequired => (
            StatusCode::CONFLICT,
            "Tentukan saldo awal atau lewati saldo awal.",
        ),
        Code::OpeningAlreadyDecided => {
            (StatusCode::CONFLICT, "Keputusan saldo awal sudah tercatat.")
        }
        Code::AlreadyConfirmedActivity => (StatusCode::CONFLICT, "Aktivitas ini sudah tercatat."),
        Code::IdempotencyPayloadMismatch => (
            StatusCode::CONFLICT,
            "Identitas percobaan sudah dipakai untuk isian berbeda.",
        ),
        Code::InvalidActivityState => (
            StatusCode::CONFLICT,
            "Tindakan ini tidak tersedia untuk aktivitas tersebut.",
        ),
    };
    let mut body = json!({
        "code": reason.code, "message": message,
        "requestId": crypto::id().unwrap_or_else(|_| "unavailable".into()),
    });
    if let Some(attempt) = attempt {
        body["attemptId"] = json!(attempt);
        body["status"] = json!("REJECTED");
    }
    if let Some(details) = &reason.conflict_details {
        body["conflictDetails"] = details.clone();
    }
    if reason.code == Code::TemporaryFailure {
        body["retryable"] = json!(true);
    }
    (status, Json(body)).into_response()
}

impl IntoResponse for Failure {
    fn into_response(self) -> Response {
        match self {
            Self::Business(reason) => rejection(&reason, None),
            Self::Temporary => rejection(&Code::TemporaryFailure.into(), None),
            Self::Unknown => rejection(&Code::OutcomeUnknown.into(), None),
            Self::Internal => failure(
                StatusCode::INTERNAL_SERVER_ERROR,
                "INTERNAL_ERROR",
                "Permintaan gagal diproses.",
                None,
            ),
        }
    }
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct Command {
    attempt_id: Uuid,
    client_activity_id: Uuid,
    #[serde(flatten)]
    fields: Map<String, Value>,
}

impl Command {
    fn data<T: DeserializeOwned>(&mut self) -> Result<T, Failure> {
        let fields = std::mem::take(&mut self.fields);
        serde_json::from_value(Value::Object(fields)).map_err(|_| Code::ValidationError.into())
    }

    fn version(&mut self) -> Result<i64, Failure> {
        self.fields
            .remove("expectedVersion")
            .and_then(|value| value.as_i64())
            .filter(|version| *version > 0)
            .ok_or(Code::ValidationError.into())
    }

    fn empty(&self) -> Result<(), Failure> {
        if !self.fields.is_empty() {
            return Err(Code::ValidationError.into());
        }
        Ok(())
    }

    async fn execute(
        self,
        state: AppState,
        actor: Actor,
        operation: Mutation,
    ) -> Result<Response, Failure> {
        if self.attempt_id.get_version_num() != 4 || self.client_activity_id.get_version_num() != 4
        {
            return Err(Code::ValidationError.into());
        }
        let outcome = financial::execute(
            &state.auth.db,
            &actor.0.owner_id,
            self.attempt_id,
            self.client_activity_id,
            operation,
        )
        .await?;
        Ok(match outcome {
            Outcome::Confirmed(_) => Json(outcome).into_response(),
            Outcome::Rejected {
                attempt_id,
                rejection: reason,
            } => rejection(&reason, Some(attempt_id)),
        })
    }
}

fn resource_id(value: &str) -> Result<Uuid, Failure> {
    Uuid::parse_str(value).map_err(|_| Code::NotFound.into())
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Target {
    target_balance: Money,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Name {
    name: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Delete {
    reason: Option<String>,
}

async fn opening(
    State(state): State<AppState>,
    actor: Actor,
    Input(mut cmd): Input<Command>,
) -> Result<Response, Failure> {
    let Target { target_balance } = cmd.data()?;
    cmd.execute(
        state,
        actor,
        Mutation::Opening {
            target: Some(target_balance),
        },
    )
    .await
}

async fn skip(
    State(state): State<AppState>,
    actor: Actor,
    Input(cmd): Input<Command>,
) -> Result<Response, Failure> {
    cmd.empty()?;
    cmd.execute(state, actor, Mutation::Opening { target: None })
        .await
}

async fn adjust(
    State(state): State<AppState>,
    actor: Actor,
    Input(mut cmd): Input<Command>,
) -> Result<Response, Failure> {
    let Target { target_balance } = cmd.data()?;
    cmd.execute(
        state,
        actor,
        Mutation::Adjustment {
            target: target_balance,
        },
    )
    .await
}

async fn create(
    State(state): State<AppState>,
    actor: Actor,
    Input(mut cmd): Input<Command>,
) -> Result<Response, Failure> {
    let input = cmd.data()?;
    cmd.execute(state, actor, Mutation::Create(input)).await
}

async fn edit(
    State(state): State<AppState>,
    actor: Actor,
    Path(id): Path<String>,
    Input(mut cmd): Input<Command>,
) -> Result<Response, Failure> {
    let id = resource_id(&id)?;
    let version = cmd.version()?;
    let input = cmd.data()?;
    cmd.execute(state, actor, Mutation::Edit { id, version, input })
        .await
}

async fn delete(
    State(state): State<AppState>,
    actor: Actor,
    Path(id): Path<String>,
    Input(mut cmd): Input<Command>,
) -> Result<Response, Failure> {
    let id = resource_id(&id)?;
    let version = cmd.version()?;
    let Delete { reason } = cmd.data()?;
    cmd.execute(
        state,
        actor,
        Mutation::Delete {
            id,
            version,
            reason,
        },
    )
    .await
}

async fn restore(
    State(state): State<AppState>,
    actor: Actor,
    Path(id): Path<String>,
    Input(mut cmd): Input<Command>,
) -> Result<Response, Failure> {
    let id = resource_id(&id)?;
    let version = cmd.version()?;
    cmd.empty()?;
    cmd.execute(state, actor, Mutation::Restore { id, version })
        .await
}

async fn add_borrower(
    State(state): State<AppState>,
    actor: Actor,
    Input(mut cmd): Input<Command>,
) -> Result<Response, Failure> {
    let input = cmd.data()?;
    cmd.execute(state, actor, Mutation::AddBorrower(input))
        .await
}

async fn edit_borrower(
    State(state): State<AppState>,
    actor: Actor,
    Path(id): Path<String>,
    Input(mut cmd): Input<Command>,
) -> Result<Response, Failure> {
    let id = resource_id(&id)?;
    let version = cmd.version()?;
    let input = cmd.data()?;
    cmd.execute(state, actor, Mutation::EditBorrower { id, version, input })
        .await
}

async fn borrower_action(
    State(state): State<AppState>,
    actor: Actor,
    Path((id, action)): Path<(String, String)>,
    Input(mut cmd): Input<Command>,
) -> Result<Response, Failure> {
    let id = resource_id(&id)?;
    let archive = match action.as_str() {
        "archive" => true,
        "reactivate" => false,
        _ => return Err(Code::NotFound.into()),
    };
    let version = cmd.version()?;
    cmd.empty()?;
    cmd.execute(
        state,
        actor,
        Mutation::ArchiveBorrower {
            id,
            version,
            archive,
        },
    )
    .await
}

async fn add_category(
    State(state): State<AppState>,
    actor: Actor,
    Input(mut cmd): Input<Command>,
) -> Result<Response, Failure> {
    let Name { name } = cmd.data()?;
    cmd.execute(state, actor, Mutation::AddCategory { name })
        .await
}

async fn edit_category(
    State(state): State<AppState>,
    actor: Actor,
    Path(id): Path<String>,
    Input(mut cmd): Input<Command>,
) -> Result<Response, Failure> {
    let id = resource_id(&id)?;
    let version = cmd.version()?;
    let Name { name } = cmd.data()?;
    cmd.execute(state, actor, Mutation::RenameCategory { id, version, name })
        .await
}

async fn category_action(
    State(state): State<AppState>,
    actor: Actor,
    Path((id, action)): Path<(String, String)>,
    Input(mut cmd): Input<Command>,
) -> Result<Response, Failure> {
    let id = resource_id(&id)?;
    let archive = match action.as_str() {
        "archive" => true,
        "restore" => false,
        _ => return Err(Code::NotFound.into()),
    };
    let version = cmd.version()?;
    cmd.empty()?;
    cmd.execute(
        state,
        actor,
        Mutation::ArchiveCategory {
            id,
            version,
            archive,
        },
    )
    .await
}

async fn state(State(state): State<AppState>, actor: Actor) -> Result<Json<Value>, Failure> {
    Ok(Json(
        financial::view_state(&state.auth.db, &actor.0.owner_id).await?,
    ))
}

async fn integrity(State(state): State<AppState>, actor: Actor) -> Result<Json<Value>, Failure> {
    let value = financial::view_state(&state.auth.db, &actor.0.owner_id).await?;
    Ok(Json(
        json!({"frozen": value["frozen"], "recoveryActive": value["recoveryActive"]}),
    ))
}

#[derive(Deserialize)]
struct History {
    #[serde(default)]
    deleted: bool,
    before: Option<i64>,
}

async fn history(
    State(state): State<AppState>,
    actor: Actor,
    Query(filter): Query<History>,
) -> Result<Json<Value>, Failure> {
    Ok(Json(
        financial::history(
            &state.auth.db,
            &actor.0.owner_id,
            filter.deleted,
            filter.before,
        )
        .await?,
    ))
}

async fn activity(
    State(state): State<AppState>,
    actor: Actor,
    Path(id): Path<String>,
) -> Result<Json<Activity>, Failure> {
    let mut conn = state.auth.db.acquire().await?;
    Ok(Json(
        store::one(&mut conn, &actor.0.owner_id, &resource_id(&id)?.to_string()).await?,
    ))
}

async fn borrowers(
    State(state): State<AppState>,
    actor: Actor,
) -> Result<Json<Vec<Value>>, Failure> {
    Ok(Json(
        financial::borrowers(&state.auth.db, &actor.0.owner_id).await?,
    ))
}

async fn borrower(
    State(state): State<AppState>,
    actor: Actor,
    Path(id): Path<String>,
) -> Result<Json<Value>, Failure> {
    let mut conn = state.auth.db.acquire().await?;
    Ok(Json(
        store::borrower(&mut conn, &actor.0.owner_id, &resource_id(&id)?.to_string())
            .await?
            .view(),
    ))
}

async fn categories(
    State(state): State<AppState>,
    actor: Actor,
) -> Result<Json<Vec<store::Category>>, Failure> {
    let mut conn = state.auth.db.acquire().await?;
    Ok(Json(store::categories(&mut conn, &actor.0.owner_id).await?))
}

async fn lookup(
    State(state): State<AppState>,
    actor: Actor,
    Path(id): Path<String>,
) -> Result<Json<Outcome>, Failure> {
    Ok(Json(
        financial::lookup(&state.auth.db, &actor.0.owner_id, resource_id(&id)?).await?,
    ))
}

#[derive(Deserialize)]
struct AuditQuery {
    before: Option<u64>,
}

async fn audit(
    State(state): State<AppState>,
    actor: Actor,
    Query(query): Query<AuditQuery>,
) -> Result<Json<Value>, Failure> {
    Ok(Json(
        financial::audit_page(&state.auth.db, &actor.0.owner_id, query.before).await?,
    ))
}
