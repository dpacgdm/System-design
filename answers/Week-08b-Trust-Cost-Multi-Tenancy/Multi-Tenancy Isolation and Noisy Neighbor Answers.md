# Multi-Tenancy Isolation and Noisy Neighbor Answers

Open only after attempting the learner file Ops Sim.

## One Enterprise Seller Starves the Marketplace

### Q1 - Scarce resources

- Redis session cluster is saturated: p99 46 ms, 18k
  evicted session keys/min, and seller_4812 leaderboard
  consumes 41% ops.
- PostgreSQL shard 7 is saturated by seller_4812
  export/import: 190M rows, 840 GB temp spill, lock
  waits, and 640 of 700 connections.
- Kafka broker/partition is hot: seller_4812 is 61% of
  topic bytes, partition 113 lag is 19M, broker-9
  network is 96%.

### Q2 - P1 versus possible P0

The marketplace latency, Redis eviction, DB waits, and
Kafka lag are P1 availability/performance issues. The
tenant_context=null debug lookup and tenant_mismatch
denies are possible data-isolation symptoms and may be
P0 until proven otherwise. Preserve evidence while
mitigating performance narrowly.

### Q3 - First 15 minutes

1. Assign incident command plus separate security lead
   for data-isolation review.
2. Disable or restrict /internal/orders/debug and
   preserve logs/traces before rotation.
3. Apply tenant-specific limits to seller_4812 analytics
   export/import concurrency and Kafka producer bytes.
4. Move or cap seller_4812 leaderboard/cache workload
   away from session Redis; do not flush the session
   cluster.
5. Cancel or move the 365-day export to a replica/async
   report path; preserve checkout reserved DB
   connections.
6. Protect unrelated tenants by degrading seller
   analytics before checkout confirmation.

### Q4 - Bad fixes

- Flushing Redis evicts every tenant session and creates
  login/origin storms without fixing hot-key behavior.
- Raising PostgreSQL max_connections increases memory
  and scheduling pressure and usually worsens
  saturation.
- Disabling debug endpoint authorization increases
  possible data exposure during the incident.
- Moving seller_4812 without capacity math can overload
  the destination and create route-split bugs.

### Q5 - Capacity math

If seller_4812 is 61% of bytes and broker-9 is already
at 96% network, raising its quota by 50% adds roughly
30.5 percentage points of current pressure. Demand can
exceed 120% of safe broker capacity, causing producer
latency, ISR risk, consumer lag, and collateral damage.
Repartition or isolate before raising quota.

### Q6 - Durable fix

- Redis: separate session and leaderboard/analytics
  cache classes, tenant quotas, max value size, hot-key
  sharding, and command allowlists.
- PostgreSQL: per-tenant/job pools, checkout reserved
  connections, export timeouts, replica/offline exports,
  and RLS/session reset tests.
- Kafka: producer quotas, better partition keys,
  dedicated topics/cells for enterprise auctions,
  compression, and tenant-tier lag SLOs.
- Support tooling: mandatory tenant context, object
  authorization, approval workflow, immutable audit, and
  endpoint kill switch.
- Metrics: top-N tenant heavy hitters plus tier/shard
  metrics rather than tenant_id on every series.

### Q7 - Org and evidence

By T+10 include incident command, checkout, seller
analytics, DB, Kafka/platform, Redis/runtime, security,
legal/privacy if exposure is plausible, and customer
success for seller_4812 plus affected tenants. Preserve
request logs, authz logs, support approval logs, DB
audit, traces, cache samples, and tenant routing
versions.
