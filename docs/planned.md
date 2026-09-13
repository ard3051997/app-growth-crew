# Managed Self-Hosted Beta Execution Roadmap

## Status Legend

- `[x]` Implemented in the current repository and covered by a focused regression test where noted.
- `[ ]` Required. `Partial:` identifies implemented groundwork that does not yet satisfy the complete roadmap claim. A route, table, scheduler job, MCP tool, UI control, or unexecuted deployment file is not completion by itself.

## Implementation Status - July 20, 2026

### Completed in This Build

- [x] Added managed-mode API authentication and authorization in `src/api_server/auth.py`: global API-key/proxy authentication, `admin`/`viewer` mutation separation, a global read-only switch, config-write gating, and secure-mode CORS preflight enforcement.
- [x] Added RevenueCat webhook shared-secret verification, required provider event IDs, persistent hashed replay receipts, retryable claims, API-lifespan outbox recovery, fail-closed receipt errors, and subscriber-identifier redaction.
- [x] Connected API routes and `run_autonomous_loop.py` to the shared `ExperimentLifecycle`; generic `PATCH` can no longer choose arbitrary statuses, and scheduler evaluation/execution uses the same lifecycle implementation.
- [x] Added the server-owned Play conversion proposal path at `POST /api/apps/{package}/store-conversion/proposals`. The server derives package, baseline counts, metric, hypothesis, target tool/arguments, rulebook evidence, and live listing provenance; the generic endpoint rejects executable proposals outside an explicit local-development compatibility flag.
- [x] Implemented and tested `recommend_only`, `manual`, and `auto_low_risk` behavior for the single beta executor, including deterministic policy downgrade, read-only blocking, measured-baseline validation, one-locale text limits, conflicts, brakes, snapshot-before-write, read-after-write verification, and verified rollback.
- [x] Replaced store-conversion use of rolling-rate Welch evaluation with non-overlapping visitor/install observations and a pooled two-proportion z-test. The scheduler now collects exact latest-day storefront counts instead of repeated rolling `7d` rates.
- [x] Added operational truth records for connector runs, source watermarks, snapshot provenance/partial state, scheduler heartbeat, SQLite foreign keys/WAL/busy timeout, and additive schema versioning. Production listing/journey failures now expose unavailable states; synthetic fallbacks require explicit demo mode.
- [x] Applied the evidence workflow in JMIP: server-authorized semantic actions, an accessible approval/detail drawer, lifecycle progression, before/after metadata diff, provenance badges, count-bearing observations, and explicit destructive confirmations.
- [x] Added a managed self-hosted source-tree deployment bundle: backend/frontend Dockerfiles, Compose topology, private backend network, read-only defaults, Caddy same-origin proxy, separate service secrets, health checks, scheduler guard, checksummed SQLite backup/restore tooling, and an operator runbook.

### Required Before Design-Partner Deployment

- [ ] Partial: the isolated Docker Desktop stack now passes image build, startup health, proxy authentication, viewer/admin read-only enforcement, restart, online backup, checksum verification, and restore. A clean remote Linux host and cross-version upgrade/rollback drill remain.
- [ ] Run a dedicated staging Play app through propose, manual approve, execute, remote verify, period-correct observe/evaluate, retain, rollback, drift conflict, timeout reconciliation, and restored-backup drills.
- [ ] Replace Basic/API-key beta access with the agreed production identity/TLS ingress or explicitly accept and document that design-partner limitation; auth is mandatory in Compose but remains opt-in for local source-tree runs.
- [ ] Add durable experiment command IDs/idempotency keys, immutable revisions/events, execution attempts/leases, and restart reconciliation. Current status projection plus `action_log` blocks several retries but is not the target event-sourced lifecycle.
- [ ] Complete statistical safeguards: confidence intervals, Fisher fallback for sparse cells, evaluator versioning, predeclared checkpoints, contamination detection, late-correction history, and a denominator/consecutive-period safety guardrail.
- [ ] Remove remaining truthfulness gaps: GA4 event-frequency ordering still looks like a journey, some aggregate paths still use zero for unavailable data, Play vitals remain placeholders, and system trust still defaults to `moderate` in legacy code.
- [ ] Keep RevenueCat/FCM lifecycle automation disabled for partners until a real subscriber-to-FCM-token/segment mapping replaces the current `app_user_id` token assumption.
- [ ] Add migration/restore release tests, off-host encrypted backup guidance, request correlation, broader action-log redaction, and the remaining system data-health/capability views.
- [ ] Complete internal dogfood and the design-partner milestones below; no partner production write has been validated by the local safe test suite.

### Verification Snapshot

- [x] Python safe suite: **509 passed**; live credentialed integration tests excluded.
- [x] Frontend unit/component suite: **18 passed**.
- [x] Frontend lint passed.
- [x] Frontend production build passed.
- [x] Python package build passed.
- [x] Repository-wide Ruff lint and format checks passed for `src/` and `tests/`.
- [x] Repository-wide mypy passed for all **85 source files**.
- [x] Docker Compose configuration and both production images built successfully with Docker `29.6.2` / Compose `v5.3.1`; the isolated API, scheduler, and proxy reached healthy state.
- [x] Published-route checks passed for public health, protected UI/API reads, viewer mutation denial, and admin read-only denial.
- [x] SQLite online backup, checksum verification, service restart, restore, and data rollback were exercised against disposable named volumes.
- [x] Frontend container `npm ci` and audit completed with **0 vulnerabilities**.

## Mobbin UI References Applied

