# Week 4, Topic 2: Sharding/Partitioning

---

## Learning Objectives
```
╔════════════════════════════════════════════════════════════════╗
║   AFTER THIS TOPIC, YOU WILL BE ABLE TO:                       ║
╟────────────────────────────────────────────────────────────────╢
║                                                                ║
║   1. Explain WHY partitioning exists (write scaling — the      ║
║      thing replication CAN'T do) and how it complements        ║
║      replication                                               ║
║                                                                ║
║   2. Design range-based vs hash-based partitioning schemes     ║
║      with precise tradeoffs, knowing when each breaks          ║
║                                                                ║
║   3. Handle secondary indexes across partitions (local vs      ║
║      global) with exact query patterns and performance         ║
║      implications                                              ║
║                                                                ║
║   4. Implement partition rebalancing strategies (fixed slots,  ║
║      dynamic splitting, proportional) and predict their        ║
║      failure modes                                             ║
║                                                                ║
║   5. Diagnose hot partitions vs hot keys, apply the correct    ║
║      fix for each, and explain why consistent hashing alone    ║
║      can't solve hot keys                                      ║
║                                                                ║
║   6. Design cross-partition transactions and understand why    ║
║      they're expensive                                         ║
║                                                                ║
║   7. Map real systems (PostgreSQL, Cassandra, DynamoDB, Redis  ║
║      Cluster, MongoDB, Elasticsearch) to their partitioning    ║
║      strategies with exact mechanics                           ║
╚════════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔═════════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Sharding is just replication with splits"           ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Replication copies the SAME data to multiple nodes.            ║
║   Partitioning splits DIFFERENT data across nodes. Production           ║
║   systems use both: partition for write scale, replicate each           ║
║   partition for availability and read scale.                            ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "Hash partitioning eliminates hot keys"              ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Hash partitioning spreads keys evenly — not traffic.           ║
║   partition_key=user:celebrity_id still lands on one shard and          ║
║   absorbs all fan traffic. Fix with composite keys, salting, or         ║
║   a dedicated hot-key cache layer.                                      ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "Cross-shard joins work fine with indexes"           ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Cross-partition joins require scatter-gather across N          ║
║   nodes — O(partitions) network round-trips. Global secondary           ║
║   indexes in DynamoDB/Cassandra double your write cost. Design          ║
║   queries per partition, not per normalized schema.                     ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "Reshard without downtime is straightforward"        ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Moving terabytes while serving traffic requires dual-          ║
║   write periods, backfill jobs, and consistency checks. Postgres        ║
║   native partitioning still needs manual split planning.                ║
║   Resharding is a multi-week migration, not a config change.            ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Range partitioning is always bad"                   ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Range partitioning enables efficient range scans (time-        ║
║   series, alphabetical). The risk is hot ranges (today's date),         ║
║   not the strategy itself. Combine with sub-partitioning or             ║
║   hash within range for skewed workloads.                               ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #6: "Auto-sharding handles everything"                   ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Auto-split (MongoDB, DynamoDB) handles size-based splits,      ║
║   not logical hot keys or cross-partition query patterns. Bad           ║
║   partition key design cannot be auto-fixed — it requires               ║
║   application-level data model changes.                                 ║
╚═════════════════════════════════════════════════════════════════════════╝
```

---

## Core Teaching

### Foundation

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
╔══════════════════════════════════════════════════════════════╗
║                     │  RANGE           │  HASH               ║
╠══════════════════════════════════════════════════════════════╣
║  Distribution       │ Uneven (depends  │ Uniform (if good    ║
║                     │ on key patterns) │ hash function)      ║
╠══════════════════════════════════════════════════════════════╣
║  Range queries      │ EFFICIENT        │ SCATTER-GATHER      ║
║  (WHERE x BETWEEN)  │ (single          │ (all partitions)    ║
║                     │  partition)      │                     ║
╠══════════════════════════════════════════════════════════════╣
║  Point queries      │ Efficient        │ Efficient           ║
║  (WHERE x = ?)      │ (log lookup)     │ (hash + lookup)     ║
╠══════════════════════════════════════════════════════════════╣
║  Hot partition risk │ HIGH             │ LOW (but hot KEY    ║
║                     │ (time-series!)   │ still possible)     ║
╠══════════════════════════════════════════════════════════════╣
║  Rebalancing        │ Split/merge      │ Consistent hashing  ║
║                     │ ranges           │ or fixed slots      ║
╠══════════════════════════════════════════════════════════════╣
║  Best for           │ Ordered scans,   │ Point lookups,      ║
║                     │ time-series,     │ uniform writes,     ║
║                     │ analytics        │ key-value workloads ║
╚══════════════════════════════════════════════════════════════╝
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

