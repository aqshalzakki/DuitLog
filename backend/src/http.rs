use std::net::SocketAddr;
mod evidence;
mod finance;

use axum::{
    Json, Router,
    body::Body,
    extract::{ConnectInfo, DefaultBodyLimit, FromRequest, FromRequestParts, Path, Request, State},
    http::{HeaderMap, HeaderValue, StatusCode, header, request::Parts},
    middleware::{self, Next},
    response::{IntoResponse, Response},
    routing::{delete, get, post},
};
use serde::{Deserialize, de::DeserializeOwned};
use serde_json::json;

use crate::{
    auth::{self, Auth, Cookies, Error, Principal},
    crypto,
    storage::Storage,
};

const ACCESS: &str = "__Host-duit-access";
const REFRESH: &str = "__Host-duit-refresh";

#[derive(Clone)]
struct AppState {
    auth: Auth,
    origin: String,
    storage: Storage,
}

pub fn router(auth: Auth, origin: String, storage: Storage) -> Router {
    let state = AppState {
        auth,
        origin,
        storage,
    };
    let api = Router::new()
        .route("/healthz", get(health))
        .route("/readyz", get(ready))
        .route("/auth/register", post(register))
        .route("/auth/login", post(login))
        .route("/auth/verify-email", post(verify))
        .route("/auth/resend-verification", post(resend))
        .route("/auth/forgot-password", post(forgot))
        .route("/auth/reset-password", post(reset))
        .route("/auth/refresh", post(refresh))
        .route("/auth/logout", post(logout))
        .route("/auth/logout-all", post(logout_all))
        .route("/me", get(me))
        .route("/sessions", get(sessions))
        .route("/sessions/{id}", delete(revoke_device))
        .route("/account/verified", get(verified))
        .merge(finance::routes())
        .merge(evidence::routes())
        .fallback(|| async { Error::NotFound })
        .method_not_allowed_fallback(|| async {
            failure(
                StatusCode::METHOD_NOT_ALLOWED,
                "METHOD_NOT_ALLOWED",
                "Metode tidak tersedia.",
                None,
            )
        })
        .layer(DefaultBodyLimit::max(4096))
        .layer(middleware::from_fn_with_state(state.clone(), security));
    Router::new().nest("/api/v1", api).with_state(state)
}

impl IntoResponse for Error {
    fn into_response(self) -> Response {
        let (status, code, message, field) = match self {
            Self::Field(field, message) => (
                StatusCode::BAD_REQUEST,
                "VALIDATION_ERROR",
                "Periksa isian formulir.",
                Some((field, message)),
            ),
            Self::InvalidCode => (
                StatusCode::BAD_REQUEST,
                "INVALID_CODE",
                "Kode tidak valid atau sudah kedaluwarsa.",
                None,
            ),
            Self::Credentials => (
                StatusCode::UNAUTHORIZED,
                "INVALID_CREDENTIALS",
                "Email atau kata sandi tidak cocok.",
                None,
            ),
            Self::Unauthorized => (
                StatusCode::UNAUTHORIZED,
                "UNAUTHORIZED",
                "Silakan masuk kembali.",
                None,
            ),
            Self::Forbidden => (
                StatusCode::FORBIDDEN,
                "EMAIL_VERIFICATION_REQUIRED",
                "Verifikasi email diperlukan.",
                None,
            ),
            Self::NotFound => (
                StatusCode::NOT_FOUND,
                "NOT_FOUND",
                "Data tidak ditemukan.",
                None,
            ),
            Self::RateLimited => (
                StatusCode::TOO_MANY_REQUESTS,
                "RATE_LIMITED",
                "Terlalu banyak percobaan. Coba lagi nanti.",
                None,
            ),
            Self::Internal => (
                StatusCode::INTERNAL_SERVER_ERROR,
                "INTERNAL_ERROR",
                "Permintaan gagal diproses.",
                None,
            ),
        };
        failure(status, code, message, field)
    }
}

fn failure(status: StatusCode, code: &str, message: &str, field: Option<(&str, &str)>) -> Response {
    let request_id = crypto::id().unwrap_or_else(|_| "unavailable".to_owned());
    if status.is_server_error() {
        eprintln!("API request failed request_id={request_id} code={code}");
    }
    let mut payload = json!({ "code": code, "message": message, "requestId": request_id });
    if let Some((name, error)) = field {
        payload["fieldErrors"] = json!({ (name): error });
    }
    (status, Json(payload)).into_response()
}

