# Week 5, Topic 2: Database Scaling Patterns — Scaling the Bottleneck You Actually Have

## 0. Pre-flight Compliance Check

1. **Current roadmap status:**  
   Week 4 is complete. The handoff roadmap says Week 5 is Database Internals, with Cassandra Architecture followed by Database Scaling Patterns. Cassandra Architecture already exists in the repo and is written as a deep storage-engine topic, so the correct continuation is **Week 5, Topic 2: Database Scaling Patterns**.

2. **Exact topic I will generate:**  
   **Week 5, Topic 2: Database Scaling Patterns — Scaling the Bottleneck You Actually Have**

3. **Why this is the correct next topic:**  
   Cassandra Architecture teaches one database’s internals deeply: LSM-trees, commitlog, memtables, SSTables, bloom filters, read amplification, compaction, tombstones, and repair. The next step is broader: how to scale databases in production without applying the wrong pattern to the wrong bottleneck.

4. **Prior topics I will connect to:**  
   SQL Deep Dive, NoSQL Taxonomy, Caching Patterns, CAP/PACELC, Consistency Models, Consistent Hashing, Replication Strategies, Sharding/Partitioning, Consensus/Raft, Cassandra Architecture.

5. **Active learner gaps I will test:**  
   - Cross-system capacity verification: before moving load from PostgreSQL to Redis/OpenSearch/replicas, verify the target system can absorb it.
   - Organizational communication: include incident command, stakeholder updates, and flash-sale runbook gaps.
   - Defense layer ordering: label primary prevention, fallback, and last resort.
   - Operational prerequisites: verify admin access, reserved connections, safe command paths, stale client cleanup.
   - Metadata vs data operations during recovery: avoid heavy rebalancing, full reindexing, or data movement during active fire unless it is the least bad option.

6. **Reference style target:**  
   `REST vs GraphQL vs gRPC.md`: misconception correction, concrete examples, mechanics, strengths/problems, production failure patterns, exact SRE commands, decision framework, and hardcore incident scenario.

7. **Things I will NOT do:**  
   I will not skip to Kafka, event-driven architecture, microservices, rate limiting, load balancing, or system designs. I will not say “add replicas,” “add cache,” or “shard it” without proving the bottleneck.

8. **Self-critique bar before writing:**  
   A senior SRE should be able to use this module during an incident review. Every pattern must answer: what it solves, what it does not solve, when it makes things worse, what metrics prove it, and how to operate it safely.

---

## 1. Learning Objectives

```text
╔══════════════════════════════════════════════════════════════╗
║   AFTER THIS TOPIC, YOU WILL BE ABLE TO:                     ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║  1. Diagnose whether a database bottleneck is caused by      ║
║     CPU saturation, memory/cache misses, disk I/O, WAL/fsync,║
║     lock waits, connection exhaustion, replication lag,       ║
║     vacuum debt, hot partitions, or bad query plans.         ║
║                                                              ║
║  2. Explain why adding read replicas does NOT reduce write   ║
║     amplification, primary WAL generation, lock contention,  ║
║     or single-writer bottlenecks.                            ║
║                                                              ║
║  3. Calculate when read replicas fail because replica lag    ║
║     exceeds a product SLA or violates read-your-writes       ║
║     consistency.                                             ║
║                                                              ║
║  4. Size PgBouncer pools and explain why increasing          ║
║     max_connections can reduce throughput instead of         ║
║     increasing capacity.                                     ║
║                                                              ║
║  5. Use EXPLAIN ANALYZE BUFFERS to prove whether a query     ║
║     needs an index, a different index, a rewritten query,    ║
║     better statistics, partition pruning, or fewer rows.     ║
║                                                              ║
║  6. Distinguish partitioning from sharding, and explain      ║
║     hot partitions, scatter-gather reads, cross-shard joins, ║
║     global indexes, and rebalancing risk.                    ║
║                                                              ║
║  7. Decide when to use caching, read replicas, indexes,      ║
║     vertical scaling, partitioning, sharding, CQRS, CDC,     ║
║     or multi-region replication based on the actual          ║
║     bottleneck.                                              ║
║                                                              ║
║  8. Diagnose multi-system database incidents involving       ║
║     PostgreSQL, PgBouncer, Redis, Kafka/Debezium,            ║
║     OpenSearch, Kubernetes, and read replicas.               ║
║                                                              ║
║  9. Build mitigation plans that verify cross-system capacity ║
║     before redirecting traffic, failing over, warming cache, ║
║     or rebuilding read models.                               ║
║                                                              ║
║ 10. Explain to an interviewer or incident commander why      ║
║     “scale the database” is not a plan until the bottleneck  ║
║     has been named and measured.                             ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

---

## 2. What People Get Wrong

### WRONG MODEL 1: “Just add read replicas.”

**Why it is wrong:**  
Read replicas scale some reads. They do not scale writes. They do not reduce primary WAL generation. They do not fix bad queries. They do not eliminate lock contention on the primary. They add replication lag, failover complexity, read routing logic, more connection pools, and more systems to monitor.

```text
Primary workload:
  10K writes/sec
  20K reads/sec

Add 3 replicas:
  Reads can be split.
  Writes still all hit the primary.
  WAL still generated on the primary.
  Replication stream now has to feed 3 followers.
```

**Production consequence:**  
A team sees primary CPU at 95%, adds three replicas, moves dashboards to replicas, and discovers the primary is still dying because the bottleneck was write-heavy WAL/fsync pressure and lock contention, not read throughput.

---

### WRONG MODEL 2: “Sharding solves all scaling problems.”

**Why it is wrong:**  
Sharding only helps when the bottleneck can be divided by shard key. If your query needs all shards, you just created a distributed query engine with worse tail latency. If your shard key is wrong, one shard still melts.

```text
Good sharding query:
  WHERE customer_id = 123
  → route to shard 7

Bad sharding query:
  WHERE status = 'pending'
  → scatter to all shards
  → merge results
  → p99 = slowest shard
```

**Production consequence:**  
A company shards orders by `order_id`, but customer support queries by `customer_id`. Every support dashboard becomes scatter-gather across 128 shards. The p95 goes from 200ms to 8 seconds.

---

### WRONG MODEL 3: “Connection pooling increases database capacity.”

**Why it is wrong:**  
Pooling does not make PostgreSQL execute more queries at once. It limits concurrency to a sane level. It protects the database from thousands of idle clients and connection storms.

```text
No pool:
  500 pods × 20 DB connections = 10,000 backend connections

PostgreSQL optimal active queries on 32 cores:
  roughly 64-128 active queries, depending workload

10,000 connections ≠ 10,000 useful workers.
10,000 connections = memory pressure + context switching + lock contention.
```

**Production consequence:**  
A team increases app pool size from 10 to 100 during an incident. PostgreSQL gets more backends, more context switches, more memory pressure, and throughput drops.

---

### WRONG MODEL 4: “Caching removes database load.”

**Why it is wrong:**  
Caching removes load only when hit ratio is high, keys are not too hot, data can be stale, and cache invalidation is correct. A cache can amplify outages through stampedes, hot keys, eviction storms, stale data, and reconnect storms.

**Production consequence:**  
A Redis cache expires the `homepage:trending` key every 5 minutes. At expiry, 80,000 clients miss simultaneously, all hit PostgreSQL, and the cache becomes the trigger for a database outage.

---

### WRONG MODEL 5: “A bigger instance fixes bad queries.”

**Why it is wrong:**  
Vertical scaling buys headroom. It does not fix an O(N) query, missing index, wrong join order, bad statistics, unbounded sort, or N+1 application pattern.

```text
Bad query:
  SELECT * FROM events WHERE user_id = 123 ORDER BY created_at DESC LIMIT 20;

Table:
  2 billion rows

Missing index:
  (user_id, created_at DESC)

Bigger CPU helps a little.
The correct index changes the problem class.
```

**Production consequence:**  
The team upgrades from 16 cores to 64 cores and delays the incident by one month. Then data grows 4x and the same sequential scan returns as a larger dragon.

---

### WRONG MODEL 6: “Partitioning and replication are the same.”

**Why it is wrong:**  
Replication copies the same data to multiple nodes. Partitioning splits data into pieces. Replication gives availability/read scale. Partitioning gives data-size management and sometimes write/read locality.

```text
Replication:
  Node A: all users
  Node B: all users
  Node C: all users

Partitioning:
  Partition 1: users 0-999999
  Partition 2: users 1000000-1999999
  Partition 3: users 2000000-2999999
