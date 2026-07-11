# Design Google Search

> **Week 12** — System design module: crawl → index → rank → serve at web scale
> **Prerequisites:** Week 7 (Inverted Indexes), Week 12 (Web Crawler), Week 3 (Consistent Hashing)

---

## Learning Objectives

```
╔══════════════════════════════════════════════════════════════════════════════╗
║   AFTER THIS TOPIC, YOU WILL BE ABLE TO:                                     ║
╟──────────────────────────────────────────────────────────────────────────────╢
║                                                                              ║
║   1. Design an end-to-end web search system from URL discovery               ║
║      through inverted-index serving, explaining how crawl, index,            ║
║      rank, and query subsystems decouple and scale independently             ║
║                                                                              ║
║   2. Architect Googlebot-class crawling: URL frontier, per-host              ║
║      politeness, robots.txt integration, deduplication, and crawl            ║
║      budget allocation under finite fetch capacity                           ║
║                                                                              ║
║   3. Explain inverted indexes, posting lists, forward indexes, and           ║
║      BM25 scoring with enough precision to debug relevance regressions       ║
║      and size index shards correctly                                         ║
║                                                                              ║
║   4. Describe PageRank intuition and power iteration as an offline           ║
║      link-graph signal — and where it sits in a modern multi-signal          ║
║      ranker alongside BM25, freshness, and Learning to Rank                  ║
║                                                                              ║
║   5. Architect query serving for sub-200ms p99: query parsing, shard         ║
║      fanout, posting-list intersection, top-K heap merge, and LTR            ║
║      reranking within latency budgets                                        ║
║                                                                              ║
║   6. Choose between term-based vs doc-id index sharding, mitigate            ║
║      hot-term skew, and design replica strategies for head-query             ║
║      load without blowing storage budgets                                    ║
║                                                                              ║
║   7. Diagnose multi-symptom search incidents: stale index, hot shards,       ║
║      crawl stalls, ranking deploy regressions, and cache poisoning           ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

### Foundation

> Progress through Foundation → Staff → Principal stretch. Staff is the mastery gate.


```
╔═══════════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Search = database with LIKE queries"                  ║
╟───────────────────────────────────────────────────────────────────────────╢
║   WRONG. Full-text search over billions of documents requires inverted    ║
║   indexes — term → posting list mappings — not row scans. SQL LIKE        ║
║   '%foo%' is O(n) over document bodies; inverted lookup is O(log V + k)   ║
║   where V is vocabulary size and k is result count. At 50B pages,         ║
║   sequential scan is physically impossible within human lifetimes.        ║
╠═══════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "Crawl everything, index everything"                   ║
╟───────────────────────────────────────────────────────────────────────────╢
║   WRONG. Crawl budget is finite — Googlebot cannot fetch the entire       ║
║   web daily. You prioritize by PageRank, freshness signals, sitemap       ║
║   hints, and host politeness. Most URLs on the web are never crawled.     ║
║   Infinite calendar traps and faceted navigation can consume an entire    ║
║   host's budget without adding searchable value.                          ║
╠═══════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "PageRank IS the ranking algorithm"                    ║
╟───────────────────────────────────────────────────────────────────────────╢
║   WRONG. PageRank is ONE precomputed link-based authority signal from     ║
║   the 1998 paper. Modern Google Search blends hundreds of signals:        ║
║   BM25 term relevance, neural embeddings, freshness, spam scores,         ║
║   user context, site quality, and Learning-to-Rank models. PageRank       ║
║   answers "is this page important on the web?" not "does it match         ║
║   this query?"                                                            ║
╠═══════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "One inverted index shard handles all queries"         ║
╟───────────────────────────────────────────────────────────────────────────╢
║   WRONG. A single shard melts on head terms ("facebook", "weather").      ║
║   Production systems shard by doc-id OR by term ranges, replicate hot     ║
║   partitions, and may maintain separate indices for head vs tail.         ║
║   Query fanout to all shards on every request does not scale past         ║
║   tens of billions of documents.                                          ║
╠═══════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Index freshness = crawl timestamp"                    ║
╟───────────────────────────────────────────────────────────────────────────╢
║   WRONG. A page can be crawled successfully and still be invisible in     ║
║   search for hours if the indexing pipeline is backlogged, if a bulk      ║
║   rebuild is in progress, or if the serving generation hasn't cut over.   ║
║   Crawl dashboards and search freshness dashboards measure different      ║
║   things — conflating them causes the #1 on-call confusion in search.     ║
╠═══════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #6: "More replicas always improve query latency"           ║
╟───────────────────────────────────────────────────────────────────────────╢
║   WRONG. Replicas serve reads but multiply indexing write amplification.  ║
║   During bulk rebuilds, 15 replicas means 15× segment merge work.         ║
║   Replicas also increase cache fragmentation — each replica cold-starts   ║
║   independently unless you use dedicated query-only replicas fed by       ║
║   immutable index snapshots.                                              ║
╚═══════════════════════════════════════════════════════════════════════════╝
```

---

## Core Teaching — End-to-End Architecture

### Why Web Search Is a Different Problem

```
THE FUNDAMENTAL CONSTRAINT: THE WEB IS BIGGER THAN YOU

  Estimated public web pages:     ~50 billion indexed (Google, 2024 estimates)
  New pages/day:                  millions
  Queries/day (Google):           ~8.5 billion (~99,000 QPS average)
  Peak QPS (estimated):           500K+ during major events

  You cannot:
    → Store all pages in one database
    → Scan all pages per query
    → Crawl all pages daily
    → Rank all matching docs fully (millions of hits per query)

  You MUST:
    → Prioritize what to crawl (crawl budget)
    → Precompute what you can (PageRank, link graph, spam scores)
    → Index for fast term lookup (inverted index)
    → Approximate ranking in stages (cheap retrieval → expensive rerank)
    → Serve from replicated, sharded infrastructure globally
```

### The Four Subsystems (Loosely Coupled)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    GOOGLE SEARCH — LOGICAL ARCHITECTURE                 │
└─────────────────────────────────────────────────────────────────────────┘

  SUBSYSTEM 1: CRAWL (Googlebot)
  ─────────────────────────────
  Input:  seeds, sitemaps, discovered links, recrawl schedules
  Output: raw HTML/WARC, extracted links, HTTP metadata
  Stores: URL frontier (Cassandra/DynamoDB-class), dedup Bloom filters
  SLA:    politeness > throughput; never get blocked

  SUBSYSTEM 2: INDEX (Indexer + Link Graph)
  ─────────────────────────────────────────
  Input:  parsed documents (title, body, anchors, headers)
  Output: inverted index segments, forward index, link graph edges
  Stores: Colossus/GFS/S3 + custom column stores
  SLA:    batch rebuild hours; incremental updates minutes–hours

  SUBSYSTEM 3: RANK (Offline + Query-Time)
  ────────────────────────────────────────
  Input:  link graph, click logs, quality raters, document features
  Output: PageRank scores, spam scores, LTR model weights
  Stores: Bigtable/DynamoDB feature stores
  SLA:    offline jobs daily; query-time scoring <50ms budget

  SUBSYSTEM 4: SERVE (Query Pipeline)
  ───────────────────────────────────
  Input:  user query + context (locale, device, history)
  Output: ranked SERP (10 blue links + rich results)
  Stores: in-memory index segments on query nodes, query cache
  SLA:    p99 < 200ms end-to-end globally

DATA FLOW (simplified):

  Web pages
      │
      ▼
  ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
  │ Googlebot│────►│  Parser  │────►│ Indexer  │────►│  Index   │
  │  Crawl   │     │ + Link   │     │ Pipeline │     │ Segments │
  └──────────┘     │ Extract  │     └──────────┘     └────┬─────┘
                   └──────────┘                           │
                                                          │
  ┌──────────┐     ┌──────────┐     ┌──────────┐          │
  │   User   │────►│  Query   │────►│  Index   │◄─────────┘
  │  Query   │     │  Parser  │     │  Shards  │
  └──────────┘     └────┬─────┘     └────┬─────┘
                        │                │
                        ▼                ▼
                   ┌──────────┐     ┌──────────┐
                   │  Merge   │◄────│ Posting  │
                   │  Top-K   │     │ Lists    │
                   └────┬─────┘     └──────────┘
                        │
                        ▼
                   ┌──────────┐     ┌──────────┐
                   │   LTR    │────►│   SERP   │
                   │ Rerank   │     │ Response │
                   └──────────┘     └──────────┘

  Offline (parallel):
    Link graph ──► PageRank iteration ──► doc authority scores
    Click logs ──► LTR training ──► reranker model weights
```

### Latency Budget Decomposition

```
QUERY LATENCY BUDGET (200ms p99 target):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Component                    Typical Budget    What Breaks It
  ─────────────────────────    ──────────────    ──────────────
  DNS + TLS + network RTT      10–30ms           Geographic distance
  Query parsing + spellcheck   2–5ms             Complex NLP pipelines
  Query cache lookup           1–3ms             Cache miss storm
  Shard fanout (network)       20–40ms           Hot shard, slow node
  Posting list intersection    30–80ms           High-IDF rare term combos
  Top-K heap merge             5–15ms            Too many candidate docs
  Forward index fetch          10–30ms           Large snippet fields
  LTR rerank (top 100–1000)    20–50ms           Model complexity creep
  SERP assembly + ads          10–30ms           Ad auction timeout
  ─────────────────────────    ──────────────
  TOTAL                        ~100–200ms        Any single stage 3× over

KEY INSIGHT: Retrieval must be CHEAP. You cannot run a neural network
on 10 million candidate documents. Pipeline:

  Stage 1: Inverted index → 10,000 candidates   (BM25, ~50ms)
  Stage 2: Lightweight filters → 1,000            (spam, freshness, ~10ms)
  Stage 3: LTR rerank → 10 final results          (ML model, ~40ms)
```

### Storage Scale Anchors