async fn security(State(state): State<AppState>, request: Request<Body>, next: Next) -> Response {
    let headers = request.headers();
    let mut response = if !request.method().is_safe()
        && (headers
            .get(header::ORIGIN)
            .and_then(|value| value.to_str().ok())
            != Some(state.origin.as_str())
            || headers
                .get("x-duit-csrf")
                .and_then(|value| value.to_str().ok())
                != Some("1"))
    {
        failure(
            StatusCode::FORBIDDEN,
            "CSRF_REJECTED",
            "Asal permintaan tidak diizinkan.",
            None,
        )
    } else {
        next.run(request).await
    };
    let headers = response.headers_mut();
    headers.insert(header::CACHE_CONTROL, HeaderValue::from_static("no-store"));
    headers.insert(
        header::X_CONTENT_TYPE_OPTIONS,
        HeaderValue::from_static("nosniff"),
    );
    headers.insert(
        header::REFERRER_POLICY,
        HeaderValue::from_static("no-referrer"),
    );
    response
}

struct Input<T>(T);

impl<S: Send + Sync, T: DeserializeOwned> FromRequest<S> for Input<T> {
    type Rejection = Response;

    async fn from_request(request: Request, state: &S) -> Result<Self, Self::Rejection> {
        Json::<T>::from_request(request, state)
            .await
            .map(|Json(value)| Self(value))
            .map_err(|error| {
                failure(
                    error.status(),
                    "INVALID_BODY",
                    "Format permintaan tidak valid.",
                    None,
                )
            })
    }
}

fn cookie<'a>(headers: &'a HeaderMap, name: &str) -> Option<&'a str> {
    let mut matching = headers
        .get_all(header::COOKIE)
        .iter()
        .filter_map(|value| value.to_str().ok())
        .flat_map(|value| value.split(';'))
        .filter_map(|value| value.trim().split_once('='))
        .filter_map(|(key, value)| (key == name).then_some(value));
    let value = matching.next()?;
    matching.next().is_none().then_some(value)
}

impl FromRequestParts<AppState> for Principal {
    type Rejection = Error;

    async fn from_request_parts(parts: &mut Parts, state: &AppState) -> Result<Self, Error> {
        state
            .auth
            .principal(cookie(&parts.headers, ACCESS).ok_or(Error::Unauthorized)?)
            .await
    }
}

