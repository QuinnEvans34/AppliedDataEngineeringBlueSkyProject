"""Deterministic local staged matching from Bluesky candidates to Twitter trends."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from typing import Any

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

CANDIDATE_REQUIRED_COLUMNS = [
    "uri",
    "post_created_at",
    "candidate_phrase_clean",
    "candidate_phrase_alnum",
    "candidate_source_type",
]

TREND_REQUIRED_COLUMNS = [
    "name",
    "normalized_key_no_hash",
    "trend_name_clean",
    "normalized_date",
    "counts",
    "num_hours",
]

STAGE_PRIORITY = {
    "exact": 0,
    "fuzzy": 1,
    "semantic": 2,
    "unmatched": 3,
}

LEXICAL_BLOCK_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "from",
    "he",
    "her",
    "his",
    "i",
    "in",
    "is",
    "it",
    "its",
    "me",
    "my",
    "of",
    "on",
    "or",
    "our",
    "she",
    "that",
    "the",
    "their",
    "them",
    "they",
    "this",
    "to",
    "us",
    "we",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
    "you",
    "your",
}


@dataclass(frozen=True)
class MatchConfig:
    date_window_days: int = 3
    fuzzy_min_score: float = 0.88
    semantic_min_score: float = 0.60
    max_stage_pool: int = 5000
    semantic_pool_top_k: int = 250


def match_post_candidates_to_trends(
    candidates_df: pd.DataFrame,
    trends_df: pd.DataFrame,
    config: MatchConfig | dict[str, Any] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Run staged exact->fuzzy->semantic matching and return full + best + summary."""

    cfg = _resolve_config(config)
    _validate_candidate_schema(candidates_df)
    _validate_trend_schema(trends_df)

    candidates = _prepare_candidates(candidates_df)
    trends = _prepare_trends(trends_df)
    trend_rows = trends.to_dict(orient="records")
    trend_keys = [str(value) for value in trends["trend_key_no_hash"].tolist()]
    trend_names = [str(value) for value in trends["trend_name_clean"].tolist()]
    trend_counts = [_safe_float(value) for value in trends["counts_numeric"].tolist()]

    exact_index = _build_exact_index(trends)
    token_index = _build_trend_token_index(trends)
    trends_by_date = _build_trend_date_index(trends)
    all_trend_ids = trends["trend_id"].tolist()
    global_top_trend_ids = (
        trends.sort_values(
            ["counts_numeric", "trend_name_clean"],
            ascending=[False, True],
            kind="stable",
        )["trend_id"]
        .astype(int)
        .tolist()
    )

    print("  Building TF-IDF index...")
    tfidf_vectorizer, tfidf_matrix = _build_tfidf_index(trend_keys)
    print("  Building FAISS semantic index...")
    sentence_model, faiss_index = _build_faiss_index(trend_keys)
    print("  Index build complete.")

    output_rows: list[dict[str, Any]] = []
    total_candidates = len(candidates)
    _progress_interval = max(1, total_candidates // 20)

    for candidate in candidates.itertuples(index=False):
        candidate_row = candidate._asdict()
        candidate_id = int(candidate_row["candidate_id"])

        if candidate_id % _progress_interval == 0:
            print(f"  Matching candidate {candidate_id:,} / {total_candidates:,} ({candidate_id * 100 // total_candidates}%)")

        temporal_pool, temporal_pool_mode = _temporal_pool_for_candidate(
            candidate_row=candidate_row,
            trends_by_date=trends_by_date,
            all_trend_ids=all_trend_ids,
            cfg=cfg,
        )
        temporal_pool_set = set(temporal_pool)
        candidate_key = str(candidate_row.get("candidate_key", ""))

        if not candidate_key:
            output_rows.append(
                _build_unmatched_row(
                    candidate_row=candidate_row,
                    temporal_pool_mode=temporal_pool_mode,
                )
            )
            continue

        exact_matches = _match_exact(
            candidate_row=candidate_row,
            exact_index=exact_index,
            temporal_pool_set=temporal_pool_set,
            trend_rows=trend_rows,
            trend_counts=trend_counts,
            trend_names=trend_names,
        )
        if exact_matches:
            output_rows.extend(
                _build_stage_rows(
                    candidate_row=candidate_row,
                    trend_matches=exact_matches,
                    stage="exact",
                    method="normalized_equality",
                    temporal_pool_mode=temporal_pool_mode,
                )
            )
            continue

        stage_pool, tfidf_pre_scores = _build_stage_pool(
            candidate_row=candidate_row,
            temporal_pool=temporal_pool,
            token_index=token_index,
            global_top_trend_ids=global_top_trend_ids,
            trend_keys=trend_keys,
            trend_counts=trend_counts,
            trend_names=trend_names,
            tfidf_vectorizer=tfidf_vectorizer,
            tfidf_matrix=tfidf_matrix,
            cfg=cfg,
        )

        fuzzy_matches = _match_fuzzy(
            candidate_row=candidate_row,
            trend_ids=stage_pool,
            trend_rows=trend_rows,
            trend_keys=trend_keys,
            trend_counts=trend_counts,
            trend_names=trend_names,
            tfidf_pre_scores=tfidf_pre_scores,
            cfg=cfg,
        )
        if fuzzy_matches:
            output_rows.extend(
                _build_stage_rows(
                    candidate_row=candidate_row,
                    trend_matches=fuzzy_matches,
                    stage="fuzzy",
                    method="difflib_sequence_ratio",
                    temporal_pool_mode=temporal_pool_mode,
                )
            )
            continue

        semantic_pool = _semantic_pool_from_faiss(
            candidate_row=candidate_row,
            temporal_pool=temporal_pool,
            sentence_model=sentence_model,
            faiss_index=faiss_index,
            cfg=cfg,
        )
        semantic_matches = _match_semantic(
            candidate_row=candidate_row,
            trend_ids=semantic_pool,
            trend_rows=trend_rows,
            trend_keys=trend_keys,
            trend_counts=trend_counts,
            trend_names=trend_names,
            cfg=cfg,
        )
        if semantic_matches:
            output_rows.extend(
                _build_stage_rows(
                    candidate_row=candidate_row,
                    trend_matches=semantic_matches,
                    stage="semantic",
                    method="token_cosine_char_trigram",
                    temporal_pool_mode=temporal_pool_mode,
                )
            )
            continue

        output_rows.append(
            _build_unmatched_row(
                candidate_row=candidate_row,
                temporal_pool_mode=temporal_pool_mode,
            )
        )

    print(f"  Matching complete: {total_candidates:,} candidates processed.")

    full_matches_df = pd.DataFrame(output_rows)
    if full_matches_df.empty:
        full_matches_df = pd.DataFrame(columns=_output_columns())
    else:
        full_matches_df = full_matches_df[_output_columns()]

    full_matches_df = _apply_ambiguity_flags(full_matches_df)
    full_matches_df = full_matches_df.sort_values(
        ["candidate_id", "stage_rank", "trend_name_clean"],
        kind="stable",
    ).reset_index(drop=True)

    best_matches_df = select_best_post_matches(full_matches_df)
    summary = summarize_match_results(
        full_matches_df=full_matches_df,
        best_matches_df=best_matches_df,
        cfg=cfg,
    )

    return full_matches_df, best_matches_df, summary


def select_best_post_matches(full_matches_df: pd.DataFrame) -> pd.DataFrame:
    """Select one deterministic best match row per post URI."""

    if full_matches_df.empty:
        return full_matches_df.copy()

    ranked = full_matches_df.copy()
    ranked["_stage_priority"] = ranked["match_stage"].map(STAGE_PRIORITY).fillna(99)
    ranked["_counts_for_sort"] = pd.to_numeric(ranked["trend_counts"], errors="coerce").fillna(-1e18)

    ranked = ranked.sort_values(
        [
            "uri",
            "_stage_priority",
            "match_score",
            "_counts_for_sort",
            "trend_name_clean",
            "candidate_rank_in_post",
            "candidate_phrase_alnum",
        ],
        ascending=[True, True, False, False, True, True, True],
        kind="stable",
    )

    best = ranked.groupby("uri", as_index=False).head(1).copy()
    best = best.drop(columns=["_stage_priority", "_counts_for_sort"])
    return best.reset_index(drop=True)


def summarize_match_results(
    *,
    full_matches_df: pd.DataFrame,
    best_matches_df: pd.DataFrame,
    cfg: MatchConfig,
) -> dict[str, Any]:
    """Summarize staged matching results for diagnostics and reporting."""

    if full_matches_df.empty:
        return {
            "config": asdict(cfg),
            "total_candidate_rows": 0,
            "total_unique_candidates": 0,
            "total_unique_posts": 0,
            "candidate_stage_counts": {},
            "post_stage_counts": {},
            "post_matched_rate": 0.0,
            "ambiguous_candidate_count": 0,
            "ambiguous_candidate_rate": 0.0,
            "full_row_stage_counts": {},
            "temporal_pool_mode_counts": {},
        }

    candidate_best = _best_row_per_candidate(full_matches_df)

    candidate_stage_counts = {
        str(stage): int(count)
        for stage, count in candidate_best["match_stage"].value_counts(dropna=False).items()
    }
    post_stage_counts = {
        str(stage): int(count)
        for stage, count in best_matches_df["match_stage"].value_counts(dropna=False).items()
    }

    post_total = int(best_matches_df["uri"].nunique())
    post_matched = int(best_matches_df.loc[best_matches_df["is_matched"], "uri"].nunique())

    ambiguous_candidates = int(
        full_matches_df.loc[full_matches_df["is_ambiguous"], "candidate_id"].nunique()
    )
    unique_candidates = int(full_matches_df["candidate_id"].nunique())

    summary = {
        "config": asdict(cfg),
        "total_candidate_rows": int(len(full_matches_df)),
        "total_unique_candidates": unique_candidates,
        "total_unique_posts": post_total,
        "candidate_stage_counts": candidate_stage_counts,
        "post_stage_counts": post_stage_counts,
        "post_matched_rate": float(post_matched / post_total) if post_total else 0.0,
        "ambiguous_candidate_count": ambiguous_candidates,
        "ambiguous_candidate_rate": float(ambiguous_candidates / unique_candidates)
        if unique_candidates
        else 0.0,
        "full_row_stage_counts": {
            str(stage): int(count)
            for stage, count in full_matches_df["match_stage"].value_counts(dropna=False).items()
        },
        "temporal_pool_mode_counts": {
            str(mode): int(count)
            for mode, count in candidate_best["temporal_pool_mode"].value_counts(dropna=False).items()
        },
        "top_exact_trends": _top_matches_for_stage(full_matches_df, stage="exact"),
        "top_fuzzy_trends": _top_matches_for_stage(full_matches_df, stage="fuzzy"),
        "top_semantic_trends": _top_matches_for_stage(full_matches_df, stage="semantic"),
    }
    return summary


def _resolve_config(config: MatchConfig | dict[str, Any] | None) -> MatchConfig:
    if config is None:
        return MatchConfig()
    if isinstance(config, MatchConfig):
        return config
    if isinstance(config, dict):
        return MatchConfig(**config)
    raise TypeError(f"Unsupported config type: {type(config)!r}")


def _validate_candidate_schema(df: pd.DataFrame) -> None:
    missing = [column for column in CANDIDATE_REQUIRED_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(
            f"Candidate dataframe missing required columns: {missing!r}. "
            f"Available: {list(df.columns)!r}"
        )


def _validate_trend_schema(df: pd.DataFrame) -> None:
    missing = [column for column in TREND_REQUIRED_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(
            f"Trend dataframe missing required columns: {missing!r}. "
            f"Available: {list(df.columns)!r}"
        )


def _prepare_candidates(df: pd.DataFrame) -> pd.DataFrame:
    prepared = df.copy().reset_index(drop=True)
    prepared["candidate_id"] = np.arange(len(prepared), dtype=int)
    prepared["candidate_phrase_clean"] = prepared["candidate_phrase_clean"].fillna("").astype(str)
    prepared["candidate_phrase_alnum"] = prepared["candidate_phrase_alnum"].fillna("").astype(str)
    prepared["candidate_key"] = prepared["candidate_phrase_alnum"].map(_normalize_key)
    prepared["candidate_tokens"] = prepared["candidate_key"].map(_tokenize)

    parsed_dates = pd.to_datetime(prepared["post_created_at"], errors="coerce", utc=True)
    prepared["candidate_date"] = parsed_dates.dt.floor("D")
    return prepared


def _prepare_trends(df: pd.DataFrame) -> pd.DataFrame:
    prepared = df.copy().reset_index(drop=True)
    prepared["trend_id"] = np.arange(len(prepared), dtype=int)
    prepared["trend_name_raw"] = prepared["name"].fillna("").astype(str)
    prepared["trend_name_clean"] = prepared["trend_name_clean"].fillna("").astype(str)
    prepared["trend_key_no_hash"] = prepared["normalized_key_no_hash"].fillna("").astype(str).map(
        _normalize_key
    )
    prepared["trend_tokens"] = prepared["trend_key_no_hash"].map(_tokenize)
    prepared["trend_date"] = pd.to_datetime(prepared["normalized_date"], errors="coerce", utc=True).dt.floor("D")
    prepared["counts_numeric"] = pd.to_numeric(prepared["counts"], errors="coerce")
    prepared["num_hours_numeric"] = pd.to_numeric(prepared["num_hours"], errors="coerce")
    return prepared


def _build_exact_index(trends: pd.DataFrame) -> dict[str, list[int]]:
    index: dict[str, list[int]] = {}
    grouped = trends.groupby("trend_key_no_hash", sort=False)["trend_id"].apply(list)
    for key, trend_ids in grouped.items():
        index[str(key)] = list(trend_ids)
    return index


def _build_trend_token_index(trends: pd.DataFrame) -> dict[str, list[int]]:
    token_map: dict[str, list[int]] = {}
    for row in trends[["trend_id", "trend_tokens"]].itertuples(index=False):
        trend_id = int(row.trend_id)
        tokens = list(dict.fromkeys(row.trend_tokens))
        for token in tokens:
            token_map.setdefault(token, []).append(trend_id)
    return token_map


def _build_trend_date_index(trends: pd.DataFrame) -> dict[pd.Timestamp, list[int]]:
    result: dict[pd.Timestamp, list[int]] = {}
    valid = trends.dropna(subset=["trend_date"])
    for date_value, slice_df in valid.groupby("trend_date", sort=False):
        result[pd.Timestamp(date_value)] = slice_df["trend_id"].astype(int).tolist()
    return result


def _build_tfidf_index(
    trend_keys: list[str],
) -> tuple[TfidfVectorizer, Any]:
    """Build TF-IDF char-ngram index over all trend keys. Called once."""

    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 3))
    tfidf_matrix = vectorizer.fit_transform(trend_keys)
    return vectorizer, tfidf_matrix


def _build_faiss_index(
    trend_keys: list[str],
) -> tuple[Any, Any]:
    """Build FAISS inner-product index over sentence embeddings. Called once."""

    import faiss
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer("all-MiniLM-L6-v2")
    embeddings = model.encode(
        trend_keys, batch_size=256, show_progress_bar=True,
    ).astype("float32")
    faiss.normalize_L2(embeddings)

    dimension = embeddings.shape[1]
    index = faiss.IndexFlatIP(dimension)
    index.add(embeddings)
    return model, index


def _temporal_pool_for_candidate(
    *,
    candidate_row: dict[str, Any],
    trends_by_date: dict[pd.Timestamp, list[int]],
    all_trend_ids: list[int],
    cfg: MatchConfig,
) -> tuple[list[int], str]:
    candidate_date = candidate_row.get("candidate_date")
    if pd.isna(candidate_date):
        return list(all_trend_ids), "global_fallback_no_candidate_date"

    candidate_date = pd.Timestamp(candidate_date)
    pool: list[int] = []
    for day_offset in range(-cfg.date_window_days, cfg.date_window_days + 1):
        target = candidate_date + pd.Timedelta(days=day_offset)
        pool.extend(trends_by_date.get(target, []))

    pool = list(dict.fromkeys(pool))
    if pool:
        return pool, "date_window"
    return list(all_trend_ids), "global_fallback_no_date_overlap"


def _match_exact(
    *,
    candidate_row: dict[str, Any],
    exact_index: dict[str, list[int]],
    temporal_pool_set: set[int],
    trend_rows: list[dict[str, Any]],
    trend_counts: list[float],
    trend_names: list[str],
) -> list[dict[str, Any]]:
    candidate_key = str(candidate_row.get("candidate_key", ""))
    if not candidate_key:
        return []

    trend_ids = [trend_id for trend_id in exact_index.get(candidate_key, []) if trend_id in temporal_pool_set]
    if not trend_ids:
        return []

    stage_rows: list[dict[str, Any]] = []
    for trend_id in trend_ids:
        trend_row = trend_rows[int(trend_id)]
        stage_rows.append(
            {
                "trend_id": int(trend_id),
                "trend_row": trend_row,
                "match_score": 1.0,
                "lexical_score": 1.0,
                "semantic_token_cosine": np.nan,
                "semantic_char_trigram_jaccard": np.nan,
            }
        )

    stage_rows = sorted(
        stage_rows,
        key=lambda row: (
            -trend_counts[int(row["trend_id"])],
            trend_names[int(row["trend_id"])],
        ),
    )
    return stage_rows


def _build_stage_pool(
    *,
    candidate_row: dict[str, Any],
    temporal_pool: list[int],
    token_index: dict[str, list[int]],
    global_top_trend_ids: list[int],
    trend_keys: list[str],
    trend_counts: list[float],
    trend_names: list[str],
    tfidf_vectorizer: TfidfVectorizer,
    tfidf_matrix: Any,
    cfg: MatchConfig,
) -> tuple[list[int], dict[int, float]]:
    candidate_tokens = [
        token
        for token in candidate_row.get("candidate_tokens", [])
        if token and token not in LEXICAL_BLOCK_STOPWORDS
    ]

    # lexical blocking by token overlap
    blocked_ids: list[int] = []
    for token in candidate_tokens:
        blocked_ids.extend(token_index.get(token, []))

    blocked_ids = list(dict.fromkeys(blocked_ids))
    temporal_pool_set = set(temporal_pool)

    if blocked_ids:
        pool = [trend_id for trend_id in blocked_ids if trend_id in temporal_pool_set]
    elif not candidate_tokens:
        pool = []
        for trend_id in global_top_trend_ids:
            if trend_id in temporal_pool_set:
                pool.append(trend_id)
                if len(pool) >= cfg.max_stage_pool:
                    break
    else:
        pool = list(temporal_pool)

    # Vectorized TF-IDF cosine scoring replaces per-trend SequenceMatcher loop.
    candidate_key = str(candidate_row.get("candidate_key", ""))
    if not pool or not candidate_key:
        return pool[: cfg.max_stage_pool], {}

    candidate_vec = tfidf_vectorizer.transform([candidate_key])
    all_tfidf_scores = linear_kernel(candidate_vec, tfidf_matrix).flatten()
    tfidf_pre_scores: dict[int, float] = {
        int(tid): float(all_tfidf_scores[int(tid)]) for tid in pool
    }

    ranked_pool = sorted(
        pool,
        key=lambda trend_id: (
            -tfidf_pre_scores.get(int(trend_id), 0.0),
            -trend_counts[int(trend_id)],
            trend_names[int(trend_id)],
        ),
    )
    capped_pool = ranked_pool[: cfg.max_stage_pool]
    return capped_pool, tfidf_pre_scores


_TFIDF_PREFILTER_THRESHOLD = 0.20


def _match_fuzzy(
    *,
    candidate_row: dict[str, Any],
    trend_ids: list[int],
    trend_rows: list[dict[str, Any]],
    trend_keys: list[str],
    trend_counts: list[float],
    trend_names: list[str],
    tfidf_pre_scores: dict[int, float] | None = None,
    cfg: MatchConfig,
) -> list[dict[str, Any]]:
    candidate_key = str(candidate_row.get("candidate_key", ""))
    if not candidate_key or not trend_ids:
        return []

    hits: list[dict[str, Any]] = []
    for trend_id in trend_ids:
        # TF-IDF pre-filter: skip trends with low char-ngram similarity to
        # avoid expensive SequenceMatcher calls on obvious non-matches.
        if tfidf_pre_scores is not None:
            tfidf_score = tfidf_pre_scores.get(int(trend_id), 0.0)
            if tfidf_score < _TFIDF_PREFILTER_THRESHOLD:
                continue

        trend_key = trend_keys[int(trend_id)]
        score = _sequence_ratio(candidate_key, trend_key)
        if score >= cfg.fuzzy_min_score:
            trend_row = trend_rows[int(trend_id)]
            hits.append(
                {
                    "trend_id": int(trend_id),
                    "trend_row": trend_row,
                    "match_score": float(score),
                    "lexical_score": float(score),
                    "semantic_token_cosine": np.nan,
                    "semantic_char_trigram_jaccard": np.nan,
                }
            )

    hits = sorted(
        hits,
        key=lambda row: (
            -row["match_score"],
            -trend_counts[int(row["trend_id"])],
            trend_names[int(row["trend_id"])],
        ),
    )
    return hits


def _semantic_pool_from_faiss(
    *,
    candidate_row: dict[str, Any],
    temporal_pool: list[int],
    sentence_model: Any,
    faiss_index: Any,
    cfg: MatchConfig,
) -> list[int]:
    """Retrieve semantic nearest-neighbor candidates via FAISS."""

    import faiss as _faiss

    candidate_key = str(candidate_row.get("candidate_key", ""))
    if not candidate_key:
        return []

    embedding = sentence_model.encode([candidate_key]).astype("float32")
    _faiss.normalize_L2(embedding)

    k = min(cfg.semantic_pool_top_k * 4, faiss_index.ntotal)
    if k == 0:
        return []
    _, indices = faiss_index.search(embedding, k)

    temporal_set = set(temporal_pool)
    pool = [int(idx) for idx in indices[0] if idx != -1 and int(idx) in temporal_set]
    return pool[: cfg.semantic_pool_top_k]


def _match_semantic(
    *,
    candidate_row: dict[str, Any],
    trend_ids: list[int],
    trend_rows: list[dict[str, Any]],
    trend_keys: list[str],
    trend_counts: list[float],
    trend_names: list[str],
    cfg: MatchConfig,
) -> list[dict[str, Any]]:
    candidate_phrase = str(candidate_row.get("candidate_key", ""))
    if not candidate_phrase or not trend_ids:
        return []

    hits: list[dict[str, Any]] = []
    candidate_trigrams = _char_ngrams(candidate_phrase, n=3)
    candidate_tokens_counted = _token_counts(candidate_phrase)
    matcher = SequenceMatcher(a=candidate_phrase)
    for trend_id in trend_ids:
        trend_row = trend_rows[int(trend_id)]
        trend_phrase = trend_keys[int(trend_id)]

        token_cosine = _token_cosine_from_counts(candidate_tokens_counted, _token_counts(trend_phrase))
        trigram_jaccard = _char_trigram_jaccard_from_sets(candidate_trigrams, _char_ngrams(trend_phrase, n=3))
        combined = 0.7 * token_cosine + 0.3 * trigram_jaccard

        if combined >= cfg.semantic_min_score:
            matcher.set_seq2(trend_phrase)
            hits.append(
                {
                    "trend_id": int(trend_id),
                    "trend_row": trend_row,
                    "match_score": float(combined),
                    "lexical_score": float(matcher.ratio()),
                    "semantic_token_cosine": float(token_cosine),
                    "semantic_char_trigram_jaccard": float(trigram_jaccard),
                }
            )

    hits = sorted(
        hits,
        key=lambda row: (
            -row["match_score"],
            -trend_counts[int(row["trend_id"])],
            trend_names[int(row["trend_id"])],
        ),
    )
    return hits


def _build_stage_rows(
    *,
    candidate_row: dict[str, Any],
    trend_matches: list[dict[str, Any]],
    stage: str,
    method: str,
    temporal_pool_mode: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rank, match in enumerate(trend_matches, start=1):
        trend_row = match["trend_row"]
        row = _candidate_context(candidate_row)
        row.update(
            {
                "trend_id": int(match["trend_id"]),
                "trend_date": trend_row.get("normalized_date"),
                "trend_name_raw": trend_row.get("trend_name_raw"),
                "trend_name_clean": trend_row.get("trend_name_clean"),
                "trend_key_no_hash": trend_row.get("trend_key_no_hash"),
                "trend_counts": _safe_float(trend_row.get("counts_numeric")),
                "trend_num_hours": _safe_float(trend_row.get("num_hours_numeric")),
                "match_stage": stage,
                "match_method": method,
                "match_score": float(match["match_score"]),
                "lexical_score": float(match.get("lexical_score", np.nan)),
                "semantic_token_cosine": match.get("semantic_token_cosine", np.nan),
                "semantic_char_trigram_jaccard": match.get(
                    "semantic_char_trigram_jaccard", np.nan
                ),
                "stage_rank": int(rank),
                "temporal_pool_mode": temporal_pool_mode,
                "is_matched": True,
                "is_ambiguous": False,
                "ambiguity_count": 0,
            }
        )
        rows.append(row)
    return rows


def _build_unmatched_row(*, candidate_row: dict[str, Any], temporal_pool_mode: str) -> dict[str, Any]:
    row = _candidate_context(candidate_row)
    row.update(
        {
            "trend_id": np.nan,
            "trend_date": "",
            "trend_name_raw": "",
            "trend_name_clean": "",
            "trend_key_no_hash": "",
            "trend_counts": np.nan,
            "trend_num_hours": np.nan,
            "match_stage": "unmatched",
            "match_method": "none",
            "match_score": 0.0,
            "lexical_score": np.nan,
            "semantic_token_cosine": np.nan,
            "semantic_char_trigram_jaccard": np.nan,
            "stage_rank": 1,
            "temporal_pool_mode": temporal_pool_mode,
            "is_matched": False,
            "is_ambiguous": False,
            "ambiguity_count": 0,
        }
    )
    return row


def _candidate_context(candidate_row: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": int(candidate_row["candidate_id"]),
        "uri": str(candidate_row.get("uri", "")),
        "post_created_at": str(candidate_row.get("post_created_at", "")),
        "post_text_raw": str(candidate_row.get("post_text_raw", "")),
        "post_text_clean": str(candidate_row.get("post_text_clean", "")),
        "candidate_phrase_raw": str(candidate_row.get("candidate_phrase_raw", "")),
        "candidate_phrase_clean": str(candidate_row.get("candidate_phrase_clean", "")),
        "candidate_phrase_alnum": str(candidate_row.get("candidate_phrase_alnum", "")),
        "candidate_source_type": str(candidate_row.get("candidate_source_type", "")),
        "candidate_rank_in_post": int(candidate_row.get("candidate_rank_in_post", 0) or 0),
    }


def _apply_ambiguity_flags(full_matches_df: pd.DataFrame) -> pd.DataFrame:
    if full_matches_df.empty:
        return full_matches_df

    out = full_matches_df.copy()
    matched = out[out["is_matched"]].copy()
    if matched.empty:
        return out

    ambiguity = matched.groupby("candidate_id").size().rename("ambiguity_count")
    out = out.merge(ambiguity, on="candidate_id", how="left", suffixes=("", "_new"))
    out["ambiguity_count"] = (
        out["ambiguity_count_new"].fillna(out["ambiguity_count"]).fillna(0).astype(int)
    )
    out = out.drop(columns=["ambiguity_count_new"])
    out["is_ambiguous"] = out["ambiguity_count"] > 1
    out.loc[~out["is_matched"], "is_ambiguous"] = False
    out.loc[~out["is_matched"], "ambiguity_count"] = 0
    return out


def _best_row_per_candidate(full_matches_df: pd.DataFrame) -> pd.DataFrame:
    ranked = full_matches_df.copy()
    ranked["_stage_priority"] = ranked["match_stage"].map(STAGE_PRIORITY).fillna(99)
    ranked["_counts_for_sort"] = pd.to_numeric(ranked["trend_counts"], errors="coerce").fillna(-1e18)

    ranked = ranked.sort_values(
        [
            "candidate_id",
            "_stage_priority",
            "match_score",
            "_counts_for_sort",
            "trend_name_clean",
            "stage_rank",
        ],
        ascending=[True, True, False, False, True, True],
        kind="stable",
    )

    best = ranked.groupby("candidate_id", as_index=False).head(1).copy()
    best = best.drop(columns=["_stage_priority", "_counts_for_sort"])
    return best.reset_index(drop=True)


def _top_matches_for_stage(full_matches_df: pd.DataFrame, stage: str) -> list[dict[str, Any]]:
    subset = full_matches_df[(full_matches_df["match_stage"] == stage) & (full_matches_df["is_matched"])]
    if subset.empty:
        return []

    counts = subset["trend_name_clean"].value_counts(dropna=False).head(10)
    return [
        {"trend_name_clean": str(name), "count": int(count)}
        for name, count in counts.items()
    ]


def _normalize_key(value: str) -> str:
    return " ".join(str(value).strip().casefold().split())


def _tokenize(value: str) -> list[str]:
    return [token for token in _normalize_key(value).split(" ") if token]


def _sequence_ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return float(SequenceMatcher(a=a, b=b).ratio())


def _token_counts(value: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for token in _tokenize(value):
        counts[token] = counts.get(token, 0) + 1
    return counts


def _token_cosine_from_counts(counts_a: dict[str, int], counts_b: dict[str, int]) -> float:
    if not counts_a or not counts_b:
        return 0.0

    vocab = set(counts_a) | set(counts_b)
    dot = float(sum(counts_a.get(token, 0) * counts_b.get(token, 0) for token in vocab))
    norm_a = float(np.sqrt(sum(v * v for v in counts_a.values())))
    norm_b = float(np.sqrt(sum(v * v for v in counts_b.values())))

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _token_cosine_similarity(a: str, b: str) -> float:
    return _token_cosine_from_counts(_token_counts(a), _token_counts(b))


def _char_trigram_jaccard_from_sets(grams_a: set[str], grams_b: set[str]) -> float:
    if not grams_a or not grams_b:
        return 0.0
    intersection = len(grams_a & grams_b)
    union = len(grams_a | grams_b)
    if union == 0:
        return 0.0
    return float(intersection / union)


def _char_trigram_jaccard(a: str, b: str) -> float:
    return _char_trigram_jaccard_from_sets(_char_ngrams(a, n=3), _char_ngrams(b, n=3))


def _char_ngrams(value: str, n: int) -> set[str]:
    text = _normalize_key(value)
    if not text:
        return set()
    if len(text) < n:
        return {text}
    return {text[i : i + n] for i in range(0, len(text) - n + 1)}


def _safe_float(value: Any) -> float:
    try:
        if pd.isna(value):
            return float("nan")
    except Exception:
        pass
    try:
        return float(value)
    except Exception:
        return float("nan")


def _output_columns() -> list[str]:
    return [
        "candidate_id",
        "uri",
        "post_created_at",
        "post_text_raw",
        "post_text_clean",
        "candidate_phrase_raw",
        "candidate_phrase_clean",
        "candidate_phrase_alnum",
        "candidate_source_type",
        "candidate_rank_in_post",
        "trend_id",
        "trend_date",
        "trend_name_raw",
        "trend_name_clean",
        "trend_key_no_hash",
        "trend_counts",
        "trend_num_hours",
        "match_stage",
        "match_method",
        "match_score",
        "lexical_score",
        "semantic_token_cosine",
        "semantic_char_trigram_jaccard",
        "stage_rank",
        "temporal_pool_mode",
        "is_matched",
        "is_ambiguous",
        "ambiguity_count",
    ]
