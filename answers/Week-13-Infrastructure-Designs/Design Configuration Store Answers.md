# Answer Key - Design Configuration Store

> Open only after attempting the learner file questions.

This key is written for principal/staff-level self-review.
A passing answer should name the irreversible decisions, trust boundaries, highest-amplification actors, unit economics, and smallest safe blast-radius boundary.
It should also say what to turn off first during an incident without corrupting the correctness-critical path.

## Principal Model Answer - What Excellent Looks Like

1. Uses Raft/etcd for small critical metadata, not blob storage.
2. Enforces object size and watch scope.
3. Plans snapshot, compaction, and defrag.
4. Separates API server auth from etcd peer/client trust.
5. Understands watch amplification and apiserver cache behavior.

## Ops Sim / Incident Model Answer

### Root cause chain

1. Compaction missed or was disabled, so revision history grew until DB quota pressure.
2. Large ConfigMaps accelerated storage growth and fsync cost.
3. Fifty controllers watching / amplified every object change into huge watch traffic.
4. API server timeouts caused reconnect/relist loops, increasing load while the quorum was degraded.

### Immediate recovery

1. Identify and stop rogue broad watchers first.
2. Take snapshot before destructive maintenance.
3. Compact old revisions and defrag members one at a time, respecting quorum.
4. Delete or migrate oversized ConfigMaps after policy approval.
5. Raise quota only after reclaiming space and validating disk headroom.

### Long-term fixes

1. Auto-compaction with retention appropriate to watch lag.
2. Admission policy rejecting large ConfigMaps/Secrets and broad watch permissions.
3. Controller guidelines requiring scoped informers.
4. DB size, fsync, watch fan-out, and compaction-lag alerts.
5. Dedicated prod etcd with fast disks and tested restore drills.

---

## Design Gates (mandatory) - Principal-Depth Model Responses

### Gate 1 - Authn/z trust boundary

1. Principal inventory: kubectl users, service accounts, controllers, apiservers, admission webhooks, etcd members, backup/restore jobs, cluster admins
2. First untrusted boundary: Kubernetes API server or config-store API before Raft/etcd quorum
3. Final authorization decision: API server RBAC/admission plus etcd client cert policy for control-plane components
4. Accepted identity artifacts: user cert/OIDC token, service-account JWT, mTLS client cert for apiservers/etcd peers, job identity for backup/compaction
5. Service-to-service trust: mTLS/SPIFFE workload identity plus short-lived service tokens
6. Public clients never choose tenant/user/object IDs without server-side policy checks.
7. Admin/support access requires break-glass approval, reason codes, scoped duration, and immutable audit logs.
8. Background workers carry job identity and original actor context where user intent matters.
9. Capability or signed URL tokens are scoped to one object, operation, expiry, and content hash where applicable.
10. Identity or policy outage behavior: mutating writes and broad watches fail closed; existing pods continue with cached config; narrow read-only requests may serve from apiserver cache if policy permits
11. Read-only degraded mode is acceptable only for explicitly public or previously authorized cached data.
12. Writes, deletes, money movement, admin actions, and privacy-sensitive reads fail closed.
13. Audit events include actor, subject, tenant/context, decision, policy version, request ID, and source IP/device.
14. Cross-region failover preserves auth state; it never bypasses policy to restore availability.
15. A good answer draws this trust boundary before drawing caches, queues, or databases.
16. Model summary: Clients should never talk to etcd directly; API server authn/z and admission protect object scope before consensus storage is touched.

### Gate 2 - Abuse and misuse

