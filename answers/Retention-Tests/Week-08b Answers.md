# Week-08b Answers

Open only after attempting the retention questions.

## Part 1: Rapid-fire answers

1. Likely missing Vary/Cookie/Authorization or personalized response
   cached publicly. Evidence: cache status HIT for personalized route,
   identical cache key across sessions, response headers lacking
   private/no-store, and CDN logs serving the same object to different
   users.
2. HTTP/2 multiplexes streams on one connection, so connection-level
   flow control or TCP loss can affect many streams. HTTP/1.1 usually
   isolates requests across more connections but pays request/connection
   head-of-line costs.
3. Leading metrics include compaction pending bytes, write stall time,
   L0 file count, disk write bandwidth, and p99 memtable flush latency.
   Bad fix: blindly adding write threads without disk capacity or
   compaction strategy.
4. Missing idempotency/exactly-once business effect. Use an idempotency
   key or payment operation key persisted with result before retry.
5. Linearizability/read-your-writes/durability of acknowledged writes
   depending protocol. A stale leader accepting writes risks lost or
   divergent writes.
6. A generic cached plan for small tenants may scan badly for a large
   tenant; also missing tenant-specific/partial index, stale stats,
   parameter sniffing, or partition pruning failure.
7. Consumer CPU slow, downstream DB/search slow, partition skew/hot
   broker, rebalance churn, deserialization/schema errors, or
   fetch/commit config bottleneck.
8. A flag evaluation test requiring tenant context and default-deny for
   missing tenant; config diff should show targeted tenant list and
   canary parity.
9. It creates high cardinality and may leak tenant identity. Use
   tier/shard/cell metrics plus top-N heavy-hitter logs or controlled
   exemplars.
10. Compare issuer, audience, allowed algorithm, JWKS key set/cache,
    kid, clock skew/leeway, token_use, policy bundle, and deny list.
11. Cost per successful order is allocated checkout-domain cost divided
    by successful orders. Forgotten costs include egress/cross-AZ,
    observability, auth/session/cache share, retries, replication, NAT,
    and idle headroom.
12. Every access path can omit or lose tenant_id: APIs, joins, caches,
    exports, search, support tools, background jobs, and connection-pool
    session state.

## Part 2: Scenario answers

1. API JWT validation/JWKS cache layer. Mitigate by publishing/forcing
   known-good JWKS with both keys, single-flight/negative cache, and
   pausing rotation. Reject disabling signature validation.
2. Cross-region raw data scan and data locality mistake. Degrade
   standard seller live analytics, switch to curated regional data or
   run near raw data, and restore sampling/compression.
3. Per-tenant/job-class DB connection and concurrency limiter with
   checkout reserved pool. Raising max_connections increases memory and
   scheduling pressure and may worsen DB latency.
4. Tenant cache-key bleed. Immediately stop route or invalidate affected
   key class and deploy tenant-scoped key. Test key builders require
   tenant context for tenant-specific data.
5. Partition key creates a hot tenant partition and no producer
   quota/fairness. Need better keying, quotas, dedicated topic/cell for
   hot seller, or workload separation.
6. $0.24 - $0.18 = $0.06/order. 120,000/min * $0.06 = $7,200/min =
   $432,000/hour above break-even.
7. Inspect client/server cert expiry, SAN/principal, trust-bundle
   version skew, unknown authority errors, sidecar TLS alerts,
   authorization policy denies, and cert issuance failures.
8. testSecret did not test the same fresh connection path through
   PgBouncer/app user, or setSecret did not update DB credential
   consistently before finishSecret promoted.
9. Preserve request logs, authz logs, support approval/audit, query
   result metadata, trace, user identity, tenant routing version.
   Include security, legal/privacy, support owner, service owner, and
   incident command.
10. Prior weeks: CDN caching, feature flags, origin capacity,
    observability. Week-08b: cost/unit economics, egress, capacity, and
    bad cost fix sequencing.

## Part 3: Decision answers

1. Browser checkout usually prefers HttpOnly Secure SameSite server
   session for XSS resistance and immediate revocation. Bearer token
   reduces lookup but is replayable if stolen and risky in localStorage.
2. Use shared/cell for long tail, partition/cell for bursty auction
   sellers, and dedicated DB/search/cache or account for
   enterprise/regulatory cases that pay for it. Avoid one global model.
3. Stable checkout: Savings Plan/reserved baseline plus on-demand
   headroom. Nightly interruptible jobs: spot with checkpointing.
   Unknown analytics: on-demand/serverless until shape stabilizes.
4. Global safety limit, tier entitlement, endpoint cost weights,
   per-tenant concurrency for analytics, checkout reserved capacity,
   top-N tenant logs, metrics by tier/shard/cell.
5. Need p95/p99 CPU and memory, throttling, latency, queue depth,
   failover headroom, event calendar, dependency limits, HPA behavior,
   canary/rollback, and cost per successful unit.
6. Wrong audience. Accepting it lets seller-admin delegated authority
   act as checkout authority, a confused-deputy vulnerability.
7. Versioned tenant route map, cache TTL, dual-write idempotency,
   read-after-write checks, source authoritative until verified,
   count/hash comparison, rollback route, destination capacity, affected
   tenants.
8. Incident sampling override with expiry, approval, and automatic
   reversion to tail/error sampling; alert on ingest slope by
   deploy/owner.

## Part 4: Mini Ops Sim sample

1. Freeze/mark deploy and build a shared timeline. Metric: deploy events
   by service. Reject random rollbacks before identifying blast radii.
2. Check auth separately: 401 reason, JWKS, session latency. Reject
   disabling token validation.
3. Check shared resource pressure: Redis evictions/hot keys, Kafka hot
   partitions, DB connections by tenant. Reject global cache flush or
   raising all limits.
4. Check cost anomaly dimensions: egress/NAT/observability by feature
   and region. Reject cutting checkout capacity as first move.
5. Apply narrow mitigations by layer/tenant/feature, preserve security
   evidence, and communicate business tradeoffs. Reject hiding symptoms
   by turning off alerts.
