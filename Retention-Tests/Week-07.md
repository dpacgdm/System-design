# WEEK 7 RETENTION TEST

Covers **Weeks 1–7** (transport through specialized components). Answer from memory before opening worked-answer files or teaching modules.

---

## Rules

```
╔═══════════════════════════════════════════════════════════════╗
║   RULES OF ENGAGEMENT                                         ║
╟───────────────────────────────────────────────────────────────╢
║                                                               ║
║   1. Answer from MEMORY. Do not re-read the teaching modules. ║
║                                                               ║
║   2. Rapid-fire: 2–4 sentences per question.                  ║
║                                                               ║
║   3. Compound scenario: full depth expected.                  ║
║                                                               ║
║   4. "I don't remember" is valid — it tells us what to        ║
║      review.                                                  ║
╚═══════════════════════════════════════════════════════════════╝
```

---

## Part 1: Cross-Week Rapid-Fire (Weeks 1–6 recall)

**Q1 (Week 1 — HTTP):** ALB idle timeout is 60s. WebSocket connections drop every 60s exactly. WebSocket server CPU is 30%. What is the fix, and why is NLB idle timeout (350s) a red herring?

**Q2 (Week 4 — Sharding):** Shard key is `tenant_id`. Query: "top 10 products by revenue globally, last 24h." What happens on the OLTP cluster, and what system serves this query instead?

**Q3 (Week 5 — PgBouncer):** Transaction-pooled PgBouncer. App uses `SET LOCAL app.user_id = 42` for RLS. User A intermittently sees User B's rows. Explain in one mechanism sentence and one fix.

**Q4 (Week 6 — Kafka):** Consumer group rebalance storm during deploy: `max.poll.interval.ms` exceeded on 30% of pods. Lag spikes from 2s to 20 minutes. Name two config/levers (one consumer, one ops) that stop the storm without reducing partition count.

**Q5 (Week 6 — Saga):** Choreographed saga over Kafka: PaymentCharged published, ShipmentCreated consumer crashes after DB write, before offset commit. Offset rewinds on restart. What breaks without idempotency, and what key do you dedupe on?

**Q6 (Week 6 — Outbox):** Schema Registry set to `BACKWARD`. Producer deploy drops optional field `gift_message`. Debezium connector halts with deserialization error. Why did compatibility mode not save you, and what mode/policy would have?

---

## Part 2: Week 7 Rapid-Fire (Load Balancing / Rate Limiting / Search / IDs / Feature Flags)

Answer all 12. Keep each answer concise.

**Q7 (Load Balancing):** ALB uses round-robin. Backend pods have heterogeneous CPU (c5.4xlarge mixed with c5.xlarge). p99 latency skews to larger instances. Why, and what algorithm or architecture fixes it?

**Q8 (Load Balancing):** Rolling deploy: new pods pass ALB health check (`/health` returns 200) but fail on real traffic for 90 seconds (JIT warmup). Users see 502s. What health check design catches this, and what is connection draining's role?

**Q9 (Load Balancing):** gRPC long-lived HTTP/2 through NLB vs Envoy with `LEAST_REQUEST`. Checkout latency bimodal: 12ms or 1.8s. Same symptom as Week 1 — state why L7 fix differs from client-side `round_robin` here.

**Q10 (Load Balancing):** Cross-zone ALB disabled. 80% of clients in us-east-1a; pods spread evenly across 3 AZs. Data transfer bill spikes; p99 latency +40ms for majority. Two fixes (one architectural, one config).

**Q11 (Rate Limiting):** Token bucket: 1000 tokens, refill 100/s, burst allowed. Sliding window counter at edge says client is under limit; origin returns 429. Explain the discrepancy in one paragraph (edge vs origin, window boundaries).

**Q12 (Rate Limiting):** Global rate limit 10k req/s across 40 API gateway instances. Redis-backed counter with 1s TTL buckets. At exactly 10k/s steady traffic, clients see ~15% false 429s. What went wrong with bucket granularity and what algorithm family fixes it?

**Q13 (Rate Limiting):** User tier limits: free 10 req/min, pro 1000 req/min. Adversary rotates 500 free-tier API keys behind one NAT IP. Fixed IP-based limit blocks legitimate corporate users. Name two limit dimensions and one composite key strategy.

**Q14 (Search):** Elasticsearch index `products`: 12 shards, `refresh_interval=1s`. Write rate 5k docs/s. Search p99 fine; indexing backlog grows 20 min behind. Merchants complain new products invisible. Two tuning levers and one architectural split.

**Q15 (Search):** Query: `title:iphone AND category:electronics`. Inverted index has 40M postings for `electronics`, 2M for `iphone`. Which term do you iterate first in AND intersection, and why does index order not match query order?

**Q16 (Search):** Postgres is source of truth. Debezium → ES near-real-time search. User updates price, searches within 500ms, sees old price. Replication lag 200ms; ES refresh 1s. Break down the staleness budget by layer.

**Q17 (Unique IDs):** Snowflake-style IDs: 41-bit timestamp, 10-bit machine, 12-bit sequence. Clock skew NTP step -500ms on one generator node. What failure mode hits sort order and DB B-tree locality, and what is the standard mitigation?

**Q18 (Unique IDs):** `UUID v4` as primary key on Postgres orders table, 50k inserts/s. Index bloat and p99 insert latency degrade over 48h. Why (one mechanism), and name one ID scheme that preserves roughly time-ordered inserts.

**Q19 (Feature Flags):** LaunchDarkly-style flag evaluated client-side with 60s cache. Kill-switch for payment provider fails to propagate for 90s after toggle. Payments still route to broken provider. Client-side vs server-side evaluation — pick one for kill-switches and defend in two sentences.