- [x] **Aboard approval drawer:** the right-side experiment detail/approval drawer in `frontend/src/pages/ExperimentCenter.tsx` keeps evidence, validation, consequences, and actions in one review surface.
- [x] **PlanetScale change approval:** proposal validation, attributed approval, and execution are separate server commands; approval does not itself perform a manual-mode write.
- [x] **GitHub before/after diff:** ASO and experiment views use explicit removed/before and added/after metadata panels instead of an opaque generated result.
- [x] **Vercel lifecycle progression:** `LifecycleProgress` presents the proposal-to-outcome stages and terminal blocked states as a compact operational progression.
- [x] **Cloudflare provenance/operations:** `ProvenanceBadge`, connector watermarks, scheduler state, unavailable states, and source timestamps expose operational truth beside product data.
- [x] **Slite destructive confirmation:** reject and rollback require a dedicated confirmation state, explain consequences, and require attributed reason text before dispatch.

## Product Thesis

MCP-GC should compete with the repo-defined Fload as a **managed, self-hosted app-growth operator**, not as another broad analytics dashboard. Fload can aggregate and display metrics; MCP-GC must turn trusted evidence into a reversible store-conversion proposal, route it through an explicit autonomy policy, execute it safely, and show whether it worked.

The beta product is one isolated deployment per design partner, operated and updated by us while credentials and raw app data remain on that partner's host. JMIP is the evidence and control surface for the local API and worker. There is no shared multi-tenant data plane in beta.

The first complete wedge is Android Play Store metadata conversion:

`store data -> evidence -> server-owned proposal -> validation -> approval/policy -> reversible write -> period-correct observation -> verdict -> JMIP audit trail`

Success is not dashboard usage. It is a shorter time from a trustworthy conversion problem to a safely evaluated change, with no untracked production mutations.

## Current-State Caveats

### Security and safety already present

- [x] `src/api_server/routes/system.py` masks configured secrets and credential paths, preserves masked values on update, allowlists writable keys, and rejects newline injection; covered by `tests/test_backend_safety.py`.
- [x] `src/api_server/routes/apps.py` masks per-app secrets/paths and rejects unknown or immutable app-config updates; covered by `tests/test_backend_safety.py`.
- [x] Uploaded code ZIPs are bounded and reject traversal, duplicate paths, encryption, symlinks, oversized members, and expanded-size abuse; covered by `tests/test_backend_safety.py`.
- [x] `src/api_server/main.py` defaults CORS to the local Vite origins and refuses wildcard configuration; covered by `tests/test_backend_safety.py`.
- [x] Experiment writes and the vitals scan resolve per-app credentials, and Play Store execution rejects a tool argument targeting a different package; covered by `tests/test_backend_lifecycle.py`.
- [x] Emergency brakes are persisted in SQLite and checked before scheduler writes; safety state is exposed by `/api/system/safety`; covered by `tests/test_backend_safety.py` and `tests/test_backend_lifecycle.py`.
- [x] `deploy_approved_experiment` requires a measured baseline, permits only the rollback-tested `play_store/update_listing` path, captures and persists the pre-state before the external write, and does not requeue an uncertain post-write result; covered by `tests/test_backend_safety.py`.
- [x] Manual and automatic rollback change lifecycle state only after the external rollback succeeds; covered by `tests/test_backend_safety.py`.
- [x] The experiment API rejects unknown IDs and invalid state transitions; the SQLite migration preserves the new execution fields; covered by `tests/test_backend_lifecycle.py` and `tests/test_experiment_db.py`.
- [x] Period-specific funnel/revenue requests do not silently reuse the cached 30-day snapshot; covered by `tests/test_backend_safety.py`.
- [x] `pyproject.toml` constrains `pyjwt>=2.12.0` for the identified authenticity-verification CVE.

These controls are a useful base, not a claim that the product lifecycle is connected or production-authoritative.

### Audit Findings Resolved in This Build

- [x] Managed deployments now require API authentication. `ApiSecurityMiddleware` applies `admin`/`viewer` authorization to the entire `/api` surface, preserves health access, independently verifies RevenueCat, and enforces read-only/config-write switches. Local auth remains intentionally opt-in and is not a partner deployment profile.
- [x] `/api/webhooks/revenuecat` now verifies a configurable shared-secret header, requires provider event IDs, hashes and persists replay receipts before scheduling work, recovers retryable work, fails closed on receipt-store errors, and redacts subscriber identifiers from logs/actions.
- [x] Lifecycle authority is connected through `ExperimentLifecycle`: semantic API commands and scheduler execution/evaluation use the same service, frontend actions come from `available_actions`, and generic `PATCH` is restricted to an attributable rejection contract.
- [x] Executable browser-defined generic experiments are blocked by default. The store-conversion endpoint constructs the executable lifecycle payload from server-fetched listing/rulebook/storefront evidence; local-only generic compatibility requires explicit environment opt-in.
- [x] Store conversion no longer uses the rolling Welch path. Count-bearing observations enforce non-overlapping periods after baseline/execution, scheduler collection uses exact daily storefront counts, and lifecycle evaluation uses pooled baseline/treatment counts.
- [x] Deployment absence is resolved at the artifact/runbook level by `compose.yaml` and `deploy/`: source-tree backend, separately built frontend, private network, proxy auth, secrets, read-only defaults, checksummed backup/restore, and upgrade/rollback instructions. Runtime validation remains outstanding because Docker was unavailable locally.

### Unresolved Caveats

