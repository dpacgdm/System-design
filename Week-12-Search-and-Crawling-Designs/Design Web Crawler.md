
# Design Web Crawler

> Week 12, Topic 2 — System Design. Distributed web crawling at search-engine scale:
> politeness, URL frontier, layered dedup, Bloom filter math, and AWS fleet operations.
> Connects to Week 12 Design Google Search (crawl is subsystem 1 of 5).

Same teaching contract as CDN Fundamentals: ASCII diagrams, production numbers,
AWS deployment sketches, and incident-driven learning.


---

## Learning Objectives

```
╔══════════════════════════════════════════════════════════════════════╗
║ AFTER THIS TOPIC, YOU WILL BE ABLE TO:                               ║
║                                                                      ║
║ 1. Design a distributed crawler: seed → normalize → dedup →          ║
║    frontier → fetch → parse → store → re-enqueue                     ║
║                                                                      ║
║ 2. Implement politeness: robots.txt (RFC 9309), token buckets,       ║
║    per-host concurrency, exponential backoff                         ║
║                                                                      ║
║ 3. Architect URL frontier: per-host priority queues, work stealing,  ║
║    revisit scheduling, crawl budget allocation                       ║
║                                                                      ║
║ 4. Build layered dedup: normalization, canonical URLs, Bloom math    ║
║    (m, n, k, p), exact stores, SimHash near-duplicate detection      ║
║                                                                      ║
║ 5. Operate crawl fleets on AWS: ECS, SQS, S3, DynamoDB, Redis        ║
║    with host-consistent hashing, leases, crawl generations           ║
║                                                                      ║
║ 6. Diagnose crawl incidents: traps, skew, robots violations,         ║
║    dedup leaks, frontier starvation, blocklist events                ║
╚══════════════════════════════════════════════════════════════════════╝
```


---

## Wrong Mental Models (Destroy These First)


```
╔════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╗
║ MENTAL MODEL #1: "Crawler = wget in a loop"                                                                                                                                                ║
║                                                                                                                                                                                            ║
║ WRONG. wget is single-threaded and stateless. Production crawlers are distributed schedulers with terabyte-scale dedup stores and per-host politeness enforced across thousands of workers.║
╚════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╝
```


```
╔════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╗
║ MENTAL MODEL #2: "Fetch faster = better crawler"                                                                                   ║
║                                                                                                                                    ║
║ WRONG. Throughput is capped by host politeness, not NIC speed. Fast on one host = blocked. Fast across millions of hosts = correct.║
╚════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╝
```


```
╔════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╗
║ MENTAL MODEL #3: "Bloom filter = exact dedup"                                                                                              ║
║                                                                                                                                            ║
║ WRONG. Blooms have false positives. They skip the exact-store lookup for definite negatives only. False positives silently drop fresh URLs.║
╚════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╝
```


```
╔════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╗
║ MENTAL MODEL #4: "One global URL queue"                                                                                ║
║                                                                                                                        ║
║ WRONG. Single heap causes hot-host starvation and politeness leaks. Use per-host queues + global round-robin scheduler.║
╚════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╝
```


```
╔═══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╗
║ MENTAL MODEL #5: "robots.txt is optional"                                                                                 ║
║                                                                                                                           ║
║ WRONG. RFC 9309 is the contract. Violations → blocks, lawsuits, reputational damage. Cache, refresh, audit every decision.║
╚═══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╝
```


```
╔═════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╗
║ MENTAL MODEL #6: "Dedup once, never revisit"                                                                                        ║
║                                                                                                                                     ║
║ WRONG. Pages change. Revisit scheduling re-enqueues by freshness, PageRank, and Last-Modified. Dedup is per-generation, not forever.║
╚═════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╝
```



---

## Core Teaching — Crawler Architecture



### Why Web Crawlers Exist

```
THE FUNDAMENTAL PROBLEM
━━━━━━━━━━━━━━━━━━━━━━━

  Web scale (2024 order-of-magnitude):
    → ~2B pages indexed by major engines; ~50B+ URLs exist
    → Tens of millions of new/changed pages per day
    → Link graph small-world diameter ~19 hops

  Systems that need crawlers:
    → Search engines (Google, Bing)
    → Archival (Internet Archive, Common Crawl)
    → Price/inventory monitors
    → SEO audit tools
    → Security scanners (attack surface discovery)
    → LLM training data pipelines

  The crawler pipeline:
    DISCOVER → NORMALIZE → DEDUP → SCHEDULE → FETCH → PARSE → STORE → REPEAT

  Downstream systems (index, rank, alert) are useless without reliable crawl.
```


### End-to-End Architecture

```
DISTRIBUTED CRAWLER — COMPONENT DIAGRAM
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

                    ┌─────────────────┐
                    │  Seed injectors │
                    │  Sitemaps, RSS  │
                    └────────┬────────┘
                             ▼
              ┌──────────────────────────────┐
              │     URL NORMALIZER           │
              └──────────────┬───────────────┘
                             ▼
              ┌──────────────────────────────┐
              │  DEDUP L1: Bloom (in-RAM)    │
              └──────────────┬───────────────┘
                             ▼
              ┌──────────────────────────────┐
              │  DEDUP L2: DynamoDB exact    │
              └──────────────┬───────────────┘
                             ▼
              ┌──────────────────────────────┐
              │  FRONTIER: per-host queues   │
              └──────────────┬───────────────┘
            ┌────────────────┼────────────────┐
            ▼                ▼                ▼
      ┌──────────┐    ┌──────────┐    ┌──────────┐
      │ Fetcher  │    │ Fetcher  │    │ Fetcher  │
      │  ECS 1   │    │  ECS 2   │    │  ECS N   │
      └────┬─────┘    └────┬─────┘    └────┬─────┘
           └───────────────┼───────────────┘
                           ▼
              ┌──────────────────────────────┐
              │  Parse → SimHash → S3 → index│
              └──────────────────────────────┘
```


### Part A: Politeness

Politeness is the product. Speed without politeness ends the crawl — blocked IPs,
legal exposure, and poisoned relationships with major origins.

```
POLITENESS STACK — ALL SIX LAYERS REQUIRED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. robots.txt compliance (RFC 9309)
  2. Per-host request rate (token bucket)
  3. Per-host concurrency cap (semaphore)
  4. Exponential backoff on 429/503/timeout
  5. Global fleet budget (max aggregate RPS)
  6. Identifiable User-Agent with contact URL + abuse@ email
```


#### robots.txt — Parsing, Caching, Enforcement

```
RFC 9309 ROBOTS EXCLUSION PROTOCOL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

FETCH:
  URL: https://{host}/robots.txt (site root only)
  2xx → parse and cache
  401/403/404 → no restrictions (allow all paths)
  5xx → use stale cache; if none, allow but retry robots in 1h

PARSING RULES:
  User-agent: MyBot
  Disallow: /private/
  Allow: /private/stats/     ← Allow wins when both match same prefix
  Crawl-delay: 2             ← non-standard; Bing/Google ignore; respect anyway
  Sitemap: https://x.com/sitemap.xml

  Longest matching prefix wins within a User-agent block.
  Order: exact bot name → * wildcard → implicit allow.

CACHE (Redis + DynamoDB):
  Key: robots:{host}
  TTL: 24h default; invalidate on robots 404→200 transition
  NEVER fetch robots on every page — doubles traffic to small sites

ENFORCEMENT (before dequeue):
  if path disallowed for our User-agent:
    skip fetch; metric robots_skip_total++; retain for audit log

PRODUCTION BUG THAT KILLS TEAMS:
  Case-sensitive path matching errors.
  Disallow: /API/  vs actual path /api/v1 → accidental crawl of blocked paths.
  Normalize paths to lowercase ONLY if origin is case-insensitive (dangerous).
  Safer: match robots paths literally; normalize crawl URLs separately.
```


#### Rate Limiting — Token Buckets Per Host

```
TOKEN BUCKET (per host, Redis-backed)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  State:
    rate:{host} → { tokens: float, last_refill_ms: int }

  Defaults (when robots silent):
    rate = 1.0 req/s
    burst = 2

  Acquire:
    elapsed = now_ms - last_refill_ms
    tokens = min(burst, tokens + elapsed * rate / 1000)
    if tokens >= 1.0:
      tokens -= 1.0; GRANT
    else:
      requeue with delay_ms = (1.0 - tokens) / rate * 1000

  Crawl-delay: 2 → rate = 0.5 req/s

DISTRIBUTED ROUTING:
  Host H always maps to Redis shard via consistent hash.
  Prevents two workers from double-spending tokens.

WORKED EXAMPLE — retailer.com during Black Friday:
  Config: rate=1/s, burst=2, fleet=500 fetchers
  Bug: all 500 fetchers hit same host (frontier skew)
  Effective rate: 500 req/s → WAF block in 30 seconds
  Fix: per-host queue + global scheduler ensures ≤ burst concurrent
```


#### Per-Host Concurrency Limits

```
CONCURRENCY ≠ RATE
━━━━━━━━━━━━━━━━━━

  8 requests at t=0, idle 7s → average 1 req/s but 8 concurrent TCP connections.
  Origins and WAFs detect concurrency patterns, not just averages.

  Redis: concurrency:{host} (INCR/DECR)
  Default max: 1 (conservative), hard cap 2 in code

  Order of acquisition:
    1. Concurrency slot
    2. Rate token
    3. robots check (cached)
    4. HTTP fetch
    5. Release concurrency in finally block

  DEPLOY GUARDRAIL:
    Feature flag max_concurrent_per_host cannot exceed 2 without SRE approval.
    The "perf fix" that caused the retailer.com incident (1→8) bypassed this.
```


#### Exponential Backoff

```
BACKOFF TABLE
━━━━━━━━━━━━━

  403         → pause host 3600s; page on-call if >5% of host fetches
  429         → Retry-After header OR 60×2^attempt seconds (max 3600)
  5xx         → 30, 60, 120, 300, 600, 3600 (with jitter)
  timeout     → same as 5xx
  conn refused→ pause 900s (host may be down)

  State: backoff:{host} → { until_ts, consecutive_errors }

  During backoff: scheduler skips host; URLs stay queued (not dropped).

  JITTER: delay += random(0, delay/4) — prevents synchronized retry storms.
```


### Part B: URL Frontier

The frontier is the heart of the crawler — a distributed priority scheduling system
that decides *which URL to fetch next* across millions of hosts.

