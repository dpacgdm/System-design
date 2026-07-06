# WEEK 6 RETENTION TEST

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

**Q1 (Kafka):** Topic `orders.events` has 32 partitions. Consumer group `fulfillment-svc` runs 48 pods. Rebalance just finished. How many pods are idle, and why can adding pods not reduce lag further without another change?

**Q2 (Kafka):** Producer uses `acks=all`, `enable.idempotence=true`, `max.in.flight.requests.per.connection=5`. Broker loses a partition leader; ISR shrinks to 1 (min ISR=2). What happens to in-flight produces, and what error class does checkout see?

**Q3 (Kafka):** Consumer processes a batch, crashes after business logic succeeds but *before* offset commit. At-least-once is configured. What guarantees break downstream, and what must the consumer implement?

**Q4 (Kafka):** `click.stream` has 128 partitions, RF=2, min ISR=1, producer `acks=1`. `orders.events` shares the same 12-broker MSK cluster. Explain how a misconfigured high-volume topic can take down checkout despite no shared code path.

**Q5 (EDA):** OrderPlaced event carries full order JSON (47 fields). Three consumers need 4 fields each. Name the anti-pattern, the preferred event shape, and one reason fat events break schema evolution.

**Q6 (EDA):** Choreography vs orchestration for a 6-step checkout flow with mandatory compensation. When do you pick orchestration despite higher operational complexity?

**Q7 (Saga):** Orchestrated saga: ReserveInventory succeeds, ChargePayment succeeds, CreateShipment fails. CompensatePayment runs but Stripe refund API times out. What is the saga state, what is the customer-visible outcome, and what idempotency key must CompensatePayment use?

**Q8 (Saga):** Hotel reservation API times out at 8s; partner creates the hold at 7.9s. Saga marks ReserveHotel failed and runs CompensateFlight. Name this failure class and the reconciliation pattern that prevents stranded holds.

**Q9 (Circuit Breaker):** fraud-svc circuit opens. checkout-svc retries fraud calls 3× with no jitter, bulkhead queue=200. payments-svc has no breaker on its RDS pool. Draw the cascade in three bullets: why payments-db saturates even though fraud is "protected."

**Q10 (Circuit Breaker):** Istio retry: `attempts=3`, `perTryTimeout=2s`, `retryOn: 503`. payments-svc returns 503 at 1.9s under load. POST /charge has no idempotency key. What is the blast radius?

**Q11 (Outbox):** checkout INSERTs into `orders` and `outbox` in one transaction, then Debezium publishes to Kafka. Debezium stalls; outbox rows accumulate. Are orders lost, are events lost, and what Week 5 mechanism threatens the primary?

**Q12 (Microservices):** `promotions-svc` and `checkout-svc` share one RDS Postgres instance. promotions runs `CREATE INDEX CONCURRENTLY` during a flash sale. Which service breaks first and why — cite the anti-pattern name.

**Q13 (Outbox):** Polling publisher vs Debezium CDC for 2k events/sec outbox peak. Name one ops advantage of polling and one durability/latency advantage of CDC.

**Q14 (EDA):** Strangler fig migration: Phase 2 routes *reads* to new service, writes still hit monolith. Product catalog read path migrated; order placement still on monolith. Name one data consistency bug this phase introduces if both paths expose `product_version`.

---

## Part 2: Compound SRE Scenario

This scenario requires knowledge from **Kafka, EDA, Saga, Circuit Breakers, Outbox/CDC, and Microservices** simultaneously. The challenge is not just knowing each pattern but **identifying which pattern each symptom belongs to** and how they cascade.

