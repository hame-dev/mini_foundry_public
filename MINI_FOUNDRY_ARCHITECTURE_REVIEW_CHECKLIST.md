# Mini Foundry Architecture Review Checklist

**Role:** Palantir Foundry-style Solution Architect  
**Source Reviewed:** `README_DEVELOPER_EVALUATION.md`  
**Review Purpose:** Evaluate whether the current Mini Foundry system structure is correct and suitable to become a mini Palantir Foundry-style platform.

---

## Implementation Status — Phase 0 (Security & Correctness), updated 2026-06-20

A reconciliation pass against the actual codebase found **most of Phase 0 was already
implemented** (the checklist below was stale). The remaining Phase 0 security gaps were
closed in this pass. Legend used throughout: `[x]` done, with the proving/changed file in
italics. Items left `[ ]` are genuinely unstarted (Phases 1–5, out of scope for this pass).

**Closed in this pass (2026-06-20):**
- Ontology writeback now requires `writeback`/`edit` on the *target dataset* (separate from the
  action capability) and blocks writes to masked/hidden columns — *`backend/app/ontology/writeback.py`,
  `backend/app/actions/execution.py`*; tests *`backend/tests/test_writeback_governance.py`*.
- ResourceACL is the only runtime enforcement path — the 4 remaining legacy
  `effective_permission` (DatasetPermission) call sites were converted — *`backend/app/pipelines/service.py`,
  `pipelines/ai.py`, `ml/router.py`, `dashboards/ai_generate.py`*; legacy path marked deprecated in
  *`backend/app/permissions/enforcement.py`*.
- Sandbox Docker isolation is now configurable (`SANDBOX_DOCKER_HOST` + `SANDBOX_RUNTIME`/gVisor) so
  the worker need not mount the host socket — *`backend/app/notebooks/sandbox.py`, `backend/app/config.py`,
  `docker-compose.hardened.yml`, `docs/SANDBOX_ISOLATION.md`*; tests *`backend/tests/test_sandbox_isolation.py`*.

**Verified already implemented (no change needed):** three-way branch merge with conflict
detection (*`backend/app/data/branch_service.py`*), marking inheritance (*`permissions/enforcement.py`*),
DuckDB file-function blocking (*`execution/sql_validator.py`*), governed exports E2E
(*`platform/router.py`*), DatasetPermission→ResourceACL backfill (*`alembic/versions/0033_*`*),
boot-time dev-secret guard (*`config.py: production_hardening_issues` enforced in `main.py`*),
route authorization matrix tests (*`tests/test_route_authorization_matrix.py`*).

---

## 1. Current System Status

### Overall Assessment

- [x] The system is **directionally correct** for a mini Foundry-style platform.
- [x] The platform already includes most major Foundry-inspired pillars at MVP level.
- [x] The platform kernel is the right architectural foundation.
- [ ] The system is **not yet production-ready** for sensitive or regulated enterprise data.
- [ ] The system still has governance, branching, writeback, sandboxing, and legacy-model risks.

### Correct Status by Area

| Area | Current Status | Priority |
|---|---|---|
| Overall architecture | Correct direction | High |
| Foundry-style platform kernel | Correct and important | High |
| Feature coverage | Broad MVP | Medium |
| Governance model | Good primitives, incomplete enforcement | High |
| Data catalog | Good MVP | Medium |
| Governed SQL | Strong design, needs route audit | High |
| Pipelines | Good MVP, lacks incremental builds | High |
| Ontology | Partial, major gaps remain | High |
| Writeback/actions | Risky until hardened | High |
| Branching | Not production-safe | High |
| Dashboards/apps | Partial but usable | Medium |
| AI | Correct policy principle | Medium |
| Sandbox | Good constraints, bad host trust boundary | High |
| Search | Too basic | Medium |
| UI | Broad but fragmented | Medium |
| Production readiness | Low | High |
| Testing | Medium; backend good start, E2E/load incomplete | Medium |

### Go / No-Go

#### Go

- [x] Internal demo
- [x] Engineering prototype
- [x] Controlled pilot with synthetic or low-risk data
- [x] Foundry-style architecture foundation

