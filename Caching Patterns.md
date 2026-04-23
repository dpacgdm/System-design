# Week 2, Topic 3: Caching Patterns

---

## Step 1: Learning Objectives

```
┌──────────────────────────────────────────────────────────────┐
│  AFTER THIS TOPIC, YOU WILL BE ABLE TO:                      │
│                                                              │
│  1. Name and explain every major caching strategy            │
│     (cache-aside, read-through, write-through,               │
│     write-behind, write-around) with precise mechanics       │
│                                                              │
│  2. Choose the correct caching strategy for a given          │
│     workload and explain the tradeoff you're making          │
│                                                              │
│  3. Explain cache invalidation — why it's "the hardest       │
│     problem in computer science" — and the specific          │
│     failure modes of each invalidation approach              │
│                                                              │
│  4. Diagnose caching incidents from metrics alone            │
│     (thundering herd, cache stampede, hot key,               │
│     cache penetration, cache avalanche)                      │
│                                                              │
│  5. Design a multi-layer caching architecture for a          │
│     system and explain what each layer protects              │
│                                                              │
│  6. Implement cache warming, TTL strategies, and             │
│     consistent hashing for cache distribution                │
│     (sets up Week 3's consistent hashing deep dive)          │
└──────────────────────────────────────────────────────────────┘
```

---

## Step 2: Core Teaching

### Why Caching Exists

```
Every system design has one fundamental bottleneck:
THE DATABASE.

  Without cache:
  ┌────────┐         ┌─────────────┐
  │ Client │────────→│  Database   │
  │        │←────────│  (disk I/O) │
  └────────┘         └─────────────┘
  
  Every request hits the database.
  Database does disk I/O: ~1-10ms per query.
  At 10,000 requests/sec: database drowns.

  With cache:
  ┌────────┐    ┌────────┐    ┌─────────────┐
  │ Client │───→│ Cache  │    │  Database   │
  │        │←───│ (RAM)  │───→│  (disk I/O) │
  └────────┘    └────────┘    └─────────────┘
  
  95% of requests served from memory: ~0.1ms
  5% of requests go to database: ~5ms
  Average latency: 0.95(0.1) + 0.05(5) = 0.345ms
  
  Without cache: 5ms average
  With cache (95% hit): 0.345ms average — 14x faster

THE CORE TRADEOFF:
  Speed vs Freshness.
  
  Cached data is ALWAYS potentially stale.
  The question is: HOW stale is acceptable?
  
  Stock price: stale by 100ms = unacceptable
  User profile picture: stale by 5 minutes = fine
  Product description: stale by 1 hour = fine
  Historical report: stale by 1 day = fine
  
  Your caching strategy depends on WHERE your data 
  falls on this spectrum.
```

---

### Part A: Caching Strategies — The Full Taxonomy

#### Strategy 1: Cache-Aside (Lazy Loading)

```
THE MOST COMMON STRATEGY. If you only learn one, 
learn this one.

WHO MANAGES THE CACHE: The APPLICATION code.
The cache and database don't know about each other.

READ PATH:
  ┌──────────┐  1. GET key  ┌───────┐
  │   App    │─────────────→│ Cache │
  │          │←─────────────│       │
  │          │  2. HIT/MISS └───────┘
  │          │
  │  if MISS:│  3. SELECT   ┌────────┐
  │          │─────────────→│   DB   │
  │          │←─────────────│        │
  │          │  4. Result   └────────┘
  │          │
  │          │  5. SET key   ┌───────┐
  │          │─────────────→│ Cache  │
  └──────────┘               └───────┘

PSEUDOCODE:
  def get_user(user_id):
      # Step 1: Check cache
      user = cache.get(f"user:{user_id}")
      
      # Step 2: Cache hit — return immediately
      if user is not None:
          return user
      
      # Step 3: Cache miss — query database
      user = db.query("SELECT * FROM users WHERE id = %s", user_id)
      
      # Step 4: Populate cache for next time
      cache.set(f"user:{user_id}", user, ttl=300)  # 5 min TTL
      
      # Step 5: Return
      return user

WRITE PATH:
  Two options — and this is where it gets interesting:

  OPTION A: Invalidate on write (most common)
    def update_user(user_id, new_data):
        db.execute("UPDATE users SET ... WHERE id = %s", user_id)
        cache.delete(f"user:{user_id}")  # Invalidate
        # Next read will miss → fetch fresh from DB → re-cache

  OPTION B: Update on write
    def update_user(user_id, new_data):
        db.execute("UPDATE users SET ... WHERE id = %s", user_id)
        cache.set(f"user:{user_id}", new_data, ttl=300)  # Update

ADVANTAGES:
  ✅ Simple to implement and reason about
  ✅ Application has full control
  ✅ Cache only contains data that's actually requested
     (no wasted memory on unpopular items)
  ✅ Cache failure is survivable (reads fall through to DB)
  ✅ Works with ANY cache (Redis, Memcached, local memory)

DISADVANTAGES:
  ❌ First request for any key is always a cache miss (cold start)
  ❌ Cache miss = 3 operations (cache check + DB read + cache write)
     instead of 1 (just DB read) — SLOWER than no cache on a miss
  ❌ Stale data possible between DB write and cache invalidation
  ❌ Application code is polluted with caching logic everywhere

WHEN TO USE:
  → General-purpose web applications
  → Read-heavy workloads
  → Data that's accessed in unpredictable patterns
  → When you want cache failures to be non-fatal
  → This is the DEFAULT choice. Use this unless you 
    have a specific reason for another strategy.
```

#### Strategy 2: Read-Through

```
WHO MANAGES THE CACHE: The CACHE LAYER itself.
The application talks ONLY to the cache.
The cache is responsible for fetching from the DB on miss.

READ PATH:
  ┌──────────┐  1. GET key  ┌─────────────────────┐
  │   App    │─────────────→│ Cache (with loader) │
  │          │←─────────────│                     │
  │          │  4. Result   │  2. MISS? →  ┌────┐ │
  └──────────┘              │  3. Fetch ←  │ DB │ │
                            │              └────┘ │
                            │  (cache stores it)  │
                            └─────────────────────┘

THE KEY DIFFERENCE FROM CACHE-ASIDE:
  Cache-aside: Application manages the cache
  Read-through: Cache manages itself

  The application code is cleaner:
  
  # Cache-aside (application manages):
  def get_user(user_id):
      user = cache.get(f"user:{user_id}")
      if user is None:
          user = db.query(...)
          cache.set(f"user:{user_id}", user, ttl=300)
      return user
  
  # Read-through (cache manages):
  def get_user(user_id):
      return cache.get(f"user:{user_id}")
      # Cache internally handles miss → DB fetch → store

IMPLEMENTATIONS:
  → Amazon DAX (DynamoDB Accelerator) — read-through 
    cache for DynamoDB
  → NCache, Hazelcast, Apache Ignite
  → Custom cache proxy layer
  → Hibernate second-level cache
  → NOT native Redis (Redis doesn't auto-fetch from DB)

ADVANTAGES:
  ✅ Application code is clean (no cache management logic)
  ✅ Cache logic centralized (change strategy in one place)
  ✅ Consistent behavior across all callers

DISADVANTAGES:
  ❌ First read is still a miss (same cold-start problem)
  ❌ Cache layer becomes a dependency (if it's down, 
     application needs fallback logic)
  ❌ Less flexibility (cache layer decides TTL, eviction)
  ❌ Harder to debug (caching is invisible to app code)

WHEN TO USE:
  → When you have a managed cache layer (DAX, Hazelcast)
  → When multiple services access the same cache
  → When you want to centralize caching logic
  → When the cache is a critical infrastructure component 
    (not just an optimization)
```

#### Strategy 3: Write-Through

```
WHO MANAGES THE CACHE: The CACHE LAYER.
Every WRITE goes through the cache to the database.
The cache is ALWAYS up-to-date.

WRITE PATH:
  ┌──────────┐  1. WRITE    ┌──────────────────────┐
  │   App    │─────────────→│ Cache                │
  │          │              │                      │
  │          │              │  2. Store in cache   │
  │          │              │  3. Write to DB      │
  │          │              │       │    ┌────┐    │
  │          │              │       └───→│ DB │    │
  │          │←─────────────│            └────┘    │
  │          │  4. ACK      │                      │
  └──────────┘  (after both)└──────────────────────┘

  Application writes TO the cache.
  Cache writes to BOTH itself AND the database.
  Application gets ACK only after BOTH succeed.

READ PATH:
  Always from cache (data is always there because 
  every write goes through cache first).

THE CRITICAL PROPERTY:
  Cache is ALWAYS consistent with database.
  No stale data. Ever.
  
  But at what cost?

ADVANTAGES:
  ✅ Cache is always up-to-date (no stale reads)
  ✅ Reads are always cache hits (after initial population)
  ✅ Data loss risk is low (data in both cache and DB)
  ✅ Simpler consistency model for the application

DISADVANTAGES:
  ❌ WRITE LATENCY DOUBLES: every write must go to 
     cache AND database before returning
     → write_latency = cache_write + db_write
     → If DB write takes 5ms: total = 5ms + 1ms = 6ms
     → Versus direct DB write: 5ms
     → Seems small, but at high write rates it compounds

  ❌ Cache fills with data that may never be READ
     → If you write 1M user profiles but only 10K 
       are active, 990K are cached but never accessed
     → Wasted memory

  ❌ Cache becomes a critical path for writes
     → Cache down = writes fail (unless you add fallback)

WHEN TO USE:
  → When read-after-write consistency is critical
     (e.g., the "I updated my profile but see old data" 
     problem from the SQL topic — this eliminates it)
  → When writes are relatively infrequent
  → When combined with read-through (the cache handles 
     both reads and writes transparently)
```