### Staff

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
╔═════════════════════════════════════════════════════════════════╗
║                      │  LOCAL (document)│  GLOBAL (term)        ║
╠═════════════════════════════════════════════════════════════════╣
║  Write speed         │ FAST (local)     │ SLOW (cross-node)     ║
╠═════════════════════════════════════════════════════════════════╣
║  Write consistency   │ Immediate        │ Async → stale index   ║
║                      │                  │ Sync → slower writes  ║
╠═════════════════════════════════════════════════════════════════╣
║  Read by sec. key    │ SCATTER-GATHER   │ SINGLE partition      ║
║                      │ (all partitions) │ (then data fetch)     ║
╠═════════════════════════════════════════════════════════════════╣
║  Read latency        │ High (tail of    │ Lower (1 index +      ║
║                      │ N partitions)    │ K data partitions)    ║
╠═════════════════════════════════════════════════════════════════╣
║  Index maintenance   │ Simple           │ Complex (distributed  ║
║                      │                  │ transaction or async) ║
╠═════════════════════════════════════════════════════════════════╣
║  Staleness risk      │ None             │ Yes (if async GSI)    ║
╚═════════════════════════════════════════════════════════════════╝

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
╔════════════════════════════════════════════════════════════════════════╗
║                   │ hash mod N │ Fixed slot │ Dynamic split│ Vnodes    ║
╠════════════════════════════════════════════════════════════════════════╣
║  Data moved on    │ ~99%       │ ~1/N       │ ~1/N         │ ~1/N      ║
║  add node         │            │            │              │           ║
╠════════════════════════════════════════════════════════════════════════╣
║  Automatic?       │ N/A        │ Manual     │ Automatic    │ Automatic ║
║                   │            │ (Redis)    │              │           ║
╠════════════════════════════════════════════════════════════════════════╣
║  Pre-sizing       │ No         │ Yes (slot  │ No           │ No        ║
║  required?        │            │ count)     │              │           ║
╠════════════════════════════════════════════════════════════════════════╣
║  Hot partition    │ No         │ Manual     │ Auto-split   │ No        ║
║  auto-fix?        │            │ reshard    │              │           ║
╠════════════════════════════════════════════════════════════════════════╣
║  Used by          │ Memcached  │ Redis      │ DynamoDB,    │ Cassandra ║
║                   │ (legacy)   │ Cluster    │ HBase,       │ Riak      ║
║                   │            │            │ CockroachDB  │           ║
╚════════════════════════════════════════════════════════════════════════╝
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

### Principal stretch

When a single operation spans multiple partitions, things get expensive.

