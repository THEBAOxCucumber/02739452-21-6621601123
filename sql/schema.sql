-- Common schema for every source (NASA EONET, GDACS, USGS, ReliefWeb HTML).
CREATE TABLE IF NOT EXISTS disaster_events (
  id BIGSERIAL PRIMARY KEY,
  source_name TEXT NOT NULL,
  source_event_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  event_name TEXT,
  event_time TIMESTAMPTZ NOT NULL,
  latitude DOUBLE PRECISION NOT NULL CHECK (latitude BETWEEN -90 AND 90),
  longitude DOUBLE PRECISION NOT NULL CHECK (longitude BETWEEN -180 AND 180),
  magnitude DOUBLE PRECISION,
  magnitude_unit TEXT,
  severity TEXT,
  country TEXT,
  source_url TEXT,
  raw_data JSONB NOT NULL DEFAULT '{}'::jsonb,
  -- Cross-source de-duplication: points at the canonical row when this event was
  -- also reported by a higher-priority source (rules in src/database/postgres.py).
  duplicate_of BIGINT REFERENCES disaster_events(id) ON DELETE SET NULL,
  duplicate_rule TEXT,
  fetched_at TIMESTAMPTZ NOT NULL,             -- when the source was last fetched
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),  -- first insert
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),   -- last UPSERT
  CONSTRAINT uq_disaster_events_source UNIQUE (source_name, source_event_id)
);
CREATE INDEX IF NOT EXISTS idx_events_time ON disaster_events (event_time DESC);
CREATE INDEX IF NOT EXISTS idx_events_type ON disaster_events (event_type);
CREATE INDEX IF NOT EXISTS idx_events_source ON disaster_events (source_name);
CREATE INDEX IF NOT EXISTS idx_events_lat_lon ON disaster_events (latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_events_canonical ON disaster_events (event_time DESC) WHERE duplicate_of IS NULL;

-- Rows that failed validation, with the reason. Re-running updates last_seen_at
-- instead of adding new copies.
CREATE TABLE IF NOT EXISTS data_quarantine (
  id BIGSERIAL PRIMARY KEY,
  source_name TEXT NOT NULL,
  source_event_id TEXT NOT NULL DEFAULT '',
  reason TEXT NOT NULL,
  raw_data JSONB NOT NULL DEFAULT '{}'::jsonb,
  dag_run_id TEXT,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_quarantine UNIQUE (source_name, source_event_id, reason)
);

-- One row per source per DAG run plus an '__overall__' row.
CREATE TABLE IF NOT EXISTS pipeline_runs (
  id BIGSERIAL PRIMARY KEY,
  dag_id TEXT NOT NULL,
  dag_run_id TEXT NOT NULL,
  source_name TEXT NOT NULL,
  status TEXT NOT NULL,
  records_extracted INTEGER NOT NULL DEFAULT 0,
  records_loaded INTEGER NOT NULL DEFAULT 0,
  records_quarantined INTEGER NOT NULL DEFAULT 0,
  message TEXT,
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_pipeline_runs UNIQUE (dag_run_id, source_name)
);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_finished ON pipeline_runs (finished_at DESC);

CREATE TABLE IF NOT EXISTS data_quality_results (
  id BIGSERIAL PRIMARY KEY,
  dag_run_id TEXT NOT NULL,
  check_name TEXT NOT NULL,
  passed BOOLEAN NOT NULL,
  observed_value TEXT,
  expectation TEXT,
  checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_quality UNIQUE (dag_run_id, check_name)
);
