# Phase 6 Live Diagnostic and Contract Validation

Date: 2026-04-01

## Objective
Run a bounded real-data diagnostic to validate end-to-end live behavior and data contracts for:
1. real firehose ingest (small one-shot sample)
2. immediate public API hydrate lookup on captured URI(s)
3. one true maturity-path hydrate worker execution for at least one eligible URI in bounded one-shot mode

This phase is diagnostic validation only (not feature work, not scale/perf testing, not production operation).

## Preconditions / readiness check
- Re-read completed for:
  - `bluesky_pipeline/main_firehose.py`
  - `bluesky_pipeline/firehose/client.py`
  - `bluesky_pipeline/firehose/decoder.py`
  - `bluesky_pipeline/firehose/extractor.py`
  - `bluesky_pipeline/firehose/normalizer.py`
  - `bluesky_pipeline/state/sqlite_store.py`
  - `bluesky_pipeline/hydrate/client.py`
  - `bluesky_pipeline/hydrate/selector.py`
  - `bluesky_pipeline/hydrate/normalizer.py`
  - `bluesky_pipeline/main_hydrate.py`
- Dependency precheck:
  - `websockets` import OK
  - `atproto_firehose` import OK
  - `atproto_core` import OK
- Safety check for bounded run:
  - one-shot mode only
  - single worker only
  - isolated DB/output/log directories only
  - intentionally small capture target

## Phase 5 constraints relevant to this run
- One-shot retryable-cycle guard remains active and relevant.
- Claim counters are treated as claim-volume, not unique-post totals.
- No DB-level deferred retry schedule (`next_attempt_at`) exists yet.
- Logging handler duplicate-attach hardening remains relevant for repeat invocations.

## Environment and configuration used
Runtime:
- Working dir: `/Users/quintonevans/Desktop/Neumont/AppliedMachineLearning/ProjectOne/AppliedDataEngineeringBlueSkyProject`
- Host timezone: `America/Denver`
- Date: `2026-04-01`

Isolated phase paths:
- Base: `data/phase6_diagnostic_20260401`
- DB path: `data/phase6_diagnostic_20260401/state/phase6_live.db`
- Raw output dir: `data/phase6_diagnostic_20260401/raw_posts`
- Hydrated output dir: `data/phase6_diagnostic_20260401/hydrated_posts`
- Miss output dir: `data/phase6_diagnostic_20260401/hydration_misses`
- Logs:
  - `data/phase6_diagnostic_20260401/logs/firehose_phase6.log`
  - `data/phase6_diagnostic_20260401/logs/hydrate_phase6.log`
- Diagnostic artifacts:
  - `data/phase6_diagnostic_20260401/artifacts`

One-shot confirmation:
- Firehose executed with explicit bounded target (`--target-count 25`) and exits.
- Hydrator executed without `--continue-polling`.
- No parallel worker fanout was used.

Key config/run values used:
- Firehose:
  - `target_count=25`
  - `recv_timeout_seconds=30`
  - `progress_log_interval_seconds=5`
  - `progress_db_sync_interval_seconds=2`
  - `max_rows_per_file=100`
  - `max_seconds_per_file=120`
- Hydrate:
  - `claim_batch_size=5`
  - `request_batch_size=5`
  - `maturity_hours=0` (bounded diagnostic choice for immediate eligibility)
  - `max_rows_per_file=100`
  - `max_seconds_per_file=120`