#### Strategy 4: Write-Behind (Write-Back)

```
WHO MANAGES THE CACHE: The CACHE LAYER.
Writes go to cache ONLY. The cache asynchronously 
flushes to the database in the background.

WRITE PATH:
  ┌──────────┐  1. WRITE    ┌──────────────────────┐
  │   App    │─────────────→│ Cache                │
  │          │←─────────────│                      │
  │          │  2. ACK      │  (data in cache only)│
  └──────────┘  (immediate!)│                      │
                            │  3. Later (async):   │
                            │     batch flush      │
                            │       │    ┌────┐    │
                            │       └───→│ DB │    │
                            │            └────┘    │
                            └──────────────────────┘

  Application writes TO the cache.
  Cache ACKs IMMEDIATELY (before DB write).
  Cache batches and flushes writes to DB asynchronously.

THIS IS THE OPPOSITE TRADEOFF FROM WRITE-THROUGH:

  Write-through: Slow writes, zero data loss risk
  Write-behind:  Fast writes, DATA LOSS RISK

ADVANTAGES:
  ✅ Writes are EXTREMELY fast (just memory write + ACK)
  ✅ Database is shielded from write spikes
     (cache absorbs the burst, flushes gradually)
  ✅ Batch writes to DB (can coalesce multiple updates 
     to the same key into one DB write)
  ✅ Database can go down temporarily without blocking 
     writes (cache absorbs until DB recovers)

DISADVANTAGES:
  ❌ DATA LOSS RISK: If the cache crashes before flushing 
     to DB, those writes are LOST. Gone. Unrecoverable.
     This is the critical tradeoff.
  ❌ Complex failure handling (what if DB rejects a write 
     that the cache already ACKed to the application?)
  ❌ Consistency window: data in cache but not yet in DB 
     → other readers of the DB see stale data
  ❌ Hard to implement correctly (batching, retry, 
     ordering guarantees, deduplication)

WHEN TO USE:
  → Write-heavy workloads where latency matters more 
    than durability (click tracking, page views, likes)
  → When you can tolerate small data loss windows
  → When the database is a bottleneck for writes
  → Analytics pipelines where eventual consistency is fine
  → NEVER for financial data, orders, or anything where 
    a lost write = real-world consequence
```

#### Strategy 5: Write-Around

```
WRITES go directly to the database, BYPASSING the cache.
READS use cache-aside (lazy loading).

WRITE PATH:
  ┌──────────┐  1. WRITE    ┌────────┐
  │   App    │─────────────→│   DB   │
  │          │←─────────────│        │
  │          │  2. ACK      └────────┘
  └──────────┘
  (Cache is NOT updated or invalidated)

READ PATH:
  Same as cache-aside (check cache → miss → read DB → populate cache)

THE IDEA:
  If most writes are never immediately re-read, 
  why bother updating the cache?
  
  Let the cache fill naturally through reads.
  Writes go straight to DB.

ADVANTAGES:
  ✅ Writes are fast (only one destination: DB)
  ✅ Cache isn't polluted with recently-written data 
     that might never be read
  ✅ Simple — no cache invalidation logic on write path

DISADVANTAGES:
  ❌ Read-after-write ALWAYS misses the cache
     (you just wrote to DB, cache doesn't know about it)
  ❌ Higher read latency for recently-written data
  ❌ Cache can be stale indefinitely (no invalidation 
     triggered by writes — relies entirely on TTL expiry)

WHEN TO USE:
  → Data that's written frequently but read rarely
    (log entries, audit trails, analytics events)
  → When write performance is more important than 
    read-after-write consistency
  → When combined with appropriate TTLs
```

#### Strategy Comparison Matrix

```
┌──────────────────┬───────────┬───────────┬────────────┬──────────┐
│ STRATEGY         │ READ      │ WRITE     │ CONSISTENCY│ BEST FOR │
│                  │ LATENCY   │ LATENCY   │            │          │
├──────────────────┼───────────┼───────────┼────────────┼──────────┤
│ Cache-Aside      │ Miss=slow │ Normal    │ Eventual   │ General  │
│                  │ Hit=fast  │+invalidate│ (TTL-based)│ purpose  │
├──────────────────┼───────────┼───────────┼────────────┼──────────┤
│ Read-Through     │ Miss=slow │ Normal    │ Eventual   │ Managed  │
│                  │ Hit=fast  │           │ (TTL-based)│ caches   │
├──────────────────┼───────────┼───────────┼────────────┼──────────┤
│ Write-Through    │ Always    │ SLOW      │ STRONG     │ Read-    │
│                  │ fast      │ (2 writes)│ (always    │ after-   │
│                  │           │           │  fresh)    │ write    │
├──────────────────┼───────────┼───────────┼────────────┼──────────┤
│ Write-Behind     │ Always    │ VERY FAST │ Eventual   │ Write-   │
│                  │ fast      │ (async)   │ (DATA LOSS │ heavy    │
│                  │           │           │  RISK)     │          │
├──────────────────┼───────────┼───────────┼────────────┼──────────┤
│ Write-Around     │ Miss=slow │ Fast      │ Eventual   │ Write-   │
│                  │ Hit=fast  │ (DB only) │ (stale     │ rarely-  │
│                  │           │           │  until TTL)│ read     │
└──────────────────┴───────────┴───────────┴────────────┴──────────┘

MOST REAL SYSTEMS:
  Cache-aside for 90% of use cases.
  Write-through for the few cases where consistency matters.
  Write-behind for analytics/metrics.
  
  Often COMBINED:
  → Cache-aside for reads + write-around for writes
    = the simplest production pattern
  → Read-through + write-through
    = the fully managed pattern (DAX, Hazelcast)
```

---

### Part B: Cache Invalidation — The Hard Problem

```
"There are only two hard things in Computer Science: 
 cache invalidation and naming things." — Phil Karlton

Why is this hard? Because the cache and database are 
TWO SEPARATE SYSTEMS. Keeping them in sync requires 
solving a distributed consistency problem.
```

#### The Stale Data Problem

```
SCENARIO: User updates their profile name.

  TIME    DATABASE              CACHE
  ─────   ────────              ─────
  T=0     name: "Alice"         name: "Alice"     (consistent)
  T=1     UPDATE name="Alicia"  name: "Alice"     (STALE!)
  T=2     name: "Alicia"        name: "Alice"     (still stale)
  ...
  T=300   name: "Alicia"        (TTL expires, key deleted)
  T=301   name: "Alicia"        (miss → re-fetch → "Alicia")

  For 300 seconds (5 minutes), every read from cache 
  returned "Alice" even though the database says "Alicia."
  
  Is this acceptable? DEPENDS ON THE USE CASE.
  For a display name: probably yes.
  For an account balance: absolutely not.
```

#### Invalidation Strategies

