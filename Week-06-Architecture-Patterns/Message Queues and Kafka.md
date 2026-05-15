# Week 6, Topic 1: Message Queues and Kafka

Last verified: 2026-05-15

Messaging is the architecture move you make when work no longer has to happen
inside one request-response call. It lets a system say:

```text
This fact happened. Other systems may react when they can.
```

That sentence is powerful. It also opens a trapdoor. Once work becomes async,
you inherit lag, duplicates, replay, poison messages, schema evolution, ordering
limits, and operational state that can quietly drift away from the user-facing
API.

This topic teaches queues and Kafka as production systems, not interview
stickers.

---

## 1. Learning objectives

```text
After this topic, you should be able to:

1. Separate task queues, pub/sub, and durable event logs.
2. Explain why Kafka is not just a queue.
3. Choose between direct RPC, SQS, RabbitMQ, Kafka, Redis Streams, NATS,
   Kinesis, and database polling.
4. Explain Kafka topics, partitions, offsets, leaders, followers, ISR, producer
   acks, consumer groups, and rebalancing.
5. Design partition keys that preserve required ordering without creating hot
   partitions.
6. Calculate consumer lag growth and catch-up time.
7. Explain at-most-once, at-least-once, effectively-once, and exactly-once scope.
8. Diagnose poison messages, retry storms, retention loss, rebalance storms,
   and downstream bottlenecks.
9. Build a safe incident response for Kafka-backed systems.
10. Defend messaging choices in a system design interview with operational
    tradeoffs, not slogans.
```

---

## 2. What people get wrong

### Wrong model 1: Kafka is a queue

A task queue says:

```text
Here is a job. One worker should do it. Remove it when done.
```

Kafka says:

```text
Here is an ordered append-only record in a partition. Consumers track their own
position. Retention decides when the record disappears.
```

Task queue shape:

```text
+----------+      +-------+      +----------+
| Producer | ---> | Queue | ---> | Worker A |
+----------+      +-------+      +----------+
                      |
                      +------->  +----------+
                                 | Worker B |
                                 +----------+
```

A job is claimed and eventually removed.

Kafka log shape:

```text
Topic: orders
Partition 0

+---------+---------+---------+---------+---------+
| off 100 | off 101 | off 102 | off 103 | off 104 |
+---------+---------+---------+---------+---------+
      ^                   ^
      |                   |
 fraud-service       search-indexer
 committed offset    committed offset
```

The same record can be read by many consumer groups. The record is not removed
because one consumer processed it.

### Wrong model 2: async means faster

Async can make the user-facing request faster by moving work out of the path.
It does not reduce total work.

```text
Synchronous checkout:

client -> API -> orders DB -> payment -> email -> search -> analytics

Async checkout:

client -> API -> orders DB -> publish event
                         |
                         v
                  email/search/analytics later
```

The second design shortens checkout latency, but the system still has to send
email, update search, and process analytics. Async changes when and where work
happens.

### Wrong model 3: consumer lag is a Kafka problem

Kafka may only be the scoreboard.

```text
Producer rate:          80,000 records/sec
Consumer poll rate:     80,000 records/sec
OpenSearch write rate:  15,000 records/sec

Real progress:          15,000 records/sec
Lag growth:             65,000 records/sec
```

The broker can be healthy while a read model is hours stale.

### Wrong model 4: exactly-once means the business action happens once

Kafka transactions can coordinate Kafka reads, Kafka writes, and Kafka offset
commits inside Kafka. They do not control Stripe, an email provider, a warehouse
API, Redis, or PostgreSQL side effects unless those systems are part of a safe
idempotent protocol.

```text
Kafka topic A -> stream processor -> Kafka topic B
  Kafka transactions can help.

Kafka topic A -> consumer -> payment provider
  Kafka cannot un-send a payment request.
```

For external effects, the practical production design is:

```text
at-least-once delivery + idempotency + reconciliation
```

### Wrong model 5: more partitions always means more capacity

Partitions increase maximum parallelism, but they also increase metadata,
leaders, files, recovery work, rebalancing cost, monitoring noise, and operational
blast radius.

More partitions help only if the workload can actually spread across them.