```
FRONTIER DESIGN GOALS
━━━━━━━━━━━━━━━━━━━━━

  1. High-priority URLs fetched first (sitemaps, high PageRank, fresh)
  2. No host receives more than its politeness budget
  3. No host starves the global queue (fairness across hosts)
  4. Worker failure loses zero URLs (durable queues + leases)
  5. Revisit URLs re-enter with correct priority decay
```


#### Per-Host Priority Queues

```
TWO-LEVEL QUEUE ARCHITECTURE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Level 1: Global scheduler heap
    Entry: (next_eligible_ts, host_id)
    Picks host whose politeness window is open

  Level 2: Per-host priority queue
    Entry: (priority_score, url, enqueue_ts)
    Lower score = higher priority

  SCHEDULER LOOP (each fetcher):
    1. Pop host H from global heap where next_eligible_ts <= now
    2. Pop highest-priority URL from queue[H]
    3. Acquire rate token for H
    4. Fetch URL
    5. Push H back to global heap with next_eligible_ts = now + inter_request_delay

  PRIORITY SCORE FORMULA (typical):
    score = depth_penalty + age_penalty - inlink_score - freshness_boost

    depth_penalty    = depth × 1000        (BFS bias)
    age_penalty      = hours_since_enqueue × 10
    inlink_score     = log(inlink_count) × 500
    freshness_boost  = -10000 if from sitemap lastmod < 24h

  WHY NOT ONE GLOBAL HEAP:
    Single heap of 10B URLs → impossible in RAM.
    Per-host queues shard naturally; hot host only affects its shard.
```


#### Work Stealing Across Fetchers

```
WORK STEALING — WHEN IDLE WORKERS HELP BUSY SHARDS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Problem: host-consistent assignment creates skew.
    news.site.com has 10M URLs; obscure.blog has 3.
    Worker assigned to news.site is saturated; worker on obscure.blog is idle.

  Solution: lease-based work stealing
    1. Each URL dequeue acquires lease (url, worker_id, expiry_ts)
    2. Lease TTL: 120s (fetch timeout + parse buffer)
    3. Idle worker scans stealable hosts (same region, under politeness cap)
    4. Steals batch of up to 10 URLs with new lease

  STEAL CONSTRAINTS:
    → Never steal from host in backoff
    → Never exceed global per-host concurrency (stealer checks Redis)
    → Stolen URLs keep original host for rate limiting

  AWS IMPLEMENTATION:
    Primary: SQS per-host queues (or partitioned by host hash)
    Stealing: worker polls neighboring partitions when own queue empty >5s
    Lease: DynamoDB conditional update on url_lease table

  METRICS:
    crawl_steal_total{from_shard, to_worker}
    crawl_idle_worker_seconds
    Alert: idle_worker_seconds p95 > 60 → frontier imbalance
```


#### Revisit Scheduling

```
REVISIT — PAGES CHANGE; DEDUP IS NOT FOREVER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  After successful fetch, compute next_crawl_ts:

  POLICIES (Cho & Garcia-Molina):
    Uniform:     next = now + fixed_interval
    Proportional: interval ∝ 1/change_rate
    Exponential: interval doubles if unchanged, halves if changed

  PRODUCTION HYBRID:
    if Last-Modified unchanged AND content_hash unchanged:
      next_crawl = now + min(current_interval × 2, max_interval)
    else:
      next_crawl = now + min_interval

    Bounds: min=1 day, max=90 days for generic web
    High PageRank: min=1 hour, max=7 days

  STORAGE:
    DynamoDB: url_state → { last_fetch, next_crawl, change_rate, content_hash }

  RE-ENQUEUE:
    Cron/worker scans next_crawl < now → push to frontier with revisit priority
    Revisit priority < discovery priority (fresh URLs win during budget crunch)

  CRAWL GENERATION:
    generation_id increments weekly/monthly for full recrawl sweeps
    Dedup bloom reset per generation; exact store keyed by (url, generation)
```


### Part C: Dedup and URL Normalization

Duplicate URLs waste fetch budget, storage, and index capacity. Dedup starts before
the frontier — every duplicate rejected early saves a politeness token.

```
DEDUP PIPELINE (in order)
━━━━━━━━━━━━━━━━━━━━━━━━━

  1. Syntax normalization (cheap, deterministic)
  2. Canonical URL resolution (rel=canonical, redirects)
  3. Bloom filter L1 (RAM, per shard)
  4. Exact store L2 (DynamoDB/RocksDB)
  5. Content fingerprint post-fetch (SimHash for near-dup)
```


#### URL Normalization Rules

```
NORMALIZATION CHECKLIST
━━━━━━━━━━━━━━━━━━━━━━━

  Scheme:      http → https if port 443 reachable (configurable)
  Host:        lowercase; punycode for IDN; strip www. if config says so
  Port:        remove default (:80, :443)
  Path:        decode %encoding; resolve . and ..; merge duplicate slashes
  Query:       sort params; remove tracking (utm_*, fbclid, gclid)
  Fragment:    strip #anchor (not sent to server)
  Default path: add / if empty

TRAP DETECTION (reject or cap):
  Calendar traps:  /archive/2024/01/01 ... infinite dates
  Session traps:   ?sessionid=random (infinite param space)
  Pagination caps: max depth 100 for ?page=N patterns
  Binary traps:    .zip, .exe unless explicitly allowed

EXAMPLE:
  HTTP://WWW.Example.COM:80/a/../a?b=2&a=1&utm_source=x#frag
  → https://example.com/a?a=1&b=2

  Collisions if too aggressive:
    example.com/page vs example.com/Page (case-sensitive servers)
  → Maintain host-level case_sensitivity flag learned from 404 patterns
```


#### Canonical URLs

```
CANONICAL RESOLUTION
━━━━━━━━━━━━━━━━━━━━

  Sources (priority order):
    1. HTTP 301/308 redirect target (permanent)
    2. <link rel="canonical" href="..."> in HTML
    3. Normalized URL itself

  Store mapping: alias_url → canonical_url in DynamoDB
  Fetch canonical once; alias URLs skip fetch if canonical seen.

  REDIRECT CHAINS:
    Max hops: 5
    Loop detection: visited set in redirect follower
    302/307: do NOT update canonical (temporary)

  DUPLICATE CONTENT CLUSTERS:
    /product/123?utm=email
    /product/123?utm=social
    /product/123/
    → all map to canonical /product/123
```


#### SimHash Near-Duplicate Detection

```
SIMHASH — NEAR-DUP AT CONTENT LEVEL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  URL dedup catches identical URLs.
  SimHash catches: mirror sites, scraped content, template boilerplate.

  ALGORITHM (Charikar 2002):
    1. Tokenize page text (shingles: 3-word windows)
    2. Hash each shingle to 64-bit
    3. For each bit position: +1 if hash bit=1, else -1
    4. Final signature: bit i = 1 if score[i] > 0

  SIMILARITY:
    hamming_distance(simhash_a, simhash_b) ≤ 3 → near duplicate (typical threshold)

  STORAGE:
    LSH buckets: split 64-bit hash into 4 × 16-bit bands
    Query buckets for candidates; verify hamming distance

  ACTION ON NEAR-DUP:
    Skip index update; optionally store alias pointer
    Do NOT skip link extraction (links may differ)

  FALSE POSITIVES:
    Short pages (<200 tokens) → unreliable SimHash; require exact match

  AWS:
    SimHash computed in ECS parser task
    Signatures in DynamoDB (canonical_url → simhash)
    LSH index in Redis or custom RocksDB CF
```


### Part D: Bloom Filters — Math and Layered Dedup

Bloom filters are probabilistic membership structures that trade false positives
for massive memory savings. They are the first gate in layered dedup.

```
WHY BLOOM FILTERS IN CRAWLERS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Exact dedup of 100B URLs × 16 bytes hash = 1.6 TB minimum
  Bloom at 10 bits/element × 100B = 125 GB (fits in distributed RAM)

  Bloom says:
    "Definitely NOT seen" → proceed to exact store (fast path ~99.9%)
    "MAYBE seen" → check exact store (slow path)

  False positive: Bloom says maybe seen → exact store says no → FETCH ANYWAY
  False negative: IMPOSSIBLE (never skip a URL that wasn't inserted)
```


#### Bloom Filter Mathematics

```
PARAMETERS
━━━━━━━━━━

  m = number of bits in bitmap
  n = number of elements inserted
  k = number of hash functions
  p = false positive probability

OPTIMAL k:
  k = (m/n) × ln(2) ≈ 0.693 × (m/n)

OPTIMAL m for target p:
  m = -n × ln(p) / (ln(2))²

  For p = 0.01 (1%):  m ≈ 9.6 bits/element
  For p = 0.001:      m ≈ 14.4 bits/element
  For p = 0.0001:     m ≈ 19.2 bits/element

FALSE POSITIVE RATE (after n inserts):
  p ≈ (1 - e^(-kn/m))^k

WORKED EXAMPLE:
  n = 1 billion URLs per crawl generation
  Target p = 0.001 (0.1%)

  m = -10^9 × ln(0.001) / (ln(2))²
    = -10^9 × (-6.908) / 0.480
    ≈ 14.4 × 10^9 bits
    ≈ 1.8 GB per generation shard

  k = (14.4/1) × 0.693 ≈ 10 hash functions

  At p=0.001: 1M false positives per billion checks
  → 1M unnecessary exact-store lookups (cheap)
  → 0 false negatives (correct)

COST OF FALSE POSITIVES:
  Each FP skips a never-seen URL → PERMANENT content loss for generation
  Production target: p ≤ 0.0001 for main crawl; p ≤ 0.01 for recrawl shards
```


#### Hash Functions and Bitmap Sizing

```
IMPLEMENTATION DETAILS
━━━━━━━━━━━━━━━━━━━━

  Hash functions (k=10):
    Use double hashing: h_i(x) = (h1(x) + i×h2(x)) mod m
    h1, h2 = murmur3 or xxhash of URL bytes

  Bitmap storage:
    Sharded by url_hash mod num_shards
    Each shard: in-memory RoaringBitmap or raw bit array
    Persist snapshot to S3 every 15 min for recovery

  INSERT (on URL accepted to frontier):
    for i in 0..k-1: bitmap.set(h_i(url) mod m)

  CHECK (on URL discovery):
    for i in 0..k-1:
      if not bitmap.test(h_i(url) mod m): return DEFINITELY_NEW
    return MAYBE_SEEN → check DynamoDB

  COUNTING BLOOM (for deletions — rarely used in crawl):
    4-bit counters instead of bits; supports delete
    Crawl generations prefer fresh bloom over counting (simpler)
```


