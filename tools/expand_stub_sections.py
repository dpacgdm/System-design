#!/usr/bin/env python3
"""Replace thin script-injected stub sections with gold-standard depth content.

Each entry maps a file to (stub_text, full_text). Stub matching is exact so this
script is idempotent: once the full text is in place, the stub no longer matches.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REPLACEMENTS: dict[str, list[tuple[str, str]]] = {
    # ---------------------------------------------------------------- NoSQL
    "Week-02-Storage-Fundamentals/NoSQL Taxonomy.md": [
        (
            """## SRE Diagnostic Toolkit

```
METRICS: Cassandra UNAVAILABLE, Redis evicted_keys, Mongo replication lag
COMMANDS: nodetool status, redis-cli INFO, db.serverStatus().repl
SIGNATURES: QUORUM failures with 2/3 nodes → RF math; hot partition key
```

---
""",
            """## SRE Diagnostic Toolkit

```
WHAT TO WATCH (per NoSQL family)

  CASSANDRA / SCYLLA (wide-column)
    Metrics:
      org.apache.cassandra.metrics.ClientRequest.Unavailable.{Read,Write}
      org.apache.cassandra.metrics.ClientRequest.Timeout.{Read,Write}
      Table.LiveSSTableCount, PendingCompactions, TombstoneScannedHistogram
      Storage.Load (per node), DroppedMessages (MUTATION, READ_REPAIR)
    Commands:
      nodetool status              # UN/DN state, ownership %, load skew
      nodetool tpstats             # dropped mutations, blocked flush writers
      nodetool tablehistograms ks tbl   # p99 read/write, SSTables per read
      nodetool compactionstats     # backlog; growing = write pressure
    Signatures:
      Unavailable spikes with 2/3 nodes UP  -> R+W<=N misconfig or RF wrong
      TombstoneScanned p99 in thousands     -> queue/delete anti-pattern
      One node 3x Load                      -> hot partition (unbounded key)

  REDIS (KV / cache)
    Metrics: evicted_keys, keyspace_hits/misses, used_memory vs maxmemory,
             connected_clients, instantaneous_ops_per_sec, blocked_clients
    Commands:
      redis-cli INFO stats | egrep 'hit|miss|evict|expired'
      redis-cli --bigkeys              # find hot/large keys
      redis-cli --latency-history -i 1 # p99 latency over time
      redis-cli SLOWLOG GET 20
    Signatures:
      evicted_keys climbing + latency spike -> memory pressure, wrong maxmemory-policy
      one slot/key dominating ops           -> hot key; need client-side cache or shard

  MONGODB (document)
    Metrics: replication lag (optime diff), WT cache dirty %, page faults,
             opcounters, scanAndOrder, queued readers/writers
    Commands:
      rs.status()                     # member health, optimeDate lag
      db.serverStatus().wiredTiger.cache
      db.currentOp({ secs_running: { $gt: 5 } })
      db.collection.explain('executionStats').find({...})
    Signatures:
      COLLSCAN in explain             -> missing index
      replication lag growing         -> secondary IO-bound or primary write storm

  DYNAMODB (managed KV/document)
    Metrics: ThrottledRequests, ConsumedRead/WriteCapacityUnits, hot-partition
             (CloudWatch Contributor Insights), SuccessfulRequestLatency
    Signatures:
      Throttling with capacity headroom -> hot partition key (low cardinality PK)

LOG PATTERNS:
  "Operation timed out - received only N responses"  (Cassandra CL not met)
  "OOM command not allowed when used memory > maxmemory" (Redis)
  "not master and slaveOk=false"                       (Mongo read routing)
```

---
""",
        ),
        (
            """## Decision Framework

```
DOCUMENT: flexible schema, horizontal scale → MongoDB/Dynamo
WIDE-COLUMN: write-heavy, partition key access → Cassandra
KV: session/cache → Redis/Dynamo
GRAPH: traversals → Neo4j (not for OLTP scale)
SEARCH: full-text → Elasticsearch (CQRS read model)
Pick ONE primary store per bounded context; polyglot via events.
```

---
""",
            """## Decision Framework

