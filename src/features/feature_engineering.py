"""Deterministic local feature engineering for Bluesky engagement prediction."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import gzip
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from src.source_paths import resolve_bluesky_source_root

REQUIRED_PREPARED_COLUMNS = [
    "uri",
    "post_created_at",
    "source_run_tag",
    "text_source",
    "hydrated_author_did",
    "hydrated_author_handle",
    "post_text_raw",
    "post_text_clean",
    "post_text_alnum",
    "post_token_count",
    "post_char_count",
    "has_hashtag",
    "has_url",
    "has_mention",
    "has_special_chars",
    "has_non_ascii",
]

REQUIRED_BEST_MATCH_COLUMNS = [
    "uri",
    "match_stage",
    "match_score",
    "match_method",
    "temporal_pool_mode",
    "trend_name_clean",
    "trend_date",
    "trend_counts",
    "trend_num_hours",
    "is_matched",
    "is_ambiguous",
]

REQUIRED_FULL_MATCH_COLUMNS = [
    "uri",
    "candidate_id",
    "is_matched",
]

REQUIRED_HYDRATED_COLUMNS = [
    "uri",
    "author_did",
    "author_handle",
    "like_count",
    "reply_count",
    "repost_count",
    "quote_count",
]

REQUIRED_ACTOR_COLUMNS = [
    "did",
    "handle",
    "followers_count",
    "follows_count",
    "posts_count",
    "display_name",
    "description",
    "has_avatar",
    "has_banner",
]

STAGE_ORDER = ["exact", "fuzzy", "semantic", "unmatched", "no_candidate"]


@dataclass(frozen=True)
class FeatureConfig:
    """Configuration for deterministic local feature construction."""

    low_quantile: float = 0.33
    high_quantile: float = 0.66


def select_best_hydrated_source_file(
    prepared_df: pd.DataFrame,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Pick best hydrated source by URI overlap, row count, then lexical path."""

    _validate_required_columns(prepared_df, REQUIRED_PREPARED_COLUMNS, "prepared_df")

    prepared_uris = {
        str(uri).strip()
        for uri in prepared_df["uri"].fillna("")
        if str(uri).strip()
    }

    resolved_base_dir = resolve_bluesky_source_root(base_dir)

    candidates: list[dict[str, Any]] = []
    for path in sorted(resolved_base_dir.rglob("hydrated_posts_*.jsonl.gz")):
        profile = _profile_hydrated_file(path=path, prepared_uris=prepared_uris)
        candidates.append(profile)

    if not candidates:
        raise FileNotFoundError(f"No hydrated posts files found under: {resolved_base_dir}")

    ranked = sorted(
        candidates,
        key=lambda item: (
            -item["uri_overlap_count"],
            -item["row_count"],
            item["file_path"],
        ),
    )
    return {
        "selected": ranked[0],
        "candidates_ranked": ranked,
        "resolved_base_dir": resolved_base_dir.as_posix(),
        "selection_rule": "uri_overlap_count desc, row_count desc, file_path asc",
    }