- [ ] `PlayStoreClient.get_vitals_overview()` still returns placeholders. Brake persistence and manual controls are real, but the automatic production vitals signal is not authoritative.
- [ ] Partial: RevenueCat sender/replay security is implemented, but re-engagement still treats `app_user_id` as an FCM registration token. Keep lifecycle push disabled until an authoritative token/segment mapping exists.
- [ ] Hypothesis generation and `get_latest_system_trust()` still contain hard-coded/default `moderate` trust. Execution authority now comes from deterministic autonomy modes, but legacy trust display/copy can still mislead.
- [ ] Partial: count-bearing two-proportion evaluation is active, but sparse-count Fisher fallback, confidence intervals, evaluator versioning, checkpoint/peeking policy, contamination detection, correction history, and a separate robust rollback guardrail are not implemented.
- [ ] Partial: listing and journey failures return unavailable outside explicit demo mode, and operational source states exist. GA4 frequency ordering is still labeled as a flow, and some portfolio/revenue paths still use zero where availability should remain unknown.
- [ ] The experiment lifecycle lacks immutable revisions/events, command idempotency keys, a durable execution queue/lease, and restart reconciliation. `active`/`rolling_back` prevent blind retries after uncertain dispatch, but an operator reconciliation workflow is still missing.
- [ ] Partial: deployment images, health checks, restart, and backup/restore now pass in an isolated Docker Desktop stack. TLS is still delegated to private ingress, migrations run during application initialization, backups are not automatically encrypted/off-host, and clean-host upgrade/rollback remains unverified.
- [ ] `src/api_server/` and `src/run_autonomous_loop.py` remain outside the Hatch wheel package list; the managed backend image deliberately copies the source tree. The Python wheel build passing does not make those applications wheel-installable.
- [ ] Existing documentation still contains broader “complete” lifecycle/autonomy claims. Partner-facing capability messaging must be driven by probes and the gated milestones below.

## Product and Engineering Rules

- [x] One server-side lifecycle service owns the implemented experiment transitions. API routes, the scheduler, and JMIP semantic actions use `ExperimentLifecycle`; Telegram callback migration remains separate Phase 4 work.
- [x] The server owns executable proposal mechanics. JMIP can submit proposed text and policy controls, but not package, MCP tool, executable arguments, baseline, confidence, or verdict.
- [ ] Partial: listing/proposal and operational paths distinguish unavailable/stale/synthetic data, but zero-valued unknowns and GA4 event-frequency “flow” semantics remain.
- [ ] No external mutation runs unless its policy, validation, pre-state snapshot, rollback handler, idempotency key, and evidence source are all recorded.
- [x] For the Play metadata golden path, autonomy cannot bypass deterministic validation, conflict checks, brakes, audit logging, measured evidence, or rollback readiness.
- [x] The beta stays single-tenant and SQLite-backed. Postgres, distributed orchestration, and a shared credential plane require demonstrated scale, not anticipation.

## Phase 0: Secure and Truthful Beta Boundary

### Work

- [ ] Partial: Compose serves JMIP and `/api` from one Caddy origin, publishes only the proxy on loopback by default, and keeps API/scheduler on an internal network. TLS termination is still delegated to private ingress and Docker execution is unverified.
- [x] Add operator authentication for every `/api` route except `/api/health` and independently authenticated provider webhooks. Managed mode has `admin`/`viewer` roles and requires admin authority for mutations.
- [ ] Partial: RevenueCat uses constant-time shared-secret verification, persistent hashed provider IDs, replay suppression, retry claims, and outbox recovery. Unknown app validation and real FCM token/segment mapping remain.
- [ ] Partial: authenticated API actions record middleware-derived actors, and webhook logs/actions redact subscriber IDs. Request IDs and comprehensive cross-route structured redaction remain.
- [ ] Partial: `get_app_journeys` and `get_app_listing` return unavailable outside explicit demo mode, with tests. Demo mode is explicit, but a global proof that demo mode cannot coexist with writes is still required.
- [ ] Partial: connector sync runs, watermarks, scheduler heartbeat, and safe errors now drive observed `success | partial | stale | unavailable` states. Capability probes and explicit `unsupported` state are incomplete.
- [ ] Mark Play vitals `unsupported` until the Play Developer Reporting API is implemented. Disable automatic vitals-based execution brakes when the signal is unavailable while preserving manual brakes.
- [ ] Partial: the experiment UI now uses “before / after” and evidence language, but GA4 event frequency and broader README lifecycle claims remain stale.
- [ ] Partial: CI now includes Gitleaks and pinned actions, and the PyJWT constraint remains. Dependency/image vulnerability gates are not yet present.

### Acceptance Criteria

- [ ] Partial: managed-mode middleware enforces health-only anonymous access and viewer mutation denial with an authorization matrix test; the test does not enumerate every mounted route.
- [x] A forged or replayed RevenueCat webhook causes no duplicate background task and no false action-log success entry.
- [ ] With GA4, Play listing, or vitals unavailable, APIs return provenance-bearing unavailable states and JMIP renders “Unavailable,” never plausible mock values or `0`.
- [ ] Production logs and action records contain correlation IDs and actors but no configured secret, local credential path, FCM token, or raw subscriber identifier.
- [ ] Security, backend, frontend, dependency, and image scans pass in CI from a clean checkout.

## Phase 1: Authoritative Experiment Lifecycle

### Work