```
STEP 1 — DOES THE WORKLOAD ACTUALLY NEED NoSQL?
  Relational + <10TB + joins + ad-hoc queries  -> stay on Postgres/Aurora.
  Reach for NoSQL when a SPECIFIC access pattern or scale axis breaks SQL:
    - write throughput beyond a single primary       -> wide-column
    - unbounded horizontal scale on a known key      -> KV / wide-column
    - deeply nested aggregates read/written together -> document
    - relationship traversal is the query            -> graph
    - relevance-ranked full-text search              -> search engine

STEP 2 — PICK THE FAMILY BY ACCESS PATTERN (not by hype)

  ┌───────────────┬───────────────────────────┬───────────────────────────┐
  │ Family        │ Choose when                │ Do NOT choose when         │
  ├───────────────┼───────────────────────────┼───────────────────────────┤
  │ Wide-column   │ Massive writes, time-      │ Ad-hoc queries, joins,     │
  │ (Cassandra)   │ series, known partition    │ strong multi-key txns      │
  │               │ key, tunable consistency   │                            │
  ├───────────────┼───────────────────────────┼───────────────────────────┤
  │ Document      │ Aggregate read/write as a  │ Many-to-many joins,        │
  │ (Mongo/Dynamo)│ unit, flexible schema      │ cross-document txns hot    │
  ├───────────────┼───────────────────────────┼───────────────────────────┤
  │ KV            │ Session, cache, feature    │ Range scans, secondary     │
  │ (Redis/Dynamo)│ flags, sub-ms lookups      │ query dimensions          │
  ├───────────────┼───────────────────────────┼───────────────────────────┤
  │ Graph         │ Traversals, recommendation │ OLTP at web scale,         │
  │ (Neo4j)       │ social graph, fraud rings  │ high write throughput      │
  ├───────────────┼───────────────────────────┼───────────────────────────┤
  │ Search        │ Full-text, relevance,      │ Source of truth, ACID      │
  │ (Elastic)     │ aggregations, facets       │ writes, financial data     │
  └───────────────┴───────────────────────────┴───────────────────────────┘

STEP 3 — MODEL FOR THE QUERY, NOT THE ENTITY
  Wide-column/KV: design the partition key from the read path first.
    Good PK: high cardinality + even access (user_id, device_id#day).
    Bad PK:  status, country, boolean -> hot partitions.

STEP 4 — CONSISTENCY BUDGET (ties to Week 3)
  Need read-your-writes on a key -> R+W>N (QUORUM/QUORUM) in Cassandra,
  strong reads in Dynamo, primary reads in Mongo.
  Tolerate staleness -> CL=ONE reads, eventually consistent Dynamo reads.

RULE: ONE primary store per bounded context. Add a second store only behind
an event stream (CDC/outbox, Week 6) with a documented rebuild procedure.
Every extra store is a dual-write consistency bug waiting to happen.
```

---
""",
        ),
    ],
    # -------------------------------------------------------- Consistency Models
    "Week-03-Distributed-Systems-Theory/Consistency Models.md": [
        (
            """## SRE Diagnostic Toolkit

```
DIAGNOSE: stale read after write → replication lag + read replica routing
COMMANDS: SHOW SLAVE STATUS; aurora_replica_lag; session token (Mongo)
METRICS: read-after-write violation rate (custom), replica lag p99
```

---
""",
            """## SRE Diagnostic Toolkit

```
THE CORE SYMPTOM: "I wrote it, then couldn't read it" (or read an old value).
Almost every consistency bug reduces to replication lag + wrong read routing.

METRICS TO INSTRUMENT
  Replica lag (per replica):
    Postgres:  SELECT (now() - pg_last_xact_replay_timestamp()) AS lag;
    MySQL:     SHOW REPLICA STATUS -> Seconds_Behind_Source
    Aurora:    CloudWatch AuroraReplicaLag (ms)
    Mongo:     rs.printSecondaryReplicationInfo()
  Read-after-write violation rate (custom SLI):
    On critical flows, tag the write LSN/timestamp, then on the next read
    assert replica_replay >= write_lsn. Emit a counter when it is not.
  Staleness distribution:
    Histogram of (read_time - value_write_time) at the app layer.

COMMANDS / QUERIES
  Postgres primary vs replica LSN gap:
    SELECT client_addr,
           pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS bytes_behind
    FROM pg_stat_replication;
  Aurora: aurora_replica_status() / CloudWatch per-instance lag.
  Mongo causal session (guarantees read-your-writes across nodes):
    session.startTransaction(); ... afterClusterTime is tracked automatically.
  DynamoDB: use ConsistentRead=true for the read-your-writes path only.

DECISION TREE WHEN A STALE READ IS REPORTED
  1. Is the read hitting a replica? (check connection routing / reader endpoint)
  2. What is current replica lag vs the age of the write?
       lag > write_age  -> expected staleness; route this flow to primary
  3. Is lag itself anomalous? -> replica IO-bound, long-running query, or
     slot bloat (Week 5). Fix the lag, not just the routing.
  4. Is it truly concurrent (two writers)? -> this is a conflict, not lag;
     you need causal metadata / version vectors (Week 8), not primary reads.

LOG PATTERNS
  "row not found" immediately after successful insert  -> replica read of new row
  count/balance flips between refreshes                -> replica lag jitter
  monotonic read violation (value goes backward)       -> load-balanced replicas
                                                          with different lag
```

