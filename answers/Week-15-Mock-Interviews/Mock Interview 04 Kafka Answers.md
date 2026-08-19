# Answer Key - Mock Interview 04 Kafka

> Open only after attempting the learner file questions.

This key is written for principal/staff-level self-review.
A passing answer should name the irreversible decisions, trust boundaries, highest-amplification actors, unit economics, and smallest safe blast-radius boundary.
It should also say what to turn off first during an incident without corrupting the correctness-critical path.

## Principal Model Answer - What Excellent Looks Like

1. Explains log vs queue before saying Kafka.
2. Sizes partitions from throughput and ordering key.
3. Uses RF=3, min.insync.replicas=2, acks=all for critical data.
4. Separates retry/DLQ topics from main partitions.
5. Understands lag, rebalances, ISR, and replay economics.
6. Frames the answer in timed interview phases and calls out tradeoffs before implementation detail.

## Ops Sim / Incident Model Answer

### Interview narrative additions

1. Minute 0-5: clarify functional scope, scale, guarantees, and explicit non-goals.
2. Minute 5-12: do back-of-the-envelope math for the dominant workload and peak multiplier.
3. Minute 12-18: define API, state model, keys, and durable data ownership.
4. Minute 18-28: draw the architecture with control plane, data plane, and async paths.
5. Minute 28-40: deep dive into the system-specific bottlenecks, correctness invariants, and failure modes.
6. Minute 40-45: summarize V1, V2, metrics, and the top risks.

### Scoring guidance

1. A top answer states tradeoffs before naming technologies.
2. A top answer keeps one invariant central throughout the design.
3. A top answer ties capacity estimates to partitioning/sharding/cell boundaries.
4. A top answer has a graceful degradation path that preserves correctness.
5. A top answer handles abuse, tenancy, cost, and blast radius without prompting.

---

## Design Gates (mandatory) - Principal-Depth Model Responses

### Gate 1 - Authn/z trust boundary

1. Principal inventory: producers, consumers, brokers, controller/KRaft quorum, schema registry, connect jobs, stream processors, admins, tenant services
2. First untrusted boundary: Kafka ingress/load balancer or broker listener before SASL/mTLS authentication
3. Final authorization decision: Kafka ACL/authorizer and schema registry compatibility policy
4. Accepted identity artifacts: mTLS/SASL principal for producers/consumers, workload identity for Connect/Flink, admin token with scoped ACLs
5. Service-to-service trust: mTLS/SPIFFE workload identity plus short-lived service tokens
6. Public clients never choose tenant/user/object IDs without server-side policy checks.
7. Admin/support access requires break-glass approval, reason codes, scoped duration, and immutable audit logs.
8. Background workers carry job identity and original actor context where user intent matters.
9. Capability or signed URL tokens are scoped to one object, operation, expiry, and content hash where applicable.
10. Identity or policy outage behavior: produce/consume/admin operations fail closed if ACLs unavailable; consumers may continue from assigned partitions if already authorized and policy cache is valid
11. Read-only degraded mode is acceptable only for explicitly public or previously authorized cached data.
12. Writes, deletes, money movement, admin actions, and privacy-sensitive reads fail closed.
13. Audit events include actor, subject, tenant/context, decision, policy version, request ID, and source IP/device.
14. Cross-region failover preserves auth state; it never bypasses policy to restore availability.
15. A good answer draws this trust boundary before drawing caches, queues, or databases.
16. Model summary: Topic, group, transactional-id, and schema permissions are separate; a producer identity is not automatically allowed to consume or reset offsets.

### Gate 2 - Abuse and misuse