```
INCIDENT REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Severity: P1
Service: Global e-commerce checkout platform
  (think: Shopify-scale flash sales, Prime Day traffic)

  Users place orders in real-time. Order confirmation
  must arrive within 5 seconds. Fulfillment tracking
  must appear within 2 minutes. Platform handles
  140,000 orders/hour during peak events.

ARCHITECTURE:

  ╔════════════════════════════════════════════════════════════════╗
  ║   CLIENT / EDGE LAYER                                          ║
  ║   Browser/Mobile → CloudFront → ALB                            ║
  ║     → api-gateway (5s deadline, JWT auth)                      ║
  ║                                                                ║
  ║   CHECKOUT MICROSERVICES (EKS, us-east-1)                      ║
  ║   api-gateway → checkout-svc (20 replicas)                     ║
  ║     ├──► fraud-svc (Resilience4j breaker, 3 retries)           ║
  ║     ├──► payments-svc (gRPC, Istio retry 3× on 503)            ║
  ║     └──► inventory-svc (sync HTTP, 2s timeout)                 ║
  ║                                                                ║
  ║   ORDER PERSISTENCE (Transactional Outbox)                     ║
  ║   checkout-svc → RDS PostgreSQL orders DB (primary)            ║
  ║     └── Same txn: INSERT orders + INSERT outbox                ║
  ║                                                                ║
  ║   EVENT PUBLISHING (Dual Path — intentional redundancy)        ║
  ║   Path A: Debezium slot debezium_outbox_orders                 ║
  ║     → MSK topic orders.outbox (32 parts, RF=3, min ISR=2)      ║
  ║   Path B: checkout-svc direct producer                         ║
  ║     → MSK topic orders.events (64 parts, RF=3, min ISR=2)      ║
  ║     (acks=all, enable.idempotence=true)                        ║
  ║                                                                ║
  ║   DOWNSTREAM CONSUMERS                                         ║
  ║   fulfillment-svc (8 pods, consumer group, idempotent)         ║
  ║     ← orders.outbox (Debezium path)                            ║
  ║   analytics-svc (12 pods)                                      ║
  ║     ← orders.events (direct producer path)                     ║
  ║                                                                ║
  ║   KAFKA CLUSTER (MSK, shared)                                  ║
  ║   12 brokers, 3 AZs                                            ║
  ║   click.stream: 128 parts, RF=2, min ISR=1, 140k msg/s         ║
  ║   orders.outbox: 32 parts, RF=3, min ISR=2                     ║
  ║   orders.events: 64 parts, RF=3, min ISR=2                     ║
  ║                                                                ║
  ║   SAGA (Separate product line, same org)                       ║
  ║   travel-booking Step Functions saga                           ║
  ║     shares Stripe API rate limit with payments-svc             ║
  ║     no bulkhead between them                                   ║
  ║                                                                ║
  ║   RESILIENCE CONFIG (as deployed)                              ║
  ║   fraud-svc: breaker OPEN after 50% failures in 10s window     ║
  ║   checkout→payments: gRPC deadline 4s (not propagated)         ║
  ║   payments-svc: no circuit breaker on RDS pool (50 conns/pod)  ║
  ║   Debezium: no alert on slot retained WAL bytes                ║
  ╚════════════════════════════════════════════════════════════════╝

INCIDENT TIMELINE:

  13:40 — Edge team deploys click-stream-ingest v2.3.
          New producer config: acks=1, batch.size=65536,
          linger.ms=100. Traffic: 140,000 msg/s sustained.

  13:45 — CloudWatch alarm: MSK UnderReplicatedPartitions
          spiking on click.stream. oncall-data dismisses
          as "expected during deploy."

  13:52 — checkout 5xx rate climbs to 9%.
          orders.events produce failures: NotEnoughReplicas.
          PagerDuty P1 fires.

  13:57 — Debezium connector orders-outbox-pub flapping.
          confirmed_flush_lsn frozen for 12 minutes.
          pg_wal directory climbing.

  14:02 — orders DB disk usage hits 78%.
          DBA: "replay_lag on replicas is fine (<100ms).
          Why is WAL not being recycled?"

  14:08 — fulfillment consumer lag hits 45,000 messages.
          Customer support: "Order confirmed email received,
          but no tracking number after 30 minutes."

  14:11 — SRE scales fulfillment 8→20 pods.
          Lag INCREASES to 52,000. Rebalance storm visible
          in consumer group metrics.

  14:10 — fraud-svc recovers from earlier blip.
          Circuit breaker transitions to HALF-OPEN.

  14:14 — Step Functions dashboard shows saga_stuck_count=23
          on TripBookingSaga (unrelated product line).
          oncall-app asks: "Ignore?"

  14:15 — YOU join the incident bridge.
          Disk projected full at 15:30 UTC (83% now).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Question 1:** There are SIX distinct problems in this incident (checkout 5xx, missing tracking, Debezium/WAL bloat, fulfillment lag worsening after scale, potential double-charge risk, saga stuck count). For each one:
- Name the problem
- Identify which PATTERN it belongs to (Kafka, Outbox/CDC, Saga, Circuit Breaker, Microservices, EDA)
- State the root cause in one sentence
- Cite the specific monitoring evidence

**Question 2:** These problems are NOT independent. Draw at least THREE causal relationships — which problems make other problems WORSE? Include a cascade diagram showing how click.stream misconfiguration reaches checkout 5xx.

**Question 3:** You are the incident commander at 14:15 UTC. Disk is 83%, projected full at 15:30. Rank your stabilization options and pick ONE path for the first 60 seconds:
- (A) Drop Debezium slot + replay outbox manually
- (B) Throttle click.stream producers
- (C) Extend disk + scale Debezium tasks

Justify trade-offs for order durability, fulfillment catch-up, and blast radius.

**Question 4:** Why did scaling fulfillment 8→20 pods WORSEN lag from 45k to 52k? What single config change fixes consumer throughput without touching checkout code?

**Question 5:** fraud-svc recovered at 14:10 but checkout error rate still 67% at 14:15. Explain using circuit breaker half-open behavior AND payments-db connection pool math. Include the microservices anti-pattern that allowed this.

**Question 6:** The outbox pattern succeeded at one layer and failed at another during this incident. State precisely WHERE — reference Phase 1 (DB transaction) vs Phase 2 (publish to Kafka). What guarantees held and what broke?

**Question 7:** List six post-incident changes with owners: two Kafka, two outbox/CDC, two resilience/microservices. No vague "improve monitoring."

---

# WEEK 6 RETENTION TEST — ANSWERS

---

# Part 1: Rapid-Fire

---

**Q1 (Kafka — Partition Ceiling):**
Only **32 pods can actively consume** — one per partition. The other **16 pods are idle** (48 − 32 = 16). Adding pods cannot reduce lag further because **consumer throughput is bounded by partition count**, not pod count. To increase parallelism you must **increase partition count** (with rebalancing trade-offs) or optimize per-partition processing speed.

---

**Q2 (Kafka — ISR Shrink):**
With `min.insync.replicas=2` and ISR shrunk to 1, the broker **rejects all produces** that require `acks=all` because the minimum in-sync replica requirement is not met. Checkout sees **`NotEnoughReplicasException`** (or `NOT_ENOUGH_REPLICAS` in client metrics). In-flight requests fail — they are **not silently committed**. The idempotent producer may retry, but retries also fail until ISR recovers or min ISR is lowered (dangerous).

---

**Q3 (Kafka — At-Least-Once Duplicate):**
The consumer **processed the message but did not commit the offset**. On restart, Kafka redelivers the same message → **duplicate processing downstream**. The consumer must implement **idempotent handlers** (dedupe by event ID, natural key upsert, or idempotency table). Without this, fulfillment may create duplicate shipments, analytics double-counts revenue, etc.

---

**Q4 (Kafka — Shared Cluster Blast Radius):**
`click.stream` with `acks=1` and `min ISR=1` allows writes when only the leader has the data — **no follower durability guarantee**. At 140k msg/s, broker disk I/O, network, and CPU saturate. This degrades **all topics on the cluster** — including `orders.events` with `acks=all`. Leader election storms, disk pressure, and network contention cause `orders.events` ISR to shrink → checkout produces fail with `NotEnoughReplicas`. **No shared code path required — shared infrastructure is the coupling.**

---

**Q5 (EDA — Fat Events):**
Anti-pattern: **Fat Event / Event Carried State Transfer**. Preferred shape: **thin domain events** carrying only identifiers and changed fields (`orderId`, `status`, `totalCents`). Fat events break schema evolution because **every field change forces all consumers to update** even if they only read 4 fields — and backward compatibility becomes a coordination nightmare across 3+ teams.

---

**Q6 (EDA — Orchestration vs Choreography):**
Pick **orchestration** when you need **centralized visibility into saga state**, mandatory compensation ordering, or complex failure recovery (6 steps with rollback dependencies). Checkout with payment + inventory + shipping fits orchestration because a **Step Functions or saga orchestrator** can track "where am I in the flow" and run compensations in reverse order — choreography scatters state across consumers and makes "stuck at step 4" nearly impossible to debug.

---

**Q7 (Saga — Compensation Timeout):**
Saga state: **COMPENSATING / STUCK** — forward steps partially completed, compensation in progress but not confirmed. Customer-visible outcome: **charged but no shipment** (payment succeeded, shipment failed, refund pending/unknown). CompensatePayment must use **`paymentIntentId` or `chargeId` from the original ChargePayment step** as idempotency key — Stripe dedupes on `Idempotency-Key` header, so retries of the same refund do not double-refund.

---

**Q8 (Saga — Ambiguous Timeout):**
Failure class: **Saga Timeout Ambiguity** — the partner may have succeeded even though the caller timed out. Reconciliation pattern: **Pending Operation Log + Reconciler worker** — record the reservation attempt with a correlation ID, run a background job that queries partner API for hold status, and either confirm or release. Without this, CompensateFlight cancels a flight while a hotel hold remains → **stranded resources and billing disputes**.

---

**Q9 (Circuit Breaker — Cascade Through Bulkhead):**
1. fraud-svc breaker opens → checkout **still retries 3× with no jitter** → 3× traffic hits the (failing) fraud path before fallback, wasting checkout threads.
2. checkout threads blocked on fraud retries **fill the bulkhead queue (200)** → new checkout requests queue or timeout.
3. Requests that bypass fraud (or use cached fraud scores) **still hit payments-svc** → payments-svc has **no pool breaker** → 20 checkout replicas × retries open **50 conns/pod × N pods** to RDS → **payments-db saturates** despite fraud being "protected."

---

**Q10 (Circuit Breaker — Retry Without Idempotency):**
Each POST /charge that gets 503 at 1.9s triggers **3 Istio retries** (attempts=3). Without idempotency key, **each retry is a new charge attempt** → up to **3× charges per checkout**. Blast radius: customers double/triple charged, Stripe dispute volume spikes, manual refund queue. The 503 at 1.9s (under perTryTimeout=2s) means retries **will execute** — not timeout-skipped.

---

**Q11 (Outbox — Phase 1 vs Phase 2):**
**Orders are NOT lost** — they committed in the same transaction as outbox rows (Phase 1 succeeded). **Events are NOT lost** — they sit in the outbox table waiting for publish. What breaks is **timeliness** — fulfillment does not see events until Debezium catches up. Week 5 mechanism threatening primary: **replication slot WAL retention** — Debezium slot with frozen `confirmed_flush_lsn` prevents Postgres from recycling WAL → **pg_wal grows until disk full** → primary may become read-only or crash.

---

**Q12 (Microservices — Shared Database Anti-Pattern):**
**checkout-svc breaks first** — flash sale traffic hammers the shared RDS with checkout writes; `CREATE INDEX CONCURRENTLY` on promotions tables causes **heavy I/O and lock contention** on shared buffer pool and disk. Anti-pattern: **Shared Database** — microservices must not share a Postgres instance; schema/index operations on one service become **noisy neighbor** failures for all co-located services.

---

**Q13 (Outbox — Polling vs CDC):**
**Polling advantage:** Simpler ops — no replication slot, no WAL retention risk, works on any database without logical decoding permissions; easy to pause/resume without slot corruption. **CDC advantage:** Lower end-to-end latency (milliseconds from commit to Kafka vs poll interval seconds) and **exactly-once capture order** tied to transaction log — no missed rows between poll windows if the poller crashes mid-batch.

---

**Q14 (EDA — Strangler Fig Phase 2):**
**Stale `product_version` on order placement:** User reads catalog from new service (version 7), adds to cart, but monolith write path still sees version 5 — order placed against outdated price or discontinued SKU. Optimistic locking fails silently because read and write paths don't share the same version source. Fix: **version parity gate** — monolith write must validate against new catalog service before accepting order.

---

# Part 2: Compound SRE Scenario

---

## Question 1: Six Problems — Pattern, Root Cause, Evidence

### Problem 1: Checkout 5xx (Kafka Layer)

**Root cause:** `click.stream` misconfiguration (`acks=1`, `min ISR=1`) at 140k msg/s saturated MSK broker resources, causing ISR shrink on `orders.events` and produce failures with `NotEnoughReplicas` for checkout's `acks=all` producer.

**Evidence:**
```
→ checkout 5xx ~9% starting 13:52
→ orders.events produce failures: NotEnoughReplicas
→ UnderReplicatedPartitions spiking on click.stream at 13:45
→ Edge deploy at 13:40 changed producer to acks=1
→ click.stream: 140k msg/s on shared 12-broker cluster
→ orders.events requires min ISR=2; cluster-wide pressure 
  prevents maintaining ISR