```

**Production consequence:**  
A team adds replicas expecting to solve a 9TB table maintenance problem. Vacuum, index bloat, and backup duration remain painful because every replica still has the same giant table.

---

### WRONG MODEL 7: “Eventual consistency is acceptable everywhere.”

**Why it is wrong:**  
Eventual consistency is a product decision, not a technical vibe. It is acceptable for recommendations, dashboards, search indexes, and notifications. It is not acceptable for payment authorization, inventory reservation, allergy checks, account balances, or fraud holds unless carefully bounded.

**Production consequence:**  
Checkout reads inventory from a replica lagging 12 seconds behind. Customers buy items already sold out. The database is “available,” but the business state is wrong.

---

### WRONG MODEL 8: “Autoscaling databases works like autoscaling stateless services.”

**Why it is wrong:**  
Stateless pods can be added quickly. Databases have data gravity. Adding a replica requires copying data, replaying WAL, warming cache, validating lag, opening connections, and updating routing.

**Production consequence:**  
Kubernetes scales app pods from 100 to 500 during flash sale. Each pod opens 20 DB connections. PostgreSQL sees 10,000 new connections before the database can scale. The autoscaler becomes an incident amplifier.

---

## 3. Core Teaching

## 3A. The Scaling Problem Taxonomy

Before scaling anything, name the bottleneck.

```text
╔══════════════════════════════════════════════════════════════╗
║                DATABASE BOTTLENECK TAXONOMY                 ║
╟───────────────────────┬──────────────────────────────────────╢
║ Bottleneck             │ Typical First-Class Fix              ║
╠═══════════════════════╪══════════════════════════════════════╣
║ CPU saturation         │ Query/index/schema optimization      ║
║ Memory/cache misses    │ Working-set reduction, more RAM      ║
║ Disk I/O saturation    │ Index/query changes, storage tuning  ║
║ WAL/fsync pressure     │ Batch writes, reduce indexes, shard  ║
║ Lock contention        │ Shorter transactions, row design     ║
║ Connection exhaustion  │ PgBouncer, pool sizing               ║
║ Hot row/tenant         │ Data model change, sharding, queues  ║
║ Bad query plans        │ ANALYZE, stats, indexes, rewrite     ║
║ Index bloat            │ VACUUM, REINDEX CONCURRENTLY         ║
║ Vacuum debt            │ Tune autovacuum, reduce long txns    ║
║ Replication lag        │ Reduce writes, fix replica load      ║
║ Network saturation     │ Payload reduction, colocate services ║
║ Read amplification     │ Indexes, compaction, denormalization ║
║ Write amplification    │ Fewer indexes, batching, LSM tuning  ║
║ Coordination overhead  │ Avoid distributed transactions       ║
║ Cross-shard queries    │ Query routing, read model, redesign  ║
╚═══════════════════════╧══════════════════════════════════════╝
```

The first rule:

```text
If you cannot name the bottleneck, you are not scaling.
You are gambling with infrastructure.
```

### Example: Same symptom, different causes

Symptom:

```text
Checkout p95 went from 300ms to 4s.
```

Possible causes:

```text
1. CPU saturation:
   Bad query doing sequential scan.

2. Lock contention:
   Everyone updating same inventory row.

3. Connection exhaustion:
   Requests waiting in PgBouncer queue.

4. Disk I/O:
   Checkpoint storm, WAL fsync slow.

5. Replica lag:
   App retries because stale reads confuse workflow.

6. Cache stampede:
   Redis miss storm pushes reads to primary.

7. Network:
   DB in another AZ/region or packet loss.

8. Query plan regression:
   Statistics drift after data distribution changed.
```

Same symptom. Eight different fixes.

---

## 3B. Vertical Scaling

Vertical scaling means making one database node bigger: more CPU, more RAM, faster disk, more network bandwidth.

```text
Before:
  PostgreSQL primary
  16 vCPU
  64 GB RAM
  8K IOPS
  p95 query latency: 180ms

After:
  PostgreSQL primary
  64 vCPU
  256 GB RAM
  64K IOPS
  p95 query latency: 60ms
```

### What it solves

Vertical scaling helps when the bottleneck is local resource capacity:

```text
CPU-bound queries
Working set larger than RAM
Disk I/O saturation
Checkpoint pressure
WAL fsync latency
Sort/hash operations spilling to disk
```

### What it does not solve

```text
Bad data model
Single hot row
Unbounded table growth
Cross-region latency
Read-after-write consistency needs
Lock contention from long transactions
Application N+1 queries
Wrong indexes
Shard key mistakes
```

### Working-set math

A database is fast when the hot working set fits in memory.

```text
Table size:             2 TB
Index size:             600 GB
Hot data in last 7 days: 120 GB
Hot indexes:             80 GB
Total hot working set:  200 GB

Instance RAM:           256 GB
shared_buffers:          64 GB
OS page cache available: ~160 GB

Result:
  Hot set roughly fits.
  Reads mostly hit memory.
```

Now data grows:

```text
Hot working set after 6 months: 500 GB
RAM still: 256 GB

Result:
  Cache hit ratio falls.
  Random reads hit disk.
  p99 latency explodes.
```

### Metrics to confirm

PostgreSQL:

```sql
SELECT
  datname,
  blks_hit,
  blks_read,
  round(100.0 * blks_hit / nullif(blks_hit + blks_read, 0), 2) AS cache_hit_pct
FROM pg_stat_database;
```

Good:

```text
cache_hit_pct > 99% for OLTP
```

Bad:

```text
cache_hit_pct < 95% with rising read latency
```

Linux:

```bash
iostat -xz 1
vmstat 1
free -m
```

Look for:

```text
%iowait high
await high
r/s high
major page faults
swap usage
```

### When vertical scaling lies

You upgrade hardware and the symptom improves. That does not prove you fixed the cause.

```text
Sequential scan:
  500M rows scanned
  Old instance: 8 seconds
  New instance: 3 seconds

This is faster.
It is still wrong.
```

Correct fix:

```sql
CREATE INDEX CONCURRENTLY idx_events_user_created
ON events (user_id, created_at DESC);
```

Then:

```text
Old query: scan 500M rows
New query: read 20 rows from index
Latency: 3s -> 8ms
```

### Production example

An orders table has 800M rows.

```sql
SELECT *
FROM orders
WHERE customer_id = 123
ORDER BY created_at DESC
LIMIT 20;
```

Without index:

```text
Seq Scan on orders
Rows removed by filter: 799,999,980
Execution time: 12,400ms
```

With index:

```sql
CREATE INDEX CONCURRENTLY idx_orders_customer_created
ON orders (customer_id, created_at DESC);
```

New plan:

```text
Index Scan using idx_orders_customer_created
Rows returned: 20
Execution time: 6ms
```

A bigger instance was not the scaling pattern. The index was.

---

## 3C. Read Replicas

Read replicas copy data from the primary and serve read queries.

```text
                 writes
Clients ───────────────► Primary
                           │
                           │ WAL stream
                           ▼
                      Read Replica 1
                           │
                           ▼
                      Read Replica 2
```

### What replicas solve

```text
Read throughput
Read isolation for analytics
Geographic read latency
High availability failover targets
Backup offloading
```

### What replicas do not solve

```text
Write throughput
Primary lock contention
Primary WAL generation
Primary fsync latency
Bad query shape
Stale-read-sensitive workflows
Single-writer bottleneck
```

### Physical vs logical replication

Physical replication:

```text
Primary WAL bytes -> replica replays same storage-level changes
```

Pros:

```text
Fast
Exact physical copy
Good for HA
```

Cons:

```text
Same major-version constraints depending database
Replica mostly read-only
Replicates everything
```

Logical replication:

```text
Primary changes decoded into row-level operations
INSERT/UPDATE/DELETE applied downstream
```

Pros:

```text
Selective tables
Cross-version migrations
Read-model pipelines
CDC foundation
```

Cons:

```text
More moving parts
Schema coordination
Replication slots can retain WAL
Higher decoding overhead
```

### Replica lag mechanics

Replica lag appears when the replica cannot receive, flush, or replay changes as fast as the primary produces them.

```text
Primary writes:
  40 MB/s WAL

Replica replay capacity:
  25 MB/s WAL

Lag growth:
  15 MB/s

After 10 minutes:
  15 MB/s × 600s = 9,000 MB = 9 GB WAL behind
```

If business reads from that replica:

```text
Orders page: stale by minutes
Inventory: wrong
Account balance: dangerous
Search index: maybe acceptable
Analytics dashboard: acceptable if labeled
```

### Commands

On primary:

```sql
SELECT
  application_name,
  client_addr,
  state,
  sent_lsn,
  write_lsn,
  flush_lsn,
  replay_lsn,
  pg_wal_lsn_diff(sent_lsn, replay_lsn) AS replay_lag_bytes,
  write_lag,
  flush_lag,
  replay_lag
FROM pg_stat_replication;
```

Good:

```text
state = streaming
replay_lag near 0
replay_lag_bytes small and stable
```

Bad:

```text
replay_lag increasing
replay_lag_bytes increasing
state = catchup or disconnected
```

On replica:

```sql
SELECT
  now() - pg_last_xact_replay_timestamp() AS replica_delay;