- [x] Introduce `ExperimentLifecycle` under `src/app_manager/` as the implemented state authority. API semantic commands and scheduler execution/evaluation call it instead of maintaining separate transition logic.
- [ ] Partial: implemented states cover `proposed -> approved -> active -> measuring -> concluded`, plus `rejected`, `rolling_back`, and `rolled_back`. The target explicit `draft`, `executing`, `execution_failed`, and `reconciliation_required` model is incomplete.
- [ ] Record every transition in append-only `experiment_events` with actor, reason, prior/new state, command id, and timestamp. Keep `experiments.status` as a transactionally updated projection.
- [x] Replace arbitrary generic status mutation with semantic validate/approve/reject/execute/observe/evaluate/retain/rollback endpoints. The deprecated `PATCH` accepts attributable rejection only.
- [ ] Partial: repeated lifecycle execute/approve/reject operations have state-based idempotence and RevenueCat has a durable receipt/outbox. Experiment command keys, optimistic revisions, execution leases, and a notification outbox remain.
- [ ] Re-read queue state after proposal creation and before action. Never act on the stale `db_exps` list currently loaded near the start of `run_prao_cycle()`.
- [ ] Reconcile `executing` attempts after restart by reading the remote listing and comparing hashes. Never guess success or automatically retry a write with an unknown outcome.
- [ ] Partial: validation blocks another active/measuring experiment for the app. Locale/metric/surface-specific conflict records and database enforcement remain.

### Acceptance Criteria

- [ ] Partial: semantic API and scheduler transitions use `ExperimentLifecycle`, but legacy DB helpers remain and there is no append-only lifecycle event store.
- [ ] Partial: repeated in-process execution is tested to produce one write; restart/duplicate-worker guarantees require durable commands and leases.
- [ ] Invalid, stale-revision, conflicting, and brake-blocked commands fail before snapshot or external execution.
- [ ] Every experiment can be reconstructed in order from events, including who approved it, what executed, and why it concluded or stopped.
- [ ] A simulated crash before write, after write, and after remote success but before local finalization reaches a deterministic recoverable state in integration tests.

## Phase 2: Explicit Autonomy Modes

### Contract

- [x] `recommend_only`: collect evidence and create proposals; lifecycle validation disables approval and execution.
- [x] `manual`: an authenticated admin must issue attributed approval before a separate execution command can write the Play listing.
- [x] `auto_low_risk`: automatic approval/execution is limited by the validator to reversible `en-US` Play text metadata under measured evidence, app/system policy, conflict, brake, and rollback gates.

### Work

- [ ] Partial: requested mode is persisted per experiment and capped by system environment plus app rulebook; there is no versioned deployment/app policy record. JMIP defaults to `recommend_only`, while the direct proposal model still defaults to `manual`.
- [x] Replace `conservative | moderate | aggressive` as an execution control. Legacy trust remains display/prompt context but does not grant write authority.
- [ ] Partial: deterministic validation uses executor, locale, text fields, reversibility, conflicts, source freshness/counts, and app/system limits, independent of LLM risk. A persisted risk class and daily cap are absent.
- [ ] Require a typed reason, actor, and confirmation to increase autonomy. Downgrades and emergency brakes take effect immediately.
- [ ] Partial: `auto_low_risk` requires one locale, text-only metadata, live listing, fresh fixed baseline counts, no active app conflict, brakes clear, and a tested rollback. Proposal-time listing hash comparison and a configured daily execution cap remain.

### Acceptance Criteria

- [x] A mode matrix covers the only beta executor and proves `recommend_only` does not approve/write, `manual` does not auto-write, and policy-downgraded auto mode does not reach the writer.
- [ ] Switching to `recommend_only` blocks queued unexecuted writes without corrupting approved history.
- [x] `auto_low_risk` validation requires exactly `aso_metadata`, `play_store/update_listing`, `store_view_to_install_rate`, and `en-US`; unsupported tools/arguments cannot reach the lifecycle writer.
- [ ] JMIP shows the effective mode and the exact policy decision on each proposal; it does not infer mode from a trust label.

## Phase 3: Server-Owned Store Conversion Proposal

### Work

- [x] Add dedicated server-owned proposal construction in `store_conversion_proposals.py` and the package-bound API route. It fetches the live listing, rulebook, and complete daily storefront rows and then submits through the lifecycle boundary.
- [ ] Partial: the proposal persists exact baseline periods/counts/freshness, listing/rulebook provenance, and current/proposed content. Evidence is stored as JSON without immutable revisions, hashes, or normalized evidence records.
- [x] Constrain generated/operator listing input to typed `ListingText`; the server derives the canonical full listing and maps it to the fixed Play update executor only after deterministic validation.
- [x] JMIP cannot submit `app_package`, `target_tool`, `target_args`, baseline, confidence, or risk to the store-conversion route. Generic executable creation is blocked unless explicitly enabled in local development.
- [x] Validate package/locale ownership, live listing, complete/fresh measured counts, Play lengths, required/prohibited terms, control characters, no-op changes, rulebook binding, and omitted-field preservation.
- [ ] Store proposal revisions; editing creates a new immutable revision and invalidates approval of the prior revision.
- [x] Scope executable beta proposals to Google Play `en-US` title, short description, and full description; the route rejects iOS identifiers and validator rejects other surfaces.

### Acceptance Criteria

- [x] The store-conversion request model forbids extra MCP tool, package, baseline, or executable-argument fields.
- [x] Every accepted proposal contains a live listing snapshot plus complete, fresh, visitor-weighted daily storefront baseline counts.
- [ ] The persisted executable payload is derived from the approved typed patch and current server snapshot, not browser state or raw LLM JSON.
- [ ] A listing changed remotely after proposal creation fails optimistic preflight and returns to review; it is never overwritten silently.
- [ ] Ten golden rulebook/listing fixtures cover length boundaries, prohibited terms, omitted fields, locale handling, no-op changes, and malicious model output.

