# SNOWFLAKE_CREDIT_STRATEGY.md
## Snowflake Credit Efficiency Rules — All SQL Must Follow These

---

### Budget
Total Snowflake credit budget for this project: $10–20 maximum.
Target: as close to $0 as possible during development.

---

### Rule 1: Views Over Tables Everywhere Possible
Every new object in ENHANCED and CURATED layers must be a VIEW,
not a TABLE or MATERIALIZED VIEW, unless there is an explicit reason
to materialize. Views cost zero credits to define. They only consume
credits when queried.

```sql
-- CORRECT
CREATE OR REPLACE VIEW STG_ENHANCED_POSTS AS ...

-- WRONG — costs credits to build and store
CREATE OR REPLACE TABLE STG_ENHANCED_POSTS AS ...
CREATE OR REPLACE MATERIALIZED VIEW STG_ENHANCED_POSTS AS ...
```

---

### Rule 2: No Automatic Tasks or Streams Running on a Schedule
Do NOT create Snowflake Tasks with schedules (AFTER x MINUTES).
Do NOT activate existing streams unless explicitly told to.
All pipeline execution is manual COPY INTO, not automated ingestion.
The existing Snowpipes and Tasks in the codebase exist but are NOT
running — do not add new ones or activate existing ones.

---

### Rule 3: Use the Smallest Warehouse Possible
All queries run on COMPUTE_WH (X-SMALL) unless the query is known
to be very large. Never suggest LARGE or X-LARGE warehouses.
Suspend warehouse immediately after use:

```sql
ALTER WAREHOUSE COMPUTE_WH SUSPEND;
```

Add this as a comment reminder at the bottom of every SQL file.

---

### Rule 4: Develop and Test on Samples
Every new view should be validated with a LIMIT 100 query before
running against the full dataset. Never run SELECT * on landing
tables during development.

```sql
-- Development validation pattern
SELECT * FROM STG_ENHANCED_POSTS LIMIT 100;
-- NOT: SELECT * FROM STG_ENHANCED_POSTS;
```

---

### Rule 5: No CLONE, No Data Sharing, No Marketplace Queries During Dev
The Twitter trending topics data already exists as a local Parquet
file from a previous snapshot. Do NOT query the Snowflake Marketplace
dataset (DAILY_TWITTER_TOP_TRENDS.DIESEL.TWITTER_TRENDING) during
development — load the local snapshot instead. Marketplace queries
consume credits.

---

### Rule 6: COPY INTO Only When Data Is Ready
Do not run COPY INTO statements during SQL development. COPY INTO
is only run once per dataset family when the actual pipeline output
files are ready to load. Write the COPY INTO statements in the SQL
files as comments during development.

---

### Rule 7: No Clustering Keys During Development
Do not add CLUSTER BY clauses to any table definitions during
development. These are a post-launch optimization and cost credits
to maintain automatically.

---

### Credit Cost Reference
| Operation | Credit Cost |
|---|---|
| CREATE VIEW | $0 |
| SELECT on view (X-SMALL, <1min) | ~$0.001 |
| COPY INTO 1M rows | ~$0.05–0.10 |
| CREATE TABLE AS SELECT 1M rows | ~$0.10–0.20 |
| Marketplace query | Variable, avoid |
| Task running every 5 min | ~$2/day |
| Materialized view refresh | Variable, avoid |