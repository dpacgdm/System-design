# Answer Key - Distributed Key-Value Store

> Open only after attempting the learner file questions.

This key is written for principal/staff-level self-review.
A passing answer should name the irreversible decisions, trust boundaries, highest-amplification actors, unit economics, and smallest safe blast-radius boundary.
It should also say what to turn off first during an incident without corrupting the correctness-critical path.

## Principal Model Answer - What Excellent Looks Like

1. Clarifies consistency requirements before choosing Dynamo/Cassandra patterns.
2. Uses consistent hashing/token ranges and replication factor deliberately.
3. Explains quorum, hinted handoff, read repair, compaction, and tombstones.
4. Treats hot keys as primary failure mode.
5. Separates session TTL/expiration from delete/tombstone safety.

## Ops Sim / Incident Model Answer

### Hot partition cascade

1. A 2:30 batch job wrote sessions with shared prefix sg-prod-batch-.
2. Partition key distribution skewed so 40% of writes hit one replica set/node.
3. Node ap-sg-42 accumulated 847 SSTables and high I/O wait, raising p99 latency.
4. LOCAL_QUORUM writes timed out when one replica was slow/down and surviving replicas took hints.
5. Hinted handoff shifted load to ap-sg-17, causing secondary overload and gossip suspects.

### Immediate mitigation

1. Stop the offending batch job and block the prefix/key pattern.
2. Throttle client retries and shed low-priority session writes in ap-southeast.
3. Disable or slow hinted handoff replay until live traffic stabilizes.
4. Route new sessions through a corrected high-cardinality key format.
5. Add capacity only after hot traffic is throttled; otherwise new nodes inherit compaction debt.

### Why LOCAL_QUORUM did not save users

1. LOCAL_QUORUM protects durability/consistency in a local DC; it does not guarantee low latency.
2. If two replicas are slow or overloaded, quorum cannot complete before timeout.
3. Coordinator, compaction, and disk queues can fail before data is logically unavailable.
4. A hot partition makes RF=3 three hot replicas, not three independent capacities.

---

## Design Gates (mandatory) - Principal-Depth Model Responses

### Gate 1 - Authn/z trust boundary

1. Principal inventory: application services, end users through apps, coordinator nodes, replica nodes, repair jobs, backup jobs, admins/support operators, tenant services
2. First untrusted boundary: client SDK/API gateway before coordinator nodes
3. Final authorization decision: KV access service or table/keyspace policy before coordinator accepts a read/write
4. Accepted identity artifacts: service token/API key, workload identity, table/keyspace role, admin break-glass token, backup job identity
5. Service-to-service trust: mTLS/SPIFFE workload identity plus short-lived service tokens
6. Public clients never choose tenant/user/object IDs without server-side policy checks.
7. Admin/support access requires break-glass approval, reason codes, scoped duration, and immutable audit logs.
8. Background workers carry job identity and original actor context where user intent matters.
9. Capability or signed URL tokens are scoped to one object, operation, expiry, and content hash where applicable.
10. Identity or policy outage behavior: writes at strong/LOCAL_QUORUM fail if policy or quorum unavailable; eventually consistent reads may serve stale only where caller requested it
11. Read-only degraded mode is acceptable only for explicitly public or previously authorized cached data.
12. Writes, deletes, money movement, admin actions, and privacy-sensitive reads fail closed.
13. Audit events include actor, subject, tenant/context, decision, policy version, request ID, and source IP/device.
14. Cross-region failover preserves auth state; it never bypasses policy to restore availability.
15. A good answer draws this trust boundary before drawing caches, queues, or databases.
16. Model summary: The coordinator enforces table/keyspace/prefix access and consistency choice; replicas are not exposed to untrusted callers.

### Gate 2 - Abuse and misuse

