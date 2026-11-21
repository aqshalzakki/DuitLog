//! Private S3-compatible object storage (Tech Spec §10.2): path-style requests signed with AWS
//! Signature V4. Only the API and worker hold the credentials; browsers never see a storage URL.
use std::{env, time::Duration};

use hmac::{Hmac, Mac};
use reqwest::{Client, Method, StatusCode};
use sha2::{Digest, Sha256};
use time::OffsetDateTime;

#[derive(Debug, PartialEq)]
pub enum StorageError {
    /// Network, timeout or a 5xx: worth retrying later with the same object key.
    Unavailable,
    /// The object does not exist.
    Missing,
}

#[derive(Clone)]
pub struct Storage {
    client: Client,
    endpoint: url::Url,
    bucket: String,
    region: String,
    access_key: String,
    secret_key: String,
}

impl Storage {
    pub fn from_env() -> Result<Self, &'static str> {
        let endpoint =
            url::Url::parse(&env::var("DUIT_S3_ENDPOINT").map_err(|_| "Set DUIT_S3_ENDPOINT")?)
                .map_err(|_| "Invalid DUIT_S3_ENDPOINT")?;
        let loopback = matches!(endpoint.host_str(), Some("127.0.0.1" | "localhost"));
        if endpoint.scheme() != "https" && !(endpoint.scheme() == "http" && loopback) {
            return Err("DUIT_S3_ENDPOINT must be HTTPS (plain HTTP only on loopback)");
        }
        if endpoint.path() != "/" || endpoint.query().is_some() {
            return Err("DUIT_S3_ENDPOINT must be a bare origin");
        }
        let bucket = env::var("DUIT_S3_BUCKET").map_err(|_| "Set DUIT_S3_BUCKET")?;
        if bucket.is_empty()
            || !bucket
                .bytes()
                .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
        {
            return Err("Invalid DUIT_S3_BUCKET");
        }
        let client = Client::builder()
            .connect_timeout(Duration::from_secs(5))
            .timeout(Duration::from_secs(30))
            .build()
            .map_err(|_| "Storage client initialization failed")?;
        Ok(Self {
            client,
            endpoint,
            bucket,
            region: env::var("DUIT_S3_REGION").unwrap_or_else(|_| "us-east-1".into()),
            access_key: env::var("DUIT_S3_ACCESS_KEY").map_err(|_| "Set DUIT_S3_ACCESS_KEY")?,
            secret_key: env::var("DUIT_S3_SECRET_KEY").map_err(|_| "Set DUIT_S3_SECRET_KEY")?,
        })
    }

    /// Creates the bucket if it does not exist yet (dev and test setup; production pre-provisions it).
    pub async fn ensure_bucket(&self) -> Result<(), StorageError> {
        let path = format!("/{}", self.bucket);
        let status = self
            .send(Method::PUT, &path, Vec::new(), None)
            .await?
            .status();
        if status.is_success() || status == StatusCode::CONFLICT {
            return Ok(());
        }
        Err(StorageError::Unavailable)
    }

    pub async fn put(
        &self,
        key: &str,
        body: Vec<u8>,
        content_type: &str,
    ) -> Result<(), StorageError> {
        let response = self
            .send(Method::PUT, &self.path(key), body, Some(content_type))
            .await?;
        if response.status().is_success() {
            return Ok(());
        }
        Err(StorageError::Unavailable)
    }

    /// Reads a whole object. Evidence is at most 10 MB, so buffering is bounded.
    pub async fn get(&self, key: &str) -> Result<Vec<u8>, StorageError> {
        let response = self
            .send(Method::GET, &self.path(key), Vec::new(), None)
            .await?;
        match response.status() {
            status if status.is_success() => Ok(response
                .bytes()
                .await
                .map_err(|_| StorageError::Unavailable)?
                .to_vec()),
            StatusCode::NOT_FOUND => Err(StorageError::Missing),
            _ => Err(StorageError::Unavailable),
        }
    }

    fn path(&self, key: &str) -> String {
        format!("/{}/{}", self.bucket, key)
    }

    async fn send(
        &self,
        method: Method,
        path: &str,
        body: Vec<u8>,
        content_type: Option<&str>,
    ) -> Result<reqwest::Response, StorageError> {
        let host = match self.endpoint.port() {
            Some(port) => format!("{}:{port}", self.endpoint.host_str().unwrap_or_default()),
            None => self.endpoint.host_str().unwrap_or_default().to_owned(),
        };
        let payload = hex(&Sha256::digest(&body));
        let now = OffsetDateTime::now_utc();
        let stamp = format!(
            "{:04}{:02}{:02}T{:02}{:02}{:02}Z",
            now.year(),
            u8::from(now.month()),
            now.day(),
            now.hour(),
            now.minute(),
            now.second()
        );
        let headers = [
            ("host", host.as_str()),
            ("x-amz-content-sha256", payload.as_str()),
            ("x-amz-date", stamp.as_str()),
        ];
        let signature = sign(
            method.as_str(),
            path,
            &headers,
            &payload,
            &stamp,
            &self.region,
            &self.secret_key,
        )
        .ok_or(StorageError::Unavailable)?;
        let authorization = format!(
            "AWS4-HMAC-SHA256 Credential={}/{}/{}/s3/aws4_request, SignedHeaders={}, Signature={signature}",
            self.access_key,
            &stamp[..8],
            self.region,
            signed_names(&headers),
        );
        let url = self
            .endpoint
            .join(path)
            .map_err(|_| StorageError::Unavailable)?;
        let mut request = self
            .client
            .request(method, url)
            .header("x-amz-content-sha256", payload)
            .header("x-amz-date", stamp)
            .header("authorization", authorization)
            .body(body);
        if let Some(content_type) = content_type {
            request = request.header("content-type", content_type);
        }
        request.send().await.map_err(|_| StorageError::Unavailable)
    }
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn hmac(key: &[u8], data: &str) -> Option<Vec<u8>> {
    let mut mac = Hmac::<Sha256>::new_from_slice(key).ok()?; // HMAC takes any key length
    mac.update(data.as_bytes());
    Some(mac.finalize().into_bytes().to_vec())
}

