# Week 9, Topic 3: Design URL Shortener TinyURL

---

## Learning Objectives
```
╔═══════════════════════════════════════════════════════════════════════════════════╗
║   AFTER THIS MODULE, YOU WILL BE ABLE TO:                                         ║
╟───────────────────────────────────────────────────────────────────────────────────╢
║                                                                                   ║
║   1. Formulate high-read-throughput (100:1 read-to-write ratio) capacity sizing   ║
║      and low-latency redirection targets for a global URL shortening platform     ║
║                                                                                   ║
║   2. Architect collision-free short URL generation using Base62 encoding and      ║
║      distributed Key Generation Service (KGS) range leasing (etcd / ZooKeeper)    ║
║                                                                                   ║
║   3. Defend HTTP 301 (Moved Permanently) vs HTTP 302 (Found) redirection semantics║
║      weighing browser cache offload against real-time click analytics accuracy    ║
║                                                                                   ║
║   4. Protect backend datastores from cache penetration attacks via Redis Bloom    ║
║      filters and multi-tiered CDN edge caching                                    ║
║                                                                                   ║
║   5. Design partitioned NoSQL data models (Cassandra / DynamoDB) supporting custom║
║      vanity aliases, automatic TTL expirations, and streaming click telemetry     ║
╚═══════════════════════════════════════════════════════════════════════════════════╝
```

---

## Section 2: Wrong Mental Models (Destroy These First)

```
╔════════════════════════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Hash the long URL using MD5/SHA256 and truncate to 7 chars"        ║
╟────────────────────────────────────────────────────────────────────────────────────────╢
║   WRONG. Truncating cryptographic hashes causes frequent hash collisions. Resolving    ║
║   collisions requires expensive recursive database lookups or sequential salting.      ║
║   Production platforms use monotonic numeric IDs converted to Base62 strings.          ║
╠════════════════════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "Use a single central SQL auto-increment ID column"                 ║
╟────────────────────────────────────────────────────────────────────────────────────────╢
║   WRONG. A single database auto-increment sequence creates a catastrophic write        ║
║   bottleneck and single point of failure. Modern architectures use distributed ID      ║
║   generators or Key Generation Services (KGS) leasing pre-allocated integer ranges.    ║
╠════════════════════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "Always return HTTP 301 Moved Permanently for maximum speed"        ║
╟────────────────────────────────────────────────────────────────────────────────────────╢
║   WRONG. HTTP 301 instructs browsers to cache the redirect permanently on client       ║
║   disks. Subsequent clicks never touch your servers, completely blinding your analytics║
║   engine, preventing monetization, and disabling instant link expiration.              ║
╠════════════════════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "Hit the persistent database on every single redirect request"      ║
╟────────────────────────────────────────────────────────────────────────────────────────╢
║   WRONG. URL shorteners exhibit extreme read skew (99% reads, 1% writes). Querying     ║
║   the database for 100,000 req/sec will saturate connection pools and disk I/O.        ║
║   Multi-tier in-memory caching (CDN Edge + Redis) handles 95%+ of all redirect queries.║
╠════════════════════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Custom vanity aliases can be drawn from the standard KGS pool"     ║
╟────────────────────────────────────────────────────────────────────────────────────────╢
║   WRONG. Custom aliases (e.g. 'tinyurl.com/blackfriday') are arbitrary human words,    ║
║   not sequential integers. Custom aliases must bypass KGS and pass through dedicated   ║
║   uniqueness checks with reserved keyword protection (e.g. /api, /admin, /login).      ║
╚════════════════════════════════════════════════════════════════════════════════════════╝
```

---

## Section 3: Requirements & Sizing Calculations

### 1. Functional Requirements

