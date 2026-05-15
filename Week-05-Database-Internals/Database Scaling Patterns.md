# Week 5, Topic 2: Database Scaling Patterns

Last verified: 2026-05-15

Database scaling is not one technique. It is the discipline of matching a
specific bottleneck to the smallest safe architectural change.

The dangerous sentence is:

```text
The database is slow, so let us scale it.
```

The useful sentence is:

```text
The database is slow because active queries hold connections 40x longer after a
missing-index deploy, causing PgBouncer queue growth and replica lag.
```

The first sentence produces random infrastructure. The second produces a plan.

---

## 1. Learning objectives

After this topic, you should be able to:

```text
1. Identify whether a database bottleneck is CPU, memory, disk, WAL, lock,
   connection, query-plan, replication, or partition skew related.
2. Explain why read replicas do not scale writes.
3. Explain why connection pools protect databases but do not create capacity.
4. Use indexes, query plans, cache, replicas, partitioning, sharding, and CQRS
   only when they match the bottleneck.
5. Diagnose replica lag, cache stampedes, hot shards, bad plans, and failover
   connection storms.
6. Build safe mitigation plans that check downstream capacity before moving
   traffic.
7. Explain the operational risk of heavy data movement during an active incident.
```

---

## 2. The wrong mental models

### Wrong model 1: add read replicas

Read replicas help with some reads. They do not reduce primary writes, WAL
creation, lock contention, or fsync pressure.

```text
Writes:

+---------+       +---------+
| Clients | ----> | Primary |
+---------+       +---------+
                      |
                      | WAL stream
                      v
                 +---------+
                 | Replica |
                 +---------+

All writes still enter through the primary.
```

If the primary is write-bound, adding read replicas may change nothing or make
replication pressure worse.

### Wrong model 2: cache removes database load

A cache removes load only when hit ratio, key distribution, TTL policy, and
invalidation are healthy.

```text
Healthy cache:

Client -> App -> Cache hit -> Response

Stampede:

Client -> App -> Cache miss -> Database
Client -> App -> Cache miss -> Database
Client -> App -> Cache miss -> Database
```

A cache can protect the database. It can also become a scheduled database attack
if many hot keys expire together.

### Wrong model 3: sharding solves everything

Sharding helps only when the workload can be routed by shard key.

```text
Good query:

WHERE customer_id = 42
        |
        v
+----------------+
| Shard for 42   |
+----------------+

Bad query:

WHERE status = 'pending'
        |
        v
+---------+ +---------+ +---------+ +---------+
| Shard 1 | | Shard 2 | | Shard 3 | | Shard 4 |
+---------+ +---------+ +---------+ +---------+
```

The second query is scatter-gather. More shards can make it slower.

### Wrong model 4: bigger instance fixes bad queries

Vertical scaling buys time. It does not change an O(N) query into an O(log N)
query.

```text
Bad query:
  scan 800 million rows

Bigger instance:
  scans faster

Correct index:
  reads the 20 rows needed
```

---

## 3. Bottleneck taxonomy

Start by naming the bottleneck.

```text
+-----------------------+---------------------------------------+
| Bottleneck            | First useful direction                |
+-----------------------+---------------------------------------+
| Bad query plan        | EXPLAIN, ANALYZE, indexes, rewrite    |
| CPU saturation        | query reduction, indexes, scale up    |
| Memory pressure       | working-set reduction, more RAM       |
| Disk I/O              | indexes, storage, partitioning        |
| WAL/fsync pressure    | batch writes, fewer indexes, shard    |
| Lock contention       | shorter transactions, row redesign    |
| Connection exhaustion | PgBouncer, pool sizing, timeouts      |
| Replica lag           | reduce replay load, lag-aware routing |
| Hot tenant/key        | isolation, bucketing, rate limiting   |
| Large table           | partition, archive, lifecycle policy  |
| Complex reads         | CQRS, materialized views, search      |
| Global latency        | regional reads, multi-region design   |
+-----------------------+---------------------------------------+
```

Same symptom, different causes:

```text
Symptom: checkout p95 jumps from 300ms to 4s

Possible causes:
  - missing index
  - lock wait on inventory row
  - PgBouncer queue
  - cache stampede
  - replica lag and retries
  - checkpoint or disk saturation
  - query plan regression
  - hot tenant or bot traffic
```

Scaling begins after measurement, not before.

---

## 4. Vertical scaling

Vertical scaling means giving one database node more CPU, memory, disk, or
network.

```text
Before:

+------------------+
| PostgreSQL       |
| 16 vCPU          |
| 64 GB RAM        |
| 8K IOPS          |
+------------------+

After:

+------------------+
| PostgreSQL       |
| 64 vCPU          |
| 256 GB RAM       |
| 64K IOPS         |
+------------------+
```

It helps when the bottleneck is local resource capacity.

It does not fix:

```text
- wrong index
- bad join order
- hot row
- unbounded sort
- bad API fanout
- cross-region latency
- too many writes for one primary
```

Working-set example:

```text
Hot data:       120 GB
Hot indexes:     80 GB
Hot set total:  200 GB
RAM:            256 GB

Likely outcome:
  hot reads mostly stay in memory
```

Six months later:

```text
Hot set total:  500 GB
RAM:            256 GB

Likely outcome:
  cache hit ratio falls
  random disk reads rise
  p99 latency grows
```

Useful checks:

```sql
SELECT
  datname,
  blks_hit,
  blks_read,
  round(100.0 * blks_hit / nullif(blks_hit + blks_read, 0), 2) AS cache_hit_pct
FROM pg_stat_database;
```

```bash
iostat -xz 1
vmstat 1
free -m
```

---

## 5. Indexing and query optimization

The cheapest scaling pattern is often a correct index.

Query:

```sql
SELECT id, status, total_cents, created_at
FROM orders
WHERE customer_id = 123
ORDER BY created_at DESC
LIMIT 20;
```

Bad plan shape:

```text
Seq Scan on orders
  Rows Removed by Filter: 799999980
  Buffers: shared read=1300000
  Execution Time: 12400 ms
```

Useful index:

```sql
CREATE INDEX CONCURRENTLY idx_orders_customer_created
ON orders (customer_id, created_at DESC)
INCLUDE (status, total_cents);
```

Good plan shape:

```text
Index Scan using idx_orders_customer_created
  Index Cond: customer_id = 123
  Buffers: shared hit=45
  Execution Time: 6 ms
```

Composite index rule:

```text
Index: (customer_id, status, created_at)

Good:
  WHERE customer_id = ?
  WHERE customer_id = ? AND status = ?

Bad:
  WHERE status = ?
  WHERE created_at > ?
```

The index is sorted from left to right. The leftmost column matters.

Indexes are not free:

```text
More indexes:
  + faster matching reads
  - slower writes
  - more WAL
  - more bloat
  - more vacuum work
  - more storage
```

Use:

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT ...;
```

Plain `EXPLAIN` shows estimates. `EXPLAIN ANALYZE` runs the query and shows what
actually happened.

---

## 6. Connection pooling

PostgreSQL uses one backend process per connection. Thousands of connections are
not thousands of useful workers.

```text
Without pooling:

500 app pods * 20 connections = 10,000 database connections
```

That is memory pressure, context switching, and lock contention.

PgBouncer shape:

```text
+----------+      +-----------+      +-------------+
| App pods | ---> | PgBouncer | ---> | PostgreSQL  |
+----------+      +-----------+      +-------------+
  many conns        100 conns          real workers
```

Pool modes:

```text
session:
  server connection held for the client session

transaction:
  server connection held for one transaction

statement:
  server connection held for one statement
```

Transaction pooling is common for stateless web workloads, but it breaks code
that assumes session-local state.

Capacity math:

```text
Pool size:            100 server connections
Normal query time:    50 ms
Approx throughput:    100 / 0.05 = 2,000 qps