Exact commands run:
1. Test suite rerun
```bash
python3 -m unittest discover -s tests -v
```
2. Bounded live firehose capture
```bash
python3 -m bluesky_pipeline.main_firehose \
  --db-path data/phase6_diagnostic_20260401/state/phase6_live.db \
  --log-path data/phase6_diagnostic_20260401/logs/firehose_phase6.log \
  --raw-output-dir data/phase6_diagnostic_20260401/raw_posts \
  --target-count 25 \
  --recv-timeout-seconds 30 \
  --progress-log-interval-seconds 5 \
  --progress-db-sync-interval-seconds 2 \
  --max-rows-per-file 100 \
  --max-seconds-per-file 120
```
3. Immediate public API lookup (fresh captured URI) and normalized sample artifact write
```bash
python3 - <<'PY'
import json, urllib.parse, urllib.request, ssl, certifi
from datetime import datetime, timezone
from bluesky_pipeline.hydrate.normalizer import normalize_hydrated_post

uri = 'at://did:plc:l5ykcgaeg5noxtdbqiu77boo/app.bsky.feed.post/3mihe7wquq22i'
endpoint = 'https://public.api.bsky.app/xrpc/app.bsky.feed.getPosts'
url = endpoint + '?' + urllib.parse.urlencode([('uris', uri)])
ctx = ssl.create_default_context(cafile=certifi.where())
req = urllib.request.Request(url, headers={'User-Agent':'bluesky-pipeline-phase6-diagnostic/1.0'})
with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
    payload = json.loads(r.read().decode('utf-8'))

with open('data/phase6_diagnostic_20260401/artifacts/immediate_lookup_raw_response.json','w',encoding='utf-8') as f:
    json.dump(payload,f,ensure_ascii=False,indent=2)

post = payload['posts'][0]
norm = normalize_hydrated_post('phase6_immediate_lookup','cap_20260401T184939Z_85c99020',post,datetime.now(timezone.utc).isoformat())
with open('data/phase6_diagnostic_20260401/artifacts/immediate_lookup_normalized_sample.json','w',encoding='utf-8') as f:
    json.dump(norm,f,ensure_ascii=False,indent=2)
PY
```
4. One-shot live hydrate run
```bash
python3 -m bluesky_pipeline.main_hydrate \
  --db-path data/phase6_diagnostic_20260401/state/phase6_live.db \
  --log-path data/phase6_diagnostic_20260401/logs/hydrate_phase6.log \
  --capture-run-id cap_20260401T184939Z_85c99020 \
  --hydrated-output-dir data/phase6_diagnostic_20260401/hydrated_posts \
  --miss-output-dir data/phase6_diagnostic_20260401/hydration_misses \
  --claim-batch-size 5 \
  --request-batch-size 5 \
  --maturity-hours 0 \
  --max-rows-per-file 100 \
  --max-seconds-per-file 120
```

## Test suite rerun result
Command:
```bash
python3 -m unittest discover -s tests -v
```
Result:
- 17 tests run
- all passed
- no failures
- one `ResourceWarning` from test harness temp HTTP object cleanup (non-failing)

## Firehose diagnostic capture summary
Live firehose run result:
- `capture_run_id`: `cap_20260401T184939Z_85c99020`
- status: `completed`
- target count: `25`
- written post count: `25`
- unique sampled URIs (from output file): `25`
- run window:
  - started: `2026-04-01T18:49:39.570362+00:00`
  - completed: `2026-04-01T18:49:40.846690+00:00`

Firehose log confirmation:
- job started
- firehose URL configured
- target reached and run exited cleanly
- progress line observed with `decoded=230`, `matches=25`, `decode_errors=0`, `extract_errors=0`

Bounded artifact files:
- raw sample file: `data/phase6_diagnostic_20260401/raw_posts/cap_20260401T184939Z_85c99020/raw_posts_000001.jsonl.gz`
- extracted sample lines: `data/phase6_diagnostic_20260401/artifacts/raw_firehose_sample.jsonl`
- state sample lines: `data/phase6_diagnostic_20260401/artifacts/captured_posts_state_sample.jsonl`
- summary JSON: `data/phase6_diagnostic_20260401/artifacts/capture_summary.json`

## Sample captured post identifiers
Representative URI selection:
1. Normal post (no reply/embed flags):
   - `at://did:plc:l5ykcgaeg5noxtdbqiu77boo/app.bsky.feed.post/3mihe7wquq22i`
   - reason: baseline simple post contract.
2. Rich/complex post (`has_embed=true`):
   - `at://did:plc:73qgdt6gfor27mdo65lgygxh/app.bsky.feed.post/3mihe7wbmh22n`
   - reason: exercises embedded external media and facet/link structure.
3. Oldest-in-sample post by `record_created_at`:
   - `at://did:plc:i4ulcycxlr3yugkorjbrcjtd/app.bsky.feed.post/3mihe6nw3ds2s`
   - `record_created_at=2026-04-01T18:48:56.308Z`
   - reason: closest thing to “older” within bounded fresh capture window.

Additional bounded stats from raw output:
- total rows: `25`
- unique URIs: `25`
- `has_embed=true`: `4`
- `has_reply=true`: `17`

## Raw firehose contract observations
Observed normalized raw row shape includes:
- identifiers: `capture_run_id`, `seq`, `repo_did`, `rkey`, `uri`, `cid`
- timing: `event_time`, `record_created_at`, `captured_at`
- classification: `operation`, `collection`, `has_reply`, `has_embed`
- payload: `record` object

