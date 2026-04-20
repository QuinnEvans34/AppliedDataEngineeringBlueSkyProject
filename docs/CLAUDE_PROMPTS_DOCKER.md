# CLAUDE_PROMPTS_DOCKER.md
## Phased Prompts — Containerize the Pipeline

Work through phases in order. Full design is in
`docs/PROMPT_DOCKER_PRODUCTION.md`.

**Prerequisite.** The host `.venv` workflow currently works. Do
not break it at any phase — Docker is an *additive* deployment
target. After every phase, `python -m bluesky_pipeline.firehose`
(or whatever the current command is) must still work on the host.

---

## Phase A — Base image, dev container, dockerignore, env template

**Scope:** set up the scaffolding. After this phase you can build
the base image and drop into a dev shell, but no service runs yet.

```
>>> PROMPT START >>>
Read before editing:
  - docs/PROMPT_DOCKER_PRODUCTION.md
  - requirements.txt
  - bluesky_pipeline/  (tree it, identify entry-point modules —
    we'll use this info in Phases B and C; for now we only need
    to know it exists)

Do ONLY Phase A:

1. Create .dockerignore at the project root excluding:
     .venv/, .git/, data/, .pytest_cache/, __pycache__/,
     *.pyc, *.sqlite*, .DS_Store, node_modules/, tests/,
     *.log, docs/, .env, .env.*
   Keep sql/, bluesky_pipeline/, requirements.txt,
   pyproject.toml, and scripts/ (if it exists) in the build
   context.

2. Create docker/base.Dockerfile as a multi-stage build:
   - Stage 1 (builder): FROM python:3.12-slim-bookworm AS builder
     - apt-get install build toolchain (build-essential, git,
       curl) — only what's needed to compile any wheels that
       need it.
     - Create /app/.venv, python -m venv /app/.venv
     - COPY requirements.txt
     - /app/.venv/bin/pip install --no-cache-dir -r requirements.txt
   - Stage 2 (runtime): FROM python:3.12-slim-bookworm
     - Install only runtime apt deps if any (likely none beyond
       what python:slim includes).
     - RUN useradd --system --uid 10001 --shell /bin/bash bluesky
     - RUN mkdir -p /app /data && chown -R bluesky:bluesky /app /data
     - COPY --from=builder --chown=bluesky:bluesky /app/.venv /app/.venv
     - ENV PATH="/app/.venv/bin:$PATH"
     - ENV PYTHONUNBUFFERED=1
     - ENV PYTHONDONTWRITEBYTECODE=1
     - WORKDIR /app
     - COPY --chown=bluesky:bluesky bluesky_pipeline/ /app/bluesky_pipeline/
     - COPY --chown=bluesky:bluesky sql/ /app/sql/
     - USER bluesky
     - No ENTRYPOINT (derived images set it).
   Pin the python image to python:3.12-slim-bookworm for both
   stages. Do NOT pin the digest yet — we'll do that in Phase D
   once the images build cleanly.

3. Create docker/dev.Dockerfile:
   - FROM bluesky-base:dev  (we'll wire the tag in docker-compose)
   - Stay in a writable context — do NOT copy bluesky_pipeline or
     sql; the dev workflow mounts the repo at /app so edits are
     live.
   - Install dev tools: pytest, ruff, ipython via a small
     requirements-dev.txt (create it with those three, pinned
     loose initially). Use the venv at /app/.venv.
   - USER bluesky. Default CMD: ["bash"].

4. Create env.example at the project root with every env var the
   containers will read, each commented with its purpose and
   whether it's required. At minimum:
     # Snowflake — required for sql-runner and render_profanity_udf
     SNOWFLAKE_ACCOUNT=
     SNOWFLAKE_USER=
     SNOWFLAKE_PASSWORD=
     SNOWFLAKE_WAREHOUSE=COMPUTE_WH
     SNOWFLAKE_DATABASE=BLUESKYDATAENGINEERINGPROJECT
     SNOWFLAKE_ROLE=
     # Bluesky firehose — optional overrides
     BLUESKY_FIREHOSE_URL=
     # Output directory inside the container (shared volume)
     DATA_DIR=/data
   Comment which services read which vars.

5. Add `.env` to .gitignore if not already present.

6. Create a minimal docker-compose.yml at the project root with
   only the `dev` service wired. No long-running services yet.
   Mount the repo at /app so dev edits are live. Mount ./data at
   /data. Read env_file: .env. Set user: "10001:10001",
   read_only: true with tmpfs for /tmp, and no restart policy
   (default).

7. Create Makefile at the project root with these targets ONLY
   for Phase A:
     build-base:  docker build -f docker/base.Dockerfile -t bluesky-base:dev .
     build-dev:   docker build -f docker/dev.Dockerfile -t bluesky-dev:dev .
     build:       depends on build-base build-dev
     shell:       docker compose run --rm dev
     down:        docker compose down
   Later phases will add more targets.

Do NOT write Dockerfiles for firehose, hydrate, trend-match,
twitter-trends, or sql-runner yet. Do NOT add compose services
for them yet. Do NOT touch requirements.txt other than reading it.

Stop and report when done. Tell me: (a) whether
`make build` completes cleanly in your run (note: you may not
be able to run docker yourself — if so, say so; I'll run it
locally), (b) the final image size of bluesky-base if you ran
it, (c) any requirements.txt dependency that failed to install
in the slim image (common culprits: things needing gcc).
<<< PROMPT END <<<
```