```
STRATEGY 1: TTL-Based Expiration (Passive)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Set a TTL when caching. Key expires automatically.
  Next read after expiry → cache miss → fresh data from DB.

  cache.set("user:123", data, ttl=300)  # 5 minutes

  STALE WINDOW: 0 to TTL seconds (worst case = full TTL)

  ┌──────────────────────────────────────────────────┐
  │  TTL TOO SHORT:                                  │
  │  → More cache misses → more DB load              │
  │  → Defeats the purpose of caching                │
  │  → High DB query rate                            │
  │                                                  │
  │  TTL TOO LONG:                                   │
  │  → More stale data → bad user experience         │
  │  → Users see old information                     │
  │  → Data inconsistencies in the UI                │
  │                                                  │
  │  CHOOSING TTL:                                   │
  │  → How often does this data change?              │
  │  → How bad is it if users see stale data?        │
  │  → How much DB load can we handle on misses?     │
  │                                                  │
  │  User profile: TTL=300s (changes rarely)         │
  │  Product price: TTL=60s (changes occasionally)   │
  │  Stock count: TTL=10s (changes frequently)       │
  │  Live score: TTL=1s (changes constantly)         │
  └──────────────────────────────────────────────────┘

  Advantages:
  ✅ Simplest possible approach
  ✅ Self-healing (stale data ALWAYS eventually corrected)
  ✅ No coordination needed between writers and cache
  
  Disadvantages:
  ❌ Guaranteed stale window
  ❌ No way to force immediate consistency
  ❌ TTL tuning is guesswork


STRATEGY 2: Active Invalidation (Delete on Write)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  When data changes, explicitly delete the cache key.
  Next read will miss and re-fetch fresh data.

  def update_user(user_id, new_data):
      db.execute("UPDATE users SET name = %s WHERE id = %s", 
                 new_data, user_id)
      cache.delete(f"user:{user_id}")

  STALE WINDOW: time between DB write and cache delete
  (typically milliseconds)

  BUT THERE'S A RACE CONDITION:

  Thread A (writer)           Thread B (reader)
  ──────────────              ──────────────
  UPDATE DB: name="Alicia"
                              GET cache → MISS
                              SELECT DB → "Alicia"
  DELETE cache (key already    
    gone from miss above)     
                              SET cache: "Alicia"
                              
  This sequence is FINE — cache has "Alicia" ✓

  BUT what about THIS sequence:

  Thread A (writer)           Thread B (reader)
  ──────────────              ──────────────
                              GET cache → MISS
                              SELECT DB → "Alice" (old!)
  UPDATE DB: name="Alicia"
  DELETE cache (key doesn't   
    exist yet — delete is     
    a no-op!)                 
                              SET cache: "Alice" ← STALE!
  
  Cache now contains "Alice" even though DB has "Alicia."
  The invalidation came BETWEEN the read and the re-cache.
  
  This is the CLASSIC RACE CONDITION of cache invalidation.
  TTL is the safety net — eventually the stale entry expires.

  ┌──────────────────────────────────────────────────┐
  │  HOW LIKELY IS THIS RACE?                        │
  │                                                  │
  │  Thread B's read and set happen in ~5ms.         │
  │  Thread A's write must land in that exact 5ms    │
  │  window AFTER B reads but BEFORE B writes cache. │
  │                                                  │
  │  Low probability. But at 100K requests/sec,      │
  │  low probability events happen regularly.        │
  │                                                  │
  │  Mitigation: ALWAYS combine active invalidation  │
  │  with a TTL as a safety net.                     │
  │                                                  │
  │  cache.set("user:123", data, ttl=300)            │
  │  Even if the race occurs, stale data expires     │
  │  in at most 300 seconds.                         │
  └──────────────────────────────────────────────────┘


STRATEGY 3: Active Update (Write-Through on Write)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  When data changes, update the cache with the new value.

  def update_user(user_id, new_data):
      db.execute("UPDATE users SET name = %s WHERE id = %s", 
                 new_data, user_id)
      cache.set(f"user:{user_id}", new_data, ttl=300)

  This ALSO has a race condition:

  Thread A (writer 1)         Thread B (writer 2)
  ──────────────              ──────────────
  UPDATE DB: name="Alicia"
                              UPDATE DB: name="Bob"
                              SET cache: "Bob"
  SET cache: "Alicia"         
  
  DB has "Bob" (B's write was later).
  Cache has "Alicia" (A's cache update was later).
  INCONSISTENT.

  This is the LOST UPDATE problem applied to caching.
  
  The fix: DELETE is safer than UPDATE for invalidation.
  DELETE + re-fetch always gets the latest DB value.
  UPDATE risks write ordering issues.

  RULE OF THUMB:
    Prefer DELETE over UPDATE for cache invalidation.
    Let the next read re-populate from the source of truth.


STRATEGY 4: Event-Driven Invalidation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Database writes emit events (via CDC — Change Data Capture).
  A consumer processes events and invalidates the cache.

  ┌────────┐   write   ┌────────┐   CDC event   ┌─────────┐
  │  App   │──────────→│   DB   │──────────────→│  Kafka  │
  └────────┘           └────────┘               └────┬────┘
                                                     │
                                              ┌──────┴──────┐
                                              │  Consumer   │
                                              │  DELETE key │
                                              │  from cache │
                                              └──────┬──────┘
                                                     │
                                                ┌────▼────┐
                                                │  Cache  │
                                                └─────────┘

  The application doesn't need to know about the cache.
  The database change AUTOMATICALLY triggers invalidation.

  IMPLEMENTATIONS:
  → PostgreSQL: Logical replication / LISTEN/NOTIFY
  → MySQL: Binlog → Debezium → Kafka → Consumer
  → DynamoDB: DynamoDB Streams → Lambda → Redis
  → MongoDB: Change Streams → Consumer → Redis

  ADVANTAGES:
  ✅ Application code is clean (no cache logic in writes)
  ✅ Works across multiple services (Service A writes to DB,
     Service B's cache is automatically invalidated)
  ✅ Reliable (event queue ensures delivery)
  ✅ Decoupled (writer doesn't need to know about cache)

  DISADVANTAGES:
  ❌ LATENCY: Event pipeline adds delay (50ms-2s typically)
     → Stale window = pipeline latency
  ❌ Complexity: Kafka/CDC infrastructure to maintain
  ❌ Ordering: Events may arrive out of order
  ❌ Another system that can fail (Kafka down = no invalidation)

  WHEN TO USE:
  → Microservices where the writer and reader are different services
  → When you need cross-service cache coherence
  → When you already have a CDC pipeline (Debezium)
```

#### The Delete vs Update Decision

```
┌──────────────────────────────────────────────────────────────┐
│  RULE: PREFER DELETE OVER UPDATE FOR INVALIDATION            │
│                                                              │
│  DELETE (invalidate):                                        │
│  → Next read: cache miss → re-fetch from DB → fresh data     │
│  → ALWAYS gets latest value (DB is source of truth)          │
│  → Cost: one extra DB read on next access                    │
│  → Race condition: mild (stale data from read-before-delete) │
│  → Self-correcting with TTL                                  │
│                                                              │
│  UPDATE (overwrite):                                         │
│  → Immediately puts new value in cache                       │
│  → No extra DB read needed                                   │
│  → Race condition: SEVERE (write ordering)                   │
│  → Two concurrent updates can leave cache permanently wrong  │
│  → Only self-corrects when TTL expires                       │
│                                                              │
│  USE UPDATE ONLY WHEN:                                       │
│  → Single writer (no concurrent update risk)                 │
│  → You NEED the write to be immediately visible in cache     │
│  → You can guarantee write ordering (version numbers)        │
│                                                              │
│  USE DELETE FOR EVERYTHING ELSE (which is most cases).       │
└──────────────────────────────────────────────────────────────┘
```

---

### Part C: Cache Failure Patterns

These are the patterns that cause production incidents. Every one of these has taken down major systems.

#### Pattern 1: Cache Stampede (Thundering Herd)

