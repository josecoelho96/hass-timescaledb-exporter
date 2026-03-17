-- Enable compression on the hypertable
-- segmentby entity_id: groups all rows for one entity together (matches query pattern)
-- orderby time DESC: enables efficient range scans within compressed segments
ALTER TABLE ha_states SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'entity_id',
    timescaledb.compress_orderby = 'time DESC'
);

-- Auto-compress chunks older than 7 days
SELECT add_compression_policy('ha_states', INTERVAL '7 days', if_not_exists => TRUE);
