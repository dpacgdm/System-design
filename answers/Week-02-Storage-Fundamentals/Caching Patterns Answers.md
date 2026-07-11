# Answer Key - Caching Patterns

> Open only after attempting the learner file Ops Sim.

## Ops Sim: Northstar Flash Deal Cache Stampede

### Q1 - Layer & root cause

Three interacting problems:

1. Stale-price race: cache key was deleted before the DB transaction committed; concurrent miss rebuilt old data into Redis.
2. Stampede: no singleflight/stale-while-revalidate/jitter, so many clients rebuilt the same key at once.
3. Hot key: `deal:sku:watch-8844` is large and receives 82k reads/min on one Redis node.

### Q2 - Evidence

- Timeline shows `DEL` before `COMMIT`, then rebuild from old DB snapshot.
- Redis L2 hit rate falls to 63% while Postgres QPS rises 18x.
- SLOWLOG and hot-key access show one large key blocking node-3.

Misleading metric: L1/L2 hit rate alone. A high hit rate can still serve wrong prices; correctness must be measured with mismatch alerts.

### Q3 - First actions

1. Declare P1 because users are charged wrong prices.
2. Stop checkout for affected promoted SKUs or force price verification from source of truth before charge.
3. Correct/purge the affected keys after the DB commit is verified.
4. Disable delete-before-commit path; use after-commit invalidation or write-through.
5. Enable singleflight/rebuild locking and temporary stale-while-revalidate for read-only product display.
6. Reduce hot-key pressure with local coalescing, key splitting, or CDN/static snapshot for public deal content.

### Q4 - Bad fixes

Increasing TTL preserves wrong prices longer and expands financial exposure.

Flushing all Redis keys creates a global cache miss storm, shifting load to Postgres and other backing stores. It may take checkout down even if only one deal key is corrupt.

### Q5 - Capacity / blast radius

At 7,600 reads/sec and p99 310ms, at-risk systems include:
- PgBouncer client/server pools.
- Postgres CPU/IO and connection count.
- App worker pools waiting on DB reads.
- Checkout price verification latency.
- Any service sharing the same Redis node or database.

### Q6 - Durable fix

- Invalidate after commit, or use transactional outbox/CDC to publish price changes.
- Add singleflight locks for cache rebuilds.
- Add TTL jitter and stale-while-revalidate for display-only data.
- Split large hot keys by field or shard; avoid `HGETALL` on multi-MB values.
- Use source-of-truth price verification in checkout.

Acceptance: replay promotion launch with no price mismatches, no Redis node >70% CPU, and Postgres QPS within planned fallback capacity.

### Q7 - Org / runbook

Notify incident commander, checkout/pricing owners, finance, legal, support, and business owner.

Start affected-order identification and refund/credit workflow immediately. Pre-authorized: disable affected SKU checkout, bypass cache for final price calculation, purge specific price keys after DB verification.
# Answer Key — Caching Patterns

> Open only after attempting the learner file questions.

---

# Incident Deep-Dive: Cache Stampede, Hot Keys, and Stale Pricing

---

## Question 1: All Problems — Root Cause, Component, Evidence

### Problem 1: Cache Stampede / Thundering Herd (The Cascade Trigger)

**Component:** L1 Caffeine → L2 Redis → PostgreSQL (all three layers)

**Root cause:** The marketing push notification sent 800,000 users to browse Manhattan restaurants simultaneously. This 4.4x traffic spike (50K → 220K concurrent) overwhelmed the cache hierarchy. The L1 cache (5,000 entries per server, 30s TTL) is far too small for the sudden working set of Manhattan restaurants being browsed. L1 misses cascade to L2 Redis. The surge of L2 lookups for the same popular restaurants creates a **cache stampede** — hundreds of concurrent requests for the same key all miss L2 simultaneously (because the key either expired or was never cached for that specific data), all fall through to PostgreSQL, all independently query the database for the same data, and all independently re-cache the result.

**Evidence:**
```
→ Traffic: 50K → 220K concurrent in 90 seconds (4.4x spike)
→ L1 hit rate: 72% → 31% (cache too small for new working set)
→ L2 hit rate: 96% → 71% (stampede misses flooding Redis)
→ PostgreSQL queries/sec: 380 → 8,400 (22x increase — NOT 4.4x,
  because cache misses multiply the load on the DB)
→ L1 eviction: 12,000 keys/sec (cache is thrashing —
  explained in Q3)
→ Redis ops/sec: 45K → 189K (4.2x increase in Redis traffic)
```

### Problem 2: Hot Key on Redis Node 3 (Infrastructure Bottleneck)

**Component:** Redis Cluster node 3

**Root cause:** Restaurant 5678 is a popular Manhattan restaurant. Its data is stored as a 2.3MB hash key (`restaurant:manhattan:5678`) that hashes to a slot owned by Redis node 3. The marketing campaign drives 47,000 accesses/minute to this single key. Redis is single-threaded — every HGETALL on a 2.3MB key blocks the event loop for ~23ms. At 47,000 requests/minute (~783/sec), the key alone consumes `783 × 23ms = 18 seconds of processing per second` — exceeding 100% of a single-threaded Redis node's capacity.