```text
Topic partitions: 48
Hot key: SNKR-2026
All hot events hash to partition 17

Adding consumers: no fix
Adding partitions: no immediate fix without repartitioning new writes
```

---

## 3. The three messaging shapes

### 3.1 Task queue

Use when one job should be done by one worker.

```text
+----------+      +-------------+      +----------+
| Producer | ---> | Task Queue  | ---> | Worker A |
+----------+      +-------------+      +----------+
                         |
                         +------->     +----------+
                                       | Worker B |
                                       +----------+
```

Examples:

```text
send one email
resize one image
process one uploaded document
retry one webhook delivery
run one billing job
```

Important mechanics:

```text
acknowledgement:
  worker tells queue the job succeeded

visibility timeout:
  job becomes visible again if worker dies before ack

dead-letter queue:
  jobs go here after bounded failures

retry policy:
  controls when failed work is retried
```

Best fits:

```text
SQS, RabbitMQ, Celery, Sidekiq, Resque
```

Kafka can be used as a work queue, but it is usually not the cleanest tool for
simple one-job-one-worker systems.

### 3.2 Pub/sub

Use when many subscribers should receive the same message.

```text
+-----------+      +-------+      +----------+
| Publisher | ---> | Topic | ---> | Consumer |
+-----------+      +-------+      +----------+
                      |
                      +------->   +----------+
                      |           | Consumer |
                      |           +----------+
                      |
                      +------->   +----------+
                                  | Consumer |
                                  +----------+
```

Examples:

```text
UserSignedUp
OrderPlaced
ProductPriceChanged
PaymentCaptured
```

Important mechanics:

```text
fanout
subscription ownership
subscriber isolation
schema compatibility
per-subscriber retries
```

Best fits:

```text
SNS, Google Pub/Sub, RabbitMQ exchanges, Kafka topics
```

### 3.3 Durable event log

Use when the history is valuable and replay is a feature.

```text
Topic: order-events

+-------------+-------------+--------------+---------+-----------+
| OrderPlaced | PaymentMade | ItemPacked   | Shipped | Delivered |
+-------------+-------------+--------------+---------+-----------+
       0             1              2           3          4
```

Consumers can replay from retained offsets.

Examples:

```text
rebuild a search index
recompute analytics
feed fraud scoring
reprocess events after a bug fix
stream CDC from PostgreSQL
build materialized read models
```

Best fits:

```text
Kafka, Redpanda, Pulsar, Kinesis, Azure Event Hubs
```

---

## 4. Option comparison

```text
+------------------+---------------------------+--------------------------+
| Option           | Best for                  | Poor fit                 |
+------------------+---------------------------+--------------------------+
| Direct RPC       | immediate answer          | fanout side effects      |
| DB polling       | tiny local workflows      | high-volume streams      |
| SQS              | managed task queue        | long replay log          |
| RabbitMQ         | routing and task queues   | huge retained log        |
| Kafka            | durable event streams     | tiny background jobs     |
| Redis Streams    | small/medium streams      | long-term event backbone |
| NATS             | low-latency messaging     | audit/replay history     |
| Kinesis          | managed ordered shards    | arbitrary task routing   |
+------------------+---------------------------+--------------------------+
```

### Direct RPC

```text
+---------+      +---------+
| Service | ---> | Service |
+---------+      +---------+
```

Strengths:

```text
clear request/response
caller knows result immediately
natural for queries and commands needing a decision
simple debugging path
```

Problems:

```text
caller waits
dependency failure propagates
fanout multiplies latency
retries can amplify outages
not replayable
```

Use for:

```text
payment authorization
inventory reservation
login
read queries
synchronous validation
```

Do not use for:

```text
email after checkout
analytics
search indexing
recommendation refresh
low-priority notifications
```

### SQS-style queue

Strengths:

```text
managed durability
simple worker scaling
visibility timeout
DLQ support
low operator burden
```

Problems:

```text
not a replay log
message retention is bounded
ordering requires FIFO and has throughput tradeoffs
harder for many independent replaying consumers
```

### RabbitMQ-style broker

Strengths:

```text
rich routing
exchanges and bindings
per-queue semantics
strong work-queue ergonomics
```