---
""",
        ),
        (
            """## Decision Framework

```
STRONG / SERIALIZABLE → financial ledger, inventory decrement
CAUSAL → social feed ordering, session-scoped reads
READ-YOUR-WRITES → post-signup profile, post-checkout order history
EVENTUAL → analytics, search index, CDN
Choose weakest model that satisfies user-visible invariant.
```

---
""",
            """## Decision Framework

```
PRINCIPLE: Choose the WEAKEST model that still preserves the user-visible
invariant. Stronger models cost latency, availability, and throughput.

MAP THE INVARIANT -> THE MODEL

  ┌────────────────────────────┬──────────────────────┬─────────────────────┐
  │ User-visible requirement   │ Model needed         │ Mechanism           │
  ├────────────────────────────┼──────────────────────┼─────────────────────┤
  │ No double-spend, unique    │ Linearizable /       │ single-leader +     │
  │ constraint, inventory=0    │ serializable         │ primary reads, or   │
  │                            │                      │ consensus (Raft)    │
  ├────────────────────────────┼──────────────────────┼─────────────────────┤
  │ "See my own change now"    │ Read-your-writes     │ route user to       │
  │ (profile, order history)   │ (session)            │ primary or sticky   │
  │                            │                      │ replica; wait-for-  │
  │                            │                      │ LSN                 │
  ├────────────────────────────┼──────────────────────┼─────────────────────┤
  │ Reply never appears before │ Causal               │ version vectors /   │
  │ the message it answers     │                      │ causal tokens (Wk8) │
  ├────────────────────────────┼──────────────────────┼─────────────────────┤
  │ Value never goes backward  │ Monotonic reads      │ pin session to one  │
  │ on refresh                 │                      │ replica             │
  ├────────────────────────────┼──────────────────────┼─────────────────────┤
  │ Analytics, search, CDN,    │ Eventual             │ async replication,  │
  │ counters that converge     │                      │ read any replica    │
  └────────────────────────────┴──────────────────────┴─────────────────────┘

PER-FLOW, NOT PER-SYSTEM
  The same database can serve linearizable checkout AND eventual product
  browsing. Pick the model per endpoint. Do not make the whole app pay
  primary-read latency because ONE flow needs it.

COST LADDER (weak -> strong)
  eventual  <  monotonic/RYW  <  causal  <  linearizable/serializable
     cheap, HA                                    expensive, CP under partition

COMMON MISTAKES
  - "SERIALIZABLE everywhere" -> retry storms, throughput collapse.
  - Read-your-writes solved by reading primary for ALL reads -> primary melts.
  - Assuming replicas are strongly consistent because they are "in the same DB".
```

---
""",
        ),
    ],
    # -------------------------------------------------------- Consistent Hashing
    "Week-03-Distributed-Systems-Theory/Consistent Hashing.md": [
        (
            """## SRE Diagnostic Toolkit

```
COMMANDS: ring visualization, vnode count per node, key distribution histogram
METRICS: per-node request rate skew, rebalance duration, moved-key fraction
SIGNATURES: one node 3× traffic → hot vnode; mass migration → ring churn bug
```

---
""",
            """## SRE Diagnostic Toolkit

```
WHAT GOES WRONG WITH A RING: load skew, migration storms, and hot keys that
no amount of rebalancing can fix.

METRICS TO WATCH
  Per-node load skew:
    max(node_request_rate) / avg(node_request_rate)   (target < 1.3)
    max(node_bytes_stored) / avg(node_bytes_stored)
  Vnode distribution:
    tokens (vnodes) per physical node; std-dev of key ownership %
  Rebalance health:
    fraction of keys moved on a membership change (should be ~1/N)
    streaming/bootstrap throughput and ETA
  Hot key detection:
    top-K key request rate vs median (Redis --bigkeys, Cassandra
    nodetool toppartitions ks tbl 1000)

COMMANDS
  Cassandra:
    nodetool status            # ownership % per node — uneven => token imbalance
    nodetool ring              # token ranges per node
    nodetool toppartitions     # hot partitions in a live window
    nodetool netstats          # streaming during bootstrap/decommission
  Redis Cluster:
    redis-cli cluster nodes    # slot ranges per node
    redis-cli cluster slots
    redis-cli --hotkeys        # (with LFU maxmemory-policy)

DIAGNOSTIC DECISION TREE
  One node hot, ownership even?
    -> HOT KEY (single partition), not a ring problem. Consistent hashing
       cannot split a single key. Fix: split the key (add a suffix bucket),
       add a client-side/edge cache, or replicate the key.
  One node hot, ownership UNeven?
    -> too few vnodes or bad token assignment. Increase vnodes (100-256/node)
       or rebalance tokens.
  Massive key movement on adding one node?
    -> you are NOT using consistent hashing (likely hash mod N) OR vnode
       count is tiny. Correct consistent hashing moves ~1/N of keys.

LOG / SIGNATURE PATTERNS
  Latency spike on ONE shard during a scale-out  -> streaming saturating that node
  Cache hit ratio cliff after adding a node      -> keys remapped (expected once,
                                                    warm the new node before cutover)
```

