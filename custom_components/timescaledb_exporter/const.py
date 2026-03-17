"""Constants for the TimescaleDB Exporter integration."""

DOMAIN = "timescaledb_exporter"

# Config keys
CONF_DATABASE = "database"
CONF_SSL = "ssl"

# Option keys
CONF_BATCH_SIZE = "batch_size"
CONF_FLUSH_INTERVAL = "flush_interval"
CONF_EXCLUDED_ENTITY_GLOBS = "excluded_entity_globs"
CONF_EXCLUDED_DOMAINS = "excluded_domains"
CONF_COMPRESSION_AFTER_DAYS = "compression_after_days"
CONF_RETENTION_RAW_DAYS = "retention_raw_days"
CONF_RETENTION_HOURLY_DAYS = "retention_hourly_days"
CONF_RETENTION_DAILY_DAYS = "retention_daily_days"
CONF_CHUNK_INTERVAL_HOURS = "chunk_interval_hours"

# Defaults
DEFAULT_PORT = 5432
DEFAULT_DATABASE = "homeassistant"
DEFAULT_BATCH_SIZE = 50
DEFAULT_FLUSH_INTERVAL = 1
DEFAULT_COMPRESSION_AFTER_DAYS = 7
DEFAULT_RETENTION_RAW_DAYS = 365
DEFAULT_RETENTION_HOURLY_DAYS = 730
DEFAULT_RETENTION_DAILY_DAYS = 0  # 0 = keep forever
DEFAULT_CHUNK_INTERVAL_HOURS = 24
DEFAULT_MAX_QUEUE_SIZE = 10000

# State values to ignore for numeric parsing
IGNORED_STATES = frozenset({"unavailable", "unknown", "none", ""})