Incident query time:  2 seconds
Approx throughput:    100 / 2 = 50 qps
```

When queries slow down, connections stay checked out longer. The pool fills even
if traffic does not increase.

Useful commands:

```sql
SHOW POOLS;
SHOW CLIENTS;
SHOW SERVERS;
SHOW STATS;
```

Bad signs:

```text
cl_waiting rising
sv_active maxed
pool wait time rising
```

Dangerous move:

```text
Increasing app pool size during database saturation.
```

Usually that adds pressure to the bottleneck.

---

## 7. Read replicas

A read replica copies changes from the primary and serves read traffic.

```text
                 writes
+---------+   +---------+
| Clients |-> | Primary |
+---------+   +---------+
                  |
                  | replication stream
                  v
             +---------+
             | Replica |
             +---------+
                  |
                  v
                reads
```

Replicas help with:

```text
- read-heavy workloads
- reporting isolation
- backup offload
- failover targets
- regional read latency
```

Replicas do not help with:

```text
- primary write throughput
- primary lock contention
- primary WAL generation
- stale-read-sensitive workflows
```

Replica lag math:

```text
Primary WAL generation: 40 MB/s
Replica replay:         25 MB/s
Lag growth:             15 MB/s

After 10 minutes:
  15 MB/s * 600 = 9,000 MB behind
```

PostgreSQL check:

```sql
SELECT
  application_name,
  state,
  pg_wal_lsn_diff(sent_lsn, replay_lsn) AS replay_lag_bytes,
  write_lag,
  flush_lag,
  replay_lag
FROM pg_stat_replication;
```

Read-after-write issue:

```text
T0: user updates email on primary
T1: user refreshes profile
T2: profile reads from replica
T3: replica is 3 seconds behind
T4: user sees old email
```

Fixes:

```text
- route user to primary briefly after writes
- use causal LSN tokens
- use lag-bounded read routing
- keep stale replicas out of correctness-sensitive paths
```

---

## 8. Caching

Cache-aside pattern:

```text
+--------+      +-------+      +----------+
| Client | ---> | Cache | ---> | Database |
+--------+      +-------+      +----------+
                  hit            miss only
```

Flow:

```text
1. App checks cache.
2. If hit, return value.
3. If miss, read database.
4. Store result with TTL.
5. Return value.
```

Caching helps when:

```text
- reads repeat
- stale data is acceptable
- hit ratio is high
- key distribution is not too skewed
```

Caching hurts when:

```text
- hot keys overload one cache node
- TTLs expire together
- invalidation races create stale data
- cache failure sends all traffic to the database
```

Stampede math:

```text
Hot endpoint traffic: 50,000 req/s
Database capacity:     1,000 req/s
Cache hit ratio:       99%
Normal DB load:          500 req/s

At synchronized expiry:
  50,000 req/s can hit DB
  overload = 50x
```

Mitigations:

```text
- TTL jitter
- request coalescing
- stale-while-revalidate
- background refresh
- local cache for hottest keys
- rate limits
```

Redis checks:

```bash
redis-cli INFO stats
redis-cli SLOWLOG GET 20
redis-cli --hotkeys
redis-cli MEMORY STATS
```

Avoid `MONITOR` on busy Redis unless the risk is understood. It can add load and
expose sensitive data.

---

## 9. Partitioning

Partitioning splits a large table into smaller physical pieces.

```text
orders
  |
  +-- orders_2026_01
  +-- orders_2026_02
  +-- orders_2026_03
  +-- orders_2026_04
```

Time partitioning helps with:

```text
- log tables
- event tables
- metrics
- audit trails
- archival and retention
```

Query with pruning:

```sql
SELECT count(*)
FROM events
WHERE created_at >= '2026-05-01'
  AND created_at <  '2026-06-01';
```

If the table is partitioned by month, the planner can scan only the May
partition.

Partitioning does not automatically add machine capacity if all partitions live
on the same database host.

---

## 10. Sharding

Sharding splits data across database nodes.

```text
+---------+     +---------+     +---------+
| Shard 0 |     | Shard 1 |     | Shard 2 |
| A-H     |     | I-Q     |     | R-Z     |
+---------+     +---------+     +---------+
```

Application-level routing:

```python
shard_id = hash(customer_id) % shard_count
connection = shard_map[shard_id]
```

Sharding helps when:

```text
- one primary cannot handle write throughput
- data size exceeds one node's practical limit
- access patterns route cleanly by key
```

Sharding hurts when:

```text
- queries need all shards
- joins cross shards
- transactions cross shards
- shard key changes later
- one tenant dominates traffic
```

Scatter-gather shape:

```text
              global query
                  |
        +---------+---------+
        |         |         |
        v         v         v
    +-------+ +-------+ +-------+
    |Shard A| |Shard B| |Shard C|
    +-------+ +-------+ +-------+
        |         |         |
        +---------+---------+
                  |
                  v
              merge results