---
""",
        ),
        (
            """## Decision Framework

```
CONSISTENT HASH when: dynamic membership, cache/KV ring, minimal remapping
RANGE SHARD when: range queries, time-series, ordered scans
HASH MOD N: NEVER in production (full reshuffle on N change)
Vnodes: 100–200 per physical node typical for even distribution
```

---
""",
            """## Decision Framework

```
CHOOSING A PARTITIONING SCHEME

  ┌──────────────────┬────────────────────────────┬────────────────────────┐
  │ Scheme           │ Use when                    │ Cost / caveat          │
  ├──────────────────┼────────────────────────────┼────────────────────────┤
  │ Consistent hash  │ Dynamic membership (cache,  │ No efficient range      │
  │ + vnodes         │ KV ring, Cassandra/Dynamo); │ scans; hot single key   │
  │                  │ want ~1/N remap on change   │ still unsolved          │
  ├──────────────────┼────────────────────────────┼────────────────────────┤
  │ Range sharding   │ Ordered scans, time-series, │ Hot "latest" shard for  │
  │                  │ pagination by key           │ monotonic keys; needs   │
  │                  │                             │ split/merge machinery   │
  ├──────────────────┼────────────────────────────┼────────────────────────┤
  │ Hash mod N       │ Fixed cluster, batch jobs   │ NEVER for stateful prod │
  │                  │ only                        │ — N change reshuffles   │
  │                  │                             │ ~all keys              │
  ├──────────────────┼────────────────────────────┼────────────────────────┤
  │ Directory /      │ Arbitrary placement,        │ Extra lookup + the     │
  │ lookup table     │ controlled migration        │ directory is now a SPOF │
  └──────────────────┴────────────────────────────┴────────────────────────┘

VNODE SIZING
  Too few (1 per node)  -> uneven ownership, large chunks move on change.
  Sweet spot            -> ~128-256 tokens per physical node (Cassandra default
                           256; Dynamo-style "virtual nodes" similar).
  Trade-off             -> more vnodes = smoother distribution but more metadata
                           and more streaming ranges to track.

WEIGHTED / HETEROGENEOUS NODES
  Bigger instances should own more tokens (weight by capacity), or one node
  becomes the bottleneck at even token counts.

BOUNDED-LOAD VARIANT
  Plain consistent hashing can still produce 1.5-2x skew. "Consistent hashing
  with bounded loads" caps any node at (1+eps)*average by spilling to the next
  node — worth it for cache fleets where skew = origin overload.

HARD RULE: hashing distributes KEYS, not LOAD. A single hot key defeats every
ring. Detect hot keys first (SRE toolkit above); then cache/split/replicate.
```

---
""",
        ),
    ],
    # ----------------------------------------------------- Replication Strategies
    "Week-04-Replication-Partitioning-Consensus/Replication Strategies.md": [
        (
            """## SRE Diagnostic Toolkit

```
METRICS: ReplicaLag, ReplicationSlotDiskUsage, Seconds_Behind_Master
COMMANDS: pg_stat_replication; SHOW REPLICA STATUS; pg_replication_slots
SIGNATURES: lag flat + disk growth → slot bloat; cascade replica death chain
```

---
""",
            """## SRE Diagnostic Toolkit

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
  MySQL:  SHOW REPLICA STATUS\\G   (IO/SQL thread state, error, lag)
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
""",
        ),
        (
            """## Decision Framework

```
SYNC REPLICATION: zero RPO financial writes (accept latency/availability cost)
ASYNC REPLICATION: scale reads, tolerate seconds lag (explicit stale reads)
MULTI-LEADER: offline/mobile only; conflict resolution mandatory
LEADERLESS: AP quorum (Week 4); tunable R/W consistency
```

---
""",
            """## Decision Framework

