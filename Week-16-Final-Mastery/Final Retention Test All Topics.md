# FINAL RETENTION TEST — ALL TOPICS (Weeks 1–14)

System Design curriculum capstone. Covers transport, storage, distributed theory, replication, DB internals, architecture patterns, specialized components, advanced patterns, and all design modules through Week 14.

**Target time:** 3–4 hours (Part 1: 90 min, Part 2: 90 min, Part 3: 30 min self-check)

### Topic Coverage Matrix (Weeks 1–14)

```text
WEEK │ TOPICS TESTED                          │ PART 1 Qs │ SCENARIOS
─────┼────────────────────────────────────────┼───────────┼──────────
  1  │ TCP, HTTP/2/3, DNS, CDN, WS, gRPC/GQL  │  Q1–Q9   │  A, B, C
 2-3 │ SQL, NoSQL, cache, CAP, consistency    │ Q10–Q15  │  A, B
  4  │ Raft, quorum, split brain              │ Q16–Q18  │  B, C
  5  │ Indexing, EXPLAIN, WAL, Cassandra      │ Q19–Q22  │  A, B
  6  │ Kafka, saga, outbox, gateway, microsvc │ Q23–Q27  │  A, C
  7  │ Rate limiting, CDN poisoning           │ Q28–Q30  │  A
  8  │ Clocks, CRDT, geo, SLOs                │ Q31–Q34  │  C
  9  │ WhatsApp, Twitter feed                 │ Q35–Q37  │  —
 10  │ YouTube, Uber                          │ Q38–Q40  │  —
 11  │ Payments, idempotency                  │ Q41–Q42  │  A
 12  │ Inverted index, crawler                │ Q43–Q44  │  B
 13  │ Distributed KV, Kafka, config store    │ Q45–Q47  │  B, C
 14  │ Google Docs, LLM, feature store        │ Q48–Q50  │  C
```

---

## Rules

```
╔════════════════════════════════════════════════════════════════╗
║   RULES OF ENGAGEMENT                                          ║
╟────────────────────────────────────────────────────────────────╢
║                                                                ║
║   1. Answer from MEMORY. Do not re-read the teaching           ║
║      modules. The whole point is to test what STUCK in         ║
║      your brain.                                               ║
║                                                                ║
║   2. Rapid-fire section: Keep answers concise.                 ║
║      2-4 sentences max per question. No essays.                ║
║      If you know it, you can say it quickly.                   ║
║      If you can't say it quickly, you don't know it.           ║
║                                                                ║
║   3. Compound scenarios: Full depth expected.                  ║
║      Identify which layer/pattern each symptom belongs to      ║
║      and how they cascade. This is the real test.              ║
║                                                                ║
║   4. It's OK to say "I don't remember."                        ║
║      That's honest and tells us what to review.                ║
║      Faking an answer teaches nothing.                         ║
║                                                                ║
║   5. Score yourself ONLY after attempting all parts.           ║
║      Then read the answer key. No peeking mid-test.            ║
║                                                                ║
╚════════════════════════════════════════════════════════════════╝
```

---

## Part 1: Rapid-Fire Concept Recall (50 Questions)

Answer ALL 50 in one sitting. Keep each answer to 2–4 sentences maximum.

### Week 1 — Transport, Protocols, DNS, CDN

**Q1 (TCP):** What is the purpose of the TIME_WAIT state, and what SRE problem does it cause at scale on high-traffic outbound clients?

**Q2 (DNS):** A DNS resolver handles standard queries. When does it switch from UDP to TCP, and what flag signals the switch?

**Q3 (HTTP/2):** HTTP/2 fixed HTTP-layer head-of-line blocking. Why did it make TCP-layer head-of-line blocking worse than HTTP/1.1?

**Q4 (HTTP/3):** What is QUIC's Connection ID, and what user experience problem does it solve that TCP cannot?

**Q5 (gRPC):** Six gRPC replicas behind an L4 NLB show CPU 91%, 88%, 7%, 7%, 7%, 7%. No client routing logic. One sentence: cause.

**Q6 (GraphQL):** Error dashboard shows 0.0% HTTP errors but users report broken pages. What's happening?

**Q7 (WebSockets):** 200,000 clients reconnect simultaneously after a server crash. Name the algorithm (both components) that prevents killing the replacement server.

**Q8 (CDN):** Explain `Cache-Control: public, s-maxage=60, stale-while-revalidate=300, stale-if-error=86400`. What happens at T=61 and when origin is down at T=500?

**Q9 (DNS — JVM):** Java service cannot connect after RDS failover; Python services reconnect in 60s. Root cause and exact JVM fix?

### Weeks 2–3 — SQL, NoSQL, Caching, Consistency

**Q10 (SQL):** A transaction reads a row, another transaction inserts a matching row, first transaction re-reads and sees a new phantom row. Which isolation level prevents this?

**Q11 (NoSQL):** You need flexible nested documents with secondary indexes and multi-document ACID within a shard. Document store or wide-column — which and why?

**Q12 (Caching):** Flash sale: Redis TTL=60s on product price. 50,000 users hit the same SKU; DB CPU hits 100% in 8 seconds. Name the failure mode and one infra fix without app code changes.

**Q13 (Consistency):** User posts a review, profile shows old count for 30s despite 400ms replication lag. Which consistency model failed and simplest fix without sync replication?

**Q14 (Consistent Hashing):** You add a 4th cache node to a 3-node ring with 150 virtual nodes each. What fraction of keys move vs naive modulo hashing?

**Q15 (CAP):** Network partition splits a 5-node cluster. You must keep accepting writes for a shopping cart. CP or AP — and what do users risk?

### Week 4 — Replication, Consensus, Raft

**Q16 (Raft):** A follower receives a RequestVote with `term=5` but its current term is 4. What does it do to its term and vote?

**Q17 (Split Brain):** Two nodes both believe they are leader and accept writes. Name the Raft mechanism that prevents this.

**Q18 (Quorum):** RF=3, W=2, R=2. Can a read return stale data after a successful write? State the R+W>N rule.

### Week 5 — DB Internals, Indexing, Scaling

**Q19 (Indexing):** Query filters `WHERE status='active' AND created_at > '2025-01-01'`. Composite index `(status, created_at)` vs `(created_at, status)` — which is better and why?

**Q20 (Query Plans):** `EXPLAIN` shows Seq Scan on a 200M-row table despite an index on `user_id`. Name two reasons Postgres might skip the index.

**Q21 (WAL/CDC):** Debezium slot `analytics_etl` frozen 45 min; replicas show `replay_lag < 100ms`; primary `pg_wal` grew 800 GB. Why are replicas "healthy" while disk dies?

**Q22 (Cassandra):** `CL=QUORUM` writes, `CL=ONE` reads, RF=3. Stale reads 33% of the time. Read CL fix in one line.

### Week 6 — Microservices, Kafka, Saga, Outbox

**Q23 (Kafka):** Topic has 32 partitions; consumer group runs 48 pods. How many pods are idle and why can't more pods reduce lag?

**Q24 (Saga):** ReserveInventory succeeds, ChargePayment succeeds, CreateShipment fails. CompensatePayment times out on Stripe. Saga state and required idempotency key?

**Q25 (Outbox):** checkout INSERTs `orders` + `outbox` in one txn; Debezium publishes. Debezium stalls — are orders lost, events lost, and what Week 5 mechanism threatens the primary?

**Q26 (API Gateway):** API gateway enforces 5s deadline; payments-svc gRPC has 4s internal deadline not propagated. User sees timeout at 5s but payment may have succeeded. Name the pattern failure.

**Q27 (Microservices):** `promotions-svc` and `checkout-svc` share one Postgres. promotions runs `CREATE INDEX CONCURRENTLY` during flash sale. Anti-pattern name and which service breaks first?

### Week 7 — Rate Limiting, Advanced Caching, CDN

**Q28 (Rate Limiting):** API allows 100 req/min average but must allow bursts of 20 req/sec for 5 seconds. Token bucket or sliding window log — pick one and why.

**Q29 (Rate Limiting):** Distributed rate limiter uses Redis `INCR` with TTL. Clock skew between Redis and app servers causes occasional double-counting. Name the algorithm variant that fixes this.

**Q30 (CDN Advanced):** Attacker poisons CDN cache by sending `Host: victim.com` to shared edge IP. Name the misconfiguration and the fix header.

### Week 8 — Clocks, CRDTs, Geospatial, Observability, SLOs

**Q31 (Clocks):** Two events: A happens-before B. Lamport clock: L(A)=5, L(B)=3. Possible or impossible? Why?

**Q32 (CRDTs):** Google Docs-style collaborative editing: OT vs CRDT — which tolerates offline edits without a central server and why?

