# Worked Answers — Database Scaling Patterns

This companion retrofit answers the principal-grade questions implied by the Database Scaling Patterns module. The goal is to distinguish which scaling pattern solves which bottleneck, which patterns merely move complexity, and which mitigations are unsafe during incidents.

---

## Answer 1 — Read scale vs write scale vs correctness

### Scenario

```text
A checkout database is overloaded.
Symptoms:
  - p99 checkout latency high
  - primary CPU 85%
  - read replicas at 20% CPU
  - primary write IOPS high
  - connection count near max
  - product asks to “add more replicas”
```

### Principal answer

Read replicas help only if the bottleneck is read traffic that can safely tolerate replica lag. They do not reduce primary write pressure, write locks, WAL generation, primary index maintenance, or primary transaction contention.

First classify the bottleneck:

```text
Read bottleneck:
  high SELECT load on primary
  replicas underused
  queries can tolerate staleness
  Action: route safe reads to replicas, cache, materialized views

Write bottleneck:
  high INSERT/UPDATE/DELETE volume
  WAL/IOPS high
  locks/contention high
  Action: reduce write amplification, batch, partition, shard, queue, redesign writes

Connection bottleneck:
  too many app connections
  DB CPU may or may not be high
  Action: pool tuning, pgbouncer/RDS Proxy, reduce pod-pool multiplication

Correctness bottleneck:
  retries, duplicate writes, long transactions, lock waits
  Action: idempotency, shorter transactions, outbox, safe retry design
```

Adding replicas to a write-bound primary is decorative plumbing. It may help dashboards but not checkout.

Principal line:

```text
Scaling reads, scaling writes, and preserving correctness are three different problems.
```

---

## Answer 2 — Choosing between cache, replica, materialized view, and CQRS

### Scenario

```text
An orders page is slow.
It shows customer orders, latest status, payment status, shipment status, and support flags.
The team proposes Redis caching.
```

### Principal answer

Redis may help, but first decide what freshness and correctness the page needs.

```text
Read replica:
  Good when SQL query is acceptable and slight lag is acceptable
  Risk: user may not see own recent order update

Cache-aside Redis:
  Good for repeated reads with clear invalidation or TTL
  Risk: stale order/payment status if invalidation misses

Materialized view:
  Good for precomputed relational projections
  Risk: refresh lag, lock/maintenance behavior, limited flexibility

CQRS read model:
  Good when page aggregates many services and can be event-driven
  Risk: eventual consistency, replay/backfill complexity, event correctness
```

For an order page, split fields by consequence:

```text
Order list display:
  can tolerate short lag

Payment status:
  must be carefully labeled if pending/unknown
  should not be blindly cached as final

Shipment status:
  often eventually consistent

Support flags/fraud/manual hold:
  may need stronger freshness depending business risk
```

Principal answer:

```text
Do not cache a business lie.
Cache only data whose staleness window is explicit and acceptable.
```

---

## Answer 3 — Connection pool scaling failure

### Scenario

```text
Kubernetes deployment scales checkout-api from 20 pods to 80 pods.
Each pod has maxPoolSize=50.
PostgreSQL max_connections=2000.
After autoscaling, DB latency worsens and new connections fail.
```

### Principal answer

The theoretical application connection capacity changed from:

```text
20 pods × 50 = 1000 possible DB connections
80 pods × 50 = 4000 possible DB connections
```

That exceeds PostgreSQL max_connections and may overload the database even before hitting the hard limit. More app pods can increase throughput only if the downstream database has headroom. Otherwise they multiply pressure.

What can go wrong:

```text
DB connection exhaustion
memory overhead per backend
context switching
lock contention
I/O queueing
connection storms during deploy/failover
pool wait timeouts in application
```

Immediate actions:

```text
reduce maxPoolSize per pod
cap autoscaler replicas based on DB capacity
use PgBouncer/RDS Proxy where appropriate
separate read/write pools
shed noncritical traffic
avoid blindly increasing max_connections
```

Principal line:

```text
The application pool is not just an optimization; it is a concurrency governor protecting the database.
```

---

## Answer 4 — Partitioning vs sharding vs archival

