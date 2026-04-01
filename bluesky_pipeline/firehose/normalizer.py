"""Raw capture normalization.

Normalizes extracted firehose post-create events into the stable raw row schema
used by local `.jsonl.gz` output files.
"""

from __future__ import annotations

import base64
from typing import Any, Mapping

from bluesky_pipeline.firehose.extractor import ExtractedPostEvent
from bluesky_pipeline.utils.time_utils import utc_now_iso


def normalize_raw_post(
    extracted: ExtractedPostEvent,
    capture_run_id: str,
    captured_at: str | None = None,
) -> Mapping[str, Any]:
    """Convert extracted post-create event into Dataset A row shape."""

    captured_ts = captured_at or utc_now_iso()

    return {
        "capture_run_id": capture_run_id,
        "seq": extracted.seq,
        "repo_did": extracted.repo_did,
        "event_time": extracted.event_time,
        "operation": extracted.operation,
        "collection": extracted.collection,
        "rkey": extracted.rkey,
        "uri": extracted.uri,
        "cid": extracted.cid,
        "record_created_at": extracted.record.get("createdAt"),
        "has_reply": extracted.record.get("reply") is not None,
        "has_embed": extracted.record.get("embed") is not None,
        "captured_at": captured_ts,
        "record": _to_json_safe(extracted.record),
    }


def _to_json_safe(value: Any) -> Any:
    """Recursively coerce values into JSON-serializable primitives."""

    if isinstance(value, Mapping):
        return {str(k): _to_json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_to_json_safe(item) for item in value]
    if isinstance(value, bytes):
        encoded = base64.b64encode(value).decode("ascii")
        return {"$bytes_b64": encoded}
    return value
