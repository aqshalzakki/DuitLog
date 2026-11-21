-- One optional evidence file per activity (BR-FILE-01..06). Bytes live in private object storage;
-- this row is the reference, the quarantine state and the worker's job lease in one place.
CREATE TABLE evidence (
    owner_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL, -- client upload id: retry identity
    activity_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    object_key VARCHAR(80) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    file_name VARCHAR(180) NOT NULL,
    content_type VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    size INT UNSIGNED NOT NULL CHECK (size BETWEEN 1 AND 10485760),
    sha256 BINARY(32) NOT NULL,
    status ENUM('QUARANTINED', 'AVAILABLE', 'REJECTED', 'REMOVED') NOT NULL,
    created_at BIGINT NOT NULL,
    checked_at BIGINT NULL,
    removed_at BIGINT NULL,
    attempts INT UNSIGNED NOT NULL DEFAULT 0,
    next_run_at BIGINT NOT NULL,
    lease_token CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL,
    lease_until BIGINT NULL,
    -- At most one QUARANTINED/AVAILABLE file per activity, enforced by the database.
    active_activity CHAR(36) CHARACTER SET ascii COLLATE ascii_bin
        AS (IF(status IN ('QUARANTINED', 'AVAILABLE'), activity_id, NULL)) STORED,
    PRIMARY KEY (owner_id, id),
    UNIQUE KEY one_active (owner_id, active_activity),
    INDEX by_activity (owner_id, activity_id, created_at),
    INDEX quarantine (status, next_run_at),
    FOREIGN KEY (owner_id, activity_id) REFERENCES activities(owner_id, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