**Q33 (Geospatial):** Uber needs "drivers within 2km" queries at 10k QPS. GeoHash vs S2 vs H3 — name the tradeoff that drives the choice.

**Q34 (SLOs):** 99.9% monthly SLO, error budget 43.2 min. Burn rate alert fires at 14.4× consumption. How many minutes until budget exhausted at current rate?

### Week 9 — WhatsApp, Twitter Feed

**Q35 (WhatsApp):** User A sends messages to User B while B is offline. Describe the delivery guarantee path (store-and-forward) and ordering guarantee within a chat.

**Q36 (Twitter Feed):** Celebrity with 80M followers posts a tweet. Fan-out-on-write vs fan-out-on-read — which fails and what's the hybrid fix?

**Q37 (Twitter Feed):** Home timeline merge of 500 followed users' tweets. How do you bound read latency — name the data structure and precomputation strategy.

### Week 10 — YouTube, Uber

**Q38 (YouTube):** 4K video upload at 2 Gbps. Name the pipeline stages from upload to first playback (at least 4) and where CDN fits.

**Q39 (Uber):** Surge pricing area needs sub-second driver-rider matching for 50k concurrent requests in a city. Name the geospatial index and why grid-based naive scan fails.

**Q40 (YouTube):** DASH adaptive bitrate: client buffer at 2s, bandwidth drops 80%. What does the player do and what CDN behavior helps?

### Week 11 — Payments, E-Commerce

**Q41 (Payments):** Double-click "Pay" sends two identical POSTs. What header/field prevents double charge and what DB constraint backs it?

**Q42 (Payments):** "Exactly-once payment processing" — achievable end-to-end? Answer in one sentence with the correct guarantee name.

### Week 12 — Google Search, Web Crawler

**Q43 (Search):** Query "system design interview" — describe inverted index lookup in 3 steps (tokenize → ? → ?).

**Q44 (Crawler):** Crawler hits `robots.txt` disallow but discovers URL via sitemap. Politeness rule: crawl or skip? Name the rate-limiting mechanism too.

### Week 13 — Distributed KV, Kafka Design, Config Store

**Q45 (Distributed KV):** 3-node KV with leader-follower replication. Leader dies; follower promoted. Uncommitted writes on old leader — how does fencing prevent zombie writes?

**Q46 (Kafka Design):** Order events keyed by `user_id`. Hot user generates 50k events/sec. What's the symptom and partition key redesign?

**Q47 (Config Store):** 10,000 services watch a config key. etcd watch storm after bulk update. Name the push vs pull tradeoff and mitigation.

### Week 14 — Google Docs, LLM Serving, Feature Store

**Q48 (Google Docs):** Two users edit the same paragraph offline for 10 minutes, then reconnect. OT vs CRDT merge — which avoids a central merge server?

**Q49 (LLM Serving):** 70B model, 10k concurrent chat users, p95 TTFT 800ms target. Name batching strategy and the GPU metric you'd watch.

**Q50 (Feature Store):** Training pipeline writes features hourly; serving needs <10ms lookup. Online vs offline store — what goes where and sync mechanism?

---

## Part 2: Multi-Topic Compound Scenarios (3 Scenarios)

Each scenario spans **4+ topic areas**. Full depth expected — layer identification, root cause, prioritization, and exact mitigations.

---

### Scenario A: "Black Friday Total System Failure"

```text
INCIDENT REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Severity: P0
Service: Global e-commerce + payments platform
  2.1M concurrent users, $4.2M/minute GMV at peak

ARCHITECTURE:

  ╔══════════════════════════════════════════════════════════════╗
  ║  EDGE: CloudFront CDN → WAF → ALB                            ║
  ║    Static assets + API cache (product pages)                 ║
  ║                                                              ║
  ║  API: api-gateway (rate limit: 1000 req/min/user)            ║
  ║    → catalog-svc (GraphQL)                                   ║
  ║    → checkout-svc (REST) → payments-svc (gRPC, L4 LB)        ║
  ║    → inventory-svc (sync HTTP)                               ║
  ║                                                              ║
  ║  REAL-TIME: WebSocket → live inventory counters              ║
  ║                                                              ║
  ║  DATA: PostgreSQL (orders) + Redis (cache, rate limits)      ║
  ║    Debezium → Kafka orders.events → fulfillment-svc          ║
  ║    Cassandra (product catalog, CL=QUORUM write, CL=ONE read) ║
  ║                                                              ║
  ║  PAYMENTS: Stripe API, idempotency keys in payments-svc      ║
  ║  SLO: checkout success 99.95%, payment p99 < 2s              ║
  ╚══════════════════════════════════════════════════════════════╝

TIMELINE:

  00:00 — Black Friday sale opens. Traffic 40× normal.

  00:03 — PagerDuty: checkout success rate 62%. SLO burn 8×.

  00:05 — Symptoms discovered:
    SYMPTOM 1: Product page shows "In Stock: 847" but checkout
               says "Sold Out" for same SKU.
    SYMPTOM 2: payments-svc replicas: CPU 4%, 3%, 92%, 89%, 5%.
               gRPC latency p99: 4.8s (SLO: 2s).
    SYMPTOM 3: Redis memory 98%. Rate limiter returning 429 for
               40% of legitimate users. Bot traffic mixed in.
    SYMPTOM 4: fulfillment-svc lag 120k. Customers charged but
               no shipping email. Debezium slot lag 45 min.
    SYMPTOM 5: EU users: 15s page load first visit, then fine.
               QUIC success rate: 71%.
    SYMPTOM 6: GraphQL errors: 0% HTTP 5xx. Support tickets:
               "cart shows $0 total."

  00:12 — inventory-svc OOMKilled. Shared Postgres connection
          pool exhausted (promotions-svc + checkout-svc).

  00:18 — You join as incident commander.
```

**A1:** For each of the SIX symptoms, identify the layer/pattern (CDN, caching, gRPC, rate limiting, Kafka/CDC, HTTP/3, GraphQL, microservices anti-pattern) and state root cause in one sentence with monitoring evidence.

**A2:** Draw at least THREE causal relationships between symptoms (e.g., Symptom 2 → Symptom 4). ASCII diagram required.

**A3:** Rank all six symptoms 1–6 for incident response priority. Justify using revenue impact, data integrity, legal risk, and cascade potential. Table format.

**A4:** Give immediate mitigations for your TOP 3 priorities with exact commands (kubectl, aws, redis-cli, SQL, or curl). Include verification steps.

**A5:** Six post-incident action items with owners — two must be SLO/error-budget related, two Kafka/outbox, two architecture.

---

### Scenario B: "Search Platform Index Corruption During Crawl Surge"

```text
INCIDENT REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Severity: P1
Service: Internal + public search (Google Search-scale subset)
  8B documents indexed, 450k queries/sec peak

ARCHITECTURE:

  ╔════════════════════════════════════════════════════════════════╗
  ║  CRAWLER FLEET (10k workers)                                   ║
  ║    Frontier queue (Kafka crawl.urls) → fetch → parse           ║
  ║    Politeness: 1 req/sec/domain, robots.txt cache in Redis     ║
  ║    Dedup: Bloom filter + distributed KV (URL → doc_id)         ║
  ║                                                                ║
  ║  INDEXING PIPELINE                                             ║
  ║    Kafka index.documents → tokenize → inverted index shards    ║
  ║    256 shards, consistent hashing on term                      ║
  ║    Replicas: RF=2, leader-based replication                    ║
  ║                                                                ║
  ║  SERVING                                                       ║
  ║    Query → scatter-gather 256 shards → merge → rank (BM25)     ║
  ║    CDN for static assets only; search API uncached             ║
  ║                                                                ║
  ║  CONFIG: etcd cluster (3 nodes) — shard map, crawl budgets     ║
  ║  SLO: p99 query latency 120ms, index freshness < 15 min        ║
  ╚════════════════════════════════════════════════════════════════╝

TIMELINE:

  06:00 — Major news event. Crawl rate 12× normal. 2M new URLs/hour.

  06:22 — Query results missing recent headlines. Freshness SLO
          breached. index_lag_minutes: 47.

  06:30 — Shard 47 leader OOM during merge. Follower promoted.
          12% of posting lists for terms starting with "bre" corrupted.

  06:35 — Crawler workers report 85% HTTP 429 from a major publisher.
          robots.txt cache TTL=24h; publisher changed disallow 2h ago.

  06:40 — etcd watch latency p99 8s (normal 20ms). Config updates
          delayed. Crawl budget not throttling.

  06:45 — Distributed KV: vector clock conflict rate 0.3% on URL
          dedup keys. Duplicate documents entering index pipeline.

  06:50 — Monitoring: 0% search API errors. User reports: "search
          broken for breaking news." Result count dropped 18% for
          news queries only.
```

