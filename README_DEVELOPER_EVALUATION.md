# Mini Foundry — Complete Developer Evaluation Guide

**Purpose:** This document gives an external reviewer everything needed to understand Mini Foundry’s architecture, current behavior, workflows, and gaps — so they can recommend the next development steps.

**Last updated:** June 2026  
**Repository:** `mini_foundry`  
**Branch context:** Active development on `v1_1` with a Palantir Foundry–inspired feature set  
**Coverage:** 28 backend routers · 77 workflows · 105 platform pages · 11 Celery tasks · 33 DB migrations · ~200+ API endpoints

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [What Mini Foundry Is](#2-what-mini-foundry-is)
3. [Technology Stack](#3-technology-stack)
4. [Runtime Architecture](#4-runtime-architecture)
5. [Repository Structure](#5-repository-structure)
6. [Platform Kernel (Shared Foundations)](#6-platform-kernel-shared-foundations)
7. [Database & Migrations](#7-database--migrations)
8. [Security & Governance Model](#8-security--governance-model)
9. [Feature Areas — What Exists and How It Works](#9-feature-areas--what-exists-and-how-it-works)
10. [Complete Process Workflows](#10-complete-process-workflows) — **every major process, step by step**
11. [API Surface](#11-api-surface)
12. [Frontend Structure & Navigation](#12-frontend-structure--navigation)
13. [Background Jobs & Workers](#13-background-jobs--workers)
14. [AI System](#14-ai-system)
15. [Testing & Quality Signals](#15-testing--quality-signals)
16. [Known Gaps, Risks & Technical Debt](#16-known-gaps-risks--technical-debt)
17. [Recommended Next Development Steps](#17-recommended-next-development-steps)
18. [Local Development Guide](#18-local-development-guide)
19. [Key Files to Inspect First](#19-key-files-to-inspect-first)
20. [Related Documentation](#20-related-documentation)
21. [Complete Coverage Matrix](#21-complete-coverage-matrix)

---

## 1. Executive Summary

Mini Foundry is a **self-hosted data platform inspired by Palantir Foundry**. It is not a full Foundry clone; it is a practical system where teams can:

- Connect and ingest data (CSV, Parquet, Postgres, REST)
- Catalog, profile, preview, and govern datasets
- Run governed SQL across multiple execution engines
- Build pipelines, dashboards, notebooks, and operational apps
- Model business objects in an ontology layer
- Trigger actions and workflows with audit trails
- Use AI (local or cloud) for SQL, Python, pipelines, and dashboards — with backend enforcement

### Current maturity

| Dimension | Status |
|-----------|--------|
| Feature breadth | **High** — most Foundry-like pillars have at least an MVP |
| Platform coherence | **Medium** — shared kernel exists but not all paths use it uniformly |
| Security/governance | **Medium** — strong primitives; some edge cases and legacy paths remain |
| Production readiness | **Low** — development defaults; hardening flags exist but need ops work |
| Test coverage | **Medium** — ~300+ backend unit tests; limited E2E |

### Governing design principle

```text
AI suggests.
Backend validates and enforces.
Workers execute long-running work.
Permissions filter what users can see or run.
Audit logs record sensitive operations.
Postgres persists metadata and staging data.
Redis accelerates cache and queue operations.
Object storage (MinIO/S3) stores lakehouse artifacts.
```

Every sensitive path should follow:

```text
resolve resource
  → resolve branch/version context
  → authorize user (capabilities + markings)
  → apply row policies and column masks
  → execute through approved engine
  → capture lineage
  → write audit event
  → return governed result
```

---

## 2. What Mini Foundry Is

### Product vision

Mini Foundry aims to be a **data operating system**: one place to connect data, govern access, transform it, model it as business objects, visualize it, act on it, and automate around it — with AI as an assistant, not an authority.

### Inspiration vs. scope

| Foundry concept | Mini Foundry equivalent | Maturity |
|-----------------|-------------------------|----------|
| Data Connection | Connectors (CSV, Parquet, Postgres, REST) | MVP |
| Dataset catalog | Catalog + profiles + quality | Good |
| Contour / Explore | Visual explore builder | Partial |
| Pipeline Builder | Graph pipelines + builds | Good |
| Ontology / Phonograph | Object types, links, actions, writeback | Partial |
| Object Explorer | Object browser + detail pages | Partial |
| Workshop / Apps | App builder + published apps | Partial |
| Quiver | Time-series analysis | MVP |
| AIP / Logic | AI assistant, logic canvas, evals | Partial |
| Governance | Markings, ACLs, audit, access requests | Good |
| Code Repositories | In-app Git + transforms + PRs | Partial |
| Automate | Automation monitors | MVP (new) |
| Multipass / SSO | OIDC, SAML stubs, LDAP config, API tokens | Partial |

### What is explicitly out of scope (today)

- Full enterprise Foundry parity (Fusion spreadsheets, Notepad, Marketplace, Cipher, streaming pipelines, etc.)
- Managed cloud deployment templates (TLS, HA, multi-tenant isolation are documented but not provisioned)
- Real-time streaming ingest (Kafka-style)

---

## 3. Technology Stack

### Frontend

| Layer | Technology |
|-------|------------|
| Framework | Next.js 15 (App Router) |
| Language | TypeScript |
| Styling | Tailwind CSS |
| Editors | Monaco (SQL, code) |
| Charts | ECharts |
| Layout | React Grid Layout (dashboards) |
| Graphs | React Flow / @xyflow (pipelines, lineage, ontology) |

### Backend

| Layer | Technology |
|-------|------------|
| API | FastAPI |
| ORM | SQLAlchemy (async) |
| Validation | Pydantic v2 |
| Migrations | Alembic |
| SQL parsing | sqlglot |
| Data processing | Pandas, PyArrow |
| ML | scikit-learn, joblib |

### Infrastructure

| Service | Role |
|---------|------|
| PostgreSQL 16 | Metadata DB, staging tables, ontology edits |
| Redis 7 | Cache, Celery broker/result backend |
| MinIO | S3-compatible object storage for Parquet lakehouse |
| Celery worker | Async jobs (pipelines, notebooks, profiling, etc.) |
| Celery beat | Scheduled jobs |
| Trino | Optional distributed SQL (Spark routed via Trino by default) |
| Ollama | Optional local AI (Docker profile `ai`) |
| Docker sandbox | Isolated Python execution (`mini-foundry-sandbox:0.5`) |

---

## 4. Runtime Architecture

```text
┌─────────────────────────────────────────────────────────────────┐
│  Browser — Next.js frontend (port 3000)                         │
│  JWT/session cookie → Authorization header on API calls         │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP JSON /api/v1
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  FastAPI backend (port 8000)                                    │
│  Middleware: request ID, idempotency, rate limiting, CORS       │
│  Routers: auth, data, connectors, governed_query, pipelines, …  │
└───┬──────────────┬──────────────┬──────────────┬────────────────┘
    │              │              │              │
    ▼              ▼              ▼              ▼
 PostgreSQL     Redis          MinIO/S3       Celery workers
 (metadata)    (cache/queue)  (Parquet)      (jobs + sandbox)
                                                    │
                                                    ▼
                                              Docker sandbox
                                              (--network=none, read-only FS)
```

### Docker Compose services

| Service | Purpose |
|---------|---------|
| `postgres` | Main database |
| `redis` | Cache + Celery |
| `minio` + `minio-init` | Object storage bucket setup |
| `migrate` | Alembic `upgrade head` on startup |
| `backend` | FastAPI on `:8000` |
| `worker` | Celery worker (mounts Docker socket for sandbox) |
| `beat` | Celery beat scheduler |
| `frontend` | Next.js on `:3000` |
| `trino` | Optional SQL engine |
| `ollama` + `ollama-init` | Optional local AI (profile `ai`) |
| `sandbox-image` | Builds `mini-foundry-sandbox:0.5` |

### Startup sequence (`backend/app/main.py`)

1. Production hardening checks (fail fast in `production` if misconfigured)
2. Seed admin user (`ADMIN_EMAIL` / `ADMIN_PASSWORD`)
3. Optional demo seed (`SEED_DEMO_DATA=true`)
4. Sync existing domain objects into platform `resources` table
5. Load user workflow definitions from `actions/workflows_user/`
6. Register all API routers under `/api/v1`

---

## 5. Repository Structure

```text
mini_foundry/
├── backend/
│   ├── app/                    # FastAPI application modules
│   ├── alembic/versions/       # 33 database migrations (0001–0033)
│   ├── docker/sandbox/         # Python sandbox Docker image
│   ├── tests/                  # ~48 test modules, 300+ tests
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── app/
│   │   ├── (platform)/         # New unified shell (105+ pages)
│   │   ├── catalog/            # Legacy routes (redirects/wrappers exist)
│   │   ├── dashboards/
│   │   ├── pipelines/
│   │   └── …                   # Other legacy app routes
│   ├── components/             # Shared UI (dashboards, pipelines, layout, …)
│   ├── lib/                    # api.ts, polling, workspace helpers
│   └── e2e/                    # Playwright specs (6 files)
├── docker/trino/catalog/       # Trino catalog definitions
├── docker-compose.yml
├── Makefile
├── .env.example
└── docs/ (various README*.md planning files)
```

### Backend module map

| Module | Path | Responsibility |
|--------|------|----------------|
| **Platform kernel** | `platform/` | Projects, resources, ACLs, versions, branches, access requests, exports, approvals |
| **Auth** | `auth/` | Register/login, JWT, sessions, OIDC/SAML/LDAP stubs, API tokens, service accounts |
| **Permissions** | `permissions/` | Dataset grants (legacy), ResourceACL, row policies, column masks, secrets (Fernet) |
| **Governed query** | `governed_query/` | Central SQL enforcement: resolve datasets, rewrite masks/RLS, execute, audit |
| **Data / catalog** | `data/` | Datasets, columns, profiles, preview, branching, lineage, explore, quality |
| **Connectors** | `connectors/` | CSV, Parquet, Postgres, REST ingestion + sync |
| **Execution** | `execution/` | SQL validator, sql_runner, DuckDB/Trino/Spark runners, query cancellation |
| **Pipelines** | `pipelines/` | Graph CRUD, compiler, preview/run, expectations, AI generation |
| **Dashboards** | `dashboards/` | CRUD, render, widgets, saved queries, AI generation, permissions |
| **Notebooks** | `notebooks/` | CRUD, cells, sandbox execution, AI Python |
| **Ontology** | `ontology/` | Object types, relationships, layouts, YAML import, writeback |
| **Actions** | `actions/` | Action registry, triggers, user workflows |
| **Applications** | `applications/` | Operational app builder + published runtime |
| **Code repo** | `code_repo/` | Repos, files, Git ops, PRs, transforms, test runs |
| **Jobs** | `jobs/` | Job model, Celery app, tasks, schedules |
| **AI** | `ai/` | Provider gateway, SQL/Python/logic endpoints, policy enforcement |
| **ML** | `ml/` | Model registry, training jobs, prediction preview |
| **Workspace** | `workspace/` | Folders, items, permissions (being absorbed into platform kernel) |
| **Governance** | `governance/` | Usage metrics, export requests, admin governance |
| **Notifications** | `notifications/` | In-app notifications + SSE stream |
| **Automation** | `automation/` | Condition→effect monitors (Foundry Automate-like) |
| **Collaboration** | `collaboration/` | Resource comments |
| **Media** | `media/` | Media sets (unstructured data) — early |
| **Activity** | `activity/` | Recents and favorites |
| **Explore** | `explore/` | Platform search (substring scan, not full-text index) |
| **Timeseries** | `timeseries/` | Quiver-style analysis |
| **Operations** | `operations/` | Health, queues, caches, logs console |
| **Audit** | `audit/` | Event persistence + admin viewer |
| **Cache** | `cache/` | Redis SQL/AI/render cache helpers |
| **Storage** | `storage/` | fsspec filesystem + Parquet helpers |
| **Seeds** | `seeds/` | Demo data (e-commerce dataset, ontology, pipeline) |

---

## 6. Platform Kernel (Shared Foundations)

Migration `0023_platform_kernel.py` introduced a **unified resource model**. This is the most important architectural direction in the codebase.

### Core tables

| Table | Purpose |
|-------|---------|
| `projects` | Top-level organizational/security boundary |
| `resources` | Every platform object (dataset, pipeline, dashboard, notebook, …) |
| `resource_versions` | Immutable version snapshots per branch |
| `resource_acl` | Capability grants (user/group/role) with inheritance flag |
| `resource_access_requests` | Access request workflow |
| `resource_markings` | Security classification tags on resources |
| `branches` | Global branch metadata |
| `build_runs` | Pipeline execution records |
| `lineage_edges` | Version-aware lineage graph |
| `export_requests` | Governed export approval flow |
| `approvals` | Generic approval queue |

### Resource types (non-exhaustive)

```text
dataset, pipeline, dashboard, notebook, ontology_object_type,
ontology_action, code_repository, ml_model, application, folder, project, …
```

### Capabilities (authorization)

```text
view_metadata    — see catalog entry, schema, lineage
view_data        — preview rows
use_in_sql       — reference in SQL queries
use_in_python    — mount in notebook/code sandbox
use_with_ai      — include in AI prompts
export           — request data export
edit             — modify resource definition
manage           — grant permissions, delete
run              — execute pipeline/action/build
publish          — publish dashboard/app
writeback        — ontology action side effects
```

### How authorization works

1. **ResourceACL** is the primary source of truth (migration `0033` backfills from legacy `dataset_permissions`)
2. Capabilities are checked via `require_object_capability()` in `permissions/enforcement.py`
3. **Security markings** are evaluated before ACL — user must hold all required markings
4. **Inheritance**: ACL entries with `inherit=true` propagate from parent folder/project
5. **Permission version** counter bumps on policy changes → invalidates Redis cache keys

Legacy tables (`dataset_permissions`, `column_permissions`, etc.) still exist but are being retired.

---

## 7. Database & Migrations

33 Alembic migrations trace product evolution:

| Range | Themes |
|-------|--------|
| 0001–0004 | Auth, catalog, dashboards, notebooks |
| 0005–0008 | Ontology, jobs, pipelines, Foundry parity batch |
| 0009–0012 | Workspace, secrets, branching, ontology writeback |
| 0013–0018 | Security markings, governance metadata, usage metrics, physical branching, materialization |
| 0019–0022 | Ontology validation, dashboard pages, code repo Git, redesign contracts |
| 0023–0027 | **Platform kernel**, operational controls, OIDC/branch/ML/lineage, versions/exports/approvals |
| 0028–0033 | Action governance, secret metadata, AI registry, dataset quality, observability manifests, remaining-work foundations |

Notable recent migration (`0033_remaining_work_foundations`):

- Creates dedicated `mf_datasets` schema (datasets no longer land in `public` alongside `users`)
- Backfills `resource_acl` from legacy `dataset_permissions`
- Adds notifications, automation monitors, API tokens, collaboration comments tables
- Adds explicit `change_type` on ontology actions

---

## 8. Security & Governance Model

### Authentication

| Method | Status |
|--------|--------|
| Email/password + JWT | ✅ Production path for dev |
| HttpOnly session cookies | ✅ Supported (`session_cookie_name=mf_session`) |
| Bearer JWT in header | ⚠️ Disabled by default (`allow_bearer_auth=false`) |
| OIDC | ✅ Real config when `oidc_issuer` set; simulated stub otherwise |
| SAML / LDAP | Config hooks exist; not fully wired |
| API tokens / service accounts | ✅ Added in recent migrations |
| Login lockout | ✅ Configurable attempts/window |

**Dev default:** `admin@mini.local` / `admin`

### SQL safety

1. **sqlglot AST validator** (`execution/sql_validator.py`) — blocks DDL/DML, multi-statement, unsafe constructs
2. **Governed query service** (`governed_query/service.py`) — default-deny: every table reference must resolve to a governed dataset the user has capability on
3. **Mask pushdown** — column masks compiled into SQL projections before execution
4. **Row policies** — injected as WHERE clauses via AST rewrite
5. **Read-only transactions** — local Postgres engine sets `default_transaction_read_only=on`
6. **Row limits** — enforced via AST (`enforce_outer_limit`), not regex
7. **Query cancellation** — `POST /api/v1/queries/{query_id}/cancel`

### Execution engines

| Engine | When used | Notes |
|--------|-----------|-------|
| PostgreSQL | Staging tables, external Postgres sources | Branch schemas: `mf_branch_{name}` |
| DuckDB | Parquet-backed datasets in MinIO | Can attach Postgres via `postgres_scanner` for cross-engine joins |
| Trino | Configured distributed queries | Default Spark runner routes here |
| Spark Connect | Optional when `SPARK_RUNNER_TYPE=spark` | |

### Python sandbox

User code **never runs in the backend process** (`allow_inprocess_code_exec=false` by default).

Sandbox container constraints (`notebooks/sandbox.py`):

```text
--network=none
--memory=1g --cpus=1
--read-only + tmpfs /tmp
--security-opt no-new-privileges
Per-run workspace mount (read/write)
Permitted dataset Parquet copies (read-only)
```

Worker mounts host Docker socket to spawn sandboxes — **major trust boundary**.

### Secrets

Connector passwords encrypted with Fernet (`permissions/secrets.py`), key derived from `ENCRYPTION_KEY`.

### Audit

Events logged for: login, permission changes, dataset preview, SQL runs, AI usage, notebook/code execution, pipeline builds, action triggers, exports, etc.

---

## 9. Feature Areas — What Exists and How It Works

### 9.1 Data connectors & ingestion

**Supported connectors:**

| Connector | Behavior |
|-----------|----------|
| CSV upload | Parsed with Pandas → Postgres staging table in `mf_datasets` schema |
| Parquet upload | Stored in MinIO → DuckDB engine |
| Postgres | Connection test, schema discovery, table sync (read-only source) |
| REST API | GET with pagination + bearer/api-key auth |

**Flow:**

```text
User uploads/connects → backend validates → data lands in staging or object storage
→ dataset + column metadata registered → profiling job queued → catalog visible per ACL
```

**Sync:** `POST /connectors/{source_id}/sync` triggers Celery job.

### 9.2 Catalog & datasets

**Capabilities:**

- List datasets visible to user (filtered by ACL + markings)
- Dataset detail: columns, profile, stewards, tags, glossary terms, security markings
- Preview rows (via governed query with masks + row policies)
- Visual explore (Contour-style step builder: filter, group-by, aggregate)
- Dataset branching: create branch, commit, diff, merge, abort
- Lineage graph (resource-level + version edges)
- Quality rules and expectations
- Dataset versions with storage manifests

**Dataset detail tabs** (platform UI under `/data/datasets/[id]/`):

- Overview, Explore, Branches, Profile, Quality, Permissions, Lineage, History

### 9.3 Governed SQL & analytics

**Entry points:**

- `/analytics/sql` — Monaco SQL editor + AI generation
- AI endpoints: `POST /ai/sql`, `POST /ai/run-sql`
- Dashboard render bindings
- Saved queries

**Governed query pipeline:**

```text
User SQL
  → sqlglot validate (SELECT-only)
  → resolve table refs → datasets (default-deny if ungoverned)
  → require_object_capability per dataset
  → resolve row policies + column masks
  → compile_governed_source_sql (rewrite projections + RLS)
  → pick_engine (postgres | duckdb | trino)
  → run_sql with timeout + row limit
  → apply fallback masks if needed
  → audit SQL_RUN event
  → return rows + dataset_versions metadata
```

**AI policy per dataset:** `local_only` | `cloud_allowed` | `metadata_only` | `no_external`

### 9.4 Pipelines & builds

**Capabilities:**

- Visual pipeline builder (React Flow graph)
- Node types: source, transform, join, filter, aggregate, output, etc.
- Compiler produces executable plan
- Preview (sample output) and Run (materializes output dataset)
- Expectations / data quality gates
- AI pipeline generation
- Build runs with inputs/outputs/logs
- Security marking propagation to output datasets
- Branch-aware pipeline versions

**Materialization flow:**

```text
User clicks Run → Celery job (run_pipeline task)
  → compiler executes graph node by node
  → output written to staging or Parquet
  → new dataset/version registered
  → lineage edges captured
  → build_run record updated
```

### 9.5 Dashboards

**Capabilities:**

- Drag-and-drop canvas (React Grid Layout)
- Widget types: metric, bar/line/pie chart, table, markdown, filter bar
- Data bindings → governed SQL queries
- Saved queries CRUD
- Publish workflow (draft → published)
- Dashboard permissions via ResourceACL
- Render cache (Redis, keyed on user + permission version + query hash)
- AI dashboard generation

### 9.6 Notebooks

**Capabilities:**

- Notebook CRUD, cell CRUD, reorder
- Cell execution via Celery → Docker sandbox
- AI-assisted Python generation
- Dataset mounts in sandbox (permitted Parquet copies only)
- Output: stdout, stderr, matplotlib images, small DataFrame samples

### 9.7 Ontology & object explorer

**Capabilities:**

- Object types with properties mapped to dataset columns
- Link types between object types
- Ontology graph visualization
- YAML import for bulk ontology setup
- Layout persistence
- Object search and detail pages
- **Actions** with permission grants
- **Writeback** to backing datasets (with audit in `ontology_edits`)
- Webhook dispatch on ontology changes

**Gap:** Object Sets (saved filterable sets) and Functions on Objects are not fully implemented.

### 9.8 Applications (Workshop-like)

**Capabilities:**

- App builder with pages and widgets
- Object table, detail, charts, action forms
- Publish workflow
- Published app runtime at `/apps/published/[appId]`
- Branch-aware app versions

### 9.9 Code repository

**Capabilities:**

- Repository CRUD, file browse/edit
- Git log, diff, branches, commit
- Pull requests with comments
- `@transform` decorator code transforms
- Run/test via sandbox worker jobs only

### 9.10 ML models

**Capabilities:**

- Model registry CRUD
- Train model version (Celery job)
- List versions, prediction preview
- Governed via ResourceACL

### 9.11 Time series (Quiver)

**Capabilities:**

- Operations: raw series, rolling, regression, FFT, resample
- UI at `/analytics/quiver`
- Backend: `POST /timeseries/analyze`

### 9.12 Governance admin

**UI areas under `/governance/`:**

- Users, groups, roles, capabilities
- Markings, row policies, column masks, secrets
- Access requests, approvals, exports, audit log

### 9.13 Operations

**UI areas under `/operations/`:**

- Jobs list/detail/cancel
- Schedules
- Health checks
- Queue depth, cache stats, logs

### 9.14 Notifications & automation

**Notifications:** In-app bell + SSE stream (`/notifications/stream`)

**Automation monitors:** Condition→effect rules (e.g., stale dataset → notify, failed build → trigger action)

### 9.15 AI platform

| Feature | Route / module |
|---------|----------------|
| AI assistant | `/ai/assistant` |
| AIP Logic canvas | `/ai/logic` |
| AI evaluations | `/ai/evaluations` |
| AI usage metrics | `/ai/usage` |
| Provider settings | `/settings/ai` |
| Providers | Ollama, Gemini, OpenAI-compatible custom |

### 9.16 Media sets (unstructured data)

**API prefix:** `/media-sets`

- Create media set (PDF, images, documents) with versioned uploads to object storage
- Link media versions to ontology objects via `ontology_links` JSON
- Download: `GET /media-sets/{id}/versions/{version_id}/download`

**Status:** Backend MVP; limited dedicated UI (may surface via data catch-all routes).

### 9.17 Collaboration (resource comments)

**API prefix:** `/collaboration`

- Threaded comments on any platform resource
- `@email` mention parsing → triggers notifications to mentioned users
- Resolve comment: `POST /collaboration/comments/{id}/resolve`

**UI:** `ResourceComments` component on resource detail pages.

### 9.18 Activity (recents & favorites)

**API prefix:** `/activity`

- `GET /activity/recents` — recently viewed resources
- `GET /activity/favorites` — starred resources
- `POST /activity/track` — record a view event
- `POST /activity/favorites/toggle` — star/unstar

**UI:** Workspace home, command palette integration.

### 9.19 Workspace (legacy folder tree)

**API prefix:** `/workspace`

Parallel to platform kernel folders; legacy `workspace_items` tree with its own permission model.

- Roots, folders, items CRUD, move, repair
- Per-item permissions (being superseded by ResourceACL)

**Gap:** Dual workspace models (legacy + platform) coexist during migration.

### 9.20 Streaming connectors

**API prefix:** `/connectors/streams`

- Register stream sources (Kafka-like abstraction)
- Subscriptions with checkpoint/watermark
- Poll: `POST /connectors/streams/subscriptions/{id}/poll`

**Status:** API scaffolding exists; not a full streaming pipeline product.

### 9.21 Operations console

**API prefix:** `/operations`

| Endpoint | Purpose |
|----------|---------|
| `GET /operations/workers` | Celery worker health |
| `GET /operations/queues` | Queue depths |
| `GET /operations/caches` | Redis cache stats |
| `POST /operations/caches/flush` | Admin cache flush |
| `GET /operations/storage` | MinIO/object storage usage |
| `GET /operations/metrics` | Platform metrics snapshot |
| `GET /operations/hardening` | Production hardening checklist status |
| `GET /operations/logs` | Recent structured logs |

**UI:** `/operations/*` pages (jobs, schedules, health, workers, queues, caches, storage, metrics, logs).

### 9.22 Enterprise identity (SAML / LDAP)

**API prefix:** `/enterprise`

- `GET /enterprise/saml/status`, `POST /enterprise/saml/test`
- `GET /enterprise/ldap/status`, `POST /enterprise/ldap/sync`

**Gap:** Config hooks; full SAML assertion handling and LDAP group sync incomplete.

### 9.23 Cross-cutting HTTP middleware

Applied to every request in `main.py`:

| Middleware | Module | Purpose |
|------------|--------|---------|
| Request ID | `observability.py` | `X-Request-ID` header for tracing |
| Idempotency | `idempotency.py` | `Idempotency-Key` header dedupes mutations |
| Rate limiting | `rate_limit.py` | Per-user/IP limits on auth + expensive endpoints |
| CORS | FastAPI | Restricts origin to `FRONTEND_ORIGIN` |

### 9.24 Demo seed & first boot

When `SEED_DEMO_DATA=true` (Compose default):

1. `seed_demo()` runs after migrations on backend startup.
2. Creates sample e-commerce dataset, ontology types, sample pipeline.
3. Idempotent — safe to re-run without duplicating.

**Manual:** `make seed-demo` or `python -m app.seeds.demo --force`.

---

## 10. Complete Process Workflows

This section documents **every major process** in Mini Foundry: who triggers it, which UI/API is used, what the backend does step by step, and what gets audited. Use this as the primary reference for evaluating whether each workflow is complete and safe.

### Workflow index

| # | Process | Section |
|---|---------|---------|
| 1 | Golden path (full demo) | [10.1](#101-golden-path-recommended-demo) |
| 2 | Login / session / auth | [10.2](#102-authentication--session) |
| 3 | Register user | [10.3](#103-user-registration) |
| 4 | OIDC / SSO login | [10.4](#104-oidc--sso-login) |
| 5 | API token / service account | [10.5](#105-api-token--service-account) |
| 6 | Project & resource lifecycle | [10.6](#106-project--resource-lifecycle) |
| 7 | CSV upload & ingestion | [10.7](#107-csv-upload--ingestion) |
| 8 | Parquet upload | [10.8](#108-parquet-upload) |
| 9 | Postgres connector + sync | [10.9](#109-postgres-connector--sync) |
| 10 | REST API connector | [10.10](#1010-rest-api-connector) |
| 11 | Connector re-sync | [10.11](#1011-connector-resync) |
| 12 | Catalog browse & preview | [10.12](#1012-catalog-browse--preview) |
| 13 | Visual explore (Contour) | [10.13](#1013-visual-explore-contour) |
| 14 | Dataset quality rules | [10.14](#1014-dataset-quality-rules) |
| 15 | Dataset versioning | [10.15](#1015-dataset-versioning) |
| 16 | Dataset-level branching | [10.16](#1016-dataset-level-branching) |
| 17 | Global/project branching | [10.17](#1017-globalproject-branching) |
| 18 | Permission grant | [10.18](#1018-permission-grant) |
| 19 | Access request & approval | [10.19](#1019-access-request--approval) |
| 20 | Row policies | [10.20](#1020-row-policies) |
| 21 | Column masking | [10.21](#1021-column-masking) |
| 22 | Security markings | [10.22](#1022-security-markings) |
| 23 | Governed export | [10.23](#1023-governed-export) |
| 24 | Manual SQL query | [10.24](#1024-manual-sql-query) |
| 25 | AI SQL generate + run | [10.25](#1025-ai-sql-generate--run) |
| 26 | Query cancellation | [10.26](#1026-query-cancellation) |
| 27 | Saved queries | [10.27](#1027-saved-queries) |
| 28 | Pipeline create / validate | [10.28](#1028-pipeline-create--validate) |
| 29 | Pipeline preview | [10.29](#1029-pipeline-preview) |
| 30 | Pipeline run (build) | [10.30](#1030-pipeline-run-build) |
| 31 | AI pipeline generation | [10.31](#1031-ai-pipeline-generation) |
| 32 | Dashboard create / edit | [10.32](#1032-dashboard-create--edit) |
| 33 | Dashboard render | [10.33](#1033-dashboard-render) |
| 34 | Dashboard publish | [10.34](#1034-dashboard-publish) |
| 35 | Notebook cell execution | [10.35](#1035-notebook-cell-execution) |
| 36 | Ontology setup & YAML import | [10.36](#1036-ontology-setup--yaml-import) |
| 37 | Object explorer query | [10.37](#1037-object-explorer-query) |
| 38 | Action trigger + writeback | [10.38](#1038-action-trigger--writeback) |
| 39 | App builder publish | [10.39](#1039-app-builder-publish) |
| 40 | Code repo transform / test | [10.40](#1040-code-repo-transform--test) |
| 41 | Pull request workflow | [10.41](#1041-pull-request-workflow) |
| 42 | ML model training | [10.42](#1042-ml-model-training) |
| 43 | Time series (Quiver) | [10.43](#1043-time-series-quiver) |
| 44 | AIP Logic canvas | [10.44](#1044-aip-logic-canvas) |
| 45 | Lineage & impact analysis | [10.45](#1045-lineage--impact-analysis) |
| 46 | Background job lifecycle | [10.46](#1046-background-job-lifecycle) |
| 47 | Scheduled jobs (beat) | [10.47](#1047-scheduled-jobs-beat) |
| 48 | Automation monitors | [10.48](#1048-automation-monitors) |
| 49 | Notifications | [10.49](#1049-notifications) |
| 50 | Platform search | [10.50](#1050-platform-search) |
| 51 | Audit log review | [10.51](#1051-audit-log-review) |
| 52 | Password reset | [10.52](#1052-password-reset) |
| 53 | Admin user & session management | [10.53](#1053-admin-user--session-management) |
| 54 | User AI settings | [10.54](#1054-user-ai-settings) |
| 55 | AI prompt registry | [10.55](#1055-ai-prompt-registry) |
| 56 | AI Python (notebook assist) | [10.56](#1056-ai-python-notebook-assist) |
| 57 | Connector connection test | [10.57](#1057-connector-connection-test) |
| 58 | Streaming connector poll | [10.58](#1058-streaming-connector-poll) |
| 59 | Media set upload & download | [10.59](#1059-media-set-upload--download) |
| 60 | Resource comments & @mentions | [10.60](#1060-resource-comments--mentions) |
| 61 | Recents & favorites | [10.61](#1061-recents--favorites) |
| 62 | Legacy workspace folders | [10.62](#1062-legacy-workspace-folders) |
| 63 | Pipeline join suggestions | [10.63](#1063-pipeline-join-suggestions) |
| 64 | Pipeline expectations gate | [10.64](#1064-pipeline-expectations-gate) |
| 65 | Generic approval queue | [10.65](#1065-generic-approval-queue) |
| 66 | Job retry & SSE streaming | [10.66](#1066-job-retry--sse-streaming) |
| 67 | Schedule run-now | [10.67](#1067-schedule-run-now) |
| 68 | Operations cache flush | [10.68](#1068-operations-cache-flush) |
| 69 | ML version promote / rollback | [10.69](#1069-ml-version-promote--rollback) |
| 70 | Dashboard permissions | [10.70](#1070-dashboard-permissions) |
| 71 | Ontology admin CRUD | [10.71](#1071-ontology-admin-crud) |
| 72 | User workflow execution | [10.72](#1072-user-workflow-execution) |
| 73 | Ontology webhook dispatch | [10.73](#1073-ontology-webhook-dispatch) |
| 74 | LDAP directory sync | [10.74](#1074-ldap-directory-sync) |
| 75 | Audit retention & export | [10.75](#1075-audit-retention--export) |
| 76 | Demo seed / first boot | [10.76](#1076-demo-seed--first-boot) |
| 77 | Governance groups & secrets | [10.77](#1077-governance-groups--secrets-admin) |

---

### 10.1 Golden path (recommended demo)

**Goal:** Prove the platform works end-to-end in one session.

| Step | Actor | Action | Route / API |
|------|-------|--------|-------------|
| 1 | Admin | Login | `/login` → `POST /auth/login` |
| 2 | Admin | Upload CSV | `/data/sources/new` → `POST /connectors/csv` |
| 3 | Admin | Open catalog | `/data/catalog` → `GET /catalog/datasets` |
| 4 | Admin | Preview dataset | Dataset detail → `GET /catalog/datasets/{id}/preview` |
| 5 | Admin | Grant analyst access | `/governance/users` → `POST /admin/permissions/grant` or project ACL |
| 6 | Analyst | AI SQL + run | `/analytics/sql` → `POST /ai/sql` → `POST /ai/run-sql` |
| 7 | Analyst | Build pipeline + run | `/build/pipelines` → `POST /pipelines/{id}/run` |
| 8 | Either | View lineage | `/data/lineage` → `GET /catalog/lineage` |
| 9 | Admin | Map ontology | `/ontology/manager` → admin ontology APIs |
| 10 | Analyst | Browse objects | `/ontology/explorer` → `GET /ontology/objects` |
| 11 | Analyst | Create dashboard | `/apps/dashboards/new` → render + publish |
| 12 | Analyst | Trigger action | Object detail → `POST /actions/trigger` |
| 13 | Admin | Review audit | `/governance/audit` → `GET /admin/audit` |

---

### 10.2 Authentication & session

**Trigger:** User opens `/login` and submits credentials.

**Steps:**

1. Frontend sends `POST /api/v1/auth/login` with email + password.
2. Backend (`auth/router.py`) verifies password hash (`auth/security.py`).
3. Login lockout checked if too many failures (`config.login_lockout_*`).
4. Backend returns either:
   - **Session cookie** (`mf_session` httpOnly) — preferred production path, or
   - **JWT token** in response body if bearer auth enabled.
5. Frontend stores session; `apiFetch` (`lib/api.ts`) attaches cookie or `Authorization: Bearer`.
6. `GET /auth/me` loads user + roles on every AppShell mount.
7. On `401`, token cleared and redirect to `/login`.
8. `POST /auth/logout` invalidates server-side session.
9. `POST /auth/refresh` rotates session/token if configured.

**Audit:** Login success/failure events logged.

**Modules:** `auth/router.py`, `auth/security.py`, `deps.py`, `frontend/lib/api.ts`

---

### 10.3 User registration

**Trigger:** `POST /auth/register` (if enabled on login page).

**Steps:**

1. Validate email uniqueness.
2. Hash password, create `users` row.
3. Assign default role (typically `viewer`).
4. Return user object or auto-login token.

**Admin alternative:** `POST /admin/users` with role assignment by admin.

---

### 10.4 OIDC / SSO login

**Trigger:** User clicks SSO button → `/auth/sso/login`.

**Steps:**

1. If `oidc_issuer` configured: redirect to real OIDC provider with PKCE/state.
2. If not configured: simulated stub returns dummy authorization URL (dev only).
3. Callback at `/auth/sso/callback` exchanges code → provisions/links user → issues session.
4. OIDC group/role claims mapped to platform roles (`oidc_group_claim`, `oidc_role_claim`).

**Gap:** Simulated SSO must be disabled in production (`require_production_hardening`).

**Modules:** `auth/sso.py`, `auth/enterprise_router.py`

---

### 10.5 API token / service account

**Trigger:** Admin creates token via governance or `POST /auth/tokens`.

**Steps:**

1. Admin creates service account or personal API token with scoped capabilities.
2. Token stored hashed; plaintext shown once to user.
3. Client sends `Authorization: Bearer <api_token>` on requests.
4. Backend resolves token → user/service account → same permission checks as session auth.

**Note:** `allow_bearer_auth=false` by default in config.

**Modules:** `auth/token_router.py`

---

### 10.6 Project & resource lifecycle

**Trigger:** Workspace UI `/workspace/projects`.

**Create project:**

1. `POST /platform/projects` → creates `projects` row.
2. Optional project ACL via `POST /platform/projects/{id}/access`.

**Organize resources:**

1. Every domain object (dataset, pipeline, dashboard, …) gets a `resources` row (synced at startup via `sync_existing_resources`).
2. `POST /platform/folders` creates folder resource.
3. `PATCH /platform/resources/{id}/move` moves resource into folder/project.
4. `PATCH /platform/resources/{id}/transfer` changes owner.

**Soft delete & restore:**

1. `DELETE /platform/resources/{id}` sets `deleted_at`.
2. Resource appears in `/workspace/trash` → `GET /platform/trash`.
3. `POST /platform/resources/{id}/restore` undeletes.
4. `DELETE /platform/trash/purge` permanently removes (admin).

**Version snapshots:**

1. `POST /platform/resources/{id}/versions` creates immutable `resource_versions` row with manifest JSON.
2. Used by pipelines, dashboards, apps, ontology on branches.

**Modules:** `platform/router.py`, `platform/service.py`, `platform/models.py`

---

### 10.7 CSV upload & ingestion

**Trigger:** `/data/sources/new` → CSV tab.

**Steps:**

1. **Optional preview:** `POST /connectors/csv/preview` — infer columns/types before commit.
2. User submits multipart form → `POST /connectors/csv`.
3. Backend (`connectors/csv_upload.py`):
   - Parses CSV with Pandas.
   - Normalizes table name → `staging_{name}_{uuid}`.
   - Writes to Postgres table in **`mf_datasets`** schema (not `public`).
   - Creates `data_sources` + `datasets` + `dataset_columns` rows.
   - Registers platform `resources` row.
   - Creates initial `resource_versions` / storage manifest.
4. Celery job queued: `csv_profile` task → computes profile stats.
5. Lineage edge: connector → dataset captured.
6. Dataset visible in catalog if user has `view_metadata`.
7. Audit: `CONNECTOR_CREATED`, `DATASET_CREATED`.

**Engine:** `execution_engine=postgres` for CSV datasets.

---

### 10.8 Parquet upload

**Trigger:** `/data/sources/new` → Parquet tab → `POST /connectors/parquet`.

**Steps:**

1. Parquet bytes written to temp file.
2. Uploaded to MinIO: `s3://{bucket}/datasets/{dataset_id}.parquet`.
3. PyArrow reads schema; columns registered in catalog.
4. Dataset `execution_engine=duckdb`; queries run via DuckDB runner.
5. Profiling job queued.

**Modules:** `connectors/parquet_upload.py`, `storage/parquet.py`, `storage/fs.py`

---

### 10.9 Postgres connector & sync

**Trigger:** `/data/sources/new` → Postgres tab.

**Register source:**

1. `POST /connectors/postgres/test` — test connection (result persisted).
2. `POST /connectors/postgres` — store connection config; password encrypted in `secrets` table.
3. Celery job: `postgres_discover` — discovers schemas/tables → registers dataset metadata per table.

**Ongoing sync:**

See [10.11 Connector re-sync](#1011-connector-resync).

**Modules:** `connectors/postgres.py`, `jobs/tasks/postgres_discover.py`, `permissions/secrets.py`

---

### 10.10 REST API connector

**Trigger:** `/data/sources/new` → REST tab → `POST /connectors/rest`.

**Steps:**

1. User configures URL, auth (bearer/api-key), pagination (page-number).
2. Backend pulls pages via GET requests.
3. Response JSON flattened → staging table or Parquet in object storage.
4. Dataset + columns registered; sync run recorded.

**Gap:** Incremental watermark sync is partial.

---

### 10.11 Connector re-sync

**Trigger:** Sources list → Sync button → `POST /connectors/{source_id}/sync`.

**Steps:**

1. Creates `sync_run` record with status `queued`.
2. Celery worker re-reads source data.
3. Updates staging table or Parquet file.
4. Bumps dataset version; updates profile.
5. User polls `GET /connectors/{source_id}/sync-runs` for history/logs.
6. Lineage updated; audit logged.

---

### 10.12 Catalog browse & preview

**Browse:**

1. `GET /catalog/datasets` — filtered by ResourceACL + security markings.
2. `GET /catalog/datasets/{id}` — detail with columns, profile, stewards, tags, markings.

**Preview:**

1. UI calls `GET /catalog/datasets/{id}/preview?limit=N`.
2. Backend routes through **`governed_dataset_preview()`** in `governed_query/service.py`:
   - Builds `SELECT * … LIMIT N`.
   - Requires `view_data` capability.
   - Applies row policies + column mask pushdown.
   - Executes on correct engine.
3. Audit: `DATASET_VIEWED` / preview event.
4. Result cached in Redis (key includes user + permission version + query hash).

---

### 10.13 Visual explore (Contour)

**Trigger:** `/data/datasets/[id]/explore` → `POST /catalog/datasets/{id}/explore`.

**Steps:**

1. User builds step chain in UI: filter → group-by → aggregate → …
2. Frontend sends step JSON to backend.
3. Backend (`data/router.py`) compiles steps to SQL subquery.
4. Compiled SQL executed via **governed_query** (same enforcement as SQL editor).
5. Results returned for visualization in explore UI.

**Modules:** `data/router.py`, `governed_query/service.py`

---

### 10.14 Dataset quality rules

**Trigger:** Dataset quality tab → `/data/datasets/[id]` quality section.

**Define rules:**

1. `POST /catalog/datasets/{id}/quality-rules` — e.g. non-null, value range, row count.
2. Rules stored in `quality_rules` table.

**Run quality check:**

1. `POST /catalog/datasets/{id}/quality-run` — evaluates rules against current dataset version.
2. Results in `GET /catalog/datasets/{id}/quality-results`.
3. Pipeline builds can gate on quality status (partial enforcement).

**Freshness:** `GET /catalog/datasets/{id}/freshness` — last updated timestamp check.

---

### 10.15 Dataset versioning

**Trigger:** Dataset detail → Versions tab.

**Steps:**

1. Every ingestion/build creates a `resource_versions` / dataset version row with manifest (row count, storage URI, content hash).
2. `GET /catalog/datasets/{id}/versions` — version history.
3. `GET /catalog/datasets/{id}/versions/diff` — schema diff between versions.
4. `POST /catalog/datasets/{id}/versions/{version_id}/promote` — set as current version pointer.
5. `GET /catalog/datasets/{id}/storage-manifests` — file-level manifest for Parquet datasets.
6. Classifications: `POST /catalog/datasets/{id}/classifications/confirm` — steward confirms PII/sensitivity labels.

---

### 10.16 Dataset-level branching

**Trigger:** `/data/datasets/[id]/branches`.

**Create branch transaction:**

1. `POST /catalog/datasets/{id}/branches` — creates branch transaction with `transaction_id`.
2. Postgres: copies/moves data into `mf_branch_{name}` schema.
3. DuckDB: copies Parquet to branch prefix in MinIO.

**Edit on branch:**

1. User works with `branch_name` context (BranchSelector in AppShell).
2. Queries rewrite schema to branch schema (`sql_runner._rewrite_branch_schemas`).

**Commit:**

1. `POST /catalog/datasets/{id}/branches/{transaction_id}/commit` — marks transaction committed.

**Diff:**

1. `GET /catalog/datasets/{id}/branches/{transaction_id}/diff` — row/schema differences vs main.

**Merge:**

1. `POST /catalog/datasets/{id}/branches/{transaction_id}/merge`.
2. **Current behavior:** DELETE all rows in target + INSERT from branch (destructive — see §16).
3. Branch schema/files may not be cleaned up.

**Abort:**

1. `DELETE /catalog/datasets/{id}/branches/{transaction_id}` — drops branch schema.

**Modules:** `data/branch_service.py`, `data/router.py`

---

### 10.17 Global/project branching

**Trigger:** `/workspace/branches` or project branches tab.

**Steps:**

1. `POST /platform/branches` — create named branch from `main` (pipelines, apps, ontology, dashboards get branch context).
2. User edits resources with `branch_name` in API payloads or BranchSelector.
3. `GET /platform/branches/{id}/compare` — diff changed resources vs parent.
4. `POST /platform/branches/{id}/review` — submit for review (approval queue).
5. `POST /platform/branches/{id}/merge` — merge branch resources to main.
6. `POST /platform/branches/{id}/abandon` — discard branch.

**Gap:** Frontend branch taskbar is partial; not all editors read global branch context.

**Modules:** `platform/router.py`, `platform/branch_service.py`

---

### 10.18 Permission grant

**Trigger:** Admin at `/governance/users` or resource permissions panel.

**Steps:**

1. Admin selects user/group/role + resource + capabilities.
2. `POST /admin/permissions/grant` (legacy) or `POST /platform/projects/{id}/access` / resource ACL endpoint.
3. `resource_acl` row created with capabilities JSON array.
4. `permission_versions` counter incremented → invalidates Redis caches.
5. Audit: `PERMISSION_CHANGED`.

**Capabilities checked at runtime:** `view_metadata`, `view_data`, `use_in_sql`, `use_in_python`, `use_with_ai`, `export`, `edit`, `manage`, `run`, `publish`, `writeback`.

**Modules:** `permissions/enforcement.py`, `permissions/router.py`, `platform/router.py`

---

### 10.19 Access request & approval

**Trigger:** User clicks "Request access" on a resource they cannot use.

**Steps:**

1. `POST /platform/resources/{id}/access-requests` with requested capabilities + reason.
2. Request stored as `pending` in `resource_access_requests`.
3. Notification sent to resource owner/admin.
4. Admin reviews at `/governance/access-requests` → `GET /platform/access-requests`.
5. `POST /platform/access-requests/{id}/decision` — approve or deny.
6. On approve: ResourceACL row created; notification sent to requester.
7. Audit logged.

**Explain permission:** `GET /platform/resources/{id}/permissions/explain` — why user can/cannot access.

---

### 10.20 Row policies

**Trigger:** `/governance/row-policies` admin UI.

**Steps:**

1. Admin defines row filter per dataset (column, operator, value, user attribute reference).
2. Policy saved to `row_policies` table.
3. On every governed query:
   - `resolve_row_policies()` loads applicable policies.
   - `compile_governed_source_sql()` injects WHERE clause via sqlglot AST rewrite.
4. Permission version bumped on policy change.

**Gap:** Raw SQL string policies exist in legacy data; structured DSL preferred. Writeback path may not apply row policies (see §16).

**Modules:** `permissions/row_policy.py`, `governed_query/rewrite.py`

---

### 10.21 Column masking

**Trigger:** `/governance/column-masks` admin UI.

**Steps:**

1. Admin sets mask strategy per column: `hidden`, `partial`, `hash`, etc.
2. Stored in `column_permissions` / mask registry.
3. On governed query: masks compiled into SELECT projections (pushdown) before execution.
4. Fallback post-query masking if column list unknown.
5. Hidden columns removed from API response.

**Modules:** `permissions/masking.py`, `governed_query/rewrite.py`

---

### 10.22 Security markings

**Trigger:** `/governance/markings` admin UI.

**Steps:**

1. Admin creates markings (e.g. `PII`, `SECRET`).
2. Assigns markings to resources via `resource_markings`.
3. Assigns marking eligibility to users/groups via `POST /governance/markings/eligibility`.
4. At authorization time: user must hold **all** resource markings before any capability applies.
5. Markings checked **before** admin/owner grants (owners cannot bypass markings via governed_query).

**Gap:** Markings on parent folders may not inherit to children automatically.

**Modules:** `permissions/enforcement.py`, `governance/router.py`

---

### 10.23 Governed export

**Trigger:** User requests data export from governance UI → `/governance/exports`.

**Steps:**

1. `POST /platform/exports` or `POST /platform/resources/{id}/exports` — creates export request (requires `export` capability).
2. Request enters approval queue → `GET /platform/approvals`.
3. Admin approves → `POST /platform/approvals/{id}/decision`.
4. `POST /platform/exports/{id}/generate` — backend runs governed query with masks/RLS applied, writes CSV/Parquet artifact.
5. `GET /platform/exports/{id}/download` — user downloads watermarked/audited file.

**Gap:** Download path exists in platform router; verify end-to-end in your environment.

**Audit:** Export request, approval, download events.

---

### 10.24 Manual SQL query

**Trigger:** `/analytics/sql` — user writes SQL in Monaco editor.

**Steps:**

1. User submits SQL (+ optional `query_id` for cancellation).
2. Request hits `POST /ai/run-sql` or governed query endpoint.
3. **Governed query pipeline** (`governed_query/service.py`):
   - `validate_sql()` — sqlglot AST, SELECT-only, single statement.
   - `resolve_datasets_for_sql()` — every table ref must match a dataset (**default-deny**).
   - `require_object_capability(..., use_in_sql)` per dataset.
   - Row policies + masks compiled in.
   - `pick_engine()` — postgres | duckdb | trino.
   - `run_sql()` — timeout, row limit via AST, read-only transaction (local PG).
4. Result optionally cached in Redis.
5. Audit: `SQL_RUN` with query hash + dataset version IDs.

**Cancel:** See [10.26](#1026-query-cancellation).

---

### 10.25 AI SQL generate + run

**Trigger:** SQL editor → natural language prompt.

**Generate only:**

1. `POST /ai/sql` with prompt + optional dataset IDs.
2. Backend checks `use_with_ai` capability + dataset `ai_policy`.
3. Prompt built with allowed schema/samples per policy (`local_only` / `metadata_only` / etc.).
4. AI gateway calls provider (Ollama/Gemini/custom).
5. Returns SQL draft — **not executed**.

**Generate + run:**

1. User clicks Run → `POST /ai/run-sql`.
2. Same AI generation step, then SQL passed through full governed query pipeline (§10.24).
3. Audit: `AI_PROVIDER_USED` + `SQL_RUN`.

**Modules:** `ai/router.py`, `ai/gateway.py`, `ai/policy.py`, `governed_query/service.py`

---

### 10.26 Query cancellation

**Trigger:** User clicks Cancel in SQL editor while query running.

**Steps:**

1. Frontend generates `query_id` UUID before starting query.
2. Query registered in `query_registry` (`execution/cancellation.py`).
3. `POST /api/v1/queries/{query_id}/cancel` — sets cancelled flag, invokes engine cancel callback.
4. Running query raises/interrupts; registry cleaned up in `finally` block.

**Modules:** `governed_query/router.py`, `execution/cancellation.py`

---

### 10.27 Saved queries

**Trigger:** Dashboard builder or SQL workspace → save query.

**Steps:**

1. `POST /dashboards/saved-queries` — stores SQL text + metadata as resource.
2. Version history: `GET /dashboards/saved-queries/{id}/versions`.
3. Dashboard widgets bind to saved query ID.
4. On render: saved SQL executed through governed query with same enforcement.

---

### 10.28 Pipeline create / validate

**Trigger:** `/build/pipelines/new`.

**Create:**

1. `POST /pipelines` — creates pipeline + empty graph.
2. User adds nodes/edges in React Flow UI.
3. `PATCH /pipelines/{id}` — persists graph JSON to `pipeline_nodes` / `pipeline_edges`.
4. Platform resource row linked.

**Validate:**

1. `POST /pipelines/{id}/validate` — compiler checks graph connectivity, schema compatibility, supported ops.
2. Returns errors/warnings before save or run.
3. Branch-aware: validation uses `branch_name` from context.

**Modules:** `pipelines/router.py`, `pipelines/compiler.py`, `pipelines/service.py`

---

### 10.29 Pipeline preview

**Trigger:** Pipeline builder → Preview panel → `POST /pipelines/{id}/preview`.

**Steps:**

1. Compiler resolves source datasets → checks `view_data` / `use_in_sql` permissions.
2. Executes graph with row limit (sample rows only).
3. Returns preview DataFrame for selected output node.
4. No materialization; no new dataset created.
5. Node-level preview: `GET /pipelines/{id}/nodes/{node_id}/preview`.
6. Node schema: `GET /pipelines/{id}/nodes/{node_id}/schema`.

---

### 10.30 Pipeline run (build)

**Trigger:** Pipeline builder → Run → `POST /pipelines/{id}/run`.

**Steps:**

1. Backend validates graph + permissions on all source datasets.
2. Creates `jobs` row (type `pipeline_run`) + `build_runs` platform record.
3. Celery task `run_pipeline` dispatched to worker.
4. Worker (`jobs/tasks/run_pipeline.py`):
   - Loads pipeline graph for branch/version.
   - Compiler executes node-by-node.
   - Applies expectations/quality gates if configured.
   - Writes output to Postgres staging or MinIO Parquet.
   - Creates/updates output dataset + new version.
   - Propagates security markings to output.
   - Captures lineage edges (inputs → output).
   - Logs build inputs/outputs on `build_runs`.
5. Frontend polls job status via `/operations/jobs/{id}` or build runs page.
6. SSE stream available: `GET /platform/build-runs/{id}/stream`.
7. Audit: pipeline run event; usage metrics logged.

**Modules:** `pipelines/service.py`, `jobs/tasks/run_pipeline.py`, `platform/models.py`

---

### 10.31 AI pipeline generation

**Trigger:** Pipeline builder → AI prompt → `POST /pipelines/ai-generate`.

**Steps:**

1. User describes desired pipeline in natural language.
2. Backend checks AI policy on referenced datasets.
3. AI returns graph JSON draft.
4. Frontend shows draft in builder (validate before save recommended).
5. User edits → validate → run (§10.28–10.30).

---

### 10.32 Dashboard create / edit

**Trigger:** `/apps/dashboards/new`.

**Steps:**

1. `POST /dashboards` — creates dashboard resource + empty component list.
2. User drags widgets from palette onto React Grid Layout canvas.
3. Each widget configured: type, data binding (SQL or saved query), styling.
4. `PUT /dashboards/{id}` — persists components to `dashboard_components`.
5. `POST /dashboards/{id}/permissions` — ResourceACL grants.
6. AI draft: `POST /dashboards/ai-generate`.

---

### 10.33 Dashboard render

**Trigger:** Opening dashboard viewer or editor preview.

**Steps:**

1. `POST /dashboards/{id}/render` — renders all components.
2. For each component with data binding:
   - Resolve SQL / saved query.
   - Execute via **governed_query** (masks + RLS + capability checks).
   - Check Redis render cache (key: user + permission version + query hash + dashboard version).
3. Per-component render: `POST /dashboards/{id}/components/{component_id}/render`.
4. Frontend renders ECharts charts, tables, metric cards, markdown.
5. Audit logged for sensitive renders.

**Cache refresh job:** Celery `dashboard_cache_refresh` pre-warms published dashboards on schedule.

**Modules:** `dashboards/data_binding.py`, `dashboards/router.py`, `cache/render_cache.py`

---

### 10.34 Dashboard publish

**Trigger:** `/apps/dashboards/[id]/publish`.

**Steps:**

1. Dashboard in `draft` state with validated components.
2. `POST /dashboards/{id}/publish` — sets status to `published`, creates resource version snapshot.
3. Published viewers see stable version; editors continue on draft (branch-aware).
4. E2E test: `frontend/e2e/dashboard-publish.spec.ts`.

---

### 10.35 Notebook cell execution

**Trigger:** `/develop/notebooks/[id]` → Run cell.

**Steps:**

1. User edits cell source (Python).
2. `POST /notebooks/{id}/cells/{cell_id}/run`.
3. Backend checks `use_in_python` on datasets referenced in cell.
4. Creates Celery job → worker runs `notebook_cell` task.
5. Worker (`notebooks/sandbox.py`):
   - Creates temp workspace under `SANDBOX_WORK_ROOT`.
   - Copies permitted dataset Parquet files to read-only mount.
   - Spawns Docker container (`mini-foundry-sandbox:0.5`):
     - `--network=none`, `--read-only`, memory/CPU limits.
   - Captures stdout, stderr, matplotlib PNG, small DataFrame head.
   - Deletes workspace after run.
6. Cell output persisted; UI polls job or receives result.
7. Audit: notebook execution event.

**AI Python:** AI can generate cell code; execution still goes through sandbox only.

**Modules:** `notebooks/router.py`, `notebooks/sandbox.py`, `jobs/tasks/notebook_cell.py`

---

### 10.36 Ontology setup & YAML import

**Trigger:** `/ontology/manager`, `/ontology/import`.

**Manual setup:**

1. Admin creates object types: `POST /admin/ontology/objects`.
2. Maps properties to dataset columns.
3. Creates link types: `POST /admin/ontology/relationships`.
4. Defines actions: `POST /admin/ontology/actions` + grant permissions.

**YAML bulk import:**

1. `POST /admin/ontology/import-yaml` — validates schema, creates/updates types/links/actions.
2. Dry-run/diff UI partial.

**Layout:** `POST /ontology/layout` — saves graph node positions for ontology manager UI.

**Modules:** `ontology/router.py`, `ontology/yaml_import.py`

---

### 10.37 Object explorer query

**Trigger:** `/ontology/explorer` or `/ontology/objects/[type]/[id]`.

**Steps:**

1. `GET /ontology/objects` — list object types user can see.
2. `GET /ontology/objects/{type_name}` — search/filter instances (backed by governed dataset query).
3. `GET /ontology/object-types/{type_name}/detail` — schema + backing dataset info.
4. Object detail page loads properties; masked columns hidden per user masks.
5. Related objects via link types in `RelatedObjectsTable` component.

**Gap:** Object Sets (saved filters) not fully implemented.

---

### 10.38 Action trigger + writeback

**Trigger:** Object detail page or dashboard action button → `POST /actions/trigger`.

**Steps:**

1. Optional preview: `POST /actions/preview` — shows what would change.
2. User confirms → `POST /actions/trigger` with action ID + object key + input params.
3. Backend checks action permission grant + `writeback` capability.
4. Loads current row from backing dataset.
5. **Writeback** (`ontology/writeback.py`):
   - Applies UPDATE/INSERT/DELETE on backing table.
   - Records `ontology_edits` row with before/after JSON.
6. Celery job may dispatch `ontology_webhook` to external URL.
7. Audit: action trigger event.
8. Action runs list: `GET /actions/runs`.

**Gaps (see §16):** Writeback may skip row policies; masked columns may appear in before/after snapshots; branch-unaware writes.

---

### 10.39 App builder publish

**Trigger:** `/apps/builder/[appId]` → Publish.

**Steps:**

1. User builds app pages with widgets (object table, detail, charts, action forms).
2. App saved via applications API (`PATCH /applications/{id}`).
3. `POST /applications/{id}/publish` — creates published version snapshot.
4. Runtime at `/apps/published/[appId]` → `GET /applications/{id}/published`.
5. Preview mode: `GET /applications/{id}/preview`.
6. Version history: `GET /applications/{id}/versions`.
7. E2E: `frontend/e2e/app-publish.spec.ts`.

**Gap:** Published app action widgets lack full approval/idempotency UX of object detail actions.

**Modules:** `applications/router.py`

---

### 10.40 Code repo transform / test

**Trigger:** `/develop/code/[id]`.

**Edit & run:**

1. User edits Python files with `@transform` decorators.
2. `POST /code-repo/run` — creates Celery job → `code_transform` task.
3. Worker runs transform in Docker sandbox (same isolation as notebooks).
4. Output dataset registered if transform produces data.
5. `POST /code-repo/test` — runs pytest in sandbox via `code_test` task.

**Git operations:**

- `GET /{repo_id}/git/log`, `/git/diff`, `/git/branches`
- `POST /{repo_id}/git/commit`, `/git/branches`

**Modules:** `code_repo/router.py`, `jobs/tasks/code_transform.py`, `jobs/tasks/code_test.py`

---

### 10.41 Pull request workflow

**Trigger:** Code repo → Create PR.

**Steps:**

1. User creates branch, makes changes, commits.
2. `POST /code-repo/repositories/{id}/pull-requests` — opens PR.
3. Reviewer views `GET /code-repo/pull-requests/{id}` + diff.
4. Comments: `POST /code-repo/pull-requests/{id}/comments`.
5. Status update merges or closes PR (partial — full review workflow incomplete).

---

### 10.42 ML model training

**Trigger:** `/develop/models` → Train.

**Steps:**

1. `POST /models` — register model resource.
2. `POST /models/{id}/train` — Celery `model_train` job.
3. Worker trains scikit-learn model on permitted dataset; saves artifact to storage.
4. Version recorded with training params + metrics + lineage to source dataset.
5. `GET /models/{id}/versions` — list versions.
6. Predict preview: governed prediction endpoint (artifact path/metrics returned).

**Modules:** `ml/router.py`, `jobs/tasks/model_train.py`

---

### 10.43 Time series (Quiver)

**Trigger:** `/analytics/quiver`.

**Steps:**

1. User selects dataset + time column + value column.
2. Chooses operation: raw, rolling mean, regression, FFT, resample.
3. `POST /timeseries/analyze` — backend loads governed dataset sample, runs analysis.
4. Results returned for chart rendering in Quiver UI.

**Modules:** `timeseries/router.py`, `timeseries/service.py`

---

### 10.44 AIP Logic canvas

**Trigger:** `/ai/logic`.

**Steps:**

1. User builds step graph: LLM prompt nodes, SQL nodes, template nodes.
2. `POST /ai/logic/run` — executes steps in sequence.
3. Each SQL step goes through governed query.
4. Each LLM step checks AI policy.
5. Run recorded in `ai_runs` + `ai_tool_calls` tables.
6. Usage visible at `/ai/usage`.

**Evaluations:** `/ai/evaluations` — deterministic leakage/safety test suites via `POST /ai/evaluations/{id}/run`.

**Modules:** `ai/router.py`, `ai/logic_executor.py`

---

### 10.45 Lineage & impact analysis

**Trigger:** `/data/lineage` or resource detail lineage tab.

**Global lineage:**

1. `GET /catalog/lineage` — full graph of dataset/pipeline edges.

**Resource lineage:**

1. `GET /platform/resources/{id}/lineage` — upstream/downstream for one resource.
2. `GET /platform/resources/{id}/impact` — what breaks if this resource changes (used in E2E `lineage-impact.spec.ts`).

**Capture points:** Connector ingest, pipeline run, ontology mapping, dashboard bindings, exports.

**Gap:** Column-level lineage only where manually captured; no automatic SQL parser lineage.

---

### 10.46 Background job lifecycle

**Trigger:** Any async operation (pipeline, notebook, profiling, …).

**Steps:**

1. API creates `jobs` row with status `queued`, type, input JSON, owner.
2. Celery worker picks up task → status `running`.
3. Worker executes task function in `jobs/tasks/`.
4. On success: status `succeeded`, output JSON stored.
5. On failure: status `failed`, error summary stored.
6. User views `/operations/jobs` → `GET /jobs`.
7. Detail: `GET /jobs/{id}` with logs/progress.
8. Cancel: `POST /jobs/{id}/cancel` — best-effort cancellation.

**Job types:** See §13 Celery task table.

**Modules:** `jobs/router.py`, `jobs/service.py`, `jobs/state_machine.py`

---

### 10.47 Scheduled jobs (beat)

**Trigger:** Admin creates schedule at `/operations/schedules`.

**Steps:**

1. `POST /admin/schedules` — cron expression + job type + input payload.
2. Celery beat loads schedules on startup from DB.
3. Beat fires task at scheduled time → normal job lifecycle (§10.46).
4. Schedule types: pipeline run, dashboard cache refresh, scheduled report, monitor evaluation.

**Scheduled report:** `scheduled_report` task — generates report JSON; email delivery partial.

**Modules:** `jobs/router.py` (schedules_router), `jobs/scheduler.py`

---

### 10.48 Automation monitors

**Trigger:** Admin creates monitor (API or future UI).

**Steps:**

1. `POST /automation/monitors` — condition JSON + effects list (notify, trigger action, etc.).
2. Monitor stored as platform resource.
3. Scheduler or manual `POST /automation/monitors/{id}/evaluate` runs condition check.
4. On match: effects executed (create notification, queue action, etc.).
5. Run history in `automation_monitor_runs`.

**Example conditions:** dataset stale > N hours, build failed twice, quality gate failed.

**Modules:** `automation/router.py`, `automation/service.py`

---

### 10.49 Notifications

**Trigger:** System events (approval needed, build failed, access granted, …).

**Steps:**

1. Backend creates `notifications` row for target user(s).
2. User sees unread count in AppShell bell (SSE-driven).
3. `GET /notifications` — list notifications.
4. `POST /notifications/{id}/read` — mark read.
5. SSE: `GET /notifications/stream` — real-time push to frontend.

**Gap:** Email/SMTP delivery not wired; in-app only.

**Modules:** `notifications/router.py`, `notifications/service.py`

---

### 10.50 Platform search

**Trigger:** Command palette (⌘K) or `/analytics/explore`.

**Steps:**

1. User types search query.
2. `GET /explore/search?q=…` — Python substring match over resource names, datasets, pipelines, etc.
3. Results ranked by simple match score (not full-text index).

**Gap:** No Postgres FTS or OpenSearch; no search over object instances or column names.

**Modules:** `explore/router.py`

---

### 10.51 Audit log review

**Trigger:** `/governance/audit`.

**Steps:**

1. `GET /admin/audit` — paginated audit log entries.
2. Filter by event type, user, resource, date range.
3. Events include: login, permission changes, dataset preview, SQL runs, AI calls, builds, actions, exports.

**Gap:** Retention policy and admin export controls partial.

**Modules:** `audit/router.py`, `audit/logger.py`

---

### 10.52 Password reset

**Trigger:** Login page → forgot password.

**Steps:**

1. `POST /auth/password-reset/request` with email → creates reset token (logged; email delivery depends on config).
2. User receives link/token → `POST /auth/password-reset/confirm` with token + new password.
3. Password hash updated; existing sessions may be invalidated.

**Modules:** `auth/router.py`

---

### 10.53 Admin user & session management

**Trigger:** `/governance/users`.

**Steps:**

1. `GET /admin/users` — list all users with roles.
2. `POST /admin/users` — create user with initial roles.
3. `POST /admin/users/assign-role` — add role to user.
4. `GET /admin/users/sessions` — list active sessions.
5. `POST /admin/users/sessions/{id}/revoke` — force logout.

**Modules:** `auth/admin_router.py`

---

### 10.54 User AI settings

**Trigger:** `/settings/ai`.

**Steps:**

1. `GET /settings/ai` — current provider, model, policy (`metadata_only` default).
2. User selects Ollama / Gemini / custom + optional API key.
3. `PUT /settings/ai` — persisted in `user_settings` table (API key never returned in GET).
4. Subsequent AI calls use these preferences via `ai/gateway.py`.

---

### 10.55 AI prompt registry

**Trigger:** `/ai/prompts` admin/creator UI.

**Steps:**

1. `GET /ai/prompts` — list versioned prompt templates.
2. `POST /ai/prompts` — create template with allowed context types.
3. `POST /ai/prompts/preview` — render template with sample variables (no provider call).
4. AI runs reference `prompt_template_id` in `ai_runs` audit table.
5. `DELETE /ai/prompts/{id}` — remove template.

---

### 10.56 AI Python (notebook assist)

**Trigger:** Notebook cell → "Generate with AI".

**Steps:**

1. Frontend sends cell context + dataset IDs to AI Python endpoint (via `ai/router.py`).
2. Backend checks `use_with_ai` + dataset AI policy.
3. AI returns Python draft — **not executed** until user runs cell (§10.35 sandbox).
4. Same policy redaction rules as SQL generation.

---

### 10.57 Connector connection test

**Trigger:** Source detail → Test connection.

**Steps:**

1. `POST /connectors/{source_id}/test` — runs live connection check.
2. Result persisted in `connector_test_results`.
3. History: `GET /connectors/{source_id}/test-results`.

---

### 10.58 Streaming connector poll

**Trigger:** API or scheduled job polling a stream subscription.

**Steps:**

1. Admin creates stream: `POST /connectors/streams`.
2. Creates subscription: `POST /connectors/streams/{id}/subscriptions`.
3. Poll: `POST /connectors/streams/subscriptions/{id}/poll` — fetches new records.
4. Checkpoint: `POST .../checkpoint` — saves watermark offset.

**Gap:** Not a full Kafka streaming pipeline; poll-based MVP.

---

### 10.59 Media set upload & download

**Trigger:** API (UI partial).

**Steps:**

1. `POST /media-sets` — create media set resource.
2. `POST /media-sets/{id}/versions` — multipart file upload → MinIO.
3. Optional ontology link metadata on version.
4. Download: `GET /media-sets/{id}/versions/{version_id}/download` — streamed file response.

---

### 10.60 Resource comments & @mentions

**Trigger:** Comments panel on resource detail pages.

**Steps:**

1. `GET /collaboration/resources/{id}/comments` — list thread.
2. User posts `POST .../comments` with body containing `@user@email.com`.
3. Backend parses mentions → creates notifications for mentioned users.
4. Moderator resolves: `POST /collaboration/comments/{id}/resolve`.

**Modules:** `collaboration/router.py`, `components/platform/ResourceComments.tsx`

---

### 10.61 Recents & favorites

**Trigger:** Automatic on resource view; manual star toggle.

**Steps:**

1. Opening a resource calls `POST /activity/track` (resource_type, id, title, path).
2. Recents shown on workspace home: `GET /activity/recents`.
3. Star icon toggles `POST /activity/favorites/toggle`.
4. Favorites list: `GET /activity/favorites`.

---

### 10.62 Legacy workspace folders

**Trigger:** Legacy `/workspace` tree (parallel to platform projects).

**Steps:**

1. `GET /workspace/roots` — top-level workspace roots.
2. `POST /workspace/folders` — create folder item.
3. `POST /workspace/items` — add resource reference.
4. `POST /workspace/items/{id}/move` — reorganize tree.
5. `POST /workspace/items/{id}/permissions` — legacy per-item grants.
6. `POST /workspace/repair` — fix broken parent references.

**Gap:** Migrate fully to platform kernel (`/platform/projects`, `/platform/folders`).

---

### 10.63 Pipeline join suggestions

**Trigger:** Pipeline builder join node → suggest joins.

**Steps:**

1. User selects two source nodes.
2. `GET /pipelines/_suggest/join?left_dataset=…&right_dataset=…`
3. Backend analyzes column name overlap + types → suggests join keys.
4. User accepts suggestion in join node config.

---

### 10.64 Pipeline expectations gate

**Trigger:** `/build/pipelines/[id]/expectations` + pipeline run.

**Steps:**

1. User defines expectations on pipeline (non-null, range, row count) in expectations UI.
2. Expectations stored on pipeline graph metadata.
3. On `POST /pipelines/{id}/run`, compiler evaluates expectations post-node or post-build.
4. Failed expectation → build status `failed` with constraint detail in build logs.

---

### 10.65 Generic approval queue

**Trigger:** `/governance/approvals` (exports, branch merges, dangerous actions, …).

**Steps:**

1. Sensitive operation creates `approvals` row (linked to export, branch review, etc.).
2. `GET /platform/approvals` — admin sees pending queue.
3. `POST /platform/approvals/{id}/decision` — approve/deny with note.
4. Downstream action proceeds or is blocked; notification sent.

**Related:** Export flow (§10.23), branch review (§10.17).

---

### 10.66 Job retry & SSE streaming

**Trigger:** Failed job detail page.

**Retry:**

1. `POST /jobs/{job_id}/retry` — re-queues job with same input (idempotency key checked).

**Live updates:**

1. `GET /jobs/{job_id}/stream` — SSE progress/log stream to frontend.
2. Build runs: `GET /platform/build-runs/{build_id}/stream`.

---

### 10.67 Schedule run-now

**Trigger:** `/operations/schedules` → Run now.

**Steps:**

1. Admin creates schedule: `POST /admin/schedules` with cron + job type + payload.
2. Celery beat loads schedule on startup.
3. Manual trigger: `POST /admin/schedules/{id}/run-now` — immediate job enqueue.
4. Pause/edit/delete via `PUT` / `DELETE /admin/schedules/{id}`.

---

### 10.68 Operations cache flush

**Trigger:** `/operations/caches` → Flush (admin).

**Steps:**

1. `GET /operations/caches` — shows SQL cache, render cache, AI cache key counts/TTLs.
2. `POST /operations/caches/flush` — optional scope param clears Redis namespaces.
3. All users see fresh query results after permission-sensitive flush.

---

### 10.69 ML version promote / rollback

**Trigger:** `/develop/models` → model detail.

**Promote:**

1. Training completes → version status `ready`.
2. `POST /models/{id}/versions/{version_id}/promote` — sets as `current_version_id`, status `promoted`.
3. Lineage + audit: `MODEL_VERSION_PROMOTED`.

**Rollback:**

1. `POST /models/{id}/rollback` — reverts to previous ready version.

**Predict preview:** `POST /models/{id}/versions/{version_id}/predict-preview`.

---

### 10.70 Dashboard permissions

**Trigger:** Dashboard settings → sharing.

**Steps:**

1. `POST /dashboards/{id}/permissions` — grant user/role capabilities on dashboard resource.
2. `DELETE /dashboards/{id}/permissions` — revoke grant.
3. Render checks dashboard ResourceACL before executing widget queries.

---

### 10.71 Ontology admin CRUD

**Trigger:** `/ontology/manager`, `/ontology/object-types`, `/ontology/link-types`.

**Steps:**

1. Create object: `POST /admin/ontology/objects` — type, properties, backing dataset mapping.
2. Update: `PUT /admin/ontology/objects/{id}`.
3. Delete: `DELETE /admin/ontology/objects/{id}`.
4. Create link: `POST /admin/ontology/relationships`.
5. Delete link: `DELETE /admin/ontology/relationships/{rel_id}`.
6. YAML bulk: `POST /admin/ontology/import-yaml`.
7. Action admin: `POST/PATCH/DELETE /admin/ontology/actions` + `POST .../grant`.

**Object instance query:** `GET /objects/{type}/{id}`, `GET .../related/{rel_name}`.

---

### 10.72 User workflow execution

**Trigger:** Action or automation effect referencing a workflow key.

**Steps:**

1. Workflow definitions loaded at startup from `actions/workflows_user/` (`load_user_workflows()`).
2. Action trigger or automation effect enqueues Celery `run_workflow` job.
3. Worker executes registered workflow steps (Python handlers in action registry).
4. Job output stored; audit logged.

**Admin:** `GET /admin/workflows` — list registered workflow keys.

---

### 10.73 Ontology webhook dispatch

**Trigger:** Successful ontology writeback with webhook configured on action.

**Steps:**

1. Writeback completes (§10.38).
2. Celery task `ontology_webhook` queued with edit payload.
3. Worker POSTs to configured external URL (before/after diff, object metadata).
4. Delivery status recorded; failures retried per job policy.

---

### 10.74 LDAP directory sync

**Trigger:** Admin → enterprise settings → `POST /enterprise/ldap/sync`.

**Steps:**

1. Requires `ldap_sync_enabled=true` + bind credentials in config.
2. Connects to LDAP/AD, reads users and group memberships.
3. Provisions/updates platform users; maps LDAP groups to roles (partial).
4. Returns sync summary (created/updated/deactivated counts).

**Gap:** Full AD group → platform group mapping incomplete.

---

### 10.75 Audit retention & export

**Trigger:** Admin audit settings.

**Steps:**

1. `GET /admin/audit/retention` — current retention policy config.
2. `POST /admin/audit/retention/purge` — delete entries older than threshold.
3. `GET /admin/audit/export` — download audit log CSV/JSON for compliance.

---

### 10.76 Demo seed / first boot

**Trigger:** `SEED_DEMO_DATA=true` on first `docker compose up`.

**Steps:**

1. Migrations run (`migrate` service).
2. Backend startup calls `seed_demo(session)`.
3. Creates demo users (if configured), sample orders dataset, ontology, pipeline.
4. Idempotent checks prevent duplicate resources.
5. User can immediately run golden path (§10.1) without manual upload.

---

### 10.77 Governance groups & secrets admin

**Groups** (`/governance/groups`):

1. `POST /governance/groups` — create group.
2. `POST /governance/groups/{id}/members` — add user.
3. Group used as ACL subject in ResourceACL grants.

**Secrets** (`/governance/secrets`):

1. `POST /governance/secrets` — store encrypted secret (value never returned).
2. Referenced by connector `secret_ref` fields.
3. `GET /governance/secrets/manager/status` — local vs Vault vs SOPS provider status.
4. Delete: `DELETE /governance/secrets/{id}`.

**Roles & capabilities** (`/governance/roles`, `/governance/capabilities`):

- Admin CRUD via `governance/admin_router.py`; mutations bump permission version.

---

### Workflow completeness summary

| Area | Workflow § | Backend | UI | Known gaps |
|------|-----------|---------|-----|------------|
| Auth & session | 10.2–10.5, 10.52–10.53 | ✅ | ✅ | Simulated SSO in dev |
| Password reset | 10.52 | ✅ | ⚠️ | Email delivery partial |
| Platform kernel | 10.6 | ✅ | ✅ | Dual workspace models |
| Connectors (batch) | 10.7–10.11, 10.57 | ✅ | ✅ | Incremental sync partial |
| Streaming connectors | 10.58 | ⚠️ | ❌ | Poll MVP only |
| Catalog & preview | 10.12 | ✅ | ✅ | — |
| Explore / Contour | 10.13 | ✅ | ✅ | — |
| Quality & freshness | 10.14 | ✅ | ✅ | Build gate partial |
| Dataset versioning | 10.15 | ✅ | ⚠️ | UI thin on some tabs |
| Branching | 10.16–10.17 | ⚠️ | ⚠️ | Destructive merge |
| Permissions & ACL | 10.18 | ✅ | ✅ | Legacy tables remain |
| Access requests | 10.19 | ✅ | ✅ | — |
| Row policies / masks | 10.20–10.21 | ✅ | ✅ | Writeback bypass |
| Markings | 10.22 | ✅ | ✅ | Folder inheritance |
| Export | 10.23, 10.65 | ⚠️ | ⚠️ | Verify download E2E |
| Governed SQL | 10.24–10.26 | ✅ | ✅ | DuckDB file fn audit |
| Saved queries | 10.27 | ✅ | ✅ | — |
| Pipelines | 10.28–10.31, 10.63–10.64 | ✅ | ✅ | Incremental builds |
| Dashboards | 10.32–10.34, 10.70 | ✅ | ✅ | Map widget stub |
| Notebooks | 10.35, 10.56 | ✅ | ✅ | History UI partial |
| Ontology & actions | 10.36–10.38, 10.71, 10.73 | ⚠️ | ⚠️ | Writeback governance |
| Apps | 10.39 | ✅ | ⚠️ | Runtime action UX |
| Code repo & PRs | 10.40–10.41 | ✅ | ⚠️ | PR review partial |
| ML models | 10.42, 10.69 | ✅ | ⚠️ | Predict execution partial |
| Time series | 10.43 | ✅ | ✅ | — |
| AI platform | 10.44–10.45, 10.54–10.55 | ✅ | ✅ | RAG/agents absent |
| Lineage | 10.45 | ✅ | ✅ | Column lineage manual |
| Jobs & schedules | 10.46–10.47, 10.66–10.67 | ✅ | ✅ | — |
| Automation | 10.48 | ✅ | ⚠️ | Limited UI |
| Notifications | 10.49 | ✅ | ✅ | No email |
| Search | 10.50 | ⚠️ | ⚠️ | No FTS |
| Audit | 10.51, 10.75 | ✅ | ✅ | — |
| Media sets | 10.59 | ⚠️ | ❌ | API only |
| Collaboration | 10.60 | ✅ | ⚠️ | No full-page UI |
| Activity | 10.61 | ✅ | ✅ | — |
| Legacy workspace | 10.62 | ✅ | ⚠️ | Migrate to platform |
| Operations | 10.68 | ✅ | ✅ | Metrics dashboards basic |
| Enterprise LDAP | 10.74 | ⚠️ | ❌ | Config hooks |
| Demo seed | 10.76 | ✅ | — | — |
| Governance admin | 10.77 | ✅ | ✅ | — |
| User workflows | 10.72 | ✅ | ⚠️ | Registry in code |

**Total documented workflows: 77** (§10.1–§10.77)

---

## 11. Complete API Surface

All application APIs under **`/api/v1`**. Auth: session cookie (`mf_session`) or Bearer token (if `allow_bearer_auth=true`). System routes: `/health`, `/api/v1/system/health`.

### 11.1 Auth (`/auth`, `/auth/sso`, `/enterprise`, `/auth/tokens`, `/admin/users`)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/auth/register` | Register user |
| POST | `/auth/login` | Login → session/JWT |
| POST | `/auth/refresh` | Refresh session |
| POST | `/auth/logout` | Invalidate session |
| GET | `/auth/me` | Current user + roles |
| POST | `/auth/password-reset/request` | Request reset token |
| POST | `/auth/password-reset/confirm` | Set new password |
| GET | `/auth/sso/login` | OIDC redirect (or stub) |
| GET | `/auth/sso/callback` | OIDC callback |
| GET | `/enterprise/saml/status` | SAML adapter status |
| POST | `/enterprise/saml/test` | Test SAML config |
| GET | `/enterprise/ldap/status` | LDAP adapter status |
| POST | `/enterprise/ldap/sync` | Sync LDAP users/groups |
| GET | `/auth/tokens` | List user's API tokens |
| POST | `/auth/tokens` | Create API token |
| DELETE | `/auth/tokens/{id}` | Revoke token |
| GET | `/admin/users` | List users (admin) |
| POST | `/admin/users` | Create user (admin) |
| POST | `/admin/users/assign-role` | Assign role |
| GET | `/admin/users/sessions` | Active sessions |
| POST | `/admin/users/sessions/{id}/revoke` | Revoke session |
| GET | `/admin/service-accounts` | List service accounts |
| POST | `/admin/service-accounts` | Create service account |
| POST | `/admin/service-accounts/{id}/tokens` | Issue SA token |

### 11.2 Catalog & data (`/catalog`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/catalog/datasets` | List datasets |
| GET | `/catalog/datasets/{id}` | Dataset detail |
| GET | `/catalog/datasets/{id}/preview` | Governed row preview |
| POST | `/catalog/datasets/{id}/explore` | Contour explore steps |
| GET | `/catalog/datasets/{id}/versions` | Version history |
| GET | `/catalog/datasets/{id}/storage-manifests` | Storage manifests |
| POST | `/catalog/datasets/{id}/classifications/confirm` | Confirm PII labels |
| POST | `/catalog/datasets/{id}/versions/{vid}/promote` | Promote version |
| GET | `/catalog/datasets/{id}/versions/diff` | Schema diff |
| GET | `/catalog/datasets/{id}/branches` | List branch transactions |
| POST | `/catalog/datasets/{id}/branches` | Create branch |
| POST | `/catalog/datasets/{id}/branches/{tid}/commit` | Commit branch |
| POST | `/catalog/datasets/{id}/branches/{tid}/merge` | Merge branch |
| GET | `/catalog/datasets/{id}/branches/{tid}/diff` | Branch diff |
| DELETE | `/catalog/datasets/{id}/branches/{tid}` | Abort branch |
| GET | `/catalog/lineage` | Global lineage graph |
| GET/POST/DELETE | `/catalog/datasets/{id}/quality-rules` | Quality rules CRUD |
| POST | `/catalog/datasets/{id}/quality-run` | Run quality checks |
| GET | `/catalog/datasets/{id}/quality-results` | Quality results |
| GET/PUT | `/catalog/datasets/{id}/freshness` | Freshness threshold |

### 11.3 Connectors (`/connectors`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/connectors` | List connectors |
| POST | `/connectors/csv/preview` | Preview CSV schema |
| POST | `/connectors/csv` | Upload CSV |
| POST | `/connectors/parquet` | Upload Parquet |
| POST | `/connectors/postgres/test` | Test Postgres conn |
| POST | `/connectors/postgres` | Register Postgres source |
| POST | `/connectors/rest` | Register REST source |
| POST | `/connectors/{id}/sync` | Trigger sync job |
| GET | `/connectors/{id}/sync-runs` | Sync run history |
| POST | `/connectors/{id}/test` | Test existing connector |
| GET | `/connectors/{id}/test-results` | Test result history |
| GET/POST | `/connectors/streams` | Stream sources |
| GET/POST | `/connectors/streams/{id}/subscriptions` | Subscriptions |
| POST | `/connectors/streams/subscriptions/{id}/checkpoint` | Save watermark |
| POST | `/connectors/streams/subscriptions/{id}/poll` | Poll stream |

### 11.4 Governed query (`/queries`)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/queries/{query_id}/cancel` | Cancel running SQL |

*(SQL execution goes through `/ai/run-sql`, catalog preview, dashboard render — all use `governed_query` service internally.)*

### 11.5 AI (`/ai`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/ai/providers` | List AI providers |
| POST | `/ai/sql` | NL → SQL draft |
| POST | `/ai/run-sql` | Generate + execute SQL |
| POST | `/ai/logic/run` | AIP Logic canvas run |
| GET | `/ai/runs`, `/ai/runs/{id}` | AI run history |
| GET | `/ai/tool-calls` | Tool call audit |
| GET | `/ai/usage` | Usage metrics |
| GET/POST/DELETE | `/ai/prompts` | Prompt template registry |
| POST | `/ai/prompts/preview` | Preview prompt render |
| GET/POST/DELETE | `/ai/evaluations` | Eval suites |
| POST | `/ai/evaluations/{id}/run` | Run eval suite |

### 11.6 Pipelines (`/pipelines`)

| Method | Path | Purpose |
|--------|------|---------|
| GET/POST | `/pipelines` | List / create |
| GET/PATCH/DELETE | `/pipelines/{id}` | Read / update / delete |
| POST | `/pipelines/{id}/preview` | Sample preview |
| POST | `/pipelines/{id}/run` | Materialize build |
| GET | `/pipelines/{id}/nodes/{nid}/schema` | Node output schema |
| GET | `/pipelines/{id}/nodes/{nid}/preview` | Node sample rows |
| POST | `/pipelines/{id}/validate` | Validate graph |
| GET | `/pipelines/_suggest/join` | Join key suggestions |
| POST | `/pipelines/ai-generate` | AI graph draft |

### 11.7 Dashboards (`/dashboards`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/dashboards/widgets` | Widget type registry |
| GET/POST/PUT/DELETE | `/dashboards/saved-queries` | Saved query CRUD |
| GET | `/dashboards/saved-queries/{id}/versions` | Query versions |
| GET/POST | `/dashboards` | List / create |
| GET/PUT/DELETE | `/dashboards/{id}` | CRUD |
| POST | `/dashboards/{id}/publish` | Publish dashboard |
| POST | `/dashboards/{id}/render` | Render all widgets |
| POST | `/dashboards/{id}/components/{cid}/render` | Render one widget |
| POST | `/dashboards/ai-generate` | AI dashboard draft |
| POST/DELETE | `/dashboards/{id}/permissions` | Dashboard ACL |

### 11.8 Notebooks (`/notebooks`)

| Method | Path | Purpose |
|--------|------|---------|
| GET/POST | `/notebooks` | List / create |
| GET/PUT/DELETE | `/notebooks/{id}` | CRUD |
| POST | `/notebooks/{id}/cells` | Add cell |
| PUT/DELETE | `/notebooks/{id}/cells/{cid}` | Edit / delete cell |
| POST | `/notebooks/{id}/reorder` | Reorder cells |
| POST | `/notebooks/{id}/cells/{cid}/run` | Run cell (sandbox job) |

### 11.9 Ontology (`/ontology`, `/admin/ontology`, `/objects`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/ontology/graph` | Ontology graph |
| POST | `/ontology/layout` | Save layout positions |
| GET | `/ontology/objects` | List object types |
| GET | `/ontology/objects/{type}` | Search instances |
| GET | `/ontology/object-types/{type}/detail` | Type schema |
| GET | `/objects/{type}/{id}` | Object instance detail |
| GET | `/objects/{type}/{id}/related/{rel}` | Related objects |
| POST/PUT/DELETE | `/admin/ontology/objects` | Admin object CRUD |
| POST/DELETE | `/admin/ontology/relationships` | Link CRUD |
| POST | `/admin/ontology/import-yaml` | Bulk YAML import |

### 11.10 Actions (`/actions`, `/admin`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/actions` | List actions user can trigger |
| POST | `/actions/trigger` | Execute action + writeback |
| POST | `/actions/preview` | Preview action effect |
| GET | `/actions/runs` | Action run history |
| GET | `/admin/workflows` | Registered workflow keys |
| GET/POST/PATCH/DELETE | `/admin/ontology/actions` | Action admin CRUD |
| POST | `/admin/ontology/actions/grant` | Grant action permission |

### 11.11 Platform kernel (`/platform`)

| Method | Path | Purpose |
|--------|------|---------|
| GET/POST | `/platform/projects` | Projects |
| GET | `/platform/projects/{id}` | Project detail |
| GET/POST/DELETE | `/platform/projects/{id}/access` | Project ACL |
| GET | `/platform/projects/{id}/activity` | Project activity feed |
| POST | `/platform/folders` | Create folder resource |
| GET | `/platform/resources` | List resources |
| GET/PATCH/DELETE | `/platform/resources/{id}` | Read / move / transfer / delete |
| GET | `/platform/trash` | Soft-deleted resources |
| POST | `/platform/resources/{id}/restore` | Restore from trash |
| DELETE | `/platform/trash/purge` | Permanent purge |
| GET/POST | `/platform/resources/{id}/versions` | Resource versions |
| GET | `/platform/resources/{id}/lineage` | Resource lineage |
| GET | `/platform/resources/{id}/impact` | Impact analysis |
| GET | `/platform/resources/{id}/permissions/explain` | Permission explanation |
| POST | `/platform/resources/{id}/access-requests` | Request access |
| GET | `/platform/access-requests` | List requests |
| POST | `/platform/access-requests/{id}/decision` | Approve/deny |
| POST/GET | `/platform/exports` | Export requests |
| POST | `/platform/exports/{id}/generate` | Generate export file |
| GET | `/platform/exports/{id}/download` | Download export |
| GET | `/platform/approvals` | Approval queue |
| POST | `/platform/approvals/{id}/decision` | Approval decision |
| GET/POST | `/platform/branches` | Global branches |
| GET | `/platform/branches/{id}/compare` | Branch compare |
| POST | `/platform/branches/{id}/review` | Submit for review |
| POST | `/platform/branches/{id}/merge` | Merge branch |
| POST | `/platform/branches/{id}/abandon` | Abandon branch |
| GET | `/platform/build-runs/{id}/stream` | Build log SSE |

### 11.12 Applications (`/applications`)

| Method | Path | Purpose |
|--------|------|---------|
| GET/POST | `/applications` | List / create apps |
| GET/PUT | `/applications/{id}` | Read / update |
| POST | `/applications/{id}/publish` | Publish app |
| GET | `/applications/{id}/versions` | Version history |
| GET | `/applications/{id}/published` | Published runtime |
| GET | `/applications/{id}/preview` | Preview runtime |
| GET | `/applications/{id}/lineage` | App lineage |

### 11.13 Code repository (`/code-repo`)

| Method | Path | Purpose |
|--------|------|---------|
| GET/POST | `/code-repo/repositories` | List / create |
| GET | `/code-repo/repositories/{id}` | Repo detail |
| GET/PUT | `/code-repo/repositories/{id}/files/content` | Read / write file |
| POST | `/code-repo/repositories/{id}/folders` | Create folder |
| POST | `/code-repo/run` | Run transform (sandbox) |
| POST | `/code-repo/test` | Run tests (sandbox) |
| GET/POST | `/code-repo/{id}/git/log`, `/commit`, `/diff`, `/branches` | Git ops |
| GET/POST | `/code-repo/{id}/pull-requests` | PR list / create |
| GET | `/code-repo/pull-requests/{id}` | PR detail |
| GET | `/code-repo/pull-requests/{id}/diff` | PR diff |
| POST | `/code-repo/pull-requests/{id}/comments` | PR comment |
| PATCH | `/code-repo/pull-requests/{id}/status` | Merge/close PR |

### 11.14 ML models (`/models`)

| Method | Path | Purpose |
|--------|------|---------|
| GET/POST | `/models` | List / register |
| GET/DELETE | `/models/{id}` | Detail / delete |
| GET | `/models/{id}/detail` | Full detail + versions |
| POST | `/models/{id}/train` | Queue training job |
| GET | `/models/{id}/versions` | List versions |
| POST | `/models/{id}/versions/{vid}/predict-preview` | Predict preview |
| POST | `/models/{id}/versions/{vid}/promote` | Promote version |
| POST | `/models/{id}/rollback` | Rollback to previous |

### 11.15 Jobs & schedules (`/jobs`, `/admin/schedules`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/jobs` | List jobs |
| GET | `/jobs/_meta/job-types` | Job type metadata |
| GET | `/jobs/{id}` | Job detail + logs |
| GET | `/jobs/{id}/stream` | Job SSE stream |
| POST | `/jobs/{id}/cancel` | Cancel job |
| POST | `/jobs/{id}/retry` | Retry failed job |
| GET/POST/PUT/DELETE | `/admin/schedules` | Schedule CRUD |
| POST | `/admin/schedules/{id}/run-now` | Manual schedule trigger |

### 11.16 Governance (`/governance`, `/governance` admin prefix)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/governance/metrics` | Usage/compute metrics |
| GET/POST | `/governance/groups` | Groups CRUD |
| GET/POST/DELETE | `/governance/groups/{id}/members` | Group membership |
| GET/POST | `/governance/markings` | Security markings |
| GET/POST/DELETE | `/governance/markings/eligibility` | Marking eligibility |
| GET/POST/DELETE | `/governance/roles` | Roles (admin) |
| GET | `/governance/capabilities` | Capability catalog |
| GET | `/governance/capabilities/grants` | Capability grant summary |
| GET/POST/DELETE | `/governance/row-policies` | Row policies |
| GET/POST/DELETE | `/governance/column-masks` | Column masks |
| GET/POST/DELETE | `/governance/secrets` | Encrypted secrets |
| GET | `/governance/secrets/manager/status` | Secret manager status |
| GET | `/governance/policies/summary` | Policy summary dashboard |

### 11.17 Permissions (legacy) (`/admin/permissions`)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/admin/permissions/grant` | Legacy grant (migrating to ResourceACL) |
| DELETE | `/admin/permissions/revoke` | Legacy revoke |

### 11.18 Other modules

| Prefix | Key endpoints |
|--------|---------------|
| `/activity` | `/recents`, `/favorites`, `/track`, `/favorites/toggle` |
| `/audit` | `GET /admin/audit`, `/retention`, `/export` |
| `/automation/monitors` | CRUD + `/evaluate` + `/runs` |
| `/collaboration` | `/resources/{id}/comments`, `/comments/{id}/resolve` |
| `/explore` | `GET /explore` — platform search |
| `/media-sets` | CRUD + version upload/download |
| `/notifications` | list, summary, SSE stream, read |
| `/settings` | `GET/PUT /settings/ai` |
| `/timeseries` | `POST /timeseries/analyze` |
| `/workspace` | items, folders, roots, move, repair, permissions |
| `/operations` | workers, queues, caches, storage, metrics, hardening, logs |

**Interactive docs:** `http://localhost:8000/docs` (OpenAPI) when backend is running.

---

## 12. Frontend Structure & Navigation

### 12.1 Platform shell (`frontend/app/(platform)/`)

The unified UI uses `AppShell` with sidebar navigation (see `components/layout/AppShell.tsx`).

**Sidebar groups:**

| Group | Primary routes |
|-------|----------------|
| Workspace | `/workspace`, `/workspace/trash`, `/data/catalog`, `/data/sources`, `/data/lineage` |
| Build | `/build/pipelines`, `/build/runs`, `/workspace/branches`, `/ontology/manager`, `/ontology/explorer`, `/apps/builder`, `/apps/dashboards` |
| Analyze & Develop | `/analytics/sql`, `/analytics/explore`, `/analytics/quiver`, `/develop/notebooks`, `/develop/code`, `/develop/models`, `/ai/assistant` |
| Govern & Operate | `/governance/users`, `/governance/access-requests`, `/governance/audit`, `/operations/jobs`, `/operations/schedules`, `/operations/health`, `/settings/ai` |

**Global shell features:** Command palette (⌘K), branch selector, branch taskbar, notification bell (SSE), health indicator, breadcrumbs, theme toggle.

### 12.2 Complete platform page map (105 pages)

Every route under `frontend/app/(platform)/`:

| Route | Purpose | Backend APIs used |
|-------|---------|-------------------|
| `/` | Platform home redirect | — |
| **Workspace** | | |
| `/workspace` | Workspace home, recents | `/activity/recents` |
| `/workspace/trash` | Soft-deleted resources | `/platform/trash`, restore |
| `/workspace/branches` | Global branch list | `/platform/branches` |
| `/workspace/projects` | Project list | `/platform/projects` |
| `/workspace/projects/[id]` | Project detail | `/platform/projects/{id}` |
| `/workspace/projects/[id]/access` | Project ACL | `/platform/projects/{id}/access` |
| `/workspace/projects/[id]/activity` | Project activity | `/platform/projects/{id}/activity` |
| `/workspace/projects/[id]/branches` | Project branches | `/platform/branches` |
| `/workspace/spaces` | Spaces (organizational) | platform resources |
| **Data** | | |
| `/data/catalog` | Dataset catalog | `/catalog/datasets` |
| `/data/sources` | Connector list | `/connectors` |
| `/data/sources/new` | New connector wizard | `/connectors/csv`, postgres, rest, parquet |
| `/data/datasets/[id]` | Dataset detail (tabs) | `/catalog/datasets/{id}` |
| `/data/datasets/[id]/explore` | Contour explore | `/catalog/datasets/{id}/explore` |
| `/data/datasets/[id]/branches` | Dataset branching | branch APIs |
| `/data/lineage` | Global lineage graph | `/catalog/lineage` |
| `/data/lineage/[resourceId]` | Resource lineage | `/platform/resources/{id}/lineage` |
| **Build** | | |
| `/build/pipelines` | Pipeline list | `/pipelines` |
| `/build/pipelines/new` | New pipeline | `POST /pipelines` |
| `/build/pipelines/[id]` | Pipeline overview | `/pipelines/{id}` |
| `/build/pipelines/[id]/graph` | Pipeline canvas | `PATCH /pipelines/{id}` |
| `/build/pipelines/[id]/preview` | Preview panel | `/pipelines/{id}/preview` |
| `/build/pipelines/[id]/builds` | Build history | build runs |
| `/build/pipelines/[id]/expectations` | Quality expectations | pipeline metadata |
| `/build/pipelines/[id]/lineage` | Pipeline lineage | lineage APIs |
| `/build/pipelines/[id]/branches` | Pipeline branches | branch context |
| `/build/pipelines/[id]/schedules` | Pipeline schedules | `/admin/schedules` |
| `/build/runs` | All build runs | `/platform/build-runs`, jobs |
| **Ontology** | | |
| `/ontology/manager` | Ontology graph editor | `/ontology/graph`, `/layout` |
| `/ontology/explorer` | Object explorer | `/ontology/objects` |
| `/ontology/object-types` | Object type admin | admin ontology APIs |
| `/ontology/link-types` | Link type admin | admin relationships |
| `/ontology/actions` | Action definitions | `/admin/ontology/actions` |
| `/ontology/import` | YAML import | `/admin/ontology/import-yaml` |
| `/ontology/functions` | Functions on objects (stub) | — |
| `/ontology/objects/[type]/[id]` | Object detail + actions | `/objects/{type}/{id}` |
| **Apps** | | |
| `/apps/builder` | App list | `/applications` |
| `/apps/builder/[appId]` | App editor | `/applications/{id}` |
| `/apps/builder/[appId]/preview` | App preview | `/applications/{id}/preview` |
| `/apps/builder/[appId]/publish` | Publish flow | `/applications/{id}/publish` |
| `/apps/published/[appId]` | Published runtime | `/applications/{id}/published` |
| `/apps/dashboards` | Dashboard list | `/dashboards` |
| `/apps/dashboards/new` | New dashboard | `POST /dashboards` |
| `/apps/dashboards/[id]` | Dashboard viewer | `/dashboards/{id}/render` |
| `/apps/dashboards/[id]/edit` | Dashboard editor | `PUT /dashboards/{id}` |
| `/apps/dashboards/[id]/preview` | Dashboard preview | render API |
| `/apps/dashboards/[id]/publish` | Publish dashboard | `/dashboards/{id}/publish` |
| **Analytics & Develop** | | |
| `/analytics/sql` | SQL + AI workspace | `/ai/sql`, `/ai/run-sql` |
| `/analytics/explore` | Platform search | `/explore` |
| `/analytics/quiver` | Time series | `/timeseries/analyze` |
| `/analytics/timeseries` | Timeseries alt route | same |
| `/develop/notebooks` | Notebook list | `/notebooks` |
| `/develop/notebooks/new` | Create notebook | `POST /notebooks` |
| `/develop/notebooks/[id]` | Notebook editor | cell CRUD + run |
| `/develop/code` | Code repo list | `/code-repo/repositories` |
| `/develop/code/[id]` | Code editor + Git | code-repo APIs |
| `/develop/models` | ML registry | `/models` |
| **AI** | | |
| `/ai/assistant` | AI chat assistant | AI gateway |
| `/ai/logic` | AIP Logic canvas | `/ai/logic/run` |
| `/ai/evaluations` | AI eval suites | `/ai/evaluations` |
| `/ai/usage` | AI usage metrics | `/ai/usage` |
| `/ai/prompts` | Prompt registry | `/ai/prompts` |
| `/ai/tool-calls` | Tool call audit | `/ai/tool-calls` |
| **Governance** | | |
| `/governance` | Governance overview | `/governance/metrics` |
| `/governance/users` | User admin | `/admin/users` |
| `/governance/groups` | Groups | `/governance/groups` |
| `/governance/roles` | Roles | `/governance/roles` |
| `/governance/capabilities` | Capability catalog | `/governance/capabilities` |
| `/governance/markings` | Security markings | `/governance/markings` |
| `/governance/row-policies` | Row policies | `/governance/row-policies` |
| `/governance/column-masks` | Column masks | `/governance/column-masks` |
| `/governance/secrets` | Secrets vault | `/governance/secrets` |
| `/governance/policies` | Policy summary | `/governance/policies/summary` |
| `/governance/access-requests` | Access queue | `/platform/access-requests` |
| `/governance/approvals` | Approval queue | `/platform/approvals` |
| `/governance/exports` | Export requests | `/platform/exports` |
| `/governance/audit` | Audit log | `/admin/audit` |
| **Operations** | | |
| `/operations/jobs` | Job list | `/jobs` |
| `/operations/jobs/[jobId]` | Job detail + stream | `/jobs/{id}`, SSE |
| `/operations/schedules` | Schedules | `/admin/schedules` |
| `/operations/health` | System health | `/system/health` |
| `/operations/workers` | Worker status | `/operations/workers` |
| `/operations/queues` | Queue depths | `/operations/queues` |
| `/operations/caches` | Cache stats + flush | `/operations/caches` |
| `/operations/storage` | Object storage usage | `/operations/storage` |
| `/operations/metrics` | Platform metrics | `/operations/metrics` |
| `/operations/logs` | Log viewer | `/operations/logs` |
| **Settings & other** | | |
| `/settings` | Settings home | — |
| `/settings/ai` | AI provider prefs | `/settings/ai` |
| `/notifications` | Notification inbox | `/notifications` |
| `/help` | In-app help guide | — |
| `[...path]` catch-alls | Fallback panels | varies |

### 12.3 Legacy routes (still active)

These exist outside `(platform)/` with redirects or wrappers:

```text
/login                    — auth (outside platform shell)
/catalog/*                — redirects to /data/catalog/*
/pipelines/*              — redirects to /build/pipelines/*
/dashboards/*             — redirects to /apps/dashboards/*
/sql/*                    — redirects to /analytics/sql/*
/notebooks/*              — redirects to /develop/notebooks/*
/code-repo/*              — redirects to /develop/code/*
/admin/*                  — partial redirects to /governance/*, /operations/*
/object-explorer/*        — redirects to /ontology/explorer
/quiver/*                 — redirects to /analytics/quiver
/aip-logic/*              — redirects to /ai/logic
```

**Gap:** Not all legacy pages use the new design system components (`FoundryPrimitives` → platform design system migration incomplete).

### 12.4 Shared components & libs

| Path | Role |
|------|------|
| `frontend/lib/api.ts` | Central API client, auth, error handling |
| `frontend/lib/polling.ts` | Job/build status polling |
| `frontend/lib/pipelines.ts` | Pipeline graph helpers |
| `frontend/lib/workspace.ts` | Workspace navigation helpers |
| `frontend/components/layout/AppShell.tsx` | Main shell |
| `frontend/components/layout/CommandPalette.tsx` | ⌘K search |
| `frontend/components/platform/BranchSelector.tsx` | Branch context |
| `frontend/components/platform/ResourceComments.tsx` | Collaboration |
| `frontend/components/pipelines/*` | Pipeline builder |
| `frontend/components/dashboards/*` | Dashboard builder |
| `frontend/components/ontology/*` | Object explorer widgets |
| `frontend/contexts/DashboardVariables.tsx` | Workshop-style dashboard variables |

### 12.5 E2E tests (Playwright)

| Spec | Flow tested |
|------|-------------|
| `login.spec.ts` | Login |
| `permission-denied.spec.ts` | ACL denial UX |
| `dashboard-publish.spec.ts` | Dashboard publish |
| `app-publish.spec.ts` | App publish |
| `branch-and-ai-governance.spec.ts` | Branch + AI policy |
| `lineage-impact.spec.ts` | Lineage impact analysis |

---

## 13. Background Jobs & Workers

### Celery task types

| Task | File | Purpose |
|------|------|---------|
| `run_pipeline` | `jobs/tasks/run_pipeline.py` | Pipeline materialization |
| `notebook_cell` | `jobs/tasks/notebook_cell.py` | Sandbox cell execution |
| `code_transform` | `jobs/tasks/code_transform.py` | Code repo transforms |
| `code_test` | `jobs/tasks/code_test.py` | Code repo test runs |
| `csv_profile` | `jobs/tasks/csv_profile.py` | Dataset profiling |
| `postgres_discover` | `jobs/tasks/postgres_discover.py` | Postgres schema discovery |
| `dashboard_cache_refresh` | `jobs/tasks/dashboard_cache_refresh.py` | Warm dashboard render cache |
| `run_workflow` | `jobs/tasks/run_workflow.py` | User workflow execution |
| `ontology_webhook` | `jobs/tasks/ontology_webhook.py` | Webhook dispatch |
| `model_train` | `jobs/tasks/model_train.py` | ML training |
| `scheduled_report` | `jobs/tasks/scheduled_report.py` | Scheduled reports |

### Job states

Canonical state machine tested in `test_job_state_machine.py`: `queued` → `running` → `succeeded` / `failed` / `canceled`

### Celery task → workflow cross-reference

| Job type string | Task module | Workflow |
|-----------------|-------------|----------|
| `pipeline_run` | `run_pipeline.py` | §10.30 |
| `notebook_cell` | `notebook_cell.py` | §10.35 |
| `code_transform` | `code_transform.py` | §10.40 |
| `code_test` | `code_test.py` | §10.40 |
| `csv_profile` | `csv_profile.py` | §10.7 |
| `postgres_discover` | `postgres_discover.py` | §10.9 |
| `dashboard_cache_refresh` | `dashboard_cache_refresh.py` | §10.33 |
| `workflow_run` | `run_workflow.py` | §10.72 |
| `ontology_webhook` | `ontology_webhook.py` | §10.73 |
| `model_train` | `model_train.py` | §10.42 |
| `scheduled_report` | `scheduled_report.py` | §10.67 |

Beat scheduler loads persisted schedules from DB on worker startup (`jobs/scheduler.py`).

## 14. AI System

### Provider gateway (`ai/gateway.py`)

Routes requests to Ollama, Gemini, or custom OpenAI-compatible endpoint based on user settings and request.

### AI policy enforcement

Before sending data to a provider:

1. Check dataset `ai_policy` field
2. Check user has `use_with_ai` capability
3. Redact/limit schema and row samples per policy

### AI features

| Feature | Description |
|---------|-------------|
| SQL generation | Natural language → SQL draft (validated before run) |
| Python generation | Notebook cell assistance |
| Pipeline generation | Graph draft from prompt |
| Dashboard generation | Widget layout draft |
| AIP Logic | Multi-step canvas: LLM + SQL + templates |
| Evaluations | Deterministic eval runs for leakage tests |

**Rule:** AI output is never trusted — always validated server-side.

---

## 15. Testing & Quality Signals

### Backend tests

48 test modules, 300+ test cases. Full inventory:

| Test file | Area covered |
|-----------|--------------|
| `test_sql_validator.py` | SQL AST safety |
| `test_governed_query_security.py` | Governed query rewrite |
| `test_row_policies.py` | Row policy DSL |
| `test_masking.py`, `test_masking_pushdown.py` | Column masks + pushdown |
| `test_resource_authorization.py` | ResourceACL |
| `test_route_authorization_matrix.py` | Route auth coverage |
| `test_engine_routing.py` | Postgres/DuckDB/Trino routing |
| `test_duckdb_runner.py`, `test_duckdb_branch_routing.py` | DuckDB engine |
| `test_cross_source.py` | Cross-engine queries |
| `test_spark_trino_runners.py` | Trino/Spark |
| `test_pipelines_compiler.py`, `test_pipeline_governance.py` | Pipelines |
| `test_dashboard_validation.py` | Dashboard defs |
| `test_sandbox_security.py`, `test_code_sandbox_jobs.py` | Sandbox isolation |
| `test_transform_sandbox_dispatch.py` | Code transform jobs |
| `test_coderepo_notebook_acl.py` | Code repo + notebook ACL |
| `test_action_registry.py` | Actions/workflows |
| `test_yaml_import.py` | Ontology YAML |
| `test_sandbox_ontology.py` | Ontology sandbox |
| `test_ai_policy.py`, `test_ai_python_prompt.py`, `test_ai_pages.py` | AI |
| `test_aip_logic.py` | AIP Logic |
| `test_app_versioning.py`, `test_project_ux.py` | Platform kernel |
| `test_auth_governance.py` | Auth hardening |
| `test_governance_admin.py` | Governance admin CRUD |
| `test_operations_api.py` | Operations console |
| `test_ml_app_acl.py` | ML + app ACL |
| `test_dataset_quality.py`, `test_dataset_transform.py` | Data quality |
| `test_cache_key.py`, `test_render_cache_key.py` | Cache keys |
| `test_secrets.py` | Fernet encryption |
| `test_identifiers.py` | SQL identifier safety |
| `test_job_state_machine.py` | Job states |
| `test_schedule_validation.py` | Schedules |
| `test_seed_demo.py` | Demo seed |
| `test_timeseries.py` | Quiver |
| `test_explore_router.py` | Platform search |
| `test_openapi_contract.py` | OpenAPI schema |
| `test_postgres_connector.py` | Postgres connector |
| `test_code_transform.py` | Code transforms |
| `test_sandbox_result_parser.py` | Sandbox output parsing |
| `test_integration_stack.py` | Full Docker stack (optional) |

**Run tests:**

```bash
cd backend && pytest -q
# or
make test
```

### Frontend tests

- Component tests: `frontend/components/__tests__/`
- Lib tests: `frontend/lib/__tests__/`
- E2E (Playwright): 6 specs in `frontend/e2e/`

```bash
cd frontend && pnpm lint && pnpm build
```

### What tests do NOT cover well

- Full browser E2E across all product areas
- Concurrent multi-user editing
- Load/stress testing
- Sandbox escape attempts in CI
- All dialect-specific SQL edge cases

---

## 16. Known Gaps, Risks & Technical Debt

### Critical / high priority

| Issue | Detail | Status |
|-------|--------|--------|
| Branch merge is destructive | Merge = DELETE target + INSERT from branch; parent changes lost silently | ❌ Open |
| Writeback governance gaps | Ontology writeback may skip row policies/masks on some paths | ⚠️ Partial |
| DuckDB file read functions | User SQL could potentially use `read_parquet` with platform S3 creds | ⚠️ Needs audit |
| Docker socket on worker | Worker compromise → host compromise risk | ❌ Open (infra) |
| Legacy permission tables | Dual system with ResourceACL + old tables | ⚠️ Migration in progress |
| Marking inheritance | Markings on folders may not propagate to children | ⚠️ Partial |

### Medium priority

| Issue | Detail |
|-------|--------|
| Cross-engine blending | DuckDB postgres_scanner helps; not all combinations tested |
| Object Sets | Saved filterable object sets — major Foundry gap |
| Functions on Objects | Derived properties — stub only |
| Indexed search | Substring scan, not Postgres FTS or OpenSearch |
| Export downloads | Approval flow exists; governed file generation incomplete |
| Incremental builds | Partition/watermark model partial |
| Column-level lineage | Manual capture only; no SQL parser lineage |
| Frontend migration | Legacy routes still coexist with platform shell |
| Permission-aware nav | Sidebar shows all links regardless of capabilities |
| Map widget | Declared in registry but not implemented |

### Lower priority / out of scope

- Streaming pipelines (Kafka)
- Fusion spreadsheets, Notepad, Marketplace
- Cipher field encryption
- Resource comments @mentions
- Full SAML/LDAP group sync

### Development-only defaults (NOT production-ready)

```text
Default admin password: admin
Default JWT secret: change-me-in-production
Default ENCRYPTION_KEY: dev-secret-key-change-me-in-prod-32chars
Default MinIO credentials: minioadmin
JWT in localStorage (when bearer auth enabled)
Simulated SSO when OIDC not configured
Worker Docker socket mount
```

Production mode enforces hardening via `require_production_hardening=true` in config.

---

## 17. Recommended Next Development Steps

Based on current codebase state, recommended priority order for your reviewer:

### Phase 0 — Security & correctness (do first)

1. **Fix branch merge** — diff-based merge with conflict detection; never silent data loss
2. **Harden ontology writeback** — apply row policies + column masks to read/write paths
3. **Audit DuckDB user SQL** — block or scope `read_parquet`/`read_csv` table functions
4. **Complete ResourceACL migration** — retire legacy permission tables entirely
5. **Marking inheritance** — walk parent chain like ACL inheritance does

### Phase 1 — Platform coherence

6. **Route all data paths through governed_query** — audit legacy catalog/dashboard paths
7. **Immutable dataset versions everywhere** — preview, SQL cache keys, build inputs/outputs
8. **Branch review/merge UI** — backend APIs exist; frontend workflow incomplete
9. **Permission-aware navigation** — hide/disable UI actions user cannot perform

### Phase 2 — Foundry parity gaps

10. **Object Sets** — unlocks app variables and cross-filtering
11. **Incremental pipeline builds** — partitions, watermarks, backfill
12. **Governed export file generation** — complete the export approval → download flow
13. **Indexed platform search** — Postgres FTS minimum
14. **Column-level lineage** — sqlglot-based parser

### Phase 3 — Infrastructure & ops

15. **Sandbox host isolation** — remove Docker socket from worker or use rootless/gVisor
16. **Structured logging + metrics dashboards**
17. **CI: migration smoke, authorization matrix, frontend build**
18. **Backup/restore drills**

### Phase 4 — Product polish

19. **Migrate all legacy frontend routes to `(platform)` shell**
20. **AI sidecars on all builders** + shared draft diff viewer
21. **Notification delivery** (email) for approvals, build failures
22. **E2E test suite** for golden path

---

## 18. Local Development Guide

### Quick start (full stack)

```bash
cp .env.example .env
docker compose up -d --build

# Optional local AI
docker compose --profile ai up -d ollama ollama-init
```

**URLs:**

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| Backend health | http://localhost:8000/health |
| System health | http://localhost:8000/api/v1/system/health |
| API docs | http://localhost:8000/docs |
| MinIO console | http://localhost:9001 |
| Trino | http://localhost:8080 |

**Default login:** `admin@mini.local` / `admin`

### Local backend only

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

### Local frontend only

```bash
cd frontend
cp .env.local.example .env.local
pnpm install
pnpm dev
```

### Build sandbox image

```bash
make build-sandbox
```

### Seed demo data

```bash
make seed-demo
# or set SEED_DEMO_DATA=true in .env
```

### Smoke test checklist

1. Upload CSV → appears in catalog
2. Preview dataset → masked columns if configured
3. AI SQL → generate → run → results
4. Try `DELETE FROM ...` → rejected by validator
5. Create pipeline → preview → run → output dataset
6. View lineage graph
7. Check audit log for events

---

## 19. Key Files to Inspect First

If reviewing with limited time, read these files in order:

| Priority | File | Why |
|----------|------|-----|
| 1 | `docker-compose.yml` | Full runtime topology |
| 2 | `backend/app/main.py` | Startup + router registration |
| 3 | `backend/app/config.py` | All configuration + hardening flags |
| 4 | `backend/app/platform/models.py` | Platform kernel schema |
| 5 | `backend/app/permissions/enforcement.py` | Authorization logic |
| 6 | `backend/app/governed_query/service.py` | Central SQL enforcement |
| 7 | `backend/app/execution/sql_validator.py` | SQL safety rules |
| 8 | `backend/app/pipelines/compiler.py` | Pipeline execution logic |
| 9 | `backend/app/notebooks/sandbox.py` | Python isolation |
| 10 | `backend/app/data/branch_service.py` | Branch merge behavior |
| 11 | `backend/app/ontology/writeback.py` | Action side effects |
| 12 | `frontend/lib/api.ts` | Frontend auth + API |
| 13 | `frontend/components/layout/AppShell.tsx` | Navigation shell |
| 14 | `backend/tests/` | Automated safety coverage |

---

## 20. Related Documentation

| File | Contents |
|------|----------|
| `README.md` | Original MVP quick start (outdated feature list) |
| `README_mini_foundry.md` | Original full product specification |
| `SYSTEM_OVERVIEW_FOR_REVIEW.md` | Detailed technical review document |
| `MINI_FOUNDRY_FINAL_README.md` | Architecture review + development checklist |
| `README_REMAINING_WORK.md` | Open gaps audit (June 2026) — some items since fixed |
| `HANDOFF_PARITY_ROADMAP.md` | Phase-by-phase parity implementation notes |
| `palantir_parity_audit.md` | Feature parity comparison |

**Note:** Older docs may describe intended future work or issues already fixed. This file (`README_DEVELOPER_EVALUATION.md`) reflects the best current snapshot for evaluation purposes. Cross-check critical security claims against the live code in `governed_query/` and `permissions/`.

---

## 21. Complete Coverage Matrix

This matrix confirms every backend router module and major frontend area is documented in this file. If a row is missing from §9–§12, it is a documentation gap to fix.

### 21.1 Backend router → documentation map

| Router module | API § | Workflow § | Feature § |
|---------------|-------|------------|-----------|
| `auth/router.py` | 11.1 | 10.2, 10.3, 10.52 | 8 |
| `auth/sso.py` | 11.1 | 10.4 | 8 |
| `auth/enterprise_router.py` | 11.1 | 10.74 | 9.22 |
| `auth/admin_router.py` | 11.1 | 10.53 | 9.12 |
| `auth/token_router.py` | 11.1 | 10.5 | 8 |
| `data/router.py` | 11.2 | 10.12–10.16 | 9.2 |
| `connectors/router.py` | 11.3 | 10.7–10.11, 10.57–10.58 | 9.1 |
| `governed_query/router.py` | 11.4 | 10.26 | 8, 9.3 |
| `ai/router.py` | 11.5 | 10.25, 10.44–10.45, 10.54–10.56 | 9.15, 14 |
| `pipelines/router.py` | 11.6 | 10.28–10.31, 10.63–10.64 | 9.4 |
| `dashboards/router.py` | 11.7 | 10.32–10.34, 10.70 | 9.5 |
| `notebooks/router.py` | 11.8 | 10.35, 10.56 | 9.6 |
| `ontology/router.py` | 11.9 | 10.36–10.37, 10.71 | 9.7 |
| `actions/router.py` | 11.10 | 10.38, 10.72 | 9.7 |
| `platform/router.py` | 11.11 | 10.6, 10.17, 10.19, 10.23, 10.65 | 6 |
| `applications/router.py` | 11.12 | 10.39 | 9.8 |
| `code_repo/router.py` | 11.13 | 10.40–10.41 | 9.9 |
| `ml/router.py` | 11.14 | 10.42, 10.69 | 9.10 |
| `jobs/router.py` | 11.15 | 10.46–10.47, 10.66–10.67 | 13 |
| `governance/router.py` | 11.16 | 10.22, 10.77 | 9.12 |
| `governance/admin_router.py` | 11.16 | 10.20–10.21, 10.77 | 9.12 |
| `permissions/router.py` | 11.17 | 10.18 | 8 |
| `audit/router.py` | 11.18 | 10.51, 10.75 | 9.12 |
| `activity/router.py` | 11.18 | 10.61 | 9.18 |
| `automation/router.py` | 11.18 | 10.48 | 9.14 |
| `collaboration/router.py` | 11.18 | 10.60 | 9.17 |
| `explore/router.py` | 11.18 | 10.50 | 9.3 |
| `media/router.py` | 11.18 | 10.59 | 9.16 |
| `notifications/router.py` | 11.18 | 10.49 | 9.14 |
| `settings/router.py` | 11.18 | 10.54 | 9.15 |
| `timeseries/router.py` | 11.18 | 10.43 | 9.11 |
| `workspace/router.py` | 11.18 | 10.62 | 9.19 |
| `operations/router.py` | 11.18 | 10.68 | 9.21 |

**All 28 backend routers: documented ✅**

### 21.2 Celery tasks → workflow map

| Task | Workflow § | Triggered by |
|------|------------|--------------|
| `csv_profile` | 10.7 | CSV upload completes |
| `postgres_discover` | 10.9 | Postgres source registration |
| `run_pipeline` | 10.30 | Pipeline Run button |
| `notebook_cell` | 10.35 | Notebook cell Run |
| `code_transform` | 10.40 | Code repo Run transform |
| `code_test` | 10.40 | Code repo Run tests |
| `dashboard_cache_refresh` | 10.33 | Schedule or manual warm |
| `run_workflow` | 10.72 | Action/automation workflow key |
| `ontology_webhook` | 10.73 | Post-writeback webhook |
| `model_train` | 10.42 | ML Train button |
| `scheduled_report` | 10.67 | Beat schedule |

**All 11 Celery tasks: documented ✅**

### 21.3 Database tables → module map

| Table group | Key tables | Module |
|-------------|------------|--------|
| Auth | `users`, `roles`, `user_roles`, `sessions` | `auth/models.py` |
| Platform kernel | `projects`, `resources`, `resource_versions`, `resource_acl`, `resource_access_requests`, `branches`, `build_runs`, `lineage_edges`, `export_requests`, `approvals` | `platform/models.py` |
| Catalog | `data_sources`, `datasets`, `dataset_columns`, `dataset_profiles`, `branch_transactions`, `quality_rules`, `quality_results` | `data/models.py` |
| Permissions | `row_policies`, `column_permissions`, `secrets`, `permission_versions`, `resource_markings` | `permissions/models.py` |
| Governance | `usage_metrics`, groups, markings eligibility | `governance/models.py` |
| Pipelines | `pipelines`, `pipeline_nodes`, `pipeline_edges` | `pipelines/models.py` |
| Dashboards | `dashboards`, `dashboard_components`, `saved_queries` | `dashboards/models.py` |
| Notebooks | `notebooks`, `notebook_cells` | `notebooks/models.py` |
| Ontology | `ontology_objects`, `ontology_relationships`, `ontology_actions`, `ontology_edits`, `ontology_layouts` | `ontology/models.py` |
| Jobs | `jobs`, `schedules` | `jobs/models.py` |
| AI | `ai_runs`, `ai_tool_calls`, prompt templates, evaluations | `ai/models.py` |
| ML | `ml_models`, `ml_model_versions` | `ml/models.py` |
| Code repo | `code_repositories`, `pull_requests` | `code_repo/models.py` |
| Apps | `applications`, app versions | `applications/models.py` |
| Notifications | `notifications` | `notifications/models.py` |
| Automation | `automation_monitors`, `automation_monitor_runs` | `automation/models.py` |
| Collaboration | `resource_comments` | `collaboration/models.py` |
| Activity | `resource_activity` | `activity/models.py` |
| Media | `media_sets`, `media_set_versions` | `media/models.py` |
| Audit | `audit_logs` | `audit/models.py` |
| Connectors | `sync_runs`, `connector_test_results`, stream tables | `connectors/models.py` |
| Workspace (legacy) | `workspace_items`, `workspace_permissions` | `workspace/models.py` |
| Settings | `user_settings` | `settings/models.py` |

**33 Alembic migrations (0001–0033): summarized in §7**

### 21.4 Intentionally out of scope (not in codebase)

These Foundry products have **no implementation** — documented as gaps, not omissions:

| Foundry product | Status |
|-----------------|--------|
| Fusion (spreadsheets) | Not started |
| Notepad / Reports | Not started |
| Marketplace / DevOps packaging | Not started |
| Cipher (field encryption) | Not started |
| Full Kafka streaming pipelines | API stub only |
| RAG / vector DB / AI agents | Not started |
| Object Sets (saved filterable sets) | Not started |
| Functions on Objects execution | Stub page only |

### 21.5 Documentation completeness checklist

| Document section | Covers |
|------------------|--------|
| §1–§2 | Product purpose, maturity, scope |
| §3–§4 | Stack, architecture, Docker topology |
| §5 | Full repo + backend module map |
| §6 | Platform kernel (resources, ACL, capabilities) |
| §7 | 33 migrations |
| §8 | Security model (auth, SQL, sandbox, audit) |
| §9.1–§9.24 | All 24 feature areas including media, collaboration, streaming, ops |
| §10.1–§10.77 | **77 step-by-step workflows** |
| §11.1–§11.18 | **Complete API inventory** (~200+ endpoints) |
| §12.1–§12.5 | Shell, **105 platform pages**, legacy routes, components, E2E |
| §13 | Celery tasks + job states |
| §14 | AI system detail |
| §15 | Tests (~48 modules, 6 E2E) |
| §16–§17 | Gaps + recommended next steps |
| §18–§19 | Local dev + key files |
| §21 | Coverage matrix (this section) |

---

Use this checklist when assessing the project:

### Architecture
- [ ] Does the platform kernel (resources, ACL, versions) make sense as the unifying model?
- [ ] Are module boundaries clear and maintainable?
- [ ] Is long-running work consistently delegated to Celery?

### Security
- [ ] Are all data-returning routes using governed_query or equivalent enforcement?
- [ ] Is sandbox isolation acceptable for the deployment model?
- [ ] Are default secrets rotated before any real deployment?
- [ ] Is branch merge safe for production data?

### Product
- [ ] Can a user complete the golden path end-to-end?
- [ ] Are the biggest Foundry gaps (Object Sets, incremental builds, search) acceptable for v1?
- [ ] Is the UI coherent or still fragmented between legacy and platform routes?

### Engineering
- [ ] Can a clean clone run with `docker compose up -d --build`?
- [ ] Do migrations apply cleanly from empty DB?
- [ ] Is test coverage sufficient for governance-critical paths?
- [ ] Is there a credible path to production hardening?

### Recommendation template

After review, document:

1. **Go / no-go** for the intended use case (internal tool, demo, production)
2. **Top 5 fixes** before any real users touch data
3. **Top 5 features** that unlock the most product value
4. **Estimated effort** per phase (rough t-shirt sizes)
5. **Architectural decisions** that should not be revisited vs. ones that need redesign

---

*This document was generated to support external evaluation of Mini Foundry. For questions about specific modules, start with the key files in §19 and the related docs in §20.*