```
ORDER-OF-MAGNITUDE NUMBERS (public estimates + industry lore):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Documents indexed:        tens of billions
  Unique terms (vocabulary): hundreds of millions after stemming
  Average document size:    ~50 KB HTML (highly variable)
  Inverted index size:      often 20–40% of raw corpus (compressed)
  Link graph edges:         trillions (stored compactly)
  Index shard count:        thousands of serving partitions
  Crawl rate:               billions of pages/day fleet-wide
  Recrawl half-life:        high-PR pages: days; long tail: months

  AWS ANALOG for a mid-size search product (NOT Google scale):
    OpenSearch: 20 data nodes, r6g.2xlarge
    500M documents, 50 primary shards, 1 replica
    Index size: ~15 TB
    Query: 5K QPS, p99 80ms
```

---

### Part A: Crawling — The Googlebot Pipeline

#### What Googlebot Actually Is

```
Googlebot is NOT a single program. It is a FLEET of distributed fetchers
coordinated by schedulers, frontiers, and politeness enforcers.

COMPONENTS:
  ┌─────────────────┐
  │ Seed injectors  │  sitemaps, RSS, URL submission, discovered links
  └────────┬────────┘
           ▼
  ┌─────────────────┐
  │ URL normalizer  │  canonical form, strip fragments, trap detection
  └────────┬────────┘
           ▼
  ┌─────────────────┐
  │ Dedup layer     │  Bloom filter (fast) → exact store (correct)
  └────────┬────────┘
           ▼
  ┌─────────────────┐
  │ Frontier mgr    │  per-host priority queues, crawl budget allocator
  └────────┬────────┘
           ▼
  ┌─────────────────┐
  │ Politeness gate │  robots.txt, rate limiter, crawl-delay
  └────────┬────────┘
           ▼
  ┌─────────────────┐
  │ Fetch workers   │  HTTP/2, conditional GET, DNS cache
  └────────┬────────┘
           ▼
  ┌─────────────────┐
  │ Render pipeline │  HTML parse OR headless Chrome for JS SPAs
  └────────┬────────┘
           ▼
  ┌─────────────────┐
  │ Link extractor  │  <a href>, canonical, sitemap refs → frontier
  └─────────────────┘
```

#### URL Frontier — The Heart of the Crawler

```
THE URL FRONTIER PROBLEM:
━━━━━━━━━━━━━━━━━━━━━━━━

  You have billions of URLs waiting to be fetched.
  You have finite fetch capacity (millions of fetches/hour).
  You must decide: WHICH URL next?

  Naive approach: one global priority queue
  → DISASTER: one slow host (timeout 30s) blocks entire fleet
  → DISASTER: one spam domain floods queue with infinite URLs

  Production approach: PER-HOST priority queues + global scheduler

  ┌───────────────────────────────────────────────────────────────┐
  │                       FRONTIER MANAGER                        │
  │                                                               │
  │   Global scheduler picks HOST, then picks URL from that host  │
  │                                                               │
  │   host: amazon.com     [url1, url2, url3, ...]  priority: 0.9 │
  │   host: wikipedia.org  [url1, url2, ...]        priority: 0.8 │
  │   host: blog.example   [url1, ...]              priority: 0.1 │
  │   host: trap.site      [url1..url999999]        priority: 0.0 │
  │                     (crawl trap detected)                     │
  └───────────────────────────────────────────────────────────────┘

PRIORITY SCORE (conceptual formula):

  priority(url) = w1 * PageRank(host)
                + w2 * freshness_decay(last_crawl)
                + w3 * sitemap_priority
                + w4 * recrawl_urgency(content_change_signal)
                - w5 * crawl_depth_penalty
                - w6 * duplicate_content_score

  High PageRank host → fetched more often
  Recently changed page → recrawl sooner
  Calendar trap (/page?date=2020-01-01...) → depth penalty crushes priority
```

#### Politeness — Non-Negotiable Contract with the Web

```
POLITENESS RULES (production baseline):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. robots.txt compliance
     → Fetch robots.txt first (cache 24h)
     → Respect Disallow, Crawl-delay, sitemap directives
     → Googlebot user-agent specific rules

  2. Per-host rate limiting
     → Default: ~1 request/second/host (varies by host capacity signals)
     → Adaptive: back off on 429, 503, connection timeouts
     → NEVER hammer a single host because your scheduler has a bug

  3. Concurrent connection limits
     → Max N simultaneous connections per host (typically 2–8)
     → Prevents SYN flood appearance even if rate limiter allows

  4. Conditional requests
     → If-Modified-Since / If-None-Match on recrawls
     → 304 Not Modified → skip reindexing, update crawl timestamp only
     → Saves bandwidth AND index churn

TOKEN BUCKET IMPLEMENTATION (per host):

  ┌──────────────────────────────────────┐
  │  Redis key: politeness:amazon.com    │
  │  tokens: 3.7                         │
  │  refill_rate: 1.0/sec                │
  │  max_burst: 5                        │
  └──────────────────────────────────────┘

  Before fetch:
    tokens = HGET politeness:amazon.com tokens
    if tokens >= 1:
      HINCRBY politeness:amazon.com tokens -1
      proceed with fetch
    else:
      requeue URL with delay = time_until_next_token

  On 429 Too Many Requests:
    refill_rate *= 0.5   (halve rate)
    requeue all pending URLs for this host with 60s delay

WHY POLITENESS MATTERS BEYOND ETHICS:
  → Blocked crawler = stale index for that entire domain
  → Legal liability (CFAA, GDPR scraping rules in some jurisdictions)
  → Reputation: webmasters report abusive bots → IP range blocks
```

#### Crawl Budget Allocation

```
CRAWL BUDGET: finite fetches per day across entire fleet
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Total fleet capacity:     ~billions fetches/day (Google-scale estimate)
  URLs discovered/day:      far exceeds capacity
  → You MUST prioritize

  ALLOCATION STRATEGIES:

  1. PageRank-weighted scheduling
     High-PR pages recrawled every few days
     Long-tail pages: weeks to months between crawls

  2. Freshness signals
     News sites: recrawl every minutes–hours
     Static documentation: recrawl every months

  3. Host-level caps
     Prevent one domain from consuming >X% of daily budget
     Detect crawl traps early (URL count exploding, unique content flat)

  4. Sitemap hints
     <lastmod> in sitemap.xml boosts recrawl priority
     Webmasters use Search Console to request recrawl (limited quota)

CRAWL TRAP DETECTION:

  Symptom: host generates 1M URLs/day, indexed doc count flat

  Signatures:
    → Session IDs in URLs: /product?id=abc&sid=random
    → Calendar pagination: /archive/2020/01/01, /archive/2020/01/02...
    → Faceted navigation: /shoes?color=red&size=10&brand=nike&...

  Mitigation:
    → URL normalization rules (strip session params)
    → Max depth per host
    → SimHash near-duplicate detection (same content, different URL)
    → Manual host-level crawl rate reduction
```

#### JavaScript Rendering — The Two-Tier Fetch Model

```
MODERN WEB = MUCH CONTENT BEHIND JAVASCRIPT

  Static HTML fetch:     fast (~100ms), cheap, sees server-rendered content
  Headless render:       slow (2–10s), expensive (Chrome instance), sees SPA content

  Googlebot uses TWO-TIER strategy:

  Tier 1 (default): HTTP fetch + HTML parser
    → Works for 70–80% of pages (SSR, static sites)
    → Extracts <a href> links from raw HTML

  Tier 2 (selective): Headless Chrome render queue
    → Triggered when: empty body, heavy JS framework detected,
      webmaster flagged, or initial fetch missing expected content
    → Renders page, waits for network idle, extracts DOM

  COST COMPARISON:
    HTML fetch:     ~$0.000001 per page (bandwidth + CPU)
    JS render:      ~$0.001 per page (1000× more expensive)
    → Render queue is strictly budgeted

  AWS ANALOG:
    Lambda + Puppeteer for selective render
    SQS priority queue: HTML fetch (high throughput) vs render (low concurrency)
    CloudWatch alarm: render_queue_depth > 100K → scale render fleet
```

#### Deduplication — Three Layers

```
DEDUP LAYER 1: URL NORMALIZATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Before any dedup check, normalize:
    http://example.com/page  →  https://example.com/page  (canonical scheme)
    /Page?id=1&sid=abc       →  /page?id=1                 (lowercase, strip session)
    /page#section            →  /page                      (strip fragment)
    /page?b=2&a=1            →  /page?a=1&b=2              (sort query params)

DEDUP LAYER 2: BLOOM FILTER (probabilistic, in-memory)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  "Have we probably seen this URL before?"
  → 10 bits per URL, ~1% false positive rate
  → False positive: skip a never-seen URL (acceptable loss)
  → False negative: impossible (Bloom filters have no false negatives)
  → Size: 10B URLs × 10 bits = 12.5 GB (fits in RAM across fleet)

DEDUP LAYER 3: EXACT STORE (DynamoDB/Cassandra)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  url_hash → {first_seen, last_crawl, crawl_count, content_hash}
  → Definitive answer: seen or not
  → Used when Bloom says "maybe new" or for recrawl scheduling
  → Partition key: hash(url) for even distribution
```

---

### Part B: Indexing — Inverted Index Deep Dive

#### From Documents to Postings

```
INDEXING PIPELINE:
━━━━━━━━━━━━━━━━

  Raw HTML
      │
      ▼
  ┌─────────────┐
  │ HTML parser │  extract title, body, h1-h6, meta, anchor text
  └──────┬──────┘
         ▼
  ┌─────────────┐
  │  Analyzer   │  tokenize → lowercase → stem → stopword removal
  └──────┬──────┘
         ▼
  ┌─────────────┐
  │  Indexer    │  build posting lists, compute term stats (df, tf)
  └──────┬──────┘
         ▼
  ┌─────────────┐
  │  Segment    │  immutable on-disk index chunk (Lucene segment)
  │  writer     │
  └─────────────┘

EXAMPLE CORPUS:

  Doc 1 (doc_id=101): "Google search engine ranking"
  Doc 2 (doc_id=102): "Search engines use inverted indexes"
  Doc 3 (doc_id=103): "Google ranking algorithm updates"

AFTER TOKENIZATION (lowercase, no stopwords):

  Doc 101: [google, search, engine, ranking]
  Doc 102: [search, engines, use, inverted, indexes]
  Doc 103: [google, ranking, algorithm, updates]
```

#### Inverted Index Structure