```

Mistaken interpretation:

```text
During low-write periods, this can look stale because no new transaction timestamp exists.
Use LSN lag too.
```

### Read-after-write inconsistency

Timeline:

```text
T0: User updates email on primary.
T1: App redirects user to profile page.
T2: Profile page reads from replica.
T3: Replica is 3 seconds behind.
T4: User sees old email.
```

Fix options:

```text
1. Route user's reads to primary for N seconds after write.
2. Use causal token/LSN tracking.
3. Read from lag-bounded replica only.
4. Accept staleness only for non-critical views.
```

### When replicas make primary worse

More replicas can increase primary burden:

```text
Primary must stream WAL to each replica.
Network bandwidth increases.
Replication slots may retain WAL.
Long-running replica queries can delay replay.
Monitoring/routing complexity increases.
```

If replicas lag, clients retry. Retries increase load. Increased load increases lag. Lag causes more retries. The snake starts eating its monitoring dashboard.

---

## 3D. Caching

Caching stores frequently read data closer to the application.

```text
Client -> App -> Redis -> PostgreSQL
               cache hit
```

### Cache-aside

App checks cache first. On miss, app loads DB and writes cache.

```text
GET key
  if exists -> return
  else:
    SELECT from DB
    SET key value TTL
```

Solves:

```text
Repeated reads of same data
Expensive aggregations
Hot product/user/profile pages
```

Does not solve:

```text
Write bottlenecks
Strict consistency
Large unique working sets
Uncacheable ad-hoc queries
```

Makes worse:

```text
Stampedes
Stale data
Hot keys
Redis memory pressure
DB overload on cache failure
```

### Stampede math

```text
Endpoint: /trending
Traffic: 50,000 requests/sec
Cache TTL: 300s
DB query cost: 150ms
Cache expires globally at T=0

If 10% of requests hit before cache refill:
  5,000 DB queries/sec

DB can handle:
  300 queries/sec

Overload factor:
  5,000 / 300 = 16.7x
```

Fix:

```text
TTL jitter
singleflight/request coalescing
stale-while-revalidate
background refresh
cache warming
rate limits
```

### Hot key

```text
Key: product:iphone-launch
Traffic: 200K reads/sec
Redis cluster nodes: 20

Consistent hashing distributes keys.
It does not split one key.

One node gets 200K reads/sec.
Other nodes are idle.
```

Fix:

```text
local in-process cache
key replication
client-side request coalescing
CDN if public
split object into subkeys if possible
```

### Negative caching

If many users request missing data:

```text
GET /coupon/SUPERBOWL2026
```

Without negative cache:

```text
Every miss hits DB.
```

With negative cache:

```text
coupon:SUPERBOWL2026 -> NOT_FOUND, TTL 30s
```

Danger:

```text
If coupon is created after negative cache, users still see not found until TTL expires.
```

---

## 3E. Indexing and Query Optimization as Scaling

The cheapest scaling pattern is often a correct index.

### B-tree mechanics

A B-tree index stores sorted keys with pointers to table rows.

```text
Index on (customer_id, created_at DESC)

               [customer_id ranges]
                  /          \
          [cust 1-500]     [cust 501-1000]
             /   \              /    \
          leaves linked in sorted order
```

Lookup:

```text
WHERE customer_id = 123
ORDER BY created_at DESC
LIMIT 20

1. Traverse tree to customer_id=123.
2. Walk newest created_at entries.
3. Stop after 20 rows.
```

### Composite index leftmost prefix

Index:

```sql
CREATE INDEX idx_orders_customer_status_created
ON orders (customer_id, status, created_at DESC);
```

Good:

```sql
WHERE customer_id = 123;
WHERE customer_id = 123 AND status = 'paid';
WHERE customer_id = 123 AND status = 'paid'
ORDER BY created_at DESC;
```

Bad:

```sql
WHERE status = 'paid';
WHERE created_at > now() - interval '1 day';
```

Because the index is sorted first by `customer_id`.

### Covering index

Query:

```sql
SELECT order_id, status, total_cents
FROM orders
WHERE customer_id = 123
ORDER BY created_at DESC
LIMIT 20;
```

Index:

```sql
CREATE INDEX CONCURRENTLY idx_orders_customer_created_cover
ON orders (customer_id, created_at DESC)
INCLUDE (order_id, status, total_cents);
```

Benefit:

```text
Index-only scan possible if visibility map cooperates.
Less heap access.
Lower I/O.
```

### Indexes slow writes

Every insert must update every relevant index.

```text
Table: orders
Indexes: 12
Write: INSERT order

Work:
  1 heap write
  12 index writes
  WAL for heap
  WAL for index changes
```

More indexes:

```text
better reads
slower writes
more WAL
more bloat
more vacuum work
more storage
```

### EXPLAIN ANALYZE BUFFERS

Command:

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT *
FROM orders
WHERE customer_id = 123
ORDER BY created_at DESC
LIMIT 20;
```

Bad output shape:

```text
Seq Scan on orders
  Filter: customer_id = 123
  Rows Removed by Filter: 799999980
  Buffers: shared read=1300000
Execution Time: 12400 ms
```

Good output shape:

```text
Index Scan using idx_orders_customer_created on orders
  Index Cond: customer_id = 123
  Buffers: shared hit=45
Execution Time: 6 ms
```

Mistaken interpretation:

```text
Cost numbers are planner estimates, not milliseconds.
Actual time and buffers show what happened.
```

---

## 3F. Connection Pooling

PostgreSQL uses one backend process per connection. Thousands of connections are expensive.

```text
500 app pods
20 connections per pod
= 10,000 PostgreSQL backends
```

That is not capacity. That is a scheduling riot.

### PgBouncer

```text
Apps ── thousands of client conns ──► PgBouncer
                                      │
                                      │ 100 server conns
                                      ▼
                                  PostgreSQL
```

### Pool modes

```text
session:
  server connection held for entire client session
  safest compatibility
  worst multiplexing

transaction:
  server connection held only during transaction
  best default for many web apps
  breaks session state assumptions

statement:
  server connection held for one statement
  highest multiplexing
  breaks multi-statement transactions
```

### Pool sizing math

PostgreSQL primary:

```text
CPU cores: 32
Useful active DB work: maybe 64-128 active queries
max_connections: 300
Reserved admin: 10
Replication/maintenance: 20
Safe app server connections: ~200
```

PgBouncer:

```ini
pool_mode = transaction
max_client_conn = 10000
default_pool_size = 50
reserve_pool_size = 10
query_wait_timeout = 10
server_idle_timeout = 300
```

If there are four app users/databases:

```text
4 × default_pool_size 50 = 200 server connections
```

This fits.

Danger:

```text
10 app roles × default_pool_size 50 = 500 server connections
```

This exceeds your safe budget.

### Commands

```sql
SHOW max_connections;
SHOW superuser_reserved_connections;
```

PgBouncer:

```sql
SHOW POOLS;
SHOW CLIENTS;
SHOW SERVERS;
SHOW STATS;
```

Bad `SHOW POOLS` smell:

```text
cl_active high
cl_waiting high
sv_active maxed
avg_wait_time increasing
```

Immediate meaning:

```text
Clients are waiting for DB server connections.
Either DB is slow, pool is undersized, or workload exceeded capacity.
```

Dangerous move:

```text
Increase app pool size.
```

Usually this increases pressure.

Safer:

```text
Identify slow queries holding server conns.
Kill/limit worst offenders.
Reduce app concurrency.
Shed non-critical traffic.
Increase PgBouncer server pool only if DB has headroom.
```

---

## 3G. Partitioning

Partitioning splits a table into smaller physical pieces.

```text
orders
├── orders_2026_01
├── orders_2026_02
├── orders_2026_03
└── orders_2026_04
```

### Time-based partitioning

Good for:

```text
events
logs
orders
metrics
audit trails
```

Query:

```sql
SELECT count(*)
FROM events
WHERE created_at >= '2026-05-01'
  AND created_at <  '2026-06-01';
```

If partitioned by month:

```text
Planner scans only May partition.
```

This is partition pruning.

### What partitioning solves

```text
Large table maintenance
Faster deletes/drop old data
Partition pruning
Smaller indexes per partition
Vacuum isolation
Data lifecycle management
```

### What it does not solve

```text
All partitions on same machine still share CPU/disk
Bad queries can still scan many partitions
Wrong partition key creates no pruning
Global uniqueness can be harder
```

### Hash partitioning

```text
orders partitioned by hash(customer_id)
```

Good:

```text
Even distribution across partitions
```

Bad:

```text
Time-based archival harder
Range queries across time hit many partitions
```

### Hot partition

```text
Partition key: tenant_id
Tenant A: 70% of traffic
Tenant B-Z: 30%

One tenant partition melts.
```

Fix:

```text
split hot tenant
compound key
tenant_id + bucket
dedicated shard for large tenant
rate limit tenant
```

