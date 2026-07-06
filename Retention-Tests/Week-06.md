# WEEK 6 RETENTION TEST

Covers **Weeks 1–6** (transport through architecture patterns). Answer from memory before opening module expert analyses or worked-answer files.

---

## Rules

```
╔════════════════════════════════════════════════════════════════╗
║   RULES OF ENGAGEMENT                                          ║
╟────────────────────────────────────────────────────────────────╢
║                                                                ║
║   1. Answer from MEMORY. Do not re-read the teaching modules.  ║
║                                                                ║
║   2. Rapid-fire: 2–4 sentences per question.                   ║
║                                                                ║
║   3. Compound scenario: full depth expected.                   ║
║      This is the real test — identify which pattern each       ║
║      symptom belongs to and how they cascade.                  ║
║                                                                ║
║   4. "I don't remember" is valid — it tells us what to         ║
║      review.                                                   ║
╚════════════════════════════════════════════════════════════════╝
```

---

## Part 1: Cross-Week Rapid-Fire (Weeks 1–5 recall)

**Q1 (Week 1 — gRPC):** Checkout API uses gRPC behind an internal NLB. Six replicas show CPU 8%, 7%, 9%, 91%, 88%, 7%. No client-side routing config. One sentence: cause and fix.

**Q2 (Week 2 — Caching):** Flash sale starts. Redis cache for product price TTL=60s. Origin DB CPU hits 100% in 8 seconds despite cache. 50,000 concurrent users hit the same SKU. Name the failure mode and one infrastructure-level fix that does not require app code changes.

**Q3 (Week 3 — Consistency):** User posts a review, immediately navigates to their profile — old review count. Refreshes 30 seconds later — correct count. Replication lag is 400ms. Which consistency model failed, and what is the simplest fix that does not require synchronous replication?

**Q4 (Week 5 — Scaling):** Debezium slot `analytics_etl` shows `confirmed_flush_lsn` frozen for 45 minutes. Streaming replicas report `replay_lag < 100ms`. Primary `pg_wal` grew 800 GB. Why are replicas "healthy" while disk is dying?

**Q5 (Week 5 — Cassandra):** `CL=QUORUM` writes, `CL=ONE` reads, RF=3. A read immediately after write returns stale data 33% of the time. State the R+W>N rule and the read CL fix in one line each.

---

## Part 2: Week 6 Rapid-Fire (Kafka / EDA / Saga / Resilience / Outbox / Microservices)

Answer all 14. Keep each answer concise.

**Q6 (Kafka):** Topic `orders.events` has 32 partitions. Consumer group `fulfillment-svc` runs 48 pods. Rebalance just finished. How many pods are idle, and why can adding pods not reduce lag further without another change?

**Q7 (Kafka):** Producer uses `acks=all`, `enable.idempotence=true`, `max.in.flight.requests.per.connection=5`. Broker loses a partition leader; ISR shrinks to 1 (min ISR=2). What happens to in-flight produces, and what error class does checkout see?

**Q8 (Kafka):** Consumer processes a batch, crashes after business logic succeeds but *before* offset commit. At-least-once is configured. What guarantees break downstream, and what must the consumer implement?

**Q9 (Kafka):** `click.stream` has 128 partitions, RF=2, min ISR=1, producer `acks=1`. `orders.events` shares the same 12-broker cluster. Explain how a misconfigured high-volume topic can take down checkout despite no shared code path.

**Q10 (EDA):** OrderPlaced event carries full order JSON (47 fields). Three consumers need 4 fields each. Name the anti-pattern, the preferred event shape, and one reason fat events break schema evolution.

**Q11 (EDA):** Choreography vs orchestration for a 6-step checkout flow with mandatory compensation. When do you pick orchestration despite higher operational complexity?

**Q12 (Saga):** Orchestrated saga: ReserveInventory succeeds, ChargePayment succeeds, CreateShipment fails. CompensatePayment runs but Stripe refund API times out. What is the saga state, what is the customer-visible outcome, and what idempotency key must CompensatePayment use?