## Phase 4: Validation and Safe Execution

### Work

- [ ] Partial: `ExperimentLifecycle` implements typed validation/read/write/verify/rollback for the single Play text path, but there is no reusable executor registry contract.
- [ ] Partial: full rollback snapshot and active claim are persisted before write. Command/revision identity, expected pre-state hash, and execution lease are absent.
- [ ] Partial: execution revalidates current mode, brake, conflict, baseline freshness, package/locale, and rollback support. It does not compare a proposal-time remote hash or persist a credential capability probe.
- [x] Verify the remote listing after apply and persist the actual post-state plus client result; a successful client return alone is not accepted as proof.
- [ ] Partial: uncertain forward writes stay `active`, uncertain rollbacks stay `rolling_back`, and retries are blocked. There is no restart read-reconciliation command, explicit `reconciliation_required` projection, or operator notification workflow.
- [x] Roll back only from the persisted pre-state after checking treatment-state drift; verify the remote restored fields before marking `rolled_back`.
- [ ] Route Telegram through the command API rather than directly approving a tool call. Bind callbacks to experiment revision, actor/chat, expiry, and one-time nonce.
- [ ] Keep `action_log` as a user-facing projection, but derive it from lifecycle/execution events so failed and blocked attempts cannot disappear.

### Acceptance Criteria

- [ ] Partial: the implemented experiment executor cannot mutate without a durable snapshot and rollback path; other MCP/webhook mutation surfaces are not yet governed by this lifecycle.
- [ ] Package, locale, revision, pre-state hash, and policy are checked immediately before every write.
- [x] Play listing execution success requires remote read-back equality; rollback success requires verified remote restoration.
- [x] Lifecycle timeouts leave forward/rollback state non-retryable (`active`/`rolling_back`) rather than automatically replaying an uncertain write.
- [ ] A staging Play app completes approve, execute, verify, observe, conclude, and rollback drills with an exported audit bundle.

## Phase 5: Period-Correct Observation and Evaluation

### Work

- [ ] Partial: observations now persist period boundaries, visitors, installs, locale, phase, source, rate, and raw JSON. Normalized immutable evidence IDs, source-record/ingest timestamps, completeness, and correction versions remain.
- [x] Store conversion uses traced Play storefront `installs / visitors` counts from `listing_performance_by_country`, not funnel-engine daily rates.
- [ ] Partial: proposal baselines require a contiguous complete daily window, and treatment periods must begin strictly after baseline and verified execution and cannot overlap. Provider-day completeness/finality at execution time needs stronger guarantees.
- [x] Scheduler observation collects exact one-day storefront counts, rejects overlapping/conflicting duplicates, and no longer inserts repeated rolling `7d` snapshots.
- [ ] Partial: pooled baseline/treatment counts use a two-sided two-proportion z-test and persist rates, counts, z-score, confidence, method, and verdict. Confidence intervals, p-value field, effect fields, evaluator version, and Fisher fallback remain.
- [x] Minimum observation days and visitors, target lift, significance, rollback degradation, and max-window inconclusive behavior are enforced in lifecycle evaluation.
- [ ] Evaluate formal verdicts only at predeclared checkpoints or final window to avoid unbounded daily peeking. Safety rollback uses a separate guardrail with minimum denominator, consecutive complete periods, and explicit degradation threshold.
- [ ] Detect contamination from overlapping store experiments, remote listing drift, missing days, source-definition changes, or major acquisition-mix changes; pause and mark the result non-attributable rather than forcing a verdict.

### Acceptance Criteria

- [ ] Partial: tests prove strict post-baseline/execution treatment dates and overlap rejection; provider timezone/day-finality boundaries are not covered.
- [ ] Hand-calculated two-proportion and Fisher fixtures match the evaluator, including zero visitors, low counts, missing days, identical rates, positive lift, degradation, and max-window inconclusive cases.
- [ ] Re-ingestion is idempotent, and late provider corrections create a versioned reevaluation event rather than silently rewriting a published verdict.
- [ ] Partial: JMIP displays observation source and visitor sample counts plus baseline evidence, but full period/count presentation and all confidence prerequisites are incomplete.
- [x] The scheduler and authoritative lifecycle no longer use `ExperimentEvaluator`/constant scalar baselines for store conversion; the legacy class remains unused by this path.

## Phase 6: JMIP Evidence Flow

### Work

- [ ] Partial: the experiment drawer uses the semantic detail API for baseline evidence, diff, validation, actions, observations, evaluation, and action history. It lacks normalized execution receipts, full periods, and immutable event timeline.
- [ ] Partial: reusable provenance badges expose source, live/snapshot, and captured time in proposal/experiment views. Every KPI does not yet carry period, freshness, completeness, and estimate metadata.
- [x] Replace arbitrary frontend status transitions with `available_actions` returned by the lifecycle detail contract and semantic command endpoints.
- [ ] Rename “A/B” copy to “before/after” unless a provider-backed concurrent control exists. Keep confidence language tied to the persisted evaluation method.
- [ ] Split journey evidence into `declared` (`EVENTS.md`), `observed_event_frequency` (GA4 aggregate), and future `observed_path` evidence. Never synthesize a path from frequency order.
- [ ] Partial: listing/journey production fallbacks and key experiment empty states are explicit; hard-coded trust, GA4 flow semantics, placeholder vitals, and some zero defaults remain.
- [ ] Export a redacted evidence bundle containing experiment JSON, event timeline, source periods, listing snapshots/diffs, execution receipts, and evaluator result for operator review or support.

### Acceptance Criteria