---

## 3H. Sharding

Sharding splits data across multiple database nodes.

```text
Shard 0: customers 0-999999
Shard 1: customers 1000000-1999999
Shard 2: customers 2000000-2999999
```

### Application-level sharding

The application decides where data lives.

```python
shard_id = hash(customer_id) % 16
connection = shard_map[shard_id]
```

Pros:

```text
Simple conceptually
Works with ordinary PostgreSQL/MySQL
Clear routing for key-based queries
```

Cons:

```text
App owns complexity
Cross-shard queries are painful
Resharding is hard
Schema changes across shards
Backups across shards
Transactions across shards
```

### Scatter-gather

Query:

```sql
SELECT *
FROM orders
WHERE status = 'pending'
ORDER BY created_at DESC
LIMIT 100;
```

If `orders` is sharded by `customer_id`:

```text
Send query to all 64 shards.
Each shard returns candidates.
Coordinator merges/sorts.
p99 = slowest shard.
```

Math:

```text
Per-shard p95: 100ms
Per-shard p99: 500ms
64 shards queried

Chance at least one shard is p99-ish is high.
User sees tail latency.
```

### Cross-shard transactions

Transfer money:

```text
Debit account on shard 3.
Credit account on shard 19.
```

Choices:

```text
2PC:
  strong but coordination-heavy

Saga:
  eventual, compensating actions

Redesign:
  place related accounts together if possible

Central ledger:
  one strongly consistent system for money movement
```

### Rebalancing under load

Adding shards is not free.

```text
Move 2 TB from shard 4 to shard 17
Network bandwidth: 200 MB/s safe
Time:
  2 TB / 200 MB/s ≈ 10,000s ≈ 2.8 hours
```

But rebalancing consumes:

```text
disk I/O
network
CPU
replication bandwidth
cache warmth
operator attention
```

Dangerous during incident:

```text
Starting heavy data movement while DB is already I/O saturated.
```

---

## 3I. CQRS and Read Models

CQRS separates write model from read model.

```text
Write path:
  App -> PostgreSQL authoritative store

CDC path:
  PostgreSQL WAL -> Debezium -> Kafka -> Read model builder

Read path:
  App -> OpenSearch / Redis / materialized table
```

### What it solves

```text
Complex read queries
Search
Dashboard aggregation
Different read/write shapes
Expensive joins
High read fanout
```

### What it does not solve

```text
Strong read-after-write by default
Write path bottlenecks
Schema governance
Operational complexity
```

### Dual-write trap

Bad:

```python
db.insert(order)
kafka.publish(OrderCreated)
```

Failure:

```text
DB insert succeeds.
Kafka publish fails.
Order exists, event missing.
```

Or:

```text
Kafka publish succeeds.
DB transaction rolls back.
Event exists for order that does not.
```

Fix:

```text
Outbox pattern:
  Write order and outbox event in same DB transaction.
  CDC publishes outbox row to Kafka.
```

### Rebuild/replay

Read models must be rebuildable.

```text
If OpenSearch corrupts:
  1. Create new index.
  2. Replay events or snapshot + CDC.
  3. Validate counts.
  4. Switch alias.
```

Dangerous during incident:

```text
Rebuilding 5 TB search index while DB primary is saturated.
```

---

## 3J. Multi-Region Scaling

Multi-region databases solve geography, not magic.

```text
Users in India -> ap-south
Users in Europe -> eu-west
Users in US -> us-east
```

### Leader-follower

```text
Writes -> primary region
Reads -> local replicas
```

Pros:

```text
Simple conflict model
One write authority
```

Cons:

```text
Remote writes pay cross-region latency
Replica reads stale
Region failover hard
```

### Multi-leader

```text
US accepts writes.
EU accepts writes.
They replicate to each other.
```

Pros:

```text
Low local write latency
Regional autonomy
```

Cons:

```text
Write conflicts
Clock skew
Merge logic
Split-brain risk
```

### Leaderless/quorum

```text
Write to N replicas.
Read from R replicas.
If R + W > N, quorum overlap.
```

Pros:

```text
Availability
Tunable consistency
```

Cons:

```text
Operational complexity
Read repair
Hinted handoff
Conflict resolution
Tail latency
```

### PACELC reminder

```text
If Partition:
  choose Availability or Consistency.

Else:
  choose Latency or Consistency.
```

Multi-region always pays this tax. Sometimes the invoice arrives as user latency. Sometimes as stale data. Sometimes as conflict resolution.

---

## 3K. When NOT to Scale the Database

Do not scale the database when the real problem is upstream.

```text
Bad API shape:
  1 user request -> 500 DB queries

Fix:
  batch, join, DataLoader, change endpoint
```

```text
Non-critical synchronous work:
  checkout waits for email, analytics, recommendation update

Fix:
  async after commit
```

```text
Pointless consistency requirement:
  dashboard reads from primary because "fresh is better"

Fix:
  replica with lag label
```

```text
Cold data:
  8 years of audit logs in hot OLTP table

Fix:
  archive/tier/partition
```

```text
Traffic spike:
  bot or abusive tenant

Fix:
  rate limit, tenant isolation, shed load
```

Scaling is not always adding capacity. Sometimes it is removing unnecessary work.

---

## 4. Decision Framework

```text
╔══════════════════════════════════════════════════════════════════════╗
║              DATABASE SCALING DECISION FRAMEWORK                    ║
╠═══════════════════════╦════════════════════╦════════════════════════╣
║ Bottleneck             ║ Try First          ║ Prove With             ║
╠═══════════════════════╬════════════════════╬════════════════════════╣
║ Bad query              ║ Index/query rewrite║ EXPLAIN ANALYZE BUFFERS║
║ Too many connections   ║ PgBouncer          ║ SHOW POOLS, activity   ║
║ Read-heavy workload    ║ Replica/cache      ║ QPS, lag, hit ratio    ║
║ Write-heavy primary    ║ Batch/shard        ║ WAL, fsync, locks      ║
║ Large table            ║ Partition/archive  ║ table/index size       ║
║ Hot tenant             ║ isolate/split      ║ per-tenant metrics     ║
║ Complex reads          ║ CQRS/read model    ║ query cost, fanout     ║
║ Global latency         ║ multi-region       ║ RTT, consistency needs ║
║ Lock contention        ║ tx redesign        ║ pg_locks, waits        ║
║ Replica lag            ║ reduce replay load ║ pg_stat_replication    ║
╚═══════════════════════╩════════════════════╩════════════════════════╝
```

## Do Not Apply Scaling Patterns Blindly

If the database is CPU-bound because of a sequential scan, adding replicas can multiply the bad query across more machines. You now have the same bad plan in more places.

If the primary is WAL-bound, adding indexes can make writes slower.

If Redis is already near CPU saturation, moving more reads to Redis during a PostgreSQL incident can turn one incident into two.

If OpenSearch is already at high heap pressure, redirecting product catalog reads there can cause search instability.

If a replica is lagging, routing checkout reads to it can create correctness bugs.

The pattern is not the plan. The bottleneck is the plan.

---

## 5. Production Failure Patterns

### FAILURE 1: Read Replica Lag Causes Stale User-Visible Reads

**WHAT HAPPENS:**  
The application writes to primary but reads from a lagging replica.

**WHY IT HAPPENS:**  
Replication is asynchronous. The primary commits before the replica replays WAL.

**SYMPTOMS:**

```text
- User updates data but sees old value.
- Dashboards show stale counts.
- Order confirmation page missing newly created order.
- Replica lag increasing.
- Support tickets: "I just changed it but it reverted."
```

**NUMBERS:**

```text
Primary WAL generation: 30 MB/s
Replica replay: 20 MB/s
Lag growth: 10 MB/s
After 5 minutes: 3 GB WAL behind

If average WAL for a checkout is 20 KB:
  3 GB / 20 KB ≈ 150,000 checkout changes behind
```

**HOW TO DETECT:**

```sql
SELECT
  application_name,
  state,
  pg_wal_lsn_diff(sent_lsn, replay_lsn) AS lag_bytes,
  replay_lag
FROM pg_stat_replication;
```

**IMMEDIATE MITIGATION:**

1. Route read-your-writes flows to primary.
2. Disable replica reads for safety-critical paths.
3. Remove lagging replica from read pool.
4. Reduce heavy analytical queries on replica.
5. Communicate stale-read impact to support/product.

**LONG-TERM FIX:**

```text
- Lag-aware read routing.
- Causal tokens/LSN tracking.
- Separate analytics replicas.
- Strong read policy for critical features.
- Alerts on business lag, not just byte lag.
```

**DANGEROUS MOVE:**  
Blindly promote a lagging replica. You may lose committed data.

---

### FAILURE 2: Connection Pool Exhaustion from Slow Queries

**WHAT HAPPENS:**  
Queries become slower. Connections stay checked out longer. Pool fills. New requests queue. Latency explodes.

