"""Snowflake connection/session helpers for loader operations."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from snowflake_loader.config import LoaderConfig

try:
    import snowflake.connector
except Exception:  # pragma: no cover - runtime dependency presence check
    snowflake = None


class SnowflakeSession:
    """Small wrapper around a Snowflake connector connection."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    @classmethod
    def connect_from_config(cls, config: LoaderConfig) -> "SnowflakeSession":
        if snowflake is None:
            raise RuntimeError(
                "snowflake-connector-python is not installed. "
                "Install it before running non-dry loader runs."
            )

        connection = snowflake.connector.connect(
            account=config.auth.account,
            user=config.auth.user,
            password=config.auth.password,
            role=config.auth.role,
            warehouse=config.auth.warehouse,
            database=config.auth.database,
            schema=config.auth.schema,
            autocommit=True,
        )
        session = cls(connection)
        session.execute(
            "ALTER SESSION SET QUERY_TAG = %s",
            (f"bluesky_loader:{config.load_invocation_id}",),
        )
        return session

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "SnowflakeSession":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        self.close()

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> list[Any]:
        cursor = self._connection.cursor()
        try:
            if params is None:
                cursor.execute(sql)
            else:
                cursor.execute(sql, params)
            try:
                return cursor.fetchall()
            except Exception:
                return []
        finally:
            cursor.close()

    def execute_scalar(self, sql: str, params: Sequence[Any] | None = None) -> Any:
        rows = self.execute(sql, params)
        if not rows:
            return None
        return rows[0][0]
