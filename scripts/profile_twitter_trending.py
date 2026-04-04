#!/usr/bin/env python3
"""Local profiling for twitter_trending snapshot artifacts (no Snowflake usage)."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

DEFAULT_SNAPSHOT_PATH = Path(
    "local/reference_snapshots/twitter_trending/twitter_trending_full.parquet"
)
DEFAULT_VALIDATION_REPORT_PATH = Path(
    "local/reference_snapshots/twitter_trending/twitter_trending_validation_report.json"
)
DEFAULT_PROFILE_JSON_PATH = Path(
    "local/reference_snapshots/twitter_trending/twitter_trending_profile_report.json"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Profile local twitter_trending parquet snapshot."
    )
    parser.add_argument("--snapshot-path", type=Path, default=DEFAULT_SNAPSHOT_PATH)
    parser.add_argument(
        "--validation-report-path",
        type=Path,
        default=DEFAULT_VALIDATION_REPORT_PATH,
    )
    parser.add_argument("--output-json", type=Path, default=DEFAULT_PROFILE_JSON_PATH)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _require_validated_snapshot(args.validation_report_path)

    if not args.snapshot_path.exists():
        raise FileNotFoundError(
            "Full local snapshot is missing. Expected: "
            f"{args.snapshot_path}. Prior snapshot phase is incomplete."
        )

    profile = build_profile_report(load_snapshot(args.snapshot_path))
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    print(json.dumps(profile, indent=2))
    return 0


def load_snapshot(snapshot_path: Path) -> pd.DataFrame:
    df = pd.read_parquet(snapshot_path)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    if "name" in df.columns:
        df["name"] = df["name"].astype(str).str.strip()
    return df


def _require_validated_snapshot(validation_report_path: Path) -> None:
    if not validation_report_path.exists():
        raise FileNotFoundError(
            "Validation report is missing. Expected: "
            f"{validation_report_path}. Run the local snapshot validation phase first."
        )

    try:
        validation_report = json.loads(validation_report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Validation report is not valid JSON: "
            f"{validation_report_path}"
        ) from exc

    overall_pass = validation_report.get("overall_pass")
    blocking_issues = validation_report.get("blocking_issues") or []

    if overall_pass is not True:
        raise RuntimeError(
            "Validation report indicates prior phase did not pass "
            f"(overall_pass={overall_pass!r}). Stop profiling until this is resolved."
        )
    if blocking_issues:
        raise RuntimeError(
            "Validation report contains blocking issues. Stop profiling until resolved: "
            + "; ".join(str(issue) for issue in blocking_issues)
        )


def build_profile_report(df: pd.DataFrame) -> dict[str, Any]:
    required_columns = {"num_hours", "date", "name", "counts"}
    missing = required_columns.difference(df.columns)
    if missing:
        raise ValueError(f"Snapshot is missing required columns: {sorted(missing)}")

    name = df["name"]
    row_count = int(len(df))
    unique_topic_count = int(name.nunique(dropna=True))
    unique_date_count = int(df["date"].nunique(dropna=True))

    rows_per_day = (
        df.groupby("date")
        .size()
        .reset_index(name="row_count")
        .sort_values("date")
    )
    rows_per_day["date"] = rows_per_day["date"].astype(str)

    duplicate_rows = int(df.duplicated().sum())
    duplicate_date_name = int(df.duplicated(subset=["date", "name"]).sum())
    name_frequency = name.value_counts()

    char_len = name.str.len()
    token_len = name.str.split().map(len)

    hashtag_counter = Counter()
    hashtag_regex = re.compile(r"#[A-Za-z0-9_]+")
    for value in name:
        hashtag_counter.update(hashtag_regex.findall(value))

    noise_metrics = _build_noise_metrics(name=name, token_len=token_len)
    numeric_checks = {
        "counts": _numeric_outlier_check(pd.to_numeric(df["counts"], errors="coerce")),
        "num_hours": _numeric_outlier_check(
            pd.to_numeric(df["num_hours"], errors="coerce")
        ),
    }

    lowered = name.str.lower()
    case_variant_collisions = int(name.groupby(lowered).nunique().gt(1).sum())

    report: dict[str, Any] = {
        "dataset": {
            "row_count": row_count,
            "columns": list(df.columns),
            "dtypes": {column: str(dtype) for column, dtype in df.dtypes.items()},
            "unique_topic_count": unique_topic_count,
            "unique_date_count": unique_date_count,
            "rows_per_day_summary": {
                "min": int(rows_per_day["row_count"].min()),
                "max": int(rows_per_day["row_count"].max()),
                "median": float(rows_per_day["row_count"].median()),
                "mean": float(rows_per_day["row_count"].mean()),
            },
        },
        "missing_values": {
            column: int(count) for column, count in df.isna().sum().items()
        },
        "duplicates": {
            "duplicate_rows": duplicate_rows,
            "duplicate_date_name_rows": duplicate_date_name,
            "repeated_topics_ge_2": int((name_frequency >= 2).sum()),
            "repeated_topics_ge_10": int((name_frequency >= 10).sum()),
            "top_topics": _series_head_to_records(name_frequency, "name", "count", 25),
        },
        "date_distribution": rows_per_day.to_dict(orient="records"),
        "numeric_outliers": numeric_checks,
        "text_profile": {
            "topic_length_chars": _describe_numeric_series(char_len),
            "topic_length_tokens": _describe_numeric_series(token_len),
            "hashtag_rows": int(name.str.contains("#", regex=False).sum()),
            "unique_hashtags": int(len(hashtag_counter)),
            "top_hashtags": [
                {"hashtag": hashtag, "count": int(count)}
                for hashtag, count in hashtag_counter.most_common(25)
            ],
            "noise_metrics": noise_metrics,
            "case_variant_collisions": case_variant_collisions,
            "noise_examples": _build_noise_examples(name),
        },
        "candidate_cleaning_rules": [
            "Unicode-normalize to NFKC, trim outer whitespace, and collapse repeated internal whitespace.",
            "Case-fold to lowercase for matching keys while preserving original display name separately.",
            "Build two normalized keys: one with leading # removed and one retaining hashtag semantics.",
            "Replace punctuation separators (&, -, apostrophes, periods) with spaces before token matching.",
            "Normalize curved apostrophes and similar punctuation to ASCII equivalents before stripping.",
            "Strip leading $ from ticker-like terms into a secondary ticker key while keeping original token.",
            "Retain alphanumeric tokens; remove other punctuation except # and $ in dedicated variants.",
            "Deduplicate by (date, normalized_key_no_hash) during matching prep.",
            "Use both exact normalized-key match and fallback fuzzy/semantic tiers for robust recall.",
        ],
    }
    return report


def _describe_numeric_series(series: pd.Series) -> dict[str, float]:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    described = clean.describe(percentiles=[0.5, 0.9, 0.95, 0.99])
    return {
        "count": float(described["count"]),
        "mean": float(described["mean"]),
        "std": float(described["std"]),
        "min": float(described["min"]),
        "p50": float(described["50%"]),
        "p90": float(described["90%"]),
        "p95": float(described["95%"]),
        "p99": float(described["99%"]),
        "max": float(described["max"]),
    }


def _numeric_outlier_check(series: pd.Series) -> dict[str, Any]:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return {
            "row_count": 0,
            "iqr_lower": None,
            "iqr_upper": None,
            "outlier_count": 0,
            "outlier_ratio": 0.0,
            "describe": {},
        }

    q1 = float(clean.quantile(0.25))
    q3 = float(clean.quantile(0.75))
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    outlier_count = int(((clean < lower) | (clean > upper)).sum())
    return {
        "row_count": int(len(clean)),
        "iqr_lower": float(lower),
        "iqr_upper": float(upper),
        "outlier_count": outlier_count,
        "outlier_ratio": float(outlier_count / len(clean)),
        "describe": _describe_numeric_series(clean),
    }


def _build_noise_metrics(*, name: pd.Series, token_len: pd.Series) -> dict[str, int]:
    return {
        "starts_with_hash": int(name.str.startswith("#").sum()),
        "contains_ampersand": int(name.str.contains("&", regex=False).sum()),
        "contains_apostrophe_ascii": int(name.str.contains("'", regex=False).sum()),
        "contains_apostrophe_curly": int(name.str.contains("’", regex=False).sum()),
        "contains_hyphen": int(name.str.contains("-", regex=False).sum()),
        "contains_comma": int(name.str.contains(",", regex=False).sum()),
        "contains_period": int(name.str.contains(".", regex=False).sum()),
        "contains_digits": int(name.str.contains(r"\d", regex=True).sum()),
        "contains_dollar": int(name.str.contains("$", regex=False).sum()),
        "contains_non_ascii": int(name.str.contains(r"[^\x00-\x7F]", regex=True).sum()),
        "contains_non_alnum_space_hash": int(
            name.str.contains(r"[^A-Za-z0-9#\s]", regex=True).sum()
        ),
        "multi_word_rows": int((token_len >= 2).sum()),
    }


def _build_noise_examples(name: pd.Series, limit: int = 40) -> list[str]:
    mask = (
        name.str.contains(r"[^A-Za-z0-9#\s]", regex=True)
        | name.str.contains(r"\d", regex=True)
        | name.str.contains("$", regex=False)
    )
    return name[mask].drop_duplicates().head(limit).tolist()


def _series_head_to_records(
    series: pd.Series,
    key_label: str,
    value_label: str,
    limit: int,
) -> list[dict[str, Any]]:
    head = series.head(limit)
    return [
        {key_label: str(idx), value_label: int(val)}
        for idx, val in head.items()
    ]


if __name__ == "__main__":
    raise SystemExit(main())