```

User latency becomes tied to the slowest shard plus merge time.

Hot tenant example:

```text
16 shards
expected average: 10K qps/shard
Tenant A:         70K qps
Shard 9 total:    80K qps
```

Hashing distributes keys, not load. A single huge tenant can still melt one
shard.

---

## 11. CQRS and read models

CQRS separates the write model from read models optimized for query patterns.

```text
Write path:

+-----+      +----------+
| API | ---> | OrdersDB |
+-----+      +----------+
                 |
                 | CDC or outbox
                 v
              +-------+
              | Kafka |
              +-------+
                 |
        +--------+--------+
        |                 |
        v                 v
+--------------+   +--------------+
| Search index |   | Analytics DB |
+--------------+   +--------------+
```

CQRS helps with:

```text
- expensive joins
- search
- dashboards
- high read fanout
- different read/write data shapes
```

It introduces:

```text
- eventual consistency
- replay requirements
- schema versioning
- duplicate event handling
- reconciliation
```

Dual-write trap:

```python
db.insert(order)
kafka.publish(OrderCreated)
```

If the database write succeeds and the publish fails, the order exists without an
event. If the publish succeeds and the transaction rolls back, the event lies.

Safer pattern:

```text
1. Write business row and outbox row in one DB transaction.
2. CDC reads outbox row.
3. Publisher emits event.
4. Consumers are idempotent.
```

---

## 12. Multi-region scaling

Multi-region design is a consistency and latency tradeoff, not a free speed
button.

Leader-follower:

```text
+-----------+        async replication        +-----------+
| US leader | ------------------------------> | EU replica|
+-----------+                                 +-----------+
     ^                                             |
     | writes                                      | local reads
     |                                             v
  clients                                      EU clients
```

Pros:

```text
- one write authority
- simpler conflict model
- local reads may be faster
```

Cons:

```text
- remote writes pay latency
- local reads can be stale
- failover must handle data loss windows
```

Multi-leader:

```text
+-----------+ <----------------------------> +-----------+
| US leader |                                | EU leader |
+-----------+                                +-----------+
```

Pros:

```text
- local writes
- regional autonomy
```

Cons:

```text
- conflicts
- clock skew
- merge logic
- split-brain risk
```

PACELC reminder:

```text
If partitioned: choose availability or consistency.
Else:           choose latency or consistency.
```

---

## 13. Production failure patterns

### Failure 1: replica lag creates stale reads

Symptoms:

```text
- user writes data and sees old data
- support tickets say changes reverted
- replica lag grows
- business dashboards disagree with primary
```

Detect:

```sql
SELECT
  application_name,
  pg_wal_lsn_diff(sent_lsn, replay_lsn) AS lag_bytes,
  replay_lag
FROM pg_stat_replication;
```

Mitigate:

```text
1. Remove lagging replica from critical read pool.
2. Route read-after-write flows to primary.
3. Reduce heavy queries on replicas.
4. Communicate stale-read impact clearly.
```

Long-term:

```text
- lag-aware routing
- causal read tokens
- separate analytics replicas
- alerts on business lag age
```

### Failure 2: connection pool saturation

Symptoms:

```text
- PgBouncer cl_waiting rises
- app timeouts rise
- database CPU may be moderate
- active queries hold connections longer
```

Detect:

```sql
SELECT pid, state, wait_event_type, wait_event,
       now() - query_start AS age, query
