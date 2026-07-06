# WEEK 1 RETENTION TEST

## Rules

```
╔═══════════════════════════════════════════════════════════════╗
║   RULES OF ENGAGEMENT                                         ║
╟───────────────────────────────────────────────────────────────╢
║                                                               ║
║   1. Answer from MEMORY. Do not re-read the teaching          ║
║      modules. The whole point is to test what STUCK in        ║
║      your brain.                                              ║
║                                                               ║
║   2. Rapid-fire section: Keep answers concise.                ║
║      2-4 sentences max per question. No essays.               ║
║      If you know it, you can say it quickly.                  ║
║      If you can't say it quickly, you don't know it.          ║
║                                                               ║
║   3. Compound scenario: Full depth expected.                  ║
║      This is the real test.                                   ║
║                                                               ║
║   4. It's OK to say "I don't remember."                       ║
║      That's honest and tells us what to review.               ║
║      Faking an answer teaches nothing.                        ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
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
╔══════════════════════════════════════════════════════════════════════╗
║  RANK │ PROBLEM              │ JUSTIFICATION                         ║
╠══════════════════════════════════════════════════════════════════════╣
║   1   │ Stale Prices (CDN)   │ LEGAL RISK. Users are making          ║
║       │                      │ financial decisions (bids) based      ║
║       │                      │ on incorrect data. Auction integrity  ║
║       │                      │ is compromised. This is potential     ║
║       │                      │ fraud liability. Every second this    ║
║       │                      │ persists, more users are misled.      ║
║       │                      │ Also FEEDS Problems A and D by        ║
║       │                      │ generating artificial bid volume.     ║
╠══════════════════════════════════════════════════════════════════════╣
║   2   │ gRPC Black Hole (A)  │ CORE FUNCTION. Bid processing at      ║
║       │                      │ 2,300ms vs 500ms SLA. The platform's  ║
║       │                      │ entire purpose is real-time bidding.  ║
║       │                      │ This is ALSO the root of the cascade  ║
║       │                      │ — fixing it reduces retry volume,     ║
║       │                      │ which reduces DNS load (helps D).     ║
║       │                      │ Highest cascading benefit.            ║
╠══════════════════════════════════════════════════════════════════════╣
║   3   │ CoreDNS Overload (D) │ BLAST RADIUS. Affects ALL services    ║
║       │                      │ in the cluster, not just bidding.     ║
║       │                      │ Payment processing, search, auth —    ║
║       │                      │ everything that makes an internal     ║
║       │                      │ DNS query is degraded. Also feeds     ║
║       │                      │ back into Problem A, making bids      ║
║       │                      │ even slower.                          ║
╠══════════════════════════════════════════════════════════════════════╣
║   4   │ WebSocket Drops (B)  │ USER EXPERIENCE. 5% of users          ║
║       │                      │ affected, they reconnect in seconds,  ║
║       │                      │ annoying but not data-corrupting.     ║
║       │                      │ Does NOT cascade into other problems. ║
║       │                      │ The live bid ticker (WebSocket) is    ║
║       │                      │ actually showing CORRECT data — it's  ║
║       │                      │ the GraphQL/CDN path that's wrong.    ║
╠══════════════════════════════════════════════════════════════════════╣
║   5   │ EU QUIC Fallback (C) │ NARROW SCOPE. Only affects EU         ║
║       │                      │ corporate users, only on first load,  ║
║       │                      │ site works after fallback. Zero       ║
║       │                      │ data integrity impact. Zero cascade.  ║
║       │                      │ Can be fixed after the incident.      ║
╚══════════════════════════════════════════════════════════════════════╝
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

