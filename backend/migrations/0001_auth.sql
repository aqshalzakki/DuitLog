CREATE TABLE accounts (
    id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    email VARCHAR(254) CHARACTER SET ascii COLLATE ascii_bin NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    password_hash VARCHAR(255) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    verified_at BIGINT NULL,
    created_at BIGINT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE device_sessions (
    id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    owner_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    label VARCHAR(100) NOT NULL,
    access_digest BINARY(32) NOT NULL UNIQUE,
    access_expires_at BIGINT NOT NULL,
    created_at BIGINT NOT NULL,
    last_seen_at BIGINT NOT NULL,
    expires_at BIGINT NOT NULL,
    revoked_at BIGINT NULL,
    INDEX owner_active (owner_id, revoked_at, expires_at),
    FOREIGN KEY (owner_id) REFERENCES accounts(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE refresh_tokens (
    digest BINARY(32) PRIMARY KEY,
    session_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    used_at BIGINT NULL,
    FOREIGN KEY (session_id) REFERENCES device_sessions(id)
) ENGINE=InnoDB;

CREATE TABLE auth_challenges (
    id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    owner_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    purpose ENUM('verify', 'reset') NOT NULL,
    digest BINARY(32) NOT NULL UNIQUE,
    expires_at BIGINT NOT NULL,
    consumed_at BIGINT NULL,
    INDEX owner_purpose (owner_id, purpose, consumed_at),
    FOREIGN KEY (owner_id) REFERENCES accounts(id)
) ENGINE=InnoDB;

CREATE TABLE mail_jobs (
    challenge_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    next_run_at BIGINT NOT NULL,
    attempts INT UNSIGNED NOT NULL DEFAULT 0,
    lease_token CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL,
    lease_until BIGINT NULL,
    completed_at BIGINT NULL,
    failed_at BIGINT NULL,
    INDEX ready_jobs (completed_at, failed_at, next_run_at),
    FOREIGN KEY (challenge_id) REFERENCES auth_challenges(id)
) ENGINE=InnoDB;

CREATE TABLE auth_rate_limits (
    rate_key BINARY(32) PRIMARY KEY,
    hits INT UNSIGNED NOT NULL,
    reset_at BIGINT NOT NULL,
    INDEX expiry (reset_at)
) ENGINE=InnoDB;
