use argon2::{
    Argon2,
    password_hash::{PasswordHash, PasswordHasher, PasswordVerifier, SaltString},
};
use base64::{Engine, engine::general_purpose::URL_SAFE_NO_PAD};
use hmac::{Hmac, Mac};
use sha2::{Digest, Sha256};

use crate::auth::Error;

fn random<const N: usize>() -> Result<[u8; N], Error> {
    let mut bytes = [0; N];
    getrandom::fill(&mut bytes).map_err(|_| Error::Internal)?;
    Ok(bytes)
}

pub fn id() -> Result<String, Error> {
    Ok(uuid::Builder::from_random_bytes(random()?)
        .into_uuid()
        .to_string())
}

pub fn token() -> Result<String, Error> {
    Ok(URL_SAFE_NO_PAD.encode(random::<32>()?))
}

pub fn digest(value: &str) -> Vec<u8> {
    Sha256::digest(value.as_bytes()).to_vec()
}

pub fn valid_token(value: &str) -> bool {
    value.len() == 43
        && URL_SAFE_NO_PAD
            .decode(value)
            .is_ok_and(|bytes| bytes.len() == 32)
}

pub fn mail_code(key: &[u8; 32], purpose: &str, challenge: &str) -> Result<String, Error> {
    let mut mac = Hmac::<Sha256>::new_from_slice(key).map_err(|_| Error::Internal)?;
    mac.update(b"duitlog-email-v1:");
    mac.update(purpose.as_bytes());
    mac.update(b":");
    mac.update(challenge.as_bytes());
    Ok(URL_SAFE_NO_PAD.encode(mac.finalize().into_bytes()))
}

pub fn password_hash(password: &str) -> Result<String, Error> {
    let salt = SaltString::encode_b64(&random::<16>()?).map_err(|_| Error::Internal)?;
    let hash = Argon2::default()
        .hash_password(password.as_bytes(), &salt)
        .map_err(|_| Error::Internal)?;
    Ok(hash.to_string())
}

pub fn password_matches(password: &str, encoded: &str) -> Result<bool, Error> {
    let hash = PasswordHash::new(encoded).map_err(|_| Error::Internal)?;
    match Argon2::default().verify_password(password.as_bytes(), &hash) {
        Ok(()) => Ok(true),
        Err(argon2::password_hash::Error::Password) => Ok(false),
        Err(_) => Err(Error::Internal),
    }
}
