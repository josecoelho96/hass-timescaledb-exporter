"""Lightweight SQL migration runner with version tracking for TimescaleDB."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import logging
from pathlib import Path

import asyncpg

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Migration:
    """Represents a single SQL migration file."""

    version: int
    name: str
    sql: str
    checksum: str


class MigrationManager:
    """Run and track SQL migrations against TimescaleDB.

    Migrations are loaded from the versions/ directory next to this file.
    Files must follow the naming convention: V001__description.sql
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        """Initialize the migration manager."""
        self._pool = pool
        self._versions_dir = Path(__file__).parent / "versions"

    async def initialize(self) -> None:
        """Create the migration tracking table if it doesn't exist."""
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version     INTEGER PRIMARY KEY,
                    name        TEXT NOT NULL,
                    checksum    TEXT NOT NULL,
                    applied_at  TIMESTAMPTZ DEFAULT NOW()
                )
            """)

    async def load_migrations(self) -> list[Migration]:
        """Load SQL migration files from the versions/ directory."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._load_migrations_sync)

    def _load_migrations_sync(self) -> list[Migration]:
        """Load SQL migration files synchronously (run in executor)."""
        if not self._versions_dir.exists():
            return []

        migrations: list[Migration] = []
        for sql_file in sorted(self._versions_dir.glob("V*.sql")):
            parts = sql_file.stem.split("__", 1)
            version = int(parts[0][1:])  # strip leading "V"
            name = parts[1] if len(parts) > 1 else sql_file.stem
            sql = sql_file.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode()).hexdigest()[:16]
            migrations.append(Migration(version=version, name=name, sql=sql, checksum=checksum))
        return migrations

    async def get_applied_versions(self) -> dict[int, str]:
        """Return a mapping of version -> checksum for applied migrations."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT version, checksum FROM schema_migrations ORDER BY version"
            )
            return {r["version"]: r["checksum"] for r in rows}

    async def get_current_version(self) -> int:
        """Return the highest applied migration version, or 0 if none applied."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
            )
            return row["version"] if row else 0

    async def migrate(self) -> int:
        """Apply all pending migrations in order.

        Returns the number of migrations applied.
        """
        await self.initialize()
        applied = await self.get_applied_versions()
        migrations = await self.load_migrations()
        count = 0

        for migration in migrations:
            if migration.version in applied:
                if applied[migration.version] != migration.checksum:
                    _LOGGER.warning(
                        "Migration V%03d checksum mismatch: expected %s, found %s. "
                        "This migration was already applied with different content",
                        migration.version,
                        migration.checksum,
                        applied[migration.version],
                    )
                continue

            _LOGGER.info("Applying migration V%03d: %s", migration.version, migration.name)
            async with self._pool.acquire() as conn, conn.transaction():
                await conn.execute(migration.sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (version, name, checksum) VALUES ($1, $2, $3)",
                    migration.version,
                    migration.name,
                    migration.checksum,
                )
            _LOGGER.info("Applied migration V%03d: %s", migration.version, migration.name)
            count += 1

        return count