**WHY IT HAPPENS:**  
Pool capacity is concurrency, not throughput. If each query holds a connection 20x longer, effective throughput falls 20x.

**NUMBERS:**

```text
Pool size: 100 server connections
Normal query duration: 50ms

Capacity:
  100 / 0.05 = 2,000 queries/sec

Incident query duration: 2s

Capacity:
  100 / 2 = 50 queries/sec
```

**SYMPTOMS:**

```text
- PgBouncer cl_waiting rising.
- App timeouts.
- DB CPU maybe not maxed.
- Queries stuck active.
- HTTP p95 increases before error rate.
```

**HOW TO DETECT:**

```sql
-- PostgreSQL
SELECT pid, state, wait_event_type, wait_event, now() - query_start AS age, query
FROM pg_stat_activity
WHERE state <> 'idle'
ORDER BY age DESC
LIMIT 20;
```

```sql
-- PgBouncer
SHOW POOLS;
SHOW CLIENTS;
SHOW SERVERS;
```

**IMMEDIATE MITIGATION:**

1. Preserve admin access.
2. Identify longest-running queries.
3. Cancel non-critical offenders.
4. Shed non-critical traffic.
5. Reduce app concurrency if DB saturated.
6. Increase pool only if DB has CPU/I/O headroom.

**LONG-TERM FIX:**

```text
- Query timeouts.
- Statement timeout per workload.
- Better indexes.
- Separate pools per service/workload.
- Backpressure at app layer.
```

**DANGEROUS MOVE:**  
Increasing application pool size. This usually worsens the queue.

---

### FAILURE 3: Adding Replicas Melts the Primary with WAL Pressure

**WHAT HAPPENS:**  
More replicas are added, but primary network/WAL pressure increases and write latency worsens.

**WHY IT HAPPENS:**  
The primary must stream WAL. Replication slots can retain WAL if replicas lag. More replicas also increase monitoring, connections, and failover complexity.

**NUMBERS:**

```text
WAL generation: 80 MB/s
Replicas: 5
Outbound replication traffic: up to 400 MB/s

Primary network safe budget: 300 MB/s
Over budget: 100 MB/s
```

**SYMPTOMS:**

```text
- WAL directory growing.
- Replication slots retaining WAL.
- Primary network egress high.
- Write latency increases.
- Replicas still lag.
```

**HOW TO DETECT:**

```sql
SELECT slot_name, active, restart_lsn,
       pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) AS retained_bytes
FROM pg_replication_slots;
```

```bash
df -h
iostat -xz 1
```

**IMMEDIATE MITIGATION:**

1. Drop unused/stale replication slots only after confirming they are safe.
2. Stop adding replicas.
3. Reduce write volume if possible.
4. Move analytics away from hot replicas.
5. Increase WAL storage only as a temporary safety step.

**LONG-TERM FIX:**

```text
- Cascading replicas where appropriate.
- Separate analytics pipeline.
- Capacity budget for replication egress.
- WAL retention alerts.
```

**DANGEROUS MOVE:**  
Deleting WAL or replication slots without understanding recovery impact.

---

### FAILURE 4: Cache Stampede After TTL Expiry

**WHAT HAPPENS:**  
A hot key expires. Many clients miss at once. All regenerate from DB.

**WHY IT HAPPENS:**  
TTL synchronization creates a periodic herd.

**NUMBERS:**

```text
Hot key traffic: 40,000 req/sec
Cache hit ratio before expiry: 99.5%
DB sees: 200 req/sec

At expiry for 2 seconds:
  40,000 req/sec hit DB

DB capacity: 1,000 req/sec
Overload: 40x
```

**HOW TO DETECT:**

```bash
redis-cli INFO stats
redis-cli --hotkeys
redis-cli SLOWLOG GET 20
```

PostgreSQL:

```sql
SELECT query, calls, mean_exec_time
FROM pg_stat_statements
ORDER BY calls DESC
LIMIT 20;
```

**IMMEDIATE MITIGATION:**

1. Extend TTL for hot keys.
2. Enable stale-while-revalidate.
3. Add singleflight lock.
4. Rate limit regeneration.
5. Serve degraded/stale response.

**LONG-TERM FIX:**

```text
- TTL jitter.
- Background refresh.
- Cache warming before launch.
- Local cache for hottest keys.
```

**DANGEROUS MOVE:**  
Flush Redis during DB stress.

---

### FAILURE 5: Hot Tenant Overwhelms One Shard

**WHAT HAPPENS:**  
One tenant/customer creates most traffic and overloads one shard.

**WHY IT HAPPENS:**  
Hashing distributes keys, not load. A single hot key or hot tenant remains hot.

**NUMBERS:**

```text
16 shards
Total traffic: 160K QPS
Expected average: 10K QPS/shard

Tenant A: 70K QPS
Shard 9 total: 80K QPS
Other shards: 5K-8K QPS
```

**HOW TO DETECT:**

```sql
SELECT tenant_id, count(*)
FROM request_log
WHERE created_at > now() - interval '5 minutes'
GROUP BY tenant_id
ORDER BY count(*) DESC
LIMIT 20;
```

Look at per-shard metrics:

```text
CPU
QPS
p95 latency
lock waits
connection count
disk I/O
```

**IMMEDIATE MITIGATION:**

1. Rate limit hot tenant if contract allows.
2. Move tenant to dedicated capacity if prebuilt.
3. Disable non-critical features for tenant.
4. Avoid resharding during peak unless already automated and safe.

**LONG-TERM FIX:**

```text
- Tenant isolation.
- Tenant-aware capacity planning.
- Split large tenants by secondary bucket.
- Dedicated shard class for whales.
```

**DANGEROUS MOVE:**  
Full rebalancing during active overload without I/O headroom.

---

### FAILURE 6: Query Plan Regression After Statistics Drift

**WHAT HAPPENS:**  
A query suddenly chooses a bad plan.

**WHY IT HAPPENS:**  
Data distribution changed. Statistics stale. Planner estimates wrong cardinality.

**SYMPTOMS:**

```text
- Same query text suddenly slower.
- EXPLAIN estimated rows far from actual rows.
- Recent data load or tenant growth.
- CPU and buffers spike.
```

**HOW TO DETECT:**

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT ...
```

Look for:

```text
estimated rows: 100
actual rows: 10,000,000
```

Check stats:

```sql
SELECT relname, last_analyze, last_autoanalyze
FROM pg_stat_user_tables
ORDER BY last_autoanalyze NULLS FIRST
LIMIT 20;
```

**IMMEDIATE MITIGATION:**

```sql
ANALYZE table_name;
```

If one query is melting production:

```sql
SELECT pg_cancel_backend(pid);
```

**LONG-TERM FIX:**

```text
- Tune autovacuum/analyze thresholds.
- Extended statistics.
- Better indexes.
- Query rewrite.
- Plan regression alerts for critical queries.
```

**DANGEROUS MOVE:**  
Randomly disabling planner options globally during production.

---

### FAILURE 7: Index Bloat and Vacuum Debt

**WHAT HAPPENS:**  
Tables and indexes contain many dead tuples. Queries read more pages. Writes slow down. Vacuum cannot catch up.

**WHY IT HAPPENS:**  
MVCC creates old row versions. Long transactions prevent cleanup. High update/delete churn bloats indexes.

**HOW TO DETECT:**

```sql
SELECT
  relname,
  n_dead_tup,
  n_live_tup,
  last_vacuum,
  last_autovacuum
FROM pg_stat_user_tables
ORDER BY n_dead_tup DESC
LIMIT 20;
```

Long transactions:

```sql
SELECT pid, now() - xact_start AS xact_age, state, query
FROM pg_stat_activity
WHERE xact_start IS NOT NULL
ORDER BY xact_age DESC
LIMIT 20;
```

**IMMEDIATE MITIGATION:**

1. Kill or fix long idle-in-transaction sessions.
2. Let autovacuum catch up.
3. Avoid heavy reindex during peak.
4. Use `REINDEX CONCURRENTLY` only with capacity checks.

**LONG-TERM FIX:**

```text
- Autovacuum tuning.
- Shorter transactions.
- Lower update churn.
- Fillfactor tuning for hot update tables.
- Index lifecycle review.
```

**DANGEROUS MOVE:**  
`VACUUM FULL` during incident. It rewrites the table and takes strong locks.

---

### FAILURE 8: Cross-Shard Scatter-Gather Tail Explosion

**WHAT HAPPENS:**  
A query fans out to all shards. User latency becomes slowest-shard latency plus merge time.

**NUMBERS:**

```text
64 shards
Average shard latency: 80ms
One shard p99: 2s
Coordinator merge: 300ms

User p99:
  2s + 300ms = 2.3s
