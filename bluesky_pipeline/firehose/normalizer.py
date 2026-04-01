"""Raw capture normalization scaffolding.

Intended responsibility:
- map extracted post data to stable raw output rows
- promote convenience fields used by downstream hydration/state logic
"""

from __future__ import annotations

from typing import Any, Mapping

from bluesky_pipeline.firehose.extractor import ExtractedPostEvent


def normalize_raw_post(
    extracted: ExtractedPostEvent,
    capture_run_id: str,
    captured_at: str,
) -> Mapping[str, Any]:
    """Convert extracted post event into Dataset A raw row shape."""

    return {
        "capture_run_id": capture_run_id,
        "seq": extracted.seq,
        "repo_did": extracted.repo_did,
        "event_time": None,
        "operation": "create",
        "collection": extracted.collection,
        "rkey": extracted.rkey,
        "uri": extracted.uri,
        "cid": extracted.cid,
        "record_created_at": extracted.record.get("createdAt"),
        "has_reply": bool(extracted.record.get("reply")),
        "has_embed": bool(extracted.record.get("embed")),
        "captured_at": captured_at,
        "record": dict(extracted.record),
    }
