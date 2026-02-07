-- Error learning schema (Phase 3H)
-- Institutional knowledge: learn from errors to improve future execution

-- Error records table
CREATE TABLE IF NOT EXISTS error_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ DEFAULT now(),

    -- Classification
    category TEXT NOT NULL,  -- api_failure, timeout, rate_limited, etc.
    severity TEXT NOT NULL DEFAULT 'medium',  -- low, medium, high, critical

    -- Context
    task_id TEXT,
    query TEXT,
    instrument TEXT,
    arrangement_type TEXT,
    tool TEXT,

    -- Error details
    error_message TEXT NOT NULL,
    error_type TEXT,  -- Exception class name
    stack_trace TEXT,

    -- Learning context
    query_intent TEXT,
    iteration INTEGER,
    findings_count INTEGER,

    -- Resolution
    was_recovered BOOLEAN DEFAULT false,
    recovery_method TEXT,

    -- Tenant isolation
    app_id UUID REFERENCES apps(id) ON DELETE CASCADE
);

-- Error patterns table
CREATE TABLE IF NOT EXISTS error_patterns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),

    -- Pattern identification
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,

    -- Pattern criteria
    category TEXT NOT NULL,
    instrument TEXT,
    tool TEXT,
    query_pattern TEXT,  -- Keywords or regex

    -- Statistics
    occurrence_count INTEGER DEFAULT 0,
    first_seen TIMESTAMPTZ DEFAULT now(),
    last_seen TIMESTAMPTZ DEFAULT now(),

    -- Learning
    suggested_action TEXT,
    success_after_adjustment INTEGER DEFAULT 0,
    confidence FLOAT DEFAULT 0.5,

    -- Tenant isolation (NULL = global pattern)
    app_id UUID REFERENCES apps(id) ON DELETE CASCADE
);

-- Indexes for error_records
CREATE INDEX idx_error_records_timestamp ON error_records(timestamp DESC);
CREATE INDEX idx_error_records_category ON error_records(category);
CREATE INDEX idx_error_records_instrument ON error_records(instrument);
CREATE INDEX idx_error_records_tool ON error_records(tool);
CREATE INDEX idx_error_records_task_id ON error_records(task_id);
CREATE INDEX idx_error_records_app_id ON error_records(app_id);

-- Indexes for error_patterns
CREATE INDEX idx_error_patterns_category ON error_patterns(category);
CREATE INDEX idx_error_patterns_instrument ON error_patterns(instrument);
CREATE INDEX idx_error_patterns_app_id ON error_patterns(app_id);

-- Enable RLS
ALTER TABLE error_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE error_patterns ENABLE ROW LEVEL SECURITY;

-- Cleanup function for old errors (called by pg_cron)
CREATE OR REPLACE FUNCTION cleanup_old_errors(max_age_days INTEGER DEFAULT 30)
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM error_records
    WHERE timestamp < now() - (max_age_days || ' days')::INTERVAL;

    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Schedule daily cleanup at 3am (uncomment to enable)
-- SELECT cron.schedule('error-cleanup', '0 3 * * *', 'SELECT cleanup_old_errors(30)');