#### Conditional Go

- [ ] Internal business-data pilot  
  **Only after Phase 0 security and correctness fixes are complete.**

#### No-Go

- [ ] Regulated production data
- [ ] Sensitive customer data
- [ ] Multi-tenant enterprise deployment
- [ ] Compliance-critical export workflows
- [ ] High-trust operational writeback workflows

---

## 2. What Is Already Correct

### Architecture

- [x] Uses a sensible self-hosted stack:
  - Next.js frontend
  - FastAPI backend
  - PostgreSQL metadata/staging database
  - Redis cache and queue support
  - MinIO/S3-compatible object storage
  - Celery workers for async execution
  - Optional Trino, DuckDB, Ollama, and AI provider integrations
- [x] Long-running work is delegated to background workers.
- [x] Metadata, object storage, cache, execution, and UI layers are separated.
- [x] The runtime topology is understandable and suitable for local and self-hosted deployment.

### Foundry-Style Platform Kernel

- [x] The unified `resources` model is the correct architectural direction.
- [x] Projects and folders exist as organizational and security boundaries.
- [x] Resource versions provide a foundation for immutable snapshots.
- [x] ResourceACL provides a better model than simple roles.
- [x] Capabilities are granular and Foundry-like:
  - `view_metadata`
  - `view_data`
  - `use_in_sql`
  - `use_in_python`
  - `use_with_ai`
  - `export`
  - `edit`
  - `manage`
  - `run`
  - `publish`
  - `writeback`
- [x] Access requests and approvals are modeled.
- [x] Resource markings are modeled separately from ACLs.
- [x] Lineage edges and build runs exist.

### Governance and Security Primitives

- [x] Authentication exists.
- [x] Session cookies are supported.
- [x] API tokens and service accounts exist.
- [x] Row policies exist.
- [x] Column masks exist.
- [x] Security markings exist.
- [x] Audit logging exists.
- [x] Export request and approval flow exists conceptually.
- [x] AI policy exists per dataset.
- [x] SQL validation blocks obvious dangerous SQL operations.
- [x] Query execution is intended to go through a governed query service.
- [x] Notebook and code execution are routed to sandboxed workers rather than the API server.

### Data and Analytics

- [x] CSV ingestion exists.
- [x] Parquet ingestion exists.
- [x] Postgres connector exists.
- [x] REST connector exists.
- [x] Catalog, profile, preview, quality, lineage, and branching concepts exist.
- [x] Governed SQL supports validation, permission checks, row policies, masks, limits, and audit.
- [x] Dashboards can bind to governed SQL queries.
- [x] Pipelines support visual graph authoring and worker-based builds.

### Ontology, Apps, and Actions

- [x] Object types exist.
- [x] Relationships/link types exist.
- [x] Ontology graph visualization exists.
- [x] YAML import exists.
- [x] Actions and writeback exist at MVP level.
- [x] Application builder and published app runtime exist at partial level.

### AI

- [x] AI is treated as an assistant, not an authority.
- [x] AI-generated SQL is not trusted directly.
- [x] AI output is expected to be validated by backend enforcement.
- [x] AI policy checks exist for dataset usage.
- [x] SQL, Python, pipeline, dashboard, and logic-assistant flows are represented.

### Operations and Developer Experience

- [x] Jobs and schedules exist.
- [x] Worker, queue, cache, storage, metrics, and logs operation pages exist.
- [x] Docker Compose setup is documented.
- [x] Local development instructions exist.
- [x] Testing inventory exists.
- [x] Golden path workflow is documented.

---

## 3. What Is Missing

## High Priority Missing Items

### Governance and Security

