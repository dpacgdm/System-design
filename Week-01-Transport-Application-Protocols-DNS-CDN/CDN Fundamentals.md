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
╔══════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "CDN = faster hosting"                    ║
╟──────────────────────────────────────────────────────────────╢
║   WRONG. A CDN is a distributed CACHE with optional edge       ║
║   compute. It does not replace origin capacity planning.       ║
║   On cache miss, you still hit origin — often harder during    ║
║   incidents (thundering herd, purge storms).                   ║
╠══════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "Set a long max-age and forget it"          ║
╟──────────────────────────────────────────────────────────────╢
║   WRONG. TTL without invalidation strategy = stale content     ║
║   during deploys. Versioned URLs (content-hash filenames)      ║
║   are the gold standard; TTL alone is not invalidation.        ║
╠══════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "Vary: Cookie fixes personalized caching"   ║
╟──────────────────────────────────────────────────────────────╢
║   WRONG. Vary: Cookie creates per-cookie cache entries —       ║
║   cache hit ratio collapses. Authenticated pages should use      ║
║   Cache-Control: private, no-store. Never cache user-specific  ║
║   HTML at the edge without explicit, reviewed design.          ║
╠══════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "CDN hit ratio is the only metric"          ║
╟──────────────────────────────────────────────────────────────╢
║   WRONG. 99% hit ratio with 1% miss on 1M RPS = 10K origin    ║
║   requests/sec. Track origin offload AND absolute miss RPS.    ║
╠══════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Purge fixes everything instantly"          ║
╟──────────────────────────────────────────────────────────────╢
║   WRONG. Purge propagates in 60–300s globally. Purge storms     ║
║   can overload origin. Purge is emergency response, not a      ║
║   deployment workflow.                                         ║
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
╔══════════════════════════════════════════════════════════════╗
║  TIME   │ ACTION                          │ IMPACT           ║
╠══════════════════════════════════════════════════════════════╣
║  +0s    │ Purge CDN cache (all /account/* │ STOPS            ║
║         │ or purge_everything)            │ exposure         ║
╠══════════════════════════════════════════════════════════════╣
║  +30s   │ Roll back deployment            │ PREVENTS         ║
║         │                                 │ recurrence       ║
╠══════════════════════════════════════════════════════════════╣
║  +60s   │ Verify: Cache-Control: private  │ CONFIRMS         ║
║         │ CF-Cache-Status: DYNAMIC        │ fix              ║
╠══════════════════════════════════════════════════════════════╣
║  +2min  │ Notify security/legal/support   │ COMPLIANCE       ║
╠══════════════════════════════════════════════════════════════╣
║  +5min  │ Analyze logs for blast radius   │ SCOPE            ║
╠══════════════════════════════════════════════════════════════╣
║  +15min │ Notify affected users           │ TRUST            ║
╚══════════════════════════════════════════════════════════════╝
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
║   ❌ Wrong model (current):                                  ║
║      Default: no cache header                                ║
║      Developer ADDS caching per route                        ║
║      Risk: developer adds caching to wrong route             ║
║                                                              ║
║   ✅ Correct model:                                          ║
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
╔════════════════════════════════════════════════════════════════════════════════════════════════════════════╗
║  LAYER                  │ CONTROL                                    │ CATCHES THIS SCENARIO?              ║

---

> **Retention test moved:** Week 1 rapid-fire + compound scenario (auction platform)
> are in [Retention-Tests/Week-01.md](../Retention-Tests/Week-01.md) to keep this
> module topic-only per curriculum standards.

