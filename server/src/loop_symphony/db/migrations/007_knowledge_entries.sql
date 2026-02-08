-- Knowledge entries schema (Phase 5A)
-- Structured knowledge layer: capabilities, boundaries, patterns, changelog, user learnings

CREATE TABLE IF NOT EXISTS knowledge_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category TEXT NOT NULL,          -- capabilities, boundaries, patterns, changelog, user
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'seed',  -- seed, error_tracker, arrangement_tracker, trust_tracker, manual, system
    confidence FLOAT NOT NULL DEFAULT 1.0,
    user_id TEXT,                     -- null for global entries, set for per-user knowledge
    tags JSONB DEFAULT '[]'::jsonb,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_knowledge_category ON knowledge_entries(category) WHERE is_active = TRUE;
CREATE INDEX idx_knowledge_user ON knowledge_entries(user_id) WHERE user_id IS NOT NULL AND is_active = TRUE;
CREATE INDEX idx_knowledge_source ON knowledge_entries(source) WHERE is_active = TRUE;
CREATE INDEX idx_knowledge_category_source ON knowledge_entries(category, source) WHERE is_active = TRUE;

-- Enable RLS
ALTER TABLE knowledge_entries ENABLE ROW LEVEL SECURITY;
