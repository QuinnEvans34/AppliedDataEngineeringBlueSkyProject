"""Deterministic local Bluesky post-text normalization helpers."""

from __future__ import annotations

import gzip
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from src.source_paths import resolve_bluesky_source_root

SOURCE_FAMILIES = {
    "raw_posts": "raw",
    "hydrated_posts": "hydrated",
}
HASHTAG_RE = re.compile(r"(?<!\w)#\w+")
URL_RE = re.compile(
    r"((https?://\S+)|(www\.\S+)|(\b(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/\S*)?\b))",
    re.IGNORECASE,
)
MENTION_RE = re.compile(r"(?<!\w)@\w+")
NON_ASCII_RE = re.compile(r"[^\x00-\x7F]")
SPECIAL_RE = re.compile(r"[^A-Za-z0-9\s]")
MULTISPACE_RE = re.compile(r"\s+")
SEPARATOR_RE = re.compile(r"[&\-/_,.;:!?(){}\[\]\"`]+")
ALNUM_RE = re.compile(r"[^a-z0-9\s]")


def discover_local_source_candidates(base_dir: Path | str | None = None) -> list[dict[str, Any]]:
    """Discover local run-root candidates that contain raw/hydrated post files."""

    root = resolve_bluesky_source_root(base_dir)
    if not root.exists():
        raise FileNotFoundError(f"Base directory does not exist: {root}")

    candidate_map: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("*.jsonl.gz")):
        family, run_root = _extract_family_and_run_root(path)
        if not family or run_root is None:
            continue

        run_root_key = run_root.as_posix()
        candidate = candidate_map.setdefault(
            run_root_key,
            {
                "run_root": run_root,
                "raw_paths": [],
                "hydrated_paths": [],
            },
        )
        candidate[f"{family}_paths"].append(path)

    candidates: list[dict[str, Any]] = []
    for key in sorted(candidate_map):
        candidate = candidate_map[key]
        candidate["raw_paths"] = sorted(candidate["raw_paths"])
        candidate["hydrated_paths"] = sorted(candidate["hydrated_paths"])
        if candidate["raw_paths"] or candidate["hydrated_paths"]:
            candidates.append(candidate)
    return candidates


def evaluate_source_candidate(
    *,
    run_root: Path | str,
    raw_paths: Iterable[Path | str],
    hydrated_paths: Iterable[Path | str],
) -> dict[str, Any]:
    """Profile one source candidate for deterministic source selection."""

    run_root_path = Path(run_root)
    raw_paths_list = [Path(path) for path in raw_paths]
    hydrated_paths_list = [Path(path) for path in hydrated_paths]
    raw_rows = _load_many_jsonl_gz(raw_paths_list)
    hydrated_rows = _load_many_jsonl_gz(hydrated_paths_list)

    raw_texts = [extract_post_text(row) for row in raw_rows]
    hydrated_texts = [extract_post_text(row) for row in hydrated_rows]

    raw_non_empty_text_count = sum(1 for text in raw_texts if text.strip())
    hydrated_non_empty_text_count = sum(1 for text in hydrated_texts if text.strip())
    raw_uri_count = len({_uri_from_row(row) for row in raw_rows if _uri_from_row(row)})
    hydrated_uri_count = len(
        {_uri_from_row(row) for row in hydrated_rows if _uri_from_row(row)}
    )
    unique_uri_count = len(
        {
            _uri_from_row(row)
            for row in [*raw_rows, *hydrated_rows]
            if _uri_from_row(row)
        }
    )

    source_run_tag = run_root_path.name if run_root_path.name else run_root_path.as_posix()
    prepared_df = prepare_bluesky_posts(
        raw_rows=raw_rows,
        hydrated_rows=hydrated_rows,
        source_run_tag=source_run_tag,
    )
    prepared_non_empty_text_count = int(
        prepared_df["post_text_clean"].fillna("").str.strip().ne("").sum()
    )
    text_source_counts = {
        str(key): int(value)
        for key, value in prepared_df["text_source"].value_counts(dropna=False).items()
    }

    record_text_present_count = sum(
        1 for row in [*raw_rows, *hydrated_rows] if isinstance(_get(row, "record.text"), str)
    )
    top_level_text_present_count = sum(
        1 for row in [*raw_rows, *hydrated_rows] if isinstance(row.get("text"), str)
    )

    return {
        "run_root": run_root_path.as_posix(),
        "run_root_name": run_root_path.name,
        "raw_path_count": len(raw_paths_list),
        "hydrated_path_count": len(hydrated_paths_list),
        "raw_row_count": len(raw_rows),
        "hydrated_row_count": len(hydrated_rows),
        "raw_non_empty_text_count": raw_non_empty_text_count,
        "hydrated_non_empty_text_count": hydrated_non_empty_text_count,
        "raw_uri_count": raw_uri_count,
        "hydrated_uri_count": hydrated_uri_count,
        "unique_uri_count": unique_uri_count,
        "prepared_row_count": int(len(prepared_df)),
        "prepared_non_empty_text_count": prepared_non_empty_text_count,
        "text_source_counts": text_source_counts,
        "record_text_present_count": record_text_present_count,
        "top_level_text_present_count": top_level_text_present_count,
    }


