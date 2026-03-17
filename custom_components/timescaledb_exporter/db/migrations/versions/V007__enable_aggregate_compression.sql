-- Enable compression on continuous aggregates for storage efficiency

ALTER MATERIALIZED VIEW ha_states_5min SET (
    timescaledb.compress
);
SELECT add_compression_policy('ha_states_5min', INTERVAL '7 days', if_not_exists => TRUE);

ALTER MATERIALIZED VIEW ha_states_hourly SET (
    timescaledb.compress
);
SELECT add_compression_policy('ha_states_hourly', INTERVAL '30 days', if_not_exists => TRUE);

ALTER MATERIALIZED VIEW ha_states_daily SET (
    timescaledb.compress
);
SELECT add_compression_policy('ha_states_daily', INTERVAL '90 days', if_not_exists => TRUE);

ALTER MATERIALIZED VIEW ha_state_changes_hourly SET (
    timescaledb.compress
);
SELECT add_compression_policy('ha_state_changes_hourly', INTERVAL '30 days', if_not_exists => TRUE);

ALTER MATERIALIZED VIEW ha_state_changes_daily SET (
    timescaledb.compress
);
SELECT add_compression_policy('ha_state_changes_daily', INTERVAL '90 days', if_not_exists => TRUE);