```
FUNCTIONAL REQUIREMENTS (Interview Scope):
  P0 — Core Requirements:
    → Shorten URL: Generate a unique, compact short URL (7 characters) given a long URL.
    → High-Speed Redirection: Redirect short URL requests to the original long URL with < 15ms latency.
    → Custom Aliases: Allow users to specify custom vanity URLs (e.g., tinyurl.com/my-campaign).
    → Link Expiration (TTL): Support optional expiration timestamps after which links return 404/410.
    → High Availability: 99.99% availability for redirection endpoints (reads must never fail).

  P1 — Desirable Features:
    → Click Analytics: Track click counts, referrer sources, geographic locations, and user-agent devices.
    → Malicious Link Detection: Screen target URLs against Google Safe Browsing API.
```

### 2. Capacity Sizing (Back-of-the-Envelope)

| Metric Factor | Baseline Value | Peak Load (3x Surge) | 5-Year Requirement |
| :--- | :--- | :--- | :--- |
| **1. Write Volume (PUT)** | 1,000 new URLs/sec | ~3,000 new URLs/sec | ~158 Billion URLs (5 years) |
| **2. Read Volume (GET)** | 100,000 redirects/sec| ~300,000 redirects/sec| 100:1 Read-to-Write Ratio |
| **3. Ingress / Egress** | ~500 KB/s Write Ingress| ~50 MB/s Read Egress | Highly asymmetric network I/O|
| **4. Storage Footprint** | ~500 bytes per mapping | ~43.2 GB / day | ~79 Terabytes (5 years) |
| **5. Cache Memory (RAM)** | 20% of daily URLs (80/20)| ~8.64 GB RAM cache | Easily fits in 2 Redis nodes |

---

## Section 4: High-Level Design (HLD) Box-and-Arrow

```
                    DISTRIBUTED URL SHORTENER — ARCHITECTURE
                    ════════════════════════════════════════

   ┌────────────────────┐          ┌────────────────────┐
   │ Mobile / Web User  │          │ Enterprise API Bot │
   └─────────┬──────────┘          └─────────┬──────────┘
             │                               │
             └───────────────┬───────────────┘
                             │
            ┌────────────────┴───────────────────────────────┐
            │ (A) GET /{short_code} (Redirect: 99% traffic)  │ (B) POST /api/v1/urls (Shorten: 1%)
            ▼                                               ▼
   ┌─────────────────────────────────┐             ┌─────────────────────────────────┐
   │ Global CDN Edge Tier            │             │ API Gateway & Rate Limiter      │
   │ (Cloudflare / CloudFront)       │             │ - Token bucket per IP / API key │
   │ - Caches viral hot links        │             └───────────────┬─────────────────┘
   │ - Edge 302 Redirection (< 10ms) │                             │
   └─────────┬───────────────────────┘                             │
             │ (Cache Miss)                                        ▼
             ▼                                     ┌─────────────────────────────────┐
   ┌─────────────────────────────────┐             │ URL Shortener Write Service     │
   │ Redirection Read Service Fleet  │             │ - Validates URL & runs malware  │
   │ - High-throughput Go / Rust API │             │   screening (Safe Browsing)     │
   │ - Validates short_code format   │             │ - Leases token range from KGS   │
   └─────────┬───────────────────────┘             └───────────────┬─────────────────┘
             │                                                     │
             ├───────────────────────────────┐                     │
             ▼                               ▼                     │
   ┌───────────────────┐           ┌───────────────────┐           │
   │ Redis Bloom Filter│           │ Redis Cache Fleet │           │
   │ - Shields DB from │           │ - LRU Cache of    │           │
   │   invalid queries │           │   hot 20% URLs    │           │
   │   (0.1% FP rate)  │           │ - Sub-ms lookups  │           │
   └───────────────────┘           └─────────┬─────────┘           │
                                             │ (Cache Miss)        │
                                             ▼                     ▼
                                   ┌─────────────────────────────────┐
                                   │ Distributed NoSQL Datastore     │
                                   │ (Cassandra / DynamoDB / Scylla) │
                                   │ - Key: short_code (Hash Key)    │
                                   │ - Multi-region replication      │
                                   └─────────┬───────────────────────┘
                                             │
                                             │ (3) Async Telemetry Event
                                             ▼
   ┌─────────────────────────────────┐      ┌─────────────────────────────────┐
   │ Key Generation Service (KGS)    │      │ Kafka Clickstream Event Topic   │
   │ - Pre-allocates 1M token ranges │      │ - {short_code, ts, ip, geo, ua} │
   │ - Uses etcd for range leasing   │      └──────────────┬──────────────────┘
   └─────────────────────────────────┘                     │
                                                           ▼
                                            ┌─────────────────────────────────┐
                                            │ Analytics Aggregator Pipeline   │
                                            │ (ClickHouse / Druid OLAP)       │
                                            │ - Hourly/Daily click dashboards │
                                            └─────────────────────────────────┘
```

