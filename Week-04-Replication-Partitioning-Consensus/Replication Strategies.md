# Week 4, Topic 1: Replication Strategies

---

## 1. Learning Objectives

```
After this topic, you will be able to:

1. Explain leader-follower, multi-leader, and leaderless replication
   with exact write/read paths and failure modes for each
2. Articulate sync vs async vs semi-synchronous replication tradeoffs
   with precise durability and availability guarantees
3. Trace WAL-based physical replication vs logical replication vs
   CDC at the byte/record level
4. Map every replication topology to its PACELC classification
   and predict exactly which consistency violations each produces
5. Design replication topologies for real systems, choosing the
   right strategy per feature based on consequence analysis
6. Diagnose replication lag incidents using exact tools and commands
7. Explain failover mechanics — what goes wrong, why split-brain
   happens, and how to prevent it
```

---

## 2. Core Teaching

### 2.1 — Why Replication Exists

Every reason to replicate falls into exactly three buckets:

```
╔══════════════════════════════════════════════════════════════╗
║   WHY REPLICATE?                                             ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   1. HIGH AVAILABILITY (fault tolerance)                     ║
║      → Node dies → another has the data → keep serving       ║
║                                                              ║
║   2. LOW LATENCY (geographic proximity)                      ║
║      → User in Tokyo reads from Tokyo replica                ║
║      → Not from Virginia primary 170ms away                  ║
║                                                              ║
║   3. READ SCALABILITY (throughput)                           ║
║      → 1 primary handles 10K writes/sec                      ║
║      → 5 replicas handle 50K reads/sec total                 ║
║      → Reads scale horizontally; writes DON'T                ║
║        (this is the fundamental constraint)                  ║
╚══════════════════════════════════════════════════════════════╝
```

That third point is critical: **replication scales reads, not writes.** Every replication topology we'll cover shares this constraint. To scale writes, you need partitioning (Topic 2).

---

### 2.2 — Topology 1: Leader-Follower (Single-Leader)

This is the most common replication topology in production. PostgreSQL, MySQL, MongoDB (replica sets), Redis Sentinel — all default to this.

```
  ╔══════════════════════════════════════════════════════════════╗
  ║                LEADER-FOLLOWER REPLICATION                   ║
  ╟──────────────────────────────────────────────────────────────╢
  ║                                                              ║
  ║   Clients (writes)           Clients (reads)                 ║
  ║        │                     │    │    │                     ║
  ║        ▼                     ▼    ▼    ▼                     ║
  ║   ╭─────────╮          ╭────╮ ╭────╮ ╭────╮                  ║
  ║   │  LEADER  │──WAL──▶│ F1 │ │ F2 │ │ F3 │                   ║
  ║   │ (primary)│  stream │    │ │    │ │    │                  ║
  ╚══════════════════════════════════════════════════════════════╝
  │       │                 ▲                                │
  │       │    replication  │                                │
  │       ╰─────stream──────╯                                │
  │                                                          │
  │  RULES:                                                  │
  │  → ALL writes go to leader. No exceptions.               │
  │  → Followers receive replication stream and apply it.    │
  │  → Reads can go to leader OR followers.                  │
  │  → Followers are read-only.                              │
  ╰──────────────────────────────────────────────────────────╯
```

**The write path (PostgreSQL):**

```
  Client                  Leader                    Follower
    │                       │                          │
    │── BEGIN + INSERT ────▶│                          │
    │                       │── write WAL record ──▶ disk
    │                       │   (sequential append)    │
    │                       │── apply to heap ────▶ memory
    │                       │                          │
    │                       │── stream WAL bytes ─────▶│
    │                       │                          │── apply WAL
    │                       │                          │   to local
    │◀── COMMIT ACK ────────│                          │   copy
    │                       │                          │
    
  KEY QUESTION: When does the leader send COMMIT ACK?
  → BEFORE or AFTER the follower confirms?
  → This is the sync vs async decision.
```

---

### 2.3 — Synchronous vs Asynchronous vs Semi-Synchronous

This is where Week 3's PACELC theory becomes concrete.

#### Synchronous Replication

```
  Client          Leader           Follower
    │                │                 │
    │── WRITE ──────▶│                 │
    │                │── WAL stream ──▶│
    │                │                 │── apply
    │                │◀── ACK ─────────│
    │◀── COMMIT ─────│                 │
    │                │                 │
    
  Leader waits for follower ACK before confirming to client.
  
  GUARANTEES:
  ✓ Zero data loss on leader failure (RPO = 0)
  ✓ Follower is always caught up
  ✓ Failover loses ZERO committed transactions
  
  COSTS:
  ✗ Write latency = leader_time + network_RTT + follower_apply
  ✗ If follower is slow/dead → leader BLOCKS
  ✗ Availability depends on follower health
  
  PACELC: PC/EC — sacrifices latency AND availability for consistency
```

#### Asynchronous Replication

```
  Client          Leader           Follower
    │                │                 │
    │── WRITE ──────▶│                 │
    │◀── COMMIT ─────│                 │
    │                │── WAL stream ──▶│  (later)
    │                │                 │── apply
    │                │                 │
    
  Leader commits IMMEDIATELY. Streams WAL to follower later.
  
  GUARANTEES:
  ✓ Low write latency (leader-only)
  ✓ Leader never blocks on follower
  ✓ Follower failure doesn't affect writes
  
  COSTS:
  ✗ REPLICATION LAG — follower is behind by milliseconds to seconds
  ✗ Leader failure LOSES uncommitted-to-follower transactions
  ✗ RPO > 0 (you lose the lag window)
  ✗ Reads from follower may be STALE
  
  PACELC: PA/EL — sacrifices consistency for latency and availability
```

**This is exactly Alice's trade from Week 3.** The EU-West replica was async, fell behind, served a stale balance, and Alice overdrew by $120K. That's async replication lag made concrete.

#### Semi-Synchronous (the production sweet spot)

```
  ╔══════════════════════════════════════════════════════════════╗
  ║   SEMI-SYNCHRONOUS                                           ║
  ╟──────────────────────────────────────────────────────────────╢
  ║                                                              ║
  ║   Leader          F1 (sync)        F2 (async)                ║
  ║     │                │                 │                     ║
  ║     │── WAL ────────▶│                 │                     ║
  ║     │                │── apply         │                     ║
  ║     │◀── ACK ────────│                 │                     ║
  ║     │── COMMIT ──▶ client             │                      ║
  ║     │── WAL ──────────────────────────▶│ (async)             ║
  ║     │                │                 │                     ║
  ║                                                              ║
  ║   ONE follower is synchronous. Rest are async.               ║
  ║   If the sync follower dies → promote an async one           ║
  ║   to sync. This is "semi-synchronous."                       ║
  ║                                                              ║
  ║   PostgreSQL: synchronous_standby_names = 'FIRST 1 (*)'      ║
  ║   MySQL: rpl_semi_sync_master_wait_for_slave_count = 1       ║
  ║                                                              ║
  ║   GUARANTEES:                                                ║
  ║   ✓ At least TWO copies before COMMIT (leader + 1)           ║
  ║   ✓ Leader failure → sync follower has ALL data              ║
  ║   ✓ If sync follower dies → auto-switch to another           ║
  ║   ✓ Write latency = leader + ONE follower only               ║
  ║                                                              ║
  ║   COSTS:                                                     ║
  ║   ✗ Write latency > pure async (by 1 network RTT)            ║
  ║   ✗ If ALL followers die → leader blocks or                  ║
  ║     downgrades to async (configurable)                       ║
  ║                                                              ║
  ║   PACELC: PC/EL — consistent during partition,               ║
  ║     but optimizes for latency in normal operation            ║
  ║     because only ONE sync follower (not all)                 ║
  ╚══════════════════════════════════════════════════════════════╝
```

**The comparison matrix:**

```
╔══════════════════════════════════════════════════════════════╗
║               │  SYNC    │  ASYNC    │  SEMI-SYNC            ║
╠══════════════════════════════════════════════════════════════╣
║  Data loss on │  ZERO    │  YES      │  ZERO                 ║
║  leader fail  │          │  (lag     │  (if sync             ║
║               │          │   window) │   follower up)        ║
╠══════════════════════════════════════════════════════════════╣
║  Write latency│  HIGH    │  LOW      │  MEDIUM               ║
║               │ (all     │ (leader   │ (leader + 1)          ║
║               │  nodes)  │  only)    │                       ║
╠══════════════════════════════════════════════════════════════╣
║  Availability │  LOW     │  HIGH     │  MEDIUM-HIGH          ║
║  during node  │ (blocks  │ (keeps    │ (auto-switch          ║
║  failure      │  writes) │  writing) │  sync target)         ║
╠══════════════════════════════════════════════════════════════╣
║  Read staleness│ NONE    │  YES      │  NONE from sync,      ║
║               │          │           │  YES from async       ║
╠══════════════════════════════════════════════════════════════╣
║  PACELC      │  PC/EC   │  PA/EL    │  PC/EL                 ║
╠══════════════════════════════════════════════════════════════╣
║  Use when    │ Financial│ Analytics,│ MOST production        ║
║              │ ledger,  │ read      │ databases.             ║
║              │ inventory│ replicas, │ Default choice.        ║
║              │ counts   │ CDN origin│                        ║
╚══════════════════════════════════════════════════════════════╝
```

---

### 2.4 — The Replication Stream: WAL vs Logical vs CDC

There are fundamentally different ways to transmit changes from leader to follower:

#### Physical (WAL-based) Replication

```
  ╔══════════════════════════════════════════════════════════════╗
  ║   PHYSICAL REPLICATION (PostgreSQL streaming repl.)          ║
  ╟──────────────────────────────────────────────────────────────╢
  ║                                                              ║
  ║   Leader writes WAL (Write-Ahead Log):                       ║
  ║   ╭──────────────────────────────────────────────────╮       ║
  ║   │ LSN: 0/16B3780  XID: 5023                        │       ║
  ║   │ Type: HEAP_INSERT                                │       ║
  ║   │ Table OID: 16385  Block: 42  Offset: 3           │       ║
  ║   │ Data: \x00000001 \x48656C6C6F...                 │       ║
  ╚══════════════════════════════════════════════════════════════╝
  │                                                        │
  │  This is BYTE-LEVEL. Block 42, offset 3.               │
  │  Follower replays exact same bytes to exact same       │
  │  locations on disk.                                    │
  │                                                        │
  │  REQUIREMENTS:                                         │
  │  → Same PostgreSQL major version (byte format matches) │
  │  → Same architecture (x86 → x86, not x86 → ARM)        │
  │  → Same OS page size                                   │
  │  → Follower is byte-for-byte identical to leader       │
  │                                                        │
  │  PROS:                                                 │
  │  ✓ Fast — just streaming bytes, no parsing             │
  │  ✓ Exact copy — zero divergence possible               │
  │  ✓ Supports PITR (Point In Time Recovery)              │
  │                                                        │
  │  CONS:                                                 │
  │  ✗ Cannot replicate across versions (PG 15 → PG 16)    │
  │  ✗ Cannot replicate across platforms                   │
  │  ✗ Cannot replicate a subset of tables                 │
  │  ✗ Cannot transform data during replication            │
  │  ✗ Follower is 100% read-only (no local indexes)       │
  ╰─────────────────────────────────────────────────────────╯
```

