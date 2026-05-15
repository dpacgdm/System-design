# Week 6, Topic 1: Message Queues and Kafka

Last verified: 2026-05-15

Asynchronous messaging is not a magic performance switch. It is a design tool
for moving work across time, isolating failures, smoothing bursts, and allowing
multiple systems to react to the same business fact.

It also creates new problems: delayed work, duplicate processing, ordering
limits, consumer lag, schema drift, poison messages, replay safety, and hidden
business delay.

---

## 1. Learning objectives

After this topic, you should be able to:

```text
1. Explain the difference between a task queue, pub/sub, and a durable log.
2. Decide when to use direct RPC, SQS, RabbitMQ, Kafka, Redis Streams, or NATS.
3. Explain Kafka topics, partitions, offsets, producers, consumers, and groups.
4. Explain why Kafka is not a normal queue.
5. Design partition keys that preserve ordering without creating hot partitions.
6. Diagnose consumer lag using offsets, throughput, and downstream bottlenecks.
7. Explain at-most-once, at-least-once, effectively-once, and exactly-once scope.
8. Identify poison messages, retry storms, rebalance storms, and DLQ misuse.
9. Operate Kafka safely during incidents without causing data loss or lag explosions.
10. Defend a messaging architecture in a system design interview and in a P1 review.
```

---

## 2. Why messaging exists

A fully synchronous checkout path looks simple:

```text
+--------+    +-----+    +---------+    +-----------+    +-------+
| Client | -> | API | -> | Payment | -> | Inventory | -> | Email |
+--------+    +-----+    +---------+    +-----------+    +-------+
```

The problem is that user latency becomes the sum of the slow path, and
availability becomes coupled to every inline dependency.

```text
If each dependency is 99.9% available:

Payment     99.9%
Inventory   99.9%
Email       99.9%
Analytics   99.9%
Search      99.9%

End-to-end availability:
  0.999 ^ 5 = 0.995
  about 99.5%
```

One optional email service should not block checkout. One slow analytics sink
should not turn order placement into wet cement.

With messaging:

```text
                         synchronous
+--------+    +-----+    +----------+
| Client | -> | API | -> | OrdersDB |
+--------+    +-----+    +----------+
                 |
                 | OrderPlaced
                 v
              +-------+
              | Kafka |
              +-------+
                 |
       +---------+---------+
       |         |         |
       v         v         v
    +------+  +------+  +---------+
    |Email |  |Search|  |Analytics|
    +------+  +------+  +---------+
```

The checkout path stays short. Optional consumers can lag or fail independently.
But the system now needs idempotency, replay, lag monitoring, and schema
discipline.

---

## 3. What people get wrong

### Wrong model 1: Kafka is a queue

A traditional task queue says:

```text
Take this job. One worker should process it. Then remove it.
```

Kafka says:

```text
Append this record to an ordered partition. Consumers read it at offsets.
Retention decides when it disappears.
```

Task queue:

```text
+--------+    +--------+    +--------+
| job 1  | -> | job 2  | -> | job 3  |
+--------+    +--------+    +--------+
    |             |             |
    v             v             v
+--------+    +--------+    +--------+
|Worker A|    |Worker B|    |Worker C|
+--------+    +--------+    +--------+
```

Kafka log:

```text
Topic: orders
Partition 0

+---------+---------+---------+---------+
| off 101 | off 102 | off 103 | off 104 |
+---------+---------+---------+---------+
     ^         ^
     |         |
  fraud     search
  offset    offset
```

The record remains available until retention or compaction removes it. Each
consumer group tracks its own progress.

### Wrong model 2: async means faster

Async moves work out of the user-facing path. It does not delete work.

```text
Before:
  checkout latency = DB + payment + email + search + analytics

After:
  checkout latency = DB + payment + publish event

Still required later:
  email + search + analytics
```

### Wrong model 3: consumer lag is just a Kafka problem

Consumer lag is often a downstream problem wearing a Kafka hat.

```text
Producer rate:        50,000 events/sec
Consumer read rate:   50,000 events/sec
Downstream DB writes: 12,000 events/sec

Real throughput:      12,000 events/sec
Lag growth:           38,000 events/sec
```

Kafka is the smoke alarm. The fire may be OpenSearch, PostgreSQL, Redis, an HTTP
dependency, CPU, schema validation, a poison message, or a bad deploy.

### Wrong model 4: exactly once means the business action happens once

Kafka transactions can coordinate Kafka offsets and Kafka writes in specific
read-process-write pipelines. They do not automatically make an external payment
provider, email sender, or database update happen exactly once.