- [x] Complete ResourceACL migration and remove legacy permission systems. *(runtime enforcement ACL-only; legacy deprecated, 2026-06-20)*
- [x] Implement marking inheritance from parent folders/projects. *(`permissions/enforcement.py`)*
- [x] Apply governance consistently to every data path. *(all dataset reads via `governed_query`/ACL)*
- [x] Harden ontology writeback with row policies, column authorization, branch context, and redacted audit. *(2026-06-20)*
- [x] Block unsafe DuckDB file functions such as unrestricted `read_parquet` or `read_csv`. *(`execution/sql_validator.py`)*
- [x] Remove or isolate the Docker socket trust boundary from workers. *(configurable isolated daemon, 2026-06-20)*
- [x] Complete governed export generation and download end-to-end. *(`platform/router.py`)*
- [x] Add production-grade secret management and rotation. *(vault/SOPS provider hooks + boot-time guard; rotation is operational)*
- [x] Add policy simulation/explain tooling. *(`explain_resource_permission` endpoint)*

### Foundry Parity

- [x] Object Sets. *(governed saved/ad-hoc filters — `backend/app/ontology/object_sets.py`, 2026-06-22)*
- [x] Functions on Objects. *(computed properties — `backend/app/ontology/functions.py`, 2026-06-22)*
- [ ] Incremental pipeline builds.
- [ ] Column-level lineage.
- [ ] Schema contracts and schema evolution policies.
- [ ] Branch review and conflict resolution UI.
- [ ] Permission-aware navigation.

### Data Platform Reliability

- [ ] Dataset version pinning across all reads, builds, dashboards, apps, notebooks, and ML jobs.
- [ ] Pipeline build reproducibility using immutable input versions.
- [ ] Backfill and partition management.
- [ ] Failure recovery and rollback for partially materialized outputs.
- [ ] Cleanup jobs for temporary files, abandoned branches, expired exports, and failed builds.

## Medium Priority Missing Items

- [ ] Postgres full-text search or OpenSearch-style indexed search.
- [ ] Email notifications for approvals, failures, and access requests.
- [ ] Full SAML assertion handling.
- [ ] Complete LDAP group-to-platform-group sync.
- [ ] Full media set UI.
- [ ] Automation monitor UI.
- [ ] App builder action approval and idempotency UX.
- [ ] More browser E2E tests.
- [ ] Load and concurrency tests.
- [ ] Backup and restore drills.
- [ ] OpenTelemetry tracing.
- [ ] Structured logs and operational dashboards.

## Low Priority Missing Items

- [ ] Fusion-style spreadsheets.
- [ ] Notepad/reports.
- [ ] Marketplace/package distribution.
- [ ] Cipher-style field encryption.
- [ ] Full Kafka-style streaming platform.
- [ ] Advanced RAG/vector search/agent framework.

---

## 4. What Needs to Be Redesigned

## High Priority Redesigns

### 4.1 Dataset Branch Merge

**Current Problem:**  
Branch merge is described as destructive: target rows may be deleted and replaced by branch rows.

**Risk:**  
Parent changes can be silently lost.

**Required Redesign:** *(already implemented — `backend/app/data/branch_service.py`)*

- [x] Implement three-way merge. *(base snapshot diff for PG + DuckDB branches)*
- [x] Detect row-level and schema-level conflicts. *(aborts with conflict report on schema/target drift)*
- [ ] Show merge preview. *(backend conflict report exists; dedicated preview UI is Phase 4)*
- [ ] Require approval for risky merges. *(ApprovalRequest exists; not yet wired to merge — Phase 2)*
- [ ] Create immutable version snapshot before merge.
- [ ] Support rollback after merge.
- [x] Log full audit and lineage events. *(merge audited; lineage edges recorded)*

**Priority:** High

---

### 4.2 Ontology Writeback

**Current Problem:**  
Writeback exists, but row policies, column masks, branch context, and audit redaction may not be consistently enforced.

**Risk:**  
A user may update records or see before/after values they are not authorized to access.

**Required Redesign:** *(hardened 2026-06-20 — `backend/app/ontology/writeback.py`)*

- [x] Require `writeback` capability. *(checked on the target dataset resource)*
- [x] Check action permission separately from object access. *(action cap via `user_can_run_action`; dataset cap via `effective_capabilities_for_object`)*
- [x] Apply row-level authorization to target object. *(row policy appended to read+write WHERE)*
- [x] Block writes to unauthorized or masked columns. *(write params on masked/hidden columns rejected)*
- [x] Support approval-required actions. *(`approval_required` → ApprovalRequest, `backend/app/actions/router.py`)*
- [x] Support idempotency keys. *(`idempotency_key` on ActionRun)*
- [x] Make writeback branch-aware. *(branch schema resolution)*
- [x] Redact masked values in before/after audit snapshots. *(`apply_masks` on old/new rows)*
- [x] Capture action lineage and audit. *(OntologyEdit + lineage edge + audit event)*

