CREATE TYPE lead_status AS ENUM (
    'received',
    'processing',
    'enriched',
    'scored',
    'routed',
    'needs_review',
    'alert_failed',
    'cold',
    'nurture'
);

CREATE TABLE IF NOT EXISTS leads (
    id              BIGSERIAL PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    payload         JSONB NOT NULL,
    status          lead_status NOT NULL DEFAULT 'received',
    error           TEXT,
    enrichment_data JSONB,
    score           INTEGER,
    score_bucket    TEXT,
    elapsed_seconds DOUBLE PRECISION,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_leads_status ON leads (status);
CREATE INDEX IF NOT EXISTS idx_leads_idempotency_key ON leads (idempotency_key);