#### Layered Dedup Architecture

```
THREE-LAYER DEDUP
━━━━━━━━━━━━━━━━━

  Layer 0: In-process LRU (1M URLs, hot path dedup within worker)
  Layer 1: Bloom filter shard (10 bits/elem, in RAM)
  Layer 2: DynamoDB conditional put (url_hash → seen_ts, generation)

  FLOW:
    URL → L0 hit? → drop
        → L1 miss? → L2 conditional put (if new → frontier)
        → L1 hit  → L2 get (if exists → drop; else → frontier + bloom insert)

  GENERATION ROLLOVER:
    Weekly: new bloom shard; old archived to S3
    Exact store: TTL or generation partition key
    URLs from prior generation may be re-fetched (revisit policy)

  METRICS:
    dedup_l0_hit_rate
    dedup_bloom_maybe_rate (should ≈ p + true_hit_rate)
    dedup_exact_reject_rate
    dedup_false_positive_estimate (maybe - exact_hit)
```


```
BLOOM SIZING: Small crawl shard
━━━━━━━━━━━━━━━━━━━━━━━━
  n = 1,000,000 URLs
  p = 0.01 false positive rate

  m = 9,585,058 bits = 1.20 MB (0.001 GB)
  k = 6.6 hash functions (round to 7)

  At saturation: ~1.00% of NEW urls falsely rejected
  At 10M checks/day: ~100,000 false positives/day

  ⚠ TOO HIGH — content loss unacceptable
```


```
BLOOM SIZING: Billion-URL generation
━━━━━━━━━━━━━━━━━━━━━━━━
  n = 1,000,000,000 URLs
  p = 0.001 false positive rate

  m = 14,377,587,566 bits = 1797.20 MB (1.797 GB)
  k = 10.0 hash functions (round to 10)

  At saturation: ~0.10% of NEW urls falsely rejected
  At 10M checks/day: ~10,000 false positives/day

  ✓ Acceptable for production
```


```
BLOOM SIZING: Google-scale generation
━━━━━━━━━━━━━━━━━━━━━━━━
  n = 100,000,000,000 URLs
  p = 0.0001 false positive rate

  m = 1,917,011,675,473 bits = 239626.46 MB (239.626 GB)
  k = 13.3 hash functions (round to 13)

  At saturation: ~0.01% of NEW urls falsely rejected
  At 10M checks/day: ~1,000 false positives/day

  ✓ Acceptable for production
```


```
BLOOM SIZING: UNDERSIZED — anti-pattern
━━━━━━━━━━━━━━━━━━━━━━━━
  n = 10,000,000 URLs
  p = 0.05 false positive rate

  m = 62,352,242 bits = 7.79 MB (0.008 GB)
  k = 4.3 hash functions (round to 4)

  At saturation: ~5.00% of NEW urls falsely rejected
  At 10M checks/day: ~500,000 false positives/day

  ⚠ TOO HIGH — content loss unacceptable
```


### Part E: Distributed Crawl Coordination

Single-machine crawlers hit RAM, disk, and politeness walls around 100–500 req/s.
Production systems partition work across hundreds of fetchers with strict coordination.

```
COORDINATION REQUIREMENTS
━━━━━━━━━━━━━━━━━━━━━━━━━

  1. Same URL never fetched twice concurrently (leases)
  2. Same host never exceeds politeness budget (host-consistent state)
  3. Worker death → URL returns to frontier (lease expiry)
  4. Fleet deploy → no duplicate work storm (graceful drain)
  5. Crawl generation rollover → clean dedup boundary
```


#### Host-Consistent Hashing

```
HOST-CONSISTENT HASHING
━━━━━━━━━━━━━━━━━━━━━━━

  Problem: which worker owns host H's politeness state and queue?

  Ring: hash(host) → position on 0..2^32 ring
  Workers claim arc segments; host H owned by worker W = successor(hash(H))

  On worker add/remove: only hosts in moved arcs rebalance (minimal disruption)

  REDIS CLUSTER MAPPING:
    Same hash routes rate:{host}, concurrency:{host}, queue:{host}
    to same Redis slot → single-writer per host politeness

  SQS PARTITIONING:
    queue_name = crawl-frontier-{hash(host) mod 256}
    256 queues × N consumers with steal-from-neighbor

  VS URL-CONSISTENT HASHING:
    URL-consistent: bad — hot URL creates hot worker
    Host-consistent: good — politeness naturally per-host
```


#### Leases and Exactly-Once Fetch Intent

```
LEASE PROTOCOL
━━━━━━━━━━━━━━

  DynamoDB table: url_leases
    PK: url_hash
    attrs: worker_id, lease_until, generation, status

  Dequeue:
    TransactWrite: Put lease if not exists OR lease expired
    Conditional: attribute_not_exists OR lease_until < now

  Heartbeat: extend lease every 30s during long fetch/parse
  Complete: delete lease; update url_state with fetch result
  Fail: lease expires → reaper returns URL to frontier

  LEASE TTL: 120s default (tune to p99 fetch + parse latency × 2)

  DUPLICATE FETCH PREVENTION:
    Two workers cannot hold valid lease on same URL
    At-most-once fetch intent; at-least-once storage (S3 overwrite ok)
```


#### Crawl Generations

```
CRAWL GENERATIONS
━━━━━━━━━━━━━━━━━

  generation_id: monotonic integer (or date stamp 20250706)

  Purpose:
    → Reset Bloom filters without unbounded growth
    → Full recrawl sweeps ("refresh entire index")
    → A/B crawl policy experiments

  ROLLOVER PROCEDURE:
    1. Create generation N+1 bloom shards (empty)
    2. Dual-write: new URLs go to both N and N+1 blooms (24h overlap)
    3. Switch dedup reads to N+1
    4. Archive generation N bloom to S3 Glacier
    5. Purge exact store entries where generation < N-1 (retain 2)

  REVISIT vs GENERATION:
    Revisit re-fetches within same generation if next_crawl elapsed
    Generation bump forces re-fetch even if recently seen

  AWS:
    generation_id in SQS message attributes
    S3 prefix: s3://crawl-raw/{generation}/{host}/{url_hash}.html
    DynamoDB GSI on generation for progress dashboards
```


### AWS Deployment Architecture

```
AWS CRAWL FLEET — REFERENCE ARCHITECTURE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
  │ Seed Lambda │     │ Sitemap     │     │ Admin API   │
  │ (scheduled) │     │ ingest SQS  │     │ (manual)    │
  └──────┬──────┘     └──────┬──────┘     └──────┬──────┘
         └───────────────────┼───────────────────┘
                             ▼
                    ┌─────────────────┐
                    │ Normalizer ECS  │
                    │ (stateless)     │
                    └────────┬────────┘
                             ▼
                    ┌─────────────────┐
                    │ Dedup Lambda    │
                    │ Bloom local +   │
                    │ DDB conditional │
                    └────────┬────────┘
                             ▼
         ┌───────────────────┴───────────────────┐
         ▼                   ▼                   ▼
  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
  │ SQS frontier│    │ SQS frontier│    │ SQS frontier│
  │ shard 0     │    │ shard 1     │    │ shard 255   │
  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘
         └───────────────────┼───────────────────┘
                             ▼
                    ┌─────────────────┐
                    │ Fetcher ECS     │
                    │ Fargate fleet   │
                    │ 100-5000 tasks  │
                    └────────┬────────┘
                             ▼
         ┌───────────────────┼───────────────────┐
         ▼                   ▼                   ▼
  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
  │ S3 raw HTML │    │ ElastiCache │    │ DynamoDB    │
  │ + lifecycle │    │ Redis       │    │ url_state   │
  └─────────────┘    │ robots/rate │    │ url_leases  │
                     └─────────────┘    └─────────────┘

COST LEVERS:
  → S3 Intelligent-Tiering for raw crawl (access drops after index)
  → Fargate Spot for fetchers (interruptible; lease handles retry)
  → DynamoDB on-demand for spiky enqueue; provisioned for steady revisit
  → ElastiCache r6g for Redis (memory-bound politeness state)

OBSERVABILITY:
  CloudWatch: crawl_fetch_total, crawl_error_rate, frontier_depth
  X-Ray: trace URL from seed → S3
  Alarms: frontier_depth > 24h drain time; 403_rate > 5%
```


### Crawl Budget Allocation

```
CRAWL BUDGET — FINITE FETCHES, INFINITE WEB
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Total budget: 50M fetches/day (example mid-size engine)

  Allocation strategy:
    Tier 1 (40%): High PageRank + fresh sitemap URLs
    Tier 2 (30%): Revisit schedule (changed pages)
    Tier 3 (20%): Discovery (new links from crawled pages)
    Tier 4 (10%):  Experimental / long-tail / recrawl generation

  ENFORCEMENT:
    Token bucket at tier level in scheduler
    When Tier 1 exhausts daily quota → spill to next day, not steal from Tier 3

  METRICS:
    crawl_budget_used{tier} / crawl_budget_limit{tier}
    Alert: Tier 1 <80% utilized by 20:00 UTC → discovery starvation upstream
```

### URL Trap Catalog

```
URL TRAPS — DETECT AND NEUTRALIZE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


  Calendar trap:
    Pattern: /event/{year}/{month}/{day}
    Fix: Cap date range ±1 year from now


  Session trap:
    Pattern: ?sessionid={random}
    Fix: Strip session params; max 1 fetch per path template


  Pagination trap:
    Pattern: ?page={n}
    Fix: Cap page≤100; detect last page via empty result


  Crawl space trap:
    Pattern: /product/{id}/reviews?page={n}
    Fix: Combine pagination + ID enumeration limits


  Infinite redirect:
    Pattern: A→B→A
    Fix: Max 5 hops; loop detection in redirect follower


  Soft 404 trap:
    Pattern: 200 OK with empty body
    Fix: Detect via content length <500B + boilerplate SimHash


  Mirror trap:
    Pattern: identical content, different domains
    Fix: SimHash cluster; fetch one canonical


  Faceted search:
    Pattern: ?color=red&size=M&...
    Fix: Max 3 query params; strip faceted combinations


```


### HTTP Fetch Layer — Production Details

