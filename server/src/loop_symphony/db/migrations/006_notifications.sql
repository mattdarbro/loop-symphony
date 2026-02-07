-- Notifications schema (Phase 3I)
-- Configurable notification preferences and delivery history

-- Notification preferences per user
CREATE TABLE IF NOT EXISTS notification_preferences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    app_id UUID NOT NULL REFERENCES apps(id) ON DELETE CASCADE,

    -- Global preferences
    enabled BOOLEAN DEFAULT true,
    notify_on_complete BOOLEAN DEFAULT true,
    notify_on_failure BOOLEAN DEFAULT true,
    notify_on_heartbeat BOOLEAN DEFAULT true,

    -- Batching
    batch_low_priority BOOLEAN DEFAULT true,
    batch_interval_minutes INTEGER DEFAULT 30,

    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),

    UNIQUE(user_id, app_id)
);

-- Channel configurations (one per channel per user)
CREATE TABLE IF NOT EXISTS notification_channels (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    preferences_id UUID NOT NULL REFERENCES notification_preferences(id) ON DELETE CASCADE,

    -- Channel type
    channel TEXT NOT NULL,  -- telegram, webhook, push, email
    enabled BOOLEAN DEFAULT true,

    -- Channel-specific config
    telegram_chat_id TEXT,
    webhook_url TEXT,
    push_device_token TEXT,
    email_address TEXT,

    -- Preferences
    min_priority TEXT DEFAULT 'normal',  -- low, normal, high, critical
    quiet_hours_start INTEGER,  -- 0-23
    quiet_hours_end INTEGER,    -- 0-23

    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),

    UNIQUE(preferences_id, channel)
);

-- Notification history
CREATE TABLE IF NOT EXISTS notification_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    notification_id UUID NOT NULL,
    user_id UUID REFERENCES user_profiles(id) ON DELETE SET NULL,
    app_id UUID REFERENCES apps(id) ON DELETE SET NULL,

    -- Content
    type TEXT NOT NULL,  -- task_complete, task_failed, heartbeat_result, etc.
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    task_id TEXT,

    created_at TIMESTAMPTZ DEFAULT now()
);

-- Delivery results (one per channel per notification)
CREATE TABLE IF NOT EXISTS notification_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    history_id UUID NOT NULL REFERENCES notification_history(id) ON DELETE CASCADE,

    channel TEXT NOT NULL,
    success BOOLEAN NOT NULL,
    sent_at TIMESTAMPTZ DEFAULT now(),
    error_message TEXT,
    external_id TEXT  -- Message ID from external service
);

-- Indexes
CREATE INDEX idx_notification_preferences_user ON notification_preferences(user_id);
CREATE INDEX idx_notification_preferences_app ON notification_preferences(app_id);
CREATE INDEX idx_notification_channels_prefs ON notification_channels(preferences_id);
CREATE INDEX idx_notification_history_user ON notification_history(user_id);
CREATE INDEX idx_notification_history_created ON notification_history(created_at DESC);
CREATE INDEX idx_notification_results_history ON notification_results(history_id);

-- Enable RLS
ALTER TABLE notification_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_channels ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_results ENABLE ROW LEVEL SECURITY;

-- Cleanup function for old notification history (called by pg_cron)
CREATE OR REPLACE FUNCTION cleanup_old_notifications(max_age_days INTEGER DEFAULT 90)
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM notification_history
    WHERE created_at < now() - (max_age_days || ' days')::INTERVAL;

    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Schedule monthly cleanup (uncomment to enable)
-- SELECT cron.schedule('notification-cleanup', '0 4 1 * *', 'SELECT cleanup_old_notifications(90)');