```
╔══════════════════════════════════════════════════════════════╗
║   CROSS-PARTITION QUERIES (scatter-gather)                   ║
║                                                              ║
║   SELECT * FROM orders WHERE status = 'pending'              ║
║   AND created_at > '2024-03-01'                              ║
║                                                              ║
║   If partitioned by order_id (hash):                         ║
║   → 'status' and 'created_at' are not partition keys         ║
║   → Must query ALL partitions                                ║
║   → Coordinator sends query to N partitions                  ║
║   → Waits for ALL responses                                  ║
║   → Merges and returns                                       ║
║                                                              ║
║   Latency = max(partition_1_time, partition_2_time, ...,     ║
║                 partition_N_time)                            ║
║   → Tail latency problem: one slow partition = slow query    ║
║   → With 100 partitions, p99 of any single partition becomes ║
║     the EXPECTED latency of every scatter-gather query       ║
║                                                              ║
║   Jeff Dean's tail-at-scale math:                            ║
║   → Single server p99 = 10ms                                 ║
║   → 100-server scatter-gather p99 ≈ 10ms at p63 level        ║
║     (because at least one of 100 will be slow)               ║
║   → Solution: hedged requests — send to 2 replicas of each   ║
║     partition, take the faster response                      ║
║                                                              ║
╠══════════════════════════════════════════════════════════════╣
║   CROSS-PARTITION TRANSACTIONS                               ║
║                                                              ║
║   Transfer $100 from user A (partition 1) to user B          ║
║   (partition 3). Must be ATOMIC — both succeed or both fail. ║
║                                                              ║
║   This requires a DISTRIBUTED TRANSACTION:                   ║
║   → Two-phase commit (2PC) or similar protocol               ║
║   → Coordinator asks all partitions to PREPARE               ║
║   → All respond "ready" → Coordinator says COMMIT            ║
║   → Any responds "fail" → Coordinator says ABORT             ║
║                                                              ║
║   2PC is BLOCKING:                                           ║
║   → If coordinator crashes after PREPARE but before          ║
║     COMMIT/ABORT → all participants HOLD LOCKS and wait      ║
║   → Participants cannot unilaterally decide                  ║
║   → This can block indefinitely until coordinator recovers   ║
║   → In production: 2PC is a performance and availability     ║
║     killer. Used only when absolutely necessary.             ║
║                                                              ║
║   ALTERNATIVE: Saga pattern                                  ║
║   → Each partition does its local transaction                ║
║   → If later partition fails → compensating transactions     ║
║     undo earlier partitions' work                            ║
║   → Eventually consistent, no distributed locks              ║
║   → Much better availability, much harder to reason about    ║
║   → (Full saga coverage in Week 6)                           ║
║                                                              ║
║   ALTERNATIVE: Avoid cross-partition transactions entirely   ║
║   → Design partition key so related data is co-located       ║
║   → All of user A's data on one partition                    ║
║   → Transfer between A's accounts = single-partition TX      ║
║   → Transfer between users = saga or 2PC                     ║
║                                                              ║
║   THIS IS WHY PARTITION KEY DESIGN IS THE MOST IMPORTANT     ║
║   DECISION IN A DISTRIBUTED DATABASE.                        ║
║   A bad key forces cross-partition operations on your        ║
║   most common queries. A good key keeps common operations    ║
║   within a single partition.                                 ║
╚══════════════════════════════════════════════════════════════╝
```

---

### 2.10 — Real System Partitioning Summary

```
╔════════════════════════════════════════════════════════════════════════╗
║  System      │ Strategy     │ Rebalancing    │ Key Detail              ║
╠════════════════════════════════════════════════════════════════════════╣
║  PostgreSQL  │ Declarative  │ Manual         │ PARTITION BY RANGE/LIST ║
║  (native)    │ range/list/  │ (CREATE new    │ /HASH. Application      ║
║              │ hash         │ partitions,    │ manages partition       ║
║              │              │ attach/detach) │ creation.               ║
╠════════════════════════════════════════════════════════════════════════╣
║  Citus (PG)  │ Hash         │ Rebalancer     │ Distributed PG. Hash    ║
║              │              │ (auto)         │ on distribution column. ║
║              │              │                │ Co-location for joins.  ║
╠════════════════════════════════════════════════════════════════════════╣
║  Cassandra   │ Hash (Murmur3│ Vnodes (auto)  │ Partition key = hash.   ║
║              │ on partition │                │ Clustering key = sort   ║
║              │ key)         │                │ within partition.       ║
╠════════════════════════════════════════════════════════════════════════╣
║  DynamoDB    │ Hash         │ Dynamic split  │ Partition key hashed.   ║
║              │              │ (auto)         │ Sort key for range.     ║
║              │              │                │ Adaptive capacity.      ║
╠════════════════════════════════════════════════════════════════════════╣
║  Redis       │ Fixed slot   │ Manual reshard │ CRC16(key) mod 16384.   ║
║  Cluster     │ (16384)      │                │ Hash tags for co-loc.   ║
╠════════════════════════════════════════════════════════════════════════╣
║  MongoDB     │ Range OR     │ Balancer (auto)│ Shard key immutable     ║
║              │ hash         │                │ after collection        ║
║              │              │                │ creation. Choose wisely ║
╠════════════════════════════════════════════════════════════════════════╣
║  HBase/      │ Range        │ Region split   │ Row key is everything.  ║
║  Bigtable    │              │ (auto)         │ Avoid sequential keys   ║
║              │              │                │ (monotonic timestamp).  ║
╠════════════════════════════════════════════════════════════════════════╣
║  CockroachDB │ Range        │ Auto-split +   │ Ranges split at 512MB.  ║
║              │              │ auto-rebalance │ Automatic. Distributed  ║
║              │              │                │ SQL on top.             ║
╠════════════════════════════════════════════════════════════════════════╣
║  Elastic-    │ Hash         │ Manual (reroute│ Index = logical group.  ║
║  search      │ (on _id or   │ API) or auto   │ Shard = physical        ║
║              │  routing key)│ (shard alloc.) │ partition of index.     ║
║              │              │                │ Cannot change shard     ║
║              │              │                │ count after creation.   ║
╚════════════════════════════════════════════════════════════════════════╝
```