```
CHOOSE THE TOPOLOGY BY RPO/RTO AND WRITE PATTERN

  ┌──────────────────┬───────────────────────────┬───────────────────────────┐
  │ Topology         │ Choose when                │ Price you pay              │
  ├──────────────────┼───────────────────────────┼───────────────────────────┤
  │ Single-leader    │ Default OLTP; strong per-  │ Write throughput capped by │
  │ async replicas   │ key order; read scaling    │ one primary; replicas stale│
  ├──────────────────┼───────────────────────────┼───────────────────────────┤
  │ Single-leader    │ Zero data loss on failover │ Write latency = slowest    │
  │ SYNC (semi-sync) │ (financial ledger)         │ acked replica; availability│
  │                  │                            │ drops if replica down      │
  ├──────────────────┼───────────────────────────┼───────────────────────────┤
  │ Multi-leader     │ Multi-region writes,       │ Write conflicts are        │
  │                  │ offline/mobile sync        │ INEVITABLE; need CRDTs or  │
  │                  │                            │ app merge (Week 8)         │
  ├──────────────────┼───────────────────────────┼───────────────────────────┤
  │ Leaderless       │ AP, always-writable,       │ Tunable but no free lunch: │
  │ quorum (Dynamo)  │ tunable consistency        │ R+W>N for strong per-key;  │
  │                  │                            │ read repair / anti-entropy │
  └──────────────────┴───────────────────────────┴───────────────────────────┘

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
""",
        ),
    ],
    # ----------------------------------------------------------------- Sharding
    "Week-04-Replication-Partitioning-Consensus/Sharding.md": [
        (
            """## SRE Diagnostic Toolkit

```
METRICS: per-shard QPS/CPU, cross-shard query rate, rebalance progress
COMMANDS: Vitess vtctl ShardReport; Citus shard sizes; scatter-gather latency
SIGNATURES: one shard 80% CPU → bad shard key; fan-out → missing co-location
```

---
""",
            """## SRE Diagnostic Toolkit

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
""",
        ),
        (
            """## Decision Framework

```
SHARD KEY: high cardinality, even distribution, query locality (user_id, tenant_id)
AVOID: monotonic keys (time-only) → hot last shard
RESHARDING: dual-write + backfill + cutover; never in-place split under load
CROSS-SHARD TX: 2PC only if unavoidable; prefer saga/outbox per aggregate
```

---
""",
            """## Decision Framework

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

  ┌───────────────┬────────────────────────────┬──────────────────────────┐
  │ Strategy      │ Choose when                 │ Caveat                   │
  ├───────────────┼────────────────────────────┼──────────────────────────┤
  │ Hash(key)     │ Even write distribution,    │ No range scans on key    │
  │               │ point lookups               │                          │
  ├───────────────┼────────────────────────────┼──────────────────────────┤
  │ Range(key)    │ Range queries, time-series  │ Hot latest shard;        │
  │               │                             │ needs split/merge        │
  ├───────────────┼────────────────────────────┼──────────────────────────┤
  │ Directory/    │ Arbitrary placement,        │ Lookup service is a SPOF │
  │ lookup        │ tenant isolation            │ / extra hop             │
  ├───────────────┼────────────────────────────┼──────────────────────────┤
  │ Geo/          │ Data residency, latency     │ Cross-region joins hard  │
  │ entity-group  │                             │                          │
  └───────────────┴────────────────────────────┴──────────────────────────┘

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
""",
        ),
    ],
    # ------------------------------------------------------------- Consensus Raft
    "Week-04-Replication-Partitioning-Consensus/Consensus Raft.md": [
        (
            """## Decision Framework

```
USE RAFT/ETCD when: small consistent metadata, config, locks, service discovery
NOT RAFT when: high-throughput data plane (use leaderless + app logic)
CLUSTER SIZE: 3 or 5 nodes; 5 for AZ fault tolerance; avoid even counts
DEPLOY: never rolling restart all followers simultaneously (election storm)
```

---
""",
            """## Decision Framework

```
WHEN CONSENSUS (RAFT/PAXOS) IS THE RIGHT TOOL

  USE IT FOR (small, strongly-consistent, low-write-rate state):
    - cluster membership / leader election
    - configuration and feature-flag source of truth (etcd, Consul)
    - distributed locks / leases / fencing tokens
    - service discovery registries
    - metadata for a larger system (shard maps, schema versions)

  DO NOT USE IT FOR (high-throughput data plane):
    - user data at web scale             -> leaderless quorum (Dynamo/Cassandra)
    - event streams                      -> Kafka (ISR replication, not Raft per msg)
    - anything writing >~10k ops/s to the SAME group -> the leader is a bottleneck;
      every write is a full round-trip to a quorum + fsync.

CLUSTER SIZING

  ┌────────┬───────────────────┬───────────────────────────────────────────┐
  │ Nodes  │ Tolerates failures│ Notes                                       │
  ├────────┼───────────────────┼───────────────────────────────────────────┤
  │ 3      │ 1                 │ spread across 3 AZs; common default         │
  │ 5      │ 2                 │ survives 1 AZ + 1 node; more quorum latency │
  │ 7      │ 3                 │ rarely worth it; write latency grows        │
  │ even   │ — (avoid)         │ no availability gain, worse quorum          │
  └────────┴───────────────────┴───────────────────────────────────────────┘
  Quorum = floor(N/2)+1. Bigger clusters = more durable but SLOWER writes
  (must wait for a majority to fsync).