**Evidence:**
```
→ Redis node 3 CPU: 98% (other nodes presumably normal)
→ Redis node 3 response time: 23ms (other nodes: 0.4ms) — 57x slower
→ slowlog: HGETALL restaurant:manhattan:5678 = 23ms
→ Key size: 2.3MB (extremely large for Redis — should be <10KB)
→ Access count: 47,000 times in last minute
→ Memory: 13.8GB / 16GB (86%) — high but not the primary issue;
  CPU/throughput is the bottleneck
```

### Problem 3: Stale Price Cache Race Condition (Financial/Legal Issue)

**Component:** Redis L2 cache ↔ PostgreSQL write path (cache invalidation logic)

**Root cause:** The cache invalidation sequence has a race condition. The application deletes the Redis key (`menu:restaurant:5678`) BEFORE the PostgreSQL transaction commits the new prices. In the window between cache deletion and transaction commit (~45ms in this case), concurrent requests miss the cache, read the OLD prices from PostgreSQL (transaction not yet committed, so READ COMMITTED isolation returns the previous row version), and re-cache those stale prices with a 300-second TTL.

**Evidence:**
```
→ Timeline reconstruction (18:31:00.100 - 18:31:00.151):
  → Cache delete at .105, DB commit at .150
  → 45ms window where cache is empty but DB has old data
  → 340 concurrent requests in that window
  → First request at .108 reads old prices, re-caches at .110
  → DB commits at .150 — too late, cache already poisoned
→ Customer complaints: "I see full prices, not 50% off"
→ Order service logs: orders using CACHED full prices
→ Restaurant owner: "I updated but customers see old prices"
→ Finance team: "We're charging full price during a 50% off campaign"
```

### Problem 4: L1 Cache Thrashing (Amplifier)

**Component:** Caffeine L1 cache (in-process on each app server)

**Root cause:** The L1 cache is limited to 5,000 entries per server. The marketing campaign caused a sudden expansion of the active working set — users browsing hundreds of Manhattan restaurants simultaneously. The working set exceeds 5,000 entries, so every new restaurant lookup evicts a recently-cached entry. The evicted entries are then re-requested almost immediately (high-traffic restaurants), creating a thrashing cycle where the cache is full but useless. Explained in detail in Q3.

**Evidence:**
```
→ cache_size: 5,000/5,000 on EVERY server (full)
→ eviction_count: 12,000/sec (entries being pushed out
  as fast as they come in)
→ hit_rate: 72% → 31% (cache is full but ineffective)
→ 40 servers × 12,000/sec = 480,000 evictions/sec globally
```

### Problem 5: PostgreSQL Connection Pool Near Exhaustion

**Component:** PostgreSQL (via connection pool)

**Root cause:** Cache misses from L1 and L2 cascade to PostgreSQL. With the `SELECT * FROM menu_items WHERE restaurant_id = $1` query averaging 89ms under load (normally ~4ms), connections are held ~22x longer. Pool capacity is consumed by slow queries. At 180/200 connections used, the pool is approaching exhaustion — once it hits 200, new requests will block or fail with "Connection pool exhausted."

**Evidence:**
```
→ Connection pool: 180/200 (90% utilized, 20 connections from failure)
→ Queries/sec: 380 → 8,400 (22x increase)
→ p99 latency: 4ms → 340ms
→ Query avg_exec_time: 89ms (normally much lower —
  contention + I/O pressure from 22x query volume)
→ Error: "Connection pool exhausted" already appearing at 18:36
```

### Cascade vs Independent

```
╔══════════════════════════════════════════════════════════════╗
║  CAUSED BY CASCADE    │ CHAIN                                ║
╠══════════════════════════════════════════════════════════════╣
║  L1 thrashing         │ Traffic spike → working set          ║
║                       │ exceeds L1 capacity → thrashing      ║
╠══════════════════════════════════════════════════════════════╣
║  L2 Redis overload    │ L1 misses cascade to L2 +            ║
║                       │ hot key amplifies load on node 3     ║
╠══════════════════════════════════════════════════════════════╣
║  PostgreSQL overload  │ L1 miss + L2 miss → DB fallback      ║
║                       │ at 22x normal volume                 ║
╠══════════════════════════════════════════════════════════════╣
║  Connection pool      │ Slow DB queries hold connections     ║
║  exhaustion           │ longer → pool drains                 ║
╠══════════════════════════════════════════════════════════════╣
║                       │                                      ║
║  INDEPENDENT          │ REASON                               ║
╠══════════════════════════════════════════════════════════════╣
║  Stale price race     │ This is a CODE BUG in the cache      ║
║  condition            │ invalidation logic. It would         ║
║                       │ exist even without the traffic       ║
║                       │ spike. The spike made it VISIBLE     ║
║                       │ (340 concurrent requests in the      ║
║                       │ race window) but the bug was         ║
║                       │ always latent. Under normal          ║
║                       │ traffic, maybe 1-2 requests hit      ║
║                       │ the window — still wrong but         ║
║                       │ rarely noticed.                      ║
╠══════════════════════════════════════════════════════════════╣
║  Hot key (2.3MB)      │ PARTIALLY independent. The key       ║
║                       │ being 2.3MB is a pre-existing        ║
║                       │ data modeling problem. The traffic   ║
║                       │ spike made it catastrophic.          ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Question 2: The Cache Invalidation Race Condition

### Why Deleting Before Commit Caused the Problem

```
The application's invalidation sequence:

  18:31:00.102 — BEGIN transaction
  18:31:00.105 — DELETE Redis key "menu:restaurant:5678"
  18:31:00.108 — UPDATE menu_items SET price = price * 0.5
                  WHERE restaurant_id = 5678
  18:31:00.150 — COMMIT