Problems:

```text
large backlogs can hurt broker health
long replay history is not its primary shape
routing topology can become hidden architecture
```

### Kafka-style log

Strengths:

```text
high-throughput append log
replayable history
partition ordering
many independent consumer groups
retention and compaction
CDC and analytics backbone
```

Problems:

```text
partition-key mistakes are expensive
consumer lag can hide business delay
simple task queues are awkward
operations require discipline
exactly-once is often misunderstood
```

---

## 5. Kafka core model

Kafka has four core nouns.

```text
topic      = named stream of records
partition  = ordered shard of a topic
offset     = position inside one partition
consumer   = process reading records
```

Topic with partitions:

```text
Topic: orders

Partition 0
+-------+-------+-------+-------+
| off 0 | off 1 | off 2 | off 3 |
+-------+-------+-------+-------+

Partition 1
+-------+-------+-------+-------+
| off 0 | off 1 | off 2 | off 3 |
+-------+-------+-------+-------+
```

Ordering guarantee:

```text
Guaranteed:
  off 0 before off 1 inside the same partition

Not guaranteed:
  global ordering across partitions
```

A useful event record includes more than payload.

```text
key:              customer-123
value:            OrderPlaced payload
event_id:         evt_01J...
correlation_id:   request trace across services
causation_id:     event or command that caused this event
schema_version:   payload contract version
occurred_at:      when business fact occurred
published_at:     when event entered the stream
```

---

## 6. Kafka write path

```text
+----------+      +---------+      +----------+
| Producer | ---> | Leader  | ---> | Follower |
+----------+      +---------+      +----------+
                      |
                      v
                 append to log
```

Flow:

```text
1. Producer serializes record.
2. Producer chooses partition from key or partitioner.
3. Producer batches records.
4. Producer sends batch to partition leader.
5. Leader appends batch to local log.
6. Followers replicate from leader.
7. Producer receives ack according to durability settings.
```

Important settings:

```text
acks=0:
  producer does not wait; fastest and unsafe

acks=1:
  leader confirms local write; can lose data if leader dies before replication

acks=all:
  leader waits for in-sync replica requirement

replication.factor=3:
  three copies when healthy

min.insync.replicas=2:
  at least two in-sync replicas required for acknowledged writes with acks=all
```

Safe baseline for important events:

```text
replication.factor=3
acks=all
min.insync.replicas=2
enable.idempotence=true
```

Tradeoff:

```text
Higher durability can increase latency and can reject writes during replica
problems. That is better than silently acknowledging records that are not durable.
```

---

## 7. Kafka read path and consumer groups

A consumer group shares partitions across its members.

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

One partition has at most one active owner inside a group.

```text
partitions: 4
consumers:  8

active useful consumers: 4
idle consumers:          4
```

Different groups are independent.

```text
+-------------+
| orders topic|
+-------------+
   |     |     |
   v     v     v
fraud  search analytics
 group  group   group
```

Fraud can be caught up while analytics is hours behind.

---

## 8. Offsets and delivery semantics

Offset:

```text
Partition 2

+-----+-----+-----+-----+-----+
| 100 | 101 | 102 | 103 | 104 |
+-----+-----+-----+-----+-----+
              ^
              |
         current work
```

Commit before processing:

```text
1. poll offset 102
2. commit offset 103
3. process record
4. crash

Result:
  record may be lost from business perspective
```

Process before commit:

```text
1. poll offset 102
2. process record
3. commit offset 103
4. crash before commit

Result:
  record may process again
```

That is why production consumers need idempotency.

```sql
BEGIN;

INSERT INTO processed_events(event_id)
VALUES ('evt_123')
ON CONFLICT DO NOTHING;

-- If inserted, apply business change.
-- If already present, skip duplicate.

COMMIT;
```

Guarantee summary:

```text
+------------------+----------------------------+-------------------------+
| Guarantee        | Meaning                    | Requirement             |
+------------------+----------------------------+-------------------------+
| At-most-once     | may lose, no duplicates    | commit before process   |
| At-least-once    | duplicates possible        | process before commit   |
| Effectively-once | business state once        | idempotency and dedupe  |
| Exactly-once     | scoped transactional claim | same transaction domain |
+------------------+----------------------------+-------------------------+
```