```
FETCHER IMPLEMENTATION
━━━━━━━━━━━━━━━━━━━━━━

  Connection pooling: max 1 idle conn per host (respect concurrency)
  TLS: session resumption; SNI required; cert validation ON
  Timeouts: connect 5s, TTFB 15s, total 30s
  Redirects: follow max 5; preserve cookies only if same registrable domain
  Compression: Accept-Encoding: gzip, br
  Conditional GET: If-Modified-Since / If-None-Match on revisits
    304 → skip S3 write; update next_crawl only

  USER-AGENT:
    MyBot/1.0 (+https://example.com/bot; abuse@example.com)

  RESPONSE HANDLING:
    2xx → parse
    3xx → redirect module
    4xx → log; 404 removes from revisit (optional)
    5xx → backoff
    non-HTML → store but skip link extract (pdf, img capped)

  SIZE LIMIT: abort >5MB unless allowlist (robots, sitemap)
```


### DynamoDB Schema Reference

```
TABLE: crawl_url_state
━━━━━━━━━━━━━━━━━━━━

  PK: url_hash (S) — SHA256 of normalized URL
  attrs:
    canonical_url (S)
    first_seen (N) — epoch ms
    last_fetch (N)
    next_crawl (N)
    fetch_count (N)
    content_hash (S)
    simhash (N)
    generation (N)
    status (S) — active|robots_blocked|quarantined

  GSI1: next_crawl-index — for revisit scanner
  GSI2: generation-status-index — progress dashboards

TABLE: url_leases
  PK: url_hash
  attrs: worker_id, lease_until, generation

  TTL on lease_until for automatic cleanup

TABLE: robots_cache
  PK: host
  attrs: body, fetched_at, etag, ttl
```


### Redis Key Catalog

```
REDIS KEYS (host-consistent shard)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  rate:{host}              → HASH {tokens, last_refill_ms}
  concurrency:{host}       → INT
  backoff:{host}           → HASH {until_ts, errors, last_status}
  robots:{host}            → STRING (serialized rules JSON)
  quarantine:{url_hash}    → STRING with TTL 86400
  frontier_seq:{host}      → INT monotonic for FIFO tie-break

  MEMORY ESTIMATE:
    10M active hosts × 500 bytes avg = 5 GB
    Plan ElastiCache cluster mode with 3 shards
```


### Interview Walkthrough — 45 Minute Crawler Design

```
MINUTE 0-5: CLARIFY
  → Scale: 1B pages? 10M/day fetch budget?
  → Politeness: must comply robots? (yes)
  → Storage: raw HTML or extracted text?
  → Freshness: revisit frequency?

MINUTE 5-15: HIGH-LEVEL
  Draw: seed → normalize → dedup → frontier → fetcher → S3 → indexer
  Emphasize per-host politeness as first-class

MINUTE 15-25: DEEP DIVE (interviewer picks)
  Frontier: per-host queues + scheduler
  Dedup: Bloom sizing with numbers
  Distributed: leases + host-consistent hash

MINUTE 25-35: SCALE AND FAILURE
  Bloom 10 bits × 1B URLs = 1.25 GB
  Worker death → lease expiry
  Crawler trap → detection rules

MINUTE 35-45: OPS AND EVOLUTION
  Crawl generations
  Metrics and alerts
  "What if retailer blocks us?" → incident response
```


### Global Scheduler — Pseudocode

```
SCHEDULER MAIN LOOP (runs every 100ms per fetcher cluster)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  eligible_hosts = redis.zrangebyscore("global_schedule", 0, now_ms, limit=100)

  for host in eligible_hosts:
    if redis.exists(f"backoff:{host}"):
      continue

    url_entry = redis.zpopmin(f"frontier:{host}")
    if not url_entry:
      continue

    if not acquire_rate_token(host):
      redis.zadd(f"frontier:{host}", url_entry)  // requeue
      redis.zadd("global_schedule", host, now_ms + retry_delay)
      continue

    if not acquire_concurrency(host):
      redis.zadd(f"frontier:{host}", url_entry)
      continue

    if not robots_allows(host, url_entry.path):
      mark_skipped(url_entry)
      continue

    dispatch_to_fetcher(url_entry, host)
    next_eligible = now_ms + inter_request_ms(host)
    redis.zadd("global_schedule", host, next_eligible)

  // Work stealing branch (if idle > 5s)
  if fetcher_idle():
    steal_from_neighbor_shard(max_urls=10)
```

### SQS Message Schema

```
FRONTIER MESSAGE (JSON)
━━━━━━━━━━━━━━━━━━━━━━━

  {
    "url": "https://example.com/products/123",
    "normalized_url_hash": "sha256:abc...",
    "host": "example.com",
    "priority": 4500,
    "depth": 3,
    "discovered_from": "https://example.com/catalog",
    "enqueue_ts": 1720234567890,
    "generation": 20250706,
    "revisit": false,
    "sitemap_lastmod": "2025-07-05T12:00:00Z"
  }

  Attributes:
    HostHash: String — for FIFO ordering per host (if using FIFO queues)

  Visibility timeout: 120s (matches lease TTL)
  DLQ after 5 receives → poison pill investigation
```

### Monitoring Dashboard Panels

```
GRAFANA DASHBOARD: CRAWL-FLEET-OVERVIEW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Row 1 — Throughput:
    crawl_fetch_total (rate, by status)
    crawl_bytes_downloaded (rate)
    crawl_parse_duration_ms (histogram)

  Row 2 — Health:
    crawl_error_rate (403, 429, 5xx stacked)
    frontier_depth (by shard, top 10)
    dedup_reject_rate (bloom vs exact)

  Row 3 — Politeness:
    rate_token_wait_ms (p99 by host tier)
    hosts_in_backoff (count)
    robots_skip_total (rate)

  Row 4 — Capacity:
    ecs_fetcher_running_count
    sqs_approximate_messages_visible (by shard)
    redis_memory_usage_percent

  ALERTS (PagerDuty):
    P1: crawl_error_rate > 20% for 5 min
    P1: robots_violation_total > 0 (should never fire)
    P2: frontier_depth growth > 1M/hour sustained
    P2: dedup_fp_estimate > 0.1%
    P3: idle_worker_seconds p95 > 120
```

### Legal, Ethics, and Compliance

```
CRAWL COMPLIANCE CHECKLIST
━━━━━━━━━━━━━━━━━━━━━━━━━━━

  □ robots.txt enforced for every fetch
  □ Terms of Service reviewed for target domains (especially e-commerce)
  □ User-Agent identifies bot with contact URL
  □ abuse@ mailbox monitored (<24h response SLA)
  □ PII handling: do not index logged-in pages, session cookies
  □ GDPR: right to erasure → URL blocklist propagation to all generations
  □ CFAA (US): respect access controls; credentials only with authorization
  □ Rate limits documented in partner contracts

  hiQ v. LinkedIn (2022): scraping public data has limits;
  authenticated/scoped access remains contractual.

  WHEN IN DOUBT: slower crawl + legal review > fast crawl + lawsuit
```

### Link Extraction and URL Discovery

```
PARSER PIPELINE
━━━━━━━━━━━━━━━

  Input: raw HTML bytes from S3
  Steps:
    1. Charset detection (Content-Type header > meta charset)
    2. HTML parse (streaming parser for large pages)
    3. Extract:
       - <a href>
       - <link rel="alternate"> (feeds)
       - <img src> (optional image crawl)
       - canonical link
       - meta refresh
    4. Resolve relative URLs against base href
    5. Filter: same-domain policy if configured
    6. Normalize → dedup pipeline

  JAVASCRIPT RENDERING:
    Default: OFF (10× cost, bot detection risk)
    Enable: headless Chrome pool for allowlisted domains only
    AWS: separate ECS service with GPU-less burstable tasks

  SITEMAP PARSING:
    XML sitemap index → recursive fetch
    Priority and lastmod boost frontier score
    news:news sitemap for freshness tier
```

### Capacity Planning Worksheet

```
WORKED CAPACITY EXAMPLE
━━━━━━━━━━━━━━━━━━━━━━━

  Target: 20M fetches/day

  Fetches/sec average: 20M / 86400 ≈ 231 RPS
  Peak (3× average): ~700 RPS

  Fetcher task: 5 RPS sustainable (HTTP + parse + enqueue)
  Tasks needed: 700 / 5 = 140 fetcher tasks (+ 30% headroom) ≈ 182 tasks

  S3 writes: 20M × 50KB avg = 1 TB/day raw HTML
  Monthly S3: ~30 TB → Intelligent-Tiering ~$600-800/month

  DynamoDB: 20M conditional writes/day = 231 WCU sustained
  On-demand: ~$25/day for writes + reads for revisit scanner

  Redis: 2M active hosts × 500B = 1 GB politeness state

  SQS: 20M messages/day; 256 shards = 78K msg/shard/day (trivial)

  Bloom: 5B cumulative URLs × 10 bits = 6.25 GB across 5 shards
```


### Mercator Architecture Lessons (Google, 1999–present)

```
MERCATOR CRAWLER — HISTORICAL FOUNDATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Heydon & Najork built Mercator at Google as the reference scalable crawler.
  Key ideas still used everywhere:

  1. URL SEEN TEST before enqueue (dedup at discovery, not fetch)
  2. Per-host queues with global scheduler (not one priority queue)
  3. Pluggable URL filter chain (robots, traps, domain policy)
  4. Separate fetcher and indexer processes (pipeline decoupling)
  5. Checksum-based content change detection

  EVOLUTION 1999 → 2025:
    Single datacenter → multi-region anycast egress
    In-memory URL set → Bloom + Bigtable/DynamoDB
    Synchronous fetch → lease-based async with SQS/Kafka
    PageRank in crawl priority → hundreds of freshness/quality signals

  READ THE PAPER before claiming "I'd just use Kafka for everything."
  Kafka moves bytes; Mercator answers *what* bytes to move and *when*.
```


### Token Bucket vs Leaky Bucket vs Fixed Window