**Q13 (Saga):** Hotel reservation API times out at 8s; partner creates the hold at 7.9s. Saga marks ReserveHotel failed and runs CompensateFlight. Name this failure class and the reconciliation pattern that prevents stranded holds.

**Q14 (Circuit Breaker):** fraud-svc circuit opens. checkout-svc retries fraud calls 3× with no jitter, bulkhead queue=200. payments-svc has no breaker on its DB pool. Draw the cascade in three bullets: why payments-db saturates even though fraud is "protected."

**Q15 (Circuit Breaker):** Istio retry: `attempts=3`, `perTryTimeout=2s`, `retryOn: 503`. payments-svc returns 503 at 1.9s under load. POST /charge has no idempotency key. What is the blast radius?

**Q16 (Outbox):** checkout INSERTs into `orders` and `outbox` in one transaction, then Debezium publishes to Kafka. Debezium stalls; outbox rows accumulate. Are orders lost, are events lost, and what Week 5 mechanism threatens the primary?

**Q17 (Outbox):** Polling publisher vs Debezium CDC for 2k events/sec outbox peak. Name one ops advantage of polling and one durability/latency advantage of CDC.

**Q18 (Microservices):** `promotions-svc` and `checkout-svc` share one Postgres instance. promotions runs `CREATE INDEX CONCURRENTLY` during a flash sale. Which service breaks first and why — cite the anti-pattern name.

**Q19 (Microservices):** Strangler fig migration: Phase 2 routes *reads* to new service, writes still hit monolith. Product catalog read path is migrated. Order placement still on monolith. Name one data consistency bug this phase introduces if both paths expose `product_version`.

---

## Part 3: Compound SRE Scenario — "The Tuesday Checkout Cascade"

```text
THE PAGE (14:15 UTC, peak US shopping):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  PagerDuty: [P1] checkout success rate < 90%
             [P1] orders-primary: disk_used > 83%
             [P2] fulfillment consumer lag > 40k

  Slack #incidents (last 35 minutes, paraphrased):

    13:45  oncall-data:   "MSK UnderReplicatedPartitions spiking
                           on click.stream — probably the edge
                           deploy, acks=1 on 140k msg/s."
    13:52  oncall-sre:    "checkout 5xx ~9%. orders.events produce
                           failures — NotEnoughReplicas."
    13:57  oncall-data:   "Debezium orders-outbox-pub flapping.
                           confirmed_flush_lsn frozen. pg_wal climbing."
    14:02  oncall-dba:    "orders DB disk 78%, WAL retention anomaly.
                           replicas show replay_lag fine."
    14:08  oncall-app:    "fulfillment lag 45k. customers: 'order
                           confirmed, no tracking number.'"
    14:11  oncall-sre:    "Scaled fulfillment 8→20 pods. Lag worse —
                           same partition count."
    14:14  oncall-app:    "Step Functions TripBookingSaga unrelated
                           but saga_stuck_count=23 — ignore?"
    14:15  YOU join bridge.

  THE STAGE:

   MICROSERVICES / CHECKOUT PATH
   ─────────────────────────────
   ALB → api-gateway (5s deadline) → checkout-svc (20 replicas)
     ├──► fraud-svc (circuit breaker, 3 retries, no jitter)
     ├──► payments-svc (gRPC, Istio retry 3× on 503)
     └──► inventory-svc (sync HTTP, 2s timeout)

   Order write: checkout-svc → PostgreSQL orders DB (primary)
     └── transactional outbox INSERT (same txn)

   EVENT PATH
   ──────────
   Debezium slot debezium_outbox_orders → orders.outbox topic
     └── fulfillment-svc (8 pods, consumer group, idempotent)
   checkout-svc ALSO produces OrderPlaced → orders.events
     (acks=all, idempotence=true)

   KAFKA CLUSTER (shared)
   ──────────────────────
   12 brokers. click.stream: 128 parts, RF=2, min ISR=1, 140k msg/s.
   orders.outbox: 32 parts, RF=3, min ISR=2.
   orders.events: 64 parts, RF=3, min ISR=2.

   SAGA (separate product line, same org)
   ──────────────────────────────────────
   travel-booking Step Functions saga shares Stripe API rate limit
   with payments-svc. No bulkhead between them.

   RESILIENCE CONFIG (as deployed)
   ───────────────────────────────
   fraud-svc: Resilience4j breaker OPEN after 50% failures.
   checkout→payments: gRPC deadline 4s (not propagated from gateway).
   payments-svc: no circuit breaker on RDS pool (50 conns/pod).
   Debezium: no alert on slot retained WAL bytes.
```