**B1:** Identify FIVE distinct problems (including hidden monitoring blind spot). Map each to: crawler, inverted index, distributed KV, consensus/config, CAP/consistency, or observability.

**B2:** The 0% error rate with broken results — explain the observability gap. What SLI would catch this?

**B3:** Prioritize fixes 1–5. Consider index integrity vs crawl politeness vs config storm.

**B4:** Immediate mitigations: how do you (a) stop corruption spreading, (b) rebuild shard 47, (c) fix robots.txt staleness — exact steps/commands.

**B5:** Design the steady-state architecture change that prevents hot-term shard OOM during crawl surges. Reference consistent hashing and partitioning strategy.

---

### Scenario C: "Realtime Collaboration + AI Platform Outage"

```text
INCIDENT REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Severity: P1
Service: Google Docs-like editor + embedded AI assistant
  340k concurrent documents, 28k LLM inference req/sec

ARCHITECTURE:

  ╔════════════════════════════════════════════════════════════════╗
  ║  COLLABORATION                                                 ║
  ║    WebSocket gateway (sticky sessions, L7 ALB)                 ║
  ║    CRDT document state (RGA/YNATA) in memory per doc           ║
  ║    Persistence: append-only op log → Kafka doc.ops             ║
  ║    Presence: Redis pub/sub, TTL 30s                            ║
  ║                                                                ║
  ║  AI ASSISTANT                                                  ║
  ║    llm-gateway → model-serving (vLLM, continuous batching)     ║
  ║    Feature store: Redis (online) + S3 Parquet (offline)        ║
  ║    Point-in-time features for user writing style               ║
  ║                                                                ║
  ║  CLOCKS: Hybrid logical clocks on op log                       ║
  ║  SLO: edit propagation < 200ms p99, AI TTFT < 1.5s p95         ║
  ║  Error budget: 0.1% monthly (43.2 min)                         ║
  ╚════════════════════════════════════════════════════════════════╝

TIMELINE:

  14:00 — Product launch: AI "rewrite paragraph" for all users.

  14:05 — WebSocket disconnect rate 12%/min. Users see stale cursors.
          Presence shows users in wrong document sections.

  14:08 — LLM p95 TTFT 6.2s (SLO 1.5s). GPU util 98%. Queue depth 4k.
          No batching timeout configured.

  14:12 — Document merge conflicts: 0.8% of ops fail CRDT merge.
          Users report "my edits vanished." Vector clock skew detected
          between us-east and eu-west gateways.

  14:15 — Feature store: 34% of AI requests use 6-hour-old features.
          Online store sync lag from offline pipeline (Kafka Connect).

  14:18 — Error budget burn: 22×. SLO dashboard green — edit latency
          SLO met. AI SLO red but composite SLO widget shows "OK."

  14:20 — Kafka doc.ops consumer lag 890k. New edits not persisting.
          In-memory CRDT state diverging from durable log.
```

**C1:** Map each timeline event to: WebSockets, CRDTs/clocks, LLM serving, feature store, Kafka, SLO/observability. Root cause per event.

**C2:** Explain how consumer lag + in-memory CRDT creates a durability vs availability tradeoff (CAP). What fails first on partition?

**C3:** Priority ranking 1–6 for the six problem areas. Legal/data-loss lens for "edits vanished."

**C4:** Mitigations for top 3: include WebSocket heartbeat, GPU batching config, feature store sync, and Kafka consumer scaling — with commands/params.

**C5:** Design the SLO/error-budget structure that would have caught the "composite SLO green" false negative. Name SLIs, burn-rate windows, and alert thresholds.

---

## Part 3: Self-Assessment Checklist

Complete AFTER attempting Parts 1 and 2. Check each box honestly.

### Knowledge Retention by Week

```text
WEEK COVERAGE SELF-CHECK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Week 1  Transport/DNS/CDN
  [ ] I can explain TCP vs UDP tradeoffs without notes
  [ ] I can diagnose HTTP/2 vs HTTP/3 issues from symptoms
  [ ] I know WebSocket reconnection and CDN cache headers cold

Week 2-3  Storage & Theory
  [ ] I can pick SQL vs NoSQL for a given schema/access pattern
  [ ] I can explain cache failure modes (thundering herd, stampede)
  [ ] I can apply CAP and consistency models to a partition scenario

Week 4  Consensus
  [ ] I can walk through Raft leader election from memory
  [ ] I understand quorum math (R+W>N) and can compute it

Week 5  DB Internals
  [ ] I can read EXPLAIN output and suggest index fixes
  [ ] I understand WAL/slot bloat vs replica lag distinction

Week 6  Architecture Patterns
  [ ] I can diagram saga compensation and outbox two-phase flow
  [ ] I know why Kafka partition count limits consumer parallelism

Week 7  Specialized Components
  [ ] I can implement rate limiting tradeoffs (burst vs accuracy)
  [ ] I understand CDN cache poisoning and Host header validation

Week 8  Advanced Patterns
  [ ] I can explain CRDT vs OT and when each applies
  [ ] I can compute error budget burn rate and set alert thresholds

Week 9-10  Feed & Mobility Designs
  [ ] I can design fan-out strategy for celebrity vs normal users
  [ ] I understand geospatial indexing for Uber-scale matching

Week 11  Commerce
  [ ] I can explain payment idempotency end-to-end
  [ ] I know inventory reservation patterns for oversell prevention

Week 12  Search & Crawling
  [ ] I can describe inverted index query path
  [ ] I understand crawler politeness and robots.txt precedence

Week 13  Infrastructure
  [ ] I can explain distributed KV fencing and leader failover
  [ ] I understand Kafka hot-partition symptoms and key redesign

Week 14  Collaboration & AI
  [ ] I can explain CRDT merge without central coordinator
  [ ] I know online vs offline feature store and point-in-time joins
```

### Scoring Rubric

```text
PART 1 — RAPID-FIRE (50 questions Q1–Q50, score out of 50)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  45–50  (90%+)   MASTERY — curriculum retained; mock-interview ready
  40–44  (80–89%) SOLID — review weak weeks only
  30–39  (60–79%) GAPS — schedule targeted re-read of failed topics
  < 30   (< 60%)  RE-STUDY — revisit weeks 1–8 fundamentals first

  Per-week target: ≥ 80% within that week's questions

PART 2 — COMPOUND SCENARIOS (3 scenarios, 15 tasks total)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Scenario A (E-commerce):  /5 tasks at principal depth
  Scenario B (Search):      /5 tasks at principal depth
  Scenario C (Collab+AI):   /5 tasks at principal depth

  13–15  EXPERT — you think in cascades and layers automatically
  10–12  STRONG — minor gaps in prioritization or commands
  7–9    DEVELOPING — can identify problems but struggle on sequencing
  < 7    REVIEW — re-do Week 01 and Week 06 compound scenarios

PART 3 — SELF-CHECK HONESTY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Count checked boxes: ___ / 24

  20–24  Ready for senior/staff mock interviews
  14–19  Ready for mid-level mocks; drill unchecked weeks
  < 14   Not yet interview-ready on breadth

OVERALL FINAL VERDICT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ALL THREE parts ≥ 80%  →  Curriculum COMPLETE. Proceed to mocks.
  Part 1 < 80%           →  Re-read failed weeks before mocks.
  Part 2 < 70%           →  Re-do compound scenarios in Weeks 1, 6, 9–14.
  Part 3 < 16 boxes      →  Breadth insufficient; extend study 2–4 weeks.
```

### Week-Specific Review Map

```text
IF YOU MISSED QUESTIONS IN…          REVIEW MODULE
─────────────────────────────────────────────────────────────
Q1–Q9                                Week 01 transport/DNS/CDN
Q10–Q15                              Weeks 02–03 storage/theory
Q16–Q18                              Week 04 replication/consensus
Q19–Q22                              Week 05 DB internals
Q23–Q27                              Week 06 architecture patterns
Q28–Q30                              Week 07 specialized components
Q31–Q34                              Week 08 advanced patterns
Q35–Q37                              Week 09 feed/chat designs
Q38–Q40                              Week 10 media/mobility
Q41–Q42                              Week 11 commerce/payments
Q43–Q44                              Week 12 search/crawling
Q45–Q47                              Week 13 infrastructure
Q48–Q50                              Week 14 collaboration/AI
```

---

# FINAL RETENTION TEST — EXPERT ANSWERS

---

# Part 1: Rapid-Fire Answers

---

**Q1 (TCP — TIME_WAIT):**
TIME_WAIT ensures delayed packets from a closed connection aren't accepted by a new connection reusing the same 4-tuple. It lasts 2×MSL so all old packets expire. At scale, thousands of outbound connections in TIME_WAIT cause **ephemeral port exhaustion** — the client cannot open new connections until ports recycle.

