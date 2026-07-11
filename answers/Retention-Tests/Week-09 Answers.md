# Answer Key - Week-09

> Open only after attempting `Retention-Tests/Week-09.md`.

## Part 1: Rapid-fire model answers

**A01 [W1 DNS]**
- Prompt focus: A Route 53 failover changes the A record, but Java clients keep the old endpoint for hours. What cache behavior and JVM setting explain it?
- Model answer: DNS/JVM caching can pin stale answers; check TTLs and `networkaddress.cache.ttl`. Bad fix: repeated DNS changes without client restart or cache policy.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A02 [W1 CDN]**
- Prompt focus: A product response with `Set-Cookie` is cached at the edge and served cross-user. What header and cache-key evidence proves the leak?
- Model answer: Personalized responses must vary by auth/session or be private/no-store. Evidence is `Set-Cookie`, missing `Cache-Control: private/no-store`, and cache key lacking user/auth context.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A03 [W1 HTTP/2]**
- Prompt focus: A gRPC client uses one long-lived HTTP/2 connection through an L4 load balancer and one backend is hot. Explain why scaling pods does not fix it.
- Model answer: HTTP/2 multiplexes many streams over one connection; an L4 balancer chooses at connection creation. Need more channels, L7/xDS balancing, or connection draining.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A04 [W1 TCP]**
- Prompt focus: Outbound calls fail with `EADDRNOTAVAIL`, high `TIME_WAIT`, and normal upstream CPU. What resource is exhausted?
- Model answer: Ephemeral ports or NAT connection tracking are exhausted. Reuse connections, pool clients, reduce per-request dials; kernel tuning alone is incomplete.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A05 [W1 WebSocket]**
- Prompt focus: A gateway deploy drops 600k sockets and reconnects arrive in a synchronized spike. Name the client and gateway defenses.
- Model answer: Use exponential backoff with jitter, reconnect admission control, per-IP/device limits, and staged draining. Fixed retry is the bad fix.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A06 [W2 SQL]**
- Prompt focus: A query `tenant_id=? AND created_at>?` is slow only for one large tenant. Name two planner/index explanations.
- Model answer: Stats may hide skew; a composite index order may not match predicates/order. Use tenant-aware stats, partial indexes, or custom plans for whales.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A07 [W2 NoSQL]**
- Prompt focus: A DynamoDB table partitions by `tenant_id`; one seller consumes 70% of WCU. Why is average table utilization misleading?
- Model answer: Hot partition/key and tenant fairness matter more than table average. Need per-partition/per-tenant WCU, adaptive sharding, and throttles.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A08 [W2 Cache]**
- Prompt focus: Redis key `product:123` stores tenant-specific price. Which invariant is missing?
- Model answer: Cache namespace/key must include tenant, price list, auth/audience, and version. Bad fix: longer TTL on a wrong key.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A09 [W2 LSM]**
- Prompt focus: An LSM store has high L0 files, pending compaction bytes, and p99 write stalls. What should you reject?
- Model answer: Reject unlimited write concurrency or major compaction during peak. Shed writes, add compaction/disk headroom, and tune flush/compaction.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A10 [W2 Cache Stampede]**
- Prompt focus: A hot key expires and database QPS jumps 80x. What pattern prevents it?
- Model answer: Use singleflight/request coalescing, probabilistic early refresh, stale-while-revalidate, and TTL jitter.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A11 [W3 CAP]**
- Prompt focus: During a partition, checkout rejects stale payment authorization but dashboards stay stale. Which tradeoff does each choose?
- Model answer: Checkout chooses consistency/safety over availability for money; dashboards choose availability with stale data. State the invariant per path.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A12 [W3 Consistency]**
- Prompt focus: A user changes a setting, refreshes, and sees the old value. Which session guarantee failed?
- Model answer: Read-your-writes/session consistency failed. Route to primary or a replica caught up to required version/LSN.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A13 [W3 Quorum]**
- Prompt focus: RF=3, W=1, R=1 is used for carts. What anomaly must product accept?
- Model answer: Stale reads and lost/overwritten updates under failures are possible. Product must accept eventual convergence or raise quorum/coordination.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A14 [W3 Hashing]**
- Prompt focus: Moving from `hash(id) mod 20` to `mod 24` moves most keys. What strategy lowers movement?
- Model answer: Modulo remaps most keys; consistent hashing/rendezvous hashing with virtual nodes moves a smaller fraction.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A15 [W3 Clocks]**
- Prompt focus: Two auth services disagree whether a JWT is expired by 90 seconds. What do you inspect?
- Model answer: NTP offset, leeway, issuer/audience clocks, monotonic vs wall clock usage, and token `iat/nbf/exp` validation.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A16 [W4 Replication]**
- Prompt focus: An async replica is used for fraud margin checks and lags 45 seconds. Why is that unacceptable?
- Model answer: The invariant needs fresh authorization/risk state. Use primary or required-LSN replica routing; stale derived reads can approve unsafe orders.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A17 [W4 Raft]**
- Prompt focus: A candidate missing a committed log entry requests votes. Why reject it?
- Model answer: Raft election safety requires voters choose an up-to-date log; otherwise committed entries can be lost.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A18 [W4 Sharding]**
- Prompt focus: One seller import opens 500 DB connections and unrelated sellers time out. Which resource lacked reservation?
- Model answer: Shared connection/thread/IO pools lacked per-tenant quotas or bulkheads. Fleet capacity was not reserved by tenant/workload.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A19 [W4 CDC]**
- Prompt focus: A replication slot retains WAL while Kafka is unhealthy. Which metric pages before disk fills?
- Model answer: Slot retained bytes and source lag/time-to-fill on WAL disk. Do not drop the slot without recovery plan.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A20 [W4 Failover]**
- Prompt focus: An old leader recovers and still accepts writes after failover. Name the prevention mechanism.
- Model answer: Fencing tokens/leases/epochs and client routing that refuses stale leaders prevent split-brain writes.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A21 [W5 Pooling]**
- Prompt focus: PgBouncer queue depth rises while Postgres CPU is 35%. Name two possible bottlenecks.
- Model answer: Server connection cap, transaction pooling misuse, locks, slow queries, or app pool starvation can bottleneck before CPU.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A22 [W5 CQRS]**
- Prompt focus: Search is stale but OLTP write succeeded. What lag proves the read model is behind?
- Model answer: Projection lag by LSN/offset, oldest unprocessed event age, and source-to-index freshness prove CQRS delay.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A23 [W5 Cassandra]**
- Prompt focus: Tombstones per read jump to 100k after deletes. Why can reads fail while writes are fine?
- Model answer: Reads scan tombstones/SSTables and compaction debt; writes append. Need TTL/TWCS/bucketing and safe cleanup.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A24 [W5 Sharding]**
- Prompt focus: A composite key omits tenant for a multi-tenant table. What incident shape follows?
- Model answer: Hot/cross-tenant partitions, noisy neighbors, and authorization/cache bugs. Choose shard key around access pattern and isolation.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A25 [W6 Kafka]**
- Prompt focus: Consumer lag is high for one partition only. What does that imply before adding consumers?
- Model answer: Hot key/partition or poison message. One consumer owns a partition, so adding consumers alone may not help.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A26 [W6 Outbox]**
- Prompt focus: Checkout writes DB then publishes Kafka outside the transaction. What failure window exists?
- Model answer: DB commit can succeed while publish fails or publish can succeed then DB rollbacks. Outbox commits state and event atomically.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A27 [W6 Saga]**
- Prompt focus: A refund saga calls PSP twice after timeout. Which persisted key prevents duplicate external effect?
- Model answer: A stable PSP idempotency/operation key tied to the saga step, with a durable saga log and fencing.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A28 [W6 Backpressure]**
- Prompt focus: Email service slows and Kafka lag grows. What degradation is safe?
- Model answer: Throttle or pause low-priority email, DLQ/quarantine poison records, preserve money/inventory events, and drain within headroom.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A29 [W6 Circuit]**
- Prompt focus: A dependency has p99 8s and clients retry every 200ms. What pattern reduces blast radius?
- Model answer: Bounded timeout, exponential backoff with jitter, circuit breaker, and bulkhead isolation.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A30 [W7 Rate Limit]**
- Prompt focus: A shared token bucket lets one tenant spend all burst credits. What limiter hierarchy protects others?
- Model answer: Global plus per-tenant plus per-user/endpoint buckets, weighted quotas, and priority pools.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A31 [W7 ID]**
- Prompt focus: Kubernetes pods share the same Snowflake worker id. Why do duplicate IDs appear?
- Model answer: Same timestamp + worker id + sequence space can collide; use leased/fenced worker IDs and clock rollback handling.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A32 [W7 Search]**
- Prompt focus: OpenSearch shards reach 120GB and recovery takes hours. What invariant was missed?
- Model answer: Rollover/shard-size targets and recovery-time objectives. Keep shard sizes and segment counts within operational limits.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A33 [W7 Flags]**
- Prompt focus: A tenant-scoped flag evaluates true globally when context is missing. What default should apply?
- Model answer: Fail closed/safe for critical paths; require targeting context and have fast kill switches/guardrails.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A34 [W7 LB]**
- Prompt focus: mTLS handshakes spike on every request after a client change. Which signal matters?
- Model answer: Connection reuse/pool hit rate, TLS handshake rate, and upstream keepalive. Per-request dials overload CPU/latency.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A35 [W8 Observability]**
- Prompt focus: Adding raw tenant_id and order_id to every metric creates millions of series. What is safer?
- Model answer: Bound labels, use exemplars/logs/traces for high-cardinality IDs, tenant allowlists, and aggregation.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A36 [W8 SLO]**
- Prompt focus: Global availability is green but enterprise tier is red. Which budget matters?
- Model answer: The contractual slice: enterprise/region/payment path. Global averages can hide SLO burn.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A37 [W8 Alerting]**
- Prompt focus: CPU pages fire during a batch job while users are fine. What should page instead?
- Model answer: User-visible SLO burn, error rate, latency, saturation that predicts customer impact, or correctness failures.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A38 [W8 Geo]**
- Prompt focus: Driver location older than 90 seconds remains matchable. What guard is missing?
- Model answer: Freshness TTL/heartbeat gating and ETA by freshness bucket. Disable stale supply rather than widen radius blindly.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A39 [W8 Causality]**
- Prompt focus: Trace spans show event B before event A across services. What does wall-clock time not prove?
- Model answer: Wall clocks do not prove causality. Use domain sequence, Lamport clocks, vector clocks, or parent operation IDs.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A40 [W8 CRDT]**
- Prompt focus: A deleted cart item reappears after offline sync. What merge rule is suspect?
- Model answer: Last-write-wins without tombstones/causal context. Use observed-remove semantics and checkout revalidation.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A41 [W8 Clocks]**
- Prompt focus: A coupon expires early in one region and late in another. What is the likely class of bug?
- Model answer: Wall-clock skew in correctness decisions. Centralize validation or use DB/server time, plus NTP offset alerts.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A42 [08b Auth]**
- Prompt focus: JWT has valid signature and issuer but wrong audience. What vulnerability appears if accepted?
- Model answer: Confused-deputy/cross-service token acceptance. Validate audience, issuer, scopes, tenant, and token type.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A43 [08b mTLS]**
- Prompt focus: mTLS fails only checkout -> ledger in one AZ. What facts do you compare?
- Model answer: Client/server cert chain, SAN, SPIFFE ID, trust bundle, expiry, mesh policy, and AZ-specific rollout.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A44 [08b Cost]**
- Prompt focus: NAT gateway bytes jump after analytics deploy. Why may compute scaling be wrong?
- Model answer: The bottleneck/cost is egress path and cross-AZ/region traffic, not CPU. Inspect byte paths before scaling.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A45 [08b Tenancy]**
- Prompt focus: Support exports by order_id without tenant context. What invariant is missing?
- Model answer: Authorization and data access must include tenant boundary in every path, not only table schema.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A46 [08b Noisy Neighbor]**
- Prompt focus: A seller export starves checkout in a shared pool. What isolation is missing?
- Model answer: Workload/tenant bulkheads, quotas, priority queues, and admission control for expensive jobs.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A47 [W9 Feed]**
- Prompt focus: Why does a home timeline use write fan-out for normal users but hybrid/read fan-out for celebrities? Add the mechanism you would name in a Northstar incident.
- Model answer: Celebrity followers create extreme write amplification; normal users benefit from precomputed reads. Hybrid stores celebrity tweets once and merges at read time. Include the mechanism explicitly and tie it to a metric or invariant.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A48 [W9 Feed]**
- Prompt focus: What is the celebrity problem in a 50M-follower account? Add the evidence you would name in a Northstar incident.
- Model answer: One post becomes tens of millions of timeline writes, cache updates, replication events, and retries for one action. Include the evidence explicitly and tie it to a metric or invariant.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A49 [W9 Feed]**
- Prompt focus: Why are Redis sorted sets useful for cached timelines, and what hot-key risk appears? Add the first mitigation you would name in a Northstar incident.
- Model answer: They support scored ordering/pagination and trimming. Shared celebrity keys or whale timelines can hot-spot one shard. Include the first mitigation explicitly and tie it to a metric or invariant.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A50 [W9 Feed]**
- Prompt focus: How do tombstones help deleted tweets in cached timelines? Add the bad fix you would name in a Northstar incident.
- Model answer: Read-time tombstone/visibility checks hide deleted or blocked content before async cleanup removes timeline IDs. Include the bad fix explicitly and tie it to a metric or invariant.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A51 [W9 Chat]**
- Prompt focus: How do you preserve per-chat order when mobile retries a message? Add the capacity check you would name in a Northstar incident.
- Model answer: Use client message id, server id/sequence, chat-keyed ordered log, and idempotent ingress/fan-out. Include the capacity check explicitly and tie it to a metric or invariant.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A52 [W9 Chat]**
- Prompt focus: Why is presence allowed to be stale but message history is not? Add the durable guardrail you would name in a Northstar incident.
- Model answer: Presence is ephemeral and approximate; accepted messages are durable user data with ordering expectations. Include the durable guardrail explicitly and tie it to a metric or invariant.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A53 [W9 Social Ops]**
- Prompt focus: Why is scaling fan-out consumers insufficient when lag is on one partition? Add the tenant/blast-radius check you would name in a Northstar incident.
- Model answer: Only one consumer owns the hot partition; downstream Redis/Cassandra may already be saturated. Include the tenant/blast-radius check explicitly and tie it to a metric or invariant.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A54 [W9 WebSocket]**
- Prompt focus: What bid-notification SLO signal should override a feed launch? Add the recovery step you would name in a Northstar incident.
- Model answer: Live bid delivery latency/error rate is a critical user path; social boost should be shed first. Include the recovery step explicitly and tie it to a metric or invariant.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A55 [W9 Cache]**
- Prompt focus: What should a celebrity_recent cache key include to avoid cross-tenant or stale visibility? Add the alerting signal you would name in a Northstar incident.
- Model answer: Seller id, visibility/version, locale/audience where relevant, TTL, and invalidation/tombstone checks. Include the alerting signal explicitly and tie it to a metric or invariant.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A56 [W9 Recovery]**
- Prompt focus: How do you rebuild stale timelines without a second incident? Add the design invariant you would name in a Northstar incident.
- Model answer: Drain lag with bounded concurrency, lazy rebuild active users, read-time merge source timelines, and monitor downstream headroom. Include the design invariant explicitly and tie it to a metric or invariant.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A57 [W9 Feed]**
- Prompt focus: Why does a home timeline use write fan-out for normal users but hybrid/read fan-out for celebrities? Add the runbook owner you would name in a Northstar incident.
- Model answer: Celebrity followers create extreme write amplification; normal users benefit from precomputed reads. Hybrid stores celebrity tweets once and merges at read time. Include the runbook owner explicitly and tie it to a metric or invariant.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A58 [W9 Feed]**
- Prompt focus: What is the celebrity problem in a 50M-follower account? Add the mechanism you would name in a Northstar incident.
- Model answer: One post becomes tens of millions of timeline writes, cache updates, replication events, and retries for one action. Include the mechanism explicitly and tie it to a metric or invariant.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A59 [W9 Feed]**
- Prompt focus: Why are Redis sorted sets useful for cached timelines, and what hot-key risk appears? Add the evidence you would name in a Northstar incident.
- Model answer: They support scored ordering/pagination and trimming. Shared celebrity keys or whale timelines can hot-spot one shard. Include the evidence explicitly and tie it to a metric or invariant.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A60 [W9 Feed]**
- Prompt focus: How do tombstones help deleted tweets in cached timelines? Add the first mitigation you would name in a Northstar incident.
- Model answer: Read-time tombstone/visibility checks hide deleted or blocked content before async cleanup removes timeline IDs. Include the first mitigation explicitly and tie it to a metric or invariant.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A61 [W9 Chat]**
- Prompt focus: How do you preserve per-chat order when mobile retries a message? Add the bad fix you would name in a Northstar incident.
- Model answer: Use client message id, server id/sequence, chat-keyed ordered log, and idempotent ingress/fan-out. Include the bad fix explicitly and tie it to a metric or invariant.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A62 [W9 Chat]**
- Prompt focus: Why is presence allowed to be stale but message history is not? Add the capacity check you would name in a Northstar incident.
- Model answer: Presence is ephemeral and approximate; accepted messages are durable user data with ordering expectations. Include the capacity check explicitly and tie it to a metric or invariant.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A63 [W9 Social Ops]**
- Prompt focus: Why is scaling fan-out consumers insufficient when lag is on one partition? Add the durable guardrail you would name in a Northstar incident.
- Model answer: Only one consumer owns the hot partition; downstream Redis/Cassandra may already be saturated. Include the durable guardrail explicitly and tie it to a metric or invariant.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A64 [W9 WebSocket]**
- Prompt focus: What bid-notification SLO signal should override a feed launch? Add the tenant/blast-radius check you would name in a Northstar incident.
- Model answer: Live bid delivery latency/error rate is a critical user path; social boost should be shed first. Include the tenant/blast-radius check explicitly and tie it to a metric or invariant.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A65 [W9 Cache]**
- Prompt focus: What should a celebrity_recent cache key include to avoid cross-tenant or stale visibility? Add the recovery step you would name in a Northstar incident.
- Model answer: Seller id, visibility/version, locale/audience where relevant, TTL, and invalidation/tombstone checks. Include the recovery step explicitly and tie it to a metric or invariant.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A66 [W9 Recovery]**
- Prompt focus: How do you rebuild stale timelines without a second incident? Add the alerting signal you would name in a Northstar incident.
- Model answer: Drain lag with bounded concurrency, lazy rebuild active users, read-time merge source timelines, and monitor downstream headroom. Include the alerting signal explicitly and tie it to a metric or invariant.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A67 [W9 Feed]**
- Prompt focus: Why does a home timeline use write fan-out for normal users but hybrid/read fan-out for celebrities? Add the design invariant you would name in a Northstar incident.
- Model answer: Celebrity followers create extreme write amplification; normal users benefit from precomputed reads. Hybrid stores celebrity tweets once and merges at read time. Include the design invariant explicitly and tie it to a metric or invariant.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A68 [W9 Feed]**
- Prompt focus: What is the celebrity problem in a 50M-follower account? Add the runbook owner you would name in a Northstar incident.
- Model answer: One post becomes tens of millions of timeline writes, cache updates, replication events, and retries for one action. Include the runbook owner explicitly and tie it to a metric or invariant.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A69 [W09 Mix]**
- Prompt focus: A launch feature touches checkout, Kafka, Redis, and search. What decides which subsystem gets protected first?
- Model answer: The product invariant: money, inventory, tenant isolation, and source-of-truth writes outrank freshness and analytics.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A70 [W09 Mix]**
- Prompt focus: A global dashboard is green while one paid tier is red. What is your next query?
- Model answer: Slice by tenant tier, region, endpoint, dependency, and client version; page on contractual SLO burn.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A71 [W09 Mix]**
- Prompt focus: A team proposes replaying all backlog at max concurrency. What do you ask first?
- Model answer: Downstream headroom, idempotency keys, ordering constraints, replay rate, and time-to-drain.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A72 [W09 Mix]**
- Prompt focus: A cache contains derived state. When can it be source of truth?
- Model answer: Almost never for checkout/money/inventory; only if explicitly designed as authoritative with durability and reconciliation.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A73 [W09 Mix]**
- Prompt focus: A retry storm starts after a dependency p99 spike. Name the limiter stack.
- Model answer: Timeouts, exponential backoff with jitter, retry budget, circuit breaker, bulkhead, queue admission.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A74 [W09 Mix]**
- Prompt focus: A NoSQL hot partition appears during a celebrity or enterprise event. What metric disproves fleet-average comfort?
- Model answer: Per-partition/key load, replica-set CPU, p99 by key/tenant, throttles, and queue/compaction debt.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A75 [W09 Mix]**
- Prompt focus: A bad flag is cached on mobile for 30 minutes. What rollback design should exist?
- Model answer: Server-side kill switch, short TTL for critical flags, fail-closed defaults, and forced config refresh/version denylist.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A76 [W09 Mix]**
- Prompt focus: An incident bridge wants to lower durability to recover p99. What process applies?
- Model answer: Senior approval with explicit RPO/data-loss statement; prefer shedding noncritical work first.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A77 [W09 Mix]**
- Prompt focus: Support asks for affected customers. What data do you preserve?
- Model answer: Incident window, source-of-truth records, IDs/offsets/LSNs, logs/traces without PII leakage, and customer-impact markers.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

