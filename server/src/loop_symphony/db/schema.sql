-- Loop Symphony Database Schema
-- Run this in Supabase SQL Editor to set up tables

-- Tasks table - stores task requests and responses
CREATE TABLE IF NOT EXISTS tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, running, complete, failed
    outcome TEXT,                             -- complete, saturated, bounded, inconclusive
    response JSONB,
    error TEXT,                               -- Error message if failed
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

-- Index for status queries
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);

-- Index for created_at queries
CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at DESC);

-- Task iterations table - for debugging and learning
CREATE TABLE IF NOT EXISTS task_iterations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
    iteration_num INT NOT NULL,
    phase TEXT NOT NULL,                      -- problem, hypothesis, test, analysis, reflection
    input JSONB,
    output JSONB,
    duration_ms INT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for task_id lookups
CREATE INDEX IF NOT EXISTS idx_task_iterations_task_id ON task_iterations(task_id);

-- Function to auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Trigger to auto-update updated_at
DROP TRIGGER IF EXISTS update_tasks_updated_at ON tasks;
CREATE TRIGGER update_tasks_updated_at
    BEFORE UPDATE ON tasks
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Enable Row Level Security (RLS) - configure as needed
ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE task_iterations ENABLE ROW LEVEL SECURITY;

-- Default policy: allow all for service role (adjust for production)
CREATE POLICY "Service role can do all on tasks"
    ON tasks FOR ALL
    USING (true)
    WITH CHECK (true);

CREATE POLICY "Service role can do all on task_iterations"
    ON task_iterations FOR ALL
    USING (true)
    WITH CHECK (true);