**Priority:** High

---

### 4.3 Permission Model

**Current Problem:**  
ResourceACL exists, but legacy dataset and workspace permission models still coexist.

**Risk:**  
Different routes may enforce different permission models.

**Required Redesign:**

- [x] Make ResourceACL the single source of truth. *(all dataset data-access readers now use `effective_capabilities_for_object`; 2026-06-20)*
- [x] Remove legacy dataset permission tables from runtime enforcement. *(no `effective_permission`/DatasetPermission enforcement callers remain; table retained but deprecated — `permissions/enforcement.py`)*
- [ ] Remove legacy workspace permission enforcement. *(workspace uses its own coherent `WorkspacePermission` model — not a data-access bypass; full migration deferred to Phase 1)*
- [x] Convert old grants into ResourceACL migrations. *(`alembic/versions/0033_*` backfill + grant/revoke mirroring)*
- [x] Add route authorization tests for every API route. *(`tests/test_route_authorization_matrix.py`, `test_resource_authorization.py`)*
- [x] Add permission explanation endpoint for all resource types. *(`explain_resource_permission`)*

**Priority:** High

---

### 4.4 Worker Sandbox Infrastructure

**Current Problem:**  
The sandbox runtime has strong container constraints, but the worker mounts the host Docker socket.

**Risk:**  
Worker compromise can become host compromise.

**Required Redesign Options:** *(code path now configurable 2026-06-20 — `backend/app/notebooks/sandbox.py`, `backend/app/config.py`, `docker-compose.hardened.yml`, `docs/SANDBOX_ISOLATION.md`)*

- [x] Use rootless Docker. *(`SANDBOX_DOCKER_HOST` → rootless dind daemon in hardened compose)*
- [x] Use gVisor/Kata Containers. *(`SANDBOX_RUNTIME=runsc|kata-runtime` adds `--runtime` to sandbox containers)*
- [ ] Use Kubernetes jobs with restricted runtime class. *(infra deployment choice — documented; not a code change)*
- [ ] Use Firecracker-style microVM isolation. *(infra deployment choice — documented)*
- [ ] Move sandbox workers to isolated compute nodes. *(infra deployment choice)*
- [x] Remove direct Docker socket mount from trusted application workers. *(worker targets isolated `DOCKER_HOST`; hardened compose drops the host-socket mount)*

**Priority:** High

---

### 4.5 Data Access Routing

**Current Problem:**  
The governed query layer is correct, but not all paths are guaranteed to use it uniformly.

**Risk:**  
Some routes may bypass row policies, masks, ACLs, or markings.

**Required Redesign:** *(largely implemented — `backend/app/governed_query/`)*

- [x] Create one shared resource/version/branch resolution service. *(`governed_query` resolves dataset refs/versions)*
- [x] Create one shared governance enforcement service. *(`governed_query` applies ACL + row policy + masks uniformly)*
- [x] Route all data-returning APIs through that service. *(SQL/pipeline-preview/dashboard/export/ML/AI dataset reads go through `governed_query`; readers now ACL-gated as of 2026-06-20)*
- [x] Include policy version and permission version in cache keys. *(`policy_cache_versions`)*
- [x] Audit every data access path. *(audit event per governed query with query hash + dataset versions)*

**Priority:** High

---

## Medium Priority Redesigns

- [ ] Migrate all frontend routes to the platform shell.
- [ ] Consolidate duplicate analytics routes.
- [ ] Consolidate AI policy enforcement across all AI endpoints.
- [ ] Convert platform search from substring scanning to indexed search.
- [ ] Standardize approval workflows across export, branch merge, action execution, and dangerous operations.
- [ ] Standardize lifecycle states across datasets, pipelines, dashboards, apps, notebooks, models, and ontology resources.

