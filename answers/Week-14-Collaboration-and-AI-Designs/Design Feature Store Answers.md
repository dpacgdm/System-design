# Answer Key - Design Feature Store

> Open only after attempting the learner file questions.

This key is written for principal/staff-level self-review.
A passing answer should name the irreversible decisions, trust boundaries, highest-amplification actors, unit economics, and smallest safe blast-radius boundary.
It should also say what to turn off first during an incident without corrupting the correctness-critical path.

## Principal Model Answer - What Excellent Looks Like

1. Defines registry, offline store, online store, and materialization paths.
2. Explains point-in-time joins and training-serving skew.
3. Monitors freshness, nulls, drift, and online latency.
4. Treats backfills as risky production changes.
5. Provides model fallback/default strategy with owner approval.

## Ops Sim / Incident Model Answer

### Freshness degradation diagnosis

1. Recommendation CTR dropped while model binary was unchanged, pointing to feature data, not model code.
2. user_7d_click was 45 minutes stale versus 5-minute SLA, so ranking used old engagement signals.
3. Flink checkpoint failures prevented durable progress and caused replay pressure.
4. DynamoDB throttled a hot partition, likely from skewed entity keys or high-fanout materialization.
5. Compare fresh offline recomputation against online store values.

### Mitigation

1. Freeze new feature/backfill jobs and identify the hot feature/entity key.
2. Increase or isolate DynamoDB capacity for the hot feature view if key design is still safe.
3. Route affected recommender to fallback model/default feature set or last-known-good snapshot.
4. Restart Flink from a known checkpoint only after hot-partition throttling is controlled.
5. Backfill missed windows in order and validate distribution before full traffic.

### Prevention

1. Per-feature freshness SLO and stale-value circuit breaker.
2. Hot-key detection before materialization rollout.
3. Backfill admission control with tenant budgets.
4. Feature registry requires owner, TTL, default semantics, and model dependency graph.
5. Shadow compare online vs offline feature distributions continuously.

---

## Design Gates (mandatory) - Principal-Depth Model Responses

### Gate 1 - Authn/z trust boundary

1. Principal inventory: model serving service, data scientists, feature registry admins, stream/batch materialization jobs, offline training jobs, online store, tenants/teams, support/admin actors
2. First untrusted boundary: feature serving API and registry API before online/offline stores
3. Final authorization decision: Feature registry policy and serving API entitlement by model/team/tenant/feature view
4. Accepted identity artifacts: workload identity for model serving and jobs, user SSO for registry, scoped tokens for notebooks, admin break-glass token
5. Service-to-service trust: mTLS/SPIFFE workload identity plus short-lived service tokens
6. Public clients never choose tenant/user/object IDs without server-side policy checks.
7. Admin/support access requires break-glass approval, reason codes, scoped duration, and immutable audit logs.
8. Background workers carry job identity and original actor context where user intent matters.
9. Capability or signed URL tokens are scoped to one object, operation, expiry, and content hash where applicable.
10. Identity or policy outage behavior: serving of approved cached feature values may continue within TTL; feature registration, schema changes, backfills, and cross-tenant reads fail closed
11. Read-only degraded mode is acceptable only for explicitly public or previously authorized cached data.
12. Writes, deletes, money movement, admin actions, and privacy-sensitive reads fail closed.
13. Audit events include actor, subject, tenant/context, decision, policy version, request ID, and source IP/device.
14. Cross-region failover preserves auth state; it never bypasses policy to restore availability.
15. A good answer draws this trust boundary before drawing caches, queues, or databases.
16. Model summary: The registry is the control plane; online/offline stores enforce the same feature, entity, and tenant policy.

### Gate 2 - Abuse and misuse

