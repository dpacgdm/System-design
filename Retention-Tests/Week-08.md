# WEEK 8 RETENTION TEST

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

**Q1 (Clocks):** Two servers: Server A local time T=100, Server B local time T=105 (NTP-synced). Event e1 on A at local 100; event e2 on B at local 104. Can e2 causally precede e1? What does Lamport clock assignment guarantee vs what it does *not*?

**Q2 (Clocks):** Spanner TrueTime: commit wait adds ~8ms to every transaction. Why does this buy external consistency, and what happens to write latency if clock uncertainty spikes 10×?

**Q3 (Vector Clocks):** Vector clock at replica: `{A:3, B:2}`. Incoming event `{A:2, B:4}`. Is it concurrent, causally before, or after? What merge rule applies for a CRDT grow-only set?

**Q4 (CRDTs):** Two offline editors merge LWW-Register on `title` with timestamps from unsynced laptop clocks. User A sets "Draft" at local T=1000; User B sets "Final" at local T=999. Winner? Why is LWW-register dangerous without logical clocks?

**Q5 (CRDTs):** OR-Set: add "alice", remove "alice", add "alice" on two replicas without sync. What is the state after merge, and why does OR-Set beat plain Set with tombstones?

**Q6 (Geospatial):** Uber driver matching: 50k drivers online, query 3km radius around rider. Geohash prefix 6 chars ≈ 1.2km. Why is naive "query one geohash cell" wrong at cell boundaries, and what is the standard fix?

**Q7 (Geospatial):** PostGIS `ST_DWithin` on unindexed geometry column. p99 4s at 200 QPS. After `CREATE INDEX ON geography USING GIST`. What does the index prune, and why does SRID 4326 vs 3857 matter for distance accuracy?

**Q8 (Observability):** Metric `http_request_duration_seconds{user_id="..."}` with 2M active users. Prometheus cardinality explosion. Rewrite as two metrics that answer p99 latency *and* debug single-user slowness without high-cardinality series.

**Q9 (Observability):** RED vs USE: classify `container_cpu_cfs_throttled_seconds_total`, `grpc_server_handled_total{code}`, `node_disk_io_time_seconds_total` — which method, and what action each implies.

**Q10 (Observability):** Trace sampling: head-based 1% vs tail-based "keep errors and >2s." Checkout failure rate 0.2%; p99 regression only on Android clients. Which sampling finds the regression faster and why?

**Q11 (SLOs):** SLI: successful checkout completions / checkout attempts. 30-day SLO 99.9%. Error budget in minutes of downtime equivalent. Burn rate 14.4× for 5 minutes — page or ticket? Name the alert tier.

**Q12 (SLOs):** Multi-window burn alert: 1h window at 14.4× AND 6h window at 6×. Why require both instead of either alone?

**Q13 (Observability):** Logs show 0 errors; metrics show 0% 5xx; users report broken checkout. GraphQL partial failures return HTTP 200 with `{ errors: [...] }`. What signal class catches this, and what field do you alert on?

**Q14 (Observability):** Leading vs lagging: `kafka.server.UnderReplicatedPartitions` vs `checkout_success_rate`. How many minutes of lead time is typical if only lagging alert exists, and name one leading indicator for Postgres replication slot bloat?

---

## Part 2: Compound SRE Scenario

This scenario requires knowledge from **Observability, Clocks/Ordering, Lamport/Vector Clocks, CRDTs, Geospatial, and SLOs** simultaneously. The challenge is diagnosing a slow-burn latency regression where every individual metric looks healthy until you cross-reference signals.

