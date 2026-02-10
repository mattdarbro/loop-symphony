-- Phase 5B: Knowledge Sync
-- Add version tracking and room sync infrastructure

-- Add version column to knowledge_entries for delta sync
ALTER TABLE knowledge_entries ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 0;

-- Global version counter
CREATE TABLE IF NOT EXISTS knowledge_sync_state (
    key TEXT PRIMARY KEY DEFAULT 'global',
    current_version INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
INSERT INTO knowledge_sync_state (key, current_version) VALUES ('global', 0) ON CONFLICT DO NOTHING;

-- Per-room sync tracking
CREATE TABLE IF NOT EXISTS room_sync_state (
    room_id TEXT PRIMARY KEY,
    last_synced_version INTEGER NOT NULL DEFAULT 0,
    last_sync_at TIMESTAMPTZ DEFAULT NOW()
);

-- Room learnings staging table
CREATE TABLE IF NOT EXISTS room_learnings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    confidence FLOAT DEFAULT 0.5,
    tags JSONB DEFAULT '[]'::jsonb,
    observed_at TIMESTAMPTZ NOT NULL,
    processed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_room_learnings_unprocessed ON room_learnings(processed) WHERE processed = FALSE;
CREATE INDEX IF NOT EXISTS idx_knowledge_version ON knowledge_entries(version);