1. Highest amplification actor: producer burst or consumer group rebalance/lag that turns backlog into disk, network, and downstream DB pressure
2. Authenticated abuse surfaces: topic creation, high-cardinality partitions, large messages, offset reset, replay jobs, retry topics, schema changes, consumer scaling
3. Quota dimensions: per-principal produce/consume bytes, per-topic partitions, per-group members, per-tenant storage, per-transactional-id, broker network/disk caps, global replay budget
4. Global safety caps are separate from per-principal quotas so one bug cannot consume the fleet.
5. Entity-key limits protect hot keys even when all callers are legitimate.
6. Worker concurrency limits protect downstream stores from replay storms and fan-out storms.
7. Retry budgets are finite, jittered, and tied to user intent or idempotency keys.
8. Retry hazard: consumers timing out max.poll.interval and rejoining repeatedly, causing rebalance storms while producers continue ingest
9. Telemetry separating flash crowd from abuse: bytes in/out by principal, partition skew, produce throttling, group rebalances, lag derivative, ISR shrink, request queue, message size, DLQ growth
10. Organic spikes preserve normal identity diversity; attacks show skewed principals, IPs, clients, or entities.
11. Abuse controls emit allow/deny/throttle decisions into a stream suitable for forensics.
12. Degradation sheds optional work before it rejects correctness-critical operations.
13. Runbooks say when to pause producers, disable retries, or drop optional enrichments.
14. A good answer includes both prevention and incident-time containment.
15. A weak answer only says add rate limiting without keys, budgets, or kill switches.
16. Model summary: The platform isolates tenants by topic, quota, group, and replay budget; lag is debt and rollback does not erase it.

### Gate 3 - Multi-tenant isolation

1. Tenancy model: tenant topic namespace, ACL principal, consumer group, quota entity, broker rack/cell, schema subject
2. Tenant/context propagation: tenant/topic, principal, group.id, client.id, transaction.id, schema subject, request_id in logs, metrics, DLQ, and support tools
3. Shared resource reservations: broker disk/network, topic partitions, controller metadata, consumer group capacity, schema registry QPS, replay lanes
4. Every cache key, queue message, object prefix, metric label, and support export carries tenant/context explicitly.
5. Missing tenant/context is a policy error, not a default-to-global behavior.
6. Async jobs include context in the payload and in the worker authorization decision.
7. Support tools filter by tenant/context server-side and log the exact export scope.
8. Noisy-neighbor control: throttle one principal/topic, pause one producer, fence one transactional-id, block one consumer group, or move a tenant to dedicated cluster
9. Large tenants or hot entities can be isolated into dedicated shards/cells/topics without global migration.
10. Backfills and replays run in tenant-scoped lanes with byte and concurrency budgets.
11. Observability cardinality is bounded so one tenant cannot bankrupt metrics ingestion.
12. Isolation test: tenant cannot read other topics, reset other offsets, register incompatible schemas, consume DLQ, or view logs containing payloads
13. Disaster recovery restores tenant boundaries, not only bytes.
14. A good answer names logical isolation and physical capacity isolation.
15. A weak answer says tenant_id column and stops there.
16. Model summary: Topic namespace plus ACL/quota is the tenant boundary; consumer groups are independent but share broker disk/network.

### Gate 4 - Unit cost at target scale

1. Business unit: one produced event retained and consumed by one consumer group
2. Rough unit-cost model: event bytes times retention times replication plus consumer egress; fan-out to N consumer groups multiplies read/network cost
3. Dominant line items: broker NVMe, RF=3 storage, cross-AZ traffic, consumer egress, tiered storage, schema registry, observability, replay headroom
4. Include replication, idle headroom, cross-AZ/region transfer, observability, and replay capacity.
5. Separate fixed control-plane cost from variable data-plane cost.
6. Track p50 and p99 cost because tail work often drives autoscaling and queue depth.
7. Chargeback/showback attributes cost by tenant/context, feature, endpoint, and deploy version.
8. Cost alert before margin/SLO breach: cost per GB produced-retained-consumed and lag-drain cost per tenant/topic
9. Capacity planning includes event-day peak multiplier, not only daily average.
10. Cost regressions need rollback criteria just like latency regressions.
11. Graceful cost reduction: pause low-priority producers, reduce retention for non-critical topics, throttle replays, disable analytics consumers, route retries to retry topics; never enable unclean leader election for critical data
12. Never reduce cost by weakening correctness, auth, audit, or durability guarantees.
13. Cold storage, compaction, tiering, sampling, and caching are explicit levers with owners.
14. A good answer can defend an order-of-magnitude number on a whiteboard.
15. A weak answer lists cloud products without pricing the business unit.
16. Model summary: Retention and fan-out dominate cost; partition count is both throughput capacity and operational overhead.

### Gate 5 - Failure blast radius

