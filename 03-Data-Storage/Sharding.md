# Week 4, Topic 2: Sharding/Partitioning

---

## 1. Learning Objectives

```
After this topic, you will be able to:

1. Explain WHY partitioning exists (write scaling — the thing 
   replication CAN'T do) and how it complements replication
2. Design range-based vs hash-based partitioning schemes with 
   precise tradeoffs, knowing exactly when each breaks
3. Handle secondary indexes across partitions (local vs global)
   with exact query patterns and performance implications
4. Implement partition rebalancing strategies (fixed slots, 
   dynamic splitting, proportional) and predict their failure modes
5. Diagnose hot partitions vs hot keys, apply the correct fix 
   for each, and explain why consistent hashing alone can't 
   solve hot keys (connecting to Week 3 T3)
6. Design cross-partition transactions and understand why they're 
   expensive (foreshadowing consensus in Topic 3)
7. Map real systems (PostgreSQL, Cassandra, DynamoDB, Redis 
   Cluster, MongoDB, Elasticsearch) to their partitioning 
   strategies with exact mechanics
```

---

## 2. Core Teaching

### 2.1 — Why Partition?

Replication (Topic 1) gives you:
- ✓ High availability
- ✓ Read scalability
- ✗ **Write scalability** — every replica applies every write

When a single node can't handle all your data or all your write throughput, you must **split the dataset across multiple nodes**. Each piece is a **partition** (also called shard, region, vnode, tablet, or vBucket depending on the system).

```
╔═══════════════════════════════════════════════════════════════╗
║   REPLICATION vs PARTITIONING                                 ║
╟───────────────────────────────────────────────────────────────╢
║                                                               ║
║   REPLICATION: Same data on multiple nodes                    ║
║   → Copies everything everywhere                              ║
║   → Scales reads. Does NOT scale writes.                      ║
║                                                               ║
║   PARTITIONING: Different data on different nodes             ║
║   → Each node owns a SUBSET of the data                       ║
║   → Scales reads AND writes (each partition handles           ║
║     its own reads AND writes independently)                   ║
║                                                               ║
║   IN PRACTICE: You use BOTH.                                  ║
║                                                               ║
║   ╭─────────────────────────────────────────────────────────╮ ║
║   │  Partition A          Partition B          Partition C  │ ║
║   │  ╭────────╮          ╭────────╮          ╭────────╮     │ ║
║   │  │Leader A│          │Leader B│          │Leader C│     │ ║
╚═══════════════════════════════════════════════════════════════╝
│  │      │                   │                   │          │  │
│  │  ╔═══════════════════════════════════════════════════════════════╗
│  │  ║   │  │Replica │          │Replica │          │Replica │     │ ║
│  │  ║   │  │  A1    │          │  B1    │          │  C1    │     │ ║
│  │  ╚═══════════════════════════════════════════════════════════════╝
│  │      │                   │                   │          │  │
│  │  ╔═══════════════════════════════════════════════════════════════╗
│  │  ║   │  │Replica │          │Replica │          │Replica │     │ ║
│  │  ║   │  │  A2    │          │  B2    │          │  C2    │     │ ║
│  │  ╚═══════════════════════════════════════════════════════════════╝
│  │                                                         │  │
│  │  Each partition is REPLICATED for fault tolerance.      │  │
│  │  Each node may host partitions from DIFFERENT shards.   │  │
│  ╰─────────────────────────────────────────────────────────╯  │
│                                                               │
│  Example: Cassandra with RF=3                                 │
│  → Data partitioned by token (hash of partition key)          │
│  → Each partition replicated to 3 nodes (RF=3)                │
│  → 6 physical nodes may host hundreds of token ranges,        │
│    each range replicated 3 times                              │
│                                                               │
│  Example: Redis Cluster                                       │
│  → 16384 slots (partitions)                                   │
│  → Each slot assigned to one master                           │
│  → Each master has 1+ replicas                                │
│  → 6-node cluster = 3 masters + 3 replicas                    │
│    → Each master owns ~5,461 slots                            │
╰───────────────────────────────────────────────────────────────╯
```

### 2.2 — The Fundamental Question: Which Partition Gets Which Key?

Every partitioning scheme answers one question: **given a key, which node owns it?** There are two fundamental approaches.

---

### 2.3 — Strategy 1: Range Partitioning

```
╔══════════════════════════════════════════════════════════════╗
║   RANGE PARTITIONING                                         ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   Assign contiguous ranges of keys to each partition.        ║
║                                                              ║
║   Example: User IDs                                          ║
║   ╭────────────┬────────────┬────────────┬────────────╮      ║
║   │ Partition 1│ Partition 2│ Partition 3│ Partition 4│      ║
║   │ IDs 1-250K │ 250K-500K  │ 500K-750K  │ 750K-1M    │      ║
╚══════════════════════════════════════════════════════════════╝
│                                                               │
│  Example: Timestamps (time-series data)                       │
│  ╔══════════════════════════════════════════════════════════════╗
│  ║   │ Partition 1│ Partition 2│ Partition 3│ Partition 4│      ║
│  ║   │  January   │  February  │   March    │   April    │      ║
│  ╚══════════════════════════════════════════════════════════════╝
│                                                               │
│  PROS:                                                        │
│  ✓ RANGE QUERIES ARE EFFICIENT                                │
│    "Give me all orders from March 1-15" → hits ONE partition  │
│    No scatter-gather needed.                                  │
│  ✓ Keys within a range are SORTED within the partition        │
│    → Sequential scan, not random I/O                          │
│  ✓ Easy to understand and reason about                        │
│  ✓ Natural for time-series data                               │
│                                                               │
│  CONS:                                                        │
│  ✗ HOT PARTITIONS                                             │
│    Time-series: ALL current writes hit the "today" partition  │
│    Yesterday's partition is idle. Tomorrow's doesn't exist.   │
│    → Write throughput limited to ONE node's capacity          │
│    → You partitioned for write scaling but only ONE           │
│      partition receives writes. Defeats the purpose.          │
│                                                               │
│  ✗ UNEVEN DATA DISTRIBUTION                                  │
│    User IDs 1-250K may have 10x more data than 750K-1M        │
│    (early users have years of history, new users have none)  │
│                                                               │
│  ✗ BOUNDARY MANAGEMENT                                       │
│    Ranges must be chosen or adjusted as data grows.           │
│    Manual range assignment is error-prone.                    │
│                                                               │
│  REAL SYSTEMS USING RANGE PARTITIONING:                       │
│  → HBase: row key ranges, auto-splitting regions              │
│  → Google Bigtable: row key ranges, tablet splitting          │
│  → CockroachDB: range-based, auto-splitting at 512MB          │
│  → PostgreSQL: PARTITION BY RANGE                             │
│  → MongoDB: range-based sharding (sh.shardCollection with     │
│    ranged shard key)                                          │
╰───────────────────────────────────────────────────────────────╯
```

**The time-series hot partition problem visualized:**

```
  TIME-SERIES WRITES (e.g., IoT sensor data)
  
  Partition:  Jan    Feb    Mar    Apr (current)
  Write TPS:  0      0      0     45,000
              ▓      ▓      ▓     ████████████████████
              
  You have 4 partitions on 4 nodes but ALL writes 
  hit one node. You've gained nothing from partitioning.
  
  FIX 1: Compound partition key
  → Instead of partitioning by timestamp alone:
    partition_key = (sensor_id, month)
  → 1000 sensors × 1 month = 1000 partitions for April
  → Writes spread across all nodes
  → Range query for one sensor's March data still hits 
    one partition: (sensor_42, March)
  → Range query for ALL sensors in March → scatter-gather
    across 1000 partitions (tradeoff!)
  
  FIX 2: Hash-prefix + range
  → partition_key = hash(sensor_id) % N + timestamp
  → Spreads writes but loses pure range query efficiency
  
  This is exactly what Cassandra does:
  → PRIMARY KEY ((sensor_id), timestamp)
  → sensor_id is the PARTITION KEY (hashed, spreads data)
  → timestamp is the CLUSTERING KEY (sorted within partition)
  → "All readings for sensor_42 between March 1-15" = 
    single partition scan (efficient!)
  → "All readings across ALL sensors for March 1" = 
    full scatter-gather (expensive)
```

---

### 2.4 — Strategy 2: Hash Partitioning

```
╔═══════════════════════════════════════════════════════════════╗
║   HASH PARTITIONING                                           ║
╟───────────────────────────────────────────────────────────────╢
║                                                               ║
║   Apply a hash function to the key. Hash value determines     ║
║   the partition.                                              ║
║                                                               ║
║   partition = hash(key) mod N    ← NAIVE (don't do this)      ║
║   partition = hash(key) → ring   ← CONSISTENT HASHING         ║
║   partition = hash(key) → slot   ← FIXED SLOT (Redis Cluster) ║
║                                                               ║
║   Example: hash("user:42") = 0x7A3F → slot 8127 → Node 2      ║
║                                                               ║
║   ╭──────────┬──────────┬──────────┬──────────╮               ║
║   │Partition1│Partition2│Partition3│Partition4│               ║
║   │hash 0-   │hash 25%- │hash 50%- │hash 75%- │               ║
║   │  25%     │  50%     │  75%     │  100%    │               ║
║   │          │          │          │          │               ║
║   │ user:7   │ user:42  │ user:15  │ user:3   │               ║
║   │ user:91  │ user:88  │ user:23  │ user:56  │               ║
║   │ user:104 │ user:201 │ user:67  │ user:999 │               ║
╚═══════════════════════════════════════════════════════════════╝
│                                                               │
│  Keys are UNIFORMLY distributed across partitions.            │
│  Adjacent keys (user:41, user:42, user:43) land on            │
│  DIFFERENT partitions.                                        │
│                                                               │
│  PROS:                                                        │
│  ✓ UNIFORM DISTRIBUTION                                       │
│    Good hash function → even spread → no hot partitions       │
│    (assuming no hot KEYS — Week 3 T3 distinction)             │
│  ✓ No manual range boundary management                        │
│  ✓ Adding/removing nodes is predictable                       │
│    (with consistent hashing: ~K/N keys move)                  │
│                                                               │
│  CONS:                                                        │
│  ✗ RANGE QUERIES ARE DESTROYED                                │
│    "All orders from March 1-15" → keys are scattered          │
│    across ALL partitions → must query ALL partitions           │
│    → SCATTER-GATHER: send query to every partition,           │
│      merge results. O(N) network calls.                       │
│  ✗ Adjacent keys have no locality                             │
│    user:42's data and user:43's data are on different nodes   │
│  ✗ Hash function quality matters                              │
│    Bad hash → skewed distribution → hot partitions anyway     │
│                                                               │
│  REAL SYSTEMS USING HASH PARTITIONING:                        │
│  → Cassandra: Murmur3Partitioner (default)                    │
│  → DynamoDB: hash of partition key                            │
│  → Redis Cluster: CRC16(key) mod 16384                        │
│  → MongoDB: hashed shard key option                           │
│  → Memcached: client-side consistent hashing                  │
│  → Riak: consistent hashing ring                              │
╰───────────────────────────────────────────────────────────────╯
```

**The critical comparison:**

```
╭────────────────────┬──────────────────┬──────────────────────╮
│                    │  RANGE           │  HASH                │
├────────────────────┼──────────────────┼──────────────────────┤
│ Distribution       │ Uneven (depends  │ Uniform (if good     │
│                    │ on key patterns) │ hash function)       │
├────────────────────┼──────────────────┼──────────────────────┤
│ Range queries      │ EFFICIENT        │ SCATTER-GATHER       │
│ (WHERE x BETWEEN)  │ (single          │ (all partitions)     │
│                    │  partition)      │                      │
├────────────────────┼──────────────────┼──────────────────────┤
│ Point queries      │ Efficient        │ Efficient            │
│ (WHERE x = ?)      │ (log lookup)     │ (hash + lookup)      │
├────────────────────┼──────────────────┼──────────────────────┤
│ Hot partition risk │ HIGH             │ LOW (but hot KEY     │
│                    │ (time-series!)   │ still possible)      │
├────────────────────┼──────────────────┼──────────────────────┤
│ Rebalancing        │ Split/merge      │ Consistent hashing   │
│                    │ ranges           │ or fixed slots       │
├────────────────────┼──────────────────┼──────────────────────┤
│ Best for           │ Ordered scans,   │ Point lookups,       │
│                    │ time-series,     │ uniform writes,      │
│                    │ analytics        │ key-value workloads  │
╰────────────────────┴──────────────────┴──────────────────────╯
```

---

### 2.5 — Compound Partitioning Keys (The Best of Both)

Cassandra's approach is the most elegant solution to the range-vs-hash tradeoff:

```
╭───────────────────────────────────────────────────────────────╮
│  CASSANDRA COMPOUND KEY MODEL                                 │
│                                                               │
│  PRIMARY KEY ((partition_key), clustering_key1, clustering_key2)
│               ^^^^^^^^^^^^^^^^  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
│               HASHED →           SORTED WITHIN PARTITION      │
│               determines node    determines order on disk     │
│                                                               │
│  Example: Sensor readings                                     │
│  CREATE TABLE readings (                                      │
│    sensor_id  text,                                           │
│    day        date,                                           │
│    timestamp  timestamp,                                      │
│    value      double,                                         │
│    PRIMARY KEY ((sensor_id, day), timestamp)                  │
│  );                                                           │
│                                                               │
│  → (sensor_id, day) is the PARTITION KEY                      │
│    → hash(sensor_id + day) determines which node              │
│    → Each sensor-day combination is a separate partition      │
│    → Writes for 1000 sensors spread across all nodes          │
│                                                               │
│  → timestamp is the CLUSTERING KEY                            │
│    → SORTED within the partition                              │
│    → Range scan within a single sensor-day is efficient       │
│                                                               │
│  QUERY PATTERNS:                                              │
│                                                               │
│  ✓ EFFICIENT (single partition):                              │
│  SELECT * FROM readings                                       │
│  WHERE sensor_id = 'sensor_42'                                │
│    AND day = '2024-03-15'                                     │
│    AND timestamp > '2024-03-15 08:00:00'                      │
│    AND timestamp < '2024-03-15 17:00:00';                     │
│  → hash('sensor_42' + '2024-03-15') → one node                │
│  → Sequential scan of sorted timestamps within that partition │
│                                                               │
│  ✗ EXPENSIVE (scatter-gather):                                │
│  SELECT * FROM readings                                       │
│  WHERE day = '2024-03-15';                                    │
│  → Must check ALL partitions (every sensor on that day)       │
│  → Full cluster scan. In Cassandra: requires ALLOW FILTERING  │
│    or a secondary index (both bad at scale)                   │
│                                                               │
│  ✗ IMPOSSIBLE without ALLOW FILTERING:                       │
│  SELECT * FROM readings                                       │
│  WHERE timestamp > '2024-03-15 08:00:00';                     │
│  → timestamp is clustering key — can't query without          │
│    specifying partition key first                             │
│  → Cassandra enforces: you MUST provide partition key         │
│    in every query (no full-table scans by default)            │
│                                                               │
│  THIS IS THE FUNDAMENTAL DESIGN CONSTRAINT:                   │
│  Your partition key determines your access patterns.          │
│  Choose the wrong partition key → either hot partitions       │
│  OR scatter-gather on your most common query. There is        │
│  no fix after the fact (requires data migration).             │
╰───────────────────────────────────────────────────────────────╯
```

---

### 2.6 — Secondary Indexes Across Partitions

What happens when you need to query by something other than the partition key? This is the secondary index problem, and it has two solutions, each with painful tradeoffs.

```
╔══════════════════════════════════════════════════════════════╗
║   THE PROBLEM                                                ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   Table: orders                                              ║
║   Partition key: order_id (hashed)                           ║
║                                                              ║
║   Query: "Find all orders for customer_id = 42"              ║
║                                                              ║
║   customer_id is NOT the partition key. The orders for       ║
║   customer 42 are SCATTERED across all partitions            ║
║   (because order_id is hashed, not customer_id).             ║
║                                                              ║
║   You need a SECONDARY INDEX on customer_id.                 ║
║   Two approaches:                                            ║
╚══════════════════════════════════════════════════════════════╝
```

#### Approach 1: Local Secondary Index (document-partitioned)

```
╭───────────────────────────────────────────────────────────────╮
│  LOCAL SECONDARY INDEX                                        │
│                                                               │
│  Each partition maintains its OWN index of the data it holds. │
│                                                               │
│  Partition 0              Partition 1              Partition 2│
│  ╭──────────────╮        ╭──────────────╮        ╭──────────╮ │
│  │ Orders:      │        │ Orders:      │        │ Orders:  │ │
│  │  id:1 c:42   │        │  id:4 c:42   │        │ id:7 c:99│ |
│  │  id:2 c:99   │        │  id:5 c:17   │        │ id:8 c:42│ |
│  │  id:3 c:17   │        │  id:6 c:42   │        │ id:9 c:17│ |
│  │              │        │              │        │          │ │
│  │ Local Index: │        │ Local Index: │        │ Local Idx│ │
│  │  c:17 → [3]  │        │  c:17 → [5]  │        │  c:17→[9]│ │
│  │  c:42 → [1]  │        │  c:42 → [4,6]│        │  c:42→[8]│ │
│  │  c:99 → [2]  │        │              │        │  c:99→[7]│ │
│  ╰──────────────╯        ╰──────────────╯        ╰──────────╯ │
│                                                               │
│  WRITE: Fast. Update local index on same partition.           │
│         index_update = same_node_operation (microseconds)     │
│                                                               │
│  READ by secondary key (customer_id=42):                      │
│  → Must query ALL partitions (scatter-gather)                 │
│  → "Where is customer 42's data?" → EVERYWHERE, maybe.        │
│  → Send query to partition 0, 1, 2 → merge results            │
│  → Latency = slowest partition response (tail latency)        │
│                                                               │
│  This is called SCATTER-GATHER and it's expensive:            │
│  → 100 partitions = 100 network calls for one query           │
│  → p99 latency dominated by slowest partition                 │
│  → One slow partition (GC pause, disk I/O) slows the          │
│    entire query                                               │
│                                                               │
│  USED BY: Cassandra (secondary indexes), MongoDB,             │
│           Elasticsearch (by default), DynamoDB (LSI)          │
│                                                               │
│  BEST WHEN: Writes are frequent, secondary key reads          │
│  are infrequent or can tolerate higher latency                │
╰───────────────────────────────────────────────────────────────╯
```

#### Approach 2: Global Secondary Index (term-partitioned)

```
╔══════════════════════════════════════════════════════════════╗
║   GLOBAL SECONDARY INDEX                                     ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   The index itself is PARTITIONED — but by the indexed term, ║
║   not by the same key as the data.                           ║
║                                                              ║
║   Data Partitions (by order_id):                             ║
║   ╭──────────────╮  ╭──────────────╮  ╭──────────────╮       ║
║   │ P0: orders   │  │ P1: orders   │  │ P2: orders   │       ║
║   │  id:1 c:42   │  │  id:4 c:42   │  │  id:7 c:99   │       ║
║   │  id:2 c:99   │  │  id:5 c:17   │  │  id:8 c:42   │       ║
║   │  id:3 c:17   │  │  id:6 c:42   │  │  id:9 c:17   │       ║
╚══════════════════════════════════════════════════════════════╝
│                                                               │
│  Global Index Partitions (by customer_id range):              │
│  ╔══════════════════════════════════════════════════════════════╗
│  ║   │ Index P-A (c:1-50)  │  │ Index P-B (c:51-100)│           ║
│  ║   │  c:17 → [3,5,9]     │  │  c:99 → [2,7]       │           ║
│  ║   │  c:42 → [1,4,6,8]   │  │                     │           ║
│  ╚══════════════════════════════════════════════════════════════╝
│                                                               │
│  READ by secondary key (customer_id=42):                      │
│  → customer_id=42 falls in index partition A                  │
│  → Query ONE index partition → get [1,4,6,8]                  │
│  → Then fetch orders 1,4,6,8 from data partitions             │
│  → TWO phases, but index lookup hits ONE partition, not all   │
│                                                               │
│  WRITE:                                                       │
│  → Insert order id:10, c:42 into data partition P1            │
│  → ALSO update global index partition A to add id:10 to c:42  │
│  → This is a CROSS-PARTITION WRITE (two different nodes)      │
│  → Either: synchronous (slow, consistent) or                  │
│    asynchronous (fast, index temporarily stale)               │
│                                                               │
│  USED BY: DynamoDB (GSI — asynchronously updated),            │
│           CockroachDB, Google Spanner                         │
│                                                               │
│  DynamoDB GSI detail:                                         │
│  → GSI is eventually consistent (async replication)           │
│  → Reads from GSI may not reflect recent writes               │
│  → GSI has its own provisioned throughput (separate from      │
│    base table) — if GSI throttles, base table writes          │
│    can ALSO throttle (backpressure)                           │
│                                                               │
│  BEST WHEN: Secondary key reads are frequent and need to      │
│  be fast. Willing to pay slower/more complex writes.          │
╰───────────────────────────────────────────────────────────────╯
```

**The comparison:**

```
╭─────────────────────┬──────────────────┬──────────────────────╮
│                     │  LOCAL (document)│  GLOBAL (term)       │ 
├─────────────────────┼──────────────────┼──────────────────────┤
│ Write speed         │ FAST (local)     │ SLOW (cross-node)    │
├─────────────────────┼──────────────────┼──────────────────────┤
│ Write consistency   │ Immediate        │ Async → stale index  │
│                     │                  │ Sync → slower writes │
├─────────────────────┼──────────────────┼──────────────────────┤
│ Read by sec. key    │ SCATTER-GATHER   │ SINGLE partition     │
│                     │ (all partitions) │ (then data fetch)    │
├─────────────────────┼──────────────────┼──────────────────────┤
│ Read latency        │ High (tail of    │ Lower (1 index +     │
│                     │ N partitions)    │ K data partitions)   │
├─────────────────────┼──────────────────┼──────────────────────┤
│ Index maintenance   │ Simple           │ Complex (distributed │
│                     │                  │ transaction or async)│
├─────────────────────┼──────────────────┼──────────────────────┤
│ Staleness risk      │ None             │ Yes (if async GSI)   │
╰─────────────────────┴──────────────────┴──────────────────────╯

DECISION FRAMEWORK:
→ Write-heavy, occasional secondary reads → LOCAL
→ Read-heavy on secondary key → GLOBAL
→ Consistency required on secondary reads → GLOBAL + sync 
  (expensive) or LOCAL + scatter-gather (slow)
→ Neither is free. This is a fundamental tradeoff.
```

---

### 2.7 — Rebalancing Partitions

Data grows. Nodes fail. You add capacity. Partitions must move between nodes. This is rebalancing, and getting it wrong causes outages.

