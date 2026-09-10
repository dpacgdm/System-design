# Week 7, Topic 3: Distributed Counters and Heavy Hitters Top-K

---

## Learning Objectives
```
╔══════════════════════════════════════════════════════════════════════════╗
║   AFTER THIS MODULE, YOU WILL BE ABLE TO:                                ║
╟──────────────────────────────────────────────────────────────────────────╢
║                                                                          ║
║   1. Formulate requirements and capacity sizing for real-time counters   ║
║      and streaming heavy-hitters at 1 Billion+ daily events              ║
║                                                                          ║
║   2. Design an HLD blueprint separating lossy ingestion, streaming sketch║
║      aggregators, cached counter tiers, and durable persistence          ║
║                                                                          ║
║   3. Master the Count-Min Sketch and Space-Saving algorithms with bounded║
║      error guarantees and constant O(K) memory                           ║
║                                                                          ║
║   4. Solve the viral video hot-key bottleneck using counter sharding,    ║
║      write-buffering, and asynchronous batch flushes                     ║
║                                                                          ║
║   5. Architect bot-resistant view deduplication and defend counter       ║
║      accuracy in high-stakes interview scenarios                         ║
╚══════════════════════════════════════════════════════════════════════════╝
```

---

## Section 2: Wrong Mental Models (Destroy These First)

```
╔════════════════════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "View counting is just executing Redis INCR per view"           ║
╟────────────────────────────────────────────────────────────────────────────────────╢
║   WRONG. For a viral video with 100k views/sec, a single Redis key becomes         ║
║   a massive CPU bottleneck on that shard. Furthermore, direct increments           ║
║   provide zero deduplication against bots and replay loops.                        ║
╠════════════════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "Find trending topics with SELECT ... ORDER BY COUNT(*) DESC"   ║
╟────────────────────────────────────────────────────────────────────────────────────╢
║   WRONG. Scanning millions of tweets to aggregate frequencies in a relational      ║
║   or NoSQL table causes catastrophic I/O and latency spikes. Top-K streaming       ║
║   requires in-memory stream sketches, not full-table aggregations.                 ║
╠════════════════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "Probabilistic data structures return random garbage"           ║
╟────────────────────────────────────────────────────────────────────────────────────╢
║   WRONG. Structures like Count-Min Sketch and HyperLogLog provide mathematically   ║
║   proven error bounds (e.g. within 1% error with 99.9% confidence) while           ║
║   consuming 99.99% less memory than exact hash maps.                               ║
╠════════════════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "Every view count must update instantaneously in UI"            ║
╟────────────────────────────────────────────────────────────────────────────────────╢
║   WRONG. View counts are inherently eventually consistent. A creator seeing        ║
║   1,004,200 instead of 1,004,250 for 30 seconds causes zero harm. Batching         ║
║   and delayed flushing protect database write throughput.                          ║
╠════════════════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "A fixed 1-minute window is sufficient for rate limiting"       ║
╟────────────────────────────────────────────────────────────────────────────────────╢
║   WRONG. Fixed windows suffer from the boundary burst problem: a user can send     ║
║   100% of their quota at 00:59 and another 100% at 01:00, doubling allowed traffic.║
║   Sliding window counters or token buckets are required.                           ║
╚════════════════════════════════════════════════════════════════════════════════════╝
```

---

## Section 3: Requirements & Sizing Calculations

### 1. Functional Requirements

```
FUNCTIONAL REQUIREMENTS (Interview Scope):
  P0 — Core Requirements:
    → Real-Time Increment: Record views, clicks, or event counts with low latency (< 50ms).
    → Eventually Consistent Display: Return current counts for video/ad with <= 30s freshness lag.
    → Heavy Hitters (Top-K): Return the Top-K most popular items (e.g., Top 100 trending hashtags)
      over a rolling time window (last 1 hour, last 24 hours).
    → High Availability: The ingestion path must never drop events even under 5x viral traffic bursts.

  P1 — Desirable Features:
    → Bot & Fraud Deduplication: Discard repeated plays from the same user within a short window.
    → Distributed Rate Limiting: Support sliding window rate limits per user/API key.
```

