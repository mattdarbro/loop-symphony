-- Magenta Loop: content analytics pipeline tables

-- Historical content performance metrics
CREATE TABLE IF NOT EXISTS content_performance (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    app_id UUID REFERENCES apps(id),
    content_id TEXT NOT NULL,
    creator_id TEXT NOT NULL,
    platform TEXT NOT NULL DEFAULT 'youtube',
    title TEXT,
    published_at TIMESTAMPTZ,

    -- Core metrics
    views INTEGER DEFAULT 0,
    likes INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    shares INTEGER DEFAULT 0,
    subscribers_gained INTEGER DEFAULT 0,
    subscribers_lost INTEGER DEFAULT 0,

    -- Retention
    avg_view_duration_seconds FLOAT DEFAULT 0.0,
    avg_view_percentage FLOAT DEFAULT 0.0,
    retention_curve JSONB DEFAULT '[]'::jsonb,
    total_duration_seconds FLOAT DEFAULT 0.0,

    -- Traffic sources & demographics
    traffic_sources JSONB DEFAULT '{}'::jsonb,
    demographics JSONB DEFAULT '{}'::jsonb,

    -- Channel context
    subscriber_count INTEGER DEFAULT 0,
    category TEXT,

    -- Impressions
    impressions INTEGER DEFAULT 0,
    impression_click_through_rate FLOAT DEFAULT 0.0,

    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (app_id, content_id, platform)
);

CREATE INDEX idx_content_perf_creator ON content_performance(creator_id) WHERE is_active = TRUE;
CREATE INDEX idx_content_perf_app ON content_performance(app_id) WHERE is_active = TRUE;
CREATE INDEX idx_content_perf_views ON content_performance(views DESC) WHERE is_active = TRUE;
CREATE INDEX idx_content_perf_created ON content_performance(created_at DESC) WHERE is_active = TRUE;

ALTER TABLE content_performance ENABLE ROW LEVEL SECURITY;


-- YouTube category benchmarks by subscriber tier
CREATE TABLE IF NOT EXISTS content_benchmarks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform TEXT NOT NULL DEFAULT 'youtube',
    category TEXT NOT NULL,
    subscriber_tier TEXT NOT NULL,           -- e.g. '1k-10k', '10k-100k', '100k-1m'
    avg_view_percentage FLOAT DEFAULT 0.0,
    avg_ctr FLOAT DEFAULT 0.0,
    avg_subscriber_feed_ratio FLOAT DEFAULT 0.0,
    avg_browse_traffic_ratio FLOAT DEFAULT 0.0,
    sample_size INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (platform, category, subscriber_tier)
);

CREATE INDEX idx_benchmarks_lookup ON content_benchmarks(platform, category, subscriber_tier) WHERE is_active = TRUE;

ALTER TABLE content_benchmarks ENABLE ROW LEVEL SECURITY;


-- Actionable prescriptions with status tracking
CREATE TABLE IF NOT EXISTS content_prescriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    app_id UUID REFERENCES apps(id),
    creator_id TEXT NOT NULL,
    content_id TEXT NOT NULL,
    diagnosis_type TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    specific_action TEXT NOT NULL,
    reference_content_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',   -- pending, applied, evaluated, skipped
    followup_content_id TEXT,
    effectiveness_score FLOAT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_prescriptions_creator ON content_prescriptions(creator_id) WHERE is_active = TRUE;
CREATE INDEX idx_prescriptions_status ON content_prescriptions(status) WHERE is_active = TRUE;
CREATE INDEX idx_prescriptions_app ON content_prescriptions(app_id) WHERE is_active = TRUE;

ALTER TABLE content_prescriptions ENABLE ROW LEVEL SECURITY;


-- Generated narrative reports
CREATE TABLE IF NOT EXISTS content_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    app_id UUID REFERENCES apps(id),
    creator_id TEXT NOT NULL,
    report_type TEXT NOT NULL DEFAULT 'standard',  -- standard, weekly, urgent
    title TEXT NOT NULL,
    narrative TEXT NOT NULL,
    diagnoses_count INTEGER DEFAULT 0,
    prescriptions_count INTEGER DEFAULT 0,
    tracking_summary TEXT,
    notification_payload JSONB DEFAULT '{}'::jsonb,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_reports_creator ON content_reports(creator_id) WHERE is_active = TRUE;
CREATE INDEX idx_reports_app ON content_reports(app_id) WHERE is_active = TRUE;
CREATE INDEX idx_reports_created ON content_reports(created_at DESC) WHERE is_active = TRUE;

ALTER TABLE content_reports ENABLE ROW LEVEL SECURITY;