#### Logical Replication

```
  ╔══════════════════════════════════════════════════════════════╗
  ║   LOGICAL REPLICATION (PostgreSQL logical decoding)          ║
  ╟──────────────────────────────────────────────────────────────╢
  ║                                                              ║
  ║   Leader decodes WAL into logical operations:                ║
  ║   ╭───────────────────────────────────────────────────╮      ║
  ║   │ INSERT INTO users (id, name, email)               │      ║
  ║   │ VALUES (1, 'Alice', 'alice@example.com')          │      ║
  ║   │ LSN: 0/16B3780                                    │      ║
  ╚══════════════════════════════════════════════════════════════╝
  │                                                         │
  │  This is ROW-LEVEL. Table name, column values.          │
  │  Follower applies as a logical SQL-like operation.      │
  │                                                         │
  │  REQUIREMENTS:                                          │
  │  → Publication on leader: CREATE PUBLICATION my_pub     │
  │    FOR TABLE users, orders;                             │
  │  → Subscription on follower: CREATE SUBSCRIPTION        │
  │    my_sub CONNECTION '...' PUBLICATION my_pub;          │
  │  → Tables must exist on follower with compatible schema │
  │                                                         │
  │  PROS:                                                  │
  │  ✓ Cross-version (PG 14 → PG 16)                        │
  │  ✓ Cross-platform (x86 → ARM)                           │
  │  ✓ Selective — replicate specific tables only           │
  │  ✓ Follower can have local indexes, extra columns       │
  │  ✓ Follower can receive writes (multi-master possible)  │
  │  ✓ Enables zero-downtime major version upgrades         │
  │                                                         │
  │  CONS:                                                  │
  │  ✗ Slower — decoding + re-applying (not raw bytes)     │
  │  ✗ DDL (schema changes) NOT replicated automatically   │
  │  ✗ Large object support limited                        │
  │  ✗ Sequence values not replicated                      │
  │  ✗ Conflict detection is primitive (errors on conflict)│
  ╰─────────────────────────────────────────────────────────╯
```

#### Change Data Capture (CDC)

```
  ╔══════════════════════════════════════════════════════════════╗
  ║   CHANGE DATA CAPTURE                                        ║
  ╟──────────────────────────────────────────────────────────────╢
  ║                                                              ║
  ║   CDC captures every change as an EVENT and publishes        ║
  ║   it to an external system (usually Kafka).                  ║
  ║                                                              ║
  ║   ╭─────────╮    WAL     ╭──────────╮    ╭─────────╮         ║
  ║   │ Leader  │──────────▶│ Debezium │───▶│  Kafka  │          ║
  ║   │  (PG)   │  logical   │ connector│    │  topic  │         ║
  ╚══════════════════════════════════════════════════════════════╝
  │                                              │         │
  │                    ╔══════════════════════════════════════════════════════════════╗
  │                    ║                     ▼           ▼              ▼             ║
  │                    ║               ╭──────────╮ ╭────────╮  ╭──────────╮          ║
  │                    ║               │ Search   │ │ Cache  │  │ Analytics│          ║
  │                    ║               │ (Elastic)│ │(Redis) │  │ (Spark)  │          ║
  │                    ╚══════════════════════════════════════════════════════════════╝
  │                                                        │
  │  CDC EVENT (Debezium format):                          │
  │  {                                                     │
  │    "op": "c",           // c=create, u=update, d=del   │
  │    "before": null,      // previous state (for u/d)    │
  │    "after": {           // new state                   │
  │      "id": 1,                                          │
  │      "name": "Alice",                                  │
  │      "email": "alice@example.com"                      │
  │    },                                                  │
  │    "source": {                                         │
  │      "lsn": 23456789,  // WAL position                 │
  │      "txId": 5023,     // transaction ID               │
  │      "ts_ms": 1709234567890                            │
  │    }                                                   │
  │  }                                                     │
  │                                                        │
  │  THIS IS HOW YOU SOLVE THE HEALTHCARE SCENARIO.        │
  │  Dr. Chen's allergy cache was stale because cache-     │
  │  aside missed the invalidation. With CDC:              │
  │  → Allergy UPDATE hits PostgreSQL                      │
  │  → Debezium captures WAL change                        │
  │  → Publishes to Kafka topic "allergy-changes"          │
  │  → Cache invalidation consumer DELETES Redis key       │
  │  → Next read goes to DB, gets fresh data               │
  │  → No more stale allergy data in cache                 │
  │                                                        │
  │  PROS:                                                 │
  │  ✓ Decouples DB from downstream consumers              │
  │  ✓ Kafka provides durable, replayable event log        │
  │  ✓ Multiple consumers from single change stream        │
  │  ✓ Search index, cache, analytics all stay in sync     │
  │  ✓ "before" + "after" enables conflict detection       │
  │                                                        │
  │  CONS:                                                 │
  │  ✗ Additional infrastructure (Kafka + connectors)      │
  │  ✗ Eventually consistent (Kafka consumer lag)          │
  │  ✗ Ordering only guaranteed within a partition         │
  │  ✗ Schema evolution coordination across consumers      │
  ╰────────────────────────────────────────────────────────╯
```

**Comparison:**

```
╔════════════════════════════════════════════════════════════════╗
║                 │  PHYSICAL   │  LOGICAL       │  CDC          ║
║                 │  (WAL)      │  (row-level)   │  (events)     ║
╠════════════════════════════════════════════════════════════════╣
║  Unit of repl.  │ Disk blocks │ Row operations │ Change events ║
╠════════════════════════════════════════════════════════════════╣
║  Cross-version  │ NO          │ YES            │ YES           ║
╠════════════════════════════════════════════════════════════════╣
║  Cross-platform │ NO          │ YES            │ YES           ║
╠════════════════════════════════════════════════════════════════╣
║  Selective      │ NO (all)    │ YES (tables)   │ YES (tables)  ║
╠════════════════════════════════════════════════════════════════╣
║  Dest writable  │ NO          │ YES            │ YES (diff DB) ║
╠════════════════════════════════════════════════════════════════╣
║  Speed          │ Fastest     │ Medium         │ Medium        ║
╠════════════════════════════════════════════════════════════════╣
║  Multi-consumer │ NO          │ Limited        │ YES (Kafka)   ║
╠════════════════════════════════════════════════════════════════╣
║  Primary use    │ HA failover │ Version upgrade│ Cache sync,   ║
║                 │ read replica│ selective repl.│ search index, ║
║                 │             │                │ event-driven  ║
╚════════════════════════════════════════════════════════════════╝
```

---

### 2.5 — Replication Lag and Its Consistency Violations

This connects directly to Week 3 Topic 2. Every consistency violation we studied is **caused by replication lag**:

```
╔══════════════════════════════════════════════════════════════╗
║   REPLICATION LAG → CONSISTENCY VIOLATIONS MAP               ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   LAG = 0ms:   Linearizable reads from follower              ║
║   LAG = 5ms:   Usually fine. Most apps never notice.         ║
║   LAG = 100ms: Read-your-writes violations start appearing   ║
║                (user writes, reads from replica, doesn't     ║
║                see own write yet)                            ║
║   LAG = 1s:    Monotonic reads violations if round-robin     ║
║                across replicas with different lag            ║
║   LAG = 5s:    Consistent prefix violations across shards    ║
║                with different replication speeds             ║
║   LAG = 30s+:  Visible to users. Dashboards "stuck."         ║
║                "I updated my profile but it's still showing  ║
║                the old name."                                ║
║   LAG = ∞:     Follower disconnected. Replication broken.    ║
║                                                              ║
║   THE FUNDAMENTAL TENSION:                                   ║
║   → Async replication = high availability + low latency      ║
║   → But lag is UNBOUNDED. It's usually ms, but during:       ║
║     • Follower recovery from crash                           ║
║     • Network congestion                                     ║
║     • Leader under heavy write load                          ║
║     • Long-running queries on follower (PG: recovery         ║
║       conflict → replay paused)                              ║
║     • Vacuum operations                                      ║
║   → Lag can spike from 5ms to 30 seconds with no warning     ║
║                                                              ║
║   THIS IS WHY "EVENTUAL CONSISTENCY" IS DANGEROUS:           ║
║   "Eventually" has NO UPPER BOUND.                           ║
╚══════════════════════════════════════════════════════════════╝
```

**Monitoring replication lag (exact commands):**

```sql
-- PostgreSQL: check replication lag on PRIMARY
SELECT 
  client_addr,
  state,
  sent_lsn,
  write_lsn,
  flush_lsn,
  replay_lsn,
  pg_wal_lsn_diff(sent_lsn, replay_lsn) AS replay_lag_bytes,
  write_lag,      -- time between WAL write on primary and write on replica
  flush_lag,      -- time until replica flushes to disk
  replay_lag      -- time until replica replays the WAL
FROM pg_stat_replication;

-- PostgreSQL: check lag on REPLICA itself
SELECT 
  now() - pg_last_xact_replay_timestamp() AS replication_delay;
-- WARNING: this is misleading during low-write periods
-- (no new transactions → timestamp doesn't advance → looks lagged)

-- MySQL: check replica lag
SHOW REPLICA STATUS\G
-- Key field: Seconds_Behind_Source
-- WARNING: this measures lag of CURRENT event being applied,
-- not the most recent event. Misleading during large transactions.

-- Redis: check replication
INFO replication
# role:master
# connected_slaves:2
# slave0:ip=10.0.1.2,port=6379,state=online,offset=123456,lag=0
# slave1:ip=10.0.1.3,port=6379,state=online,offset=123400,lag=1
# The "offset" difference tells you exact bytes behind.
# "lag" is seconds since last ACK.
```

---

### 2.6 — Topology 2: Multi-Leader (Multi-Master)

