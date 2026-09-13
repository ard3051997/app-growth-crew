# MCP-GC Remaining Work Checklist

Use this as the operational checklist for moving from the locally verified managed beta to a design-partner release. The complete long-term roadmap remains in [`planned.md`](planned.md).

## Status Legend

- `[ ]` Not completed
- `[~]` In progress or partially complete
- `[x]` Completed and verified

## Current Baseline

- [x] Authoritative Play metadata experiment lifecycle
- [x] `recommend_only`, `manual`, and `auto_low_risk` execution modes
- [x] Server-owned store-conversion proposals
- [x] Deterministic rulebook validation
- [x] Snapshot-before-write and verified rollback
- [x] Count-based, non-overlapping store-conversion evaluation
- [x] API authentication, roles, read-only mode, and webhook replay protection
- [x] JMIP evidence, diff, lifecycle, provenance, and safety interfaces
- [x] Docker images and isolated Compose deployment
- [x] Docker health, authentication, restart, backup, and restore validation
- [x] Python tests, Ruff, mypy, frontend tests, lint, build, and package build

## P0: Before External Deployment

### 1. Sanitize Credentials

- [ ] Replace credential values and machine-specific paths in tracked configuration with placeholders or `null`.
- [ ] Remove customer-specific values from tests, examples, and documentation.
- [ ] Rotate credentials that may have appeared in Git history.
- [ ] Run Gitleaks against the full repository history.
- [ ] Review every finding and record any accepted false positive.
- [ ] Confirm deployment secrets exist only in ignored files, mounted secrets, or a secret manager.

**Done when:** a clean clone contains no usable credential, private path, customer identifier, or token.

### 2. Live Staging Play Store Drill

- [ ] Create or select a dedicated non-production Android app.
- [ ] Configure least-privilege Play read/write credentials.
- [ ] Configure current Play storefront GCS reports.
- [ ] Confirm at least seven complete baseline days are available.
- [ ] Generate a server-owned store-conversion proposal.
- [ ] Verify current listing, rulebook, baseline counts, and provenance.
- [ ] Approve the proposal in `manual` mode.
- [ ] Execute the listing update.
- [ ] Confirm read-after-write verification matches the approved proposal.
- [ ] Confirm the action log contains validation, approval, snapshot, execution, and verification.
- [ ] Wait for complete post-change Play report days.
- [ ] Collect treatment observations.
- [ ] Evaluate the experiment from visitor/install counts.
- [ ] Test retaining a winner.
- [ ] Test a verified rollback to the original listing.
- [ ] Simulate remote listing drift and confirm execution/rollback is blocked.
- [ ] Simulate a timeout or unknown write result and complete operator reconciliation.

**Done when:** the full lifecycle is demonstrated against a staging Play app without an untracked or duplicate write.

### 3. Clean Linux Host Deployment

- [ ] Provision a clean Linux VM with Docker and Compose.
- [ ] Configure private TLS ingress or VPN access.
- [ ] Generate independent proxy, webhook, admin, and viewer secrets.
- [ ] Mount a sanitized app catalog and least-privilege provider credentials.
- [ ] Start the Compose stack from a clean checkout.
- [ ] Verify API, scheduler, proxy, and persistent volume health.
- [ ] Verify unauthenticated requests are rejected.
- [ ] Verify viewer reads succeed and viewer mutations fail.
- [ ] Verify admin mutations remain blocked in read-only mode.
- [ ] Restart the host and confirm scheduler/database recovery.
- [ ] Create an online SQLite backup.
- [ ] Export the backup to encrypted off-host storage.
- [ ] Restore the backup onto a blank host.
- [ ] Perform one pinned-image upgrade.
- [ ] Perform one application rollback to the prior version.

**Done when:** a clean host can be installed, restarted, upgraded, rolled back, backed up, and restored using only the operator runbook.

## P1: Lifecycle Reliability

### 4. Durable Commands And Revisions

- [ ] Add immutable experiment revisions.
- [ ] Invalidate approval whenever proposal content changes.
- [ ] Add command IDs and `Idempotency-Key` support.
- [ ] Add optimistic revision checks to mutation commands.
- [ ] Add append-only experiment lifecycle events.
- [ ] Add execution attempts with lease owner and lease expiry.
- [ ] Add a unique command constraint to prevent duplicate execution.
- [ ] Add a durable notification outbox for Telegram and operator alerts.
- [ ] Add restart recovery for expired execution leases.

**Done when:** duplicate commands, worker restarts, and retried requests produce at most one external write.

### 5. Operator Reconciliation

- [ ] Add an explicit `reconciliation_required` lifecycle state.
- [ ] Store expected pre-state and expected post-state hashes.
- [ ] Retry remote reads, never uncertain writes.
- [ ] Show expected, previous, and current remote listing in JMIP.
- [ ] Add operator actions to confirm success, confirm rollback, or escalate.
- [ ] Block conflicting writes while reconciliation is unresolved.
- [ ] Export reconciliation evidence in the support bundle.