---

**Q2 (DNS — UDP/TCP):**
Standard queries use **UDP** (single request/response, low overhead). It switches to **TCP** when the response exceeds 512 bytes or the response has the **TC (truncation)** bit set — common with DNSSEC or large record sets.

---

**Q3 (HTTP/2 — TCP HoL):**
HTTP/1.1 used ~6 parallel TCP connections; one lost packet blocked only that connection's streams. HTTP/2 multiplexes all streams onto **one TCP connection**, so a single lost packet stalls **every** stream simultaneously — 6× worse blast radius per packet loss.

---

**Q4 (HTTP/3 — QUIC CID):**
QUIC identifies connections by a **Connection ID** token, not the TCP 4-tuple. When a mobile user switches WiFi→cellular (IP changes), the QUIC connection survives. TCP dies instantly because the 4-tuple breaks.

---

**Q5 (gRPC — L4 Black Hole):**
**L4 load balancer + long-lived HTTP/2 gRPC connections.** The L4 LB distributes TCP connections at connect time, not requests. All multiplexed RPCs pin to 2 connections → 2 hot replicas, 4 idle.

---

**Q6 (GraphQL — Error Masking):**
GraphQL returns **HTTP 200** for partial failures; errors live in the `"errors"` JSON field. HTTP monitoring sees 100% success while clients receive null fields and broken pages.

---

**Q7 (WebSockets — Reconnection):**
**Exponential backoff with jitter.** Backoff spreads retries over time (1s, 2s, 4s…); jitter randomizes within each window so 200k clients don't reconnect in synchronized waves.

---

**Q8 (CDN — Cache-Control):**
```
T=0:   MISS → fetch origin, cache fresh for 60s (s-maxage).
T=61:  STALE → stale-while-revalidate serves cached copy immediately;
       async background revalidation to origin.
T=361: Beyond SWR window → synchronous revalidation required.
T=500 (origin down): stale-if-error serves stale up to 86400s
       instead of 502/504.
```

---

**Q9 (DNS — JVM):**
JVM caches DNS **indefinitely** by default (`networkaddress.cache.ttl=-1`). Python uses OS resolver and honors TTL. Fix: `-Dsun.net.inetaddr.ttl=30` or set `networkaddress.cache.ttl=30` in `java.security`.

---

**Q10 (SQL — Phantom Reads):**
**SERIALIZABLE** prevents phantom reads. **READ COMMITTED** and **REPEATABLE READ** (Postgres MVCC snapshot) may still see phantoms depending on engine; SERIALIZABLE is the safe answer.

---

**Q11 (NoSQL — Document vs Wide-Column):**
**Document store** (MongoDB, DynamoDB document mode) — nested JSON, secondary indexes, multi-document transactions within a partition. Wide-column (Cassandra) optimizes flat wide rows keyed by partition key, not arbitrary nested documents.

---

**Q12 (Caching — Thundering Herd):**
**Cache stampede / thundering herd** — TTL expired simultaneously for 50k users; all miss cache and hit DB. Infra fix without app code: **request coalescing / single-flight** at CDN or Redis proxy (e.g., `proxy_cache_lock on` in nginx, or CDN origin shield with mutex).

---

**Q13 (Consistency — Read-Your-Writes):**
**Read-your-writes** consistency failed. Simplest fix: route the user's reads to the primary (or session-sticky replica) for a short window after write, without requiring synchronous replication cluster-wide.

---

**Q14 (Consistent Hashing):**
With consistent hashing, adding 1 node to N nodes moves approximately **1/(N+1)** of keys — ~25% for 3→4 nodes. Naive modulo moves ~75%. Virtual nodes improve uniformity but same fraction moves.

---

**Q15 (CAP — Shopping Cart):**
Choose **AP** (availability + partition tolerance) — accept writes during partition. Risk: **divergent cart state** on split nodes; resolve with CRDT merge, last-write-wins, or reconciliation when partition heals. CP would reject writes and lose revenue.

---

**Q16 (Raft — RequestVote):**
Follower updates its term to **5** (sees higher term), then grants vote if log is at least as up-to-date. It rejects votes for stale terms.

---

**Q17 (Split Brain):**
**Quorum requirement** — only a leader elected by majority of votes can accept writes. Two leaders cannot both hold majority in a 5-node cluster. **Fencing tokens** on storage prevent stale leader writes.

---

**Q18 (Quorum — R+W>N):**
R+W=4 > N=3, so reads and writes quorums **overlap** — a read after successful write should see the write. With async replication timing, stale reads are still possible briefly; strict linearizability needs W=majority + read from leader or R=majority with sync.

---

**Q19 (Indexing — Composite Order):**
**(status, created_at)** — equality filter on `status` first, then range on `created_at` within matching status rows. `(created_at, status)` forces scanning all recent dates across all statuses before filtering.

---

**Q20 (Query Plans — Seq Scan):**
(1) **Low selectivity** — index would return most of 200M rows; seq scan cheaper. (2) **Stale statistics** — planner underestimates index benefit. Also: `work_mem` too low for index-only scan, or query wraps column preventing index use.

---

**Q21 (WAL/CDC — Slot Bloat):**
Replicas are healthy (replay keeps up). The **Debezium replication slot** holds WAL on the primary because the connector hasn't confirmed flush LSN — consumers of the slot lag, not streaming replicas. Primary disk grows from **retained WAL for the slot**.

---

**Q22 (Cassandra — Read CL):**
R+W>N: W=2, R=1, N=3 → 2+1=3, barely overlaps. Fix: **`CL=QUORUM` reads** (R=2) so R+W=4>3, guaranteeing overlap with write quorum.

---

**Q23 (Kafka — Partition Limit):**
**16 pods idle** (48−32). Each partition is consumed by at most one consumer in the group. Adding pods beyond partition count cannot increase parallelism — must **increase partition count** (with rebalancing caveats).

---

**Q24 (Saga — Compensation Timeout):**
Saga state: **compensating / stuck** — forward steps 1–2 committed, step 3 failed, compensation in-flight. Customer may see charge without shipment. **Idempotency key:** same `payment_id` or `refund_idempotency_key` derived from original charge ID for Stripe retry safety.

---

**Q25 (Outbox — Debezium Stall):**
Orders are **NOT lost** (committed in DB). Events are **delayed, not lost** (rows in outbox table). Week 5 threat: **WAL bloat** from replication slot retaining unflushed LSN, filling primary disk.

---

**Q26 (API Gateway — Deadline Propagation):**
**Missing deadline propagation / timeout budget.** Gateway 5s deadline doesn't cancel in-flight payment at 4s; payment succeeds after client timeout → **orphan payment / duplicate retry risk**. Fix: propagate `grpc-timeout` or context deadline.

---

**Q27 (Microservices — Shared DB):**
Anti-pattern: **Shared Database**. `CREATE INDEX CONCURRENTLY` still causes I/O spike and lock contention. **checkout-svc breaks first** — flash sale write load on same tables/indexes; promotions index build competes for I/O and connections.

---

**Q28 (Rate Limiting — Burst):**
**Token bucket** — allows accumulated tokens for bursts (20/sec for 5s) while maintaining 100/min average drain rate. Sliding window log is accurate but memory-heavy per user; token bucket is standard for burst tolerance.

---

**Q29 (Rate Limiting — Sliding Window):**
**Sliding window counter** or **Redis cell** algorithm — divides window into sub-buckets, avoids boundary effects of fixed windows. For clock skew: use **Redis server time** (`TIME` command) as authority, not app clocks.

---

**Q30 (CDN — Cache Poisoning):**
**Host header injection** on shared CDN IP without origin validating Host. Fix: CDN sends **`X-Forwarded-Host`** or origin validates `Host` matches expected domain; CDN **cache key includes Host header**.

---

**Q31 (Clocks — Lamport):**
**Impossible.** If A happens-before B, then L(A) < L(B) always. L(B)=3 < L(A)=5 contradicts causal order — indicates clock not properly updated or events misidentified.

---

**Q32 (CRDTs — Offline):**
**CRDT** — merge function is commutative/associative/idempotent; no central server needed for convergence. OT requires central transformation server or lock-step synchronization; offline OT diverges without coordination.

---

**Q33 (Geospatial — Index Choice):**
**H3/S2** for uniform hexagonal cells with hierarchical resolution — better than GeoHash for edge/corner neighbors. GeoHash has anisotropy (rectangles distort at poles). Grid naive scan is O(all drivers) per query — fails at city scale.

---

**Q34 (SLOs — Burn Rate):**
At 14.4× burn: budget exhausted in **43.2 / 14.4 = 3 minutes** if rate holds. Alert correctly signals imminent SLO breach requiring immediate rollback or traffic shed.

