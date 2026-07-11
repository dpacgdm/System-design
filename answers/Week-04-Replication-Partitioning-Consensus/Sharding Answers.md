# Answer Key — Sharding

> Open only after attempting the learner file questions.

---

---

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
╔═══════════════════════════════════════════════════════════════╗
║  SYSTEM       │ PROBLEM TYPE │ FIX                            ║
╠═══════════════════════════════════════════════════════════════╣
║  Cassandra    │ Hot PARTITION│ Synthetic shard_id in          ║
║               │ (celebrity   │ partition key. Celebrity       ║
║               │  feed)       │ feeds split across 16          ║
║               │              │ partitions → 16 node sets.     ║
╠═══════════════════════════════════════════════════════════════╣
║  Elasticsearch│ Hot PARTITION│ Time-based index rollover      ║
║               │ (oversized   │ with ILM. Keep shards <30GB.   ║
║               │  shards)     │ Re-index existing data.        ║
╠═══════════════════════════════════════════════════════════════╣
║  Redis        │ Hot KEY      │ App-level local cache (5s      ║
║               │ (trending    │ TTL). 120K reads/sec → 10.     ║
║               │  topic)      │ Redis replica reads as backup. ║
╠═══════════════════════════════════════════════════════════════╣
║  Citus        │ Query-       │ Materialized view for          ║
║               │ partition    │ cross-shard aggregates.        ║
║               │ mismatch     │ Refresh every 5 min, not       ║
║               │ (scatter-    │ every 10 sec.                  ║
║               │  gather)     │                                ║
╚═══════════════════════════════════════════════════════════════╝
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
╔══════════════════════════════════════════════════════════════╗
║   TIME   │ ACTION                         │ SYSTEM           ║
╠══════════════════════════════════════════════════════════════╣
║   0:00   │ Stop Cassandra data streaming  │ Cassandra        ║
║   0:30   │ Force nodes UP (restart gossip)│ Cassandra        ║
║   1:30   │ Deploy feed caching for hot    │ Cassandra + App  ║
║          │ partitions                     │                  ║
╠══════════════════════════════════════════════════════════════╣
║   3:00   │ Clear ES heap, reduce queues   │ Elasticsearch    ║
║   3:30   │ Throttle search at app layer   │ Elasticsearch    ║
║   5:00   │ Scale ES cluster (add nodes)   │ Elasticsearch    ║
╠══════════════════════════════════════════════════════════════╣
║   7:00   │ Deploy local cache for hot key │ Redis            ║
║   8:00   │ Kill stacking queries, disable │ Citus            ║
║          │ dashboard auto-refresh         │                  ║
╠══════════════════════════════════════════════════════════════╣
║  10:00   │ Systematic verification        │ All              ║
║  15:00   │ Confirm stable, communicate    │ All              ║
╚══════════════════════════════════════════════════════════════╝

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
