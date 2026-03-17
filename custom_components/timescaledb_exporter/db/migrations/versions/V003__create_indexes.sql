-- Primary query pattern: look up entity history ordered by time
CREATE INDEX IF NOT EXISTS ix_ha_states_entity_time
    ON ha_states (entity_id, time DESC);

-- Partial index for numeric-only aggregation queries
CREATE INDEX IF NOT EXISTS ix_ha_states_numeric
    ON ha_states (entity_id, time DESC)
    WHERE state_numeric IS NOT NULL;