- [ ] An operator can answer “what changed, who/what approved it, what evidence justified it, what source measured it, and can it be restored?” from one page.
- [x] JMIP cannot advance lifecycle state with arbitrary statuses or submit generic executable mechanics; it uses server-provided semantic actions and the package-bound proposal endpoint.
- [ ] Disconnecting every connector produces explicit unavailable states with no fabricated metric, listing, journey, or confidence.
- [ ] Frontend contract tests use generated OpenAPI types or validated schemas and fail when backend response contracts drift.

## Phase 7: Deployment Packaging and Operations

### Work

- [ ] Partial: source-tree backend and independent frontend/proxy Dockerfiles exist and explicitly include API/scheduler sources. Images were not built locally, and release images/tags are not yet published by digest.
- [ ] Partial: Compose provides shared SQLite, separate service secrets, same-origin proxying, health checks, restart policies, hardened containers, and a single loopback-published proxy. TLS is delegated to private ingress and explicit resource limits are absent.
- [ ] Partial: additive schema versioning and migration records exist, but migrations run during initialization; there is no standalone preflight CLI, automatic pre-upgrade backup, or migration-mismatch stop contract.
- [ ] Partial: checksummed SQLite online backup/restore tools and runbook exist. Automatic encryption/off-host transfer, broader config/evidence backup scope, and CI restore verification remain.
- [ ] Partial: connector-run/watermark history, scheduler heartbeat, last cycle, source-safe errors, and latest snapshot are exposed. Queue depth, disk/DB health, backup age, and complete JMIP operations view remain.
- [ ] Partial: managed backup/upgrade/rollback procedures are documented. Compatibility automation, published digest pulls, migration smoke tests, and support-bundle generation remain.
- [x] Managed packaging keeps credentials in customer-host Compose secrets with separate API/scheduler mounts and no default support telemetry plane.

### Acceptance Criteria

- [ ] A fresh Linux VM can reach authenticated JMIP from only the documented public port after one supported install flow.
- [ ] Reboot resumes schedules without duplicate execution; two worker replicas cannot execute the same command.
- [ ] Backup restoration on a blank host preserves experiment events, evidence, policies, and brake state and can still verify the audit chain.
- [ ] Upgrade and rollback are exercised from the previous beta version with no unrecorded external mutation.

## Phase 8: Onboarding and Data Trust

### Work

- [ ] Build an onboarding wizard that creates one app entry, validates package ownership, tests each connector with least-privilege read access, records source timezone/latency, and imports enough storefront history for a baseline.
- [ ] Separate read readiness from write readiness. Require an explicit write-scope test and a successful snapshot/rollback dry run before `manual` can execute; require a staging execution drill before `auto_low_risk` is selectable.
- [ ] Show a per-app capability matrix sourced from real probes: store read/write, storefront counts, GA4, RevenueCat, AdMob, GCS, vitals, FCM, App Store, and rollback support.
- [ ] Partial: proposal/ingestion checks cover freshness, missing baseline days, invalid/duplicate treatment periods, impossible counts, and package binding. Dimension duplication, timezone ambiguity, and cross-source conflicts remain.
- [ ] Partial: store conversion now authoritatively uses Play storefront counts rather than GA4/funnel estimates. Revenue overlap/precedence rules are not fully enforced.
- [ ] Partial: proposal and observation evidence preserve visitor/install units, provider source, periods, and locale. Other portfolio metrics can still substitute/aggregate ambiguously.
- [ ] Partial: JMIP and generic experiment creation default to `recommend_only`, and managed Compose defaults globally read-only. The direct store proposal model defaults to `manual`, and onboarding gates are not implemented.

### Acceptance Criteria

- [ ] A partner cannot finish onboarding with an unknown package, inaccessible credential file, missing metric definition, or ambiguous source period hidden as “connected.”
- [ ] The capability matrix agrees with direct connector probes and controls which product actions are offered.
- [ ] Partial: proposal creation requires and displays seven complete fresh storefront days with daily/count evidence before validation. Normalized source-record links and onboarding eligibility gates remain.
- [ ] Removing or expiring credentials changes health to unavailable without exposing the secret or replacing data with zero.

## Phase 9: Design-Partner and GTM Milestones

### Milestone A: Internal Dogfood

- [ ] Run `recommend_only` on one repository-configured Android app for 14 days.
- [ ] Review at least five server-owned proposals; reject low-quality proposals with structured reasons to improve validation/prompt inputs.
- [ ] Complete two manual staging experiments and one rollback drill with 100% event/evidence coverage and zero duplicate or untracked writes.
- [ ] Exit when source freshness is at least 95% over scheduled periods and every displayed metric has provenance.

### Milestone B: Two Managed Design Partners

- [ ] Deploy one isolated managed instance per partner, covering at least five apps total, initially in `recommend_only`.
- [ ] Conduct weekly evidence reviews and measure proposal acceptance, time-to-decision, data downtime, support time, and reasons for rejection; do not optimize for page views.
- [ ] Exit when each partner can onboard an app, understand a proposal without engineer interpretation, export evidence, and restore from backup.

### Milestone C: Manual Production Beta

- [ ] Enable `manual` only for partners that pass write-readiness and staging rollback gates.
- [ ] Complete at least ten verified Play metadata executions across partners with no untracked mutation, no unresolved reconciliation, and 100% rollback snapshot coverage.
- [ ] Publish case studies only from concluded period-correct experiments; report counts, periods, method, and uncertainty, not unsupported causal or A/B claims.

### Milestone D: Auto-Low-Risk Pilot

