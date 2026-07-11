# Week 4, Topic 1: Replication Strategies

---

## Learning Objectives
```
╔════════════════════════════════════════════════════════════════╗
║   AFTER THIS TOPIC, YOU WILL BE ABLE TO:                       ║
╟────────────────────────────────────────────────────────────────╢
║                                                                ║
║   1. Explain leader-follower, multi-leader, and leaderless     ║
║      replication with exact write/read paths and failure       ║
║      modes for each                                            ║
║                                                                ║
║   2. Articulate sync vs async vs semi-synchronous replication  ║
║      tradeoffs with precise durability and availability        ║
║      guarantees                                                ║
║                                                                ║
║   3. Trace WAL-based physical replication vs logical           ║
║      replication vs CDC at the byte/record level               ║
║                                                                ║
║   4. Map every replication topology to its PACELC              ║
║      classification and predict which consistency violations   ║
║      each produces                                             ║
║                                                                ║
║   5. Design replication topologies for real systems, choosing  ║
║      the right strategy per feature based on consequence       ║
║      analysis                                                  ║
║                                                                ║
║   6. Diagnose replication lag incidents using exact tools and  ║
║      commands                                                  ║
║                                                                ║
║   7. Explain failover mechanics — what goes wrong, why         ║
║      split-brain happens, and how to prevent it                ║
╚════════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔═══════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Async replication is fine for money"              ║
╟───────────────────────────────────────────────────────────────────────╢
║   WRONG. Async replication acknowledges writes before they reach      ║
║   a durable replica. Leader crash between ack and replicate =         ║
║   committed data lost. Financial systems need sync or semi-sync       ║
║   to a quorum — accepting the latency cost.                           ║
╠═══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "More replicas = more write capacity"              ║
╟───────────────────────────────────────────────────────────────────────╢
║   WRONG. Every replica applies every write. Replication scales        ║
║   READS, not writes. Write scaling requires partitioning (sharding)   ║
║   — not adding followers.                                             ║
╠═══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "Automatic failover is safe and instant"           ║
╟───────────────────────────────────────────────────────────────────────╢
║   WRONG. Promoting a lagging replica loses data. Promoting two        ║
║   replicas simultaneously causes split-brain. Old leader coming       ║
║   back accepts writes against the new leader. Failover needs          ║
║   fencing (STONITH), quorum, and careful lag thresholds.              ║
╠═══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "Logical replication = CDC = same thing"           ║
╟───────────────────────────────────────────────────────────────────────╢
║   WRONG. Physical replication copies WAL bytes (Postgres streaming).  ║
║   Logical replication decodes row changes (version-specific). CDC     ║
║   (Debezium) reads logical changes for external systems. Different    ║
║   latency, filtering, and schema evolution behavior.                  ║
╠═══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Multi-leader is leader-follower with extras"      ║
╟───────────────────────────────────────────────────────────────────────╢
║   WRONG. Multi-leader allows concurrent writes to the same data       ║
║   in different regions — conflicts are INEVITABLE. You need           ║
║   conflict resolution (LWW, CRDTs), not just "more leaders."          ║
╠═══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #6: "Replication lag is just a dashboard metric"       ║
╟───────────────────────────────────────────────────────────────────────╢
║   WRONG. Lag means stale reads, failed failovers (promote lagging     ║
║   replica = data loss), and broken read-your-writes. Alert on         ║
║   lag seconds AND business impact (stale checkout, missing posts).    ║
╚═══════════════════════════════════════════════════════════════════════╝
```

---

## Core Teaching

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

## Production Patterns

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

## SRE Diagnostic Toolkit

