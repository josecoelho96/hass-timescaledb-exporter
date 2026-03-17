-- 5-minute continuous aggregate for high-frequency numeric sensors
CREATE MATERIALIZED VIEW IF NOT EXISTS ha_states_5min
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('5 minutes', time)  AS bucket,
    entity_id,
    AVG(state_numeric)              AS avg_value,
    MIN(state_numeric)              AS min_value,
    MAX(state_numeric)              AS max_value,
    COUNT(*)                        AS sample_count,
    LAST(state_numeric, time)       AS last_value,
    FIRST(state_numeric, time)      AS first_value
FROM ha_states
WHERE state_numeric IS NOT NULL
GROUP BY bucket, entity_id
WITH NO DATA;

-- Refresh every 5 minutes, look back 1 day for late-arriving data
SELECT add_continuous_aggregate_policy('ha_states_5min',
    start_offset    => INTERVAL '1 day',
    end_offset      => INTERVAL '5 minutes',
    schedule_interval => INTERVAL '5 minutes',
    if_not_exists   => TRUE
);

-- Hourly continuous aggregate (hierarchical, built on 5-minute)
CREATE MATERIALIZED VIEW IF NOT EXISTS ha_states_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', bucket)   AS bucket,
    entity_id,
    AVG(avg_value)                  AS avg_value,
    MIN(min_value)                  AS min_value,
    MAX(max_value)                  AS max_value,
    SUM(sample_count)               AS sample_count,
    LAST(last_value, bucket)        AS last_value,
    FIRST(first_value, bucket)      AS first_value
FROM ha_states_5min
GROUP BY time_bucket('1 hour', bucket), entity_id
WITH NO DATA;

-- Refresh hourly, look back 3 days for late-arriving data
SELECT add_continuous_aggregate_policy('ha_states_hourly',
    start_offset    => INTERVAL '3 days',
    end_offset      => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists   => TRUE
);

-- Daily continuous aggregate (hierarchical, built on hourly)
CREATE MATERIALIZED VIEW IF NOT EXISTS ha_states_daily
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', bucket)    AS bucket,
    entity_id,
    AVG(avg_value)                  AS avg_value,
    MIN(min_value)                  AS min_value,
    MAX(max_value)                  AS max_value,
    SUM(sample_count)               AS sample_count,
    LAST(last_value, bucket)        AS last_value,
    FIRST(first_value, bucket)      AS first_value
FROM ha_states_hourly
GROUP BY time_bucket('1 day', bucket), entity_id
WITH NO DATA;

-- Refresh daily, look back 7 days
SELECT add_continuous_aggregate_policy('ha_states_daily',
    start_offset    => INTERVAL '7 days',
    end_offset      => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 day',
    if_not_exists   => TRUE
);

-- State change tracking for binary/enum entities (hourly)
CREATE MATERIALIZED VIEW IF NOT EXISTS ha_state_changes_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time)     AS bucket,
    entity_id,
    state,
    COUNT(*)                        AS state_change_count
FROM ha_states
GROUP BY bucket, entity_id, state
WITH NO DATA;

SELECT add_continuous_aggregate_policy('ha_state_changes_hourly',
    start_offset    => INTERVAL '3 days',
    end_offset      => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists   => TRUE
);

-- Daily state change rollup (hierarchical, built on hourly)
CREATE MATERIALIZED VIEW IF NOT EXISTS ha_state_changes_daily
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', bucket)    AS bucket,
    entity_id,
    state,
    SUM(state_change_count)         AS state_change_count
FROM ha_state_changes_hourly
GROUP BY time_bucket('1 day', bucket), entity_id, state
WITH NO DATA;

SELECT add_continuous_aggregate_policy('ha_state_changes_daily',
    start_offset    => INTERVAL '7 days',
    end_offset      => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 day',
    if_not_exists   => TRUE
);