1. Highest amplification actor: hot key or bad partition key that routes a large fraction of traffic to the same replica set
2. Authenticated abuse surfaces: batch writes with shared prefixes, unbounded scans, high-cardinality table creation, repair/replay jobs, low-CL reads after high-CL writes
3. Quota dimensions: per-tenant/keyspace/table, per-partition key, per-coordinator, per-DC, per-repair job, per-query page, global hint/repair budget
4. Global safety caps are separate from per-principal quotas so one bug cannot consume the fleet.
5. Entity-key limits protect hot keys even when all callers are legitimate.
6. Worker concurrency limits protect downstream stores from replay storms and fan-out storms.
7. Retry budgets are finite, jittered, and tied to user intent or idempotency keys.
8. Retry hazard: client retries on WriteTimeout to the same hot partition and hinted handoff replay overwhelming surviving replicas
9. Telemetry separating flash crowd from abuse: partition heat, coordinator latency, SSTable count, tombstones, hint queue, read-repair rate, CL timeout by DC, compaction backlog
10. Organic spikes preserve normal identity diversity; attacks show skewed principals, IPs, clients, or entities.
11. Abuse controls emit allow/deny/throttle decisions into a stream suitable for forensics.
12. Degradation sheds optional work before it rejects correctness-critical operations.
13. Runbooks say when to pause producers, disable retries, or drop optional enrichments.
14. A good answer includes both prevention and incident-time containment.
15. A weak answer only says add rate limiting without keys, budgets, or kill switches.
16. Model summary: Uniform hashing only protects uniform keys; the answer must defend hot partitions and operational replay storms.

### Gate 3 - Multi-tenant isolation

1. Tenancy model: keyspace/table/prefix tenant, region/DC, replication group, workload class, backup/export scope
2. Tenant/context propagation: tenant_id, keyspace, table, partition key hash, consistency level, DC, request_id in queries, hints, repairs, backups, and logs
3. Shared resource reservations: per-tenant WCU/RCU, partition heat caps, repair bandwidth, compaction I/O, hint storage, coordinator pools
4. Every cache key, queue message, object prefix, metric label, and support export carries tenant/context explicitly.
5. Missing tenant/context is a policy error, not a default-to-global behavior.
6. Async jobs include context in the payload and in the worker authorization decision.
7. Support tools filter by tenant/context server-side and log the exact export scope.
8. Noisy-neighbor control: throttle one tenant/table/key prefix, disable one batch job, quarantine one DC, or move a hot tenant to a dedicated ring
9. Large tenants or hot entities can be isolated into dedicated shards/cells/topics without global migration.
10. Backfills and replays run in tenant-scoped lanes with byte and concurrency budgets.
11. Observability cardinality is bounded so one tenant cannot bankrupt metrics ingestion.
12. Isolation test: tenant A cannot read B through API, secondary index, backup export, repair stream, cache, or support tooling
13. Disaster recovery restores tenant boundaries, not only bytes.
14. A good answer names logical isolation and physical capacity isolation.
15. A weak answer says tenant_id column and stops there.
16. Model summary: Keyspace/table plus capacity is the tenant boundary; partition heat controls prevent noisy-neighbor overload.

### Gate 4 - Unit cost at target scale

1. Business unit: one read or write at the chosen consistency level
2. Rough unit-cost model: unit cost varies by consistency level: W=2/R=2 costs multiple replica reads/writes, plus compaction, repair, hints, and storage amplification
3. Dominant line items: SSD/IOPS, replication factor, compaction CPU/I/O, cross-DC replication, repair bandwidth, tombstone scans, backups, observability
4. Include replication, idle headroom, cross-AZ/region transfer, observability, and replay capacity.
5. Separate fixed control-plane cost from variable data-plane cost.
6. Track p50 and p99 cost because tail work often drives autoscaling and queue depth.
7. Chargeback/showback attributes cost by tenant/context, feature, endpoint, and deploy version.
8. Cost alert before margin/SLO breach: cost per million CL-specific ops and hottest-partition cost by tenant/table
9. Capacity planning includes event-day peak multiplier, not only daily average.
10. Cost regressions need rollback criteria just like latency regressions.
11. Graceful cost reduction: lower non-critical read consistency, shed scans/analytics, pause repairs/backfills, rate-limit hot key, serve stale sessions only if product accepts re-auth; never drop committed writes
12. Never reduce cost by weakening correctness, auth, audit, or durability guarantees.
13. Cold storage, compaction, tiering, sampling, and caching are explicit levers with owners.
14. A good answer can defend an order-of-magnitude number on a whiteboard.
15. A weak answer lists cloud products without pricing the business unit.
16. Model summary: Replication factor and compaction/repair amplification make storage cost much larger than raw value bytes.