```
INVERTED INDEX (term → postings):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Term          Document Frequency (df)    Posting List
  ──────────    ───────────────────────    ─────────────────────────────
  google        2                          [(101, tf=1, pos=[0]),
                                             (103, tf=1, pos=[0])]
  search        2                          [(101, tf=1, pos=[1]),
                                             (102, tf=1, pos=[0])]
  engine        1                          [(101, tf=1, pos=[2])]
  engines       1                          [(102, tf=1, pos=[1])]
  ranking       2                          [(101, tf=1, pos=[3]),
                                             (103, tf=1, pos=[1])]
  inverted      1                          [(102, tf=1, pos=[3])]
  indexes       1                          [(102, tf=1, pos=[4])]
  algorithm     1                          [(103, tf=1, pos=[2])]
  updates       1                          [(103, tf=1, pos=[3])]

POSTING LIST ENTRY (compact on disk):
  doc_id:     variable-byte encoded integer (delta compression)
  tf:         term frequency in document
  positions:  [optional] word positions for phrase queries
  payloads:   [optional] font size, anchor boost flags

ON-DISK LAYOUT (Lucene-inspired):

  ┌─────────────────────────────────────────┐
  │  Dictionary (term → pointer)            │  ← binary search / FST
  ├─────────────────────────────────────────┤
  │  Postings file (doc_id deltas, tf)      │  ← compressed bit-packing
  ├─────────────────────────────────────────┤
  │  Positions file (optional)              │
  ├─────────────────────────────────────────┤
  │  Norms file (doc length for BM25)       │
  └─────────────────────────────────────────┘
```

#### Forward Index — Why You Need Both

```
FORWARD INDEX (doc_id → document metadata):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Inverted index answers: "Which docs contain term X?"
  Forward index answers:  "What is doc 101's title, URL, snippet, PageRank?"

  Doc 101:
    url:        https://example.com/google-search
    title:      "Google Search Engine Ranking Guide"
    body_snip:  "...Google search engine ranking factors..."
    pagerank:   0.0042
    crawl_date: 2024-11-15
    lang:       en
    spam_score: 0.02

WHY NOT STORE EVERYTHING IN POSTINGS?
  → Posting lists are scanned for EVERY query term
  → Bloated postings = slower intersection
  → Forward index fetched ONLY for top-K candidates after retrieval

QUERY FLOW:
  1. Inverted index: find docs matching all terms     (cheap, millions of docs)
  2. BM25 score using tf from postings + df from index (cheap)
  3. Forward index: fetch title/snippet for top 1000   (moderate)
  4. LTR rerank top 1000 → final 10                    (expensive)
```

#### BM25 — The Workhorse Ranking Function

```
BM25 (Best Matching 25) — Okapi BM25 formula:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  score(D, Q) = Σ  IDF(qi) × ─────────────────────────────
               qi∈Q              tf(qi,D) × (k1 + 1)
                                 ─────────────────────────────
                                 tf(qi,D) + k1 × (1 - b + b × |D|/avgdl)

  Where:
    qi     = each query term
    tf     = term frequency in document D
    |D|    = document length (word count)
    avgdl  = average document length in corpus
    k1     = term frequency saturation (typical: 1.2–2.0)
    b      = length normalization (typical: 0.75)
    IDF(qi) = log( (N - df(qi) + 0.5) / (df(qi) + 0.5) + 1 )

INTUITION:

  IDF: rare terms matter more
    "the" appears in every doc → IDF ≈ 0 → ignored
    "kubernetes" in 0.01% of docs → high IDF → strong signal

  TF saturation: diminishing returns
    Word appears 1 time  → good signal
    Word appears 50 times → NOT 50× better (spam indicator)
    k1 controls saturation curve

  Length normalization:
    Long doc mentions "python" 20 times → might just be a long page
    Short doc mentions "python" 5 times → probably very relevant
    b=0.75 penalizes long documents moderately

WORKED EXAMPLE (simplified):

  Query: "google ranking"
  Corpus: N=3 docs, avgdl=6 words

  IDF(google)  = log((3 - 2 + 0.5)/(2 + 0.5) + 1) = log(1.6) ≈ 0.47
  IDF(ranking) = log((3 - 2 + 0.5)/(2 + 0.5) + 1) = log(1.6) ≈ 0.47

  Doc 103 "Google ranking algorithm updates" (4 words):
    tf(google)=1, tf(ranking)=1, |D|=4
    BM25(103) ≈ 0.47 × 1.38 + 0.47 × 1.38 ≈ 1.30

  Doc 101 "Google search engine ranking" (4 words):
    tf(google)=1, tf(ranking)=1, |D|=4
    BM25(101) ≈ 1.30  (same terms, same score in this toy example)

  Doc 102 "Search engines use inverted indexes" (5 words):
    tf(google)=0, tf(ranking)=0
    BM25(102) = 0  (no matching terms)

TUNING k1 AND b IN PRODUCTION:
  k1=1.2, b=0.75: Elasticsearch/OpenSearch defaults
  Higher k1: more weight to term frequency (good for technical docs)
  Lower b: less length penalty (good for long-form content)
  → A/B test relevance metrics (NDCG@10) when tuning
```

#### Index Segment Lifecycle

```
LUCENE-STYLE SEGMENT MODEL (used by Elasticsearch, Google internally):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  WRITE PATH:
    Document arrives → in-memory buffer (RAM)
    Buffer fills (or refresh_interval) → flush to immutable SEGMENT on disk
    Segment: self-contained inverted index chunk

  ┌─────────┐  ┌─────────┐  ┌─────────┐
  │ Seg A   │  │ Seg B   │  │ Seg C   │   ← immutable, never modified
  │ 1M docs │  │ 500K    │  │ 2M docs │
  └─────────┘  └─────────┘  └─────────┘

  QUERY PATH:
    Search ALL segments in parallel
    Merge top-K from each → global top-K

  MERGE (background):
    Seg A + Seg B → Seg D (compacted, fewer files)
    Deletes old segments when merge complete

  NEAR-REAL-TIME (NRT):
    Default refresh_interval: 1 second (Elasticsearch)
    Document indexed → visible in search within ~1s
    Tradeoff: faster refresh = more segments = slower queries

  FULL REBUILD (Google-scale batch):
    Build new index generation from scratch on batch cluster
    Atomic cutover: flip query traffic to new generation
    Old generation deleted after TTL
    → Avoids merge amplification on live serving cluster
```

---

### Part C: PageRank — Link Graph Authority (Overview)

#### Intuition — Random Surfer Model

```
PAGERANK CORE IDEA (Brin & Page, 1998):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Imagine a user randomly clicking links on the web.
  Eventually, they spend more time on pages with many incoming links
  from other important pages.

  A page is IMPORTANT if IMPORTANT pages link to it.

  NOT: "most links wins" (spam farms would dominate)
  BUT: links from high-quality pages matter more than links from junk

  ANALOGY:
    Academic citations — a paper cited by Nobel laureates is more
    influential than one cited by unknown undergraduates.
    PageRank generalizes this to the entire web graph.
```

#### The Formula

```
PAGERANK EQUATION:
━━━━━━━━━━━━━━━━━━

  PR(A) = (1-d)/N  +  d × Σ  PR(Ti) / C(Ti)
                         Ti∈In(A)

  Where:
    PR(A)     = PageRank of page A
    d         = damping factor (typically 0.85)
    N         = total pages in graph
    In(A)     = pages that link TO A
    Ti        = a page linking to A
    C(Ti)     = number of outbound links on page Ti

  (1-d)/N  = teleport probability — surfer jumps to random page
             Prevents pages with no inlinks from having PR=0
             Prevents sink nodes from absorbing all rank

  d × Σ... = link-following probability — surfer follows a random
             outbound link from current page

NUMERIC EXAMPLE (4 pages):

  Links:  A→B, A→C, B→C, C→A, D→C

  ┌─────┐     ┌─────┐
  │  A  │────►│  B  │
  └──┬──┘     └──┬──┘
     │           │
     ▼           ▼
  ┌─────┐◄──────┘
  │  C  │◄──┐
  └──┬──┘   │
     │      │
     ▼      │
  (back to A)│
             │
  ┌─────┐────┘
  │  D  │  (D links only to C)
  └─────┘

  After convergence (d=0.85):
    PR(A) ≈ 0.37   (gets link from C, links out to B,C)
    PR(B) ≈ 0.08   (one inlink from A)
    PR(C) ≈ 0.42   (inlinks from A, B, D — most authoritative)
    PR(D) ≈ 0.13   (no inlinks, but teleport term gives baseline)
```

#### Power Iteration — How It's Computed

```
POWER ITERATION ALGORITHM:
━━━━━━━━━━━━━━━━━━━━━━━━━━

  PageRank is computed OFFLINE on the link graph — not per query.

  1. Initialize: PR(p) = 1/N for all pages

  2. Iterate until convergence:
       for each page p:
         PR_new(p) = (1-d)/N + d × Σ PR_old(t)/outdegree(t)
                              t→p

  3. Stop when max|PR_new - PR_old| < ε (e.g., ε = 10⁻⁶)

  Convergence: typically 50–100 iterations for web-scale graphs

  SPARSE MATRIX FORM (efficient at scale):

    r = (1-d)/N × 1  +  d × M × r

    M = column-stochastic adjacency matrix (N × N, mostly zeros)
    r = PageRank vector

  At Google scale:
    N ≈ 50 billion pages
    M is sparse: average ~10 outlinks per page → 500B non-zero entries
    Stored compressed; MapReduce/Spark iteration over link graph
    Computed daily or weekly; incremental updates for changed subgraphs

  AWS ANALOG for smaller link graphs:
    Store edges in S3: s3://link-graph/edges/part-*.parquet
    Spark job: PageRank.run(graph, maxIter=50, resetProb=0.15)
    Output: doc_id → pagerank_score in DynamoDB feature store
    Query servers read precomputed score at rerank time
```

#### Where PageRank Sits in Modern Ranking