### Scenario

```text
A table has 15 billion rows and grows by 200 million rows/day.
Most queries read the last 7 days.
Compliance requires 7 years retention.
The team proposes sharding by customer_id.
```

### Principal answer

This sounds like a time-retention and maintenance problem before it sounds like a customer sharding problem.

Useful pattern:

```text
native time partitioning:
  partition by day/week/month
  makes retention, vacuum, index maintenance, and archival manageable

hot/cold storage split:
  recent data in OLTP database
  older data in warehouse/object storage/search archive

customer_id sharding:
  helps if customer-specific write/read throughput is bottleneck
  does not by itself solve 7-year retention or time-window scans
```

Recommended approach:

```text
1. Partition by time for lifecycle management.
2. Keep last N days/months in fast OLTP path.
3. Archive older data to cheaper analytical storage.
4. Add customer or tenant sharding only if per-customer throughput/storage requires it.
5. Provide support/audit query path that can cross hot/cold stores intentionally.
```

Principal caveat:

```text
Do not shard when partitioning and archival solve the real problem with less operational blast radius.
```

---

## Answer 5 — CQRS and event-driven read models

### Scenario

```text
A product page reads from catalog, pricing, inventory, reviews, promotions, and recommendations.
p99 latency is high because the page fans out to many services.
The team proposes a CQRS read model.
```

### Principal answer

CQRS can improve read latency by precomputing a product-page projection, but it creates an event correctness problem.

Benefits:

```text
fast reads
fewer runtime dependencies
controlled query shape
better cacheability
isolates product-page read traffic from OLTP systems
```

New responsibilities:

```text
event contracts
outbox/CDC correctness
idempotent consumers
replay/backfill strategy
freshness SLO
staleness indicators
poison-message handling
schema evolution
read-model rebuild procedure
```

Failure modes:

```text
inventory stale → oversell risk
pricing stale → revenue/customer trust issue
promotion stale → wrong discount
reviews stale → lower consequence
recommendations stale → usually acceptable
```

Principal answer:

```text
CQRS moves latency out of the request path and into the data pipeline.
That is good only if the pipeline has observable freshness, replay safety, and business-aware staleness policy.
```

Design:

```text
source-of-truth services emit domain events via outbox
projection builder consumes events idempotently
projection store keyed by product_id
page reads projection in one call
critical fields include freshness timestamp and source version
fallback path exists for high-risk fields like price/inventory
```

---

## Answer 6 — Scaling during an incident

### Scenario

```text
An incident page says:
  - DB p99 latency high
  - app pods CPU high
  - DB connections 95%
  - lock_waits rising
  - Kafka lag rising

Someone says: “Scale the app and consumers.”
```

### Principal answer

Scaling is not automatically mitigation. It can be an amplifier.

If DB connections and lock waits are already high, scaling app pods or consumers may:

```text
open more DB connections
increase concurrent transactions
increase lock contention
increase retries
increase queue drain pressure into the DB
worsen p99 latency
```

First determine:

```text
Is app CPU high because it is doing useful work, spinning on retries, or waiting?
Is Kafka lag rising because consumers are slow, or because downstream DB writes are blocked?
Are lock waits caused by a single blocker, hot row, migration, or broad workload?
Is the DB CPU-bound, I/O-bound, lock-bound, or connection-bound?
```

Safe first actions:

```text
freeze deploys
reduce retry amplification
identify blocking transactions
pause or slow noncritical consumers
shed noncritical traffic
rollback recent DB/app change
protect payment/order correctness
```

Principal line:

```text
Scale only the layer that is the bottleneck, and only if its dependencies can absorb the extra work.
```

---

## Final rubric

```text
Passing answer:
  - knows replicas, cache, partitioning, sharding, CQRS
  - can say which patterns help reads vs writes
  - recognizes connection limits

Principal answer:
  - diagnoses the actual bottleneck first
  - rejects unsafe blanket scaling
  - separates performance from correctness
  - models stale-data consequences per field/workflow
  - treats CQRS as a pipeline with freshness SLOs
  - uses pools, queues, and autoscaling as pressure-control systems
```
