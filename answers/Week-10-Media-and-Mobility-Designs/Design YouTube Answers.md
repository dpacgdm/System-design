# Answer Key - Design YouTube

> Open only after attempting the learner file questions.

This key is written for principal/staff-level self-review.
A passing answer should name the irreversible decisions, trust boundaries, highest-amplification actors, unit economics, and smallest safe blast-radius boundary.
It should also say what to turn off first during an incident without corrupting the correctness-critical path.

## Principal Model Answer - What Excellent Looks Like

1. Uses resumable direct-to-object-storage upload and async transcode fan-out.
2. Separates manifest TTL from immutable segment TTL.
3. Uses deduped async view counting with monotonic display.
4. Designs recommendations as multi-stage retrieval/ranking with fallback.
5. Treats CDN hit ratio as an SLO and cost metric.

## Ops Sim / Incident Model Answer

### CDN TTL root cause cascade

1. Deploy changed .ts segment TTL from 86400 to 60 seconds.
2. Segment cache hit ratio fell from 94% to 62%, causing an origin miss storm.
3. S3 origin saw elevated GET 503s; players buffered and start time p95 rose to 8.2s.
4. Videos stuck in processing were a concurrent symptom, not the primary playback cause.
5. View counts dropped because Kafka/Flink lag plus a non-monotonic Redis-to-Aurora flush overwrote higher counts with stale lower values.

### First 15 minutes mitigation

1. Rollback CloudFront segment behavior to long TTL and verify cache policy checksum.
2. Enable or verify Origin Shield to collapse miss storms.
3. Do not invalidate all segments; use targeted manifest invalidation only if needed.
4. Throttle player retry storms and protect origin with request budgets.
5. Pause non-critical transcode/recommendation work if it competes with origin/Kafka.
6. Patch view count flush to max(existing, computed) before replaying lag.

### Long-term controls

1. IaC policy forbids low TTL on immutable segment extensions.
2. Canary CDN behavior and verify Age header before global rollout.
3. Separate manifests from segments in policy review.
4. Alert on origin offload and displayed view-count decrease.
5. Run a replay test where view aggregation lags for an hour and display remains monotonic.

---

## Design Gates (mandatory) - Principal-Depth Model Responses

### Gate 1 - Authn/z trust boundary

1. Principal inventory: viewers, creators, channel managers, player devices, upload workers, transcode workers, recommendation services, CDN/origin services, moderators, ad partners, support/admin actors
2. First untrusted boundary: API Gateway for metadata/upload control and CDN edge for playback segments/manifests
3. Final authorization decision: Metadata/Entitlement services for video/channel actions; CDN signed URL policy for private or restricted playback; moderation policy for publishability
4. Accepted identity artifacts: session/OAuth token, creator role token, signed upload URL, signed playback URL, workload identity for workers
5. Service-to-service trust: mTLS/SPIFFE workload identity plus short-lived service tokens
6. Public clients never choose tenant/user/object IDs without server-side policy checks.
7. Admin/support access requires break-glass approval, reason codes, scoped duration, and immutable audit logs.
8. Background workers carry job identity and original actor context where user intent matters.
9. Capability or signed URL tokens are scoped to one object, operation, expiry, and content hash where applicable.
10. Identity or policy outage behavior: public cached segments may continue serving; private/age-restricted/member-only playback, upload complete, publish, delete, monetization, and moderation fail closed
11. Read-only degraded mode is acceptable only for explicitly public or previously authorized cached data.
12. Writes, deletes, money movement, admin actions, and privacy-sensitive reads fail closed.
13. Audit events include actor, subject, tenant/context, decision, policy version, request ID, and source IP/device.
14. Cross-region failover preserves auth state; it never bypasses policy to restore availability.
15. A good answer draws this trust boundary before drawing caches, queues, or databases.
16. Model summary: The source video and metadata are protected objects; CDN cacheability never overrides entitlement, visibility, copyright, or moderation state.

### Gate 2 - Abuse and misuse