OPERATIONAL RULES (where clusters actually die)
  - Disk fsync latency IS your write latency. Put the Raft log on fast, local
    NVMe; a slow EBS volume causes election storms and proposal timeouts.
  - Never rolling-restart all followers at once, and never let clients hammer
    the leader on boot -> thundering herd + repeated elections (see incident).
  - Keep the keyspace SMALL. etcd is metadata, not a database; watch DB size
    and compact/defrag on schedule.
  - Set client backoff + jitter on watches and leases so a leader change does
    not trigger a reconnect stampede.

ALTERNATIVES
  Need HA config but not linearizability? A replicated cache + versioned S3
  object may be simpler than running Raft. Consensus is powerful and expensive
  — reach for it only when you truly need agreement, not just replication.
```

---
""",
        ),
    ],
    # --------------------------------------------------------- Cassandra Architecture
    "Week-05-Database-Internals/Cassandra Architecture.md": [
        (
            """## Decision Framework

```
WRITE PATH: commitlog → memtable → SSTable; tune flush/compaction for workload
READ CL + WRITE CL: R+W>N for strong per-key (usually QUORUM/QUORUM)
PARTITION KEY: query-driven; avoid ALLOW FILTERING in production
REPAIR: full repair monthly; incremental daily; tombstone gc within gc_grace
```

---
""",
            """## Decision Framework

```
IS CASSANDRA THE RIGHT STORE?
  YES when: massive write throughput, linear scale-out, multi-DC active/active,
            time-series / event / sensor data, a KNOWN partition-keyed access
            pattern, and eventual (tunable) consistency is acceptable.
  NO when:  ad-hoc queries, joins, strong multi-partition transactions,
            read-modify-write on contended keys, or low data volume (operational
            overhead not worth it — use Postgres).

CONSISTENCY LEVEL (per query, ties to Week 3)
  RF = replication factor (e.g., 3). Choose CL for reads (R) and writes (W):
    Strong per-key read-your-writes  -> R + W > RF   (QUORUM/QUORUM is default)
    Max availability, tolerate stale -> W=ONE, R=ONE (fast, may read old data)
    Multi-DC:                         LOCAL_QUORUM to avoid cross-DC latency
  Never assume "QUORUM = always consistent" — a read immediately after a
  W=ONE write can still be stale. Match R and W to the invariant.

DATA MODELING (the make-or-break)
  - Model ONE table PER query. Denormalize aggressively; writes are cheap.
  - Partition key: high cardinality + bounded partition size (< ~100MB,
    < ~100k rows). Unbounded partitions (all events under one key) kill you.
  - Clustering columns define on-disk order -> design for the range you read.
  - NEVER use ALLOW FILTERING in production (full-cluster scan).
  - Avoid queue patterns (write then delete) -> tombstone hell.

COMPACTION STRATEGY
  ┌──────────────────────┬───────────────────────────────────────────────┐
  │ STCS (Size-Tiered)   │ write-heavy, general default                    │
  │ LCS (Leveled)        │ read-heavy, bounded read amplification, more IO │
  │ TWCS (Time-Window)   │ time-series/TTL data — drops whole SSTables     │
  └──────────────────────┴───────────────────────────────────────────────┘

OPERATIONS
  - Repair within gc_grace_seconds (default 10 days) or deletes resurrect.
  - Full repair periodically; incremental more often; watch tombstone warnings.
  - Watch pending compactions and SSTables-per-read (read amplification).
```

---
""",
        ),
    ],
    # -------------------------------------------------- Database Scaling Patterns
    "Week-05-Database-Internals/Database Scaling Patterns.md": [
        (
            """## SRE Diagnostic Toolkit

```
FOUR NUMBERS: CPU%, IOPS, connections, replication lag — always first
COMMANDS: pg_stat_activity, pg_replication_slots, pg_stat_statements top queries
SLO: p99 query latency, replication lag p99, connection pool wait time
```

---
""",
            """## SRE Diagnostic Toolkit

```
START WITH FOUR NUMBERS — they point to the correct scaling rung:
  1. CPU%            high -> bad query plan / missing index (Rung 0), not "add nodes"
  2. IOPS / disk     high -> missing index or cache too small (Rung 0/3)
  3. Connections     at max -> pooling missing (Rung 1), not a bigger box
  4. Replication lag high -> replica IO-bound or slot bloat (Rung 2 / slot fix)

