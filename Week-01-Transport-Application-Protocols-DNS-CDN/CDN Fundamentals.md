# Topic 6: CDN Fundamentals

## Learning Objectives

```
╔══════════════════════════════════════════════════════════════╗
║   AFTER THIS TOPIC, YOU WILL BE ABLE TO:                     ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   1. Explain how a CDN works end-to-end: from origin         ║
║      server to edge node to user, including cache            ║
║      hierarchies, cache keys, and invalidation               ║
║                                                              ║
║   2. Distinguish between Push CDN and Pull CDN and           ║
║      choose the right model for a given system               ║
║                                                              ║
║   3. Design a CDN caching strategy for a real system         ║
║      (static assets, dynamic API responses, video            ║
║      streaming) with correct cache headers                   ║
║                                                              ║
║   4. Diagnose CDN-related production incidents:              ║
║      stale content, cache stampedes, origin overload,        ║
║      cache poisoning, and geographic inconsistency           ║
║                                                              ║
║   5. Calculate CDN cache hit ratios, estimate origin         ║
║      load reduction, and know when a CDN helps vs            ║
║      when it doesn't                                         ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔══════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "CDN = faster hosting"                        ║
╟──────────────────────────────────────────────────────────────────╢
║   WRONG. A CDN is a distributed CACHE with optional edge         ║
║   compute. It does not replace origin capacity planning.         ║
║   On cache miss, you still hit origin — often harder during      ║
║   incidents (thundering herd, purge storms).                     ║
╠══════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "Set a long max-age and forget it"            ║
╟──────────────────────────────────────────────────────────────────╢
║   WRONG. TTL without invalidation strategy = stale content       ║
║   during deploys. Versioned URLs (content-hash filenames)        ║
║   are the gold standard; TTL alone is not invalidation.          ║
╠══════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "Vary: Cookie fixes personalized caching"     ║
╟──────────────────────────────────────────────────────────────────╢
║   WRONG. Vary: Cookie creates per-cookie cache entries —         ║
║   cache hit ratio collapses. Authenticated pages should use      ║
║   Cache-Control: private, no-store. Never cache user-specific    ║
║   HTML at the edge without explicit, reviewed design.            ║
╠══════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "CDN hit ratio is the only metric"            ║
╟──────────────────────────────────────────────────────────────────╢
║   WRONG. 99% hit ratio with 1% miss on 1M RPS = 10K origin       ║
║   requests/sec. Track origin offload AND absolute miss RPS.      ║
╠══════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Purge fixes everything instantly"            ║
╟──────────────────────────────────────────────────────────────────╢
║   WRONG. Purge propagates in 60–300s globally. Purge storms      ║
║   can overload origin. Purge is emergency response, not a        ║
║   deployment workflow.                                           ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## Why CDNs Exist

### Foundation

```
THE FUNDAMENTAL PROBLEM: PHYSICS

Your server is in Virginia (us-east-1).
Your users are everywhere.

Speed of light in fiber: ~200,000 km/s
Round-trip distance and minimum latency:

  Virginia → New York:    550 km   →  ~5ms RTT
  Virginia → London:    5,500 km   → ~55ms RTT
  Virginia → Tokyo:    10,900 km   → ~109ms RTT
  Virginia → Sydney:   16,000 km   → ~160ms RTT
  Virginia → São Paulo: 8,000 km   → ~80ms RTT

These are PHYSICAL MINIMUMS (speed of light).
Real-world latency is 2-3x worse due to:
  → Fiber routes are not straight lines
  → Router hops add processing delay
  → Congestion adds queuing delay

Actual RTT Virginia → Tokyo: ~180-250ms

For a webpage with 50 resources:
  50 resources × 200ms RTT = 10 seconds minimum
  (Even with HTTP/2 multiplexing, TCP slow start
   and congestion control still limit throughput
   on high-latency links)

THE SOLUTION: Put copies of your content CLOSER to users.

  Instead of Virginia → Tokyo (200ms):
  Tokyo CDN edge → Tokyo user (5ms)

  40x faster. That's what a CDN does.
```

## What IS a CDN?

```
CDN = Content Delivery Network

A GLOBALLY DISTRIBUTED NETWORK of servers (called
"edge nodes" or "Points of Presence" / PoPs) that
cache copies of your content close to end users.

SCALE OF MAJOR CDNs:

  Cloudflare:  ~310 cities, 120+ countries
  Akamai:      ~4,100 PoPs, 135+ countries
  AWS CloudFront: ~600 PoPs, 90+ cities
  Fastly:      ~80 PoPs, optimized for performance
  Google CDN:  ~187 PoPs (same network as Google Search)

WHAT CDNs SERVE:

  Static content (the original use case):
    → Images (JPEG, PNG, WebP, AVIF)
    → CSS, JavaScript files
    → Fonts (WOFF2)
    → Video files (MP4, HLS segments)
    → PDF documents
    → Software downloads

  Dynamic content (modern use case):
    → API responses (with short TTLs)
    → Personalized content (using edge computing)
    → Live video streams (HLS/DASH segments)
    → WebSocket connections (edge termination)

  Security:
    → DDoS protection (absorb attack at edge)
    → WAF (Web Application Firewall)
    → Bot mitigation
    → TLS termination (reduce origin load)
```

---

## CDN Architecture — How It Actually Works

```
WITHOUT CDN:

  User (Tokyo) ─────── 200ms ─────── Origin (Virginia)
  Every request travels across the Pacific.
  Every user hits your origin server directly.

WITH CDN:

  User (Tokyo) ── 5ms ── Edge (Tokyo)
                            │
                            │ (cache miss only)
                            │
                         200ms
                            │
                            ▼
                      Origin (Virginia)

  FIRST USER from Tokyo:
    Edge (Tokyo): "I don't have this. Let me fetch it."
    Edge → Origin: 200ms round trip
    Edge caches the response.
    Edge → User: serves from cache
    Total: ~200ms (same as no CDN, first request)

  EVERY SUBSEQUENT USER from Tokyo:
    Edge (Tokyo): "I have this cached!"
    Edge → User: 5ms
    Origin is never contacted.
    Total: 5ms (40x faster)
```

### The Full Request Flow

```
STEP BY STEP: User requests https://cdn.example.com/logo.png

1. DNS RESOLUTION
   User's browser resolves cdn.example.com
   → CDN's DNS (Route 53, Cloudflare DNS, etc.) uses
     GeoDNS/Anycast to return the IP of the NEAREST
     edge node
   → User in Tokyo gets IP of Tokyo edge
   → User in London gets IP of London edge

   This is where CDN and DNS connect:
   The CDN USES DNS to route users to the nearest edge.

2. TLS HANDSHAKE
   User connects to the edge node via HTTPS.
   The edge node handles TLS termination.
   → Edge has the TLS certificate for cdn.example.com
   → The handshake happens with 5ms RTT (local edge)
   → NOT 200ms RTT to origin
   → TLS setup alone saves ~400ms for distant users
     (TLS 1.2 = 2 RTT, at 200ms each = 400ms saved)

3. CACHE LOOKUP
   Edge node receives the HTTP request:
   GET /logo.png HTTP/2
   Host: cdn.example.com

   Edge checks its local cache:

   CACHE HIT:
     → File exists in edge cache
     → TTL hasn't expired
     → Return cached response immediately
     → Response header: X-Cache: HIT
     → Total latency: ~5ms
     → Origin never contacted

   CACHE MISS:
     → File not in cache, OR TTL expired
     → Edge must fetch from origin
     → Proceed to step 4

4. ORIGIN FETCH (cache miss only)
   Edge connects to origin server:
   → Some CDNs keep persistent connections to origin
     (connection pooling, avoids TCP handshake overhead)
   → Edge sends the request to origin
   → Origin responds with the content + cache headers

   Origin response:
   HTTP/2 200 OK
   Content-Type: image/png
   Cache-Control: public, max-age=86400
   ETag: "abc123"
   Content-Length: 45678

   [binary image data]