**Done when:** crashes before, during, and after a provider write always lead to a deterministic recoverable state.

### 6. Telegram Approval Integration

- [ ] Route Telegram approvals through `ExperimentLifecycle` commands.
- [ ] Bind each callback to experiment ID and immutable revision.
- [ ] Include a one-time nonce and expiry.
- [ ] Record Telegram chat/user identity as the approval actor.
- [ ] Reject replayed, expired, or revision-mismatched callbacks.
- [ ] Prevent old messages from approving edited proposals.

**Done when:** dashboard and Telegram approvals obey the same state machine, policy, and audit trail.

## P1: Statistical Quality

### 7. Evaluation Safeguards

- [ ] Add absolute and relative effect confidence intervals.
- [ ] Add Fisher's exact test for sparse cells.
- [ ] Persist evaluator name and version.
- [ ] Define predeclared evaluation checkpoints.
- [ ] Prevent unbounded daily significance peeking.
- [ ] Add minimum visitor and install thresholds per app/category.
- [ ] Add consecutive-period requirements for automatic safety rollback.
- [ ] Separate a below-target result from demonstrated harmful degradation.
- [ ] Add contamination detection for concurrent listing changes.
- [ ] Add contamination detection for material acquisition-mix changes.
- [ ] Version reevaluations when Play reports are corrected late.

**Done when:** every verdict can be reproduced from persisted periods, counts, method, thresholds, and evaluator version.

### 8. Measurement Provenance

- [ ] Persist provider report timestamps separately from ingestion timestamps.
- [ ] Record expected and actual source latency.
- [ ] Detect missing and corrected report days.
- [ ] Preserve locale, country, and traffic-source dimensions.
- [ ] Preserve native units and metric definitions.
- [ ] Link displayed rates to numerator and denominator evidence.
- [ ] Mark carried-forward values with their original timestamps.
- [ ] Prevent stale data from receiving a fresh snapshot timestamp.

**Done when:** every dashboard metric can be traced to its provider, period, counts, freshness, and transformation.

## P1: Data And Integrations

### 9. Real Play Vitals

- [ ] Implement crash and ANR data through the Play Developer Reporting API.
- [ ] Store vitals scan history and source timestamps.
- [ ] Add stale/unavailable vitals states.
- [ ] Validate thresholds against a staging app.
- [ ] Test emergency-brake activation and recovery.
- [ ] Enable automatic vitals brakes only after staging validation.

**Done when:** crash/ANR safety decisions are based on observed provider data rather than placeholders.

### 10. RevenueCat To FCM Identity

- [ ] Stop treating RevenueCat `app_user_id` as an FCM token.
- [ ] Define an authoritative subscriber-to-device-token or segment mapping.
- [ ] Handle users with multiple devices and expired tokens.
- [ ] Add opt-out and consent handling.
- [ ] Add delivery receipts and conversion attribution.
- [ ] Keep push execution disabled until mapping and consent are verified.

**Done when:** a verified RevenueCat event can target the intended opted-in device or segment without exposing subscriber identifiers.

### 11. True GA4 Journey Evidence

- [ ] Separate declared journeys from observed event frequency.
- [ ] Stop labeling event-count order as an observed user path.
- [ ] Add BigQuery or exported event-sequence ingestion.
- [ ] Construct real ordered paths using user/session/event timestamps.
- [ ] Add path coverage and source-latency metadata.
- [ ] Mark frequency-only views clearly when sequence data is unavailable.

**Done when:** JMIP distinguishes declared flow, aggregate event frequency, and observed user sequence.

### 12. Revenue Accuracy

- [ ] Add explicit App Store vendor configuration.
- [ ] Preserve provider-native currency and proceeds fields.
- [ ] Use dated FX rates instead of static conversion assumptions.
- [ ] Distinguish gross revenue, developer proceeds, MRR, and estimated profit.
- [ ] Prevent overlapping RevenueCat/store/GA4 periods from being summed twice.
- [ ] Reconcile source differences and show variance in JMIP.

**Done when:** revenue totals have explicit definitions, periods, currencies, source precedence, and reconciliation evidence.

## P1: Product Operations

### 13. Onboarding Wizard

- [ ] Add safe app create, archive, and remove operations.
- [ ] Test connector credentials and required permissions.
- [ ] Discover accessible AdMob apps.
- [ ] Discover GA4 properties and streams.
- [ ] Discover RevenueCat projects/apps.
- [ ] Detect GCS Play report availability.
- [ ] Confirm cross-source app mappings with the operator.
- [ ] Show initial history backfill progress.
- [ ] Separate read readiness from write readiness.
- [ ] Require a successful rollback drill before enabling `auto_low_risk`.

**Done when:** an operator can add an app and understand every missing capability without editing JSON manually.

### 14. Capability And Data Health Views