1. Highest amplification actor: broad LIST/WATCH clients and controllers watching / that multiply every revision to many consumers
2. Authenticated abuse surfaces: large ConfigMaps/Secrets, broad watches, rapid update loops, admission bypass, backup/restore jobs, compaction-disabled history
3. Quota dimensions: per-namespace object count/size, per-service-account watch count, per-prefix QPS, per-controller event budget, DB quota, global watch fan-out cap
4. Global safety caps are separate from per-principal quotas so one bug cannot consume the fleet.
5. Entity-key limits protect hot keys even when all callers are legitimate.
6. Worker concurrency limits protect downstream stores from replay storms and fan-out storms.
7. Retry budgets are finite, jittered, and tied to user intent or idempotency keys.
8. Retry hazard: controllers reconnecting broad watches during apiserver/etcd latency and replaying all events, compounding fan-out
9. Telemetry separating flash crowd from abuse: watch events/sec by principal, DB size, revision growth, compaction lag, ConfigMap size, apiserver watch cache churn, leader fsync latency
10. Organic spikes preserve normal identity diversity; attacks show skewed principals, IPs, clients, or entities.
11. Abuse controls emit allow/deny/throttle decisions into a stream suitable for forensics.
12. Degradation sheds optional work before it rejects correctness-critical operations.
13. Runbooks say when to pause producers, disable retries, or drop optional enrichments.
14. A good answer includes both prevention and incident-time containment.
15. A weak answer only says add rate limiting without keys, budgets, or kill switches.
16. Model summary: A well-meaning controller can be the abuser; watch scope and object size limits are core safety controls.

### Gate 3 - Multi-tenant isolation

1. Tenancy model: cluster, namespace, API group/resource, service account, control-plane component, etcd prefix
2. Tenant/context propagation: cluster_id, namespace, resource, service_account, controller_name, revision, and request_id in API audit logs, watch streams, backups, and metrics
3. Shared resource reservations: etcd quota, watch cache memory, apiserver inflight requests, controller concurrency, backup bandwidth, compaction/defrag windows
4. Every cache key, queue message, object prefix, metric label, and support export carries tenant/context explicitly.
5. Missing tenant/context is a policy error, not a default-to-global behavior.
6. Async jobs include context in the payload and in the worker authorization decision.
7. Support tools filter by tenant/context server-side and log the exact export scope.
8. Noisy-neighbor control: disable one controller, block one namespace/object type, pause one admission webhook, or isolate a cluster/apiserver cell
9. Large tenants or hot entities can be isolated into dedicated shards/cells/topics without global migration.
10. Backfills and replays run in tenant-scoped lanes with byte and concurrency budgets.
11. Observability cardinality is bounded so one tenant cannot bankrupt metrics ingestion.
12. Isolation test: namespace RBAC denies direct API, watch, export, audit-log, and backup restore access to other namespaces or secret data
13. Disaster recovery restores tenant boundaries, not only bytes.
14. A good answer names logical isolation and physical capacity isolation.
15. A weak answer says tenant_id column and stops there.
16. Model summary: Namespace/resource scope is the tenant boundary, while controller watch scope is the operational blast-radius boundary.

### Gate 4 - Unit cost at target scale

1. Business unit: one strongly consistent config write or watch-delivered revision
2. Rough unit-cost model: unit cost includes Raft quorum fsync, revision history, watch fan-out, apiserver cache, backup retention, and compaction/defrag I/O
3. Dominant line items: NVMe/IOPS, apiserver CPU/memory, watch bandwidth, backup storage, audit logs, idle quorum nodes
4. Include replication, idle headroom, cross-AZ/region transfer, observability, and replay capacity.
5. Separate fixed control-plane cost from variable data-plane cost.
6. Track p50 and p99 cost because tail work often drives autoscaling and queue depth.
7. Chargeback/showback attributes cost by tenant/context, feature, endpoint, and deploy version.
8. Cost alert before margin/SLO breach: cost and latency per committed revision plus watch fan-out events per revision
9. Capacity planning includes event-day peak multiplier, not only daily average.
10. Cost regressions need rollback criteria just like latency regressions.
11. Graceful cost reduction: reject large objects, pause noisy controllers, narrow watches, serve cached reads, delay non-critical controllers; never skip quorum for writes
12. Never reduce cost by weakening correctness, auth, audit, or durability guarantees.
13. Cold storage, compaction, tiering, sampling, and caching are explicit levers with owners.
14. A good answer can defend an order-of-magnitude number on a whiteboard.
15. A weak answer lists cloud products without pricing the business unit.
16. Model summary: The hidden cost is not one write; it is one revision multiplied through every broad watch and retained until compaction.

### Gate 5 - Failure blast radius

