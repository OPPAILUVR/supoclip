CREATE TABLE IF NOT EXISTS live_streamers (
    id VARCHAR(36) PRIMARY KEY DEFAULT uuid_generate_v4()::text,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    platform VARCHAR(32) NOT NULL,
    channel_url VARCHAR(500) NOT NULL,
    channel_handle VARCHAR(100),
    is_live BOOLEAN NOT NULL DEFAULT false,
    current_stream_title VARCHAR(500),
    current_stream_url TEXT,
    current_stream_id VARCHAR(255),
    last_checked_at TIMESTAMP WITH TIME ZONE,
    last_live_at TIMESTAMP WITH TIME ZONE,
    is_active BOOLEAN NOT NULL DEFAULT true,
    buffer_minutes INTEGER NOT NULL DEFAULT 10,
    min_virality_score INTEGER NOT NULL DEFAULT 75,
    current_task_id VARCHAR(36) REFERENCES tasks(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS live_stream_events (
    id VARCHAR(36) PRIMARY KEY DEFAULT uuid_generate_v4()::text,
    streamer_id VARCHAR(36) NOT NULL REFERENCES live_streamers(id) ON DELETE CASCADE,
    task_id VARCHAR(36) REFERENCES tasks(id) ON DELETE SET NULL,
    clip_id VARCHAR(36) REFERENCES generated_clips(id) ON DELETE SET NULL,
    event_type VARCHAR(50) NOT NULL,
    title VARCHAR(500),
    virality_score INTEGER,
    details JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_live_streamers_user ON live_streamers(user_id);
CREATE INDEX IF NOT EXISTS idx_live_streamers_active ON live_streamers(is_active);
CREATE INDEX IF NOT EXISTS idx_live_stream_events_streamer ON live_stream_events(streamer_id);