**A78 [W09 Mix]**
- Prompt focus: What distinguishes a passing answer from a principal answer in this curriculum?
- Model answer: Mechanism plus evidence, safe sequencing, capacity math, invariant protection, and org/runbook ownership.
- Must include: layer/mechanism, evidence signal, protected invariant, and one rejected bad fix.

---

## Part 2: Compound scenario answer

### Executive diagnosis

The correct answer starts from the affected slice, not the global dashboard. Name the current-week system under stress, then show how retries, queues, caches, or observability amplified the incident. Preserve source-of-truth correctness and degrade lower-value user experience first.

### Evidence map

Use these evidence classes:
- Sliced SLO/user signal beats global availability.
- Current-week telemetry identifies the domain-specific mechanism.
- Spaced foundation signals reveal amplifiers: retry storms, hot partitions, pool saturation, stale replicas, CDC lag, or cardinality explosions.
- Config proves why the bad mitigation was possible.

### First 15-minute mitigation

1. Declare P1 and assign an incident commander.
2. Freeze launch flags, deploys, rebalances, schema changes, and bulk replay touching the path.
3. Restore or activate the safest kill switch for the launch behavior.
4. Shed noncritical work: dashboards, recommendations, exports, notifications, transcoding, or low-priority AI jobs before weakening checkout correctness.
5. Bound retries with jitter and enforce retry budgets/admission control.
6. Protect the source of truth and mark uncertain outcomes for reconciliation.
7. Verify with sliced SLI, scarce-resource metric, lag derivative, and customer-visible error rate.