1. Smallest intended failure boundary: cluster, namespace, resource prefix, watch stream, apiserver cell, etcd member/quorum
2. Shared dependencies between critical and optional paths: etcd shared by scheduling, controllers, secrets, config, and API discovery
3. Fail closed: writes, secrets, RBAC changes, lease/lock mutations, admin restore
4. Serve stale or degraded: controller caches, read-only config views, existing pod env/config until restart
5. Disable first: rogue broad watchers, large ConfigMap writers, non-critical controllers, audit verbosity spikes, backup jobs
6. Runbook hazard that widens blast radius: raising etcd quota before compaction/defrag, deleting data without snapshot, or globally restarting all controllers
7. Bulkheads separate user-facing serving from analytics, backfill, replay, and support tooling.
8. Feature flags are scoped by cell/region/tenant/entity, with a global kill only for known-safe toggles.
9. Queues have dead-letter and replay throttles; replay is never unbounded during recovery.
10. Caches have namespace-level invalidation; global flushes require incident commander approval.
11. Autoscaling must not scale a bad retry loop faster than dependencies can absorb it.
12. Game day: DB quota and watch storm with one rogue controller, snapshot/compact/defrag recovery, and namespace-scoped throttling
13. Alerts fire on leading indicators inside the boundary before customers see platform-wide impact.
14. A good answer says what remains working when one shard/cell/topic fails.
15. A weak answer treats multi-region replication as a substitute for blast-radius design.
16. Model summary: Protect quorum and API writes by shedding watchers and oversized objects before changing consensus safety.

---

## Evaluator Rubric and Red Flags

1. Names the core correctness invariant for etcd/Kubernetes-style configuration store: each committed config revision is ordered, durable, authorized, and watch-delivered without allowing unbounded history or fan-out to kill the quorum
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

1. Treating caches, queues, or CDN as the source of truth when etcd/Kubernetes-style configuration store needs durable reconciliation.
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

1. Verify dashboards expose user-impact SLOs for etcd/Kubernetes-style configuration store.
2. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
3. Verify the runbook has a rollback step and a separate reconciliation step.
4. Verify each queue or stream has bounded retry and dead-letter handling.
5. Verify every emergency command is scoped to the smallest safe boundary.
6. Verify post-incident cleanup drains backlog without violating customer promises.
7. Verify schema/config changes cannot bypass review or automated policy checks.
8. Verify tenant/context labels are present in logs without leaking secrets or PII.
9. Verify load tests include skewed traffic, not only uniform distributions.
10. Verify cost dashboards break down the business unit by feature and tenant/context.
11. Verify dashboards expose user-impact SLOs for etcd/Kubernetes-style configuration store.
12. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
13. Verify the runbook has a rollback step and a separate reconciliation step.
14. Verify each queue or stream has bounded retry and dead-letter handling.
15. Verify every emergency command is scoped to the smallest safe boundary.
16. Verify post-incident cleanup drains backlog without violating customer promises.
17. Verify schema/config changes cannot bypass review or automated policy checks.
18. Verify tenant/context labels are present in logs without leaking secrets or PII.
19. Verify load tests include skewed traffic, not only uniform distributions.
20. Verify cost dashboards break down the business unit by feature and tenant/context.
21. Verify dashboards expose user-impact SLOs for etcd/Kubernetes-style configuration store.
22. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
23. Verify the runbook has a rollback step and a separate reconciliation step.
24. Verify each queue or stream has bounded retry and dead-letter handling.
25. Verify every emergency command is scoped to the smallest safe boundary.
26. Verify post-incident cleanup drains backlog without violating customer promises.
27. Verify schema/config changes cannot bypass review or automated policy checks.
28. Verify tenant/context labels are present in logs without leaking secrets or PII.
29. Verify load tests include skewed traffic, not only uniform distributions.
30. Verify cost dashboards break down the business unit by feature and tenant/context.
31. Verify dashboards expose user-impact SLOs for etcd/Kubernetes-style configuration store.
32. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
33. Verify the runbook has a rollback step and a separate reconciliation step.
34. Verify each queue or stream has bounded retry and dead-letter handling.
35. Verify every emergency command is scoped to the smallest safe boundary.
36. Verify post-incident cleanup drains backlog without violating customer promises.
37. Verify schema/config changes cannot bypass review or automated policy checks.


---