```
PAGERANK IS ONE SIGNAL — NOT THE RANKER:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Query-time ranking pipeline (conceptual):

  Stage 1 — RETRIEVAL (inverted index + BM25):
    "Find docs containing query terms, score by term relevance"
    → PageRank NOT used here (too expensive per query)

  Stage 2 — QUALITY FILTER:
    spam_score < threshold
    freshness > minimum for time-sensitive queries
    → PageRank may filter very low-PR pages for head queries

  Stage 3 — RERANK (Learning to Rank):
    Features fed to ML model:
      BM25_score
      PageRank_score          ← precomputed offline
      click_through_rate
      dwell_time
      title_match
      url_depth
      https_flag
      ... hundreds more

    Model output: final relevance score for top-K candidates

  INTERVIEW SOUNDBITE:
    "PageRank answers global authority — is this page important on
     the web? BM25 answers local relevance — does this page match
     the query? Modern search needs both, plus behavioral signals."
```

---

### Part D: Query Serving — Parse, Fanout, Merge, Rank

#### Query Parsing Pipeline

```
USER TYPES: "best kubernetes tutorial site:github.com"

QUERY PARSER OUTPUT:
━━━━━━━━━━━━━━━━━━

  Raw tokens:     ["best", "kubernetes", "tutorial", "site:github.com"]

  After analysis:
    terms:        ["kubernetes", "tutorial"]     (stemmed)
    stopwords:    ["best"] removed OR kept as weak signal
    operator:     site:github.com → filter host=github.com
    intent:       informational (not navigational, not transactional)
    spellcheck:   no correction needed
    synonyms:     kubernetes ↔ k8s (optional expansion)

PARSER STAGES:

  ┌──────────────┐
  │ Tokenizer    │  split on whitespace/punctuation
  └──────┬───────┘
         ▼
  ┌──────────────┐
  │ Normalizer   │  lowercase, unicode NFKC, accent folding
  └──────┬───────┘
         ▼
  ┌──────────────┐
  │ Spell checker│  edit distance ≤2, query log priors
  └──────┬───────┘
         ▼
  ┌──────────────┐
  │ Operator     │  site:, filetype:, intitle:, -exclude
  │ parser       │
  └──────┬───────┘
         ▼
  ┌──────────────┐
  │ Intent       │  navigational / informational / transactional
  │ classifier   │
  └──────────────┘
```

#### Shard Fanout — Scatter-Gather

```
QUERY FANOUT ARCHITECTURE:
━━━━━━━━━━━━━━━━━━━━━━━━━━

  User query arrives at QUERY COORDINATOR (root server)

  Coordinator:
    1. Parses query → list of terms + filters
    2. Determines which SHARDS hold those terms (routing table)
    3. Sends parallel RPCs to shard servers
    4. Collects partial results
    5. Merges into global top-K
    6. Sends top-K to reranker

  ┌─────────────┐
  │   User      │
  └──────┬──────┘
         │ "kubernetes tutorial"
         ▼
  ┌─────────────┐
  │ Coordinator │
  └──────┬──────┘
         │
    ┌────┼────┬────────┬────────┐
    ▼    ▼    ▼        ▼        ▼
  ┌────┐┌────┐┌────┐  ┌────┐  ┌────┐
  │Sh0 ││Sh1 ││Sh2 │  │Sh3 │  │ShN │
  └────┘└────┘└────┘  └────┘  └────┘
    │    │    │         │       │
    └────┴────┴────┬────┴───────┘
                   ▼
            ┌─────────────┐
            │ Merge Top-K │
            │   (heap)    │
            └──────┬──────┘
                   ▼
            ┌─────────────┐
            │ LTR Rerank  │
            └──────┬──────┘
                   ▼
               SERP JSON

DOC-ID SHARDING FANOUT:
  Query "kubernetes tutorial" → fan out to ALL shards
  Each shard returns its local top-100 by BM25
  Coordinator merges N × 100 candidates → global top-100

TERM SHARDING FANOUT:
  "kubernetes" → shard 7 only
  "tutorial"   → shard 3 only
  Intersect posting lists from shard 7 AND shard 3
  → fewer shards touched for multi-term queries
  → BUT hot term "facebook" overloads shard 7
```

#### Posting List Intersection

```
BOOLEAN AND QUERY: "kubernetes" AND "tutorial"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Posting list "kubernetes": [101, 205, 309, 412, 501, 602, ...]  (sorted)
  Posting list "tutorial":   [101, 309, 445, 501, 789, ...]       (sorted)

  MERGE-INTERSECT (two-pointer algorithm):

    ptr_k = 0, ptr_t = 0
    results = []

    while ptr_k < len(k8s) and ptr_t < len(tutorial):
      if k8s[ptr_k] == tutorial[ptr_t]:
        results.append(k8s[ptr_k])
        ptr_k++; ptr_t++
      elif k8s[ptr_k] < tutorial[ptr_t]:
        ptr_k++
      else:
        ptr_t++

    Result: [101, 309, 501]

  Complexity: O(|list1| + |list2|) — linear, not O(|list1| × |list2|)

  WITH SKIP POINTERS (production optimization):
    Posting lists store skip entries every √n positions
    When doc_id at ptr_k << doc_id at ptr_t, skip ahead in k8s list
    → sub-linear for skewed list length differences

  PHRASE QUERY: "kubernetes tutorial" (adjacent terms)
    Requires POSITIONS in posting list entries
    Check pos(kubernetes) + 1 == pos(tutorial) in same doc
    → more expensive; often deferred to rerank stage
```

#### Top-K Merge Across Shards

```
DISTRIBUTED TOP-K (WAND algorithm family):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Problem: 100 shards each return top-100 local results
           Coordinator must find global top-10 without sorting 10,000 items

  NAIVE: collect all 10,000, sort → O(n log n) — too slow

  HEAP MERGE:
    Maintain min-heap of size K=10 (global)
    For each shard result (score, doc_id):
      if heap.size < K: push
      elif score > heap.min: pop min, push new
    → O(N_shards × local_K × log K) = manageable

  WAND (Weak AND, optional early termination):
    Each shard sends upper-bound score per term
    Coordinator skips shards whose upper bound < current heap minimum
    → safe pruning when BM25 scores are bounded per shard

  EXAMPLE:
    Shard 0 top score: 12.4
    Shard 1 top score: 8.1
    Shard 2 top score: 15.7  ← likely global winner
    ...
    If heap minimum is 11.0, shard 1 cannot contribute → skip its RPC response
```

#### Learning to Rank (LTR)

```
LTR — ML OVER HAND-TUNED WEIGHTS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  WHY LTR?
    BM25 + PageRank + manual boosts → 2005-era relevance
    Hundreds of signals interact non-linearly
    Human tuning does not scale; ML learns from click logs

  TRAINING DATA:
    Query q, doc d, label relevance (0–4 from human raters)
    OR implicit: clicked = relevant, skipped = not relevant

  FEATURE VECTOR (per query-doc pair):
    [BM25_score, PageRank, title_tf, url_match, freshness_days,
     click_rate_7d, dwell_time_p50, domain_authority, ...]

  MODEL TYPES:
    Pointwise:  predict relevance score per doc independently
    Pairwise:   learn which of two docs is better (RankNet, LambdaMART)
    Listwise:   optimize entire ranked list (ListNet)

  PRODUCTION CONSTRAINT:
    LTR runs on top 100–1000 candidates ONLY
    Model inference budget: ~30–50ms for 1000 docs
    → Feature precomputation critical (PageRank offline, not per query)
    → Model served via TensorFlow Serving / custom C++ scorer

  AWS ANALOG:
    SageMaker trains LambdaMART on S3 click logs
    Model artifact in S3 → loaded by query reranker pods
    Feature store: DynamoDB for precomputed doc features
    A/B test via feature flag: 5% traffic on model v2.15
```

#### Query Result Cache

```
QUERY CACHE LAYER:
━━━━━━━━━━━━━━━━━━

  Exact-match cache: hash(normalized_query + locale) → SERP JSON
  TTL: 60–300 seconds for head queries
  Hit rate: 20–40% for popular queries ("weather", "facebook")

  ┌───────────────┐
  │ Edge POP      │  ← cache hit: 5ms response, no backend touch
  └──────┬────────┘
         │ miss
         ▼
  ┌───────────────┐
  │ Query         │  ← regional cache: 20ms
  │ Cache (Redis) │
  └──────┬────────┘
         │ miss
         ▼
  ┌───────────────┐
  │ Full query    │  ← 100–200ms path
  │ pipeline      │
  └───────────────┘

  CACHE INVALIDATION TRIGGERS:
    Index generation cutover → flush all (atomic)
    Ranking model deploy → flush or version cache keys
    Manual purge for legal takedowns (DMCA)

  DANGER: stale-if-error during index outage
    Serves deleted/404 pages from cache
    → compound incident symptom (Week 12 compound scenario)
```

---

### Part E: Index Sharding — Term vs Doc-ID, Hot Terms, Replicas

#### Why Sharding Is Mandatory

```
SINGLE-NODE INDEX LIMITS:
━━━━━━━━━━━━━━━━━━━━━━━━━

  50 billion documents × ~2 KB inverted index per doc ≈ 100 TB index
  No single machine has 100 TB RAM for in-memory serving
  Even on SSD: query latency degrades with single-node I/O contention

  Sharding splits the index across N machines.
  Each shard is an independent inverted index subset.
  Query coordinator merges results across shards.

  GOOGLE-SCALE: thousands of shards
  AWS OpenSearch mid-size: 20–50 primary shards
```

#### Doc-ID Sharding (Document Partitioning)

```
DOC-ID SHARDING:
━━━━━━━━━━━━━━━━

  Shard assignment: shard_id = hash(doc_id) mod N

  ┌─────────────────────────────────────────────────────────┐
  │  Shard 0: docs where hash(doc_id) % 32 == 0             │
  │  Shard 1: docs where hash(doc_id) % 32 == 1             │
  │  ...                                                    │
  │  Shard 31: docs where hash(doc_id) % 32 == 31           │
  └─────────────────────────────────────────────────────────┘

  PROS:
    ✓ Even document distribution (hash spreads uniformly)
    ✓ Simple routing for indexing: hash(doc_id) → shard
    ✓ Adding shards: consistent hashing minimizes remapping (Week 3)

  CONS:
    ✗ EVERY query fans out to ALL shards
    ✗ Query "facebook" touches all 32 shards even though term is rare
    ✗ Cross-shard merge required for every query

  WHEN TO USE:
    → Default for Elasticsearch/OpenSearch
    → Query QPS moderate; shard count ≤ 100
    → Even doc sizes; no extreme hot terms
```

