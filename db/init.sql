CREATE TABLE IF NOT EXISTS runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    input_question TEXT NOT NULL,
    final_answer JSONB,
    status TEXT NOT NULL DEFAULT 'pending',
    total_cost_usd NUMERIC(10, 6) DEFAULT 0
);
