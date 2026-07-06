# WEEK 8 RETENTION TEST

Covers **Weeks 1–8** (transport through advanced distributed patterns and observability). Answer from memory before opening worked-answer files or teaching modules.

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

## Part 1: Cross-Week Rapid-Fire (Weeks 1–7 recall)

**Q1 (Week 2 — SQL):** Serializable isolation on `UPDATE accounts SET balance = balance - 100 WHERE id = 1`. Two concurrent transfers from the same account both read balance=500, both succeed, balance=-100. Which anomaly is this, and what is one Postgres-specific mitigation besides Serializable?

**Q2 (Week 3 — CAP):** Network partition splits Redis primary from 2 of 3 replicas. Primary accepts writes; minority side elects new primary. Two clients write same key. Classify the CAP choice during partition and name the consistency repair tool.

**Q3 (Week 6 — Circuit Breaker):** Parent gRPC call sets 3s deadline. Child service ignores context; runs 30s. Trace shows parent cancelled at 3s, child completes at 30s and writes to DB. What pattern failed, and what is the orphan work risk?

**Q4 (Week 7 — Search):** ES query uses `function_score` on geo distance. Index has 80M docs; filter on `category` is selective (0.1%). Planner still scans all geo postings. What index/query shape fix reduces work?

**Q5 (Week 7 — Rate Limiting):** API key limit 100 req/s via GCRA (generic cell rate algorithm) at edge. Burst of 150 req in 200ms, then idle 5s. How many succeed on first burst, and why is GCRA preferred over strict leaky bucket for this SLA?

**Q6 (Week 7 — Load Balancing):** Pod readiness passes but fails liveness after receiving traffic (OOM during spike). Kubernetes keeps routing until liveness kills pod. What probe change and what LB setting reduce user-visible errors?

---

## Part 2: Week 8 Rapid-Fire (Clocks / Causality / CRDTs / Geo / Observability / SLOs)

Answer all 12. Keep each answer concise.

**Q7 (Clocks):** Two servers: Server A `T=100`, Server B `T=105` (NTP). Event e1 on A at local 100; e2 on B at local 104. Can e2 causally precede e1? What does Lamport clock assignment guarantee vs what it does *not*?

**Q8 (Clocks):** Spanner TrueTime: commit wait + uncertainty interval. Why does adding 8ms to every transaction buy external consistency, and what happens to write latency if clock uncertainty spikes 10×?

**Q9 (Vector Clocks):** Vector clock at replica: `{A:3, B:2}`. Incoming event `{A:2, B:4}`. Is it concurrent, causally before, or after? What merge rule applies for a CRDT grow-only set?

**Q10 (CRDTs):** Two offline editors merge LWW-Register on `title` with timestamps from unsynced laptop clocks. User A sets "Draft" at local T=1000; User B sets "Final" at local T=999. Winner? Why is LWW-register dangerous without logical clocks?

**Q11 (CRDTs):** OR-Set: add "alice", remove "alice", add "alice" on two replicas without sync. What is the state after merge, and why does OR-Set beat plain Set with tombstones?

**Q12 (Geospatial):** Uber driver matching: 50k drivers online, query 3km radius around rider. Geohash prefix 6 chars ≈ 1.2km. Why is naive "query one geohash cell" wrong at cell boundaries, and what is the standard fix?

**Q13 (Geospatial):** PostGIS `ST_DWithin` on unindexed geometry column. p99 4s at 200 QPS. `CREATE INDEX` on geography using GIST. What does the index prune, and why does SRID 4326 vs 3857 matter for distance accuracy?

**Q14 (Observability):** Metric `http_request_duration_seconds{user_id="..."}` with 2M active users. Prometheus cardinality explosion. Rewrite as two metrics that answer p99 latency *and* debug single-user slowness without high-cardinality series.

**Q15 (Observability):** RED vs USE: classify `container_cpu_cfs_throttled_seconds_total`, `grpc_server_handled_total{code}`, `node_disk_io_time_seconds_total` — which method, and what action each implies.

**Q16 (Observability):** Trace sampling: head-based 1% vs tail-based "keep errors and >2s." Checkout failure rate 0.2%; p99 regression only on Android clients. Which sampling finds the regression faster and why?

**Q17 (SLOs):** SLI: "successful checkout completions / checkout attempts." 30-day SLO 99.9%. Error budget in minutes of downtime equivalent. Burn rate 14.4× for 5 minutes — page or ticket? Name the alert tier.

**Q18 (SLOs):** Multi-window burn alert: 1h window at 14.4× AND 6h window at 6×. Why require both instead of either alone?

**Q19 (Observability):** Logs show 0 errors; metrics show 0% 5xx; users report broken checkout. GraphQL partial failures return HTTP 200 with `{ errors: [...] }`. What signal class catches this, and what field do you alert on?

**Q20 (Observability):** Leading vs lagging: `kafka.server.UnderReplicatedPartitions` vs `checkout_success_rate`. How many minutes of lead time is typical if only lagging alert exists, and name one leading indicator for Postgres replication slot bloat.

---

## Part 3: Compound SRE Scenario — "The Slow-Burn Latency Mystery"

