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



---

> **Answer key (do not open until you attempt the Ops Sim / questions):**  
> [`../answers/Retention-Tests/Week-06 Answers.md`](../answers/Retention-Tests/Week-06 Answers.md)



---

## Part X: Spaced Mix Expansion (Week 6)

Answer from memory. 2-4 sentences each unless math is required.

**QX1:** Why outbox+CDC beats dual-write for order→search projection?

**QX2:** Saga compensation vs 2PC: when is compensation unacceptable?

**QX3:** Kafka idempotent producer prevents what, and what does it NOT prevent?

**QX4:** Bulkhead vs circuit breaker: which stops thread-pool exhaustion from a slow dependency?

**QX5:** Event-driven dual publish without outbox: name the inconsistency window.

**QX6:** Backpressure: two concrete signals and one unsafe retry pattern.

**QX7:** Exactly-once end-to-end across DB+Kafka: what must be true?

**QX8:** Poison message handling: park vs drop vs infinite retry — pick with reason.


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