def select_best_local_source_candidate(
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """
    Select the best local source candidate by deterministic ranking.

    Ranking:
    1) highest prepared non-empty text count
    2) highest unique URI count
    3) highest prepared row count
    4) lexical run-root path tie-break
    """

    resolved_base_dir = resolve_bluesky_source_root(base_dir)
    candidates = discover_local_source_candidates(base_dir=resolved_base_dir)
    if not candidates:
        raise ValueError(f"No local source candidates found under: {resolved_base_dir}")

    evaluations: list[dict[str, Any]] = []
    for candidate in candidates:
        metrics = evaluate_source_candidate(
            run_root=candidate["run_root"],
            raw_paths=candidate["raw_paths"],
            hydrated_paths=candidate["hydrated_paths"],
        )
        evaluations.append(
            {
                **metrics,
                "raw_paths": [Path(p).as_posix() for p in candidate["raw_paths"]],
                "hydrated_paths": [Path(p).as_posix() for p in candidate["hydrated_paths"]],
            }
        )

    ranked = sorted(
        evaluations,
        key=lambda item: (
            -item["prepared_non_empty_text_count"],
            -item["unique_uri_count"],
            -item["prepared_row_count"],
            item["run_root"],
        ),
    )
    best = ranked[0]
    if best["prepared_non_empty_text_count"] <= 0:
        raise ValueError(
            "No source candidate has non-empty prepared text coverage. "
            "Cannot continue with local text preparation."
        )

    return {
        "selected": best,
        "candidates_ranked": ranked,
        "resolved_base_dir": resolved_base_dir.as_posix(),
        "selection_rule": (
            "prepared_non_empty_text_count desc, unique_uri_count desc, "
            "prepared_row_count desc, run_root asc"
        ),
        "selected_text_field_preference": "record.text (fallback: text)",
    }


def load_jsonl_gz(path: Path | str) -> list[dict[str, Any]]:
    """Load one gzip JSONL file into a list of dictionaries."""

    target = Path(path)
    rows: list[dict[str, Any]] = []
    with gzip.open(target, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            rows.append(json.loads(line))
    return rows


def extract_post_text(row: dict[str, Any]) -> str:
    """Extract text from a known Bluesky row shape, falling back safely."""

    record = row.get("record")
    if isinstance(record, dict):
        text = record.get("text")
        if isinstance(text, str):
            return text

    text = row.get("text")
    if isinstance(text, str):
        return text

    return ""


def normalize_post_text(text: str | None) -> dict[str, object]:
    """Normalize one post text value and emit deterministic helper fields."""

    raw = text if isinstance(text, str) else ""
    normalized = unicodedata.normalize("NFKC", raw)
    normalized = normalized.replace("’", "'").replace("‘", "'")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\n", " ").replace("\t", " ")

    has_hashtag = bool(HASHTAG_RE.search(normalized))
    has_url = bool(URL_RE.search(normalized))
    has_mention = bool(MENTION_RE.search(normalized))
    has_non_ascii = bool(NON_ASCII_RE.search(normalized))
    has_special_chars = bool(SPECIAL_RE.search(normalized))

    lowered = normalized.lower()
    separated = SEPARATOR_RE.sub(" ", lowered)
    clean = MULTISPACE_RE.sub(" ", separated).strip()

    alnum = ALNUM_RE.sub(" ", clean)
    alnum = MULTISPACE_RE.sub(" ", alnum).strip()

    token_count = len(clean.split()) if clean else 0
    char_count = len(clean)

    return {
        "post_text_raw": raw,
        "post_text_clean": clean,
        "post_text_alnum": alnum,
        "post_token_count": token_count,
        "post_char_count": char_count,
        "has_hashtag": has_hashtag,
        "has_url": has_url,
        "has_mention": has_mention,
        "has_special_chars": has_special_chars,
        "has_non_ascii": has_non_ascii,
    }


def prepare_bluesky_posts(
    raw_rows: Iterable[dict[str, Any]],
    hydrated_rows: Iterable[dict[str, Any]],
    source_run_tag: str,
) -> pd.DataFrame:
    """Build one prepared record per URI, preferring hydrated rows when both exist."""

    raw_by_uri: dict[str, dict[str, Any]] = {}
    hydrated_by_uri: dict[str, dict[str, Any]] = {}

    for row in raw_rows:
        uri = _uri_from_row(row)
        if uri and uri not in raw_by_uri:
            raw_by_uri[uri] = row

    for row in hydrated_rows:
        uri = _uri_from_row(row)
        if uri and uri not in hydrated_by_uri:
            hydrated_by_uri[uri] = row

    records: list[dict[str, Any]] = []
    for uri in sorted(set(raw_by_uri) | set(hydrated_by_uri)):
        raw_row = raw_by_uri.get(uri)
        hydrated_row = hydrated_by_uri.get(uri)

        hydrated_text = extract_post_text(hydrated_row) if hydrated_row else ""
        raw_text = extract_post_text(raw_row) if raw_row else ""
        selected_text = hydrated_text if hydrated_text else raw_text

        normalized = normalize_post_text(selected_text)

        record: dict[str, Any] = {
            "uri": uri,
            "post_created_at": _select_post_created_at(
                raw_row=raw_row,
                hydrated_row=hydrated_row,
            ),
            "source_run_tag": source_run_tag,
            "text_source": (
                "hydrated_record_text"
                if hydrated_text
                else ("raw_record_text" if raw_text else "none")
            ),
            "raw_capture_run_id": _get(raw_row, "capture_run_id"),
            "raw_captured_at": _get(raw_row, "captured_at"),
            "raw_repo_did": _get(raw_row, "repo_did"),
            "raw_record_created_at": _get(raw_row, "record_created_at"),
            "hydrated_capture_run_id": _get(hydrated_row, "capture_run_id"),
            "hydrated_hydrate_run_id": _get(hydrated_row, "hydrate_run_id"),
            "hydrated_author_did": _get(hydrated_row, "author_did"),
            "hydrated_author_handle": _get(hydrated_row, "author_handle"),
            "hydrated_indexed_at": _get(hydrated_row, "indexed_at"),
            "hydrated_hydrated_at": _get(hydrated_row, "hydrated_at"),
            "raw_source_row_json": json.dumps(
                raw_row, ensure_ascii=False, sort_keys=True
            )
            if raw_row
            else "",
            "hydrated_source_row_json": json.dumps(
                hydrated_row, ensure_ascii=False, sort_keys=True
            )
            if hydrated_row
            else "",
        }
        record.update(normalized)
        records.append(record)

    return pd.DataFrame(records)


def summarize_prepared_posts(df: pd.DataFrame) -> dict[str, Any]:
    """Create compact profiling summary for prepared post data."""

    if df.empty:
        return {
            "row_count": 0,
            "non_empty_raw_text_count": 0,
            "non_empty_clean_text_count": 0,
            "blank_clean_text_count": 0,
            "duplicate_raw_text_rows_non_empty": 0,
            "duplicate_clean_text_rows_non_empty": 0,
            "text_source_counts": {},
            "flag_counts": {},
        }

    raw = df["post_text_raw"].fillna("").astype(str)
    clean = df["post_text_clean"].fillna("").astype(str)
    raw_non_empty_mask = raw.str.strip().ne("")
    clean_non_empty_mask = clean.str.strip().ne("")

    duplicate_raw = int(df.loc[raw_non_empty_mask].duplicated(subset=["post_text_raw"]).sum())
    duplicate_clean = int(
        df.loc[clean_non_empty_mask].duplicated(subset=["post_text_clean"]).sum()
    )
    text_source_counts = {
        str(key): int(value)
        for key, value in df["text_source"].value_counts(dropna=False).items()
    }

    flag_columns = [
        "has_hashtag",
        "has_url",
        "has_mention",
        "has_special_chars",
        "has_non_ascii",
    ]
    flag_counts: dict[str, int] = {}
    for column in flag_columns:
        if column in df.columns:
            flag_counts[column] = int(df[column].fillna(False).astype(bool).sum())

    return {
        "row_count": int(len(df)),
        "non_empty_raw_text_count": int(raw_non_empty_mask.sum()),
        "non_empty_clean_text_count": int(clean_non_empty_mask.sum()),
        "blank_clean_text_count": int((~clean_non_empty_mask).sum()),
        "duplicate_raw_text_rows_non_empty": duplicate_raw,
        "duplicate_clean_text_rows_non_empty": duplicate_clean,
        "text_source_counts": text_source_counts,
        "flag_counts": flag_counts,
    }


def prepare_bluesky_posts_from_files(
    *,
    raw_paths: Iterable[Path | str],
    hydrated_paths: Iterable[Path | str],
    source_run_tag: str,
) -> pd.DataFrame:
    """Load source files and build prepared DataFrame."""

    raw_rows: list[dict[str, Any]] = []
    hydrated_rows: list[dict[str, Any]] = []

    for path in raw_paths:
        raw_rows.extend(load_jsonl_gz(path))
    for path in hydrated_paths:
        hydrated_rows.extend(load_jsonl_gz(path))

    return prepare_bluesky_posts(
        raw_rows=raw_rows,
        hydrated_rows=hydrated_rows,
        source_run_tag=source_run_tag,
    )


def prepare_from_best_local_source(
    *,
    base_dir: Path | str | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Select best local source candidate and return prepared dataframe + selection context."""

    selection = select_best_local_source_candidate(base_dir=base_dir)
    chosen = selection["selected"]

    prepared = prepare_bluesky_posts_from_files(
        raw_paths=chosen["raw_paths"],
        hydrated_paths=chosen["hydrated_paths"],
        source_run_tag=chosen["run_root_name"] or chosen["run_root"],
    )
    prepared = prepared.sort_values(["uri"], kind="stable").reset_index(drop=True)

    return prepared, selection


def _load_many_jsonl_gz(paths: Iterable[Path | str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        rows.extend(load_jsonl_gz(path))
    return rows


def _uri_from_row(row: dict[str, Any]) -> str:
    value = row.get("uri")
    return str(value) if isinstance(value, str) and value else ""


def _select_post_created_at(
    *,
    raw_row: dict[str, Any] | None,
    hydrated_row: dict[str, Any] | None,
) -> str:
    for value in (
        _get(raw_row, "record_created_at"),
        _get(hydrated_row, "record.createdAt"),
        _get(hydrated_row, "indexed_at"),
        _get(hydrated_row, "hydrated_at"),
        _get(raw_row, "captured_at"),
    ):
        if isinstance(value, str) and value:
            return value
    return ""


def _get(row: dict[str, Any] | None, path: str) -> Any:
    if not isinstance(row, dict):
        return None
    current: Any = row
    for key in path.split("."):
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return None
    return current


def _extract_family_and_run_root(path: Path) -> tuple[str | None, Path | None]:
    parts = path.parts
    for folder, family in SOURCE_FAMILIES.items():
        if folder in parts:
            idx = parts.index(folder)
            if idx <= 0:
                return None, None
            return family, Path(*parts[:idx])
    return None, None