#### Term Sharding (Lexical Partitioning)

```
TERM SHARDING:
━━━━━━━━━━━━━━

  Shard assignment: shard_id = hash(term) mod N

  Term "kubernetes" → Shard 7
  Term "facebook"   → Shard 3
  Term "tutorial"   → Shard 12

  Multi-term query "kubernetes tutorial":
    → Contact ONLY Shard 7 AND Shard 12
    → Intersect posting lists locally after fetch
    → Fewer shards touched than doc-id sharding

  PROS:
    ✓ Reduced fanout for multi-term queries
    ✓ Hot term isolated to one shard (can over-replicate that shard)

  CONS:
    ✗ SEVERE hot term problem: "the", "a", "facebook" overload one shard
    ✗ Vocabulary skew: English terms dominate; shard 3 gets 10× traffic
    ✗ Rebalancing requires moving entire term posting lists (large)

  HOT TERM MITIGATIONS:
    1. Stopword removal: "the" never hits index
    2. Hot term replication: "facebook" posting list copied to shards 3,3a,3b,3c
    3. Two-tier index: head terms in dedicated in-memory shard
    4. Query routing: coordinator knows "facebook" → hot shard replica set
```

#### Hybrid Sharding (Production Reality)

```
GOOGLE-CLASS HYBRID (conceptual):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Layer 1: Doc-id sharded base index (bulk of long-tail)
  Layer 2: Head-term overlay index (top 10K queries precomputed)
  Layer 3: Vertical indices (News, Images, Shopping — separate clusters)

  Query "kubernetes tutorial":
    → Base index: fanout all doc-id shards, BM25 retrieval
    → Merge top-500

  Query "facebook" (navigational):
    → Head index: single shard lookup, instant result
    → Skip full fanout entirely

  AWS ANALOG:
    OpenSearch: doc-id sharding for catalog index
    ElastiCache: head query cache for top 1000 queries
    Separate OpenSearch domain for autocomplete (prefix index)
```

#### Replica Strategy

```
REPLICAS: read scaling + failover
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Primary shard: accepts writes (indexing)
  Replica shard: copy of primary, serves reads (queries)

  ┌──────────┐     replication     ┌──────────┐
  │ Primary 0│ ──────────────────► │ Replica 0│
  │ (writes) │                     │ (reads)  │
  └──────────┘                     └──────────┘

  Query routing:
    Coordinator picks replica with lowest load (round-robin + latency)
    Hot shard: add replicas 0a, 0b, 0c — all serve identical data

  WRITE AMPLIFICATION:
    1 document indexed → written to primary + R replicas
    Segment merge runs on EACH copy
    15 replicas = 16× indexing CPU during bulk rebuild

  IMMUTABLE SNAPSHOT REPLICAS (Google pattern):
    Batch build index generation on offline cluster
    Snapshot to GFS/S3
    Query nodes load snapshot read-only — no live indexing on serving path
    → Replicas are cheap (no merge overhead)
    → Cutover = deploy new snapshot to query fleet

  AWS OpenSearch:
    aws opensearch describe-domain --domain-name prod-search
    → NumberOfNodes, DedicatedMasterEnabled
    UltraWarm for older indices (S3-backed, slower queries)
    Cold storage for archival (restore minutes–hours)
```

#### Hot Shard Detection and Mitigation

```
HOT SHARD SIGNATURES:
━━━━━━━━━━━━━━━━━━━━━

  Metrics:
    shard_query_rate{shard="7"} >> all others (3–10×)
    shard_cpu{shard="7"} > 90% sustained
    shard_p99_latency{shard="7"} > 500ms while others < 100ms

  Root causes:
    1. Term sharding + head query ("weather", brand names)
    2. Doc-id sharding + viral doc (everyone links to one page)
    3. Skewed hash (unlikely with good hash function)
    4. Replica failure → all traffic to remaining replica

  MITIGATIONS (ordered by invasiveness):
    1. Add replicas to hot shard (minutes, if capacity exists)
    2. Query cache warm for hot queries (hours)
    3. Dedicated hot-shard cluster (days)
    4. Reshard / rebalance (weeks, requires reindex)
```

---

### Part F: Query Understanding and Spell Correction

```
QUERY UNDERSTANDING LAYERS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Layer 1 — Normalization:
    "K8s tutorial" → tokens [k8s, tutorial]
    Unicode normalization, accent removal

  Layer 2 — Spell correction:
    "kubernets tutorial" → "kubernetes tutorial"
    Noisy channel model: P(query|correct) × P(correct)
    Query log priors: "kubernets" → "kubernetes" (high frequency)

  Layer 3 — Synonym expansion (optional):
    k8s ↔ kubernetes (same posting list OR query-time OR)

  Layer 4 — Intent classification:
    "facebook" → navigational (user wants facebook.com)
    "how to bake bread" → informational
    "buy running shoes" → transactional

  Navigational queries: skip full retrieval, direct domain match
  → why null results on brand queries hurt so much in the incident
```

### Part G: Snippet Generation and Highlighting

```
SNIPPET GENERATION (after top-K selected):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Forward index provides: title, body text, URL
  Snippet: extract ~160 chars around best-matching query terms

  Algorithm:
    1. Find positions of query terms in body (from posting positions)
    2. Choose window maximizing term density
    3. Insert <b> highlights around matched terms
    4. Append ellipsis if truncated

  Cost: only for top-10 results, not full corpus
  Stored fields in Lucene: _source or docvalues for title/URL
```

### Part H: Link Graph Storage for PageRank

```
LINK GRAPH EDGE FORMAT:
━━━━━━━━━━━━━━━━━━━━━━━

  Each crawled page yields outlinks:
    (source_doc_id, anchor_text, target_url, target_doc_id_if_known)

  Storage: compressed sparse adjacency lists
    doc_id → [outlink_doc_ids...]

  Scale: 50B pages × 10 outlinks = 500B edges
    ~4 bytes per edge compressed = 2 TB link graph

  Incremental update:
    Daily full PageRank too expensive
    → compute on changed subgraph (new/changed pages ± 2 hops)
    → propagate delta to global scores

  AWS analog:
    Edges in S3 Parquet partitioned by source_doc_id % 1024
    Spark GraphFrames percolate nightly
```

### Part I: Autocomplete and Prefix Indices

```
AUTocomplete IS NOT THE SAME INDEX:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Inverted index: optimized for term lookup (hash/FST)
  Prefix index: optimized for "prefix → completions"

  Structure: edge n-gram tokenization
    "kubernetes" → [k, ku, kub, kube, kuber, kubern, kubernet, kubernetes]

  Separate lightweight index OR in-memory trie at edge
  Latency budget: < 20ms (user types every 100ms)

  AWS: API Gateway → Lambda → ElastiCache trie
  OR OpenSearch completion suggester field (memory heavy)
```

### Part J: Spam and Quality Signals

```
SPAM DETECTION (offline + query-time filter):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Offline signals:
    Link farm detection (unnatural inlink patterns)
    Keyword stuffing (tf unnaturally high)
    Cloaking (different content for bot vs user)
    Thin content (low unique token count)

  Query-time:
    spam_score > 0.8 → filter before LTR (save ML budget)
    Penguin-class updates demote manipulative link profiles

  Production pattern:
    Manual actions (Search Console) → doc-level noindex flag in forward index
```

### Part K: Geographic and Language Routing

```
GLOBAL QUERY SERVING:
━━━━━━━━━━━━━━━━━━━━━

  User in Tokyo → query coordinator in asia-northeast1
  Index shard replica in same region (avoid cross-Pacific fanout)

  Language detection on query → route to language-specific index slice
  OR: lang field filter on unified index

  Geo bias: boost results with ccTLD matching user country
  Not censorship — relevance signal (local business for local query)

  AWS: Route 53 geolocation routing to regional OpenSearch domains
  CloudFront for query cache at edge (60s TTL)
```

### Part L: Ad Integration and Doc ID Stability

```
WHY DOC_ID STABILITY MATTERS FOR ADS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Ad auction: bid on keyword → match to doc_id → render ad with landing URL
  If doc_id changes during index rebuild → ad points to 404
  Incident Symptom B: CTR drop because doc_ids in cache ≠ current index

  Production invariant:
    doc_id = hash(canonical_url) — stable across reindexes
    URL changes → new doc_id, redirect old → new in forward index
    Index generation cutover does NOT reassign doc_ids

  Cache keys must include index_generation to prevent stale ad matches
```



## Concrete Examples — Real Systems and AWS Analogs

### Google Search (Reference Architecture)

```
GOOGLE (public information + engineering blog lore):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Crawl:     Googlebot fleet, Caffeine crawl system (2009+)
  Storage:   Colossus (GFS successor), Bigtable for metadata
  Index:     Caffeine continuous indexing (no batch-only rebuild)
  Query:     index shards on query nodes globally distributed
  Ranking:   RankBrain (2015), BERT (2019), MUM — neural signals
             PageRank still computed on link graph offline

  Key differentiator vs startup search:
    → Continuous indexing pipeline (minutes freshness for news)
    → Separate index tiers by content type and quality
    → Global query serving with geographic routing
```

### Bing / Microsoft Bing

```
BING ARCHITECTURE (published research):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Similar crawl → index → serve pipeline
  Tiger crawl system (successor to earlier MSNBot)
  Index serving: partitioned by doc-id with aggressive caching
  Differentiation: social signals (Twitter partnership era),
                   entity graph (Satori knowledge base)

  Lesson: even #2 search engine faces same sharding/hot-term problems
```

### AWS OpenSearch — E-Commerce Product Search

