ALTER TABLE evidence ADD UNIQUE KEY by_object_key (object_key);

CREATE TABLE evidence_cleanup (
    object_key VARCHAR(80) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    next_run_at BIGINT NOT NULL,
    sealed BOOLEAN NOT NULL DEFAULT FALSE,
    attempts BIGINT UNSIGNED NOT NULL DEFAULT 0,
    INDEX due (next_run_at, object_key)
) ENGINE=InnoDB;
