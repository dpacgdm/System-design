# Answer Key - NoSQL Taxonomy

> Open only after attempting the learner file questions.

# Incident Deep-Dive: Multi-Database Cascade Failure

---

## Question 1: All Problems — Root Cause and Evidence

### Problem 1: Cassandra Quorum Degradation (The Trigger)

**Component:** Cassandra (Activity feed / notifications)

**Root cause:** Node 2 hardware failure reduces the 3-node cluster to 2 nodes. With RF=3 and QUORUM consistency, the system has **zero margin** — it needs exactly 2 responses and has exactly 2 nodes available. Any additional latency or timeout on either surviving node causes quorum failures.

**Evidence:**
```
→ nodetool status: Node 2 DN (Down Normal), owns 33.3%
→ Feed writes: 5ms → 45ms (9x increase — surviving nodes
  absorbing 50% more coordinator + replica work)
→ Feed reads: some fail with "ConsistencyLevel QUORUM
  not achieved, only 2 of 3 replicas responded"
→ Failure starts immediately at 14:01, 1 minute after
  node 2 death — directly correlated
```

### Problem 2: Redis Memory Pressure and Eviction Storm

**Component:** Redis Cluster (Timeline cache, sessions, rate limiting)

**Root cause:** Cache miss rate increased because Cassandra feed reads are failing, driving more fallback traffic through Redis for timeline cache lookups. Redis node 2 is at 92% of maxmemory (14.1GB / 15GB). The eviction policy (`volatile-lru`) is aggressively evicting keys with TTLs to stay under the memory limit — but it's evicting HOT timeline cache keys that are immediately re-requested, creating a **churn cycle** where evicted keys are re-fetched, re-cached, and re-evicted.

**Evidence:**
```
→ Memory: 14.1GB / 15GB (94% — critically close to limit)
→ Eviction rate: 4,200 keys/sec (21,000 in 5 minutes)
→ Cache hit rate: 94% → 67% (27-point drop)
→ keyspace_hits: 340,000 vs keyspace_misses: 170,000
  → Hit ratio: 340K / (340K+170K) = 66.7% ← MATCHES the 67%
→ connected_clients: 12,400 (massive — 50 app servers ×
  ~250 connections each is plausible under retry pressure)
→ instantaneous_ops_per_sec: 89,000 (high throughput demand)
→ expired_keys: only 890 in 5 min (natural TTL expiry is LOW —
  the 21,000 evictions are FORCED evictions, not organic expiry)
```

### Problem 3: Redis Node 2 Timeout / Overload

**Component:** Redis Cluster node 2 (specific master)

**Root cause:** Redis node 2 specifically is overwhelmed. At 89,000 ops/sec with 12,400 connected clients and 247 blocked clients, the single-threaded Redis event loop cannot process commands fast enough. Memory management overhead from constant evictions (scanning for LRU candidates) adds CPU pressure to every operation.

**Evidence:**
```
→ "TimeoutError: Redis command timed out after 500ms" — 340/minute
→ "All timeouts from Redis Cluster node 2 (master)" — isolated
  to one node
→ blocked_clients: 247 — clients waiting on blocking operations
  (BLPOP, BRPOP, or just queued behind slow operations)
→ 89,000 ops/sec with LRU eviction scanning on every write =
  CPU saturation on single-threaded Redis
```

### Problem 4: MongoDB Connection Spike / Read Latency

**Component:** MongoDB (Posts, comments)

**Root cause:** When the feed cache misses in Redis AND the Cassandra feed read fails, the application falls back to **full feed reconstruction from MongoDB** — querying the posts collection directly. This fallback path takes 180-400ms per request and is hitting 34% of feed requests. Each reconstruction holds a MongoDB connection for the duration, causing connection accumulation. MongoDB read latency is up 3x because of connection overhead and increased query volume, NOT because MongoDB itself is unhealthy.

**Evidence:**
```
→ Connections: 1,847 (normally ~400) — 4.6x increase
→ Read latency: 12ms → 38ms (3.2x increase)
→ Write latency: normal (writes aren't affected —
  this is purely a read-side load issue)
→ MongoDB rs.status(): all members healthy, lag <0.2s
  (MongoDB itself is fine — it's being OVERLOADED by
  traffic it was never designed to handle at this volume)
→ Feed rendering service: 34% of requests hitting the
  full reconstruction path (180-400ms each)
```

### Problem 5: Neo4j Empty Friend Suggestions

**Component:** Neo4j (Friend recommendations) — but the root cause is UPSTREAM, not in Neo4j.