```
REPLICATION FAILS IN THREE SHAPES: lag, slot bloat, and split-brain.

METRICS
  Lag:
    Postgres:  pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) per replica
    MySQL:     Seconds_Behind_Source
    Aurora:    AuroraReplicaLag (ms), AuroraReplicaLagMaximum
  Slot / WAL retention:
    Postgres:  pg_replication_slots.restart_lsn distance from current WAL
               (a slot with a dead consumer pins WAL -> disk fills)
    ReplicationSlotDiskUsage (CloudWatch RDS)
  Apply throughput:
    replay rate vs primary write rate; if replay < write, lag grows unbounded.

COMMANDS
  Postgres:
    SELECT client_addr, state, sent_lsn, replay_lsn,
           pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS bytes_behind
    FROM pg_stat_replication;
    SELECT slot_name, active,
           pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS retained
    FROM pg_replication_slots ORDER BY retained DESC;
  MySQL:  SHOW REPLICA STATUS\G   (IO/SQL thread state, error, lag)
  Aurora: CloudWatch per-replica lag; check reader endpoint routing.

SIGNATURES -> ROOT CAUSE
  Lag flat but DISK on primary climbing        -> inactive replication slot
                                                  (dead/paused consumer) pinning WAL
  Lag grows only under write bursts            -> replica IO/CPU bound; single-
                                                  threaded apply (MySQL) can't keep up
  Replica falls over, lag on OTHERS jumps      -> read traffic re-homed onto fewer
                                                  replicas -> cascade; shed reads
  Two nodes both accept writes after failover  -> split-brain; fence the old primary
                                                  before promoting (STONITH)

WHAT TO DO
  - Slot bloat: drop the orphaned slot (pg_drop_replication_slot) AFTER
    confirming the consumer is gone; set max_slot_wal_keep_size to cap risk.
  - Chronic apply lag: bigger replica, parallel apply, or move heavy read
    queries off the replica.
  - Never promote without fencing — a returning old primary causes divergence.
```

---

## Decision Framework

```
CHOOSE THE TOPOLOGY BY RPO/RTO AND WRITE PATTERN

  ┌──────────────────┬────────────────────────────┬────────────────────────────┐
  │ Topology         │ Choose when                │ Price you pay              │
  ├──────────────────┼────────────────────────────┼────────────────────────────┤
  │ Single-leader    │ Default OLTP; strong per-  │ Write throughput capped by │
  │ async replicas   │ key order; read scaling    │ one primary; replicas stale│
  ├──────────────────┼────────────────────────────┼────────────────────────────┤
  │ Single-leader    │ Zero data loss on failover │ Write latency = slowest    │
  │ SYNC (semi-sync) │ (financial ledger)         │ acked replica; availability│
  │                  │                            │ drops if replica down      │
  ├──────────────────┼────────────────────────────┼────────────────────────────┤
  │ Multi-leader     │ Multi-region writes,       │ Write conflicts are        │
  │                  │ offline/mobile sync        │ INEVITABLE; need CRDTs or  │
  │                  │                            │ app merge (Week 8)         │
  ├──────────────────┼────────────────────────────┼────────────────────────────┤
  │ Leaderless       │ AP, always-writable,       │ Tunable but no free lunch: │
  │ quorum (Dynamo)  │ tunable consistency        │ R+W>N for strong per-key;  │
  │                  │                            │ read repair / anti-entropy │
  └──────────────────┴────────────────────────────┴────────────────────────────┘

SYNC vs ASYNC — THE REAL DECISION
  Ask: "What is the cost of losing the last N seconds of writes on failover?"
    Catastrophic (money, legal) -> synchronous / semi-sync, accept latency.
    Recoverable (analytics)     -> async, cheaper and more available.
  Semi-sync (ack from >=1 replica) is the common middle ground: bounded RPO
  without waiting for ALL replicas.

QUORUM MATH (leaderless)
  N replicas, W write acks, R read acks.
    Strong per-key read  -> R + W > N (e.g., N=3, W=2, R=2).
    Faster writes        -> W=1 (risk: read stale / lost on node loss).
    Faster reads         -> R=1 (risk: stale read).
  Sloppy quorum + hinted handoff trades consistency for availability during
  partitions — know which one your datastore defaults to.

READ ROUTING (ties to Week 3)
  Read-your-writes flows -> primary or wait-for-LSN on replica.
  Everything else        -> replicas, with staleness budget documented.
```