---

**Q35 (WhatsApp — Delivery):**
Messages **stored on server** when recipient offline; delivered on reconnect (store-and-forward). **Ordering within a chat** guaranteed via server-assigned sequence numbers or timestamps per conversation; cross-chat ordering not guaranteed.

---

**Q36 (Twitter — Celebrity Fan-out):**
**Fan-out-on-write fails** — writing 80M timeline rows per tweet is O(followers). **Hybrid:** fan-out-on-write for normal users; **fan-out-on-read** for celebrities (merge celebrity tweets at read time from separate cache).

---

**Q37 (Twitter — Timeline Merge):**
**Precomputed home timeline** in Redis/cache per user (fan-out-on-write for normal accounts). For read: fetch cached timeline (bounded size, e.g., top 800 tweets), merge celebrity tweets, rank by score. Data structure: **sorted set** by timestamp/score.

---

**Q38 (YouTube — Pipeline):**
Upload → **blob storage** → **transcoding** (multiple resolutions) → **thumbnail generation** → **CDN distribution** (edge caching) → **DASH manifest** served to client. CDN serves segments; origin is object storage behind CDN.

---

**Q39 (Uber — Matching):**
**Geospatial index** (GeoHash grid, H3, or quadtree). Naive grid scan checks all drivers O(n). Index queries only neighboring cells within 2km radius — O(log n + k) where k is nearby drivers.

---

**Q40 (YouTube — ABR):**
Player **downgrades to lower bitrate** rendition from DASH manifest. CDN helps via **multiple bitrate segments pre-cached at edge** and **origin shield** so downgrade fetches don't hit origin.

---

**Q41 (Payments — Idempotency):**
**Idempotency-Key** header (or `payment_intent` client key). DB: **unique constraint** on `(merchant_id, idempotency_key)` or Stripe's native idempotency. Second request returns same result, no double charge.

---

**Q42 (Payments — Exactly-Once):**
**Not achievable end-to-end.** Correct guarantee: **at-least-once delivery + idempotent consumers** = **effectively-once** processing for payments.

---

**Q43 (Search — Inverted Index):**
Tokenize query → **lookup each term in inverted index** (posting lists of doc IDs) → **intersect/merge posting lists** (AND/OR) → fetch doc metadata → rank by BM25/PageRank.

---

**Q44 (Crawler — robots.txt):**
**Skip** — `robots.txt` disallow takes precedence; sitemap does not override disallow. Rate limiting: **token bucket per domain** (1 req/sec) with centralized politeness scheduler.

---

**Q45 (Distributed KV — Fencing):**
**Fencing token** — new leader gets monotonically increasing token; storage rejects writes with stale (lower) token from old leader. Prevents zombie leader from corrupting state after failover.

---

**Q46 (Kafka — Hot Partition):**
Symptom: **single partition at 100% disk/CPU**, consumer lag on one partition only. Redesign: **compound key** `hash(user_id + session_id)` or **salted key** `hash(user_id + random_bucket)` to spread load.

---

**Q47 (Config Store — Watch Storm):**
Push watches don't scale to 10k watchers on bulk update. Mitigation: **version polling with long poll**, **hierarchical config with local cache + TTL**, **debounced watch notifications**, or **gossip-based propagation** (Consul).

---

**Q48 (Google Docs — Offline Merge):**
**CRDT** — each replica merges independently using commutative operations; no central merge server. OT requires transformation server to serialize concurrent ops.

---

**Q49 (LLM Serving — Batching):**
**Continuous batching** (vLLM/TGI) — dynamically batch incoming requests. Watch **GPU KV-cache utilization** and **batch token throughput**; also **TTFT vs TPOT** tradeoff under queue depth.

---

**Q50 (Feature Store — Online/Offline):**
**Offline:** S3 Parquet for training (hourly batch). **Online:** Redis/Dynamo for <10ms serving. Sync: **Kafka Connect** or **Flink** stream from offline pipeline; **point-in-time** exports for training prevent leakage.

---

# Part 2: Compound Scenario Answers

---

## Scenario A: Black Friday Total System Failure

### A1: Six Symptoms — Layer, Root Cause, Evidence

**Symptom 1: Stock mismatch (CDN/Caching + Consistency)**
Root cause: Product page cached at CDN with `s-maxage=300` including stale inventory count; checkout hits live inventory-svc/DB.
```
Evidence: WebSocket counter (live) vs page (cached) diverge
          CDN cache HIT on product API; inventory-svc shows 0
```

**Symptom 2: gRPC payment latency (gRPC/L4 LB)**
Root cause: L4 LB pins gRPC HTTP/2 connections to 2 of 5 payment replicas.
```
Evidence: CPU 92%/89% on 2 replicas, 3–5% on others
          p99 4.8s on hot replicas; architecture says L4 LB
```

**Symptom 3: Redis 429 storm (Rate Limiting)**
Root cause: Redis memory 98% → evictions corrupt rate-limit counters; bot traffic shares per-IP limits with NAT users; legitimate users throttled.
```
Evidence: 40% 429 on legitimate cohort; Redis evicted_keys spike
          memory 98%; no separate bot bucket
```

**Symptom 4: Fulfillment lag + Debezium (Kafka/CDC/Outbox)**
Root cause: Debezium slot lag 45 min retains WAL; fulfillment consumers starved; events committed in outbox but unpublished.
```
Evidence: lag 120k; slot confirmed_flush_lsn frozen
          customers charged (checkout OK) but no fulfillment event
```

**Symptom 5: EU slow load (HTTP/3/QUIC)**
Root cause: QUIC UDP 443 blocked by corporate firewall; browser times out QUIC then falls back to TCP.
```
Evidence: QUIC success 71%; 15s first load, then fine
          EU corporate network pattern
```

**Symptom 6: GraphQL $0 cart (GraphQL Error Masking)**
Root cause: Partial GraphQL errors return HTTP 200; `cart.total` resolver failed silently; monitoring sees 0% 5xx.
```
Evidence: 0% HTTP errors; support tickets for $0 total
          errors[] field populated in responses
```

**Symptom 7 (implicit): inventory OOM + shared DB (Microservices Anti-pattern)**
Root cause: promotions-svc and checkout-svc share Postgres pool; promotions load + flash sale exhausts connections; inventory-svc OOM from connection wait.
```
Evidence: OOMKilled inventory-svc; pool exhausted
          two services on same DB instance
```

**Mitigations for Symptoms 4–6 (after top 3 stabilized):**

```bash
# SYMPTOM 4: Debezium / fulfillment lag
# Scale Debezium connector tasks
curl -X PUT debezium-connect:8083/connectors/orders-outbox-pub/tasks/scale \
  -H "Content-Type: application/json" -d '{"tasks.max": 8}'

# Monitor slot advance (MUST decrease)
psql -c "SELECT slot_name, pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn)) AS retained FROM pg_replication_slots WHERE slot_name='debezium_outbox_orders';"

# Scale fulfillment consumers (≤ partition count)
kubectl scale deployment/fulfillment-svc --replicas=32

# SYMPTOM 5: EU QUIC fallback
# Short-term: disable HTTP/3 on CloudFront for EU enterprise ASN ranges
# Or reduce QUIC timeout via Alt-Svc max-age + early TCP fallback hint

# SYMPTOM 6: GraphQL $0 cart
# Add GraphQL error monitoring immediately:
# alert: rate(graphql_errors_total[5m]) > 0
# WHERE graphql_errors_total counts responses with non-empty errors[] field

kubectl set env deployment/catalog-svc GRAPHQL_ERROR_METRICS=enabled
```

---

### A2: Causal Relationships

```
                    Stale CDN inventory (Symptom 1)
                              │
                              ▼ artificial "in stock" demand
                    ┌─────────────────┐
                    │ checkout surge  │
                    └────────┬────────┘
                             │
         ┌───────────────────┼───────────────────┐
         ▼                   ▼                   ▼
  gRPC payment hot      shared DB pool       more orders
  replicas (Sym 2)      exhausted (Sym 7)    written
         │                   │                   │
         │                   ▼                   ▼
         │            inventory OOM         outbox grows
         │                                   │
         └──────── retries ──────────────────┤
                                             ▼
                                    Debezium lag (Sym 4)
                                             │
                                             ▼
                                    fulfillment lag

  Redis memory pressure (Sym 3) ← connection storms from retries
       │
       ▼
  429 on legitimate users → more client retries → worse Redis load
```

---

### A3: Priority Ranking

