-- Saved arrangements for meta-learning (Phase 3C)
-- Run this migration in Supabase SQL Editor

-- Table for saved arrangements (reusable compositions and loops)
CREATE TABLE IF NOT EXISTS saved_arrangements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    app_id UUID REFERENCES apps(id) ON DELETE CASCADE,  -- NULL = global
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    arrangement_type TEXT NOT NULL CHECK (arrangement_type IN ('composition', 'loop')),

    -- The actual arrangement spec (JSON)
    composition_spec JSONB,  -- ArrangementProposal when type=composition
    loop_spec JSONB,         -- LoopProposal when type=loop

    -- Matching metadata
    query_patterns TEXT[] DEFAULT '{}',
    tags TEXT[] DEFAULT '{}',

    -- Statistics
    total_executions INTEGER DEFAULT 0,
    successful_executions INTEGER DEFAULT 0,
    average_confidence FLOAT DEFAULT 0.0,
    average_duration_ms FLOAT DEFAULT 0.0,
    last_executed_at TIMESTAMPTZ,

    -- Status and timestamps
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),

    -- Ensure name is unique within app scope
    UNIQUE(app_id, name)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_saved_arrangements_app_id ON saved_arrangements(app_id);
CREATE INDEX IF NOT EXISTS idx_saved_arrangements_name ON saved_arrangements(name);
CREATE INDEX IF NOT EXISTS idx_saved_arrangements_type ON saved_arrangements(arrangement_type);
CREATE INDEX IF NOT EXISTS idx_saved_arrangements_tags ON saved_arrangements USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_saved_arrangements_is_active ON saved_arrangements(is_active);

-- Enable RLS
ALTER TABLE saved_arrangements ENABLE ROW LEVEL SECURITY;

-- RLS policies for app isolation
CREATE POLICY "Apps can only see their own arrangements" ON saved_arrangements
    FOR SELECT USING (app_id IS NULL OR app_id = current_setting('app.current_app_id', true)::uuid);

CREATE POLICY "Apps can only insert their own arrangements" ON saved_arrangements
    FOR INSERT WITH CHECK (app_id IS NULL OR app_id = current_setting('app.current_app_id', true)::uuid);

CREATE POLICY "Apps can only update their own arrangements" ON saved_arrangements
    FOR UPDATE USING (app_id IS NULL OR app_id = current_setting('app.current_app_id', true)::uuid);

CREATE POLICY "Apps can only delete their own arrangements" ON saved_arrangements
    FOR DELETE USING (app_id IS NULL OR app_id = current_setting('app.current_app_id', true)::uuid);

-- Comments for documentation
COMMENT ON TABLE saved_arrangements IS 'Saved arrangements for reuse - learned patterns from successful executions';
COMMENT ON COLUMN saved_arrangements.app_id IS 'NULL means global (available to all apps)';
COMMENT ON COLUMN saved_arrangements.composition_spec IS 'ArrangementProposal JSON for type=composition';
COMMENT ON COLUMN saved_arrangements.loop_spec IS 'LoopProposal JSON for type=loop';
COMMENT ON COLUMN saved_arrangements.query_patterns IS 'Query patterns this arrangement works well for';
