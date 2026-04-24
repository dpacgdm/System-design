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

## Why CDNs Exist

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

# Incident Deep-Dive: CDN Cache Poisoning — PII Exposure

---

## Question 1: The Exact Sequence — From Deployment to Data Breach

### Tracing the Timeline, Request by Request

```
3:10:00 PM — Deployment goes out.
  The account_dashboard controller now returns:
    Cache-Control: public, s-maxage=300
  Instead of:
    Cache-Control: private, no-cache

  At this moment, nothing is broken yet.
  The CDN has no cached copy of /account/dashboard.
  The PREVIOUS cached version (if any) had 
  Cache-Control: private, so Cloudflare never 
  cached it. The CDN cache slot for this URL is EMPTY.
```

```
~3:10:XX PM — The FIRST user to request /account/dashboard 
              after the deployment becomes the victim.

  User 88421 (let's call her Sarah) opens her browser 
  and navigates to https://shop.example.com/account/dashboard

  REQUEST FLOW:
  
  Sarah's browser
    │
    ├─► GET /account/dashboard
    │   Cookie: session=sarah_session_token
    │
    ▼
  Cloudflare CDN Edge (e.g., Chicago POP)
    │
    │  Cloudflare checks its cache for /account/dashboard
    │  Cache key: scheme + host + path = 
    │    "https://shop.example.com/account/dashboard"
    │  Result: CACHE MISS (no cached copy exists)
    │
    │  Cloudflare forwards the request to origin, 
    │  INCLUDING Sarah's session cookie.
    │
    ├─► GET /account/dashboard
    │   Cookie: session=sarah_session_token
    │
    ▼
  Origin Application Server
    │
    │  The application:
    │    1. Reads sarah_session_token from the cookie
    │    2. Looks up Sarah's session → User ID 88421
    │    3. Queries database for Sarah's name, address, 
    │       order history
    │    4. Renders dashboard.html with SARAH'S DATA
    │    5. Returns the response with the NEW cache header:
    │
    │  HTTP/2 200
    │  Content-Type: text/html
    │  Cache-Control: public, s-maxage=300   ← THE BUG
    │  Set-Cookie: session=abc123
    │  Vary: Accept-Encoding
    │  Body: <html>Welcome, Sarah! Your address: 
    │        123 Main St... Order #4521: ...</html>
    │
    ▼
  Cloudflare CDN Edge
    │
    │  Cloudflare reads the response headers:
    │    Cache-Control: public, s-maxage=300
    │
    │  "public" → I AM ALLOWED to cache this
    │  "s-maxage=300" → Cache it for 300 seconds (5 min)
    │
    │  Cloudflare STORES Sarah's fully rendered account 
    │  page in its edge cache:
    │    Cache key: "https://shop.example.com/account/dashboard"
    │    Cache value: Sarah's complete HTML (name, address, orders)
    │    TTL: 300 seconds
    │    Stored at: ~3:10 PM
    │    Expires at: ~3:15 PM
    │
    │  Cloudflare returns the response to Sarah.
    │  Sarah sees her own account page. Everything looks normal.
    │  Sarah has NO IDEA her data just got cached publicly.
    │
    ▼
  Sarah's browser renders her account page. ✅ Looks correct.
```

```
~3:10 to 3:15 PM — EVERY subsequent user gets Sarah's data.

  User 77210 (Bob) navigates to /account/dashboard.

  Bob's browser
    │
    ├─► GET /account/dashboard
    │   Cookie: session=bob_session_token
    │
    ▼
  Cloudflare CDN Edge
    │
    │  Cloudflare checks its cache for /account/dashboard
    │  Cache key: "https://shop.example.com/account/dashboard"
    │  Result: CACHE HIT ✅ (cached 187 seconds ago)
    │
    │  Cloudflare DOES NOT forward the request to origin.
    │  It doesn't even LOOK at Bob's cookie.
    │  It returns the cached response DIRECTLY:
    │
    │  HTTP/2 200
    │  Content-Type: text/html
    │  Cache-Control: public, s-maxage=300
    │  CF-Cache-Status: HIT        ← served from cache
    │  Age: 187                    ← cached 187 seconds ago
    │  Body: <html>Welcome, Sarah! Your address: 
    │        123 Main St... Order #4521: ...</html>
    │
    ▼
  Bob's browser renders SARAH'S account page.
  Bob sees Sarah's name, address, order history.
  
  ❌ PERSONAL DATA BREACH
```

### Why User 88421 Specifically?

```
Sarah (User 88421) was not special. She was simply 
the FIRST USER to request /account/dashboard after 
the deployment at 3:10 PM that hit a Cloudflare edge 
node with an empty cache slot for that URL.

If Bob had loaded the page 0.5 seconds before Sarah,
BOB'S data would be the cached version, and SARAH 
would be the one seeing Bob's information.

The "victim" is determined by a RACE CONDITION:
  → First request after deployment + cache miss 
    = that user's data becomes the cached version
  → Every subsequent request within the 300-second 
    TTL serves that first user's data

This is also PER EDGE POP:
  → Cloudflare has 300+ Points of Presence worldwide
  → Each POP has its own independent cache
  → The "first user" at the Chicago POP might be Sarah
  → The "first user" at the London POP might be someone else
  → MULTIPLE users' PII may be exposed simultaneously 
    at different edge locations
  → This makes the breach WORSE than it appears — 
    it's not one victim, it's potentially 300+ victims 
    (one per POP that received traffic after 3:10 PM)
```

### The Evidence in the curl Output

```
curl -sI https://shop.example.com/account/dashboard

HTTP/2 200
Content-Type: text/html
Cache-Control: public, s-maxage=300    ← THE ROOT CAUSE
                                         "public" = CDN may cache
                                         "s-maxage=300" = cache for 5 min
Set-Cookie: session=abc123             ← RED FLAG: setting a cookie
                                         on a cached response means 
                                         the SESSION is being shared too
CF-Cache-Status: HIT                   ← PROOF: served from CDN cache,
                                         not from origin
Age: 187                               ← Cached 187 seconds ago
                                         (3 min 7 sec since first cache)
Vary: Accept-Encoding                  ← Only varies on encoding,
                                         NOT on Cookie/Authorization
                                         → all users get the same cache
```

---

## Question 2: Immediate Mitigation — Every Second Counts

This is a **SECURITY incident with active PII exposure**. Every second the cached content is served, another user potentially sees someone else's personal data. Priority is: **stop the bleeding, then clean up, then investigate.**

### Action 1: PURGE THE CDN CACHE — RIGHT NOW (Second 0-30)

```bash
# Purge the specific URL from ALL Cloudflare edge POPs worldwide
# This is the single fastest action to stop PII exposure.

curl -X POST "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/purge_cache" \
  -H "Authorization: Bearer $CF_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "files": [
      "https://shop.example.com/account/dashboard",
      "https://shop.example.com/account/orders",
      "https://shop.example.com/account/profile",
      "https://shop.example.com/account/addresses",
      "https://shop.example.com/account/payment-methods"
    ]
  }'

# Don't just purge /account/dashboard.
# The deployment changed the CONTROLLER — it likely 
# affects ALL /account/* routes.
# Purge EVERY account-related URL.

# If unsure which URLs are affected, PURGE EVERYTHING:
curl -X POST "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/purge_cache" \
  -H "Authorization: Bearer $CF_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"purge_everything": true}'

# Yes, this will cause a temporary cache miss storm on origin.
# That is infinitely preferable to continuing to serve PII.
# You can deal with origin load AFTER the breach is stopped.
```

