# Twitter Trending Local Profile Findings

Date: 2026-04-03

## Dataset size
- Source (local only): `local/reference_snapshots/twitter_trending/twitter_trending_full.parquet`
- Total rows: `101,731`
- Columns: `num_hours, date, name, counts`
- Unique topics (`name`): `33,973`
- Unique dates: `749`
- Daily row-count range: `35` to `244` (median `136.0`, mean `135.82`)

## Key columns for downstream use
- `date`: day-level key for time-windowed matching.
- `name`: trend text requiring normalization.
- `counts`: heavy-tailed popularity signal (not robust for hard thresholds).
- `num_hours`: trend-duration-like signal (`1..24`) useful as secondary context.

## Duplicate findings
- Exact duplicate rows: `122`
- Duplicate `date + name` rows: `122`
- Repeated topics across dates (`count >= 2`): `14,119`
- Repeated topics with high recurrence (`count >= 10`): `1,884`
- Recommendation: deduplicate by `(date, normalized_key_no_hash)` after normalization.

## Missing-value findings
- `num_hours`: `0`
- `date`: `0`
- `name`: `0`
- `counts`: `0`
- Outcome: no null branch is needed for baseline normalization, but keep defensive handling in reusable transforms.

## Noise findings in trend names
- Hashtag-led rows: `17,180`
- Unique hashtags: `7,032`
- Contains digits: `4,220`
- Contains dollar-sign tickers: `2,158`
- Contains punctuation/non-alnum (excluding whitespace and `#`): `4,406`
- Contains non-ASCII characters: `546`
- Case-variant collisions (`lower(name)` has multiple originals): `1,283`
- Multi-word rows: `34,032`

Representative noisy examples:
- `#FreenBecky1stFMVN`
- `$MEW`
- `Big 4`
- `Elite 8`
- `ELITE 8`
- `#80million`
- `Flau’jae`
- `$BENJI`

## Numeric outlier checks
- `counts`:
  - p50: `14481.0`
  - p99: `859933.6999999986`
  - max: `10652034.0`
  - IQR outliers: `11,999` rows (`11.79%`)
- `num_hours`:
  - p50: `2.0`
  - p99: `13.0`
  - max: `24.0`
  - IQR outliers: `2,202` rows (`2.16%`)

## Exact recommended normalization rules
1. Unicode-normalize trend names to `NFKC`.
2. Trim leading/trailing whitespace and collapse repeated internal whitespace.
3. Case-fold to lowercase for canonical match keys, while preserving the original `name` for display/audit.
4. Build dual hash-aware keys:
   - `normalized_key_with_hash`: normalized text with hashtag semantics preserved.
   - `normalized_key_no_hash`: remove one leading `#` before normalization.
5. Normalize punctuation variants before token cleanup:
   - map curved apostrophes (`’`) to `'`
   - replace separators (`&`, `-`, `.`, `,`) with spaces.
6. Build ticker-aware variant `normalized_key_no_dollar` by removing one leading `$` while preserving raw value.
7. Build canonical compare key by removing residual non-alphanumeric punctuation after the steps above.
8. Deduplicate prepared trend rows by `(date, normalized_key_no_hash)`.

## Risks for downstream matching
- Raw exact-string matching will miss case, hashtag, ticker, punctuation, and Unicode variants.
- Multi-word phrase variation and punctuation noise create false negatives for strict exact matching.
- Heavy skew in `counts` means popularity thresholds alone are unreliable for candidate selection.

## Recommendation for the next phase
- Implement deterministic local normalization outputs first (canonical keys + deduplicated per-date trend table).
- Keep exact matching as tier 1 only.
- Add fuzzy and semantic fallback tiers in later matching work for recall.
- Explicit decision: exact matching alone is **not sufficient**.
