CREATE TABLE financial_recovery (
    id TINYINT PRIMARY KEY,
    active BOOLEAN NOT NULL
) ENGINE=InnoDB;
INSERT INTO financial_recovery VALUES (1, FALSE);

CREATE TABLE financial_accounts (
    owner_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    balance BIGINT NOT NULL DEFAULT 0,
    receivables BIGINT NOT NULL DEFAULT 0,
    next_sequence BIGINT NOT NULL DEFAULT 1,
    version BIGINT NOT NULL DEFAULT 0,
    opening VARCHAR(8) NOT NULL DEFAULT 'pending',
    frozen BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at BIGINT NULL,
    FOREIGN KEY (owner_id) REFERENCES accounts(id)
) ENGINE=InnoDB;

CREATE TABLE borrowers (
    owner_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    name VARCHAR(100) NOT NULL,
    phone VARCHAR(40) NULL,
    notes VARCHAR(1000) NULL,
    outstanding BIGINT NOT NULL DEFAULT 0 CHECK (outstanding >= 0),
    archived BOOLEAN NOT NULL DEFAULT FALSE,
    version BIGINT NOT NULL DEFAULT 1,
    PRIMARY KEY (owner_id, id),
    FOREIGN KEY (owner_id) REFERENCES accounts(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE categories (
    owner_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    name VARCHAR(100) NOT NULL,
    archived BOOLEAN NOT NULL DEFAULT FALSE,
    version BIGINT NOT NULL DEFAULT 1,
    PRIMARY KEY (owner_id, id),
    FOREIGN KEY (owner_id) REFERENCES accounts(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE activities (
    owner_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    sequence BIGINT NOT NULL,
    effective_at BIGINT NOT NULL,
    kind TINYINT NOT NULL CHECK (kind BETWEEN 1 AND 6),
    amount BIGINT NULL CHECK (amount > 0),
    target_balance BIGINT NULL,
    snapshot_delta BIGINT NULL,
    borrower_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL,
    category_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL,
    title VARCHAR(180) NULL,
    description VARCHAR(2000) NULL,
    affect_cash_balance BOOLEAN NULL,
    depends_on JSON NOT NULL,
    deleted BOOLEAN NOT NULL DEFAULT FALSE,
    version BIGINT NOT NULL DEFAULT 1,
    PRIMARY KEY (owner_id, id),
    UNIQUE KEY financial_sequence (owner_id, sequence),
    INDEX financial_chronology (owner_id, effective_at, sequence, id),
    INDEX financial_history (owner_id, deleted, effective_at, sequence, id),
    INDEX borrower_chronology (owner_id, borrower_id, effective_at, sequence),
    FOREIGN KEY (owner_id) REFERENCES accounts(id),
    FOREIGN KEY (owner_id, borrower_id) REFERENCES borrowers(owner_id, id),
    FOREIGN KEY (owner_id, category_id) REFERENCES categories(owner_id, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE financial_operations (
    owner_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    attempt_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    payload_hash BINARY(32) NOT NULL,
    result JSON NOT NULL,
    action_at BIGINT NOT NULL,
    PRIMARY KEY (owner_id, attempt_id),
    FOREIGN KEY (owner_id) REFERENCES accounts(id)
) ENGINE=InnoDB;

CREATE TABLE financial_client_creates (
    owner_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    client_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    attempt_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    PRIMARY KEY (owner_id, client_id),
    FOREIGN KEY (owner_id, attempt_id) REFERENCES financial_operations(owner_id, attempt_id)
) ENGINE=InnoDB;

CREATE TABLE financial_audit (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    owner_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    actor VARCHAR(100) NOT NULL,
    action VARCHAR(40) NOT NULL,
    action_at BIGINT NOT NULL,
    attempt_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL,
    details JSON NOT NULL,
    INDEX financial_action_order (owner_id, action_at, id),
    FOREIGN KEY (owner_id) REFERENCES accounts(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