**Strategy 1: hash-mod-N (DON'T DO THIS)**

```
partition = hash(key) mod N

  N=3:  hash("user:42") mod 3 = node 1
  N=4:  hash("user:42") mod 4 = node 2     ← MOVED
  
  Adding 1 node to 3 changes ~75% of key assignments.
  Adding 1 node to 100 changes ~99%.
  
  This is the Week 3 Topic 3 lesson:
  MASSIVE data migration on every topology change.
  Cache stampede. Service disruption. DON'T.
```

**Strategy 2: Fixed Number of Slots (Redis Cluster, Riak, early Cassandra)**

```
╔════════════════════════════════════════════════════════════════╗
║   FIXED SLOT ASSIGNMENT                                        ║
╟────────────────────────────────────────────────────────────────╢
║                                                                ║
║   Create MANY more partitions than nodes at the start.         ║
║   Assign multiple partitions to each node.                     ║
║   When nodes change, MOVE WHOLE PARTITIONS, don't rehash.      ║
║                                                                ║
║   Redis Cluster: 16384 fixed slots                             ║
║                                                                ║
║   3 nodes:                                                     ║
║   Node A: slots 0-5460        (5,461 slots)                    ║
║   Node B: slots 5461-10922    (5,462 slots)                    ║
║   Node C: slots 10923-16383   (5,461 slots)                    ║
║                                                                ║
║   Add Node D:                                                  ║
║   Node A: slots 0-4095        (4,096 slots) → gave 1365 to D   ║
║   Node B: slots 5461-9556     (4,096 slots) → gave 1366 to D   ║
║   Node C: slots 10923-15017   (4,095 slots) → gave 1366 to D   ║
║   Node D: slots 4096-5460,    (4,097 slots) ← received from    ║
║           9557-10922,                          A, B, and C     ║
║           15018-16383                                          ║
║                                                                ║
║   WHAT MOVED: ~25% of slots (one node's worth)                 ║
║   WHAT DIDN'T MOVE: 75% of data stays on same node             ║
║                                                                ║
║   TRADEOFF: Number of slots is FIXED at cluster creation.      ║
║   → Too few slots: can't distribute evenly across many nodes   ║
║     (16384 slots / 1000 nodes = 16 slots each — too coarse)    ║
║   → Too many slots: metadata overhead, gossip message size     ║
║     (Redis chose 16384: 16KB bitmap fits in one gossip packet) ║
║   → Must estimate maximum cluster size at creation time        ║
║                                                                ║
║   Redis Cluster commands:                                      ║
║   redis-cli --cluster reshard <host>:<port>                    ║
║   redis-cli --cluster rebalance <host>:<port>                  ║
║   redis-cli CLUSTER SETSLOT <slot> IMPORTING <node-id>         ║
║   redis-cli CLUSTER SETSLOT <slot> MIGRATING <node-id>         ║
║   redis-cli CLUSTER SETSLOT <slot> NODE <node-id>              ║
╚════════════════════════════════════════════════════════════════╝
```

**Strategy 3: Dynamic Splitting (DynamoDB, HBase, CockroachDB)**

```
╔══════════════════════════════════════════════════════════════╗
║   DYNAMIC PARTITION SPLITTING                                ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   Start with ONE partition. Split when it gets too big       ║
║   or too hot. Merge when it gets too small.                  ║
║                                                              ║
║   DynamoDB Adaptive Capacity:                                ║
║                                                              ║
║   Initial: 1 partition, 3000 RCU, 1000 WCU capacity          ║
║                                                              ║
║   Data grows past 10GB:                                      ║
║   ╭────────────────────╮        ╭──────────╮ ╭──────────╮    ║
║   │ Partition 1 (12GB) │  ──▶   │ P1a (6GB)│ │ P1b (6GB)│    ║
║   │ Range: A-Z         │  split │ Range A-M│ │ Range N-Z│    ║
║   │ 1000 WCU           │        │ 500 WCU  │ │ 500 WCU  │    ║
╚══════════════════════════════════════════════════════════════╝
│                                                               │
│  Throughput exceeds partition capacity:                       │
│  → DynamoDB detects hot partition                             │
│  → Splits and redistributes throughput                        │
│  → "Adaptive capacity" borrows unused throughput              │
│    from cold partitions to give to hot ones                   │
│                                                               │
│  HBase: Region splitting                                      │
│  → Default split size: 10GB per region                        │
│  → RegionServer splits automatically                          │
│  → HBase Master assigns new region to least-loaded server     │
│                                                               │
│  CockroachDB: Range splitting                                 │
│  → Default split size: 512MB per range                        │
│  → Automatic splitting and rebalancing                        │
│  → Leaseholder (leader) moves to balance load                 │
│                                                               │
│  PROS:                                                        │
│  ✓ No pre-sizing. Grows with your data.                       │
│  ✓ Hot partitions split automatically.                        │
│  ✓ Adapts to changing access patterns.                        │
│                                                               │
│  CONS:                                                        │
│  ✗ Split is a brief pause in writes to that range             │
│  ✗ Cascade risk: rapid splits under sudden load               │
│    (many splits → many region moves → metadata churn)         │
│  ✗ Pre-splitting recommended for known high-write workloads   │
│    (HBase: RegionSplitter, DynamoDB: on-demand mode)          │
╰───────────────────────────────────────────────────────────────╯
```

**Strategy 4: Proportional to Node Count (Cassandra vnodes)**

```
╔══════════════════════════════════════════════════════════════╗
║   VNODES (Virtual Nodes)                                     ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   From Week 3 Topic 3 — now in the rebalancing context:      ║
║                                                              ║
║   Each node owns V virtual positions on the hash ring.       ║
║   Default: num_tokens = 256 per node in Cassandra.           ║
║                                                              ║
║   3 nodes × 256 vnodes = 768 token ranges                    ║
║   Add 4th node: new node takes ~256/1024 ≈ 25% of ranges     ║
║   from existing nodes (roughly equal from each).             ║
║                                                              ║
║   Rebalancing is AUTOMATIC:                                  ║
║   → New node announces itself via gossip                     ║
║   → Existing nodes stream appropriate token ranges to it     ║
║   → nodetool status shows JOINING → NORMAL                   ║
║                                                              ║
║   PROS:                                                      ║
║   ✓ Adding nodes is (mostly) automatic                       ║
║   ✓ Data spread improves with more vnodes                    ║
║   ✓ Heterogeneous hardware: more vnodes on bigger nodes      ║
║                                                              ║
║   CONS:                                                      ║
║   ✗ Repair is expensive (must repair each vnode range)       ║
║   ✗ Streaming during bootstrap can overload existing nodes   ║
║   ✗ Cassandra 4.0 moved toward fewer, larger tokens          ║
║     (num_tokens = 16) to reduce overhead                     ║
║   ✗ Token assignment can still be uneven                     ║
║     (Cassandra 4.0: new token allocation algorithm)          ║
╚══════════════════════════════════════════════════════════════╝
```

**Rebalancing comparison:**

```
╭──────────────────┬────────────┬────────────┬──────────────┬──────────╮
│                  │ hash mod N │ Fixed slot │ Dynamic split│ Vnodes   │
├──────────────────┼────────────┼────────────┼──────────────┼──────────┤
│ Data moved on    │ ~99%       │ ~1/N       │ ~1/N         │ ~1/N     │
│ add node         │            │            │              │          │
├──────────────────┼────────────┼────────────┼──────────────┼──────────┤
│ Automatic?       │ N/A        │ Manual     │ Automatic    │ Automatic│
│                  │            │ (Redis)    │              │          │
├──────────────────┼────────────┼────────────┼──────────────┼──────────┤
│ Pre-sizing       │ No         │ Yes (slot  │ No           │ No       │
│ required?        │            │ count)     │              │          │
├──────────────────┼────────────┼────────────┼──────────────┼──────────┤
│ Hot partition    │ No         │ Manual     │ Auto-split   │ No       │
│ auto-fix?        │            │ reshard    │              │          │
├──────────────────┼────────────┼────────────┼──────────────┼──────────┤
│ Used by          │ Memcached  │ Redis      │ DynamoDB,    │ Cassandra│
│                  │ (legacy)   │ Cluster    │ HBase,       │ Riak     │
│                  │            │            │ CockroachDB  │          │
╰──────────────────┴────────────┴────────────┴──────────────┴──────────╯
```

---

### 2.8 — Hot Partitions vs Hot Keys (Reinforcing Week 3 T3)

This distinction keeps appearing, so let's formalize it:

```
╔══════════════════════════════════════════════════════════════════╗
║   HOT PARTITION                     HOT KEY                      ║
║   ─────────────                     ───────                      ║
║   Many keys on one partition        ONE key gets extreme         ║
║   get disproportionate traffic      traffic                      ║
║                                                                  ║
║   CAUSE: Bad partition key choice   CAUSE: Application           ║
║   (time-series on timestamp,        pattern (celebrity post,     ║
║    skewed distribution)             flash sale item, config)     ║
║                                                                  ║
║   FIX: Choose better partition key  FIX: Can't fix with          ║
║   or re-partition. Consistent       partitioning alone.          ║
║   hashing helps distribute.         Must use:                    ║
║                                     → Local cache (app-level)    ║
║                                     → Key sharding (append       ║
║                                       random suffix to key)      ║
║                                     → Read replicas              ║
║                                     → Dedicated node             ║
║                                                                  ║
║   EXAMPLE: All January writes       EXAMPLE: Beyoncé's tweet     ║
║   to one partition                  gets 1M reads/sec            ║
║                                                                  ║
║   DETECTION:                        DETECTION:                   ║
║   → Per-partition throughput metrics│  → Per-key access tracking ║
║   → nodetool cfstats (Cassandra)   │  → Redis HOTKEYS flag       ║
║   → DynamoDB consumed capacity     │  → redis-cli --hotkeys      ║
║     per partition                  │  → DynamoDB Contributor     ║
║   → CloudWatch SuccessfulRequest   │    Insights                 ║
║     Count per partition            │                             ║
║                                                                  ║
║   FROM WEEK 3 T3 SESSION STORE SCENARIO:                         ║
║   "Consistent hashing distributes KEYS.                          ║
║    It cannot distribute a SINGLE KEY."                           ║
║   → workspace hot key at 820 reads/sec was a HOT KEY problem     ║
║   → No amount of resharding or rebalancing helps                 ║
║   → Solution was local cache or key sharding                     ║
╚══════════════════════════════════════════════════════════════════╝
```

---

### 2.9 — Cross-Partition Operations

When a single operation spans multiple partitions, things get expensive.

```
╭───────────────────────────────────────────────────────────────╮
│  CROSS-PARTITION QUERIES (scatter-gather)                     │
│                                                               │
│  SELECT * FROM orders WHERE status = 'pending'                │
│  AND created_at > '2024-03-01'                                │
│                                                               │
│  If partitioned by order_id (hash):                           │
│  → 'status' and 'created_at' are not partition keys           │
│  → Must query ALL partitions                                  │
│  → Coordinator sends query to N partitions                    │
│  → Waits for ALL responses                                    │
│  → Merges and returns                                         │
│                                                               │
│  Latency = max(partition_1_time, partition_2_time, ...,       │
│                partition_N_time)                              │
│  → Tail latency problem: one slow partition = slow query      │
│  → With 100 partitions, p99 of any single partition becomes   │
│    the EXPECTED latency of every scatter-gather query         │
│                                                               │
│  Jeff Dean's tail-at-scale math:                              │
│  → Single server p99 = 10ms                                   │
│  → 100-server scatter-gather p99 ≈ 10ms at p63 level          │
│    (because at least one of 100 will be slow)                 │
│  → Solution: hedged requests — send to 2 replicas of each     │
│    partition, take the faster response                        │
│                                                               │
├───────────────────────────────────────────────────────────────┤
│  CROSS-PARTITION TRANSACTIONS                                 │
│                                                               │
│  Transfer $100 from user A (partition 1) to user B            │
│  (partition 3). Must be ATOMIC — both succeed or both fail.   │
│                                                               │
│  This requires a DISTRIBUTED TRANSACTION:                     │
│  → Two-phase commit (2PC) or similar protocol                 │
│  → Coordinator asks all partitions to PREPARE                 │
│  → All respond "ready" → Coordinator says COMMIT              │
│  → Any responds "fail" → Coordinator says ABORT               │
│                                                               │
│  2PC is BLOCKING:                                             │
│  → If coordinator crashes after PREPARE but before            │
│    COMMIT/ABORT → all participants HOLD LOCKS and wait        │
│  → Participants cannot unilaterally decide                    │
│  → This can block indefinitely until coordinator recovers     │
│  → In production: 2PC is a performance and availability       │
│    killer. Used only when absolutely necessary.               │
│                                                               │
│  ALTERNATIVE: Saga pattern                                    │
│  → Each partition does its local transaction                  │
│  → If later partition fails → compensating transactions       │
│    undo earlier partitions' work                              │
│  → Eventually consistent, no distributed locks                │
│  → Much better availability, much harder to reason about      │
│  → (Full saga coverage in Week 6)                             │
│                                                               │
│  ALTERNATIVE: Avoid cross-partition transactions entirely     │
│  → Design partition key so related data is co-located         │
│  → All of user A's data on one partition                      │
│  → Transfer between A's accounts = single-partition TX        │
│  → Transfer between users = saga or 2PC                       │
│                                                               │
│  THIS IS WHY PARTITION KEY DESIGN IS THE MOST IMPORTANT       │
│  DECISION IN A DISTRIBUTED DATABASE.                          │
│  A bad key forces cross-partition operations on your          │
│  most common queries. A good key keeps common operations      │
│  within a single partition.                                   │
╰───────────────────────────────────────────────────────────────╯
```

---

### 2.10 — Real System Partitioning Summary

```
╭─────────────┬──────────────┬────────────────┬────────────────────────╮
│ System      │ Strategy     │ Rebalancing    │ Key Detail             │
├─────────────┼──────────────┼────────────────┼────────────────────────┤
│ PostgreSQL  │ Declarative  │ Manual         │ PARTITION BY RANGE/LIST│
│ (native)    │ range/list/  │ (CREATE new    │ /HASH. Application     │
│             │ hash         │ partitions,    │ manages partition      │
│             │              │ attach/detach) │ creation.              │
├─────────────┼──────────────┼────────────────┼────────────────────────┤
│ Citus (PG)  │ Hash         │ Rebalancer     │ Distributed PG. Hash   │
│             │              │ (auto)         │ on distribution column.│
│             │              │                │ Co-location for joins. │
├─────────────┼──────────────┼────────────────┼────────────────────────┤
│ Cassandra   │ Hash (Murmur3│ Vnodes (auto)  │ Partition key = hash.  │
│             │ on partition │                │ Clustering key = sort  │
│             │ key)         │                │ within partition.      │
├─────────────┼──────────────┼────────────────┼────────────────────────┤
│ DynamoDB    │ Hash         │ Dynamic split  │ Partition key hashed.  │
│             │              │ (auto)         │ Sort key for range.    │
│             │              │                │ Adaptive capacity.     │
├─────────────┼──────────────┼────────────────┼────────────────────────┤
│ Redis       │ Fixed slot   │ Manual reshard │ CRC16(key) mod 16384.  │
│ Cluster     │ (16384)      │                │ Hash tags for co-loc.  │
├─────────────┼──────────────┼────────────────┼────────────────────────┤
│ MongoDB     │ Range OR     │ Balancer (auto)│ Shard key immutable    │
│             │ hash         │                │ after collection       │
│             │              │                │ creation. Choose wisely│
├─────────────┼──────────────┼────────────────┼────────────────────────┤
│ HBase/      │ Range        │ Region split   │ Row key is everything. │
│ Bigtable    │              │ (auto)         │ Avoid sequential keys  │
│             │              │                │ (monotonic timestamp). │
├─────────────┼──────────────┼────────────────┼────────────────────────┤
│ CockroachDB │ Range        │ Auto-split +   │ Ranges split at 512MB. │
│             │              │ auto-rebalance │ Automatic. Distributed │
│             │              │                │ SQL on top.            │
├─────────────┼──────────────┼────────────────┼────────────────────────┤
│ Elastic-    │ Hash         │ Manual (reroute│ Index = logical group. │
│ search      │ (on _id or   │ API) or auto   │ Shard = physical       │
│             │  routing key)│ (shard alloc.) │ partition of index.    │
│             │              │                │ Cannot change shard    │
│             │              │                │ count after creation.  │
╰─────────────┴──────────────┴────────────────┴────────────────────────╯
```

---

## 3. Production Patterns & Failure Modes

```
╭───────────────────────────────────────────────────────────────╮
│  FAILURE MODE 1: CHOOSING THE WRONG PARTITION KEY             │
│                                                               │
│  The most expensive mistake in distributed databases.         │
│  Cannot be fixed without full data migration.                 │
│                                                               │
│  Example: E-commerce orders partitioned by customer_id        │
│  → Walmart's B2B account generates 40% of all orders          │
│  → One partition holds 40% of all data and traffic            │
│  → That node is 10x hotter than others                        │
│  → Solution: re-partition by order_id (uniform distribution)  │
│  → Cost: full data migration, application changes, downtime   │
│                                                               │
│  RULE: Partition key must have HIGH CARDINALITY and           │
│  UNIFORM DISTRIBUTION. Test with real data histograms         │
│  before deploying.                                            │
│                                                               │
├───────────────────────────────────────────────────────────────┤
│  FAILURE MODE 2: SCATTER-GATHER AMPLIFICATION                 │
│                                                               │
│  Common anti-pattern: "We'll just do scatter-gather."         │
│                                                               │
│  10 partitions: scatter-gather adds ~10ms overhead            │
│  100 partitions: scatter-gather adds ~50ms overhead           │
│  1000 partitions: scatter-gather becomes dominant cost        │
│                                                               │
│  And it gets worse under load:                                │
│  → Each scatter-gather holds connections to ALL partitions    │
│  → 100 concurrent scatter-gathers × 1000 partitions           │
│    = 100,000 concurrent connections across the cluster        │
│  → Connection exhaustion cascades                             │
│                                                               │
│  RULE: If your most common query requires scatter-gather,     │
│  your partition key is wrong. Redesign.                       │
│                                                               │
├───────────────────────────────────────────────────────────────┤
│  FAILURE MODE 3: REBALANCING UNDER LOAD (Week 3 T3 callback)  │
│                                                               │
│  Adding a node during peak traffic:                           │
│  → Data streams from existing nodes to new node               │
│  → Existing nodes: serving production queries AND streaming   │
│  → Disk I/O and network bandwidth compete                     │
│  → Production query latency increases                         │
│  → If latency exceeds health check → cascading failures       │
│                                                               │
│  RULE: Rebalance during low-traffic windows. If you must      │
│  rebalance during peak: throttle streaming rate.              │
│  Cassandra: -Dcassandra.compaction_throughput_mb_per_sec      │
│  Redis: redis-cli --cluster reshard --cluster-pipeline 1000   │
│                                                               │
├───────────────────────────────────────────────────────────────┤
│  FAILURE MODE 4: SHARD EXHAUSTION                             │
│                                                               │
│  Elasticsearch: you create an index with 5 shards.            │
│  Data grows. Each shard reaches 50GB (recommended max).       │
│  You cannot change the number of shards on an existing index. │
│  → Must create a new index with more shards                   │
│  → Reindex ALL data from old index to new                     │
│  → Switch alias from old to new                               │
│  → This can take hours for large indices                      │
│                                                               │
│  FIX: Time-based index pattern                                │
│  → logs-2024.03.15, logs-2024.03.16, ...                      │
│  → Each day's index has appropriate shard count               │
│  → Alias "logs-current" points to today's index               │
│  → Old indices can be force-merged, shrunk, or deleted        │
│  → ILM (Index Lifecycle Management) automates this            │
╰───────────────────────────────────────────────────────────────╯
```

---

## 4. Hands-On Exercise

```
╭───────────────────────────────────────────────────────────────╮
│  EXERCISE: Observe Partitioning Behavior                      │
│                                                               │
│  Option A: PostgreSQL Native Partitioning                     │
│                                                               │
│  CREATE TABLE orders (                                        │
│    id          bigserial,                                     │
│    customer_id int NOT NULL,                                  │
│    created_at  timestamp NOT NULL,                            │
│    amount      numeric(10,2),                                 │
│    status      text                                           │
│  ) PARTITION BY RANGE (created_at);                           │
│                                                               │
│  CREATE TABLE orders_2024_q1 PARTITION OF orders              │
│    FOR VALUES FROM ('2024-01-01') TO ('2024-04-01');          │
│  CREATE TABLE orders_2024_q2 PARTITION OF orders              │
│    FOR VALUES FROM ('2024-04-01') TO ('2024-07-01');          │
│                                                               │
│  -- Insert data across partitions:                            │
│  INSERT INTO orders (customer_id, created_at, amount, status) │
│  SELECT                                                       │
│    (random()*1000)::int,                                      │
│    timestamp '2024-01-01' + random()*interval '180 days',     │
│    (random()*500)::numeric(10,2),                             │
│    (ARRAY['pending','shipped','delivered'])[floor(random()*3+1)::int]
│  FROM generate_series(1, 1000000);                            │
│                                                               │
│  -- See partition pruning in action:                          │
│  EXPLAIN ANALYZE SELECT * FROM orders                         │
│  WHERE created_at BETWEEN '2024-02-01' AND '2024-02-28';      │
│  -- Should scan ONLY orders_2024_q1                           │
│                                                               │
│  EXPLAIN ANALYZE SELECT * FROM orders                         │
│  WHERE status = 'pending';                                    │
│  -- Scans ALL partitions (status is not partition key)        │
│                                                               │
│  Option B: Redis Cluster Slot Distribution                    │
│                                                               │
│  redis-cli -c -h <node> CLUSTER KEYSLOT "user:42"             │
│  redis-cli -c -h <node> CLUSTER KEYSLOT "user:43"             │
│  redis-cli -c -h <node> CLUSTER KEYSLOT "order:100"           │
│  -- See how different keys land on different slots            │
│                                                               │
│  redis-cli -c -h <node> CLUSTER KEYSLOT "{user:42}.cart"      │
│  redis-cli -c -h <node> CLUSTER KEYSLOT "{user:42}.profile"   │
│  -- Same slot! Hash tags force co-location.                   │
│  -- Enables multi-key operations on same partition.           │
╰───────────────────────────────────────────────────────────────╯
```

---

## 5. SRE Scenario

### Scenario: Social Media Analytics Platform — Partition Meltdown

```
SETUP:
━━━━━━
You run a social media analytics platform. Core system:

→ PostgreSQL (Citus — distributed) for user profiles and 
  relationships. Sharded by user_id (hash). 32 shards 
  across 8 worker nodes (4 shards per node).

→ Cassandra (12-node cluster, RF=3) for the activity feed.
  Table schema:
  CREATE TABLE feed_events (
    user_id     bigint,
    event_day   date,
    event_time  timestamp,
    event_type  text,
    payload     text,
    PRIMARY KEY ((user_id, event_day), event_time)
  ) WITH CLUSTERING ORDER BY (event_time DESC);

→ Elasticsearch (6-node cluster) for search.
  Index: "posts" — 12 primary shards, 1 replica each = 
  24 total shards. Created 18 months ago.
  Each primary shard is now 65GB (recommended max: 50GB).

→ Redis Cluster (6 masters, 6 replicas) for caching 
  trending topics and hot post metadata.

TRAFFIC PATTERNS:
  → 45M DAU, ~3,200 writes/sec to Cassandra
  → Search: ~8,000 queries/sec to Elasticsearch
  → Top 0.1% of users (celebrities) generate 35% of 
    feed read traffic
  → Trending topics change every ~15 minutes

THE INCIDENT (multi-system cascade):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
09:00 — A K-pop group (BTS) announces a comeback. 
        Their fan base (ARMY) generates a massive spike.
09:01 — Cassandra: user_id for @BTS_official's feed 
        partition receives 47,000 reads/sec (normal for 
        that partition: 200 reads/sec). The three 
        Cassandra nodes holding this partition's replicas 
        hit 94% CPU.
09:03 — Elasticsearch: search queries for "BTS comeback" 
        spike to 35,000 queries/sec. The "posts" index 
        shards are 65GB each — queries take 800ms+ 
        (normally 120ms). Three ES nodes holding the 
        hottest shards are GC-thrashing (heap pressure 
        from large shard segments).
09:05 — Redis Cluster: trending topic cache for "BTS" 
        becomes a hot key. The master node holding this 
        slot processes 120,000 reads/sec. Redis is 
        single-threaded — p99 latency spikes from 1ms 
        to 45ms for ALL keys on that node (not just BTS).
09:07 — Citus (PostgreSQL): analytics dashboard queries 
        for "top engaged users" trigger scatter-gather 
        across all 32 shards. Each query takes 2.3 seconds 
        (normally 400ms). Dashboard auto-refreshes every 
        10 seconds, stacking queries.
09:09 — The Cassandra nodes at 94% CPU start timing out 
        on gossip heartbeats. Other nodes mark them as 
        DOWN. Cassandra begins streaming data for those 
        token ranges to remaining nodes (hint: they're 
        NOT actually down — they're just slow).
09:11 — Elasticsearch circuit breaker trips on 2 nodes 
        (parent circuit breaker: heap > 95%). Those nodes 
        reject all queries. The remaining 4 ES nodes now 
        handle ALL search traffic, including the rejected 
        nodes' shards (replicas).
09:13 — Full degradation: Feed reads timing out. Search 
        returning errors. Trending topics stale. Dashboard 
        unresponsive. User complaints trending on Twitter 
        (ironic).
```

**Questions:**

**Q1:** You have FOUR different systems experiencing partition-related problems simultaneously. For each system (Cassandra, Elasticsearch, Redis, Citus), diagnose: is this a hot PARTITION problem or a hot KEY problem? What's the precise root cause, and what's the correct partitioning-level fix for each?

**Q2:** At 09:09, Cassandra marks the overloaded nodes as DOWN and begins streaming data. Explain why this makes the situation WORSE, not better. What Cassandra configuration would have prevented this specific amplification? Include exact config parameters.

**Q3:** The Elasticsearch shards are 65GB each (created 18 months ago with 12 shards). You can't change the shard count on an existing index. Design the immediate mitigation AND the long-term fix. For the long-term fix, include the exact index lifecycle strategy that prevents this from recurring.

**Q4:** Write your prioritized mitigation plan for the first 15 minutes. You must address all four systems. For each action, specify: what it fixes, what it doesn't fix, and what you need to VERIFY before executing it.

**Q5:** Design the post-mortem architecture that handles the next celebrity event without degradation. For each system, specify the partitioning strategy change and how it addresses the specific failure mode observed.

---

## 6. Targeted Reading

```
DDIA Chapter 6: Partitioning (pp 199-217)
  → pp 199-204: Partitioning of Key-Value Data
    (range vs hash — compare with what you just learned)
  → pp 204-207: Skewed Workloads and Relieving Hot Spots
    (hot partition vs hot key distinction)
  → pp 207-211: Partitioning and Secondary Indexes
    (local vs global — exact match to teaching above)
  → pp 211-216: Rebalancing Partitions
    (four strategies — compare with the four taught here)
  → pp 216-217: Request Routing
    (how does a client know which partition to query?)

DDIA Chapter 7: pp 220-230 (preview for Week 4 T3)
  → Distributed transactions and 2PC overview
```

---

## 7. Key Takeaways

```
1. Partitioning scales WRITES (and data size). Replication 
   scales reads. You almost always use BOTH together. Each 
   partition is replicated; each replica serves reads.

2. Range partitioning enables efficient range queries but 
   creates hot partitions (time-series = all writes to one 
   node). Hash partitioning gives uniform distribution but 
   destroys range queries. Compound keys (Cassandra, DynamoDB) 
   give you both: hash the partition key, sort the clustering key.

3. Secondary indexes across partitions have NO free option: 
   local
```
# Scenario: Social Media Analytics Platform — Partition Meltdown

---

## Q1: Hot Partition vs Hot Key — Each System

### Cassandra: HOT PARTITION

```
DIAGNOSIS: Hot PARTITION, not hot key.

The partition key is (user_id, event_day). 
@BTS_official's feed for today is a SINGLE PARTITION:
  (user_id=@BTS_official, event_day=2025-01-17)

This partition lives on exactly 3 replicas (RF=3).
ALL 47,000 reads/sec for "show me BTS's latest activity" 
hit the SAME three nodes, because every request resolves 
to the same partition.

WHY THIS ISN'T A HOT KEY:
  A hot key problem means one KEY within a well-distributed 
  system gets disproportionate traffic. Here, the partition 
  itself is the problem. The partition key design 
  GUARANTEES that all reads for one user's daily feed 
  land on the same nodes. For normal users (200 reads/sec), 
  this is fine. For a celebrity with 47,000 reads/sec, 
  the partition becomes a bottleneck.

  The clustering columns (event_time DESC) spread data 
  WITHIN the partition (multiple rows per partition), 
  but they don't spread READS across nodes. Every read 
  for BTS's feed today goes to the same 3 nodes 
  regardless of which event_time is requested.

PRECISE ROOT CAUSE:
  The compound partition key (user_id, event_day) creates 
  one partition per user per day. This is a good design 
  for MOST users — it keeps a user's daily feed co-located 
  for efficient range scans on event_time. But it creates 
  unbounded fan-in for celebrity users: ALL reads for 
  one celebrity's daily feed converge on 3 nodes.

  ╔══════════════════════════════════════════════════════════════╗
  ║   12-node cluster, RF=3                                      ║
  ╟──────────────────────────────────────────────────────────────╢
  ║                                                              ║
  ║   Token ring distribution:                                   ║
  ║   Nodes 4, 7, 11 own @BTS_official's token range             ║
  ║                                                              ║
  ║   47,000 reads/sec ──► Node 4  (94% CPU)                     ║
  ║   47,000 reads/sec ──► Node 7  (94% CPU)                     ║
  ║   47,000 reads/sec ──► Node 11 (94% CPU)                     ║
  ║                                                              ║
  ║   Nodes 1-3, 5-6, 8-10, 12: 8-15% CPU                        ║
  ║   (handling normal user traffic — perfectly fine)            ║
  ║                                                              ║
  ║   3 nodes at 94%, 9 nodes idle. The cluster has              ║
  ║   75% of its capacity sitting unused while 25%               ║
  ║   is melting.                                                ║
  ╚══════════════════════════════════════════════════════════════╝

PARTITIONING-LEVEL FIX:

  The fix is to SPLIT the hot partition across multiple 
  nodes while maintaining read efficiency.

  APPROACH: Add a synthetic shard bucket to the partition key.

  NEW SCHEMA:
  CREATE TABLE feed_events (
    user_id     bigint,
    event_day   date,
    shard_id    int,        -- NEW: 0 to N-1
    event_time  timestamp,
    event_type  text,
    payload     text,
    PRIMARY KEY ((user_id, event_day, shard_id), event_time)
  ) WITH CLUSTERING ORDER BY (event_time DESC);

  For normal users (shard_count = 1):
    shard_id = 0 always. Behavior identical to current 
    schema. One partition per user per day.

  For celebrity users (shard_count = 16):
    shard_id = hash(event_id) % 16
    Each write goes to one of 16 partitions.
    Each partition maps to different nodes on the token ring.
    47,000 reads/sec ÷ 16 shards = ~2,940 reads/sec per shard.
    Spread across many more than 3 nodes.

  READ PATH:
    # Normal user: single partition read (fast)
    SELECT * FROM feed_events 
    WHERE user_id = ? AND event_day = ? AND shard_id = 0
    ORDER BY event_time DESC LIMIT 20;

    # Celebrity user: scatter-gather across N shards
    # (parallel reads, merge results by event_time)
    futures = []
    for shard in range(user_shard_count(user_id)):
        futures.append(
            session.execute_async(
                "SELECT * FROM feed_events "
                "WHERE user_id = ? AND event_day = ? "
                "AND shard_id = ? "
                "ORDER BY event_time DESC LIMIT 20",
                (user_id, event_day, shard)
            )
        )
    results = merge_by_event_time(await_all(futures))
    return results[:20]

  HOW TO DETERMINE SHARD COUNT PER USER:
    # Metadata table:
    CREATE TABLE user_shard_config (
      user_id    bigint PRIMARY KEY,
      shard_count int    -- default 1, celebrities get 8-32
    );

    # Set based on follower count or read traffic:
    # < 100K followers: shard_count = 1
    # 100K - 1M: shard_count = 4
    # 1M - 10M: shard_count = 8
    # > 10M: shard_count = 16

  TRADEOFF:
    → Normal users: zero change (shard_count=1, same perf)
    → Celebrity reads: slightly more complex (scatter-gather)
      but each individual read is fast (small partition)
    → Celebrity writes: must compute shard_id (trivial hash)
    → Net effect: 47K reads/sec spread across 16 partitions 
      on ~12+ distinct nodes instead of 3 nodes
```

### Elasticsearch: HOT PARTITION (Oversized Shards)

```
DIAGNOSIS: Hot PARTITION caused by under-sharding 
(too few shards for the data volume), not hot key.

Elasticsearch search is SCATTER-GATHER: a query hits 
ALL primary shards (or their replicas), each shard 
executes the query locally, and results are merged.

The "BTS comeback" query hits all 12 primary shards. 
The problem isn't that one shard gets more queries — 
ALL shards get every query. The problem is that each 
shard is 65GB (30% over the recommended 50GB max), 
making each per-shard query slow:
  → Large Lucene segments require more heap for caching
  → Merge operations on large segments cause GC pressure
  → Query execution on 65GB of data per shard takes 
    800ms instead of 120ms

At 35,000 queries/sec, each query touching all 12 shards:
  → 420,000 shard-level operations per second
  → Each taking 800ms+ instead of 120ms
  → Nodes can't keep up → GC thrashing → circuit breaker

PRECISE ROOT CAUSE:
  The index was created 18 months ago with 12 shards. 
  Data grew continuously. Elasticsearch doesn't allow 
  changing shard count on an existing index. The shards 
  grew from ~10GB to 65GB with no intervention.

  12 primary shards × 65GB = 780GB total index size.
  At the recommended 50GB/shard: need 16 primary shards.
  At a more comfortable 30GB/shard: need 26 primary shards.

  The index was never re-sharded or rolled over to a 
  new index with more shards. 18 months of neglect.

  ╔══════════════════════════════════════════════════════════════╗
  ║   6 ES nodes, 12 primary shards + 12 replicas                ║
  ╟──────────────────────────────────────────────────────────────╢
  ║                                                              ║
  ║   Node 1: P0, P1, R6, R7        (~260GB)                     ║
  ║   Node 2: P2, P3, R8, R9        (~260GB)                     ║
  ║   Node 3: P4, P5, R10, R11      (~260GB)                     ║
  ║   Node 4: P6, P7, R0, R1        (~260GB)                     ║
  ║   Node 5: P8, P9, R2, R3        (~260GB)                     ║
  ║   Node 6: P10, P11, R4, R5      (~260GB)                     ║
  ║                                                              ║
  ║   Every query hits 12 shards (scatter-gather).               ║
  ║   With replicas: each node serves 4 shards.                  ║
  ║   At 35K queries/sec: ~23K shard ops/sec/node.               ║
  ║   At 65GB per shard: 800ms per op.                           ║
  ║   → Queues build → heap fills → GC thrashing.                ║
  ╚══════════════════════════════════════════════════════════════╝

PARTITIONING-LEVEL FIX:

  IMMEDIATE: Can't re-shard existing index. Detailed in Q3.
  
  LONG-TERM: Time-based index rollover with proper shard 
  sizing. Instead of one monolithic "posts" index, use 
  daily or weekly indices:

  posts-2025.01.17  (12 shards, small — today's data)
  posts-2025.01.16  (12 shards, slightly larger)
  posts-2025.01.w02 (weekly rollup for older data)
  posts-2024.12     (monthly rollup for old data)

  Use an index alias "posts" that points to all of them.
  Queries hit all backing indices, but each individual 
  shard is small (< 30GB).

  Combined with ILM (Index Lifecycle Management):
  → Hot phase: today's index, 24 shards on SSD nodes
  → Warm phase: last 7 days, merged to fewer shards
  → Cold phase: older than 30 days, force-merged, 
    on cheaper storage
  → Delete phase: older than 365 days, removed

  Detailed in Q3.
```

### Redis: HOT KEY

```
DIAGNOSIS: Hot KEY, not hot partition.

The trending topic "BTS" is a SINGLE KEY on a SINGLE 
Redis master. CRC16("trending:BTS") maps to one slot, 
which lives on one master node. All 120,000 reads/sec 
converge on that one node.

The slots on that Redis master are evenly distributed 
(~2730 slots). The PARTITION distribution is fine. But 
one KEY within one slot generates 120,000 reads/sec.

Redis is single-threaded. All operations on a node — 
including operations for OTHER keys on OTHER slots on 
the same master — must wait in the same event loop. 
120K reads/sec for one key monopolizes the CPU, causing 
p99 latency to spike for ALL keys on that node:
  → "trending:BTS": direct victim (hot key)
  → "trending:sports", "trending:politics": collateral 
    damage (same node, same event loop)
  → "session:user123": collateral damage if on same node
  → ALL keys on that master: 1ms → 45ms

PRECISE ROOT CAUSE:
  Trending topic data is stored as one key per topic.
  The application layer treats Redis as a simple cache: 
  read "trending:BTS", if miss → compute → write back.
  At 120K reads/sec, this is far beyond what a single 
  Redis node can handle for one key while maintaining 
  low latency for other keys.

PARTITIONING-LEVEL FIX:

  Hot keys CANNOT be fixed by repartitioning or resharding. 
  The key maps to one slot by definition. Moving the slot 
  to another node just moves the problem.

  FIX 1: Application-level local caching (IMMEDIATE)

    Trending topics change every ~15 minutes. There is 
    ZERO reason to hit Redis 120K times per second for 
    data that changes every 900 seconds.

    # Each application server caches trending topics 
    # in local memory with a 5-second TTL:
    
    local_cache = TTLCache(maxsize=1000, ttl=5)
    
    async def get_trending_topic(topic):
        cached = local_cache.get(f"trending:{topic}")
        if cached:
            return cached  # no Redis call
        result = await redis.get(f"trending:{topic}")
        local_cache[f"trending:{topic}"] = result
        return result

    With 50 app servers, each refreshing every 5 seconds:
    → 50 servers × 1 read per 5s = 10 reads/sec to Redis
    → Down from 120,000 reads/sec
    → 99.99% reduction in Redis load for this key

  FIX 2: Read from replicas for hot keys (COMPLEMENTARY)

    Redis Cluster replicas can serve reads if the client 
    sends READONLY:

    # For hot keys, direct reads to the replica instead 
    # of the master:
    redis_replica.execute_command("READONLY")
    result = redis_replica.get("trending:BTS")

    This spreads reads across master + replica (2 nodes 
    instead of 1). Combined with local caching, the 
    Redis load becomes negligible.

  FIX 3: Key sharding (if data is mutable/large)

    If trending topic data were large or frequently 
    updated (it's not — it changes every 15 min), 
    shard across multiple keys:

    trending:BTS:0, trending:BTS:1, ... trending:BTS:7
    
    Client picks a random shard to read from.
    Each shard lives on a different slot → different master.
    Spreads reads across 8 nodes.

    NOT NEEDED HERE because Fix 1 (local caching) reduces 
    Redis reads to ~10/sec. But this pattern is useful 
    for truly high-write hot keys.
```

### Citus (PostgreSQL): SCATTER-GATHER ANTI-PATTERN

```
DIAGNOSIS: Neither hot partition nor hot key. This is 
a QUERY-PARTITION MISMATCH — the query pattern doesn't 
align with the partition strategy.

The data is sharded by user_id (hash). This is correct 
for user-specific queries: "give me user X's profile" 
→ single shard, fast.

But the analytics dashboard queries for "top engaged 
users" across ALL users. This requires scanning every 
shard:

  SELECT user_id, engagement_score 
  FROM user_analytics 
  ORDER BY engagement_score DESC 
  LIMIT 100;

  Citus rewrites this as 32 parallel queries (one per 
  shard), each returning its local top 100, then merges 
  all 32 result sets on the coordinator to find the 
  global top 100.

  32 shards × 2.3 seconds per shard = serial: 73.6 seconds
  But Citus parallelizes: effective time ~2.3 seconds 
  (bounded by the slowest shard).

  At 2.3 seconds per query and dashboard refreshing every 
  10 seconds: queries STACK. The previous query hasn't 
  finished when the next refresh fires. Connection pool 
  fills with concurrent scatter-gather queries.

PRECISE ROOT CAUSE:
  1. The analytics query is a CROSS-SHARD AGGREGATE on 
     a table sharded by user_id. Every query touches 
     all 32 shards. This is O(shards) per query — 
     inherently expensive in a distributed database.

  2. The dashboard auto-refreshes every 10 seconds, 
     stacking queries faster than they complete.

  3. Each scatter-gather query holds 32 connections 
     (one per shard) for 2.3 seconds. Multiple concurrent 
     queries: 3 queries × 32 connections = 96 connections 
     held simultaneously on the coordinator.

PARTITIONING-LEVEL FIX:

  The partitioning strategy (hash by user_id) is CORRECT 
  for the primary workload (user-specific queries). Don't 
  change it. Fix the analytics query pattern instead.

  FIX 1: Materialized view / pre-computed aggregation

    # Pre-compute the "top engaged users" result:
    CREATE MATERIALIZED VIEW top_engaged_users AS
    SELECT user_id, engagement_score
    FROM user_analytics
    ORDER BY engagement_score DESC
    LIMIT 1000;

    # Refresh on a schedule (not on every dashboard load):
    # Cron job or pg_cron:
    SELECT cron.schedule(
      'refresh_top_engaged', 
      '*/5 * * * *',  -- every 5 minutes
      'REFRESH MATERIALIZED VIEW CONCURRENTLY top_engaged_users;'
    );

    Dashboard reads from the materialized view: 
    single-shard, single-node, sub-millisecond.
    The expensive scatter-gather runs once per 5 minutes 
    (background), not every 10 seconds.

  FIX 2: Dashboard rate limiting

    # Dashboard auto-refresh: 10s → 60s minimum
    # AND: if previous query is still running, 
    # don't start another one:

    async def get_top_engaged():
        if ongoing_query_lock.locked():
            return cached_result  # return stale result
        async with ongoing_query_lock:
            result = await db.fetch(
                "SELECT * FROM top_engaged_users"
            )
            cached_result = result
            return result

  FIX 3: Reference tables for analytics dimensions

    If the engagement score can be maintained incrementally 
    (incremented on each interaction), store it as a 
    Citus REFERENCE TABLE (replicated to all nodes):

    SELECT create_reference_table('user_engagement_scores');

    Reference tables are copied to every worker node.
    Queries against them don't require scatter-gather.
    But this only works for small tables (< millions of rows).
    For 45M users: too large for a reference table.
    Stick with Fix 1 (materialized view).
```

### Summary Table

```
╭──────────────┬──────────────┬───────────────────────────────╮
│ SYSTEM       │ PROBLEM TYPE │ FIX                           │
├──────────────┼──────────────┼───────────────────────────────┤
│ Cassandra    │ Hot PARTITION│ Synthetic shard_id in         │
│              │ (celebrity   │ partition key. Celebrity      │
│              │  feed)       │ feeds split across 16         │
│              │              │ partitions → 16 node sets.    │
├──────────────┼──────────────┼───────────────────────────────┤
│ Elasticsearch│ Hot PARTITION│ Time-based index rollover     │
│              │ (oversized   │ with ILM. Keep shards <30GB.  │
│              │  shards)     │ Re-index existing data.       │
├──────────────┼──────────────┼───────────────────────────────┤
│ Redis        │ Hot KEY      │ App-level local cache (5s     │
│              │ (trending    │ TTL). 120K reads/sec → 10.    │
│              │  topic)      │ Redis replica reads as backup.│
├──────────────┼──────────────┼───────────────────────────────┤
│ Citus        │ Query-       │ Materialized view for         │
│              │ partition    │ cross-shard aggregates.       │
│              │ mismatch     │ Refresh every 5 min, not      │
│              │ (scatter-    │ every 10 sec.                 │
│              │  gather)     │                               │
╰──────────────┴──────────────┴───────────────────────────────╯
```

---

## Q2: Cassandra False Down Detection — Why It Makes Things Worse

### What Happens at 09:09

```
CASSANDRA GOSSIP PROTOCOL:

  Every node sends gossip heartbeats to random peers 
  every second. Each heartbeat includes the node's 
  generation, heartbeat counter, and load information.

  If a node doesn't respond to gossip within 
  phi_convict_threshold (default: 8) on the phi 
  accrual failure detector, it's marked UNREACHABLE.

  At 09:09, nodes 4, 7, and 11 (holding BTS partitions) 
  are at 94% CPU. They're processing 47K reads/sec 
  each. Their gossip responses are DELAYED because:
  → CPU is saturated processing read requests
  → Gossip runs on the same thread pool (or competing 
    for CPU time)
  → Response time exceeds the phi threshold
  → Other nodes conclude: "nodes 4, 7, 11 are DOWN"

  BUT THEY'RE NOT DOWN. They're slow. The data is 
  intact. The nodes are processing requests (slowly). 
  They just can't respond to gossip fast enough.
```

### Why the Response Makes Things WORSE

```
WHAT CASSANDRA DOES WHEN NODES ARE MARKED DOWN:

  1. HINTS ACCUMULATION:
     → Coordinator nodes that receive writes for token 
       ranges owned by "down" nodes store HINTS locally.
     → "I'll deliver this write to node 4 when it comes 
       back up."
     → 3,200 writes/sec × 3 replicas × fraction destined 
       for these nodes = significant hint volume.
     → Hints consume disk and memory on coordinator nodes.

  2. READ ROUTING CHANGES:
     → Reads that would go to nodes 4, 7, 11 are now 
       routed to OTHER nodes that hold replica data 
       for those token ranges.
     → Those other nodes were at 8-15% CPU. Now they 
       absorb the 47K reads/sec that the "down" nodes 
       were handling.
     → But wait — with RF=3 and 3 nodes "down," for 
       some token ranges there may be NO available 
       replica → reads FAIL.

  3. THE CATASTROPHIC RESPONSE — DATA STREAMING:
     
     If Cassandra thinks the nodes are PERMANENTLY gone, 
     it may trigger REPAIR or REBUILD operations. More 
     commonly, the hint handoff and read-repair 
     mechanisms generate massive I/O:

     → Hinted handoff: when nodes 4, 7, 11 come "back" 
       (they were never actually gone), ALL accumulated 
       hints are streamed to them simultaneously.
     → Read repair: reads from other replicas detect 
       "inconsistencies" (the "down" nodes missed some 
       writes during the gossip-unreachable window).
       Read repair triggers writes to fix the "down" 
       nodes.
     → Both operations generate ENORMOUS additional I/O 
       on nodes that are ALREADY at 94% CPU.

  THE DEATH SPIRAL:

  ╔══════════════════════════════════════════════════════════════╗
  ║                                                              ║
  ║   Nodes 4,7,11 at 94% CPU (handling BTS reads)               ║
  ║        │                                                     ║
  ║        ▼                                                     ║
  ║   Gossip heartbeats delayed → marked DOWN                    ║
  ║        │                                                     ║
  ║        ├──► Reads rerouted to other nodes                    ║
  ║        │    → Other nodes now overloaded too                 ║
  ║        │    → More nodes slow on gossip                      ║
  ║        │    → More nodes marked DOWN                         ║
  ║        │    → CASCADING failure across cluster               ║
  ║        │                                                     ║
  ║        ├──► Hints accumulating on coordinators               ║
  ║        │    → Coordinator disk/memory pressure               ║
  ║        │                                                     ║
  ║        ╰──► When "recovered": hint handoff storm             ║
  ║             → Massive write I/O to already-hot               ║
  ║               nodes                                          ║
  ║             → CPU: 94% → 100%                                ║
  ║             → Now ACTUALLY unresponsive                      ║
  ║             → Marked DOWN again (correctly this              ║
  ║               time)                                          ║
  ║             → More data streaming...                         ║
  ║                                                              ║
  ║   FEEDBACK LOOP: slow → marked down → recovery               ║
  ║   I/O → slower → marked down again → more I/O                ║
  ╚══════════════════════════════════════════════════════════════╝
```

### Configuration to Prevent This

```
PARAMETER 1: phi_convict_threshold (cassandra.yaml)

  # Default: 8
  # Higher value = less sensitive to latency spikes, 
  # fewer false positives.
  
  phi_convict_threshold: 12
  
  # The phi accrual failure detector calculates the 
  # probability that a node has failed based on the 
  # inter-arrival time of heartbeats. A threshold of 
  # 8 means: "if the probability of failure exceeds 
  # e^(-8), mark as down." 
  # 
  # At 12: requires much stronger evidence of failure.
  # A node that's slow (94% CPU, delayed heartbeats) 
  # but still responding occasionally will NOT be 
  # marked down.
  #
  # Tradeoff: genuinely dead nodes take longer to 
  # detect (~30-60s instead of ~10-15s). Acceptable 
  # for preventing false downs.


PARAMETER 2: native_transport_max_threads (cassandra.yaml)

  # Default: 128
  # Controls the thread pool for client requests.
  # At 47K reads/sec, this pool is exhausted, causing 
  # queuing that delays gossip responses.
  
  native_transport_max_threads: 256
  
  # Doubles the request handling capacity.
  # But more importantly, separates gossip from client 
  # traffic (gossip uses a separate thread pool, but 
  # CPU contention still affects it).


PARAMETER 3: Separate gossip from read I/O 
  (JVM/OS-level)

  # Pin gossip threads to dedicated CPU cores using 
  # processor affinity. This ensures gossip can respond 
  # even when client request threads are saturated.
  
  # In cassandra-env.sh:
  # -Dcassandra.available_processors=<N> 
  # (limits Cassandra's view of available CPUs, leaving 
  # some for OS/gossip overhead)
  
  # Or: use cgroups to reserve 2 CPU cores for 
  # Cassandra internal operations (gossip, compaction, 
  # hint handoff) separate from the request pool.


PARAMETER 4: hinted_handoff_throttle_in_kb (cassandra.yaml)

  # Default: 1024 (1MB/s per node)
  # Controls how fast hints are replayed when a "down" 
  # node comes back.
  
  hinted_handoff_throttle_in_kb: 256
  
  # Reduce to 256KB/s: hints replay slowly, preventing 
  # the hint handoff storm from overwhelming already-
  # stressed nodes.
  #
  # Tradeoff: takes longer to fully synchronize data 
  # after a false-down event. Acceptable — consistency 
  # will be achieved via read-repair in the meantime.


PARAMETER 5: read_request_timeout_in_ms (cassandra.yaml)

  # Default: 5000 (5 seconds)
  # If a read takes longer than this, the coordinator 
  # times out and tries another replica.
  
  read_request_timeout_in_ms: 2000
  
  # Lower timeout: coordinator gives up on slow nodes 
  # faster and routes to a healthy replica.
  # This provides natural backpressure: overloaded nodes 
  # get fewer reads (coordinators stop waiting for them) 
  # → their CPU pressure decreases → they recover.
  #
  # Tradeoff: more timeout errors visible to clients 
  # during the spike. But the alternative (5-second 
  # timeout holding connections) is worse — it keeps 
  # connections tied up longer, amplifying pool pressure.


MOST CRITICAL SINGLE CHANGE: phi_convict_threshold: 12

  This one parameter would have prevented the entire 
  09:09 cascade. The nodes would have been recognized 
  as SLOW but not DOWN. No data streaming, no hint 
  storms, no cascading failure detection.

  The read latency would still be degraded (nodes at 
  94% CPU are slow), but the cluster would remain 
  STABLE — degraded performance, not a meltdown.
```

---

## Q3: Elasticsearch — Immediate Mitigation and Long-Term Fix

### Immediate Mitigation

```
YOU CANNOT re-shard an existing Elasticsearch index. 
The shard count is fixed at creation time. The 12 
primary shards at 65GB each are what you have.

IMMEDIATE ACTION 1: ADD NODES TO SPREAD SHARD LOAD [2-3 minutes]

  The cluster has 6 nodes, 24 total shards (12P + 12R).
  Each node holds 4 shards (~260GB per node).
  
  Add 2-4 more nodes to the cluster. Elasticsearch 
  automatically rebalances shards across the new nodes.

  # Add nodes to cluster (assuming cloud/k8s):
  kubectl scale statefulset elasticsearch --replicas=10
  
  # Or if manual: start new ES instances pointing to 
  # the same cluster.name.

  After rebalancing with 10 nodes:
  → 24 shards ÷ 10 nodes = 2-3 shards per node
  → Each node: ~130-195GB instead of ~260GB
  → Less heap pressure per node
  → Better GC behavior

  This doesn't fix the 65GB shard problem, but it 
  reduces per-node load enough to stop GC thrashing.

  VERIFY: 
  GET /_cluster/health
  # status: green (all shards allocated)
  GET /_nodes/stats/jvm
  # heap_used_percent < 75% on all nodes
  # gc.collectors.old.collection_count not climbing


IMMEDIATE ACTION 2: INCREASE REPLICA COUNT [3-5 minutes]

  Currently: 1 replica per shard (12P + 12R = 24 shards).
  With search being scatter-gather, more replicas means 
  more nodes can serve queries in parallel.

  PUT /posts/_settings
  {
    "number_of_replicas": 2
  }

  Now: 12P + 24R = 36 shards.
  With 10 nodes: 3-4 shards per node.
  
  Each search query can now hit ANY of 3 copies per 
  shard (1 primary + 2 replicas). The adaptive replica 
  selection algorithm routes to the least-loaded copy.
  
  This spreads the 35,000 queries/sec across more nodes.

  VERIFY: 
  GET /_cluster/health
  # active_shards: 36
  # relocating_shards: 0 (rebalancing complete)


IMMEDIATE ACTION 3: TRIP CIRCUIT BREAKERS GRACEFULLY [30 seconds]

  Two nodes already tripped circuit breakers (heap > 95%).
  They're rejecting queries. Force a recovery:

  # Clear field data cache (often the largest heap consumer):
  POST /posts/_cache/clear?fielddata=true
  
  # Reduce search queue size to prevent overwhelming 
  # recovering nodes:
  PUT /_cluster/settings
  {
    "transient": {
      "thread_pool.search.queue_size": 200
    }
  }
  # Default is 1000. Reducing to 200 causes faster 
  # rejection (429 errors) instead of heap-filling queues.
  
  # If nodes are still GC-thrashing, force a 
  # segment merge to reduce segment count (fewer 
  # segments = less heap for bookkeeping):
  POST /posts/_forcemerge?max_num_segments=5&only_expunge_deletes=true

  CAUTION: _forcemerge is I/O intensive. Only do this 
  if the nodes have stabilized enough to handle it.
  In the middle of an active incident: skip this, 
  rely on Actions 1 and 2 first.

  VERIFY:
  GET /_nodes/stats/breaker
  # parent.tripped: count should stop increasing
  # parent.estimated_size < parent.limit_size


IMMEDIATE ACTION 4: THROTTLE SEARCH TRAFFIC [30 seconds]

  While the cluster recovers, rate-limit search queries 
  at the application level:

  # Application-level rate limiter:
  search_semaphore = asyncio.Semaphore(500)
  # Max 500 concurrent ES searches (vs unbounded 35K/sec)
  
  async def search_posts(query):
      if not search_semaphore.acquire_nowait():
          return SearchResult(
              results=[],
              message="Search is experiencing high demand. "
                      "Results may be limited.",
              status="degraded"
          )
      try:
          return await es_client.search(index="posts", body=query)
      finally:
          search_semaphore.release()
  
  # Users get degraded search (partial results or 
  # "try again" message) instead of timeouts.
```

### Long-Term Fix: Index Lifecycle Management

```
LONG-TERM FIX: TIME-BASED INDICES WITH ILM

  Instead of one monolithic "posts" index, use 
  time-based indices behind an alias:

  INDEX NAMING: posts-YYYY.MM.DD (daily rollover)
  ALIAS: "posts" → points to all daily indices

  CREATION TEMPLATE:
  PUT /_index_template/posts_template
  {
    "index_patterns": ["posts-*"],
    "template": {
      "settings": {
        "number_of_shards": 6,
        "number_of_replicas": 1,
        "index.lifecycle.name": "posts_ilm_policy",
        "index.lifecycle.rollover_alias": "posts-write"
      }
    }
  }

  ILM POLICY:
  PUT /_ilm/policy/posts_ilm_policy
  {
    "policy": {
      "phases": {
        "hot": {
          "min_age": "0ms",
          "actions": {
            "rollover": {
              "max_primary_shard_size": "30GB",
              "max_age": "1d"
            },
            "set_priority": { "priority": 100 }
          }
        },
        "warm": {
          "min_age": "7d",
          "actions": {
            "shrink": {
              "number_of_shards": 3
            },
            "forcemerge": {
              "max_num_segments": 1
            },
            "allocate": {
              "require": { "data": "warm" }
            },
            "set_priority": { "priority": 50 }
          }
        },
        "cold": {
          "min_age": "30d",
          "actions": {
            "allocate": {
              "require": { "data": "cold" }
            },
            "set_priority": { "priority": 0 }
          }
        },
        "delete": {
          "min_age": "365d",
          "actions": {
            "delete": {}
          }
        }
      }
    }
  }

  HOW THIS PREVENTS THE PROBLEM:

  ╔══════════════════════════════════════════════════════════════╗
  ║                                                              ║
  ║   HOT PHASE (today + recent):                                ║
  ║   → New index created daily (or when any primary             ║
  ║     shard hits 30GB)                                         ║
  ║   → 6 primary shards per daily index                         ║
  ║   → At ~3,200 writes/sec, daily data volume ~10GB            ║
  ║   → Each shard: ~1.7GB. Well under 30GB limit.               ║
  ║   → Queries for recent data: fast (small shards)             ║
  ║                                                              ║
  ║   WARM PHASE (7-30 days old):                                ║
  ║   → Shrink from 6 shards to 3 (data is no longer             ║
  ║     being written to, safe to consolidate)                   ║
  ║   → Force-merge to 1 segment per shard (optimal              ║
  ║     for read performance, no merge overhead)                 ║
  ║   → Move to warm-tier nodes (cheaper, less I/O)              ║
  ║                                                              ║
  ║   COLD PHASE (30-365 days):                                  ║
  ║   → Move to cold-tier nodes (cheapest storage)               ║
  ║   → Rarely queried, acceptable latency                       ║
  ║                                                              ║
  ║   DELETE PHASE (>365 days):                                  ║
  ║   → Auto-delete. No manual intervention.                     ║
  ║                                                              ║
  ║   SHARD SIZE GUARANTEE:                                      ║
  ║   → The rollover condition "max_primary_shard_size:          ║
  ║     30GB" ensures NO shard EVER exceeds 30GB.                ║
  ║   → If traffic spikes cause faster data growth,              ║
  ║     rollover happens sooner (sub-daily).                     ║
  ║   → Self-regulating: more writes = more indices              ║
  ║     = smaller shards per index.                              ║
  ║                                                              ║
  ╚══════════════════════════════════════════════════════════════╝

  MIGRATION FROM CURRENT INDEX:

  # Step 1: Create the ILM policy and template (above)
  
  # Step 2: Reindex the old 780GB "posts" index into 
  # time-based indices:
  POST /_reindex
  {
    "source": {
      "index": "posts",
      "query": {
        "range": {
          "created_at": {
            "gte": "2025-01-01",
            "lt": "2025-01-18"
          }
        }
      }
    },
    "dest": {
      "index": "posts-2025.01.17",
      "pipeline": "add_routing"
    }
  }
  # Repeat for each day/week/month of historical data.
  # This is a BACKGROUND operation — run during off-peak.
  # Can take hours for 780GB. 

  # Step 3: Create the "posts" alias pointing to all 
  # new time-based indices:
  POST /_aliases
  {
    "actions": [
      { "remove": { "index": "posts", "alias": "*" }},
      { "add": { "index": "posts-*", "alias": "posts" }},
      { "add": { 
          "index": "posts-2025.01.17", 
          "alias": "posts-write",
          "is_write_index": true 
      }}
    ]
  }

  # Step 4: Verify queries work against alias.
  # Step 5: Delete old monolithic "posts" index.

  TIMELINE: 
  → ILM policy: deploy today (takes effect on new indices)
  → Reindex historical data: 1-2 weeks (background)
  → Delete old index: after verification
```

---

## Q4: Prioritized Mitigation Plan — First 15 Minutes

### Priority Assessment

```
╔══════════════════════════════════════════════════════════════╗
║   SEVERITY RANKING (by user impact and blast radius):        ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   1. CASSANDRA FALSE-DOWN CASCADE [09:09]                    ║
║      → Feed reads failing for ALL users (not just BTS)       ║
║      → Data streaming amplifying load on remaining nodes     ║
║      → Risk: entire Cassandra cluster becomes unavailable    ║
║      → BLAST RADIUS: TOTAL (all feed reads)                  ║
║                                                              ║
║   2. ELASTICSEARCH CIRCUIT BREAKER [09:11]                   ║
║      → Search returning errors                               ║
║      → 2 of 6 nodes rejecting all queries                    ║
║      → Remaining 4 nodes absorbing all traffic               ║
║      → BLAST RADIUS: ALL search users                        ║
║                                                              ║
║   3. REDIS HOT KEY [09:05]                                   ║
║      → Trending topics stale                                 ║
║      → ALL keys on hot node degraded (45ms p99)              ║
║      → BLAST RADIUS: all users on that Redis master          ║
║                                                              ║
║   4. CITUS SCATTER-GATHER [09:07]                            ║
║      → Dashboard unresponsive                                ║
║      → Internal tool, not user-facing                        ║
║      → BLAST RADIUS: analytics team only                     ║
║                                                              ║
║   CASSANDRA FIRST: it's cascading and getting worse.         ║
║   If the false-down detection spreads to more nodes,         ║
║   the entire feed system goes down.                          ║
╚══════════════════════════════════════════════════════════════╝
```

### Minute 0-3: Stop the Cassandra Cascade

```
ACTION 1: STOP CASSANDRA DATA STREAMING [0:00 — 30 seconds]

  The immediate danger: data streaming to/from "down" 
  nodes is amplifying load. Stop it.

  # On each Cassandra node that initiated streaming:
  nodetool stop -- all
  # Stops all streaming operations (repair, bootstrap, etc.)

  # Verify streaming stopped:
  nodetool netstats
  # Should show "Not sending" and "Not receiving"

  WHAT THIS FIXES: Stops the I/O amplification on 
  nodes 4, 7, 11 (already at 94% CPU, streaming makes 
  it worse) and on the nodes absorbing the streaming 
  data.

  WHAT THIS DOESN'T FIX: Nodes 4, 7, 11 are still at 
  94% CPU from BTS reads. They're still marked DOWN 
  in gossip. Reads are still being rerouted.

  VERIFY BEFORE EXECUTING: Check that the streaming 
  is actually the false-down recovery, not a legitimate 
  bootstrap of a new node:
  nodetool status
  # Look for UJ (Up Joining) vs DN (Down Normal)
  # If nodes 4,7,11 show DN: they're falsely marked down
  # Stopping streaming is correct.


ACTION 2: FORCE CASSANDRA TO RECOGNIZE NODES AS UP [0:30 — 1 minute]

  # On any live node, manually mark the "down" nodes 
  # as up by restarting gossip:
  
  # Option A: Restart gossip on the "down" nodes themselves
  nodetool disablegossip  # on nodes 4, 7, 11
  sleep 2
  nodetool enablegossip   # gossip restarts with fresh heartbeats
  
  # The phi accrual detector resets. Fresh heartbeats 
  # arrive at other nodes. If the nodes can respond to 
  # gossip (they can — they're slow, not dead), they'll 
  # be marked UP again within seconds.

  # Option B: If Option A doesn't work (nodes too 
  # overloaded to process nodetool):
  # On the OTHER nodes, temporarily increase the 
  # phi_convict_threshold:
  # (Requires cassandra.yaml change + restart — slower.
  #  Prefer Option A.)

  WHAT THIS FIXES: Stops the false-down detection → 
  stops read rerouting → stops hint accumulation → 
  stops the cascade amplification loop.

  VERIFY: 
  nodetool status
  # All 12 nodes showing UN (Up Normal)
  nodetool gossipinfo | grep STATUS
  # All nodes: STATUS:NORMAL


ACTION 3: REDUCE BTS READ LOAD ON CASSANDRA [1:30 — 2 minutes]

  The root cause: 47K reads/sec to one partition. 
  Even with nodes marked UP, they're still at 94% CPU.

  IMMEDIATE: Application-level caching for hot partitions.

  # BTS's feed data changes relatively slowly 
  # (they post maybe a few times per hour). 
  # Cache the feed in the application layer:
  
  # Feature flag or config:
  HOT_FEED_CACHE_ENABLED=true
  HOT_FEED_CACHE_TTL=10  # 10 seconds
  
  # Application logic:
  async def get_feed(user_id, event_day):
      cache_key = f"feed:{user_id}:{event_day}"
      
      # Check local in-memory cache first
      cached = local_cache.get(cache_key)
      if cached:
          return cached
      
      # Check Redis (distributed cache)
      cached = await redis.get(cache_key)
      if cached:
          local_cache.set(cache_key, cached, ttl=5)
          return cached
      
      # Cache miss: read from Cassandra
      result = await cassandra.execute(
          feed_query, (user_id, event_day)
      )
      await redis.set(cache_key, serialize(result), ex=10)
      local_cache.set(cache_key, result, ttl=5)
      return result

  With 50 app servers and 5s local cache TTL:
  → 50 servers × 1 read per 5s = 10 Cassandra reads/sec
  → Down from 47,000 reads/sec
  → Nodes 4, 7, 11 CPU: 94% → ~15% within seconds

  WHAT THIS FIXES: The root cause — hot partition load.
  
  WHAT THIS DOESN'T FIX: The structural vulnerability 
  (next celebrity event will cause the same problem). 
  Long-term fix = partition sharding (Q1).

  VERIFY:
  nodetool tpstats  # on nodes 4, 7, 11
  # ReadStage active threads dropping
  # Pending should be decreasing toward 0
  
  # CPU monitoring:
  # Nodes 4, 7, 11 should drop from 94% to <30% 
  # within 30 seconds of cache deployment
```

### Minute 3-7: Fix Elasticsearch

```
ACTION 4: CLEAR ES HEAP AND REDUCE QUEUE [3:00 — 1 minute]

  # Clear field data cache on all nodes:
  POST /posts/_cache/clear?fielddata=true

  # Reduce search queue to provide backpressure:
  PUT /_cluster/settings
  {
    "transient": {
      "thread_pool.search.queue_size": 200
    }
  }

  VERIFY BEFORE EXECUTING: Check which nodes tripped 
  circuit breakers:
  GET /_nodes/stats/breaker
  # Look for parent.tripped > 0

  WHAT THIS FIXES: Immediate heap pressure on the 2 
  tripped nodes. They may recover enough to start 
  serving queries again.

  WHAT THIS DOESN'T FIX: 65GB shards are still slow. 
  35K queries/sec is still too many for the cluster size.


ACTION 5: THROTTLE SEARCH AT APPLICATION LAYER [3:30 — 1 minute]

  Rate-limit concurrent ES queries:

  SEARCH_CONCURRENCY_LIMIT = 500
  # Deploy via feature flag or config push
  
  # Excess queries get graceful degradation:
  # "Search results may be limited during high traffic"

  WHAT THIS FIXES: Prevents ES from being overwhelmed 
  by unbounded query volume. Keeps heap stable.

  VERIFY:
  GET /_cluster/health
  # status should improve from red → yellow → green
  GET /_nodes/stats/jvm
  # heap_used_percent stabilizing below 80%


ACTION 6: ADD ES NODES IF AVAILABLE [5:00 — 2-5 minutes]

  # If cloud autoscaling is available:
  kubectl scale statefulset elasticsearch --replicas=10
  
  # Or manually launch 2-4 new ES instances.
  # Shard rebalancing begins automatically.
  
  # This takes a few minutes for shards to relocate.
  # Monitor:
  GET /_cluster/health
  # relocating_shards: should decrease toward 0
  
  # Don't wait for full rebalancing. The throttle 
  # (Action 5) keeps the cluster stable while 
  # rebalancing proceeds.
```

### Minute 7-10: Fix Redis and Citus

```
ACTION 7: LOCAL CACHE FOR REDIS HOT KEY [7:00 — 1 minute]

  Deploy application-level local caching for trending 
  topics (same solution as Q1):

  HOT_KEY_LOCAL_CACHE_ENABLED=true
  HOT_KEY_LOCAL_CACHE_TTL=5

  120K Redis reads/sec → ~10/sec.
  Redis master CPU drops. p99 latency for ALL keys 
  on that node recovers from 45ms → <2ms.

  VERIFY:
  redis-cli -h <hot-master> INFO stats | grep instantaneous_ops
  # Should drop dramatically
  redis-cli -h <hot-master> --latency-history -i 2
  # p99 should return to <2ms

  WHAT THIS FIXES: Hot key load + collateral damage 
  to all other keys on the same master.


ACTION 8: KILL STACKING DASHBOARD QUERIES [8:00 — 1 minute]

  # On Citus coordinator, find and kill the stacking 
  # scatter-gather queries:
  
  SELECT pg_terminate_backend(pid)
  FROM pg_stat_activity
  WHERE query LIKE '%top_engaged%'
    AND state = 'active'
    AND query_start < now() - interval '10 seconds';

  # Disable dashboard auto-refresh or increase interval:
  feature_flag.set("DASHBOARD_REFRESH_INTERVAL", 300)  # 5 minutes
  
  # Or: block the dashboard endpoint entirely during 
  # the incident:
  # nginx: return 503 for /api/analytics/top-engaged

  VERIFY:
  # Citus coordinator connection count drops
  SELECT count(*) FROM pg_stat_activity WHERE state = 'active';
  # Should decrease significantly

  WHAT THIS FIXES: Scatter-gather connection pressure.
  WHAT THIS DOESN'T FIX: Underlying need for 
  materialized view (post-mortem item).
```

### Minute 10-15: Verify and Monitor

```
ACTION 9: SYSTEMATIC VERIFICATION [10:00 — 5 minutes]

  CHECK CASSANDRA:
  nodetool status  # all nodes UN
  nodetool tpstats  # no pending reads stacking
  # Feed read latency: should be back to <50ms
  # CPU on nodes 4, 7, 11: should be <30%

  CHECK ELASTICSEARCH:
  GET /_cluster/health  # status: green or yellow
  GET /_nodes/stats/jvm  # heap < 80% on all nodes
  # Search latency: should be <500ms (still elevated 
  # due to 65GB shards, but functional)
  # Error rate: should be near 0%

  CHECK REDIS:
  redis-cli -h <each-master> INFO stats
  # No single master above 60% CPU
  # p99 < 5ms across all masters

  CHECK CITUS:
  # Dashboard queries not stacking
  # Coordinator connections < 50% of max
  # User-facing queries (profile lookups) unaffected

  IF ANY CHECK FAILS: investigate that system 
  specifically before declaring stable.

  COMMUNICATE: Update stakeholders at 10-minute mark:
  "Systems stabilizing. Feed reads recovered. Search 
  degraded but functional (rate-limited). Trending 
  topics recovering. Dashboard temporarily disabled. 
  Full monitoring in progress."
```

### Mitigation Timeline

```
╭─────────┬────────────────────────────────┬───────────────────╮
│  TIME   │ ACTION                         │ SYSTEM            │
├─────────┼────────────────────────────────┼───────────────────┤
│  0:00   │ Stop Cassandra data streaming  │ Cassandra         │
│  0:30   │ Force nodes UP (restart gossip)│ Cassandra         │
│  1:30   │ Deploy feed caching for hot    │ Cassandra + App   │
│         │ partitions                     │                   │
├─────────┼────────────────────────────────┼───────────────────┤
│  3:00   │ Clear ES heap, reduce queues   │ Elasticsearch     │
│  3:30   │ Throttle search at app layer   │ Elasticsearch     │
│  5:00   │ Scale ES cluster (add nodes)   │ Elasticsearch     │
├─────────┼────────────────────────────────┼───────────────────┤
│  7:00   │ Deploy local cache for hot key │ Redis             │
│  8:00   │ Kill stacking queries, disable │ Citus             │
│         │ dashboard auto-refresh         │                   │
├─────────┼────────────────────────────────┼───────────────────┤
│ 10:00   │ Systematic verification        │ All               │
│ 15:00   │ Confirm stable, communicate    │ All               │
╰─────────┴────────────────────────────────┴───────────────────╯

ORDER RATIONALE:
  Cassandra FIRST: cascading and getting worse. Every 
  minute of delay risks more nodes being marked DOWN 
  → total feed outage.
  
  Elasticsearch SECOND: search errors affect all users, 
  but the circuit breaker is actually PROTECTING the 
  cluster (preventing heap OOM). It's degraded but 
  stable. Less urgent than Cassandra's active cascade.
  
  Redis THIRD: hot key causes latency spike but Redis 
  isn't cascading — it's just slow. Other masters are 
  fine. User impact is limited to trending topics 
  staleness + latency on one master.
  
  Citus LAST: internal dashboard only. No user-facing 
  impact. Kill queries and disable the dashboard — 
  30-second fix, lowest priority.
```

---

## Q5: Post-Mortem Architecture — Celebrity-Proof Design

### Cassandra: Dynamic Partition Sharding

```
FAILURE MODE: Celebrity feed partition receives 200x 
normal read traffic. Three nodes holding that partition 
become CPU-saturated. False-down detection cascades.

FIX: Synthetic shard_id in partition key (detailed in 
Q1) + automatic shard count adjustment.

NEW ARCHITECTURE:

  1. FEED TABLE WITH SHARD_ID:
     CREATE TABLE feed_events (
       user_id     bigint,
       event_day   date,
       shard_id    int,
       event_time  timestamp,
       event_type  text,
       payload     text,
       PRIMARY KEY ((user_id, event_day, shard_id), event_time)
     ) WITH CLUSTERING ORDER BY (event_time DESC);

  2. SHARD COUNT REGISTRY:
     CREATE TABLE user_shard_config (
       user_id     bigint PRIMARY KEY,
       shard_count int,
       updated_at  timestamp
     );

  3. AUTOMATIC SCALING:
     Monitor per-partition read rate. When a partition 
     exceeds a threshold (e.g., 5,000 reads/sec), 
     automatically increase shard_count:

     async def monitor_hot_partitions():
         # Query Cassandra metrics (JMX or system tables):
         hot_partitions = get_partitions_above_threshold(
             reads_per_sec=5000
         )
         for partition in hot_partitions:
             current_shards = get_shard_count(partition.user_id)
             new_shards = min(current_shards * 2, 64)
             if new_shards > current_shards:
                 await expand_shards(
                     partition.user_id, 
                     current_shards, 
                     new_shards
                 )

     # expand_shards: write new data to new shard range,
     # background-migrate existing data from old shards.
     # Reads query both old and new shard ranges during 
     # migration.

  4. GOSSIP PROTECTION:
     phi_convict_threshold: 12  # prevent false-downs
     hinted_handoff_throttle_in_kb: 256  # gentle recovery

  5. APPLICATION-LEVEL FEED CACHE:
     ALWAYS cache celebrity feeds in Redis (TTL=10s).
     This is the first line of defense — Cassandra 
     should never receive 47K reads/sec for a single 
     partition. The cache absorbs the spike. Cassandra 
     handles the 10/sec cache misses comfortably.

HOW THIS HANDLES THE NEXT BTS EVENT:
  → BTS has shard_count=16 (configured based on history)
  → 47K reads/sec hits Redis cache first → 10/sec to Cassandra
  → 10/sec ÷ 16 shards = <1 read/sec per partition
  → Spread across many nodes on the token ring
  → No single node receives disproportionate load
  → Even if cache fails: 47K ÷ 16 = 2,937/sec per shard
  → ~3K reads/sec across 3 replicas = 1K/node. Comfortable.
```

### Elasticsearch: Time-Based Indices with ILM

```
FAILURE MODE: 18-month-old monolithic index with 65GB 
shards causes GC thrashing under query spikes. Cannot 
re-shard in place.

FIX: Time-based index rollover with ILM (detailed in Q3).

POST-MORTEM ADDITIONS:

  1. SHARD SIZE ALERTING:
     # Prometheus alert when any shard exceeds 40GB:
     - alert: ESShardTooLarge
       expr: |
         elasticsearch_index_stats_store_size_bytes{type="primary"} 
         / elasticsearch_index_stats_shards_count > 40e9
       for: 1h
       labels:
         severity: warning
       annotations:
         message: "Shard size exceeds 40GB. Rollover may be needed."

  2. QUERY-LEVEL CIRCUIT BREAKER:
     # Application-side: if search p99 > 500ms for 
     # 2 consecutive minutes, activate degraded mode:
     # → Limit results to last 7 days (smaller indices)
     # → Return cached trending results instead of live search
     # → Display "Search results limited during high traffic"

  3. DEDICATED HOT-TOPIC SEARCH INDEX:
     # Separate index for trending/viral content:
     # "posts-hot" — small, frequently refreshed, 
     # optimized for the queries that spike during events.
     # When BTS trends: "BTS comeback" queries hit 
     # posts-hot (small, fast) instead of the full 
     # posts archive (780GB).

HOW THIS HANDLES THE NEXT BTS EVENT:
  → Daily indices: today's index has 6 shards × ~1.7GB each
  → Most "BTS comeback" searches are for RECENT posts
  → Query routing: recent-first (today + yesterday = 
    12 small shards, fast)
  → Full archive search: separate slow path, rate-limited
  → Shard sizes never exceed 30GB (ILM rollover guarantees)
  → No GC thrashing: small shards = small heap footprint
```

### Redis: Hot Key Protection Layer

```
FAILURE MODE: Single trending topic key receives 120K 
reads/sec, saturating single-threaded Redis master. 
Collateral damage to all keys on that node.

FIX: Multi-layer caching + read from replicas.

POST-MORTEM ARCHITECTURE:

  1. APPLICATION-LEVEL LOCAL CACHE (L1):
     Every app server caches trending topics in-memory.
     TTL = 5 seconds. This is the primary defense.
     
     120K reads/sec → 10/sec to Redis.
     
     This is a PERMANENT configuration, not a hotfix.
     Trending topics change every ~15 minutes. A 5-second 
     local cache has zero impact on freshness.

  2. REDIS REPLICA READS FOR TRENDING (L2):
     When L1 misses, read from the REPLICA of the hot 
     master, not the master itself:

     redis_replica.execute_command("READONLY")
     result = redis_replica.get("trending:BTS")
     
     Spreads L2 reads across master + replica.
     With L1 absorbing 99.99%: L2 load is negligible.

  3. SEPARATE REDIS CLUSTER FOR TRENDING:
     Trending topic data on a SEPARATE Redis cluster 
     from session/cart data. Blast radius isolation:
     → Trending Redis overload cannot affect sessions
     → Sessions are critical (logged-out users = lost sales)
     → Trending data is non-critical (stale trending = 
       mild UX degradation)

  4. KEY SHARDING FOR FUTURE-PROOFING:
     # Even with L1 cache, shard trending keys:
     trending:BTS:0 through trending:BTS:7
     # Each shard on a different slot/master.
     # Client picks random shard on read.
     # Defense in depth: if L1 fails, L2 still 
     # distributes across 8 masters.

HOW THIS HANDLES THE NEXT BTS EVENT:
  → L1 local cache absorbs 99.99% of reads
  → L2 replica reads handle the <10/sec cache misses
  → Trending Redis is isolated from session Redis
  → Even total trending Redis failure: only stale trending 
    topics, no session impact
  → Redis master CPU: <5% (vs 94% during incident)
```

### Citus: Pre-Computed Analytics

```
FAILURE MODE: Cross-shard scatter-gather analytics 
queries stack during high traffic, consuming coordinator 
connections and blocking the connection pool.

FIX: Materialized views + query throttling.

POST-MORTEM ARCHITECTURE:

  1. MATERIALIZED VIEW FOR TOP-N QUERIES:
     CREATE MATERIALIZED VIEW top_engaged_users AS
     SELECT user_id, engagement_score, 
            follower_count, post_count
     FROM user_analytics
     ORDER BY engagement_score DESC
     LIMIT 1000;

     # Refresh every 5 minutes via pg_cron:
     SELECT cron.schedule(
       'refresh_top_engaged',
       '*/5 * * * *',
       'REFRESH MATERIALIZED VIEW CONCURRENTLY 
        top_engaged_users;'
     );

     Dashboard reads from materialized view: single-node, 
     sub-millisecond. No scatter-gather.

  2. QUERY GOVERNOR:
     # Limit concurrent scatter-gather queries on 
     # the coordinator:
     
     # postgresql.conf on coordinator:
     # statement_timeout = 10s (kill queries > 10s)
     
     # Application level:
     analytics_semaphore = asyncio.Semaphore(3)
     # Max 3 concurrent scatter-gather queries at any time
     
     async def get_top_engaged():
         if not analytics_semaphore.acquire_nowait():
             # Return cached/stale result instead of 
             # stacking another scatter-gather query
             return await get_cached_top_engaged()
         try:
             return await citus_coordinator.fetch(
                 "SELECT * FROM top_engaged_users"  
                 # Reads from materialized view, NOT 
                 # scatter-gather. But even this is 
                 # rate-limited as defense in depth.
             )
         finally:
             analytics_semaphore.release()

     # Even if someone bypasses the materialized view 
     # and runs a raw scatter-gather, the semaphore 
     # limits the damage to 3 concurrent queries.

  3. SEPARATE CONNECTION POOL FOR ANALYTICS:
     # Citus coordinator PgBouncer config:
     [databases]
     app_queries = host=coordinator port=5432 pool_size=150
     analytics   = host=coordinator port=5432 pool_size=30
     
     # Analytics queries can only consume 30 connections.
     # Even if all 30 are tied up in scatter-gather 
     # queries, the 150 app connections are untouched.
     # User-facing queries (profile lookups by user_id 
     # — single-shard, fast) are isolated from analytics.

  4. DASHBOARD CIRCUIT BREAKER:
     # If coordinator CPU > 70% or active connections 
     # > 80% of pool:
     # → Dashboard automatically switches to "cached mode"
     # → Shows data from last successful refresh
     # → Displays "Data may be up to 10 minutes old"
     # → Stops issuing new queries until load drops

     # Prometheus alert:
     - alert: CitusCoordinatorHighLoad
       expr: |
         pg_stat_activity_count{state="active",database="analytics"} 
         > 24
       for: 30s
       labels:
         severity: warning
         automation: dashboard_cached_mode
       annotations:
         runbook: |
           AUTOMATED: Set DASHBOARD_MODE=cached
           Dashboard serves stale data until load drops.

HOW THIS HANDLES THE NEXT BTS EVENT:
  → Dashboard reads from materialized view (no scatter-gather)
  → Materialized view refreshes every 5 minutes (background, 
    single scatter-gather, takes ~2.3s, tolerable)
  → Even if someone runs a manual analytics query: 
    semaphore limits to 3 concurrent, separate pool limits 
    to 30 connections, statement_timeout kills at 10s
  → User-facing queries (single-shard by user_id) are 
    completely isolated on their own pool
  → Coordinator never overloads from analytics
```

### Post-Mortem Architecture Summary

```
╭──────────────┬──────────────────────────┬──────────────────────╮
│ SYSTEM       │ CHANGE                   │ FAILURE MODE         │
│              │                          │ PREVENTED            │
├──────────────┼──────────────────────────┼──────────────────────┤
│ Cassandra    │ Synthetic shard_id in    │ Hot partition        │
│              │ partition key + dynamic  │ overloading 3 nodes  │
│              │ shard count scaling      │                      │
│              ├──────────────────────────┼──────────────────────┤
│              │ phi_convict_threshold:12 │ False-down detection │
│              │ + hint throttling        │ and cascade          │
│              ├──────────────────────────┼──────────────────────┤
│              │ Application-level feed   │ 47K reads/sec ever   │
│              │ cache (L1 + Redis L2)    │ reaching Cassandra   │
├──────────────┼──────────────────────────┼──────────────────────┤
│ Elastic-     │ Time-based indices with  │ 65GB shards causing  │
│ search       │ ILM (max 30GB/shard)     │ GC thrashing         │
│              ├──────────────────────────┼──────────────────────┤
│              │ Dedicated hot-topic      │ Viral search spikes  │
│              │ search index             │ hitting full archive │
│              ├──────────────────────────┼──────────────────────┤
│              │ App-level query          │ Unbounded query      │
│              │ throttling + degradation │ volume overwhelming  │
│              │                          │ cluster              │
├──────────────┼──────────────────────────┼──────────────────────┤
│ Redis        │ L1 local cache (5s TTL)  │ Hot key saturating   │
│              │ for trending topics      │ single-threaded node │
│              ├──────────────────────────┼──────────────────────┤
│              │ Separate Redis cluster   │ Trending load        │
│              │ for trending vs sessions │ affecting sessions   │
│              ├──────────────────────────┼──────────────────────┤
│              │ Key sharding (defense    │ Future hot keys if   │
│              │ in depth)                │ L1 cache fails       │
├──────────────┼──────────────────────────┼──────────────────────┤
│ Citus        │ Materialized view for    │ Scatter-gather       │
│              │ top-N analytics          │ query stacking       │
│              ├──────────────────────────┼──────────────────────┤
│              │ Separate connection pool │ Analytics starving   │
│              │ for analytics vs app     │ app queries          │
│              ├──────────────────────────┼──────────────────────┤
│              │ Query governor           │ Unbounded concurrent │
│              │ (semaphore + timeout)    │ scatter-gathers      │
╰──────────────┴──────────────────────────┴──────────────────────╯

DEFENSE IN DEPTH ACROSS ALL SYSTEMS:

  Layer 1: APPLICATION CACHING
    → Local in-memory cache absorbs 99%+ of reads 
      for hot data (feeds, trending topics)
    → Systems never see the raw traffic spike

  Layer 2: PARTITION DESIGN
    → Hot partitions are sharded across multiple nodes
    → No single node receives disproportionate load
    → Even if cache fails, partition-level distribution 
      handles the load

  Layer 3: SYSTEM-LEVEL PROTECTION
    → Gossip threshold prevents false-down cascades
    → Circuit breakers prevent heap exhaustion
    → Connection pool isolation prevents cross-concern 
      resource starvation
    → Query governors prevent unbounded scatter-gather

  Layer 4: GRACEFUL DEGRADATION
    → Search returns "limited results" instead of errors
    → Dashboard shows stale data instead of timing out
    → Trending topics serve from local cache instead of 
      overwhelming Redis
    → Feed cache serves 10-second-old data instead of 
      hammering Cassandra

  AN ATTACKER (or a K-pop army) WOULD NEED TO OVERWHELM 
  ALL FOUR LAYERS SIMULTANEOUSLY TO CAUSE THE SAME 
  INCIDENT. Application cache failure + partition 
  sharding failure + gossip/circuit breaker failure + 
  degradation logic failure. Each layer is independently 
  sufficient to prevent the cascade.
```


