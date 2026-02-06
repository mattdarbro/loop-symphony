-- Add webhook_url column to heartbeats table
-- Run this migration in Supabase SQL Editor

ALTER TABLE heartbeats
ADD COLUMN IF NOT EXISTS webhook_url TEXT;

-- Add comment for documentation
COMMENT ON COLUMN heartbeats.webhook_url IS 'Optional URL to POST results when heartbeat completes';
