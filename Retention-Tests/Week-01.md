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




---

> **Answer key (do not open until you attempt the Ops Sim / questions):**  
> [`../answers/Retention-Tests/Week-01 Answers.md`](../answers/Retention-Tests/Week-01 Answers.md)