### End-to-End Execution Flow

```
STEP 1: SHORTEN URL (WRITE PATH)
  1. Client sends POST /api/v1/urls with `{"long_url": "https://example.com/very/long/path"}`.
  2. Write Service pulls the next available sequential integer from its local in-memory range buffer
     (e.g., 1048576, leased in bulk from KGS).
  3. Service encodes integer into Base62 string: `1048576 -> "4c2A"`.
  4. Writes mapping `{short_code: "4c2A", long_url: "...", created_at, ttl}` to DynamoDB.
  5. Populates Redis Bloom filter with "4c2A" and pre-warms Redis cache.
  6. Returns HTTP 201 Created with short URL `https://tinyurl.com/4c2A`.

STEP 2: REDIRECT URL (READ PATH)
  1. User clicks `https://tinyurl.com/4c2A`.
  2. Edge CDN checks cache; if miss, forwards to Redirection Service.
  3. Redirection Service queries Redis Bloom filter:
     - If Bloom filter returns FALSE: Link does NOT exist! Returns HTTP 404 immediately. Zero DB hit.
  4. Service checks Redis Cache:
     - If Hit: returns long_url directly in < 2ms.
  5. If Cache Miss: queries DynamoDB by primary key `short_code = "4c2A"`.
     - Writes long_url into Redis with TTL.
  6. Emits click tracking payload to Kafka topic `url.clicks` asynchronously.
  7. Returns HTTP 302 Found with `Location: https://example.com/very/long/path`.
```

---

## Section 5: Core Technical Deep Dives (Interview Focus)

### Deep Dive 1: Base62 Token Encoding & Combinatorics

```
WHY BASE62 (AND NOT BASE64 OR HEXADECIMAL)?
  - Characters used: [0-9] (10 digits) + [a-z] (26 lowercase) + [A-Z] (26 uppercase) = 62 characters.
  - Base64 includes '+' and '/' which have reserved syntactic meanings in URLs (require percent-encoding).
  - Hexadecimal (Base16) yields long, ugly strings ($16^7 \approx 268 \text{ Million}$ vs $62^7 \approx 3.5 \text{ Trillion}$).

THE COMBINATORIAL CAPACITY:
  $$\text{Capacity} = 62^L$$
  - Length 6: $62^6 \approx 56.8 \text{ Billion URLs}$
  - Length 7: $62^7 \approx 3,521,614,606,208 \text{ URLs (3.52 Trillion!)}$

SENIOR INTERVIEW CALCULATION:
  At 1,000 writes/second = 31.5 Billion URLs per year:
  $$3.52 \text{ Trillion} / 31.5 \text{ Billion} \approx 111.7 \text{ years of capacity!}$$
  A 7-character Base62 string provides more than a century of collision-free unique short codes.
```

### Deep Dive 2: Key Generation Service (KGS) & Range-Based Allocation

```
THE DISTRIBUTED ID COLLISION PROBLEM:
  - If multiple web servers generate random 7-character strings, collisions grow with the Birthday Paradox.
  - If web servers check the DB before inserting, write latency doubles and causes race conditions.