5. EDGE CACHES AND SERVES
   Edge stores the response in its local cache.
   Edge returns the response to the user.

   Response to user includes CDN-specific headers:
   X-Cache: MISS          (first request — origin fetch)
   X-Cache-Hits: 0
   Age: 0                 (just cached, age = 0 seconds)
   CF-Cache-Status: MISS  (Cloudflare-specific)

6. SUBSEQUENT REQUESTS
   Next user in Tokyo requests the same file:

   Edge checks cache → HIT
   Response:
   X-Cache: HIT
   X-Cache-Hits: 847
   Age: 3600              (cached 1 hour ago)
   Cache-Control: public, max-age=86400

   No origin contact. 5ms response.
```

### Cache Hierarchy (Shield / Mid-Tier)

```
Large CDNs don't just have edge → origin.
They have a HIERARCHY:

  User → Edge (Tokyo) → Shield (US-West) → Origin (Virginia)

  ╔══════════════════════════════════════════════════════════════╗
  ║                                                              ║
  ║   Edge Layer (hundreds of PoPs worldwide)                    ║
  ║   ╭─────╮ ╭─────╮ ╭─────╮ ╭─────╮ ╭─────╮                    ║
  ║   │Tokyo│ │Seoul│ │Delhi│ │Dubai│ │Lagos│ ...                ║
  ╚══════════════════════════════════════════════════════════════╝
  │     │       │       │       │       │                │
  │     ╰───────┴───────┴───┬───┴───────╯                │
  │                         │                            │
  │  Shield Layer (few regional PoPs)                    │
  │                    ╔══════════════════════════════════════════════════════════════╗
  │                    ║                     │ US-West │                              ║
  │                    ║                     │ Shield  │                              ║
  │                    ╚══════════════════════════════════════════════════════════════╝
  │                         │                            │
  │  Origin                 │                            │
  │                    ╔══════════════════════════════════════════════════════════════╗
  │                    ║                     │ Virginia│                              ║
  │                    ║                     │ Origin  │                              ║
  │                    ╚══════════════════════════════════════════════════════════════╝
  │                                                      │
  ╰──────────────────────────────────────────────────────╯

WHY A SHIELD LAYER?

Without shield:
  Cache miss at Tokyo edge  → hits origin
  Cache miss at Seoul edge  → hits origin
  Cache miss at Delhi edge  → hits origin
  100 edge PoPs with cache miss = 100 origin requests
  For the SAME content!

  If content just expired (TTL) across all edges
  simultaneously → thundering herd on origin

With shield:
  Cache miss at Tokyo edge  → hits shield (US-West)
  Cache miss at Seoul edge  → hits shield (US-West)
  Cache miss at Delhi edge  → hits shield (US-West)
  Shield has the content cached → serves all three
  Only ONE shield miss = ONE origin request

  Origin sees 1 request instead of 100.
  Shield absorbs the thundering herd.