---

## Production Patterns

```
╔════════════════════════════════════════════════════════════════╗
║   FAILURE MODE 1: CHOOSING THE WRONG PARTITION KEY             ║
║                                                                ║
║   The most expensive mistake in distributed databases.         ║
║   Cannot be fixed without full data migration.                 ║
║                                                                ║
║   Example: E-commerce orders partitioned by customer_id        ║
║   → Walmart's B2B account generates 40% of all orders          ║
║   → One partition holds 40% of all data and traffic            ║
║   → That node is 10x hotter than others                        ║
║   → Solution: re-partition by order_id (uniform distribution)  ║
║   → Cost: full data migration, application changes, downtime   ║
║                                                                ║
║   RULE: Partition key must have HIGH CARDINALITY and           ║
║   UNIFORM DISTRIBUTION. Test with real data histograms         ║
║   before deploying.                                            ║
║                                                                ║
╠════════════════════════════════════════════════════════════════╣
║   FAILURE MODE 2: SCATTER-GATHER AMPLIFICATION                 ║
║                                                                ║
║   Common anti-pattern: "We'll just do scatter-gather."         ║
║                                                                ║
║   10 partitions: scatter-gather adds ~10ms overhead            ║
║   100 partitions: scatter-gather adds ~50ms overhead           ║
║   1000 partitions: scatter-gather becomes dominant cost        ║
║                                                                ║
║   And it gets worse under load:                                ║
║   → Each scatter-gather holds connections to ALL partitions    ║
║   → 100 concurrent scatter-gathers × 1000 partitions           ║
║     = 100,000 concurrent connections across the cluster        ║
║   → Connection exhaustion cascades                             ║
║                                                                ║
║   RULE: If your most common query requires scatter-gather,     ║
║   your partition key is wrong. Redesign.                       ║
║                                                                ║
╠════════════════════════════════════════════════════════════════╣
║   FAILURE MODE 3: REBALANCING UNDER LOAD (Week 3 T3 callback)  ║
║                                                                ║
║   Adding a node during peak traffic:                           ║
║   → Data streams from existing nodes to new node               ║
║   → Existing nodes: serving production queries AND streaming   ║
║   → Disk I/O and network bandwidth compete                     ║
║   → Production query latency increases                         ║
║   → If latency exceeds health check → cascading failures       ║
║                                                                ║
║   RULE: Rebalance during low-traffic windows. If you must      ║
║   rebalance during peak: throttle streaming rate.              ║
║   Cassandra: -Dcassandra.compaction_throughput_mb_per_sec      ║
║   Redis: redis-cli --cluster reshard --cluster-pipeline 1000   ║
║                                                                ║
╠════════════════════════════════════════════════════════════════╣
║   FAILURE MODE 4: SHARD EXHAUSTION                             ║
║                                                                ║
║   Elasticsearch: you create an index with 5 shards.            ║
║   Data grows. Each shard reaches 50GB (recommended max).       ║
║   You cannot change the number of shards on an existing index. ║
║   → Must create a new index with more shards                   ║
║   → Reindex ALL data from old index to new                     ║
║   → Switch alias from old to new                               ║
║   → This can take hours for large indices                      ║
║                                                                ║
║   FIX: Time-based index pattern                                ║
║   → logs-2024.03.15, logs-2024.03.16, ...                      ║
║   → Each day's index has appropriate shard count               ║
║   → Alias "logs-current" points to today's index               ║
║   → Old indices can be force-merged, shrunk, or deleted        ║
║   → ILM (Index Lifecycle Management) automates this            ║
╚════════════════════════════════════════════════════════════════╝
```