The problem is in the ORDER OF OPERATIONS.

At 18:31:00.105, the Redis key is deleted.
At 18:31:00.105-18:31:00.150, the Redis cache is EMPTY
but the database STILL HAS THE OLD PRICES.

WHY? PostgreSQL uses MVCC (Multi-Version Concurrency Control).
Under READ COMMITTED isolation (the default):
  → Other transactions can only see data that has been COMMITTED
  → The new prices are part of an UNCOMMITTED transaction
  → Any concurrent SELECT reads the LAST COMMITTED version
    (the old full prices)

So the window of vulnerability is:

  ╔══════════════════════════════════════════════════════════════╗
  ║                                                              ║
  ║   CACHE DELETE          DB COMMIT                            ║
  ║        │                    │                                ║
  ║   ─────┼────────────────────┼──────── time ────►             ║
  ║        │                    │                                ║
  ║        │◄──── DANGER ZONE ──►│                               ║
  ║        │   (cache empty,     │                               ║
  ║        │    DB has old data) │                               ║
  ║        │                    │                                ║
  ║   Any request in this window:                                ║
  ║     1. Checks Redis → MISS (we just deleted it)              ║
  ║     2. Falls through to PostgreSQL                           ║
  ║     3. Reads OLD prices (UPDATE not committed yet)           ║
  ║     4. Re-caches OLD prices in Redis with TTL=300            ║
  ║     5. Cache is now POISONED for 300 seconds                 ║
  ║                                                              ║
  ║   Even after the DB commits at .150:                         ║
  ║     → The correct prices are in PostgreSQL                   ║
  ║     → But Redis has the OLD prices                           ║
  ║     → All subsequent reads hit Redis (cache HIT)             ║
  ║     → Everyone sees stale prices for up to 300s              ║
  ║                                                              ║
  ╚══════════════════════════════════════════════════════════════╝

With 340 concurrent requests in a 45ms window:
  → The FIRST request to hit PostgreSQL after the cache
    delete re-poisons the cache
  → The remaining 339 requests get cache HITs on the
    poisoned entry
  → Nobody sees the new prices until TTL expires (300s)
  → 5 MINUTES of wrong pricing during a major promotion
```

### Approach 1: Delete AFTER Commit (Simple, Slight Staleness Window)

```python
# Delete the cache key AFTER the database transaction commits.
# This ensures that when the cache is empty and requests
# fall through to PostgreSQL, they read the NEW committed data.

async def update_menu_prices(restaurant_id, new_prices):
    # Step 1: Commit to database FIRST
    async with db.transaction():
        await db.execute(
            "UPDATE menu_items SET price = $1 "
            "WHERE restaurant_id = $2",
            new_prices, restaurant_id
        )
    # ← Transaction COMMITTED here

    # Step 2: Delete cache AFTER commit
    await redis.delete(f"menu:restaurant:{restaurant_id}")

    # Now when concurrent requests miss Redis,
    # they read from PostgreSQL and get the NEW prices.
```

**Tradeoff:**
```
✓ PREVENTS the stale-cache-poisoning race condition
✓ Simple to implement — just reorder two lines
✓ Concurrent reads after cache delete see NEW prices

✗ SMALL STALENESS WINDOW exists between DB commit and
   cache delete (~5-50ms depending on network latency
   to Redis). During this window, reads hit the STALE
   cache entry (old prices). But this window is:
   - Much shorter than the 45ms danger zone in the original
   - Serves stale data that EXISTS, not empty-then-repoisoned
   - Self-resolving as soon as the delete executes

✗ If the cache delete FAILS (Redis down, network blip):
   - Cache retains old data until TTL expires (300s)
   - Need a retry mechanism or background invalidation job

✗ Still vulnerable to a DIFFERENT race: if another request
   is reading from PostgreSQL at the exact moment between
   commit and cache delete, it might re-cache the old
   data... wait, no — after commit, PostgreSQL returns
   new data. This race doesn't exist.

   ACTUALLY: there IS a subtler race:
   Request A: reads DB (gets new prices) at T=1
   Cache delete happens at T=2
   Request B: misses cache at T=3, reads DB (new prices)
   Request A: writes to cache at T=4 (new prices ✓)

   This is fine — both A and B have new prices.
   The delete-after-commit approach is SAFE from
   the poisoning race.
```

### Approach 2: Write-Through Cache (Strongest Consistency)

```python
# Instead of deleting the cache key, OVERWRITE it with
# the new data after the database commits.
# No cache miss occurs, so no stampede, no race condition.

async def update_menu_prices(restaurant_id, new_prices):
    # Step 1: Commit to database
    async with db.transaction():
        await db.execute(
            "UPDATE menu_items SET price = $1 "
            "WHERE restaurant_id = $2",
            new_prices, restaurant_id
        )
    # ← Transaction COMMITTED

    # Step 2: Write the new data directly to cache
    new_menu_data = await db.fetch(
        "SELECT * FROM menu_items WHERE restaurant_id = $1",
        restaurant_id
    )
    await redis.set(
        f"menu:restaurant:{restaurant_id}",
        serialize(new_menu_data),
        ex=300  # Reset TTL
    )

    # Cache now has CORRECT data immediately.
    # No cache miss → no stampede → no race condition.
