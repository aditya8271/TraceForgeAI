CREATE TABLE IF NOT EXISTS public_data_cache (
    id SMALLINT PRIMARY KEY CHECK (id = 1),
    payload JSONB,
    refresh_status JSONB,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text
);
