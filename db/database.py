"""Async Azure SQL access via aioodbc.

All queries are parameterized (``?`` placeholders) — never f-string SQL (CLAUDE.md).
"""

import logging
from typing import Any

import aioodbc

logger = logging.getLogger(__name__)


class Database:
    """A thin async wrapper around an aioodbc connection pool."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: aioodbc.Pool | None = None

    async def connect(self) -> None:
        """Open the connection pool (idempotent)."""
        if self._pool is None:
            self._pool = await aioodbc.create_pool(dsn=self._dsn, autocommit=True)
            logger.info("Opened Azure SQL connection pool")

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool is not None:
            self._pool.close()
            await self._pool.wait_closed()
            self._pool = None
            logger.info("Closed Azure SQL connection pool")

    def _require_pool(self) -> aioodbc.Pool:
        if self._pool is None:
            raise RuntimeError("Database pool is not open; call connect() first.")
        return self._pool

    @staticmethod
    def _rows_to_dicts(cursor: Any, rows: list[Any]) -> list[dict[str, Any]]:
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row, strict=False)) for row in rows]

    async def fetch_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        """Run a query and return all rows as dicts."""
        pool = self._require_pool()
        async with pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(sql, *params)
            rows = await cur.fetchall()
            return self._rows_to_dicts(cur, rows)

    async def fetch_one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        """Run a query and return the first row as a dict, or None."""
        rows = await self.fetch_all(sql, params)
        return rows[0] if rows else None

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        """Run a non-query statement; return affected row count."""
        pool = self._require_pool()
        async with pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(sql, *params)
            return cur.rowcount
