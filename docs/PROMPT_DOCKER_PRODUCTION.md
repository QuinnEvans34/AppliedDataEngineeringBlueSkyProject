# PROMPT_DOCKER_PRODUCTION.md
## Claude-Extension Prompt — Containerize the Bluesky Pipeline for Production

Paste the **Prompt** section into the Claude extension. The rest is
background for the human reviewer.

---

### Why This Refactor

The Python side of the pipeline (firehose ingest, hydration, Twitter
trend scraping + normalization, trend matcher, Snowflake loader) all
runs today against the repo's `.venv` on the developer's laptop.
That means:

- **Not reproducible** — Python version and package versions drift
  across machines. "Works on my machine" bugs eat time.
- **Not deployable** — there is no artifact to ship to a server, a
  colleague's machine, or a CI runner.
- **Not isolated** — firehose ingest, which is a long-running
  network-facing process, shares the OS and filesystem with
  everything else the laptop is doing.
- **No secrets boundary** — Snowflake credentials live in the same
  shell env that runs arbitrary Python from the repo.
- **No resource controls** — a runaway hydration job can consume all
  host CPU / memory with nothing to stop it.

Containerizing fixes all of these and lets the project grow into
something that could realistically run on a server or a Kubernetes
cluster without rewrites.

---

### Target Topology

```
                          ┌─────────────────────────┐
                          │  shared volume:  /data  │
                          │  (host-mounted in dev,  │
                          │  Snowflake stage in     │
                          │  production)            │
                          └────────────┬────────────┘
                                       │
 ┌─────────────┐   ┌──────────────┐   │   ┌──────────────┐   ┌──────────────┐
 │ firehose    │──▶│ hydrate      │──┼──▶│ trend-match  │──▶│ sql-runner   │
 │ (long-run)  │   │ (long-run)   │   │   │ (batch)      │   │ (batch)      │
 └─────────────┘   └──────────────┘   │   └──────────────┘   └──────────────┘
                                       │                        │
                                       ▼                        ▼
                            hydration_misses/ etc.       Snowflake (external)
```

Services are independent containers orchestrated by `docker-compose`
for local dev. In production each is its own deployable (ECS task,
Kubernetes Deployment, Nomad job — whichever comes later).

---

### Containers We Need

| Service | Image name | Kind | Lifecycle |
|---|---|---|---|
| `firehose` | `bluesky-firehose:<tag>` | Long-running | Streams from Bluesky, writes JSONL.gz to `/data/raw_posts` |
| `hydrate` | `bluesky-hydrate:<tag>` | Long-running | Watches `/data/raw_posts`, hydrates posts, writes `/data/hydrated_posts` and `/data/hydration_misses` |
| `twitter-trends` | `bluesky-twitter-trends:<tag>` | Scheduled batch | Pulls daily trends, writes `/data/twitter_trends` |
| `trend-match` | `bluesky-trend-match:<tag>` | Scheduled batch | FAISS vector match; writes `/data/trend_matches` |
| `sql-runner` | `bluesky-sql-runner:<tag>` | Ad-hoc / scheduled | Deploys SQL from `sql/` against Snowflake; can also kick off `PUT @stage` uploads from `/data` |
| `pipeline-dev` | `bluesky-dev:<tag>` | Interactive | Dev-only convenience container with venv + CLI tools, mounts the repo |

All images share a common base (`bluesky-base`) built from a single
Dockerfile stage to keep the Python version pinned and the layer
cache warm.

---

### Production Hardening Checklist

Every image (except `pipeline-dev`) must:

1. **Multi-stage build.** Stage 1 installs build toolchain + deps
   into a virtualenv; stage 2 copies only the venv + app source into
   a `python:3.12-slim` runtime. Dropping build tooling from the
   final image cuts size ~400MB → ~150MB and removes CVE surface.
2. **Non-root user.** `RUN useradd --system --uid 10001 bluesky &&
   USER bluesky`. The process never runs as root.
3. **Read-only root filesystem.** `read_only: true` in compose,
   with explicit `tmpfs` for `/tmp` and a mounted volume for
   `/data`.
