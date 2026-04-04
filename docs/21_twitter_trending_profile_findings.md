# Twitter Trending Local Profile Findings

Date: 2026-04-03

## Dataset size
- Source (local only): `local/reference_snapshots/twitter_trending/twitter_trending_full.parquet`
- Total rows: `101,731`
- Columns: `num_hours`, `date`, `name`, `counts`
- Unique topics (`name`): `33,973`
- Unique dates: `749`
- Daily row-count range: `35` to `244` (median `136`)

## Key columns for downstream use
- `date`: day-level partition key for temporal matching windows.
- `name`: primary trend text needing normalization.
- `counts`: noisy popularity signal; very heavy-tailed.
- `num_hours`: trend-duration-like signal; bounded `1..24`.

## Duplicate findings
- Exact duplicate rows: `122`
- Duplicate `date + name`: `122`
- Repeated topics across dates (count >= 2): `14,119`
- Recommendation: deduplicate by `(date, normalized_key_no_hash)` in downstream prep.

## Missing-value findings
- Missing values by column:
  - `num_hours`: `0`
  - `date`: `0`
  - `name`: `0`
  - `counts`: `0`
- No null-handling branch is required for phase-1 normalization, but keep defensive guards.

## Noise findings in trend names
- Hashtag-led rows: `17,180`
- Unique hashtags: `7,032`
- Contains digits: `4,220`
- Contains dollar-sign tickers: `2,158`
- Contains non-alnum (excluding whitespace and `#`): `4,406`
- Contains non-ASCII characters: `546`
- Case-variant collisions (`lower(name)` maps to multiple originals): `1,283`
- Multi-word rows: `34,032`

Representative noisy examples:
- `#FreenBecky1stFMVN`
- `$MEW`
- `ELITE 8` vs `Elite 8`
- `Flau’jae`
- `Martin Luther King Jr.`
- `T-Mobile`

## Numeric outlier findings
- `counts`:
  - p50: `14,481`
  - p99: `859,933.7`
  - max: `10,652,034`
  - IQR outliers: `11,999` rows (`11.79%`)
- `num_hours`:
  - p50: `2`
  - p99: `13`
  - max: `24`
  - IQR outliers: `2,202` rows (`2.16%`)

Interpretation: `counts` is highly skewed; avoid brittle min/max clipping assumptions for matching logic.

## Exact recommended normalization rules
1. Unicode-normalize trend text to `NFKC`.
2. Trim outer whitespace and collapse repeated internal whitespace to single spaces.
3. Case-fold to lowercase for canonical match keys while preserving original `name` for display/audit.
4. Build two keys:
   - `normalized_key_no_hash`: remove a leading `#` then normalize.
   - `normalized_key_with_hash`: normalize but preserve leading `#`.
5. Normalize punctuation variants:
   - map curved apostrophes (`’`) to `'`
   - replace separators (`&`, `-`, `.`, `,`) with spaces before token normalization
6. Create ticker-aware variant:
   - strip one leading `$` into `normalized_key_no_dollar` while keeping original value.
7. Remove non-alphanumeric punctuation from canonical matching keys (after steps above), but keep auxiliary hashtag/ticker variants.
8. Deduplicate prepared trend rows by `(date, normalized_key_no_hash)`.

## Risks for downstream matching
- Exact raw-string matching will miss:
  - case variants (`ELITE 8` vs `Elite 8`)
  - hashtag/non-hashtag variants (`#SmackDown` vs `SmackDown`)
  - punctuation variants (`T-Mobile`, apostrophe forms)
  - ticker and symbol-prefixed variants (`$TSLA`)
- Multi-token phrase variation and noisy campaign tags imply additional fuzzy/semantic fallback is likely needed.

## Recommendation for next phase
- Next phase should implement deterministic local normalization artifacts first:
  - canonical keys (`with_hash`, `no_hash`, `no_dollar`)
  - deduplicated per-date normalized trend table
  - reproducible transform pipeline + tests for punctuation/Unicode/case behavior
- Exact matching alone is **not sufficient** as the only strategy; design matching phase with exact-first plus fuzzy and semantic fallback tiers.
