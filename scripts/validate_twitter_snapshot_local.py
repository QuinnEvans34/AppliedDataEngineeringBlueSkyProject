#!/usr/bin/env python3
"""Validate local Twitter snapshot artifacts (local-only, no Snowflake queries)."""

from __future__ import annotations

import argparse
import importlib.util
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

EXPECTED_METADATA_FIELDS: tuple[str, ...] = (
    "source_table",
    "extraction_started_at_utc",
    "extraction_completed_at_utc",
    "row_count",
    "column_names",
    "local_file_path",
    "sample_file_paths",
)


def _load_run_preflight() -> Callable[[], dict[str, Any]]:
    try:
        from preflight_local_data_env import run_preflight as _run_preflight

        return _run_preflight
    except ModuleNotFoundError:
        module_path = Path(__file__).with_name("preflight_local_data_env.py")
        spec = importlib.util.spec_from_file_location(
            "preflight_local_data_env", module_path
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Unable to load preflight_local_data_env.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        return module.run_preflight


run_preflight = _load_run_preflight()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate local Twitter snapshot artifacts without Snowflake access."
    )
    parser.add_argument(
        "--full-parquet",
        type=Path,
        default=Path(
            "local/reference_snapshots/twitter_trending/twitter_trending_full.parquet"
        ),
    )
    parser.add_argument(
        "--metadata-json",
        type=Path,
        default=Path(
            "local/reference_snapshots/twitter_trending/twitter_trending_snapshot_metadata.json"
        ),
    )
    parser.add_argument(
        "--sample-parquet",
        type=Path,
        default=Path("data/samples/twitter_trending_sample_1000.parquet"),
    )
    parser.add_argument(
        "--sample-csv",
        type=Path,
        default=Path("data/samples/twitter_trending_sample_1000.csv"),
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=Path(
            "local/reference_snapshots/twitter_trending/twitter_trending_validation_report.json"
        ),
    )
    return parser