```
REAListic AWS DEPLOYMENT (500M products):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Architecture:
    RDS PostgreSQL (source of truth)
      → DMS CDC → Kafka → Lambda consumers → OpenSearch bulk API

  OpenSearch domain:
    20 data nodes: r6g.2xlarge (64 GB RAM each)
    3 dedicated masters: m6g.large
    50 primary shards, 1 replica = 100 shard copies
    Index: products-v3, mapping explicit (no dynamic)

  Index mapping (excerpt):
    {
      "mappings": {
        "properties": {
          "sku":        { "type": "keyword" },
          "title":      { "type": "text", "analyzer": "english" },
          "brand":      { "type": "keyword" },
          "price":      { "type": "float" },
          "category":   { "type": "keyword" },
          "in_stock":   { "type": "boolean" }
        }
      }
    }

  Query (bool + filter + boost):
    POST /products-v3/_search
    {
      "query": {
        "bool": {
          "must": { "multi_match": { "query": "wireless headphones",
              "fields": ["title^3", "description"] }},
          "filter": [
            { "term": { "in_stock": true }},
            { "range": { "price": { "lte": 200 }}}
          ]
        }
      },
      "size": 20
    }

  Sizing math:
    500M docs × ~1.5 KB index overhead ≈ 750 GB raw
    With replicas: 1.5 TB
    20 nodes × 500 GB EBS gp3 = 10 TB capacity (headroom for merges)
```

### Algolia — Hosted Search SaaS

```
ALGOLIA (when to buy vs build):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Managed inverted index + typo tolerance + facets
  No crawl — you push records via API
  Sub-10ms p50 via global edge network

  Use when:
    → Site search < 100M records
    → No custom crawl budget needs
    → Team lacks search SRE expertise

  Don't use when:
    → Public web crawl at billion-page scale
    → Custom ranking is core product differentiator
    → Cost at scale ($$ per record/month adds up)
```

### Elasticsearch at Stripe (Published)

```
STRIPE SEARCH (engineering blog):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Internal document/search for support and ops
  Elasticsearch cluster with strict mapping governance
  Key lesson: mapping explosions from dynamic fields caused outages
  → Explicit mappings, dynamic: strict, reindex playbook documented
```

---

### Staff

## Production Patterns

### Pattern 1: Blue/Green Index Generations

```
PROBLEM: Live reindex on serving cluster causes merge storms + latency spikes

SOLUTION:
  1. Build index generation N+1 on BATCH cluster (no query traffic)
  2. Validate: doc count, sample query parity, checksum
  3. Atomic cutover: update routing table / alias swap
  4. Keep generation N for 24h rollback window
  5. Delete generation N after confidence interval

  Elasticsearch alias pattern:
    POST /_aliases
    {
      "actions": [
        { "remove": { "index": "catalog-v2", "alias": "catalog-live" }},
        { "add":    { "index": "catalog-v3", "alias": "catalog-live" }}
      ]
    }

  Rollback: reverse the actions (< 1 second)
```

### Pattern 2: CQRS — Postgres Source of Truth, OpenSearch Read Model

```
FROM WEEK 5 / WEEK 7 (integrated):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Write path:  API → PostgreSQL (ACID)
  Read path:   API → OpenSearch (search SLA)

  Sync: DMS CDC → Kafka → idempotent consumer → bulk index

  INVARIANT: OpenSearch is NEVER source of truth
  Rebuild procedure: reindex from Postgres snapshot (tested quarterly)

  Idempotency key: (doc_id, version) — ignore stale CDC events
```

### Pattern 3: Tiered Freshness Pipelines

```
HOT PATH (products, news):
  Crawl → Kafka → stream indexer → serving index in < 5 min
  Simplified mapping (fewer analyzed fields)

COLD PATH (long-tail web):
  Batch crawl → batch index → daily generation cutover

  Separate Kafka topics:
    crawl.priority.high  (SLA: 5 min to searchable)
    crawl.priority.low   (SLA: 24 hours)
```

### Pattern 4: Canary Ranking Deploys

```
RANKING MODEL DEPLOY:
━━━━━━━━━━━━━━━━━━━━━

  1. Shadow mode: compute new scores, log diff, don't serve (24h)
  2. Canary: 1% traffic on model v2.14
  3. Monitor: NDCG@10, null-result rate, p99 latency, ad CTR
  4. Ramp: 1% → 5% → 25% → 100% over 48h if metrics green
  5. Instant rollback: feature flag OFF

  NEVER deploy ranking change + index rebuild simultaneously
  → impossible to attribute regressions
```

### Pattern 5: Query Understanding Cache Warming

```
Before major event (Black Friday, election):
  Pre-warm query cache with expected head queries
  Pre-scale query coordinator pool + hot shard replicas
  Freeze non-essential index rebuilds 48h before event
  Run load test at 2× expected QPS against staging index snapshot
```

---

## Failure Modes

### Failure 1: Index Lag — Crawl Green, Search Stale

```
SYMPTOM:  crawl_completed_total normal; index_lag_seconds climbing
CAUSE:    Indexer fleet undersized; mapping change triggered reanalysis
          of all docs; Kafka consumer lag
BLAST:    New products invisible; revenue loss; support tickets
FIX:      Scale indexers; shed low-priority crawl; hot-path partial index
PREVENT:  Autoscale on index_queue_depth; separate hot/cold pipelines
```

### Failure 2: Hot Shard Meltdown

```
SYMPTOM:  p99 latency 800ms on 5% of queries; one shard CPU 100%
CAUSE:    Head query ("brand name") + term sharding OR skewed doc
BLAST:    User-facing slowness; ad auction timeouts; cascading retries
FIX:      Add replicas; enable query cache; route head queries to overlay
PREVENT:  Hot term detection dashboard; head query index tier
```

### Failure 3: Ranking Deploy Regression

```
SYMPTOM:  null_result_rate +3%; CTR -20%; no infra alerts
CAUSE:    Freshness weight increased 40%; stale high-PR docs demoted
          below threshold; navigational queries broken
BLAST:    Revenue (ads on wrong docs); user trust
FIX:      Rollback model via feature flag (< 5 min)
PREVENT:  Shadow mode; canary deploy; navigational query golden set tests
```

### Failure 4: Crawl Politeness Leak

```
SYMPTOM:  Single host receiving 500 req/sec; 429 responses; IP block
CAUSE:    Scheduler bug bypassed token bucket; trap URL explosion
BLAST:    Entire domain drops from index; legal escalation possible
FIX:      Emergency host drain; fix scheduler; backoff 24h before recrawl
PREVENT:  Per-host rate metric alerts; max URLs/host/hour cap
```

### Failure 5: Index Corruption / Partial Generation

```
SYMPTOM:  Random docs missing fields; shard 7 red; checksum mismatch
CAUSE:    Bulk index interrupted; bad deployment; disk failure mid-merge
BLAST:    Inconsistent SERPs; ad doc_id mismatch; 404 in top results
FIX:      Stop cutover; rebuild shard 7 from snapshot; do NOT serve partial
PREVENT:  Checksum validation before alias swap; replica quorum reads
```

### Failure 6: Query Cache Serving Deleted Content

```
SYMPTOM:  Top results are 404 pages; index shows doc deleted
CAUSE:    stale-if-error during index outage; cache TTL too long
BLAST:    User frustration; brand damage; "Google is broken" tweets
FIX:      Purge query cache; disable stale-if-error; force index refresh
PREVENT:  Cache key includes index generation; purge on generation cutover
```

---

## SRE Diagnostic Toolkit

```
SEARCH INCIDENT DEBUGGING — EXACT COMMANDS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# ─── OPENSEARCH / ELASTICSEARCH CLUSTER HEALTH ───

# Cluster status (green/yellow/red)
curl -s -u "$OS_USER:$OS_PASS" \
  "https://search-prod.us-east-1.es.amazonaws.com/_cluster/health?pretty"

# Output interpretation:
#   green  → all primary + replica shards assigned
#   yellow → replicas missing (single-AZ, node down)
#   red    → primary shards missing — QUERY FAILURES on those shards

# Per-shard allocation — find unassigned/red shards
curl -s -u "$OS_USER:$OS_PASS" \
  "https://search-prod.us-east-1.es.amazonaws.com/_cat/shards?v&s=state"

curl -s -u "$OS_USER:$OS_PASS" \
  "https://search-prod.us-east-1.es.amazonaws.com/_cat/shards?v&h=index,shard,prirep,state,docs,store,node" \
  | awk '$4 != "STARTED" {print}'

# Hot shard detection — docs and size per shard
curl -s -u "$OS_USER:$OS_PASS" \
  "https://search-prod.us-east-1.es.amazonaws.com/_cat/shards/products-v3?v&s=store:desc" \
  | head -20

# Node CPU / JVM heap pressure
curl -s -u "$OS_USER:$OS_PASS" \
  "https://search-prod.us-east-1.es.amazonaws.com/_cat/nodes?v&h=name,heap.percent,cpu,load_1m,disk.used_percent"

# ─── QUERY LATENCY AND SLOW LOG ───

# Enable slow query log (>500ms) temporarily
curl -s -X PUT -u "$OS_USER:$OS_PASS" \
  "https://search-prod.us-east-1.es.amazonaws.com/products-v3/_settings" \
  -H "Content-Type: application/json" \
  -d '{
    "index.search.slowlog.threshold.query.warn": "500ms",
    "index.search.slowlog.threshold.fetch.warn": "200ms"
  }'

# Profile a specific slow query
curl -s -X POST -u "$OS_USER:$OS_PASS" \
  "https://search-prod.us-east-1.es.amazonaws.com/products-v3/_search" \
  -H "Content-Type: application/json" \
  -d '{
    "profile": true,
    "query": { "match": { "title": "wireless headphones noise canceling" }},
    "size": 10
  }' | jq '.profile.shards[0].searches[0].query'

# Measure query latency from client
curl -w "\nTTFB: %{time_starttransfer}s Total: %{time_total}s\n" \
  -s -o /dev/null -X POST -u "$OS_USER:$OS_PASS" \
  "https://search-prod.us-east-1.es.amazonaws.com/products-v3/_search" \
  -H "Content-Type: application/json" \
  -d '{"query":{"match":{"title":"test"}},"size":1}'

# ─── INDEX LAG / CDC PIPELINE ───

# Kafka consumer lag (indexer group)
kafka-consumer-groups.sh --bootstrap-server $KAFKA_BROKERS \
  --group opensearch-indexer-v3 --describe

# Expected output columns: LAG per partition
# LAG > 100000 sustained → index falling behind crawl

# OpenSearch indexing rate
curl -s -u "$OS_USER:$OS_PASS" \
  "https://search-prod.us-east-1.es.amazonaws.com/_cat/indices/products-v3?v&h=index,docs.count,store.size,health"

# Compare doc count vs source DB
psql "$RDS_URL" -c "SELECT COUNT(*) FROM products WHERE active=true;"
# vs OpenSearch docs.count — mismatch > 1% warrants investigation

# ─── CRAWL FLEET DIAGNOSTICS ───

# Per-host fetch rate from crawl logs (CloudWatch Logs Insights)
# fields @timestamp, host, status_code, latency_ms
# | filter service = "googlebot-fetcher"
# | stats count() as fetches, avg(latency_ms) by host
# | sort fetches desc
# | limit 20

aws logs start-query \
  --log-group-name /aws/ecs/crawl-fetcher \
  --start-time $(date -d '1 hour ago' +%s) \
  --end-time $(date +%s) \
  --query-string 'fields host, status_code | stats count() by host | sort count desc | limit 10'

# Politeness bucket inspection (Redis)
redis-cli -h crawl-politeness.cache.amazonaws.com HGETALL "politeness:amazon.com"
# tokens, last_refill, refill_rate — tokens near 0 + high queue = backoff

# Frontier queue depth per host
redis-cli -h crawl-frontier.cache.amazonaws.com ZCARD "frontier:amazon.com"
# ZCARD > 1000000 → possible crawl trap

# ─── QUERY CACHE ───

# Redis query cache stats
redis-cli -h query-cache.cache.amazonaws.com INFO stats | grep keyspace
redis-cli INFO stats | egrep "keyspace_hits|keyspace_misses"
# hit_rate = hits / (hits + misses) — below 20% on head queries = problem

# Sample cache key for head query
redis-cli GET "qcache:en-US:$(echo -n 'wireless headphones' | sha256sum | cut -d' ' -f1)"

# Purge query cache (emergency — expect latency spike)
redis-cli -h query-cache.cache.amazonaws.com FLUSHDB

# ─── INDEX GENERATION / ALIAS ───

# Which index generation is live?
curl -s -u "$OS_USER:$OS_PASS" \
  "https://search-prod.us-east-1.es.amazonaws.com/_alias/catalog-live?pretty"

# Document count per generation
curl -s -u "$OS_USER:$OS_PASS" \
  "https://search-prod.us-east-1.es.amazonaws.com/_cat/indices/catalog-*?v&h=index,docs.count,store.size"

# ─── AWS OPENSEARCH SERVICE API ───

# Domain cluster config
aws opensearch describe-domain --domain-name prod-search \
  --query 'DomainStatus.{InstanceType:ClusterConfig.InstanceType,InstanceCount:ClusterConfig.InstanceCount,EngineVersion:EngineVersion}'

# Recent automated snapshot (restore point)
aws opensearch describe-domain --domain-name prod-search \
  --query 'DomainStatus.SnapshotOptions'

# ─── RANKING DEPLOY VERIFICATION ───

# Compare null-result rate (Prometheus)
# rate(search_null_results_total[5m]) / rate(search_queries_total[5m])

# PromQL — spike after deploy at 06:00
# increase(search_null_results_total{model="v2.14"}[15m])
#   / increase(search_queries_total[15m]) > 0.02

# Golden set regression (run from CI/canary script)
python scripts/golden_queries.py --model v2.14 --baseline v2.13 \
  --queries tests/data/navigational_1000.txt --threshold 0.95
```