```
WHAT HAPPENS:
  A popular cache key expires.
  Thousands of concurrent requests all experience 
  a cache miss simultaneously.
  All of them query the database at the same time.
  Database is overwhelmed.

  ┌──────────────────────────────────────────────┐
  │  TIME                                        │
  │  ─────                                       │
  │  T=0    Cache has "product:popular" (TTL=60) │
  │         Hit rate: 99.9%                      │
  │         DB queries/sec: 10                   │
  │                                              │
  │  T=60   TTL expires. Key deleted.            │
  │                                              │
  │  T=60.001  5,000 requests arrive             │
  │            ALL miss the cache                │
  │            ALL query the database:           │
  │            "SELECT * FROM products           │
  │             WHERE id = 'popular'"            │
  │            → 5,000 identical queries         │
  │            → DB CPU spikes to 100%           │
  │            → p99 latency: 200ms → 8,000ms    │
  │                                              │
  │  T=60.5  First response comes back.          │
  │          First request re-caches the key.    │
  │          Remaining 4,999 requests also get   │
  │          responses and try to re-cache       │
  │          (4,999 redundant cache writes).     │
  │                                              │
  │  T=61   Everything is fine again.            │
  │         Until the NEXT TTL expiry...         │
  └──────────────────────────────────────────────┘

FIX 1: DISTRIBUTED LOCK (Mutex)

  On cache miss:
  1. Try to acquire a lock: SET lock:product:popular NX EX 5
     (SET if Not eXists, Expires in 5 seconds)
  2. If lock acquired: YOU are the ONE request that queries DB
     and re-populates the cache. Everyone else waits.
  3. If lock NOT acquired: someone else is fetching. 
     Wait 50ms, then retry the cache GET.

  def get_product_with_lock(product_id):
      # Check cache
      data = cache.get(f"product:{product_id}")
      if data is not None:
          return data
      
      # Try to acquire lock
      lock_key = f"lock:product:{product_id}"
      got_lock = cache.set(lock_key, "1", nx=True, ex=5)
      
      if got_lock:
          # I'm the winner — fetch from DB
          data = db.query("SELECT * FROM products WHERE id = %s", 
                          product_id)
          cache.set(f"product:{product_id}", data, ttl=60)
          cache.delete(lock_key)
          return data
      else:
          # Someone else is fetching — wait and retry
          time.sleep(0.05)  # 50ms
          return get_product_with_lock(product_id)  # retry


FIX 2: STALE-WHILE-REVALIDATE (Background Refresh)

  Store TWO pieces of metadata with each cache entry:
  → The data itself
  → A "soft TTL" (when to start refreshing)
  → A "hard TTL" (when to definitely expire)

  cache.set("product:popular", {
      "data": {...},
      "soft_ttl": now() + 50,   # Start refreshing at 50s
      "hard_ttl": now() + 70    # Actually expire at 70s
  }, ttl=70)

  On read:
  → If within soft_ttl: return cached data (fresh)
  → If past soft_ttl but within hard_ttl: 
    return cached (stale) data AND trigger async refresh
  → If past hard_ttl: cache miss (shouldn't happen if 
    refresh worked)

  ┌──────────────────────────────────────────────┐
  │  0s      50s           70s                   │
  │  │ FRESH  │ STALE BUT   │ EXPIRED            │
  │  │        │ REFRESHING  │                    │
  │  ├────────┼─────────────┼────────────────    │
  │         soft_ttl     hard_ttl                │
  │                                              │
  │  At 50s: ONE background thread refreshes     │
  │  At 51s: fresh data in cache, new TTLs set   │
  │  Users ALWAYS get data (stale for ~1 second) │
  │  Database sees ONE query, not 5,000.         │
  └──────────────────────────────────────────────┘

  This is exactly what the HTTP Cache-Control header 
  stale-while-revalidate does (from the CDN topic).
  Same concept applied to application-level caching.


FIX 3: JITTERED TTLs

  If you have 10,000 cache keys all with TTL=60:
  → They were all cached at roughly the same time
  → They ALL expire at roughly the same time
  → Mass stampede

  Fix: Add random jitter to TTL.
  
  ttl = 60 + random.randint(-10, 10)  # 50-70 seconds
  
  Now keys expire at different times.
  Instead of 10,000 simultaneous misses, you get 
  ~500 misses per second spread over 20 seconds.
  The database can handle 500/sec. It can't handle 10,000.
```

#### Pattern 2: Hot Key Problem

```
WHAT HAPPENS:
  One specific key receives disproportionate traffic.
  The single Redis node holding that key becomes the 
  bottleneck, even if other nodes have capacity.

  Example: Celebrity posts a tweet. "tweet:celebrity:123" 
  gets 500,000 reads/sec. That key lives on ONE Redis node.
  That node maxes out. Other nodes are idle.

  ┌─────────┐  ┌─────────┐  ┌─────────┐
  │ Node A  │  │ Node B  │  │ Node C  │
  │ 500K    │  │ 2K      │  │ 3K      │
  │ ops/sec │  │ ops/sec │  │ ops/sec │
  │ ██████  │  │ ▓       │  │ ▓       │
  │ MAXED   │  │ idle    │  │ idle    │
  └─────────┘  └─────────┘  └─────────┘

FIXES:

FIX 1: READ REPLICAS FOR HOT KEYS
  Detect hot keys → replicate to multiple nodes.
  
  Instead of one key "tweet:123", create:
  "tweet:123:r1", "tweet:123:r2", "tweet:123:r3"
  All with the same data.
  
  On read: randomly pick a replica.
  
  def get_hot_key(key, num_replicas=5):
      replica_id = random.randint(1, num_replicas)
      return cache.get(f"{key}:r{replica_id}")
  
  500K reads spread across 5 replicas = 100K per node.

FIX 2: LOCAL CACHE (L1 + L2)
  Each application server caches hot keys in LOCAL memory.
  
  ┌──────────────┐    ┌──────────────┐
  │ App Server 1 │    │ App Server 2 │
  │ ┌──────────┐ │    │ ┌──────────┐ │
  │ │ L1 Cache │ │    │ │ L1 Cache │ │
  │ │ (local   │ │    │ │ (local   │ │
  │ │  memory) │ │    │ │  memory) │ │
  │ └────┬─────┘ │    │ └────┬─────┘ │
  └──────┼───────┘    └──────┼───────┘
         │                   │
         ▼                   ▼
  ┌──────────────────────────────────┐
  │  L2 Cache (Redis)                │
  │  (distributed, shared)           │
  └──────────────┬───────────────────┘
                 │
                 ▼
  ┌──────────────────────────────────┐
  │  Database                        │
  └──────────────────────────────────┘
  
  L1: In-process memory (HashMap, Guava Cache, Caffeine)
      → Sub-microsecond access
      → Limited size (100MB-1GB per server)
      → TTL: very short (5-30 seconds) to limit staleness
      → No network hop
  
  L2: Redis/Memcached
      → Sub-millisecond access
      → Large capacity (GBs-TBs across cluster)
      → TTL: longer (minutes-hours)
      → Network hop required

  For hot keys:
  → L1 absorbs 95% of reads (no Redis traffic at all)
  → Only L1 misses reach Redis
  → 500K reads/sec × 50 servers = 10K reads per server
  → L1 handles all 10K locally
  → Redis sees almost zero traffic for this key

  TRADEOFF: L1 cache is PER-SERVER, so each server has 
  its own copy, which can be slightly different.
  Maximum staleness = L1 TTL.
```

#### Pattern 3: Cache Penetration

```
WHAT HAPPENS:
  Requests for data that DOESN'T EXIST — not in cache, 
  not in database. Every request is a cache miss that 
  queries the database, finds nothing, and doesn't cache 
  anything (there's nothing to cache).

  Example: Attacker sends requests for user IDs that 
  don't exist: user:999999999, user:999999998, ...
  
  Each request: cache miss → DB query → not found → 
  no cache → next request misses again → DB query...
  
  The cache provides ZERO protection because there's 
  nothing to cache.

FIX 1: CACHE NEGATIVE RESULTS (Null Caching)

  If the database returns nothing, cache a sentinel:
  
  def get_user(user_id):
      data = cache.get(f"user:{user_id}")
      if data == "NULL_SENTINEL":
          return None  # Known to not exist
      if data is not None:
          return data
      
      data = db.query(...)
      if data is None:
          cache.set(f"user:{user_id}", "NULL_SENTINEL", ttl=60)
          return None
      
      cache.set(f"user:{user_id}", data, ttl=300)
      return data
  
  Now the second request for a non-existent user hits 
  the cache and gets "NULL_SENTINEL" — no DB query.
  
  Use SHORT TTL for null entries (60s) so that if the 
  data is created later, it becomes visible relatively quickly.

FIX 2: BLOOM FILTER

  A Bloom filter is a probabilistic data structure that 
  answers: "Is this element in the set?"
  
  → "Definitely NOT in the set" — guaranteed correct
  → "Probably in the set" — might be wrong (false positive)
  → NEVER gives false negatives
  
  ┌──────────────────────────────────────────────┐
  │  Before querying cache or DB, check Bloom:   │
  │                                              │
  │  bloom.contains("user:999999999")            │
  │  → "Not in set" → return null immediately    │
  │     (don't even check cache or DB)           │
  │                                              │
  │  bloom.contains("user:123")                  │
  │  → "Probably in set" → proceed to cache/DB   │
  │                                              │
  │  Bloom filter: 1 bit per element × ~10 bits  │
  │  for 1% false positive rate                  │
  │  100M users → ~120MB Bloom filter            │
  │  Fits in memory. O(1) lookup.                │
  │                                              │
  │  Eliminates 100% of non-existent key queries │
  │  (with a small false positive rate).         │
  └──────────────────────────────────────────────┘
```

#### Pattern 4: Cache Avalanche

