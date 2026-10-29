"""Idempotent additive Worker trust tables; preserve frozen schema-24 migration history.

These tables are not an independent privilege registry or CPU/GPU authorization.
Kept separate from numbered schema migrations so historical 23->24 upgrade tests
remain valid. No future transaction may consume nonce outside locked Claim audit.
"""
WORKER_TRUST_SCHEMA = r"""
CREATE TABLE IF NOT EXISTS production_worker_keys (
    key_id TEXT PRIMARY KEY,
    executor_id TEXT NOT NULL,
    public_key_hex TEXT NOT NULL UNIQUE CHECK(length(public_key_hex)=64),
    key_fingerprint TEXT NOT NULL UNIQUE CHECK(length(key_fingerprint)=64),
    registered_by TEXT NOT NULL,
    operator_receipt_sha256 TEXT NOT NULL CHECK(length(operator_receipt_sha256)=64),
    enrolled_at TEXT NOT NULL,
    revoked_at TEXT,
    revoked_reason TEXT,
    CHECK (length(key_id) BETWEEN 16 AND 128)
);
CREATE INDEX IF NOT EXISTS idx_worker_keys_active
    ON production_worker_keys(executor_id, revoked_at, enrolled_at);

CREATE TABLE IF NOT EXISTS production_worker_challenges (
    nonce_digest TEXT PRIMARY KEY CHECK(length(nonce_digest)=64),
    key_id TEXT NOT NULL REFERENCES production_worker_keys(key_id) ON DELETE RESTRICT,
    executor_id TEXT NOT NULL,
    production_job_id TEXT NOT NULL REFERENCES production_jobs(production_job_id) ON DELETE RESTRICT,
    plan_digest TEXT NOT NULL CHECK(length(plan_digest)=64),
    issued_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT,
    CHECK (issued_at < expires_at)
);
CREATE INDEX IF NOT EXISTS idx_worker_challenges_key_job
    ON production_worker_challenges(key_id, production_job_id, expires_at);
"""
