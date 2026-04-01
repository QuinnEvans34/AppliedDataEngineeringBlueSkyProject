# Phase 6 One Real Firehose Post

Date: 2026-04-01

- Source artifact path: `data/phase6_diagnostic_20260401/artifacts/raw_firehose_sample.jsonl`
- Capture run id: `cap_20260401T184939Z_85c99020`
- Exact URI: `at://did:plc:l5ykcgaeg5noxtdbqiu77boo/app.bsky.feed.post/3mihe7wquq22i`
- Exact CID: `bafyreiciycbxjyhzy3e64ufiwdp2difwskn2nzpwpw5hyalu4bymvw47mm`
- `has_reply`: `false`
- `has_embed`: `false`

This row came directly from the Phase 6 firehose capture artifacts, not from hydrated output.

## Raw Firehose Row
```json
{"capture_run_id": "cap_20260401T184939Z_85c99020", "seq": 28756093036, "repo_did": "did:plc:l5ykcgaeg5noxtdbqiu77boo", "event_time": "2026-04-01T18:49:39.658Z", "operation": "create", "collection": "app.bsky.feed.post", "rkey": "3mihe7wquq22i", "uri": "at://did:plc:l5ykcgaeg5noxtdbqiu77boo/app.bsky.feed.post/3mihe7wquq22i", "cid": "bafyreiciycbxjyhzy3e64ufiwdp2difwskn2nzpwpw5hyalu4bymvw47mm", "record_created_at": "2026-04-01T18:49:39.129Z", "has_reply": false, "has_embed": false, "captured_at": "2026-04-01T18:49:40.662473+00:00", "record": {"text": "Voiko moderni talous käytännössä kasvaa ilman että velan määrä myös kasvaa? Ainut keino ehkä jokin tuottavuusräjähdys, kuten äärimmäisen kannattava fuusiovoima tai vastaava?", "$type": "app.bsky.feed.post", "langs": ["fi"], "createdAt": "2026-04-01T18:49:39.129Z"}}
```

## Field Breakdown
- `capture_run_id`: Identifier for the specific firehose capture run that produced this row.
- `seq`: Firehose sequence number for event ordering.
- `repo_did`: DID of the repo/account that emitted the record.
- `rkey`: Record key for the post inside the collection.
- `uri`: Full AT URI for this post record.
- `cid`: Content identifier observed at capture time.
- `event_time`: Event timestamp from the firehose event context.
- `record_created_at`: Post creation timestamp from the record payload.
- `captured_at`: Timestamp when this pipeline wrote/captured the row.
- `operation`: Repo operation type (`create` here).
- `collection`: ATProto collection (`app.bsky.feed.post` here).
- `has_reply`: Boolean indicating whether reply linkage exists in `record`.
- `has_embed`: Boolean indicating whether embed content exists in `record`.
- `record`: Raw decoded post payload as captured from the firehose event.

## Verification Notes
- This row was sourced from firehose capture artifact `data/phase6_diagnostic_20260401/artifacts/raw_firehose_sample.jsonl`, not from hydrate output.
- The JSON appears correctly decoded and structurally valid.
- No bytes-safe wrapper objects like `{"$bytes_b64": "..."}` appear in this specific row.
- The row shape matches the Phase 6 contract expectations for normalized raw firehose rows (`capture_run_id`, identity fields, timing fields, flags, and nested `record`).