```
WHAT HAPPENS:
  The ENTIRE CACHE LAYER goes down simultaneously.
  ALL traffic suddenly hits the database.
  Database collapses under the load it was designed 
  to be protected from.

  This is different from a stampede (one key expires).
  This is the ENTIRE cache failing at once.

  Causes:
  → Redis cluster crash (all nodes)
  → Network partition between app servers and Redis
  → Redis restart (cold cache)
  → Mass TTL expiration (all keys set at same time 
    with same TTL)

FIXES:

FIX 1: HIGH AVAILABILITY FOR CACHE LAYER
  → Redis Sentinel (automatic failover)
  → Redis Cluster (data distributed, partial failure OK)
  → Multi-region cache replication
  → Never have a single Redis instance for production.

FIX 2: CIRCUIT BREAKER ON DATABASE
  If cache is down, don't send ALL traffic to DB.
  Use a circuit breaker:
  
  → CLOSED: Cache works, DB gets normal load
  → OPEN: Cache is down. DB is overwhelmed. 
    REJECT requests with a degraded response 
    instead of killing the DB.
  → HALF-OPEN: Try a few requests to see if DB 
    can handle them. If yes, close circuit.
  
  Better to return "service temporarily degraded" 
  to SOME users than to crash the database and 
  degrade service for ALL users.

FIX 3: CACHE WARMING ON RESTART
  When cache restarts (cold), pre-populate it with 
  the most frequently accessed keys BEFORE opening 
  it to traffic.
  
  → Keep a list of "top 10,000 most accessed keys"
  → On cache restart: query DB for all 10,000
  → Populate cache BEFORE accepting traffic
  → Then open to traffic — most hits are warm
  
  This prevents the "cold start stampede" where 
  an empty cache causes 100% miss rate → DB overload.

FIX 4: GRACEFUL DEGRADATION
  Application should function (degraded) without cache:
  → Serve stale data from a secondary source
  → Return partial results
  → Queue requests and process slowly
  → Show "loading" instead of error
  
  NEVER design a system where cache failure = total failure.
  Cache is an OPTIMIZATION, not a dependency.
  (Although in practice, many systems accidentally make 
  it a dependency.)
```

---

### Part D: Multi-Layer Caching Architecture

```
PRODUCTION SYSTEMS USE MULTIPLE CACHE LAYERS:

  ┌─────────────────────────────────────────────────────┐
  │                                                     │
  │  ┌───────────────────────────────────────────┐      │
  │  │  LAYER 0: Browser Cache                   │      │
  │  │  Cache-Control: max-age=3600              │      │
  │  │  → Eliminates the HTTP request entirely   │      │
  │  │  → Zero latency                           │      │
  │  │  → Per-user, private data OK              │      │
  │  └────────────────────┬──────────────────────┘      │
  │                       │ (miss or expired)           │
  │  ┌────────────────────▼──────────────────────┐      │
  │  │  LAYER 1: CDN Edge Cache                  │      │
  │  │  CloudFront, Cloudflare, Fastly           │      │
  │  │  → Geographically distributed             │      │
  │  │  → Public, static, and semi-static content│      │
  │  │  → Latency: 1-20ms (edge proximity)       │      │
  │  └────────────────────┬──────────────────────┘      │
  │                       │ (miss)                      │
  │  ┌────────────────────▼──────────────────────┐      │
  │  │  LAYER 2: Application Local Cache (L1)    │      │
  │  │  In-process: Caffeine, Guava, HashMap     │      │
  │  │  → Per-server, not shared                 │      │
  │  │  → Sub-microsecond access                 |      │
  │  │  → Very short TTL (5-30s)                 │      │
  │  │  → Hot keys, config, metadata             │      │
  │  └────────────────────┬──────────────────────┘      │
  │                       │ (miss)                      │
  │  ┌────────────────────▼──────────────────────┐      │
  │  │  LAYER 3: Distributed Cache (L2)          │      │
  │  │  Redis, Memcached                         │      │
  │  │  → Shared across all app servers          │      │
  │  │  → Sub-millisecond access                 │      │
  │  │  → Larger capacity (GBs-TBs)              │      │
  │  │  → Longer TTL (minutes-hours)             │      │
  │  └────────────────────┬──────────────────────┘      │
  │                       │ (miss)                      │
  │  ┌────────────────────▼──────────────────────┐      │
  │  │  LAYER 4: Database Query Cache            │      │
  │  │  PostgreSQL shared_buffers, MySQL buffer  │      │
  │  │  pool, MongoDB WiredTiger cache           │      │
  │  │  → DB-level page/result caching           │      │
  │  │  → Automatic, managed by DB engine        │      │
  │  └────────────────────┬──────────────────────┘      │
  │                       │ (miss)                      │
  │  ┌────────────────────▼──────────────────────┐      │
  │  │  LAYER 5: Disk (actual data)              │      │
  │  │  → Final source of truth                  │      │
  │  │  → Slowest layer (1-10ms)                 │      │
  │  └───────────────────────────────────────────┘      │
  │                                                     │
  │  EACH LAYER REDUCES TRAFFIC TO THE NEXT:            │
  │  Browser: absorbs 40% of requests (never leave user)│
  │  CDN: absorbs 35% (never reach origin)              │
  │  L1: absorbs 15% (never leave the server)           │
  │  L2: absorbs 8% (one network hop to Redis)          │
  │  DB Cache: absorbs 1.5% (memory vs disk)            │
  │  Disk: handles 0.5% of original traffic             │
  │                                                     │
  │  Result: 100,000 requests/sec at the browser        │
  │  → 500 queries/sec actually hit disk                │
  │  → 200x reduction through layered caching           │
  └─────────────────────────────────────────────────────┘
```

---

## Step 3: Production Patterns & Failure Modes

```
┌─────────────────────────────────────────────────────────────┐
│  FAILURE MODE #1: CACHE INCONSISTENCY ACROSS SERVICES       │
│                                                             │
│  Scenario: Service A caches user profiles with TTL=300.     │
│  Service B also caches user profiles with TTL=600.          │
│  User updates name via Service A.                           │
│  Service A invalidates ITS cache.                           │
│  Service B still has the OLD name for up to 600 seconds     │
│                                                             │
│  User sees their new name on page A, old name on page B.    │
│                                                             │
│  Fix:                                                       │
│  → Centralized cache (both services use same Redis key)     │
│  → Event-driven invalidation (DB change → Kafka → both      │
│    services invalidate)                                     │
│  → Consistent TTLs across services for the same data        │
├─────────────────────────────────────────────────────────────┤
│  FAILURE MODE #2: SERIALIZATION MISMATCH                    │
│                                                             │
│  Scenario: You deploy a new version of User model.          │
│  New field added: "preferences" (JSON object).              │
│  Cache still has old User objects without "preferences."    │
│  New code reads from cache → deserializes → crash because   │
│  "preferences" field is missing.                            │
│                                                             │
│  Fix:                                                       │
│  → ALWAYS handle missing fields in deserialization          │
│  → Version your cache keys: "user:v2:123" vs "user:v1:123"  │
│  → Flush cache during deployments that change data shape    │
│  → Use backward-compatible serialization (Protobuf,         │
│    Avro — handle missing fields gracefully)                 │
├─────────────────────────────────────────────────────────────┤
│  FAILURE MODE #3: BIG KEY PROBLEM                           │
│                                                             │
│  Scenario: Cache a user's order history. New users have     │
│  2-3 orders. Power users have 50,000 orders.                │
│  One Redis GET returns 4MB of data.                         │
│                                                             │
│  What breaks:                                               │
│  → Redis single-threaded: 4MB serialization blocks          │
│    the event loop for ~10ms                                 │
│  → Network: 4MB transfer on every cache hit                 │
│  → All other Redis operations delayed                       │
│  → The big key is slow AND slows down everything else       │
│                                                             │
│  Fix:                                                       │
│  → Don't cache unbounded collections                        │
│  → Cache only "recent 20 orders" not "all orders"           │
│  → Split big values: "orders:123:page:1",                   │
│    "orders:123:page:2"                                      │
│  → Monitor: redis-cli --bigkeys                             │
│    (finds the largest keys in the database)                 │
│  → Set a max value size policy: "no cache value > 100KB"    │
├─────────────────────────────────────────────────────────────┤
│  FAILURE MODE #4: DOGPILE AFTER DEPLOY                      │
│                                                             │
│  Scenario: You deploy new code that changes cache key       │
│  format from "user:{id}" to "user:v2:{id}".                 │
│  ALL existing cache keys are now invisible to new code.     │
│  100% cache miss rate immediately after deploy.             │
│  Database gets slammed with every request.                  │
│                                                             │
│  This is an artificial cache avalanche caused by deploy.    │
│                                                             │
│  Fix:                                                       │
│  → Read from BOTH old and new key formats during migration  │
│  → Pre-warm new keys BEFORE switching code                  │
│  → Gradual rollout (canary) to limit miss rate impact       │
│  → Never change key format without a migration strategy     │
└─────────────────────────────────────────────────────────────┘
```

---

## Step 4: Hands-On Exercises