```
RATE LIMIT ALGORITHM COMPARISON
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ┌──────────────┬────────────────────────────────────────────────────┐
  │ Algorithm    │ Crawler fit                                        │
  ├──────────────┼────────────────────────────────────────────────────┤
  │ Token bucket │ BEST — allows controlled burst (2 quick requests   │
  │              │ then idle); matches origin connection patterns     │
  ├──────────────┼────────────────────────────────────────────────────┤
  │ Leaky bucket │ OK — smooth output rate; no burst; feels sluggish  │
  │              │ for sitemap ingestion spikes                       │
  ├──────────────┼────────────────────────────────────────────────────┤
  │ Fixed window │ BAD — 999 req at 00:59.999 + 999 at 01:00 = burst  │
  │              │ WAF trigger; never use for politeness               │
  ├──────────────┼────────────────────────────────────────────────────┤
  │ Sliding log  │ Precise but O(n) memory per host; 10M hosts = costly │
  └──────────────┴────────────────────────────────────────────────────┘

  IMPLEMENTATION NOTE:
    Token bucket in Redis uses Lua script for atomic refill+acquire.
    Race without Lua: two workers both see tokens=1, both fetch → 2× rate.
```


### SimHash — Step-by-Step Worked Example

```
SIMHASH WALKTHROUGH (simplified 8-bit; production uses 64-bit)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Document A tokens: ["quick", "brown", "fox"]
  Document B tokens: ["quick", "brown", "dog"]

  Shingle hashes ( pretend 8-bit ):
    "quick" → 10110101
    "brown" → 11001010
    "fox"   → 01110011
    "dog"   → 10011100

  For Doc A, bit scores:
    bit7: +1+1-1 = +1 → 1
    bit6: +1-1+1 = +1 → 1
    ... aggregate → signature_A = 11101011

  signature_B differs in fox/dog token hashes
  Hamming distance = 3 → near duplicate if threshold ≥3

  PRODUCTION:
    64-bit signatures; threshold 3-5 depending on vertical
    News: stricter (3) — duplicate articles common
    Product: looser (5) — spec sheets share boilerplate
```


### URL Normalization — Edge Cases

```
NORMALIZATION EDGE CASES THAT BREAK NAIVE IMPLEMENTATIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  CASE 1: IDN homograph attack
    https://аррIe.com (Cyrillic) vs https://apple.com
    → Punycode normalize: xn--...
    → Optional: reject mixed-script domains

  CASE 2: Default port in redirect chain
    http://example.com:80 → https://example.com (no port)
    → Both must hash to same canonical after normalization

  CASE 3: Trailing slash semantics
    example.com/foo vs example.com/foo/
    → Server may 301 one to other; learn from redirect, don't assume

  CASE 4: Case-sensitive paths (Linux origins)
    /Page vs /page — different resources
    → Do NOT lowercase path without host-specific rule

  CASE 5: Empty query vs no query
    /search vs /search?
    → Normalize to identical form (strip empty query)

  CASE 6: Repeated parameters
    ?a=1&a=2 → preserve order or sort? RFC: server-dependent
    → Pick one policy; document; never flip mid-generation

  TEST SUITE: maintain 500+ normalization unit tests from production bugs
```


### robots.txt — Real-World Examples

```
ROBOTS.TXT PATTERNS FROM LIVE SITES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  PATTERN A — Block all except sitemap (paywall sites):
    User-agent: *
    Disallow: /
    Allow: /sitemap.xml
    → Your crawler indexes nothing unless contract allows

  PATTERN B — Aggressive AI bot blocking (2024+ trend):
    User-agent: GPTBot
    Disallow: /
    User-agent: Googlebot
    Allow: /
    → Match YOUR bot name exactly; don't assume * covers you

  PATTERN C — Crawl-delay (Bing respects, Google ignores):
    User-agent: *
    Crawl-delay: 10
    → Set rate = 0.1 req/s for compliance

  PATTERN D — Wildcard paths:
    Disallow: /*.pdf$
    Disallow: /temp/
    → Implement glob matching per RFC 9309

  FETCH FREQUENCY:
    Cache 24h; re-fetch on 404→200; honor Cache-Control: max-age on robots
```


### Distributed Fetcher Fleet — ECS Task Design

```
ECS FARGATE FETCHER TASK
━━━━━━━━━━━━━━━━━━━━━━

  Task definition:
    CPU: 512 (0.5 vCPU)
    Memory: 1024 MB
    Network: awsvpc (one ENI per task for egress diversity)

  Container:
    Image: crawl-fetcher:20250706
    Environment:
      SQS_SHARD_ID: from task slot
      REDIS_CLUSTER: crawl-redis.xxx
      GENERATION: 20250706
    Secrets: none (no credentials in crawl for public web)

  Lifecycle:
    SIGTERM → stop dequeuing; finish in-flight (max 120s); exit 0

  Auto Scaling:
    Metric: SQS ApproximateNumberOfMessagesVisible (cluster aggregate)
    Target: 1000 messages per task
    Scale out: +50 tasks/min; scale in: -10 tasks/min (slow drain)

  SPOT STRATEGY:
    70% Fargate Spot + 30% On-Demand
    Spot interruption → task SIGTERM → lease expires → retry
```


### S3 Raw Storage Layout and Lifecycle

```
S3 KEY LAYOUT
━━━━━━━━━━━━━

  s3://crawl-raw-prod/
    {generation}/
      {host_hash[:2]}/
        {host}/
          {url_hash}.html.gz
          {url_hash}.meta.json

  meta.json:
    {
      "url": "https://...",
      "status": 200,
      "headers": {"content-type": "text/html", "last-modified": "..."},
      "fetch_ts": 1720234567890,
      "worker_id": "ecs-task/abc",
      "content_length": 48291,
      "simhash": "0x1a2b3c4d5e6f7089"
    }

  LIFECYCLE:
    Day 0-30: S3 Standard (indexer re-reads)
    Day 30-90: Intelligent-Tiering
    Day 90+: Glacier Instant Retrieval (compliance/debug)
    Delete: generation < N-2 after index confirmation
```


### Revisit Policy — Numerical Simulation

```
REVISIT SIMULATION — NEWS SITE VS STATIC BLOG
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  News site: changes 80% of pages daily
    min_interval = 1 hour
    After unchanged fetch: interval × 2 (cap 6 hours for news)
    Fetches/page/week ≈ 28-40

  Static blog: changes 2% monthly
    min_interval = 1 day
    After unchanged: interval × 2 (cap 90 days)
    Fetches/page/year ≈ 4-6

  CRAWL BUDGET IMPACT:
    100K news URLs × 30 fetches/month = 3M fetches
    100K blog URLs × 0.5 fetches/month = 50K fetches
    → News consumes 98% of revisit budget for equal URL count
    → Tier allocation prevents blog starvation (see crawl budget)
```


### Host-Consistent Hashing — Ring Diagram

```
CONSISTENT HASH RING (conceptual)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

         0
         │
    W3 ──┼── W1
         │
    W2 ──┴── (hash space)

  hash("cnn.com")     → near W1 → W1 owns cnn.com politeness
  hash(" obscure.io") → near W2

  ADD W4:
    Only hosts between W3 and W4 move from W3 to W4
    ~25% rebalance for 4 workers (not 100%)

  VIRTUAL NODES:
    Each physical worker has 100 virtual points on ring
    Reduces load variance when worker count is small
```


### Crawl Generation Migration Runbook

```
GENERATION ROLLOVER RUNBOOK — WEEKLY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  T-7d:  Provision generation N+1 infrastructure (empty blooms)
  T-1d:  Dual-write blooms (insert into N and N+1)
  T-0:   Flip read path to N+1 primary
  T+1h:  Monitor dedup_fp_estimate and fetch_duplicate_rate
  T+24h: Stop writes to generation N bloom
  T+48h: Snapshot N bloom to S3 Glacier
  T+7d:  Archive S3 prefix generation N-2

  ROLLBACK TRIGGERS:
    dedup_fp_estimate > 0.5% for 15 min
    fetch_total drops >20% (false positive storm skipping URLs)

  COMMUNICATION:
    #crawl-platform Slack; index team on standby for recrawl needs
```

### Additional Production Patterns


#### Dynamic politeness from server signals

```
Parse Retry-After, X-RateLimit-Remaining headers
Adapt token bucket rate dynamically (floor: robots/Crawl-delay)
Store learned rate in Redis rate:{host}:learned_cap
```


#### Domain-level circuit breaker

```
5 consecutive 503 → open circuit 30 min for domain
Half-open: 1 probe request; success → close; fail → extend
Separate from host-level (CDN may route domains to same IP)
```


#### Sitemap-priority injection lane

```
Dedicated SQS queue for sitemap URLs bypasses BFS depth penalty
Rate still host-limited; priority boost only in scheduler
Prevents new product pages waiting behind pagination traps
```


#### Cross-region crawl with geo-affinity

```
Fetch from us-east-1 for .com US-heavy hosts
Route via host TLD heuristics + RTT probes
Reduces origin latency; politeness unchanged (same host view)
```


#### Content-type aware fetch budget

```
HTML: full fetch + parse
PDF: fetch only if allowlist; max 10MB
Images: skip unless image search vertical
Saves 40% bandwidth on mixed-content sites
```



### Failure Deep Dive — Duplicate Fetch Storm

```
DUPLICATE FETCH STORM
━━━━━━━━━━━━━━━━━━━━━

  TRIGGER: Bloom shard lost on restart without S3 snapshot recovery
  EFFECT: All URLs in shard appear "new" → thundering herd to exact store
  DynamoDB throttling → conditional write retries → enqueue duplicates
  Same URL fetched 10-50× concurrently before leases stabilize

  SIGNATURE:
    fetch_total 5× baseline
    dynamodb_throttled_requests spike
    duplicate_content_s3_keys (same url_hash, different fetch_ts)

  FIX:
    Immediate: pause enqueue from affected shard
    Restore bloom from latest S3 snapshot
    Run dedup compaction job on exact store (merge by url_hash)

  PREVENT:
    Bloom snapshot every 5 min; verify snapshot age on startup
    Startup gate: refuse dequeue until bloom loaded OR exact-only mode
```


### Failure Deep Dive — Infinite Subdomain Trap

```
SUBDOMAIN ENUMERATION TRAP
━━━━━━━━━━━━━━━━━━━━━━━━

  ATTACK PATTERN: links to a1.example.com, a2.example.com, ... a999999.example.com
  Each subdomain treated as separate host → separate politeness bucket
  Effective parallelism: 1 req/s × 1M subdomains = 1M req/s aggregate

  DETECT:
    Unique subdomain count per registrable domain > 1000/hour
    Wildcard DNS *.example.com returning same content (SimHash identical)

  FIX:
    Collapse to registrable domain (eTLD+1) for politeness when wildcard detected
    Cap subdomain discovery at 100 per eTLD+1 per generation
    Public suffix list (PSL) for domain extraction — use mozilla/gecko PSL
```