1. Highest amplification actor: stream materialization or backfill job writing hot entity keys into online store, plus model serving fan-out requesting many features per inference
2. Authenticated abuse surfaces: backfills, feature registration, online lookups, notebook exports, stream replays, entity joins, training set generation
3. Quota dimensions: per-team feature views, per-model lookup QPS, per-entity hot key, per-backfill bytes, per-DynamoDB partition, per-offline query, global materialization budget
4. Global safety caps are separate from per-principal quotas so one bug cannot consume the fleet.
5. Entity-key limits protect hot keys even when all callers are legitimate.
6. Worker concurrency limits protect downstream stores from replay storms and fan-out storms.
7. Retry budgets are finite, jittered, and tied to user intent or idempotency keys.
8. Retry hazard: failed checkpoints replaying hot-partition writes and model serving retrying feature vectors during online-store throttling
9. Telemetry separating flash crowd from abuse: feature freshness, null rate, distribution drift, online p99, DynamoDB throttle by key, Flink checkpoint duration, backfill bytes, registry change rate
10. Organic spikes preserve normal identity diversity; attacks show skewed principals, IPs, clients, or entities.
11. Abuse controls emit allow/deny/throttle decisions into a stream suitable for forensics.
12. Degradation sheds optional work before it rejects correctness-critical operations.
13. Runbooks say when to pause producers, disable retries, or drop optional enrichments.
14. A good answer includes both prevention and incident-time containment.
15. A weak answer only says add rate limiting without keys, budgets, or kill switches.
16. Model summary: ML teams can overload shared serving by backfills or hot features; governance includes runtime capacity, not only schema review.

### Gate 3 - Multi-tenant isolation

1. Tenancy model: team/model tenant, feature view, entity keyspace, offline dataset, online table, environment
2. Tenant/context propagation: tenant/team, model_id, feature_view, entity_key, event_time, materialization job_id, and request_id in registry, Kafka, DynamoDB, offline store, and logs
3. Shared resource reservations: per-model QPS, per-feature write capacity, per-team backfill slots, online hot partition budgets, offline warehouse queues, stream processor slots
4. Every cache key, queue message, object prefix, metric label, and support export carries tenant/context explicitly.
5. Missing tenant/context is a policy error, not a default-to-global behavior.
6. Async jobs include context in the payload and in the worker authorization decision.
7. Support tools filter by tenant/context server-side and log the exact export scope.
8. Noisy-neighbor control: disable one feature view, freeze one backfill, serve default for one model, move hot feature to dedicated table, or route one tenant to stale cache
9. Large tenants or hot entities can be isolated into dedicated shards/cells/topics without global migration.
10. Backfills and replays run in tenant-scoped lanes with byte and concurrency budgets.
11. Observability cardinality is bounded so one tenant cannot bankrupt metrics ingestion.
12. Isolation test: team A cannot retrieve B features through online lookup, offline training join, notebook export, registry browse, or logs
13. Disaster recovery restores tenant boundaries, not only bytes.
14. A good answer names logical isolation and physical capacity isolation.
15. A weak answer says tenant_id column and stops there.
16. Model summary: Feature view and team/model tenant are boundaries; point-in-time correctness requires event-time context in every async path.

### Gate 4 - Unit cost at target scale

1. Business unit: one feature vector served for one model inference plus one materialized feature update
2. Rough unit-cost model: online lookup fan-out plus write/materialization plus offline scans for training; high-cardinality features and backfills dominate peaks
3. Dominant line items: DynamoDB/Redis online ops, Flink/Kinesis, offline warehouse scans, object storage, feature monitoring, backfill compute, model-serving retries
4. Include replication, idle headroom, cross-AZ/region transfer, observability, and replay capacity.
5. Separate fixed control-plane cost from variable data-plane cost.
6. Track p50 and p99 cost because tail work often drives autoscaling and queue depth.
7. Chargeback/showback attributes cost by tenant/context, feature, endpoint, and deploy version.
8. Cost alert before margin/SLO breach: cost per 1,000 feature vectors served and materialization cost per feature view by team/model
9. Capacity planning includes event-day peak multiplier, not only daily average.
10. Cost regressions need rollback criteria just like latency regressions.
11. Graceful cost reduction: serve stale within exception, drop optional features to defaults, pause backfills, reduce monitoring sample rate, route low-tier models to cached vectors; never leak future data into training
12. Never reduce cost by weakening correctness, auth, audit, or durability guarantees.
13. Cold storage, compaction, tiering, sampling, and caching are explicit levers with owners.
14. A good answer can defend an order-of-magnitude number on a whiteboard.
15. A weak answer lists cloud products without pricing the business unit.
16. Model summary: Online latency and offline point-in-time scans are different cost centers, both attributed to feature owners.