```
┌──────────────────────────────────────────────────────────────┐
│  EXERCISE 1: Observe Cache Stampede                          │
│                                                              │
│  # Start Redis                                               │
│  docker run -p 6379:6379 redis:7                             │
│                                                              │
│  # Set a key with short TTL                                  │
│  redis-cli SET product:popular "data" EX 5                   │
│                                                              │
│  # In a Python script, simulate concurrent readers:          │
│  import redis, threading, time                               │
│                                                              │
│  r = redis.Redis()                                           │
│  db_queries = 0                                              │
│                                                              │
│  def reader():                                               │
│      global db_queries                                       │
│      for _ in range(100):                                    │
│          val = r.get("product:popular")                      │
│          if val is None:                                     │
│              db_queries += 1  # This is a "DB query"         │
│              time.sleep(0.01) # Simulate DB latency          │
│              r.set("product:popular", "data", ex=5)          │
│          time.sleep(0.05)                                    │
│                                                              │
│  # Launch 50 threads                                         │
│threads = [threading.Thread(target=reader) for _ in range(50)]│
│  for t in threads: t.start()                                 │
│  for t in threads: t.join()                                  │
│                                                              │
│  print(f"DB queries: {db_queries}")                          │
│  # Without locking: db_queries will be HIGH (many threads    │
│  # miss simultaneously after TTL expiry)                     │
│  # With locking (add NX lock): db_queries will be LOW        │
│  # (only 1 thread fetches, others wait)                      │
│                                                              │
│  # OBSERVE: The stampede in action. Then add the lock        │
│  # pattern and observe the difference.                       │
├──────────────────────────────────────────────────────────────┤
│  EXERCISE 2: Observe Cache Penetration                       │
│                                                              │
│  # Without null caching:                                     │
│  redis-cli GET "user:nonexistent"                            │
│  # Returns (nil) — cache miss every time                     │
│  # In production: this goes to DB every time                 │
│                                                              │
│  # With null caching:                                        │
│  redis-cli SET "user:nonexistent" "NULL" EX 60               │
│  redis-cli GET "user:nonexistent"                            │
│  # Returns "NULL" — cache HIT (no DB query!)                 │
│                                                              │
│  # After 60 seconds:                                         │
│  redis-cli GET "user:nonexistent"                            │
│  # Returns (nil) — TTL expired, would re-check DB            │
│                                                              │
│  # OBSERVE: The difference between "no protection" and       │
│  # "null caching" against non-existent key attacks.          │
├──────────────────────────────────────────────────────────────┤
│  EXERCISE 3: See the Race Condition                          │
│                                                              │
│  # Simulate the invalidation race condition:                 │
│  # Terminal 1 (writer):                                      │
│  redis-cli SET user:1 "Alice"                                │
│  # Wait, then:                                               │
│  redis-cli SET user:1 "Alicia"                               │
│                                                              │
│  # Terminal 2 (reader, run between the two SET commands):    │
│  redis-cli GET user:1                                        │
│  # If you GET between the DB update and cache update,        │
│  # you see "Alice" (stale)                                   │
│                                                              │
│  # Now try with DELETE strategy:                             │
│  # Terminal 1 (writer):                                      │
│  redis-cli DEL user:1                                        │
│                                                              │
│  # Terminal 2 (reader):                                      │
│  redis-cli GET user:1                                        │
│  # Returns (nil) — miss — forces re-read from DB             │
│  # This ALWAYS gets fresh data on the re-read.               │
│                                                              │
│  # OBSERVE: DELETE is safer than UPDATE for invalidation     │
│  # because it forces re-read from source of truth.           │
└──────────────────────────────────────────────────────────────┘
```

---

## Step 5: SRE Scenario

```
┌──────────────────────────────────────────────────────────────┐
│  SCENARIO: Food Delivery Platform — Peak Dinner Rush         │
│                                                              │
│  You're the on-call SRE for a food delivery app.             │
│  Stack:                                                      │
│  → PostgreSQL: Orders, restaurants, menu items               │
│  → Redis Cluster: 6 masters, each with 1 replica             │
│    → L2 cache for menu data, restaurant info, pricing        │
│    → Session storage                                         │
│    → Rate limiting                                           │
│  → Caffeine (in-process): L1 cache on each app server        │
│    → 30-second TTL, 5,000 entry max per server               │
│  → CDN: Static assets + restaurant images                    │
│  → 40 application servers                                    │
│  → Average 50K concurrent users during dinner rush           │
│                                                              │
│  ARCHITECTURE:                                               │
│  Read path for "view restaurant menu":                       │
│    L1 (Caffeine) → L2 (Redis) → PostgreSQL                   │
│    Cache-aside at both layers.                               │
│    L1 TTL: 30 seconds                                        │
│    L2 TTL: 300 seconds (5 minutes)                           │
│                                                              │
│  Invalidation: On menu update by restaurant owner,           │
│    application DELETEs the Redis key.                        │
│    L1 caches are NOT explicitly invalidated                  │
│    (they rely on 30-second TTL).                             │
│                                                              │
│  ALERT TIMELINE (Friday 6:30 PM — peak dinner):              │
│                                                              │
│  18:30 — All systems nominal. Cache hit rate: L1=72%,        │
│          L2=96%. DB queries/sec: 380.                        │
│                                                              │
│  18:31 — Marketing campaign launches: "50% off all           │
│          restaurants in Manhattan!" Push notification        │
│          sent to 800,000 users simultaneously.               │
│                                                              │
│  18:32 — Traffic spike: concurrent users 50K → 220K          │
│          in 90 seconds.                                      │
│                                                              │
│  18:33 — L2 Redis cache hit rate: 96% → 71%.                 │
│          Redis ops/sec: 45K → 189K.                          │
│          Redis node 3 CPU: 98%.                              │
│          Redis node 3 slowlog shows:                         │
│            "HGETALL restaurant:manhattan:5678"               │
│            duration: 23ms (normally <1ms)                    │
│            This key is 2.3MB.                                │
│                                                              │
│  18:34 — PostgreSQL: queries/sec: 380 → 8,400.               │
│          p99 query latency: 4ms → 340ms.                     │
│          Top query in pg_stat_statements:                    │
│            SELECT * FROM menu_items                          │
│            WHERE restaurant_id = $1                          │
│            avg_exec_time: 89ms                               │
│            calls in last minute: 4,200                       │
│          Connection pool: 180/200 (approaching limit).       │
│                                                              │
│  18:35 — L1 Caffeine stats across all 40 servers:            │
│          hit_rate: 72% → 31%.                                │
│          eviction_count: 12,000/sec (across all servers).    │
│          cache_size: 5,000/5,000 on every server (FULL).     │
│                                                              │
│  18:36 — Application error rate: 0.1% → 4.7%.                │
│          Errors: "Connection pool exhausted" (PostgreSQL)    │
│          Errors: "Timeout waiting for Redis response"        │
│          Orders/sec: 850 → 340 (orders DROPPING).            │
│                                                              │
│  18:37 — Customer complaints flooding in:                    │
│          "I can't see the menu"                              │
│          "The app is super slow"                             │
│          "I see prices from earlier today, not the 50% off"  │
│          "I placed an order but got charged full price"      │
│                                                              │
│  18:38 — Redis node 3 response time: 23ms average            │
│          (other nodes: 0.4ms average).                       │
│          Redis MEMORY on node 3: 13.8GB / 16GB (86%).        │
│          One key "restaurant:manhattan:5678" was accessed    │
│          47,000 times in the last minute.                    │
│                                                              │
│  18:39 — Restaurant owner for restaurant 5678 calls          │
│          support: "I updated my menu to show 50% off         │
│          prices but customers are saying they still see      │
│          full prices and are being CHARGED full price!"      │
│                                                              │
│  18:40 — Order service logs show:                            │
│          Orders for restaurant 5678 are using CACHED         │
│          menu prices (full price) from Redis L2 cache,       │
│          NOT the updated 50%-off prices in PostgreSQL.       │
│          The Redis key "menu:restaurant:5678" was            │
│          invalidated at 18:31 when the owner updated,        │
│          but was immediately re-cached by the FLOOD          │
│          of concurrent requests — one of which read          │
│          the OLD price from PostgreSQL before the            │
│          UPDATE transaction committed.                       │
│                                                              │
│          Timeline reconstruction:                            │
│          18:31:00.100 — Owner submits price update           │
│          18:31:00.102 — BEGIN transaction in PostgreSQL      │
│          18:31:00.105 — Application DELETEs Redis key        │
│            "menu:restaurant:5678"                            │
│          18:31:00.106 — 340 concurrent requests for          │
│            restaurant 5678 menu → all MISS Redis             │
│          18:31:00.108 — First request reads PostgreSQL       │
│            → transaction NOT YET COMMITTED                   │
│            → reads OLD prices (full price)                   │
│          18:31:00.110 — First request re-caches OLD          │
│            prices in Redis with TTL=300                      │
│          18:31:00.150 — PostgreSQL COMMITS new prices        │
│          18:31:00.151 — 339 remaining requests get           │
│            Redis HIT → OLD (full) prices                     │
│                                                              │
│          Result: Redis has STALE prices for up to 300s.      │
│          Orders placed in this window are charged            │
│          FULL PRICE despite the promotion.                   │
│                                                              │
│  18:41 — Finance team alerts: "We're charging customers      │
│          full price during a 50% off campaign. This is a     │
│          legal issue. We'll have to refund every affected    │
│          order."                                             │
│                                                              │
└──────────────────────────────────────────────────────────────┘

QUESTIONS:

Q1: Identify ALL the problems from the alerts. For each, 
    specify the root cause, affected component, and evidence. 
    Separate the CASCADE problems from the INDEPENDENT problems.

Q2: The stale pricing bug (18:40 timeline reconstruction) 
    is a classic cache invalidation race condition. 
    
    Explain PRECISELY why deleting the cache key BEFORE 
    the database transaction commits caused this problem. 
    Then explain TWO different approaches that would have 
    prevented it — with tradeoffs of each.

Q3: The L1 Caffeine cache hit rate dropped from 72% to 31%. 
    The L1 cache is FULL (5,000/5,000) on every server 
    and evicting 12,000 keys/sec.
    
    Explain what's happening at the L1 layer. Why did the 
    hit rate drop if the cache is full? Full cache should 
    mean more data available, not less.

Q4: Restaurant 5678's data is a 2.3MB key accessed 
    47,000 times/minute, all landing on Redis node 3.
    This is a HOT KEY problem.
    
    Give TWO immediate mitigations and ONE long-term fix.
    Be specific about the tradeoffs.

Q5: The customer complaint "I placed an order but got 
    charged full price" is now a FINANCIAL and LEGAL issue.
    This changes your prioritization.
    
    Give your complete prioritized mitigation plan.
    Address both the technical systems AND the business 
    impact. Remember: one change → verify → next change.
    Also: what is the ONE thing you should have done 
    BEFORE the marketing campaign launched?
```