Concrete field observations:
- normal sample has `has_reply=false`, `has_embed=false`, and `record.text`/`record.langs`.
- complex sample has `has_embed=true` and nested `record.embed.external` including URI/title/description/thumb.
- binary-ish values in raw decoded records are JSON-safe encoded where needed (e.g. `{"$bytes_b64": ...}` in embedded thumb ref path).

## Normalized unresolved-post contract observations
`captured_posts` rows were created with expected unresolved contract fields:
- keys: `uri` PK, `capture_run_id`, `repo_did`, `rkey`, `cid_at_capture`, `seq`
- timing: `record_created_at`, `captured_at`
- hydration state fields: `hydration_status`, `hydration_attempt_count`, `last_hydration_attempt_at`, `hydrated_at`, `hydrate_run_id`, claim fields

Pre-hydrate sample artifact (`captured_posts_state_sample.jsonl`) shows initial unresolved rows as:
- `hydration_status='pending'`
- `hydration_attempt_count=0`
- `last_hydration_attempt_at=null`

Post-hydrate DB state for sampled URIs shows:
- `hydration_status='hydrated'`
- `hydration_attempt_count=1`
- `last_hydration_attempt_at` and `hydrated_at` populated
- `hydrate_run_id='hyd_20260401T185109Z_97b40e6f'`
- `last_error=null`

## Immediate hydrate/API lookup results
Immediate lookup diagnostic (contract/connectivity check) was run against one freshly captured URI:
- endpoint: `app.bsky.feed.getPosts`
- requested URI:
  - `at://did:plc:l5ykcgaeg5noxtdbqiu77boo/app.bsky.feed.post/3mihe7wquq22i`
- response summary:
  - `posts` length: `1`
  - returned URI matches request

Artifacts:
- raw API payload: `data/phase6_diagnostic_20260401/artifacts/immediate_lookup_raw_response.json`
- normalized row sample: `data/phase6_diagnostic_20260401/artifacts/immediate_lookup_normalized_sample.json`

Important distinction:
- This immediate lookup validates external API connectivity + response contract.
- It is not evidence of delayed maturity waiting behavior.

## Raw hydrate API contract observations
Observed `getPosts` payload shape:
- top-level: `{ "posts": [ ... ] }`
- per post view fields observed:
  - `uri`, `cid`, `author`, `record`, `replyCount`, `repostCount`, `likeCount`, `quoteCount`, `indexedAt`, `labels`
- author object includes:
  - `did`, `handle`, `displayName`, plus optional metadata like `avatar`, `associated`, `createdAt`, `labels`
- record object includes post body and optional rich structures (`embed`, `facets`, etc.)

## Normalized hydrated contract observations
Hydrated Dataset-B row shape observed in `hydrated_posts_000001.jsonl.gz`:
- run linkage: `hydrate_run_id`, `capture_run_id`
- identifiers: `uri`, `cid`
- hydrate timing/index: `indexed_at`, `hydrated_at`
- author flattening: `author_did`, `author_handle`, `author_display_name`
- engagement counters: `reply_count`, `repost_count`, `like_count`, `quote_count`
- policy labels: `labels`
- preserved payload: `record`

Observed preservation behavior:
- normal post remains simple text/lang record.
- complex post retains rich record content (`embed.external`, `facets`) in normalized output.

## Mature hydration validation results
Live mature-path hydration run:
- `hydrate_run_id`: `hyd_20260401T185109Z_97b40e6f`
- associated `capture_run_id`: `cap_20260401T184939Z_85c99020`
- status: `completed`
- run window:
  - started: `2026-04-01T18:51:09.201592+00:00`
  - completed: `2026-04-01T18:51:09.820610+00:00`

Run counters from DB:
- `eligible_post_count=25` (claim-volume at run level)
- `hydrated_post_count=25`
- `missing_post_count=0`
- `failed_post_count=0`

Worker progress line confirms:
- claims taken: `claimed=25`
- request batches: `5`
- requested URIs: `25`
- hydrated rows written: `25`
- retryable/missing/failed state updates: `0/0/0`

Selector maturity semantics validated for this bounded run:
- maturity gate is based on `captured_at` cutoff.
- for this specific diagnostic, `maturity_hours=0` made sampled unresolved rows immediately eligible.
- this validates mature-path orchestration mechanics and state transitions, but does not validate long-delay (e.g. 24h) waiting behavior.

