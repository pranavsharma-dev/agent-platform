CREATE TABLE IF NOT EXISTS runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    input_question TEXT NOT NULL,
    final_answer JSONB,
    status TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT,
    total_cost_usd NUMERIC(10, 6) DEFAULT 0
);

CREATE TABLE IF NOT EXISTS spans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES runs(id),
    step_index INTEGER NOT NULL,
    step_type TEXT NOT NULL,
    tool_name TEXT,
    input_json JSONB,
    output_json JSONB,
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    cost_usd NUMERIC(10, 8) DEFAULT 0,
    cache_hit BOOLEAN DEFAULT FALSE,
    latency_ms REAL NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_spans_run_id ON spans(run_id);