- [ ] Offer `auto_low_risk` as an explicit opt-in to one partner after at least five successful manual executions on the same executor and no failed rollback drill.
- [ ] Cap automatic executions per app and deployment, provide an immediate mode downgrade and manual brake, and review every automatic decision weekly.
- [ ] Exit when at least five automatic executions satisfy all policy/evidence gates, with zero policy escapes, duplicate writes, unresolved remote states, or missing audit events.

### Positioning and Commercial Test

- [ ] Sell “managed evidence-to-action for app-store conversion” rather than “all-in-one app analytics” or “fully autonomous growth.”
- [ ] Demonstrate the differentiator against Fload with one traceable workflow: identify conversion gap, inspect evidence, approve a listing diff, verify the remote change, and evaluate counts over fixed periods.
- [ ] Test a per-deployment platform fee plus managed onboarding/support; defer usage pricing until connector and LLM costs are measured from partner runs.
- [ ] Do not expand to paid UA, pricing, or lifecycle automation until design partners repeatedly complete the store-conversion loop and request the adjacent action.

## Data Model Target

The schema evolves the existing `data/store_performance.db`; it does not introduce a second authoritative store.

### Core Records

- [ ] `autonomy_policies`: `scope_type`, `scope_id`, `mode`, `allowed_executor`, `daily_cap`, `changed_by`, `changed_at`, `revision`.
- [ ] Partial: `experiments` now stores stable identity, package, type, status, execution mode, validation/evidence JSON, approval attribution, execution/evaluation timestamps/results, and observation thresholds. Locale, revision/approved revision, risk class, and normalized observation-start projection remain.
- [ ] `experiment_revisions`: immutable `experiment_id`, `revision`, operator intent, hypothesis, typed proposed patch, expected listing hash, rulebook version, evidence-set ID, validation result, and model/prompt versions.
- [ ] `experiment_events`: append-only `sequence`, `experiment_id`, `event_type`, `from_status`, `to_status`, `actor_type`, `actor_id`, `reason_code`, `reason`, `command_id`, `created_at`.
- [ ] `evidence_records`: `id`, `app_package`, `metric`, `source`, `source_mode`, dimensions JSON, `period_start`, `period_end`, numerator, denominator, value, source timestamp, ingest timestamp, completeness, raw-reference hash, and schema version.
- [ ] `experiment_evidence`: immutable join from experiment revision to evidence record with purpose `diagnosis | baseline | guardrail | treatment | context`.
- [ ] `listing_snapshots`: package, locale, provider, captured time, normalized listing JSON, content hash, and remote revision/etag when available.
- [ ] `execution_attempts`: command/idempotency key, experiment revision, executor, lease owner/expiry, expected pre-hash, pre/post snapshot IDs, provider receipt, state, started/completed times, and redacted error code.
- [ ] Partial: evaluation JSON persists method, baseline/treatment counts/rates, z-score, confidence, change, observation minima, verdict, reason, and evaluated time. A normalized versioned result table, intervals, p-value, checkpoints, and contamination flags remain.
- [x] `sync_runs` plus `source_watermarks` persist connector/source, app, requested/completed periods, status, record count, safe error, timestamps, and last-success freshness projection; request correlation remains future work.
- [ ] Partial: `webhook_event_receipts` is a durable RevenueCat receipt/claim/retry outbox with redacted payload handling. A generic lifecycle/notification outbox remains.

### Invariants

- [ ] Partial: foreign keys, WAL, and busy timeout are enabled on managed DB connections. There is no append-only lifecycle event transaction yet.
- [ ] Experiment revision, evidence, listing snapshots, execution attempts, and evaluations are immutable; corrections append new records.
- [ ] Partial: observation date/period conflict checks and webhook provider/event uniqueness are enforced. Experiment command/event/lease uniqueness remains.
- [ ] `approved_revision == execution_attempt.revision`; changing a proposal invalidates prior approval.
- [ ] A concluded verdict references a persisted evaluation result; a rolled-back state references a verified rollback attempt.

## API Contract Target

Target contract: all responses include `request_id`; data responses include `source_status`, `period`, `freshness`, and `as_of` where applicable. Mutation requests require authentication, `Idempotency-Key`, and expected `revision`. Authentication and several provenance fields exist; request IDs, command idempotency headers, and revisions remain incomplete.

- [x] `POST /api/apps/{package}/store-conversion/proposals`: accepts typed listing/policy controls only and returns the canonical server-owned proposal, validation, and lifecycle experiment. Immutable revision/idempotency remains future work.
- [x] `GET /api/experiments/{id}`: returns lifecycle projection, allowed commands/action links, effective policy/validation, evidence/diff, observations, evaluation, and action history.
- [ ] `GET /api/experiments/{id}/timeline`: returns ordered lifecycle, execution, observation, evaluation, and rollback events.
- [ ] Partial: `POST /api/experiments/{id}/approve` records the middleware-authenticated actor and required reason, but has no immutable revision check.
- [ ] Partial: `POST /api/experiments/{id}/reject` records authenticated actor/reason, but has no revision or structured reason code.
- [ ] Partial: `POST /api/experiments/{id}/execute` enforces approved validated state and verified execution, but runs in the request process without revision/idempotency or a durable command queue.
- [ ] Partial: `POST /api/experiments/{id}/rollback` requires attributed reason and verified restoration, but runs in the request process without revision/idempotency or a durable command queue.
- [ ] `GET /api/experiments/{id}/evidence`: returns immutable source records, listing diff/snapshots, validation, and provenance.
- [ ] Partial: count-based evaluation is returned in experiment detail and by `POST /api/experiments/{id}/evaluate`; a dedicated immutable `GET` resource and contamination status remain.
- [ ] `GET /api/apps/{package}/capabilities`: returns probed read/write/rollback readiness per connector.
- [ ] `GET /api/apps/{package}/data-health`: returns connector runs, freshness, missing periods, and blockers.
- [ ] `PUT /api/system/autonomy`: admin-only `{mode, expected_revision, reason}`; app overrides use `/api/apps/{package}/autonomy`.
- [ ] `POST /api/system/safety/{package}/brake` and `DELETE /api/system/safety/{package}/brake`: admin-only, audited commands; clearing requires reason and current brake revision.
- [x] Remove arbitrary lifecycle semantics from generic `PATCH /api/experiments/{id}`; its strictly validated compatibility shape supports attributable rejection only, and JMIP uses semantic commands.