```
╔═════╦══════════════════════════╦══════════════════════════════════════════╗
║ RANK║ SYMPTOM                  ║ JUSTIFICATION                            ║
╠═════╬══════════════════════════╬══════════════════════════════════════════╣
║  1  ║ Stock mismatch (Sym 1)   ║ DATA INTEGRITY — users make purchase     ║
║     ║                          ║ decisions on false availability. Drives  ║
║     ║                          ║ artificial demand amplifying all else.   ║
╠═════╬══════════════════════════╬══════════════════════════════════════════╣
║  2  ║ gRPC payments (Sym 2)    ║ REVENUE — payment SLO breach; charges   ║
║     ║                          ║ timing out. Fixes reduce retry storms.   ║
╠═════╬══════════════════════════╬══════════════════════════════════════════╣
║  3  ║ Shared DB / OOM (Sym 7)  ║ BLAST RADIUS — blocks all checkout and  ║
║     ║                          ║ inventory; cascade source for Sym 4.     ║
╠═════╬══════════════════════════╬══════════════════════════════════════════╣
║  4  ║ Debezium lag (Sym 4)     ║ FULFILLMENT — money captured, orders    ║
║     ║                          ║ not shipped; WAL disk risk on primary.   ║
╠═════╬══════════════════════════╬══════════════════════════════════════════╣
║  5  ║ Redis 429 (Sym 3)        ║ UX — blocks users but less data corrupt  ║
╠═════╬══════════════════════════╬══════════════════════════════════════════╣
║  6  ║ EU QUIC (Sym 5)          ║ NARROW — subset, first-load only         ║
╠═════╬══════════════════════════╬══════════════════════════════════════════╣
║  7  ║ GraphQL $0 (Sym 6)       ║ LOWER volume than payment fail; fix      ║
║     ║                          ║ after core path stable                   ║
╚═════╩══════════════════════════╩══════════════════════════════════════════╝
```

---

### A4: Top 3 Mitigations

**Priority 1 — Stale inventory cache:**
```bash
# Purge CDN cache for product/inventory paths
aws cloudfront create-invalidation \
  --distribution-id $CF_ID \
  --paths "/api/products/*" "/graphql"

# Roll back cache headers on product API
kubectl rollout undo deployment/catalog-svc

# Verify: inventory must not be in CDN-cached response
curl -sI "https://api.example.com/products/SKU-123" | grep -i cache-control
# Expect: private, no-cache (not public, s-maxage)
```

**Priority 2 — gRPC black hole:**
```bash
# Force connection redistribution
kubectl rollout restart deployment/checkout-svc

# Verify CPU equalizes
kubectl top pods -l app=payments-svc --watch
# Target: all replicas 15-25% CPU, p99 < 2s

# Post-incident: deploy L7 gRPC-aware LB (Envoy/Istio)
```

**Priority 3 — Shared DB exhaustion:**
```bash
# Emergency: scale connection pooler (PgBouncer)
kubectl scale deployment/pgbouncer --replicas=5

# Throttle promotions-svc (non-critical during incident)
kubectl scale deployment/promotions-svc --replicas=0

# Scale inventory-svc with memory headroom
kubectl set resources deployment/inventory-svc \
  --limits=memory=4Gi --requests=memory=2Gi

# Verify pool
psql -c "SELECT count(*) FROM pg_stat_activity WHERE state='active';"
```

### Mitigation Timeline — Scenario A

```
╔═══════════════════════════════════════════════════════════════╗
║  T+0s      │ Purge CDN product/inventory cache paths          ║
║  T+15s     │ Roll back catalog-svc cache-header deploy        ║
║  T+30s     │ Restart checkout-svc (redistribute gRPC conns)   ║
║  T+45s     │ Scale promotions-svc to 0 (stop shared DB load)  ║
║  T+60s     │ Scale PgBouncer; verify payments CPU equalized   ║
║  T+90s     │ redis-cli MEMORY PURGE; raise maxmemory-policy   ║
║  T+120s    │ Scale CoreDNS / fix ndots if DNS elevated        ║
║  T+180s    │ Scale Debezium tasks; monitor slot LSN advance   ║
║  T+300s    │ Verify checkout success > 99%; payment p99 < 2s  ║
║            │                                                  ║
║  LATER     │ Deploy L7 gRPC LB; separate Postgres per svc     ║
║  (post)    │ GraphQL error-field alert; QUIC fallback hint    ║
╚═══════════════════════════════════════════════════════════════╝
```

---

### A5: Post-Incident Actions

```
╔════════════════════════════════════════════════════════════════════╗
║ # │ ACTION                              │ OWNER        │ WEEK REF  ║
╠═══╬═════════════════════════════════════╬══════════════╬═══════════╣
║ 1 │ Separate Postgres per service       │ Platform     │ Week 6    ║
║ 2 │ Deploy L7 gRPC load balancing       │ SRE          │ Week 1/6  ║
║ 3 │ SLO: separate checkout vs payment   │ SRE          │ Week 8    ║
║ 4 │ Error budget burn alerts at 6×/14×  │ SRE          │ Week 8    ║
║ 5 │ Debezium slot lag + WAL bytes alert │ Data Eng     │ Week 5/6  ║
║ 6 │ Outbox replay runbook + slot monitor│ Data Eng     │ Week 6    ║
║ 7 │ GraphQL error field monitoring      │ App Eng      │ Week 1    ║
║ 8 │ CDN cache policy audit (no dynamic)   │ Frontend SRE │ Week 1/7  ║
╚═══╩═════════════════════════════════════╩══════════════╩═══════════╝
```

---

## Scenario B: Search Platform Index Corruption

### B1: Five Problems

| # | Problem | Layer | Root Cause |
|---|---------|-------|------------|
| 1 | Missing recent headlines | Inverted index / freshness | Index lag 47 min; pipeline can't keep up with 12× crawl |
| 2 | Shard 47 corruption | Replication / leader failover | Leader OOM during merge; follower promoted with partial WAL |
| 3 | robots.txt 429 storm | Crawler politeness | 24h robots cache stale; publisher blocked; workers retry aggressively |
| 4 | etcd watch latency | Config/consensus | Watch storm from 10k workers; etcd CPU saturated |
| 5 | KV duplicate docs | Distributed KV / clocks | Vector clock conflicts on URL dedup → same doc indexed twice |
| 6 | Monitoring blind spot | Observability | 0% API errors; no **result quality / recall SLI** |

---

### B2: Observability Gap — Expert Analysis

HTTP 200 with incomplete results is a **silent quality degradation** — the worst class of monitoring blind spot because all infrastructure metrics look healthy.

```
WHAT STANDARD MONITORING SHOWS          WHAT USERS EXPERIENCE
────────────────────────────────────────────────────────────────
search_api_requests_total ↑             "Breaking news missing"
search_api_latency_p99: 95ms ✓          Results feel "incomplete"
search_api_errors_total: 0 ✓            18% fewer results for news
shard_47_cpu: 78% ✓                     Wrong ranking for fresh docs
```

**SLIs that would catch this:**

| SLI | Measurement | Alert Threshold |
|-----|-------------|-----------------|
| `query_recall@10` | Golden-set queries vs expected doc IDs | Drop > 5% for 5 min |
| `index_freshness_lag_minutes` | `now() - max(doc_indexed_at)` | > 15 min |
| `per_shard_doc_count_drift` | Shard doc count vs 24h rolling median | > 10% deviation |
| `news_query_result_count_ratio` | Result count vs category baseline | < 0.85 for 10 min |

The 0% error rate is technically correct — the API returned valid JSON. The **quality SLI** is what's missing. This is Week 8 observability: measure symptoms users feel, not just HTTP status codes.

---

### B3: Priority Ranking

```
╔═════╦══════════════════════════════╦══════════════════════════════════════════╗
║ RANK║ PROBLEM                      ║ JUSTIFICATION                            ║
╠═════╬══════════════════════════════╬══════════════════════════════════════════╣
║  1  ║ Quarantine shard 47          ║ INTEGRITY — corrupted posting lists      ║
║     ║                              ║ actively serve wrong results; stop bleed   ║
╠═════╬══════════════════════════════╬══════════════════════════════════════════╣
║  2  ║ Rebuild shard 47             ║ USER-VISIBLE — 12% of "bre*" terms wrong ║
║     ║                              ║ news queries most affected               ║
╠═════╬══════════════════════════════╬══════════════════════════════════════════╣
║  3  ║ Throttle crawl + robots fix  ║ STOP MAKING WORSE — 429 storm risks IP   ║
║     ║                              ║ ban; stale robots.txt violates politeness║
╠═════╬══════════════════════════════╬══════════════════════════════════════════╣
║  4  ║ Index pipeline lag (freshness) ║ SLO breach but existing index servable   ║
║     ║                              ║ for non-news queries                     ║
╠═════╬══════════════════════════════╬══════════════════════════════════════════╣
║  5  ║ etcd watch storm             ║ DELAYED config — crawl budget not updated  ║
║     ║                              ║ but manual throttle works short-term       ║
╠═════╬══════════════════════════════╬══════════════════════════════════════════╣
║  6  ║ KV vector clock duplicates   ║ 0.3% dup rate — slow burn; dedup in merge║
╠═════╬══════════════════════════════╬══════════════════════════════════════════╣
║  7  ║ Observability gap            ║ POST-INCIDENT — doesn't fix active users   ║
╚═════╩══════════════════════════════╩══════════════════════════════════════════╝
```