```

---

### Problem 2: Missing Tracking Numbers (Outbox/CDC + EDA Layer)

**Root cause:** Debezium connector stalled with frozen `confirmed_flush_lsn`, so outbox events were not published to Kafka — fulfillment-svc never received OrderPlaced events despite orders being committed in the database.

**Evidence:**
```
→ Debezium orders-outbox-pub flapping at 13:57
→ confirmed_flush_lsn frozen 12+ minutes
→ fulfillment lag 45,000 messages by 14:08
→ Customer: "order confirmed email received, no tracking"
→ Order confirmation email uses Path B (direct producer) 
  which also failed — but some emails may have been 
  queued before failure; outbox path is fulfillment's source
```

---

### Problem 3: WAL Bloat / Disk Pressure (Outbox/CDC → Week 5 Bridge)

**Root cause:** Debezium replication slot retained WAL because `confirmed_flush_lsn` stopped advancing — Postgres cannot recycle WAL segments, causing `pg_wal` to grow toward disk exhaustion.

**Evidence:**
```
→ orders DB disk 78% at 14:02, projected 83% at 14:15
→ pg_wal climbing
→ confirmed_flush_lsn frozen (same root as Problem 2)
→ replicas show replay_lag < 100ms (streaming replicas are 
  fine — this is SLOT retention, not replica lag)
