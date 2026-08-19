# Answer Key - Design Twitter Feed

> Open only after attempting the learner file questions.

This key is written for principal/staff-level self-review.
A passing answer should name the irreversible decisions, trust boundaries, highest-amplification actors, unit economics, and smallest safe blast-radius boundary.
It should also say what to turn off first during an incident without corrupting the correctness-critical path.

## Principal Model Answer - What Excellent Looks Like

1. Chooses hybrid fan-out and explains why celebrity thresholds are cost and reliability controls.
2. Separates durable tweet write from derived home timeline entries.
3. Defines deletion/block/mute repair for already-fanned-out items.
4. Handles event traffic by scoped degradation to chronological feed and celebrity cache TTLs.
5. Names Redis, Kafka, graph, ranking, and hydration as separate bottlenecks.

## Ops Sim / Incident Model Answer

### Global Music Awards root cause chain

1. Normal-user tweet volume raised fan-out writes from baseline to millions of ZADD/sec.
2. @HostLive below the celebrity threshold caused an 8M-write single-tweet push storm.
3. @GMA_Official and @StarArtist were correctly on pull path but created hot celebrity_recent keys.
4. Ranking feature store was hit by an offline Spark job, turning optional ranking into a synchronous feed outage.
5. Old mobile clients retried without backoff, amplifying 504s into more read load.
6. A Redis reshard during peak widened the blast radius and sent fan-out events to DLQ.
7. Aurora replica lag made follower lists stale, causing correctness symptoms separate from latency.

### First mitigation order

1. Disable ranked feed globally or by event regions; chronological feed is acceptable degradation.
2. Pin/extend celebrity_recent micro-cache and prewarm known event keys across pods.
3. Raise @HostLive above celebrity threshold immediately and stop additional push fan-out for that author.
4. Pause offline feature refresh and protect ranking Redis from batch jobs.
5. Throttle old client versions at the edge with Retry-After and server-side request coalescing.
6. Do not reshard Redis during the event; isolate hot keys or route them to dedicated cache instead.
7. Drain DLQ only after p99 and Redis CPU normalize, with per-author and per-partition budgets.

### Prevention gates

1. Event-mode config must preclassify likely celebrity/live accounts.
2. Fan-out workers require per-author write budgets independent of follower count.
3. Ranking calls need timeout, fallback, and circuit breaker so feed reads do not block on ML.
4. Client retry policy is a production dependency and must be enforced server-side for old versions.
5. Runbooks must forbid online resharding and global cache flush during peak without incident commander approval.

---

## Design Gates (mandatory) - Principal-Depth Model Responses

### Gate 1 - Authn/z trust boundary

1. Principal inventory: end users, mobile devices, session service, post API, timeline service, fan-out workers, ranking service, graph service, ad partners, support/admin actors
2. First untrusted boundary: API Gateway/edge auth before Post API and Timeline API
3. Final authorization decision: Timeline/Post services using graph, block/mute, privacy, and ads policy services
4. Accepted identity artifacts: session cookie or OAuth bearer token for users; workload identity for services; scoped admin token for support
5. Service-to-service trust: mTLS/SPIFFE workload identity plus short-lived service tokens
6. Public clients never choose tenant/user/object IDs without server-side policy checks.
7. Admin/support access requires break-glass approval, reason codes, scoped duration, and immutable audit logs.
8. Background workers carry job identity and original actor context where user intent matters.
9. Capability or signed URL tokens are scoped to one object, operation, expiry, and content hash where applicable.
10. Identity or policy outage behavior: post/write/admin paths fail closed; previously authorized public media and cached public tweets may serve stale; private/protected timelines do not bypass policy
11. Read-only degraded mode is acceptable only for explicitly public or previously authorized cached data.
12. Writes, deletes, money movement, admin actions, and privacy-sensitive reads fail closed.
13. Audit events include actor, subject, tenant/context, decision, policy version, request ID, and source IP/device.
14. Cross-region failover preserves auth state; it never bypasses policy to restore availability.
15. A good answer draws this trust boundary before drawing caches, queues, or databases.
16. Model summary: Authenticate at the edge, authorize each tweet/timeline action inside the owning service, and never let cached feed entries bypass block, mute, protected-account, or deletion policy.

### Gate 2 - Abuse and misuse

