# 21 Local Twitter Dataset Profiling Findings

Date: 2026-04-04T06:01:17.141595+00:00

## Dataset Shape
- Source of truth: `local/reference_snapshots/twitter_trending/twitter_trending_full.parquet`
- Rows: `101,731`
- Columns: `4`
- Column names: `num_hours, date, name, counts`
- Dtypes: `{'num_hours': 'int8', 'date': 'object', 'name': 'str', 'counts': 'float64'}`
- Candidate uniqueness notes:
  - unique `name`: `33,973`
  - unique dates: `749`
  - unique `(date, name)` pairs: `101,609`

## Missingness
- Null counts by column: `{'num_hours': 0, 'date': 0, 'name': 0, 'counts': 0}`
- Blank-string counts by column: `{'date': 0, 'name': 0}`
- Columns with no missingness: `['num_hours', 'date', 'name', 'counts']`
- Columns with partial missingness: `[]`
- Columns with severe missingness (>=20%): `[]`

## Duplicate Findings
Duplicate definitions checked:
- full-row duplicates
- duplicate `(date, name)` pairs
- repeated `name` across dates

Results:
- Full-row duplicates: `122`
- Duplicate `(date, name)` pairs: `122`
- Repeated names (count >= 2): `14,119`
- Repeated names (count >= 10): `1,884`

## Value Distribution Highlights
- `counts` p50/p95/p99/max: `14481.0` / `253503.0` / `859933.6999999986` / `10652034.0`
- `num_hours` p50/p95/p99/max: `2.0` / `9.0` / `13.0` / `24.0`
- `name` char length p50/p95/max: `8.0` / `18.0` / `30.0`
- `name` token length p50/p95/max: `1.0` / `2.0` / `7.0`

## Naming/Noise Findings
- Case-variant collisions: `1,281`
- Hashtag-led rows: `17,180`
- Unique hashtags: `7,032`
- Rows with punctuation/noise chars: `4,406`
- Non-ASCII rows: `546`
- URL-like rows: `0`
- Emoji rows: `0`
- Low-information rows: `8,327`
- Lexical collision keys (>=2 rows): `14,178`

Representative lexical collision examples:
- key `#` variants: `#ฟิล์มธนภัทร`, `#عيد_الفطر_المبارك`, `#สมรสเท่าเทียม`, `#햇살처럼_찾아와준_선우의_스물둘`
- key `#smackdown` variants: `#SmackDown`, `#Smackdown`
- key `#wweraw` variants: `#WWERaw`, `#WWERAW`
- key `good tuesday` variants: `Good Tuesday`, `good tuesday`
- key `good friday` variants: `Good Friday`, `good friday`

## Temporal Findings
- Date range: `2024-01-01` to `2026-01-24`
- Distinct dates: `749`
- Missing dates inside min-max range: `6`
- Daily density min/median/mean/max: `35` / `136.0` / `135.82242990654206` / `244`
- Sparse days (<50 rows): `4`
- Sparse days (<100 rows): `11`

## Suspicious Numeric Findings
- `counts` zero rows: `1,395`
- `counts` negative rows: `0`
- `num_hours` zero rows: `0`
- `num_hours` negative rows: `0`
- `num_hours` > 24 rows: `0`
- `counts` IQR outliers: `11,999` (`11.79%`)
- `num_hours` IQR outliers: `2,202` (`2.16%`)

## Exact Recommended Normalization Rules For Phase 22
1. Preserve raw columns (`name`, `date`, `num_hours`, `counts`) unchanged and add derived normalized fields.
2. Unicode-normalize trend names with NFKC, then normalize curly apostrophes (`’`/`‘`) to ASCII apostrophe.
3. Trim leading/trailing whitespace and collapse repeated internal whitespace to single spaces.
4. Case-fold to lowercase for canonical matching keys while keeping raw display text separately.
5. Create dual hashtag-aware keys: one preserving leading `#` and one with a single leading `#` removed.
6. Normalize separator punctuation (`&`, `-`, `.`, `,`, `/`, `_`) to spaces before tokenization.
7. Create a ticker-aware variant by removing a single leading `$` for symbol-prefixed topics.
8. Create an alphanumeric helper key by stripping non-alphanumeric characters after normalization.
9. Add helper flags and metrics (`is_hashtag`, `has_special_chars`, `has_non_ascii`, token count, char count).
10. Deduplicate prepared trend rows by (`date`, normalized_no_hash_key`) in Phase 22.

## Go/No-Go For Phase 22
- Decision: **GO**
- Ready for Phase 22 trend normalization: `True`
- Rationale: Profiling is complete, data quality is understood, and deterministic normalization rules are specified.
