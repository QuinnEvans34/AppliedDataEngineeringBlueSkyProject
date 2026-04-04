#!/usr/bin/env python3
"""One-time local-first snapshot for Snowflake Twitter trending dataset."""

from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

try:
    import snowflake.connector
except Exception as exc:  # pragma: no cover
    raise RuntimeError(
        "snowflake-connector-python is required to run this script"
    ) from exc


DEFAULT_SOURCE_TABLE = "DAILY_TWITTER_TOP_TRENDS.DIESEL.TWITTER_TRENDING"
DEFAULT_SAMPLE_SIZE = 1000
FULL_SNAPSHOT_PATH = Path("local/reference_snapshots/twitter_trending/twitter_trending_full.parquet")
METADATA_PATH = Path(
    "local/reference_snapshots/twitter_trending/twitter_trending_snapshot_metadata.json"
)
SAMPLE_PARQUET_PATH = Path("data/samples/twitter_trending_sample_1000.parquet")
SAMPLE_CSV_PATH = Path("data/samples/twitter_trending_sample_1000.csv")

REQUIRED_ENV_VARS = (
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_USER",
    "SNOWFLAKE_PASSWORD",
    "SNOWFLAKE_ROLE",
    "SNOWFLAKE_WAREHOUSE",
    "SNOWFLAKE_DATABASE",
    "SNOWFLAKE_SCHEMA",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Extract Snowflake Twitter trending table once and preserve it locally "
            "for local-only downstream development."
        )
    )
    parser.add_argument("--source-table", default=DEFAULT_SOURCE_TABLE)
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.sample_size < 0:
        raise ValueError("sample-size must be >= 0")

    _ensure_required_env_vars()
    _prepare_output_paths(
        full_snapshot=FULL_SNAPSHOT_PATH,
        metadata_path=METADATA_PATH,
        sample_parquet=SAMPLE_PARQUET_PATH,
        sample_csv=SAMPLE_CSV_PATH,
    )

    query = f"SELECT * FROM {args.source_table}"
    extraction_started_at = datetime.now(timezone.utc)

    conn = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        role=os.environ["SNOWFLAKE_ROLE"],
        warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
        database=os.environ["SNOWFLAKE_DATABASE"],
        schema=os.environ["SNOWFLAKE_SCHEMA"],
        autocommit=True,
    )

    row_count = 0
    schema: pa.Schema | None = None
    query_id: str | None = None
    sample_tables: list[pa.Table] = []
    sample_rows_collected = 0
    parquet_writer: pq.ParquetWriter | None = None

    try:
        cursor = conn.cursor()
        try:
            cursor.execute(query)
            query_id = cursor.sfqid

            for batch in cursor.fetch_arrow_batches():
                table = _as_arrow_table(batch)
                if table.num_rows == 0:
                    continue

                if schema is None:
                    schema = table.schema
                    parquet_writer = pq.ParquetWriter(str(FULL_SNAPSHOT_PATH), schema=schema)

                row_count += table.num_rows
                assert parquet_writer is not None
                parquet_writer.write_table(table)

                remaining = args.sample_size - sample_rows_collected
                if remaining > 0:
                    take_rows = min(remaining, table.num_rows)
                    sample_tables.append(table.slice(0, take_rows))
                    sample_rows_collected += take_rows
        finally:
            cursor.close()
    finally:
        if parquet_writer is not None:
            parquet_writer.close()
        conn.close()

    if schema is None:
        # Preserve an empty snapshot in a valid parquet format if table has no rows.
        schema = pa.schema([])
        pq.write_table(pa.table({}), str(FULL_SNAPSHOT_PATH))

    sample_table = _build_sample_table(sample_tables, schema=schema)
    pq.write_table(sample_table, str(SAMPLE_PARQUET_PATH))
    _write_sample_csv(sample_table, SAMPLE_CSV_PATH)

    extraction_completed_at = datetime.now(timezone.utc)
    metadata = {
        "source_table": args.source_table,
        "query": query,
        "query_id": query_id,
        "query_count": 1,
        "extraction_started_at_utc": extraction_started_at.isoformat(),
        "extraction_completed_at_utc": extraction_completed_at.isoformat(),
        "row_count": row_count,
        "column_names": list(sample_table.schema.names if row_count == 0 else schema.names),
        "column_dtypes": {field.name: str(field.type) for field in schema},
        "local_file_path": str(FULL_SNAPSHOT_PATH.resolve()),
        "sample_file_paths": {
            "parquet": str(SAMPLE_PARQUET_PATH.resolve()),
            "csv": str(SAMPLE_CSV_PATH.resolve()),
        },
        "notes": [
            "Single-query extraction from Snowflake marketplace source.",
            "Row counts, schema metadata, and sample files were derived locally after fetch.",
            "Designed for local-only downstream development without repeated Snowflake reads.",
        ],
    }

    METADATA_PATH.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata, indent=2))
    return 0


def _ensure_required_env_vars() -> None:
    missing = [name for name in REQUIRED_ENV_VARS if not (os.getenv(name) or "").strip()]
    if missing:
        raise ValueError(
            "Missing required Snowflake environment variables: " + ", ".join(missing)
        )


def _prepare_output_paths(
    *,
    full_snapshot: Path,
    metadata_path: Path,
    sample_parquet: Path,
    sample_csv: Path,
) -> None:
    for path in (full_snapshot, metadata_path, sample_parquet, sample_csv):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()


def _as_arrow_table(batch: Any) -> pa.Table:
    if isinstance(batch, pa.Table):
        return batch
    if isinstance(batch, pa.RecordBatch):
        return pa.Table.from_batches([batch])
    raise TypeError(f"Unexpected Arrow batch type: {type(batch)!r}")


def _build_sample_table(sample_tables: list[pa.Table], *, schema: pa.Schema) -> pa.Table:
    if sample_tables:
        if len(sample_tables) == 1:
            return sample_tables[0]
        return pa.concat_tables(sample_tables)

    return pa.Table.from_arrays(
        arrays=[pa.array([], type=field.type) for field in schema],
        names=[field.name for field in schema],
    )


def _write_sample_csv(table: pa.Table, path: Path) -> None:
    columns = table.column_names
    rows = table.to_pylist()

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_cell(value) for key, value in row.items()})


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return json.dumps(value, ensure_ascii=True, default=str)


if __name__ == "__main__":
    raise SystemExit(main())