```

**HOW TO DETECT:**

```text
- Query fanout count.
- Per-shard latency histogram.
- Coordinator merge time.
- Slowest shard identity.
```

**IMMEDIATE MITIGATION:**

1. Disable expensive global query.
2. Serve cached/precomputed results.
3. Add time bounds.
4. Reduce shard fanout with routing key.

**LONG-TERM FIX:**

```text
- Read model.
- Denormalized aggregate.
- Better shard key.
- Search/OLAP system for global queries.
```

**DANGEROUS MOVE:**  
Adding more shards. More shards can make scatter-gather worse.

---

### FAILURE 9: Failover Causes Thundering Herd

**WHAT HAPPENS:**  
Primary fails. Clients reconnect simultaneously. PgBouncer/app pools storm the new primary.

**SYMPTOMS:**

```text
- New primary promoted.
- Thousands of connections open.
- DNS stale clients keep hitting old primary.
- PgBouncer pools full.
- CPU high before useful traffic resumes.
```

**HOW TO DETECT:**

```sql
SELECT count(*), state
FROM pg_stat_activity
GROUP BY state;
```

PgBouncer:

```sql
SHOW CLIENTS;
SHOW SERVERS;
SHOW POOLS;
```

**IMMEDIATE MITIGATION:**

1. Confirm single writable primary.
2. Verify fencing/old primary not accepting writes.
3. Throttle reconnects.
4. Restart app waves gradually.
5. Preserve admin connections.
6. Check replication timeline/data loss.

**LONG-TERM FIX:**

```text
- Connection jitter.
- Failover runbook.
- Client DNS TTL discipline.
- PgBouncer in front of primary.
- Fencing tokens.
```

**DANGEROUS MOVE:**  
Promoting multiple replicas or allowing old primary back without rewind/fencing.

---

### FAILURE 10: Dual-Write Inconsistency

**WHAT HAPPENS:**  
DB update succeeds but cache/search/Kafka update fails, or vice versa.

**WHY IT HAPPENS:**  
Two systems cannot be updated atomically without a coordination pattern.

**HOW TO DETECT:**

```sql
-- Compare DB order count to search/read model count by time bucket.
SELECT date_trunc('minute', created_at), count(*)
FROM orders
WHERE created_at > now() - interval '1 hour'
GROUP BY 1
ORDER BY 1;
```

OpenSearch:

```bash
curl -s localhost:9200/orders/_count
```

Kafka/Debezium:

```bash
kafka-consumer-groups --bootstrap-server broker:9092 \
  --describe --group search-indexer
```

**IMMEDIATE MITIGATION:**

1. Stop relying on inconsistent read model for critical flow.
2. Route critical reads to DB if capacity allows.
3. Start reconciliation job with rate limit.
4. Communicate stale search/cache impact.

**LONG-TERM FIX:**

```text
- Transactional outbox.
- CDC pipeline.
- Idempotent consumers.
- Replayable events.
- Reconciliation checks.
```

**DANGEROUS MOVE:**  
Ad-hoc backfill at full speed during primary saturation.

---

### FAILURE 11: Rebalancing Under Load Makes Outage Worse

**WHAT HAPPENS:**  
Team starts moving data to fix hot shard. The movement consumes I/O/network and worsens the incident.

**NUMBERS:**

```text
Shard overloaded disk:
  85% util
  10ms await

Rebalance copy:
  adds 150 MB/s reads
  adds 150 MB/s writes

Disk util:
  99%
await:
  80ms
```

**HOW TO DETECT:**

```bash
iostat -xz 1
iftop
df -h
```

**IMMEDIATE MITIGATION:**

1. Pause or throttle rebalance.
2. Shed hot traffic.
3. Use metadata-only routing changes if prebuilt.
4. Move only small hot subset if safe.

**LONG-TERM FIX:**

```text
- Online rebalancing with throttles.
- Pre-split hot tenants.
- Capacity-aware shard movement.
- Dry-run playbooks.
```

**DANGEROUS MOVE:**  
Bulk data movement during I/O saturation.

---

### FAILURE 12: Multi-Region Consistency Surprise

**WHAT HAPPENS:**  
A feature assumes local reads are fresh globally. Multi-region replication violates that assumption.

**NUMBERS:**

```text
US primary writes order.
EU replica lag: 800ms normal, 12s during incident.
EU user checks order status after 1s.
Reads old state.
```

**SYMPTOMS:**

```text
- Region-specific stale reads.
- Support tickets cluster by geography.
- Conflict resolution logs.
- Higher latency after forcing primary reads.
```

**HOW TO DETECT:**

```text
- Per-region replication lag.
- Read path region tags.
- Trace showing read served from stale replica.
```

**IMMEDIATE MITIGATION:**

1. Route critical reads to primary or bounded-lag replica.
2. Add UI stale labels for non-critical views.
3. Disable conflicting writes in secondary region if needed.

**LONG-TERM FIX:**

```text
- Per-feature consistency policy.
- Causal reads.
- Regional ownership.
- Conflict resolution.
- PACELC-driven design.
```

**DANGEROUS MOVE:**  
Assuming “eventual” has a business-safe bound.

---

## 6. SRE Diagnostic Toolkit

### PostgreSQL

```sql
SELECT pid, usename, application_name, client_addr,
       state, wait_event_type, wait_event,
       now() - query_start AS query_age,
       query
FROM pg_stat_activity
ORDER BY query_age DESC
LIMIT 20;
```

Proves:

```text
Who is active, waiting, idle in transaction, or holding connections.
```

Bad:

```text
many active long queries
many idle in transaction
wait_event = Lock
```

---

```sql
SELECT query, calls, total_exec_time, mean_exec_time,
       rows, shared_blks_hit, shared_blks_read
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT 20;
```

Proves:

```text
Which queries consume total DB time.
```

Mistake:

```text
Looking only at mean latency. A 20ms query called 10M times can be worse than one 5s query.
```

---

```sql
SELECT locktype, relation::regclass, mode, granted, pid
FROM pg_locks
ORDER BY granted, relation;
```

Proves:

```text
Lock waits and blockers.
```

---

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT ...
```

Proves:

```text
Actual plan, actual rows, actual time, buffer hits/reads.
```

---

```sql
SELECT relname, n_live_tup, n_dead_tup,
       last_vacuum, last_autovacuum,
       last_analyze, last_autoanalyze
FROM pg_stat_user_tables
ORDER BY n_dead_tup DESC
LIMIT 20;
```

Proves:

```text
Vacuum/analyze health.
```

---

```sql
SHOW max_connections;
SHOW shared_buffers;
SHOW work_mem;
SHOW effective_cache_size;
```

Proves:

```text
Capacity/config assumptions.
```

### Linux

```bash
iostat -xz 1
```

Good:

```text
reasonable await
util not pinned
```

Bad:

```text
%util near 100
await high
queue depth high
```

---

```bash
vmstat 1
```

Watch:

```text
r: run queue
b: blocked processes
wa: I/O wait
si/so: swap in/out
```

---

```bash
ss -s
```

Proves:

```text
Socket pressure, TIME_WAIT, established counts.
```

### PgBouncer

```sql
SHOW POOLS;
SHOW CLIENTS;
SHOW SERVERS;
SHOW STATS;
```

Good:

```text
low cl_waiting
server connections stable
```

Bad:

```text
cl_waiting rising
sv_active maxed
pool wait increasing
```

### Redis

```bash
redis-cli INFO
redis-cli SLOWLOG GET 20
redis-cli --hotkeys
redis-cli MEMORY STATS
```

Warning:

```text
MONITOR is dangerous on busy Redis.
It can add load and expose sensitive data.
Use only briefly and carefully.
```

### Kafka/Debezium

```bash
kafka-consumer-groups --bootstrap-server broker:9092 \
  --describe --group search-indexer
```

Proves:

```text
Consumer lag by partition.
```

Bad:

```text
lag rising on one partition only -> hot key or stuck poison message
lag rising everywhere -> consumer undercapacity or downstream outage
```

### Cassandra

```bash
nodetool status
nodetool tpstats
nodetool tablehistograms keyspace table
nodetool toppartitions keyspace table
nodetool compactionstats
```

### OpenSearch

```bash
curl -s localhost:9200/_cluster/health?pretty
curl -s localhost:9200/_cat/shards?v
curl -s localhost:9200/_cat/thread_pool?v
curl -s localhost:9200/_nodes/stats?pretty
```

---

## 7. Hands-On Exercise

## Diagnose and fix a missing-index scaling problem in PostgreSQL

### Setup assumptions

```text
PostgreSQL available locally.
You can create a test database.
Dataset size can be reduced if laptop is small.
```

### Create table

```sql
CREATE TABLE orders (
  id bigserial PRIMARY KEY,
  customer_id bigint NOT NULL,
  status text NOT NULL,
  total_cents integer NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
```

### Insert data