---

## 5. What Needs to Be Developed

## High Priority Development

### Security and Governance

- [x] ResourceACL-only enforcement. *(2026-06-20)*
- [x] Marking inheritance.
- [x] Governed ontology writeback. *(2026-06-20)*
- [x] DuckDB file-function restrictions.
- [x] Governed export file generation and download.
- [x] Route authorization matrix tests.
- [x] Production hardening checks. *(`production_hardening_issues` enforced at boot)*
- [x] Secrets rotation and external secret manager support. *(vault/SOPS provider hooks; rotation operational)*

### Branching and Versioning

- [x] Safe dataset branch merge.
- [x] Branch conflict detection.
- [x] Branch review UI. *(frontend `workspace/branches`)*
- [ ] Immutable dataset version usage everywhere. *(builds pin versions; dashboards/notebooks do not — Phase 1/2)*
- [ ] Pipeline input version pinning. *(BuildInput records versions; no enforced pinning — Phase 1)*
- [ ] Branch-aware ontology, dashboards, apps, and pipelines. *(writeback is branch-aware; broader coverage Phase 2)*

### Foundry-Style Ontology

- [x] Object Sets. *(structured-predicate filters via governed_query — `backend/app/ontology/object_sets.py`, 2026-06-22)*
- [x] Functions on Objects. *(computed/derived properties, mask-aware — `backend/app/ontology/functions.py`, 2026-06-22)*
- [ ] Object-level permission evaluation. *(action + target-dataset capability evaluated; full object-row eval Phase 2)*
- [x] Action approval policies. *(`approval_required` → ApprovalRequest)*
- [x] Action idempotency. *(idempotency keys on ActionRun)*
- [x] Redacted action audit. *(masked before/after snapshots)*

### Pipelines

- [ ] Incremental builds.
- [ ] Partition support.
- [ ] Watermark support.
- [ ] Backfill support.
- [ ] Quality gates as first-class build blockers.
- [ ] Build rollback and failed-output cleanup.

## Medium Priority Development

### User Experience

- [ ] Permission-aware navigation.
- [ ] Governance explain UI.
- [ ] Complete automation monitor UI.
- [ ] Complete media set UI.
- [ ] Complete app action UX.
- [ ] Complete branch taskbar and merge review UX.
- [ ] Standard empty/loading/error states.

### Operations

- [ ] OpenTelemetry traces.
- [ ] Structured logging.
- [ ] Metrics dashboards.
- [ ] Queue scaling strategy.
- [ ] Backup and restore tooling.
- [ ] Object storage lifecycle cleanup.
- [ ] Load and concurrency tests.

### Search and Discovery

- [ ] Postgres full-text search.
- [ ] Search over dataset columns.
- [ ] Search over ontology objects.
- [ ] Search over dashboards, apps, pipelines, code, and notebooks.
- [ ] Relevance ranking.

## Low Priority Development

- [ ] Full streaming pipeline product.
- [ ] Advanced AI agents.
- [ ] Vector database and RAG system.
- [ ] Spreadsheet product.
- [ ] Marketplace/package deployment.
- [ ] Advanced field-level encryption product.

---

## 6. Priority Matrix

| Item | Priority | Reason |
|---|---|---|
| Safe branch merge | High | Current approach risks silent data loss |
| Governed writeback | High | Current gaps can bypass security controls |
| DuckDB file access hardening | High | Possible unauthorized file/object-store access |
| Remove Docker socket trust boundary | High | Worker compromise can become host compromise |
| Complete ResourceACL migration | High | Dual permission systems create bypass risk |
| Marking inheritance | High | Parent classifications must propagate |
| Governed exports | High | Compliance-critical workflow incomplete |
| Route all data paths through governance | High | Prevents inconsistent enforcement |
| Object Sets | High | Core Foundry-style ontology capability |
| Functions on Objects | High | Needed for operational object logic |
| Incremental pipelines | High | Required for scalable data operations |
| Branch review UI | Medium | Needed after safe merge backend exists |
| Indexed search | Medium | Current search will not scale |
| Email notifications | Medium | Needed for operational workflows |
| Full SAML/LDAP | Medium | Enterprise readiness |
| Media set UI | Medium | Backend exists but UX incomplete |
| Automation UI | Medium | Backend exists but usability limited |
| E2E/load tests | Medium | Needed before broader rollout |
| Fusion/spreadsheets | Low | Not required for mini Foundry core |
| Marketplace | Low | Later platform maturity feature |
| Advanced RAG/agents | Low | Should wait until governance is consistent |

