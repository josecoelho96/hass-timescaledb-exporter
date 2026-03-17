"""Tests for the policy manager (retention + compression)."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.timescaledb_exporter.db.policies import (
    apply_compression_policy,
    apply_retention_policies,
)


@pytest.fixture
def mock_pool() -> MagicMock:
    """Create a mock asyncpg pool with connection context manager."""
    pool = MagicMock()
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = ctx

    return pool


def _get_conn(pool: MagicMock) -> AsyncMock:
    return pool.acquire.return_value.__aenter__.return_value


class TestApplyRetentionPolicies:
    """Tests for retention policy application."""

    async def test_sets_all_policies(self, mock_pool: MagicMock) -> None:
        """When all values > 0, policies are set for all tables."""
        await apply_retention_policies(
            mock_pool,
            retention_raw_days=30,
            retention_hourly_days=365,
            retention_daily_days=730,
        )
        conn = _get_conn(mock_pool)
        # Each table: remove + add = 2 calls, 6 tables total = 12 calls
        assert conn.execute.call_count == 12

    async def test_removes_policy_when_zero(self, mock_pool: MagicMock) -> None:
        """When days=0, only remove is called (keep forever)."""
        await apply_retention_policies(
            mock_pool,
            retention_raw_days=0,
            retention_hourly_days=0,
            retention_daily_days=0,
        )
        conn = _get_conn(mock_pool)
        # 6 remove calls, no add calls
        assert conn.execute.call_count == 6
        for call in conn.execute.call_args_list:
            assert "remove_retention_policy" in call.args[0]

    async def test_mixed_set_and_remove(self, mock_pool: MagicMock) -> None:
        """Some tables get policies, some get them removed."""
        await apply_retention_policies(
            mock_pool,
            retention_raw_days=365,
            retention_hourly_days=0,
            retention_daily_days=730,
        )
        conn = _get_conn(mock_pool)
        # raw: remove+add(2), 5min: remove+add(2),
        # hourly x2: remove(2), daily x2: remove+add(4) = 10
        assert conn.execute.call_count == 10

    async def test_sql_contains_correct_table_names(self, mock_pool: MagicMock) -> None:
        """Verify the correct table names appear in SQL."""
        await apply_retention_policies(
            mock_pool,
            retention_raw_days=10,
            retention_hourly_days=20,
            retention_daily_days=30,
        )
        conn = _get_conn(mock_pool)
        sql_calls = [call.args[0] for call in conn.execute.call_args_list]
        sql_text = " ".join(sql_calls)
        assert "ha_states" in sql_text
        assert "ha_states_5min" in sql_text
        assert "ha_states_hourly" in sql_text
        assert "ha_states_daily" in sql_text
        assert "ha_state_changes_hourly" in sql_text
        assert "ha_state_changes_daily" in sql_text

    async def test_interval_value_passed(self, mock_pool: MagicMock) -> None:
        """Verify the day interval is passed as the second argument."""
        await apply_retention_policies(
            mock_pool,
            retention_raw_days=42,
            retention_hourly_days=0,
            retention_daily_days=0,
        )
        conn = _get_conn(mock_pool)
        # raw + 5min both get add calls with 42 days
        add_calls = [c for c in conn.execute.call_args_list if "add_retention_policy" in c.args[0]]
        assert len(add_calls) == 2
        assert add_calls[0].args[1] == timedelta(days=42)
        assert add_calls[1].args[1] == timedelta(days=42)


class TestApplyCompressionPolicy:
    """Tests for compression policy application."""

    async def test_removes_then_adds(self, mock_pool: MagicMock) -> None:
        """Compression policy is removed then re-added."""
        await apply_compression_policy(mock_pool, compression_after_days=14)
        conn = _get_conn(mock_pool)
        assert conn.execute.call_count == 2
        assert "remove_compression_policy" in conn.execute.call_args_list[0].args[0]
        assert "add_compression_policy" in conn.execute.call_args_list[1].args[0]

    async def test_interval_value(self, mock_pool: MagicMock) -> None:
        """Correct interval is passed to the add call."""
        await apply_compression_policy(mock_pool, compression_after_days=30)
        conn = _get_conn(mock_pool)
        add_call = conn.execute.call_args_list[1]
        assert add_call.args[1] == timedelta(days=30)