Claim safety outcomes:
- final `captured_posts` check shows no lingering claims (`claimed_by_worker` null for all rows, `claim_expires_at` null for all rows).

Miss behavior in this run:
- no misses occurred (`missing_post_count=0`), so no miss output files were emitted.

## Output files and persistence results
`batch_files` persistence validation:
1. Firehose file row:
   - `dataset_type=raw_posts`
   - `row_count=25`, `status=closed`, `byte_size=6292`
2. Hydrate file row:
   - `dataset_type=hydrated_posts`
   - `row_count=25`, `status=closed`, `byte_size=6658`

Readable artifact checks:
- raw gzip file successfully read and parsed as JSONL
- hydrated gzip file successfully read and parsed as JSONL
- immediate lookup artifacts parsed as JSON
- contract cross-stage sample artifact created:
  - `data/phase6_diagnostic_20260401/artifacts/contract_samples.json`

State consistency checks:
- `captured_posts` by hydration status:
  - `hydrated: 25`
- sampled rows show consistent `uri/cid` continuity from capture to hydration.

## Contract comparison summary
Stage A: raw firehose normalized row
- Contains capture context and extracted post metadata (`seq`, `repo_did`, `rkey`, `uri`, `cid`, `record_created_at`, `captured_at`, `record`).

Stage B: unresolved/state row (`captured_posts`)
- Persists canonical post identity and hydration lifecycle status (`pending -> claimed -> hydrated`), with attempt/error/claim metadata.

Stage C: raw hydrate API (`getPosts`)
- Returns public post view contract (`posts[]` with author, engagement counts, indexedAt, record).

Stage D: normalized hydrated output row
- Flattens authoritative post view into Dataset B shape while preserving full `record` payload.

Cross-stage mapping (confirmed on representative URIs):
- `uri` stable across all stages.
- `cid` from capture aligns with hydrated output in sampled rows.
- `record` richness present in raw capture and hydrated normalized output for complex posts.

## Problems encountered
1. Blocking live firehose TLS issue (before fix):
   - websocket connection failed certificate verification in this environment.
2. Blocking firehose file finalization issue (before fix):
   - raw row serialization failed when decoded record contained `bytes`-typed values.
3. Blocking hydrate API TLS issue (before fix):
   - HTTPS `getPosts` lookup failed certificate verification in this environment.
4. Non-blocking diagnostic script issue:
   - first ad-hoc immediate-lookup script used wrong normalizer symbol; rerun used correct function.

## Fixes made
1. `bluesky_pipeline/firehose/client.py`
- Added SSL context wiring using certifi CA bundle fallback to support certificate validation reliably for websocket connection.

2. `bluesky_pipeline/firehose/normalizer.py`
- Added JSON-safe conversion for raw normalized records so bytes-like values serialize safely (base64 wrapper object).

3. `bluesky_pipeline/hydrate/client.py`
- Added SSL context wiring using certifi CA bundle fallback for `urllib` HTTPS requests.

4. Validation after fixes
- full test suite rerun passed (`17/17`).
- bounded live firehose run completed and persisted correctly.
- immediate lookup succeeded against live endpoint.
- one-shot mature hydrate run completed with expected state/output updates.

## Remaining risks / caveats
- This phase intentionally used `maturity_hours=0` for bounded diagnostic timing; it does not prove long-delay maturity waiting behavior in real time.
- No retryable/miss/failure path occurred in this specific live sample; those paths are covered by automated tests, but not re-observed on live traffic in this short run.
- Single small run only; not a throughput/reliability soak test.

## Final verdict
Bounded Phase 6 live diagnostic is successful for intended scope.

Validated in real data:
- firehose connection, ingestion, parsing, URI extraction, unresolved-state insertion
- immediate `getPosts` contract/connectivity lookup
- mature-path hydration loop execution (one-shot), claiming, writing, and state transition completion
- output file persistence/readability and `batch_files` closure tracking

Given the explicit scope limits and caveats above, hydration/firehose integration is acceptable to proceed to the next phase.

## Exact recommended next step
Proceed to Phase 7 with a focused objective:
1. restore production maturity threshold (`maturity_hours=24`) for normal operation
2. run a time-shift or staged preloaded unresolved-post scenario to observe a true delayed maturity pickup in near-real test time
3. optionally execute one bounded live retry/miss diagnostic window (fault-injection or naturally retryable case) to complement this Phase 6 success case