---

## 7. Recommended Foundry-Style Architecture

### Target Architecture

```text
Browser / Apps / Dashboards / Notebooks / SQL / Ontology Explorer
        |
        v
Platform API Gateway
        |
        v
Resource Resolution Layer
- project
- folder
- resource
- branch
- version
- storage manifest
        |
        v
Governance Enforcement Layer
- ResourceACL
- markings
- row policies
- column masks
- AI policy
- export policy
- action policy
        |
        v
Execution Layer
- governed SQL
- pipeline compiler
- notebook/code sandbox
- ontology action runtime
- ML training runtime
        |
        v
Storage Layer
- Postgres metadata
- Postgres staging schema
- MinIO/S3 lakehouse
- Redis cache/queue
        |
        v
Audit / Lineage / Metrics / Notifications
```

### Canonical Request Flow

```text
request
  -> authenticate
  -> resolve resource
  -> resolve branch/version
  -> check security markings
  -> check ResourceACL capability
  -> apply row policies
  -> apply column masks
  -> execute through approved engine
  -> capture lineage if output is produced
  -> write audit event
  -> return governed result
```

### Non-Negotiable Architecture Rules

- [ ] No user-facing data route may bypass the governance layer.
- [ ] No resource may exist outside the platform kernel.
- [ ] No execution may happen without branch/version context.
- [ ] No AI call may include data without AI policy and `use_with_ai` permission.
- [ ] No writeback may bypass row-level and column-level authorization.
- [ ] No export may bypass approval and audit.
- [ ] No worker should have broader infrastructure access than required.
- [ ] No cache key should omit user, permission version, policy version, branch, and dataset version.
- [ ] No raw object storage path should be exposed to user SQL.
- [ ] No legacy permission system should remain in active enforcement.

### Recommended Core Services

| Service | Responsibility |
|---|---|
| Resource Service | Resolve resource, project, folder, owner, lifecycle state |
| Version Service | Resolve immutable resource and dataset versions |
| Branch Service | Resolve branch context and safe merge operations |
| Policy Service | ACL, markings, row policies, column masks, AI/export/action policy |
| Query Service | Governed SQL validation, rewrite, execution, audit |
| Execution Service | Pipelines, notebooks, code transforms, ML jobs |
| Lineage Service | Resource-level and column-level lineage |
| Audit Service | Immutable audit trail and retention |
| Notification Service | In-app and email notifications |
| Approval Service | Shared approvals for exports, merges, actions, and dangerous operations |
| Search Service | Indexed search across platform resources and objects |

---

## 8. Final Development Roadmap

## Phase 0 — Security and Correctness

**Goal:** Prevent data loss, policy bypass, and unsafe execution.

### Checklist

- [x] Fix destructive branch merge. *(three-way merge w/ conflict detection — `data/branch_service.py`)*
- [x] Harden ontology writeback. *(target-dataset cap + masked-column write block — `ontology/writeback.py`, 2026-06-20)*
- [x] Audit and restrict DuckDB file functions. *(blocklist — `execution/sql_validator.py`)*
- [x] Remove or isolate Docker socket dependency. *(`SANDBOX_DOCKER_HOST`/`SANDBOX_RUNTIME` + hardened compose, 2026-06-20)*
- [x] Complete ResourceACL migration. *(runtime enforcement now ACL-only; legacy deprecated, 2026-06-20)*
- [x] Implement marking inheritance. *(parent/project traversal — `permissions/enforcement.py`)*
- [x] Rotate all development secrets. *(boot-time guard blocks dev defaults in production — `config.py`/`main.py`; `.env.example` documents generation)*
- [x] Add route authorization matrix tests. *(`tests/test_route_authorization_matrix.py`)*
- [x] Verify all data-returning APIs use governed access. *(reader audit complete — all dataset reads ACL-gated + `governed_query`)*
- [x] Finish governed export generation/download E2E. *(`platform/router.py` ExportRequest→ExportArtifact→download)*