## Test and Release Gates

### Unit and Property Tests

- [ ] Partial: tests cover implemented state transitions, terminal rejection/retain/rollback, app conflict, mode policy matrix, and deterministic validation. Revision invalidation and generalized risk classification remain.
- [ ] Partial: tests cover listing normalization/completion, package/field/rulebook validation, extra-field rejection, synthetic-source rejection, and rulebook/webhook redaction. Proposal hashes and broader log redaction remain.
- [ ] Partial: tests cover count-based two-proportion outcomes, non-overlap, minimum days/visitors, max-window behavior, and no low-confidence rollback. Fisher, intervals, contamination, checkpoints, corrections, and robust guardrails remain.
- [x] ZIP limits, webhook authentication/replay/retry, auth roles, secret masking, read-only gating, and package/path isolation are regression-covered.

### Database and API Tests

- [ ] Partial: additive legacy-schema tests cover lifecycle/observation columns, schema version, foreign keys, WAL, and busy timeout. Event/projection atomicity and restored production-shaped backup compatibility remain.
- [x] Request-model/API tests reject extra executable proposal fields and arbitrary generic status transitions.
- [ ] Partial: the auth matrix covers anonymous/viewer/admin/proxy/webhook/read-only behavior, and lifecycle tests cover repeated execution. Per-command idempotency keys and revisions are absent.
- [ ] Partial: tests cover unavailable listing/journey/funnel states, stale sources, synthetic baseline rejection, and carried-forward timestamps. Portfolio-wide zero/estimate semantics remain.

### Execution and Failure Tests

- [ ] Partial: fake-provider tests cover validation, snapshot ordering, write/read-back, rollback/read-back, remote rollback drift, unsuccessful writes, unknown timeouts, duplicate lifecycle calls, webhook duplicate/retry/expiry, and policy downgrade. Worker death, experiment lease expiry, proposal hash drift, and restart reconciliation remain.
- [ ] Staging Play tests use a dedicated beta app and confirm actual remote state; they never target a design partner production app in CI.
- [ ] Partial: lifecycle period tests use a controllable clock and the scheduler records exact daily counts/heartbeat. Misfire, restart, provider timezone, and single-executor lease tests remain.

### UI and Packaging Tests

- [ ] Partial: 12 frontend tests cover core lifecycle, proposal API behavior, safety status, and utilities; full auth/mode/error/reconciliation/evaluation/export e2e coverage remains.
- [ ] Compose smoke test starts a clean deployment, runs migrations, authenticates, creates a recommendation, restarts, backs up, restores, and upgrades from the previous schema. Docker was unavailable locally for this build.
- [ ] Partial: this build passed 499 safe Python tests, 12 frontend tests, frontend lint/build, package build, and targeted Ruff. CI defines broader Ruff/mypy/Python matrix/Gitleaks/deployment checks, but image/dependency scans and credentialed staging execution remain.

## Explicitly Out of Scope for the Beta

- [ ] Multi-tenant SaaS, shared databases, centralized customer credentials, organization billing, SSO directory sync, and regional control planes.
- [ ] Native concurrent A/B assignment, causal claims from GA4 event ordering, Bayesian optimization, multi-armed bandits, or cross-app budget allocation.
- [ ] Autonomous releases/rollouts, paywall/pricing changes, entitlement writes, push delivery, paid-UA budget changes, review replies, creative/image updates, iOS writes, Jira/Confluence writes, and Remote Config writes.
- [ ] Meta Ads, Firebase Crashlytics/Remote Config, AppFollow paid integration, and real Play vitals execution gates until their connector, provenance, and rollback contracts pass the same release gates.
- [ ] Replacing SQLite or APScheduler solely for anticipated scale; first add authoritative transactions, leases, reconciliation, backups, and operational evidence.
- [ ] Broad dashboard parity with Fload. Add a metric or integration only when it improves proposal quality, safety, evaluation, or a validated design-partner workflow.

## Beta Definition of Done

- [ ] A managed self-hosted installation starts securely, exposes authenticated same-origin JMIP, survives restart/upgrade/restore, and keeps partner credentials local.
- [x] The implemented/tested golden path can recommend, manually execute, and auto-execute only validated low-risk Play text metadata through `ExperimentLifecycle`; live staging and partner deployment gates remain separately unchecked.
- [ ] Every write is policy-allowed, validated, snapshotted, idempotent, remotely verified, auditable, reconcilable, and rollback-tested.
- [ ] Store conversion uses non-overlapping complete periods and visitor/install counts with a persisted two-proportion evaluation.
- [ ] JMIP displays source, freshness, counts, periods, diffs, actors, receipts, uncertainty, and unavailable states without synthetic production data.
- [ ] Two design partners complete the manual loop, and one explicitly opts into the gated auto-low-risk pilot under the milestones above.