```text
THE PAGE (16:40 UTC, Tuesday — no deploy today):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  PagerDuty: [P2] checkout p99 > 800ms (SLO 250ms) — Slack only
             [NOT PAGED] error rate 0.08% (within budget)

  Slack #incidents (last 4 hours):

    12:55  oncall-app:     "Android checkout p99 creeping up.
                            iOS flat. No deploy since Friday."
    13:40  oncall-sre:     "Traces sampled 1% head-based — nothing
                            obvious. CPU/memory normal all services."
    14:20  oncall-data:    "Spanner transaction p99 +6ms cluster-wide.
                            Clock uncertainty metric elevated us-central1."
    15:05  oncall-mobile:  "Android 14 only? Maybe TLS stack —
                            unconfirmed."
    15:50  oncall-sre:     "Enabled tail sampling for errors + slow
                            traces. Found checkout spans waiting on
                            inventory-svc 620ms — but inventory p99
                            metric says 45ms."
    16:10  oncall-sre:     "inventory-svc: 8 of 40 pods on c5a.xlarge
                            in us-east-1c; rest c5.4xlarge. 1c had
                            AZ network event 12:30–13:15 per AWS status."
    16:25  oncall-platform: "ALB least-outstanding-requests enabled
                            last month. Target skew: 1c pods 3× traffic."
    16:35  oncall-product:  "Feature flag checkout_express_path enabled
                            for 25% users Monday — skips tax svc. Android
                            cohort over-represented in flag."
    16:40  CFO Slack thread: "Conversion down 3% since noon — not
                            waiting for SLO burn. What's going on?"

  THE STAGE:

   ARCHITECTURE
   ────────────
   mobile → CloudFront → ALB (LOR algorithm) → checkout-svc
     ├──► inventory-svc (40 pods, multi-AZ, gRPC)
     ├──► tax-svc (skipped for express path)
     └──► payments-svc

   CRDT / COLLAB CART (edge case in scope)
   ───────────────────────────────────────
   Shared family cart uses OR-Set CRDT synced via WebSocket.
   Android clients batch sync every 30s; iOS realtime.
   Cart service embeds vector clock in merge API.

   OBSERVABILITY STACK
   ───────────────────
   Prometheus + Grafana (RED on all services)
   Tempo traces: head 1% until 15:50, then tail sampling
   Loki logs: JSON structured, info level default
   SLO: checkout p99 < 250ms, 99.9% monthly availability
   Alerts: 5xx burn-rate (multi-window), p99 ticket at 800ms

   TIME / INFRA
   ────────────
   inventory-svc in 1c: c5a.xlarge (smaller instances, same pod count)
   Spanner adjacency: fraud-svc reads external score (not on critical path)
   NTP drift alert fired 14:18 on 3 hosts in 1c (auto-remediated)

   FEATURE FLAGS
   ─────────────
   checkout_express_path: 25% Android-heavy cohort
   cart_crdt_batch_sync: 100% Android, 0% iOS
```

**Your tasks:**

1. List at least five contributing factors ranked by customer impact. Tag each: observability gap, clock/time, CRDT/sync, load balancing, feature flag, or AZ impairment.

2. Explain the inventory paradox: distributed trace shows 620ms wait on inventory-svc; service-level p99 metric reports 45ms. How can both be true? Name two metric or aggregation bugs that cause this.

3. The p99 alert fired as P2 Slack, not page. Error budget burn is low. Make the case for paging anyway — or against — using multi-window burn, symptom vs cause, and CFO conversion signal.

4. Spanner uncertainty elevated 14:18–14:45. checkout-svc does not use Spanner. Is Spanner a red herring? If yes, what correlated infrastructure event explains the timing coincidence?

5. OR-Set cart: Android batch sync + express path skips tax. User sees wrong cart total at payment. Trace causality without reading code — what ordering guarantees failed?

6. Design the observability fix package: three alerts (leading), two dashboard panels, one sampling policy change. Include specific metric/trace names and thresholds that would have shortened MTTR from 4h to <30min.

7. Post-incident: four changes (one LB/pod sizing, one flag/canary, one observability, one CRDT client sync) with owners and acceptance criteria.

---

## Scoring Guide (self-check after module expert analyses)

```text
Part 1 (Q1–Q6):     5/6+  → Weeks 1–7 still solid
Part 2 (Q7–Q20):   10/14+ → Week 8 advanced patterns retained
Part 3 (scenario):   Principal depth on slow-burn / multi-signal diagnosis

Overall:
  Ready for Week 9  → 85%+ across parts
  Review Week 8     → below 70% on Part 2
  Review Observability → below 60% on Q14–Q20
```

---

> **Worked answers:**
> - [Observability — Production Scenario & SLO sections](../Week-08-Advanced-Patterns/Observability.md) (*The Slow-Burn Latency Mystery* and burn-rate alerting)
> - Week 8 modules for Clocks, CRDTs, and Geospatial are **in progress** — analyses will live in `Week-08-Advanced-Patterns/` when published.
> - Cross-week bridge:
>   - [Circuit Breakers — Incident Scenario](../Week-06-Architecture-Patterns/Circuit%20Breakers%20Bulkheads%20Timeouts%20Retries%20and%20Backpressure.md)
>   - [Retention Test Week 7](./Week-07.md) (search, rate limit, LB recall)