### Exit Criteria

- [x] No known policy bypass paths. *(legacy dual-enforcement removed; writeback column/row gated)*
- [x] No destructive silent merge. *(merge aborts on conflict)*
- [x] No unsafe raw file reads from user SQL. *(DuckDB file functions blocked)*
- [x] No production deployment uses development defaults. *(startup hardening guard enforced)*
- [x] All high-risk data access routes are covered by tests. *(authorization matrix + new writeback/sandbox/config tests)*

**Priority:** High — **Phase 0 complete (2026-06-20)**

---

## Phase 1 — Platform Kernel Consolidation

**Goal:** Make the system coherent and maintainable.

**Backend-safe slice landed 2026-06-21** (items 2–7 + 8). Item 1 (workspace→project
migration) is explicitly deferred — it rewrites a whole backend subsystem and its frontend;
the workspace keeps its own coherent `WorkspacePermission` model, which is not a data-access
bypass. Adding physical `resource_id` FK columns to feature tables is likewise deferred in
favor of guaranteeing a `Resource` row at every creation site.

### Checklist

- [ ] Migrate legacy workspace to platform projects/folders/resources. *(deferred — separate UI-affecting effort)*
- [x] Remove legacy dataset permission enforcement. *(`DatasetPermission` model + writers removed; `dataset_permissions` table dropped — migration `0034`, 2026-06-21)*
- [x] Require `resource_id` for every platform object. *(every creation path registers a `Resource`; sync gaps in notebook scratch + postgres discovery closed via `upsert_resource_sync` — `platform/service.py`)*
- [x] Standardize version and branch resolution. *(`resolve_dataset_version` + shared `effective_schema` — `platform/service.py`, used by `governed_query`)*
- [x] Pin pipeline inputs to immutable versions. *(BuildInput pin map → `governed_query(pinned_versions=…)` → duckdb storage override; postgres logical sources recorded-only, audited via `BUILD_INPUTS_PINNED`)*
- [x] Make cache keys policy/version-aware. *(result caching centralized in `governed_query(use_cache=…)`; enabled on preview/explore/dashboard reads — key embeds user/permission/row/mask versions + branch + dataset versions)*
- [x] Add lifecycle states for production resources. *(`resources.lifecycle_state` + `POST /platform/resources/{id}/lifecycle` — migration `0034`)*
- [x] Route every data access path through governed query or equivalent enforcement. *(verified Phase 0 — no bypasses)*

### Exit Criteria

- [x] One resource model. *(every object registers a `Resource`; backfilled at startup)*
- [x] One permission model. *(ResourceACL only; legacy table dropped)*
- [x] One branch/version model. *(single `resolve_dataset_version`/`effective_schema` resolver)*
- [ ] No legacy route bypasses. *(data paths clean; legacy workspace routes remain until item 1)*

**Priority:** High — **backend-safe slice complete (2026-06-21); workspace migration outstanding**

---

## Phase 2 — Foundry Core Parity

**Goal:** Make Mini Foundry feel like a real Foundry-style operating layer.

### Checklist