def select_best_actor_profile_source_file(
    prepared_df: pd.DataFrame,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Pick best actor profile source by DID overlap, row count, then lexical path."""

    _validate_required_columns(prepared_df, REQUIRED_PREPARED_COLUMNS, "prepared_df")

    prepared_dids = {
        str(did).strip()
        for did in prepared_df["hydrated_author_did"].fillna("")
        if str(did).strip()
    }

    resolved_base_dir = resolve_bluesky_source_root(base_dir)

    candidates: list[dict[str, Any]] = []
    for path in sorted(resolved_base_dir.rglob("actor_profiles_*.jsonl.gz")):
        profile = _profile_actor_file(path=path, prepared_dids=prepared_dids)
        candidates.append(profile)

    if not candidates:
        raise FileNotFoundError(f"No actor profiles files found under: {resolved_base_dir}")

    ranked = sorted(
        candidates,
        key=lambda item: (
            -item["did_overlap_count"],
            -item["row_count"],
            item["file_path"],
        ),
    )
    return {
        "selected": ranked[0],
        "candidates_ranked": ranked,
        "resolved_base_dir": resolved_base_dir.as_posix(),
        "selection_rule": "did_overlap_count desc, row_count desc, file_path asc",
    }


def load_hydrated_metrics_file(path: Path | str) -> pd.DataFrame:
    """Load hydrated engagement rows from one local gzip JSONL file."""

    rows: list[dict[str, Any]] = []
    for row in _iter_jsonl_gz(path):
        rows.append(
            {
                "uri": _as_str(row.get("uri")),
                "author_did": _as_str(row.get("author_did")),
                "author_handle": _as_str(row.get("author_handle")),
                "like_count": _to_float(row.get("like_count")),
                "reply_count": _to_float(row.get("reply_count")),
                "repost_count": _to_float(row.get("repost_count")),
                "quote_count": _to_float(row.get("quote_count")),
                "indexed_at": _as_str(row.get("indexed_at")),
                "hydrated_at": _as_str(row.get("hydrated_at")),
                "capture_run_id": _as_str(row.get("capture_run_id")),
                "hydrate_run_id": _as_str(row.get("hydrate_run_id")),
            }
        )

    hydrated_df = pd.DataFrame(rows)
    if hydrated_df.empty:
        hydrated_df = pd.DataFrame(columns=[*REQUIRED_HYDRATED_COLUMNS, "indexed_at", "hydrated_at", "capture_run_id", "hydrate_run_id"])
    _validate_required_columns(hydrated_df, REQUIRED_HYDRATED_COLUMNS, "hydrated_df")

    hydrated_df = hydrated_df.sort_values(["uri", "hydrated_at", "indexed_at"], ascending=[True, False, False], kind="stable")
    hydrated_df = hydrated_df.drop_duplicates(subset=["uri"], keep="first").reset_index(drop=True)
    return hydrated_df


def load_actor_profiles_file(path: Path | str) -> pd.DataFrame:
    """Load actor profile rows from one local gzip JSONL file."""

    rows: list[dict[str, Any]] = []
    for row in _iter_jsonl_gz(path):
        profile = row.get("profile") if isinstance(row.get("profile"), dict) else {}
        rows.append(
            {
                "did": _as_str(row.get("did")),
                "handle": _as_str(row.get("handle")),
                "followers_count": _to_float(row.get("followers_count")),
                "follows_count": _to_float(row.get("follows_count")),
                "posts_count": _to_float(row.get("posts_count")),
                "display_name": _as_str(row.get("display_name")),
                "description": _as_str(row.get("description")),
                "has_avatar": bool(profile.get("avatar") or row.get("avatar")),
                "has_banner": bool(profile.get("banner") or row.get("banner")),
                "actor_created_at": _as_str(row.get("created_at")),
                "actor_indexed_at": _as_str(row.get("indexed_at")),
                "actor_run_id": _as_str(row.get("actor_run_id")),
            }
        )

    actor_df = pd.DataFrame(rows)
    if actor_df.empty:
        actor_df = pd.DataFrame(columns=[*REQUIRED_ACTOR_COLUMNS, "actor_created_at", "actor_indexed_at", "actor_run_id"])
    _validate_required_columns(actor_df, REQUIRED_ACTOR_COLUMNS, "actor_df")

    actor_df = actor_df.sort_values(["did", "actor_indexed_at", "actor_created_at"], ascending=[True, False, False], kind="stable")
    actor_df = actor_df.drop_duplicates(subset=["did"], keep="first").reset_index(drop=True)
    return actor_df


def build_local_engagement_feature_table(
    prepared_df: pd.DataFrame,
    best_matches_df: pd.DataFrame,
    full_matches_df: pd.DataFrame,
    hydrated_df: pd.DataFrame,
    actor_df: pd.DataFrame,
    config: FeatureConfig | dict[str, Any] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build one-row-per-post local engagement feature table."""

    cfg = _resolve_config(config)

    _validate_required_columns(prepared_df, REQUIRED_PREPARED_COLUMNS, "prepared_df")
    _validate_required_columns(best_matches_df, REQUIRED_BEST_MATCH_COLUMNS, "best_matches_df")
    _validate_required_columns(full_matches_df, REQUIRED_FULL_MATCH_COLUMNS, "full_matches_df")
    _validate_required_columns(hydrated_df, REQUIRED_HYDRATED_COLUMNS, "hydrated_df")
    _validate_required_columns(actor_df, REQUIRED_ACTOR_COLUMNS, "actor_df")

    base = prepared_df.copy()
    base["uri"] = base["uri"].astype(str)

    join_coverage: dict[str, dict[str, Any]] = {}

    best_join = _prepare_best_matches_for_join(best_matches_df)
    base = base.merge(best_join, on="uri", how="left", indicator="_merge_best")
    join_coverage["prepared_to_best_match"] = _build_coverage(base, "_merge_best")
    base = base.drop(columns=["_merge_best"])

    candidate_agg = _aggregate_candidate_counts(full_matches_df)
    base = base.merge(candidate_agg, on="uri", how="left", indicator="_merge_candidate_agg")
    join_coverage["with_candidate_aggregates"] = _build_coverage(base, "_merge_candidate_agg")
    base = base.drop(columns=["_merge_candidate_agg"])

    hydrated_join = hydrated_df.rename(columns={
        "author_did": "eng_author_did",
        "author_handle": "eng_author_handle",
    })
    base = base.merge(hydrated_join, on="uri", how="left", indicator="_merge_hydrated")
    join_coverage["with_hydrated_metrics"] = _build_coverage(base, "_merge_hydrated")
    base = base.drop(columns=["_merge_hydrated"])

    actor_join = actor_df.rename(columns={
        "did": "actor_did",
        "handle": "actor_handle",
    })
    base = base.merge(
        actor_join,
        left_on="hydrated_author_did",
        right_on="actor_did",
        how="left",
        indicator="_merge_actor",
    )
    join_coverage["with_actor_profiles"] = _build_coverage(base, "_merge_actor")
    base = base.drop(columns=["_merge_actor"])

    features = _derive_feature_columns(base)
    features, labeling_meta = _derive_engagement_target(features, cfg)
    features = _finalize_feature_types(features)

    feature_groups = get_feature_column_groups(features)
    summary = summarize_feature_table(
        features_df=features,
        join_coverage=join_coverage,
        labeling_meta=labeling_meta,
        feature_groups=feature_groups,
        config=cfg,
    )

    features = features.sort_values(["uri"], kind="stable").reset_index(drop=True)
    return features, summary


def get_feature_column_groups(features_df: pd.DataFrame) -> dict[str, list[str]]:
    """Return deterministic model/label/debug column groups."""

    label_columns = [
        "engagement_label",
        "engagement_total",
        "eng_like_count",
        "eng_reply_count",
        "eng_repost_count",
        "eng_quote_count",
    ]

    debug_columns = [
        "uri",
        "post_created_at",
        "source_run_tag",
        "text_source",
        "hydrated_author_did",
        "hydrated_author_handle",
        "trend_name_clean",
        "trend_date",
        "match_method",
        "temporal_pool_mode",
        "eng_author_did",
        "eng_author_handle",
        "actor_did",
        "actor_handle",
        "post_text_raw",
        "post_text_clean",
        "post_text_alnum",
    ]

    present_labels = [column for column in label_columns if column in features_df.columns]
    present_debug = [column for column in debug_columns if column in features_df.columns]

    excluded = set(present_labels) | set(present_debug)
    model_features = [
        column
        for column in features_df.columns
        if column not in excluded
        and not column.startswith("raw_source_row_json")
        and not column.startswith("hydrated_source_row_json")
    ]

    return {
        "model_feature_columns": model_features,
        "label_columns": present_labels,
        "debug_columns": present_debug,
    }


def summarize_feature_table(
    *,
    features_df: pd.DataFrame,
    join_coverage: dict[str, dict[str, Any]],
    labeling_meta: dict[str, Any],
    feature_groups: dict[str, list[str]],
    config: FeatureConfig,
) -> dict[str, Any]:
    """Build compact summary metrics for documentation and QA."""

    label_distribution = {
        str(key): int(value)
        for key, value in features_df["engagement_label"].value_counts(dropna=False).items()
    }

    stage_distribution = {
        str(key): int(value)
        for key, value in features_df["match_stage"].value_counts(dropna=False).items()
    }

    model_cols = feature_groups["model_feature_columns"]
    missing_by_feature = {
        column: int(features_df[column].isna().sum())
        for column in model_cols
    }

    numeric_cols = [
        column
        for column in model_cols
        if pd.api.types.is_numeric_dtype(features_df[column])
    ]
    categorical_cols = [
        column
        for column in model_cols
        if pd.api.types.is_object_dtype(features_df[column])
        or isinstance(features_df[column].dtype, pd.CategoricalDtype)
    ]

    numeric_summary: dict[str, dict[str, float]] = {}
    for column in numeric_cols:
        series = pd.to_numeric(features_df[column], errors="coerce")
        numeric_summary[column] = {
            "min": float(series.min(skipna=True)) if series.notna().any() else 0.0,
            "mean": float(series.mean(skipna=True)) if series.notna().any() else 0.0,
            "max": float(series.max(skipna=True)) if series.notna().any() else 0.0,
        }

    categorical_cardinality = {
        column: int(features_df[column].nunique(dropna=True))
        for column in categorical_cols
    }

    return {
        "phase": "26_local_feature_engineering",
        "config": asdict(config),
        "row_count": int(len(features_df)),
        "unique_uri_count": int(features_df["uri"].nunique()) if "uri" in features_df.columns else 0,
        "join_coverage": join_coverage,
        "labeling": labeling_meta,
        "label_distribution": label_distribution,
        "match_stage_distribution": stage_distribution,
        "missingness_by_model_feature": missing_by_feature,
        "numeric_model_feature_summary": numeric_summary,
        "categorical_model_feature_cardinality": categorical_cardinality,
        "feature_groups": feature_groups,
    }


def _prepare_best_matches_for_join(best_matches_df: pd.DataFrame) -> pd.DataFrame:
    best = best_matches_df.copy()
    best["uri"] = best["uri"].astype(str)

    stage_rank = {
        "exact": 0,
        "fuzzy": 1,
        "semantic": 2,
        "unmatched": 3,
    }
    best["_stage_rank"] = best["match_stage"].map(stage_rank).fillna(99)
    best["_score"] = pd.to_numeric(best["match_score"], errors="coerce").fillna(0.0)
    best["_trend_counts"] = pd.to_numeric(best["trend_counts"], errors="coerce").fillna(0.0)

    best = best.sort_values(
        ["uri", "_stage_rank", "_score", "_trend_counts", "trend_name_clean"],
        ascending=[True, True, False, False, True],
        kind="stable",
    )
    best = best.drop_duplicates(subset=["uri"], keep="first")

    keep_columns = [
        "uri",
        "match_stage",
        "match_score",
        "match_method",
        "temporal_pool_mode",
        "trend_name_clean",
        "trend_date",
        "trend_counts",
        "trend_num_hours",
        "is_matched",
        "is_ambiguous",
    ]
    return best[keep_columns].reset_index(drop=True)


def _aggregate_candidate_counts(full_matches_df: pd.DataFrame) -> pd.DataFrame:
    candidate_level = (
        full_matches_df[["uri", "candidate_id", "is_matched"]]
        .copy()
        .groupby(["uri", "candidate_id"], as_index=False)["is_matched"]
        .max()
    )

    agg = candidate_level.groupby("uri", as_index=False).agg(
        candidate_count=("candidate_id", "nunique"),
        matched_candidate_count=("is_matched", "sum"),
    )
    agg["matched_candidate_count"] = pd.to_numeric(agg["matched_candidate_count"], errors="coerce").fillna(0).astype(int)
    agg["candidate_count"] = pd.to_numeric(agg["candidate_count"], errors="coerce").fillna(0).astype(int)
    agg["matched_candidate_rate"] = np.where(
        agg["candidate_count"] > 0,
        agg["matched_candidate_count"] / agg["candidate_count"],
        0.0,
    )
    return agg


def _derive_feature_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    out["candidate_count"] = pd.to_numeric(out["candidate_count"], errors="coerce").fillna(0).astype(int)
    out["matched_candidate_count"] = pd.to_numeric(out["matched_candidate_count"], errors="coerce").fillna(0).astype(int)
    out["matched_candidate_rate"] = pd.to_numeric(out["matched_candidate_rate"], errors="coerce").fillna(0.0)

    out["has_candidate"] = out["candidate_count"] > 0
    out["has_trend_match"] = out["is_matched"].fillna(False).astype(bool)
    out["is_ambiguous_match"] = out["is_ambiguous"].fillna(False).astype(bool)

    out["match_score"] = pd.to_numeric(out["match_score"], errors="coerce").fillna(0.0)
    out["trend_counts"] = pd.to_numeric(out["trend_counts"], errors="coerce").fillna(0.0)
    out["trend_num_hours"] = pd.to_numeric(out["trend_num_hours"], errors="coerce").fillna(0.0)

    post_dt = pd.to_datetime(out["post_created_at"], errors="coerce", utc=True)
    trend_dt = pd.to_datetime(out["trend_date"], errors="coerce", utc=True)

    out["trend_date_available"] = trend_dt.notna()
    out["trend_post_day_diff"] = (trend_dt.dt.normalize() - post_dt.dt.normalize()).dt.days
    out["same_day_trend_match"] = out["has_trend_match"] & out["trend_post_day_diff"].eq(0)

    out["post_hour_utc"] = post_dt.dt.hour.fillna(0).astype(int)
    out["post_day_of_week"] = post_dt.dt.dayofweek.fillna(0).astype(int)
    out["post_is_weekend"] = out["post_day_of_week"].isin([5, 6])
    out["post_month"] = post_dt.dt.month.fillna(0).astype(int)

    out["post_unique_token_count"] = out["post_text_alnum"].map(_unique_token_count).astype(int)
    out["post_unique_token_ratio"] = np.where(
        pd.to_numeric(out["post_token_count"], errors="coerce").fillna(0) > 0,
        out["post_unique_token_count"] / pd.to_numeric(out["post_token_count"], errors="coerce").fillna(0),
        0.0,
    )
    out["raw_exclamation_count"] = out["post_text_raw"].map(lambda text: _count_char(text, "!")).astype(int)
    out["raw_question_count"] = out["post_text_raw"].map(lambda text: _count_char(text, "?")).astype(int)
    out["raw_uppercase_ratio"] = out["post_text_raw"].map(_uppercase_ratio).astype(float)

    out["eng_like_count"] = pd.to_numeric(out["like_count"], errors="coerce").fillna(0.0)
    out["eng_reply_count"] = pd.to_numeric(out["reply_count"], errors="coerce").fillna(0.0)
    out["eng_repost_count"] = pd.to_numeric(out["repost_count"], errors="coerce").fillna(0.0)
    out["eng_quote_count"] = pd.to_numeric(out["quote_count"], errors="coerce").fillna(0.0)

    out["actor_profile_found"] = out["actor_did"].fillna("").astype(str).str.strip().ne("")
    out["actor_followers_count"] = pd.to_numeric(out["followers_count"], errors="coerce").fillna(0.0)
    out["actor_follows_count"] = pd.to_numeric(out["follows_count"], errors="coerce").fillna(0.0)
    out["actor_posts_count"] = pd.to_numeric(out["posts_count"], errors="coerce").fillna(0.0)
    out["actor_followers_to_follows_ratio"] = np.where(
        out["actor_follows_count"] > 0,
        out["actor_followers_count"] / out["actor_follows_count"],
        0.0,
    )

    out["actor_has_display_name"] = out["display_name"].fillna("").astype(str).str.strip().ne("")
    out["actor_has_description"] = out["description"].fillna("").astype(str).str.strip().ne("")
    out["actor_description_char_count"] = out["description"].fillna("").astype(str).str.len().astype(int)
    out["actor_has_avatar"] = out["has_avatar"].fillna(False).astype(bool)
    out["actor_has_banner"] = out["has_banner"].fillna(False).astype(bool)

    return out


def _derive_engagement_target(df: pd.DataFrame, cfg: FeatureConfig) -> tuple[pd.DataFrame, dict[str, Any]]:
    out = df.copy()

    out["engagement_total"] = (
        out["eng_like_count"]
        + out["eng_reply_count"]
        + out["eng_repost_count"]
        + out["eng_quote_count"]
    )

    q_low = float(out["engagement_total"].quantile(cfg.low_quantile))
    q_high = float(out["engagement_total"].quantile(cfg.high_quantile))

    fallback_reason = ""
    if q_low == q_high:
        labels, fallback_reason = _fallback_count_labels(out["engagement_total"])
        rule = "fallback_count_bins"
    else:
        labels = np.where(
            out["engagement_total"] <= q_low,
            "LOW",
            np.where(out["engagement_total"] <= q_high, "MEDIUM", "HIGH"),
        )
        rule = "quantile_bins"

        temp_labels = pd.Series(labels)
        label_counts = temp_labels.value_counts().to_dict()
        if any(label_counts.get(label, 0) == 0 for label in ("LOW", "MEDIUM", "HIGH")):
            labels, fallback_reason = _fallback_count_labels(out["engagement_total"])
            rule = "fallback_count_bins"

    out["engagement_label"] = pd.Categorical(labels, categories=["LOW", "MEDIUM", "HIGH"], ordered=True)

    labeling_meta = {
        "rule": rule,
        "low_quantile": cfg.low_quantile,
        "high_quantile": cfg.high_quantile,
        "low_threshold": q_low,
        "high_threshold": q_high,
        "fallback_reason": fallback_reason,
    }

    return out, labeling_meta


def _finalize_feature_types(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    bool_columns = [
        "has_hashtag",
        "has_url",
        "has_mention",
        "has_special_chars",
        "has_non_ascii",
        "has_candidate",
        "has_trend_match",
        "is_ambiguous_match",
        "trend_date_available",
        "same_day_trend_match",
        "post_is_weekend",
        "actor_profile_found",
        "actor_has_display_name",
        "actor_has_description",
        "actor_has_avatar",
        "actor_has_banner",
    ]
    for column in bool_columns:
        if column in out.columns:
            out[column] = out[column].fillna(False).astype(bool)

    numeric_columns = [
        "post_token_count",
        "post_char_count",
        "post_unique_token_count",
        "post_unique_token_ratio",
        "raw_exclamation_count",
        "raw_question_count",
        "raw_uppercase_ratio",
        "candidate_count",
        "matched_candidate_count",
        "matched_candidate_rate",
        "match_score",
        "trend_counts",
        "trend_num_hours",
        "trend_post_day_diff",
        "post_hour_utc",
        "post_day_of_week",
        "post_month",
        "actor_followers_count",
        "actor_follows_count",
        "actor_posts_count",
        "actor_followers_to_follows_ratio",
        "actor_description_char_count",
        "eng_like_count",
        "eng_reply_count",
        "eng_repost_count",
        "eng_quote_count",
        "engagement_total",
    ]
    for column in numeric_columns:
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors="coerce").fillna(0.0)

    out["match_stage"] = out["match_stage"].fillna("no_candidate")
    out["match_stage"] = pd.Categorical(out["match_stage"], categories=STAGE_ORDER, ordered=True)

    out["match_method"] = out["match_method"].fillna("none")
    out["temporal_pool_mode"] = out["temporal_pool_mode"].fillna("none")
    out["trend_name_clean"] = out["trend_name_clean"].fillna("")
    out["trend_date"] = out["trend_date"].fillna("")

    return out


def _build_coverage(df: pd.DataFrame, indicator_col: str) -> dict[str, Any]:
    counts = df[indicator_col].value_counts(dropna=False).to_dict()
    matched_rows = int(counts.get("both", 0))
    left_only = int(counts.get("left_only", 0))
    total_rows = int(len(df))
    return {
        "total_rows": total_rows,
        "matched_rows": matched_rows,
        "left_only_rows": left_only,
        "coverage_rate": float(matched_rows / total_rows) if total_rows else 0.0,
    }


def _profile_hydrated_file(path: Path, prepared_uris: set[str]) -> dict[str, Any]:
    row_count = 0
    uri_set: set[str] = set()
    for row in _iter_jsonl_gz(path):
        row_count += 1
        uri = _as_str(row.get("uri"))
        if uri:
            uri_set.add(uri)

    overlap = len(uri_set & prepared_uris)
    return {
        "file_path": path.as_posix(),
        "row_count": int(row_count),
        "unique_uri_count": int(len(uri_set)),
        "uri_overlap_count": int(overlap),
        "uri_overlap_rate": float(overlap / len(prepared_uris)) if prepared_uris else 0.0,
    }


def _profile_actor_file(path: Path, prepared_dids: set[str]) -> dict[str, Any]:
    row_count = 0
    did_set: set[str] = set()
    for row in _iter_jsonl_gz(path):
        row_count += 1
        did = _as_str(row.get("did"))
        if did:
            did_set.add(did)

    overlap = len(did_set & prepared_dids)
    return {
        "file_path": path.as_posix(),
        "row_count": int(row_count),
        "unique_did_count": int(len(did_set)),
        "did_overlap_count": int(overlap),
        "did_overlap_rate": float(overlap / len(prepared_dids)) if prepared_dids else 0.0,
    }


def _iter_jsonl_gz(path: Path | str) -> Iterable[dict[str, Any]]:
    target = Path(path)
    with gzip.open(target, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            yield json.loads(line)


def _resolve_config(config: FeatureConfig | dict[str, Any] | None) -> FeatureConfig:
    if config is None:
        return FeatureConfig()
    if isinstance(config, FeatureConfig):
        return config
    return FeatureConfig(**config)


def _validate_required_columns(df: pd.DataFrame, required: Iterable[str], name: str) -> None:
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(f"{name} missing required columns: {missing}")


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _unique_token_count(text: Any) -> int:
    if not isinstance(text, str):
        return 0
    tokens = [token for token in text.split() if token]
    return len(set(tokens))


def _count_char(text: Any, char: str) -> int:
    if not isinstance(text, str):
        return 0
    return text.count(char)


def _uppercase_ratio(text: Any) -> float:
    if not isinstance(text, str) or not text:
        return 0.0
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return 0.0
    upper = sum(1 for char in letters if char.isupper())
    return float(upper / len(letters))


def _fallback_count_labels(values: pd.Series) -> tuple[np.ndarray, str]:
    labels = np.where(
        values <= 0,
        "LOW",
        np.where(values == 1, "MEDIUM", "HIGH"),
    )
    return labels, "collapsed_quantile_or_empty_class"


__all__ = [
    "FeatureConfig",
    "build_local_engagement_feature_table",
    "get_feature_column_groups",
    "load_actor_profiles_file",
    "load_hydrated_metrics_file",
    "select_best_actor_profile_source_file",
    "select_best_hydrated_source_file",
    "summarize_feature_table",
]