---

## Step 6: Targeted Reading

```
┌──────────────────────────────────────────────────────────────┐
│  READ AFTER THIS LESSON:                                     │
│                                                              │
│  DDIA Chapter 5: "Replication"                               │
│  → Pages 151-167 (Leaders and Followers)                     │
│  → Focus on: "Implementation of Replication Logs"            │
│    This connects to how caches can use replication           │
│    logs (CDC) for event-driven invalidation.                 │
│                                                              │
│  DDIA Chapter 5: continued                                   │
│  → Pages 167-178 (Problems with Replication Lag)             │
│  → Sections: "Reading Your Own Writes",                      │
│    "Monotonic Reads", "Consistent Prefix Reads"              │
│  → These are the SAME consistency challenges that            │
│    caching creates. The parallel between replication         │
│    lag and cache staleness is deliberate — both are          │
│    forms of "reading from a copy that's behind the           │
│    primary source of truth."                                 │
│                                                              │
│  DDIA Chapter 12: "The Future of Data Systems"               │
│  → Pages 499-515 (Derived Data vs Source of Truth)           │
│  → A cache IS derived data. This chapter frames              │
│    caching within the broader context of derived             │
│    data systems. Reinforces the "source of truth"            │
│    principle we covered in invalidation strategies.          │
│                                                              │
│  TOTAL: ~45 pages. Read as reinforcement.                    │
│  The replication lag sections will feel familiar —           │
│  you already understand these concepts from the SQL          │
│  topic (replica lag) and now from caching (stale data).      │
│  DDIA unifies them into one framework.                       │
└──────────────────────────────────────────────────────────────┘
```

---

## Step 7: Key Takeaways

```
┌──────────────────────────────────────────────────────────────┐
│  5 THINGS TO REMEMBER IF YOU FORGET EVERYTHING ELSE          │
│                                                              │
│  1. Cache-aside is the DEFAULT strategy. Use it unless       │
│     you have a specific reason for another. It's simple,     │
│     resilient to cache failure, and well-understood.         │
│     Combine with TTL as safety net. Always.                  │
│                                                              │
│  2. Prefer DELETE over UPDATE for invalidation.              │
│     DELETE + re-fetch always gets the latest value from      │
│     the source of truth. UPDATE risks write-ordering         │
│     races between concurrent writers. The extra DB read      │
│     on the next cache miss is a small price for correctness. │
│                                                              │
│  3. Cache stampede is the #1 caching production incident.    │
│     Fix with: distributed lock (only one thread re-fetches), │
│     stale-while-revalidate (background refresh before        │
│     expiry), and jittered TTLs (spread expirations).         │
│     Use ALL THREE in production for critical keys.           │
│                                                              │
│  4. Multi-layer caching (Browser → CDN → L1 → L2 → DB)       │
│     each layer reduces traffic to the next. But it also      │
│     multiplies the STALENESS window and the INVALIDATION     │
│     complexity. More layers = faster reads = harder to       │
│     reason about consistency.                                │
│                                                              │
│  5. A cache is NOT a source of truth. Ever. It's a           │
│     derived copy that's allowed to be stale. Design your     │
│     system so that the WORST CASE of stale cache data        │
│     causes user inconvenience, not financial loss or         │
│     data corruption. If stale cache data can cause real      │
│     harm (wrong prices, wrong balances), you need            │
│     write-through or synchronous invalidation on that        │
│     specific data path.                                      │
└──────────────────────────────────────────────────────────────┘
```




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
┌──────────────────────┬───────────────────────────────────┐
│ CAUSED BY CASCADE    │ CHAIN                             │
├──────────────────────┼───────────────────────────────────┤
│ L1 thrashing         │ Traffic spike → working set       │
│                      │ exceeds L1 capacity → thrashing   │
├──────────────────────┼───────────────────────────────────┤
│ L2 Redis overload    │ L1 misses cascade to L2 +         │
│                      │ hot key amplifies load on node 3  │
├──────────────────────┼───────────────────────────────────┤
│ PostgreSQL overload  │ L1 miss + L2 miss → DB fallback   │
│                      │ at 22x normal volume              │
├──────────────────────┼───────────────────────────────────┤
│ Connection pool      │ Slow DB queries hold connections  │
│ exhaustion           │ longer → pool drains              │
├──────────────────────┼───────────────────────────────────┤
│                      │                                   │
│ INDEPENDENT          │ REASON                            │
├──────────────────────┼───────────────────────────────────┤
│ Stale price race     │ This is a CODE BUG in the cache   │
│ condition            │ invalidation logic. It would      │
│                      │ exist even without the traffic    │
│                      │ spike. The spike made it VISIBLE  │
│                      │ (340 concurrent requests in the   │
│                      │ race window) but the bug was      │
│                      │ always latent. Under normal       │
│                      │ traffic, maybe 1-2 requests hit   │
│                      │ the window — still wrong but      │
│                      │ rarely noticed.                   │
├──────────────────────┼───────────────────────────────────┤
│ Hot key (2.3MB)      │ PARTIALLY independent. The key    │
│                      │ being 2.3MB is a pre-existing     │
│                      │ data modeling problem. The traffic│
│                      │ spike made it catastrophic.       │
└──────────────────────┴───────────────────────────────────┘
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

  ┌─────────────────────────────────────────────────────┐
  │                                                     │
  │  CACHE DELETE          DB COMMIT                    │
  │       │                    │                        │
  │  ─────┼────────────────────┼──────── time ────►     │
  │       │                    │                        │
  │       │◄──── DANGER ZONE ──►│                       │
  │       │   (cache empty,     │                       │
  │       │    DB has old data) │                       │
  │       │                    │                        │
  │  Any request in this window:                        │
  │    1. Checks Redis → MISS (we just deleted it)      │
  │    2. Falls through to PostgreSQL                   │
  │    3. Reads OLD prices (UPDATE not committed yet)   │
  │    4. Re-caches OLD prices in Redis with TTL=300    │
  │    5. Cache is now POISONED for 300 seconds         │
  │                                                     │
  │  Even after the DB commits at .150:                 │
  │    → The correct prices are in PostgreSQL           │
  │    → But Redis has the OLD prices                   │
  │    → All subsequent reads hit Redis (cache HIT)     │
  │    → Everyone sees stale prices for up to 300s      │
  │                                                     │
  └─────────────────────────────────────────────────────┘

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
✅ PREVENTS the stale-cache-poisoning race condition
✅ Simple to implement — just reorder two lines
✅ Concurrent reads after cache delete see NEW prices

❌ SMALL STALENESS WINDOW exists between DB commit and 
   cache delete (~5-50ms depending on network latency 
   to Redis). During this window, reads hit the STALE 
   cache entry (old prices). But this window is:
   - Much shorter than the 45ms danger zone in the original
   - Serves stale data that EXISTS, not empty-then-repoisoned
   - Self-resolving as soon as the delete executes

❌ If the cache delete FAILS (Redis down, network blip):
   - Cache retains old data until TTL expires (300s)
   - Need a retry mechanism or background invalidation job