```
  ╔══════════════════════════════════════════════════════════════╗
  ║   MULTI-LEADER REPLICATION                                   ║
  ╟──────────────────────────────────────────────────────────────╢
  ║                                                              ║
  ║        US-EAST                         EU-WEST               ║
  ║   ╭──────────────╮               ╭──────────────╮            ║
  ║   │   Leader A   │◀────────────▶│   Leader B   │             ║
  ║   │  (reads +    │  async cross- │  (reads +    │            ║
  ║   │   writes)    │  replication  │   writes)    │            ║
  ╚══════════════════════════════════════════════════════════════╝
  │         │                              │                  │
  │    ╔══════════════════════════════════════════════════════════════╗
  │    ║     │ F1 │ F2 │                    │ F3 │ F4 │               ║
  │    ╚══════════════════════════════════════════════════════════════╝
  │                                                           │
  │  RULES:                                                   │
  │  → Multiple nodes accept writes                           │
  │  → Each leader replicates to others asynchronously        │
  │  → Each leader may also have its own followers            │
  │                                                           │
  │  WHEN TO USE:                                             │
  │  ✓ Multi-datacenter operation (writes in every DC)        │
  │  ✓ Offline operation (laptop/mobile writes locally,       │
  │    syncs later — CouchDB, Google Docs)                    │
  │  ✓ Collaborative editing                                  │
  │                                                           │
  │  THE BIG PROBLEM: WRITE CONFLICTS                         │
  ╰───────────────────────────────────────────────────────────╯
```

**Write Conflicts — The Fundamental Problem:**

```
  Timeline:
  
  T=0    User A in US writes: UPDATE users SET name='Alice'  WHERE id=1
  T=0    User B in EU writes: UPDATE users SET name='Alicia' WHERE id=1
  
  T=1    US leader has name='Alice'
         EU leader has name='Alicia'
  
  T=2    Cross-replication delivers both writes to both leaders.
         
         US leader sees: local='Alice', incoming='Alicia'  → CONFLICT
         EU leader sees: local='Alicia', incoming='Alice'  → CONFLICT
         
  BOTH leaders must resolve to the SAME value.
  Otherwise they permanently diverge. (Split-brain at the row level.)
```

**Conflict Resolution Strategies:**

```
╔══════════════════════════════════════════════════════════════╗
║   1. LAST-WRITER-WINS (LWW)                                  ║
║      → Attach timestamp to every write                       ║
║      → Higher timestamp wins, lower is silently DISCARDED    ║
║      → Simple. But: clock skew → data loss.                  ║
║      → Cassandra DEFAULT. DynamoDB with timestamps.          ║
║      → DANGEROUS for anything where both writes matter       ║
║        (e.g., two different items added to a cart)           ║
║                                                              ║
║   2. MERGE VALUES                                            ║
║      → For specific data types: union sets, max counters     ║
║      → Shopping cart: union both items = {A_item, B_item}    ║
║      → Counter: CRDT (Conflict-free Replicated Data Type)    ║
║      → Requires data-type-specific merge functions           ║
║                                                              ║
║   3. CUSTOM APPLICATION LOGIC                                ║
║      → Database stores ALL conflicting versions              ║
║      → Application reads all versions, presents to user      ║
║      → User resolves (or app applies business rules)         ║
║      → CouchDB: stores "conflict" flag on document           ║
║      → Most flexible, most engineering effort                ║
║                                                              ║
║   4. CONFLICT AVOIDANCE (best strategy)                      ║
║      → Route all writes for a given entity to ONE leader     ║
║      → User X always writes to US-East leader                ║
║      → User Y always writes to EU-West leader                ║
║      → No conflicts because same entity never written        ║
║        to two leaders simultaneously                         ║
║      → Breaks if user moves regions or leader fails          ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

**Multi-leader topology shapes:**

```
  CIRCULAR:                    STAR:                ALL-TO-ALL:
  
  A ──▶ B                   A ──▶ B                A ◀──▶ B
  ▲     │                   ▲  ╱  │                │ ╲  ╱ │
  │     ▼                   │ ╱   ▼                │  ╲╱  │
  D ◀── C                   D ◀── C                D ◀──▶ C
  
  Problem: single           Problem: hub            Best:
  node failure              failure breaks           redundant
  breaks the ring           everything               paths
  
  Production: avoid circular and star. Use all-to-all.
  But all-to-all has causality ordering issues
  (Update may arrive before the Insert it depends on).
```

**PACELC classification of multi-leader:**

```
Multi-leader is PA/EL:
→ During partition: each leader keeps accepting writes (Available)
→ Else: low latency (local writes, async cross-replication)
→ Consistency is sacrificed: conflicts must be resolved after the fact
```

---

### 2.7 — Topology 3: Leaderless Replication

```
  ╔══════════════════════════════════════════════════════════════╗
  ║   LEADERLESS REPLICATION (Dynamo-style)                      ║
  ╟──────────────────────────────────────────────────────────────╢
  ║                                                              ║
  ║   Used by: Cassandra, DynamoDB, Riak, Voldemort              ║
  ║                                                              ║
  ║        Client                                                ║
  ║       ╱  │  ╲           No single leader.                    ║
  ║      ▼   ▼   ▼          Client writes to MULTIPLE nodes.     ║
  ║    ╭───╮╭───╮╭───╮      Client reads from MULTIPLE nodes.    ║
  ║    │ A ││ B ││ C │      Quorum determines success.           ║
  ╚══════════════════════════════════════════════════════════════╝
  │                                                           │
  │  WRITE: send to ALL N replicas.                           │
  │         Consider success when W acknowledge.              │
  │                                                           │
  │  READ: send to ALL N replicas.                            │
  │        Take value with highest version from R responses.  │
  │                                                           │
  │  QUORUM CONDITION: R + W > N                              │
  │  → Guarantees at least ONE node has latest write          │
  │  → With N=3, W=2, R=2: always overlap of ≥1 fresh node    │
  │                                                           │
  │    WRITE (W=2)        READ (R=2)                          │
  │    ╔══════════════════════════════════════════════════════════════╗
  │    ║     │ A │ ✓ (ack)      │ A │ v2 ✓ (latest)                   ║
  │    ║     ├───┤              ├───┤                                 ║
  │    ║     │ B │ ✓ (ack)      │ B │ v1 (stale)                      ║
  │    ║     ├───┤              ├───┤                                 ║
  │    ║     │ C │ ✗ (timeout)  │ C │ (not queried, R=2 satisfied)    ║
  │    ╚══════════════════════════════════════════════════════════════╝
  │                                                           │
  │    Client reads A(v2) and B(v1). Returns v2 (highest).    │
  │    Optionally triggers READ REPAIR on B.                  │
  │                                                           │
  ╰───────────────────────────────────────────────────────────╯
```

**Quorum math — the tuning knobs:**

```
  N = total replicas (typically 3 or 5)
  W = write acknowledgments required
  R = read acknowledgments required
  
  ╔══════════════════════════════════════════════════════════════╗
  ║  Config │ W │ R │ Properties                                 ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  Strong │ 2 │ 2 │ R+W=4 > 3=N. Guaranteed overlap.           ║
  ║  reads  │   │   │ Trades latency for consistency.            ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  Fast   │ 3 │ 1 │ R+W=4 > 3=N. Still overlaps!               ║
  ║  reads  │   │   │ Writes slow (all 3). Reads fast (1).       ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  Fast   │ 1 │ 3 │ R+W=4 > 3=N. Still overlaps.               ║
  ║  writes │   │   │ Writes fast (1). Reads slow (3).           ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  Even-  │ 1 │ 1 │ R+W=2 < 3=N. NO OVERLAP.                   ║
  ║  tual   │   │   │ Fast but may read stale data.              ║
  ║         │   │   │ This is Cassandra CL=ONE.                  ║
  ╠══════════════════════════════════════════════════════════════╣
  ║  W=N    │ 3 │ 1 │ R+W=4 > N. But W=N means ANY node          ║
  ║         │   │   │ failure blocks ALL writes. Avoid.          ║
  ╚══════════════════════════════════════════════════════════════╝
  
  IMPORTANT CAVEAT: R+W>N does NOT guarantee linearizability!
  It guarantees you READ the latest write, but:
  → Concurrent writes may be partially visible
  → Sloppy quorums (hinted handoff) break the overlap
  → Network delays mean "latest" is ambiguous
  
  For linearizability in leaderless: need read-repair +
  anti-entropy + NO sloppy quorum — and even then it's
  tricky. Cassandra with QUORUM is "strong" but not
  linearizable in the formal sense.