1. Highest amplification actor: popular video playback and upload/transcode fan-out, where one video can create billions of segment requests or dozens of renditions
2. Authenticated abuse surfaces: view-count events, upload sessions, comments/live chat, recommendation refresh, scraping manifests, CDN cache-busting, transcode retries
3. Quota dimensions: per-viewer event, per-IP/player, per-channel upload/storage, per-video view dedupe, per-region origin miss, per-transcode queue, global CDN miss cap
4. Global safety caps are separate from per-principal quotas so one bug cannot consume the fleet.
5. Entity-key limits protect hot keys even when all callers are legitimate.
6. Worker concurrency limits protect downstream stores from replay storms and fan-out storms.
7. Retry budgets are finite, jittered, and tied to user intent or idempotency keys.
8. Retry hazard: players retrying segment misses and transcode jobs retrying large renditions while origin/CDN is already saturated
9. Telemetry separating flash crowd from abuse: viewer/device entropy, watch duration, segment miss ratio, repeated range requests, upload failure rate, bot-like event timing, origin egress slope
10. Organic spikes preserve normal identity diversity; attacks show skewed principals, IPs, clients, or entities.
11. Abuse controls emit allow/deny/throttle decisions into a stream suitable for forensics.
12. Degradation sheds optional work before it rejects correctness-critical operations.
13. Runbooks say when to pause producers, disable retries, or drop optional enrichments.
14. A good answer includes both prevention and incident-time containment.
15. A weak answer only says add rate limiting without keys, budgets, or kill switches.
16. Model summary: View fraud and cache-busting look like traffic; controls need dedupe, origin-miss budgets, and channel-level quotas.

### Gate 3 - Multi-tenant isolation

1. Tenancy model: creator/channel tenant, viewer account, region, content visibility class, advertiser/monetization tenant, CDN distribution/origin prefix
2. Tenant/context propagation: channel_id, video_id, visibility, region, rights policy, ad tenant, and request_id propagate through metadata, Kafka events, S3 prefixes, search, recsys, logs, and support tools
3. Shared resource reservations: per-channel upload/transcode slots, origin request budgets, recommendation feature budgets, view aggregation partitions, moderation queue capacity
4. Every cache key, queue message, object prefix, metric label, and support export carries tenant/context explicitly.
5. Missing tenant/context is a policy error, not a default-to-global behavior.
6. Async jobs include context in the payload and in the worker authorization decision.
7. Support tools filter by tenant/context server-side and log the exact export scope.
8. Noisy-neighbor control: freeze one channel upload queue, demonetize/disable one video, cap one region origin miss, route one distribution to safe cache policy, or pause one transcode ladder
9. Large tenants or hot entities can be isolated into dedicated shards/cells/topics without global migration.
10. Backfills and replays run in tenant-scoped lanes with byte and concurrency budgets.
11. Observability cardinality is bounded so one tenant cannot bankrupt metrics ingestion.
12. Isolation test: private video cannot be fetched through stale CDN URL, search index, recommendation feed, analytics export, or support download after visibility change
13. Disaster recovery restores tenant boundaries, not only bytes.
14. A good answer names logical isolation and physical capacity isolation.
15. A weak answer says tenant_id column and stops there.
16. Model summary: Channel/video visibility and rights policy are the tenant boundary; cache, search, and analytics all need the same context.

### Gate 4 - Unit cost at target scale

1. Business unit: one watched video minute plus one upload/transcode job
2. Rough unit-cost model: egress dominates watched minutes; upload cost scales by raw storage plus transcode ladder; recommendations and view aggregation are secondary but material at global scale
3. Dominant line items: CDN egress, origin miss traffic, S3 storage, MediaConvert/FFmpeg GPU/CPU, live ingest, recommendation inference, Kafka/Flink view events, observability
4. Include replication, idle headroom, cross-AZ/region transfer, observability, and replay capacity.
5. Separate fixed control-plane cost from variable data-plane cost.
6. Track p50 and p99 cost because tail work often drives autoscaling and queue depth.
7. Chargeback/showback attributes cost by tenant/context, feature, endpoint, and deploy version.
8. Cost alert before margin/SLO breach: cost per thousand watched minutes, origin miss cost per video, and transcode cost per uploaded hour
9. Capacity planning includes event-day peak multiplier, not only daily average.
10. Cost regressions need rollback criteria just like latency regressions.
11. Graceful cost reduction: serve lower bitrate, disable autoplay/recommendation refresh, delay high-resolution transcodes, shorten analytics freshness, pause non-critical thumbnails while preserving playback and source durability
12. Never reduce cost by weakening correctness, auth, audit, or durability guarantees.
13. Cold storage, compaction, tiering, sampling, and caching are explicit levers with owners.
14. A good answer can defend an order-of-magnitude number on a whiteboard.
15. A weak answer lists cloud products without pricing the business unit.
16. Model summary: Playback economics are controlled by CDN hit ratio; a small TTL mistake can dominate all other costs.