```

**Tradeoff:**
```
✓ ELIMINATES the cache miss entirely — no race window
✓ ELIMINATES the stampede on popular keys
   (cache never goes empty)
✓ Strongest consistency — cache is updated atomically
   with the write
✓ No window where any read can see stale data
   (except the tiny commit-to-cache-write gap)

✗ MORE COMPLEX: requires the write path to know the
   exact cache key format and serialization
   → Tight coupling between write path and cache schema
   → If the cache key format changes, writes break

✗ EXTRA DATABASE READ after commit to populate the cache
   → One additional SELECT per write operation
   → Acceptable for menu updates (infrequent writes)
   → Would be problematic for high-write-rate data

✗ DOESN'T HELP if the write-through fails:
   → If Redis is unreachable during the SET, the cache
     retains old data (same as Approach 1)
   → Need retry/fallback mechanism

✗ SUBTLE RACE still possible with concurrent writers:
   Writer A: commits price=$50, writes to cache ($50)
   Writer B: commits price=$45, writes to cache ($45)
   If Writer A's cache write is delayed:
     Writer B writes $45 to cache
     Writer A overwrites with $50 (STALE!)
   Fix: use a version counter or timestamp in the cache
   key to prevent out-of-order writes
```

### Summary

```
╔═══════════════════════════════════════════════════════════════╗
║                      │ DELETE AFTER COMMIT│ WRITE-THROUGH     ║
╠═══════════════════════════════════════════════════════════════╣
║  Race condition      │ ELIMINATED         │ ELIMINATED        ║
║  Stampede on miss    │ Still possible     │ ELIMINATED        ║
║                      │ (cache is empty    │ (cache never      ║
║                      │ briefly)           │ empty)            ║
╠═══════════════════════════════════════════════════════════════╣
║  Complexity          │ LOW (reorder lines)│ MODERATE (write   ║
║                      │                    │ path knows cache) ║
╠═══════════════════════════════════════════════════════════════╣
║  Staleness window    │ ~5-50ms (commit to │ ~5-50ms (commit   ║
║                      │ delete)            │ to cache write)   ║
╠═══════════════════════════════════════════════════════════════╣
║  Concurrent writer   │ SAFE (delete is    │ NEEDS versioning  ║
║  safety              │ idempotent)        │ to prevent stale  ║
║                      │                    │ overwrites        ║
╠═══════════════════════════════════════════════════════════════╣
║  For this incident   │ SUFFICIENT         │ BETTER            ║
║                      │ (menu updates are  │ (also prevents    ║
║                      │ infrequent)        │ stampede on the   ║
║                      │                    │ popular key)      ║
╚═══════════════════════════════════════════════════════════════╝
```

---

## Question 3: L1 Caffeine Cache — Full but Useless

### The Paradox: Full Cache, Terrible Hit Rate

```
At first glance this seems contradictory:
  → Cache is FULL: 5,000/5,000 entries
  → "Full" means maximum data is available
  → So hit rate should be HIGH, not 31%

But FULL doesn't mean EFFECTIVE.
The cache is full of the WRONG data.
```

### What's Happening: Working Set Exceeds Cache Size

```
BEFORE the campaign (normal dinner rush):
  → 50K concurrent users
  → Users browse a moderate variety of restaurants
  → Working set: ~3,000-4,000 unique restaurant/menu
    combinations being actively accessed
  → L1 cache size: 5,000 entries
  → Working set FITS in cache: 4,000 < 5,000
  → Hit rate: 72% (good — most popular items are cached,
    some misses from long-tail restaurants)

  ╔══════════════════════════════════════════════════════════════╗
  ║   L1 Cache (5,000 slots)                                     ║
  ║   ████████████████████░░░░░░░░                               ║
  ║   ◄── 4,000 active ──►◄ 1000 ►                               ║
  ║                         free                                 ║
  ║   Working set FITS. Hit rate HIGH.                           ║
  ╚══════════════════════════════════════════════════════════════╝

AFTER the campaign launches (18:31+):
  → 220K concurrent users (4.4x)
  → ALL browsing Manhattan restaurants specifically
  → Plus normal traffic to non-Manhattan restaurants
  → Working set EXPLODES: 15,000-20,000 unique
    restaurant/menu/item combinations being actively
    accessed across all 40 servers
  → L1 cache size: STILL 5,000 entries per server
  → Working set FAR EXCEEDS cache: 15,000 >> 5,000

  ╔══════════════════════════════════════════════════════════════╗
  ║   L1 Cache (5,000 slots)                                     ║
  ║   ████████████████████████████████████                       ║
  ║   ◄────────── 5,000 FULL ──────────►                         ║
  ║                                                              ║
  ║   Working set: 15,000+ entries needed                        ║
  ║   Only 5,000 can fit.                                        ║
  ║   Cache is FULL but can only hold 1/3                        ║
  ║   of what's being requested.                                 ║
  ╚══════════════════════════════════════════════════════════════╝