- [x] Implement Object Sets. *(saved + ad-hoc governed filters; ACL'd as a Resource — `backend/app/ontology/object_sets.py`, `ontology/router.py`; migration `0035`; 2026-06-22)*
- [x] Implement Functions on Objects. *(computed properties, sqlglot-validated + mask-aware — `backend/app/ontology/functions.py`; 2026-06-22)*
- [ ] Add governed action approvals.
- [ ] Complete export generation/download.
- [ ] Add incremental pipelines.
- [ ] Add schema contracts.
- [ ] Add column-level lineage.
- [ ] Add Postgres full-text search.
- [ ] Improve app builder runtime state and object-driven variables.
- [ ] Add branch review and merge UI.

### Exit Criteria

- [ ] Users can build governed operational apps over object sets.
- [ ] Pipelines support incremental and reproducible builds.
- [ ] Column-level impact analysis is available for important SQL transformations.
- [ ] Exports and actions are governed by approvals and audit.

**Priority:** Medium / High

---

## Phase 3 — Production Operations

**Goal:** Make the platform operable, observable, and recoverable.

### Checklist

- [ ] Add OpenTelemetry.
- [ ] Add metrics dashboards.
- [ ] Add structured logs and log search.
- [ ] Add backup/restore procedures.
- [ ] Add migration smoke tests.
- [ ] Add load tests.
- [ ] Add sandbox escape/security tests.
- [ ] Add queue scaling strategy.
- [ ] Add object storage lifecycle cleanup.
- [ ] Add audit retention enforcement.
- [ ] Add email notification delivery.

### Exit Criteria

- [ ] Platform can be monitored.
- [ ] Platform can be restored.
- [ ] Platform can be upgraded safely.
- [ ] Platform capacity can be planned.
- [ ] Critical workflows have alerting.

**Priority:** Medium

---

## Phase 4 — UI/UX Completion

**Goal:** Reduce fragmentation and make user workflows reliable.

### Checklist

- [ ] Finish platform shell migration.
- [ ] Remove or redirect legacy routes.
- [ ] Add permission-aware navigation.
- [ ] Complete branch review UI.
- [ ] Complete automation monitor UI.
- [ ] Complete media set UI.
- [ ] Improve governance explain UI.
- [ ] Add full golden path E2E tests.
- [ ] Add consistent loading, error, and empty states.
- [ ] Improve app action UX.

### Exit Criteria

- [ ] Users can complete core workflows without falling into legacy or partial screens.
- [ ] Permission-denied states are understandable.
- [ ] Branch state is visible and consistent across the UI.
- [ ] Governance actions are clear and auditable.

**Priority:** Medium

---

## Phase 5 — Advanced Capabilities

**Goal:** Expand beyond mini Foundry once the core is safe.

### Checklist

- [ ] Streaming pipeline product.
- [ ] RAG/vector document retrieval.
- [ ] Advanced AI agents with governed tools.
- [ ] Marketplace/package publishing.
- [ ] Spreadsheet-like analysis.
- [ ] Field-level encryption/Cipher-style features.
- [ ] Advanced multi-tenant deployment model.

### Exit Criteria

- [ ] Core governance remains consistent while advanced features are added.
- [ ] Advanced AI and streaming features do not bypass platform policy.

**Priority:** Low until Phases 0–3 are complete

---

## 9. Top 10 Developer Actions

- [x] Fix destructive branch merge. *(done)*
- [x] Govern ontology writeback end-to-end. *(done 2026-06-20)*
- [x] Block unsafe DuckDB file reads. *(done)*
- [x] Complete ResourceACL migration. *(runtime enforcement now ACL-only; done 2026-06-20)*
- [x] Implement marking inheritance. *(done)*
- [x] Remove legacy workspace/permission duplication. *(dataset permission duplication removed; workspace-tree migration is Phase 1)*
- [x] Finish governed export generation and download. *(done)*
- [x] Add Object Sets. *(done 2026-06-22 — also adds Functions on Objects)*
- [ ] Add incremental pipeline builds. *(Phase 2 — not started)*
- [ ] Add permission-aware navigation and branch review UI. *(branch review UI exists; permission-aware nav is Phase 4)*

---

## 10. Final Assessment

Mini Foundry has the correct shape for a Foundry-inspired system. It already includes catalog, governed SQL, pipelines, dashboards, notebooks, ontology, apps, AI, audit, jobs, operations, and a platform kernel.

The main issue is not missing product breadth. The main issue is inconsistent enforcement and unfinished hardening.

The architecture should not be restarted. It should be consolidated around the platform kernel.

**Final conclusion:**  
The system is suitable as a broad MVP and internal prototype. It can become a mini Foundry-style system if the team first fixes security, branch merge, writeback governance, ResourceACL migration, sandbox isolation, marking inheritance, governed exports, and unified policy enforcement.