```

**Anti-entropy mechanisms (how stale nodes catch up):**

```
╔═══════════════════════════════════════════════════════════════╗
║   1. READ REPAIR (on-read)                                    ║
║      → During a quorum read, client detects stale replica     ║
║      → Client writes latest value BACK to stale node          ║
║      → Fixes staleness lazily, only for data being read       ║
║      → Cold data never gets repaired                          ║
║                                                               ║
║   2. HINTED HANDOFF (during write)                            ║
║      → Node C is down during write                            ║
║      → Coordinator stores "hint" for C's data on Node A       ║
║      → When C comes back, A sends hints to C                  ║
║      → C catches up without full anti-entropy                 ║
║      → WARNING: "sloppy quorum" — hint stored on a node       ║
║        that's NOT one of the N designated replicas.           ║
║        R+W>N no longer guarantees overlap!                    ║
║                                                               ║
║   3. ANTI-ENTROPY REPAIR (background)                         ║
║      → Full comparison of data across replicas                ║
║      → Cassandra: Merkle tree comparison (hash tree)          ║
║        → Hash all data on each replica into a tree            ║
║        → Compare tree roots → drill into branches that differ ║
║        → Only transfer differing data                         ║
║      → Expensive. Run periodically (gc_grace_seconds).        ║
║      → In Cassandra: nodetool repair                          ║
║      → If you don't run repair within gc_grace_seconds        ║
║        (default 10 days), tombstones get deleted and          ║
║        deleted data REAPPEARS ("zombie data")                 ║
╚═══════════════════════════════════════════════════════════════╝
```

---

### 2.8 — Failover: The Hardest Part of Replication

Failover in leader-follower replication is where most production incidents live.

```
╔══════════════════════════════════════════════════════════════╗
║   FAILOVER SEQUENCE (leader-follower)                        ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   1. DETECT leader is dead                                   ║
║      → Heartbeat timeout (typically 10-30 seconds)           ║
║      → Problem: slow leader ≠ dead leader                    ║
║      → Too aggressive: false failovers (split-brain)         ║
║      → Too conservative: long downtime                       ║
║                                                              ║
║   2. CHOOSE new leader                                       ║
║      → Most up-to-date replica (least replication lag)       ║
║      → PostgreSQL: pg_wal_lsn_diff comparison                ║
║      → MySQL: GTID position comparison                       ║
║      → MongoDB: Raft-like election among replica set members ║
║                                                              ║
║   3. RECONFIGURE system                                      ║
║      → Clients must send writes to new leader                ║
║      → Old followers must follow new leader                  ║
║      → Virtual IP (VIP) or DNS update points to new leader   ║
║      → Connection pools must reconnect                       ║
║                                                              ║
║   4. HANDLE old leader                                       ║
║      → When old leader comes back, it MUST become follower   ║
║      → If it thinks it's still leader → SPLIT-BRAIN          ║
║      → STONITH: "Shoot The Other Node In The Head"           ║
║        (fence the old leader before promoting new one)       ║
║      → AWS: revoke old primary's EBS volumes                 ║
╚══════════════════════════════════════════════════════════════╝
```

**What goes wrong during failover:**

```
╭──────────────────────────────────────────────────────────────╮
│  FAILOVER FAILURE MODE 1: DATA LOSS                          │
│                                                              │
│  Async replication. Leader had writes not yet replicated.    │
│  Leader dies. New leader promoted from behind replica.       │
│  Those writes are PERMANENTLY LOST.                          │
│                                                              │
│  Example: GitHub 2018 incident                               │
│  → MySQL primary in US-East became unreachable               │
│  → Promoted US-West replica that was seconds behind          │
│  → Auto-increment IDs on new primary overlapped with         │
│    IDs from lost transactions on old primary                 │
│  → Webhooks fired for wrong repositories                     │
│  → Required manual data reconciliation                       │
│                                                              │
│  Mitigation: semi-sync replication. Or accept the data loss  │
│  window and design for it (idempotent writes, reconciliation)│
├──────────────────────────────────────────────────────────────┤
│  FAILOVER FAILURE MODE 2: SPLIT-BRAIN                        │
│                                                              │
│  Old leader comes back thinking it's still leader.           │
│  Two nodes accept writes simultaneously.                     │
│  Data diverges permanently.                                  │
│                                                              │
│  ╔══════════════════════════════════════════════════════════════╗
│  ║   │ Old     │  "I'm the leader!" │ New     │                 ║
│  ║   │ Leader  │←── writes ──╮      │ Leader  │                 ║
│  ║   │ (back   │             │      │(promoted│ ←── writes      ║
│  ║   │  online)│             │      │  while  │                 ║
│  ╚══════════════════════════════════════════════════════════════╝
│                     still point │  down)   │                 │
│                     here        ╰─────────╯                  │
│                                                              │
│  Mitigation: fencing tokens, STONITH, epoch numbers          │
│  → New leader gets epoch E+1                                 │
│  → Storage rejects writes with epoch ≤ E                     │
│  → Even if old leader sends writes, they're rejected         │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│  FAILOVER FAILURE MODE 3: CASCADING FAILURES                 │
│                                                              │
│  This is the connection to your growth area.                 │
│                                                              │
│  Scenario: Leader fails. New leader promoted. All read       │
│  replicas AND application servers reconnect simultaneously.  │
│  → New leader's connection pool: max_connections = 500       │
│  → 12 app servers × 50 connections each = 600                │
│  → Exceeds max_connections → connection refused errors       │
│  → App servers retry aggressively → thundering herd          │
│  → New leader overloaded before it serves a single query     │
│                                                              │
│  THIS IS CAPACITY VERIFICATION BEFORE FAILOVER.              │
│  Before promoting: is the new leader sized to handle         │
│  the full write load + reconnection storm?                   │
│                                                              │
│  Mitigation: connection pooler (PgBouncer) between apps      │
│  and DB, exponential backoff on reconnection, gradual        │
│  traffic shift, pre-provisioned capacity.                    │
├──────────────────────────────────────────────────────────────┤
│  FAILOVER FAILURE MODE 4: CLIENT CACHE STALE LEADER          │
│                                                              │
│  DNS TTL or client-side connection cache still points to     │
│  old leader. Writes go to demoted node → fail silently       │
│  or return errors.                                           │
│                                                              │
│  Mitigation: low DNS TTL before maintenance, health check    │
│  on write path (verify "am I writing to actual leader?"),    │
│  pg_is_in_recovery() check on connection.                    │
╰──────────────────────────────────────────────────────────────╯
```

---

### 2.9 — Putting It All Together: Which Topology When?

```
╔═══════════════════════════════════════════════════════════════╗
║   TOPOLOGY         │  USE WHEN                                ║
╠═══════════════════════════════════════════════════════════════╣
║   Single-leader    │  DEFAULT CHOICE. Strong consistency      ║
║   (leader-follower)│  needed. Single DC or low cross-DC       ║
║                    │  write latency acceptable. Most apps.    ║
║                    │  PostgreSQL, MySQL, MongoDB, Redis.      ║
╠═══════════════════════════════════════════════════════════════╣
║   Multi-leader     │  Multi-DC writes required AND eventual   ║
║                    │  consistency acceptable AND you have     ║
║                    │  conflict resolution strategy.           ║
║                    │  CouchDB, Postgres BDR, collaborative    ║
║                    │  editing tools.                          ║
║                    │  AVOID unless you truly need it —        ║
║                    │  conflict resolution is HARD.            ║
╠═══════════════════════════════════════════════════════════════╣
║   Leaderless       │  High availability paramount.            ║
║   (Dynamo-style)   │  Write to any node. Tunable consistency. ║
║                    │  Cassandra, DynamoDB, Riak.              ║
║                    │  Best for: time series, IoT, counters,   ║
║                    │  sensor data, activity feeds.            ║
║                    │  Not for: banking, inventory, anything   ║
║                    │  needing strong consistency.             ║
╚═══════════════════════════════════════════════════════════════╝
```

---

## 3. Production Patterns & Failure Modes

```
╔══════════════════════════════════════════════════════════════╗
║   PATTERN 1: READ REPLICA PROMOTION CHAIN                    ║
║                                                              ║
║   Production setup:                                          ║
║   Primary → Sync standby → 3 async read replicas             ║
║                                                              ║
║   Primary dies →                                             ║
║     Sync standby promoted (zero data loss) →                 ║
║     One async replica promoted to new sync standby →         ║
║     Remaining 2 async replicas re-pointed to new primary     ║
║                                                              ║
║   This is PostgreSQL Patroni / pg_auto_failover pattern.     ║
║   Tools: Patroni, pg_auto_failover, repmgr                   ║
║   In AWS: RDS Multi-AZ does this automatically.              ║
║                                                              ║
╠══════════════════════════════════════════════════════════════╣
║   PATTERN 2: CASCADING REPLICATION                           ║
║                                                              ║
║   Primary → Replica1 → Replica2 → Replica3                   ║
║                                                              ║
║   Why: reduce load on primary (only streams to 1 follower)   ║
║   Risk: Replica1 fails → Replica2 and Replica3 stop          ║
║          receiving updates. Increased lag, potential         ║
║          data loss.                                          ║
║   PostgreSQL: primary_conninfo can point to another replica  ║
║                                                              ║
╠══════════════════════════════════════════════════════════════╣
║   PATTERN 3: DELAYED REPLICA                                 ║
║                                                              ║
║   PostgreSQL: recovery_min_apply_delay = '1h'                ║
║   MySQL: CHANGE REPLICATION SOURCE TO SOURCE_DELAY = 3600    ║
║                                                              ║
║   Intentionally 1 hour behind. Why?                          ║
║   → "Oh no, someone ran DROP TABLE in production"            ║
║   → Switch to delayed replica that hasn't applied it yet     ║
║   → Recover data from before the DROP                        ║
║   → Cheaper than PITR from backup                            ║
║   → THIS is your "human error" safety net                    ║
║                                                              ║
╠══════════════════════════════════════════════════════════════╣
║   PATTERN 4: CROSS-REGION REPLICATION                        ║
║                                                              ║
║   Primary in us-east-1 → Async replica in eu-west-1          ║
║   → Network RTT: ~80ms (transatlantic)                       ║
║   → Sync replication across regions is usually unacceptable  ║
║     (doubles write latency from ~5ms to ~85ms)               ║
║   → Async means eu-west-1 reads are ~80ms+ behind            ║
║   → For reads only! Writes still go to primary.              ║
║   → Exception: Google Spanner uses GPS+atomic clocks to      ║
║     achieve synchronous cross-region with bounded latency    ║
║                                                              ║
║   Alice's $120K overdraft scenario was EXACTLY this:         ║
║   async cross-region replication with stale read.            ║
╚══════════════════════════════════════════════════════════════╝
```

---

## 4. Hands-On Exercise

```
╔══════════════════════════════════════════════════════════════╗
║   EXERCISE: Observe Replication Lag in Real Time             ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   Option A: PostgreSQL (Docker)                              ║
║                                                              ║
║   # Start primary + replica with docker-compose              ║
║   # (Use bitnami/postgresql with REPLICATION_MODE)           ║
║                                                              ║
║   # On primary:                                              ║
║   psql -c "CREATE TABLE test (id serial, val text, ts        ║
║            timestamp default now());"                        ║
║                                                              ║
║   # Monitor lag on primary:                                  ║
║   watch -n 0.5 "psql -c \"SELECT client_addr,                ║
║     pg_wal_lsn_diff(sent_lsn, replay_lsn) as lag_bytes,      ║
║     replay_lag FROM pg_stat_replication;\""                  ║
║                                                              ║
║   # Generate write load:                                     ║
║   pgbench -c 10 -j 2 -T 60 -f <(echo "INSERT INTO test       ║
║     (val) VALUES (md5(random()::text));") mydb               ║
║                                                              ║
║   # Watch lag_bytes and replay_lag spike under load.         ║
║                                                              ║
║   # On replica, simulate slow query blocking replay:         ║
║   psql -c "BEGIN; SELECT pg_sleep(30); SELECT count(*)       ║
║            FROM test; COMMIT;"                               ║
║   # Watch replay_lag grow because recovery is blocked        ║
║   # by the long-running query (recovery conflict).           ║
║                                                              ║
║   # Check hot_standby_feedback and                           ║
║   # max_standby_streaming_delay interaction.                 ║
║                                                              ║
║   Option B: Redis                                            ║
║                                                              ║
║   redis-server --port 6379 &                                 ║
║   redis-server --port 6380 --replicaof 127.0.0.1 6379 &      ║
║                                                              ║
║   # Monitor:                                                 ║
║   redis-cli -p 6379 INFO replication                         ║
║   # Check: master_repl_offset vs slave offset                ║
║                                                              ║
║   # Write load:                                              ║
║   redis-benchmark -p 6379 -n 100000 -c 50 SET __rand_key__   ║
║     __rand_val__                                             ║
║                                                              ║
║   # Watch offset difference grow under load.                 ║
╚══════════════════════════════════════════════════════════════╝
```

---

## 5. SRE Scenario

### Scenario: E-Commerce Flash Sale — Replication Meltdown

```
SETUP:
━━━━━━
Your e-commerce platform is running a flash sale. 
Architecture:
  → PostgreSQL primary (us-east-1a) — all writes
  → Semi-sync standby (us-east-1b) — failover target
  → 3 async read replicas (us-east-1a, 1b, 1c) — read traffic
  → PgBouncer in front of each, max 200 server connections each
  → Application: 24 servers, connection pool of 20 each = 480 total
  → Read traffic split: 85% to read replicas, 15% to primary
  → Redis cache in front for product catalog (cache-aside, TTL 300s)

NORMAL STATE:
  → Write throughput: 3,200 TPS
  → Replication lag: 2-5ms
  → Read replica query time: p99 = 12ms

THE INCIDENT (cascading):
━━━━━━━━━━━━━━━━━━━━━━━━━
12:00:00 — Flash sale begins. Write TPS spikes to 8,100.
12:00:45 — Replication lag on async replicas grows to 800ms.
12:01:30 — An analyst's long-running query on replica-2 
           causes recovery conflict. PostgreSQL cancels 
           the query (max_standby_streaming_delay = 30s 
           exceeded) but replica-2's lag is now 14 seconds.
12:02:00 — Customers see: "Added item to cart but cart 
           shows empty" (reads hitting lagged replicas).
12:02:30 — Engineering enables "read from primary" for 
           cart reads as a hotfix.
12:02:45 — Primary connection pool (PgBouncer) saturates.
           200 connections fully utilized. New connections 
           queued. Query latency p99 jumps to 2,400ms.
12:03:15 — Semi-sync standby can't keep up with 8,100 TPS.
           synchronous_commit starts blocking. Write 
           latency goes from 5ms to 340ms.
12:03:45 — Application health checks start failing 
           (timeout = 500ms). Kubernetes kills pods and 
           restarts them.
12:04:00 — Restarting pods cause connection storm against 
           PgBouncer. PgBouncer itself crashes (too many 
           pending connections in queue, server_lifetime 
           exceeded for pooled connections).
12:04:15 — With PgBouncer down on primary, app servers 
           attempt DIRECT connections to PostgreSQL.
           max_connections = 300. 480 app connections 
           attempted. "FATAL: too many connections."
12:04:30 — ALERTS FIRING EVERYWHERE. Primary effectively 
           unreachable. Writes failing. Reads failing.
           Flash sale revenue dropping at $47K/minute.
```

**Questions:**

**Q1:** Trace the exact cascade chain. What was the TRIGGER, what were the AMPLIFIERS, and what was the critical mistake that turned a manageable replication lag event into a full platform outage?

**Q2:** At 12:02:30, engineering redirected cart reads to primary. Evaluate this decision. What should they have checked BEFORE doing this, and what would you have done instead?

**Q3:** The semi-sync standby started blocking writes at 12:03:15. You have two options:
- (A) Switch synchronous_commit to `local` (downgrade to async)
- (B) Switch synchronous_commit to `remote_write` (fsync not required on standby)

Explain the durability implications of each. Which do you choose and why?

**Q4:** It's 12:04:30. You're the on-call engineer. Write your IMMEDIATE mitigation plan (first 10 minutes). Include exact commands or config changes. Be specific about the ORDER and explain why that order matters.

**Q5:** Design the post-mortem architecture changes that would prevent this cascade. For each change, identify which link in the cascade chain it breaks.

---

## 6. Targeted Reading

```
DDIA Chapter 5: Replication (pp 151-197)
  → pp 152-160: Leaders and Followers — read carefully,
    compare with the three topologies taught here
  → pp 161-167: Problems with Replication Lag — this is
    the section that maps directly to consistency violations
    (read-your-writes, monotonic reads, consistent prefix)
  → pp 168-176: Multi-Leader Replication — focus on
    conflict resolution strategies
  → pp 177-191: Leaderless Replication — quorum math,
    sloppy quorums, hinted handoff, anti-entropy
  → pp 192-197: Summary

DDIA Chapter 9: pp 348-352 (if not already read)
  → Fencing tokens and split-brain prevention
```

---

## 7. Key Takeaways

```
1. Replication scales READS, not writes. For write scaling,
   you need partitioning/sharding (next topic).

2. Sync vs async is a PACELC tradeoff: sync = PC/EC (safe but
   slow), async = PA/EL (fast but stale), semi-sync = the
   production sweet spot (one guaranteed copy + fast).

3. Multi-leader solves cross-region write latency but CREATES
   conflict resolution problems. Avoid unless you truly need it.
   Conflict avoidance > conflict resolution.

4. Leaderless (Dynamo-style) quorum math: R+W>N for overlap.
   But quorum ≠ linearizability. Sloppy quorums break even the
   overlap guarantee. Hinted handoff is a convenience, not a
   consistency mechanism.

5. Failover is where replication goes wrong: data loss (async lag),
   split-brain (two leaders), cascade (connection storms),
   stale routing (DNS/client cache). Every failover plan needs
   fencing, capacity verification, and connection management.
```

---

Your turn on the scenario questions whenever you're ready.

# Scenario: E-Commerce Flash Sale — Replication Meltdown

---

## Q1: Cascade Chain Analysis

### The Trigger

```
TRIGGER: Flash sale write TPS spike from 3,200 → 8,100 
(2.53x increase).

This is the ONLY external event. Everything else is 
a consequence of infrastructure that wasn't sized or 
configured for this load.

The 8,100 TPS alone is NOT catastrophic. PostgreSQL 
can handle this write volume. The trigger becomes 
dangerous only because the infrastructure has no 
isolation between failure domains.
```

### The Amplifiers

```
AMPLIFIER 1: Analyst's long-running query on replica-2
  [12:01:30]
  
  Replica-2 is applying WAL records to stay in sync. 
  The analyst's query holds a snapshot that conflicts 
  with WAL replay (the query needs rows that WAL replay 
  wants to modify/delete). PostgreSQL's recovery conflict 
  resolution: after max_standby_streaming_delay (30s), 
  it CANCELS the query — but during those 30 seconds, 
  WAL replay was PAUSED on replica-2. Lag accumulates.
  
  After cancellation, replica-2 must replay 30 seconds 
  of accumulated WAL at 8,100 TPS. That's ~243,000 
  transactions to catch up, while new writes keep 
  arriving. Replica-2's lag grows to 14 seconds and 
  stays high.
  
  This didn't cause the outage, but it removed 1/3 
  of the read replica capacity at the worst possible 
  moment. The remaining 2 replicas absorb replica-2's 
  share of read traffic, increasing their load.

AMPLIFIER 2: "Read from primary" hotfix for cart reads
  [12:02:30]
  
  This is the CRITICAL MISTAKE. Detailed in Q2.
  Redirecting 85% of read traffic that was on replicas 
  to the primary overwhelms the primary's connection 
  pool. The primary was already handling 8,100 write 
  TPS + 15% of reads. Adding cart reads (a significant 
  fraction of the 85% read traffic) saturates the 
  200-connection PgBouncer pool.

AMPLIFIER 3: Semi-sync standby falling behind
  [12:03:15]
  
  The semi-sync standby must acknowledge every write 
  before the primary can commit (synchronous_commit = on).
  At 8,100 TPS, the standby's fsync rate can't keep up.
  Each write now blocks waiting for standby ACK.
  Write latency: 5ms → 340ms.
  
  This is a FEEDBACK LOOP: the primary is already 
  overloaded (connection pool saturated), now writes 
  are 68x slower, connections are held 68x longer, 
  pool pressure increases further.

AMPLIFIER 4: Kubernetes health check cascade
  [12:03:45 — 12:04:00]
  
  Health check timeout = 500ms. Write latency = 340ms + 
  queueing delay. Health checks fail → Kubernetes kills 
  pods → pods restart → connection storm.
  
  Each restarting pod creates 20 new connections 
  simultaneously (its connection pool initializes on 
  startup). Multiple pods restarting = thundering herd 
  against PgBouncer.
  
  PgBouncer crashes under the connection storm.

AMPLIFIER 5: Direct connections bypassing PgBouncer
  [12:04:15]
  
  With PgBouncer down, application servers fall back to 
  direct PostgreSQL connections. max_connections=300 but 
  480 connections attempted. "FATAL: too many connections."
  
  The connection pooler was the LAST LINE OF DEFENSE 
  between application connection demand and database 
  capacity. Its failure removes all connection management.
```

### The Critical Mistake

```
THE CRITICAL MISTAKE: Redirecting cart reads to primary 
at 12:02:30 WITHOUT verifying primary capacity.

This is the moment a MANAGEABLE problem (stale cart 
reads — annoying but not fatal) became an UNMANAGEABLE 
one (primary overload → write failures → total outage).

Before the redirect:
  → Primary: handling writes (8,100 TPS) + 15% reads
  → Primary PgBouncer: busy but not saturated
  → Problem: stale cart reads on replicas (UX issue)
  → Revenue impact: LOW (users can refresh, retry)

After the redirect:
  → Primary: handling writes + 15% reads + cart reads
  → Primary PgBouncer: SATURATED (200/200)
  → Problem: ALL writes failing, ALL reads failing
  → Revenue impact: TOTAL ($47K/minute)

The team escalated a UX annoyance into a full outage.

THE CASCADE CHAIN:

  Write TPS spike (TRIGGER)
       │
       ▼
  Replica lag grows to 800ms (EXPECTED under load)
       │
       ├──► Analyst query amplifies replica-2 lag to 14s 
       │    (AMPLIFIER — reduces replica capacity)
       │
       ▼
  Cart reads show stale data (SYMPTOM — annoying, not fatal)
       │
       ▼
  ╔═══════════════════════════════════════════════════╗
  ║ CRITICAL MISTAKE: Route cart reads to primary     ║
  ║ WITHOUT checking primary pool headroom            ║
  ╚═══════════════════════════════════════════════════╝
       │
       ▼
  Primary PgBouncer saturated (CASCADE BEGINS)
       │
       ├──► Semi-sync blocks writes (FEEDBACK LOOP)
       │         │
       │         ▼
       │    Write latency 5ms → 340ms
       │         │
       │         ▼
       │    Health checks fail (timeout 500ms)
       │         │
       │         ▼
       │    Kubernetes kills pods
       │         │
       │         ▼
       │    Connection storm on restart
       │         │
       │         ▼
       │    PgBouncer crashes
       │         │
       │         ▼
       │    Direct connections: "too many connections"
       │         │
       │         ▼
       ╰──► TOTAL OUTAGE
```

---

## Q2: Evaluating the 12:02:30 Decision

### What They Should Have Checked BEFORE Redirecting

```
CHECK 1: PRIMARY PgBouncer POOL UTILIZATION

  SHOW POOLS;  -- on primary PgBouncer
  -- or:
  psql -h pgbouncer-primary -p 6432 pgbouncer \
    -c "SHOW POOLS;"

  Look at:
  → cl_active: active client connections
  → cl_waiting: clients waiting for a server connection
  → sv_active: active server connections (out of 200 max)
  → sv_idle: idle server connections (available headroom)

  If sv_active is already >150/200 (75%+), adding 
  significant read traffic will saturate the pool.
  
  AT 12:02:30, the primary was handling 8,100 write TPS 
  + 15% of reads. With 200 server connections, utilization 
  was likely ~70-80% already. Adding cart reads would push 
  it past 100%.

  THEY DID NOT CHECK THIS.

CHECK 2: WHAT PERCENTAGE OF TOTAL READ TRAFFIC IS CART READS?

  If cart reads are 5% of all reads: redirecting them 
  adds ~4% of total read traffic to the primary. Maybe 
  manageable.
  
  If cart reads are 40% of all reads (likely during a 
  flash sale — users are actively adding to carts): 
  redirecting them adds ~34% of total read traffic to 
  the primary. Definitely not manageable.
  
  They should have computed:
    additional_load = cart_read_tps × avg_query_time
    current_headroom = (200 - sv_active) × (1000 / avg_query_time)
    
    if additional_load > current_headroom:
        DO NOT REDIRECT

CHECK 3: CAN THE REPLICA LAG PROBLEM BE FIXED INSTEAD?

  Replica lag was 800ms on healthy replicas, 14s on 
  replica-2. The 800ms lag is the actual problem for 
  cart reads. Options to fix replica lag directly:
  → Kill the analyst query on replica-2 (immediate)
  → Temporarily increase max_standby_streaming_delay 
    (prevent future conflicts)
  → Do nothing — 800ms lag means the cart will be 
    correct within 800ms on refresh

CHECK 4: IS THIS ACTUALLY A REVENUE-IMPACTING PROBLEM?

  "Cart shows empty" = user added item, refreshed, 
  saw empty cart. This is a read-your-writes violation.
  Annoying, but:
  → The item IS in the cart (write succeeded on primary)
  → Refreshing again (after 800ms replication catches up) 
    shows the correct cart
  → No data loss, no financial impact
  → Support impact: some confused users
  
  This is NOT worth risking the primary's stability.
```

### What I Would Have Done Instead

```
STEP 1: KILL THE ANALYST QUERY [Immediate — 10 seconds]

  The analyst query on replica-2 caused its lag to spike 
  to 14s. Kill it:

  -- On replica-2:
  SELECT pg_terminate_backend(pid) 
  FROM pg_stat_activity 
  WHERE query_start < now() - interval '30 seconds'
    AND state = 'active'
    AND usename = 'analyst_user';

  With the query killed, replica-2 can start catching up.
  At 8,100 TPS, replaying 14 seconds of WAL takes time, 
  but the lag will decrease.

STEP 2: READ-YOUR-WRITES FOR CART ONLY [2-3 minutes]

  Instead of redirecting ALL cart reads to primary, 
  implement targeted read-your-writes:

  After a cart WRITE succeeds on the primary, set a 
  short-lived cookie/session flag:

  async def add_to_cart(user_id, item):
      await primary_db.execute(
          "INSERT INTO cart_items ...", ...
      )
      # Flag this user for primary reads for 3 seconds
      await redis.set(
          f"cart_ryw:{user_id}", "1", ex=3
      )

  async def get_cart(user_id):
      # Check if user recently wrote to cart
      ryw_flag = await redis.get(f"cart_ryw:{user_id}")
      if ryw_flag:
          # This specific user reads from primary (3s window)
          return await primary_db.fetch(
              "SELECT * FROM cart_items WHERE user_id = $1",
              user_id
          )
      # Everyone else reads from replica
      return await replica_db.fetch(
          "SELECT * FROM cart_items WHERE user_id = $1",
          user_id
      )

  EFFECT: Only users who JUST wrote to their cart read 
  from primary, and only for 3 seconds. This is a 
  TINY fraction of total read traffic — maybe 2-5% of 
  cart reads, not 100%.
  
  Primary pool impact: negligible (a few dozen extra 
  reads/sec vs the thousands that the blanket redirect 
  would have added).

STEP 3: IF FEATURE FLAG / CODE CHANGE ISN'T FAST ENOUGH

  Simplest fix: SESSION STICKINESS on replicas.

  Configure the read load balancer to use sticky sessions 
  (hash on user_id). Each user consistently hits the SAME 
  replica. That replica's state only moves forward → 
  monotonic reads guaranteed. The user still experiences 
  up to 800ms delay on the first read after a write, but 
  they never see the cart go backward (items appearing 
  and disappearing).

  This requires ZERO code changes — it's a load balancer 
  config change:

  # HAProxy config for read replicas:
  backend pg_read_replicas
      balance source  # sticky by source IP
      # or: balance uri param(user_id) for HTTP-level stickiness
      server replica1 10.0.1.1:5432 check
      server replica2 10.0.1.2:5432 check
      server replica3 10.0.1.3:5432 check

  Combined with killing the analyst query: replica lag 
  drops back toward 800ms → 2-5ms as replica-2 catches 
  up. Cart reads become fresh within seconds. Problem 
  solved without touching the primary.
```

---

## Q3: Semi-Sync Durability Decision

### Option A: synchronous_commit = local

```
WHAT IT DOES:
  The primary considers a write committed as soon as 
  it's flushed to the PRIMARY's local WAL (fsync on 
  primary). The standby receives the WAL stream 
  asynchronously. The primary does NOT wait for the 
  standby to confirm anything.

DURABILITY IMPLICATIONS:

  SCENARIO: Primary writes transaction T, fsyncs locally, 
  commits, returns ACK to client. Client sees "success."
  
  Primary crashes BEFORE the WAL record reaches the 
  standby.
  
  Standby is promoted. Transaction T is LOST.
  The client received "success" but the transaction 
  doesn't exist on the new primary.

  WINDOW OF DATA LOSS:
  → Every transaction between the standby's last received 
    WAL position and the primary's crash point is lost.
  → At 8,100 TPS with, say, 50ms of network/write lag, 
    that's ~405 transactions per potential failover event.
  → For an e-commerce platform: 405 orders that customers 
    were told "succeeded" but don't exist after failover.
  → These are financial transactions. 405 lost orders = 
    charged customers with no order record. Reconciliation 
    nightmare.

  RECOVERY: Identical to async replication. No durability 
  guarantee beyond the primary's local disk. If the 
  primary's disk is intact after restart, no data loss. 
  If the primary is unrecoverable (disk failure), 
  transactions not yet replicated are permanently lost.
```

### Option B: synchronous_commit = remote_write

```
WHAT IT DOES:
  The primary waits until the standby confirms the WAL 
  data has been WRITTEN to the standby's OS buffer 
  (write() syscall returned). The standby has NOT 
  fsynced to disk yet. The data is in the standby's 
  OS page cache but not guaranteed to be on physical 
  disk.

DURABILITY IMPLICATIONS:

  SCENARIO: Primary writes T, waits for standby to 
  confirm remote_write. Standby writes to OS buffer, 
  sends ACK. Primary commits, returns ACK to client.

  Case 1: Primary crashes. Standby promotes.
  → Data IS on the standby (in OS buffer or fsynced 
    by background process). Transaction T survives.
  → No data loss in this case. ✓

  Case 2: Standby crashes (power loss, kernel panic).
  → OS buffer not fsynced → data in page cache is LOST.
  → But primary still has the data (it fsynced locally).
  → No data loss — primary is the source of truth. ✓

  Case 3: BOTH primary AND standby crash simultaneously.
  → Primary has fsynced locally → data survives on 
    primary's disk.
  → Standby had data in OS buffer only → data lost 
    on standby's disk.
  → When both restart: primary has the data, standby 
    doesn't. Standby re-syncs from primary.
  → No data loss IF primary's disk is intact. ✓

  Case 4: Primary crashes, THEN standby crashes before 
  fsync completes.
  → Primary is down (disk may or may not be recoverable).
  → Standby had data in OS buffer, crashes before fsync.
  → Data lost on BOTH nodes.
  → This is the ONLY data loss scenario for remote_write.
  → Probability: extremely low. Requires two independent 
    failures in rapid succession (primary crash + standby 
    crash before background fsync, which typically 
    completes within 5-30ms).

  WINDOW OF DATA LOSS:
  → Only the narrow window between standby write() and 
    standby fsync() — typically 5-30ms.
  → AND only if both nodes fail in that window.
  → Versus `local`: data loss on ANY primary crash where 
    standby hasn't received the WAL yet (~50ms window, 
    single-node failure sufficient).