### Metric Dashboard Checklist

```
METRICS TO WATCH (search-specific):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  CRAWL:
    crawl_fetch_rate{host}           per-host fetches/sec
    crawl_429_rate{host}             politeness violations
    crawl_queue_depth{host}          frontier backlog
    crawl_trap_detected_total        trap heuristics fired

  INDEX:
    index_lag_seconds                  crawl timestamp → searchable delta
    kafka_consumer_lag{group}          indexer backlog
    index_docs_total                   doc count drift
    index_merge_rate                   merge IO pressure

  QUERY:
    search_query_p50_ms / p99_ms       latency SLO
    search_shard_fanout_count          shards touched per query
    search_null_result_rate            zero-hit queries
    search_cache_hit_rate              query cache effectiveness

  RANKING:
    search_ctr@1                       click-through on position 1
    search_ndcg@10                     offline relevance proxy
    ad_ctr                             revenue-sensitive signal

  ALERTS (starting points):
    index_lag_seconds > 900            P2 — stale index
    search_p99_ms > 500 for 5m         P2 — latency SLO breach
    cluster_health != green for 2m     P1 — shard failure
    null_result_rate > baseline + 2%   P2 — ranking or index regression
```

---

## Decision Framework

```
WHEN TO USE WHAT — SEARCH DESIGN CHEATSHEET
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌────────────────────────────┬─────────────────────────────────────────┐
│ Requirement                │ Recommendation                          │
├────────────────────────────┼─────────────────────────────────────────┤
│ <1M documents, <100 QPS     │ PostgreSQL FTS or Algolia              │
│ 1M–100M docs, site search  │ Managed OpenSearch, doc-id sharding     │
│ Public web search scale    │ Custom crawl + sharded inverted index   │
│ Sub-minute freshness news  │ Streaming index + priority crawl lane   │
│ Personalized results       │ User features in reranker ONLY          │
│ Strict ACL (enterprise)    │ Filter at query time, security trim     │
│ Faceted e-commerce         │ OpenSearch + keyword fields + aggs      │
│ Autocomplete               │ Separate edge n-gram index              │
└────────────────────────────┴─────────────────────────────────────────┘

SHARDING DECISION TREE:

  Start: doc-id sharding (default)
    │
    ├─ QPS > 10K AND p99 > 200ms?
    │     YES → add replicas first
    │     NO  → continue
    │
    ├─ Hot term shard CPU > 3× average?
    │     YES → head query cache OR term overlay index
    │     NO  → continue
    │
    ├─ Fanout to all shards too expensive?
    │     YES → evaluate term sharding for tail queries
    │           BUT replicate hot terms explicitly
    │     NO  → stay doc-id

BUILD VS BUY:

  BUY (OpenSearch, Algolia, Typesense):
    → Search is supporting feature, not core product
    → Team < 2 dedicated search engineers
    → < 500M documents, standard relevance needs

  BUILD (custom crawl + index):
    → Public web index at billion+ page scale
    → Ranking is primary product moat
    → Cost optimization at scale (managed $/doc too high)
    → Custom freshness/recrawl logic impossible on SaaS

CRAWL BUDGET ALLOCATION:

  High PageRank + high change rate  → recrawl daily–weekly
  Medium PR + stable content        → recrawl monthly
  Low PR long-tail                  → recrawl yearly or never
  News/social                       → recrawl minutes–hours
  Trap detected                     → cap at 100 URLs/day/host
```

---

# 🔥 SRE SCENARIO — Multi-Symptom Search Outage During Ranking Deploy

```
INCIDENT REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Severity: P1 (revenue + user trust)
Service: QueryHub — commercial web search (Google-class at smaller scale)
Time: 06:00–07:30 UTC, Black Friday prep day
Revenue impact: 41% of platform revenue from search ads

ARCHITECTURE:
  ╔═════════════════════════════════════════════════════════════════════════╗
  ║ QUERY PATH                                                              ║
  ║   User → CloudFront (query result cache, 60s TTL, stale-if-error)       ║
  ║   → Query Coordinator (48 pods, us-east-1 + eu-west-1)                  ║
  ║   → OpenSearch cluster "catalog-v3" (180 data nodes, 12 primaries × 15  ║
  ║     replicas, doc-id sharding)                                          ║
  ║   → LTR reranker (LambdaMART v2.14, SageMaker endpoint)                 ║
  ║   → Ad auction (requires stable doc_id → landing URL mapping)           ║
  ║                                                                         ║
  ║ INDEXING PATH                                                           ║
  ║   Crawler fleet (800 fetchers) → Kafka crawl.raw                        ║
  ║   → Parser → Kafka docs.parsed → Doc Builder → bulk index ES            ║
  ║   Merchant CDC → Kafka merchant.updates → partial update API            ║
  ║                                                                         ║
  ║ CRAWLER                                                                 ║
  ║   Politeness: per-domain token bucket (Redis Cluster)                   ║
  ║   Frontier: priority queues (Cassandra)                                 ║
  ║   Dedup: SimHash + URL canonicalization                                 ║
  ║   Robots.txt cache: 24h TTL in Redis                                    ║
  ╚═════════════════════════════════════════════════════════════════════════╝

DEPLOY CONTEXT:
  05:55 — Ranking model v2.14 promoted to 100% traffic (skipped canary —
          VP override for Black Friday freshness feature)
  05:30 — Merchant bulk price update: 200K SKU price changes via CDC
  04:00 — Crawl fleet scaled +20% for Black Friday recrawl push

INCIDENT TIMELINE:

  06:00 — Deploy complete. Freshness signal weight +40% in v2.14.

  06:12 — null_result_rate: 0.02% baseline → 3.8% for brand queries
          Example: "nike air max 90" returns zero results (was #1 yesterday)

  06:18 — Ad CTR drops 22%. Ads served with doc_ids pointing to 404 URLs.

  06:24 — Crawler frontier queue depth: 890M URLs (+300M in 30 min)
          Politeness bucket for amazon.com stuck at tokens=0 for 18 minutes
          amazon.com fetch rate: 0 req/sec (normally 2 req/sec)

  06:30 — OpenSearch cluster yellow → red. catalog-v3 shard 7 primary
          UNASSIGNED. _cluster/health: 1 primary shard missing.

  06:36 — Social media: "Search is broken — top results are dead links
          from 6 months ago"

  06:42 — Partial update API returns HTTP 200, but spot-check shows
          price field missing on 15% of updated SKUs in OpenSearch

  06:48 — CloudFront query cache serving stale SERPs. stale-if-error
          engaged since 06:31 (OpenSearch red). Age header: 940 seconds.

  06:54 — On-call opens war room. Eight simultaneous symptoms (A–H).

CURRENT METRICS (06:54):
  crawl_completed_total:     5200/min (NORMAL — green dashboard)
  index_lag_seconds:         4200 and climbing (was 120 at 05:00)
  kafka_lag docs.parsed:     2.1M messages
  indexer_cpu:               94% all nodes
  search_p99_ms:             118ms (misleading — cache hits mask backend)
  search_p99_ms cache_miss:  890ms
  null_result_rate overall:  0.8%
  null_result_rate brand:    3.8%
  shard_7_state:             UNASSIGNED
  query_cache_hit_rate:      67% (elevated — stale results)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Question 1:** Eight symptoms appeared within 54 minutes. Map each symptom (A–H below) to the correct subsystem (crawl, index, query/rank, cache). Which ONE symptom is the root cause trigger, and which are amplifiers or victims? Explain the causal chain.

```
A. null_result_rate spike on brand queries (3.8%)
B. Ad CTR drop 22% with wrong doc_ids
C. Crawler queue 890M URLs, amazon.com politeness stuck
D. OpenSearch shard 7 red / UNASSIGNED
E. Top results are 404 pages crawled 6 months ago
F. Partial update 200 OK but price field missing on 15% SKUs
G. Query cache serving 940-second-old SERPs
H. index_lag_seconds 4200 while crawl rate normal
```

**Question 2:** The crawl dashboard is GREEN (5200 URLs/min). On-call junior engineer says "crawl is fine, this is a ranking bug." Explain precisely why crawl health does NOT imply search freshness. Give the metric that proves the indexing path is broken.

**Question 3:** Immediate mitigation — priority order for the next 30 minutes. For each action: expected effect, risk, and exact command or API call where applicable. What must you NOT do?

**Question 4:** Shard 7 went UNASSIGNED at 06:30. Walk through diagnosis steps to determine whether this is disk full, node crash, mapping explosion, or bad bulk index. Include exact curl/aws commands.

**Question 5:** Long-term fixes (30-day roadmap) so this compound failure cannot recur. Address: ranking deploy process, index lag SLO, cache stale-if-error policy, crawl politeness, and shard recovery.

---

> **Answer key (do not open until you attempt the Ops Sim / questions):**
> [`../answers/Week-12-Search-and-Crawling-Designs/Design Google Search Answers.md`](../answers/Week-12-Search-and-Crawling-Designs/Design%20Google%20Search%20Answers.md)

## Hands-On Exercises

```
EXERCISE 1: Build a Toy Inverted Index
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Create inverted_index.py that indexes 3 documents and answers AND queries:

  docs = {
    1: "google search engine",
    2: "search engines use inverted indexes",
    3: "google ranking algorithm"
  }

  Requirements:
    → Tokenize (lowercase, split whitespace)
    → Build term → {doc_id: tf} posting lists
    → query("google search") → intersect posting lists
    → Print results in doc_id order

  Expected output for query("google search"):
    Doc 1: terms google, search
    (Doc 3 has google but not search)