```sql
INSERT INTO orders (customer_id, status, total_cents, created_at)
SELECT
  (random() * 100000)::bigint,
  CASE WHEN random() < 0.8 THEN 'paid' ELSE 'pending' END,
  (random() * 10000)::int,
  now() - (random() * interval '365 days')
FROM generate_series(1, 3000000);
```

### Bad query

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, status, total_cents, created_at
FROM orders
WHERE customer_id = 4242
ORDER BY created_at DESC
LIMIT 20;
```

Expected bad shape:

```text
Seq Scan or expensive sort
Rows Removed by Filter: millions
Buffers: many reads/hits
Execution Time: hundreds/thousands ms
```

### Add index

```sql
CREATE INDEX CONCURRENTLY idx_orders_customer_created
ON orders (customer_id, created_at DESC)
INCLUDE (status, total_cents);
```

### Rerun

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, status, total_cents, created_at
FROM orders
WHERE customer_id = 4242
ORDER BY created_at DESC
LIMIT 20;
```

Expected good shape:

```text
Index Scan or Index Only Scan
small buffer count
Execution Time: milliseconds
```

### Break the system

Run multiple sessions of the bad query before adding the index:

```bash
pgbench -n -c 50 -j 8 -T 60 -f bad_query.sql yourdb
```

Observe:

```sql
SELECT state, wait_event_type, wait_event, count(*)
FROM pg_stat_activity
GROUP BY 1,2,3;
```

### Fix

Add the index concurrently, rerun load, compare:

```text
p95 latency
CPU
buffers read
connections active
```

### Lesson proven

The scaling pattern was not replicas, cache, or sharding. It was query/index design.

---

## 8. Hardcore SRE Scenario

```text
INCIDENT: Flash Sale Database Scaling Meltdown
Severity: P1
Business: E-commerce platform
Date: Friday 20:00 IST
Event: Celebrity sneaker drop
```

## Architecture

```text
                         ┌────────────────────┐
                         │ Mobile/Web Clients │
                         └─────────┬──────────┘
                                   │
                                   ▼
                         ┌────────────────────┐
                         │ Kubernetes Apps    │
                         │ 240 pods           │
                         │ Hikari pool 20 ea  │
                         └─────────┬──────────┘
                                   │ 4,800 client conns
                                   ▼
                         ┌────────────────────┐
                         │ PgBouncer          │
                         │ pool_size=180      │
                         │ reserve=20         │
                         └─────────┬──────────┘
                                   │
                                   ▼
                         ┌────────────────────┐
                         │ PostgreSQL Primary │
                         │ 32 vCPU, 256GB RAM │
                         │ max_conn=300       │
                         └──────┬─────┬───────┘
                                │ WAL │
             ┌──────────────────┘     └──────────────────┐
             ▼                                             ▼
      ┌───────────────┐                           ┌───────────────┐
      │ Read Replica 1│                           │ Read Replica 2│
      │ product reads │                           │ analytics     │
      └───────────────┘                           └───────────────┘

Other systems:
  Redis Cluster: product cache, cart cache
  Debezium/Kafka: order events -> OpenSearch
  OpenSearch: product search/read model
```

## Baseline

```text
PostgreSQL:
  Primary CPU: 45%
  p95 checkout query: 80ms
  p99 checkout query: 180ms
  WAL generation: 15 MB/s
  PgBouncer cl_waiting: 0
  Active server conns: 80/180

Replicas:
  replay lag: < 200ms

Redis:
  hit ratio: 96%
  CPU per node: 35%
  hottest key: 8K req/sec

OpenSearch:
  cluster green
  p95 search: 120ms

Business:
  normal revenue: $30K/min
```

## Incident metrics at 20:07

```text
Traffic:
  10x normal
  600K active users
  70% viewing same product

PostgreSQL:
  CPU: 96%
  I/O wait: 28%
  WAL generation: 85 MB/s
  checkpoint write time spike
  p95 checkout query: 9.2s
  p99 checkout query: 28s
  active server conns: 200/200
  PgBouncer cl_waiting: 3,800

Replicas:
  Replica 1 lag: 14s
  Replica 2 lag: 95s

Redis:
  hit ratio dropped from 96% to 62%
  Redis node 7 CPU: 94%
  key product:sku:SNKR-2026: 180K req/sec
  evicted_keys increasing

Kafka/Debezium:
  search-indexer lag: 4.8M messages
  outbox connector running but delayed

OpenSearch:
  yellow cluster
  indexing queue high
  search p95: 2.8s

Business:
  checkout success rate: 61%
  payment auth success but order creation missing for some users
  estimated revenue loss: $90K/min
```

## Recent changes

```text
1. Marketing moved launch time from 22:00 to 20:00 without SRE readiness review.
2. Product team added "people also bought" widget on product page.
3. Query added:

SELECT *
FROM orders
WHERE sku = $1
  AND status = 'paid'
ORDER BY created_at DESC
LIMIT 100;

4. No composite index on (sku, status, created_at).
5. Redis TTL for product page cache set to exactly 300s.
6. App deployment increased Hikari pool from 10 to 20.
```

## Misleading signals

```text
- OpenSearch is yellow, but checkout does not require search.
- Redis CPU is high, but not all Redis nodes are high.
- Replicas exist, but both are lagging.
- Primary CPU is high, but lock waits are also rising.
- Payments show successful authorizations, making business believe orders succeeded.
```

## Questions

1. What is the trigger, precondition, amplifier, victim chain?
2. Calculate why PgBouncer saturated.
3. Should you redirect product reads to Redis, replicas, OpenSearch, or primary?
4. What must you verify before each mitigation?
5. What is the immediate mitigation order?
6. What dangerous moves must be avoided?
7. What long-term architecture changes prevent this?
8. What should incident communication say?

---

## 9. Expert Answer to Scenario

### Q1. Trigger, preconditions, amplifiers, victims

```text
TRIGGER:
  Celebrity sneaker launch causes 10x traffic.

PRECONDITIONS:
  Missing index on orders(sku, status, created_at).
  Product cache TTL synchronized at 300s.
  App pool doubled from 10 to 20.
  No SRE readiness review.
  Hot product key not protected.
  Replicas already share WAL/replay dependency.
  Search indexer depends on Debezium/Kafka lag.

AMPLIFIERS:
  Cache stampede.
  Bad query holds DB connections longer.
  Larger app pools create more concurrent pressure.
  PgBouncer queue grows.
  Replica lag makes read routing unsafe.
  Redis hot node becomes secondary bottleneck.
  OpenSearch lag creates stale read model.
  Users retry checkout.

VICTIMS:
  Checkout API.
  PostgreSQL primary.
  PgBouncer.
  Redis node 7.
  Replicas.
  Kafka/OpenSearch freshness.
  Customer support/payment reconciliation.
```

Root cause chain:

```text
Launch traffic
  -> product cache TTL expires
  -> Redis misses hit app/DB
  -> new widget runs missing-index query
  -> query duration jumps
  -> connections held longer
  -> PgBouncer saturates
  -> app requests queue/time out
  -> users retry
  -> primary WAL and CPU rise
  -> replicas lag
  -> read models stale
  -> order/payment inconsistency visible
```

### Q2. PgBouncer saturation math

Baseline:

```text
Pool size: 200 server connections
Checkout query: 80ms

Capacity:
  200 / 0.08 = 2,500 queries/sec
```

Incident:

```text
Bad query p95: 9.2s

Capacity:
  200 / 9.2 ≈ 21.7 queries/sec
```

If app sends even 1,000 DB requests/sec:

```text
Queue growth:
  1,000 - 22 = 978 waiting/sec
```

In 4 seconds:

```text
~3,900 waiting clients
```

Observed:

```text
PgBouncer cl_waiting = 3,800
```

The math matches.

### Q3. Where should reads go?

Not blindly anywhere.

#### Redis?

Verify first:

```bash
redis-cli INFO
redis-cli --hotkeys
redis-cli SLOWLOG GET 20
redis-cli MEMORY STATS
```

Redis node 7 is already 94% CPU with 180K req/sec hot key. Sending more traffic there may kill Redis. Safer: serve stale local cache, CDN/static fallback, or request coalescing rather than increasing Redis dependency.

#### Replicas?

Check:

```sql
SELECT application_name, replay_lag,
       pg_wal_lsn_diff(sent_lsn, replay_lsn) AS lag_bytes
FROM pg_stat_replication;
```

Replica 1 lag 14s, Replica 2 lag 95s. Not safe for checkout or read-your-writes. Maybe safe for labeled non-critical product browsing if stale acceptable, but not inventory/order/payment.

#### OpenSearch?

OpenSearch is yellow and p95 2.8s. It is stale due to Kafka lag. Not safe for critical product availability. Maybe search browsing can degrade, but not checkout.

#### Primary?

Primary is already saturated. Do not move more reads to primary unless they replace worse work or are strictly required for correctness.

Correct answer:

```text
Reduce work first.
Do not move load blindly.
Use stale/degraded product page.
Disable people-also-bought widget.
Protect checkout correctness.
```