```text
Kafka -> Consumer -> Payment Provider

Kafka can control Kafka state.
It cannot un-send a payment request.
```

For external effects, use idempotency keys, dedupe tables, unique constraints,
reconciliation, and replay discipline.

---

## 4. Three messaging mental models

### 4.1 Task queue

Use when one work item should be handled by one worker.

```text
+----------+      +-------+      +----------+
| Producer | ---> | Queue | ---> | Worker A |
+----------+      +-------+      +----------+
                      |
                      +------->  +----------+
                                 | Worker B |
                                 +----------+
```

Examples:

```text
- send one email
- resize one image
- process one uploaded file
- retry one webhook delivery
```

Good tools:

```text
SQS, RabbitMQ, Celery-backed queues, Sidekiq, Resque
```

### 4.2 Pub/sub

Use when multiple subscribers should receive the same message.

```text
+-----------+      +-------+      +---------+
| Publisher | ---> | Topic | ---> | Email   |
+-----------+      +-------+      +---------+
                      |
                      +------->  +---------+
                      |          | Search  |
                      |          +---------+
                      |
                      +------->  +---------+
                                 | Metrics |
                                 +---------+
```

Examples:

```text
- OrderCreated
- UserSignedUp
- ProductPriceChanged
```

Good tools:

```text
SNS, Google Pub/Sub, RabbitMQ exchanges, Kafka topics
```

### 4.3 Durable event log

Use when event history itself is valuable.

```text
Topic: order-events

+---------+---------+---------+---------+---------+
| created | paid    | packed  | shipped | delivered|
+---------+---------+---------+---------+---------+
    0         1         2         3         4
```

Consumers can replay retained records.

Use cases:

```text
- rebuild search index
- feed fraud scoring
- stream analytics
- train ML features
- replay after a consumer bug fix
- stream CDC from PostgreSQL into read models
```

Good tools:

```text
Kafka, Redpanda, Pulsar, Kinesis, Event Hubs
```

---

## 5. Comparing common options

```text
+------------------+--------------------------+--------------------------+
| Tool/pattern     | Best for                 | Poor fit                 |
+------------------+--------------------------+--------------------------+
| Direct RPC       | immediate answer         | fanout side effects      |
| DB polling       | tiny local workflows     | high-volume streams      |
| SQS              | simple task queues       | replayable event logs    |
| RabbitMQ         | routing and work queues  | long-retention replay    |
| Kafka            | durable event streams    | tiny background jobs     |
| Redis Streams    | small stream workloads   | huge replay backbone     |
| NATS             | low-latency messaging    | durable audit history    |
+------------------+--------------------------+--------------------------+
```

Kafka is the right answer when the log matters:

```text
- multiple independent consumers need the same facts
- replay is required
- ordering per key matters
- throughput is high
- retained history has operational value
```

Kafka is often the wrong answer when:

```text
- one worker needs one job
- ordering is irrelevant
- throughput is tiny
- operators do not need replay
- a managed task queue would be simpler
```

---

## 6. Kafka core model

Kafka has four core nouns:

```text
topic      = named stream of records
partition  = ordered shard of a topic
offset     = record position inside one partition
consumer   = process that reads records and tracks progress
```

Topic with two partitions:

```text
Topic: orders

Partition 0:
+-------+-------+-------+-------+
| off 0 | off 1 | off 2 | off 3 |
+-------+-------+-------+-------+

Partition 1:
+-------+-------+-------+-------+
| off 0 | off 1 | off 2 | off 3 |
+-------+-------+-------+-------+
```

Ordering is per partition, not per topic.

```text
Guaranteed:
  off 0 before off 1 inside partition 0

Not guaranteed:
  total order across partition 0 and partition 1
```

Record shape:

```text
record = {
  topic: orders,
  partition: 7,
  offset: 991881,
  key: customer-123,
  timestamp: 2026-05-15T10:15:30Z,
  headers: trace_id, schema_version, idempotency_key,
  value: OrderPlaced payload
}
```

Partition choice is commonly key-based:

```text
partition = hash(record.key) % partition_count
```

If key is `customer_id`, all events for one customer usually go to the same
partition and preserve customer-level ordering.

---

## 7. Kafka write path

Simplified write path:

```text
+----------+      +--------+      +----------+
| Producer | ---> | Leader | ---> | Follower |
+----------+      +--------+      +----------+
                      |
                      v
                 append to log
```

Flow:

```text
1. Producer serializes the record.
2. Producer chooses a partition.
3. Producer batches records for efficiency.
4. Producer sends the batch to the partition leader.
5. Leader appends the batch to its local log.
6. Followers replicate the batch.
7. Leader acknowledges based on producer durability settings.
```

Producer acknowledgement modes:

```text
acks=0:
  producer does not wait
  fastest, can silently lose records

acks=1:
  leader acknowledges after local append
  can lose records if leader dies before followers copy

acks=all:
  leader waits for in-sync replica requirements
  higher durability, higher latency
```

Common durable baseline:

```text
replication.factor=3
acks=all
min.insync.replicas=2
```

If ISR falls below the minimum, writes fail instead of pretending to be durable.
That is painful but honest.

---

## 8. Kafka read path and consumer groups

A consumer group shares partitions across consumers.

```text
Topic: orders, 4 partitions

+-------------+      +------------+
| Partition 0 | ---> | Consumer A |
+-------------+      +------------+

+-------------+      +------------+
| Partition 1 | ---> | Consumer A |
+-------------+      +------------+

+-------------+      +------------+
| Partition 2 | ---> | Consumer B |
+-------------+      +------------+

+-------------+      +------------+
| Partition 3 | ---> | Consumer B |
+-------------+      +------------+
```

Within one group, one partition has at most one active owner.

```text
partitions: 4
consumers:  8

useful active consumers: 4
idle consumers:          4
```

Different consumer groups are independent:

```text
              +---------------+
              | orders topic  |
              +---------------+
                 |     |     |
                 v     v     v
              fraud search analytics
              group group  group
```

Fraud can be current while analytics is hours behind.

---

## 9. Offsets and commits

An offset is a position in one partition.

```text
Partition 2

+-----+-----+-----+-----+-----+
| 100 | 101 | 102 | 103 | 104 |
+-----+-----+-----+-----+-----+
              ^
              |
         last processed
```

Bad pattern: commit before processing.

```text
1. poll offset 102
2. commit offset 103
3. process record
4. crash

Result:
  Kafka thinks 102 is done.
  Business side effect may be missing.
```

Safer pattern: process before commit.

```text
1. poll offset 102
2. process record
3. commit offset 103
4. crash before commit

Result:
  record may process again.
```

That is at-least-once. It requires idempotent consumers.

Idempotent consumer sketch:

```sql
BEGIN;

INSERT INTO processed_events(event_id)
VALUES ('evt_123')
ON CONFLICT DO NOTHING;

-- If the insert succeeded, apply business change.
-- If not, skip duplicate.

COMMIT;
```

Duplicates are normal. Damage is optional.

---

## 10. Delivery guarantees

```text
+------------------+-----------------------------+-------------------------+
| Guarantee        | Meaning                     | Requirement             |
+------------------+-----------------------------+-------------------------+
| At-most-once     | may lose, no duplicate work | commit before process   |
| At-least-once    | no intended loss, duplicates| process before commit   |
| Effectively-once | business state changes once | idempotency + dedupe    |
| Exactly-once     | scoped transactional claim  | limited system boundary |
+------------------+-----------------------------+-------------------------+
```

At-least-once is the default safe production posture for many systems.

For external side effects:

```text
- use idempotency keys
- store processed event IDs
- use unique constraints
- reconcile periodically
- make replay safe
```

Interview-grade sentence:

```text
Kafka exactly-once is scoped. For external side effects, I design for
at-least-once delivery with idempotent handlers and reconciliation.
```

---

## 11. Partition-key design

Partition key is correctness design.

Good key for order lifecycle:

```text
key = order_id

+--------------+      +----------+
| OrderCreated | ---> |          |
+--------------+      |          |
                      |Partition |
+--------------+      |    9     |
| PaymentAuth  | ---> |          |
+--------------+      |          |
                      +----------+
+--------------+           |
| Shipped      | ----------+
+--------------+
```

All events for the order land on the same partition.

Bad key for hot product launch:

```text
key = product_id
product_id = SNKR-2026
traffic = 180,000 events/sec

Partition 0:   2K/s
Partition 1:   3K/s
Partition 2: 180K/s  <-- hot
Partition 3:   2K/s
```

Fix options:

```text
1. Key by order_id if order-level ordering is enough.
2. Key by customer_id if customer ordering matters.
3. Bucket a hot key if strict ordering for that key is not required.
4. Split topics only when ownership and consumers are clear.
```

Bucketed key:

```text
key = product_id + ':' + hash(order_id) % 32
```

This spreads load but sacrifices strict total ordering for the product.

---

## 12. Consumer lag

