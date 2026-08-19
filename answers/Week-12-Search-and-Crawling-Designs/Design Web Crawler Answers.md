# Answer Key - Design Web Crawler

> Open only after attempting the learner file questions.

This key is written for principal/staff-level self-review.
A passing answer should name the irreversible decisions, trust boundaries, highest-amplification actors, unit economics, and smallest safe blast-radius boundary.
It should also say what to turn off first during an incident without corrupting the correctness-critical path.

## Principal Model Answer - What Excellent Looks Like

1. Separates URL frontier, fetcher, parser, dedupe, and indexer.
2. Uses host-level politeness tokens and robots policy.
3. Explains canonicalization and duplicate suppression.
4. Plans index freshness recovery without re-triggering blocks.
5. Treats external site trust as a production dependency.

## Ops Sim / Incident Model Answer

### Retailer WAF root cause

1. Concurrency changed from 1 to 8 and violated the de facto politeness budget.
2. Token bucket allowed average rate but failed to cap simultaneous connection fingerprint.
3. Retailer WAF interpreted the burst from one ASN/subnet as bot traffic.
4. Robots still allowed crawling, so this was abuse/rate policy, not robots denial.
5. IP rotation during the block would burn reputation and widen the incident.

### Mitigation order

1. Rollback max_concurrent to 1 and pause frontier dequeue for retailer.com.
2. Stop IP rotation immediately.
3. Contact partner with User-Agent, timeline, and acknowledgement of misconfiguration.
4. Resume only after 403 rate drops or partner ack, at 1 concurrent with jitter.
5. Recover index through sitemap-only high-value URLs before BFS/link-following.

### Prevention

1. Hard cap per-host concurrency in code and deployment policy.
2. Canary politeness changes on low-risk hosts for 24 hours.
3. Auto-throttle host on 403/429/WAF body signature.
4. Add runbook: pause host, rollback, contact, slow resume; never rotate IPs during active block.
5. Test with a partner WAF simulator, not just token bucket math.

---

## Design Gates (mandatory) - Principal-Depth Model Responses

### Gate 1 - Authn/z trust boundary

1. Principal inventory: crawler service, scheduler/frontier workers, fetchers, parser/indexers, partner site owners, admin/support actors, API users of search index
2. First untrusted boundary: crawl admin API and outbound fetch boundary to external origins
3. Final authorization decision: Frontier/politeness service for fetch eligibility; admin API policy for crawl configuration; robots/policy evaluator for per-host rules
4. Accepted identity artifacts: workload identity for workers, signed admin token for config, declared User-Agent for external sites, partner allowlist credentials where provided
5. Service-to-service trust: mTLS/SPIFFE workload identity plus short-lived service tokens
6. Public clients never choose tenant/user/object IDs without server-side policy checks.
7. Admin/support access requires break-glass approval, reason codes, scoped duration, and immutable audit logs.
8. Background workers carry job identity and original actor context where user intent matters.
9. Capability or signed URL tokens are scoped to one object, operation, expiry, and content hash where applicable.
10. Identity or policy outage behavior: crawl config changes and partner overrides fail closed; existing frontier can pause; index serving may use stale documents
11. Read-only degraded mode is acceptable only for explicitly public or previously authorized cached data.
12. Writes, deletes, money movement, admin actions, and privacy-sensitive reads fail closed.
13. Audit events include actor, subject, tenant/context, decision, policy version, request ID, and source IP/device.
14. Cross-region failover preserves auth state; it never bypasses policy to restore availability.
15. A good answer draws this trust boundary before drawing caches, queues, or databases.
16. Model summary: The crawler is authenticated internally but untrusted by external sites; politeness policy decides whether a URL may be fetched now.

### Gate 2 - Abuse and misuse