### 2. Capacity Sizing (Back-of-the-Envelope)

| Factor | Metric | Average Load | Peak Load (5x Viral Burst) | 1-Year Requirement |
| :--- | :--- | :--- | :--- | :--- |
| **1. Throughput (RPS)** | Event Ingestion Rate | ~11,500 views/sec | ~57,500 views/sec | 365 Billion events/yr |
| **2. Read Query QPS** | View Count Display Reads | ~50,000 reads/sec | ~200,000 reads/sec | — |
| **3. Memory Working Set** | Count-Min Sketch & Top-K Heap | ~10 MB total RAM | ~25 MB total RAM | Negligible |
| **4. Storage Growth** | Durable Counter Table | ~50 MB / day | ~250 MB / day | ~18 GB / year |
| **5. Network Bandwidth** | Event Ingress (100B / event) | ~1.15 MB/sec In | ~5.75 MB/sec In | Standard NIC |

---

## Section 4: High-Level Design (HLD) Box-and-Arrow

```
                     DISTRIBUTED COUNTERS & TOP-K — HLD BLUEPRINT
                     ════════════════════════════════════════════

  ┌──────────────────┐           ┌──────────────────┐
  │ Mobile / Web App │           │ Video Player SDK │
  └────────┬─────────┘           └────────┬─────────┘
           │                              │
           └──────────────┬───────────────┘
                          │ HTTP POST /v1/views/record (event payload)
                          ▼
             ┌─────────────────────────┐
             │ API Gateway & Fraud WAF │ ──► Discard malicious / malformed requests
             └────────────┬────────────┘
                          │
                          ▼
             ┌─────────────────────────┐
             │  Event Ingestion Fleet  │ ──► Checks Bloom Filter (dedupes 24h viewer plays)
             └────────────┬────────────┘
                          │
                          │ Publishes valid raw events (partition key = `item_id`)
                          ▼
             ┌─────────────────────────┐
             │ Kafka Event Stream      │
             │ topic: `view-events`    │
             └────────────┬────────────┘
                          │
          ┌───────────────┴─────────────────────────────┐
          │ (Stream Consumer 1)                         │ (Stream Consumer 2)
          ▼                                             ▼
  ┌─────────────────────────────┐               ┌─────────────────────────────┐
  │ Counter Aggregation Workers │               │ Heavy Hitters Stream Engine │
  │ (In-memory batch buffer)    │               │ (Count-Min Sketch + MinHeap)│
  └──────────────┬──────────────┘               └──────────────┬──────────────┘
                 │                                             │
                 │ Flush aggregated delta (every 5s)           │ Queries Top-K items
                 ▼                                             ▼
  ┌─────────────────────────────┐               ┌─────────────────────────────┐
  │ Sharded Redis Counter Cache │               │ Top-K Snapshot Store        │
  │ key: `views:{item_id}:{0..9}`               │ key: `topk:trending:1h`     │
  └──────────────┬──────────────┘               └─────────────────────────────┘
                 │
                 │ Async Batch DB Flusher (every 30s)
                 ▼
  ┌─────────────────────────────┐
  │ Durable Analytics Database  │
  │ (ClickHouse / PostgreSQL)   │
  └─────────────────────────────┘
```

### End-to-End Data Flow