---

## 9. Partition-key design

Partition key controls ordering and load distribution.

Good key for order lifecycle:

```text
key = order_id

OrderPlaced -> PaymentCaptured -> Packed -> Shipped

All events for one order stay in one partition.
```

Clean ordering:

```text
Partition 9
+-------------+-----------------+--------+---------+
| OrderPlaced | PaymentCaptured | Packed | Shipped |
+-------------+-----------------+--------+---------+
```

Bad key for a launch:

```text
key = product_id
product_id = SNKR-2026
traffic = 180,000 events/sec
```

Result:

```text
Partition 0:   2K/s
Partition 1:   3K/s
Partition 2: 180K/s  <-- hot
Partition 3:   2K/s
```

Fix choices:

```text
key by order_id:
  preserves order lifecycle

key by customer_id:
  preserves customer-level order

bucket hot key:
  key = product_id + ':' + hash(order_id) % 32
  spreads load but sacrifices strict product-level total order
```

Design rule:

```text
Choose the key for the smallest entity that truly needs ordering.
```

---

## 10. Consumer lag

Lag:

```text
Log end offset:      1,000,000
Committed offset:      850,000
Lag:                  150,000 records
```

Lag growth:

```text
Producer rate: 80,000 records/sec
Consumer rate: 50,000 records/sec
Lag growth:    30,000 records/sec

After 10 minutes:
  30,000 * 600 = 18,000,000 records behind
```

Catch-up math if producers stop:

```text
Lag:             18,000,000 records
Consumer rate:       50,000 records/sec
Catch-up time:          360 sec = 6 minutes
```

Catch-up math if producers continue:

```text
Producer rate: 80,000/sec
Consumer rate: 50,000/sec

No catch-up. Lag keeps growing.
```

Lag shapes:

```text
All partitions lag:
  fleet undercapacity, downstream slow, bad deploy, broker issue

One partition lags:
  hot key, poison message, skewed assignment

Sawtooth lag:
  batch jobs, GC pauses, rebalances, scheduled downstream throttling
```

---

## 11. Rebalancing

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

Common triggers:

```text
consumer crash
new consumer joins
missed heartbeat
processing exceeds max.poll.interval.ms
network pause
GC pause
rolling deploy
autoscaler flapping
```

Bad loop:

```text
slow processing
  -> missed poll
  -> rebalance
  -> partitions pause
  -> lag grows
  -> consumer restarts
  -> same slow processing repeats
```

Mitigation:

```text
- keep processing bounded
- separate polling from long processing when appropriate
- use pause/resume for slow downstreams
- deploy consumers in waves
- avoid autoscaler flapping
- monitor rebalance rate during releases
```

---

## 12. Production failure patterns

### Failure 1: downstream bottleneck hidden as Kafka lag

Shape:

```text
+-------+      +----------+      +------------+
| Kafka | ---> | Consumer | ---> | OpenSearch |
+-------+      +----------+      +------------+
                                  slow writes
```

Symptoms:

```text
consumer lag rising
consumer CPU low or moderate
downstream p99 high
bulk write rejections
read model stale
```

Detect:

```bash
kafka-consumer-groups --bootstrap-server broker:9092 \
  --describe --group search-indexer
```

Also inspect downstream queues, p99 latency, rejection rate, and saturation.

Mitigation:

```text
1. Identify the slow dependency.
2. Pause non-critical consumers if they compete for capacity.
3. Reduce or tune batch size.
4. Add backpressure instead of unbounded retries.
5. Communicate read-model freshness separately from write correctness.
```