**Your tasks:**

1. Draw the failure chain from `click.stream` misconfiguration to three distinct customer symptoms: (a) checkout 5xx, (b) missing tracking, (c) optional double-charge reports. Label root cause vs mechanism vs symptom at each hop.

2. It is 14:15 UTC. Disk 83%, projected full ~15:30. ISR mostly recovered on orders topics. What do you run in the first 60 seconds — include exact metric/SQL/Kafka commands and what each result tells you?

3. Argue for ONE stabilization path among: (A) drop Debezium slot + replay outbox, (B) throttle click.stream producers, (C) extend disk + scale Debezium tasks. Trade-offs for order durability and fulfillment catch-up.

4. Why did scaling fulfillment 8→20 pods worsen lag? What single config change fixes consumer throughput without touching checkout?

5. fraud-svc recovered at 14:10 but checkout error rate still 67%. Explain using circuit breaker half-open behavior + payments-db connection math (15 pods × 50 pool × scaled replicas).

6. The outbox pattern succeeded at one layer and failed at another during this incident. State precisely where — reference Phase 1 (DB txn) vs Phase 2 (publish).

7. List six post-incident changes with owners: two Kafka, two outbox/CDC, two resilience/microservices. No vague "improve monitoring."

---

## Scoring Guide (self-check after module expert analyses)

```text
Part 1 (Q1–Q5):     4/5+  → Weeks 1–5 still solid
Part 2 (Q6–Q19):   11/14+ → Week 6 architecture patterns retained
Part 3 (scenario):   Principal depth on cascade diagnosis + sequencing

Overall:
  Ready for Week 7  → 85%+ across parts
  Review Week 6     → below 70% on Part 2
  Review Weeks 4–5  → below 60% on Part 1 (replication/outbox bridge)
```

---

> **Worked answers and expert analyses** (no separate Week 6 worked-answer files — answers live in module incident sections):
> - [Message Queues and Kafka — Part 12–13](../Week-06-Architecture-Patterns/Message%20Queues%20and%20Kafka.md) (*The Tuesday Afternoon Black Hole*)
> - [Event-Driven Architecture — Incident Scenario](../Week-06-Architecture-Patterns/Event-Driven%20Architecture.md)
> - [Circuit Breakers — Incident Scenario & Expert Analysis](../Week-06-Architecture-Patterns/Circuit%20Breakers%20Bulkheads%20Timeouts%20Retries%20and%20Backpressure.md)
> - [Microservices Patterns — Incident Scenario](../Week-06-Architecture-Patterns/Microservices%20Patterns.md)
> - [Saga Pattern — Incident Scenario & Expert Analysis](../Week-06-Architecture-Patterns/Saga%20Pattern.md)
> - [Outbox Pattern and CDC — SRE Scenario & Deep-Dive](../Week-06-Architecture-Patterns/Outbox%20Pattern%20and%20CDC.md)
> - [Database Scaling Patterns Worked Answers](../Week-05-Database-Internals/Database%20Scaling%20Patterns%20Worked%20Answers.md) (replication slot / WAL bridge)
