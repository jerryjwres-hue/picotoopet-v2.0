"""Schema 20: canonical connected-product evidence and import/capture manifests."""

MIGRATION_020 = r"""
CREATE TABLE IF NOT EXISTS autonomous_products (
    product_key TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    brand TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL,
    external_ref_type TEXT NOT NULL DEFAULT '',
    external_ref_id TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(origin, external_ref_type, external_ref_id)
);
CREATE INDEX IF NOT EXISTS idx_autonomous_products_title
    ON autonomous_products(title, brand);

CREATE TABLE IF NOT EXISTS autonomous_evidence (
    evidence_id TEXT PRIMARY KEY,
    product_key TEXT NOT NULL REFERENCES autonomous_products(product_key) ON DELETE RESTRICT,
    evidence_type TEXT NOT NULL,
    source TEXT NOT NULL,
    platform TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    source_entity_id TEXT NOT NULL DEFAULT '',
    text_value TEXT NOT NULL DEFAULT '',
    numeric_value REAL,
    value_json TEXT NOT NULL DEFAULT '{}',
    raw_hash TEXT NOT NULL,
    trust_level TEXT NOT NULL DEFAULT 'E',
    confidence REAL NOT NULL DEFAULT 0.0,
    captured_at TEXT NOT NULL,
    source_updated_at TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL,
    external_ref_type TEXT NOT NULL DEFAULT '',
    external_ref_id TEXT NOT NULL DEFAULT '',
    idempotency_key TEXT NOT NULL UNIQUE,
    provenance_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(product_key, evidence_type, source, source_entity_id, raw_hash)
);
CREATE INDEX IF NOT EXISTS idx_autonomous_evidence_product
    ON autonomous_evidence(product_key, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_autonomous_evidence_external_ref
    ON autonomous_evidence(external_ref_type, external_ref_id);
CREATE INDEX IF NOT EXISTS idx_autonomous_evidence_hash
    ON autonomous_evidence(raw_hash);

CREATE TABLE IF NOT EXISTS autonomous_legacy_imports (
    import_id TEXT PRIMARY KEY,
    source_sha256 TEXT NOT NULL UNIQUE,
    source_name TEXT NOT NULL,
    source_size_bytes INTEGER NOT NULL,
    source_schema_version INTEGER,
    status TEXT NOT NULL,
    products_imported INTEGER NOT NULL DEFAULT 0,
    evidence_imported INTEGER NOT NULL DEFAULT 0,
    evidence_skipped INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS autonomous_browser_captures (
    capture_id TEXT PRIMARY KEY,
    product_key TEXT NOT NULL REFERENCES autonomous_products(product_key) ON DELETE RESTRICT,
    source_url TEXT NOT NULL,
    platform TEXT NOT NULL DEFAULT '',
    capture_type TEXT NOT NULL,
    packet_sha256 TEXT NOT NULL,
    evidence_count INTEGER NOT NULL DEFAULT 0,
    idempotency_key TEXT NOT NULL UNIQUE,
    captured_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(source_url, packet_sha256)
);
CREATE INDEX IF NOT EXISTS idx_autonomous_browser_capture_product
    ON autonomous_browser_captures(product_key, captured_at DESC);
"""
