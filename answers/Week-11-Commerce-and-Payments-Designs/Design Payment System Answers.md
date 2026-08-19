# Answer Key - Design Payment System

> Open only after attempting the learner file questions.

This key is written for principal/staff-level self-review.
A passing answer should name the irreversible decisions, trust boundaries, highest-amplification actors, unit economics, and smallest safe blast-radius boundary.
It should also say what to turn off first during an incident without corrupting the correctness-critical path.

## Principal Model Answer - What Excellent Looks Like

1. Uses idempotency keys scoped to cart/order intent.
2. Separates auth, capture, void, refund, and ledger journal entries.
3. Treats PSP webhooks as signed eventually consistent inputs.
4. Displays user status from ledger plus PSP reconciliation, not saga alone.
5. Requires manual scripts to be idempotent and state-checked.

## Ops Sim / Incident Model Answer

### Causal chain

1. Stripe timeout changed from 25s to 5s while Stripe p99 was above 6s.
2. Authorize calls timed out locally even though PSP often succeeded.
3. Mandatory reconcile was removed/disabled, so the saga compensated instead of checking PSP truth.
4. User message came from saga state and falsely said payment failed.
5. Retry used new order_id/idempotency_key, creating duplicate authorization risk.
6. Void script lacked capture-state/ledger checks and risked wrongful voids.

### Remediate order_7712

1. Retrieve PSP PaymentIntent and confirm status, amount, capture state, and idempotency metadata.
2. Query ledger journal by PSP reference and order/cart IDs.
3. Query inventory reservation history and decide whether to honor, re-reserve, substitute, or cancel with refund.
4. If fulfilling, capture the original intended auth idempotently and write CAPTURE ledger entries.
5. Backfill order record linked to PSP and ledger IDs.
6. Void duplicate auth only after confirming it is not captured and customer did not intend a second order.
7. Message the customer only after PSP and ledger agree.

### Stop bleeding and prevention

1. Rollback timeout and payment-api deploy.
2. Force reconcile_auth_mandatory=true and disable void_failed_sagas cron.
3. Open circuit breaker on PSP timeout spike and keep checkout in pending state.
4. Alert when PSP latency approaches configured timeout before local compensations begin.
5. Make timeout policy derived from PSP p99.99 plus margin.
6. Prevent feature flags from disabling reconciliation in production.
7. Add deploy checklist for idempotency-key semantics and PSP sandbox soak.

---

## Design Gates (mandatory) - Principal-Depth Model Responses

### Gate 1 - Authn/z trust boundary

1. Principal inventory: buyers, merchants, checkout service, payment API, ledger service, reconciliation workers, PSP/webhook sender, fraud service, support/admin actors, finance operators
2. First untrusted boundary: checkout/payment API edge and PSP webhook ingress
3. Final authorization decision: Payment service plus ledger policy; merchant/account policy for capture/refund; PSP signature validator for callbacks
4. Accepted identity artifacts: buyer session, merchant OAuth/API key, idempotency key, signed PSP webhook, workload identity for workers, break-glass admin token
5. Service-to-service trust: mTLS/SPIFFE workload identity plus short-lived service tokens
6. Public clients never choose tenant/user/object IDs without server-side policy checks.
7. Admin/support access requires break-glass approval, reason codes, scoped duration, and immutable audit logs.
8. Background workers carry job identity and original actor context where user intent matters.
9. Capability or signed URL tokens are scoped to one object, operation, expiry, and content hash where applicable.
10. Identity or policy outage behavior: authorizations, captures, refunds, voids, ledger writes, and support adjustments fail closed; status may show pending while reconciliation catches up
11. Read-only degraded mode is acceptable only for explicitly public or previously authorized cached data.
12. Writes, deletes, money movement, admin actions, and privacy-sensitive reads fail closed.
13. Audit events include actor, subject, tenant/context, decision, policy version, request ID, and source IP/device.
14. Cross-region failover preserves auth state; it never bypasses policy to restore availability.
15. A good answer draws this trust boundary before drawing caches, queues, or databases.
16. Model summary: The ledger is the authority for displayed payment state, reconciled against PSP truth; saga status alone is never user-visible truth.

### Gate 2 - Abuse and misuse

1. Highest amplification actor: checkout retry path that creates new orders/idempotency keys and reconciliation/void jobs that call PSP at scale
2. Authenticated abuse surfaces: payment attempts, refund APIs, webhook replay, manual void scripts, merchant batch capture, card testing, support adjustments
3. Quota dimensions: per-buyer/card/IP attempts, per-merchant PSP calls, per-order idempotency, per-webhook event, per-region PSP budget, global fraud/card-testing cap
4. Global safety caps are separate from per-principal quotas so one bug cannot consume the fleet.
5. Entity-key limits protect hot keys even when all callers are legitimate.
6. Worker concurrency limits protect downstream stores from replay storms and fan-out storms.
7. Retry budgets are finite, jittered, and tied to user intent or idempotency keys.
8. Retry hazard: retrying checkout with a new order_id and idempotency key after a false failure, causing duplicate auths
9. Telemetry separating flash crowd from abuse: auth/capture mismatch, PSP latency vs timeout, duplicate card fingerprint, idempotency-key reuse/miss, timeout compensation rate, refund/void spike
10. Organic spikes preserve normal identity diversity; attacks show skewed principals, IPs, clients, or entities.
11. Abuse controls emit allow/deny/throttle decisions into a stream suitable for forensics.
12. Degradation sheds optional work before it rejects correctness-critical operations.
13. Runbooks say when to pause producers, disable retries, or drop optional enrichments.
14. A good answer includes both prevention and incident-time containment.
15. A weak answer only says add rate limiting without keys, budgets, or kill switches.
16. Model summary: Money paths need idempotency and reconciliation as abuse controls; rate limits alone cannot prevent double auths or wrongful voids.