- [ ] Add per-app connector capability probes.
- [ ] Display read, write, and rollback readiness separately.
- [ ] Display last successful synchronization and covered source date.
- [ ] Display missing periods, failures, retries, and safe error codes.
- [ ] Add manual connector retry.
- [ ] Add backfill progress.
- [ ] Add database size, disk health, and backup age.
- [ ] Add scheduler queue and execution-lease status.

**Done when:** the dashboard never equates configured credentials with a healthy connection.

### 15. Observability

- [ ] Add request and correlation IDs across API, scheduler, lifecycle, and MCP calls.
- [ ] Emit structured production JSON logs.
- [ ] Add metrics for source lag, sync failures, retries, and execution states.
- [ ] Add scheduler heartbeat alerts.
- [ ] Add centralized exception reporting.
- [ ] Expand action-log argument redaction.
- [ ] Add log retention and support-bundle export.

**Done when:** a failed sync or experiment can be diagnosed from correlation ID and redacted evidence without direct database access.

## P2: Internal Dogfood

- [ ] Run one Android app in `recommend_only` for 14 days.
- [ ] Maintain at least 95% source freshness across scheduled periods.
- [ ] Review at least five server-owned proposals.
- [ ] Record structured reasons for rejected proposals.
- [ ] Complete two manual staging experiments.
- [ ] Complete one rollback drill.
- [ ] Verify every displayed metric has provenance.
- [ ] Measure operator time from diagnosis to decision.

**Exit gate:** zero duplicate or untracked writes and complete evidence for every lifecycle event.

## P2: Design-Partner Beta

- [ ] Recruit two Android-first portfolio operators or agencies.
- [ ] Deploy one isolated managed instance per partner.
- [ ] Begin every app in `recommend_only`.
- [ ] Complete weekly evidence reviews.
- [ ] Measure proposal acceptance, rejection reasons, source downtime, and support time.
- [ ] Enable `manual` only after write-readiness and rollback drills.
- [ ] Complete at least ten verified Play metadata executions across partners.
- [ ] Maintain 100% rollback snapshot coverage.
- [ ] Publish case studies only from period-correct concluded experiments.

**Exit gate:** both partners can understand proposals, approve safely, export evidence, and restore from backup without engineer interpretation.

## P2: Auto-Low-Risk Pilot

- [ ] Select one partner with at least five successful manual executions.
- [ ] Obtain explicit opt-in for `auto_low_risk`.
- [ ] Configure per-app and per-deployment execution caps.
- [ ] Verify immediate downgrade and emergency-brake controls.
- [ ] Review every automatic decision weekly.
- [ ] Complete at least five automatic executions.
- [ ] Confirm no policy escape, duplicate write, unresolved remote state, or missing audit event.

**Exit gate:** low-risk automation is demonstrably safer and faster than manual execution without reducing evidence quality.

## Documentation And Release Hygiene

- [ ] Remove stale claims that unfinished integrations are complete.
- [ ] Publish exact metric definitions and source-lag expectations.
- [ ] Document credentials, rotation, and revocation.
- [ ] Document incident response and emergency-brake recovery.
- [ ] Document clean install, upgrade, rollback, backup, and restore.
- [ ] Document staging versus production credential scopes.
- [ ] Add a release checklist and design-partner support escalation path.

## Explicitly Out Of Scope For This Beta

- Multi-tenant SaaS control plane
- Organization billing and SSO directory synchronization
- Kubernetes solely for anticipated scale
- Autonomous releases and rollout changes
- Automated paywall or pricing changes
- Paid-UA budget automation
- iOS storefront writes
- Firebase Remote Config writes
- Native concurrent A/B assignment
- Causal claims from aggregate GA4 event ordering

## Verification Commands

```bash
# Python CI-equivalent checks
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/
uv run pytest tests/ --ignore=tests/test_integration.py -v --cov=src --cov-report=term-missing
uv build

# Frontend
npm --prefix frontend ci
npm --prefix frontend run test
npm --prefix frontend run lint
npm --prefix frontend run build
npm --prefix frontend audit

# Deployment syntax/config
sh -n deploy/load-secrets.sh deploy/scheduler-read-only-guard.sh deploy/db-tools.sh
docker compose config --quiet
docker compose build --pull
docker compose up -d --wait
docker compose ps

# Backup and restore tools
docker compose --profile tools run --rm backup backup
docker compose --profile tools run --rm backup list
# Stop API and scheduler before restore, then:
CONFIRM_RESTORE=yes docker compose --profile tools run --rm backup restore <backup-file>
```

## Recommended Execution Order

1. Credential sanitation and rotation
2. Live staging Play Store lifecycle drill
3. Clean Linux deployment and upgrade/restore drill
4. Durable command, revision, lease, and reconciliation layer
5. Statistical safeguards and measurement provenance
6. Real Play vitals and capability health
7. Internal 14-day dogfood
8. Two managed design partners
9. Manual production beta
10. Opt-in auto-low-risk pilot