fn signed_names(headers: &[(&str, &str)]) -> String {
    headers
        .iter()
        .map(|(name, _)| *name)
        .collect::<Vec<_>>()
        .join(";")
}

/// SigV4 for a request without a query string. `headers` are lowercase and sorted by name;
/// `path` must already be URI-safe (bucket names and evidence keys use only `[a-z0-9-/]`).
fn sign(
    method: &str,
    path: &str,
    headers: &[(&str, &str)],
    payload_hash: &str,
    stamp: &str,
    region: &str,
    secret: &str,
) -> Option<String> {
    let canonical_headers: String = headers
        .iter()
        .map(|(name, value)| format!("{name}:{}\n", value.trim()))
        .collect();
    let canonical = format!(
        "{method}\n{path}\n\n{canonical_headers}\n{}\n{payload_hash}",
        signed_names(headers)
    );
    let day = &stamp[..8];
    let scope = format!("{day}/{region}/s3/aws4_request");
    let to_sign = format!(
        "AWS4-HMAC-SHA256\n{stamp}\n{scope}\n{}",
        hex(&Sha256::digest(canonical.as_bytes()))
    );
    let mut key = hmac(format!("AWS4{secret}").as_bytes(), day)?;
    for part in [region, "s3", "aws4_request"] {
        key = hmac(&key, part)?;
    }
    Some(hex(&hmac(&key, &to_sign)?))
}

#[cfg(test)]
mod tests {
    use super::sign;

    /// The GET Object example from the AWS "Signature Version 4: header-based auth" documentation.
    #[test]
    fn matches_aws_reference_signature() {
        let empty = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";
        let headers = [
            ("host", "examplebucket.s3.amazonaws.com"),
            ("range", "bytes=0-9"),
            ("x-amz-content-sha256", empty),
            ("x-amz-date", "20130524T000000Z"),
        ];
        let signature = sign(
            "GET",
            "/test.txt",
            &headers,
            empty,
            "20130524T000000Z",
            "us-east-1",
            "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        );
        assert_eq!(
            signature.as_deref(),
            Some("f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41")
        );
    }
}