### Gate 3 - Multi-tenant isolation

1. Tenancy model: merchant/platform tenant, buyer account, PSP account, ledger partition, region, finance/support role
2. Tenant/context propagation: merchant_id, order_id, payment_intent_id, ledger_account, buyer_id, PSP event_id, and request_id propagate through DB, Kafka, ledger, webhooks, logs, and exports
3. Shared resource reservations: PSP call budgets, ledger write capacity, webhook worker lanes, merchant-specific queues, fraud model capacity, support adjustment limits
4. Every cache key, queue message, object prefix, metric label, and support export carries tenant/context explicitly.
5. Missing tenant/context is a policy error, not a default-to-global behavior.
6. Async jobs include context in the payload and in the worker authorization decision.
7. Support tools filter by tenant/context server-side and log the exact export scope.
8. Noisy-neighbor control: disable one merchant, pause one PSP lane, block one card fingerprint, freeze refund/capture for one account, or force pending status for one region
9. Large tenants or hot entities can be isolated into dedicated shards/cells/topics without global migration.
10. Backfills and replays run in tenant-scoped lanes with byte and concurrency budgets.
11. Observability cardinality is bounded so one tenant cannot bankrupt metrics ingestion.
12. Isolation test: merchant A cannot see/refund/export merchant B payments through API, cache, ledger report, support tool, or webhook replay
13. Disaster recovery restores tenant boundaries, not only bytes.
14. A good answer names logical isolation and physical capacity isolation.
15. A weak answer says tenant_id column and stops there.
16. Model summary: Merchant and ledger-account boundaries are hard security and accounting boundaries, not just reporting filters.

### Gate 4 - Unit cost at target scale

1. Business unit: one successful order payment lifecycle
2. Rough unit-cost model: unit cost includes PSP fees, fraud lookup, ledger write/read, webhook processing, reconciliation, support overhead, and disputed/failed-payment handling
3. Dominant line items: PSP interchange/processing fees, fraud/vendor calls, ledger storage, reconciliation jobs, observability/audit retention, chargeback operations
4. Include replication, idle headroom, cross-AZ/region transfer, observability, and replay capacity.
5. Separate fixed control-plane cost from variable data-plane cost.
6. Track p50 and p99 cost because tail work often drives autoscaling and queue depth.
7. Chargeback/showback attributes cost by tenant/context, feature, endpoint, and deploy version.
8. Cost alert before margin/SLO breach: cost per successful settled payment and PSP calls per successful checkout by merchant
9. Capacity planning includes event-day peak multiplier, not only daily average.
10. Cost regressions need rollback criteria just like latency regressions.
11. Graceful cost reduction: disable optional fraud enrichments only if risk-approved, hold status as pending, slow merchant batch operations, delay analytics; never skip ledger or reconciliation
12. Never reduce cost by weakening correctness, auth, audit, or durability guarantees.
13. Cold storage, compaction, tiering, sampling, and caching are explicit levers with owners.
14. A good answer can defend an order-of-magnitude number on a whiteboard.
15. A weak answer lists cloud products without pricing the business unit.
16. Model summary: The expensive unit is a safely settled payment with auditable ledger state and bounded PSP/vendor calls.

### Gate 5 - Failure blast radius

1. Smallest intended failure boundary: merchant, PSP lane, payment method, ledger partition, webhook topic, region/cell
2. Shared dependencies between critical and optional paths: PSP, ledger DB, fraud service, webhook workers, checkout UX, inventory reservation
3. Fail closed: captures/refunds/voids, ledger mutations, PSP webhooks with bad signatures, support money movement
4. Serve stale or degraded: payment status as pending, merchant dashboard lag, analytics/reports
5. Disable first: void cron, retry storms, optional fraud enrichment, merchant batch jobs, non-critical dashboards
6. Runbook hazard that widens blast radius: running void/refund scripts without joining PSP capture state and ledger entries; changing idempotency key semantics during incident
7. Bulkheads separate user-facing serving from analytics, backfill, replay, and support tooling.
8. Feature flags are scoped by cell/region/tenant/entity, with a global kill only for known-safe toggles.
9. Queues have dead-letter and replay throttles; replay is never unbounded during recovery.
10. Caches have namespace-level invalidation; global flushes require incident commander approval.
11. Autoscaling must not scale a bad retry loop faster than dependencies can absorb it.
12. Game day: PSP p99 exceeds timeout, reconcile worker disabled, duplicate retry, webhook delay, and manual remediation of one order
13. Alerts fire on leading indicators inside the boundary before customers see platform-wide impact.
14. A good answer says what remains working when one shard/cell/topic fails.
15. A weak answer treats multi-region replication as a substitute for blast-radius design.
16. Model summary: Keep a PSP or merchant incident from corrupting the ledger globally; pending is better than false failure or double charge.