**Q20 (Feature Flags):** Canary: 5% traffic to v2 via service mesh weight. Error rate v2 = 3%, v1 = 0.1%. SLO allows 0.5% budget burn. Auto-rollback wired to flag. Why might you still promote manually, and what metric besides error rate do you watch?

---

## Part 3: Compound SRE Scenario — "The Search Launch Meltdown"

```text
THE PAGE (11:02 UTC, product launch day):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  PagerDuty: [P1] search p99 > 2s (SLO 300ms)
             [P2] api-gateway 429 rate 18%
             [P1] checkout conversion drop 22% (symptom alert)

  Slack #incidents (last 50 minutes):

    10:15  oncall-search:  "Deployed search-v2: new ES index
                            mapping, 24 shards, refresh=1s."
    10:18  oncall-app:      "Browse OK; /search?q=launch-deal
                            times out >5s."
    10:22  oncall-platform: "ALB TargetResponseTime p99 4.2s
                            on search-api only. CPU 35%."
    10:28  oncall-data:     "Debezium → ES lag 12 min and climbing.
                            indexing rate 8k/s, cluster yellow."
    10:35  oncall-sre:       "Enabled feature flag search_v2_rollout
                            at 10% canary. Latency worse on canary
                            subset — not better."
    10:41  oncall-platform: "Added Redis rate limit 5k req/s per
                            IP at CDN edge. Support: corporate
                            customers blocked — shared egress IP."
    10:48  oncall-app:      "Product IDs in search results don't
                            match checkout — UUID v7 in search,
                            bigint in orders DB from legacy path."
    10:55  oncall-search:   "Scaled ES data nodes 6→12. Status still
                            yellow — unassigned shards."
    11:02  YOU join bridge.

  THE STAGE:

   TRAFFIC PATH
   ────────────
   CloudFront → ALB (cross-zone ON) → search-api (30 pods, Java)
     → Elasticsearch 8.x (12 data nodes, index products_v2)
   api-gateway → checkout-svc (unchanged, healthy)

   DATA PATH
   ─────────
   PostgreSQL products DB → Debezium → Kafka products.changes
     → ES indexer (16 pods) → products_v2

   RATE LIMITING (deployed 10:41)
   ──────────────────────────────
   CloudFront edge: 5k req/s per client IP (fixed window)
   api-gateway: 10k req/s global Redis counter (1s buckets)
   Per-user tier limits NOT implemented

   FEATURE FLAGS
   ─────────────
   search_v2_rollout: 10% canary (mesh weight)
   search_v2_index: controls which ES index search-api queries
   Both evaluated server-side in search-api (no client cache)

   ID SCHEME (migration in flight)
   ───────────────────────────────
   Legacy orders: bigint serial
   New catalog: UUID v7 in Postgres, indexed as keyword in ES
   Strangler fig Phase 2 — reads split, writes dual

   ES CLUSTER
   ──────────
   products_v2: 24 primary shards, RF=1 (cost save during dev)
   Reindex from products_v1 still running in background
   Hot threads: merge throttling active
```

**Your tasks:**

1. There are at least four independent problems in this incident. List each with layer (CDN, LB, rate limit, search, CDC, flags, IDs) and whether it is root cause, amplifier, or symptom.

2. ES cluster yellow with unassigned shards after scaling 6→12 nodes. What are the top two causes you check first, and what `/_cat/shards` / `/_cluster/allocation/explain` outcomes confirm each?

3. The 10:41 rate-limit change fixed neither search latency nor checkout conversion. Explain why per-IP limiting harmed corporate users and why global 10k/s Redis buckets still allow gateway 429s at steady 10k/s.

4. Debezium lag 12 min but browse (Postgres read path) is fine. User searches new SKU, finds it, add-to-cart fails "product not found." Trace the failure using ID mismatch + strangler fig Phase 2. What is the parity gate that was skipped?

5. Canary at 10% shows worse latency on v2. Name three reasons a canary can perform *worse* than baseline even when code is "better" (index design, shard count, warmup, query routing).

6. Design the rollback sequence at 11:05 with minimal customer impact: order of flag toggles, index routing, rate limit removal, and deploy rollback. Justify sequencing in terms of blast radius.

7. Six post-incident action items with owners: two search/ES, two rate limiting, one ID/migration, one feature-flag/canary process.

---

## Scoring Guide (self-check after module expert analyses)

```text
Part 1 (Q1–Q6):     5/6+  → Weeks 1–6 still solid
Part 2 (Q7–Q20):   10/14+ → Week 7 specialized components retained
Part 3 (scenario):   Principal depth on multi-layer diagnosis

Overall:
  Ready for Week 8  → 85%+ across parts
  Review Week 7     → below 70% on Part 2
  Review Week 6     → below 60% on Q4–Q6 in Part 1
```

---

> **Worked answers:**
> - Week 7 teaching modules are **in progress** — expert analyses will live in `Week-07-Specialized-Components/` when published.
> - Cross-week bridge answers:
>   - [Message Queues and Kafka — Part 12–13](../Week-06-Architecture-Patterns/Message%20Queues%20and%20Kafka.md)
>   - [Outbox Pattern and CDC — SRE Scenario](../Week-06-Architecture-Patterns/Outbox%20Pattern%20and%20CDC.md)
>   - [Database Scaling Patterns Worked Answers](../Week-05-Database-Internals/Database%20Scaling%20Patterns%20Worked%20Answers.md)
>   - [Sharding Worked Answers](../Week-04-Replication-Partitioning-Consensus/Sharding%20Worked%20Answers.md)
