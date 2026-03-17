-- Retention policy: drop raw data chunks older than 1 year
SELECT add_retention_policy('ha_states', INTERVAL '365 days', if_not_exists => TRUE);

-- Retention policy: drop 5-minute aggregates older than 1 year (same as raw)
SELECT add_retention_policy('ha_states_5min', INTERVAL '365 days', if_not_exists => TRUE);

-- Retention policy: drop hourly aggregates older than 2 years
SELECT add_retention_policy('ha_states_hourly', INTERVAL '730 days', if_not_exists => TRUE);

-- No retention on daily aggregates by default — keep forever