**Verify after Phase A (run on your host):**

```bash
make build
docker images | grep bluesky   # bluesky-base:dev and bluesky-dev:dev
make shell                      # drops you into bash as uid 10001
# inside the container:
python --version                # 3.12.x
whoami                          # bluesky
ls -la /data                    # owned by bluesky
exit
```

Commit.

---

## Phase B — Firehose and hydrate service images + compose default profile

**Scope:** the two long-running services that need to work for a
live capture run.

```
>>> PROMPT START >>>
Phase A is complete — bluesky-base:dev builds and `make shell`
works. Read:
  - docs/PROMPT_DOCKER_PRODUCTION.md (sections on firehose and
    hydrate service images)
  - bluesky_pipeline/firehose/  (to identify the actual entry
    point — check __init__.py, client.py, and any main.py)
  - bluesky_pipeline/hydrate/
  - docs/PIPELINE_ORCHESTRATION.md if present, for how these
    services are invoked today on the host.

Do ONLY Phase B:

1. Create docker/firehose.Dockerfile:
   - FROM bluesky-base:dev AS base
   - ENTRYPOINT ["python", "-m", "<confirmed firehose entry
     module>"]
     If you cannot identify an unambiguous entry point, stop and
     ask me. Do not guess — a wrong entrypoint is silently bad.
   - HEALTHCHECK --interval=60s --timeout=10s --start-period=120s
     --retries=3 CMD python -c "<one-liner that checks for a
     recent write under /data/raw_posts, exits 0 if any file was
     modified in the last 600 seconds, else exits 1>"

2. Create docker/hydrate.Dockerfile following the same pattern.
   Entrypoint points at the hydrate module; confirm first.
   Healthcheck checks /data/hydrated_posts for recent writes.

3. Extend docker-compose.yml with two new services — `firehose`
   and `hydrate` — under a `profiles: [default]` so they start
   with `docker compose up` but don't start for other profiles.
   Each service:
     image: bluesky-firehose:dev (or -hydrate)
     build: context/dockerfile pointing at the right file
     env_file: .env
     user: "10001:10001"
     read_only: true
     tmpfs: [/tmp]
     restart: unless-stopped
     volumes:
       - ./data:/data
     mem_limit: 1g    # start conservative; tune later
     cpus: "1.0"
   Add healthcheck block matching the Dockerfile HEALTHCHECK.
   Order: hydrate depends_on firehose with
   condition: service_started (healthcheck dependency is premature
   until firehose has captured enough data for hydrate to run).

4. Extend Makefile:
     build-firehose:  docker build -f docker/firehose.Dockerfile -t bluesky-firehose:dev .
     build-hydrate:   docker build -f docker/hydrate.Dockerfile -t bluesky-hydrate:dev .
     build: depends on build-base build-dev build-firehose build-hydrate
     up:            docker compose up -d
     up-default:    docker compose --profile default up -d
     logs:          docker compose logs -f $(SERVICE)
     (make logs SERVICE=firehose)
     ps:            docker compose ps

5. Do NOT create the batch service Dockerfiles. Do NOT add
   twitter-trends or trend-match or sql-runner yet.

Stop and report when done. Tell me: (a) the exact entry-point
module paths you used for firehose and hydrate, (b) the
healthcheck command you settled on for each, (c) any assumption
you made about CLI args the entry point expects — list them and
flag them for review.
<<< PROMPT END <<<
```

