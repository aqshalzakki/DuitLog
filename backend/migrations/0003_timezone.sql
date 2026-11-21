-- Account timezone for date grouping and display (BR-RPT-11). Changing it never touches stored instants.
ALTER TABLE financial_accounts ADD COLUMN timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Jakarta';