❌ Still vulnerable to a DIFFERENT race: if another request 
   is reading from PostgreSQL at the exact moment between 
   commit and cache delete, it might re-cache the old 
   data... wait, no — after commit, PostgreSQL returns 
   new data. This race doesn't exist.
   
   ACTUALLY: there IS a subtler race:
   Request A: reads DB (gets new prices) at T=1
   Cache delete happens at T=2
   Request B: misses cache at T=3, reads DB (new prices)
   Request A: writes to cache at T=4 (new prices ✅)
   
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
✅ ELIMINATES the cache miss entirely — no race window
✅ ELIMINATES the stampede on popular keys 
   (cache never goes empty)
✅ Strongest consistency — cache is updated atomically 
   with the write
✅ No window where any read can see stale data 
   (except the tiny commit-to-cache-write gap)

❌ MORE COMPLEX: requires the write path to know the 
   exact cache key format and serialization
   → Tight coupling between write path and cache schema
   → If the cache key format changes, writes break

❌ EXTRA DATABASE READ after commit to populate the cache
   → One additional SELECT per write operation
   → Acceptable for menu updates (infrequent writes)
   → Would be problematic for high-write-rate data

❌ DOESN'T HELP if the write-through fails:
   → If Redis is unreachable during the SET, the cache 
     retains old data (same as Approach 1)
   → Need retry/fallback mechanism

❌ SUBTLE RACE still possible with concurrent writers:
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
┌─────────────────────┬────────────────────┬──────────────────┐
│                     │ DELETE AFTER COMMIT│ WRITE-THROUGH    │
├─────────────────────┼────────────────────┼──────────────────┤
│ Race condition      │ ELIMINATED         │ ELIMINATED       │
│ Stampede on miss    │ Still possible     │ ELIMINATED       │
│                     │ (cache is empty    │ (cache never     │
│                     │ briefly)           │ empty)           │
├─────────────────────┼────────────────────┼──────────────────┤
│ Complexity          │ LOW (reorder lines)│ MODERATE (write  │
│                     │                    │ path knows cache)│
├─────────────────────┼────────────────────┼──────────────────┤
│ Staleness window    │ ~5-50ms (commit to │ ~5-50ms (commit  │
│                     │ delete)            │ to cache write)  │
├─────────────────────┼────────────────────┼──────────────────┤
│ Concurrent writer   │ SAFE (delete is    │ NEEDS versioning │
│ safety              │ idempotent)        │ to prevent stale │
│                     │                    │ overwrites       │
├─────────────────────┼────────────────────┼──────────────────┤
│ For this incident   │ SUFFICIENT         │ BETTER           │
│                     │ (menu updates are  │ (also prevents   │
│                     │ infrequent)        │ stampede on the  │
│                     │                    │ popular key)     │
└─────────────────────┴────────────────────┴──────────────────┘
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

  ┌─────────────────────────────────────────┐
  │  L1 Cache (5,000 slots)                 │
  │  ████████████████████░░░░░░░░           │
  │  ◄── 4,000 active ──►◄ 1000 ►           │
  │                        free             │
  │  Working set FITS. Hit rate HIGH.       │
  └─────────────────────────────────────────┘

AFTER the campaign launches (18:31+):
  → 220K concurrent users (4.4x)
  → ALL browsing Manhattan restaurants specifically
  → Plus normal traffic to non-Manhattan restaurants
  → Working set EXPLODES: 15,000-20,000 unique 
    restaurant/menu/item combinations being actively 
    accessed across all 40 servers
  → L1 cache size: STILL 5,000 entries per server
  → Working set FAR EXCEEDS cache: 15,000 >> 5,000

  ┌─────────────────────────────────────────┐
  │  L1 Cache (5,000 slots)                 │
  │  ████████████████████████████████████   │
  │  ◄────────── 5,000 FULL ──────────►     │
  │                                         │
  │  Working set: 15,000+ entries needed    │
  │  Only 5,000 can fit.                    │
  │  Cache is FULL but can only hold 1/3    │
  │  of what's being requested.             │
  └─────────────────────────────────────────┘
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
✅ Reduces Redis load for this key from 783/sec to 
   ~1-2/sec per server (one fetch per L1 TTL expiry, 
   coalesced across concurrent requests)
   40 servers × 1/30s = ~1.3 fetches/sec total
✅ Fast to implement — application-level change only
✅ No Redis infrastructure changes needed

❌ EACH OF 40 APP SERVERS still fetches the 2.3MB key 
   independently when their L1 TTL expires
   → 40 fetches every 30 seconds = 40 × 2.3MB = 92MB 
     network transfer every 30 seconds (acceptable)
❌ Doesn't fix the fundamental issue: 2.3MB is too 
   large for a Redis key
❌ L1 TTL (30s) means data could be 30 seconds stale
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
✅ Doubles the read throughput for node 3's slots
✅ No data migration or resharding needed
✅ Configuration change only — fast to deploy

❌ Only 2x improvement — if the key is accessed 783/sec 
   and each node can handle ~43/sec (1000ms / 23ms), 
   2 nodes can handle ~86/sec. We need 783/sec.
   STILL NOT ENOUGH for this specific hot key.
❌ Replica reads may return slightly stale data 
   (replication lag, typically <1ms)
❌ Doesn't solve the ROOT CAUSE: the key is too large

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
┌──────┬──────────────────────────┬────────────────────────────────┐
│ RANK │ ACTION                   │ JUSTIFICATION                  │
├──────┼──────────────────────────┼────────────────────────────────┤
│  1   │ Fix stale prices         │ FINANCIAL/LEGAL. Every second  │
│      │ (purge cache + fix code) │ = more orders at wrong price   │
│      │                          │ = more refunds = more legal    │
│      │                          │ exposure. STOP THE BLEEDING.   │
├──────┼──────────────────────────┼────────────────────────────────┤
│  2   │ Hot key mitigation       │ ENABLES fix #1 to work.        │
│      │ (request coalescing)     │ Even after purging stale cache,│
│      │                          │ 47K req/min will re-flood node │
│      │                          │ 3. Must reduce key access rate │
│      │                          │ BEFORE purging.                │
├──────┼──────────────────────────┼────────────────────────────────┤
│  3   │ PostgreSQL protection    │ DB is at 180/200 connections.  │
│      │ (connection pool +       │ If it hits 200, ALL services   │
│      │  query optimization)     │ fail, not just menus.          │
│      │                          │ Orders, payments, everything.  │
├──────┼──────────────────────────┼────────────────────────────────┤
│  4   │ L1 cache expansion       │ Reduces cascade amplification. │
│      │                          │ Every L1 hit is one less L2    │
│      │                          │ request, one less potential DB │
│      │                          │ query.                         │
├──────┼──────────────────────────┼────────────────────────────────┤
│  5   │ Notify finance/legal +   │ Parallel with technical fixes. │
│      │ identify affected orders │ Must start refund process and  │
│      │                          │ quantify financial impact.     │
└──────┴──────────────────────────┴────────────────────────────────┘
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
┌──────────┬────────────────────────────────────────────────┐
│ MINUTE   │ ACTION                                         │
├──────────┼────────────────────────────────────────────────┤
│ 0        │ START: Notify finance/legal (parallel track)   │
│          │ Deploy cache invalidation code fix             │
│          │ (write-through after commit)                   │
├──────────┼────────────────────────────────────────────────┤
│ 0-3      │ Deploy request coalescing + replica reads      │
│          │ (BEFORE cache purge to prevent stampede)       │
├──────────┼────────────────────────────────────────────────┤
│ 3-5      │ Purge stale price keys from Redis              │
│          │ Re-trigger price update through new code path  │
│          │ VERIFY: correct prices showing                 │
│          │ VERIFY: new orders at correct prices           │
├──────────┼────────────────────────────────────────────────┤
│ 5-7      │ VERIFY: Redis node 3 CPU declining             │
│          │ VERIFY: node 3 response time normalizing       │
├──────────┼────────────────────────────────────────────────┤
│ 7-10     │ Increase DB pool + add index if missing        │
│          │ VERIFY: pool usage < 70%, query latency down   │
├──────────┼────────────────────────────────────────────────┤
│ 10-12    │ Expand L1 cache to 20,000 entries              │
│          │ Rolling restart of app servers                 │
│          │ VERIFY: L1 hit rate climbing toward 70%+       │
├──────────┼────────────────────────────────────────────────┤
│ 12-15    │ Run affected order query                       │
│          │ Calculate refund amounts                       │
│          │ Initiate refund process                        │
├──────────┼────────────────────────────────────────────────┤
│ 15+      │ Monitor all systems for stability              │
│          │ Send proactive customer notifications          │
│          │ Write post-incident review                     │
│          │ Plan long-term: decompose hot key,             │
│          │   implement proper cache invalidation,         │
│          │   load test for campaign traffic patterns      │
└──────────┴────────────────────────────────────────────────┘
```