1. Highest amplification actor: per-host concurrency and frontier dequeue that can turn a config change into millions of outbound requests and partner WAF blocks
2. Authenticated abuse surfaces: crawl configuration, recrawl requests, sitemap imports, IP rotation, parser retries, frontier priority boosts, index export
3. Quota dimensions: per-host RPS/concurrency, per-domain daily fetch, per-ASN outbound, per-tenant recrawl, per-worker sockets, per-region egress, global fetch cap
4. Global safety caps are separate from per-principal quotas so one bug cannot consume the fleet.
5. Entity-key limits protect hot keys even when all callers are legitimate.
6. Worker concurrency limits protect downstream stores from replay storms and fan-out storms.
7. Retry budgets are finite, jittered, and tied to user intent or idempotency keys.
8. Retry hazard: rotating IPs and retrying during an active WAF block, burning new IP pools and widening partner distrust
9. Telemetry separating flash crowd from abuse: 403/429 by host, WAF signatures, robots changes, per-host burstiness, connection concurrency, User-Agent blocks, DNS/connect latency, index freshness loss
10. Organic spikes preserve normal identity diversity; attacks show skewed principals, IPs, clients, or entities.
11. Abuse controls emit allow/deny/throttle decisions into a stream suitable for forensics.
12. Degradation sheds optional work before it rejects correctness-critical operations.
13. Runbooks say when to pause producers, disable retries, or drop optional enrichments.
14. A good answer includes both prevention and incident-time containment.
15. A weak answer only says add rate limiting without keys, budgets, or kill switches.
16. Model summary: The system can be an accidental abuser; host-level politeness and kill switches matter more than average global crawl rate.

### Gate 3 - Multi-tenant isolation

1. Tenancy model: search vertical/tenant, host/domain, crawl priority lane, index shard, region, partner account
2. Tenant/context propagation: tenant/search vertical, host, URL fingerprint, crawl policy version, frontier lane, and request_id propagate through queues, fetch logs, object storage, index, and exports
3. Shared resource reservations: per-host fetch tokens, per-vertical frontier lanes, parser CPU, index write bandwidth, outbound IP pools, partner API quotas
4. Every cache key, queue message, object prefix, metric label, and support export carries tenant/context explicitly.
5. Missing tenant/context is a policy error, not a default-to-global behavior.
6. Async jobs include context in the payload and in the worker authorization decision.
7. Support tools filter by tenant/context server-side and log the exact export scope.
8. Noisy-neighbor control: pause one host, freeze one vertical, disable IP rotation, lower one tenant priority, or quarantine one frontier shard
9. Large tenants or hot entities can be isolated into dedicated shards/cells/topics without global migration.
10. Backfills and replays run in tenant-scoped lanes with byte and concurrency budgets.
11. Observability cardinality is bounded so one tenant cannot bankrupt metrics ingestion.
12. Isolation test: tenant A cannot cause tenant B host fetches, index exports, URL cache reads, or logs to include unauthorized crawl data
13. Disaster recovery restores tenant boundaries, not only bytes.
14. A good answer names logical isolation and physical capacity isolation.
15. A weak answer says tenant_id column and stops there.
16. Model summary: Host/domain is the most important operational tenant; one partner block must not halt unrelated crawling or burn shared IP reputation.

### Gate 4 - Unit cost at target scale

1. Business unit: one successfully fetched, parsed, deduped, and indexed URL
2. Rough unit-cost model: unit cost includes DNS/connect, bandwidth, HTML/media fetch bytes, parsing CPU, dedupe/Bloom checks, object storage, index writes, and failed/blocked retries
3. Dominant line items: egress/ingress bandwidth, parser CPU, index storage, frontier queues, object storage, IP/proxy reputation, observability logs
4. Include replication, idle headroom, cross-AZ/region transfer, observability, and replay capacity.
5. Separate fixed control-plane cost from variable data-plane cost.
6. Track p50 and p99 cost because tail work often drives autoscaling and queue depth.
7. Chargeback/showback attributes cost by tenant/context, feature, endpoint, and deploy version.
8. Cost alert before margin/SLO breach: cost per indexed canonical URL and failed-fetch cost by host/tenant
9. Capacity planning includes event-day peak multiplier, not only daily average.
10. Cost regressions need rollback criteria just like latency regressions.
11. Graceful cost reduction: serve stale index, reduce recrawl depth, crawl sitemaps only, pause low-value hosts, sample pages, delay rich extraction while preserving robots/politeness
12. Never reduce cost by weakening correctness, auth, audit, or durability guarantees.
13. Cold storage, compaction, tiering, sampling, and caching are explicit levers with owners.
14. A good answer can defend an order-of-magnitude number on a whiteboard.
15. A weak answer lists cloud products without pricing the business unit.
16. Model summary: Retries and duplicate fetches can dominate cost; freshness must be priced against partner risk and index value.