TRIAGE QUERIES (Postgres)
  Active/blocked work:
    SELECT pid, state, wait_event_type, wait_event, now()-query_start AS dur, query
    FROM pg_stat_activity WHERE state <> 'idle' ORDER BY dur DESC LIMIT 20;
  Top cost queries:
    SELECT query, calls, mean_exec_time, total_exec_time
    FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 20;
  Missing-index signal:
    high seq_scan vs idx_scan in pg_stat_user_tables on a large hot table.
  Connections:
    SELECT count(*), state FROM pg_stat_activity GROUP BY state;
    (compare to max_connections and pooler pool size)
  Replication + slots:
    SELECT * FROM pg_stat_replication;
    SELECT slot_name, active,
           pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS retained
    FROM pg_replication_slots ORDER BY retained DESC;
  Bloat / vacuum:
    SELECT relname, n_dead_tup, last_autovacuum FROM pg_stat_user_tables
    ORDER BY n_dead_tup DESC LIMIT 20;

AWS / RDS / AURORA
  CloudWatch: CPUUtilization, ReadIOPS/WriteIOPS, DatabaseConnections,
              FreeableMemory, AuroraReplicaLag, ReplicationSlotDiskUsage.
  Performance Insights: top SQL by wait (CPU vs IO vs Lock).

SLOs TO SET
  p99 query latency per critical endpoint; replication lag p99; connection-pool
  wait time; error budget on "primary CPU < 70%".

RULE: match the fix to the number. Most "we need to shard" incidents are a
missing index, an unpooled connection storm, or an orphaned replication slot.
```

---
""",
        ),
    ],
    # -------------------------------------------------------------- Observability
    "Week-08-Advanced-Patterns/Observability.md": [
        (
            """## Failure Modes

```
CARDINALITY EXPLOSION: unbounded label values → TSDB OOM / cost cliff
SAMPLING GAPS: head-based 1% sampling misses rare tail errors
LOG COST RUNAWAY: verbose debug in prod → billing surprise
ALERT FATIGUE: threshold alerts on self-healing metrics
TRACE PROPAGATION BREAK: missing context headers → broken traces
```

---
""",
            """## Failure Modes

```
FAILURE 1: CARDINALITY EXPLOSION
  Symptom:  Prometheus/CloudWatch OOM or cost spike after a deploy.
  Cause:    a label with unbounded values (user_id, request_id, full URL path).
  Math:     series = product of label cardinalities. Adding user_id (1M) to a
            metric with 20 existing series = 20M series.
  Fix:      remove high-cardinality labels; use exemplars/traces for per-request
            detail; enforce a cardinality budget in CI.

FAILURE 2: SAMPLING GAPS
  Symptom:  a real P1 error class is invisible in traces.
  Cause:    head-based sampling (decide at ingress) drops 99% BEFORE knowing the
            request errored.
  Fix:      tail-based sampling (decide after the trace completes) + always-keep
            on error/slow spans.

FAILURE 3: LOG COST RUNAWAY
  Symptom:  observability bill doubles; no incident.
  Cause:    debug logging left on in prod, or logging full payloads per request.
  Fix:      log levels by environment, structured fields not blobs, retention
            tiers, sampling of high-volume info logs.

FAILURE 4: ALERT FATIGUE / FLAPPING
  Symptom:  oncall ignores pages; real incident missed.
  Cause:    threshold alerts on self-healing metrics (single-spike CPU),
            no multi-window logic.
  Fix:      alert on user-facing SYMPTOMS via SLO burn rate (see SLOs module),
            multi-window (fast + slow), with hysteresis.

FAILURE 5: TRACE PROPAGATION BREAK
  Symptom:  traces stop at a service boundary; "orphan" spans.
  Cause:    a hop drops trace context headers (traceparent), or an async queue
            loses correlation IDs.
  Fix:      propagate W3C traceparent everywhere incl. queues; assert context in
            integration tests.

FAILURE 6: CLOCK SKEW IN SPANS/LOGS
  Symptom:  child span "starts before" parent; log ordering nonsensical.
  Cause:    unsynced host clocks (ties to Week 8 clocks module).
  Fix:      NTP/chrony discipline; rely on span parent/child causality, not raw
            wall-clock ordering.
```

---
""",
        ),
        (
            """## SRE Diagnostic Toolkit

```
METRICS: RED (rate, errors, duration); USE for nodes
LOGS: CloudWatch Logs Insights, Loki LogQL with label selectors
TRACES: X-Ray/OpenTelemetry — verify trace_id propagation
COMMANDS:
  histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))
CARDINALITY: count unique label values before shipping user_id tag
```

---
""",
            """## SRE Diagnostic Toolkit

```
THE THREE PILLARS — WHAT EACH ANSWERS
  Metrics  -> "IS something wrong, and how bad?" (cheap, aggregate, alertable)
  Traces   -> "WHERE in the request path?" (per-request causal chain)
  Logs     -> "WHY exactly did this instance fail?" (detail, expensive at scale)