def validate_local_snapshot(
    *,
    full_parquet_path: Path,
    metadata_json_path: Path,
    sample_parquet_path: Path,
    sample_csv_path: Path,
    run_env_preflight: bool = True,
) -> dict[str, Any]:
    warnings: list[str] = []
    failures: list[str] = []

    artifact_existence = {
        "full_parquet": full_parquet_path.exists(),
        "metadata_json": metadata_json_path.exists(),
        "sample_parquet": sample_parquet_path.exists(),
        "sample_csv": sample_csv_path.exists(),
    }
    for key, exists in artifact_existence.items():
        if not exists:
            failures.append(f"missing_file:{key}")

    metadata = _load_metadata(metadata_json_path) if artifact_existence["metadata_json"] else None
    if metadata is None:
        failures.append("metadata_json_parse_failed")
        metadata_parse = {
            "parsed": False,
            "error": "metadata_json_missing_or_unparseable",
            "top_level_fields": [],
            "expected_fields_present": [],
            "expected_fields_missing": list(EXPECTED_METADATA_FIELDS),
        }
    else:
        top_level = sorted(metadata.keys())
        present = [field for field in EXPECTED_METADATA_FIELDS if field in metadata]
        missing = [field for field in EXPECTED_METADATA_FIELDS if field not in metadata]
        metadata_parse = {
            "parsed": True,
            "error": None,
            "top_level_fields": top_level,
            "expected_fields_present": present,
            "expected_fields_missing": missing,
        }
        if missing:
            warnings.append("metadata_missing_some_expected_fields")

    full_info, full_df = _load_dataframe_info(
        full_parquet_path, loader=pd.read_parquet, loader_name="parquet"
    )
    if not full_info["loaded"]:
        failures.append("full_parquet_load_failed")

    sample_parquet_info, sample_parquet_df = _load_dataframe_info(
        sample_parquet_path, loader=pd.read_parquet, loader_name="parquet"
    )
    if not sample_parquet_info["loaded"]:
        failures.append("sample_parquet_load_failed")

    sample_csv_info, sample_csv_df = _load_dataframe_info(
        sample_csv_path, loader=pd.read_csv, loader_name="csv"
    )
    if not sample_csv_info["loaded"]:
        failures.append("sample_csv_load_failed")

    metadata_vs_parquet = _compare_metadata_to_parquet(
        metadata=metadata,
        full_info=full_info,
        full_parquet_path=full_parquet_path,
        sample_parquet_path=sample_parquet_path,
        sample_csv_path=sample_csv_path,
    )
    warnings.extend(metadata_vs_parquet["warnings"])
    failures.extend(metadata_vs_parquet["failures"])

    sample_vs_full = _compare_samples_to_full(
        full_df=full_df,
        sample_parquet_df=sample_parquet_df,
        sample_csv_df=sample_csv_df,
    )
    warnings.extend(sample_vs_full["warnings"])
    failures.extend(sample_vs_full["failures"])

    if run_env_preflight:
        import_checks = run_preflight()
    else:
        import_checks = {
            "timestamp_utc": None,
            "imports": {},
            "status": "skipped",
            "failures": [],
            "overall_pass": None,
        }

    if run_env_preflight and import_checks.get("status") != "pass":
        failures.append("environment_import_preflight_failed")

    status = _derive_status(warnings=warnings, failures=failures)
    recommended_next_step = _recommended_next_step(status=status)

    legacy_consistency = _build_legacy_consistency(
        metadata_vs_parquet_results=metadata_vs_parquet["results"],
        sample_vs_full_results=sample_vs_full["results"],
    )

    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "overall_status": status,
        "artifact_existence": artifact_existence,
        "file_existence": artifact_existence,
        "import_checks": import_checks,
        "loads": {
            "full_parquet": full_info,
            "sample_parquet": sample_parquet_info,
            "sample_csv": sample_csv_info,
        },
        "metadata_parse": metadata_parse,
        "metadata_vs_parquet": {
            "checks_performed": metadata_vs_parquet["checks_performed"],
            "checks_skipped": metadata_vs_parquet["checks_skipped"],
            "results": metadata_vs_parquet["results"],
        },
        "sample_vs_full": sample_vs_full["results"],
        "consistency": legacy_consistency,
        "dataset_summary": {
            "full_snapshot": _dataset_summary_for_report(full_info),
            "sample_parquet": _dataset_summary_for_report(sample_parquet_info),
            "sample_csv": _dataset_summary_for_report(sample_csv_info),
        },
        "warnings": sorted(set(warnings)),
        "failures": sorted(set(failures)),
        "blocking_issues": sorted(set(failures)),
        "recommended_next_step": recommended_next_step,
        "can_proceed_to_local_profiling": status != "fail",
        "overall_pass": status != "fail",
    }
    return report