4. **Healthcheck.** `HEALTHCHECK` in Dockerfile that runs a
   service-specific probe (e.g., firehose: "are we writing files
   and is last write within N seconds").
5. **Pinned Python base.** `python:3.12.5-slim-bookworm` (pin digest
   too, once stable).
6. **No secrets baked in.** All credentials come from environment
   variables, sourced from a `.env` file in dev and from the
   orchestrator's secret store in prod. `.env` is in `.gitignore`;
   `env.example` is checked in.
7. **`.dockerignore`.** Exclude `.venv/`, `.git/`, `data/`, `*.pyc`,
   `__pycache__/`, `.pytest_cache/`, `tests/`, `docs/`. Smaller
   build context = faster builds.
8. **Logging to stdout/stderr only.** No log files in the container.
   `docker logs` or the orchestrator's log collector owns retention.
9. **Resource limits.** `mem_limit` and `cpus:` on every compose
   service.
10. **Reproducible builds.** `pip install --no-cache-dir -r
    requirements.txt` with a pinned `requirements.txt` (versions
    and hashes). Use `pip-compile` or `uv pip compile` to regenerate
    from `requirements.in` sources.

---

### Prompt (paste into Claude extension)

> You are adding full-pipeline Docker support to the Bluesky data
> engineering project. Read `docs/SQL_FOLDER_OUTLINE.md`,
> `docs/PIPELINE_ORCHESTRATION.md`, and
> `docs/PROMPT_DOCKER_PRODUCTION.md` (this file) before making any
> changes. Inspect `bluesky_pipeline/` to confirm entry-point
> modules for each service before you assume names.
>
> **Goal.** Containerize the full pipeline (firehose, hydrate,
> twitter-trends, trend-match, sql-runner, plus a dev container)
> with production-hardened images, a `docker-compose.yml` that
> runs everything locally against a host-mounted `data/` volume,
> and docs that explain how to build, run, and ship these images.
> The host `.venv` workflow must keep working unchanged — Docker
> is an *additional* way to run the pipeline, not a replacement.
>
> **Work to do, in order:**
>
> 1. **Create `docker/` folder** with these files:
>    - `docker/base.Dockerfile` — stage 1 `python:3.12-slim` builder
>      installing from `requirements.txt`; stage 2 `python:3.12-slim`
>      runtime with only the venv + app source copied in. Non-root
>      user `bluesky:10001`. Working directory `/app`. No ENTRYPOINT
>      (derived images set it).
>    - `docker/firehose.Dockerfile` — `FROM bluesky-base`, sets
>      `ENTRYPOINT ["python", "-m", "bluesky_pipeline.firehose"]`
>      (confirm the actual module path before writing — check
>      `bluesky_pipeline/firehose/__init__.py` and `client.py`).
>      Adds a `HEALTHCHECK` that verifies the process has written a
>      file to `/data/raw_posts` within the last 10 minutes.
>    - `docker/hydrate.Dockerfile` — same pattern, entrypoint to
>      the hydrate module.
>    - `docker/twitter-trends.Dockerfile` — same pattern.
>    - `docker/trend-match.Dockerfile` — same pattern.
>    - `docker/sql-runner.Dockerfile` — installs
>      `snowflake-connector-python` (already in requirements;
>      confirm) and copies `sql/` into `/app/sql`. Entrypoint is
>      a small `scripts/run_sql.py` that takes a path glob and
>      executes files in order against Snowflake using env-var
>      credentials.
>    - `docker/dev.Dockerfile` — `FROM bluesky-base`, plus dev
>      tools: `pytest`, `ruff`, `ipython`, `snowsql` CLI if easy.
>      `USER bluesky`. No `COPY .` — the repo is mounted at runtime.
>
> 2. **Write `scripts/run_sql.py`** (≤150 lines). It:
>    - Accepts `--glob "sql/00_setup/**/*.sql"` (or a list of explicit
>      paths), an optional `--dry-run`, and an optional `--warehouse`
>      override.
>    - Reads env vars `SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER,
>      SNOWFLAKE_PASSWORD, SNOWFLAKE_WAREHOUSE, SNOWFLAKE_DATABASE,
>      SNOWFLAKE_ROLE`. Fails fast if any required var is missing.
>    - Sorts matching files by path, splits each on `;` (respecting
>      `$$ ... $$` JavaScript UDF blocks — don't naively split), and
>      executes sequentially.
>    - Logs `file → statement index → rows affected / object created`
>      for each statement. On failure, prints the offending file,
>      statement index, and Snowflake error code; exits 1.
>    - At the end, runs `ALTER WAREHOUSE <warehouse> SUSPEND;` —
>      respects the repo's credit discipline.
>
> 3. **Create `docker-compose.yml`** at the project root with:
>    - `x-env: &default-env` anchor with all SNOWFLAKE_* vars
>      coming from `${SNOWFLAKE_...}` (i.e., from `.env`).
>    - Services: `firehose`, `hydrate`, `twitter-trends`,
>      `trend-match`, `sql-runner`, `dev`. Each references its
>      Dockerfile under `docker/`, sets `read_only: true`,
>      `tmpfs: [/tmp]`, `restart: unless-stopped` (for long-running)
>      or `restart: "no"` (for batches), and `mem_limit` / `cpus`.
>    - A named volume `bluesky_data` mounted at `/data` in every
>      service, backed by `./data` on the host (dev convenience).
>    - A `profiles:` split: default profile boots `firehose +
>      hydrate + dev`; an `enrich` profile boots the batch services;
>      a `sql` profile boots just the sql-runner. This lets a
>      developer `docker compose up` without firing compute they
>      don't need.
>    - Healthcheck definitions on long-running services;
>      `depends_on:` with `condition: service_healthy` where
>      appropriate (e.g., `trend-match` depends on `hydrate` being
>      healthy).
>
> 4. **Create `.dockerignore`** at the project root excluding
>    `.venv/`, `.git/`, `data/`, `.pytest_cache/`, `__pycache__/`,
>    `*.pyc`, `*.sqlite*`, `.DS_Store`, `node_modules/`, and
>    `tests/` (the dev container still runs tests, but via mounted
>    source, not copied source). Keep `sql/` and
>    `bluesky_pipeline/` in the build context.
>
> 5. **Create `env.example`** at the project root with every
>    environment variable the containers read, commented with
>    where it's used and whether it's required. Do not check in a
>    real `.env` — add `.env` to `.gitignore` if not already.
>
> 6. **Pin `requirements.txt`.** Today the file may or may not be
>    fully pinned — inspect it. If it isn't (loose `>=` versions,
>    missing hashes), produce `requirements.in` as the source of
>    truth for top-level dependencies and regenerate a pinned
>    `requirements.txt` via `uv pip compile --generate-hashes
>    requirements.in`. Commit both files. If `uv` isn't available
>    in the repo, use `pip-compile` from `pip-tools`.
>
> 7. **Add `Makefile`** at the project root with these targets:
>    - `make build` → builds all images.
>    - `make up` → `docker compose up -d` with the default profile.
>    - `make up-enrich` → enrich profile (batch services).
>    - `make sql FILES='sql/00_setup/**/*.sql'` → runs the
>      sql-runner container against the provided glob.
>    - `make logs SERVICE=firehose` → follow logs.
>    - `make shell` → exec into the dev container.
>    - `make test` → run pytest inside the dev container against
>      mounted source.
>    - `make down` / `make clean`.
>
> 8. **Add a GitHub Actions workflow** at
>    `.github/workflows/docker-build.yml` that on push to `main`:
>    builds `bluesky-base` and each derived image, runs
>    `docker run --rm bluesky-dev pytest`, and pushes tagged images
>    to `ghcr.io/${{ github.repository }}`. Use
>    `docker/build-push-action@v5` with build cache. Gate the push
>    step on `github.event_name == 'push'`. Keep the workflow under
>    ~80 lines total.
>
> 9. **Write the runbook.** Create
>    `docs/DOCKER_RUNBOOK.md` that covers:
>    - Prereqs (Docker Desktop or engine + compose v2, `.env`).
>    - Build sequence (`make build`).
>    - Local dev flow (`make up` → `make logs SERVICE=firehose` →
>      `make shell` for debugging).
>    - Running a single-shot enrichment (`make up-enrich`).
>    - Running the SQL deploys
>      (`make sql FILES='sql/00_setup/**/*.sql'`,
>      then `sql/01_landing/**/*.sql`, etc. in the order
>      `docs/SQL_DEPLOYMENT_SEQUENCE.md` defines).
>    - Troubleshooting: healthcheck failures, read-only FS errors,
>      `/data` permission errors, Snowflake auth errors.
>    - Production deployment notes: what changes when moving off
>      `docker-compose` to ECS / Kubernetes (spoiler: swap the
>      host volume for a managed one, wire secrets to a secret
>      manager, set `restart` policy appropriately).
>
> 10. **Update `docs/SQL_FOLDER_OUTLINE.md`** — the "Pain Points"
>     section ("No containerization" moves from "open" to "tracked
>     in this refactor").
>
> **Constraints:**
> - No `latest` tags in compose or CI. Every image gets an explicit
>   version tag (git short SHA is fine).
> - No secrets in Dockerfiles, compose files, `env.example`, or
>   the runbook — only placeholders.
> - No writable root FS. If a service genuinely needs to write
>   outside `/data` or `/tmp`, that is a design smell worth calling
>   out in your final message.
> - Must not break the existing host `.venv` workflow. Do not
>   delete or modify files under `bluesky_pipeline/` that only
>   exist to support host runs.
> - Python version is 3.12 across all images — confirm current
>   requirements are compatible before locking.
>
> **What to return:**
> - All new files (Dockerfiles, compose, Makefile, dockerignore,
>   env.example, runbook, GH Actions workflow, `scripts/run_sql.py`).
> - Updated `docs/SQL_FOLDER_OUTLINE.md`.
> - Updated `requirements.txt` (+ `requirements.in` if introduced).
> - A final-message section listing (a) any entry-point module paths
>   you had to guess because the real ones weren't obvious, and
>   (b) any places where a service would need more context (e.g.,
>   "the hydrate service has no CLI interface; I wrapped
>   `bluesky_pipeline.hydrate.selector.main` — please confirm
>   that's the right entry").
>
> Ask before you start if any of the following is unclear: whether
> `snowflake-connector-python` is already a dependency (check
> `requirements.txt`), whether the project already has a CI pipeline
> we should extend rather than create, or whether the team wants
> to host images on GHCR vs. ECR vs. Docker Hub (default: GHCR
> because the repo is on GitHub).

---

### Acceptance Checklist

- [ ] `make build` completes without errors on a clean checkout.
- [ ] `make up` brings `firehose + hydrate + dev` online; all
      healthchecks go green within 60s.
- [ ] `docker inspect <container> | grep "User"` returns `bluesky`
      (uid 10001), never `root`.
- [ ] `docker inspect <container> | grep ReadonlyRootfs` returns
      `true` on every long-running service.
- [ ] `make sql FILES='sql/00_setup/**/*.sql'` deploys the setup
      files and the warehouse is SUSPENDED at the end.
- [ ] A fresh `git clone` of the repo + `cp env.example .env` +
      edit credentials + `make up` works on a teammate's machine
      without any other setup.
- [ ] CI builds and pushes images on a push to `main`.
- [ ] `data/` on the host still contains the JSONL.gz files as
      before — the containers write to the same paths the host
      scripts expect.
- [ ] Host `.venv` workflow (`python -m bluesky_pipeline.firehose ...`)
      still works unchanged.

---

### Out of Scope (Track Separately)

- Kubernetes manifests. Compose is the local-dev story; prod
  orchestration is a follow-on after we've seen the compose setup
  run reliably for a couple of weeks.
- Observability (Prometheus, OpenTelemetry). Logging to stdout is
  enough for now; real metrics need their own design doc.
- Secrets manager integration. Env vars via orchestrator secrets
  is good enough for a research project; Vault / SSM Parameter
  Store is a later concern.
- Auto-suspending the Snowflake warehouse from the sql-runner
  container via a sidecar — today `run_sql.py` does it as the last
  step; that's sufficient.
