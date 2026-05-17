# Worked Answers — Sharding

This companion retrofit answers the principal-grade questions implied by the Sharding module. The goal is to turn sharding from “split data across nodes” into production-grade reasoning about routing, resharding, transactions, hot keys, and operational blast radius.

---

## Answer 1 — When sharding is actually justified

### Scenario

```text
A single PostgreSQL orders table is 20 TB.
Writes are 35k/sec at peak.
Top queries:
  - lookup order by order_id
  - list orders by customer_id
  - find recent orders by merchant_id
  - support queries by email/date/status

The team says: “We need to shard.”
```

### Principal answer

Do not start with sharding. Start by identifying which limit is actually being hit.

```text
Possible limits:
  - storage size
  - write throughput
  - read throughput
  - index size and cache miss rate
  - vacuum/compaction/maintenance window
  - backup/restore time
  - single-table lock/migration risk
  - noisy tenant/customer/merchant hotspot
```

Sharding is justified only if simpler patterns cannot satisfy the bottleneck:

```text
Read bottleneck:
  try read replicas, caching, materialized views, search index, CQRS read model

Write bottleneck:
  sharding may be needed, but first examine batching, indexes, partitioning, write amplification

Table maintenance bottleneck:
  native partitioning may help before full application-level sharding

Support-query bottleneck:
  sharding may make it worse unless a global search/index strategy exists
```

For the given query set, no single shard key satisfies all access patterns:

```text
order_id lookup wants order_id hash
customer order list wants customer_id
merchant recent orders wants merchant_id/time
support queries want secondary/global index
```

A principal design might use:

```text
source-of-truth shard key: customer_id or merchant_id depending dominant write/query path
secondary index/read model: order_id → shard mapping
search/support index: Elasticsearch/OpenSearch or warehouse-backed support tooling
native time partitioning inside each shard for maintenance
```

The key sentence:

```text
Sharding solves one primary access path and creates problems for every access path not aligned with the shard key.
```

---

## Answer 2 — Choosing a shard key

### Scenario

```text
You must shard an orders system.
Candidate shard keys:
  - order_id
  - customer_id
  - merchant_id
  - region
  - created_at
```

### Principal answer

Choose the shard key based on the access pattern that must be local, hot-spot behavior, transaction boundaries, and blast radius.

```text
order_id:
  Pros: evenly distributed if random/hashed; direct lookup easy
  Cons: customer order list becomes scatter-gather unless indexed elsewhere
  Good for: systems dominated by direct order lookup

customer_id:
  Pros: all customer orders local; customer workflows simpler
  Cons: whale customers create hot shards; merchant queries scatter
  Good for: consumer-centric systems

merchant_id:
  Pros: merchant dashboards and fulfillment local
  Cons: large merchants can dominate one shard; customer views scatter
  Good for: marketplace operations where merchants are primary unit

region:
  Pros: locality, data residency, operational separation
  Cons: uneven load; cross-region customers/merchants complicated
  Good for: regulatory/geographic separation, not general load distribution

created_at:
  Pros: time-based retention and archival easy
  Cons: current-time shard is always hot; poor direct lookup without index
  Good for: append-only analytics/logs, not OLTP orders alone
```

A mature design often combines strategies:

```text
hash(customer_id) for write distribution
partition by time within each shard for maintenance
order_id lookup table for direct routing
merchant read model for dashboards
```

Principal caveat:

```text
The shard key is not just a storage decision; it is a product contract.
It decides which workflows are cheap, which are expensive, and which incidents are local or global.
```

---

## Answer 3 — Resharding without corrupting production

### Scenario

```text
You have 16 shards and need to move to 64.
Traffic cannot stop.
Orders and payments must remain correct.
```

### Principal answer

Resharding is a distributed migration. Treat it like a production incident waiting to hatch unless it has phases, verification, and rollback.

A safe sequence:

```text
1. Design new routing scheme
   old: hash(customer_id) % 16
   new: hash(customer_id) % 64

2. Add routing indirection
   directory service or lookup table maps shard key → physical shard
   avoid hardcoding modulo logic everywhere

3. Create new shards
   schema, indexes, permissions, monitoring, backups, connection pools

4. Dual-write or change-data-capture migration
   carefully define source of truth during transition

5. Backfill historical data
   chunked by shard key and time window
   rate-limited to avoid hurting production

6. Verify consistency
   row counts, checksums, business aggregates, spot checks, lag metrics

7. Shadow reads
   compare old-route and new-route responses without serving users from new path

8. Gradual read cutover
   tenant/customer/percentage based

9. Gradual write cutover
   only after reads and reconciliation are clean

10. Freeze old writes, final delta sync, retire old route
```

Danger zones:

```text
dual-write partial failure
out-of-order CDC
backfill racing with live writes
connection pool explosion across more shards
global transactions spanning old and new routes
support tools reading only old shards
hidden batch jobs using hardcoded shard mapping
```

Principal answer on rollback:

```text
Rollback must be designed before cutover. If new writes have occurred only on new shards, rollback requires reverse replication or a strict dual-write source of truth. If neither exists, rollback is a myth.
```

---

## Answer 4 — Cross-shard transactions

### Scenario

```text
An order workflow updates:
  - customer balance on shard A
  - inventory reservation on shard B
  - order row on shard C

The team proposes a distributed transaction.
```

### Principal answer

Cross-shard transactions are expensive because they require coordination across independent failure domains. Two-phase commit can provide atomicity but creates blocking, coordinator-failure, and operational complexity.

Better question:

```text
Can the business workflow be redesigned so the transaction boundary is local?
```

Patterns:

```text
Single aggregate ownership:
  choose shard key so the most important transaction is local

Saga:
  split workflow into steps with compensating actions

Reservation model:
  inventory reservation is temporary and expires if order fails

Ledger/outbox:
  durable local write emits event; downstream converges with idempotent consumers

Escrow/allocations:
  pre-allocate inventory or quota per shard to avoid global coordination per request
```

For payments/orders:

```text
Never make “charged customer” depend on an eventually consistent write without idempotency and reconciliation.
```

A principal answer refuses generic distributed transactions unless the invariant truly requires it and the operational cost is accepted.

Decision rule:

```text
Use cross-shard transactions only for rare, high-value operations where correctness requires atomicity and throughput is low enough to tolerate coordination.
For high-volume OLTP, redesign around local transactions + sagas + reconciliation.
```

---

## Answer 5 — Hot shards and noisy tenants

### Scenario

```text
The system is hash-sharded by merchant_id.
One large merchant runs a flash sale.
Shard 7 hits 95% CPU and 99th percentile latency explodes.
Other shards are healthy.
```

### Principal answer

This is a hot-shard/noisy-tenant problem. Average cluster utilization is irrelevant because the user-visible path is bottlenecked by one shard.

Signals:

```text
per-shard CPU, IOPS, connection count, lock waits
per-shard p95/p99 latency
per-tenant QPS and write volume
queue depth by shard
connection pool saturation by shard
Kafka/topic lag by shard key if event-driven
```

Immediate mitigations:

```text
rate-limit or shape the hot tenant
move read traffic to tenant-specific read model/cache
disable expensive noncritical queries for that tenant
scale vertically if available and safe
split the tenant across sub-shards if architecture supports it
protect other tenants by isolating the hot shard from shared workers/pools
```

Long-term fixes:

```text
tenant-aware routing
large-tenant dedicated shards
composite shard key: merchant_id + bucket
adaptive shard splitting
per-tenant quotas
separate OLTP write path from analytics/dashboard path
```

Tradeoff of composite key:

```text
merchant_id + bucket spreads load, but operations requiring full merchant ordering or aggregation now need fan-in across buckets.
```

Principal line:

```text
A hot shard is not a capacity problem; it is a distribution problem.
Adding more total shards does not help unless the hot key can actually move or split.
```

---

## Final rubric

```text
Passing answer:
  - defines sharding and shard keys
  - recognizes scatter-gather and resharding risk
  - mentions hot shards

Principal answer:
  - starts from bottleneck diagnosis
  - ties shard key to transaction boundaries and product workflows
  - designs routing indirection before resharding
  - plans verification and rollback
  - handles cross-shard correctness explicitly
  - separates capacity from distribution problems
```