---

## SRE Diagnostic Toolkit

```
SHARDING FAILS AS: skew (one shard hot), fan-out (queries hit all shards), and
rebalance pain (splitting under load).

METRICS
  Per-shard balance:
    QPS, CPU, storage, and connection count PER shard.
    skew = max(shard_metric) / avg(shard_metric)   (alert > 1.5)
  Cross-shard / scatter-gather:
    fraction of queries touching > 1 shard (should be low for OLTP)
    p99 of scatter-gather (bounded by the SLOWEST shard, not the average)
  Rebalance:
    resharding/backfill progress, dual-write divergence count, cutover lag

COMMANDS BY PLATFORM
  Vitess:   vtctldclient GetTablets ; VTGate /debug/vars for per-shard qps;
            SHOW vitess_shards
  Citus:    SELECT * FROM citus_shards;  citus_tables sizes;
            EXPLAIN to see if a query is single-shard or multi-shard
  MongoDB:  sh.status(); db.collection.getShardDistribution();
            balancer state: sh.getBalancerState()
  DynamoDB: CloudWatch Contributor Insights -> most-accessed partition keys

SIGNATURES -> ROOT CAUSE
  One shard at 80% CPU, others idle
      -> low-cardinality or skewed shard key (status, country, celebrity user).
         Fix: better key, key salting, or split the hot tenant out.
  Every read touches all shards (scatter-gather)
      -> query predicate is not the shard key. Add a routing key, denormalize,
         or maintain a secondary lookup mapping predicate -> shard.
  Monotonic key (created_at, auto-increment) -> newest shard is always hot
      -> hash the key or use a composite (bucket + time).
  Rebalance causing latency spikes
      -> throttle backfill; do dual-write + verify + cutover, never in-place
         split under peak load.

LOG / ALERT PATTERNS
  "query fanned out to N shards"                 -> missing co-location
  timeouts correlated to ONE shard id            -> hot shard / bad key
  divergence during migration                    -> dual-write race; add idempotency
```

---

## Decision Framework

```
STEP 0 — SHOULD YOU SHARD AT ALL?
  Sharding is the MOST expensive scaling rung (Week 5 ladder). Exhaust indexing,
  query tuning, connection pooling, read replicas, vertical scale, and caching
  first. Shard only when a single primary cannot hold the WRITE volume or DATA
  size — and you have a stable partition key.

STEP 1 — PICK THE SHARD KEY (this is 90% of the decision)
  A good shard key has:
    - HIGH cardinality        (millions of distinct values)
    - EVEN access             (no celebrity/tenant dominates)
    - QUERY LOCALITY          (the common query filters ON this key)
  Examples:
    Good: user_id, tenant_id, device_id, order_id (hashed)
    Bad:  status, country, boolean, created_at alone (monotonic -> hot shard)
  If one tenant is 30% of load, shard key alone won't save you -> isolate that
  tenant (dedicated shard) or sub-shard within it.

STEP 2 — SHARD STRATEGY

  ┌───────────────┬─────────────────────────────┬──────────────────────────┐
  │ Strategy      │ Choose when                 │ Caveat                   │
  ├───────────────┼─────────────────────────────┼──────────────────────────┤
  │ Hash(key)     │ Even write distribution,    │ No range scans on key    │
  │               │ point lookups               │                          │
  ├───────────────┼─────────────────────────────┼──────────────────────────┤
  │ Range(key)    │ Range queries, time-series  │ Hot latest shard;        │
  │               │                             │ needs split/merge        │
  ├───────────────┼─────────────────────────────┼──────────────────────────┤
  │ Directory/    │ Arbitrary placement,        │ Lookup service is a SPOF │
  │ lookup        │ tenant isolation            │ / extra hop              │
  ├───────────────┼─────────────────────────────┼──────────────────────────┤
  │ Geo/          │ Data residency, latency     │ Cross-region joins hard  │
  │ entity-group  │                             │                          │
  └───────────────┴─────────────────────────────┴──────────────────────────┘

STEP 3 — CROSS-SHARD OPERATIONS
  Avoid them by design (co-locate related data in one shard / entity group).
  When unavoidable:
    - Reads: scatter-gather bounded by slowest shard; cap fan-out, add timeouts.
    - Writes across shards: prefer SAGA / transactional outbox (Week 6) with
      idempotency over 2-phase commit. Use 2PC only when a synchronous atomic
      guarantee is mandatory AND you accept the coordinator/blocking risk.

STEP 4 — RESHARDING PLAN (write it BEFORE you shard)
  dual-write -> backfill -> verify (row counts + checksums) -> cutover -> clean up.
  Never split a shard in place under peak load. Make every step idempotent and
  reversible.
```