1. Highest amplification actor: a high-follower author and any fan-out worker that turns one tweet into millions of timeline inserts
2. Authenticated abuse surfaces: post tweet, follow/unfollow churn, timeline refresh scraping, reply/retweet storms, fan-out replay, ranking feature refresh
3. Quota dimensions: per-user post/read/follow limits, per-author fan-out budget, per-celebrity cache budget, per-IP/device scraping limits, per-region Redis/Kafka caps, global event-mode safety caps
4. Global safety caps are separate from per-principal quotas so one bug cannot consume the fleet.
5. Entity-key limits protect hot keys even when all callers are legitimate.
6. Worker concurrency limits protect downstream stores from replay storms and fan-out storms.
7. Retry budgets are finite, jittered, and tied to user intent or idempotency keys.
8. Retry hazard: older clients retrying failed feed loads without backoff and workers retrying Redis timeouts into DLQ/replay loops
9. Telemetry separating flash crowd from abuse: follower-count skew, author entropy, client version retry rate, ZADD/sec per author, timeline refresh cadence, cache-hit ratio, Kafka lag by partition
10. Organic spikes preserve normal identity diversity; attacks show skewed principals, IPs, clients, or entities.
11. Abuse controls emit allow/deny/throttle decisions into a stream suitable for forensics.
12. Degradation sheds optional work before it rejects correctness-critical operations.
13. Runbooks say when to pause producers, disable retries, or drop optional enrichments.
14. A good answer includes both prevention and incident-time containment.
15. A weak answer only says add rate limiting without keys, budgets, or kill switches.
16. Model summary: Treat a legitimate celebrity or live event as the same amplification shape an attacker would exploit, then cap fan-out and read retries at multiple layers.

### Gate 3 - Multi-tenant isolation

1. Tenancy model: not classic SaaS, but isolation by user, protected account, advertiser, region/cell, celebrity key, and internal business tenant
2. Tenant/context propagation: user_id, viewer_id, author_id, region, ads tenant, privacy state, and request_id propagate through Kafka, Redis keys, ranking calls, logs, and support tools
3. Shared resource reservations: Redis shards for hot celebrity keys, Kafka partition budgets, fan-out worker pools, graph DB read pools, ranking CPU, ad insertion budgets
4. Every cache key, queue message, object prefix, metric label, and support export carries tenant/context explicitly.
5. Missing tenant/context is a policy error, not a default-to-global behavior.
6. Async jobs include context in the payload and in the worker authorization decision.
7. Support tools filter by tenant/context server-side and log the exact export scope.
8. Noisy-neighbor control: throttle one author, disable one celebrity merge key, route a region to chronological feed, pause a fan-out partition, or isolate an advertiser campaign
9. Large tenants or hot entities can be isolated into dedicated shards/cells/topics without global migration.
10. Backfills and replays run in tenant-scoped lanes with byte and concurrency budgets.
11. Observability cardinality is bounded so one tenant cannot bankrupt metrics ingestion.
12. Isolation test: blocked/protected/deleted tweet never appears from Redis, ranking cache, search injection, export, or support replay after policy change
13. Disaster recovery restores tenant boundaries, not only bytes.
14. A good answer names logical isolation and physical capacity isolation.
15. A weak answer says tenant_id column and stops there.
16. Model summary: Treat user/privacy context as the tenant boundary and hot entities as noisy neighbors that need capacity and kill switches.

### Gate 4 - Unit cost at target scale

1. Business unit: one home timeline read plus one tweet fan-out operation
2. Rough unit-cost model: reads dominate: Redis ZRANGE + hydration + ranking per page; celebrity writes are explosive; event peak prices millions of ZADD/sec and cache memory headroom
3. Dominant line items: Redis memory/ops, Kafka throughput, Keyspaces/Cassandra hydration reads, ranking feature calls, media egress, observability during events, idle headroom
4. Include replication, idle headroom, cross-AZ/region transfer, observability, and replay capacity.
5. Separate fixed control-plane cost from variable data-plane cost.
6. Track p50 and p99 cost because tail work often drives autoscaling and queue depth.
7. Chargeback/showback attributes cost by tenant/context, feature, endpoint, and deploy version.
8. Cost alert before margin/SLO breach: cost per 1,000 successful feed loads and cost per million fan-out inserts by author class
9. Capacity planning includes event-day peak multiplier, not only daily average.
10. Cost regressions need rollback criteria just like latency regressions.
11. Graceful cost reduction: chronological feed, smaller page size, skip optional ranking/features/ads, lengthen celebrity cache TTL, delay non-critical fan-out while preserving tweet durability
12. Never reduce cost by weakening correctness, auth, audit, or durability guarantees.
13. Cold storage, compaction, tiering, sampling, and caching are explicit levers with owners.
14. A good answer can defend an order-of-magnitude number on a whiteboard.
15. A weak answer lists cloud products without pricing the business unit.
16. Model summary: Unit economics are governed by read volume and fan-out amplification; the cheap path is cached IDs plus bounded hydration, not per-request graph joins.