### Action 2: ROLL BACK THE DEPLOYMENT — Immediately After Purge (Second 30-90)

```bash
# The cache purge stops CURRENT exposure, but the origin 
# is STILL returning Cache-Control: public, s-maxage=300.
# If you don't roll back, the NEXT request will re-populate 
# the cache with another user's data.

# Roll back to the previous revision:
kubectl rollout undo deployment/web-application

# OR if using CI/CD:
# Trigger redeploy of the last known good artifact

# VERIFY the rollback:
curl -sI https://shop.example.com/account/dashboard \
  -H "Cookie: session=test_session"

# MUST show:
#   Cache-Control: private, no-cache
#   CF-Cache-Status: DYNAMIC (not HIT)
#
# If it still shows "public, s-maxage=300", the rollback 
# hasn't propagated yet. Wait for pod rotation.
```

### Action 3: Activate Security Incident Response Protocol (Minute 2-5)

```
This is not just an engineering problem. This is a DATA BREACH.

IMMEDIATE NOTIFICATIONS (in parallel with technical mitigation):

  □ Security team / CISO
    → "Authenticated user PII served to unauthorized users 
       via CDN cache. Active exposure from 3:10 to [purge time].
       Estimated impact: all users who visited /account/* 
       during the window."
  
  □ Legal / DPO (Data Protection Officer)
    → GDPR Article 33: 72-hour notification deadline to 
      supervisory authority if EU users affected
    → CCPA: notification requirements for CA users
    → Breach involved: names, addresses, order history, 
      potentially payment method details
  
  □ Customer support team
    → Prepare for incoming reports
    → Script: "We identified a brief technical issue that 
      may have displayed incorrect account information. 
      We have resolved it. No passwords or payment card 
      numbers were exposed."
      (Adjust based on what was ACTUALLY in the page)
```

### Action 4: Assess Blast Radius (Minute 5-15)

```bash
# Determine exactly which users' data was cached and 
# which users SAW that data.

# Step 1: Check Cloudflare logs for all HIT responses 
# on /account/* between 3:10 and purge time:

# Cloudflare Enterprise logs or Logpush:
# Filter: 
#   path STARTS WITH "/account/"
#   AND CacheStatus = "hit"
#   AND timestamp BETWEEN "3:10 PM" AND "[purge time]"

# This tells you:
#   → HOW MANY requests were served cached PII
#   → FROM WHICH edge POPs (geographic impact)
#   → Client IPs (can correlate to affected users)

# Step 2: Identify the VICTIMS (users whose data was cached)
# The first MISS request to each POP after 3:10 = the victim
# Filter Cloudflare logs:
#   path STARTS WITH "/account/"
#   AND CacheStatus = "miss"
#   AND timestamp >= "3:10 PM"
#   ORDER BY timestamp ASC
#   GROUP BY EdgeColoID  (per POP)

# The first miss per POP → that user's data was cached
# Cross-reference with origin access logs to get User IDs

# Step 3: Identify VIEWERS (users who saw others' data)
# All subsequent HIT requests on the same POP in the same 
# TTL window = users who saw the victim's data
```

### Mitigation Timeline Summary

```
╭────────┬─────────────────────────────────┬───────────╮
│ TIME   │ ACTION                          │ IMPACT    │
├────────┼─────────────────────────────────┼───────────┤
│ +0s    │ Purge CDN cache (all /account/* │ STOPS     │
│        │ or purge_everything)            │ exposure  │
├────────┼─────────────────────────────────┼───────────┤
│ +30s   │ Roll back deployment            │ PREVENTS  │
│        │                                 │ recurrence│
├────────┼─────────────────────────────────┼───────────┤
│ +60s   │ Verify: Cache-Control: private  │ CONFIRMS  │
│        │ CF-Cache-Status: DYNAMIC        │ fix       │
├────────┼─────────────────────────────────┼───────────┤
│ +2min  │ Notify security/legal/support   │ COMPLIANCE│
├────────┼─────────────────────────────────┼───────────┤
│ +5min  │ Analyze logs for blast radius   │ SCOPE     │
├────────┼─────────────────────────────────┼───────────┤
│ +15min │ Notify affected users           │ TRUST     │
╰────────┴─────────────────────────────────┴───────────╯
```

---

## Question 3: The Vary Header — Why Accept-Encoding Didn't Help

### What the Vary Header Does

```
The Vary header tells the CDN:
"This response varies depending on the value of 
[specified request header]. Create SEPARATE cache 
entries for each unique value of that header."

The response has:
  Vary: Accept-Encoding

This means Cloudflare creates separate cache entries for:
  → Accept-Encoding: gzip       → cached copy A (gzipped)
  → Accept-Encoding: br         → cached copy B (brotli)
  → Accept-Encoding: identity   → cached copy C (uncompressed)

So the cache key becomes:
  "https://shop.example.com/account/dashboard" + Accept-Encoding value
```

### Why It DIDN'T Prevent the Problem

```
Vary: Accept-Encoding varies on COMPRESSION FORMAT,
not on USER IDENTITY.

When Bob requests /account/dashboard:
  Bob's request: Accept-Encoding: gzip
  Cache key: URL + "gzip"
  
  Sarah's cached entry was ALSO Accept-Encoding: gzip
  (virtually all modern browsers send identical 
   Accept-Encoding headers)
  
  Cache key matches → CACHE HIT → Bob gets Sarah's data

  Bob and Sarah have different session cookies.
  But the Vary header doesn't include Cookie.
  So the CDN doesn't even LOOK at the cookie 
  when computing the cache key.

  ╔══════════════════════════════════════════════════════════════╗
  ║   SARAH'S REQUEST:                                           ║
  ║     URL: /account/dashboard                                  ║
  ║     Accept-Encoding: gzip, br                                ║
  ║     Cookie: session=sarah_token                              ║
  ║                                                              ║
  ║   Cache key (what CDN uses):                                 ║
  ║     /account/dashboard + gzip,br                             ║
  ║                                                              ║
  ║   BOB'S REQUEST:                                             ║
  ║     URL: /account/dashboard                                  ║
  ║     Accept-Encoding: gzip, br                                ║
  ║     Cookie: session=bob_token       ← IGNORED                ║
  ║                                                              ║
  ║   Cache key (what CDN uses):                                 ║
  ║     /account/dashboard + gzip,br                             ║
  ║                                                              ║
  ║   SAME cache key. CDN serves Sarah's page.                   ║
  ╚══════════════════════════════════════════════════════════════╝
```

### What Vary Value WOULD Have Prevented It

```
Vary: Cookie

This would tell the CDN:
"Create a SEPARATE cache entry for each unique 
Cookie header value."

  Sarah's request:
    Cookie: session=sarah_token
    Cache key: /account/dashboard + "session=sarah_token"
    → Cache MISS → fetch from origin → store Sarah's page

  Bob's request:
    Cookie: session=bob_token
    Cache key: /account/dashboard + "session=bob_token"
    → Cache MISS (different cookie = different key)
    → Fetch from origin → store Bob's page
    → Bob sees his OWN data ✅

  Each user gets their own cache entry.
  No cross-user data exposure.
```

### Why Vary: Cookie Is the WRONG Fix