```
STEP 1: INGESTION & FRAUD FILTERING
  1. Client sends view ping: `{video_id: "v_101", user_id: "u_55", timestamp: 1718000}`.
  2. API Gateway passes event to Ingestion Service.
  3. Service queries a Redis Bloom Filter with key `seen:{video_id}:{user_id}`:
     - If exists: event is marked duplicate and discarded.
     - If new: added to Bloom Filter (24h TTL) and published to Kafka.

STEP 2: BUFFERED INCREMENTS & SHARDING
  1. Counter Aggregation Workers consume from Kafka.
  2. To avoid hammering Redis on hot viral items, workers aggregate increments in an
     in-memory local hash map for 2 seconds.
  3. Worker flushes the batch delta to Redis using sharded sub-counters:
     `INCRBY views:v_101:{hash(worker_id) % 10} 42`

STEP 3: READ SERVING & RECONCILIATION
  1. User loads video page: App queries Redis for `views:v_101:*`.
  2. Redis returns the 10 sub-counters via `MGET`; app sums them up in < 1ms.
  3. Every 30 seconds, an Async Flusher persists totals to ClickHouse/PostgreSQL.
```

---

## Section 5: Core Technical Deep Dives (Interview Focus)

### Deep Dive 1: Solving the Viral Hot-Key Bottleneck (Counter Sharding)

```
PROBLEM:
  A celebrity uploads a video. 100,000 users view it every second.
  If all 100,000 requests execute `INCR views:v_101` on Redis:
  → All 100,000 commands route to the SINGLE Redis node holding key `views:v_101`.
  → That node's single-threaded event loop pegs at 100% CPU, causing timeouts across the cluster!

SENIOR INTERVIEW SOLUTION (Counter Sharding):
  1. Split the single counter into M virtual shards (e.g., M = 10 or 20):
     `views:{video_id}:0`, `views:{video_id}:1`, ..., `views:{video_id}:9`
  2. Ingestion workers pick a random shard on increment:
     shard_id = rand() % 10
     redis.incrby(f"views:{video_id}:{shard_id}", count)
  3. When reading the total view count:
     Fetch all M shards using `MGET` and sum them:
     total = sum(redis.mget("views:{video_id}:0" ... "views:{video_id}:9"))
  4. Result: Traffic is evenly distributed across 10 independent Redis keys, eliminating hot spots!
```

### Deep Dive 2: Count-Min Sketch (Mathematical Mechanics)

```
WHAT IS A COUNT-MIN SKETCH?
  A 2D array of counters of width W and depth D, paired with D independent hash functions:
  h_1(x), h_2(x), ..., h_d(x).

      Column:    0      1      2     ...    W-1
    Row 0 (h0): [ 0 ][ 142 ][  0  ] ... [  12 ]
    Row 1 (h1): [ 5 ][  0  ][ 889 ] ... [   0 ]
    Row 2 (h2): [ 0 ][  0  ][ 142 ] ... [  31 ]
    ...
    Row D-1:    [ 12][ 210 ][  0  ] ... [   4 ]

HOW IT WORKS:
  1. Insertion (Item X):
     For each row i from 0 to D-1:
       col = h_i(X) % W
       table[i][col] += 1
  2. Query (Item X):
     The estimated count is the MINIMUM across all hashed positions:
     estimate(X) = min(table[0][h_0(X)%W], table[1][h_1(X)%W], ..., table[D-1][h_{D-1}(X)%W])

CRUCIAL INTERVIEW GUARANTEES:
  → One-Sided Error: The estimate is ALWAYS >= actual count (never underestimates).
    Because hash collisions only add to counter values, the minimum value is closest to reality.
  → Mathematical Sizing:
    Width  W = ceil(e / epsilon)      (controls error margin: error <= epsilon * N)
    Depth  D = ceil(ln(1 / delta))    (controls confidence: probability >= 1 - delta)
    For 0.1% error with 99.9% confidence: W = 2,718 columns, D = 7 rows.
    Total Memory: 2,718 * 7 * 4 bytes = ~76 KB! (Handles billions of events in tiny RAM).
```

### Deep Dive 3: Heavy Hitters Top-K (Space-Saving + Min-Heap)