---

### B4: Immediate Mitigations

```bash
# (a) Quarantine shard 47 — remove from serving scatter-gather
curl -X POST etcd:2379/v2/keys/shard_map/47 -d value='{"status":"quarantine"}'

# (b) Rebuild shard 47 from Kafka index.documents compacted topic
kafka-consumer-groups --bootstrap-server $KAFKA --group rebuild-47 \
  --reset-offsets --to-earliest --topic index.documents --execute

# Run rebuild job targeting terms hash → shard 47 only
kubectl create job rebuild-shard-47 --image=indexer:v2 \
  -- --shard=47 --source=kafka --verify-checksum

# (c) Flush robots.txt cache
redis-cli --scan --pattern 'robots:*' | xargs redis-cli DEL

# Reduce crawl rate
kubectl set env deployment/crawler-master CRAWL_BUDGET_MULTIPLIER=0.3
```

---

### B5: Steady-State Architecture — Hot-Term OOM

Partition by **term hash** (256 shards) causes hot terms ("bre*") to overload one shard. Fix: **sub-partition hot terms** — detect high-frequency terms, split into **dedicated micro-shards** (consistent hashing with virtual nodes per term). Use **document-frequency threshold** to dynamically split posting lists. Reference Week 3 consistent hashing + Week 12 inverted index sharding.

```
         term "breaking" (hot)
                │
    ┌───────────┼───────────┐
    ▼           ▼           ▼
 shard-47a            shard-47b   shard-47c
 (postings   (postings   (postings
  0-33%)      33-66%)     66-100%)
```

### Mitigation Timeline — Scenario B

```
╔═══════════════════════════════════════════════════════════════╗
║  T+0s      │ Quarantine shard 47 from scatter-gather ring     ║
║  T+30s     │ Flush robots.txt Redis cache (DEL robots:*)      ║
║  T+60s     │ Throttle crawl budget to 30% (CRAWL_MULTIPLIER)  ║
║  T+90s     │ Scale etcd; debounce config watch fanout         ║
║  T+5m      │ Start shard-47 rebuild job from Kafka corpus     ║
║  T+30m     │ Swap shard alias after checksum verify           ║
║  T+1h      │ Deploy result-recall SLI alert on news queries   ║
╚═══════════════════════════════════════════════════════════════╝
```

---

## Scenario C: Realtime Collaboration + AI Platform

### C1: Event Mapping

| Time | Event | Layer | Root Cause |
|------|-------|-------|------------|
| 14:05 | WS disconnect 12%/min | WebSocket/TCP | Missing ping/pong; ALB idle timeout 60s |
| 14:05 | Stale cursors | Presence/Redis | Pub/sub gap during disconnect; TTL not refreshed |
| 14:08 | TTFT 6.2s | LLM serving | No `max_batch_tokens` cap; queue depth 4k; GPU saturated |
| 14:12 | CRDT merge failures 0.8% | CRDT/Clocks | Vector clock skew cross-region; HLC not deployed |
| 14:15 | Stale features 34% | Feature store | Kafka Connect lag; online store not refreshed |
| 14:18 | Composite SLO green | Observability | AND-composite masks AI SLO breach when edit SLO OK |
| 14:20 | Kafka lag 890k | Kafka/durability | Consumer under-provisioned; ops not persisting |

---

### C2: CAP — Consumer Lag + In-Memory CRDT

```
Partition or consumer stall:
  Availability path: edits accepted in memory (AP) — users see local state
  Durability path: Kafka log not consumed — ops not persisted

On crash: in-memory CRDT LOST → "edits vanished"
CAP choice during lag: system chose Availability (accept edits)
                        over Consistency with durable log

Fails first: DURABILITY — RPO violated for 890k ops if gateway crashes
```

**Extended CAP analysis:**

```
                    NORMAL STEADY STATE
                    ───────────────────
  Client → WebSocket → in-memory CRDT → Kafka produce (async)
                              │                    │
                              │                    ▼
                              │              doc.ops topic
                              │                    │
                              │                    ▼
                              │              consumer → durable store
                              │
                    CRDT + log CONSISTENT

                    INCIDENT STATE (lag 890k)
                    ─────────────────────────
  Client → WebSocket → in-memory CRDT → Kafka produce (async)
                              │                    │
                              │                    ╳ consumer stalled
                              │                    │
                              ▼                    ▼
                    Users see edits          Log 890k behind
                    (AVAILABLE)              (NOT durable)

  If gateway crashes NOW:
    - In-memory state: GONE (890k ops since last snapshot)
    - Kafka log: HAS ops (if produce succeeded)
    - Recovery: replay Kafka — but CRDT in-memory diverged from
      what users saw during lag window

  CORRECT INCIDENT CAP CHOICE:
    Option A (CP): reject new edits until lag < threshold
                   "Service temporarily read-only"
    Option B (AP): accept edits + sync persistence mode
                   block client ACK until Kafka produce acks
                   (latency ↑, durability preserved)
```

The architecture failed because it ran **AP during lag without sync produce** — the worst combination for a collaborative editor.

---

### C3: Priority Ranking

```
╔═════╦══════════════════════════════╦══════════════════════════════════════════╗
║ RANK║ PROBLEM                      ║ JUSTIFICATION                            ║
╠═════╬══════════════════════════════╬══════════════════════════════════════════╣
║  1  ║ Kafka consumer lag (890k)    ║ DATA LOSS RISK — in-memory diverges;     ║
║     ║                              ║ gateway crash = edits vanish; RPO breach ║
╠═════╬══════════════════════════════╬══════════════════════════════════════════╣
║  2  ║ CRDT merge failures (0.8%)   ║ DATA INTEGRITY — users lose edits;       ║
║     ║                              ║ vector clock skew is root; legal/docs risk║
╠═════╬══════════════════════════════╬══════════════════════════════════════════╣
║  3  ║ LLM TTFT 6.2s                ║ PRODUCT LAUNCH — SLO breach; 22× burn;   ║
║     ║                              ║ shed load before GPU OOM cascade         ║
╠═════╬══════════════════════════════╬══════════════════════════════════════════╣
║  4  ║ WebSocket disconnect 12%/min ║ UX — reconnect storm risk; fix ping/pong║
║     ║                              ║ stale cursors annoying not data-loss     ║
╠═════╬══════════════════════════════╬══════════════════════════════════════════╣
║  5  ║ Feature store 6h stale       ║ AI QUALITY — wrong rewrite suggestions;  ║
║     ║                              ║ not editor durability                    ║
╠═════╬══════════════════════════════╬══════════════════════════════════════════╣
║  6  ║ Composite SLO false negative ║ OBSERVABILITY — post-incident fix;       ║
║     ║                              ║ doesn't unblock users during incident    ║
╚═════╩══════════════════════════════╩══════════════════════════════════════════╝
```

---

### C4: Top 3 Mitigations

**Priority 1 — Kafka lag:**
```bash
# Scale consumers (must be ≤ partition count or add partitions)
kubectl scale deployment/doc-ops-consumer --replicas=64

# If lag critical: temporarily reject new docs (circuit breaker)
kubectl set env deployment/ws-gateway PERSISTENCE_MODE=sync
# sync mode: block ACK until Kafka produce acks (latency ↑, durability ↑)

kafka-consumer-groups --bootstrap-server $KAFKA \
  --describe --group doc-ops-consumer
```

**Priority 2 — CRDT clock skew:**
```bash
# Enable Hybrid Logical Clock on all gateways
kubectl set env deployment/ws-gateway CLOCK_MODE=HLC

# Pause cross-region traffic to single region (incident stabilization)
kubectl scale deployment/ws-gateway-eu --replicas=0

# Verify merge failure rate
curl metrics/internal/crdt_merge_failures_rate
```

**Priority 3 — LLM TTFT:**
```bash
# Configure continuous batching limits (vLLM)
kubectl set env deployment/llm-serving \
  MAX_NUM_BATCHED_TOKENS=8192 \
  MAX_WAIT_MS=50

# Shed load: rate limit AI endpoint at gateway
kubectl apply -f llm-rate-limit-500rps.yaml

# Scale GPU replicas
kubectl scale deployment/llm-serving --replicas=24
```