```
╔══════════════════════════════════════════════════════════════╗
║   Vary: Cookie would PREVENT the security issue.             ║
║   But it would be the WRONG architectural fix.               ║
║                                                              ║
║   WHY:                                                       ║
║                                                              ║
║   1. CACHE EXPLOSION                                         ║
║      Every unique session cookie = a separate                ║
║      cache entry. If you have 1 million active               ║
║      users, you now have 1 million cached copies             ║
║      of /account/dashboard in the CDN.                       ║
║      That's not caching. That's a database.                  ║
║                                                              ║
║   2. NEAR-ZERO HIT RATE                                      ║
║      Session cookies are unique per user.                    ║
║      A cache entry per user means every request              ║
║      is a cache miss (users rarely reload the                ║
║      exact same page within 300 seconds).                    ║
║      You'd have CDN overhead with no CDN benefit.            ║
║                                                              ║
║   3. PRIVACY STILL AT RISK                                   ║
║      If a user's session cookie is predictable,              ║
║      rotated, or shared (SSO), cache collisions              ║
║      could still occur.                                      ║
║                                                              ║
║   THE CORRECT FIX:                                           ║
║      Authenticated user pages should NEVER be                ║
║      cached at the CDN layer. Period.                        ║
║                                                              ║
║      Cache-Control: private, no-store                        ║
║                                                              ║
║      "private" = only the user's browser may cache           ║
║      "no-store" = don't even store it in the                 ║
║                   browser cache (sensitive data)             ║
║                                                              ║
║      The original code had it right:                         ║
║        @CacheControl(private, no-cache)                      ║
║      The developer broke it by changing to public.           ║
║                                                              ║
║      The fix is not a smarter Vary header.                   ║
║      The fix is not caching this content AT ALL              ║
║      in shared caches.                                       ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Question 4: Long-Term Controls — Making This Bug Class Impossible

The root cause is a **single developer changing one annotation** and exposing PII to the entire internet. The fix cannot be "tell developers not to do this." Humans make mistakes. The system must make this class of mistake **structurally impossible.**

### Layer 1: CDN Edge — The Last Line of Defense

**Cloudflare Cache Rules: NEVER cache authenticated content regardless of origin headers.**

```
Cloudflare Dashboard → Caching → Cache Rules

Rule 1 (HIGHEST PRIORITY):
  IF:  URL path starts with "/account/"
  OR:  Request has Cookie header containing "session="
  OR:  Request has Authorization header
  THEN: Cache eligibility = BYPASS CACHE
  
  This rule overrides ANY Cache-Control header from origin.
  Even if the origin says "public, s-maxage=31536000",
  Cloudflare will NOT cache it.
```

```
# Cloudflare API equivalent:
curl -X POST "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/rulesets" \
  -H "Authorization: Bearer $CF_API_TOKEN" \
  -d '{
    "name": "Never cache authenticated content",
    "kind": "zone",
    "phase": "http_request_cache_settings",
    "rules": [
      {
        "expression": "(http.request.uri.path starts_with \"/account\") or (http.cookie contains \"session=\") or (http.request.headers[\"authorization\"] != \"\")",
        "action": "set_cache_settings",
        "action_parameters": {
          "cache": false
        }
      }
    ]
  }'
```

**Why this is the most critical control:**
```
This is a DEFENSE-IN-DEPTH layer that protects against 
the EXACT scenario that occurred.

Even if a developer sets Cache-Control: public on an 
authenticated page, the CDN rule OVERRIDES it.

The CDN is the last checkpoint before content reaches 
users. If this layer enforces "never cache /account/*",
no code change can bypass it.
```

### Layer 2: Origin Application — Framework-Level Default

**Set secure-by-default Cache-Control headers at the framework/middleware level, not at the controller level.**

```python
# ❌ CURRENT: Cache-Control is set per-controller
# Any developer can change it. No guardrails.

@CacheControl(public, s_maxage=300)  # Developer "improves perf"
def account_dashboard(request):
    ...

# ✅ FIXED: Middleware enforces Cache-Control based on 
# authentication state. Controllers CANNOT override.

class SecureCacheMiddleware:
    def process_response(self, request, response):
        # If the request is authenticated (has a session),
        # FORCE private, no-store regardless of what the 
        # controller set
        if request.user.is_authenticated:
            response['Cache-Control'] = 'private, no-store, no-cache'
            response['Pragma'] = 'no-cache'
            # Remove any s-maxage that a controller might have set
            # This is the OVERRIDE — controllers cannot bypass this
            
            # Also: REMOVE Set-Cookie from cached responses
            # (Cloudflare should never cache a Set-Cookie response,
            #  but belt-and-suspenders)
            
        # If the request is unauthenticated AND the path 
        # is in the safe-to-cache list, allow caching
        elif request.path in CACHEABLE_PATHS:
            # Let the controller's Cache-Control through
            pass
            
        else:
            # Default: private (safe default)
            response['Cache-Control'] = 'private, no-cache'
            
        return response
```

**The critical design principle:**
```
╔══════════════════════════════════════════════════════════════╗
║   SECURE BY DEFAULT, EXPLICITLY OPT IN TO CACHING            ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   ❌ Wrong model (current):                                   ║
║      Default: no cache header                                ║
║      Developer ADDS caching per route                        ║
║      Risk: developer adds caching to wrong route             ║
║                                                              ║
║   ✅ Correct model:                                           ║
║      Default: private, no-store for ALL authed               ║
║      requests                                                ║
║      Middleware ENFORCES this regardless of                  ║
║      controller annotations                                  ║
║      Caching is ONLY allowed for explicitly                  ║
║      whitelisted, unauthenticated paths                      ║
║                                                              ║
║   A developer cannot accidentally make an authed             ║
║   page cacheable because the middleware overrides            ║
║   any cache header they set.                                 ║
╚══════════════════════════════════════════════════════════════╝
```

### Layer 3: CI/CD Pipeline — Automated Detection

**Static analysis / linting rules that catch dangerous cache headers before deployment.**

```yaml
# .github/workflows/cache-safety-check.yml
name: Cache-Control Safety Check

on: [pull_request]

jobs:
  cache-safety:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Check for public cache on authenticated routes
        run: |
          # Find all controllers in /account/ routes that set 
          # Cache-Control: public
          VIOLATIONS=$(grep -rn "@CacheControl.*public" \
            --include="*.py" --include="*.java" --include="*.ts" \
            app/controllers/account/ \
            app/controllers/user/ \
            app/controllers/checkout/ \
            app/controllers/payment/ || true)
          
          if [ -n "$VIOLATIONS" ]; then
            echo "❌ SECURITY VIOLATION: Public cache headers on authenticated routes"
            echo "$VIOLATIONS"
            echo ""
            echo "Authenticated routes (/account/*, /user/*, /checkout/*, /payment/*)"
            echo "MUST use Cache-Control: private, no-store"
            echo ""
            echo "If you believe this is a false positive, request a security review."
            exit 1
          fi
          
          echo "✅ No public cache headers on authenticated routes"
```

```yaml
      - name: Check for missing Cache-Control on new routes
        run: |
          # Any new controller that doesn't explicitly set 
          # Cache-Control is flagged for review
          DIFF=$(git diff origin/main --name-only --diff-filter=A \
            -- 'app/controllers/**')
          
          for file in $DIFF; do
            if ! grep -q "CacheControl\|cache_control\|Cache-Control" "$file"; then
              echo "⚠️  WARNING: New controller $file has no explicit Cache-Control"
              echo "   All controllers MUST set Cache-Control explicitly."
              echo "   Authenticated routes: private, no-store"
              echo "   Public content: public, s-maxage=N"
              exit 1
            fi
          done
