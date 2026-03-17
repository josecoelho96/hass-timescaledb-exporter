-- Main state changes hypertable
CREATE TABLE IF NOT EXISTS ha_states (
    time            TIMESTAMPTZ      NOT NULL,
    entity_id       TEXT             NOT NULL,
    state           TEXT,
    state_numeric   DOUBLE PRECISION,
    attributes      JSONB,
    context_id      TEXT
);

SELECT create_hypertable('ha_states', by_range('time', INTERVAL '1 day'), if_not_exists => TRUE);

-- Entity metadata lookup table (avoids repeated attribute storage)
CREATE TABLE IF NOT EXISTS ha_entity_metadata (
    entity_id           TEXT PRIMARY KEY,
    domain              TEXT NOT NULL,
    friendly_name       TEXT,
    unit_of_measurement TEXT,
    device_class        TEXT,
    is_numeric          BOOLEAN DEFAULT FALSE,
    first_seen          TIMESTAMPTZ DEFAULT NOW(),
    last_seen           TIMESTAMPTZ DEFAULT NOW()
);