fn cookie_response(cookies: Option<Cookies>) -> Result<Response, Error> {
    let mut response = StatusCode::NO_CONTENT.into_response();
    let (access, refresh, access_age, refresh_age) = match cookies {
        Some(cookies) => (
            cookies.access,
            cookies.refresh,
            cookies.access_age,
            cookies.refresh_age,
        ),
        None => (String::new(), String::new(), 0, 0),
    };
    for (name, value, age) in [
        (ACCESS, access, access_age),
        (REFRESH, refresh, refresh_age),
    ] {
        let header =
            format!("{name}={value}; Path=/; Max-Age={age}; Secure; HttpOnly; SameSite=Strict");
        response.headers_mut().append(
            header::SET_COOKIE,
            HeaderValue::from_str(&header).map_err(|_| Error::Internal)?,
        );
    }
    Ok(response)
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Register {
    name: String,
    email: String,
    password: String,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Login {
    email: String,
    password: String,
    device_name: Option<String>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Email {
    email: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Verify {
    token: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Reset {
    token: String,
    password: String,
}

async fn register(
    State(state): State<AppState>,
    ConnectInfo(peer): ConnectInfo<SocketAddr>,
    Input(body): Input<Register>,
) -> Result<StatusCode, Error> {
    state
        .auth
        .limit("register:ip", &peer.ip().to_string(), 12, 900)
        .await?;
    let email = auth::email(&body.email)?;
    state.auth.limit("register:email", &email, 3, 900).await?;
    state
        .auth
        .register(&body.name, &email, body.password)
        .await?;
    Ok(StatusCode::ACCEPTED)
}

async fn login(
    State(state): State<AppState>,
    ConnectInfo(peer): ConnectInfo<SocketAddr>,
    Input(body): Input<Login>,
) -> Result<Response, Error> {
    state
        .auth
        .limit("login:ip", &peer.ip().to_string(), 45, 900)
        .await?;
    let email = auth::email(&body.email).map_err(|_| Error::Credentials)?;
    state.auth.limit("login:email", &email, 8, 900).await?;
    let cookies = state
        .auth
        .login(&email, body.password, body.device_name.as_deref())
        .await?;
    cookie_response(Some(cookies))
}

async fn verify(
    State(state): State<AppState>,
    principal: Principal,
    Input(body): Input<Verify>,
) -> Result<StatusCode, Error> {
    state
        .auth
        .limit("verify:account", &principal.owner_id, 12, 900)
        .await?;
    state.auth.verify(&principal, body.token.trim()).await?;
    Ok(StatusCode::NO_CONTENT)
}

async fn resend(State(state): State<AppState>, principal: Principal) -> Result<StatusCode, Error> {
    state
        .auth
        .limit("resend:account", &principal.owner_id, 3, 900)
        .await?;
    state.auth.resend(&principal).await?;
    Ok(StatusCode::ACCEPTED)
}

async fn forgot(
    State(state): State<AppState>,
    ConnectInfo(peer): ConnectInfo<SocketAddr>,
    Input(body): Input<Email>,
) -> Result<StatusCode, Error> {
    state
        .auth
        .limit("forgot:ip", &peer.ip().to_string(), 18, 900)
        .await?;
    let email = auth::email(&body.email)?;
    state.auth.limit("forgot:email", &email, 4, 900).await?;
    state.auth.forgot_password(&email).await?;
    Ok(StatusCode::ACCEPTED)
}

async fn reset(
    State(state): State<AppState>,
    ConnectInfo(peer): ConnectInfo<SocketAddr>,
    Input(body): Input<Reset>,
) -> Result<StatusCode, Error> {
    state
        .auth
        .limit("reset:ip", &peer.ip().to_string(), 12, 900)
        .await?;
    state
        .auth
        .reset_password(body.token.trim(), body.password)
        .await?;
    Ok(StatusCode::NO_CONTENT)
}

async fn refresh(
    State(state): State<AppState>,
    ConnectInfo(peer): ConnectInfo<SocketAddr>,
    headers: HeaderMap,
) -> Result<Response, Error> {
    state
        .auth
        .limit("refresh:ip", &peer.ip().to_string(), 120, 60)
        .await?;
    let cookies = state
        .auth
        .refresh(cookie(&headers, REFRESH).ok_or(Error::Unauthorized)?)
        .await?;
    cookie_response(Some(cookies))
}

async fn logout(State(state): State<AppState>, headers: HeaderMap) -> Result<Response, Error> {
    if let Some(value) = cookie(&headers, REFRESH) {
        state.auth.logout(value).await?;
    }
    cookie_response(None)
}

async fn logout_all(
    State(state): State<AppState>,
    principal: Principal,
) -> Result<Response, Error> {
    state.auth.logout_all(&principal).await?;
    cookie_response(None)
}

async fn me(principal: Principal) -> Response {
    Json(principal.profile()).into_response()
}

async fn sessions(State(state): State<AppState>, principal: Principal) -> Result<Response, Error> {
    Ok(Json(state.auth.devices(&principal).await?).into_response())
}

async fn revoke_device(
    State(state): State<AppState>,
    principal: Principal,
    Path(id): Path<String>,
) -> Result<Response, Error> {
    let id = uuid::Uuid::parse_str(&id)
        .map_err(|_| Error::NotFound)?
        .to_string();
    state.auth.revoke_device(&principal, &id).await?;
    if id == principal.session_id {
        cookie_response(None)
    } else {
        Ok(StatusCode::NO_CONTENT.into_response())
    }
}

async fn verified(principal: Principal) -> Result<StatusCode, Error> {
    if principal.verified_at.is_none() {
        return Err(Error::Forbidden);
    }
    Ok(StatusCode::NO_CONTENT)
}

async fn health() -> StatusCode {
    StatusCode::NO_CONTENT
}

async fn ready(State(state): State<AppState>) -> Response {
    if sqlx::query("SELECT 1 FROM accounts LIMIT 1")
        .execute(&state.auth.db)
        .await
        .is_ok()
    {
        StatusCode::NO_CONTENT.into_response()
    } else {
        failure(
            StatusCode::SERVICE_UNAVAILABLE,
            "NOT_READY",
            "Layanan belum siap.",
            None,
        )
    }
}