**WebSocket heartbeat (parallel):**
```javascript
// Deploy: ping every 25s (below 60s ALB timeout)
setInterval(() => ws.ping(), 25000);
```

---

### C5: SLO Structure — Fix False Negative

```
SLIs (separate, never composite-AND for alerting):
  - edit_propagation_latency_p99  (target < 200ms)
  - ai_ttft_p95                   (target < 1.5s)
  - doc_persistence_lag_seconds   (target < 5s)  ← MISSING in original
  - crdt_merge_success_rate       (target > 99.99%)

Error budgets: 0.1% monthly each (43.2 min)

Burn-rate alerts (per SLI):
  6h window:  burn > 6×  → page
  1h window:  burn > 14× → page critical
  5m window:  burn > 36× → auto rollback canary

Composite dashboard: display only — NEVER alert on AND(all green)
Alert on ANY single SLI budget burn

Add: doc_persistence_lag would have fired at 14:20 (890k lag)
```

### Mitigation Timeline — Scenario C

```
╔═══════════════════════════════════════════════════════════════╗
║  T+0s      │ Scale doc-ops-consumer to partition count (64)   ║
║  T+30s     │ Enable PERSISTENCE_MODE=sync on ws-gateway       ║
║  T+60s     │ Set llm-serving MAX_WAIT_MS=50; shed 50% AI load ║
║  T+90s     │ Deploy WebSocket ping/pong every 25s             ║
║  T+120s    │ Enable HLC; pause eu-west gateway replicas       ║
║  T+180s    │ Force Kafka Connect feature-sync catch-up job    ║
║  T+300s    │ Verify consumer lag < 10k; merge failure < 0.01% ║
║            │                                                  ║
║  LATER     │ Split composite SLO; per-SLI burn-rate alerts    ║
║  (post)    │ CRDT merge test suite for offline 10-min edits   ║
╚═══════════════════════════════════════════════════════════════╝
```

---

# Part 3: Self-Assessment Checklist

Score yourself honestly. Check each box only if you can demonstrate the skill
from memory without looking at modules.

```
╔══════════════════════════════════════════════════════════════╗
║   PART 3 SCORING RUBRIC                                      ║
╟──────────────────────────────────────────────────────────────╢
║   20–24 checked  →  Ready for Week 15 mock interviews        ║
║   16–19 checked  →  Pass gate; review unchecked items        ║
║   12–15 checked  →  1 week targeted review before mocks      ║
║   < 12 checked   →  Re-do retention tests for Weeks 1–8      ║
╚══════════════════════════════════════════════════════════════╝
```

### Transport & Edge (Week 1)

- [ ] I can explain TIME_WAIT, SYN backlog, and tcp_tw_reuse trade-offs
- [ ] I can diagnose HTTP/2 TCP HOL blocking vs HTTP/3 QUIC migration
- [ ] I can trace a DNS resolution failure (ndots, TTL, JVM caching)
- [ ] I can interpret Cache-Control directives and CDN purge behavior
- [ ] I can design WebSocket reconnection with jittered exponential backoff

### Storage & Consistency (Weeks 2–5)

- [ ] I can choose SQL vs NoSQL based on access patterns, not preference
- [ ] I can calculate quorum reads/writes (R+W>N) for RF=3
- [ ] I can explain Raft leader election and log replication
- [ ] I can read an EXPLAIN plan and identify missing indexes
- [ ] I can size a sharding strategy from storage growth and QPS math

### Architecture Patterns (Weeks 6–7)

- [ ] I can design a Kafka topic (partitions, keys, retention, ISR)
- [ ] I can implement transactional outbox with correct two-phase durability
- [ ] I can explain L4 vs L7 load balancing for gRPC long-lived connections
- [ ] I can design a token bucket rate limiter with Redis Lua atomicity
- [ ] I can choose cache-aside vs write-through vs read-through per workload

### Advanced Patterns (Week 8)

- [ ] I can explain Lamport clocks vs vector clocks vs HLC
- [ ] I can describe CRDT merge semantics for a collaborative document
- [ ] I can define SLI, SLO, error budget, and burn-rate alerting
- [ ] I can design a geospatial two-phase query (geohash prefix + distance filter)

### System Designs (Weeks 9–14)

- [ ] I can design a home timeline with hybrid fan-out (write + read merge)
- [ ] I can design a payment flow with idempotency keys and double-entry ledger
- [ ] I can design a ride-matching system with geospatial indexing
- [ ] I can design a search pipeline (crawl → index → rank → serve)
- [ ] I can design a distributed KV store with consistent hashing and hinted handoff
- [ ] I can design an LLM serving platform with queueing, batching, and GPU scheduling

### Cross-Cutting SRE Skills

- [ ] I can prioritize 5+ simultaneous symptoms by blast radius and data integrity
- [ ] I can write immediate mitigation commands (not just architectural fixes)
- [ ] I can identify cascade chains (failure A amplifies failure B)
- [ ] I can distinguish mitigation from root cause in an incident timeline

### Week-Specific Review Map

```text
MISSED AREA                    →  RE-READ MODULE
─────────────────────────────────────────────────────────────
TCP/TIME_WAIT, gRPC LB         →  Week 01: TCP vs UDP
HTTP/2 HOL, QUIC               →  Week 01: HTTP-1.1-vs-HTTP-2-vs-HTTP-3
DNS ndots, TTL                 →  Week 01: DNS Resolution
CDN cache headers              →  Week 01: CDN Fundamentals
WebSocket reconnect            →  Week 01: WebSockets
SQL vs NoSQL                   →  Week 02: SQL Deep Dive, NoSQL Deep Dive
CAP, quorum                    →  Week 03-04: CAP, Raft
DB internals, indexing         →  Week 05: Database Scaling Patterns
Kafka, outbox, saga            →  Week 06: Message Queues and Kafka
Rate limiting, caching         →  Week 07: Rate Limiting, Caching Strategies
CRDTs, SLOs, geospatial        →  Week 08: CRDTs, SLOs, Geospatial
Feed, chat                     →  Week 09: Design Twitter Feed, WhatsApp
Video, Uber                    →  Week 10: Design YouTube, Design Uber
Payments, e-commerce           →  Week 11: Design Payment System
Search, crawler                →  Week 12: Design Google Search, Web Crawler
KV, Kafka, config              →  Week 13: Design Distributed KV, Kafka
Docs, LLM, feature store       →  Week 14: Design Google Docs, LLM Serving
```

---

# Part 3: Self-Assessment — Answer Key Notes

Use the scoring rubric above. If you scored below targets, map missed questions to the **Week-Specific Review Map** and re-read those modules before mock interviews.

**Curriculum completion criteria:**
- Part 1 ≥ 40/50 (80%)
- Part 2 ≥ 10/15 tasks at principal depth
- Part 3 ≥ 16/24 checkboxes

When all three pass, you have demonstrated retention across Weeks 1–14 and are ready for **Week 15 Mock Interviews**.

### Study Guide — If You Failed Specific Areas

**Transport layer blind spots (Q1–Q9):**
Re-read Week 01 modules. The auction platform scenario in `Retention-Tests/Week-01.md` is the gold-standard compound drill. Practice identifying whether a symptom is TCP, HTTP, DNS, CDN, WebSocket, or gRPC before proposing fixes.

**Storage and consistency (Q10–Q18):**
Weeks 02–04 compound in almost every production incident. If you missed quorum math, write out RF=3, W=1/2/3, R=1/2/3 combinations until R+W>N is reflexive. CAP questions require you to name what the user *loses*, not just the letter.

**Database internals (Q19–Q22):**
The Debezium slot vs replica lag distinction (Q21) appears in both Scenario A and Week 06 checkout cascade. Draw two diagrams: streaming replication path vs logical replication slot path.

**Architecture patterns (Q23–Q27):**
Kafka partition ceiling (Q23) and outbox two-phase durability (Q25) are the most commonly forgotten Week 06 facts. Diagram: Phase 1 = DB txn, Phase 2 = publish. Know which phase failed in Scenario A Symptom 4.

**Design modules (Q35–Q50):**
Low scores here mean you remember theory but not system shapes. For each design (Twitter, Uber, Google Search, Google Docs), practice drawing one box-and-arrow diagram from memory in 3 minutes.

### Retake Protocol

```text
ATTEMPT 1  →  Score all parts  →  Map misses to review map
REVIEW     →  2–3 days targeted re-read of failed weeks only
ATTEMPT 2  →  Re-test ONLY missed Part 1 questions + weakest scenario
PASS GATE  →  Part 1 ≥ 40/50, Part 2 ≥ 10/15, Part 3 ≥ 16/24
```

---

*End of Final Retention Test — All Topics*