### Failure 2: poison message blocks one partition

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
same offset in logs repeatedly
same event_id fails repeatedly
one partition lag grows
other partitions stay healthy
```

Mitigation:

```text
1. Capture original payload and headers.
2. Move to DLQ with topic, partition, offset, error, and timestamp.
3. Advance only with audit trail.
4. Build DLQ replay tooling.
```

Never skip offsets silently.

### Failure 3: retry storm

Shape:

```text
consumer -> API fails
consumer -> retry now
consumer -> retry now
consumer -> retry now
```

Fix:

```text
bounded retries
exponential backoff with jitter
delayed retry topics
circuit breaker around downstream
DLQ after permanent or repeated failure
```

### Failure 4: retention expires before recovery

```text
retention:       24 hours
consumer outage: 36 hours
missing replay:  12 hours
```

Fix:

```text
- set retention from recovery objective, not vibes
- alert on lag age approaching retention
- snapshot read models
- keep authoritative source outside Kafka when needed
```

### Failure 5: schema change breaks consumers

Symptoms:

```text
deserialization errors after producer deploy
lag starts across all partitions
DLQ fills with same schema version
```

Fix:

```text
schema registry compatibility checks
additive changes first
no semantic meaning changes under same field name
consumer contract tests
producer deploy gates
```

---

## 13. SRE diagnostic toolkit

Topic metadata:

```bash
kafka-topics --bootstrap-server broker:9092 \
  --describe --topic orders
```

Consumer group:

```bash
kafka-consumer-groups --bootstrap-server broker:9092 \
  --describe --group fraud-service
```

Interpretation:

```text
CURRENT-OFFSET = committed group offset
LOG-END-OFFSET = newest offset
LAG            = LOG-END-OFFSET - CURRENT-OFFSET
```

Metrics to dashboard:

```text
under-replicated partitions
offline partitions
ISR shrink rate
produce request latency
fetch request latency
consumer lag by group and partition
consumer lag age
rebalance rate
processing latency
DLQ records/sec
producer error rate
producer retry rate
```

Total lag is not enough. Always inspect lag by partition.

---

## 14. Decision framework

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
| Immediate response required | Direct RPC                   |
+-----------------------------+------------------------------+
```

Kafka is justified when replay, fanout, and durable partitioned ordering are
worth the operational cost.

---

## 15. Incident scenario: launch event lag meltdown

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
produce rate:        8,000 events/sec
fraud lag:           < 5,000 records
inventory lag:       < 2,000 records
search lag:          < 50,000 records
rebalance rate:      near zero
DLQ rate:            near zero
```

Incident:

```text
produce rate:        55,000 events/sec
fraud lag:           90,000 records and stable
inventory lag:       7,800,000 records and growing
search lag:          24,000,000 records and growing
rebalance rate:      120/hour
DLQ rate:            0
```

Partition lag:

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
Consumers autoscaled from 24 to 96.
Search indexer writes synchronously to OpenSearch.
```

Expert diagnosis:

```text
The partition key change created a hot partition. All launch events for the hot
product land on one partition. One partition can have only one active owner in a
consumer group, so autoscaling cannot fix that partition. It can even increase
rebalance churn.
```

Mitigation:

```text
1. Stop autoscaler churn.
2. Roll back producer key to order_id if safe.
3. Prioritize inventory over search freshness.
4. Pause or slow non-critical search indexing if it competes for resources.
5. Preserve records; do not skip offsets without audit.
6. Communicate that search is stale but order authority is safe.
```

Long-term fix:

```text
partition by the entity requiring ordering
load-test hot-key launches
alert on per-partition lag skew
separate critical and non-critical consumers
add producer-key contract checks
```

---

## 16. Key takeaways

```text
1. Kafka is a durable partitioned log, not a normal task queue.
2. Ordering is per partition.
3. Partition-key design is correctness design.
4. Consumer lag is business delay.
5. At-least-once plus idempotency is the normal safe posture.
6. Exactly-once has scope; external side effects still need dedupe.
7. More consumers do not fix one hot partition.
8. DLQs are evidence lockers, not trash cans.
9. Retention must exceed realistic recovery windows.
10. Choose Kafka when replay, fanout, and durable ordering justify the cost.
```

---

## 17. Targeted reading

```text
Kafka documentation:
  Core concepts
  Producers
  Consumers and consumer groups
  Configuration
  Operations and monitoring
  Transactions and semantics

Designing Data-Intensive Applications:
  Chapter 5: Replication
  Chapter 6: Partitioning
  Chapter 11: Stream Processing

Kafka: The Definitive Guide:
  Producers
  Consumers
  Reliable Data Delivery
  Building Data Pipelines
```
