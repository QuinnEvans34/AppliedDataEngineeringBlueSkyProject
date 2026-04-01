"""Firehose commit extraction logic.

Extractor responsibilities:
- inspect commit operations
- keep only `app.bsky.feed.post` create operations
- resolve post records from commit CAR blocks (live) or inline fields (mock)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from bluesky_pipeline.firehose.decoder import DecodedEvent


class FirehoseExtractError(ValueError):
    """Raised when commit payload is malformed beyond safe extraction."""


@dataclass(slots=True)
class ExtractedPostEvent:
    """Normalized post-create event extracted from a commit."""

    seq: int | None
    repo_did: str
    event_time: str | None
    operation: str
    collection: str
    rkey: str
    uri: str
    cid: str | None
    record: Mapping[str, Any]


@dataclass(slots=True)
class ExtractionResult:
    """Extraction output including post rows and operation scan count."""

    posts: list[ExtractedPostEvent]
    commit_ops_scanned: int


def extract_post_creates(event: DecodedEvent) -> ExtractionResult:
    """Extract post-create records from one decoded commit event."""

    if event.event_type != "commit":
        return ExtractionResult(posts=[], commit_ops_scanned=0)

    payload = event.payload

    if isinstance(payload, Mapping):
        return _extract_from_mapping_commit(event, payload)

    return _extract_from_model_commit(event, payload)


def _extract_from_mapping_commit(event: DecodedEvent, payload: Mapping[str, Any]) -> ExtractionResult:
    """Extract post-create records from mapping payload (mock/testing path)."""

    repo_did = str(payload.get("repo") or payload.get("repo_did") or "")
    if not repo_did:
        raise FirehoseExtractError("Commit payload missing repo DID")

    seq = event.seq if event.seq is not None else _coerce_int(payload.get("seq"))
    event_time = event.event_time or _coerce_str(payload.get("time"))

    ops = payload.get("ops")
    if not isinstance(ops, list):
        raise FirehoseExtractError("Commit payload missing ops list")

    records_by_cid = _build_records_by_cid_from_mapping(payload)

    extracted: list[ExtractedPostEvent] = []
    commit_ops_scanned = 0

    for op in ops:
        if not isinstance(op, Mapping):
            continue

        commit_ops_scanned += 1

        action = str(op.get("action") or op.get("op") or "")
        if action != "create":
            continue

        collection, rkey = _split_collection_and_rkey(op.get("path"))
        if collection != "app.bsky.feed.post":
            continue

        cid = _coerce_str(op.get("cid"))

        record = op.get("record")
        if not isinstance(record, Mapping):
            record = op.get("value")
        if not isinstance(record, Mapping) and cid is not None:
            record = records_by_cid.get(cid)

        if not isinstance(record, Mapping):
            continue

        uri = f"at://{repo_did}/{collection}/{rkey}"
        extracted.append(
            ExtractedPostEvent(
                seq=seq,
                repo_did=repo_did,
                event_time=event_time,
                operation="create",
                collection=collection,
                rkey=rkey,
                uri=uri,
                cid=cid,
                record=record,
            )
        )

    return ExtractionResult(posts=extracted, commit_ops_scanned=commit_ops_scanned)


def _extract_from_model_commit(event: DecodedEvent, payload: Any) -> ExtractionResult:
    """Extract post-create records from parsed subscribeRepos model payload."""

    repo_did = _coerce_str(getattr(payload, "repo", None))
    if not repo_did:
        raise FirehoseExtractError("Parsed commit model missing repo DID")

    seq = event.seq if event.seq is not None else _coerce_int(getattr(payload, "seq", None))
    event_time = event.event_time or _coerce_str(getattr(payload, "time", None))

    ops = getattr(payload, "ops", None)
    if not isinstance(ops, list):
        raise FirehoseExtractError("Parsed commit model missing ops list")

    records_by_cid = _build_records_by_cid_from_car(getattr(payload, "blocks", None))

    extracted: list[ExtractedPostEvent] = []
    commit_ops_scanned = 0

    for op in ops:
        commit_ops_scanned += 1

        action = _coerce_str(getattr(op, "action", None))
        if action != "create":
            continue

        collection, rkey = _split_collection_and_rkey(getattr(op, "path", None))
        if collection != "app.bsky.feed.post":
            continue

        raw_cid = getattr(op, "cid", None)
        cid = _coerce_str(raw_cid)

        record = None
        if raw_cid is not None:
            record = records_by_cid.get(raw_cid)
        if not isinstance(record, Mapping) and cid is not None:
            record = records_by_cid.get(cid)

        if not isinstance(record, Mapping):
            continue

        uri = f"at://{repo_did}/{collection}/{rkey}"
        extracted.append(
            ExtractedPostEvent(
                seq=seq,
                repo_did=repo_did,
                event_time=event_time,
                operation="create",
                collection=collection,
                rkey=rkey,
                uri=uri,
                cid=cid,
                record=record,
            )
        )

    return ExtractionResult(posts=extracted, commit_ops_scanned=commit_ops_scanned)


def _build_records_by_cid_from_car(blocks: Any) -> dict[Any, Mapping[str, Any]]:
    """Decode commit CAR blocks into a CID->record mapping."""

    if blocks is None:
        return {}

    if isinstance(blocks, Mapping):
        return {
            key: value
            for key, value in blocks.items()
            if isinstance(value, Mapping)
        }

    if not isinstance(blocks, (bytes, bytearray)):
        return {}

    try:
        from atproto_core.car import CAR
    except ModuleNotFoundError:
        return {}

    try:
        car = CAR.from_bytes(bytes(blocks))
    except Exception:
        return {}

    parsed: dict[Any, Mapping[str, Any]] = {}
    for cid_obj, record in car.blocks.items():
        if isinstance(record, Mapping):
            parsed[cid_obj] = record
            parsed[str(cid_obj)] = record

    return parsed


def _build_records_by_cid_from_mapping(payload: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    """Build CID->record mapping from mocked payload structures."""

    records: dict[str, Mapping[str, Any]] = {}

    direct = payload.get("records_by_cid")
    if isinstance(direct, Mapping):
        for cid, record in direct.items():
            if isinstance(cid, str) and isinstance(record, Mapping):
                records[cid] = record

    blocks = payload.get("blocks")
    if isinstance(blocks, Mapping):
        for cid, record in blocks.items():
            if isinstance(cid, str) and isinstance(record, Mapping):
                records[cid] = record

    return records


def _split_collection_and_rkey(path_value: Any) -> tuple[str, str]:
    """Split operation path into collection and rkey components."""

    if not isinstance(path_value, str):
        return "", ""

    path = path_value.strip("/")
    if "/" not in path:
        return "", ""

    collection, rkey = path.rsplit("/", 1)
    return collection, rkey


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)