PERFORMANCE IMPACT:
  remote_write waits for the standby's write() syscall — 
  which is a memory copy to the OS page cache. This is 
  sub-millisecond (typically 0.1-0.5ms).

  Compare to full synchronous_commit = on:
  → Waits for standby fsync() — physical disk write.
  → 2-10ms for SSD, longer under load.
  → At 8,100 TPS, this is the bottleneck causing 340ms.

  remote_write latency overhead: <1ms (vs 340ms for full sync).
  The standby's background fsync process handles disk 
  writes asynchronously — it doesn't block the primary.
```

### My Choice: Option B (remote_write)

```
REASONING:

                   ╭──────────────┬──────────────┬─────────────╮
                   │ local (A)    │ remote_write │ on (current)│
                   │              │ (B)          │             │
  ╭────────────────┼──────────────┼──────────────┼─────────────┤
  │ Write latency  │ ~2ms         │ ~3ms         │ 340ms       │
  │ overhead       │ (local fsync │ (local fsync │ (standby    │
  │                │  only)       │  + network + │  fsync)     │
  │                │              │  memcpy)     │             │
  ├────────────────┼──────────────┼──────────────┼─────────────┤
  │ Data loss on   │ YES — all    │ NO — standby │ NO — standby│
  │ primary crash  │ transactions │ has data in  │ has data on │
  │ (single node)  │ not yet      │ OS buffer    │ disk        │
  │                │ replicated   │              │             │
  ├────────────────┼──────────────┼──────────────┼─────────────┤
  │ Data loss on   │ YES          │ TINY window  │ NO          │
  │ dual crash     │              │ (both crash  │             │
  │                │              │  within 5-   │             │
  │                │              │  30ms)       │             │
  ├────────────────┼──────────────┼──────────────┼─────────────┤
  │ Throughput     │ Full         │ Nearly full  │ Bottlenecked│
  │ at 8,100 TPS  │              │              │ (blocking)  │
  ╰────────────────┴──────────────┴──────────────┴─────────────╯

  remote_write gives:
  → 99.99%+ of the durability of full sync 
    (only loses data if BOTH nodes crash within 5-30ms)
  → 99%+ of the performance of fully async 
    (~3ms vs ~2ms per write — negligible difference)
  → Resolves the immediate crisis (340ms → ~3ms writes)
  → Standby remains a valid failover target 
    (has all data, just not fsynced yet)

  `local` gives slightly better performance (~1ms less) 
  but opens a real data loss window on any single primary 
  failure. For an e-commerce platform processing financial 
  transactions at $47K/minute, losing 405 orders on a 
  primary crash is unacceptable.

  The tradeoff is clear: remote_write sacrifices ~1ms of 
  latency (vs local) to maintain meaningful replication 
  durability. That's the right trade for financial data.

  COMMAND:
  ALTER SYSTEM SET synchronous_commit = 'remote_write';
  SELECT pg_reload_conf();
  -- No restart required. Takes effect immediately.
  -- Verify: SHOW synchronous_commit;