```

### Layer 4: Response Validation — Runtime Canary

**A continuous test that verifies the CDN is NOT caching authenticated content.**

```python
# Runs every 60 seconds in production monitoring
def test_account_page_not_cached():
    """
    SECURITY CANARY: Verify that account pages are never 
    served from CDN cache.
    
    If this test fails, page immediately and purge CDN.
    """
    # Step 1: Make an authenticated request
    response = requests.get(
        "https://shop.example.com/account/dashboard",
        cookies={"session": CANARY_USER_SESSION_TOKEN}
    )
    
    # Step 2: Verify Cache-Control is private
    cache_control = response.headers.get("Cache-Control", "")
    assert "public" not in cache_control, \
        f"CRITICAL: /account/dashboard has Cache-Control: {cache_control}"
    assert "private" in cache_control or "no-store" in cache_control, \
        f"CRITICAL: /account/dashboard missing private/no-store: {cache_control}"
    
    # Step 3: Verify Cloudflare did NOT cache it
    cf_cache_status = response.headers.get("CF-Cache-Status", "")
    assert cf_cache_status != "HIT", \
        f"CRITICAL: /account/dashboard served from CDN cache! CF-Cache-Status: {cf_cache_status}"
    
    # Step 4: Verify response contains ONLY the canary user's data
    assert CANARY_USER_NAME in response.text, \
        "CRITICAL: /account/dashboard returned wrong user's data"
    
    # Step 5: Make an UNAUTHENTICATED request — should NOT 
    # return any user data
    unauthed = requests.get(
        "https://shop.example.com/account/dashboard"
    )
    assert unauthed.status_code in (302, 401, 403), \
        f"CRITICAL: /account/dashboard accessible without auth: {unauthed.status_code}"