### Gate 5 - Failure blast radius

1. Smallest intended failure boundary: video_id, channel_id, CDN behavior/distribution, origin prefix, transcode queue, Kafka partition, region
2. Shared dependencies between critical and optional paths: S3 origin shared by segment playback and publish pipeline; Kafka shared by views and recommendations; CDN policy shared by many videos
3. Fail closed: private playback, delete/unpublish, copyright blocks, monetization changes, upload finalization
4. Serve stale or degraded: public immutable segments, stale view count with monotonic guarantee, cached recommendations, processing status
5. Disable first: recommendation personalization, autoplay, non-critical analytics, high-res transcodes, comments/live chat, creator dashboard freshness
6. Runbook hazard that widens blast radius: lowering segment TTL globally, invalidating all segments, bypassing entitlement at CDN, or scaling transcode while origin is the bottleneck
7. Bulkheads separate user-facing serving from analytics, backfill, replay, and support tooling.
8. Feature flags are scoped by cell/region/tenant/entity, with a global kill only for known-safe toggles.
9. Queues have dead-letter and replay throttles; replay is never unbounded during recovery.
10. Caches have namespace-level invalidation; global flushes require incident commander approval.
11. Autoscaling must not scale a bad retry loop faster than dependencies can absorb it.
12. Game day: prime-time TTL regression with origin miss storm, S3 503s, view-count lag/drop, and red-herring transcode backlog
13. Alerts fire on leading indicators inside the boundary before customers see platform-wide impact.
14. A good answer says what remains working when one shard/cell/topic fails.
15. A weak answer treats multi-region replication as a substitute for blast-radius design.
16. Model summary: Keep a bad cache rule or video hot spot inside one distribution/video class and protect playback by preserving long-lived immutable segment caching.

---

## Evaluator Rubric and Red Flags

1. Names the core correctness invariant for video upload and playback platform: source video is durable after upload acknowledgment, private content stays private, and published immutable segments serve with correct entitlement and cache policy
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

1. Treating caches, queues, or CDN as the source of truth when video upload and playback platform needs durable reconciliation.
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

1. Verify dashboards expose user-impact SLOs for video upload and playback platform.
2. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
3. Verify the runbook has a rollback step and a separate reconciliation step.
4. Verify each queue or stream has bounded retry and dead-letter handling.
5. Verify every emergency command is scoped to the smallest safe boundary.
6. Verify post-incident cleanup drains backlog without violating customer promises.
7. Verify schema/config changes cannot bypass review or automated policy checks.
8. Verify tenant/context labels are present in logs without leaking secrets or PII.
9. Verify load tests include skewed traffic, not only uniform distributions.
10. Verify cost dashboards break down the business unit by feature and tenant/context.
11. Verify dashboards expose user-impact SLOs for video upload and playback platform.
12. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
13. Verify the runbook has a rollback step and a separate reconciliation step.
14. Verify each queue or stream has bounded retry and dead-letter handling.
15. Verify every emergency command is scoped to the smallest safe boundary.
16. Verify post-incident cleanup drains backlog without violating customer promises.
17. Verify schema/config changes cannot bypass review or automated policy checks.
18. Verify tenant/context labels are present in logs without leaking secrets or PII.
19. Verify load tests include skewed traffic, not only uniform distributions.
20. Verify cost dashboards break down the business unit by feature and tenant/context.
21. Verify dashboards expose user-impact SLOs for video upload and playback platform.
22. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
23. Verify the runbook has a rollback step and a separate reconciliation step.
24. Verify each queue or stream has bounded retry and dead-letter handling.
25. Verify every emergency command is scoped to the smallest safe boundary.
26. Verify post-incident cleanup drains backlog without violating customer promises.
27. Verify schema/config changes cannot bypass review or automated policy checks.
28. Verify tenant/context labels are present in logs without leaking secrets or PII.
29. Verify load tests include skewed traffic, not only uniform distributions.
30. Verify cost dashboards break down the business unit by feature and tenant/context.
31. Verify dashboards expose user-impact SLOs for video upload and playback platform.
32. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
33. Verify the runbook has a rollback step and a separate reconciliation step.
34. Verify each queue or stream has bounded retry and dead-letter handling.
35. Verify every emergency command is scoped to the smallest safe boundary.


---