---

## Evaluator Rubric and Red Flags

1. Names the core correctness invariant for payment authorization/capture/ledger system: no money movement is acknowledged without an idempotent ledger entry and reconciliation path to PSP truth
2. Quantifies the dominant scale driver instead of hand-waving capacity.
3. Explains why the fast path is safe under retry, failover, and partial dependency failure.
4. Shows the data lifecycle: hot serving, durable source of truth, compaction/tiering, and replay/repair.
5. Draws control plane and data plane separately where that separation matters.
6. Documents idempotency, deduplication, and ordering where duplicates or loss are unacceptable.
7. Includes observability tied to user impact, not only host metrics.
8. Provides a mitigation order that stops customer pain before root-cause cleanup.
9. States what is intentionally out of scope for V1 and why it is safe to defer.
10. Mentions cost and abuse as first-class design constraints.
11. Uses scoped kill switches rather than global toggles for unknown failure modes.
12. Protects support/admin paths with the same rigor as user-facing APIs.
13. Proves tenant/context isolation through tests and operational controls.
14. Connects incident symptoms to plausible root causes and rejects red herrings.
15. Leaves the system reconciled after rollback; rollback alone is rarely repair.

Common red flags:

1. Treating caches, queues, or CDN as the source of truth when payment authorization/capture/ledger system needs durable reconciliation.
2. Using average QPS when hot keys, celebrities, tenants, regions, prompts, or cells drive the p99.
3. Assuming authenticated users cannot be abusive.
4. Letting background jobs share unlimited capacity with user-serving paths.
5. Failing open on auth, payment, privacy, admin, or data-integrity paths.
6. Global cache flushes, unthrottled replays, or emergency shard changes during peak traffic.
7. No plan for stale data, duplicate events, delayed callbacks, or partial writes.
8. No explicit owner for policy, schema, quota, and configuration changes.
9. No evidence that the design was tested under the exact incident shape.
10. No cost metric at the same granularity as the scaling decision.

Minimum pass bar:

1. Can explain the happy path in under two minutes.
2. Can explain the top three failure modes in under two minutes.
3. Can state the primary data invariant without naming a cloud product.
4. Can point to the exact gate that catches the incident before production.
5. Can say which customer-visible feature is sacrificed first during overload.
6. Can say which action is never allowed during mitigation because it risks data loss or privacy breach.
7. Can produce one line of capacity math for the dominant workload.
8. Can name one blast-radius boundary and one game day that validates it.

---

## Additional Verification Checklist

1. Verify dashboards expose user-impact SLOs for payment authorization/capture/ledger system.
2. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
3. Verify the runbook has a rollback step and a separate reconciliation step.
4. Verify each queue or stream has bounded retry and dead-letter handling.
5. Verify every emergency command is scoped to the smallest safe boundary.
6. Verify post-incident cleanup drains backlog without violating customer promises.
7. Verify schema/config changes cannot bypass review or automated policy checks.
8. Verify tenant/context labels are present in logs without leaking secrets or PII.
9. Verify load tests include skewed traffic, not only uniform distributions.
10. Verify cost dashboards break down the business unit by feature and tenant/context.
11. Verify dashboards expose user-impact SLOs for payment authorization/capture/ledger system.
12. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
13. Verify the runbook has a rollback step and a separate reconciliation step.
14. Verify each queue or stream has bounded retry and dead-letter handling.
15. Verify every emergency command is scoped to the smallest safe boundary.
16. Verify post-incident cleanup drains backlog without violating customer promises.
17. Verify schema/config changes cannot bypass review or automated policy checks.
18. Verify tenant/context labels are present in logs without leaking secrets or PII.
19. Verify load tests include skewed traffic, not only uniform distributions.
20. Verify cost dashboards break down the business unit by feature and tenant/context.
21. Verify dashboards expose user-impact SLOs for payment authorization/capture/ledger system.
22. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
23. Verify the runbook has a rollback step and a separate reconciliation step.
24. Verify each queue or stream has bounded retry and dead-letter handling.
25. Verify every emergency command is scoped to the smallest safe boundary.
26. Verify post-incident cleanup drains backlog without violating customer promises.
27. Verify schema/config changes cannot bypass review or automated policy checks.
28. Verify tenant/context labels are present in logs without leaking secrets or PII.
29. Verify load tests include skewed traffic, not only uniform distributions.
30. Verify cost dashboards break down the business unit by feature and tenant/context.
31. Verify dashboards expose user-impact SLOs for payment authorization/capture/ledger system.


---