def _load_metadata(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _load_dataframe_info(
    path: Path,
    *,
    loader: Callable[[Path], pd.DataFrame],
    loader_name: str,
) -> tuple[dict[str, Any], pd.DataFrame | None]:
    if not path.exists():
        return {
            "loaded": False,
            "loader": loader_name,
            "error": "file_not_found",
            "row_count": None,
            "column_count": None,
            "column_names": [],
            "dtypes": {},
            "null_counts_by_column": {},
            "duplicate_row_count": None,
            "preview_rows": [],
        }, None

    try:
        df = loader(path)
    except Exception as exc:
        return {
            "loaded": False,
            "loader": loader_name,
            "error": f"{type(exc).__name__}: {exc}",
            "row_count": None,
            "column_count": None,
            "column_names": [],
            "dtypes": {},
            "null_counts_by_column": {},
            "duplicate_row_count": None,
            "preview_rows": [],
        }, None

    info = {
        "loaded": True,
        "loader": loader_name,
        "error": None,
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "column_names": list(df.columns),
        "dtypes": {column: str(dtype) for column, dtype in df.dtypes.items()},
        "null_counts_by_column": {
            column: int(count) for column, count in df.isna().sum().items()
        },
        "duplicate_row_count": int(df.duplicated().sum()),
        "preview_rows": _preview_rows(df, max_rows=3),
    }
    return info, df


def _compare_metadata_to_parquet(
    *,
    metadata: dict[str, Any] | None,
    full_info: dict[str, Any],
    full_parquet_path: Path,
    sample_parquet_path: Path,
    sample_csv_path: Path,
) -> dict[str, Any]:
    checks_performed: list[str] = []
    checks_skipped: dict[str, str] = {}
    results: dict[str, Any] = {}
    warnings: list[str] = []
    failures: list[str] = []

    if metadata is None:
        return {
            "checks_performed": checks_performed,
            "checks_skipped": {
                "all": "metadata unavailable",
            },
            "results": results,
            "warnings": warnings,
            "failures": failures,
        }

    if full_info.get("loaded") is not True:
        checks_skipped["row_count"] = "full parquet unavailable"
        checks_skipped["column_names"] = "full parquet unavailable"
        checks_skipped["artifact_paths"] = "full parquet unavailable"
    else:
        if "row_count" in metadata:
            checks_performed.append("row_count")
            metadata_row_count = metadata.get("row_count")
            matches = isinstance(metadata_row_count, int) and metadata_row_count == full_info["row_count"]
            results["row_count_matches"] = matches
            if matches is False:
                failures.append("metadata_row_count_mismatch")
        else:
            checks_skipped["row_count"] = "field_missing_in_metadata"

        if "column_names" in metadata:
            checks_performed.append("column_names")
            metadata_columns = metadata.get("column_names")
            matches = isinstance(metadata_columns, list) and list(metadata_columns) == full_info["column_names"]
            results["column_names_match"] = matches
            if matches is False:
                failures.append("metadata_column_names_mismatch")
        else:
            checks_skipped["column_names"] = "field_missing_in_metadata"

        if "local_file_path" in metadata or "sample_file_paths" in metadata:
            checks_performed.append("artifact_paths")
            path_results: dict[str, Any] = {}

            if "local_file_path" in metadata:
                metadata_path = metadata.get("local_file_path")
                expected = str(full_parquet_path.resolve())
                path_results["local_file_path_matches"] = metadata_path == expected
                if path_results["local_file_path_matches"] is False:
                    warnings.append("metadata_local_file_path_mismatch")
            else:
                path_results["local_file_path_matches"] = None

            sample_paths = metadata.get("sample_file_paths")
            if isinstance(sample_paths, dict):
                expected_parquet = str(sample_parquet_path.resolve())
                expected_csv = str(sample_csv_path.resolve())
                path_results["sample_parquet_path_matches"] = (
                    sample_paths.get("parquet") == expected_parquet
                )
                path_results["sample_csv_path_matches"] = (
                    sample_paths.get("csv") == expected_csv
                )
                if path_results["sample_parquet_path_matches"] is False:
                    warnings.append("metadata_sample_parquet_path_mismatch")
                if path_results["sample_csv_path_matches"] is False:
                    warnings.append("metadata_sample_csv_path_mismatch")
            else:
                path_results["sample_parquet_path_matches"] = None
                path_results["sample_csv_path_matches"] = None
                checks_skipped["sample_file_paths"] = "field_missing_or_not_mapping"

            results["artifact_path_checks"] = path_results
        else:
            checks_skipped["artifact_paths"] = "fields_missing_in_metadata"

    for ts_field in ("extraction_started_at_utc", "extraction_completed_at_utc"):
        if ts_field in metadata:
            checks_performed.append(ts_field)
            parsed = _timestamp_parseable(metadata.get(ts_field))
            results[f"{ts_field}_parseable"] = parsed
            if not parsed:
                warnings.append(f"metadata_bad_timestamp:{ts_field}")
        else:
            checks_skipped[ts_field] = "field_missing_in_metadata"

    if "query_id" in metadata:
        checks_performed.append("query_id")
        results["query_id_present"] = bool(metadata.get("query_id"))
        if not results["query_id_present"]:
            warnings.append("metadata_query_id_empty")
    else:
        checks_skipped["query_id"] = "field_missing_in_metadata"

    return {
        "checks_performed": checks_performed,
        "checks_skipped": checks_skipped,
        "results": results,
        "warnings": warnings,
        "failures": failures,
    }


def _compare_samples_to_full(
    *,
    full_df: pd.DataFrame | None,
    sample_parquet_df: pd.DataFrame | None,
    sample_csv_df: pd.DataFrame | None,
) -> dict[str, Any]:
    warnings: list[str] = []
    failures: list[str] = []
    results: dict[str, Any] = {
        "checks_performed": [],
        "checks_skipped": {},
    }

    if full_df is None:
        results["checks_skipped"]["all"] = "full dataframe unavailable"
        return {"results": results, "warnings": warnings, "failures": failures}

    expected_sample_rows = min(1000, len(full_df))
    results["expected_sample_row_count"] = expected_sample_rows

    if sample_parquet_df is None:
        failures.append("sample_parquet_unavailable_for_comparison")
    else:
        results["checks_performed"].append("sample_parquet_row_count")
        results["sample_parquet_row_count_matches_expected"] = (
            len(sample_parquet_df) == expected_sample_rows
        )
        if not results["sample_parquet_row_count_matches_expected"]:
            failures.append("sample_parquet_row_count_mismatch")

        results["checks_performed"].append("sample_parquet_columns")
        results["sample_parquet_columns_match_full"] = list(sample_parquet_df.columns) == list(
            full_df.columns
        )
        if not results["sample_parquet_columns_match_full"]:
            failures.append("sample_parquet_column_mismatch")

    if sample_csv_df is None:
        failures.append("sample_csv_unavailable_for_comparison")
    else:
        results["checks_performed"].append("sample_csv_row_count")
        results["sample_csv_row_count_matches_expected"] = (
            len(sample_csv_df) == expected_sample_rows
        )
        if not results["sample_csv_row_count_matches_expected"]:
            failures.append("sample_csv_row_count_mismatch")

        results["checks_performed"].append("sample_csv_columns")
        results["sample_csv_columns_match_full"] = list(sample_csv_df.columns) == list(
            full_df.columns
        )
        if not results["sample_csv_columns_match_full"]:
            failures.append("sample_csv_column_mismatch")

    if sample_parquet_df is not None and list(sample_parquet_df.columns) == list(full_df.columns):
        results["checks_performed"].append("sample_parquet_prefix_alignment")
        aligned = _rows_equal_as_strings(
            full_df.head(expected_sample_rows), sample_parquet_df
        )
        results["sample_parquet_prefix_matches_full"] = aligned
        if not aligned:
            warnings.append("sample_parquet_prefix_mismatch")
    else:
        results["checks_skipped"]["sample_parquet_prefix_alignment"] = (
            "sample parquet unavailable or column mismatch"
        )

    if sample_csv_df is not None and list(sample_csv_df.columns) == list(full_df.columns):
        results["checks_performed"].append("sample_csv_prefix_alignment")
        aligned = _rows_equal_as_strings(full_df.head(expected_sample_rows), sample_csv_df)
        results["sample_csv_prefix_matches_full"] = aligned
        if not aligned:
            warnings.append("sample_csv_prefix_mismatch")
    else:
        results["checks_skipped"]["sample_csv_prefix_alignment"] = (
            "sample csv unavailable or column mismatch"
        )

    return {"results": results, "warnings": warnings, "failures": failures}


def _rows_equal_as_strings(left: pd.DataFrame, right: pd.DataFrame) -> bool:
    if len(left) != len(right) or list(left.columns) != list(right.columns):
        return False
    left_norm = left.fillna("").astype(str).reset_index(drop=True)
    right_norm = right.fillna("").astype(str).reset_index(drop=True)
    return left_norm.equals(right_norm)


def _timestamp_parseable(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _dataset_summary_for_report(load_info: dict[str, Any]) -> dict[str, Any]:
    return {
        "loaded": load_info.get("loaded"),
        "row_count": load_info.get("row_count"),
        "column_count": load_info.get("column_count"),
        "column_names": load_info.get("column_names"),
        "null_counts_by_column": load_info.get("null_counts_by_column"),
        "duplicate_row_count": load_info.get("duplicate_row_count"),
    }


def _build_legacy_consistency(
    *,
    metadata_vs_parquet_results: dict[str, Any],
    sample_vs_full_results: dict[str, Any],
) -> dict[str, Any]:
    return {
        "metadata_vs_parquet": {
            "row_count_matches": metadata_vs_parquet_results.get("row_count_matches"),
            "column_names_match": metadata_vs_parquet_results.get("column_names_match"),
            "local_file_path_matches": metadata_vs_parquet_results.get(
                "artifact_path_checks", {}
            ).get("local_file_path_matches"),
            "sample_parquet_path_matches": metadata_vs_parquet_results.get(
                "artifact_path_checks", {}
            ).get("sample_parquet_path_matches"),
            "sample_csv_path_matches": metadata_vs_parquet_results.get(
                "artifact_path_checks", {}
            ).get("sample_csv_path_matches"),
        },
        "sample_vs_snapshot": {
            "expected_sample_row_count": sample_vs_full_results.get(
                "expected_sample_row_count"
            ),
            "sample_parquet_row_count_matches_expected": sample_vs_full_results.get(
                "sample_parquet_row_count_matches_expected"
            ),
            "sample_csv_row_count_matches_expected": sample_vs_full_results.get(
                "sample_csv_row_count_matches_expected"
            ),
            "sample_parquet_columns_match_snapshot": sample_vs_full_results.get(
                "sample_parquet_columns_match_full"
            ),
            "sample_csv_columns_match_snapshot": sample_vs_full_results.get(
                "sample_csv_columns_match_full"
            ),
            "sample_parquet_rows_match_snapshot_prefix": sample_vs_full_results.get(
                "sample_parquet_prefix_matches_full"
            ),
            "sample_csv_rows_match_snapshot_prefix": sample_vs_full_results.get(
                "sample_csv_prefix_matches_full"
            ),
        },
    }


def _preview_rows(df: pd.DataFrame, max_rows: int = 3) -> list[dict[str, Any]]:
    preview: list[dict[str, Any]] = []
    for _, row in df.head(max_rows).iterrows():
        preview.append({column: _to_json_safe(value) for column, value in row.items()})
    return preview


def _to_json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, (int, float, bool, str)):
        return value
    return str(value)


def _derive_status(*, warnings: list[str], failures: list[str]) -> str:
    if failures:
        return "fail"
    if warnings:
        return "warn"
    return "pass"


def _recommended_next_step(*, status: str) -> str:
    if status == "pass":
        return "Proceed to local profiling using validated local snapshot artifacts."
    if status == "warn":
        return "Proceed with caution; review warnings and confirm they are acceptable."
    return "Do not proceed to profiling until failures are resolved."


def _print_concise_summary(report: dict[str, Any], report_path: Path) -> None:
    print("Local Twitter snapshot validation")
    print(f"- status: {report['status']}")
    print(
        "- artifacts: "
        + ", ".join(
            f"{name}={'PASS' if ok else 'FAIL'}"
            for name, ok in report["artifact_existence"].items()
        )
    )
    print(f"- import_preflight: {report['import_checks']['status']}")
    print(
        "- loads: "
        f"full_parquet={'PASS' if report['loads']['full_parquet']['loaded'] else 'FAIL'}, "
        f"sample_parquet={'PASS' if report['loads']['sample_parquet']['loaded'] else 'FAIL'}, "
        f"sample_csv={'PASS' if report['loads']['sample_csv']['loaded'] else 'FAIL'}"
    )
    print(
        "- warnings: "
        + (", ".join(report["warnings"]) if report["warnings"] else "none")
    )
    print(
        "- failures: "
        + (", ".join(report["failures"]) if report["failures"] else "none")
    )
    print(f"- report: {report_path}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = validate_local_snapshot(
        full_parquet_path=args.full_parquet,
        metadata_json_path=args.metadata_json,
        sample_parquet_path=args.sample_parquet,
        sample_csv_path=args.sample_csv,
    )
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    _print_concise_summary(report, args.report_path)
    return 0 if report["status"] != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