### Crawler vs Scraper vs Indexer

```
ROLE SEPARATION
━━━━━━━━━━━━━━━

  ┌────────────┬─────────────────┬──────────────────┬─────────────────┐
  │ Component  │ Input           │ Output           │ Scale bottleneck│
  ├────────────┼─────────────────┼──────────────────┼─────────────────┤
  │ Crawler    │ URLs            │ Raw bytes + links│ Politeness      │
  │ Parser     │ Raw HTML        │ Structured docs  │ CPU per page    │
  │ Indexer    │ Parsed docs     │ Inverted index   │ Token throughput│
  │ Scraper    │ Specific pages  │ Extracted fields │ Anti-bot        │
  └────────────┴─────────────────┴──────────────────┴─────────────────┘

  Interview tip: "Design a web crawler" ≠ "Design Google Search"
  Stop at S3 + parsed document schema unless asked to continue
```

### Frequently Asked Questions

```
CRAWLER FAQ
━━━━━━━━━━━━━━━━━━━━


  Q: Why not use Kafka as the frontier?
  A: Kafka lacks per-key priority ordering at scale without complex partitioning. SQS + Redis scheduler is simpler for host-fair scheduling.


  Q: Why Bloom instead of HyperLogLog?
  A: HLL estimates cardinality; cannot test membership. Need exact 'seen this URL' test.


  Q: Why not crawl with headless Chrome everywhere?
  A: 10× cost, 5× slower, triggers bot detection. Use for JS-render allowlist only.


  Q: How handle infinite scroll sites?
  A: API discovery via network tab patterns; or accept incomplete crawl for that vertical.


  Q: Can I ignore robots for 'public' data?
  A: Legal risk. robots + ToS + CFAA. Consult legal.


  Q: How dedup across crawl generations?
  A: Generation in PK; bloom reset; exact store retains 2 generations.


```


### Extended Hands-On — Build a Mini-Crawler

```
MINI-CRAWLER PROJECT (8-10 hours)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Scope: BFS crawl single domain, max 1000 pages, polite 1 req/s

  Components:
    1. normalize.py — URL normalization with tests
    2. robots.py — fetch and parse robots.txt
    3. frontier.py — heapq priority queue per host
    4. bloom.py — Bloom filter with configurable m, k
    5. fetcher.py — httpx async with token bucket
    6. main.py — orchestrate; output JSONL to disk

  Stretch goals:
    - SimHash near-dup skip
    - Sitemap seed ingestion
    - Export metrics to Prometheus

  Evaluation rubric:
    □ Zero robots violations on test domain
    □ No duplicate URL fetches (verify log)
    □ Handles 302 redirects correctly
    □ Survives Ctrl+C with resume from checkpoint
```


### Anti-Bot and WAF Interaction

```
ORIGIN DEFENSES YOUR CRAWLER TRIGGERS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Signal                    │ Crawler mistake
  ──────────────────────────┼────────────────────────────────────
  High concurrent conn/host │ Concurrency >2
  Request regularity        │ Fixed interval (no jitter)
  Missing browser headers   │ No Accept-Language, Accept
  Datacenter IP ASN         │ AWS/GCP egress (use partner allowlist)
  TLS fingerprint           │ Go/Java http client vs Chrome
  Honeypot links            │ Follow hidden <a display:none>

  LEGITIMATE MITIGATIONS:
    Partner allowlist (IP or signed header)
    Registered bot User-Agent with verification file
    Crawl during off-peak windows contracted with origin

  DO NOT:
    Rotate residential proxies to evade blocks
    Spoof Chrome TLS fingerprint without authorization
    Solve CAPTCHAs automatically on blocked pages
```


### Metrics Catalog

```
PROMETHEUS METRICS (crawl_* prefix)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  crawl_fetch_total{host,status,generation}
  crawl_fetch_duration_seconds{host} — histogram
  crawl_fetch_bytes{host}
  crawl_robots_skip_total{host,reason}
  crawl_dedup_bloom_hit_total{result=new|maybe}
  crawl_dedup_exact_reject_total
  crawl_frontier_depth{shard}
  crawl_frontier_enqueue_total{host,priority_tier}
  crawl_lease_acquire_total{result=ok|contention}
  crawl_lease_reaper_reenqueue_total
  crawl_backoff_hosts_active
  crawl_rate_token_wait_seconds{host}
  crawl_simhash_near_dup_total
  crawl_trap_reject_total{trap_type}
  crawl_s3_write_total{result=ok|fail}
  crawl_parse_links_discovered{host}
```


### Security — SSRF and Crawler Abuse

```
SSRF RISKS IN CRAWLERS
━━━━━━━━━━━━━━━━━━━━━━

  Malicious seed URL: http://169.254.169.254/latest/meta-data/
  Crawler fetches → IAM credential leak on AWS

  DEFENSES:
    Block private IP ranges (10/8, 172.16/12, 192.168/16, 169.254/16)
    Block localhost, file://, gopher://
    Resolve DNS before fetch; reject if A record is private
    Egress proxy with network ACL for fetcher subnets

  MALICIOUS SEEDS:
    Validate seed sources; audit manual seed API
    Rate limit seed injection per operator
```


### Handoff to Indexer

```
CRAWL → INDEX CONTRACT
━━━━━━━━━━━━━━━━━━━━━━

  Indexer consumes S3 event (SQS notification):
    ObjectCreated on *.html.gz → index-lambda or index-ecs

  Message:
    {
      "s3_key": "...",
      "url": "...",
      "canonical_url": "...",
      "simhash": "...",
      "fetch_ts": ...,
      "generation": ...
    }

  Idempotency: index by (canonical_url, content_hash)
  Skip if simhash near-dup cluster already indexed

  BACKPRESSURE:
    If index lag > 1 hour: slow frontier dequeue (not stop fetch)
    Raw storage is cheap; index lag loses freshness not data
```


### Priority Score Tuning — A/B Experiments

```
PRIORITY FORMULA EXPERIMENTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Baseline score (lower = sooner fetch):
    S = 1000×depth - 500×log(inlinks) - freshness_bonus + age_hours×5

  Experiment A — freshness-heavy (news vertical):
    freshness_bonus = 20000 if sitemap_lastmod < 6h else 0
    Result: 40% faster index of breaking news; 15% blog starvation → rejected

  Experiment B — inlink-heavy (PageRank proxy):
    S = 1000×depth - 2000×log(inlinks)
    Result: better head coverage; missed long-tail discovery → hybrid adopted

  Experiment C — depth cap only:
    S = depth (pure BFS)
    Result: trap-sensitive; infinite calendar consumed budget in 6 hours

  PRODUCTION: hybrid with tier budgets (see Crawl Budget Allocation)
  Rollout: 1% of hosts for 48h; compare index freshness SLI by host tier
```

### WARC Format and Common Crawl Interop

```
WARC (Web ARChive) RECORD TYPES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  warcinfo  — crawl metadata (software, date)
  request   — HTTP request headers sent
  response  — HTTP response headers + body
  metadata  — annotations (duplicate detection)

  Common Crawl publishes WARC segments on S3:
    s3://commoncrawl/crawl-data/CC-MAIN-2024-10/segments/...

  Use case: train LLM on web text without operating crawl fleet
  Limitation: monthly snapshots; not real-time

  Your crawler output compatibility:
    Optional WARC writer alongside S3 gzip HTML
    Enables archival compliance and third-party audit
```

### Comparison — Self-Hosted vs Managed Crawl Services

```
BUILD VS BUY
━━━━━━━━━━━━

  ┌────────────────────┬─────────────────────┬─────────────────────────┐
  │ Factor             │ Self-hosted (AWS)   │ Managed (Bright Data,   │
  │                    │                     │ Zyte, Firecrawl)        │
  ├────────────────────┼─────────────────────┼─────────────────────────┤
  │ Politeness control │ Full                │ Opaque                  │
  │ Cost at 10M/day    │ ~$2-5K/mo infra     │ ~$10-50K/mo usage-based │
  │ Custom dedup       │ Full                │ Limited                 │
  │ Legal liability    │ Yours               │ Shared                  │
  │ JS rendering       │ You operate         │ Often included          │
  │ Best for           │ Search, archive     │ Ad-hoc extraction       │
  └────────────────────┴─────────────────────┴─────────────────────────┘

  System design interviews assume self-hosted with explicit politeness math.
```

### State Machine — URL Lifecycle

```
URL STATE MACHINE
━━━━━━━━━━━━━━━━━

      ┌─────────┐
      │ SEEDED  │
      └────┬────┘
           │ normalize ok
           ▼
      ┌─────────┐     bloom+exact dup    ┌────────┐
      │ QUEUED  │ ──────────────────────►│ DROPPED│
      └────┬────┘                        └────────┘
           │ lease acquired
           ▼
      ┌─────────┐     robots deny        ┌──────────────┐
      │ FETCHING│ ──────────────────────►│ROBOTS_BLOCKED│
      └────┬────┘                        └──────────────┘
           │ 200 + parse
           ▼
      ┌─────────┐     simhash dup        ┌────────────┐
      │ STORED  │ ──────────────────────►│ NEAR_DUP   │
      └────┬────┘                        └────────────┘
           │ revisit timer
           ▼
      ┌─────────┐
      │ QUEUED  │ (revisit priority)
      └─────────┘

  Terminal states: DROPPED, ROBOTS_BLOCKED (unless policy changes)
  Metrics at each transition for funnel analysis
```

### Glossary

```
CRAWLER GLOSSARY
━━━━━━━━━━━━━━━━

  Frontier       — Priority queue system of URLs waiting to be fetched
  Politeness     — Rate and concurrency limits per host
  Crawl budget   — Maximum fetches allocated per time period
  Generation     — Versioned crawl sweep with fresh dedup bloom
  Lease          — Time-limited claim preventing duplicate fetch
  eTLD+1         — Effective top-level domain + one label (registrable domain)
  SimHash        — Locality-sensitive hash for near-duplicate detection
  WARC           — Web ARChive format for stored HTTP transactions
  Poison pill    — URL that causes worker hang or resource exhaustion
  Work stealing  — Idle workers pulling tasks from busy shards
  Revisit        — Re-fetch of previously crawled URL on schedule
  Seed           — Initial URL set starting a crawl wave
  Trap           — URL pattern generating infinite unique URLs
```

### Retention Test Preview