THE KGS RANGE-LEASING ARCHITECTURE:

   ┌──────────────────────────────────────┐
   │ Central Coordinator (etcd/ZooKeeper) │
   │ Global Counter: 5,000,000            │
   └──────────────────┬───────────────────┘
                      │
       ┌──────────────┴──────────────┐
       │ (Leases 1,000,000 ID blocks)│
       ▼                             ▼
  ┌────────────────────────┐    ┌────────────────────────┐
  │ Write Worker Node 1    │    │ Write Worker Node 2    │
  │ Current Range:         │    │ Current Range:         │
  │ [1,000,000 - 1,999,999]│    │ [2,000,000 - 2,999,999]│
  │ In-memory AtomicInteger│    │ In-memory AtomicInteger│
  └────────────────────────┘    └────────────────────────┘

WHY THIS IS 100% COLLISION-FREE AND ULTRA-FAST:
  1. No Inter-Server Coordination: Worker 1 increments its local AtomicInteger in RAM (< 10 nanoseconds).
  2. Zero Database Lookups: Worker 1 never queries the DB to check if an ID is already taken.
  3. Zero Collision Probability: Worker 1 and Worker 2 are mathematically guaranteed never to generate the same ID.
  4. Failure Tolerance: If Worker 1 crashes at ID 1,000,450, the remaining 999,550 tokens are lost.
     Losing 1 million IDs out of 3.5 Trillion represents only 0.000028% capacity loss—completely harmless!
```

### Deep Dive 3: HTTP 301 vs HTTP 302 Redirection Economics

```
┌─────────────────┬──────────────────────────────┬──────────────────────────────┐
│ Attribute       │ HTTP 301 (Moved Permanently) │ HTTP 302 (Found / Temporary) │
├─────────────────┼──────────────────────────────┼──────────────────────────────┤
│ Browser Caching │ Aggressively cached on disk  │ NOT cached by browser; every │
│ Behavior        │ Browser never asks server    │ click hits redirection server│
├─────────────────┼──────────────────────────────┼──────────────────────────────┤
│ Server Load     │ Lowest (zero server traffic  │ Higher (server processes all │
│ Impact          │ on subsequent clicks)        │ redirect requests)           │
├─────────────────┼──────────────────────────────┼──────────────────────────────┤
│ Analytics &     │ BROKEN: Cannot track clicks, │ ACCURATE: Captures 100% of   │
│ Telemetry       │ referrers, or timestamps     │ user click telemetry         │
├─────────────────┼──────────────────────────────┼──────────────────────────────┤
│ Link Revocation │ IMPOSSIBLE: Browser cache    │ INSTANT: Updates apply now   │
│ & Expiration    │ ignores server status change │ without waiting on cache TTL │
└─────────────────┴──────────────────────────────┴──────────────────────────────┘

SENIOR INTERVIEW RECOMMENDATION:
  "Always choose HTTP 302 (Found) or HTTP 307 (Temporary Redirect) for production URL shorteners.
   While HTTP 301 saves server bandwidth, it permanently caches the redirect in the client's browser.
   This blinds commercial click analytics, prevents monetization, and makes security revocation of
   phishing links impossible without clearing client browser history."
```

### Deep Dive 4: Redis Bloom Filter Cache-Penetration Shield

```
THE CACHE PENETRATION ATTACK:
  An attacker generates millions of random requests: `GET /tinyurl.com/badX9a`, `GET /tinyurl.com/badZ8c`...
  - None of these exist in Redis cache (Cache Miss).
  - Every request falls through to the persistent database (DynamoDB / Cassandra).
  - Result: DB read capacity is exhausted; legitimate users experience 504 Gateway Timeouts!

THE BLOOM FILTER SOLUTION:
  1. A Redis Bloom Filter (`BF.ADD` / `BF.EXISTS`) is maintained in memory.
  2. When a short URL is created, its `short_code` is added to the Bloom filter.
  3. When a redirect request arrives:
     - Check Bloom filter in memory (< 0.5ms).
     - If Bloom filter returns FALSE: The short code DEFINITIVELY does not exist.
       Immediately return HTTP 404! Zero database queries executed!
     - If Bloom filter returns TRUE: The short code PROBABLY exists (0.1% false positive).
       Proceed to Cache / Database lookup.