### Gate 5 - Failure blast radius

1. Smallest intended failure boundary: host/domain, frontier shard, crawl tenant/vertical, outbound IP pool, index shard, region
2. Shared dependencies between critical and optional paths: frontier DB, fetcher fleet, outbound IP pool, parser workers, index write cluster, DNS resolver
3. Fail closed: robots deny, admin policy changes, partner opt-out, private/internal IP ranges
4. Serve stale or degraded: search results and cached snippets with freshness markers
5. Disable first: deep link following, low-priority recrawls, rich extraction, image fetches, IP rotation, non-critical verticals
6. Runbook hazard that widens blast radius: global concurrency increase, IP rotation during WAF block, clearing seen-URL filters, or replaying frontier without host tokens
7. Bulkheads separate user-facing serving from analytics, backfill, replay, and support tooling.
8. Feature flags are scoped by cell/region/tenant/entity, with a global kill only for known-safe toggles.
9. Queues have dead-letter and replay throttles; replay is never unbounded during recovery.
10. Caches have namespace-level invalidation; global flushes require incident commander approval.
11. Autoscaling must not scale a bad retry loop faster than dependencies can absorb it.
12. Game day: single retailer WAF blocks after concurrency increase while global crawl remains healthy and index recovers via sitemap-only crawl
13. Alerts fire on leading indicators inside the boundary before customers see platform-wide impact.
14. A good answer says what remains working when one shard/cell/topic fails.
15. A weak answer treats multi-region replication as a substitute for blast-radius design.
16. Model summary: Confine bad behavior to one host and preserve global index serving with stale data rather than aggressive recrawl.

---

## Evaluator Rubric and Red Flags

1. Names the core correctness invariant for web crawler and indexing pipeline: never fetch a URL that policy/robots/politeness disallows, and never let one host consume global crawl capacity
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

1. Treating caches, queues, or CDN as the source of truth when web crawler and indexing pipeline needs durable reconciliation.
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

1. Verify dashboards expose user-impact SLOs for web crawler and indexing pipeline.
2. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
3. Verify the runbook has a rollback step and a separate reconciliation step.
4. Verify each queue or stream has bounded retry and dead-letter handling.
5. Verify every emergency command is scoped to the smallest safe boundary.
6. Verify post-incident cleanup drains backlog without violating customer promises.
7. Verify schema/config changes cannot bypass review or automated policy checks.
8. Verify tenant/context labels are present in logs without leaking secrets or PII.
9. Verify load tests include skewed traffic, not only uniform distributions.
10. Verify cost dashboards break down the business unit by feature and tenant/context.
11. Verify dashboards expose user-impact SLOs for web crawler and indexing pipeline.
12. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
13. Verify the runbook has a rollback step and a separate reconciliation step.
14. Verify each queue or stream has bounded retry and dead-letter handling.
15. Verify every emergency command is scoped to the smallest safe boundary.
16. Verify post-incident cleanup drains backlog without violating customer promises.
17. Verify schema/config changes cannot bypass review or automated policy checks.
18. Verify tenant/context labels are present in logs without leaking secrets or PII.
19. Verify load tests include skewed traffic, not only uniform distributions.
20. Verify cost dashboards break down the business unit by feature and tenant/context.
21. Verify dashboards expose user-impact SLOs for web crawler and indexing pipeline.
22. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
23. Verify the runbook has a rollback step and a separate reconciliation step.
24. Verify each queue or stream has bounded retry and dead-letter handling.
25. Verify every emergency command is scoped to the smallest safe boundary.
26. Verify post-incident cleanup drains backlog without violating customer promises.
27. Verify schema/config changes cannot bypass review or automated policy checks.
28. Verify tenant/context labels are present in logs without leaking secrets or PII.
29. Verify load tests include skewed traffic, not only uniform distributions.
30. Verify cost dashboards break down the business unit by feature and tenant/context.
31. Verify dashboards expose user-impact SLOs for web crawler and indexing pipeline.
32. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
33. Verify the runbook has a rollback step and a separate reconciliation step.
34. Verify each queue or stream has bounded retry and dead-letter handling.
35. Verify every emergency command is scoped to the smallest safe boundary.
36. Verify post-incident cleanup drains backlog without violating customer promises.


---