```

---

## Q4: Immediate Mitigation Plan (12:04:30, First 10 Minutes)

### Situation at 12:04:30

```
STATE:
  → PgBouncer on primary: CRASHED
  → App servers: attempting direct connections → max_connections hit
  → PostgreSQL primary: rejecting new connections (300/300)
  → Semi-sync standby: blocking writes (340ms per write)
  → Health checks: failing → Kubernetes killing pods → connection storms
  → Revenue loss: $47K/minute
  → Flash sale: ongoing, users actively trying to purchase

PRIORITY HIERARCHY:
  1. Stop the bleeding (prevent further cascade)
  2. Restore write capability (revenue)
  3. Restore read capability (user experience)
  4. Stabilize and monitor
```

### Minute 0-1: Stop the Cascade

```
ACTION 1: STOP KUBERNETES FROM KILLING PODS [0:00 — 15 seconds]

  Kubernetes is making everything worse. Every killed pod 
  restarts and creates 20 new connections, amplifying 
  the connection storm. Stop the restart loop:

  # Temporarily increase health check tolerance:
  kubectl patch deployment app-server -n prod --type=json \
    -p='[{"op":"replace","path":"/spec/template/spec/containers/0/livenessProbe/failureThreshold","value":30}]'

  # Or faster — suspend the liveness probe entirely:
  kubectl patch deployment app-server -n prod --type=json \
    -p='[{"op":"remove","path":"/spec/template/spec/containers/0/livenessProbe"}]'

  WHY FIRST: Every second Kubernetes kills pods, the 
  connection storm intensifies. This is a POSITIVE 
  FEEDBACK LOOP — killing pods creates more connections, 
  which causes more failures, which kills more pods. 
  Breaking this loop is the #1 priority. Everything 
  else fails if pods keep restarting.

  VERIFY: No more pod restarts in `kubectl get events`.