Consumer lag is the distance between latest produced offset and committed group
offset.

```text
Log end offset:     1,000,000
Committed offset:     850,000
Lag:                 150,000 records
```

Lag growth:

```text
Producer rate: 20,000 records/sec
Consumer rate: 15,000 records/sec
Lag growth:     5,000 records/sec

After 10 minutes:
  5,000 * 600 = 3,000,000 records behind
```

Lag patterns:

```text
All partitions lag:
  consumer fleet too small
  downstream slow
  broker or network issue
  bad deploy

One partition lags:
  hot key
  poison message
  skewed assignment

Sawtooth lag:
  batch job
  GC pauses
  rebalance churn
```

Lag is not just a queue metric. It is business delay.

---

## 13. Rebalancing

A rebalance changes partition ownership.

```text
Before:

Partition 0 -> Consumer A
Partition 1 -> Consumer A
Partition 2 -> Consumer B
Partition 3 -> Consumer B

After Consumer C joins:

Partition 0 -> Consumer A
Partition 1 -> Consumer B
Partition 2 -> Consumer C
Partition 3 -> Consumer C
```

Causes:

```text
- consumer crash
- new consumer joins
- missed heartbeat
- processing exceeds max poll interval
- network pause
- GC pause
- rolling deploy
- autoscaler flapping
```

Failure loop:

```text
slow processing
  -> missed poll interval
  -> group marks consumer dead
  -> rebalance
  -> partitions pause
  -> lag grows
  -> same slow work repeats
```

Safe practices:

```text
- keep processing bounded
- use pause/resume for slow downstreams
- use static membership where appropriate
- avoid autoscaler flapping
- deploy consumers in waves
- watch rebalance rate during releases
```

---

## 14. Production failure patterns

### Failure 1: lag from slow downstream

Shape:

```text
+-------+      +----------+      +------------+
| Kafka | ---> | Consumer | ---> | OpenSearch |
+-------+      +----------+      +------------+
                               slow writes
```

Symptoms:

```text
- consumer lag rising
- consumer CPU low or moderate
- downstream p95/p99 high
- read model stale
```

Detect:

```bash
kafka-consumer-groups --bootstrap-server broker:9092 \
  --describe --group search-indexer
```

Mitigate:

```text
1. Identify the slow dependency.
2. Reduce batch size if downstream is overloaded.
3. Pause non-critical consumers if they compete for the same dependency.
4. Bulk more efficiently when downstream supports it.
5. Add backpressure and lag SLOs.
```

### Failure 2: poison message blocks a partition

Shape:

```text
Partition 4

+-----+---------+-----+-----+
| 100 |   101   | 102 | 103 |
+-----+---------+-----+-----+
          ^
          |
       poison
```

Symptoms:

```text
- one partition lag grows
- same offset appears in logs
- same event_id fails repeatedly
- consumer restarts or retries forever
```

Mitigate:

```text
1. Capture bad record payload and headers.
2. Move it to DLQ with topic, partition, offset, and error.
3. Advance past it only with audit trail.
4. Preserve replay tooling.
```

### Failure 3: retry storm

Shape:

```text
Consumer -> API fails
Consumer -> retry now
Consumer -> retry now
Consumer -> retry now
```

Mitigate:

```text
- exponential backoff with jitter
- delayed retry topics
- circuit breaker for downstream
- DLQ after bounded attempts
- no retries for permanent validation errors
```

### Failure 4: hot partition

Symptoms:

```text
- one partition has huge lag
- one consumer hot
- other consumers idle
- broker hosting hot leader has high load
```

Long-term fix:

```text
- redesign key
- bucket hot key if ordering allows
- split critical workloads
- alert on per-partition lag skew
```

### Failure 5: retention expires before replay

```text
retention:       24 hours
consumer outage: 36 hours
lost replay:     12 hours
```

Fix:

```text
- retention based on recovery objectives
- alert on lag age approaching retention
- keep authoritative data elsewhere
- snapshot read models for faster rebuilds
```

---

## 15. SRE diagnostic toolkit

Topic shape:

```bash
kafka-topics --bootstrap-server broker:9092 \
  --describe --topic orders
```

Consumer lag:

```bash
kafka-consumer-groups --bootstrap-server broker:9092 \
  --describe --group fraud-service
```

Interpretation:

```text
CURRENT-OFFSET = committed group offset
LOG-END-OFFSET = newest available offset
LAG            = LOG-END-OFFSET - CURRENT-OFFSET
```

Dashboard signals:

