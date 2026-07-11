# WEEK 7 RETENTION TEST

## Rules

```
╔══════════════════════════════════════════════════════════════╗
║   RULES OF ENGAGEMENT                                        ║
╟──────────────────────────────────────────────────────────────╢
║                                                              ║
║   1. Answer from MEMORY. Do not re-read the teaching         ║
║      modules. The whole point is to test what STUCK in       ║
║      your brain.                                             ║
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

## Part 1: Rapid-Fire Concept Recall (14 Questions)

Answer ALL 14 in one response. Keep each answer to 2-4 sentences maximum.

**Q1 (Load Balancing):** ALB uses round-robin. Backend pods mix c5.4xlarge (16 vCPU) and c5.xlarge (4 vCPU). p99 latency skews toward the larger instances. Why, and what algorithm or architecture fixes it?

**Q2 (Load Balancing):** Rolling deploy: new pods pass ALB health check (`/health` returns 200) but fail on real traffic for 90 seconds (JIT warmup). Users see 502s. What health check design catches this, and what is connection draining's role?

**Q3 (Load Balancing):** gRPC long-lived HTTP/2 through NLB vs Envoy sidecar with `LEAST_REQUEST`. Checkout latency is bimodal: 12ms or 1.8s. Same symptom as Week 1 gRPC black hole — state why the L7 fix here differs from client-side `round_robin`.

**Q4 (Load Balancing):** Cross-zone ALB disabled. 80% of clients in us-east-1a; pods spread evenly across 3 AZs. Data transfer bill spikes; p99 latency +40ms for majority. Two fixes (one architectural, one config).

**Q5 (Rate Limiting):** Token bucket: 1000 tokens, refill 100/s, burst allowed. Sliding window counter at CloudFront edge says client is under limit; origin ALB returns 429. Explain the discrepancy in one paragraph (edge vs origin, window boundaries).

**Q6 (Rate Limiting):** Global rate limit 10k req/s across 40 API gateway instances. Redis-backed counter with 1s TTL buckets. At exactly 10k/s steady traffic, clients see ~15% false 429s. What went wrong with bucket granularity and what algorithm family fixes it?

**Q7 (Rate Limiting):** User tier limits: free 10 req/min, pro 1000 req/min. Adversary rotates 500 free-tier API keys behind one NAT IP. Fixed IP-based limit blocks legitimate corporate users. Name two limit dimensions and one composite key strategy.

**Q8 (Search):** Elasticsearch index `products`: 12 shards, `refresh_interval=1s`. Write rate 5k docs/s. Search p99 fine; indexing backlog grows 20 min behind. Merchants complain new products invisible. Two tuning levers and one architectural split.

**Q9 (Search):** Query: `title:iphone AND category:electronics`. Inverted index has 40M postings for `electronics`, 2M for `iphone`. Which term do you iterate first in AND intersection, and why does index order not match query order?

**Q10 (Search):** Postgres is source of truth. Debezium → ES near-real-time search. User updates price, searches within 500ms, sees old price. Replication lag 200ms; ES refresh 1s. Break down the staleness budget by layer.

**Q11 (Unique IDs):** Snowflake-style IDs: 41-bit timestamp, 10-bit machine, 12-bit sequence. Clock skew — NTP step -500ms on one generator node. What failure mode hits sort order and B-tree locality, and what is the standard mitigation?

**Q12 (Feature Flags):** LaunchDarkly-style flag evaluated client-side with 60s cache. Kill-switch for payment provider fails to propagate for 90s after toggle. Payments still route to broken provider. Client-side vs server-side evaluation — pick one for kill-switches and defend in two sentences.

**Q13 (Unique IDs):** `UUID v4` as primary key on Postgres orders table, 50k inserts/s. Index bloat and p99 insert latency degrade over 48h. Why (one mechanism), and name one ID scheme that preserves roughly time-ordered inserts.

**Q14 (Feature Flags):** Canary: 5% traffic to v2 via service mesh weight. Error rate v2 = 3%, v1 = 0.1%. SLO allows 0.5% budget burn. Auto-rollback wired to flag. Why might you still promote manually, and what metric besides error rate do you watch?

---

## Part 2: Compound SRE Scenario

This scenario requires knowledge from **Load Balancing, Rate Limiting, Search/Indexes, Unique IDs, and Feature Flags** simultaneously. The challenge is identifying which layer each symptom belongs to and how a product launch day amplifies latent misconfigurations.

```
INCIDENT REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Severity: P1
Service: E-commerce product search + checkout
  (think: Amazon product launch day, limited drops)

  New product line launches at 10:00 UTC.
  Search must surface SKUs within 60 seconds of
  catalog write. Checkout conversion SLO: 99.5%.
  Platform handles 80,000 search QPS at peak.

