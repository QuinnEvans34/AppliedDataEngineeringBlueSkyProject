"""Deterministic local topic candidate generation for prepared Bluesky posts."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from typing import Any, Iterable

import pandas as pd

REQUIRED_PREPARED_COLUMNS = [
    "uri",
    "post_created_at",
    "post_text_raw",
    "post_text_clean",
    "post_text_alnum",
]

SOURCE_PRIORITY = {
    "hashtag": 0,
    "ngram_4": 1,
    "ngram_3": 2,
    "ngram_2": 3,
    "unigram_fallback": 4,
}

STOPWORDS = {
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
    "has",
    "have",
    "he",
    "her",
    "his",
    "i",
    "if",
    "in",
    "is",
    "it",
    "its",
    "me",
    "my",
    "not",
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
    "too",
    "us",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "will",
    "with",
    "you",
    "your",
}

URL_ARTIFACT_TOKENS = {
    "http",
    "https",
    "www",
    "com",
    "net",
    "org",
    "app",
    "profile",
    "shorts",
    "bsky",
}
LOW_INFO_UNIGRAM_BLOCKLIST = {
    "macro",
}

HASHTAG_RE = re.compile(r"(?<!\w)#([\w]+)", flags=re.UNICODE)
MULTISPACE_RE = re.compile(r"\s+")
SEPARATOR_RE = re.compile(r"[&\-/_,.;:!?(){}\[\]\"`]+")
NON_WORD_KEEP_HASH_DOLLAR_RE = re.compile(r"[^\w\s#$]", flags=re.UNICODE)
NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]")
TOKEN_RE = re.compile(r"[a-z0-9]+")
ID_LIKE_TOKEN_RE = re.compile(r"^(?=.*[a-z])(?=.*\d)[a-z0-9]{10,}$")


def normalize_candidate_phrase(text: str | None) -> dict[str, Any]:
    """Normalize one candidate phrase into stable compare-ready fields."""

    raw = text if isinstance(text, str) else ""
    nfkc = unicodedata.normalize("NFKC", raw)
    nfkc = nfkc.replace("’", "'").replace("‘", "'")
    nfkc = nfkc.replace("\r\n", "\n").replace("\r", "\n")
    nfkc = nfkc.replace("\n", " ").replace("\t", " ")

    lowered = nfkc.casefold().strip()
    lowered = MULTISPACE_RE.sub(" ", lowered)

    clean = _normalize_core(lowered)
    alnum = _alnum_key(clean)
    no_hash = _drop_one_leading_symbol(clean, "#")

    tokens = [token for token in alnum.split() if token]
    token_count = len(tokens)
    char_count = len(clean)

    return {
        "candidate_phrase_raw": raw,
        "candidate_phrase_clean": clean,
        "candidate_phrase_alnum": alnum,
        "candidate_phrase_no_hash": no_hash,
        "candidate_token_count": token_count,
        "candidate_char_count": char_count,
        "contains_digit": any(any(ch.isdigit() for ch in token) for token in tokens),
    }


def extract_topic_candidates_from_post(
    *,
    uri: str,
    post_created_at: str,
    post_text_raw: str | None,
    post_text_clean: str | None,
    post_text_alnum: str | None,
    max_candidates_per_post: int = 20,
) -> list[dict[str, Any]]:
    """Extract deterministic topic candidates from one prepared post."""

    raw_text = post_text_raw if isinstance(post_text_raw, str) else ""
    clean_text = post_text_clean if isinstance(post_text_clean, str) else ""
    alnum_text = post_text_alnum if isinstance(post_text_alnum, str) else ""
    created_at = post_created_at if isinstance(post_created_at, str) else ""

    candidates: list[dict[str, Any]] = []

    # 1) Hashtag candidates from normalized clean text.
    for match in HASHTAG_RE.finditer(clean_text):
        phrase = f"#{match.group(1)}"
        candidates.append(
            {
                "candidate_phrase_raw": phrase,
                "candidate_source_type": "hashtag",
                "candidate_start_index": int(match.start()),
                "is_hashtag_candidate": True,
                "is_unigram_fallback": False,
            }
        )

    # 2) 2/3/4-gram candidates from alnum tokens.
    tokens = [token for token in alnum_text.split() if token]
    for n in (4, 3, 2):
        if len(tokens) < n:
            continue
        for idx in range(0, len(tokens) - n + 1):
            phrase = " ".join(tokens[idx : idx + n])
            candidates.append(
                {
                    "candidate_phrase_raw": phrase,
                    "candidate_source_type": f"ngram_{n}",
                    "candidate_start_index": idx,
                    "is_hashtag_candidate": False,
                    "is_unigram_fallback": False,
                }
            )

    # 3) Conservative unigram fallback when no multiword/hash candidate survives filtering.
    prepared = _prepare_and_filter_candidates(
        uri=uri,
        post_created_at=created_at,
        post_text_raw=raw_text,
        post_text_clean=clean_text,
        post_text_alnum=alnum_text,
        candidates=candidates,
    )

    if not any(row["candidate_token_count"] >= 2 or row["is_hashtag_candidate"] for row in prepared):
        for idx, token in enumerate(tokens):
            candidates.append(
                {
                    "candidate_phrase_raw": token,
                    "candidate_source_type": "unigram_fallback",
                    "candidate_start_index": idx,
                    "is_hashtag_candidate": False,
                    "is_unigram_fallback": True,
                }
            )
        prepared = _prepare_and_filter_candidates(
            uri=uri,
            post_created_at=created_at,
            post_text_raw=raw_text,
            post_text_clean=clean_text,
            post_text_alnum=alnum_text,
            candidates=candidates,
        )

    ranked = sorted(
        prepared,
        key=lambda row: (
            row["source_priority"],
            row["candidate_start_index"],
            -row["candidate_token_count"],
            row["candidate_phrase_alnum"],
        ),
    )

    final_rows: list[dict[str, Any]] = []
    for rank, row in enumerate(ranked[:max_candidates_per_post], start=1):
        output = dict(row)
        output["candidate_rank_in_post"] = rank
        output.pop("source_priority", None)
        final_rows.append(output)

    return final_rows


def generate_topic_candidates_dataframe(
    prepared_posts_df: pd.DataFrame,
    *,
    max_candidates_per_post: int = 20,
) -> pd.DataFrame:
    """Generate candidate rows for a prepared Bluesky posts dataframe."""

    _validate_prepared_schema(prepared_posts_df)

    rows: list[dict[str, Any]] = []
    for item in prepared_posts_df.itertuples(index=False):
        row = item._asdict()
        uri = str(row.get("uri", ""))
        rows.extend(
            extract_topic_candidates_from_post(
                uri=uri,
                post_created_at=str(row.get("post_created_at", "")),
                post_text_raw=row.get("post_text_raw"),
                post_text_clean=row.get("post_text_clean"),
                post_text_alnum=row.get("post_text_alnum"),
                max_candidates_per_post=max_candidates_per_post,
            )
        )

    columns = [
        "uri",
        "post_created_at",
        "post_text_raw",
        "post_text_clean",
        "post_text_alnum",
        "candidate_phrase_raw",
        "candidate_phrase_clean",
        "candidate_phrase_alnum",
        "candidate_phrase_no_hash",
        "candidate_source_type",
        "candidate_token_count",
        "candidate_char_count",
        "candidate_rank_in_post",
        "is_hashtag_candidate",
        "contains_digit",
        "is_unigram_fallback",
        "candidate_start_index",
    ]

    if not rows:
        return pd.DataFrame(columns=columns)

    df = pd.DataFrame(rows)
    df = df.sort_values(["uri", "candidate_rank_in_post"], kind="stable").reset_index(drop=True)
    return df[columns]


def summarize_topic_candidates(
    *,
    prepared_posts_df: pd.DataFrame,
    candidates_df: pd.DataFrame,
) -> dict[str, Any]:
    """Build compact profile metrics for candidate extraction output."""

    total_posts = int(len(prepared_posts_df))

    if candidates_df.empty:
        return {
            "total_posts_processed": total_posts,
            "posts_with_candidates": 0,
            "posts_without_candidates": total_posts,
            "total_candidate_rows": 0,
            "avg_candidates_per_post_all": 0.0,
            "avg_candidates_per_post_with_candidates": 0.0,
            "candidate_source_type_counts": {},
            "candidate_token_count_distribution": {},
            "top_candidate_phrases": [],
        }

    per_post_counts = candidates_df.groupby("uri").size()
    posts_with_candidates = int(per_post_counts.shape[0])
    posts_without_candidates = total_posts - posts_with_candidates

    source_counts = {
        str(key): int(value)
        for key, value in candidates_df["candidate_source_type"].value_counts(dropna=False).items()
    }
    token_dist = {
        str(int(key)): int(value)
        for key, value in candidates_df["candidate_token_count"].value_counts(dropna=False).items()
    }

    phrase_counts = (
        candidates_df["candidate_phrase_alnum"].value_counts(dropna=False).head(20)
    )
    top_phrases = [
        {"candidate_phrase_alnum": str(key), "count": int(value)}
        for key, value in phrase_counts.items()
    ]

    return {
        "total_posts_processed": total_posts,
        "posts_with_candidates": posts_with_candidates,
        "posts_without_candidates": int(posts_without_candidates),
        "total_candidate_rows": int(len(candidates_df)),
        "avg_candidates_per_post_all": float(len(candidates_df) / total_posts) if total_posts else 0.0,
        "avg_candidates_per_post_with_candidates": float(per_post_counts.mean()),
        "candidate_source_type_counts": source_counts,
        "candidate_token_count_distribution": token_dist,
        "top_candidate_phrases": top_phrases,
    }


def _validate_prepared_schema(df: pd.DataFrame) -> None:
    missing = [column for column in REQUIRED_PREPARED_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(
            f"Prepared dataframe missing required columns: {missing!r}. "
            f"Available: {list(df.columns)!r}"
        )


def _prepare_and_filter_candidates(
    *,
    uri: str,
    post_created_at: str,
    post_text_raw: str,
    post_text_clean: str,
    post_text_alnum: str,
    candidates: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []

    for candidate in candidates:
        source_type = str(candidate.get("candidate_source_type", ""))
        source_priority = SOURCE_PRIORITY.get(source_type, 99)

        normalized = normalize_candidate_phrase(candidate.get("candidate_phrase_raw"))

        row = {
            "uri": uri,
            "post_created_at": post_created_at,
            "post_text_raw": post_text_raw,
            "post_text_clean": post_text_clean,
            "post_text_alnum": post_text_alnum,
            **normalized,
            "candidate_source_type": source_type,
            "candidate_start_index": int(candidate.get("candidate_start_index", 0)),
            "is_hashtag_candidate": bool(candidate.get("is_hashtag_candidate", False)),
            "is_unigram_fallback": bool(candidate.get("is_unigram_fallback", False)),
            "source_priority": source_priority,
        }

        if _should_keep_candidate(row):
            prepared.append(row)

    # Collapse duplicates within post by normalized alnum key.
    by_phrase: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in prepared:
        by_phrase[row["candidate_phrase_alnum"]].append(row)

    collapsed: list[dict[str, Any]] = []
    for same_rows in by_phrase.values():
        best = sorted(
            same_rows,
            key=lambda row: (
                row["source_priority"],
                row["candidate_start_index"],
                -row["candidate_token_count"],
                row["candidate_phrase_alnum"],
            ),
        )[0]
        collapsed.append(best)

    return collapsed


def _should_keep_candidate(row: dict[str, Any]) -> bool:
    token_count = int(row["candidate_token_count"])
    char_count = int(row["candidate_char_count"])
    phrase_alnum = str(row["candidate_phrase_alnum"])
    source_type = str(row["candidate_source_type"])

    if not phrase_alnum.strip():
        return False
    if token_count < 1 or token_count > 4:
        return False
    if char_count < 3 or char_count > 64:
        return False

    tokens = [token for token in phrase_alnum.split() if token]
    if not tokens:
        return False

    if all(token in STOPWORDS for token in tokens):
        return False

    if source_type.startswith("ngram_") and len(tokens) >= 2:
        # N-grams that begin/end with stopwords are commonly sentence fragments.
        if tokens[0] in STOPWORDS or tokens[-1] in STOPWORDS:
            return False

    artifact_hits = sum(1 for token in tokens if token in URL_ARTIFACT_TOKENS)
    if artifact_hits >= 2 or (artifact_hits and artifact_hits / len(tokens) >= 0.5):
        return False

    if any(ID_LIKE_TOKEN_RE.match(token) for token in tokens) and source_type != "hashtag":
        return False

    if token_count == 1:
        token = tokens[0]
        if len(token) < 3:
            return False
        if token in URL_ARTIFACT_TOKENS:
            return False
        if token in LOW_INFO_UNIGRAM_BLOCKLIST:
            return False

    return True


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