SERVICE HEALTH — RED METHOD (per service/endpoint)
  Rate:     rate(http_requests_total[5m])
  Errors:   rate(http_requests_total{status=~"5.."}[5m])
  Duration: histogram_quantile(0.99,
              rate(http_request_duration_seconds_bucket[5m]))

RESOURCE HEALTH — USE METHOD (per resource)
  Utilization, Saturation (queue depth / run-queue), Errors.
  node_cpu_seconds_total, node_load1, disk IO await, network drops.

LOGS (structured, queryable)
  CloudWatch Logs Insights:
    fields @timestamp, @message, service, level, trace_id
    | filter level = "ERROR"
    | stats count() by service, bin(5m)
  Loki (LogQL): {service="checkout",level="error"} | json | line_format ...
  Rule: index by low-cardinality LABELS; grep text in small time windows.

TRACES
  Verify propagation end-to-end (W3C traceparent). In X-Ray/Jaeger/Tempo:
  pivot from a slow/error span -> host metrics -> deploy event in 3 clicks.
  Tail-based sampling; always keep error and slow traces.

CARDINALITY GUARDRAIL (do this BEFORE shipping a metric)
  estimated_series = product of (distinct values of each label)
  Refuse user_id, request_id, raw path, or unbounded IDs as metric labels.
  Put per-request identity in traces/logs, not metrics.

INCIDENT WORKFLOW
  1. SLO burn-rate alert fires (symptom).  2. Dashboard: which service/endpoint?
  3. Trace: which hop adds latency/errors? 4. Logs: exact error on that hop.
  5. Correlate to deploy/config change.
```

---
""",
        ),
        (
            """## Decision Framework

```
METRICS → aggregated SLO dashboards
LOGS → "why this request failed" (structured, sampled)
TRACES → cross-service latency chain (tail sampling)
VENDOR: AWS → CloudWatch+X-Ray; K8s → Prom/Grafana/Loki/Tempo
SLO alerting: see SLOs SLIs Error Budgets and Alerting.md
```

---
""",
            """## Decision Framework

```
WHICH PILLAR FOR WHICH QUESTION

  ┌───────────────────────────────┬───────────┬────────────────────────────┐
  │ Question                       │ Pillar    │ Why                        │
  ├───────────────────────────────┼───────────┼────────────────────────────┤
  │ Are we within SLO right now?   │ Metrics   │ cheap, aggregate, alertable│
  │ Which service/hop is slow?     │ Traces    │ per-request causal chain   │
  │ Why did THIS request fail?     │ Logs      │ full detail on one event   │
  │ Novel question in an incident  │ Traces +  │ high-cardinality, ad-hoc   │
  │ we didn't predict              │ wide logs │ pivots                     │
  └───────────────────────────────┴───────────┴────────────────────────────┘

WHAT TO ALERT ON
  Page on user-facing SYMPTOMS via SLO burn rate (see
  "SLOs SLIs Error Budgets and Alerting.md"), NOT on causes like CPU%.
  Cause metrics belong on dashboards for diagnosis, not on the pager.

SAMPLING STRATEGY
  Low traffic       -> keep everything.
  High traffic      -> tail-based sampling + always-keep error/slow traces.
  Never             -> 100% trace retention at high RPS (cost + collector melt).

VENDOR / STACK CHOICE
  ┌───────────────────────┬──────────────────────────────────────────────┐
  │ AWS-native            │ CloudWatch (metrics/logs) + X-Ray (traces)     │
  │ Kubernetes / OSS      │ Prometheus + Grafana + Loki + Tempo            │
  │ High-cardinality      │ Honeycomb / Datadog (cost-aware; watch custom  │
  │ investigation         │ metric + log volume pricing)                   │
  └───────────────────────┴──────────────────────────────────────────────┘

COST DISCIPLINE
  Metrics cost scales with CARDINALITY; logs with VOLUME; traces with
  RETENTION x sampling. Budget each independently and review monthly.
```

---
""",
        ),
    ],
}


def main() -> None:
    changed = []
    for rel, pairs in REPLACEMENTS.items():
        p = ROOT / rel
        text = p.read_text(encoding="utf-8")
        original = text
        for stub, full in pairs:
            if stub in text:
                text = text.replace(stub, full, 1)
            elif full.split("\n", 1)[0] not in text:
                print(f"  WARN: stub not found and full missing in {rel}")
        if text != original:
            p.write_text(text, encoding="utf-8", newline="\n")
            changed.append(rel)
    print(f"Expanded stubs in {len(changed)} files:")
    for c in changed:
        print(f"  {c}")


if __name__ == "__main__":
    main()