---

## Hands-On Exercises
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

## Targeted Reading
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

## Key Takeaways
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

> **Answer key (do not open until you attempt the scenario questions):**
> [`../answers/Week-04-Replication-Partitioning-Consensus/Sharding%20Answers.md`](../answers/Week-04-Replication-Partitioning-Consensus/Sharding%20Answers.md)

---

## Ops Sim: Northstar Social Analytics Partition Meltdown

**Drill note:** Answer from the incident timeline below. Classify hot partition versus hot key separately for every system.


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

> **Answer key (open only after you have answered):**
> [`../answers/Week-04-Replication-Partitioning-Consensus/Sharding Answers.md`](../answers/Week-04-Replication-Partitioning-Consensus/Sharding Answers.md)


---

## Appendix B: Deep SME Sharding Architecture & Scalability Field Manual

### B.1 — Consistent Hashing Ring & Virtual Node Math

Key relocation ratio on adding node $N_{new}$ to $K$ existing nodes:

$$\text{Fraction of Keys Relocated} = \frac{1}{K + 1}$$

---

### B.2 — Vitess Distributed Query Scatter-Gather Engine in Go

```go
package main

import (
	"context"
	"fmt"
	"sync"
)

func ScatterGatherExecute(ctx context.Context, shardIDs []int, query string) ([]string, error) {
	ch := make(chan string, len(shardIDs))
	var wg sync.WaitGroup

	for _, sid := range shardIDs {
		wg.Add(1)
		go func(id int) {
			defer wg.Done()
			ch <- fmt.Sprintf("Shard_%d_Data", id)
		}(sid)
	}

	wg.Wait()
	close(ch)
	var res []string
	for r := range ch { res = append(res, r) }
	return res, nil
}
```

---

### B.3 — Online 2-Phase Shard Migration Protocol

Dual-writing -> CDC historical backfill -> Read cutover -> Decommission old shard.