### Bad-fix gallery

| Bad fix | Why it fails |
|---------|--------------|
| Trust the green global dashboard | Hides tier/region/client slice burn and delays incident response. |
| Replay or scale backlog at max concurrency | Moves queue pressure into downstream stores and can create duplicate effects. |
| Lower durability/consistency globally | Trades correctness for p99 and may create money/inventory/tenant incidents. |
| Use cache/search/telemetry as source of truth | Derived systems can be stale, partial, or overloaded. |
| Add high-cardinality labels during incident | Can take down observability when it is most needed. |

### Capacity answer

Compute at least one of: backlog drain time, retry amplification, hot key/partition share, pool waiters vs server connections, disk/WAL time-to-fill, shard recovery time, token/GPU queue time, or affected-record count. A principal answer states safe ceiling, current rate, derivative, and rollback threshold.

### Repair/reconciliation

Define affected set from source-of-truth records, stable operation ids, offsets/LSNs, and incident window. Replay with idempotency and throttles. Communicate stale windows and customer impact only after deduplication and source-of-truth checks.

### Durable changes

- Add sliced SLOs and multi-window burn-rate alerts for the critical user tier/path.
- Make launch flags fail closed with server-side kill switches and guardrails.
- Add capacity simulation and replay drills for the current-week architecture.
- Enforce idempotency, schema/contracts, and source-of-truth boundaries in CI and runtime admission.
- Update runbook ownership: incident command, service owner, data/platform owner, product, support, and security/payments when needed.

### Scoring guide

| Area | Points |
|------|--------|
| Rapid-fire mechanism accuracy | 32 |
| Root cause and evidence mapping | 18 |
| Safe incident sequencing | 16 |
| Capacity math | 10 |
| Correctness and repair plan | 12 |
| Durable design/runbook changes | 12 |

Pass gate: 85%+ with no critical miss on source-of-truth correctness or unsafe first action.