---

## Hands-On Exercises
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

## Incident Scenario

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

## Targeted Reading
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

## Ops Sim: Northstar Checkout Replica Lag Hotfix

**Time box:** 35 minutes
**Severity:** P1
**Service / domain:** PostgreSQL primary, semi-sync standby, async read replicas
**Northstar system:** Checkout OLTP

### Rules

1. Answer from memory; do not re-read the replication section mid-drill.
2. Write decisions in order (T+0 -> T+60).
3. Cite metrics/config for every claim.
4. Do not open the answer key until finished.

### 1. Scenario stem

```text
WHAT USERS SEE:
  "Added to cart" succeeds, then cart appears empty. Some checkout confirmations
  take 6s. Payment capture is not yet affected.

WHAT ON-CALL SEES:
  Async replicas lag during a flash sale. A hotfix routed cart reads to primary,
  and primary PgBouncer is now saturated.

BUSINESS CONSTRAINT:
  Cart display may lag briefly, but payment and inventory writes must remain safe.
```

### 2. Telemetry pack

```text
METRICS:
  write TPS: 3,200 -> 8,400
  async replica lag: r1=0.9s r2=18s r3=1.4s
  primary PgBouncer: cl_active=620 cl_waiting=480 sv_active=220 sv_idle=0
  primary DB CPU=68%; WAL write p99=44ms; lock waits normal
  semi-sync commit latency: 8ms -> 290ms
  cart read p99 after hotfix: 80ms -> 2.8s

LOG LINES:
  replica-2: recovery conflict with long-running query; canceling statement
  checkout-api: read_your_writes_required order_id=... routing=primary
  PgBouncer: server login failed: FATAL too many clients already

TRACE:
  cart read -> primary PgBouncer wait 2100ms -> query 12ms
```

### 3. Config pack

```yaml
replication:
  synchronous_commit: remote_apply
  semi_sync_standby: checkout-standby-1b
reads:
  cart:
    require_fresh_after_write: true
    route_all_to_primary: true   # wrong/dangerous broad hotfix
  catalog:
    route_to_replicas: true
pgbouncer_primary:
  max_server_conn: 220
```

### 4. Timeline & decision points

| Time | Event | Your move (write before reading further) |
|------|-------|------------------------------------------|
| T+0 | P1: cart anomalies and primary pool saturation. | |
| T+5 | You find the broad read-to-primary hotfix and replica-2 lag. | |
| T+15 | Team proposes `synchronous_commit=off` for checkout. | |
| T+60 | Read path is stable; semi-sync commit latency remains high. | |

### 5. Questions

**Q1 - Layer & root cause:** What triggered the incident and what amplified it?

**Q2 - Evidence:** Which signals show replica lag, primary pool saturation, and semi-sync pressure?

**Q3 - Sequencing:** What do you change in the first 15 minutes?

**Q4 - Bad fix gallery:** Why is routing all cart reads to primary dangerous? Why is `synchronous_commit=off` risky?

**Q5 - Capacity / blast radius:** If 620 active clients compete for 220 primary server connections, what waits and retries follow?

**Q6 - Durable fix:** What read-your-writes and replica-lag routing policy should replace the hotfix?

**Q7 - Org / runbook:** Who is informed during this P1 and what durability downgrade needs approval?

**Answer key:** [`../answers/Week-04-Replication-Partitioning-Consensus/Replication Strategies Answers.md`](../answers/Week-04-Replication-Partitioning-Consensus/Replication%20Strategies%20Answers.md)

---

## Key Takeaways
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

> **Answer key (do not open until you attempt the scenario questions):**
> [`../answers/Week-04-Replication-Partitioning-Consensus/Replication%20Strategies%20Answers.md`](../answers/Week-04-Replication-Partitioning-Consensus/Replication%20Strategies%20Answers.md)
