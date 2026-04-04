# 23 Local Bluesky Text Preparation Findings

Date: 2026-04-04

## Scope
- Phase spec: `docs/23_local_bluesky_text_preparation.md`
- Grounding inputs:
  - `docs/22_local_twitter_trend_normalization.md`
  - `docs/22_local_twitter_trend_normalization_findings.md`
- Mode: local-only (`0` Snowflake queries, `0` collection reruns)

## Source Selection
Selected local run root:
- `data/phase6_diagnostic_20260401`

Selected source families/files:
- `data/phase6_diagnostic_20260401/raw_posts/cap_20260401T184939Z_85c99020/raw_posts_000001.jsonl.gz`
- `data/phase6_diagnostic_20260401/hydrated_posts/hyd_20260401T185109Z_97b40e6f/hydrated_posts_000001.jsonl.gz`

Selection rule (deterministic):
1. highest `prepared_non_empty_text_count`
2. highest `unique_uri_count`
3. highest `prepared_row_count`
4. lexical `run_root` tie-break

Why this source was selected:
- candidate run roots found: `2`
- selected source has strongest usable text coverage (`24` non-empty prepared rows from `25` unique URIs)
- selected source includes both raw and hydrated families for best traceability

## Text Field and Identifier Choices
- Primary text field: `record.text`
- Fallback text field: top-level `text`
- Stable record identifier retained: `uri`
- Timestamp retained as `post_created_at` using precedence:
  - `record_created_at` -> `record.createdAt` -> `indexed_at` -> `hydrated_at` -> `captured_at`
- Traceability fields retained:
  - `source_run_tag`, `text_source`
  - selected `raw_*` / `hydrated_*` metadata fields
  - `raw_source_row_json`, `hydrated_source_row_json`

## Added Prepared Fields
- `post_text_raw`
- `post_text_clean`
- `post_text_alnum`
- `post_token_count`
- `post_char_count`
- `has_hashtag`
- `has_url`
- `has_mention`
- `has_special_chars`
- `has_non_ascii`

## Exact Preparation Rules Implemented
1. Null-safe input handling (`None` or non-string -> empty string).
2. Unicode normalization with `NFKC`.
3. Curly apostrophe normalization (`’`/`‘` -> `'`).
4. Newline normalization (`\r\n`/`\r` -> `\n`) and whitespace flattening (`\n`/`\t` -> space).
5. Lowercasing.
6. Separator punctuation normalization to spaces (for example: `& - / _ , . ; : ! ? ( ) { } [ ]`).
7. Repeated whitespace collapse and trim.
8. `post_text_clean` keeps semantic markers like `#` / `@` where present.
9. `post_text_alnum` removes non `[a-z0-9\s]` for strict helper matching.
10. Deterministic helper flags for hashtags, URLs (including bare domains), mentions, special characters, and non-ASCII text.

These rules align with Phase 22 trend normalization goals: deterministic cleanup, raw preservation, and helper fields for exact/fuzzy/semantic downstream matching.

## Output Summary
Prepared output row counts:
- total rows: `25`
- non-empty raw text rows: `24`
- non-empty clean text rows: `24`
- blank clean text rows: `1`

Text source split:
- `hydrated_record_text`: `24`
- `none`: `1`

Duplicate impact (non-empty text):
- duplicate rows by `post_text_raw`: `0`
- duplicate rows by `post_text_clean`: `0`
- unique non-empty raw text: `24`
- unique non-empty clean text: `24`

Artifact/flag counts:
- `has_hashtag`: `1`
- `has_url`: `2`
- `has_mention`: `0`
- `has_special_chars`: `22`
- `has_non_ascii`: `10`
- raw newline count: `6`
- raw repeated punctuation pattern count: `3`

## Before/After Examples
- Raw: `youtube.com/shorts/mmokh...\n\nGREAT STORY!!!`
  - Clean: `youtube com shorts mmokh great story`
  - Alnum: `youtube com shorts mmokh great story`

- Raw: `👇🏼\nbsky.app/profile/ftum...`
  - Clean: `👇🏼 bsky app profile ftum`
  - Alnum: `bsky app profile ftum`

- Raw: `ISSO MILENA VAI TB ENQUADREM A SONSA 🔥🔥🔥🔥 #bbb26`
  - Clean: `isso milena vai tb enquadrem a sonsa 🔥🔥🔥🔥 #bbb26`
  - Alnum: `isso milena vai tb enquadrem a sonsa bbb26`

- Raw: `Once you go in you're (glp) knot... coming out` + newline + `laughtrack`
  - Clean: `once you go in you're glp knot coming out laughtrack`
  - Alnum: `once you go in you re glp knot coming out laughtrack`

## Edge Cases and Limitations
- One URI has no usable text (`text_source='none'`), producing blank prepared text.
- This local slice has no mention-bearing posts (`has_mention=0`), though mention handling is implemented and tested.
- `post_text_alnum` intentionally strips punctuation/emoji/diacritics for helper matching and may reduce stylistic distinctions; raw and clean fields preserve richer signal.
- Prepared dataset size is limited (`25` rows) because it reflects currently available local diagnostic artifacts only.

## Outputs Written
- `local/derived/bluesky/bluesky_posts_prepared.parquet`
- `data/samples/bluesky_posts_prepared_sample_1000.parquet`
- `data/samples/bluesky_posts_prepared_sample_1000.csv`
- `local/derived/bluesky/bluesky_posts_preparation_summary.json` (optional compact summary)

## Readiness for Next Phase
Ready for Phase 24 candidate extraction: **YES**.

Reason:
- source selection is explicit and reproducible
- deterministic normalization is implemented and tested
- raw text + stable IDs are preserved
- prepared outputs are written to required local paths with documented limitations