→ DBA: "Why is WAL not being recycled?"
```

---

### Problem 4: Fulfillment Lag Worsened After Scale (Kafka Consumer Layer)

**Root cause:** Scaling 8→20 pods triggered a **consumer group rebalance storm** — partitions reassigned, in-flight messages reprocessed, processing paused during rebalance — temporarily increasing lag from 45k to 52k.

**Evidence:**
```
→ Scale 8→20 at 14:11
→ Lag increased 45k → 52k (worse, not better)
→ Rebalance storm visible in consumer group metrics
→ Topic has 32 partitions — only 32 consumers can be active
→ 20 pods still < 32 partitions, so idle pods aren't the 
  issue — rebalance overhead is
```

---

### Problem 5: Potential Double-Charge (Circuit Breaker + Microservices Layer)

**Root cause:** Istio retry (`attempts=3`, `retryOn: 503`) on payments-svc POST /charge **without idempotency keys** — under load, 503 responses trigger retries that create duplicate Stripe charges.

**Evidence:**
```
→ payments-svc returns 503 at 1.9s under load
→ Istio retry: attempts=3, perTryTimeout=2s, retryOn: 503
→ POST /charge has no idempotency key (architecture doc)
→ payments-svc shares Stripe rate limit with travel saga
→ checkout 5xx forces user retries → amplifies charge attempts
```

---

### Problem 6: Saga Stuck Count (Saga Layer — Amplifier, Not Root)

**Root cause:** TripBookingSaga compensations timing out because **payments-svc and travel saga share Stripe API rate limit** without bulkhead — checkout load consumes Stripe quota, starving saga compensations.

**Evidence:**
```
→ saga_stuck_count=23 on TripBookingSaga at 14:14
→ Architecture: "shares Stripe API rate limit with payments-svc"
→ "No bulkhead between them"
→ Correlated timing with checkout incident (13:52+)
→ Separate product line but shared external dependency
```

---

## Question 2: Causal Relationships

### Relationship 1: click.stream Saturation → orders.events ISR Shrink → Checkout 5xx

```
click.stream (140k msg/s, acks=1)
        │
        ▼ broker CPU/disk/network saturation
   MSK cluster degraded
        │
        ▼ cannot maintain ISR on orders.events
   NotEnoughReplicas on checkout produce
        │
        ▼
   checkout 5xx (9% → higher under retry storm)