**Verify after Phase B (host):**

```bash
make build
make up                                    # or make up-default
docker compose ps                          # firehose + hydrate Up (healthy)
make logs SERVICE=firehose                 # should see firehose output
ls -la data/raw_posts/                     # new files landing
make logs SERVICE=hydrate
ls -la data/hydrated_posts/                # eventually new files here too

# Confirm non-root and read-only:
docker inspect bluesky-firehose-<suffix> | grep '"User"'
docker inspect bluesky-firehose-<suffix> | grep ReadonlyRootfs
```

Commit.

---

## Phase C — Batch services (twitter-trends, trend-match, sql-runner) + `scripts/run_sql.py`

**Scope:** the services that run on-demand rather than streaming.
`sql-runner` is the interesting one; it deploys SQL against
Snowflake.

```
>>> PROMPT START >>>
Phase B is complete — firehose and hydrate are running in
containers and writing to /data. Read:
  - docs/PROMPT_DOCKER_PRODUCTION.md (batch service + run_sql.py
    sections)
  - bluesky_pipeline/   (identify entry points for twitter trends
    scraping/normalization and trend matching)
  - sql/00_setup/  (to understand what scripts/run_sql.py needs
    to execute)

Do ONLY Phase C:

1. Create scripts/run_sql.py (<= 150 lines). It:
   - Uses argparse with: --glob PATTERN (repeatable) OR positional
     file paths, --warehouse NAME (default: SNOWFLAKE_WAREHOUSE
     env), --dry-run, --suspend-after (default True).
   - Reads env vars SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER,
     SNOWFLAKE_PASSWORD, SNOWFLAKE_WAREHOUSE, SNOWFLAKE_DATABASE,
     SNOWFLAKE_ROLE. Fails fast with a clear error listing
     missing vars.
   - Collects matching files, sorts by path.
   - For each file: splits on `;` BUT respects JavaScript UDF
     `$$ ... $$` blocks (do not split inside them). Test this
     against sql/00_setup/04_udfs_template.sql.
   - Executes each statement via snowflake-connector-python.
     Logs `{file} [{stmt_idx}] -> OK (rows: N)` on success,
     and on failure prints file + stmt_idx + the offending SQL
     (first 500 chars) + Snowflake error code.
   - Prints a summary table at the end (files, statements, OKs,
     failures).
   - If --suspend-after: runs `ALTER WAREHOUSE <warehouse>
     SUSPEND;` at the very end, in a try/except that logs but
     does not fail the script.
   - Exit code: 0 if all statements OK, 1 otherwise.

2. Create these Dockerfiles:

   docker/twitter-trends.Dockerfile:
     FROM bluesky-base:dev
     ENTRYPOINT ["python", "-m", "<twitter trends entry module>"]
     No healthcheck (this is batch).

   docker/trend-match.Dockerfile:
     FROM bluesky-base:dev
     ENTRYPOINT ["python", "-m", "<trend match entry module>"]
     No healthcheck.

   docker/sql-runner.Dockerfile:
     FROM bluesky-base:dev
     COPY --chown=bluesky:bluesky scripts/run_sql.py /app/scripts/run_sql.py
     ENTRYPOINT ["python", "/app/scripts/run_sql.py"]
     No healthcheck.

3. Extend docker-compose.yml with three new services under
   `profiles: [enrich]` (so they don't start by default):
     twitter-trends, trend-match, sql-runner.
   Each:
     env_file: .env
     user: "10001:10001"
     read_only: true
     tmpfs: [/tmp]
     restart: "no"      # batch
     volumes: [./data:/data]
   sql-runner additionally mounts ./sql:/app/sql:ro so
   local edits to SQL files are picked up without a rebuild.

4. Extend Makefile:
     build-twitter-trends: ...
     build-trend-match:    ...
     build-sql-runner:     ...
     build: depends on all five service builds + base + dev
     up-enrich:  docker compose --profile enrich up -d
     sql:        docker compose run --rm sql-runner $(FILES)
                 # usage: make sql FILES='--glob sql/00_setup/**/*.sql'
     trends:     docker compose run --rm twitter-trends
     match:      docker compose run --rm trend-match

5. Smoke test scripts/run_sql.py against a trivial known-safe
   file before committing — e.g.
     make sql FILES='sql/99_validation/*.sql'
   (or a file you're confident is read-only).

6. Do NOT write CI workflow, runbook, or final doc polish yet —
   those are Phase D.

Stop and report when done. Tell me: (a) the entry-point module
paths you used for twitter-trends and trend-match, (b) your
statement-splitter test result for sql/00_setup/04_udfs_template.sql
(the UDF's $$ ... $$ block must not split), (c) any entry point
where you had to make an assumption about CLI args.
<<< PROMPT END <<<
```