Cloudflare: "Tiered Caching"
CloudFront: "Origin Shield"
Fastly:     "Shielding"
Akamai:     "Tiered Distribution"
```

---

## Cache Control Headers (You MUST Know These)

These HTTP headers control how CDNs (and browsers) cache your content. Getting these wrong causes some of the worst CDN incidents.

```
CACHE-CONTROL (the primary mechanism):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Cache-Control: public, max-age=86400

  public:    Any cache can store this (CDN, browser, proxy)
  private:   Only the browser can cache (NOT CDN)
             Use for: personalized content, user-specific data
  max-age=N: Cache for N seconds
  s-maxage=N: Like max-age but ONLY for shared caches (CDN)
             Overrides max-age for CDN while browser uses max-age
  no-cache:  Cache the response BUT revalidate with origin
             before using it. Does NOT mean "don't cache"!
  no-store:  Do NOT cache AT ALL. Not in CDN, not in browser.
             Use for: sensitive data (bank balances, PII)
  must-revalidate: After max-age expires, MUST revalidate
             (don't serve stale content)
  stale-while-revalidate=N: Serve stale content for up
             to N seconds while revalidating in background
  stale-if-error=N: If origin is down, serve stale content
             for up to N seconds rather than returning error
  immutable: Content will NEVER change. Don't even revalidate.
             Use for: versioned assets (app.v2.3.1.js)

COMMON PATTERNS:

  Static assets (versioned — app.abc123.js):
    Cache-Control: public, max-age=31536000, immutable
    → Cache for 1 year. Never changes (filename includes hash)
    → Browser won't even make a conditional request
    → MAXIMUM caching efficiency

  Static assets (unversioned — logo.png):
    Cache-Control: public, max-age=86400
    → Cache for 24 hours
    → After 24 hours, revalidate

  API response (dynamic but cacheable):
    Cache-Control: public, s-maxage=60, max-age=0
    → CDN caches for 60 seconds
    → Browser always revalidates (max-age=0)
    → User always gets fresh data from CDN
    → CDN absorbs load (only hits origin once per minute)

  API response (with graceful degradation):
    Cache-Control: public, s-maxage=60,
      stale-while-revalidate=300, stale-if-error=86400
    → CDN caches for 60 seconds
    → After 60s: serve stale while fetching fresh (up to 5 min)
    → If origin is DOWN: serve stale for up to 24 hours
    → Users never see an error, even during origin outage
    → THIS IS INCREDIBLY POWERFUL for resilience

  Personalized content (user dashboard):
    Cache-Control: private, no-cache
    → CDN does NOT cache (it's user-specific)
    → Browser caches but revalidates every time

  Sensitive data (bank account):
    Cache-Control: no-store
    → Nobody caches this. Ever.
    → Must be fetched fresh every time.


ETAG AND CONDITIONAL REQUESTS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Origin response:
    ETag: "abc123"
    Cache-Control: public, max-age=3600

  After 3600 seconds, cache expired. Edge revalidates:

  Edge → Origin:
    GET /logo.png
    If-None-Match: "abc123"     ← "Is this still valid?"

  If unchanged:
    Origin → Edge:
      304 Not Modified          ← "Yes, still valid"
      (NO body — saves bandwidth!)
    Edge refreshes TTL, serves cached content

  If changed:
    Origin → Edge:
      200 OK
      ETag: "def456"            ← New version
      [new file data]
    Edge updates cache, serves new content

  WHY THIS MATTERS:
  → 304 responses are TINY (just headers, no body)
  → For a 5MB image: saves 5MB of transfer
  → Reduces origin bandwidth by 80-90% for unchanged content
  → Combined with stale-while-revalidate: users never wait
    for revalidation


VARY HEADER (cache key modifier):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Vary: Accept-Encoding
  → Cache separate copies for different encodings:
    /page → gzip compressed version
    /page → brotli compressed version
    /page → uncompressed version

  Vary: Accept-Language
  → Cache separate copies per language:
    /page → English version
    /page → Japanese version
    /page → Spanish version

  Vary: Cookie
  → Cache separate copies per cookie value
  → WARNING: This effectively DISABLES caching!
  → Every user has different cookies
  → Every user gets a unique cache entry
  → CDN cache becomes useless
  → NEVER use Vary: Cookie unless you know exactly
    what you're doing

  CACHE KEY = URL + Vary headers
  → /logo.png with Vary: Accept-Encoding has 3 cache entries
  → /logo.png with Vary: Cookie has millions of cache entries
```

---

## Push CDN vs Pull CDN

```
PULL CDN (most common):
━━━━━━━━━━━━━━━━━━━━━━

  Origin exists. CDN pulls content ON DEMAND.

  First request: Edge doesn't have content → fetches from origin
  Subsequent: Edge serves from cache

  ╔══════════════════════════════════════════════════════════════╗
  ║ User │──req───►│ Edge │──miss──►│ Origin                     ║
  ║      │◄─resp───│      │◄─resp───│                            ║
  ╚══════════════════════════════════════════════════════════════╝
                     │
                     │ (stores in cache)
                     │
  ╭─────╮         ╭──────╮
  │User │──req───►│ Edge │ (cache hit — serves directly)
  │     │◄─resp───│      │
  ╰─────╯         ╰──────╯

  ADVANTAGES:
    → Simple configuration
    → No pre-provisioning needed
    → Automatic — just point DNS at CDN
    → Only caches content that's actually requested
    → No wasted storage

  DISADVANTAGES:
    → First request is slow (origin fetch)
    → Cache miss storm possible for new content
    → Origin must be available for cache misses

  USED BY: CloudFront, Cloudflare, Fastly, Akamai
  USE CASE: Websites, APIs, general content delivery


PUSH CDN:
━━━━━━━━━━

  Content is PRE-UPLOADED to the CDN before users request it.
  No origin server needed at request time.

  ╭────────╮         ╭──────╮
  │ Origin │──push──►│ Edge │ (pre-populated)
  ╰────────╯         ╰──────╯

  Later:
  ╭─────╮         ╭──────╮
  │User │──req──►│ Edge │ (always a cache hit)
  │     │◄─resp──│      │
  ╰─────╯         ╰──────╯

  ADVANTAGES:
    → No cold cache — content always available
    → No origin fetch latency on first request
    → Origin can be offline after push
    → Predictable performance (always cache hit)

  DISADVANTAGES:
    → Must explicitly upload/manage content
    → Storage costs for all content on all edges
    → Must manage invalidation manually
    → Complex deployment pipeline

  USED BY: Netflix (Open Connect), game download CDNs
  USE CASE: Large files, video, software updates where
            you KNOW what users will request

HYBRID (most production systems):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Pull for most content + pre-warm popular content.

  → New product launch? Pre-warm the product page
    and images on all edge nodes before the launch.
  → Regular content? Pull CDN handles it normally.
  → Netflix: pushes popular content to ISP-embedded
    servers (Open Connect Appliances) during off-peak hours.
```

---

## CDN Cache Key Design

### Staff

The cache key determines WHAT is cached as separate entries. Getting this wrong causes either stale content or cache pollution.

```
DEFAULT CACHE KEY:
  URL (scheme + host + path + query string)

  https://cdn.example.com/images/logo.png
  → One cache entry

  https://cdn.example.com/images/logo.png?v=2
  → DIFFERENT cache entry (query string differs)

CACHE KEY CUSTOMIZATION:

  Problem: Marketing adds tracking parameters

  /products?id=123&utm_source=twitter&utm_campaign=sale
  /products?id=123&utm_source=email&utm_campaign=sale
  /products?id=123

  All three return IDENTICAL content.
  But default cache key treats them as 3 different entries.
  Cache hit ratio drops dramatically.

  Fix: Configure CDN to STRIP marketing parameters
       from cache key:

  CloudFront: Cache Policy → Query strings →
              Whitelist only "id" parameter
  Cloudflare: Cache Rules → ignore query string params
              matching "utm_*"

  Now all three URLs map to one cache entry:
  cache_key = /products?id=123
  Cache hit ratio recovers.


CACHE KEY BY DEVICE TYPE:

  Mobile users get different content than desktop:
  → Different image sizes
  → Different page layouts
  → Different JavaScript bundles

  Cache key must include device type:

  CloudFront:
    Cache Policy → Include "CloudFront-Is-Mobile-Viewer" header

  cache_key = /page + desktop → desktop version
  cache_key = /page + mobile  → mobile version

  Without this: mobile users might get cached desktop
  version (or vice versa). Very common bug.


CACHE KEY BY COUNTRY (for localization):

  /products page shows prices in local currency.

  Cache key must include country:

  CloudFront:
    Cache Policy → Include "CloudFront-Viewer-Country" header

  cache_key = /products + US → USD prices
  cache_key = /products + JP → JPY prices
  cache_key = /products + GB → GBP prices

  Without this: A Japanese user might see USD prices
  cached by a previous American user. Real bug that
  has affected real e-commerce sites.
```

---

## Cache Invalidation (The Hard Problem)

```
"There are only two hard things in Computer Science:
 cache invalidation and naming things."
 — Phil Karlton

WHY IT'S HARD:

  You cached logo.png on 300+ edge nodes worldwide.
  Logo changes. How do you tell 300+ edges to stop
  serving the old version?

STRATEGY 1: TTL-BASED EXPIRATION (simplest)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Cache-Control: max-age=3600

  After 1 hour, edge revalidates with origin.
  Content naturally refreshes.

  PROBLEM: Content is stale for up to 1 hour.

  Acceptable for: Blog posts, documentation,
                  product images
  Not acceptable for: Price changes, security updates,
                      content takedowns (legal/DMCA)


STRATEGY 2: CACHE BUSTING VIA VERSIONED URLs (best for assets)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Instead of invalidating, serve a NEW URL:

  Old: /static/app.js         (cached for 1 year)
  New: /static/app.v2.js      (new URL, new cache entry)

  Or with content hash:
  Old: /static/app.abc123.js
  New: /static/app.def456.js

  The HTML page references the NEW URL.
  Old cached version is simply never requested again.
  (It eventually evicts from cache naturally.)

  ADVANTAGES:
  → Instant update (new URL = cache miss = fresh content)
  → No purge needed
  → Old and new versions coexist safely
  → Users mid-session keep working with old version
  → Atomic — no partial update states

  DISADVANTAGE:
  → Requires build pipeline to hash file contents
  → HTML must be updated with new URLs
  → HTML itself can't use this technique
    (its URL doesn't change)

  THIS IS THE INDUSTRY STANDARD for static assets.
  Every major website uses content-hashed filenames.
  Webpack, Vite, Next.js all do this automatically.


STRATEGY 3: PURGE / INVALIDATION API (for emergencies)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  CDNs provide APIs to invalidate specific URLs or patterns:

  CloudFront:
    aws cloudfront create-invalidation \
      --distribution-id E1234567890 \
      --paths "/images/logo.png" "/products/*"

    → Propagates to all edge nodes
    → Takes 5-15 minutes for full propagation
    → Costs money ($0.005 per path on CloudFront)
    → Free tier: 1,000 invalidation paths/month

  Cloudflare:
    curl -X POST \
      "https://api.cloudflare.com/client/v4/zones/{zone_id}/purge_cache" \
      -H "Authorization: Bearer $TOKEN" \
      -d '{"files":["https://cdn.example.com/logo.png"]}'

    → Much faster: ~30 seconds globally
    → No per-path cost
    → Can purge by tag, prefix, or everything

  Fastly:
    Surrogate-Key based purging (very powerful):

    Origin sets response header:
      Surrogate-Key: product-123 electronics sale-items

    To purge all content related to product 123:
      curl -X POST "https://api.fastly.com/service/{id}/purge/product-123"

    → Purges ALL URLs tagged with "product-123"
    → Sub-second global purge
    → No need to know individual URLs
    → This is the GOLD STANDARD for cache invalidation

  WHEN TO USE PURGE:
  → Emergency content takedown (legal, DMCA)
  → Price correction (wrong price displayed)
  → Security incident (cached page contains leaked data)
  → NOT for routine updates (use versioned URLs instead)
  → Purging too frequently defeats the purpose of caching


STRATEGY 4: STALE-WHILE-REVALIDATE (best of both worlds)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Cache-Control: public, max-age=60, stale-while-revalidate=3600

  Timeline:

  0-60 seconds: Serve from cache (fresh)
  60-3660 seconds: Serve STALE from cache immediately
                   AND fetch fresh content in background
  After 3660: Must fetch fresh before serving

  USER EXPERIENCE:
  → User ALWAYS gets an instant response (cached)
  → Content might be up to 60 seconds stale
  → After 60 seconds, next request triggers background refresh
  → User gets stale content instantly, fresh content
    appears on NEXT request
  → No user ever waits for origin fetch

  THIS IS THE MODERN BEST PRACTICE for most content.
  Used by: Vercel, Next.js (ISR), Cloudflare, most modern CDNs
```

---

## CDN for Different Content Types

```
STATIC WEBSITE ASSETS:
━━━━━━━━━━━━━━━━━━━━━

  index.html:
    Cache-Control: public, max-age=0, must-revalidate
    → Always revalidate HTML (it contains links to
      versioned assets)
    → But ETag means 304 responses are tiny

  app.abc123.js:
    Cache-Control: public, max-age=31536000, immutable
    → Cache forever. Filename changes when content changes.

  styles.def456.css:
    Cache-Control: public, max-age=31536000, immutable
    → Same as JS — versioned filename.

  images/hero.jpg:
    Cache-Control: public, max-age=86400
    → Cache 24 hours. Revalidate after.
    → Or use versioned URL for instant updates.


API RESPONSES:
━━━━━━━━━━━━━━

  GET /api/products (product listing — same for all users):
    Cache-Control: public, s-maxage=60,
      stale-while-revalidate=300
    → CDN caches for 60s
    → Stale for up to 5 min while revalidating
    → 1000 users/second → only 1 origin request/minute
    → 999 requests/second served from edge

  GET /api/products/123 (individual product):
    Cache-Control: public, s-maxage=300,
      stale-while-revalidate=3600, stale-if-error=86400
    → CDN caches for 5 minutes
    → Stale up to 1 hour while revalidating
    → If origin down, serve stale for 24 hours
    → Product pages stay available during outages

  GET /api/user/profile (personalized):
    Cache-Control: private, no-cache
    → CDN does NOT cache (user-specific)
    → Browser caches, revalidates each time

  POST /api/orders (write operation):
    Cache-Control: no-store
    → Never cache. Ever.


VIDEO STREAMING (HLS/DASH):
━━━━━━━━━━━━━━━━━━━━━━━━━━

  manifest.m3u8 (playlist file):
    Cache-Control: public, max-age=2
    → Very short cache — playlist updates frequently
      for live streams
    → For VOD: can cache longer (max-age=3600)

  segment_001.ts (video chunk):
    Cache-Control: public, max-age=86400, immutable
    → Segments are immutable once created
    → Cache aggressively
    → New segments get new filenames

  This is how Netflix, YouTube, Twitch CDNs work:
  → Short-lived manifest pointing to long-lived segments
  → Segments cached aggressively (they never change)
  → Manifest refreshed frequently (to add new segments)
```

---

## CDN Performance Metrics

```
CACHE HIT RATIO (the most important CDN metric):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Cache Hit Ratio = cache hits / total requests × 100%

  Target ratios:
    Static website:     95-99%
    E-commerce:         80-95%
    API responses:      60-80%
    Personalized:       0-30%
    Video streaming:    95-99%

  If your ratio is below target:
    → Investigate cache key configuration
    → Check for Vary: Cookie or Vary: Authorization
    → Check for query string pollution
    → Check TTL (too short = low hit ratio)
    → Check content variety (long tail of unique URLs
      = naturally lower hit ratio)

ORIGIN OFFLOAD:
━━━━━━━━━━━━━━

  How much traffic the CDN absorbs:

  Without CDN: 100,000 requests/sec hit origin
  With CDN (95% hit ratio): 5,000 requests/sec hit origin

  Origin load reduced by 95%.
  You need 20x fewer origin servers.
  THIS is the primary operational value of a CDN.

BANDWIDTH SAVINGS:
━━━━━━━━━━━━━━━━━

  CDN serves from edge → your origin egress drops.

  Without CDN: 10 TB/day origin egress
  With CDN (95% hit): 500 GB/day origin egress

  AWS data transfer: ~$0.09/GB
  Savings: 9,500 GB × $0.09 = $855/day = $25,650/month
  CDN cost: often less than the bandwidth savings
  → CDN PAYS FOR ITSELF in bandwidth savings alone

LATENCY METRICS:
━━━━━━━━━━━━━━━

  Time to First Byte (TTFB):
    Cache hit:  5-30ms (edge to user)
    Cache miss: 50-300ms (edge to origin to user)

    Monitor: TTFB distribution
    Alert on: p99 TTFB > 500ms (likely cache misses
              or origin issues)

  Cache Hit Latency vs Miss Latency:
    Track separately. If miss latency is climbing,
    origin is struggling.
```

---

## Edge Computing (CDN as Compute Platform)

### Principal stretch

```
Modern CDNs aren't just caches — they run CODE at the edge.

PLATFORMS:
  → Cloudflare Workers
  → AWS CloudFront Functions / Lambda@Edge
  → Fastly Compute@Edge
  → Vercel Edge Functions
  → Deno Deploy

WHAT YOU CAN DO AT THE EDGE:

  1. A/B TESTING
     Edge decides which version to serve:
     → No origin request needed
     → Instant decision based on cookie/header
     → Consistent assignment per user

  2. AUTHENTICATION
     Edge validates JWT tokens:
     → Invalid token → 401 response (5ms, from edge)
     → Don't waste origin resources on unauthenticated requests

  3. GEOLOCATION-BASED CONTENT
     Edge knows user's location:
     → Redirect to country-specific page
     → Show local pricing
     → Block restricted regions (sanctions compliance)

  4. IMAGE TRANSFORMATION
     Edge resizes/converts images on the fly:
     → /image.jpg?w=300&format=webp
     → Edge fetches original from origin once
     → Transforms at edge, caches the result
     → Different sizes cached as different cache entries
     → Cloudflare Image Resizing, CloudFront Functions

  5. API RESPONSE AGGREGATION
     Edge combines multiple API calls:
     → Client makes one request to edge
     → Edge makes 3 origin requests in parallel
     → Combines responses, returns to client
     → Saves 2 round trips for the client

  6. BOT PROTECTION
     Edge identifies and blocks bots:
     → Challenge suspicious traffic (CAPTCHA)
     → Rate limit by IP/session
     → Block known bad user agents
     → All without touching your origin

LIMITATIONS:
  → Execution time limits (usually 10-50ms CPU time)
  → Memory limits (128MB typically)
  → No persistent storage (must use KV stores or origin)
  → Cold start latency on some platforms (Lambda@Edge: 5-50ms)
  → Debugging is harder (logs distributed across 300+ PoPs)
```

---

## Origin Shield (Tiered Caching)

A plain CDN has one problem at scale: **every PoP is an independent cache**.
On a cache miss, each of ~300 PoPs fetches from your origin separately. A new
video or a purge can trigger 300 simultaneous origin fetches for the *same*
object. Origin shield inserts a **mid-tier cache** between the edge PoPs and
your origin so the origin sees at most one fetch per object.

```
WITHOUT ORIGIN SHIELD (flat CDN):

   Edge PoP (Tokyo) ──miss──┐
   Edge PoP (London) ─miss──┤
   Edge PoP (NYC) ───miss───┼──────► ORIGIN (Virginia)
   Edge PoP (Sydney) miss───┤        (gets 300 identical
   ... 300 PoPs ────────────┘         requests for one object)

WITH ORIGIN SHIELD (tiered):

   Edge PoP (Tokyo) ──miss──┐
   Edge PoP (London) ─miss──┤        ┌──────────────┐
   Edge PoP (NYC) ───miss───┼──miss──► ORIGIN SHIELD │──1 fetch──► ORIGIN
   Edge PoP (Sydney) miss───┤        │ (one chosen   │  (sees ONE
   ... 300 PoPs ────────────┘        │  mid-tier PoP)│   request)
                                      └──────────────┘
   All 300 edges collapse onto ONE shield PoP.
   Shield does request coalescing → origin sees 1 request.
```

```
WHY IT MATTERS (the math):

  Cold object, 300 PoPs, no shield:
    300 origin fetches × 200ms each = origin fan-in spike
    A purge of a popular asset = 300 concurrent misses = origin overload

  Same object with shield:
    300 edge misses → 1 shield → 1 origin fetch
    99.7% origin request reduction on cold-cache events

  Offload improvement is largest for:
    → Long-tail content (many objects, low per-object hit rate)
    → Large libraries (news sites, catalogs) where each PoP rarely
      has the object a given user wants
```

```
AWS SPECIFICS — CloudFront Origin Shield:

  Enable per-origin in the distribution's origin settings.
  Choose the shield Region CLOSEST TO YOUR ORIGIN (not to users):
    Origin in us-east-1  → shield in us-east-1
    Origin in eu-west-1  → shield in eu-west-1

  CloudFront already has a 2-tier structure (edge → regional edge
  cache). Origin Shield adds a designated 3rd coalescing tier.

  COST NOTE: Origin Shield adds a request-based fee, but usually
  saves more in reduced origin egress + origin compute. Model it
  (see cost section below) before enabling for low-traffic origins.
```

```
CACHE HIERARCHY RULE OF THUMB:

  Small object set, high hit rate      → shield optional
  Large object set, low per-PoP hits   → shield strongly recommended
  Frequent purges of popular assets    → shield prevents purge storms
  Expensive origin (dynamic compute)   → shield protects origin cost
```

---

## Multi-CDN Strategy and Failover

One CDN is a single point of failure. Major CDNs *do* have global outages
(Fastly 2021 took down large parts of the internet for ~1 hour; Cloudflare has
had control-plane incidents). For tier-1 availability you run **two or more
CDNs** and steer traffic between them.

```
WHY MULTI-CDN:

  1. RESILIENCE — one CDN has a global outage, fail over to the other
  2. PERFORMANCE — different CDNs are faster in different regions
     (Akamai strong in Asia, Fastly strong in US/EU, etc.)
  3. COST — negotiate/commit traffic across vendors, arbitrage egress
  4. FEATURE COVERAGE — one CDN's edge compute, another's media pipeline
```

```
HOW TRAFFIC IS STEERED (the control plane is DNS or a traffic manager):

  ┌────────────┐
  │  Client    │  resolves cdn.example.com
  └─────┬──────┘
        │  DNS query
        ▼
  ┌──────────────────────────┐   Health checks + RUM data decide
  │  Traffic manager / GSLB   │   which CDN to hand back per query:
  │  (Route 53, NS1, Cedexis) │     → weighted (80% CDN-A / 20% CDN-B)
  └───────┬──────────┬────────┘     → geo (Asia→Akamai, US→Fastly)
          │          │              → latency (fastest per RUM)
          ▼          ▼              → failover (drop unhealthy CDN)
     ┌────────┐  ┌────────┐
     │ CDN A  │  │ CDN B  │
     └───┬────┘  └───┬────┘
         └─────┬─────┘
               ▼
           ┌────────┐
           │ Origin │ (or origin shield)
           └────────┘
```

```
AWS SPECIFICS — Route 53 for multi-CDN:

  Route 53 health checks monitor each CDN endpoint.
  Routing policies:
    → Weighted: split traffic by percentage (canary a new CDN at 5%)
    → Latency-based: send users to the lowest-latency CDN endpoint
    → Failover: primary CDN + secondary; flip on health-check failure

  DNS TTL is the failover speed limit:
    TTL=60s → up to 60s of traffic to a dead CDN before clients re-resolve
    Lower TTL = faster failover, more DNS query volume/cost
    Specialized GSLB (NS1, Cedexis/Citrix ITM) do RUM-based steering
    that DNS alone can't.
```

```
THE HARD PARTS (why multi-CDN is not free):

  1. CACHE INVALIDATION FANS OUT — every purge must hit BOTH CDNs'
     purge APIs. Miss one and users get stale content from that CDN.
  2. CONFIG DRIFT — cache rules, headers, WAF policies must stay in
     sync across vendors. Use IaC (Terraform providers per CDN).
  3. TLS CERTS — each CDN needs the cert (or ACM/shared CA).
  4. OBSERVABILITY — hit ratio, errors, latency now split across
     vendors; you need unified dashboards.
  5. COST OF WARM CACHES — two caches means two cold-start populations;
     hit ratio per CDN is lower than a single-CDN setup.

  RULE: adopt multi-CDN when availability SLA or scale justifies the
  operational tax — not by default.
```

---

## Cache Invalidation at Scale: Tags and Surrogate Keys

Purging by URL does not scale when one change affects thousands of URLs
(e.g., a product price change appears on the product page, category pages,
search results, and the home page). **Cache tags** (Fastly: *Surrogate-Key*)
let you attach labels to responses and purge everything with a label in one call.

```
THE PROBLEM WITH URL PURGES:

  Product 123 price changes. It appears on:
    /product/123
    /category/shoes
    /category/sale
    /search?q=running
    /  (home page "featured")
  You would need to know and purge ALL of them by URL. Fragile.

THE FIX — TAG THE RESPONSES:

  Origin sets a header listing tags this response belongs to:

    Surrogate-Key: product-123 category-shoes category-sale
    (Fastly)
    Cache-Tag: product-123, category-shoes, category-sale
    (Cloudflare Enterprise, Akamai uses Edge-Cache-Tag)

  Later, ONE purge call by tag invalidates every response carrying it:

    PURGE key=product-123   →  drops /product/123, /category/shoes,
                               /category/sale, /search..., / — all at once
```

```
AWS SPECIFICS — CloudFront:

  CloudFront does NOT support cache tags natively. Options:
    1. Invalidation by path pattern:  /product/123*  (up to limits;
       first 1,000 paths/month free, then billed per path)
    2. Cache-control versioning: change the object key/version so old
       cached entries are simply never requested again (preferred)
    3. Put Fastly/Cloudflare in front for tag-based purge if you need it

  DESIGN RULE: prefer versioned URLs (content-hash filenames) so you
  rarely purge at all. Reserve tag/path purge for dynamic HTML/API
  responses that cannot be versioned.
```

```
INVALIDATION STRATEGY DECISION:

  Static assets (js/css/img)   → versioned filename, cache forever, never purge
  Product/HTML pages           → cache tags (Fastly/CF-Ent) or short s-maxage
  API responses                → short s-maxage + stale-while-revalidate
  Emergency (bad/PII content)  → immediate URL/tag purge + rollback origin
```

---

## Decision Framework

```
SHOULD I PUT THIS BEHIND A CDN? (per content type)

  ┌────────────────────────────────┬────────────────────────────────────┐
  │ Content                        │ CDN decision                       │
  ├────────────────────────────────┼────────────────────────────────────┤
  │ Static assets (js/css/img/font)│ YES — versioned URL, max-age=1y    │
  │ Video / large downloads        │ YES — CDN is mandatory at scale    │
  │ Public HTML pages              │ YES — short s-maxage + SWR         │
  │ Public API (GET, cacheable)    │ MAYBE — s-maxage=30-60 + SWR       │
  │ Personalized/authenticated HTML│ NO cache — private, no-store       │
  │ Mutating API (POST/PUT/DELETE) │ NO cache — pass through            │
  │ Real-time (websocket/SSE)      │ Edge terminate; do not cache body  │
  └────────────────────────────────┴────────────────────────────────────┘

WHICH CACHE HEADER? (quick chooser)

  Never changes at this URL      → Cache-Control: public, max-age=31536000, immutable
  Changes occasionally, tolerate → public, s-maxage=300, stale-while-revalidate=60
    brief staleness
  Must be fresh but survive       → public, s-maxage=0, stale-if-error=86400
    origin outages
  User-specific / secret          → private, no-store

DO I NEED ORIGIN SHIELD?
  Large object catalog OR frequent purges OR expensive origin → YES
  Small hot object set → optional

DO I NEED MULTI-CDN?
  Availability SLA > single-CDN track record OR global scale → YES
  Otherwise → single CDN + origin shield is simpler and cheaper
```

---

## CDN Cost Model (AWS-Centric)

A CDN is not just a performance tool — at scale it is a **cost lever**. The
dominant costs are data transfer out (egress) and request fees; the dominant
*savings* are reduced origin egress and origin compute.

```
CLOUDFRONT COST COMPONENTS (illustrative — check current pricing):

  1. Data transfer out to internet   — $/GB, tiered by region and volume
       (e.g., ~$0.085/GB first 10TB in US/EU, cheaper at commit tiers;
        Asia/South America higher)
  2. Data transfer CloudFront → origin (origin fetches) — $/GB
  3. HTTP/HTTPS requests              — $ per 10,000 requests
  4. Invalidations                    — first 1,000 paths/month free, then $/path
  5. Origin Shield requests           — $ per 10,000 requests
  6. Edge compute (Functions/Lambda@Edge) — $ per invocation + duration
  7. Field-level encryption, real-time logs, etc. — add-ons

KEY SAVING: origin offload.
  S3/EC2 egress to internet is often MORE expensive than CloudFront egress.
  Serving from CloudFront can be cheaper per GB than serving from S3 directly,
  AND cuts origin compute. CloudFront→origin traffic within AWS can be free
  or reduced when origin is S3/ALB in the same account.
```

```
WORKED EXAMPLE — is the CDN paying for itself?

  Site: 100 TB/month egress, 1B requests/month, 95% cache hit ratio.

  WITHOUT CDN (serve everything from S3/ALB):
    100 TB internet egress from S3 @ ~$0.09/GB   ≈ $9,000/month
    + origin compute to serve 1B requests        ≈ large
    + terrible latency for far users

  WITH CDN (95% hit):
    ~100 TB CloudFront egress @ ~$0.085/GB (tiered) ≈ $8,500
    Origin egress only on 5% misses = 5 TB          ≈ $450
    Requests: 1B @ ~$0.01/10k                       ≈ $1,000
    ─────────────────────────────────────────────────────────
    Net: similar or lower $ AND 40x faster AND origin protected

  LEVERS THAT MOVE THE BILL THE MOST:
    → Raise cache hit ratio (fewer origin fetches = less origin egress)
    → Commit/private pricing tiers for predictable high volume
    → Compress (Brotli/gzip) at edge to cut GB transferred
    → Right-size images (WebP/AVIF at edge) — often the biggest GB saver
    → Avoid over-purging (each purge = cold misses = origin egress spike)
```

```
COST TRAPS:

  1. Caching almost nothing (low hit ratio) → you pay CDN fees AND full
     origin egress. A CDN with 40% hit ratio can cost MORE than no CDN.
  2. Vary header explosion → every variant is a separate cache entry →
     hit ratio collapses → origin egress rises.
  3. Purge storms → mass invalidation → mass cold misses → origin egress spike.
  4. Cross-region origin fetches → shield in the wrong region adds transfer.
  5. Real-time logs / per-request add-ons at 1B+ requests add up fast.
```

---

## Production Failure Patterns

### Failure 1: Cache Stampede on TTL Expiry

```
SCENARIO:
  Popular product page cached with TTL=300 seconds.
  Page receives 10,000 requests/second.
  TTL expires.
  All 10,000 requests become cache misses SIMULTANEOUSLY.
  10,000 requests hit origin in 1 second.
  Origin can handle 500 requests/second.
  Origin collapses.

  ╔══════════════════════════════════════════════════════════════╗
  ║   Requests to origin over time:                              ║
  ╟──────────────────────────────────────────────────────────────╢
  ║                                                              ║
  ║   500│        ╱╲          ╱╲          ╱╲                     ║
  ║      │       ╱  ╲        ╱  ╲        ╱  ╲                    ║
  ║   100│──────╱    ╲──────╱    ╲──────╱    ╲────               ║
  ║      │     ↑      ↑    ↑      ↑    ↑                         ║
  ║      │   TTL    recover TTL  recover TTL                     ║
  ║      │   expiry         expiry       expiry                  ║
  ║      ╰─────────────────────────────────────────              ║
  ║                                                              ║
  ║   The sawtooth pattern of cache stampede.                    ║
  ╚══════════════════════════════════════════════════════════════╝

HOW TO DETECT:
  → Origin traffic shows periodic spikes at exact
    TTL intervals
  → Origin latency spikes correlate with cache TTL expiry
  → CDN cache hit ratio drops to 0% momentarily,
    then recovers

FIX:
  → stale-while-revalidate (best fix):
    Cache-Control: public, max-age=300,
      stale-while-revalidate=60
    → After TTL, serve stale and revalidate in background
    → Only ONE request triggers revalidation
    → Other 9,999 get stale content instantly
    → Origin sees 1 request, not 10,000

  → Request coalescing (CDN feature):
    Multiple simultaneous cache misses for the same URL
    are collapsed into ONE origin request.
    CDN holds the other requests until the first one
    returns, then serves all from cache.

    Cloudflare: Enabled by default
    CloudFront: "Origin Shield" provides this
    Fastly: "Request Collapsing" setting

  → Jittered TTL:
    Instead of max-age=300 for everything:
    max-age = 270 + random(0, 60)
    Different cache entries expire at different times.
    No synchronized stampede.
```

### Failure 2: Serving Stale Content After Deployment

```
SCENARIO:
  Deploy new version of website.
  index.html references new JavaScript file: app.v2.js

  Problem: CDN still has OLD index.html cached
  (referencing app.v1.js).

  User experience:
  → Gets old HTML (from CDN cache)
  → HTML references app.v1.js
  → Gets old JavaScript
  → New features don't appear
  → OR: Old HTML references app.v1.js, but app.v1.js
    has been DELETED from origin
  → 404 errors, broken site

HOW TO DETECT:
  → Deployment succeeded but users report old version
  → View source shows old file references
  → CDN response headers show: Age: 3400 (cached long ago)
  → Different users see different versions (some caches
    expired, some haven't)

FIX:
  → Purge HTML after deploy:
    aws cloudfront create-invalidation \
      --distribution-id $DIST_ID \
      --paths "/index.html" "/"

  → Better: HTML should have short TTL or no-cache:
    Cache-Control: public, max-age=0, must-revalidate
    → HTML always revalidated
    → JS/CSS use versioned filenames (cached forever)
    → Deploy = new HTML pointing to new versioned assets
    → No purge needed

  → Best: Use Surrogate-Key based purging:
    → Tag all deployment-related content with deploy version
    → After deploy: purge the version tag
    → All old content invalidated in one API call
```

### Failure 3: Cache Poisoning

```
SCENARIO:
  Attacker finds that your CDN caches based on the
  full URL including query parameters.

  Attacker requests:
  https://example.com/login?evil=<script>alert('xss')</script>

  If your application reflects query parameters in
  the page (even in error messages) AND the CDN caches
  the response:

  → CDN caches the XSS-infected page
  → All users requesting /login get the poisoned page
  → XSS attack served from CDN to every user

  This is "Web Cache Poisoning" and is a real
  attack vector (discovered by James Kettle, 2018).

MORE SUBTLE VARIANT:
  Attacker sends:
  GET /page HTTP/1.1
  Host: example.com
  X-Forwarded-Host: evil.com

  If your app uses X-Forwarded-Host to generate URLs
  in the page AND the CDN caches:
  → Cached page contains links to evil.com
  → All users get redirected to attacker's site

HOW TO DETECT:
  → Reports of unexpected content on cached pages
  → XSS reports from security scanners
  → Pages containing content that doesn't match origin
  → Check: response content matches what origin
    would generate for a clean request

FIX:
  → ONLY include in cache key the parameters your
    application actually uses
  → Strip or ignore unknown headers at CDN level
  → Strip unknown query parameters before caching
  → Normalize URLs before cache key computation
  → Set Vary header correctly (only on headers that
    legitimately change the response)
  → Use Cloudflare/Fastly WAF rules to reject
    suspicious headers
  → Regular security testing: test CDN with
    unexpected headers/params
```

### Failure 4: Origin Overload During CDN Purge

```
SCENARIO:
  Developer runs: "purge everything" on the CDN.

  All edge nodes worldwide have empty caches.
  ALL user traffic becomes cache misses.
  ALL requests flow through to origin.

  Traffic pattern:
    Normal:    5,000 req/s to origin (5% miss rate)
    After purge: 100,000 req/s to origin (100% miss rate)

  Origin capacity: 10,000 req/s
  Origin immediately overwhelmed. Site goes down.

  AND: As origin returns errors, CDN may cache the
  ERROR responses! Now users get cached 502 errors
  even after origin recovers.

HOW TO DETECT:
  → Sudden spike in origin traffic immediately after purge
  → Origin latency/error spikes
  → CDN cache hit ratio drops to 0%
  → Potentially: error responses being cached (users
    see 502 even after origin recovers)

FIX:
  → NEVER purge everything in production
  → Purge specific paths or tags only
  → If you must purge everything:
    → Increase origin capacity FIRST
    → Purge in waves (purge one region at a time)
    → Use stale-if-error so CDN serves stale instead
      of forwarding errors:
      Cache-Control: stale-if-error=86400
      → Even after purge, if origin fails, serve stale
  → Configure CDN to NOT cache error responses:
    → CloudFront: "Error Caching Minimum TTL = 0"
    → Cloudflare: "Always Online" feature
```

### Failure 5: Geographic Inconsistency

```
SCENARIO:
  You deploy a new feature. Purge the CDN.

  Users in New York see the new feature.
  Users in Tokyo see the OLD version.
  Users in London see the new feature.
  Users in Sydney see the OLD version.

  Inconsistent experience across the globe.

WHY:
  CDN purge propagation is NOT instant.
  Each PoP processes the purge independently.
  Some PoPs clear cache in 5 seconds.
  Others take 30 seconds to 15 minutes.

  During propagation: some edges serve new, some serve old.

  ADDITIONALLY: Shield/mid-tier caches may not purge
  as quickly as edge caches. Even if the edge is purged,
  the shield might still have old content and re-populate
  the edge with stale data.

HOW TO DETECT:
  → User reports: "I see the old version"
  → curl from different regions shows different content
  → CDN response Age header varies wildly across regions

FIX:
  → Versioned URLs (eliminates the problem entirely)
  → After purge, verify from multiple regions:
    curl -H "X-CDN-Debug: 1" https://cdn.example.com/page
    → Check from US, EU, Asia
  → Accept that purge-based invalidation has an
    inherent consistency window
  → For critical updates: use versioned URLs, not purges
```

---

## SRE Diagnostic Toolkit

```
CDN DEBUGGING:
━━━━━━━━━━━━━

# Check if response came from CDN cache
curl -sI https://cdn.example.com/page | \
  grep -iE "x-cache|cf-cache|age|cache-control"

# Output interpretation:
#   X-Cache: Hit from cloudfront     → CDN cache hit
#   X-Cache: Miss from cloudfront    → Origin fetch
#   CF-Cache-Status: HIT             → Cloudflare cache hit
#   CF-Cache-Status: MISS            → Cloudflare miss
#   CF-Cache-Status: DYNAMIC         → Not cacheable
#   Age: 3600                        → Cached 1 hour ago
#   Cache-Control: public, max-age=86400 → Cacheable for 24h

# Check cache headers from origin directly (bypass CDN)
# CloudFront: Use origin domain directly
curl -sI https://origin.example.com/page | \
  grep -iE "cache-control|etag|vary|surrogate"

# Force cache miss (get fresh content)
# Add cache-busting query param:
curl -sI "https://cdn.example.com/page?nocache=$(date +%s)"

# Check what cache key CDN is using
# CloudFront: Enable access logging, check cs-uri-stem and cs-uri-query
# Cloudflare: Use cf-cache-status and cf-ray headers

# Compare CDN response across regions
# Using KeyCDN's tool or manually:
for region in us-east eu-west ap-northeast; do
  echo "=== $region ==="
  curl -sI "https://cdn.example.com/page" \
    -H "X-Debug-Region: $region" | grep -i "x-cache\|age"
done

# Measure cache hit ratio from logs
# CloudFront access logs:
# Count "Hit" vs "Miss" in x-edge-result-type field
cat cloudfront-logs.gz | zcat | \
  awk '{print $13}' | sort | uniq -c | sort -rn
# Output:
#   894521  Hit
#    45123  Miss
#    12345  Error
# Hit ratio: 894521 / (894521 + 45123) = 95.2%

# Check if specific content is cached
curl -sI https://cdn.example.com/products/123 | \
  grep -i "x-cache"
# If MISS on content that should be cached:
#   → Check Cache-Control header from origin
#   → Check for Set-Cookie (prevents caching)
#   → Check Vary header (too broad = no effective caching)
#   → Check for Authorization header (prevents caching)

# Purge specific path (CloudFront)
aws cloudfront create-invalidation \
  --distribution-id E1234567890 \
  --paths "/products/123" "/products/456"

# Check invalidation status
aws cloudfront get-invalidation \
  --distribution-id E1234567890 \
  --id I1234567890

# Purge specific path (Cloudflare)
curl -X POST \
  "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/purge_cache" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"files":["https://cdn.example.com/products/123"]}'


COMMON "WHY ISN'T THIS CACHING?" DEBUGGING:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  PROBLEM: CDN always returns MISS

  CHECK 1: Does origin send Cache-Control?
    curl -sI https://origin.example.com/page | grep cache
    → If missing: add Cache-Control header at origin
    → If "no-store" or "private": that's why CDN won't cache

  CHECK 2: Does origin set Set-Cookie?
    curl -sI https://origin.example.com/page | grep set-cookie
    → Most CDNs refuse to cache responses with Set-Cookie
    → Fix: Don't set cookies on cacheable responses
    → Or: Configure CDN to ignore Set-Cookie for caching

  CHECK 3: Is Authorization header present?
    → Requests with Authorization header are not cached
      by default (RFC 7234)
    → Fix: Use Cache-Control: public (explicitly allows
      caching despite Authorization)

  CHECK 4: Is Vary header too broad?
    curl -sI https://origin.example.com/page | grep vary
    → Vary: * → NOTHING is cached
    → Vary: Cookie → effectively nothing cached
      (every user has different cookies)
    → Fix: Remove unnecessary Vary directives
    → Or: Configure CDN to ignore certain Vary values

  CHECK 5: Is the response too large?
    → Some CDNs have max cacheable size limits
    → CloudFront: 30GB max
    → Cloudflare free: 512MB max
```

---

## Hands-On Exercises

```
EXERCISE 1: See CDN Cache Headers In Action
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  # Check a major website's CDN headers:
  curl -sI https://www.cloudflare.com | \
    grep -iE "cache-control|cf-cache|age|x-cache|server"

  # Try multiple requests — watch Age increase:
  curl -sI https://www.cloudflare.com | grep -i "age:"
  sleep 5
  curl -sI https://www.cloudflare.com | grep -i "age:"
  # Age should increase by ~5

  # Try a site behind CloudFront:
  curl -sI https://aws.amazon.com | \
    grep -iE "x-cache|x-amz|age|cache-control"


EXERCISE 2: See Cache Miss vs Hit Latency Difference
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  # Request with cache-busting param (guaranteed miss):
  curl -w "TTFB: %{time_starttransfer}s\n" -so /dev/null \
    "https://www.cloudflare.com/?bust=$(date +%s)"

  # Request same URL (should be cached hit):
  curl -w "TTFB: %{time_starttransfer}s\n" -so /dev/null \
    "https://www.cloudflare.com/"

  # Compare TTFB — hit should be significantly faster


EXERCISE 3: Inspect Your Caching Headers
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  # If you have a web application:
  curl -sI https://your-site.com/ | \
    grep -iE "cache-control|etag|vary|set-cookie|age"

  # Ask yourself:
  # → Is Cache-Control set? If not, you're not caching.
  # → Is Set-Cookie present? If so, CDN won't cache.
  # → Is Vary: Cookie set? If so, CDN cache is useless.
  # → Is there an ETag? If not, no conditional requests.
```

---

## Targeted Reading

```
REQUIRED:
  1. Cloudflare Blog: "How CDN Caching Works"
     https://www.cloudflare.com/learning/cdn/what-is-caching/
     → 10 minute read
     → Best visual explanation of CDN caching layers

  2. MDN Web Docs: "HTTP Caching"
     https://developer.mozilla.org/en-US/docs/Web/HTTP/Caching
     → 20 minute read
     → Definitive reference for Cache-Control directives
     → Every directive explained with examples

OPTIONAL:
  3. Netflix Open Connect Overview
     https://openconnect.netflix.com/
     → How Netflix built their own push CDN
     → Embeds servers directly in ISP networks
     → Handles ~15% of global internet traffic
```

---

## Ops Sim: Northstar CloudFront Personalized Cache Leak

**Time box:** 30 minutes
**Severity:** P1
**Service / domain:** CloudFront cache behavior for account and checkout pages
**Northstar system:** Edge, Checkout, Session

### Rules

1. Answer from memory; do not re-read the CDN section mid-drill.
2. Write decisions in order (T+0 -> T+60).
3. Cite cache headers, metrics, or config for every claim.
4. Do not open the answer key until finished.

### 1. Scenario stem

```text
WHAT USERS SEE:
  Some logged-in users briefly see another user's saved shipping address on
  `/checkout/review`. No payment card numbers are rendered.

WHAT ON-CALL SEES:
  CloudFront hit rate jumped from 62% to 94% after a cache-policy cleanup.
  Origin error rate dropped, but privacy tickets started within 8 minutes.

BUSINESS CONSTRAINT:
  This is a security/privacy P1. You must stop leakage before optimizing origin
  load. Checkout may be degraded to origin-only.
```

### 2. Telemetry pack

```text
METRICS:
  CloudFront cache hit rate `/checkout/*`: 3% -> 78%
  Origin RPS: 18k -> 5k
  Support tickets: 0 -> 47 in 10 min; all logged-in checkout review page
  x-cache: Hit from cloudfront on personalized HTML
  origin p95: 190ms -> 260ms after bypass test

LOG LINES:
  response headers: Cache-Control: public, s-maxage=600, stale-while-revalidate=60
  response headers: Set-Cookie: ns_session=...; HttpOnly; Secure
  CloudFront log: cs-uri-stem=/checkout/review sc-status=200 x-edge-result-type=Hit
  app log: rendered user_id=8431 shipping_address_id=aa7 for session user_id=9122

TRACE:
  checkout-review HTML includes address fragment before client-side hydration.
```

### 3. Config pack

```yaml
# wrong/dangerous cache behavior
path_pattern: "/checkout/*"
cache_policy:
  default_ttl: 600
  headers_in_cache_key: []
  cookies_in_cache_key: []
  query_strings_in_cache_key: []
origin_request_policy:
  forward_cookies: ["ns_session"]

# intended behavior
account_and_checkout_html:
  cache_control: "private, no-store"
  cdn_cache: disabled
```

### 4. Timeline & decision points

| Time | Event | Your move (write before reading further) |
|------|-------|------------------------------------------|
| T+0 | P1: reports of wrong address on checkout review. | |
| T+5 | CloudFront confirms cache hits on `/checkout/review`. | |
| T+15 | Product asks to purge only the one URL and keep checkout cached. | |
| T+60 | Leakage stopped; origin RPS is 3.5x higher than before rollout. | |

### 5. Questions

**Q1 - Layer & root cause:** Which CDN mechanism leaked personalized data?

**Q2 - Evidence:** Which 3 signals prove CDN cache poisoning/personalized caching? Which metric looked beneficial but was dangerous?

**Q3 - Sequencing:** What do you do in the first 15 minutes?

**Q4 - Bad fix gallery:** Why is "purge one URL" insufficient? Why is "add Cookie to cache key" risky for checkout HTML?

**Q5 - Capacity / blast radius:** If bypassing CDN raises origin RPS from 5k to 18k and origin safe capacity is 22k, what headroom remains? What else must you watch?

**Q6 - Durable fix:** What cache policy and release guardrails prevent recurrence?

**Q7 - Org / runbook:** Who is informed for this privacy P1 and what is pre-authorized?

**Answer key:** [`../answers/Week-01-Transport-Application-Protocols-DNS-CDN/CDN Fundamentals Answers.md`](../answers/Week-01-Transport-Application-Protocols-DNS-CDN/CDN%20Fundamentals%20Answers.md)

---

## Key Takeaways

```
╔══════════════════════════════════════════════════════════════╗
║   IF YOU FORGET EVERYTHING ELSE, REMEMBER THESE:             ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   1. CDN puts content CLOSER to users. The primary           ║
║      benefit is LATENCY reduction (physics: speed            ║
║      of light) and ORIGIN OFFLOAD (95%+ of requests          ║
║      never reach your servers).                              ║
║                                                              ║
║   2. Cache-Control headers are how you tell CDNs             ║
║      what to cache and for how long.                         ║
║      MASTER these: public, private, max-age,                 ║
║      s-maxage, no-cache, no-store,                           ║
║      stale-while-revalidate, stale-if-error.                 ║
║      Getting these wrong causes outages.                     ║
║                                                              ║
║   3. VERSIONED URLS are the gold standard for cache          ║
║      invalidation. app.abc123.js cached forever.             ║
║      New version = new filename = automatic update.          ║
║      Purge APIs exist for emergencies, not routine.          ║
║                                                              ║
║   4. stale-while-revalidate + stale-if-error is the          ║
║      most powerful resilience pattern. Users always          ║
║      get instant responses. Origin outages become            ║
║      invisible. Use it everywhere possible.                  ║
║                                                              ║
║   5. The #1 CDN production killer is caching content         ║
║      that should NOT be cached (user-specific data,          ║
║      Set-Cookie responses, personalized pages).              ║
║      One user's data served to another user =                ║
║      privacy/security incident.                              ║
╚══════════════════════════════════════════════════════════════╝
```

---

# 🔥 SRE SCENARIO — CDN

```
INCIDENT REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Severity: P1 (SECURITY)
Service: E-commerce platform
Time: 3:15 PM

ARCHITECTURE:
  Users → Cloudflare CDN → Origin (application servers)

  CDN configuration:
    → Cache static assets (images, JS, CSS): max-age=31536000
    → Cache product pages: s-maxage=300 (5 min)
    → Cache API responses: s-maxage=60
    → User account pages (/account/*): Cache-Control
      set by application

INCIDENT:
  3:15 PM — Customer support receives an urgent call:
  "I logged into my account and I see someone else's
   account page. Their name, their address, their
   order history. This is NOT my account."

  3:18 PM — Three more reports come in. Different users
  seeing different people's account data.

  3:20 PM — Engineering investigates. They confirm:
  Hitting https://shop.example.com/account/dashboard
  from different browsers/devices returns the SAME
  user's account page (User ID: 88421) regardless
  of who is logged in.

  3:22 PM — curl confirms:

  curl -sI https://shop.example.com/account/dashboard

  HTTP/2 200
  Content-Type: text/html
  Cache-Control: public, s-maxage=300
  Set-Cookie: session=abc123
  CF-Cache-Status: HIT
  Age: 187
  Vary: Accept-Encoding

  3:24 PM — Engineering checks origin application logs.
  A deployment went out at 3:10 PM. Git diff shows a
  developer changed the account page controller:

  BEFORE:
    @CacheControl(private, no-cache)
    def account_dashboard(request):
        user = get_current_user(request)
        return render("dashboard.html", user=user)

  AFTER:
    @CacheControl(public, s_maxage=300)  # "improve performance"
    def account_dashboard(request):
        user = get_current_user(request)
        return render("dashboard.html", user=user)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Question 1:** Explain precisely what happened — trace the exact sequence from the deployment at 3:10 PM to User ID 88421's data being served to other users. Why was User 88421 the "victim" specifically?

**Question 2:** This is a SECURITY incident. What is the immediate mitigation? Give me exact actions in priority order — every second counts because PII is being exposed.

**Question 3:** The Vary header says `Accept-Encoding`. Explain why this DIDN'T prevent the problem, and what Vary value WOULD have prevented it (though it would have been the wrong fix).

**Question 4:** Long-term — what technical controls should exist so that this class of bug can NEVER make it to production, regardless of what a developer does in a controller?
> **Answer key (do not open until you attempt the scenario questions):**
> [`../answers/Week-01-Transport-Application-Protocols-DNS-CDN/CDN%20Fundamentals%20Answers.md`](../answers/Week-01-Transport-Application-Protocols-DNS-CDN/CDN%20Fundamentals%20Answers.md)