1. Smallest intended failure boundary: topic, partition, consumer group, broker, rack/AZ, tenant namespace, cluster
2. Shared dependencies between critical and optional paths: broker disk/network shared by critical and analytics topics; DB downstream shared by consumers; controller metadata shared globally
3. Fail closed: ACL changes, produce with insufficient ISR on critical topics, schema-incompatible writes, offset reset by unauthorized actor
4. Serve stale or degraded: consumer lag for analytics, delayed materialized views, dashboards
5. Disable first: non-critical consumers, replay jobs, analytics producers, retry amplification, large-message topics
6. Runbook hazard that widens blast radius: global producer pause, unbounded replay, increasing max.poll.records without processing model, enabling unclean leader election, or deleting topics to free disk
7. Bulkheads separate user-facing serving from analytics, backfill, replay, and support tooling.
8. Feature flags are scoped by cell/region/tenant/entity, with a global kill only for known-safe toggles.
9. Queues have dead-letter and replay throttles; replay is never unbounded during recovery.
10. Caches have namespace-level invalidation; global flushes require incident commander approval.
11. Autoscaling must not scale a bad retry loop faster than dependencies can absorb it.
12. Game day: payment topic lag 45M, rollback leaves backlog, max.poll.records causes poll timeout, scale consumers to partitions, and drain under producer throttle
13. Alerts fire on leading indicators inside the boundary before customers see platform-wide impact.
14. A good answer says what remains working when one shard/cell/topic fails.
15. A weak answer treats multi-region replication as a substitute for blast-radius design.
16. Model summary: A consumer bug should stall one group and topic, not the broker fleet or other tenants.

---

## Evaluator Rubric and Red Flags

1. Names the core correctness invariant for Mock Interview 04 Kafka: events acknowledged with acks=all and min.insync.replicas are durably ordered within a partition and independently replayable by authorized groups
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

1. Treating caches, queues, or CDN as the source of truth when Mock Interview 04 Kafka needs durable reconciliation.
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

1. Verify dashboards expose user-impact SLOs for Mock Interview 04 Kafka.
2. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
3. Verify the runbook has a rollback step and a separate reconciliation step.
4. Verify each queue or stream has bounded retry and dead-letter handling.
5. Verify every emergency command is scoped to the smallest safe boundary.
6. Verify post-incident cleanup drains backlog without violating customer promises.
7. Verify schema/config changes cannot bypass review or automated policy checks.
8. Verify tenant/context labels are present in logs without leaking secrets or PII.
9. Verify load tests include skewed traffic, not only uniform distributions.
10. Verify cost dashboards break down the business unit by feature and tenant/context.
11. Verify dashboards expose user-impact SLOs for Mock Interview 04 Kafka.
12. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
13. Verify the runbook has a rollback step and a separate reconciliation step.
14. Verify each queue or stream has bounded retry and dead-letter handling.
15. Verify every emergency command is scoped to the smallest safe boundary.
16. Verify post-incident cleanup drains backlog without violating customer promises.
17. Verify schema/config changes cannot bypass review or automated policy checks.
18. Verify tenant/context labels are present in logs without leaking secrets or PII.
19. Verify load tests include skewed traffic, not only uniform distributions.
20. Verify cost dashboards break down the business unit by feature and tenant/context.
21. Verify dashboards expose user-impact SLOs for Mock Interview 04 Kafka.
22. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
23. Verify the runbook has a rollback step and a separate reconciliation step.
24. Verify each queue or stream has bounded retry and dead-letter handling.
25. Verify every emergency command is scoped to the smallest safe boundary.
26. Verify post-incident cleanup drains backlog without violating customer promises.
27. Verify schema/config changes cannot bypass review or automated policy checks.
28. Verify tenant/context labels are present in logs without leaking secrets or PII.
29. Verify load tests include skewed traffic, not only uniform distributions.
30. Verify cost dashboards break down the business unit by feature and tenant/context.
31. Verify dashboards expose user-impact SLOs for Mock Interview 04 Kafka.
32. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
33. Verify the runbook has a rollback step and a separate reconciliation step.
34. Verify each queue or stream has bounded retry and dead-letter handling.
35. Verify every emergency command is scoped to the smallest safe boundary.
36. Verify post-incident cleanup drains backlog without violating customer promises.
37. Verify schema/config changes cannot bypass review or automated policy checks.
38. Verify tenant/context labels are present in logs without leaking secrets or PII.
39. Verify load tests include skewed traffic, not only uniform distributions.
40. Verify cost dashboards break down the business unit by feature and tenant/context.
41. Verify dashboards expose user-impact SLOs for Mock Interview 04 Kafka.
42. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.


---
