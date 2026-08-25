"""Schema 23: preserve repeated Browser Bridge scan manifests while evidence dedupes canonically."""

MIGRATION_023 = r"""
CREATE TABLE autonomous_browser_captures_v2 (
    capture_id TEXT PRIMARY KEY,
    product_key TEXT NOT NULL REFERENCES autonomous_products(product_key) ON DELETE RESTRICT,
    source_url TEXT NOT NULL,
    platform TEXT NOT NULL DEFAULT '',
    capture_type TEXT NOT NULL,
    packet_sha256 TEXT NOT NULL,
    evidence_count INTEGER NOT NULL DEFAULT 0,
    idempotency_key TEXT NOT NULL UNIQUE,
    captured_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

INSERT INTO autonomous_browser_captures_v2 (
    capture_id, product_key, source_url, platform, capture_type,
    packet_sha256, evidence_count, idempotency_key, captured_at, created_at
)
SELECT
    capture_id, product_key, source_url, platform, capture_type,
    packet_sha256, evidence_count, idempotency_key, captured_at, created_at
FROM autonomous_browser_captures;

DROP TABLE autonomous_browser_captures;
ALTER TABLE autonomous_browser_captures_v2 RENAME TO autonomous_browser_captures;

CREATE INDEX IF NOT EXISTS idx_autonomous_browser_capture_product
    ON autonomous_browser_captures(product_key, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_autonomous_browser_capture_packet
    ON autonomous_browser_captures(source_url, packet_sha256);
"""
