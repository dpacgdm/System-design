# Week 6 Retention Questions

Last verified: 2026-05-15

These questions test the Week 6 architecture-pattern modules:

```text
1. Message Queues and Kafka
2. Event-Driven Architecture
3. Microservices Patterns
4. Saga Pattern
5. Circuit Breakers, Bulkheads, Timeouts, Retries, and Backpressure
6. Outbox Pattern and CDC
```

---

## 1. Rapid fire

```text
1. Why is Kafka better described as a durable partitioned log than a queue?
2. What is the difference between a task queue, pub/sub, and durable event log?
3. Why does partition key choice affect correctness?
4. Why can adding consumers fail to reduce Kafka lag?
5. What does consumer lag hide when only total lag is graphed?
6. What is the difference between an event and a command?
7. Why is CDC not automatically a business event?
8. What is event-carried state transfer?
9. When is orchestration better than choreography?
10. What is a distributed monolith?
11. Why is a shared database a microservice boundary smell?
12. What does a saga compensate?
13. Why is timeout ambiguity dangerous in payment systems?
14. Why do retries need idempotency keys for external side effects?
15. What is retry amplification?
16. Why can a fallback path become a new outage?
17. What does a circuit breaker half-open state do?
18. What does a bulkhead isolate?
19. What problem does the transactional outbox solve?
20. Why can a PostgreSQL replication slot threaten primary disk?
```

---

## 2. Short explanations

### Question 1

A checkout service writes an order to PostgreSQL and then publishes `OrderCreated` to Kafka. The database write succeeds, but Kafka publish fails. What bug can this create, and what pattern fixes it?

Expected answer:

```text
The order exists in the database but downstream consumers never receive the event.
Email, search, fraud, and analytics may miss the order. The transactional outbox
fixes this by writing the order and outbox event in the same local transaction,
then publishing asynchronously via CDC or relay.
```

### Question 2

A Kafka consumer commits offsets before sending email. The consumer crashes after committing but before sending. What delivery behavior is this?

Expected answer:

```text
At-most-once from the business perspective. Kafka believes the record is done,
but the side effect may not have happened.
```

### Question 3

A consumer processes before committing offsets and crashes after sending email but before committing. What must the consumer implement?

Expected answer:

```text
Idempotency or dedupe. The same event may be processed again after restart.
The email consumer should store a sent marker keyed by event_id or order_id plus
email type.
```

### Question 4

A service calls recommendations during checkout. Recommendations p99 becomes 8 seconds and checkout fails. Which Week 6 patterns apply?

Expected answer:

```text
Microservice dependency classification, timeout budget, circuit breaker,
fallback, and bulkhead. Recommendations are optional and should not block the
critical checkout path.
```

---

## 3. Compound scenario: launch-week async meltdown

Architecture:

```text
+----------+      +----------+      +-------------+
| Checkout | ---> | OrdersDB | ---> | Outbox/CDC  |
+----------+      +----------+      +-------------+
                                      |
                                      v
                                  +-------+
                                  | Kafka |
                                  +-------+
                                      |
                 +--------------------+--------------------+
                 |                    |                    |
                 v                    v                    v
          +-------------+      +-------------+        +----------+
          | Inventory   |      | Search      |        | Email    |
          | Projector   |      | Indexer     |        | Sender   |
          +-------------+      +-------------+        +----------+
```

Metrics:

```text
checkout success rate:       98.9%
orders in primary DB:        normal
outbox rows older than 5m:   1,800,000
Kafka produce rate:          lower than expected
inventory lag:               8,500,000 records
search lag:                  21,000,000 records
email lag:                   4,200,000 records
DLQ rate:                    low
PostgreSQL WAL retained:     growing fast
replication slot active:     false
```

Recent changes:

```text
1. Debezium connector restarted during deploy.
2. A new event schema version was released.
3. Search indexer calls OpenSearch synchronously for every event.
4. Email sender retries immediately on provider timeout.
5. Inventory projector is partitioned by product_id.
6. Launch product_id is SNKR-2026.
```

Questions:

```text
1. Which system is authoritative for orders?
2. Is this order loss or projection freshness delay?
3. Which signal says the outbox/CDC layer is unhealthy?
4. Why is WAL retention dangerous?
5. Why might inventory lag be concentrated in one partition?
6. Why might search lag be downstream-induced rather than Kafka-induced?
7. What is unsafe about immediate email retries?
8. Which consumers should be prioritized?
9. What should not be done during the incident?
10. What long-term fixes prevent recurrence?
```

Expected expert analysis:

```text
The primary OrdersDB is authoritative. Checkout success and DB rows are normal,
so this is not initial order loss. It is a downstream freshness and side-effect
incident caused by CDC connector failure, retained WAL, hot partition risk in
inventory, slow OpenSearch writes, and unsafe email retries.

The outbox/CDC layer is unhealthy because old outbox rows are accumulating,
Kafka produce rate is lower than expected, and the replication slot is inactive.
WAL retained bytes growing fast threatens primary disk availability.

Inventory lag may be concentrated because partitioning by product_id routes all
launch product events to one Kafka partition. Adding consumers will not fix one
hot partition.

Search lag may be caused by OpenSearch synchronous indexing latency or rejection,
not Kafka itself. Email retries may amplify provider failure and create duplicate
notifications unless idempotency and backoff exist.

Prioritize inventory correctness and order-related notifications over analytics
or search freshness. Do not drop replication slots casually, delete topic data,
skip offsets without audit, or run full-speed backfills against saturated systems.

Long-term fixes include connector health alerts, WAL retention alerts, partition
key review, per-consumer priority, idempotent consumers, retry backoff with
jitter, schema compatibility gates, and projection freshness SLOs.
```

---

## 4. Interview prompts

```text
1. Design an event-driven checkout system.
2. Explain when you would choose Kafka over SQS.
3. Design a saga for travel booking.
4. Explain how to avoid double-charging a customer during retries.
5. Design a system that rebuilds search from committed database changes.
6. Explain how to prevent one slow dependency from taking down checkout.
7. Diagnose a Kafka consumer group where one partition has 99% of total lag.
8. Explain why microservices can become a distributed monolith.
```

---

## 5. Key retention hooks

```text
Kafka:
  durable log, partition ordering, consumer offsets, lag as business delay

EDA:
  events are facts, commands request action, projections are not authority

Microservices:
  independent ownership and deployment, not random service slicing

Saga:
  explicit workflow recovery, not rollback

Resilience:
  timeouts bound waiting, retries multiply load, bulkheads isolate damage

Outbox/CDC:
  local DB transaction first, reliable async publish second
```
