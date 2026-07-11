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

## Expanded Ops Sim Worked Analysis

### 1. Signal inventory

- Look for per-tenant skew across DB connections, temp spill, Redis ops, evictions, Kafka bytes, partition lag, search bulk queue, and worker concurrency.
- Fleet averages hide the problem because one tenant can be the P99 while average CPU stays low.
- Security signals such as tenant_context=null and tenant_mismatch denies are not performance noise; they are a parallel incident track.
- Top-N heavy hitters and tier/cell metrics give visibility without putting tenant_id on every time series.

### 2. Timeline reconstruction

- Mark seller import start, export start, cache hot key onset, Kafka partition skew, checkout latency rise, and support debug access.
- Identify which symptoms are caused by seller_4812 and which are independent deploy changes.
- Preserve routing-version and tenant-map changes in the timeline.
- Do not wait for complete proof of data exposure before disabling a suspect support endpoint.

### 3. Root cause statement

- The root performance cause is missing tenant and workload isolation for seller analytics/import paths sharing checkout resources.
- Redis session and leaderboard workloads share a blast radius; PostgreSQL checkout and exports share a pool; Kafka tenant_id keying creates a hot partition.
- The possible data-isolation cause is support/debug lookup without mandatory tenant context.
- This is both noisy-neighbor P1 and possible privacy P0 until evidence proves no exposure.

### 4. First 15 minutes

- Assign incident command and a separate security lead.
- Disable or restrict the debug export endpoint while preserving request and authorization logs.
- Apply tenant-specific caps to seller_4812 import/export connections, worker concurrency, Kafka producer bytes, and cache workload.
- Reserve checkout pools and degrade seller analytics before checkout confirmation.

### 5. What not to do

- Do not flush shared Redis; it evicts every tenant and creates a login storm.
- Do not raise PostgreSQL max_connections; memory and scheduler contention can worsen latency.
- Do not raise hot Kafka quota while the broker is already saturated.
- Do not migrate a whale tenant without destination capacity, route-map rollback, and dual-read verification.

### 6. Database isolation

- Use per-tenant and per-job-class pools with checkout reserved connections.
- Exports run on replicas/offline snapshots with timeouts and byte limits.
- Long imports need batching, lock-time budgets, and backpressure.
- RLS or application tenant filters must be tested with connection-pool session reset.

### 7. Cache isolation

- Session cache and leaderboard/analytics cache belong in separate clusters or namespaces with memory and command limits.
- Tenant-specific data requires tenant-scoped keys: `tenant:{id}:product:{id}` not `product:{id}`.
- Hot keys need sharding, local read-through caching, or dedicated enterprise cache lanes.
- Cache samples can contain sensitive data; preserve with privacy controls.

### 8. Kafka isolation

- Tenant_id alone preserves tenant ordering but creates whale partitions.
- Use composite keys where ordering allows, dedicated topics/cells for whales, producer quotas, compression, and per-tenant byte budgets.
- Monitor per-partition lag and broker network, not only topic-level lag.
- Replay and backfill consumers need separate quotas from live checkout consumers.

### 9. Support-tool isolation

- Support tools need explicit tenant context, approval workflow, object-level authorization, immutable audit, and kill switch.
- Order_id alone is rarely globally safe because IDs can collide, be guessed, or route to wrong tenant.
- Exports should include purpose, requester, approver, tenant, fields, row count, and trace ID.
- During incidents, support shortcuts are tempting; policy must fail closed.

### 10. Capacity math

- If one tenant is 61% of broker bytes and the broker is 96% network, a 50% quota increase adds roughly 30 percentage points of pressure.
- That pushes demand beyond safe capacity and risks ISR shrink, producer timeouts, and lag for unrelated tenants.
- For DB, 640 of 700 connections used by one tenant leaves no failover or checkout headroom.
- For Redis, 18k evictions/min in session cache is user-visible even if Redis CPU appears tolerable.

### 11. Safe tenant actions