**Root cause:** Neo4j is healthy — normal latency, no errors. The friend suggestion feature depends on **input data from an upstream source** (likely the user's friend list cached in Redis or activity data from Cassandra). With Redis evicting cached friend-list keys and timing out, the friend suggestions endpoint cannot retrieve the input parameters needed to query Neo4j. The application's error handling catches the upstream failure and returns empty results instead of an error.

**Evidence:**
```
→ Neo4j logs: no errors (Neo4j itself is perfectly healthy)
→ Neo4j query latency: normal (when queries ARE made, they're fast)
→ ~30% of users affected — correlates with Redis cache miss
  rate (33% miss rate ≈ 30% empty suggestions)
→ The 30% matches the percentage of users whose friend-list
  cache keys were evicted by volatile-lru or whose requests
  route to the overloaded Redis node 2
→ Timing: 14:08 (8 minutes into incident, after Redis
  degradation is established)
```

### Problem Map

```
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   Cassandra Node 2 Dies (14:00) ← TRIGGER                    ║
║     │                                                        ║
║     ├─► Feed reads fail / slow                               ║
║     │                                                        ║
║     ▼                                                        ║
║   Redis Cache Pressure (14:03)                               ║
║     │  (misses increase → evictions → more misses)           ║
║     │                                                        ║
║     ├─► Redis Node 2 Overload (14:10)                        ║
║     │     (timeouts → retries → more load)                   ║
║     │                                                        ║
║     ├─► MongoDB Overload (14:05)                             ║
║     │     (fallback reads → connection spike)                ║
║     │                                                        ║
║     ╰─► Neo4j Empty Results (14:08)                          ║
║           (missing input data from Redis)                    ║
║                                                              ║
║   PostgreSQL: UNAFFECTED ✓ (independent workload)            ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Question 2: The Cascade Chain

### Exact Causal Chain

```
STEP 1 (14:00): Cassandra node 2 dies
  → Immediate: cluster loses 1/3 of its capacity
  → Surviving nodes 1 and 3 absorb ALL coordinator
    and replica duties
  → Write latency: 5ms → 45ms (nodes working harder)
  → Some reads fail QUORUM (explained in Q3)

         │
         ▼

STEP 2 (14:01-14:03): Feed read failures cascade to Redis
  → Application flow for "load user feed":
    1. Check Redis timeline cache → MISS (or HIT with stale data)
    2. Read from Cassandra activity feed → FAIL (quorum not met)
    3. Fall back to MongoDB full reconstruction

  → When Cassandra reads fail, the application cannot
    POPULATE the Redis cache with fresh feed data
  → Existing cached timelines expire naturally (TTL)
  → New cache entries can't be written (source data unavailable)
  → Cache hit rate begins dropping: 94% → declining

         │
         ▼

STEP 3 (14:03): Redis memory pressure triggers eviction storm
  → Redis is already at 92% memory (14.1GB / 15GB)
  → Increased request volume (more cache checks from
    failing Cassandra reads) pushes memory higher
  → volatile-lru kicks in: evicts 4,200 keys/sec
  → CRITICAL: evicted keys include HOT timeline caches
    that are immediately re-requested
  → Evict → miss → reconstruct → re-cache → evict again
  → POSITIVE FEEDBACK LOOP:

    ╔══════════════════════════════════════════════════════════════╗
    ║   Evict key → cache miss → app queries                       ║
    ║   Cassandra/MongoDB → tries to re-cache                      ║
    ║   → memory still full → evict again                          ║
    ║   → miss again → query again → ...                           ║
    ║                                                              ║
    ║   This is CACHE THRASHING                                    ║
    ╚══════════════════════════════════════════════════════════════╝

         │
         ▼

STEP 4 (14:03-14:05): Cache misses flood MongoDB
  → 34% of feed requests now hit the full reconstruction
    path: Redis miss → Cassandra fail → MongoDB query
  → Each reconstruction: 180-400ms, holds a MongoDB
    connection for the entire duration
  → MongoDB connections: 400 → 1,847 (4.6x)
  → MongoDB read latency: 12ms → 38ms
    (connection management overhead + query queue depth)
  → MongoDB is a VICTIM, not a cause — it's healthy
    but being hammered by traffic it wasn't sized for

         │
         ▼

STEP 5 (14:05-14:10): Redis node 2 becomes overwhelmed
  → 89,000 ops/sec + constant LRU eviction scanning
  → 12,400 connected clients (retries from app servers)
  → Single-threaded Redis can't keep up
  → Commands start timing out: 340 timeouts/minute
  → 247 blocked clients queued behind slow operations
  → Timeouts trigger APPLICATION-LEVEL RETRIES
  → Retries generate MORE Redis commands → more load
  → SECOND POSITIVE FEEDBACK LOOP:

    ╔══════════════════════════════════════════════════════════════╗
    ║   Redis slow → timeout → app retries                         ║
    ║   → more Redis commands → Redis slower                       ║
    ║   → more timeouts → more retries → ...                       ║
    ╚══════════════════════════════════════════════════════════════╝

         │
         ▼

STEP 6 (14:08): Neo4j friend suggestions break
  → Friend suggestions endpoint needs user's current
    friend list as INPUT (to compute friends-of-friends)
  → Friend list is cached in Redis
  → Redis either: evicted the key (cache miss) OR
    timed out on node 2 (500ms timeout)
  → Without input data, application cannot formulate
    the Neo4j query properly
  → Error handling returns empty results (not an error)
  → 30% affected ≈ 33% Redis miss rate — CORRELATED

         │
         ▼

STEP 7 (14:10-14:15): All symptoms compound
  → "My feed is empty" — Cassandra fail + Redis miss +
    MongoDB fallback too slow
  → "I can't see friend suggestions" — Redis eviction/timeout
    → Neo4j gets no input
  → "The app is slow" — everything takes 180-400ms
    instead of 5-50ms
  → "I posted but it disappeared" — post saved to MongoDB
    (write is fine) but feed in Cassandra wasn't updated
    (write slow/failed) and Redis cache shows stale feed
    without the new post
```

### Cascade vs Independent

```
╔══════════════════════════════════════════════════════════════╗
║  CAUSED BY CASCADE    │ REASON                               ║
╠══════════════════════════════════════════════════════════════╣
║  Redis eviction storm │ Cassandra failures → more cache      ║
║                       │ checks + inability to repopulate     ║
╠══════════════════════════════════════════════════════════════╣
║  Redis node 2 timeout │ Increased ops from cache misses      ║
║                       │ + eviction CPU overhead              ║
╠══════════════════════════════════════════════════════════════╣
║  MongoDB overload     │ Fallback path from Redis miss +      ║
║                       │ Cassandra fail → full reconstruct    ║
╠══════════════════════════════════════════════════════════════╣
║  Neo4j empty results  │ Redis eviction/timeout removes       ║
║                       │ upstream input data                  ║
╠══════════════════════════════════════════════════════════════╣
║                       │                                      ║
║  INDEPENDENT          │ REASON                               ║
╠══════════════════════════════════════════════════════════════╣
║  PostgreSQL: healthy  │ User accounts/auth/friendships       ║
║                       │ are a separate workload. Not in      ║
║                       │ the feed read/write path.            ║
║                       │ Connection count, latency, CPU       ║
║                       │ all normal at 14:07.                 ║
╠══════════════════════════════════════════════════════════════╣
║  Redis memory at 92%  │ Redis was ALREADY near capacity      ║
║  pre-incident         │ before Cassandra died. This is a     ║
║  (PARTIALLY           │ pre-existing condition that made     ║
║   INDEPENDENT)        │ the cascade MUCH worse. If Redis     ║
║                       │ had been at 60% memory, evictions    ║
║                       │ wouldn't have started and the        ║
║                       │ cascade would have been contained    ║
║                       │ to just Cassandra degradation.       ║
╚══════════════════════════════════════════════════════════════╝
```

### The Key Insight: Redis Was the Amplifier

```
The Cassandra failure alone would have caused:
  → Feed reads: some failures, some slow
  → Impact: moderate, limited to activity feed

But Redis at 92% memory turned a MODERATE incident
into a PLATFORM-WIDE CASCADE:
  → The eviction storm destroyed cache effectiveness
  → Every cache miss created downstream load on
    Cassandra (making it worse) and MongoDB (dragging
    a healthy system into the incident)
  → Redis itself became a bottleneck (timeouts)
  → Neo4j — a completely unrelated feature — broke
    because its input data was evicted from Redis

If Redis had headroom, the incident would have been:
  "Some feed reads are slow, Cassandra is degraded"
Instead it became:
  "Everything is broken"

Redis was the FORCE MULTIPLIER.
```

---

## Question 3: Why QUORUM Fails with 2 of 3 Nodes Alive

### The Math That Seems Like It Should Work

```
Replication Factor (RF) = 3
Nodes in cluster = 3
QUORUM = floor(RF / 2) + 1 = floor(3/2) + 1 = 2

Node 2 is down. Nodes 1 and 3 are up.
Available replicas for ANY token range = 2
Required for QUORUM = 2

2 available ≥ 2 required → SHOULD WORK

So why do some reads fail?
```

### The Precise Technical Explanation

**With RF=3 across exactly 3 nodes, every piece of data is replicated to ALL 3 nodes. When one node dies, you have exactly 2 replicas available for every token range. QUORUM requires exactly 2 responses. This means you have ZERO MARGIN — you need both surviving nodes to respond for every single read.**

```
WHAT'S ACTUALLY HAPPENING:

The coordinator (say Node 1) receives a read at QUORUM:

  SUCCESSFUL READ:
    Node 1 (coordinator): reads locally → responds ✓
    Node 2: DOWN ✗ (known dead, not contacted)
    Node 3: contacted → responds within timeout ✓
    Responses: 2 ≥ 2 (QUORUM) → SUCCESS

  FAILED READ:
    Node 1 (coordinator): reads locally → responds ✓
    Node 2: DOWN ✗
    Node 3: contacted → DOES NOT RESPOND IN TIME ✗
    Responses: 1 < 2 (QUORUM) → FAILURE

  "Why doesn't Node 3 respond in time?"

  Node 3 is handling 1.5x its normal load:
    → All reads that would have gone to Node 2 now
      hit Nodes 1 and 3
    → All coordinator duties formerly on Node 2 are
      redistributed
    → Hinted handoff writes (storing hints for Node 2's
      data) consume disk I/O
    → The cascade from 14:03+ is driving ADDITIONAL
      read traffic to Cassandra (Redis cache misses
      falling through to Cassandra)

  Under this load:
    → JVM garbage collection pauses (10-200ms stalls)
    → Compaction I/O spikes (Cassandra background
      process merging SSTables)
    → Thread pool exhaustion (read thread pool queue
      backing up)
    → Disk I/O contention (reads competing with
      hinted handoff writes and compaction)

  Any of these can cause Node 3 to miss the
  read_request_timeout (default: 5000ms).
  When it misses timeout, coordinator gets only
  1 response → QUORUM NOT MET.
```

### Why "Some Succeed, Some Fail"

```
The failures are INTERMITTENT because they depend on
TRANSIENT conditions on the surviving nodes:

  Request at T=0.000s: Node 3 is idle → responds
                        in 3ms → QUORUM MET ✓

  Request at T=0.001s: Node 3 is in GC pause →
                        responds in 6,200ms →
                        TIMEOUT → QUORUM NOT MET ✗

  Request at T=0.002s: Node 3 is post-GC → responds
                        in 8ms → QUORUM MET ✓

The reads that fail are the ones that happen to arrive
when one of the two surviving nodes is momentarily
unable to respond — GC pause, compaction, disk flush,
thread pool full.

With 3 healthy nodes and QUORUM=2:
  → You can tolerate 1 slow response
    (any 2 of 3 can satisfy QUORUM)
  → Probability of 2 nodes being simultaneously
    slow is LOW

With 2 healthy nodes and QUORUM=2:
  → You can tolerate ZERO slow responses
  → Probability of 1 node being transiently slow
    is HIGH under load
  → Hence: intermittent failures

╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   3 nodes, QUORUM=2: TOLERATES 1 slow node                   ║
║   2 nodes, QUORUM=2: TOLERATES 0 slow nodes                  ║
║                                                              ║
║   This is the difference between SURVIVING                   ║
║   and BARELY SURVIVING.                                      ║
║                                                              ║
║   RF=3 with QUORUM on 3 nodes can tolerate                   ║
║   1 node FAILURE. But it cannot tolerate                     ║
║   1 node failure + DEGRADATION of a survivor.                ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Question 4: Why volatile-lru Makes This Worse

### What volatile-lru Does

```
Redis eviction policies:

  volatile-lru:  Evicts the Least Recently Used key
                 AMONG keys that have a TTL set.
                 Keys WITHOUT a TTL are NEVER evicted.

  allkeys-lru:   Evicts the Least Recently Used key
                 among ALL keys, regardless of TTL.
```

### The Problem: volatile-lru Protects the WRONG Keys

```
Redis is storing multiple types of data:

  TYPE 1: Timeline caches (feed data)
    → These HAVE TTLs (e.g., TTL=300s, cache for 5 minutes)
    → These are HOT — accessed on every feed load
    → These are RECONSTRUCTABLE (can be rebuilt from
      Cassandra/MongoDB, expensively)
    → volatile-lru: ELIGIBLE for eviction ← BEING EVICTED

  TYPE 2: Session storage
    → These HAVE TTLs (e.g., TTL=86400, 24-hour sessions)
    → These are WARM — accessed on every request for auth
    → volatile-lru: ELIGIBLE for eviction ← AT RISK

  TYPE 3: Rate limiting counters
    → These HAVE TTLs (e.g., TTL=60, per-minute rate windows)
    → These are SMALL but numerous
    → volatile-lru: ELIGIBLE for eviction ← BEING EVICTED

  TYPE 4: Internal application data without TTL
    → Feature flags, configuration caches, etc.
    → These may have NO TTL set
    → These might be STALE or COLD — rarely accessed
    → volatile-lru: IMMUNE FROM EVICTION ← PROTECTED

THE INVERSION:
  volatile-lru is evicting HOT, CRITICAL, FREQUENTLY
  ACCESSED keys (timeline caches with TTL) while
  PROTECTING potentially COLD, STALE, LESS IMPORTANT
  keys (anything without a TTL).

  The eviction policy is BACKWARDS for this workload.
```

### The Thrashing Effect

```
Timeline cache key "feed:user:12345" has TTL=300s.
It's accessed 50 times per minute (hot user).

  T=0:    Key exists, TTL=300s. Cache HIT ✓
  T=1:    Memory pressure → volatile-lru evicts this key
          (it has a TTL, so it's eligible)
  T=1.2:  User refreshes feed → cache MISS ✗
          → Application queries Cassandra → may fail
          → Falls back to MongoDB → 180-400ms reconstruction
          → Re-caches the result: SET feed:user:12345 ... EX 300
  T=1.3:  Memory is still at 92% → new key pushes memory up
          → volatile-lru evicts ANOTHER hot key with TTL
  T=2:    Another user's feed key evicted → same cycle

  This is CACHE THRASHING:
    Evict hot key → miss → expensive rebuild → re-cache
    → memory still full → evict another hot key → ...

  Every eviction CREATES a cache miss.
  Every cache miss CREATES downstream load.
  Every downstream response CREATES a new cache entry.
  Every new cache entry TRIGGERS another eviction.

  Net result: Redis is doing maximum WORK (evict + write
  + evict + write) with minimum BENEFIT (67% hit rate
  instead of 94%).

  Meanwhile, keys WITHOUT TTL sit untouched, consuming
  memory that could be serving hot timeline data.
```

### The Better Policy: allkeys-lru

```
allkeys-lru evicts the Least Recently Used key across
ALL keys — TTL or not.

WITH allkeys-lru:
  → A cold configuration key last accessed 3 hours ago
    (no TTL) would be evicted BEFORE a hot timeline
    cache last accessed 200ms ago (with TTL)
  → Eviction decisions are based purely on ACCESS
    RECENCY, not on whether someone happened to set
    a TTL on the key
  → Hot, frequently-accessed keys survive eviction
    regardless of their TTL status
  → Cold, rarely-accessed keys get evicted regardless
    of their TTL status

THIS MATCHES THE ACTUAL IMPORTANCE OF THE DATA.

The key that was accessed 200ms ago is almost certainly
more valuable to keep cached than the key that hasn't
been touched in 3 hours — regardless of their TTL
configuration.

╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   volatile-lru: "Evict based on TTL + LRU"                   ║
║     → Penalizes well-designed keys (those                    ║
║       with proper TTLs) while protecting                     ║
║       poorly-designed keys (no TTL)                          ║
║                                                              ║
║   allkeys-lru: "Evict based on LRU only"                     ║
║     → The most recently useful data survives                 ║
║     → Regardless of TTL configuration                        ║
║     → This is almost always what you want                    ║
║       under memory pressure                                  ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝

CAVEAT: If you have keys that MUST NEVER be evicted
(like distributed locks), allkeys-lru is dangerous.
Those keys should be in a SEPARATE Redis instance.
Mixing "evictable cache" and "non-evictable state"
in the same Redis instance is an anti-pattern.
```

---

## Question 5: Neo4j Empty Friend Suggestions

### Neo4j Is Healthy — So the Problem Is Upstream

```
Evidence that CONFIRMS Neo4j is not the problem:
  → No errors in Neo4j logs
  → Query latency: normal
  → 70% of users DO get suggestions (Neo4j CAN serve them)
  → Only 30% get empty results

If Neo4j itself were broken:
  → ALL users would be affected, not 30%
  → There would be errors in the logs
  → Latency would be elevated

The 30% number is the critical clue.
It correlates almost exactly with the Redis cache
miss rate: 33% (170K misses / (340K hits + 170K misses)).
```

### The Exact Mechanism

```
The friend suggestions endpoint does this:

  STEP 1: Get the user's current friend list
    → Check Redis cache: GET friends:user:{userId}
    → This key has a TTL (it's a cache)
    → Under volatile-lru evictions, many of these
      keys have been evicted

  STEP 2: If cache hit → use friend list as INPUT to Neo4j
    → Query Neo4j: "Find friends-of-friends of these
      users, excluding users already in the friend list"
    → Neo4j returns recommendations
    → User sees suggestions ✓

  STEP 2 (alternate): If cache MISS → ???
    → The application COULD fall back to PostgreSQL
      to get the friend list
    → But with 14.1GB memory pressure on Redis and
      500ms timeouts on node 2, the application may:

      a) Get a TIMEOUT from Redis (not a miss, a TIMEOUT)
         → Application catches TimeoutError
         → Error handler returns empty results
         → Doesn't even attempt PostgreSQL fallback

      OR

      b) Get a cache miss, attempt PostgreSQL fallback,
         but the fallback has a timeout that's being
         exceeded because the overall request budget
         is consumed by the Redis timeout wait

      OR

      c) Get a cache miss, but the error handling is
         written as:

         try:
             friends = redis.get(f"friends:{user_id}")
             if friends is None:
                 return []  # ← Returns empty instead
                             #   of falling back
         except TimeoutError:
             return []      # ← Same result

         suggestions = neo4j.query(
             "MATCH (u)-[:FRIEND]->(f)-[:FRIEND]->(rec)...",
             friend_ids=friends
         )

  In any case: Redis failure → no input for Neo4j
  → empty results returned to user

WHY 30% AND NOT 33%:
  The 33% is the overall Redis miss rate.
  The friend suggestions endpoint may access a
  different key distribution than the average.
  Some friend-list keys may be smaller (less likely
  to be evicted by LRU) or more recently accessed.
  30% ≈ 33% is close enough to confirm the correlation.
```

### The Diagnostic Proof

```
TO VERIFY THIS HYPOTHESIS:

  1. Check if friend-list keys exist in Redis:
     redis-cli --scan --pattern "friends:user:*" | wc -l
     Compare to total active users — if significantly
     fewer keys than expected, confirms eviction.

  2. Check one of the affected users:
     redis-cli EXISTS friends:user:12345
     → 0 (key doesn't exist — evicted)

     redis-cli EXISTS friends:user:67890
     → 1 (key exists — this user gets suggestions)

  3. Check application logs for the friend suggestions
     endpoint specifically:
     → Look for TimeoutError or cache miss logs
       correlated with empty responses

THIS IS THE PATTERN:
  A "healthy" system returning wrong results because
  its UPSTREAM DEPENDENCY is degraded. Neo4j can't
  know it's returning empty results for the wrong
  reason — it never even received a query for those
  30% of users. The failure is INVISIBLE from Neo4j's
  perspective.
```

---

## Question 6: Prioritized Mitigation Plan

### Priority Ranking

```
╔════════════════════════════════════════════════════════════════════╗
║  RANK │ ACTION                   │ JUSTIFICATION                   ║
╠════════════════════════════════════════════════════════════════════╣
║   1   │ Downgrade Cassandra      │ STOPS THE TRIGGER. Quorum       ║
║       │ consistency level        │ failures are the root cause     ║
║       │                          │ of the entire cascade.          ║
╠════════════════════════════════════════════════════════════════════╣
║   2   │ Fix Redis memory +       │ STOPS THE AMPLIFIER. Redis      ║
║       │ eviction policy          │ evictions are turning a single  ║
║       │                          │ Cassandra issue into platform-  ║
║       │                          │ wide degradation.               ║
╠════════════════════════════════════════════════════════════════════╣
║   3   │ Restore Cassandra        │ FIXES ROOT CAUSE permanently.   ║
║       │ capacity (replace node)  │ Until node 2 is back, zero      ║
║       │                          │ margin on quorum.               ║
╠════════════════════════════════════════════════════════════════════╣
║   4   │ MongoDB connection       │ PROTECT VICTIM. MongoDB is      ║
║       │ limiting                 │ being dragged into the cascade. ║
║       │                          │ Prevent it from becoming        ║
║       │                          │ another failure point.          ║
╠════════════════════════════════════════════════════════════════════╣
║   5   │ Neo4j input fallback     │ RESTORE FEATURE. Add fallback   ║
║       │                          │ to PostgreSQL for friend list   ║
║       │                          │ when Redis unavailable.         ║
╚════════════════════════════════════════════════════════════════════╝
```

### Step 1: Downgrade Cassandra Reads to ONE (Minute 0-3)

```bash
# With only 2 nodes alive and QUORUM=2, we have zero margin.
# Downgrade READ consistency to ONE.
# This means only 1 replica needs to respond for a read to succeed.
# With 2 nodes alive, reads will almost always succeed.

# Trade-off: possible stale reads (no read-repair at CL=ONE).
# For an activity feed, slightly stale data is acceptable.
# Much better than FAILED reads causing the entire cascade.

# APPLICATION-LEVEL CHANGE (in the Cassandra client config):
# If configurable at runtime (feature flag or config service):
```

```python
# In the activity feed service's Cassandra client:
# BEFORE:
cluster = Cluster(contact_points=['cass1', 'cass3'])
session = cluster.connect('activity')
session.default_consistency_level = ConsistencyLevel.QUORUM

# AFTER:
session.default_consistency_level = ConsistencyLevel.ONE

# Keep WRITES at QUORUM (or LOCAL_QUORUM) to maintain
# write durability — we can tolerate stale reads but
# not lost writes.
```

```bash
# If the application needs redeployment for this change:
kubectl set env deployment/feed-service \
  CASSANDRA_READ_CONSISTENCY=ONE

# VERIFY:
# → Feed read errors should drop to near zero immediately
# → "ConsistencyLevel QUORUM not achieved" errors stop
# → Feed write latency should remain at ~45ms (still slow
#   but succeeding at QUORUM with 2 nodes)
# → Watch for 60 seconds before proceeding
```

**VERIFY before proceeding:**
```
→ Cassandra read errors: 0
→ Feed reads succeeding at CL=ONE
→ Feed read latency: should drop to 5-15ms
  (only need 1 node to respond)
→ Application feed-related error rate dropping
```

### Step 2: Fix Redis Memory Pressure (Minute 3-8)

```bash
# TWO ACTIONS: change eviction policy + free memory

# ACTION 2A: Change eviction policy from volatile-lru to allkeys-lru
redis-cli -h redis-node-2 CONFIG SET maxmemory-policy allkeys-lru

# This immediately changes eviction behavior:
# → Cold keys without TTL are now eligible for eviction
# → Hot timeline caches with TTL are less likely to be evicted
# → Eviction decisions based on ACCESS RECENCY, not TTL existence

# Repeat for all Redis cluster masters:
redis-cli -h redis-node-1 CONFIG SET maxmemory-policy allkeys-lru
redis-cli -h redis-node-3 CONFIG SET maxmemory-policy allkeys-lru

# ACTION 2B: Increase maxmemory if possible (buys immediate headroom)
# Check available system memory first:
redis-cli -h redis-node-2 INFO memory
# Look at: used_memory_rss vs total_system_memory

# If system has headroom:
redis-cli -h redis-node-2 CONFIG SET maxmemory 18gb
# Gives 4GB more headroom — stops the eviction storm entirely

# If system memory is tight, DON'T increase — allkeys-lru
# alone will improve hit rate by evicting cold keys.

# ACTION 2C: Persist the config change
redis-cli -h redis-node-2 CONFIG REWRITE
```

**VERIFY before proceeding:**
```
→ Eviction rate should drop (redis-cli INFO stats | grep evicted)
→ Cache hit rate should start climbing back toward 90%+
→ Watch: keyspace_hits / (keyspace_hits + keyspace_misses)
→ Redis node 2 timeouts should decrease
  (less eviction CPU overhead)
→ MongoDB connection count should start declining
  (fewer fallback reads needed)
→ Wait 60-90 seconds — cache needs time to warm back up
```

### Step 3: Replace Cassandra Node 2 (Minute 8-20)

```bash
# This is the permanent fix — restore the cluster to 3 nodes.
# Until node 2 is back, we're running on zero margin.

# OPTION A: If node 2's hardware can be recovered/replaced
# Start the node — it will automatically rejoin and stream
# data from nodes 1 and 3:
# (on new/repaired hardware with Cassandra installed)
sudo systemctl start cassandra

# Monitor bootstrap/streaming progress:
nodetool netstats
# Look for: "Receiving" streams — data being copied
# from existing nodes

# OPTION B: If node 2 is dead, add a completely new node
# On new hardware:
# 1. Install Cassandra with same cluster_name and seeds
# 2. Set auto_bootstrap: true in cassandra.yaml
# 3. Start Cassandra — it will join and stream data

# Monitor:
nodetool status
# Wait until new node shows UN (Up Normal)
# Streaming can take 10-60 minutes depending on data volume

# OPTION C (fastest): If this is Kubernetes/containerized
kubectl delete pod cassandra-2
# StatefulSet will recreate it with persistent volume
# OR if the PV is lost:
kubectl delete pvc cassandra-data-2
kubectl delete pod cassandra-2
# New pod will bootstrap from scratch
```

```bash
# VERIFY:
nodetool status
# Should show all 3 nodes as UN
# Once 3 nodes are healthy:

# Restore QUORUM consistency for reads:
kubectl set env deployment/feed-service \
  CASSANDRA_READ_CONSISTENCY=QUORUM

# VERIFY: reads still succeeding at QUORUM with 3 nodes
```

### Step 4: Protect MongoDB (Minute 8-12, parallel with Step 3)

```bash
# MongoDB connections spiked from 400 to 1,847.
# Even though Steps 1-2 should reduce the fallback traffic,
# add protection so MongoDB doesn't become the next victim.

# Set a connection limit on the MongoDB connection pool
# in the application:
kubectl set env deployment/feed-service \
  MONGODB_MAX_POOL_SIZE=200 \
  MONGODB_WAIT_QUEUE_TIMEOUT_MS=2000

# This means:
# → Max 200 connections to MongoDB from feed service
# → If all 200 are busy, new requests wait up to 2 seconds
# → After 2 seconds, return an error (fail fast instead
#   of accumulating unlimited connections)

# Also: if feed reconstruction is still happening at high rate,
# add a circuit breaker to the fallback path:
kubectl set env deployment/feed-service \
  FEED_RECONSTRUCTION_CIRCUIT_BREAKER=true \
  FEED_RECONSTRUCTION_MAX_CONCURRENT=50

# Only allow 50 concurrent full-reconstruction requests.
# Beyond that, return a degraded "feed temporarily unavailable"
# response instead of overloading MongoDB.
```

**VERIFY:**
```
→ MongoDB connections declining toward 400
→ MongoDB read latency declining toward 12ms
→ No new MongoDB-related errors
```

### Step 5: Fix Neo4j Input Path (Minute 12-15)

```python
# The friend suggestions endpoint needs a fallback for when
# Redis doesn't have the friend list.

# BEFORE (pseudocode):
async def get_friend_suggestions(user_id):
    try:
        friends = await redis.get(f"friends:{user_id}")
        if friends is None:
            return []  # ← BUG: returns empty on cache miss
    except TimeoutError:
        return []      # ← BUG: returns empty on timeout

    return await neo4j.query(SUGGESTIONS_QUERY, friends=friends)

# AFTER:
async def get_friend_suggestions(user_id):
    friends = None

    # Try Redis first
    try:
        friends = await redis.get(f"friends:{user_id}")
    except (TimeoutError, ConnectionError):
        pass  # Fall through to PostgreSQL

    # Fallback to PostgreSQL if Redis miss/timeout
    if friends is None:
        friends = await postgres.fetch(
            "SELECT friend_id FROM friendships "
            "WHERE user_id = $1", user_id
        )
        # Re-cache for next time (async, don't block)
        asyncio.create_task(
            redis.set(f"friends:{user_id}",
                      serialize(friends), ex=3600)
        )

    if not friends:
        return []  # User genuinely has no friends

    return await neo4j.query(SUGGESTIONS_QUERY, friends=friends)
```

```bash
# Deploy:
kubectl rollout restart deployment/friend-suggestions-service

# VERIFY:
# → Empty friend suggestions rate should drop from 30% to ~0%
# → PostgreSQL connection count may increase slightly
#   (but PostgreSQL is healthy at 14:07 — plenty of headroom)
# → Neo4j query volume should increase (now receiving the
#   queries it was missing)
```

### Mitigation Timeline Summary

```
╔══════════════════════════════════════════════════════════════╗
║  MINUTE   │ ACTION                                           ║
╠══════════════════════════════════════════════════════════════╣
║  0-3      │ Downgrade Cassandra reads to CL=ONE              ║
║           │ VERIFY: feed read errors → 0                     ║
║           │ EFFECT: stops the cascade trigger                ║
╠══════════════════════════════════════════════════════════════╣
║  3-8      │ Change Redis to allkeys-lru + increase memory    ║
║           │ VERIFY: eviction rate dropping, hit rate rising  ║
║           │ EFFECT: stops the amplification loop             ║
╠══════════════════════════════════════════════════════════════╣
║  8-12     │ Protect MongoDB (connection limits + circuit     ║
║           │ breaker on reconstruction path)                  ║
║           │ VERIFY: MongoDB connections declining            ║
║           │ EFFECT: protects healthy system from overload    ║
╠══════════════════════════════════════════════════════════════╣
║  8-20     │ Replace Cassandra node 2 (parallel with above)   ║
║  (parallel)│ VERIFY: nodetool shows 3 UN nodes               ║
║           │ EFFECT: restores quorum margin permanently       ║
║           │ → Restore CL=QUORUM after node is healthy        ║
╠══════════════════════════════════════════════════════════════╣
║  12-15    │ Deploy Neo4j input fallback to PostgreSQL        ║
║           │ VERIFY: empty suggestions → 0%                   ║
║           │ EFFECT: restores friend suggestions feature      ║
╠══════════════════════════════════════════════════════════════╣
║  15+      │ Monitor stability across all systems             ║
║           │ Confirm:                                         ║
║           │   → Cassandra reads: 0 errors, <10ms latency     ║
║           │   → Redis: hit rate >90%, evictions near 0       ║
║           │   → MongoDB: connections ~400, latency ~12ms     ║
║           │   → Neo4j: suggestions working for >99% users    ║
║           │   → All customer complaints resolved             ║
║           │                                                  ║
║           │ Write post-incident review                       ║
╚══════════════════════════════════════════════════════════════╝

PRINCIPLE FOLLOWED:
  1. Stop the TRIGGER (Cassandra consistency)     → Verify
  2. Stop the AMPLIFIER (Redis eviction)          → Verify
  3. Protect VICTIMS (MongoDB, Neo4j)             → Verify
  4. Fix ROOT CAUSE permanently (replace node)    → Verify

  One change at a time. Verify. Then next change.
  Except Step 3 and Cassandra node replacement can
  run in parallel — they're independent infrastructure
  actions on different systems.
```

---

## Preserved notes from retired Northstar drill

## Ops Sim: Northstar Polyglot Store Cascade

### Q1 - Layer & root cause

Source of truth for inventory is Cassandra `inv-cas`. Redis is a cache. Mongo seller snapshots are derived/read-model data and are not safe for final checkout authorization.

The cascade starts with Cassandra quorum read timeouts after a node failure and auction load. Redis misses amplify Cassandra reads; unsafe fallback to Mongo introduces stale decisions.

### Q2 - Evidence

- Cassandra: `ReadTimeoutException received only 1 responses from 2 required`, p99 480ms, one node down.
- Redis: hit rate 58%, `volatile-lru` evicting `inventory:sku:*`.
- Mongo fallback: `stale_age=17m` and connections rising to 1,980.

### Q3 - First actions

1. Declare P1 because stock correctness affects checkout.
2. Disable `allow_checkout_on_snapshot`; snapshots may display "checking stock" but cannot approve orders.
3. For affected SKUs, route final stock checks to Cassandra write/leader path or fail closed.
4. Reduce read pressure: cache negative/uncertain state briefly, throttle non-checkout inventory badge refresh, and protect Redis memory.
5. Replace/recover the Cassandra node only after checking repair/streaming capacity.
6. Monitor false positives/oversell counters, Cassandra timeouts, Redis evictions, and Mongo connections.

### Q4 - Bad fixes

Global CL=ONE improves availability but can read stale or divergent replicas for inventory. It can create oversells or false stock displays.

Checkout on 30-minute snapshots is unsafe because auctions can sell out in seconds. Snapshot data is for display/search, not final stock reservation.

### Q5 - Capacity / blast radius

With RF=3 and LOCAL_QUORUM=2, a read needs two replica responses. If one replica is down and one surviving replica is slow/overloaded or not contacted successfully before timeout, the coordinator receives only one response and fails.

Fallback triples Mongo reads and can exhaust Mongo connection pools, slowing seller pages and any service sharing the cluster.

### Q6 - Durable fix

- Explicit source-of-truth contract: only Cassandra/checkout reservation path authorizes stock.
- Separate display freshness from checkout correctness.
- Bound fallback age and forbid stale fallback for writes.
- Tune Cassandra timeouts/speculative retry for auction hot partitions.
- Pre-warm Redis and use allkeys-lfu/lru as appropriate for cache workloads.
- Add per-SKU degradation: show "checking stock" rather than stale counts.

### Q7 - Org / runbook

Notify incident commander, inventory owner, checkout owner, Cassandra on-call, seller-content/Mongo owner, support, and auction business owner.

Allowed degradation: hide exact stock counts or show "checking stock" for affected SKUs. Not allowed: approving checkout from stale snapshots.