ACTION 2: RELIEVE SEMI-SYNC WRITE PRESSURE [0:15 — 30 seconds]

  Switch synchronous_commit to remote_write (per Q3):

  # Connect directly to PostgreSQL (PgBouncer is down):
  psql -h <primary-direct-ip> -p 5432 -U postgres \
    -c "ALTER SYSTEM SET synchronous_commit = 'remote_write';"
  psql -h <primary-direct-ip> -p 5432 -U postgres \
    -c "SELECT pg_reload_conf();"

  # Verify:
  psql -h <primary-direct-ip> -c "SHOW synchronous_commit;"
  # Expected: remote_write

  EFFECT: Write latency drops from 340ms to ~3ms.
  Connections holding transactions for 340ms now release 
  in 3ms → connection pool pressure drops ~100x.

  WHY SECOND: Even if we restore PgBouncer, writes at 
  340ms will re-saturate the pool within seconds. The 
  write bottleneck must be relieved BEFORE restoring 
  connection pooling.

  VERIFY: 
  psql -h <primary-direct-ip> -c \
    "SELECT avg(total_exec_time/calls) 
     FROM pg_stat_statements 
     WHERE query LIKE '%INSERT%' 
     AND calls > 100;"
  # Should show ~3-5ms, not 340ms.
```

### Minute 1-3: Restore Connection Infrastructure

```
ACTION 3: RESTART PgBouncer ON PRIMARY [1:00 — 45 seconds]

  systemctl restart pgbouncer
  # or if containerized:
  kubectl rollout restart deployment/pgbouncer-primary -n prod

  # Verify PgBouncer is up and accepting connections:
  psql -h pgbouncer-primary -p 6432 pgbouncer \
    -c "SHOW POOLS;"
  # Should show pools initializing with sv_active < 200

  WHY AFTER ACTION 2: If we restart PgBouncer before 
  fixing semi-sync, the 340ms writes will immediately 
  re-saturate the 200 connection pool. 
  Order matters: fix the bottleneck, THEN restore the 
  pooler.

  VERIFY: sv_active < 150, cl_waiting = 0 or minimal.


ACTION 4: REVERT CART READS TO REPLICAS [1:45 — 30 seconds]

  The 12:02:30 hotfix (cart reads to primary) is still 
  active. This is STILL dumping read traffic onto the 
  primary. Revert it:

  # Feature flag, config change, or deployment revert:
  feature_flag.set("CART_READ_SOURCE", "replica")
  # or revert the config change from 12:02:30

  EFFECT: Primary load drops significantly. The 85/15 
  read split resumes. Primary handles only writes + 
  15% reads.

  WHY AFTER ACTION 3: PgBouncer must be running before 
  we redirect traffic away from direct connections. 
  The sequence: PgBouncer up → app servers reconnect 
  through PgBouncer → revert cart reads → primary 
  load normalizes.

  VERIFY: Primary PgBouncer sv_active drops. Primary 
  CPU drops.
```

### Minute 3-5: Restore Read Path

```
ACTION 5: VERIFY AND FIX READ REPLICAS [3:00 — 2 minutes]

  Check replication lag on all three replicas:

  psql -h primary -c "
    SELECT client_addr,
           state,
           replay_lsn,
           (pg_current_wal_lsn() - replay_lsn) AS lag_bytes,
           now() - pg_last_xact_replay_timestamp() AS lag_time
    FROM pg_stat_replication;"

  EXPECTED: replica-1 and replica-3 catching up (lag 
  decreasing). Replica-2 still behind (14s from the 
  analyst query).

  Kill any remaining long queries on replica-2:
  psql -h replica-2 -c "
    SELECT pg_terminate_backend(pid) 
    FROM pg_stat_activity 
    WHERE state = 'active' 
      AND query_start < now() - interval '10 seconds'
      AND usename NOT IN ('replication_user', 'postgres');"

  Set hot_standby_feedback = off on replica-2 to prevent 
  future recovery conflicts from blocking replication 
  (or increase max_standby_streaming_delay):
  
  psql -h replica-2 -c \
    "ALTER SYSTEM SET max_standby_streaming_delay = '5s';"
  psql -h replica-2 -c "SELECT pg_reload_conf();"

  VERIFY: All three replicas show decreasing lag_time. 
  Within 2-3 minutes, lag should return to <100ms.


ACTION 6: VERIFY CART READS ARE WORKING [5:00 — 1 minute]

  With replicas catching up and cart reads back on 
  replicas, verify the user-facing issue is resolved:

  → Cart reads should show correct data (lag < 100ms)
  → If residual staleness: implement session sticky 
    routing on read replicas (Q2 solution) as a 
    non-emergency change
  → Monitor: cache hit rate, read latency, error rate
```

### Minute 5-10: Stabilize and Monitor

```
ACTION 7: RESTORE HEALTH CHECKS [6:00 — 1 minute]

  Now that the system is stable, re-enable liveness 
  probes with MORE GENEROUS thresholds:

  kubectl patch deployment app-server -n prod --type=json \
    -p='[{"op":"add","path":"/spec/template/spec/containers/0/livenessProbe","value":{
      "httpGet":{"path":"/health","port":8080},
      "initialDelaySeconds":30,
      "periodSeconds":15,
      "timeoutSeconds":5,
      "failureThreshold":10
    }}]'

  Changes from original:
  → timeout: 500ms → 5s (accommodates temporary spikes)
  → failureThreshold: original → 10 (more tolerant)
  → periodSeconds: check less frequently during recovery

  WHY LAST: Health checks can only be safely re-enabled 
  after the system is genuinely healthy. Re-enabling 
  too early risks restarting the cascade.

  VERIFY: No pod restarts for 5 consecutive minutes.


ACTION 8: MONITOR CONTINUOUSLY [7:00 — ongoing]

  # Watch key metrics for the next 30 minutes:
  watch -n 5 "psql -h pgbouncer-primary -p 6432 pgbouncer \
    -c 'SHOW POOLS;' | grep -E 'sv_active|cl_waiting'"

  watch -n 5 "psql -h primary -c \"
    SELECT client_addr, 
           now() - pg_last_xact_replay_timestamp() AS lag
    FROM pg_stat_replication;\""

  # Key thresholds:
  # → PgBouncer sv_active < 160/200 (20% headroom)
  # → Replication lag < 100ms
  # → Write latency p99 < 20ms
  # → Error rate < 0.1%
  # → No pod restarts

  If any threshold is breached: STOP and investigate 
  before making further changes.
```

### Mitigation Timeline Summary

```
╔══════════════════════════════════════════════════════════════╗
║  TIME   │ ACTION                           │ WHY THIS ORDER  ║
╠══════════════════════════════════════════════════════════════╣
║  0:00   │ Stop K8s from killing pods       │ Break feedback  ║
║         │ (disable liveness probe)         │ loop FIRST      ║
╠══════════════════════════════════════════════════════════════╣
║  0:15   │ Switch synchronous_commit to     │ Must fix write  ║
║         │ remote_write                     │ bottleneck      ║
║         │                                  │ BEFORE pooler   ║
╠══════════════════════════════════════════════════════════════╣
║  1:00   │ Restart PgBouncer on primary     │ Pooler needs    ║
║         │                                  │ healthy writes  ║
║         │                                  │ to function     ║
╠══════════════════════════════════════════════════════════════╣
║  1:45   │ Revert cart reads to replicas    │ Reduce primary  ║
║         │                                  │ load after      ║
║         │                                  │ pooler is up    ║
╠══════════════════════════════════════════════════════════════╣
║  3:00   │ Fix read replicas (kill analyst  │ Restore read    ║
║         │ query, tune conflict settings)   │ capacity        ║
╠══════════════════════════════════════════════════════════════╣
║  5:00   │ Verify cart reads working        │ Confirm UX      ║
║         │                                  │ restored        ║
╠══════════════════════════════════════════════════════════════╣
║  6:00   │ Restore health checks with       │ Only after      ║
║         │ generous thresholds              │ system is       ║
║         │                                  │ stable          ║
╠══════════════════════════════════════════════════════════════╣
║  7:00   │ Continuous monitoring            │ Watch for       ║
║         │                                  │ recurrence      ║
╚══════════════════════════════════════════════════════════════╝