```

### Relationship 2: Broker Saturation → Debezium Lag → WAL Bloat → Disk Full Risk

```
MSK cluster under pressure
        │
        ▼ Debezium connector flaps / cannot commit offsets
   confirmed_flush_lsn frozen
        │
        ▼ Postgres retains WAL for slot
   pg_wal grows (800GB trajectory)
        │
        ▼ disk 78% → 83% → projected FULL 15:30
   Primary at risk of read-only / crash
        │
        ▼ even if checkout recovers, DB may die
```

### Relationship 3: Checkout 5xx + User Retries → payments-svc Load → Stripe Rate Limit → Saga Stuck

```
checkout failures → user F5 retries
        │
        ▼ 3× Istio retries × no idempotency
   payments-svc + Stripe API hammered
        │
        ▼ shared rate limit, no bulkhead
   TripBookingSaga compensations timeout
        │
        ▼
   saga_stuck_count=23
```

### Relationship 4: Debezium Stall → Fulfillment Lag → Support Volume → Perceived "Still Broken"

```
Outbox events not published
        │
        ▼ fulfillment-svc lag 45k+
   No tracking numbers
        │
        ▼ customers call support during checkout outage
   Support tickets amplify perceived severity
        │
        ▼ engineering distracted from root cause (MSK)
```

### Full Cascade Map

```
                    click.stream misconfig
                           │
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
      MSK degraded    Debezium stall   (future: disk full)
           │               │
           ▼               ▼
    checkout 5xx     fulfillment lag
           │               │
           ▼               ▼
    user retries      no tracking
           │
           ▼
    payments-svc 503
           │
     ┌─────┴─────┐
     ▼           ▼
 double-charge  saga stuck
   risk         (Stripe limit)