### Gate 5 - Failure blast radius

1. Smallest intended failure boundary: partition key replica set, token range, node, rack/AZ, DC, keyspace/table, tenant
2. Shared dependencies between critical and optional paths: coordinator pools, compaction threads, hints, repair jobs, network, disk I/O across tenants
3. Fail closed: admin writes, schema changes, strong reads/writes when quorum unavailable, backup restore
4. Serve stale or degraded: eventual reads, cached sessions with expiry, read-only degraded mode
5. Disable first: batch job, scans, repairs, hinted handoff replay, low-priority tenants, cross-DC analytics
6. Runbook hazard that widens blast radius: increasing client retries, disabling compaction, running full repair during peak, or lowering consistency globally without product approval
7. Bulkheads separate user-facing serving from analytics, backfill, replay, and support tooling.
8. Feature flags are scoped by cell/region/tenant/entity, with a global kill only for known-safe toggles.
9. Queues have dead-letter and replay throttles; replay is never unbounded during recovery.
10. Caches have namespace-level invalidation; global flushes require incident commander approval.
11. Autoscaling must not scale a bad retry loop faster than dependencies can absorb it.
12. Game day: hot partition from bad batch prefix in one DC with LOCAL_QUORUM, hint storm, and scoped tenant throttling
13. Alerts fire on leading indicators inside the boundary before customers see platform-wide impact.
14. A good answer says what remains working when one shard/cell/topic fails.
15. A weak answer treats multi-region replication as a substitute for blast-radius design.
16. Model summary: A hot partition should hurt its replica set and tenant, not the whole ring or other DCs.

---

## Evaluator Rubric and Red Flags

1. Names the core correctness invariant for distributed key-value/session store: for the chosen consistency contract, acknowledged writes are durable enough to be read/repaired without unbounded stale or lost data
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

1. Treating caches, queues, or CDN as the source of truth when distributed key-value/session store needs durable reconciliation.
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

1. Verify dashboards expose user-impact SLOs for distributed key-value/session store.
2. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
3. Verify the runbook has a rollback step and a separate reconciliation step.
4. Verify each queue or stream has bounded retry and dead-letter handling.
5. Verify every emergency command is scoped to the smallest safe boundary.
6. Verify post-incident cleanup drains backlog without violating customer promises.
7. Verify schema/config changes cannot bypass review or automated policy checks.
8. Verify tenant/context labels are present in logs without leaking secrets or PII.
9. Verify load tests include skewed traffic, not only uniform distributions.
10. Verify cost dashboards break down the business unit by feature and tenant/context.
11. Verify dashboards expose user-impact SLOs for distributed key-value/session store.
12. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
13. Verify the runbook has a rollback step and a separate reconciliation step.
14. Verify each queue or stream has bounded retry and dead-letter handling.
15. Verify every emergency command is scoped to the smallest safe boundary.
16. Verify post-incident cleanup drains backlog without violating customer promises.
17. Verify schema/config changes cannot bypass review or automated policy checks.
18. Verify tenant/context labels are present in logs without leaking secrets or PII.
19. Verify load tests include skewed traffic, not only uniform distributions.
20. Verify cost dashboards break down the business unit by feature and tenant/context.
21. Verify dashboards expose user-impact SLOs for distributed key-value/session store.
22. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
23. Verify the runbook has a rollback step and a separate reconciliation step.
24. Verify each queue or stream has bounded retry and dead-letter handling.
25. Verify every emergency command is scoped to the smallest safe boundary.
26. Verify post-incident cleanup drains backlog without violating customer promises.
27. Verify schema/config changes cannot bypass review or automated policy checks.
28. Verify tenant/context labels are present in logs without leaking secrets or PII.
29. Verify load tests include skewed traffic, not only uniform distributions.
30. Verify cost dashboards break down the business unit by feature and tenant/context.
31. Verify dashboards expose user-impact SLOs for distributed key-value/session store.
32. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
33. Verify the runbook has a rollback step and a separate reconciliation step.
34. Verify each queue or stream has bounded retry and dead-letter handling.
35. Verify every emergency command is scoped to the smallest safe boundary.
36. Verify post-incident cleanup drains backlog without violating customer promises.
37. Verify schema/config changes cannot bypass review or automated policy checks.


---