### Gate 5 - Failure blast radius

1. Smallest intended failure boundary: feature view, entity key partition, online table, materialization job, model/tenant, region
2. Shared dependencies between critical and optional paths: online store shared by many models, stream processors shared by feature views, registry shared by teams, offline warehouse shared by training jobs
3. Fail closed: feature definitions/schema changes, cross-tenant reads, backfills without approval, training data exports
4. Serve stale or degraded: online feature values within explicit TTL and model fallback defaults
5. Disable first: non-critical features, backfills, monitoring enrichment, low-tier models, large training set generation
6. Runbook hazard that widens blast radius: global backfill replay, deleting online table data, changing default feature values without model owner approval, or disabling freshness alerts
7. Bulkheads separate user-facing serving from analytics, backfill, replay, and support tooling.
8. Feature flags are scoped by cell/region/tenant/entity, with a global kill only for known-safe toggles.
9. Queues have dead-letter and replay throttles; replay is never unbounded during recovery.
10. Caches have namespace-level invalidation; global flushes require incident commander approval.
11. Autoscaling must not scale a bad retry loop faster than dependencies can absorb it.
12. Game day: 45-minute stale user_7d_click, Flink checkpoint failure, DynamoDB hot partition, CTR drop, and model fallback validation
13. Alerts fire on leading indicators inside the boundary before customers see platform-wide impact.
14. A good answer says what remains working when one shard/cell/topic fails.
15. A weak answer treats multi-region replication as a substitute for blast-radius design.
16. Model summary: One stale/hot feature should degrade one model or feature view, not all inference tenants.

---

## Evaluator Rubric and Red Flags

1. Names the core correctness invariant for online/offline feature store: training and serving use the same feature definition with point-in-time correctness offline and bounded freshness online
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

1. Treating caches, queues, or CDN as the source of truth when online/offline feature store needs durable reconciliation.
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

1. Verify dashboards expose user-impact SLOs for online/offline feature store.
2. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
3. Verify the runbook has a rollback step and a separate reconciliation step.
4. Verify each queue or stream has bounded retry and dead-letter handling.
5. Verify every emergency command is scoped to the smallest safe boundary.
6. Verify post-incident cleanup drains backlog without violating customer promises.
7. Verify schema/config changes cannot bypass review or automated policy checks.
8. Verify tenant/context labels are present in logs without leaking secrets or PII.
9. Verify load tests include skewed traffic, not only uniform distributions.
10. Verify cost dashboards break down the business unit by feature and tenant/context.
11. Verify dashboards expose user-impact SLOs for online/offline feature store.
12. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
13. Verify the runbook has a rollback step and a separate reconciliation step.
14. Verify each queue or stream has bounded retry and dead-letter handling.
15. Verify every emergency command is scoped to the smallest safe boundary.
16. Verify post-incident cleanup drains backlog without violating customer promises.
17. Verify schema/config changes cannot bypass review or automated policy checks.
18. Verify tenant/context labels are present in logs without leaking secrets or PII.
19. Verify load tests include skewed traffic, not only uniform distributions.
20. Verify cost dashboards break down the business unit by feature and tenant/context.
21. Verify dashboards expose user-impact SLOs for online/offline feature store.
22. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
23. Verify the runbook has a rollback step and a separate reconciliation step.
24. Verify each queue or stream has bounded retry and dead-letter handling.
25. Verify every emergency command is scoped to the smallest safe boundary.
26. Verify post-incident cleanup drains backlog without violating customer promises.
27. Verify schema/config changes cannot bypass review or automated policy checks.
28. Verify tenant/context labels are present in logs without leaking secrets or PII.
29. Verify load tests include skewed traffic, not only uniform distributions.
30. Verify cost dashboards break down the business unit by feature and tenant/context.
31. Verify dashboards expose user-impact SLOs for online/offline feature store.
32. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
33. Verify the runbook has a rollback step and a separate reconciliation step.
34. Verify each queue or stream has bounded retry and dead-letter handling.
35. Verify every emergency command is scoped to the smallest safe boundary.
36. Verify post-incident cleanup drains backlog without violating customer promises.

