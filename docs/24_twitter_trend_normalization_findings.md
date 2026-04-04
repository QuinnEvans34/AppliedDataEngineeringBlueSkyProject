# Twitter Trend Normalization Findings

Date: 2026-04-03

## Output status
- Full normalized output: `local/reference_snapshots/twitter_trending/twitter_trending_normalized.parquet`
- Sample normalized output (parquet): `data/samples/twitter_trending_sample_1000_normalized.parquet`
- Sample normalized output (csv): `data/samples/twitter_trending_sample_1000_normalized.csv`
- Full normalized rows: `101,731`
- Sample normalized rows: `1,000`

## Fields added
The source columns were preserved and these derived fields were added:
- `trend_name_raw`
- `trend_name_clean`
- `trend_name_clean_no_hash`
- `trend_name_clean_no_dollar`
- `trend_name_alnum`
- `trend_name_token_count`
- `trend_name_char_count`
- `is_hashtag`
- `has_special_chars`
- `has_non_ascii`
- `normalized_key_with_hash`
- `normalized_key_no_hash`
- `normalized_key_no_dollar`
- `normalized_date`

## Rules implemented
1. Unicode normalization to `NFKC` plus curly-apostrophe normalization (`’`, `‘` -> `'`).
2. Lowercasing, trim, and internal whitespace collapse.
3. Separator normalization (`&`, `-`, `.`, `,`) to spaces.
4. Apostrophe-to-space normalization for stable token forms.
5. Dual hash-aware keys:
   - `normalized_key_with_hash` preserves hashtag semantics.
   - `normalized_key_no_hash` removes one leading `#`.
6. Ticker-aware key:
   - `normalized_key_no_dollar` removes one leading `$` after hash handling.
7. Canonical alphanumeric helper key:
   - `trend_name_alnum` strips non-alphanumeric punctuation for robust exact/fuzzy candidate generation.
8. Stable helper features for downstream matching (`token_count`, `char_count`, boolean flags, normalized date).

## Before/after examples
- `#FreenBecky1stFMVN` -> `clean=#freenbecky1stfmvn` | `no_hash=freenbecky1stfmvn` | `no_dollar=freenbecky1stfmvn` | `alnum=freenbecky1stfmvn`
- `#FHPopFestivalxNuNew` -> `clean=#fhpopfestivalxnunew` | `no_hash=fhpopfestivalxnunew` | `no_dollar=fhpopfestivalxnunew` | `alnum=fhpopfestivalxnunew`
- `#SmackDown` -> `clean=#smackdown` | `no_hash=smackdown` | `no_dollar=smackdown` | `alnum=smackdown`
- `$MEW` -> `clean=$mew` | `no_hash=$mew` | `no_dollar=mew` | `alnum=mew`
- `#MUFC` -> `clean=#mufc` | `no_hash=mufc` | `no_dollar=mufc` | `alnum=mufc`
- `#wellscharitycoin` -> `clean=#wellscharitycoin` | `no_hash=wellscharitycoin` | `no_dollar=wellscharitycoin` | `alnum=wellscharitycoin`
- `#BREMUN` -> `clean=#bremun` | `no_hash=bremun` | `no_dollar=bremun` | `alnum=bremun`
- `Big 4` -> `clean=big 4` | `no_hash=big 4` | `no_dollar=big 4` | `alnum=big 4`

## Edge cases observed
- Trends beginning with `#` keep their hashtag form in `trend_name_clean` and `normalized_key_with_hash`, while `trend_name_clean_no_hash` and `normalized_key_no_hash` provide the plain variant.
- Trends beginning with `$` keep ticker form in `trend_name_clean` and `trend_name_clean_no_hash`, while `trend_name_clean_no_dollar` provides ticker-stripped form.
- Curly apostrophes are normalized; apostrophes are converted to spaces to reduce token mismatches (`Flau’jae` -> `flau jae`).
- Non-ASCII values are preserved in cleaned keys (unless removed by alnum helper generation) and marked via `has_non_ascii`.
- Null/empty names are handled deterministically as empty strings with zero token/char counts.

## Remaining limitations
- This phase does not perform fuzzy scoring, semantic embedding, or post-to-trend matching logic.
- `trend_name_alnum` intentionally removes symbols and may collapse distinct branded forms.
- Normalization is language-agnostic and does not include locale-specific transliteration or stemming.

## Readiness and recommendation
- Raw unique names: `33,973`
- Normalized unique names (`normalized_key_with_hash`): `32,536`
- Normalized unique names (`normalized_key_no_hash`): `32,219`
- Duplicate rows on raw key (`date + name`): `122`
- Duplicate rows on normalized key (`date + normalized_key_no_hash`): `1,886`
- Rows flagged `is_hashtag`: `17,180`
- Rows flagged `has_special_chars`: `20,818`
- Rows flagged `has_non_ascii`: `546`

Recommendation:
- The normalized trend dataset is ready for local Bluesky text preparation and later matching phases.
- Matching should remain exact-first using normalized keys, with fuzzy and semantic fallback tiers added in the dedicated matching phase.