### Gate 5 - Failure blast radius

1. Smallest intended failure boundary: Redis shard, celebrity cache key, Kafka partition, fan-out worker pool, region/cell, or author class
2. Shared dependencies between critical and optional paths: Redis and ranking feature store shared by hot celebrity merges and ordinary timelines; graph DB shared by fan-out and follow actions
3. Fail closed: protected/private tweets, deletes, blocks/mutes, admin actions, post durability
4. Serve stale or degraded: public chronological timelines, celebrity recent cache for seconds, partial feed hydration with omitted tweets
5. Disable first: ranking, ads/suggestions, expensive celebrity merge depth, non-critical feature refresh, fan-out for low-priority notifications
6. Runbook hazard that widens blast radius: online Redis resharding or global cache flush during peak; replaying DLQ without per-author throttle
7. Bulkheads separate user-facing serving from analytics, backfill, replay, and support tooling.
8. Feature flags are scoped by cell/region/tenant/entity, with a global kill only for known-safe toggles.
9. Queues have dead-letter and replay throttles; replay is never unbounded during recovery.
10. Caches have namespace-level invalidation; global flushes require incident commander approval.
11. Autoscaling must not scale a bad retry loop faster than dependencies can absorb it.
12. Game day: live-event load with one below-threshold 8M-follower author, celebrity hot keys, ranking outage, old-client retry storm, and scoped degradation
13. Alerts fire on leading indicators inside the boundary before customers see platform-wide impact.
14. A good answer says what remains working when one shard/cell/topic fails.
15. A weak answer treats multi-region replication as a substitute for blast-radius design.
16. Model summary: Keep the failure inside one author/key/shard/region and preserve post durability while degrading feed freshness and ranking.

---

## Evaluator Rubric and Red Flags

1. Names the core correctness invariant for Twitter home timeline: a viewer only sees tweets they are authorized to see, and acknowledged tweets remain durable even if timeline propagation is delayed
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

1. Treating caches, queues, or CDN as the source of truth when Twitter home timeline needs durable reconciliation.
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

1. Verify dashboards expose user-impact SLOs for Twitter home timeline.
2. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
3. Verify the runbook has a rollback step and a separate reconciliation step.
4. Verify each queue or stream has bounded retry and dead-letter handling.
5. Verify every emergency command is scoped to the smallest safe boundary.
6. Verify post-incident cleanup drains backlog without violating customer promises.
7. Verify schema/config changes cannot bypass review or automated policy checks.
8. Verify tenant/context labels are present in logs without leaking secrets or PII.
9. Verify load tests include skewed traffic, not only uniform distributions.
10. Verify cost dashboards break down the business unit by feature and tenant/context.
11. Verify dashboards expose user-impact SLOs for Twitter home timeline.
12. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
13. Verify the runbook has a rollback step and a separate reconciliation step.
14. Verify each queue or stream has bounded retry and dead-letter handling.
15. Verify every emergency command is scoped to the smallest safe boundary.
16. Verify post-incident cleanup drains backlog without violating customer promises.
17. Verify schema/config changes cannot bypass review or automated policy checks.
18. Verify tenant/context labels are present in logs without leaking secrets or PII.
19. Verify load tests include skewed traffic, not only uniform distributions.
20. Verify cost dashboards break down the business unit by feature and tenant/context.
21. Verify dashboards expose user-impact SLOs for Twitter home timeline.
22. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
23. Verify the runbook has a rollback step and a separate reconciliation step.
24. Verify each queue or stream has bounded retry and dead-letter handling.
25. Verify every emergency command is scoped to the smallest safe boundary.
26. Verify post-incident cleanup drains backlog without violating customer promises.
27. Verify schema/config changes cannot bypass review or automated policy checks.
28. Verify tenant/context labels are present in logs without leaking secrets or PII.
29. Verify load tests include skewed traffic, not only uniform distributions.
30. Verify cost dashboards break down the business unit by feature and tenant/context.
31. Verify dashboards expose user-impact SLOs for Twitter home timeline.
32. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.


---