```
INCIDENT REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Severity: P2 (Slack) — escalated by CFO at 16:40
Service: Mobile checkout platform
  (think: Target/Walmart app, family shared cart)

  No deploy since Friday. Checkout p99 SLO: 250ms.
  Monthly availability SLO: 99.9%.
  Conversion dropped 3% since noon — no error spike.

ARCHITECTURE:

  ╔════════════════════════════════════════════════════════════════╗
  ║   CLIENT / EDGE LAYER                                          ║
  ║   Android/iOS mobile apps → CloudFront → ALB                   ║
  ║     ALB algorithm: least-outstanding-requests (LOR)            ║
  ║     (enabled last month)                                       ║
  ║                                                                ║
  ║   CHECKOUT PATH                                                ║
  ║   ALB → checkout-svc (30 replicas, multi-AZ)                   ║
  ║     ├──► inventory-svc (40 pods, gRPC, multi-AZ)               ║
  ║     ├──► tax-svc (skipped for express path flag)               ║
  ║     └──► payments-svc (gRPC)                                   ║
  ║                                                                ║
  ║   SHARED FAMILY CART (CRDT)                                    ║
  ║   cart-svc: OR-Set CRDT for line items                         ║
  ║     sync via WebSocket (iOS: realtime)                         ║
  ║     Android: batch sync every 30s (feature flag)               ║
  ║   Merge API embeds vector clock per cart                       ║
  ║                                                                ║
  ║   OBSERVABILITY STACK                                          ║
  ║   Prometheus + Grafana: RED metrics all services               ║
  ║   Tempo traces: head-based 1% until 15:50                      ║
  ║     then tail sampling (errors + >2s spans)                    ║
  ║   Loki: JSON structured logs, info level default               ║
  ║   Alerts: 5xx multi-window burn-rate (page)                    ║
  ║           p99 > 800ms (P2 Slack ticket only)                   ║
  ║                                                                ║
  ║   FEATURE FLAGS                                                ║
  ║   checkout_express_path: 25% users (Android-heavy)             ║
  ║     skips tax-svc call                                         ║
  ║   cart_crdt_batch_sync: 100% Android, 0% iOS                   ║
  ║                                                                ║
  ║   INFRASTRUCTURE DETAILS                                       ║
  ║   inventory-svc in us-east-1c: 8 of 40 pods on c5a.xlarge      ║
  ║     (smaller instances); rest c5.4xlarge                       ║
  ║   AWS status: AZ network event us-east-1c 12:30–13:15          ║
  ║   Spanner (fraud-svc only): uncertainty elevated 14:18–14:45   ║
  ║   NTP drift alert: 3 hosts in 1c at 14:18 (auto-remediated)    ║
  ╚════════════════════════════════════════════════════════════════╝

INCIDENT TIMELINE:

  12:30 — AWS us-east-1c network impairment begins.
          Resolves 13:15. No deploy triggered.

  12:55 — oncall-app: "Android checkout p99 creeping up.
          iOS flat. No deploy since Friday."

  13:40 — oncall-sre: "Traces sampled 1% head-based —
          nothing obvious. CPU/memory normal all services."

  14:18 — NTP drift alert on 3 inventory-svc hosts in 1c.
          Auto-remediation runs. Spanner clock uncertainty
          metric elevated us-central1 (fraud-svc only).

  14:20 — oncall-data: "Spanner transaction p99 +6ms
          cluster-wide." checkout-svc does NOT use Spanner.

  15:05 — oncall-mobile: "Android 14 only? TLS stack —
          unconfirmed hypothesis."

  15:50 — oncall-sre enables tail sampling for errors + slow
          traces. Finds checkout spans waiting on inventory-svc
          620ms — but inventory-svc p99 metric says 45ms.

  16:10 — oncall-sre: "8 of 40 inventory pods on c5a.xlarge
          in us-east-1c. LOR sends 3× traffic to 1c pods
          after AZ event left them degraded."

  16:25 — oncall-platform: "ALB LOR enabled last month.
          Target skew: 1c pods receiving 3× traffic."

  16:35 — oncall-product: "checkout_express_path enabled
          Monday for 25% — Android cohort over-represented.
          cart_crdt_batch_sync: 100% Android."

  16:35 — User report: family shared cart shows wrong total
          at payment — items added on spouse's phone missing.

  16:40 — CFO Slack: "Conversion down 3% since noon —
          not waiting for SLO burn. What's going on?"
          PagerDuty still P2 Slack only.
          YOU join bridge.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Question 1:** List at least SIX contributing factors ranked by customer impact. Tag each: observability gap, clock/time, CRDT/sync, load balancing, feature flag, or AZ impairment.

**Question 2:** Explain the inventory paradox: distributed trace shows 620ms wait on inventory-svc; service-level p99 metric reports 45ms. How can both be true? Name TWO metric or aggregation bugs that cause this.

**Question 3:** The p99 alert fired as P2 Slack, not page. Error budget burn is low. Make the case for paging anyway — or against — using multi-window burn, symptom vs cause, and the CFO conversion signal.

**Question 4:** Spanner uncertainty elevated 14:18–14:45. checkout-svc does not use Spanner. Is Spanner a red herring? If yes, what correlated infrastructure event explains the timing coincidence?

**Question 5:** OR-Set cart with Android batch sync + express path skips tax. User sees wrong cart total at payment. Trace causality without reading code — what ordering guarantees failed?

**Question 6:** Design the observability fix package: three leading alerts, two dashboard panels, one sampling policy change. Include specific metric/trace names and thresholds that would have shortened MTTR from 4h to <30min.

**Question 7:** Post-incident: four changes (one LB/pod sizing, one flag/canary, one observability, one CRDT client sync) with owners and acceptance criteria.

---



---

> **Answer key (do not open until you attempt the Ops Sim / questions):**  
> [`../answers/Retention-Tests/Week-08 Answers.md`](../answers/Retention-Tests/Week-08 Answers.md)



---

## Part X: Spaced Mix Expansion (Week 8)

Answer from memory. 2-4 sentences each unless math is required.

**QX1:** Lamport vs vector clocks: when does Lamport lie about concurrency?

**QX2:** CRDT LWW vs OR-set for shopping cart: failure mode of each.

**QX3:** SLO vs SLA vs SLI: write one correct sentence each.

**QX4:** Error budget burn alerts: why multi-window burn rates beat single threshold?

**QX5:** Observability: three signals that diagnose tail latency better than avg CPU.

**QX6:** Geo hash precision vs false positive radius: pick for courier ETA.

**QX7:** Wall clock dependency in coupon expiry across regions: what breaks?

**QX8:** Cardinality explosion in metrics: one cause and one containment.


## Part Y: Transfer Mini-Scenario (novel recombination)

```text
NORTHSTAR CHECKOUT CELL — PARTIAL BROWN OUT
  Telemetry:
    checkout p99: 80ms -> 1.8s (one AZ only)
    dependency error budget burn: 14x normal
    retry rate: 3% -> 41% on payment-authorize
    cache hit ratio: stable
    Kafka consumer lag: flat
  Wrong config candidate found in git:
    payment-authorize.timeout_ms = 50
    payment-authorize.retries = 12
    circuit_breaker.enabled = false
