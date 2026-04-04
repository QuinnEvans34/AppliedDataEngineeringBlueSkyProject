"""Deterministic local normalization helpers for Twitter trend names."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

import pandas as pd

MULTISPACE_RE = re.compile(r"\s+")
SEPARATOR_RE = re.compile(r"[&\-\.,/_]+")
NON_WORD_KEEP_HASH_DOLLAR_RE = re.compile(r"[^\w\s#$]", flags=re.UNICODE)
NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]")
SPECIAL_RE = re.compile(r"[^A-Za-z0-9\s]")
NON_ASCII_RE = re.compile(r"[^\x00-\x7F]")
URL_LIKE_RE = re.compile(
    r"(https?://\S+|www\.\S+|\b[a-z0-9-]+\.[a-z]{2,}\b)",
    flags=re.IGNORECASE,
)


def normalize_trend_name(name: str | None) -> dict[str, Any]:
    """Normalize one trend name and return deterministic helper fields."""

    trend_name_raw = name if isinstance(name, str) else ""
    is_blank_raw = trend_name_raw.strip() == ""

    nfkc = unicodedata.normalize("NFKC", trend_name_raw)
    nfkc = nfkc.replace("’", "'").replace("‘", "'")

    lowered = nfkc.casefold().strip()
    lowered = MULTISPACE_RE.sub(" ", lowered)

    normalized_key_with_hash = _normalize_core(lowered)
    normalized_key_no_hash = _normalize_core(_drop_one_leading_symbol(lowered, "#"))
    normalized_key_no_dollar = _normalize_core(
        _drop_one_leading_symbol(normalized_key_no_hash, "$")
    )

    trend_name_alnum = _alnum_key(normalized_key_no_hash)
    trend_name_token_count = len(normalized_key_no_hash.split()) if normalized_key_no_hash else 0
    trend_name_char_count = len(normalized_key_no_hash)

    stripped_raw = trend_name_raw.strip()
    is_hashtag = stripped_raw.startswith("#")
    has_special_chars = bool(SPECIAL_RE.search(trend_name_raw))
    has_non_ascii = bool(NON_ASCII_RE.search(trend_name_raw))
    has_url_like = bool(URL_LIKE_RE.search(trend_name_raw))

    return {
        "trend_name_raw": trend_name_raw,
        "trend_name_clean": normalized_key_with_hash,
        "trend_name_clean_no_hash": normalized_key_no_hash,
        "trend_name_clean_no_dollar": normalized_key_no_dollar,
        "trend_name_alnum": trend_name_alnum,
        "trend_name_token_count": trend_name_token_count,
        "trend_name_char_count": trend_name_char_count,
        "is_blank_raw": is_blank_raw,
        "is_hashtag": is_hashtag,
        "has_special_chars": has_special_chars,
        "has_non_ascii": has_non_ascii,
        "has_url_like": has_url_like,
        "normalized_key_with_hash": normalized_key_with_hash,
        "normalized_key_no_hash": normalized_key_no_hash,
        "normalized_key_no_dollar": normalized_key_no_dollar,
    }


def normalize_twitter_trending_dataframe(
    df: pd.DataFrame,
    *,
    trend_name_column: str = "name",
    date_column: str = "date",
) -> pd.DataFrame:
    """Return a copy of a Twitter trending DataFrame with derived normalization columns."""

    if trend_name_column not in df.columns:
        raise ValueError(
            f"Missing trend-name column: {trend_name_column!r}. "
            f"Available columns: {list(df.columns)!r}"
        )

    normalized = df.copy()
    norm_records = normalized[trend_name_column].map(normalize_trend_name)
    norm_df = pd.DataFrame(norm_records.tolist(), index=normalized.index)
    normalized = pd.concat([normalized, norm_df], axis=1)

    if date_column in normalized.columns:
        normalized_date = pd.to_datetime(
            normalized[date_column], errors="coerce"
        ).dt.strftime("%Y-%m-%d")
        normalized["normalized_date"] = normalized_date.fillna("")

    return normalized


def summarize_duplicate_impact(
    df_raw: pd.DataFrame,
    df_normalized: pd.DataFrame,
    *,
    date_column: str = "date",
    raw_name_column: str = "name",
    normalized_name_column: str = "normalized_key_no_hash",
    max_examples: int = 20,
) -> dict[str, Any]:
    """Summarize duplicate impact before/after normalization with collapse examples."""

    before_dup = int(df_raw.duplicated(subset=[date_column, raw_name_column]).sum())
    after_dup = int(
        df_normalized.duplicated(subset=[date_column, normalized_name_column]).sum()
    )

    grouped = (
        df_normalized.groupby([date_column, normalized_name_column], dropna=False)[
            raw_name_column
        ]
        .agg(["nunique", "size"])
        .reset_index()
    )
    collapsed = grouped[grouped["nunique"] > 1].sort_values(
        ["nunique", "size"], ascending=False
    )

    examples: list[dict[str, Any]] = []
    for _, row in collapsed.head(max_examples).iterrows():
        date_value = row[date_column]
        norm_value = row[normalized_name_column]
        variants = (
            df_normalized[
                (df_normalized[date_column] == date_value)
                & (df_normalized[normalized_name_column] == norm_value)
            ][raw_name_column]
            .drop_duplicates()
            .head(8)
            .tolist()
        )
        examples.append(
            {
                "date": str(date_value),
                "normalized_key_no_hash": str(norm_value),
                "raw_variant_count": int(row["nunique"]),
                "row_count": int(row["size"]),
                "raw_variants": [str(v) for v in variants],
            }
        )

    return {
        "duplicate_date_name_before": before_dup,
        "duplicate_date_normalized_no_hash_after": after_dup,
        "net_duplicate_delta_after_minus_before": after_dup - before_dup,
        "collapsed_key_count_with_multi_raw_variants": int(len(collapsed)),
        "collapsed_examples": examples,
    }


def _drop_one_leading_symbol(value: str, symbol: str) -> str:
    stripped = value.lstrip()
    if stripped.startswith(symbol):
        return stripped[1:].lstrip()
    return stripped


def _normalize_core(value: str) -> str:
    normalized = SEPARATOR_RE.sub(" ", value)
    normalized = normalized.replace("'", " ")
    normalized = NON_WORD_KEEP_HASH_DOLLAR_RE.sub(" ", normalized)
    normalized = MULTISPACE_RE.sub(" ", normalized)
    return normalized.strip()


def _alnum_key(value: str) -> str:
    alnum = NON_ALNUM_RE.sub(" ", value)
    alnum = MULTISPACE_RE.sub(" ", alnum)
    return alnum.strip()