```

### The Thrashing Mechanism

```
When the working set exceeds cache capacity,
Caffeine's LRU (or W-TinyLFU) eviction policy
enters a pathological cycle:

  T=0:   Cache contains restaurants A, B, C, D, E
         (5,000 entries, simplified to 5)

  T=1:   Request for restaurant F (not in cache)
         → MISS. Must evict something.
         → Evict A (least recently used)
         → Cache: B, C, D, E, F

  T=2:   Request for restaurant G (not in cache)
         → MISS. Evict B.
         → Cache: C, D, E, F, G

  T=3:   Request for restaurant A (was evicted at T=1!)
         → MISS. Evict C.
         → Cache: D, E, F, G, A

  T=4:   Request for restaurant B (was evicted at T=2!)
         → MISS. Evict D.
         → Cache: E, F, G, A, B

  ... and so on forever.

  Every new request evicts an entry that will be
  needed again soon. The cache is CHURNING through
  entries faster than they can be reused.

  This is CACHE THRASHING:
  → Cache is 100% full → maximum STORAGE
  → Cache is ~31% effective → minimum VALUE
  → 12,000 evictions/sec = 12,000 entries being
    replaced that will be needed again
  → Each eviction triggers an L2 Redis lookup
    (or PostgreSQL fallback)

  THE KEY INSIGHT:
  A cache's effectiveness depends on
  WORKING SET SIZE relative to CACHE SIZE,
  not on how FULL the cache is.

  hit_rate ≈ min(cache_size / working_set_size, 1.0)

  Before: 5,000 / 4,000 = 1.0 → capped at practical ~72%
  After:  5,000 / 15,000 = 0.33 → ~31% (MATCHES observed)