ORDER DEPENDENCY CHAIN:
  Action 1 → enables all subsequent actions (pods stop dying)
  Action 2 → must precede Action 3 (writes must be fast 
    before pooler can function)
  Action 3 → must precede Action 4 (pooler must be up 
    before redirecting traffic through it)
  Action 4 → must precede Action 5 (primary load must 
    drop before replica recovery matters for reads)
  Action 7 → must be LAST (system must be healthy before 
    health checks can enforce health)
```

---

## Q5: Post-Mortem Architecture Changes

### Change 1: Separate Connection Pools for Reads and Writes

```
WHAT: Configure separate PgBouncer instances (or separate 
pools within PgBouncer) for read and write operations 
on the primary.

  # pgbouncer.ini on primary:
  [databases]
  primary_writes = host=postgresql-primary port=5432 
                   pool_size=120
  primary_reads  = host=postgresql-primary port=5432 
                   pool_size=60

  # Application config:
  WRITE_DSN = postgresql://pgbouncer:6432/primary_writes
  READ_DSN  = postgresql://pgbouncer:6432/primary_reads

  120 connections reserved for writes (cannot be 
  consumed by reads). 60 connections for the 15% of 
  reads that go to primary. Total: 180/200 with 
  20 reserved for admin/monitoring.

CASCADE LINK IT BREAKS:
  At 12:02:30, cart reads consumed write connections.
  With separate pools: cart reads can only consume the 
  60 read connections. Even if all 60 are consumed, 
  the 120 write connections are untouched. Writes 
  continue at full speed.

  "Cart reads to primary" hotfix would have been SAFE 
  with this architecture — it would saturate the read 
  pool (degrading reads) but never affect writes.
```

### Change 2: Dedicated Analytics Replica

```
WHAT: Deploy a separate PostgreSQL replica specifically 
for analytical/reporting queries. Remove analyst access 
from the three operational replicas entirely.

  Operational replicas (1, 2, 3):
  → Serve application reads only
  → max_standby_streaming_delay = 5s (aggressive)
  → hot_standby_feedback = off
  → No analyst users have access

  Analytics replica (4):
  → Serves analyst queries, dashboards, reports
  → max_standby_streaming_delay = 300s (tolerant)
  → hot_standby_feedback = on (preserves snapshots)
  → Can lag behind significantly — analysts don't 
    need real-time data
  → If it falls hours behind: fine. It's isolated.

CASCADE LINK IT BREAKS:
  At 12:01:30, the analyst query on replica-2 caused 
  a recovery conflict that spiked replica-2's lag to 
  14 seconds. This removed 1/3 of operational read 
  capacity during peak traffic.

  With a dedicated analytics replica: the analyst query 
  runs on replica-4. Recovery conflicts on replica-4 
  don't affect operational replicas 1-3. Even if 
  replica-4 falls hours behind, operational read 
  capacity is unaffected.
```

### Change 3: Read-Your-Writes at the Application Layer

```
WHAT: Implement the targeted read-your-writes pattern 
from Q2 as a PERMANENT application feature, not a 
hotfix.

  After ANY write operation, flag the user's session 
  for primary reads for a configurable window (default 
  3 seconds). Reads within the window go to primary. 
  Reads after the window go to replicas.

  This PERMANENTLY prevents the "added item to cart 
  but cart shows empty" symptom without ever needing 
  to redirect ALL cart reads to the primary.

CASCADE LINK IT BREAKS:
  At 12:02:00, the symptom ("cart shows empty") 
  triggered the engineering team's panic response 
  (redirect all reads to primary). If read-your-writes 
  is built in from the start, this symptom NEVER 
  OCCURS. The panic redirect never happens. The 
  cascade never starts.

  This is the most critical change because it removes 
  the HUMAN DECISION that caused the cascade. The 
  system handles consistency correctly by default — 
  no one needs to make a high-pressure decision 
  about redirecting traffic.
```

### Change 4: Autoscaling PgBouncer with Connection Backpressure

```
WHAT: Configure PgBouncer to reject new connections 
with a meaningful error when pool utilization exceeds 
a threshold, rather than queuing indefinitely until 
it crashes.

  # pgbouncer.ini:
  max_client_conn = 1000     # max client connections
  default_pool_size = 200    # max server connections
  reserve_pool_size = 10     # emergency reserve
  reserve_pool_timeout = 3   # wait 3s before using reserve
  client_idle_timeout = 30   # disconnect idle clients
  query_wait_timeout = 10    # fail if queued > 10s 
                             # (instead of infinite wait)

  The key parameter: query_wait_timeout = 10.
  If a client's query can't get a server connection 
  within 10 seconds, PgBouncer returns an error instead 
  of queuing indefinitely and eventually crashing.

  Application handles the error:
  → Retry with exponential backoff
  → Return 503 to client with Retry-After header
  → Trigger autoscaling alert

CASCADE LINK IT BREAKS:
  At 12:04:00, PgBouncer crashed because queued 
  connections grew without bound. With query_wait_timeout, 
  excess connections get a clean error after 10 seconds. 
  PgBouncer stays healthy. The application can back off 
  gracefully instead of crashing the connection pooler.
```

### Change 5: Kubernetes Health Check Circuit Breaker

```
WHAT: Configure health checks with a circuit breaker 
pattern — if the DATABASE is degraded, the application 
should report "degraded but alive" instead of "dead."

  # Health check endpoint:
  @app.route('/health')
  async def health_check():
      try:
          # Fast check: can we reach PgBouncer?
          await asyncio.wait_for(
              db.execute("SELECT 1"), timeout=2.0
          )
          return Response(status=200, body="healthy")
      except asyncio.TimeoutError:
          # DB is slow but we're not dead
          # Report degraded, not failed
          return Response(status=200, body="degraded",
                         headers={"X-Health": "degraded"})
      except ConnectionRefusedError:
          # DB is truly unreachable
          return Response(status=503, body="unhealthy")

  # Kubernetes config:
  livenessProbe:
    httpGet:
      path: /health
      port: 8080
    timeoutSeconds: 10       # generous timeout
    failureThreshold: 10     # 10 failures before kill
    periodSeconds: 15        # check every 15s
  
  readinessProbe:
    httpGet:
      path: /ready           # separate endpoint
      port: 8080
    timeoutSeconds: 5
    failureThreshold: 3      # remove from LB faster
    periodSeconds: 5

  CRITICAL DISTINCTION:
  → Liveness probe: "Is the PROCESS alive?" Kill only 
    if the process is truly stuck (OOM, deadlock).
    A slow database is NOT a reason to kill the app.
  → Readiness probe: "Can this pod serve traffic?" 
    Remove from load balancer if degraded, but DON'T 
    restart it.

CASCADE LINK IT BREAKS:
  At 12:03:45, Kubernetes killed pods because the 
  500ms health check timeout was exceeded (writes 
  at 340ms + queueing). With a 10s timeout and 
  failureThreshold=10, Kubernetes tolerates ~150 
  seconds of degradation before restarting pods.
  
  More importantly: the readiness probe removes 
  degraded pods from the load balancer WITHOUT 
  killing them. No restart → no connection storm → 
  PgBouncer doesn't crash.
```

### Change 6: Pre-Sale Load Testing and Capacity Planning

```
WHAT: Load test the flash sale scenario at 2x expected 
peak BEFORE the event. Verify the system handles 
8,100+ write TPS with:
  → Connection pool headroom > 20%
  → Replication lag < 1 second
  → Semi-sync standby keeping pace
  → No recovery conflicts on replicas

Specific test:
  → Simulate 8,100 write TPS for 30 minutes
  → Simultaneously run long analytical queries on 
    replicas (simulate the analyst)
  → Simultaneously redirect cart reads to primary 
    (simulate the hotfix)
  → Monitor for cascade indicators:
    → PgBouncer queue depth
    → Semi-sync write latency
    → Replication lag

  If any cascade indicator triggers during the test: 
  the architecture cannot handle the flash sale. 
  Apply Changes 1-5 before the event.

CASCADE LINK IT BREAKS:
  ALL of them. Load testing under realistic conditions 
  reveals cascade risks before they affect production. 
  The entire incident could have been discovered and 
  prevented in a staging environment.
```

### Post-Mortem Changes Summary

```
╔══════════════════════════════════════════════════════════════╗
║  # │ CHANGE                       │ CASCADE LINK BROKEN      ║
╠══════════════════════════════════════════════════════════════╣
║  1 │ Separate read/write          │ Cart reads can't starve  ║
║    │ connection pools             │ writes                   ║
╠══════════════════════════════════════════════════════════════╣
║  2 │ Dedicated analytics replica  │ Analyst queries can't    ║
║    │                              │ degrade operational      ║
║    │                              │ replicas                 ║
╠══════════════════════════════════════════════════════════════╣
║  3 │ Built-in read-your-writes    │ "Cart empty" symptom     ║
║    │                              │ never occurs → panic     ║
║    │                              │ redirect never happens   ║
╠══════════════════════════════════════════════════════════════╣
║  4 │ PgBouncer backpressure       │ PgBouncer fails cleanly  ║
║    │ (query_wait_timeout)         │ instead of crashing      ║
╠══════════════════════════════════════════════════════════════╣
║  5 │ K8s health check circuit     │ Pods stop being killed   ║
║    │ breaker (liveness vs         │ during DB degradation    ║
║    │ readiness separation)        │                          ║
╠══════════════════════════════════════════════════════════════╣
║  6 │ Pre-sale load testing        │ ALL cascade links        ║
║    │                              │ discovered before        ║
║    │                              │ production               ║
╚══════════════════════════════════════════════════════════════╝

DEFENSE IN DEPTH:
  If Change 3 fails (read-your-writes bug): 
    → Change 1 prevents the cascade (separate pools)
  If Change 1 fails (misconfigured pools):
    → Change 4 prevents PgBouncer crash (backpressure)
  If Change 4 fails (PgBouncer crashes anyway):
    → Change 5 prevents pod restart storm (health checks)
  If Change 5 fails (pods restart anyway):
    → Change 6 would have caught this in testing

  No single change is the complete fix. Together, 
  they break the cascade at EVERY link in the chain.
```

---

Ready for evaluation. 🎯