ARCHITECTURE:

  ╔════════════════════════════════════════════════════════════════╗
  ║   CLIENT / EDGE LAYER                                          ║
  ║   Browser/Mobile → CloudFront (HTTP/2)                         ║
  ║     → Rate limit: 5k req/s per client IP (fixed window)        ║
  ║     → ALB (cross-zone ON, round-robin)                         ║
  ║                                                                ║
  ║   SEARCH PATH                                                  ║
  ║   ALB → search-api (30 pods, Java, us-east-1)                  ║
  ║     → Elasticsearch 8.x cluster (12 data nodes)                ║
  ║     → Index: products_v2 (24 primary shards, RF=1)             ║
  ║                                                                ║
  ║   CHECKOUT PATH (healthy, separate team)                       ║
  ║   api-gateway → checkout-svc (unchanged, green metrics)        ║
  ║     → RDS orders DB (bigint serial PK, legacy)                 ║
  ║                                                                ║
  ║   DATA / CDC PATH                                              ║
  ║   PostgreSQL products DB → Debezium → MSK products.changes     ║
  ║     → ES indexer (16 pods) → products_v2 index                 ║
  ║   Strangler fig Phase 2: reads split, writes dual-write        ║
  ║     New catalog: UUID v7 in Postgres                           ║
  ║     Legacy path: bigint in orders DB                           ║
  ║                                                                ║
  ║   RATE LIMITING (stacked)                                      ║
  ║   CloudFront edge: 5k req/s per IP (fixed window)              ║
  ║   api-gateway: 10k req/s global Redis counter (1s buckets)     ║
  ║   Per-user tier limits: NOT implemented                        ║
  ║                                                                ║
  ║   FEATURE FLAGS (server-side, search-api)                      ║
  ║   search_v2_rollout: 10% canary (Istio traffic weight)         ║
  ║   search_v2_index: routes queries to products_v2 vs v1         ║
  ║   No client-side flag cache                                    ║
  ║                                                                ║
  ║   ES CLUSTER STATE (at incident)                               ║
  ║   products_v2: 24 shards, RF=1 (cost save during dev)          ║
  ║   Background reindex from products_v1 still running            ║
  ║   Hot threads: merge throttling active                         ║
  ╚════════════════════════════════════════════════════════════════╝

INCIDENT TIMELINE:

  10:00 — Product launch. Marketing drives 80k search QPS.

  10:15 — search team deploys search-v2:
          New ES mapping, products_v2 index,
          24 shards, refresh_interval=1s.

  10:18 — oncall-app: "Browse OK; /search?q=launch-deal
          times out >5s."

  10:22 — ALB TargetResponseTime p99 4.2s on search-api.
          CPU only 35% — not CPU-bound.

  10:28 — Debezium → ES lag 12 min and climbing.
          Indexing rate 8k docs/s. Cluster status: YELLOW.

  10:35 — Feature flag search_v2_rollout enabled at 10%
          canary. Latency WORSE on canary subset.

  10:41 — Emergency: Redis rate limit 5k req/s per IP
          added at CloudFront edge.
          Support: corporate customers blocked —
          shared egress IP.

  10:48 — Product IDs in search results don't match
          checkout. UUID v7 in search, bigint in orders.

  10:55 — Scaled ES data nodes 6→12. Still YELLOW —
          unassigned shards persist.

  11:02 — PagerDuty P1: search p99 > 2s (SLO 300ms).
          api-gateway 429 rate 18%.
          Checkout conversion drop 22% (symptom alert).
          YOU join bridge.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Question 1:** There are at least SIX distinct problems in this incident. For each one:
- Name the problem
- Identify which LAYER it belongs to (CDN, LB, rate limit, search, CDC, feature flags, IDs)
- Classify as root cause, amplifier, or symptom
- Cite the specific monitoring evidence

**Question 2:** ES cluster YELLOW with unassigned shards after scaling 6→12 nodes. What are the top TWO causes you check first, and what `/_cat/shards` / `/_cluster/allocation/explain` outcomes confirm each?

**Question 3:** The 10:41 rate-limit change fixed neither search latency nor checkout conversion. Explain why per-IP limiting harmed corporate users AND why global 10k/s Redis buckets still allow gateway 429s at steady 10k/s traffic.

**Question 4:** Debezium lag 12 min but browse (Postgres read path) is fine. User searches new SKU, finds it, add-to-cart fails "product not found." Trace the failure using ID mismatch + strangler fig Phase 2. What parity gate was skipped?

**Question 5:** Canary at 10% shows WORSE latency on v2. Name THREE reasons a canary can perform worse than baseline even when code is "better."

**Question 6:** Design the rollback sequence at 11:05 with minimal customer impact. Order of flag toggles, index routing, rate limit removal, and deploy rollback. Justify sequencing in terms of blast radius.

**Question 7:** Six post-incident action items with owners: two search/ES, two rate limiting, one ID/migration, one feature-flag/canary process. Include acceptance criteria for each.

---



---

> **Answer key (do not open until you attempt the Ops Sim / questions):**  
> [`../answers/Retention-Tests/Week-07 Answers.md`](../answers/Retention-Tests/Week-07 Answers.md)