```

### Why 31% Specifically and Not 0%

```
Even during thrashing, SOME hits occur:

  → Very popular restaurants (top 10-20) are accessed
    so frequently that they're always "recently used"
    and survive eviction
  → Sequential requests within a 30-second TTL window
    from the SAME server hit L1 (user browsing the same
    restaurant's menu)
  → The 31% hit rate represents the fraction of requests
    that happen to hit an entry before it's evicted

  In a pure random-access pattern with working set 3x
  cache size, the expected hit rate is roughly:
    cache_size / working_set = 5,000 / 15,000 ≈ 33%

  31% is consistent with slight overhead from
  the eviction algorithm and TTL expiration.
```

### The Cascade Effect

```
L1 at 31% hit rate means 69% of requests fall through to L2.

Before: 69% of requests handled by L1 → 31% reach L2
  → L2 handles 31% of total traffic

Now: 31% handled by L1 → 69% reach L2
  → L2 handles 69% of total traffic
  → Combined with 4.4x overall traffic increase:
    → L2 receives 4.4x × (69%/31%) ≈ 9.8x normal query volume
    → This explains Redis ops/sec going from 45K to 189K (4.2x)
    → The L2 hit rate drop (96% → 71%) further cascades
      to PostgreSQL

L1 thrashing is a FORCE MULTIPLIER that amplifies
every downstream problem.
```

---

## Question 4: Hot Key — Restaurant 5678

### The Problem Quantified

```
Key: restaurant:manhattan:5678
Size: 2.3MB
Access rate: 47,000/minute (~783/sec)
Location: Redis Cluster node 3 (determined by hash slot)

Redis is SINGLE-THREADED.
HGETALL on a 2.3MB key takes ~23ms.
783 ops/sec × 23ms = 18 seconds of processing per second.

This is physically impossible — you can't spend 18 seconds
of work in 1 second on a single thread.

Redis node 3 is SATURATED entirely by this one key.
All OTHER keys that hash to node 3's slots are also
affected — they queue behind the 2.3MB HGETALL operations.
```

### Immediate Mitigation 1: Local Caching with Request Coalescing

```python
# The fastest fix: cache the hot key in the L1 Caffeine
# cache with a DEDICATED slot so it can't be evicted,
# and use request coalescing (singleflight) to prevent
# stampedes.

# Request coalescing: if 100 concurrent requests all
# want the same key, only ONE actually fetches it from
# Redis. The other 99 wait for that one result.

import asyncio
from functools import lru_cache

# In-flight request tracker (per server)
_in_flight = {}

async def get_restaurant_data(restaurant_id):
    cache_key = f"restaurant:manhattan:{restaurant_id}"

    # Check L1 first
    cached = caffeine_cache.get(cache_key)
    if cached:
        return cached

    # Request coalescing: only one request fetches from Redis
    if cache_key in _in_flight:
        # Another request is already fetching — wait for it
        return await _in_flight[cache_key]

    # I'm the first — create a future for others to wait on
    future = asyncio.get_event_loop().create_future()
    _in_flight[cache_key] = future

    try:
        result = await redis.hgetall(cache_key)
        caffeine_cache.put(cache_key, result)  # Cache in L1
        future.set_result(result)
        return result
    except Exception as e:
        future.set_exception(e)
        raise
    finally:
        del _in_flight[cache_key]
```

**Tradeoff:**
```
✓ Reduces Redis load for this key from 783/sec to
   ~1-2/sec per server (one fetch per L1 TTL expiry,
   coalesced across concurrent requests)
   40 servers × 1/30s = ~1.3 fetches/sec total
✓ Fast to implement — application-level change only
✓ No Redis infrastructure changes needed

✗ EACH OF 40 APP SERVERS still fetches the 2.3MB key
   independently when their L1 TTL expires
   → 40 fetches every 30 seconds = 40 × 2.3MB = 92MB
     network transfer every 30 seconds (acceptable)
✗ Doesn't fix the fundamental issue: 2.3MB is too
   large for a Redis key
✗ L1 TTL (30s) means data could be 30 seconds stale
   → For restaurant info, this is fine
   → For prices during a promotion update... problematic
     (connects back to the Q2 race condition)
```

### Immediate Mitigation 2: Read Replica for Hot Key

```bash
# Redis Cluster: node 3 has a replica.
# By default, replicas don't serve reads.
# Enable READONLY on the replica to distribute
# read traffic for node 3's slots.

# On each application server's Redis client, enable
# read-from-replica for GET operations:
```

```python
# In the Redis client configuration:
from redis.cluster import RedisCluster, ClusterNode

rc = RedisCluster(
    startup_nodes=[ClusterNode("redis-1", 6379)],
    read_from_replicas=True  # ← Enable replica reads
)

# Now read commands for node 3's slots can be served
# by node 3's replica, effectively doubling read capacity.
```

**Tradeoff:**
```
✓ Doubles the read throughput for node 3's slots
✓ No data migration or resharding needed
✓ Configuration change only — fast to deploy

✗ Only 2x improvement — if the key is accessed 783/sec
   and each node can handle ~43/sec (1000ms / 23ms),
   2 nodes can handle ~86/sec. We need 783/sec.
   STILL NOT ENOUGH for this specific hot key.
✗ Replica reads may return slightly stale data
   (replication lag, typically <1ms)
✗ Doesn't solve the ROOT CAUSE: the key is too large

HONEST ASSESSMENT: This helps but doesn't solve the
problem. Must be combined with Mitigation 1 (coalescing).
Together: L1 coalescing reduces Redis traffic to ~1.3/sec,
and replica reads handle that easily.
```

### Long-Term Fix: Decompose the Key + Client-Side Hashing

```
ROOT CAUSE: A single 2.3MB key containing ALL restaurant
data (menu, hours, reviews, images metadata, categories...)
all in one hash.

This violates the Redis principle: keys should be SMALL.

DECOMPOSE the monolithic key into multiple smaller keys:
```

```
BEFORE (one 2.3MB key):
  restaurant:manhattan:5678 = {
    name: "Joe's Pizza",
    address: "...",
    hours: {...},
    menu_categories: [{...}, {...}, ...],   ← 800KB
    menu_items: [{...}, {...}, ...],         ← 1.2MB
    reviews_summary: {...},                  ← 200KB
    images: [{...}, {...}],                  ← 100KB
  }

AFTER (multiple small keys):
  rest:5678:info       = {name, address, hours}        ~2KB
  rest:5678:categories = [{...}, {...}]                 ~5KB
  rest:5678:menu:cat1  = [{item1}, {item2}, ...]       ~15KB
  rest:5678:menu:cat2  = [{item1}, {item2}, ...]       ~15KB
  rest:5678:reviews    = {summary data}                 ~3KB
  rest:5678:images     = [{url, thumb}, ...]           ~2KB
```

```
BENEFITS OF DECOMPOSITION:

1. SMALLER KEYS = FASTER OPERATIONS
   GET on a 2KB key: <0.1ms (vs 23ms for 2.3MB HGETALL)
   Node 3 can handle 10,000+ ops/sec instead of 43/sec

2. DIFFERENT KEYS CAN HASH TO DIFFERENT NODES
   rest:5678:info    → might hash to node 1
   rest:5678:menu:*  → might hash to node 4
   rest:5678:reviews → might hash to node 2

   Traffic distributes across the cluster naturally.
   No single node becomes a bottleneck.

3. CLIENT ONLY FETCHES WHAT IT NEEDS
   User viewing the menu? Fetch rest:5678:menu:cat1
   User viewing hours? Fetch rest:5678:info
   No need to transfer 2.3MB when you only need 15KB.

4. CACHE INVALIDATION IS GRANULAR
   Price update? Invalidate only rest:5678:menu:*
   Hours change? Invalidate only rest:5678:info
   No need to invalidate (and refetch) 2.3MB for
   a 100-byte price change.

TRADEOFF:
  → More Redis round trips (multiple GETs vs one HGETALL)
  → Use MGET or pipeline to batch if needed
  → Slightly more complex application code
  → Need to manage multiple cache keys per restaurant
  → Worth it — the performance gain is 100x+
```

---

## Question 5: Prioritized Mitigation — Financial/Legal Issue Changes Everything

The stale pricing bug is now the **#1 priority** above all infrastructure issues. Users are being **overcharged** during a promotion. This is:
- A **financial liability** (every affected order must be refunded)
- A **legal risk** (false advertising, consumer protection laws)
- A **trust/reputation issue** (social media complaints during a major campaign)
- Growing **every second** it's not fixed (more orders at wrong prices)

### Revised Priority Ranking

```
╔════════════════════════════════════════════════════════════════════╗
║  RANK │ ACTION                   │ JUSTIFICATION                   ║
╠════════════════════════════════════════════════════════════════════╣
║   1   │ Fix stale prices         │ FINANCIAL/LEGAL. Every second   ║
║       │ (purge cache + fix code) │ = more orders at wrong price    ║
║       │                          │ = more refunds = more legal     ║
║       │                          │ exposure. STOP THE BLEEDING.    ║
╠════════════════════════════════════════════════════════════════════╣
║   2   │ Hot key mitigation       │ ENABLES fix #1 to work.         ║
║       │ (request coalescing)     │ Even after purging stale cache, ║
║       │                          │ 47K req/min will re-flood node  ║
║       │                          │ 3. Must reduce key access rate  ║
║       │                          │ BEFORE purging.                 ║
╠════════════════════════════════════════════════════════════════════╣
║   3   │ PostgreSQL protection    │ DB is at 180/200 connections.   ║
║       │ (connection pool +       │ If it hits 200, ALL services    ║
║       │  query optimization)     │ fail, not just menus.           ║
║       │                          │ Orders, payments, everything.   ║
╠════════════════════════════════════════════════════════════════════╣
║   4   │ L1 cache expansion       │ Reduces cascade amplification.  ║
║       │                          │ Every L1 hit is one less L2     ║
║       │                          │ request, one less potential DB  ║
║       │                          │ query.                          ║
╠════════════════════════════════════════════════════════════════════╣
║   5   │ Notify finance/legal +   │ Parallel with technical fixes.  ║
║       │ identify affected orders │ Must start refund process and   ║
║       │                          │ quantify financial impact.      ║
╚════════════════════════════════════════════════════════════════════╝
```

### Step 1: Fix Stale Prices (Minute 0-5)

```bash
# CRITICAL SEQUENCE: We must fix the stale price issue
# BUT we must do it carefully because of the hot key problem.
# If we just purge the cache, 47K req/min will stampede
# PostgreSQL and potentially re-cache stale data if we
# haven't fixed the code.

# ACTION 1A: Deploy the invalidation fix FIRST
# Change from delete-before-commit to write-through-after-commit
# (prevents re-poisoning when we purge the cache)
```

```python
# Deploy this code change:
async def update_menu_prices(restaurant_id, new_prices):
    async with db.transaction():
        await db.execute(
            "UPDATE menu_items SET price = $1 "
            "WHERE restaurant_id = $2",
            new_prices, restaurant_id
        )
    # Transaction COMMITTED

    # Write-through: overwrite cache with correct data
    new_menu = await db.fetch(
        "SELECT * FROM menu_items WHERE restaurant_id = $1",
        restaurant_id
    )
    await redis.set(
        f"menu:restaurant:{restaurant_id}",
        serialize(new_menu), ex=300
    )
```

```bash
# ACTION 1B: Now purge the stale cached prices
# This is safe because the code fix prevents re-poisoning

# Delete the specific stale key:
redis-cli -c DEL "menu:restaurant:5678"

# Also purge ALL Manhattan restaurant menu keys
# (other restaurants may have the same race condition):
redis-cli --scan --pattern "menu:restaurant:*" | \
  head -1000 | xargs redis-cli -c DEL

# ACTION 1C: Ask the restaurant owner to re-submit the
# price update (or trigger it programmatically):
# This will go through the NEW code path:
# commit first → write-through to cache

# VERIFY:
curl -s https://api.example.com/restaurants/5678/menu | \
  jq '.items[0].price'
# Should show 50%-off price, not full price

# Also verify Redis has correct data:
redis-cli -c GET "menu:restaurant:5678" | jq '.items[0].price'
```

**VERIFY before proceeding:**
```
→ Menu prices for restaurant 5678 show 50%-off prices
→ Redis contains correct prices
→ New orders are being placed at correct prices
→ Confirm by checking 5 recent orders in the order service logs
```

### Step 2: Hot Key Mitigation (Minute 3-7, overlapping with Step 1)

```python
# Deploy request coalescing for restaurant data fetches.
# This MUST be deployed before or simultaneously with the
# cache purge in Step 1, otherwise the purge triggers
# a stampede on node 3.

# Deploy the singleflight/coalescing pattern from Q4.
# Plus: enable read-from-replicas in Redis client config:

rc = RedisCluster(
    startup_nodes=[ClusterNode("redis-1", 6379)],
    read_from_replicas=True
)
```

```bash
kubectl set env deployment/api-service \
  REDIS_READ_FROM_REPLICAS=true \
  ENABLE_REQUEST_COALESCING=true

# VERIFY:
# → Redis node 3 CPU should drop from 98% toward 30-40%
# → Redis node 3 response time: 23ms → <1ms for most ops
# → Redis ops/sec from application → should drop significantly
```

### Step 3: Protect PostgreSQL (Minute 7-10)

```bash
# Connection pool is at 180/200. Must prevent exhaustion.

# ACTION 3A: Increase pool size temporarily
kubectl set env deployment/api-service \
  DB_POOL_SIZE=300 DB_POOL_MAX_OVERFLOW=50

# ALSO: increase PostgreSQL max_connections if needed
psql -c "ALTER SYSTEM SET max_connections = 400;"
psql -c "SELECT pg_reload_conf();"
# Note: max_connections change requires restart on some versions.
# Check if the current value allows headroom first:
psql -c "SHOW max_connections;"
```

```bash
# ACTION 3B: The query SELECT * FROM menu_items
# WHERE restaurant_id = $1 is fetching ALL columns.
# If there's a covering index or if we can SELECT
# only needed columns, do it:

# Check for missing index:
psql -c "EXPLAIN ANALYZE SELECT * FROM menu_items
         WHERE restaurant_id = 5678;"
# If sequential scan → add index:
psql -c "CREATE INDEX CONCURRENTLY idx_menu_items_restaurant
         ON menu_items(restaurant_id);"

# VERIFY:
# → Pool usage should stabilize below 70%
# → Query latency should drop as L1/L2 caches warm up
#   (because Steps 1-2 fixed cache effectiveness)
```

### Step 4: Expand L1 Cache (Minute 10-12)

```bash
# Working set is ~15,000 entries. L1 has 5,000 slots.
# Increase to 20,000 to fit the new working set.

kubectl set env deployment/api-service \
  CAFFEINE_MAX_SIZE=20000

# Rolling restart to pick up the new config:
kubectl rollout restart deployment/api-service

# VERIFY:
# → L1 hit rate should climb from 31% toward 70%+
#   (as cache warms up over 1-2 minutes)
# → L2 Redis ops/sec should decrease proportionally
# → PostgreSQL queries/sec should decrease proportionally
# → Allow 2-3 minutes for cache warming

# TRADEOFF:
# 20,000 entries × average entry size → more memory per pod
# If entries average 10KB: 20,000 × 10KB = 200MB per pod
# 40 pods × 200MB = 8GB total cluster memory
# Acceptable for preventing this class of incident.
```

### Step 5: Financial/Legal Notification and Remediation (Parallel from Minute 0)

```bash
# This runs IN PARALLEL with technical fixes.
# Don't wait for technical resolution to start this.

# ACTION 5A: Immediately notify finance + legal
# "Orders for restaurant 5678 (and potentially other
# Manhattan restaurants) placed between 18:31 and [fix time]
# were charged FULL PRICE instead of 50% off.
# Technical fix is being deployed.
# We need to identify and refund all affected orders."

# ACTION 5B: Identify affected orders
psql -c "
  SELECT o.id, o.user_id, o.total_amount, o.created_at,
         o.restaurant_id
  FROM orders o
  WHERE o.restaurant_id = 5678
  AND o.created_at BETWEEN '2024-01-01 18:31:00'
                        AND '2024-01-01 18:45:00'
  AND o.total_amount > (
    SELECT SUM(mi.price * 0.5 * oi.quantity)
    FROM order_items oi
    JOIN menu_items mi ON oi.menu_item_id = mi.id
    WHERE oi.order_id = o.id
  )
  ORDER BY o.created_at;
"
# This finds orders where the charged amount exceeds
# what the 50%-off price would have been.

# ACTION 5C: Calculate refund amounts
# Each affected order should be refunded 50% of total
# (they paid full price, should have paid half)

# ACTION 5D: Proactive customer notification
# Don't wait for complaints — email EVERY affected customer:
# "We identified a brief technical issue during our 50% off
# campaign. You were charged the full price. A refund of
# $XX.XX has been issued to your payment method.
# We apologize for the inconvenience."

# Proactive notification is ALWAYS better than waiting
# for complaints. It demonstrates accountability and
# reduces legal exposure.
```

### Complete Mitigation Timeline

```
╔══════════════════════════════════════════════════════════════╗
║  MINUTE   │ ACTION                                           ║
╠══════════════════════════════════════════════════════════════╣
║  0        │ START: Notify finance/legal (parallel track)     ║
║           │ Deploy cache invalidation code fix               ║
║           │ (write-through after commit)                     ║
╠══════════════════════════════════════════════════════════════╣
║  0-3      │ Deploy request coalescing + replica reads        ║
║           │ (BEFORE cache purge to prevent stampede)         ║
╠══════════════════════════════════════════════════════════════╣
║  3-5      │ Purge stale price keys from Redis                ║
║           │ Re-trigger price update through new code path    ║
║           │ VERIFY: correct prices showing                   ║
║           │ VERIFY: new orders at correct prices             ║
╠══════════════════════════════════════════════════════════════╣
║  5-7      │ VERIFY: Redis node 3 CPU declining               ║
║           │ VERIFY: node 3 response time normalizing         ║
╠══════════════════════════════════════════════════════════════╣
║  7-10     │ Increase DB pool + add index if missing          ║
║           │ VERIFY: pool usage < 70%, query latency down     ║
╠══════════════════════════════════════════════════════════════╣
║  10-12    │ Expand L1 cache to 20,000 entries                ║
║           │ Rolling restart of app servers                   ║
║           │ VERIFY: L1 hit rate climbing toward 70%+         ║
╠══════════════════════════════════════════════════════════════╣
║  12-15    │ Run affected order query                         ║
║           │ Calculate refund amounts                         ║
║           │ Initiate refund process                          ║
╠══════════════════════════════════════════════════════════════╣
║  15+      │ Monitor all systems for stability                ║
║           │ Send proactive customer notifications            ║
║           │ Write post-incident review                       ║
║           │ Plan long-term: decompose hot key,               ║
║           │   implement proper cache invalidation,           ║
║           │   load test for campaign traffic patterns        ║
╚══════════════════════════════════════════════════════════════╝
```