```

**Y1:** Which layer owns the primary symptom? What is the amplifier?
**Y2:** Why is raising timeout alone a bad first move?
**Y3:** Ordered mitigation T+0 to T+15 with a capacity check.
**Y4:** What durable fix + acceptance criteria?

> Answer key: see matching file under `answers/Retention-Tests/`.


---

## Part Z: Cross-Week Rapid Fire (forced recall)

**Z1:** TCP TIME_WAIT purpose and the SRE failure it causes at scale.
**Z2:** HTTP/2 vs HTTP/3 HOL blocking — one sentence each.
**Z3:** PACELC for Cassandra CL=ONE vs Postgres sync replica.
**Z4:** Quorum math RF=3 W=QUORUM R=ONE — strong consistency?
**Z5:** Hot key vs hot partition — detection signal for each.
**Z6:** Raft committed vs uncommitted — what can be lost?
**Z7:** Cache stampede — name two defenses and when each wins.
**Z8:** gRPC on L4 LB — black-hole mechanism.
**Z9:** CDN `Vary: Cookie` — why hit ratio collapses.
**Z10:** Outbox pattern — which dual-write failure it eliminates.


### Additional evidence pack (use in Part Y/Z reasoning)

```text
METRICS SNAPSHOT
  dependency_p99_ms{service="payment-authorize"}: 920
  client_inflight{service="checkout-api"}: 4,800 (limit 5,000)
  threadpool_rejected: 220/min
  az_imbalance_ratio: 2.7x
CONFIG DIFF (last 40m)
  - retries: 3
  + retries: 12
  - breaker.maxFailures: 20
  + breaker.maxFailures: 200000
```
Interpret before answering Y/Z items. Do not open answers yet.



## Evidence Interpretation Drill

Using only the metrics/config packs in this file:
1. Name the primary amplifier (not the first alert).
2. Name one red herring metric and why it misleads.
3. Give the first command/config change you would make and what you must verify before shifting traffic.
4. Write acceptance criteria for declaring the incident mitigated.

Repeat for a second pass assuming the failure is cross-AZ capacity, not the original dependency.



## Evidence Interpretation Drill

Using only the metrics/config packs in this file:
1. Name the primary amplifier (not the first alert).
2. Name one red herring metric and why it misleads.
3. Give the first command/config change you would make and what you must verify before shifting traffic.
4. Write acceptance criteria for declaring the incident mitigated.

Repeat for a second pass assuming the failure is cross-AZ capacity, not the original dependency.



## Evidence Interpretation Drill

Using only the metrics/config packs in this file:
1. Name the primary amplifier (not the first alert).
2. Name one red herring metric and why it misleads.
3. Give the first command/config change you would make and what you must verify before shifting traffic.
4. Write acceptance criteria for declaring the incident mitigated.

Repeat for a second pass assuming the failure is cross-AZ capacity, not the original dependency.



## Evidence Interpretation Drill

Using only the metrics/config packs in this file:
1. Name the primary amplifier (not the first alert).
2. Name one red herring metric and why it misleads.
3. Give the first command/config change you would make and what you must verify before shifting traffic.
4. Write acceptance criteria for declaring the incident mitigated.

Repeat for a second pass assuming the failure is cross-AZ capacity, not the original dependency.