# Alert configuration:
# If this canary fails ONCE:
#   → P1 SECURITY alert to on-call
#   → Auto-trigger CDN purge via webhook
#   → Auto-rollback last deployment (if within 30 min window)
```

### Layer 5: Code Review — Human Guardrails

```
MANDATORY CODE REVIEW RULES:

  1. ANY change to Cache-Control, Vary, CDN config, 
     or caching annotations requires review from 
     the SECURITY team, not just the feature team.

  2. PR template includes a checkbox:
     □ This PR does not modify cache headers on 
       authenticated routes
     □ If it DOES modify cache headers, security 
       review is attached

  3. CODEOWNERS file enforces this:
     # .github/CODEOWNERS
     **/cache*.py          @security-team
     **/middleware/cache*   @security-team
     **/cdn/**              @security-team
     
     # Any file with CacheControl annotation changes
     # requires security review (enforced by CI check)
```

### Complete Defense-in-Depth Matrix

```
╭────────────────────────┬────────────────────────────────────────────┬──────────────────────────────────────╮
│ LAYER                  │ CONTROL                                    │ CATCHES THIS SCENARIO?               │
├────────────────────────┼────────────────────────────────────────────┼──────────────────────────────────────┤
│ CDN Edge (Cloudflare)  │ Cache rule: never cache requests with      │ ✅ YES — CDN ignores origin's Cache- │
│                        │ session cookie or /account/* paths         │ Control: public                      │
├────────────────────────┼────────────────────────────────────────────┼──────────────────────────────────────┤
│ Application Middleware │ Middleware: force private, no-store on ALL │ ✅ YES — overrides controller        │
│                        │ authenticated responses                    │ annotation                           │
├────────────────────────┼────────────────────────────────────────────┼──────────────────────────────────────┤
│ CI Pipeline            │ Static analysis: block PRs with public     │ ✅ YES — PR blocked before merge     │
│                        │ cache on authed routes                     │                                      │
├────────────────────────┼────────────────────────────────────────────┼──────────────────────────────────────┤
│ Runtime Monitoring     │ Canary test: verify /account pages never   │ ✅ YES — detected within 60 seconds, │
│                        │ served from cache. Alert + auto-purge on   │ auto-remediated                      │
│                        │ failure                                    │                                      │
├────────────────────────┼────────────────────────────────────────────┼──────────────────────────────────────┤
│ Code Review            │ CODEOWNERS: cache changes require security │ ✅ YES — requires security signoff   │
│                        │ team review                                │                                      │
├────────────────────────┼────────────────────────────────────────────┼──────────────────────────────────────┤
│ DEFAULT POSTURE        │ Framework default is private, no-store for │ ✅ YES — even if all other controls  │
│                        │ authed requests                            │ fail, the default is safe            │
╰────────────────────────┴────────────────────────────────────────────┴──────────────────────────────────────╯

ANY SINGLE LAYER would have prevented this incident.
ALL layers together make it structurally impossible.

The developer's change would have been:
  1. Blocked at PR by CI static analysis
  2. Blocked at PR by CODEOWNERS security review
  3. Overridden at runtime by middleware
  4. Overridden at CDN by cache rules
  5. Detected in 60 seconds by canary test
  6. Auto-purged and auto-rolled back

SIX independent controls. 
The developer would need to bypass ALL SIX 
to cause this incident again.

That's defense in depth.
```\

# WEEK 1 RETENTION TEST

## Rules

```
╔══════════════════════════════════════════════════════════════╗
║   RULES OF ENGAGEMENT                                        ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   1. Answer from MEMORY. Do not re-read the teaching         ║
║      material above. The whole point is to test what         ║
║      STUCK in your brain.                                    ║
║                                                              ║
║   2. Rapid-fire section: Keep answers concise.               ║
║      2-4 sentences max per question. No essays.              ║
║      If you know it, you can say it quickly.                 ║
║      If you can't say it quickly, you don't know it.         ║
║                                                              ║
║   3. Compound scenario: Full depth expected.                 ║
║      This is the real test.                                  ║
║                                                              ║
║   4. It's OK to say "I don't remember."                      ║
║      That's honest and tells us what to review.              ║
║      Faking an answer teaches nothing.                       ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Part 1: Rapid-Fire Concept Recall (10 Questions)

Answer ALL 10 in one response. Keep each answer to 2-4 sentences maximum.

**Q1 (TCP):** What is the purpose of the TIME_WAIT state in TCP, and why does it last for 2×MSL? What SRE problem does it cause at scale?

**Q2 (TCP vs UDP):** You're designing a DNS resolver. Should it use TCP or UDP for standard queries, and why? Name the specific scenario when it switches to the other protocol.

**Q3 (HTTP):** HTTP/2 solved HTTP-layer head-of-line blocking with streams and multiplexing. Explain why HTTP/2 actually made TCP-layer head-of-line blocking WORSE than HTTP/1.1. One sentence on the mechanism is sufficient.

**Q4 (HTTP/3):** What is QUIC's connection identifier, and what specific user experience problem does it solve that TCP cannot? Name the real-world scenario.

**Q5 (REST vs gRPC):** Your monitoring shows that 2 of your 6 gRPC backend replicas are at 90% CPU while the other 4 are at 8%. No hashing or routing logic exists in your application. What is the most likely cause? One sentence.

**Q6 (GraphQL):** Your error rate dashboard shows 0.0% errors, but users are reporting broken pages on your GraphQL API. What's happening and why does standard HTTP monitoring miss it?

**Q7 (WebSockets):** 200,000 WebSocket clients are connected to a server. The server crashes. All clients attempt to reconnect. Name the specific algorithm (with both components) that prevents the reconnection from killing the replacement server.

**Q8 (DNS):** A Java service was restarted 5 days ago. You just failed over your RDS database to a new IP. The Java service cannot connect. All Python and Go services reconnected within 60 seconds. What is the root cause, and what is the exact JVM property you need to set?

**Q9 (DNS):** You're planning to migrate your API from IP 1.1.1.1 to 2.2.2.2. Your current DNS TTL is 86400 seconds. Describe the critical preparation step, when you must do it relative to the migration, and why.

**Q10 (CDN):** Explain what `Cache-Control: public, s-maxage=60, stale-while-revalidate=300, stale-if-error=86400` means. Describe EXACTLY what happens at T=0, T=61, T=361, and when the origin is down at T=500.

---

## Part 2: Compound SRE Scenario

This scenario requires knowledge from **TCP, HTTP, DNS, CDN, WebSockets, and API design** simultaneously. It is deliberately complex. The challenge is not just knowing each concept but **identifying which layer each symptom belongs to** and how they interact.

```
INCIDENT REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Severity: P1
Service: Global live auction platform
  (think: eBay live auctions, Sotheby's online)
  
  Users bid on items in real-time. Bids must be 
  delivered within 500ms or the auction integrity 
  is compromised. Platform handles 800,000 
  concurrent users during major auctions.

ARCHITECTURE:
  
  ╔══════════════════════════════════════════════════════════════╗
  ║   EXTERNAL LAYER                                             ║
  ║   Browser/Mobile → CloudFront CDN                            ║
  ║     → Static assets (JS, CSS, images)                        ║
  ║     → API responses cached at edge                           ║
  ║                                                              ║
  ║   API LAYER                                                  ║
  ║   CloudFront → ALB → 20 API servers                          ║
  ║     → REST API for browsing/search                           ║
  ║     → GraphQL API for item details                           ║
  ║                                                              ║
  ║   REAL-TIME LAYER                                            ║
  ║   Browser → NLB (L4) → 10 WebSocket servers                  ║
  ║     → Live bid updates                                       ║
  ║     → Auction countdown timers                               ║
  ║     → "Someone outbid you" notifications                     ║
  ║   WebSocket servers ← Redis Pub/Sub ←                        ║
  ║     Bid Processing Service                                   ║
  ║                                                              ║
  ║   BID PROCESSING                                             ║
  ║   API servers ──gRPC──► Bid Service (6 replicas              ║
  ║     behind L4 internal LB)                                   ║
  ║   Bid Service → PostgreSQL (primary + replica)               ║
  ║                                                              ║
  ║   DNS                                                        ║
  ║   Route 53: auction.example.com                              ║
  ║     → CloudFront distribution                                ║
  ║   Route 53: ws.auction.example.com                           ║
  ║     → NLB (WebSocket servers)                                ║
  ║   Internal: Kubernetes CoreDNS for service                   ║
  ║     discovery                                                ║
  ║                                                              ║
  ║   ALL services run in Kubernetes (EKS)                       ║
  ║   in us-east-1.                                              ║
  ╚══════════════════════════════════════════════════════════════╝

INCIDENT TIMELINE:

  20:00 — Major celebrity art auction begins.
          800,000 concurrent users.
          Everything running smoothly.

  20:15 — A developer pushes a "performance improvement" 
          to the GraphQL item details API:
          
          BEFORE: 
            Item details fetched live from DB each request
            Response: Cache-Control: private, no-cache
          
          AFTER:
            Item details cached, including current bid price
            Response: Cache-Control: public, s-maxage=30
          
          The item details response includes:
          {
            "item": {
              "id": "lot-47",
              "title": "Warhol Print",
              "currentBid": 45000,    ← CACHED
              "bidCount": 23,         ← CACHED
              "timeRemaining": 180,   ← CACHED
              "highBidder": "user_***92" ← CACHED
            }
          }

  20:16 — Users start complaining:
          "The bid price shown on the page doesn't match 
           what the live ticker says"
          "I see $45,000 on the item page but the live 
           feed shows $62,000"
          "I placed a bid for $46,000 thinking I was 
           winning but I was actually $16,000 short"

  20:22 — Auction integrity complaints escalate.
          Multiple users claim they were misled by 
          stale prices. Legal team alerted.

  20:25 — SRE team begins investigating. They notice 
          ADDITIONAL problems beyond the stale prices:

          PROBLEM A (discovered 20:25):
            Bid processing latency spiked from 50ms 
            to 2,300ms at 20:00 when the auction started.
            
            Monitoring:
            → Bid Service replicas CPU:
              replica-1: 94%
              replica-2: 88%
              replica-3: 7%
              replica-4: 7%
              replica-5: 7%
              replica-6: 7%
            → Bid Service response times: 
              replica-1: 1,800ms avg
              replica-2: 1,400ms avg
              replica-3: 12ms avg
            → gRPC calls from API servers to Bid Service: 
              12,000/sec (normally 2,000/sec)

          PROBLEM B (discovered 20:28):
            ~5% of WebSocket connections are dropping 
            every 60 seconds and reconnecting.
            
            Monitoring:
            → WebSocket reconnection rate: ~40,000/min
            → Connections drop at suspiciously regular 
              60-second intervals
            → Affects random users, not geographic
            → WebSocket servers themselves are healthy 
              (CPU 45%, memory 60%)

          PROBLEM C (discovered 20:32):
            Engineers in the EU office report that 
            auction.example.com takes 8-12 seconds 
            to load initially, then works fine.
            
            Monitoring:
            → CloudFront was configured with HTTP/3 
              support two weeks ago
            → QUIC connection success rate: 82%
            → EU office network: corporate firewall 
              managed by third-party IT

          PROBLEM D (discovered 20:35):
            CoreDNS in the Kubernetes cluster is at 
            95% CPU. Internal service-to-service 
            calls are showing elevated latency.
            
            Monitoring:
            → CoreDNS query rate: 620,000/sec 
              (normal: 150,000/sec)
            → Many queries are NXDOMAIN responses
            → Kubernetes pods have default ndots:5
            → The Bid Service makes external calls to 
              a fraud detection API: 
              fraud-check.partner-service.com

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Question 1:** There are FIVE distinct problems in this incident (the stale prices + Problems A, B, C, D). For each one:
- Name the problem
- Identify which LAYER/PROTOCOL it belongs to (TCP, HTTP, DNS, CDN, WebSocket, gRPC)
- State the root cause in one sentence
- Cite the specific monitoring evidence

**Question 2:** These five problems are NOT independent. Draw the connections — which problems make other problems WORSE? Identify at least TWO causal relationships between problems.

**Question 3:** You are the incident commander. You must prioritize fixing these five problems. Rank them 1-5 in order of priority and justify your ordering. Consider: revenue impact, legal risk, blast radius, and cascading effects.

**Question 4:** Give the immediate mitigation for your TOP 3 priority problems. Exact actions and commands.


# WEEK 1 RETENTION TEST — ANSWERS

---

# Part 1: Rapid-Fire

---

**Q1 (TCP — TIME_WAIT):**
TIME_WAIT ensures that delayed packets from a previous connection aren't misinterpreted by a new connection reusing the same source-port/dest-port tuple. It lasts 2×MSL (Maximum Segment Lifetime) to guarantee that any packet from the old connection has expired AND that the final ACK has been received or timed out. At scale, it causes **ephemeral port exhaustion** — thousands of sockets stuck in TIME_WAIT consuming ports, preventing new outbound connections from high-traffic services.

---

**Q2 (TCP vs UDP — DNS):**
UDP for standard queries — DNS is a single request/response exchange with small payloads (<512 bytes), so UDP avoids the overhead of TCP's three-way handshake. It switches to **TCP** when the response is too large for a single UDP datagram — signaled by the TC (truncation) bit in the UDP response, commonly seen with DNSSEC responses or large record sets.

---

**Q3 (HTTP/2 — HoL Blocking):**
HTTP/1.1 used 6 parallel TCP connections per domain, so a packet loss on one connection only blocked ~1/6 of resources; HTTP/2 multiplexes ALL streams onto a SINGLE TCP connection, meaning one lost packet at the TCP layer stalls EVERY stream simultaneously — making the blast radius of a single packet loss 6x worse.

---

**Q4 (HTTP/3 — QUIC Connection ID):**
QUIC identifies connections by a **Connection ID** (a random token) rather than the TCP 4-tuple (src IP, src port, dst IP, dst port). This allows a mobile user to switch from WiFi to cellular — their IP address changes, but the QUIC connection survives seamlessly because the Connection ID hasn't changed. TCP connections die instantly on network change because the 4-tuple is broken.

---

**Q5 (gRPC — L4 Black Hole):**
L4 load balancer in front of gRPC — gRPC uses long-lived HTTP/2 connections, and the L4 LB distributes TCP connections (not requests), so all gRPC requests are multiplexed onto 2-3 pinned connections hitting only 2 replicas while the other 4 receive zero traffic.

---

**Q6 (GraphQL — Error Masking):**
GraphQL returns **HTTP 200 for everything**, including errors — errors are embedded in the response body under an `"errors"` field. Standard HTTP monitoring only checks status codes, sees 200 across the board, and reports 0% errors while users receive partial or broken data.

---

**Q7 (WebSockets — Reconnection):**
**Exponential backoff with jitter.** Exponential backoff (1s, 2s, 4s, 8s... capped at ~30s) spreads reconnections over time. Jitter (random offset within each backoff window, e.g., ±50%) prevents synchronized retry waves where all clients at the same backoff step reconnect simultaneously.

---

**Q8 (DNS — JVM Caching):**
The JVM caches DNS lookups **indefinitely** by default (`networkaddress.cache.ttl=-1` when a SecurityManager is installed). The Python and Go services use OS-level DNS resolution which honors TTL, so they re-resolved within 60 seconds. Fix: set `networkaddress.cache.ttl=30` in `$JAVA_HOME/conf/security/java.security` or via `-Dsun.net.inetaddr.ttl=30` JVM flag.

---

**Q9 (DNS — TTL Pre-Lowering):**
Lower the TTL from 86400 (24 hours) to a short value like 10-30 seconds **at least 7 days before** the migration. This ensures every recursive resolver worldwide has fetched the record with the low TTL at least once, so when you make the actual IP change, caches expire within seconds. If you lower TTL and change IP simultaneously, resolvers that cached the old record with TTL=86400 could serve the stale IP for up to 24 hours.

---

**Q10 (CDN — Cache-Control Breakdown):**

```
T=0:    Cache MISS. CDN fetches from origin, caches the response.
        Response is FRESH (within s-maxage=60). Users get fresh content.

T=61:   Content is STALE. stale-while-revalidate=300 activates.
        CDN serves stale content IMMEDIATELY to the user (fast)
        AND sends an ASYNC revalidation request to origin in the background.
        User gets instant response with slightly stale data.

T=361:  Beyond stale-while-revalidate window (60+300=360).
        CDN must revalidate SYNCHRONOUSLY — user waits for origin.
        Normal cache miss behavior resumes.

T=500   Origin is DOWN. stale-if-error=86400 activates.
(down): CDN serves stale content (up to 24 hours old) instead 
        of returning a 502/504 error to the user.
        The site stays UP using stale content despite origin failure.
```

---

# Part 2: Compound SRE Scenario

---

## Question 1: Five Problems — Layer, Root Cause, Evidence

### Problem 1: Stale Bid Prices (CDN / HTTP Caching Layer)

**Root cause:** The developer changed `Cache-Control` on the GraphQL item details endpoint from `private, no-cache` to `public, s-maxage=30`, causing CloudFront to cache the response — including `currentBid`, `bidCount`, `timeRemaining`, and `highBidder` — and serve the same stale cached copy to all users for up to 30 seconds.

**Evidence:**
```
→ Users report: "$45,000 on item page but live feed shows $62,000"
→ The item details response includes currentBid as part of 
  the cached payload
→ Git diff shows: @CacheControl changed from 
  (private, no-cache) → (public, s_maxage=30)
→ Deployment at 20:15, complaints at 20:16 
  (within one s-maxage cycle)
→ The live WebSocket ticker shows CORRECT prices 
  (it bypasses the CDN), confirming the CDN cache 
  is the source of staleness
```

**Why it's dangerous:** In a live auction, a 30-second stale price is catastrophic. Bids can increment thousands of dollars in seconds. A user seeing $45,000 and bidding $46,000 when the real price is $62,000 is being **misled into a financial decision by stale data**. This is an auction integrity and legal liability issue.

---

### Problem 2 (Problem A): Bid Service gRPC Black Hole (gRPC / L4 Load Balancing Layer)

**Root cause:** The Bid Service (6 replicas) sits behind an **L4 internal load balancer**. The API servers' gRPC clients open long-lived HTTP/2 connections. The L4 LB distributed TCP connections at creation time, pinning all gRPC requests onto 2 of the 6 replicas. The other 4 replicas receive zero traffic.

**Evidence:**
```
→ CPU: replica-1: 94%, replica-2: 88%, replicas 3-6: 7%
  (Binary distribution = connection pinning, not load variance)
→ Response times: 1,800ms / 1,400ms on hot replicas, 
  12ms on idle replicas
  (Idle replicas are FAST — they're healthy but starved)
→ Architecture states: "L4 internal LB" in front of gRPC
→ gRPC calls: 12,000/sec vs 2,000/sec normal 
  (6x increase concentrated on 2 replicas)
→ 7% CPU on replicas 3-6 = healthcheck/baseline only,
  ZERO application traffic
```

---

### Problem 3 (Problem B): WebSocket 60-Second Connection Drops (TCP / Network Layer)

**Root cause:** An intermediate network component — most likely the NLB's idle connection timeout or an AWS NAT Gateway/Security Group timeout — is configured with a **60-second idle timeout**, terminating WebSocket TCP connections that have no data flowing for 60 seconds. The WebSocket implementation lacks application-level **ping/pong heartbeat frames** to keep connections alive through the idle detection window.

**Evidence:**
```
→ "Connections drop at suspiciously regular 60-second intervals"
  (Regular interval = timeout, not application crash or OOM)
→ "Affects random users, not geographic"
  (Not a specific edge/POP issue — it's infrastructure-level)
→ "WebSocket servers themselves are healthy (CPU 45%, memory 60%)"
  (The servers aren't crashing — something BETWEEN client 
   and server is killing the connection)
→ Reconnection rate: 40,000/min = ~667/sec
  (5% of 800,000 = 40,000 — these are the users who happen 
   to go 60 seconds without receiving a bid update on their 
   specific watched auction item)
```

---

### Problem 4 (Problem C): EU Slow Initial Load — QUIC/UDP Firewall Block (HTTP/3 / QUIC Layer)

**Root cause:** CloudFront was configured with HTTP/3 (QUIC) two weeks ago. QUIC runs over **UDP port 443**. The EU office's corporate firewall — managed by a third party — **blocks UDP 443** (a common corporate firewall policy, as historically all HTTPS was TCP-only). The browser attempts QUIC first, waits for the connection to time out (several seconds), then **falls back to HTTP/2 over TCP** — causing the 8-12 second initial load delay. Subsequent requests work fine because the browser caches the knowledge that QUIC failed and uses TCP/HTTP/2 directly.

**Evidence:**
```
→ "8-12 seconds to load INITIALLY, then works fine"
  (Classic QUIC-timeout-then-fallback pattern: 
   slow first load, fast subsequent loads)
→ "QUIC connection success rate: 82%"
  (18% failure rate — the EU corporate network is 
   in that 18%)
→ "EU office network: corporate firewall managed 
   by third-party IT"
  (Corporate firewalls commonly block UDP 443)
→ CloudFront HTTP/3 enabled "two weeks ago" 
  (Recent change correlates with when EU complaints 
   would have started, but masked by other issues)
```

---

### Problem 5 (Problem D): CoreDNS Overload from ndots:5 Search Domain Explosion (DNS / Kubernetes Layer)

**Root cause:** The Bid Service makes external calls to `fraud-check.partner-service.com`. With Kubernetes' default `ndots:5`, any hostname with **fewer than 5 dots** is first resolved by appending every search domain suffix before trying the absolute FQDN. `fraud-check.partner-service.com` has **3 dots** (fewer than 5), so every DNS lookup generates:

```
1. fraud-check.partner-service.com.default.svc.cluster.local  → NXDOMAIN
2. fraud-check.partner-service.com.svc.cluster.local          → NXDOMAIN
3. fraud-check.partner-service.com.cluster.local               → NXDOMAIN
4. fraud-check.partner-service.com.us-east-1.compute.internal  → NXDOMAIN
5. fraud-check.partner-service.com.                            → SUCCESS
```

**Five DNS queries for every single fraud check call.** Four of them return NXDOMAIN. At 12,000 bid requests/sec (each requiring a fraud check), that's **60,000 DNS queries/sec** just for fraud checks — and 48,000 of those are wasteful NXDOMAIN lookups.

**Evidence:**
```
→ CoreDNS CPU: 95%
→ Query rate: 620,000/sec (vs 150,000 normal = 4.13x increase)
→ "Many queries are NXDOMAIN responses" 
  (← SMOKING GUN for ndots search domain expansion)
→ "Kubernetes pods have default ndots:5"
  (← The scenario explicitly states the cause)
→ "Bid Service makes external calls to 
   fraud-check.partner-service.com"
  (3 dots < 5 ndots threshold → search domain expansion)
→ The math: 12,000 bids/sec × 5 DNS queries each = 60,000
  Additional normal internal queries: ~150,000 baseline
  DNS queries from other services handling 800K users
  Total: easily reaches 620,000/sec
```

---

## Question 2: Causal Relationships Between Problems

These five problems are NOT independent. They form a web of cascading failures:

### Causal Relationship 1: Problem A (gRPC Black Hole) → Problem D (CoreDNS Overload)

```
The gRPC black hole concentrates all 12,000 bid/sec 
onto 2 replicas.

Those 2 replicas become slow (1,800ms response time).
API servers hit timeouts and RETRY failed bids.
Each retry generates a NEW fraud-check DNS lookup.

Without retries: 12,000 bids/sec × 5 DNS queries = 60,000/sec
With retries (3x): up to 36,000 bids/sec × 5 = 180,000/sec
(just for fraud checks)

The gRPC black hole AMPLIFIES the DNS query volume 
through retry-driven fraud check calls.

╔══════════════════════════════════════════════════════════════╗
║  gRPC Black   │──────────────►│ More fraud                   ║
║  Hole (slow   │               │ check calls                  ║
║  bid process) │               │ per bid                      ║
╚══════════════════════════════════════════════════════════════╝
                                       │
                                       ▼ × 5 (ndots)
                               ╔══════════════════════════════════════════════════════════════╗
                               ║  CoreDNS                                                     ║
                               ║  overwhelmed                                                 ║
                               ╚══════════════════════════════════════════════════════════════╝
```

### Causal Relationship 2: Problem D (CoreDNS Overload) → Problem A (gRPC Black Hole) Worsening

```
CoreDNS at 95% CPU means DNS resolution is SLOW 
for everything in the cluster — including the 
Bid Service resolving fraud-check.partner-service.com.

Each fraud check call now has +500ms DNS overhead.
This makes each bid take EVEN LONGER on replicas 1-2.
Longer requests = more in-flight requests = higher CPU.

This creates a POSITIVE FEEDBACK LOOP:

  gRPC slow → retries → more DNS → CoreDNS slow
      ↑                                    │
      ╰────────────────────────────────────╯
      slower fraud checks → gRPC even slower

The two problems AMPLIFY each other.
```

### Causal Relationship 3: Stale Prices → Problem A (Increased Bid Volume)

```
Users see stale prices that are LOWER than reality.
  → User sees "$45,000" when real price is "$62,000"
  → User thinks "I can win this for $46,000!" and bids
  → Bids that would NEVER have been placed are submitted
  → Bid volume increases beyond organic levels

More bid volume → more gRPC calls → more pressure 
on the already-black-holed Bid Service → more retries 
→ more fraud check DNS queries → more CoreDNS load.

The stale cache doesn't just mislead users — it 
generates ARTIFICIAL DEMAND that amplifies Problems A and D.
```

### The Full Cascade Map

```
                    Stale Prices (CDN)
                         │
                         ▼ artificially inflated bids
                    ╭─────────╮
                ╭──►│ gRPC    │◄──╮
                │   │ Black   │   │
                │   │ Hole    │   │ slower fraud checks
                │   ╰────┬────╯   │ (DNS latency)
                │        │        │
                │  retrie│        │
                │        ▼        │
                │   ╭─────────╮   │
                │   │ CoreDNS │───╯
                │   │ Overload│
                │   ╰─────────╯
                │        │
                │        │ slow service discovery
                │        ▼
                │   ALL internal services degraded
                │   (including WebSocket server 
                │    internal calls)
                │
                ╰── retry amplification loop
```

---

## Question 3: Priority Ranking

```
╭──────┬──────────────────────┬──────────────────────────────────────╮
│ RANK │ PROBLEM              │ JUSTIFICATION                        │
├──────┼──────────────────────┼──────────────────────────────────────┤
│  1   │ Stale Prices (CDN)   │ LEGAL RISK. Users are making         │
│      │                      │ financial decisions (bids) based     │
│      │                      │ on incorrect data. Auction integrity │
│      │                      │ is compromised. This is potential    │
│      │                      │ fraud liability. Every second this   │
│      │                      │ persists, more users are misled.     │
│      │                      │ Also FEEDS Problems A and D by       │
│      │                      │ generating artificial bid volume.    │
├──────┼──────────────────────┼──────────────────────────────────────┤
│  2   │ gRPC Black Hole (A)  │ CORE FUNCTION. Bid processing at     │
│      │                      │ 2,300ms vs 500ms SLA. The platform's │
│      │                      │ entire purpose is real-time bidding. │
│      │                      │ This is ALSO the root of the cascade │
│      │                      │ — fixing it reduces retry volume,    │
│      │                      │ which reduces DNS load (helps D).    │
│      │                      │ Highest cascading benefit.           │
├──────┼──────────────────────┼──────────────────────────────────────┤
│  3   │ CoreDNS Overload (D) │ BLAST RADIUS. Affects ALL services   │
│      │                      │ in the cluster, not just bidding.    │
│      │                      │ Payment processing, search, auth —   │
│      │                      │ everything that makes an internal    │
│      │                      │ DNS query is degraded. Also feeds    │
│      │                      │ back into Problem A, making bids     │
│      │                      │ even slower.                         │
├──────┼──────────────────────┼──────────────────────────────────────┤
│  4   │ WebSocket Drops (B)  │ USER EXPERIENCE. 5% of users         │
│      │                      │ affected, they reconnect in seconds, │
│      │                      │ annoying but not data-corrupting.    │
│      │                      │ Does NOT cascade into other problems.│
│      │                      │ The live bid ticker (WebSocket) is   │
│      │                      │ actually showing CORRECT data — it's │
│      │                      │ the GraphQL/CDN path that's wrong.   │
├──────┼──────────────────────┼──────────────────────────────────────┤
│  5   │ EU QUIC Fallback (C) │ NARROW SCOPE. Only affects EU        │
│      │                      │ corporate users, only on first load, │
│      │                      │ site works after fallback. Zero      │
│      │                      │ data integrity impact. Zero cascade. │
│      │                      │ Can be fixed after the incident.     │
╰──────┴──────────────────────┴──────────────────────────────────────╯
```

---

## Question 4: Immediate Mitigation — Top 3 Priorities

### Priority 1: Stale Prices — Purge CDN + Roll Back (Seconds 0-90)

```bash
# SECOND 0: Purge CloudFront cache for the item details path
# This STOPS users from seeing stale prices immediately.

aws cloudfront create-invalidation \
  --distribution-id $CF_DISTRIBUTION_ID \
  --paths "/graphql" "/api/items/*" "/*"

# Note: GraphQL typically uses a single endpoint (/graphql),
# so we invalidate that path. Adding /* as safety net.
# CloudFront invalidations propagate globally in ~60-90 seconds.

# SECOND 10: Roll back the deployment
# The cache purge stops CURRENT stale data, but origin is 
# still returning Cache-Control: public, s-maxage=30.
# Without rollback, the NEXT request re-populates the cache.

kubectl rollout undo deployment/graphql-api

# SECOND 60: Verify the fix
curl -sI "https://auction.example.com/graphql" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ item(id:\"lot-47\") { currentBid } }"}'

# MUST show:
#   Cache-Control: private, no-cache
#   X-Cache: Miss from cloudfront
#
# If still showing public, s-maxage=30 → rollback hasn't 
# propagated. Check pod status:
kubectl rollout status deployment/graphql-api

# SECOND 90: Confirm bid prices match between 
# GraphQL responses and WebSocket live ticker
```

### Priority 2: gRPC Black Hole — Redistribute Connections (Seconds 30-180)

```bash
# The root cause is L4 LB + gRPC long-lived connections.
# We cannot replace the L4 LB with L7 mid-incident.
# But we CAN force connection redistribution.

# OPTION A (fastest): Restart the API server gRPC clients
# This drops all existing gRPC connections and forces 
# new TCP connections, which the L4 LB will distribute 
# across all 6 Bid Service replicas via round-robin.

kubectl rollout restart deployment/api-server

# After restart, 20 API servers each open connections.
# L4 LB distributes ~20 TCP connections across 6 replicas.
# ~3-4 connections per replica = much more even distribution.
# 
# THIS IS NOT A PERMANENT FIX. Over time, connections may 
# become unbalanced again. But it immediately relieves 
# the 94%/88%/7%/7%/7%/7% split.

# OPTION B (if restart is too disruptive):
# Configure gRPC clients to set maxConnectionAge
# This forces periodic connection recycling:

# In the API server gRPC client config:
# grpc.keepalive_time_ms=60000
# grpc.max_connection_age_ms=300000  (5 min)
# 
# Every 5 minutes, connections are recycled and L4 LB 
# redistributes them. Not instant but self-healing.

# VERIFY: Watch CPU equalize
kubectl top pods -l app=bid-service --watch

# Should see: all 6 replicas at ~15-20% CPU
# Response times should drop from 1,800ms to ~50ms
```

### Priority 3: CoreDNS Overload — Scale + Fix ndots (Seconds 60-300)

```bash
# ACTION 3A: IMMEDIATE — Scale CoreDNS replicas
# CoreDNS is at 95% CPU handling 620K qps.
# Scale to handle the load while we fix the root cause.

kubectl -n kube-system scale deployment/coredns --replicas=10

# Currently ~3 replicas at 95% → 10 replicas = ~28% each
# DNS resolution time should drop from 500ms to <5ms
# ALL internal services immediately benefit.

# ACTION 3B: Fix the ndots issue for the Bid Service
# The FASTEST fix: add a trailing dot to the FQDN in config.
# A trailing dot tells the resolver "this is an absolute FQDN, 
# do NOT append search domains."

# In the Bid Service's configuration/environment:
# BEFORE: FRAUD_API_HOST=fraud-check.partner-service.com
# AFTER:  FRAUD_API_HOST=fraud-check.partner-service.com.
#                                                       ^ trailing dot

kubectl set env deployment/bid-service \
  FRAUD_API_HOST="fraud-check.partner-service.com."

# This single trailing dot eliminates 4 wasted DNS queries 
# per fraud check call.
# At 12,000 calls/sec: eliminates 48,000 NXDOMAIN queries/sec
# CoreDNS load drops dramatically.

# ACTION 3C: For broader fix, add dnsConfig to the Bid Service pod spec
# to override ndots for this specific service:

kubectl patch deployment bid-service -p '{
  "spec": {"template": {"spec": {
    "dnsConfig": {
      "options": [{"name": "ndots", "value": "2"}]
    }
  }}}}'

# ndots:2 means any hostname with 2+ dots is resolved as 
# an absolute FQDN first. fraud-check.partner-service.com 
# has 3 dots → resolved directly. No search domain expansion.

# ACTION 3D: Verify
kubectl exec -it deployment/bid-service -- \
  dig fraud-check.partner-service.com | grep "Query time"
# Should show: 1-5ms (not 500ms)

# Watch CoreDNS CPU drop:
kubectl -n kube-system top pods -l k8s-app=kube-dns --watch
```

### Mitigation Timeline

```
╔══════════════════════════════════════════════════════════════╗
║  T+0s      │ Purge CloudFront cache (stale prices)           ║
║  T+10s     │ Roll back GraphQL deployment                    ║
║  T+30s     │ Restart API servers (redistribute gRPC)         ║
║  T+60s     │ Scale CoreDNS to 10 replicas                    ║
║  T+90s     │ Verify: Cache-Control: private on GraphQL       ║
║  T+120s    │ Apply trailing dot fix to fraud API FQDN        ║
║  T+180s    │ Verify: Bid Service CPU equalized               ║
║  T+240s    │ Verify: CoreDNS CPU dropping                    ║
║  T+300s    │ Verify: All bid latencies < 500ms SLA           ║
║            │                                                 ║
║  LATER     │ Problem B: Add WebSocket ping/pong every        ║
║  (post-    │ 30s to keep connections alive through           ║
║  incident) │ idle timeout                                    ║
║            │                                                 ║
║            │ Problem C: Add QUIC fallback hint via           ║
║            │ Alt-Svc header with shorter timeout, OR         ║
║            │ disable HTTP/3 for enterprise IP ranges         ║
╚══════════════════════════════════════════════════════════════╝
```