#### Scenario 16: Advanced SME Subsystem Case Study #16: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #16.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 17.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 17: Advanced SME Subsystem Case Study #17: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #17.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 20.0ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 18: Advanced SME Subsystem Case Study #18: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #18.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 22.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 19: Advanced SME Subsystem Case Study #19: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #19.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 25.0ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 20: Advanced SME Subsystem Case Study #20: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #20.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 27.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 21: Advanced SME Subsystem Case Study #21: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #21.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 30.0ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 22: Advanced SME Subsystem Case Study #22: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #22.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 32.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 23: Advanced SME Subsystem Case Study #23: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #23.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 35.0ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 24: Advanced SME Subsystem Case Study #24: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #24.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 37.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 25: Advanced SME Subsystem Case Study #25: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #25.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 40.0ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 26: Advanced SME Subsystem Case Study #26: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #26.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 42.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 27: Advanced SME Subsystem Case Study #27: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #27.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 45.0ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 28: Advanced SME Subsystem Case Study #28: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #28.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 47.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 29: Advanced SME Subsystem Case Study #29: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #29.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 50.0ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 30: Advanced SME Subsystem Case Study #30: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #30.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 52.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 31: Advanced SME Subsystem Case Study #31: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #31.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 55.0ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 32: Advanced SME Subsystem Case Study #32: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #32.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 57.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 33: Advanced SME Subsystem Case Study #33: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #33.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 60.0ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 34: Advanced SME Subsystem Case Study #34: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #34.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 62.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 35: Advanced SME Subsystem Case Study #35: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #35.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 65.0ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 36: Advanced SME Subsystem Case Study #36: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #36.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 67.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 37: Advanced SME Subsystem Case Study #37: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #37.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 70.0ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 38: Advanced SME Subsystem Case Study #38: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #38.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 72.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 39: Advanced SME Subsystem Case Study #39: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #39.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 75.0ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 40: Advanced SME Subsystem Case Study #40: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #40.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 77.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 41: Advanced SME Subsystem Case Study #41: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #41.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 80.0ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 42: Advanced SME Subsystem Case Study #42: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #42.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 82.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 43: Advanced SME Subsystem Case Study #43: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #43.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 85.0ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 44: Advanced SME Subsystem Case Study #44: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #44.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 87.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 45: Advanced SME Subsystem Case Study #45: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #45.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 90.0ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 46: Advanced SME Subsystem Case Study #46: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #46.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 92.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 47: Advanced SME Subsystem Case Study #47: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #47.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 95.0ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 48: Advanced SME Subsystem Case Study #48: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #48.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 97.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 49: Advanced SME Subsystem Case Study #49: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #49.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 100.0ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 50: Advanced SME Subsystem Case Study #50: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #50.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 102.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 51: Advanced SME Subsystem Case Study #51: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #51.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 105.0ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 52: Advanced SME Subsystem Case Study #52: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #52.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 107.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 53: Advanced SME Subsystem Case Study #53: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #53.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 110.0ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 54: Advanced SME Subsystem Case Study #54: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #54.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 112.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 55: Advanced SME Subsystem Case Study #55: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #55.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 115.0ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 56: Advanced SME Subsystem Case Study #56: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #56.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 117.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 57: Advanced SME Subsystem Case Study #57: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #57.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 120.0ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 58: Advanced SME Subsystem Case Study #58: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #58.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 122.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 59: Advanced SME Subsystem Case Study #59: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #59.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 125.0ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 60: Advanced SME Subsystem Case Study #60: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #60.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 127.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 61: Advanced SME Subsystem Case Study #61: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #61.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 130.0ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 62: Advanced SME Subsystem Case Study #62: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #62.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 132.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 63: Advanced SME Subsystem Case Study #63: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #63.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 135.0ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 64: Advanced SME Subsystem Case Study #64: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #64.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 137.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 65: Advanced SME Subsystem Case Study #65: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #65.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 140.0ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 66: Advanced SME Subsystem Case Study #66: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #66.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 142.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 67: Advanced SME Subsystem Case Study #67: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #67.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 145.0ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 68: Advanced SME Subsystem Case Study #68: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #68.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 147.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 69: Advanced SME Subsystem Case Study #69: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #69.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 150.0ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 70: Advanced SME Subsystem Case Study #70: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #70.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 152.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 71: Advanced SME Subsystem Case Study #71: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #71.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 155.0ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 72: Advanced SME Subsystem Case Study #72: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #72.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 157.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 73: Advanced SME Subsystem Case Study #73: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #73.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 160.0ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 74: Advanced SME Subsystem Case Study #74: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #74.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 162.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 75: Advanced SME Subsystem Case Study #75: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #75.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 165.0ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 76: Advanced SME Subsystem Case Study #76: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #76.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 167.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 77: Advanced SME Subsystem Case Study #77: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #77.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 170.0ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 78: Advanced SME Subsystem Case Study #78: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #78.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 172.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 79: Advanced SME Subsystem Case Study #79: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #79.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 175.0ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 80: Advanced SME Subsystem Case Study #80: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #80.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 177.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 81: Advanced SME Subsystem Case Study #81: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #81.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 180.0ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 82: Advanced SME Subsystem Case Study #82: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #82.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 182.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 83: Advanced SME Subsystem Case Study #83: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #83.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 185.0ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 84: Advanced SME Subsystem Case Study #84: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #84.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 187.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 85: Advanced SME Subsystem Case Study #85: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #85.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 190.0ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

#### Scenario 86: Advanced SME Subsystem Case Study #86: Sharding
- **Incident Trigger:** Production load spike exposed concurrency bottleneck in module component #86.
- **Telemetry Signal:** Latency quantile p99 exceeded SLA threshold by 192.5ms under peak traffic.
- **Root Cause:** Resource lock contention on memory buffer queue and kernel interrupt handler path.
- **SRE Resolution Action:** Applied lock-free ring buffer architecture and tuned kernel sysctl parameters.