```

---

## Section 6: API Design & Data Models

### 1. REST Redirection & Shortening APIs

```http
POST /api/v1/urls
Content-Type: application/json
Authorization: Bearer <api_token>

{
  "long_url": "https://www.company.com/products/deals?utm_source=spring_sale",
  "custom_alias": "spring26",
  "ttl_days": 30
}
Response: 201 Created
{
  "short_url": "https://tinyurl.com/spring26",
  "short_code": "spring26",
  "expires_at": "2026-10-10T22:00:00Z"
}

GET /spring26
Host: tinyurl.com

Response: 302 Found
Location: https://www.company.com/products/deals?utm_source=spring_sale
Cache-Control: no-cache, no-store, must-revalidate
```

### 2. Database Schema (NoSQL Key-Value Store: DynamoDB / Cassandra)

```sql
-- Partitioned by short_code hash key for O(1) single-digit millisecond lookups
CREATE TABLE url_mappings (
    short_code VARCHAR(16) PRIMARY KEY, -- Hash Partition Key
    long_url TEXT NOT NULL,
    user_id UUID,
    is_custom BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL,
    expires_at TIMESTAMP,               -- Native DynamoDB TTL attribute
    click_count BIGINT DEFAULT 0
);

-- Reserved Custom Alias Table (Prevents collisions with system routes)
CREATE TABLE reserved_keywords (
    keyword VARCHAR(64) PRIMARY KEY,    -- 'api', 'admin', 'login', 'terms'
    reason VARCHAR(128)
);