```

---

## Question 3: Incident Commander — First 60 Seconds at 14:15

**Ranking (immediate impact × reversibility):**

```
╔═══════════════════════════════════════════════════════════════════════╗
║  RANK │ ACTION                    │ WHY                               ║
╠═══════════════════════════════════════════════════════════════════════╣
║   1   │ (B) Throttle click.stream │ Stops the bleeding at source.     ║
║       │ producers                 │ MSK recovers → ISR restores →     ║
║       │                           │ checkout produces succeed.        ║
║       │                           │ Zero data loss. Reversible.       ║
╠═══════════════════════════════════════════════════════════════════════╣
║   2   │ (C) Extend disk + scale   │ Buys time for WAL but does NOT    ║
║       │ Debezium                  │ fix broker saturation. Disk       ║
║       │                           │ extension is necessary but        ║
║       │                           │ insufficient alone.               ║
╠═══════════════════════════════════════════════════════════════════════╣
║   3   │ (A) Drop slot + replay    │ LAST RESORT. Dropping slot        ║
║       │                           │ releases WAL (saves disk) but     ║
║       │                           │ loses CDC position — must         ║
║       │                           │ reconcile outbox manually.        ║
║       │                           │ Risk of missed events.            ║
╚═══════════════════════════════════════════════════════════════════════╝
```

**PICK: (B) Throttle click.stream producers — first 60 seconds:**

```bash
# SECOND 0: Confirm blast radius
aws kafka list-clusters --query 'ClusterInfoList[?ClusterName==`prod-msk`]'
aws cloudwatch get-metric-statistics \
  --namespace AWS/Kafka \
  --metric-name UnderReplicatedPartitions \
  --dimensions Name=Cluster Name,Value=prod-msk \
  --start-time $(date -u -d '30 min ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 60 --statistics Maximum

# SECOND 15: Throttle click-stream-ingest (K8s scale to 0 or 
# ConfigMap rate limit). Fastest lever: scale deployment.
kubectl scale deployment click-stream-ingest --replicas=0

# Alternative if scale-to-zero too aggressive:
kubectl set env deployment/click-stream-ingest \
  KAFKA_PRODUCER_MAX_IN_FLIGHT=1 \
  RATE_LIMIT_MSG_PER_SEC=10000

# SECOND 30: Verify ISR recovery on orders.events
kafka-topics.sh --bootstrap-server $MSK_BROKERS \
  --describe --topic orders.events | grep -v "Leader:.*Isr:.*Isr:"

# Look for: all partitions Isr count = 3 (RF=3)

# SECOND 45: Check checkout produce success rate
aws cloudwatch get-metric-statistics \
  --namespace Checkout/Custom \
  --metric-name KafkaProduceFailures \
  --dimensions Name=Topic,Value=orders.events \
  --start-time $(date -u -d '5 min ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 60 --statistics Sum

# SECOND 60: Parallel — begin disk extension (don't wait)
aws rds modify-db-instance \
  --db-instance-identifier orders-primary \
  --allocated-storage 2000 \
  --apply-immediately
```

**Trade-offs:**
- **(B) Order durability:** Preserved — no slot drop, no manual replay. Checkout `acks=all` resumes once ISR healthy.
- **(B) Fulfillment catch-up:** Debezium can resume once MSK stable; lag drains at partition processing rate. Throttle may add ~5 min to click analytics — acceptable vs P1 checkout.
- **(A) Risk:** Dropping slot loses CDC position; outbox rows must be polled and republished manually — hours of reconciliation, missed-event risk.
- **(C) Alone:** Disk extension takes 5-15 min on RDS; Debezium still flaps if MSK saturated.

---

## Question 4: Why Scaling Worsened Lag + Fix

**Why 8→20 made lag WORSE:**

Consumer group rebalance is a **stop-the-world** event for the group. When pod count changes:
1. Group coordinator triggers rebalance protocol (Eager or Cooperative).
2. **All consumption stops** during partition reassignment.
3. In-flight batches may be reprocessed (at-least-once).
4. 20 pods join fight for 32 partitions — coordinator churn.
5. During rebalance (~30-120s), **zero forward progress** — lag accumulates.
6. After rebalance, 12 pods (32−20=12) are still unused capacity... wait: 20 < 32, so all 20 get partitions. But the **rebalance pause** added ~7k messages (45k→52k) at ~140 msg/s effective drain rate during chaos.

**The deeper issue:** Even without rebalance storm, **32 partitions caps throughput at 32 × (messages/sec per partition)**. Adding pods past 32 never helps.

**Single config change (no checkout code):**

```properties
# fulfillment-svc consumer config
max.poll.records=500          # was 50 — batch more per poll
fetch.min.bytes=1048576       # 1MB — fewer round trips
partition.assignment.strategy=org.apache.kafka.clients.consumer.CooperativeStickyAssignor
# Cooperative rebalance: only moved partitions stop, not all

# OR increase partitions (requires ops change, one-time rebalance):
kafka-topics.sh --bootstrap-server $MSK_BROKERS \
  --alter --topic orders.outbox --partitions 64
```

**Best immediate fix:** `CooperativeStickyAssignor` prevents full-stop rebalance on scale. **Long-term:** increase `orders.outbox` partitions to 64 before next flash sale.

---

## Question 5: fraud Recovered but checkout Still 67% Errors

**Circuit breaker half-open behavior:**

When fraud-svc recovered at 14:10, the breaker entered **HALF-OPEN** — allowing a **trickle of test requests** through to probe recovery. If any probe fails, breaker **reopens immediately**. During half-open:
- Only ~1-3 concurrent requests test fraud (not full traffic).
- But checkout's **3 retries with no jitter** mean each checkout attempt hits fraud up to 3×.
- Half-open probes + retry storm = **breaker oscillates OPEN ↔ HALF-OPEN**, never reaching CLOSED.
- checkout-svc does not fail open to "skip fraud" — it **blocks or errors** waiting for fraud.

**Meanwhile, the REAL bottleneck shifted to payments:**

```
payments-svc RDS pool math:
  20 checkout replicas × 3 Istio retries = 60 concurrent charge attempts
  payments-svc: 15 pods × 50 connections/pod = 750 max RDS connections
  BUT: checkout 5xx → user retries → 3× effective load
  60 × 3 user retries = 180 concurrent
  + connection leaks from timed-out gRPC (4s deadline, child runs 30s)
  = pool exhaustion → 503 → more Istio retries → death spiral

At 14:15: checkout error rate 67% because:
  - fraud breaker still oscillating (symptom, not cause)
  - payments-db pool saturated (actual cause)
  - MSK may still be recovering (orders.events)
```

**Microservices anti-pattern:** **Shared Database** (payments-svc no pool breaker) + **Cascading Retry** (Istio + checkout + no jitter) + **Missing Bulkhead** (Stripe shared with saga). fraud being "protected" by a breaker is irrelevant when **payments has no breaker on its DB pool** and checkout retries amplify load downstream.

---

## Question 6: Outbox — Where It Succeeded and Failed

```
╔════════════════════════════════════════════════════════════════════════╗
║  PHASE │ WHAT HAPPENS              │ THIS INCIDENT                     ║
╠════════════════════════════════════════════════════════════════════════╣
║   1    │ DB transaction:           │ ✓ SUCCEEDED                       ║
║        │ INSERT orders + INSERT      │ Orders committed. Outbox rows   ║
║        │ outbox in same txn          │ written. ACID guarantee held.   ║
╠════════════════════════════════════════════════════════════════════════╣
║   2    │ Publish: Debezium reads     │ ✗ FAILED (timeliness)           ║
║        │ WAL → Kafka                 │ Debezium stalled. Events NOT    ║
║        │                             │ lost — sitting in outbox/WAL.   ║
║        │                             │ Fulfillment never notified.     ║
╠════════════════════════════════════════════════════════════════════════╣
║  2-alt │ Direct producer Path B      │ ✗ FAILED (same root cause)      ║
║        │ checkout → orders.events    │ MSK ISR shrink → produce fail.  ║
╚════════════════════════════════════════════════════════════════════════╝
```

**Guarantees that held:**
- **Atomicity:** Order and outbox row committed together — no order without outbox row.
- **Durability:** Data on disk in Postgres — not lost even if Kafka is down.

**Guarantees that broke:**
- **Eventual delivery timeliness:** Events not reaching Kafka within SLA (2 min tracking).
- **End-to-end exactly-once:** At-least-once on recovery + potential duplicate publishes on Debezium restart.

**Precise statement:** Outbox Phase 1 (transactional write) **worked exactly as designed**. Phase 2 (CDC publish) **failed due to infrastructure coupling** — Debezium depends on healthy MSK AND Postgres WAL recycling, both compromised by click.stream saturation. The outbox pattern **does not protect against shared Kafka cluster failure** — it only eliminates the dual-write problem between DB and message broker.

---

## Question 7: Six Post-Incident Changes (With Owners)

```
╔═══════════════════════════════════════════════════════════════════════╗
║  # │ CHANGE                              │ OWNER         │ CATEGORY   ║
╠═══════════════════════════════════════════════════════════════════════╣
║  1 │ click.stream: enforce acks=all,     │ oncall-data   │ Kafka      ║
║    │ min.insync.replicas=2 in MSK ACL    │               │            ║
║    │ + topic-level config guardrails     │               │            ║
╠═══════════════════════════════════════════════════════════════════════╣
║  2 │ Split MSK: transactional topics     │ platform-team │ Kafka      ║
║    │ (orders.*) on dedicated 6-broker    │               │            ║
║    │ cluster isolated from analytics     │               │            ║
╠═══════════════════════════════════════════════════════════════════════╣
║  3 │ CloudWatch alarm:                   │ oncall-dba    │ Outbox/CDC ║
║    │ pg_replication_slots.retained_bytes │               │            ║
║    │ > 50GB on orders-primary → page     │               │            ║
╠═══════════════════════════════════════════════════════════════════════╣
║  4 │ Outbox polling fallback worker:     │ oncall-app    │ Outbox/CDC ║
║    │ if Debezium lag > 300s, activate    │               │            ║
║    │ poller publishing from outbox table │               │            ║
╠═══════════════════════════════════════════════════════════════════════╣
║  5 │ Mandatory Stripe Idempotency-Key    │ oncall-app    │ Resilience ║
║    │ on POST /charge; disable Istio      │               │            ║
║    │ retry for non-idempotent endpoints  │               │            ║
╠═══════════════════════════════════════════════════════════════════════╣
║  6 │ Split promotions-svc to dedicated   │ platform-team │ Microsvc   ║
║    │ RDS instance; remove shared DB      │               │            ║
╚═══════════════════════════════════════════════════════════════════════╝
```

Acceptance criteria for #4: fallback poller publishes events within 60s of Debezium stall detection; zero duplicate publishes to fulfillment (dedupe by outbox `event_id`).

---

```
╔══════════════════════════════════════════════════════════════════════╗
║  # │ CHANGE                              │ OWNER        │ TYPE       ║
╠══════════════════════════════════════════════════════════════════════╣
║  1 │ click.stream: acks=all, min ISR=2   │ oncall-data  │ Kafka      ║
║  2 │ MSK cluster isolation: analytics    │ platform     │ Kafka      ║
║    │ vs transactional topics on separate │              │            ║
║    │ clusters or dedicated brokers       │              │            ║
╠══════════════════════════════════════════════════════════════════════╣
║  3 │ Alert: pg_replication_slots         │ oncall-dba   │ Outbox/CDC ║
║    │ retained_bytes > 50GB               │              │            ║
║  4 │ Outbox polling fallback when        │ oncall-app   │ Outbox/CDC ║
║    │ Debezium lag > 5 min                │              │            ║
╠══════════════════════════════════════════════════════════════════════╣
║  5 │ payments POST /charge: Stripe       │ oncall-app   │ Resilience ║
║    │ Idempotency-Key mandatory           │              │            ║
║  6 │ Split promotions DB from checkout   │ platform     │ Microsvc   ║
║    │ RDS — eliminate shared database     │              │            ║
╚══════════════════════════════════════════════════════════════════════╝
```

---

## Mitigation Timeline (Full Incident)

```
╔══════════════════════════════════════════════════════════════╗
║  T+0 (14:15)  │ Join bridge. Confirm MSK + disk trajectory   ║
║  T+15         │ Throttle click.stream producers (scale 0)    ║
║  T+30         │ Verify orders.events ISR recovering          ║
║  T+45         │ checkout 5xx dropping below 2%               ║
║  T+60         │ RDS storage extension initiated              ║
║  T+90         │ Debezium confirmed_flush_lsn advancing       ║
║  T+120        │ fulfillment lag draining (no more scale)     ║
║  T+180        │ Disable Istio retry on POST /charge (hotfix) ║
║  T+240        │ pg_wal stable, disk below 75%                ║
║  T+300        │ All checkout p99 < 500ms SLA                 ║
║               │                                              ║
║  POST-INCIDENT│ Migrate click.stream to dedicated MSK cluster║
║               │ Add Stripe bulkhead between travel + checkout║
║               │ CooperativeStickyAssignor on fulfillment     ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Scoring Guide (Self-Check)

```text
Part 1 (Q1–Q14):   11/14+ → Week 6 architecture patterns retained
Part 2 (scenario):  Principal depth on cascade diagnosis + sequencing

Overall:
  Ready for Week 7  → 85%+ across parts
  Review Week 6     → below 70% on Part 1
  Review Weeks 4–5  → struggle on Q11 (WAL/slot bridge)
```
