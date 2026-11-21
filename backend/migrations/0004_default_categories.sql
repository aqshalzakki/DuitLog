-- Default categories are created once per financial account (BR-HIS-01). Existing accounts get TRUE
-- from the column default in the same statement, so they are never changed silently; the default then
-- becomes FALSE so new rows are seeded on first use.
ALTER TABLE financial_accounts ADD COLUMN default_categories BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE financial_accounts ALTER COLUMN default_categories SET DEFAULT FALSE;