- Throttle the tenant's analytics/import class, not their checkout buyers if avoidable.
- Move exports to offline reports and communicate delay to enterprise customer success.
- Isolate the hot seller into a dedicated cell only after route-map and capacity checks.
- Preserve contractual obligations by tier while protecting marketplace safety.

### 12. Telemetry strategy

- Use top-N tenant heavy-hitter streams, logs, exemplars, and sketches for high-cardinality detail.
- Metrics should be by tier, shard, cell, workload class, and top offender label where bounded.
- Trace sampling can be raised for one tenant/cell with expiry.
- Every async message carries tenant_id and route version for audit and replay.

### 13. Organizational ownership

- Seller analytics owns import/export behavior.
- Checkout owns reserved critical capacity and customer-facing SLO.
- DB/Kafka/Redis platform owners enforce quotas and isolation primitives.
- Security/legal/privacy own exposure assessment; customer success owns seller communications.

### 14. Acceptance criteria

- One tenant import cannot consume more than its pool, byte, or worker budget.
- Checkout p99 and success rate remain inside SLO during a whale seller game day.
- Cross-tenant cache/search/export tests fail closed.
- A tenant can be throttled or isolated within the runbook target without global side effects.

## Additional Ops Sim Drills

### Runbook drill: tenant import storm

- Start a large tenant import with checkout traffic active.
- Expected behavior: import consumes only its job-class pool and yields to checkout reserved capacity.
- Telemetry: connections by tenant/job, lock waits, temp spill, queue age, and checkout p99.
- Fail condition: global DB pool saturates while tenant limiter is absent.

### Runbook drill: cache namespace leak

- Write tenant A and tenant B values with same product id.
- Expected behavior: keys differ by tenant and object authorization still checks tenant.
- Telemetry: cache key builder test, sampled key names, and response tenant id.
- Fail condition: product id alone is sufficient for lookup.

### Runbook drill: Kafka whale

- Replay a celebrity seller workload into shared checkout.events.
- Expected behavior: producer quota, composite key, or dedicated topic prevents broker-wide saturation.
- Telemetry: per-partition bytes, broker network, tenant byte budget, and consumer lag by partition.
- Fail condition: topic average lag looks fine while one partition is 21M behind.

### Runbook drill: support export

- Attempt support export with order_id and no tenant context.
- Expected behavior: request is denied, audited, and visible to security dashboards.
- Telemetry: requester, approver, tenant, object id, row count, trace id, and policy decision.
- Fail condition: debug endpoint bypasses object authorization during incident.

### Tenant migration safety

- Route maps are versioned and cached with bounded TTL.
- Dual-write or change-data-copy is idempotent and has source authoritative until verification passes.
- Verification includes counts, checksums, sampled reads, lag, and capacity of destination cell.
- Rollback is route-map only until source decommission is explicitly approved.

### Isolation model tradeoffs

- Shared table is cheapest for long tail but needs perfect tenant predicates everywhere.
- Schema or DB per tenant improves blast radius but increases migrations and operations.
- Cell-based tenancy balances long-tail efficiency with enterprise isolation.
- Dedicated resources should be paid for by enterprise tiers or risk requirements.

### Security overlap

- Noisy neighbor and data isolation often appear together because emergency tools bypass normal paths.
- Security lead runs a parallel evidence track while performance mitigations continue.
- Do not wait for legal review before stopping a suspected leaking endpoint.
- Do not destroy evidence while flushing or invalidating caches.

### Post-incident artifacts

- Publish per-resource isolation gaps: DB, Redis, Kafka, search, support tools, observability.
- Add top-N tenant dashboards and bounded-cardinality SLO slices.
- Create game days for whale import, hot cache key, hot Kafka partition, and debug endpoint denial.
- Tie every action to an owner and an acceptance test.

### Final acceptance note

- The tenant is safe to unthrottle only after checkout SLOs, isolation tests, and security evidence review all pass.
