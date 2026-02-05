-- Migration: Identity and Heartbeat System
-- Enables multi-tenant support with app_id/user_id and scheduled recurring tasks

-- Apps table (manually populated for MVP)
CREATE TABLE IF NOT EXISTS apps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    api_key TEXT NOT NULL UNIQUE,
    description TEXT,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- User profiles (per-app users)
CREATE TABLE IF NOT EXISTS user_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    app_id UUID NOT NULL REFERENCES apps(id) ON DELETE CASCADE,
    external_user_id TEXT NOT NULL,  -- iOS device/user ID from the app
    display_name TEXT,
    preferences JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now(),
    last_seen_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(app_id, external_user_id)
);

-- Heartbeat definitions (recurring task templates)
CREATE TABLE IF NOT EXISTS heartbeats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    app_id UUID NOT NULL REFERENCES apps(id) ON DELETE CASCADE,
    user_id UUID REFERENCES user_profiles(id) ON DELETE CASCADE,  -- NULL = app-wide
    name TEXT NOT NULL,
    query_template TEXT NOT NULL,  -- May contain {date}, {user_name} placeholders
    cron_expression TEXT NOT NULL,  -- e.g., "0 7 * * *" for 7am daily
    timezone TEXT DEFAULT 'UTC',
    is_active BOOLEAN DEFAULT true,
    context_template JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Heartbeat run history
CREATE TABLE IF NOT EXISTS heartbeat_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    heartbeat_id UUID NOT NULL REFERENCES heartbeats(id) ON DELETE CASCADE,
    task_id UUID REFERENCES tasks(id),  -- Link to actual task execution
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, running, completed, failed
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_user_profiles_app_id ON user_profiles(app_id);
CREATE INDEX IF NOT EXISTS idx_user_profiles_external_id ON user_profiles(app_id, external_user_id);
CREATE INDEX IF NOT EXISTS idx_heartbeats_app_id ON heartbeats(app_id);
CREATE INDEX IF NOT EXISTS idx_heartbeats_user_id ON heartbeats(user_id);
CREATE INDEX IF NOT EXISTS idx_heartbeats_active ON heartbeats(is_active) WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_heartbeat_runs_heartbeat_id ON heartbeat_runs(heartbeat_id);
CREATE INDEX IF NOT EXISTS idx_heartbeat_runs_status ON heartbeat_runs(status);
CREATE INDEX IF NOT EXISTS idx_heartbeat_runs_pending ON heartbeat_runs(status) WHERE status = 'pending';

-- RLS Policies (enable row level security for app isolation)
ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE heartbeats ENABLE ROW LEVEL SECURITY;
ALTER TABLE heartbeat_runs ENABLE ROW LEVEL SECURITY;

-- Note: pg_cron setup requires superuser access in Supabase
-- Run this in the Supabase SQL editor with appropriate permissions:
--
-- CREATE EXTENSION IF NOT EXISTS pg_cron;
--
-- CREATE OR REPLACE FUNCTION heartbeat_tick()
-- RETURNS void AS $$
-- DECLARE
--     hb RECORD;
-- BEGIN
--     FOR hb IN
--         SELECT h.id
--         FROM heartbeats h
--         WHERE h.is_active = true
--         -- In production, add cron expression matching logic here
--     LOOP
--         INSERT INTO heartbeat_runs (heartbeat_id, status)
--         VALUES (hb.id, 'pending');
--     END LOOP;
-- END;
-- $$ LANGUAGE plpgsql;
--
-- SELECT cron.schedule('heartbeat-tick', '* * * * *', 'SELECT heartbeat_tick()');
