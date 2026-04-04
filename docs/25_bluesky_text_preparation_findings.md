# Bluesky Text Preparation Findings

Date: 2026-04-03

## Source files used
Canonical local phase6 files only (no demo/validation mix):
- `data/phase6_diagnostic_20260401/raw_posts/cap_20260401T184939Z_85c99020/raw_posts_000001.jsonl.gz`
- `data/phase6_diagnostic_20260401/hydrated_posts/hyd_20260401T185109Z_97b40e6f/hydrated_posts_000001.jsonl.gz`

Why these were chosen:
- same run-root context (`phase6_diagnostic_20260401`)
- matching `uri` overlap across raw + hydrated
- richer hydrated metadata for preferred text rows
- avoids mixing with tiny demo validation data under `data/hydrated_posts/...`

## Text extraction choices
- Primary text source: `record.text`
- Fallback if missing/non-string: empty string
- Row policy: one prepared row per `uri`, hydrated row preferred when both hydrated and raw exist.

## Derived fields added
Original source columns are preserved via source-prefixed and JSON payload fields (`raw_*`, `hydrated_*`, `raw_source_row_json`, `hydrated_source_row_json`).

Added preparation fields:
- `uri`
- `post_created_at`
- `source_run_tag`
- `text_source`
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

## Rules implemented
Deterministic text normalization:
1. Unicode normalize to `NFKC`.
2. Normalize curly apostrophes to ASCII apostrophe.
3. Lowercase.
4. Replace separator punctuation (`& - / _ , . ; : ! ? (...)`) with spaces for clean text.
5. Collapse repeated whitespace and trim edges.
6. Build alphanumeric helper by removing non `[a-z0-9\\s]` and re-collapsing whitespace.
7. Compute stable token and character counts from `post_text_clean`.
8. Compute boolean helper flags:
   - hashtag: `#...`
   - mention: `@...`
   - URL: `http/https`, `www.`, or bare domains like `youtube.com/...`
   - special chars
   - non-ASCII chars

## Before/after examples
- Raw: `ISSO MILENA VAI TB ENQUADREM A SONSA 🔥🔥🔥🔥 #bbb26`  
  Clean: `isso milena vai tb enquadrem a sonsa 🔥🔥🔥🔥 #bbb26`  
  Alnum: `isso milena vai tb enquadrem a sonsa bbb26`

- Raw: `youtube.com/shorts/mmokh... GREAT STORY!!!`  
  Clean: `youtube com shorts mmokh great story`  
  Alnum: `youtube com shorts mmokh great story`

- Raw: `I feel comfortable ... relief – especially ...`  
  Clean: `i feel comfortable ... relief – especially ...`  
  Alnum: `i feel comfortable ... relief especially ...`

## Edge cases discovered
- One URI has no usable text (`text_source='none'`), resulting in empty prepared text fields.
- Mention-heavy examples were not present in this specific dataset slice (`has_mention = 0`), but mention detection logic is implemented and tested.
- Emoji/non-ASCII text appears in multiple rows; retained in `post_text_clean` and signaled by flags.
- Accent characters can become split in `post_text_alnum` (expected for strict alnum helper; raw and clean remain preserved).

## Output snapshot summary
- Prepared rows: `25` (one per URI)
- Text source split: `24` hydrated, `1` none
- Flag counts:
  - `has_hashtag`: `1`
  - `has_url`: `2`
  - `has_mention`: `0`
  - `has_special_chars`: `22`
  - `has_non_ascii`: `10`

Artifacts written:
- `local/reference_snapshots/bluesky/bluesky_posts_text_prepared.parquet`
- `data/samples/bluesky_posts_text_prepared_sample.parquet`
- `data/samples/bluesky_posts_text_prepared_sample.csv`

## Remaining limitations
- Current prepared dataset is small (`25` URIs) and reflects one diagnostic run-root only.
- Mention behavior is tested but not represented in observed rows.
- No topic extraction or trend matching has been run yet (intentionally out of scope).

## Recommendation for next phase
- Proceed to local topic-extraction phase using `post_text_clean` and helper flags.
- Use `post_text_alnum` + flags as candidate-generation features for later exact/fuzzy matching stages.

Readiness statement:
- The local Bluesky text preparation output is stable, deterministic, and ready for the next local topic-extraction phase.