```text
- under-replicated partitions
- offline partitions
- ISR shrink/expand rate
- broker produce/fetch latency
- consumer lag by group and partition
- consumer lag age
- rebalance rate
- processing latency
- DLQ records/sec
- producer error and retry rate
```

Show lag by partition. Total lag can hide one-partition disasters.

---

## 16. Decision framework

```text
+-----------------------------+------------------------------+
| Requirement                 | Likely choice                |
+-----------------------------+------------------------------+
| One job, one worker         | SQS, RabbitMQ, task queue    |
| Rich routing                | RabbitMQ                     |
| Many consumers and replay   | Kafka, Pulsar, Kinesis       |
| CDC backbone                | Kafka                        |
| Simple managed queue        | SQS                          |
| Low-latency ephemeral bus   | NATS                         |
| Small background jobs       | Sidekiq, Celery, SQS         |
| Strict immediate response   | Direct RPC                   |
+-----------------------------+------------------------------+
```

Ask before choosing Kafka:

```text
Do I need replay?
Do multiple independent consumers need the event?
Do I need partition-level ordering?
Can I tolerate and observe lag?
Can I handle duplicates?
Can I govern schema evolution?
Can I design a sane partition key?
```

---

## 17. Incident scenario: launch event lag meltdown

Architecture:

```text
+----------+      +----------+      +-----------+
| Checkout | ---> | OrdersDB | ---> | Outbox CDC|
+----------+      +----------+      +-----------+
                                      |
                                      v
                                  +-------+
                                  | Kafka |
                                  +-------+
                                      |
                    +-----------------+-----------------+
                    |                 |                 |
                    v                 v                 v
              +----------+     +-------------+     +---------+
              | Fraud    |     | Inventory   |     | Search  |
              +----------+     +-------------+     +---------+
```

Baseline:

```text
produce rate:            8,000 events/sec
fraud lag:               < 5,000 records
inventory lag:           < 2,000 records
search lag:              < 50,000 records
rebalance rate:          near zero
DLQ rate:                near zero
```

Incident:

```text
produce rate:            55,000 events/sec
fraud lag:               90,000 records and stable
inventory lag:           7,800,000 records and growing
search lag:              24,000,000 records and growing
rebalance rate:          120/hour
DLQ rate:                0
```

Partition lag sample:

```text
partition 03:       12,000
partition 04:       10,500
partition 05:    7,400,000  <-- hot
partition 06:       11,000
partition 07:       13,200
```

Recent change:

```text
Producer partition key changed from order_id to product_id.
Launch product_id = SNKR-2026.
Consumers autoscaled from 24 to 96 during the incident.
Search indexer writes synchronously to OpenSearch.
```

Diagnosis:

```text
The partition key change created a hot partition. All launch events for
SNKR-2026 land on one partition. One partition can have only one active owner in
a consumer group, so adding consumers does not increase throughput for that
partition.
```

Mitigation:

```text
1. Stop autoscaling churn.
2. Roll back producer key to order_id if safe.
3. Protect inventory consumer before search freshness.
4. Pause or slow non-critical search indexing if it competes for resources.
5. Preserve records; do not skip offsets without audit.
6. Communicate search freshness degradation separately from order authority.
```

Long-term fixes:

```text
- partition by entity requiring ordering
- load test launch-key skew
- alert on per-partition lag skew
- separate critical and non-critical consumers
- use bulk indexing and backpressure for search
- add producer-key contract checks before deployment
```

---

## 18. Key takeaways

```text
1. Kafka is a durable partitioned log, not a normal task queue.
2. Ordering is per partition, so partition-key design is correctness design.
3. Consumer lag is business delay, not just a Kafka metric.
4. At-least-once plus idempotency is the default safe production posture.
5. Exactly-once has scope; external side effects still need dedupe and repair.
6. More consumers do not help one hot partition.
7. DLQs are evidence lockers, not trash cans.
8. Retention must exceed realistic recovery and replay windows.
9. Messaging decouples failures but creates new operational state.
10. Choose Kafka when replay, fanout, and durable ordering are worth the cost.
```

---

## 19. Targeted reading

```text
Kafka documentation:
  - Core concepts
  - Producers
  - Consumers and consumer groups
  - Configuration
  - Operations and monitoring
  - Transactions and semantics

Designing Data-Intensive Applications:
  - Chapter 5: Replication
  - Chapter 6: Partitioning
  - Chapter 11: Stream Processing

Kafka: The Definitive Guide:
  - Producers
  - Consumers
  - Reliable Data Delivery
  - Building Data Pipelines
```