```
PROBLEM:
  "Find the Top 100 trending hashtags on Twitter over the last hour."
  Storing exact counters for every single unique hashtag in memory requires Gigabytes of RAM.

STREAMING SOLUTION (Space-Saving Algorithm with Min-Heap of size K):
  1. Maintain an in-memory Min-Heap of size K (e.g. K = 100) storing `(hashtag, count, error)`.
  2. When a new hashtag arrives from the stream:
     a. Case 1: Hashtag is ALREADY in the heap:
        Increment its count and re-heapify (O(log K)).
     b. Case 2: Hashtag is NOT in the heap and heap has < K elements:
        Insert `(hashtag, 1, 0)` into heap.
     c. Case 3: Hashtag is NOT in the heap and heap is FULL:
        Find minimum element in heap: min_item with count C_min.
        Replace min_item with new hashtag, set count = C_min + 1, error = C_min.
  3. Space Complexity: Constant O(K) memory regardless of stream length!
```

### Deep Dive 4: Sliding Window Rate Limiter Counter

```
THE COMBINED SLIDING WINDOW ALGORITHM:
  Instead of expensive Redis Sorted Sets tracking every request timestamp:
  Maintain two fixed counters: Current Minute (`counter_curr`) and Previous Minute (`counter_prev`).

  Estimated requests in rolling 60s window:
    weight = (60 - current_seconds_into_minute) / 60
    estimated_count = (counter_prev * weight) + counter_curr

  If estimated_count > limit: Reject request with 429 Too Many Requests.
  Memory: Only 2 integers per user in Redis (sub-millisecond evaluation, zero unbounded growth).
```

---

## Section 6: API Design & Data Models

### 1. REST APIs

```http
POST /v1/views/record
Content-Type: application/json
{
  "item_id": "video_88a91b",
  "viewer_token": "usr_tok_4910",
  "watch_duration_seconds": 45,
  "client_timestamp": "2026-09-10T22:00:00Z"
}
Response: 202 Accepted

GET /v1/views/video_88a91b
Response: 200 OK
{
  "item_id": "video_88a91b",
  "view_count": 1428590,
  "last_synced_at": "2026-09-10T21:59:50Z"
}

GET /v1/analytics/heavy-hitters?window=1h&limit=10
Response: 200 OK
{
  "window": "1h",
  "items": [
    { "rank": 1, "item_id": "hashtag_worldcup", "estimated_count": 489200 },
    { "rank": 2, "item_id": "hashtag_olympics", "estimated_count": 312000 }
  ]
}
```

### 2. Database Schema (ClickHouse / PostgreSQL)

```sql
-- ClickHouse Engine for High-Throughput Append-Only Analytics
CREATE TABLE video_view_events (
    video_id String,
    viewer_id String,
    timestamp DateTime,
    ip_hash UInt64
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (video_id, timestamp);

-- Materialized View for Aggregated Totals
CREATE TABLE video_counter_snapshots (
    video_id String,
    total_views UInt64,
    updated_at DateTime
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY video_id;
```

---

## Section 7: Failure Modes & Self-Healing Resilience

```
╔═══════════════════════════════════════════════════════════════════════════════════════════╗
║ FAILURE SCENARIO         │ DETECTION                   │ MITIGATION & RECOVERY            ║
╠═══════════════════════════════════════════════════════════════════════════════════════════╣
║ Viral Hot-Key Hits       │ Redis shard CPU hits 100%   │ Dynamically enable counter       ║
║ Single Redis Key         │ on `video:{id}:views`       │ sharding into M sub-keys.        ║
╠═══════════════════════════════════════════════════════════════════════════════════════════╣
║ Stream Processing Worker │ Kafka consumer group lag    │ Rebalance Kafka partitions;      ║
║ Crashes (Flink/Worker)   │ spikes on view topic        │ resume from latest checkpoint.   ║
╠═══════════════════════════════════════════════════════════════════════════════════════════╣
║ Bot Network Replay Flood │ Sudden spike in view events │ Pass events through Bloom filter ║
║ Duplicate Fraud Views    │ with identical IP/fingerprt │ to discard 24h duplicate views.  ║
╠═══════════════════════════════════════════════════════════════════════════════════════════╣
║ Relational DB Connection │ High thread wait time on    │ Micro-batch writes in memory     ║
║ Pool Exhaustion on Flush │ UPDATE video_counters       │ and flush max 10 times/sec.      ║
╚═══════════════════════════════════════════════════════════════════════════════════════════╝
```

