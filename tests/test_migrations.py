"""Tests for the SQL migration manager."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.timescaledb_exporter.db.migrations.manager import (
    MigrationManager,
)


@pytest.fixture
def tmp_versions_dir(tmp_path: Path) -> Path:
    """Create a temporary migrations/versions directory."""
    versions = tmp_path / "versions"
    versions.mkdir()
    return versions


@pytest.fixture
def mock_pool() -> MagicMock:
    """Return a mock asyncpg pool for migration tests."""
    pool = MagicMock()
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_conn.fetchrow = AsyncMock(return_value={"version": 0})

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = ctx

    # Transaction context manager (must be a plain MagicMock, not AsyncMock,
    # because conn.transaction() is a sync call returning an async CM)
    txn = MagicMock()
    txn.__aenter__ = AsyncMock(return_value=None)
    txn.__aexit__ = AsyncMock(return_value=False)
    mock_conn.transaction = MagicMock(return_value=txn)

    return pool


class TestLoadMigrations:
    """Tests for loading migration files."""

    async def test_load_from_directory(self, tmp_versions_dir: Path) -> None:
        """Test loading SQL files from a directory."""
        (tmp_versions_dir / "V001__create_extensions.sql").write_text("CREATE EXTENSION test;")
        (tmp_versions_dir / "V002__create_tables.sql").write_text("CREATE TABLE test();")

        manager = MigrationManager(MagicMock())
        manager._versions_dir = tmp_versions_dir

        migrations = await manager.load_migrations()
        assert len(migrations) == 2
        assert migrations[0].version == 1
        assert migrations[0].name == "create_extensions"
        assert migrations[1].version == 2
        assert migrations[1].name == "create_tables"

    async def test_load_empty_directory(self, tmp_versions_dir: Path) -> None:
        """Test loading from an empty directory."""
        manager = MigrationManager(MagicMock())
        manager._versions_dir = tmp_versions_dir

        migrations = await manager.load_migrations()
        assert len(migrations) == 0

    async def test_load_sorted_order(self, tmp_versions_dir: Path) -> None:
        """Test migrations are loaded in version order."""
        (tmp_versions_dir / "V003__third.sql").write_text("SELECT 3;")
        (tmp_versions_dir / "V001__first.sql").write_text("SELECT 1;")
        (tmp_versions_dir / "V002__second.sql").write_text("SELECT 2;")

        manager = MigrationManager(MagicMock())
        manager._versions_dir = tmp_versions_dir

        migrations = await manager.load_migrations()
        versions = [m.version for m in migrations]
        assert versions == [1, 2, 3]

    async def test_checksum_computed(self, tmp_versions_dir: Path) -> None:
        """Test that checksums are computed."""
        (tmp_versions_dir / "V001__test.sql").write_text("SELECT 1;")

        manager = MigrationManager(MagicMock())
        manager._versions_dir = tmp_versions_dir

        migrations = await manager.load_migrations()
        assert migrations[0].checksum is not None
        assert len(migrations[0].checksum) == 16

    async def test_nonexistent_directory(self) -> None:
        """Test that a missing directory returns empty list."""
        manager = MigrationManager(MagicMock())
        manager._versions_dir = Path("/nonexistent/path")

        assert await manager.load_migrations() == []


class TestMigrate:
    """Tests for migration execution."""

    async def test_apply_pending_migrations(
        self, tmp_versions_dir: Path, mock_pool: MagicMock
    ) -> None:
        """Test that pending migrations are applied."""
        (tmp_versions_dir / "V001__first.sql").write_text("SELECT 1;")
        (tmp_versions_dir / "V002__second.sql").write_text("SELECT 2;")

        manager = MigrationManager(mock_pool)
        manager._versions_dir = tmp_versions_dir

        count = await manager.migrate()
        assert count == 2

        mock_conn = mock_pool.acquire.return_value.__aenter__.return_value
        # Should have executed: create tracking table + 2 migrations (SQL + INSERT each)
        assert mock_conn.execute.call_count >= 4

    async def test_skip_already_applied(self, tmp_versions_dir: Path, mock_pool: MagicMock) -> None:
        """Test that already-applied migrations are skipped."""
        (tmp_versions_dir / "V001__first.sql").write_text("SELECT 1;")

        manager = MigrationManager(mock_pool)
        manager._versions_dir = tmp_versions_dir

        # Mock that V001 is already applied
        mock_conn = mock_pool.acquire.return_value.__aenter__.return_value
        migrations = await manager.load_migrations()
        mock_conn.fetch.return_value = [{"version": 1, "checksum": migrations[0].checksum}]

        count = await manager.migrate()
        assert count == 0

    async def test_get_current_version(self, mock_pool: MagicMock) -> None:
        """Test getting the current migration version."""
        mock_conn = mock_pool.acquire.return_value.__aenter__.return_value
        mock_conn.fetchrow.return_value = {"version": 5}

        manager = MigrationManager(mock_pool)
        version = await manager.get_current_version()
        assert version == 5