```
SELF-CHECK (Week 12 Retention)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. Given n=2×10^9 URLs and p=0.0001, compute m in GB and k.
  2. Why per-host queues instead of one global heap?
  3. What happens on Bloom false positive vs false negative?
  4. Order: concurrency slot, rate token, robots check — why?
  5. Retailer 403 spike after deploy — first three actions?
  6. When to bump crawl generation vs increase revisit frequency?
  7. Draw host-consistent hashing ring with 3 workers.
  8. SimHash hamming distance 3 — what does it mean?

  Answers in Expert Analysis and Bloom Mathematics sections.
```


---

## Concrete Examples

### Example: Googlebot

```
CRAWLER PROFILE: Googlebot
POLITENESS: 1-2 concurrent/host; ~0.5-2s between requests; robots refresh 24h
FRONTIER: PageRank-weighted; sitemaps highest priority; deep pagination capped
DEDUP: Multi-generation bloom + Bigtable exact; SimHash for near-dup
SCALE: Billions/day; global anycast egress; host-aware scheduling
AWS ANALOG: 5000+ ECS tasks, 256 SQS shards, DynamoDB global tables
```

### Example: Bingbot

```
CRAWLER PROFILE: Bingbot
POLITENESS: Similar to Google; honors Crawl-delay more strictly
FRONTIER: News URLs boosted via RSS/sitemap lastmod signals
DEDUP: Layered bloom + SQL exact store; canonical from redirects
NOTE: Bing Webmaster Tools API for crawl error feedback loop
```

### Example: Common Crawl

```
CRAWLER PROFILE: Common Crawl
POLITENESS: Conservative defaults; broad web sampling not exhaustive
FRONTIER: Breadth-first by domain quota (fair share across registrable domains)
DEDUP: URL normalization aggressive; near-dup less critical (archive use case)
OUTPUT: WARC files on S3 public dataset; monthly crawl generations
AWS: EMR for post-processing; S3 requester-pays egress
```

### Example: Internal Enterprise Crawler

```
CRAWLER PROFILE: Internal Enterprise Crawler
POLITENESS: N/A for internal; auth via SSO cookies in vault
FRONTIER: BFS from intranet seed; respect noindex meta
DEDUP: Exact URL in PostgreSQL; content hash for Confluence duplicates
AWS: VPC-only ECS; documents to OpenSearch; no public egress
```

### Example: Price Monitoring Bot

```
CRAWLER PROFILE: Price Monitoring Bot
POLITENESS: Strict 1 req/5s per retailer; residential proxy rotation (legal review)
FRONTIER: Revisit every 15min for SKUs; product URLs only (no follow)
DEDUP: SKU ID canonical; ignore cosmetic URL params
FAILURE MODE: Anti-bot CAPTCHA → alert merchandising team, not brute force
```

### Example: Internet Archive (Archive-It style)

```
CRAWLER PROFILE: Internet Archive (Archive-It style)
POLITENESS: Configurable per collection; institutions set crawl rate
FRONTIER: Curated seeds; deep crawl for approved domains
DEDUP: WARC record dedup by URL+timestamp (snapshots, not replace)
STORAGE: S3 Glacier Deep Archive; petabyte scale
```

### Example: SEO Audit Crawler

```
CRAWLER PROFILE: SEO Audit Crawler
POLITENESS: 2 concurrent, 1 req/s default; user-configurable per project
FRONTIER: Full site BFS capped at 50K URLs per audit
DEDUP: Normalize trailing slash; report duplicate title clusters via SimHash
OUTPUT: JSON report; no long-term index
```

### Example: Feed-Only Crawler

```
CRAWLER PROFILE: Feed-Only Crawler
POLITENESS: Poll RSS/Atom every 5min; conditional GET with ETag
FRONTIER: No HTML link follow; URL set = feed entries only
DEDUP: GUID primary key; pubDate for ordering
AWS: Lambda on EventBridge schedule; DynamoDB for last_seen
```


---

## Production Patterns

### Pattern: Per-host SQS with global scheduler

```
PROBLEM: Single queue creates head-of-line blocking behind slow hosts.
SOLUTION: 256 SQS queues partitioned by hash(host). Scheduler ECS task
round-robins eligible hosts using Redis next_eligible_ts.
ROLLOUT: Dual-write to old+new queues; drain old; delete.
METRIC: scheduler_tick_latency_ms p99 < 50ms
```

### Pattern: Two-phase crawl (discover then batch fetch)

```
PHASE 1: Fast HEAD/GET link extraction only → URL frontier populated
PHASE 2: Batch fetch during off-peak with pre-computed politeness plan
USE CASE: Initial domain onboarding; 10M URL discovery in hours, fetch over days
AWS: Step Functions orchestrates phases; S3 inventory for URL lists
```

### Pattern: Poison pill URL quarantine

```
DETECT: URL causing >3 fetch timeouts OR response >10MB OR parse CPU >30s
ACTION: quarantine:{url_hash} in Redis; skip for 24h; alert if cluster >100
PREVENT: max_response_bytes=5MB; parse timeout 10s; circuit breaker per path pattern
```

### Pattern: Robots cache warming

```
Before crawl wave to new TLD batch: dedicated robots-fetcher Lambda
pre-populates Redis robots:{host} for all seeds
Avoids thundering herd of robots.txt fetches on crawl start
```

### Pattern: Bloom snapshot recovery

```
On fetcher shard restart: load bloom snapshot from S3 (15-min RPO)
Missed inserts during gap → exact store catches duplicates (safe)
RTO: 2 min per 1GB bloom shard from S3
```

### Pattern: Graceful fleet drain on deploy

```
ECS: deploymentConfiguration minimumHealthyPercent=100, maximumPercent=100
New tasks start; old tasks stop dequeuing (SIGTERM handler); complete in-flight leases
Drain timeout 300s → force lease expiry for stuck URLs
```


---

## Failure Modes

### Failure: Crawler Trap — Infinite Calendar

```
SCENARIO: /events/2024/01/01, /events/2024/01/02, ... infinite date URLs
SYMPTOM: frontier_depth{host} grows unbounded; 0 indexable content
DETECT: URL pattern entropy alert; same template SimHash >1000 variants/hour
FIX: Trap rule for /events/YYYY/MM/DD → cap 365 days future; max depth 50
PREVENT: Parameter explosion limits; path regex denylist in normalizer
```

### Failure: Politeness Leak — Retailer Block

```
SCENARIO: Deploy increased concurrency 1→8 per host
SYMPTOM: HTTP 403 spike on retailer.com; frontier 4.2M deep; new IPs blocked in 30s
DETECT: fetch_status{host,403} / fetch_total > 5% for 2 min
FIX: Rollback concurrency; pause host frontier; backoff 3600s
PREVENT: Hard cap max_concurrent=2 in code; canary on 3 hosts before fleet
```

### Failure: Bloom False Positive Content Loss

```
SCENARIO: Bloom undersized at 6 bits/element for 5B URLs (p ≈ 0.05)
SYMPTOM: Index coverage drops 5%; support tickets "missing pages"
DETECT: dedup_false_positive_estimate rising; audit sample fetches for "skipped" URLs
FIX: Increase m/n to 14 bits; new generation; recrawl affected domains
PREVENT: Monitor FP rate; never deploy bloom without m/n calculation
```

### Failure: Frontier Starvation

```
SCENARIO: High-priority news host consumes all scheduler ticks
SYMPTOM: Obscure hosts uncrawled for weeks; index stale for long-tail
DETECT: last_fetch_age_p99 by host tier; fairness index (Gini coefficient)
FIX: Weighted fair queueing — each host guaranteed min 1 slot per 1000 ticks
PREVENT: Per-host daily fetch quota; deprioritize hosts exceeding budget
```

### Failure: Lease Reaper Storm

```
SCENARIO: 10K workers die simultaneously (AZ outage); leases expire together
SYMPTOM: 10M URLs re-enqueued in 60s; fetch rate spike; origins overloaded
DETECT: reaper_reenqueue_rate spike; fetch_rps 10× baseline
FIX: Rate-limit reaper to 10K URLs/s; stagger re-enqueue with random delay
PREVENT: Lease TTL jitter; multi-AZ worker spread; reaper on dedicated queue
```

### Failure: Robots.txt Stale Cache

```
SCENARIO: Site adds Disallow: / after breach; crawler serves cached allow 24h
SYMPTOM: Legal notice; sensitive URLs in index
DETECT: robots_version header mismatch; external report
FIX: Force robots refresh for domain; purge indexed URLs; incident postmortem
PREVENT: Honor Cache-Control on robots.txt; max TTL 6h for sensitive verticals
```


---

## SRE Diagnostic Toolkit


```
CRAWL DEBUGGING COMMANDS AND QUERIES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Per-host fetch status breakdown (CloudWatch Logs Insights)
fields @timestamp, host, status_code, latency_ms
| filter host = "retailer.com"
| stats count() by status_code
| sort count desc

# Frontier depth by host shard
aws cloudwatch get-metric-statistics \
  --namespace Crawl/Frontier \
  --metric-name QueueDepth \
  --dimensions Name=Shard,Value=42 \
  --start-time 2025-07-06T00:00:00Z \
  --end-time 2025-07-06T01:00:00Z \
  --period 300 --statistics Maximum

# Redis politeness state for host
redis-cli -h crawl-redis.xxx.cache.amazonaws.com GET rate:retailer.com
redis-cli GET concurrency:retailer.com
redis-cli GET backoff:retailer.com

# DynamoDB: is URL in exact store?
aws dynamodb get-item --table-name crawl_url_state \
  --key '{"url_hash":{"S":"abc123..."}}'

# Check robots cache
redis-cli GET robots:retailer.com

# S3: verify raw fetch landed
aws s3 ls s3://crawl-raw/20250706/retailer.com/ --recursive | tail

# Lease audit — stuck leases
aws dynamodb scan --table-name url_leases \
  --filter-expression "lease_until > :now" \
  --expression-attribute-values '{":now":{"N":"1720000000"}}'

COMMON SIGNATURES:
  Queue depth ↑ linear, fetch flat     → downstream indexer backpressure
  Single-host 403 >5%                  → politeness violation or WAF block
  dedup_bloom_maybe_rate ↑ without exact_hit ↑ → bloom saturation or FP rise
  idle_worker_seconds ↑                → frontier skew; enable work stealing
  reaper_reenqueue spike               → mass worker failure; rate-limit reaper
```


