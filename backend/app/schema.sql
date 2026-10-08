-- SQLite schema for the AI Brand Visibility & GEO Auditor.

CREATE TABLE IF NOT EXISTS audits (
    id TEXT PRIMARY KEY,              -- uuid4
    brand_name TEXT NOT NULL,
    url TEXT NOT NULL,
    status TEXT NOT NULL,             -- pending | running | completed | failed
    composite_score REAL,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS access_results (
    audit_id TEXT PRIMARY KEY REFERENCES audits(id),
    robots_txt_found BOOLEAN,
    robots_txt_raw TEXT,
    llms_txt_found BOOLEAN,
    llms_txt_raw TEXT,
    bot_rules_json TEXT               -- {"GPTBot": {"category": "training", "allowed": true}, ...}
);

CREATE TABLE IF NOT EXISTS technical_results (
    audit_id TEXT PRIMARY KEY REFERENCES audits(id),
    meta_description TEXT,
    has_schema_data BOOLEAN,
    schema_types_json TEXT,
    h1_count INTEGER,
    heading_structure_json TEXT,
    word_count INTEGER,
    has_statistics BOOLEAN,
    has_quotations BOOLEAN,
    has_outbound_citations BOOLEAN,
    technical_score REAL              -- 0-100, rule-based
);

CREATE TABLE IF NOT EXISTS ai_prompt_runs (
    id TEXT PRIMARY KEY,
    audit_id TEXT REFERENCES audits(id),
    prompt_text TEXT NOT NULL,
    prompt_type TEXT NOT NULL,        -- branded | unbranded
    run_number INTEGER NOT NULL,      -- which repeat (1..N)
    raw_response TEXT,
    brand_mentioned BOOLEAN,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS retrieval_results (
    audit_id TEXT PRIMARY KEY REFERENCES audits(id),
    query_text TEXT,
    brand_url_retrieved BOOLEAN,
    retrieved_rank INTEGER,           -- null if not retrieved
    raw_response_json TEXT
);

CREATE TABLE IF NOT EXISTS mention_summary (
    audit_id TEXT PRIMARY KEY REFERENCES audits(id),
    category TEXT,
    brand_known TEXT,                 -- known | hallucinated | unknown
    knowledge_consistency REAL,
    explicit_unknown_rate REAL,
    branded_mention_rate REAL,        -- knowledge-derived (1.0/0.15/0.0)
    unbranded_mention_rate REAL,      -- organic discovery
    overall_mention_rate REAL
);

CREATE TABLE IF NOT EXISTS recommendations (
    id TEXT PRIMARY KEY,
    audit_id TEXT REFERENCES audits(id),
    category TEXT NOT NULL,           -- access | technical | mention | retrieval
    severity TEXT NOT NULL,           -- high | medium | low
    description TEXT NOT NULL
);