### Q4. Operational prerequisites

Before touching DB:

```sql
SHOW max_connections;
SHOW superuser_reserved_connections;

SELECT count(*), state
FROM pg_stat_activity
GROUP BY state;
```

Can operators connect?

```text
If no reserved/admin access, mitigation may fail.
```

Before killing queries:

```sql
SELECT pid, now() - query_start AS age, application_name, query
FROM pg_stat_activity
WHERE state = 'active'
ORDER BY age DESC
LIMIT 20;
```

Before cache redirect:

```text
Check Redis hot node capacity.
```

Before failover:

```text
Check replica lag.
Check timeline/fencing.
Check old primary isolation.
```

Before reindex:

```text
Check I/O capacity.
Use CREATE INDEX CONCURRENTLY.
Do not run heavy index build if primary is already I/O saturated unless it is explicitly chosen and throttled.
```

### Q5. Immediate mitigation order

```text
L1: Stop the bleeding
```

1. Declare P1, assign incident commander.
2. Freeze deploys.
3. Disable “people also bought” widget via feature flag.
4. Serve degraded product page from stale cache/static fallback.
5. Add request coalescing/singleflight for hot product key.
6. Rate limit product-page refresh and bot traffic.
7. Preserve checkout path and admin connections.

```text
L2: Relieve database pressure
```

8. Cancel worst non-critical queries.
9. Reduce app DB concurrency if necessary.
10. Temporarily route only safe stale reads to least-lagging replica.
11. Do not route correctness-sensitive reads to lagging replicas.
12. Increase PgBouncer pool only if DB has CPU/I/O headroom. It does not.

```text
L3: Stabilize downstream systems
```

13. Pause non-critical OpenSearch indexing if it competes for resources.
14. Let Debezium/Kafka lag drain after primary stabilizes.
15. Reconcile payment auths vs orders.

```text
L4: Controlled repair
```

16. Create missing index concurrently after verifying I/O headroom:

```sql
CREATE INDEX CONCURRENTLY idx_orders_sku_status_created
ON orders (sku, status, created_at DESC);
```

But if I/O is already redline, first reduce workload.

### Q6. Dangerous moves

```text
- Fail over to a replica lagging 14s or 95s.
- Flush Redis.
- Increase app pool size.
- Rebalance shards during I/O saturation.
- Full reindex/VACUUM FULL during peak.
- Route checkout reads to stale replicas.
- Backfill OpenSearch at full speed.
- Kill all DB sessions without preserving admin and critical checkout.
```

### Q7. Long-term redesign

```text
Primary prevention:
  - Composite index for widget query.
  - Query review for launch features.
  - Cache TTL jitter.
  - Hot-key protection.
  - Launch readiness runbook.
  - Per-feature consistency policy.

Fallback:
  - Stale-while-revalidate product page.
  - Disable non-critical widgets.
  - Lag-aware read routing.
  - Dedicated analytics replica.
  - Separate pools per workload.

Last resort:
  - Queue non-critical writes.
  - Shed browse traffic to protect checkout.
  - Manual payment/order reconciliation.
  - Region or tenant-specific throttling.
```

Capacity assumptions:

```text
Redis hot-key fallback:
  must support 200K+ req/sec or use local/CDN layer.

Replica fallback:
  must have lag < product SLA and enough CPU.

OpenSearch fallback:
  must be green/yellow-safe and freshness acceptable.

Primary fallback:
  must have available connections and I/O headroom.
```

### Q8. Incident communication

Internal update:

```text
P1 checkout degradation during sneaker launch.
Primary impact: checkout success rate 61%, estimated revenue loss $90K/min.
Current hypothesis: DB connection saturation caused by cache stampede plus missing-index query from new widget.
Immediate mitigation: disabling non-critical widget, serving degraded product page, protecting checkout, preserving DB admin access.
Risk: Some payment authorizations may not have matching order records. Reconciliation owner assigned.
Next update in 10 minutes.
```

Customer/support framing:

```text
Some users may see delayed order confirmation.
Do not promise order success solely from payment authorization.
Support should use reconciliation dashboard once available.
```

---

## 10. Strict Self-Critique Before Final Answer

```text
Handoff compliance:          9.5/10
REST-file style match:       9.2/10
Depth:                       9.1/10
Production realism:          9.4/10
Internal mechanics:          9.0/10
Commands/tools:              9.3/10
Scenario complexity:         9.5/10
Numeric rigor:               9.4/10
Learner-gap targeting:       9.6/10
Lack of fluff:               9.4/10
```

### Correction Applied

The first draft was too compressed and failed the standard. The final draft adds:

```text
- wrong mental models with consequences
- bottleneck taxonomy
- mechanics for each scaling pattern
- exact commands
- realistic calculations
- failure-pattern diagnosis loops
- operational prerequisite checks
- cross-system capacity traps
- defense-layer ordering
- full incident expert answer
```

Remaining imperfection: a true 10/10 repo version should be split into a polished Markdown file and reviewed again against the existing repo’s exact voice. This chat version is suitable as a final draft for content, not yet as a copyedited repository commit.

---

## 11. Targeted Reading

```text
DDIA Chapter 3: Storage and Retrieval
Focus:
  - B-trees
  - LSM-trees
  - write amplification
  - read amplification
  - indexing tradeoffs

Extract:
  Why storage engine internals determine scaling behavior.
```

```text
DDIA Chapter 5: Replication
Focus:
  - leader-follower replication
  - replication lag
  - read-your-writes
  - monotonic reads
  - failover

Extract:
  Why replicas are consistency tradeoffs, not free capacity.
```

```text
DDIA Chapter 6: Partitioning
Focus:
  - key range partitioning
  - hash partitioning
  - skewed workloads
  - secondary indexes
  - rebalancing

Extract:
  Why shard key choice is a permanent architecture decision.
```

```text
PostgreSQL docs to read:
  - EXPLAIN
  - Runtime statistics views
  - pg_stat_statements
  - Autovacuum
  - Partitioning
  - Streaming replication
```

```text
PgBouncer docs:
  - Pool modes
  - SHOW POOLS
  - transaction pooling limitations
```

---

## 12. Key Takeaways

1. **A scaling pattern is only correct if it matches the bottleneck; replicas, cache, pools, indexes, partitioning, and sharding solve different problems.**

2. **Read replicas reduce read pressure only when stale reads are acceptable, replica lag is bounded, and the primary can afford WAL generation and streaming overhead.**

3. **Connection pooling protects the database by limiting concurrency; it does not increase the amount of useful work the database can execute.**

4. **Sharding is a last-resort write/data-size scaling pattern that buys horizontal capacity at the cost of scatter-gather, rebalancing, cross-shard transactions, and operational complexity.**

5. **During incidents, never move load to another system before verifying that system’s capacity, correctness guarantees, and operational prerequisites.**

---

## 13. Retention Hooks

### 10 rapid-fire questions from this topic

1. Why does adding a read replica not increase write throughput?
2. What does PgBouncer `cl_waiting` mean?
3. Why can increasing app DB pool size make an outage worse?
4. What does `EXPLAIN (ANALYZE, BUFFERS)` prove that plain `EXPLAIN` does not?
5. What is the leftmost-prefix rule for composite indexes?
6. Why can cache TTL synchronization cause database overload?
7. What is the difference between partitioning and sharding?
8. Why is scatter-gather dangerous for p99 latency?
9. What is the dual-write problem?
10. Why is rebalancing dangerous during active overload?

### 5 cross-topic questions from prior weeks

1. How does replication lag relate to read-your-writes consistency?
2. How does consistent hashing help rebalancing but not solve hot keys?
3. Why does CAP/PACELC matter for multi-region database design?
4. How do cache invalidation races connect to CDC and outbox patterns?
5. How does consensus prevent split-brain during database failover?

### 3 traps you are likely to miss

1. **Cross-system capacity trap:**  
   Before redirecting DB reads to Redis/OpenSearch/replicas, verify those systems have headroom.

2. **Operational prerequisite trap:**  
   Before mitigation, verify admin DB access, reserved connections, safe commands, and stale connection cleanup.

3. **Metadata vs data operation trap:**  
   During incident, prefer metadata/control-plane changes when possible. Avoid heavy data movement, full reindexing, or rebalancing unless explicitly justified.

### Mini compound scenario preview

```text
A SaaS tenant generates 80% of traffic after a product launch.
PostgreSQL primary is saturated.
Redis hot key is overloaded.
Replica lag is 45 seconds.
OpenSearch is stale by 8 minutes.
Support asks whether to route tenant reads to the replica.

Correct answer will require:
  - identifying hot tenant vs hot key
  - checking Redis capacity before cache redirect
  - rejecting stale replica for correctness-sensitive reads
  - preserving admin connections
  - ordering defenses as primary/fallback/last resort
```

Do not answer these now unless explicitly testing retention.