-- Analytics Click Event Schema (ClickHouse OLAP Database)
CREATE TABLE click_events (
    short_code LowCardinality(String),
    clicked_at DateTime,
    ip_address IPv4,
    country_code LowCardinality(FixedString(2)),
    referrer String,
    user_agent String,
    device_type LowCardinality(String)
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(clicked_at)
ORDER BY (short_code, clicked_at);
```

---

## Section 7: Failure Modes & Self-Healing Resilience

```
╔════════════════════════════════════════════════════════════════════════════════════════════╗
║ FAILURE SCENARIO         │ DETECTION                   │ MITIGATION & RECOVERY             ║
╠════════════════════════════════════════════════════════════════════════════════════════════╣
║ KGS Worker Crashes       │ Heartbeat lease expires     │ Standby KGS instance acquires new ║
║ Mid-Range (Lost Tokens)  │ in etcd coordinator (> 5s)  │ range; unused lost keys skipped   ║
╠════════════════════════════════════════════════════════════════════════════════════════════╣
║ Cache Penetration Attack │ High volume of 404s hitting │ Redis Bloom filter rejects non-   ║
║ (Random short codes)     │ database directly           │ existent short codes in RAM (<1ms)║
╠════════════════════════════════════════════════════════════════════════════════════════════╣
║ Cache Stampede / Herd    │ Sudden spike in DB read     │ Mutex lock / Singleflight on cache║
║ (Viral link cache expiry)│ latency on single short_code│ miss; only 1 worker refreshes DB  ║
╠════════════════════════════════════════════════════════════════════════════════════════════╣
║ Phishing / Malware Link  │ Real-time threat feed match │ Redirect interstice page displays ║
║ Submitted By Malicious UI│ or user fraud reports       │ security warning; sets status 451 ║
╠════════════════════════════════════════════════════════════════════════════════════════════╣
║ Database Storage Growth  │ Disk utilization alarms     │ Automated TTL scrubber deletes    ║
║ Over Multiple Years      │ exceed 80% threshold        │ expired URLs; archives cold logs  ║
╚════════════════════════════════════════════════════════════════════════════════════════════╝
```

---

## Section 8: Interview Tradeoffs & Architecture Matrix

```
┌────────────────────────┬──────────────────────────┬───────────────────────────────┐
│ Design Area            │ Candidate Approaches     │ Production Recommendation     │
├────────────────────────┼──────────────────────────┼───────────────────────────────┤
│ ID Generation Strategy │ Hash Truncation vs DB    │ KGS Range Leasing. Completely │
│                        │ Auto-inc vs KGS Range    │ eliminates collision checks.  │
├────────────────────────┼──────────────────────────┼───────────────────────────────┤
│ Redirection HTTP Code  │ HTTP 301 Permanent vs    │ HTTP 302 / 307 Temporary.     │
│                        │ HTTP 302 Temporary       │ Enables accurate analytics.   │
├────────────────────────┼──────────────────────────┼───────────────────────────────┤
│ Primary Database       │ Relational PostgreSQL vs │ Distributed NoSQL KV Store.   │
│ Engine                 │ Partitioned NoSQL (Dynamo) Pure key lookups & auto-TTL.  │
├────────────────────────┼──────────────────────────┼───────────────────────────────┤
│ Cache Penetration      │ Cache Null Keys vs       │ Redis Bloom Filter in RAM.    │
│ Defense                │ In-Memory Bloom Filter   │ Blocks 99.9% of invalid keys. │
└────────────────────────┴──────────────────────────┴───────────────────────────────┘
```

---

## Section 9: Interview Scenario Practice (Test Yourself)

```
Q1: "Why is Base62 chosen over Base64 or Hexadecimal for URL shortening?"
TALKING POINTS:
  → Safe characters: Base62 uses [0-9a-zA-Z], which are fully URL-safe without escaping.
  → Base64 issues: Contains '+' and '/' which represent delimiters in URL query strings and paths.
  → Density: Base62 provides $62^7 pprox 3.5 	ext{ Trillion}$ combinations in only 7 characters,
    whereas Hexadecimal ($16^7 pprox 268 	ext{ Million}$) requires 11+ characters for the same scale.

Q2: "How does a Key Generation Service (KGS) eliminate collision checking in distributed environments?"
TALKING POINTS:
  → Central coordinator (etcd) hands out contiguous integer ranges (e.g. 1M IDs) to write workers.
  → Each worker dispenses IDs locally in RAM using an atomic counter (`AtomicLong`).
  → No worker ever shares or overlaps ranges with another worker.
  → Zero database lookups are needed to verify uniqueness, achieving sub-millisecond write latencies.

Q3: "Why should an enterprise URL shortener use HTTP 302 instead of HTTP 301?"
TALKING POINTS:
  → Browser caching: 301 causes browsers to cache the destination indefinitely on client devices.
  → Loss of analytics: Subsequent clicks from that device never touch the server, breaking click metrics.
  → Inability to update: If a destination URL changes or needs security suspension, 301 cached clients cannot be redirected.

Q4: "How do you protect your database when an attacker floods 10,000 non-existent short codes per second?"
TALKING POINTS:
  → Attack analysis: Non-existent keys cause 100% cache misses, driving all queries directly to the database.
  → Bloom filter: Maintain a Redis Bloom filter containing all valid generated short codes.
  → Early exit: If the Bloom filter returns false, return 404 immediately without touching the database.
  → Cache nulls: For the 0.1% false positives, cache `short_code -> NULL` in Redis for 60 seconds.

Q5: "How do you handle custom vanity aliases (e.g. tiny.co/summer-sale) without breaking KGS?"
TALKING POINTS:
  → Distinct code path: Custom aliases bypass the KGS integer sequence entirely.
  → Reserved check: Verify the alias is not in a reserved keywords table (e.g., 'admin', 'api', 'help').
  → Conditional write: Insert into NoSQL using conditional write (`attribute_not_exists(short_code)`).
  → If alias exists, return 409 Conflict; otherwise write mapping and populate Bloom filter.
```