**Verify after Phase C (host):**

```bash
# Rebuild includes the new images
make build
docker images | grep bluesky      # five service images + base + dev

# Deploy setup SQL through the runner
cp env.example .env                # fill in credentials manually
make sql FILES='--glob sql/00_setup/**/*.sql'
# Expect: success messages per statement, ends with warehouse suspend

# Run trend match
make up-enrich
docker compose logs trend-match
```

Commit.

---

## Phase D — CI workflow + runbook + doc polish

**Scope:** formalize the build in CI, write the operator runbook,
update the pain-points section of the outline.

```
>>> PROMPT START >>>
Phases A-C are complete. All five service images + base + dev
build, the compose profiles work, and scripts/run_sql.py deploys
SQL successfully. Read:
  - docs/PROMPT_DOCKER_PRODUCTION.md (CI + runbook sections)
  - .github/ (check if any workflows already exist so we don't
    conflict)

Do ONLY Phase D:

1. Create .github/workflows/docker-build.yml:
   - Triggers: push to main, pull_request to main.
   - Uses docker/setup-buildx-action@v3 and
     docker/build-push-action@v5.
   - Builds base, then dev, then the four service images in
     parallel.
   - Runs tests in the dev container against mounted source:
     `docker run --rm -v $PWD:/app bluesky-dev:ci pytest`
     (on the PR event only — on push to main we trust the PR's
     green check).
   - On push to main only: logs into GHCR using
     ${{ secrets.GITHUB_TOKEN }} and pushes images tagged with
     the short git SHA. No `latest` tag.
   - Whole file under ~80 lines. Use a matrix for the four
     service images; do not copy-paste.

2. Create docs/DOCKER_RUNBOOK.md covering:
   - Prereqs (Docker Desktop or engine + compose v2, a .env
     file populated from env.example).
   - Build: `make build` and what it produces.
   - Dev flow: `make up` → `make logs SERVICE=firehose` →
     `make shell` for interactive debugging.
   - One-shot enrichment batch: `make up-enrich` and expected
     order of service completion.
   - SQL deploy: `make sql FILES='...'` with examples for each
     sql/ subfolder in the order docs/SQL_DEPLOYMENT_SEQUENCE.md
     defines.
   - Troubleshooting:
       * "read-only filesystem" errors — something is trying to
         write outside /data or /tmp; fix it in code.
       * Healthcheck keeps failing — check the write-timestamp
         logic in the Dockerfile HEALTHCHECK.
       * Snowflake auth errors — list likely causes (role not
         granted, account identifier format, MFA vs password).
       * Permission denied on /data — host directory ownership
         mismatch; `chown -R 10001:10001 ./data`.
   - Production-deployment notes — what changes when moving off
     docker-compose to ECS, Kubernetes, or Nomad: swap host
     volume for managed storage, wire secrets to the cloud's
     secret manager, tune restart policies, add a log collector.

3. Update docs/SQL_FOLDER_OUTLINE.md pain-points section — move
   "No containerization" from open to resolved in
   CLAUDE_PROMPTS_DOCKER.

4. Update docs/CLAUDE_PROMPTS_INDEX.md — mark the Docker stream
   complete once all four phases are done. (You are finishing
   the fourth phase now.)

Do NOT add Kubernetes manifests. Do NOT add Prometheus / OTEL
wiring. Those are out of scope per PROMPT_DOCKER_PRODUCTION.md.

Stop and report when done. Tell me: (a) the CI workflow total
line count, (b) whether you identified any runbook entry you
couldn't write confidently because the behavior needs to be
observed first (flag it), (c) any service that'd benefit from a
sidecar or additional deployment target beyond what's scoped
here — just flag, don't implement.
<<< PROMPT END <<<
```

**Verify after Phase D:**

1. Push a feature branch, open a PR → CI builds all images and
   runs tests.
2. Merge → CI pushes tagged images to GHCR. Check the package
   page for your repo.
3. Follow the runbook end-to-end on a fresh clone as if you were
   a new teammate. Note any friction and fix it in a follow-up.

Commit. The Docker stream is done.
