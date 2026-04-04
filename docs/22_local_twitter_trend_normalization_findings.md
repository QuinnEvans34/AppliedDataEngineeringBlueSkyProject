# 22 Local Twitter Trend Normalization Findings

Date: 2026-04-04T06:10:16.563791+00:00

## Scope
- Phase spec: `docs/22_local_twitter_trend_normalization.md`
- Grounding inputs:
  - `docs/21_local_twitter_dataset_profiling.md`
  - `docs/21_local_twitter_dataset_profiling_findings.md`
  - `local/reference_snapshots/twitter_trending/twitter_trending_profile_summary.json`
- Mode: local-only normalization (`0` Snowflake queries, `0` extraction reruns)

## What Was Created
- Reusable module: `src/nlp/trend_normalization.py`
- Notebook: `notebooks/22_local_twitter_trend_normalization.ipynb`
- Tests: `tests/test_trend_normalization.py`
- Full normalized output: `local/reference_snapshots/twitter_trending/twitter_trending_normalized.parquet`
- Sample normalized outputs:
  - `data/samples/twitter_trending_normalized_sample_1000.parquet`
  - `data/samples/twitter_trending_normalized_sample_1000.csv`
- Optional summary: `local/reference_snapshots/twitter_trending/twitter_trending_normalization_summary.json`

## Exact Rules Implemented
1. Preserve raw columns (`name`, `date`, `num_hours`, `counts`) unchanged.
2. Normalize trend text with Unicode NFKC and apostrophe normalization (`’`/`‘` -> `'`).
3. Trim outer whitespace and collapse repeated inner whitespace.
4. Case-fold to lowercase (`casefold`) for deterministic canonical keys.
5. Normalize separators (`&`, `-`, `.`, `,`, `/`, `_`) to spaces.
6. Remove non-word punctuation except hashtag and ticker markers (`#`, `$`) in cleaned text.
7. Create `trend_name_clean` (with hashtag), `trend_name_clean_no_hash`, and `trend_name_clean_no_dollar`.
8. Create `trend_name_alnum` helper key for alphanumeric-only comparison.
9. Add helper metrics/flags: token count, char count, blank flag, hashtag flag, special-char flag, non-ASCII flag, URL-like flag.
10. Preserve normalized date as `normalized_date` for downstream matching windows.

## Why These Rules Were Chosen
Rules are directly grounded in Phase 21 profiling signals:
- Case-variant collisions (`1,281`) justify case-folding.
- Hashtag-heavy trends (`17,180` rows) justify dual hash-aware keys.
- Punctuation/noise rows (`4,406`) justify separator and punctuation normalization.
- Non-ASCII trends (`546` rows) justify Unicode normalization while preserving raw values.
- Low-information and lexical-collision findings justify helper keys/flags and explicit duplicate-impact measurement.

## Material Changes After Normalization
- Row counts are preserved:
  - full: `101731` -> `101731`
  - sample: `1000` -> `1000`
- Added deterministic derived columns without overwriting raw columns.
- Derived keys now collapse lexical variants deterministically (case, hashtag, separator, punctuation variants).

## Duplicate Consolidation Impact
Full dataset (`date` + key comparison):
- duplicates before normalization (`date + raw name`): `122`
- duplicates after normalization (`date + normalized_key_no_hash`): `1892`
- net delta (after - before): `1770`
- normalized keys with multiple raw variants: `1725`

Sample (`1000` rows):
- duplicates before: `0`
- duplicates after: `22`
- net delta: `22`

Representative collapse examples:
- `2024-07-31` key `shawn` -> `Shawn`, `shawn`, `SHAWN`, `#Shawn`
- `2024-01-13` key `meet day` -> `meet day`, `Meet Day`, `MEET DAY`
- `2024-02-23` key `jeongyeon` -> `Jeongyeon`, `jeongyeon`, `JEONGYEON`
- `2024-02-25` key `i wish you would` -> `I Wish You Would`, `i wish you would`, `I WISH YOU WOULD`
- `2024-03-02` key `$opsec` -> `$opsec`, `$OpSec`, `$OPSEC`
- `2024-03-09` key `d lo` -> `D’Lo`, `D Lo`, `D-Lo`

## Edge Cases Handled
- Null and blank text values are handled explicitly (`trend_name_raw=''`, safe derived defaults).
- Hashtag-preserving and hashtag-stripped variants are both retained.
- Ticker-prefixed values keep symbol-aware and symbol-stripped variants.
- Curly apostrophes normalize consistently (`’`, `‘` -> `'`).
- Non-ASCII text is preserved in clean keys (raw preserved regardless).
- URL-like strings are flagged (`has_url_like`) and normalized deterministically by the same stable pipeline.

## Known Limitations
- No fuzzy or semantic matching is implemented in this phase.
- `trend_name_alnum` intentionally removes non-alphanumeric symbols and may collapse distinct branded forms; raw and cleaned keys are retained to avoid information loss.
- This phase does not join to Bluesky data.

## Readiness
- Ready for next phase: **YES**
- Reason: deterministic normalization logic, tested behavior, normalized outputs written, and duplicate-impact visibility is complete for exact-first matching preparation.