EXERCISE 2: BM25 by Hand
━━━━━━━━━━━━━━━━━━━━━━━

  Using the 3-doc corpus above, compute BM25 for query "google" against Doc 1 and Doc 3.
  Use k1=1.2, b=0.75, avgdl=4.

  Verify Doc 3 scores higher or equal (both contain "google" once).
  Compare your manual calculation to rank_bm25 Python library.


EXERCISE 3: OpenSearch Query Profile
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  If you have AWS OpenSearch access:
    1. Index 1000 sample product documents
    2. Run _search with "profile": true
    3. Identify which phase dominates latency: query vs fetch
    4. Add a filter on keyword field — measure latency change

  Questions:
    → Does filter context skip scoring? (yes — verify in profile)
    → How does shard count affect fanout time?


EXERCISE 4: PageRank Power Iteration
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Implement 4-node PageRank in Python (numpy optional):
    Links: 0→1, 0→2, 1→2, 2→0, 3→2
    d=0.85, iterate until delta < 1e-6

  Expected: node 2 has highest PageRank (most inlinks).
  Compare to NetworkX: nx.pagerank(G, alpha=0.85)


EXERCISE 5: Measure Crawl vs Index Lag
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Simulate with two scripts:
    crawl_sim.py:  writes JSON docs to Kafka/file at 1000/sec
    index_sim.py:  reads at 200/sec (intentionally slow)

  Monitor queue depth over 10 minutes.
  Calculate: at what queue depth does 5-minute freshness SLO break?

  This builds intuition for "crawl green, search stale" incidents.


EXERCISE 6: Shard Fanout Latency Model
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Assume:
    32 shards, each returns top-100 in 40ms (parallel)
    Merge heap: 0.5ms per candidate

  Calculate coordinator latency vs 128 shards.
  When does fanout dominate? (hint: tail latency of slowest shard)
```

---

## Key Takeaways

```
╔════════════════════════════════════════════════════════════════════════════╗
║   IF YOU FORGET EVERYTHING ELSE, REMEMBER THESE:                           ║
╟────────────────────────────────────────────────────────────────────────────╢
║                                                                            ║
║   1. Web search is FOUR decoupled systems — crawl, index, rank, serve.     ║
║      Each has its own metrics, failure modes, and scaling knobs.           ║
║      Never diagnose "search" as a monolith.                                ║
║                                                                            ║
║   2. Crawl success ≠ index freshness. Kafka lag (index_lag_seconds)        ║
║      is the metric that tells you if users can find newly crawled          ║
║      content. Green crawl dashboards lie during indexer backlogs.          ║
║                                                                            ║
║   3. Inverted indexes make term lookup O(log V + k); BM25 scores           ║
║      retrieval; forward indexes store doc metadata for top-K only.         ║
║      PageRank is precomputed offline — not run per query.                  ║
║                                                                            ║
║   4. Query serving = parse → fanout → intersect → merge top-K → LTR.       ║
║      Doc-id sharding fans out to all shards; hot terms need overlay        ║
║      indices or replication. Watch the slowest shard in fanout.            ║
║                                                                            ║
║   5. Compound incidents cascade: ranking deploy on stale index →           ║
║      null results → shard overload → cache stale-if-error masks all.       ║
║      Fix infrastructure, product, and cache in parallel workstreams.       ║
╚════════════════════════════════════════════════════════════════════════════╝
```

---

## Targeted Reading

```
REQUIRED:
  1. Brin & Page, "The Anatomy of a Large-Scale Hypertextual Web Search Engine" (1998)
     https://research.google/pubs/pub199/
     → Sections 2–4: crawl architecture, inverted index, PageRank
     → 45 minutes. The foundational paper — still accurate on structure.

  2. Elasticsearch Guide: "How a search query works"
     https://www.elastic.co/guide/en/elasticsearch/reference/current/query-dsl.html
     → Inverted index, BM25, bool query filter vs must context
     → 30 minutes. Directly applicable to OpenSearch.

  3. AWS OpenSearch Service Developer Guide: "Sizing Amazon OpenSearch Service domains"
     https://docs.aws.amazon.com/opensearch-service/latest/developerguide/sizing-domains.html
     → Instance sizing, shard count, UltraWarm tier
     → 20 minutes.

  4. Manning, Raghavan, Schütze — Introduction to Information Retrieval
     → Chapter 4 (Inverted Index), Chapter 6 (Scoring), Chapter 21 (Web Search)
     → Free online: https://nlp.stanford.edu/IR-book/

OPTIONAL:
  5. Google Research: "Large-scale Incremental Processing Using Distributed
     Transactions and Notifications" (Percolator / Caffeine indexing)
     → How Google moved from batch to continuous indexing

  6. Microsoft Bing blog: Index serving and shard management posts
     → Practical term vs doc-id sharding tradeoffs at scale

  7. Week 7 module: Search Systems and Inverted Indexes (this repo)
     → OpenSearch cluster ops, Query DSL, CDC ingestion patterns

  8. Week 12 module: Design Web Crawler (this repo)
     → URL frontier, politeness, dedup — crawl subsystem deep dive
```

---

---

## Design Gates (mandatory)

Answer these before calling the design complete. Keep responses concise in the
learner notes; compare against the answer key only after attempting the gates.

> Gate template: [`../templates/DESIGN_MODULE_GATES.md`](../templates/DESIGN_MODULE_GATES.md)
> Model responses: [`../answers/Week-12-Search-and-Crawling-Designs/Design Google Search Answers.md`](../answers/Week-12-Search-and-Crawling-Designs/Design%20Google%20Search%20Answers.md)

### Gate 1 - Authn/z trust boundary

1. Who is authenticated in this design: end user, admin, service, device, worker, tenant, or partner?
2. Where does the first untrusted request cross into your trusted control plane?
3. Which component makes the final authorization decision for each protected object or action?
4. What identity artifact is accepted: session cookie, bearer token, API key, mTLS SPIFFE ID, signed URL, or job identity?
5. What does the system do when the identity provider, policy store, or trust bundle is unavailable?

### Gate 2 - Abuse and misuse

6. Which actor can generate the largest write amplification or fan-out?
7. Which endpoint or background job can be abused while still authenticated?
8. What per-user, per-tenant, per-key, per-IP, per-region, and global quotas are required?
9. What telemetry distinguishes a legitimate flash crowd from abuse or scraping?
10. Which retry policy could amplify a partial outage into a full outage?

### Gate 3 - Multi-tenant isolation, if multi-tenant

11. What is the tenancy model for API, database, cache, queue/topic, search/index, and object storage?
12. Where is tenant context required, and how is it propagated through async jobs and support tools?
13. Which shared resource has reserved capacity or fair-share limits per tenant or tier?
14. How can one tenant be throttled, disabled, migrated, or isolated without affecting others?
15. What test proves a tenant cannot read another tenant's data through cache, search, export, or logs?

### Gate 4 - Unit cost at target scale

16. What is the business unit for cost: request, message, ride, order, document, query, minute, or tenant?
17. At the stated target scale and peak multiplier, what is the rough unit cost?
18. Which line items dominate: compute, storage, replication, egress, NAT, observability, ML inference, third-party APIs, or idle headroom?
19. What cost metric pages before margin, budget, or SLO error budget is breached?
20. What graceful degradation lowers cost without damaging the correctness-critical path?

### Gate 5 - Failure blast radius

21. What is the smallest unit that can fail independently: partition, shard, cell, topic, region, tenant, cache key, model, worker pool, or queue?
22. Which dependencies are shared between critical and non-critical paths?
23. What fails closed, what serves stale, and what can be disabled first?
24. Which runbook action could accidentally widen blast radius?
25. What game day proves the blast radius stays inside the intended boundary?