FROM pg_stat_activity
WHERE state <> 'idle'
ORDER BY age DESC
LIMIT 20;
```

```sql
SHOW POOLS;
```

Mitigate:

```text
1. Preserve admin access.
2. Cancel non-critical long-running queries.
3. Reduce app concurrency if DB is saturated.
4. Shed non-critical traffic.
5. Increase pool only if the DB has headroom.
```

### Failure 3: cache stampede

Symptoms:

```text
- cache hit ratio drops sharply
- database QPS jumps
- same query dominates pg_stat_statements
- Redis hot keys or evictions increase
```

Mitigate:

```text
- serve stale values
- add request coalescing
- extend TTL with jitter
- rate limit regeneration
- disable non-critical pages
```

### Failure 4: hot shard or hot tenant

Symptoms:

```text
- one shard has much higher CPU/QPS
- one tenant dominates traffic
- other shards are mostly idle
- scatter-gather p99 rises
```

Mitigate:

```text
- rate limit hot tenant if allowed
- move tenant only if isolation tooling exists
- disable expensive tenant features
- avoid emergency rebalancing without I/O headroom
```

### Failure 5: failover connection storm

Symptoms:

```text
- primary promoted
- thousands of clients reconnect
- new primary overloaded before useful work resumes
- stale clients keep hitting old endpoint
```

Mitigate:

```text
1. Confirm single writable primary.
2. Fence old primary.
3. Restart clients in waves.
4. Preserve admin connections.
5. Check data loss window before declaring recovery.
```

---

## 14. SRE diagnostic toolkit

PostgreSQL activity:

```sql
SELECT pid, usename, application_name, client_addr,
       state, wait_event_type, wait_event,
       now() - query_start AS query_age,
       query
FROM pg_stat_activity
ORDER BY query_age DESC
LIMIT 20;
```

Top query cost:

```sql
SELECT query, calls, total_exec_time, mean_exec_time,
       rows, shared_blks_hit, shared_blks_read
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT 20;
```

Locks:

```sql
SELECT locktype, relation::regclass, mode, granted, pid
FROM pg_locks
ORDER BY granted, relation;
```

Vacuum/analyze health:

```sql
SELECT relname, n_live_tup, n_dead_tup,
       last_vacuum, last_autovacuum,
       last_analyze, last_autoanalyze
FROM pg_stat_user_tables
ORDER BY n_dead_tup DESC
LIMIT 20;
```

Replication:

```sql
SELECT application_name, state, replay_lag,
       pg_wal_lsn_diff(sent_lsn, replay_lsn) AS lag_bytes
FROM pg_stat_replication;
```

Linux:

```bash
iostat -xz 1
vmstat 1
ss -s
```

PgBouncer:

```sql
SHOW POOLS;
SHOW CLIENTS;
SHOW SERVERS;
SHOW STATS;
```

Redis:

```bash
redis-cli INFO
redis-cli SLOWLOG GET 20
redis-cli --hotkeys
```

Kafka consumer lag for read models:

```bash
kafka-consumer-groups --bootstrap-server broker:9092 \
  --describe --group search-indexer
```

OpenSearch:

```bash
curl -s localhost:9200/_cluster/health?pretty
curl -s localhost:9200/_cat/shards?v
curl -s localhost:9200/_cat/thread_pool?v
```

---

## 15. Decision framework

```text
+-----------------------+--------------------------+-----------------------+
| Situation             | Try first                | Prove with            |
+-----------------------+--------------------------+-----------------------+
| Bad query             | index or rewrite         | EXPLAIN ANALYZE       |
| Too many connections  | PgBouncer, timeouts      | SHOW POOLS            |
| Read-heavy workload   | replica or cache         | QPS, lag, hit ratio   |
| Write-heavy primary   | batching or sharding     | WAL, fsync, locks     |
| Large historical data | partition or archive     | table/index size      |
| Hot tenant            | isolate or bucket        | per-tenant metrics    |
| Complex reads         | CQRS/read model          | query cost, fanout    |
| Global latency        | regional topology        | RTT, consistency need |
| Replica lag           | lag-aware routing        | LSN lag, replay lag   |
+-----------------------+--------------------------+-----------------------+
```

Rule:

```text
Never redirect load to another system until that system has enough capacity and
correctness for the new traffic.
```

---

## 16. Incident scenario: flash-sale database meltdown

Architecture:

```text
+---------+      +-------------+      +-----------+      +------------+
| Clients | ---> | App pods    | ---> | PgBouncer | ---> | PostgreSQL |
+---------+      +-------------+      +-----------+      +------------+
                                           |                   |
                                           |                   v
                                           |              +----------+
                                           |              | Replicas |
                                           |              +----------+
                                           |
                                           v
                                      +---------+
                                      | Redis   |
                                      +---------+