---

## Section 8: Interview Tradeoffs & Architecture Matrix

```
┌────────────────────────┬──────────────────────────┬───────────────────────────────┐
│ Counter Approach       │ Accuracy & Memory        │ Interview Recommendation      │
├────────────────────────┼──────────────────────────┼───────────────────────────────┤
│ Relational DB UPDATE   │ 100% Exact, O(N) Disk    │ Strict billing / financial    │
│ (PostgreSQL / MySQL)   │ Deadlocks > 2k QPS       │ balances only.                │
├────────────────────────┼──────────────────────────┼───────────────────────────────┤
│ Sharded Redis Counters │ 100% Exact, O(N) RAM     │ Viral video views, public ad  │
│ (Sub-keys: views:id:M) │ 50,000+ QPS, memory fast │ click counters (5-30s cache). │
├────────────────────────┼──────────────────────────┼───────────────────────────────┤
│ Count-Min Sketch       │ Probabilistic (<= +eps)  │ Heavy-hitter frequency filters│
│ (2D Hash Array)        │ Fixed ~76 KB RAM         │ and stream cardinality gating.│
├────────────────────────┼──────────────────────────┼───────────────────────────────┤
│ Space-Saving Min-Heap  │ Bounded Top-K list       │ Trending topics, top-100      │
│ (Size K Heap)          │ Fixed O(K) RAM           │ most active users/songs.      │
└────────────────────────┴──────────────────────────┴───────────────────────────────┘
```

---

## Section 9: Interview Scenario Practice (Test Yourself)

```
Q1: "Why can't we use a single Redis INCR for the YouTube view count of a viral music video?"
TALKING POINTS:
  → Single-core bottleneck: Redis is single-threaded per shard. 100k views/sec locks the core.
  → Solution: Counter Sharding across 10 keys (`views:{id}:{0..9}`). Ingestion writes to random
    shard; read queries execute `MGET` and sum.

Q2: "What is the primary difference between Count-Min Sketch and a Hash Map with counters?"
TALKING POINTS:
  → Bounded Memory: Hash map memory grows linearly O(N) with unique keys (millions of dollars).
    Count-Min Sketch has fixed O(W * D) memory (~76 KB) regardless of stream volume.
  → One-sided error: Count-Min Sketch can overestimate due to hash collisions, but NEVER
    underestimates.

Q3: "How do you prevent view count spam when bots send 5,000 view pings per second?"
TALKING POINTS:
  → Ingestion Gatekeeping: Check a rolling Redis Bloom Filter (24-hour TTL) keyed by
    `seen:{video_id}:{user_id_or_ip_fingerprint}`.
  → Duplicate pings within 24 hours are acknowledged with 202 Accepted but dropped before Kafka.

Q4: "How do you handle a temporary ClickHouse / Database outage without losing view counts?"
TALKING POINTS:
  → Buffer in Kafka: Kafka retains raw events for 7 days.
  → In-memory cache continues serving reads: Redis holds current aggregated numbers.
  → When ClickHouse recovers, the flusher replays from Kafka committed offsets.

Q5: "How does the Space-Saving algorithm guarantee that a true heavy hitter is never missed?"
TALKING POINTS:
  → If an item's true count exceeds N / (K + 1), it is mathematically guaranteed to reside in the
    Top-K heap. Any item below the threshold has bounded maximum over-estimation error.
```