---

## Decision Framework


```
CRAWLER DESIGN DECISIONS
━━━━━━━━━━━━━━━━━━━━━━━━

┌────────────────────────────┬─────────────────────────────────────────────┐
│ Question                   │ Recommendation                              │
├────────────────────────────┼─────────────────────────────────────────────┤
│ Bloom bits per element?    │ 10-14 for p≤0.001; never below 8            │
│ Exact dedup store?         │ DynamoDB (AWS) / RocksDB (self-hosted)      │
│ Frontier queue?            │ Per-host SQS shards + Redis scheduler       │
│ Default concurrent/host?   │ 1 (2 max with SRE approval)                 │
│ Default rate/host?         │ 1 req/s; honor Crawl-delay when present     │
│ Revisit policy?            │ Exponential backoff on unchanged content    │
│ Near-dup detection?        │ SimHash + LSH if index quality matters      │
│ Proxy rotation?            │ Only with legal review; last resort         │
│ Recrawl strategy?          │ Crawl generations weekly + revisit daily    │
└────────────────────────────┴─────────────────────────────────────────────┘

WHEN TO ADD WORK STEALING:
  idle_worker_seconds p95 > 30 AND frontier shard skew > 10:1

WHEN TO PAUSE A HOST:
  403 rate >5% OR 429 rate >10% OR manual abuse report

WHEN TO BUMP CRAWL GENERATION:
  Bloom FP estimate >0.1% OR policy change requiring full recrawl
```


---

## Incident Scenario


```
INCIDENT: RETAILER.COM MASS BLOCK — 2025-07-06 02:14 UTC
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TIMELINE:
  02:14  PagerDuty: crawl_error_rate{host=retailer.com} > 50%
  02:16  On-call observes HTTP 403 on 82% of fetches (was 0.1%)
  02:18  frontier_depth{retailer.com} = 4.2M (was 200K)
  02:20  New egress IPs blocked within 30s of rotation attempt
  02:25  robots.txt unchanged — still allows /products/

CORRELATION:
  Deploy 01:10 UTC — "perf fix" increased max_concurrent 1→8 per host globally

DASHBOARD SNAPSHOT:
  fetch_total{retailer.com}: 45K/min (was 8K/min)
  concurrency{retailer.com}: pegged at 8
  token_bucket_wait_ms: 0 (concurrency not rate was bottleneck)
  WAF block page in response body (confirmed via saved S3 sample)

BUSINESS IMPACT:
  Product search index stale for retailer.com (major revenue partner)
  Legal escalation path open — contract requires politeness compliance

YOUR TASK (interview / exercise):
  Q1: Most likely root cause?
  Q2: Fix in next 15 minutes?
  Q3: How to prevent recurrence?
  Q4: How to recover index freshness without re-triggering block?
```


---

## Expert Analysis — Full Worked Response


```
Q1: ROOT CAUSE ANALYSIS
━━━━━━━━━━━━━━━━━━━━━━━

Primary: Concurrency increase 1→8 violated de-facto politeness budget.
Retailer WAF correlates burst requests from same ASN/subnet as DDoS signature.
robots.txt still allows crawling — this is rate/abuse detection, not robots.

Contributing factors:
  → Global flag change without per-host canary
  → No hard cap in application code (config-only limit)
  → Token bucket measured rate but not concurrent connection fingerprint
  → IP rotation attempted during active block — burned fresh IPs

Evidence chain:
  403 body contains WAF vendor marker
  concurrency metric pegged at 8 exactly when deploy landed
  rate token bucket shows adequate spacing — rules out simple rate limit

Q2: IMMEDIATE FIX (ORDERED — MINUTES MATTER)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  T+0 min:  FEATURE FLAG rollback max_concurrent 8→1 globally
            (Do NOT gradual rollout — partner already hot)

  T+2 min:  PAUSE frontier dequeue for retailer.com
            (URLs stay queued; zero new TCP connections to origin)

  T+5 min:  STOP IP rotation — rotating while blocked burns pool
            Document current blocked CIDR for partner abuse desk

  T+10 min: CONTACT partner via abuse@ / TAM with:
            - User-Agent string
            - Approximate fetch timeline
            - Acknowledgment of concurrency misconfiguration
            - Request whitelist restoration timeline

  T+15 min: After partner ack OR 403 rate <1% for 5 min on test fetch:
            Resume at 1 concurrent, 1 req/2s with jitter
            Monitor 403 rate per minute

  T+30 min: Gradual index recovery — prioritize product URLs from sitemap
            (high business value, known-good paths)

Q3: PREVENTION (SYSTEMIC FIXES)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  CODE ENFORCEMENT:
    const MAX_CONCURRENT_PER_HOST = 2  // not configurable above 2
    Deploy pipeline rejects config >2

  CANARY PROTOCOL:
    Politeness changes roll to 3 low-risk hosts for 24h
    Auto-rollback if any host 403_rate >2%

  ALERTS:
    fetch_403_rate{host} > 5% for 2 min → auto throttle host to 1 concurrent
    fetch_rps{host} > 2× 7-day baseline → page

  TESTING:
    Robots + rate policy simulator in CI
    Replay production traffic against staging with new politeness params

  RUNBOOK:
    "403 spike" → pause host → rollback → contact → slow resume
    Never rotate IPs during active block

Q4: INDEX RECOVERY WITHOUT RE-BLOCK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Phase 1 (hours 1-6): Sitemap-only crawl at 1 req/3s
    ~50K product URLs from sitemap index
    Skip follow-links until 403 rate stable 24h

  Phase 2 (day 2-7): BFS depth=1 from product pages only
    max 500K URLs; daily quota 100K fetches

  Phase 3 (week 2+): Full revisit schedule restored
    Partner confirmed whitelist restored

  Parallel: Serve stale index with "prices may be outdated" banner
    Better stale than empty for revenue URLs

POSTMORTEM ACTION ITEMS:
  □ Hard cap in code (owner: crawl-platform)
  □ Canary framework for politeness (owner: SRE)
  □ Partner notification automation (owner: partnerships)
  □ WAF response body logging (owner: fetcher)
  □ Incident added to Week 12 retention test
```


---

## Hands-On Exercises


```
EXERCISE 1: Bloom Filter Sizing
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Given: n=500 million URLs, target false positive rate p=0.001

  Calculate:
    1. m (bits required) using m = -n ln(p) / (ln 2)²
    2. k (hash functions) using k = (m/n) ln 2
    3. Memory in GB
    4. Expected false positives per day at 10M URL checks/day

  Verify with Python:
    import math
    n = 500_000_000
    p = 0.001
    m = -n * math.log(p) / (math.log(2)**2)
    k = m / n * math.log(2)
    print(f"m={m:.0e} bits ({m/8/1e9:.2f} GB), k={k:.1f}")


EXERCISE 2: robots.txt Parser
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Write a function that given User-agent and path returns allowed/denied:

    User-agent: *
    Disallow: /admin/
    Allow: /admin/public/

  Test cases:
    /admin/           → denied
    /admin/public/x   → allowed
    /products/1       → allowed

  Edge case: longest prefix match when multiple rules apply.


EXERCISE 3: Token Bucket Simulator
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Simulate 60 seconds of requests with rate=2/s, burst=3.
  Plot token count over time with requests at t=0,0.1,0.2,0.3,1.0,1.1

  Questions:
    Which requests succeed?
    When is request at t=0.3 denied?
    When can it retry?


EXERCISE 4: URL Normalization
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Implement normalization for:
    HTTP://Example.COM:80/a/../b?z=1&utm=x&y=2#frag

  Expected: https://example.com/b?y=2&z=1

  Add tracking param strip list: utm_*, fbclid, gclid


EXERCISE 5: Inspect Real robots.txt
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  curl -s https://www.google.com/robots.txt | head -30
  curl -s https://www.reddit.com/robots.txt | head -30

  Compare: Which paths blocked for * vs Googlebot?
  How would your crawler behave differently for each?


EXERCISE 6: SimHash Hamming Distance
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Given two 64-bit SimHashes, compute hamming distance.
  If distance ≤ 3, classify as near-duplicate.

  Extend: implement LSH band lookup for candidate retrieval.


EXERCISE 7: Design Review — Startup Crawler
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Requirements: 10M pages/day, 1000 seed domains, AWS budget $5K/month

  Sketch:
    ECS task count
    SQS shard count
    DynamoDB capacity mode
    Bloom shard memory
    S3 storage estimate (avg 50KB/page)

  Present tradeoffs: on-demand vs provisioned, Spot vs On-Demand fetchers.
```


---

## Key Takeaways

```
╔══════════════════════════════════════════════════════════════════════════════╗
║ IF YOU FORGET EVERYTHING ELSE, REMEMBER THESE:                               ║
║                                                                              ║
║ 1. Politeness is the product — speed without it ends the crawl               ║
║ 2. Frontier = per-host priority queues + global scheduler, not one heap      ║
║ 3. Dedup = normalize → Bloom (L1) → exact store (L2) → SimHash (content)     ║
║ 4. Bloom math: m = -n ln(p)/(ln 2)²; never deploy without sizing m/n         ║
║ 5. Distributed crawl needs host-consistent hashing + leases + generations    ║
║ 6. False positives lose content; false negatives in Bloom are impossible     ║
║ 7. On 403 spike: pause host, rollback concurrency, never rotate IPs while hot║
╚══════════════════════════════════════════════════════════════════════════════╝
```


---

## Targeted Reading


```
REQUIRED:
  1. Heydon & Najork, "Mercator: A Scalable, Extensible Web Crawler"
     → Frontier design, link extraction, dedup at Google scale
  2. RFC 9309 — Robots Exclusion Protocol (replaces RFC 1996)
     → Normative robots.txt parsing and caching behavior
  3. Bloom, "Space/Time Trade-offs in Hash Coding with Erroneous Cells"
     → Original Bloom filter paper; false positive derivation
  4. Cho & Garcia-Molina, "Effective Page Refresh Policies for Web Crawlers"
     → Revisit scheduling: uniform, proportional, exponential

OPTIONAL:
  5. Charikar, "Similarity Estimation Techniques from Hashing Algorithms" (SimHash)
  6. AWS Architecture Blog: "Scheduling workflows at scale with Amazon SQS"
  7. Common Crawl documentation — WARC format and crawl ethics
  8. Edwards et al., "Competitive Analysis of Web Crawler Scheduling Strategies"
```