CDC path:

+------------+      +---------+      +-------------+
| PostgreSQL | ---> | Kafka   | ---> | OpenSearch  |
+------------+      +---------+      +-------------+
```

Baseline:

```text
PostgreSQL CPU:         45%
checkout p95:           80 ms
PgBouncer waiting:      0
replica lag:            < 200 ms
Redis hit ratio:        96%
OpenSearch p95:         120 ms
```

Incident:

```text
Traffic:                10x normal
PostgreSQL CPU:         96%
I/O wait:               28%
checkout p95:           9.2 s
PgBouncer waiting:      3,800
Replica 1 lag:          14 s
Replica 2 lag:          95 s
Redis hit ratio:        62%
Hot Redis key:          180K req/s
OpenSearch p95:         2.8 s
Kafka indexing lag:     4.8M messages
```

Recent changes:

```text
1. Product launch moved earlier without readiness review.
2. New "people also bought" widget added.
3. Widget query filters by sku and status, orders by created_at.
4. No composite index exists on (sku, status, created_at).
5. Product page cache TTL is exactly 300 seconds.
6. App DB pool size doubled.
```

Root cause chain:

```text
Launch traffic
  -> synchronized cache expiry
  -> DB receives miss storm
  -> new missing-index query runs slowly
  -> DB connections are held longer
  -> PgBouncer queue grows
  -> users retry
  -> WAL and CPU rise
  -> replicas lag
  -> read models become stale
```

Immediate mitigation order:

```text
1. Declare P1 and freeze deploys.
2. Disable the new widget.
3. Serve stale or degraded product page.
4. Add request coalescing for hot product key.
5. Cancel non-critical long-running queries.
6. Reduce app DB concurrency if the database is saturated.
7. Keep correctness-sensitive reads away from lagging replicas.
8. Reconcile payment authorizations against authoritative orders.
9. Create the missing index only after checking I/O headroom.
```

Dangerous moves:

```text
- fail over to a lagging replica
- flush Redis
- increase app pool size
- rebuild OpenSearch at full speed
- rebalance shards during I/O saturation
- run VACUUM FULL during peak
```

Long-term fixes:

```text
- query review for launch features
- composite index for the widget access pattern
- cache TTL jitter and stale-while-revalidate
- hot-key protection
- separate pools for critical and non-critical workloads
- lag-aware read routing
- launch readiness checklist
- reconciliation dashboard for payment/order mismatch
```

---

## 17. Key takeaways

```text
1. Scaling is matching a measured bottleneck to a specific pattern.
2. Read replicas scale reads, not primary writes.
3. Connection pools protect databases by limiting concurrency.
4. Indexes are often the cheapest scaling tool, but they slow writes.
5. Caches need jitter, coalescing, and invalidation discipline.
6. Sharding buys horizontal capacity but creates routing and query complexity.
7. CQRS improves reads by accepting async read-model maintenance.
8. Multi-region scaling is always a latency and consistency tradeoff.
9. During incidents, verify target-system capacity before redirecting traffic.
10. Heavy data movement during active saturation can turn a fire into a kiln.
```

---

## 18. Targeted reading

```text
Designing Data-Intensive Applications:
  Chapter 3: Storage and Retrieval
  Chapter 5: Replication
  Chapter 6: Partitioning

PostgreSQL documentation:
  EXPLAIN
  Runtime statistics views
  pg_stat_statements
  Autovacuum
  Declarative partitioning
  Streaming replication

PgBouncer documentation:
  Pool modes
  SHOW commands
  Transaction pooling limitations
```
