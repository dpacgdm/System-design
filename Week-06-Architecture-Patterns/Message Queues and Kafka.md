# Week 6, Topic 1: Message Queues and Kafka

Last verified: 2026-05-15

---

## Message Queues: What They Actually Are

A message queue is not "Kafka with fewer partitions" and Kafka is not "a bigger RabbitMQ."

Messaging systems exist because not all work should happen inside the user's request path.

A synchronous request says:

```text
Do this now. I am waiting for the answer.
```

A message says:

```text
This work or fact can be processed by another component later.
```

That one shift changes the whole system design.

Without messaging:

```text
Checkout API
  -> write order
  -> capture payment
  -> reserve inventory
  -> send email
  -> update search
  -> send analytics
  -> call warehouse
  -> return response to user
```

If email, analytics, or search is slow, checkout becomes slow. If one optional dependency fails, the critical path coughs up smoke.

With messaging:

```text
Checkout API
  -> write order
  -> capture payment
  -> reserve inventory
  -> publish OrderPlaced
  -> return response to user

OrderPlaced consumers:
  -> send email
  -> update search
  -> analytics
  -> warehouse notification
```

Clean shape:

```text
+--------+      +----------+      +----------+
| Client | ---> | Checkout | ---> | OrdersDB |
+--------+      +----------+      +----------+
                      |
                      | OrderPlaced
                      v
                  +--------+
                  | Broker |
                  +--------+
                   |  |  |
                   v  v  v
                Email Search Analytics
```

Messaging buys decoupling. It does not delete work. The work still happens, but now it happens later, elsewhere, and with new failure modes.

---

## The Three Different Things People Confuse

Most confusion disappears if you separate these three patterns:

```text
1. Task queue
2. Publish/subscribe
3. Durable event log
```

They all move messages, but they have different semantics.

---

## 1. Task Queue

A task queue is for work distribution.

```text
One job should be handled by one worker.
```

Example:

```text
SendReceiptEmail(order_id=123)
ResizeImage(image_id=abc)
ProcessCsvImport(import_id=999)
RetryWebhookDelivery(webhook_id=555)
```

Diagram:

```text
+----------+      +-------------+      +----------+
| Producer | ---> | Task Queue  | ---> | Worker A |
+----------+      +-------------+      +----------+
                         |
                         +------->     +----------+
                         |             | Worker B |
                         |             +----------+
                         |
                         +------->     +----------+
                                       | Worker C |
                                       +----------+
```

Core mechanics:

```text
PUSH JOB:
  Producer adds job to queue.

CLAIM JOB:
  Worker receives job.

ACK JOB:
  Worker says job succeeded.

REDELIVER JOB:
  If worker dies before ack, queue gives job to another worker.

DEAD-LETTER:
  After too many failures, job moves to a DLQ for inspection.
```

Typical systems:

```text
SQS
RabbitMQ
Sidekiq
Celery
Resque
Beanstalkd
```

Use a task queue when:

```text
- one job should be processed once logically
- order between unrelated jobs does not matter much
- workers can scale horizontally
- retry and DLQ behavior are central
```

Do not overcomplicate this. If all you need is "send this email later," Kafka may be a cathedral for a garden shed.

---

## 2. Publish/Subscribe

Pub/sub is for fanout.

```text
One published message should be seen by multiple subscribers.
```

Example:

```text
OrderPlaced
  -> Email service sends receipt
  -> Search service indexes order
  -> Analytics service records event
  -> Fraud service updates model
```

Diagram:

```text
+-----------+      +-------+      +----------+
| Publisher | ---> | Topic | ---> | Email    |
+-----------+      +-------+      +----------+
                      |
                      +------->   +----------+
                      |           | Search   |
                      |           +----------+
                      |
                      +------->   +----------+
                                  | Analytics|
                                  +----------+
```

Core mechanics:

```text
PUBLISH:
  Producer writes message to topic.

SUBSCRIBE:
  Each subscriber receives its own copy or stream view.

ISOLATION:
  Slow analytics should not block email.

FILTERING:
  Some systems allow subscribers to receive only matching messages.
```

Typical systems:

```text
SNS
Google Pub/Sub
RabbitMQ exchanges
Kafka topics
NATS
```

Use pub/sub when:

```text
- many consumers care about the same event
- consumers are independently owned
- new consumers may be added later
- side effects should not block the publisher
```

---

## 3. Durable Event Log

A durable event log is not mainly about assigning jobs. It is about retaining an ordered history that consumers can replay.

Kafka belongs here.

```text
Topic: order-events

+-------------+-----------------+---------------+---------+-----------+
| OrderPlaced | PaymentCaptured | ItemPacked    | Shipped | Delivered |
+-------------+-----------------+---------------+---------+-----------+
      0               1                 2             3          4
```

Consumers track their own position:

```text
fraud-service offset:          4
search-indexer offset:         2
analytics-pipeline offset:     0
```

The log does not delete a record because one consumer processed it. The log keeps records until retention or compaction removes them.

Use a durable log when:

```text
- replay matters
- many independent consumers need the same history
- consumers may be offline and catch up later
- read models need rebuilds
- CDC streams need fanout
- event order per key matters
```

Typical systems:

```text
Kafka
Redpanda
Pulsar
Kinesis
Azure Event Hubs
```

---

## Kafka: What It Actually Is

Kafka is a distributed, replicated, partitioned commit log.

That sentence matters.

```text
DISTRIBUTED:
  Data is spread across brokers.

REPLICATED:
  Partitions have copies for durability and availability.

PARTITIONED:
  Each topic is split into ordered shards.

COMMIT LOG:
  Records are appended, ordered, and read by offset.
```

Kafka is not optimized around "remove message after processing." It is optimized around high-throughput appends, sequential reads, replay, and independent consumer progress.

---

## Kafka Core Vocabulary

```text
BROKER:
  Kafka server.

CLUSTER:
  Group of brokers.

TOPIC:
  Named stream of records.

PARTITION:
  Ordered shard of a topic.

OFFSET:
  Position of a record inside one partition.

PRODUCER:
  Client that writes records.

CONSUMER:
  Client that reads records.

CONSUMER GROUP:
  Set of consumers sharing work for a topic.

LEADER:
  Broker currently handling reads/writes for a partition.

FOLLOWER:
  Broker replicating from the leader.

ISR:
  In-sync replicas. Followers caught up enough to be considered safe.
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

Partition 2
+-------+-------+-------+-------+
| off 0 | off 1 | off 2 | off 3 |
+-------+-------+-------+-------+
```

Ordering rule:

```text
Kafka preserves order within a partition.
Kafka does not preserve global order across partitions.
```

That is the hinge on which many Kafka designs succeed or shatter.

---

## Kafka Record Anatomy

A production Kafka record is more than a JSON blob.

```text
key:              order_123
value:            serialized event payload
headers:          metadata
partition:        7
offset:           8819231
timestamp:        2026-05-15T10:15:30Z
```

Useful event payload fields:

```text
event_id:         evt_01J...
event_type:       OrderPlaced
schema_version:   3
aggregate_type:   Order
aggregate_id:     order_123
occurred_at:      business time
published_at:     broker publish time
correlation_id:   trace across workflow
causation_id:     command/event that caused this event
producer:         checkout-service
payload:          business fields
```

Why this matters:

```text
event_id:
  dedupe and audit

aggregate_id:
  partitioning and ordering

schema_version:
  compatibility

correlation_id:
  incident debugging

occurred_at vs published_at:
  business delay vs pipeline delay
```

---

## How Kafka Writes Work

Producer write path:

```text
+----------+      +-------------+      +-------------+
| Producer | ---> | Leader      | ---> | Follower    |
+----------+      | Broker      |      | Broker      |
                  +-------------+      +-------------+
                         |
                         v
                   append to log
```

Step-by-step:

```text
1. Producer serializes record.
2. Producer chooses topic.
3. Producer chooses partition.
4. Producer batches records for throughput.
5. Producer sends batch to partition leader.
6. Leader appends batch to local log.
7. Followers replicate from leader.
8. Producer receives ack depending on durability settings.
```

### Producer acks

```text
acks=0:
  Producer does not wait for broker confirmation.
  Fastest. Unsafe for important events.

acks=1:
  Leader confirms after local append.
  Record can be lost if leader dies before followers replicate.

acks=all:
  Leader waits for in-sync replica requirement.
  Better durability. Higher latency. Can reject writes during replica trouble.
```

Durable baseline:

```text
replication.factor=3
acks=all
min.insync.replicas=2
enable.idempotence=true
```

Meaning:

```text
There are three copies when healthy.
A write is acknowledged only if enough replicas are in sync.
Producer retries are protected against duplicate sequence writes to a partition.
```

Tradeoff:

```text
If only one replica is healthy, Kafka may reject writes.
That is not Kafka being annoying. That is Kafka refusing to lie about durability.
```

---

## How Kafka Reads Work

Consumers read records from partitions.

```text
+-------------+      +------------+
| Partition 0 | ---> | Consumer A |
+-------------+      +------------+

+-------------+      +------------+
| Partition 1 | ---> | Consumer B |
+-------------+      +------------+
```

A consumer group shares partitions among consumers.

```text
Topic: orders, 4 partitions
Consumer group: search-indexer

Partition 0 -> Consumer A
Partition 1 -> Consumer A
Partition 2 -> Consumer B
Partition 3 -> Consumer B
```

Important rule:

```text
Within one consumer group, one partition is owned by at most one active consumer at a time.
```

If a topic has 4 partitions and a group has 10 consumers:

```text
4 consumers do useful partition work.
6 consumers are idle for that topic.
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

Fraud can be current while analytics is six hours behind.

---

## Offsets: The Most Important Kafka Detail

An offset is a position in a partition.

```text
Partition 2

+-----+-----+-----+-----+-----+
| 100 | 101 | 102 | 103 | 104 |
+-----+-----+-----+-----+-----+
              ^
              |
          processing
```

A consumer commits offsets to say:

```text
I have processed up to here.
```

But the timing of the commit changes the delivery guarantee.

### Commit before processing

```text
1. poll offset 102
2. commit offset 103
3. process message
4. crash before side effect
```

Result:

```text
Kafka thinks 102 is done.
Business work may be missing.
```

This is at-most-once behavior.

### Process before commit

```text
1. poll offset 102
2. process message
3. commit offset 103
4. crash after processing before commit
```

Result:

```text
Message may be processed again.
```

This is at-least-once behavior.

At-least-once is the usual safe default, but it requires idempotency.

---

## Idempotent Consumers

Idempotency means processing the same event twice has the same business result as processing it once.

Without idempotency:

```text
PaymentCaptured event delivered twice
  -> ledger row inserted twice
  -> customer balance wrong
```

With idempotency:

```sql
BEGIN;

INSERT INTO processed_events(event_id)
VALUES ('evt_123')
ON CONFLICT DO NOTHING;

-- Only apply business effect if this event_id was newly inserted.

COMMIT;
```

For external systems:

```text
Payment provider:
  use provider idempotency key

Email provider:
  store notification_sent(order_id, template)

Webhook delivery:
  include event_id and retry safely
```

Rule:

```text
Duplicates are normal. Damage is a design bug.
```

---

## Delivery Semantics

```text
AT-MOST-ONCE
  May lose messages.
  Usually commit before processing.
  Useful only for loss-tolerant telemetry.

AT-LEAST-ONCE
  Should not lose messages.
  May process duplicates.
  Requires idempotent consumers.

EFFECTIVELY-ONCE
  Infrastructure may redeliver, but business state changes once.
  Achieved with idempotency, uniqueness, and transactions.

EXACTLY-ONCE
  Scoped guarantee, often within Kafka read-process-write pipelines.
  Does not automatically cover external side effects.
```

Good interview sentence:

```text
Kafka exactly-once is scoped. For external side effects, I design for at-least-once delivery with idempotent handlers and reconciliation.
```

---

## Partition Keys: Where Kafka Designs Win or Die

Partition key decides which partition a record lands in.

Usually:

```text
partition = hash(key) % partition_count
```

If key is `order_id`:

```text
OrderPlaced(order_123)
PaymentCaptured(order_123)
OrderShipped(order_123)
```

All events for order_123 land on the same partition.

```text
Partition 8
+-------------+-----------------+--------------+
| OrderPlaced | PaymentCaptured | OrderShipped |
+-------------+-----------------+--------------+
```

That preserves order lifecycle.

### Bad key: product_id during launch

```text
key = product_id
product_id = SNKR-2026
traffic = 180,000 events/sec
```

Result:

```text
Partition 0:   3K/sec
Partition 1:   2K/sec
Partition 2: 180K/sec  <-- hot partition
Partition 3:   4K/sec
```

Adding consumers does not fix this because one partition has one active owner in a group.

### Bucketed key

If strict product-level ordering is not required:

```text
key = product_id + ':' + hash(order_id) % 32
```

This spreads load:

```text
SNKR-2026:00 -> partition A
SNKR-2026:01 -> partition B
SNKR-2026:02 -> partition C
```

But it sacrifices total order for the product.

Correct rule:

```text
Pick the smallest entity that truly requires ordering.
```

Examples:

```text
Order lifecycle:
  key by order_id

Customer notification stream:
  key by customer_id

Payment ledger for account:
  key by account_id

Analytics events:
  key by random/bucketed ID if ordering is not required
```

---

## Consumer Lag

Consumer lag is the distance between the newest record and the consumer group's committed offset.

```text
Log end offset:       1,000,000
Committed offset:       850,000
Lag:                   150,000 records
```

Lag growth math:

```text
Producer rate:   50,000 records/sec
Consumer rate:   35,000 records/sec
Lag growth:      15,000 records/sec

After 10 minutes:
  15,000 * 600 = 9,000,000 records behind
```

Catch-up math if producers stop:

```text
Lag:             9,000,000 records
Consumer rate:      35,000 records/sec
Catch-up time:          257 sec
```

But if producers keep writing faster than consumers process:

```text
No catch-up. Lag grows forever.
```

Lag patterns:

```text
ALL PARTITIONS LAG:
  consumer fleet too small
  downstream dependency slow
  bad consumer deploy
  broker/network issue

ONE PARTITION LAGS:
  hot key
  poison message
  skewed partition assignment

SAWTOOTH LAG:
  rebalances
  GC pauses
  batch jobs
  scheduled downstream throttling
```

Total lag hides disasters. Always inspect lag by partition.

---

## Rebalancing

A rebalance changes which consumer owns which partitions.

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

Rebalances are normal. Rebalance storms are not.

Common causes:

```text
consumer crash
rolling deploy
autoscaler flapping
long GC pause
network pause
consumer processing exceeds max.poll.interval.ms
```

Failure loop:

```text
slow processing
  -> consumer misses poll interval
  -> group marks consumer dead
  -> rebalance starts
  -> partitions pause
  -> lag grows
  -> new consumer gets same slow work
```

Mitigations:

```text
static membership
cooperative rebalancing
bounded processing time
separate poll loop from long work
pause/resume partitions under backpressure
deploy in small waves
avoid autoscaler flapping
```

---

## Kafka Retention and Compaction

Kafka records are removed by retention policy, not by consumer acknowledgement.

Time-based retention:

```text
Keep records for 7 days.
```

Size-based retention:

```text
Keep records until topic reaches configured size.
```

Danger:

```text
retention:       24 hours
consumer outage: 36 hours
missing replay:  12 hours
```

Lag age matters more than raw lag.

```text
Consumer is 5M records behind at 200K/sec topic rate:
  25 seconds behind

Consumer is 5M records behind at 100/sec topic rate:
  13.9 hours behind
```

### Log compaction

Compaction keeps the latest value per key eventually.

```text
key=user_1 value=A
key=user_1 value=B
key=user_1 value=C

After compaction:
key=user_1 value=C
```

Good for:

```text
latest user profile
feature flag state
account settings
configuration topics
```

Bad for:

```text
audit log where every historical change matters
payment ledger history
legal event trail
```

Compaction is not immediate deletion and not a substitute for audit storage.

---

## Kafka vs RabbitMQ vs SQS vs Redis Streams

```text
+-------------+----------------------+---------------------------+
| System      | Best at              | Watch out for             |
+-------------+----------------------+---------------------------+
| SQS         | simple managed jobs  | limited replay semantics  |
| RabbitMQ    | routing/work queues  | huge backlogs hurt broker |
| Kafka       | durable event log    | partition/key complexity  |
| Redis Stream| lightweight streams  | memory/persistence limits |
| NATS        | low latency messaging| durability varies by mode |
+-------------+----------------------+---------------------------+
```

Use SQS when:

```text
one job, one worker
managed simplicity matters
DLQ and visibility timeout are enough
```

Use RabbitMQ when:

```text
routing patterns are rich
per-service queues matter
work queue semantics dominate
```

Use Kafka when:

```text
replay matters
many independent consumers need history
high throughput event streams exist
CDC/event backbone is needed
partition-level ordering matters
```

Use Redis Streams when:

```text
small to medium stream workload
Redis is already operationally accepted
retention needs are modest
```

---

## Kafka's Strengths

```text
1. HIGH THROUGHPUT
   -> Sequential disk writes and batching
   -> Excellent for large event streams

2. REPLAY
   -> Consumers can rebuild read models
   -> Bugs can be fixed and history reprocessed

3. INDEPENDENT CONSUMERS
   -> Fraud, search, email, analytics each track their own offsets

4. PARTITION-LEVEL ORDERING
   -> Correct order for an aggregate if key is chosen well

5. DURABILITY
   -> Replication across brokers
   -> Configurable producer acknowledgements

6. ECOSYSTEM
   -> Kafka Connect, Debezium, Schema Registry, Streams, Flink, ksqlDB
```

---

## Kafka's Problems

```text
PROBLEM 1: PARTITION KEY MISTAKES ARE EXPENSIVE

  Wrong key creates hot partitions or broken ordering.
  Fixing it later usually means new topics, migration, or repartitioning.

PROBLEM 2: CONSUMER LAG IS HIDDEN BUSINESS DELAY

  API may return 200 OK while search, email, fraud, or inventory projections are stale.

PROBLEM 3: EXACTLY-ONCE IS MISUNDERSTOOD

  External side effects still need idempotency and reconciliation.

PROBLEM 4: SCHEMA EVOLUTION CAN BREAK CONSUMERS

  Removing fields or changing meaning can stop consumers hours after producer deploy.

PROBLEM 5: REBALANCE STORMS

  Bad deploys, GC pauses, or autoscaling can cause repeated rebalances and lag growth.

PROBLEM 6: OPERATIONAL WEIGHT

  Brokers, partitions, ISR, disk, controller, quotas, retention, connectors, schemas,
  consumer groups, and ACLs all need operational maturity.
```

---

## Production Failure Patterns

### Failure 1: Poison Message Blocks a Partition

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
same offset appears in logs repeatedly
one partition lag grows
consumer restarts or retries forever
other partitions are healthy
```

Immediate mitigation:

```text
1. Capture original topic, partition, offset, key, headers, payload, error.
2. Move record to DLQ or quarantine store.
3. Advance only with audit trail.
4. Keep later processing only if ordering rules allow it.
```

Dangerous move:

```text
Skipping offsets silently. That creates invisible data loss.
```

---

### Failure 2: Downstream Bottleneck Looks Like Kafka Lag

```text
+-------+      +----------+      +------------+
| Kafka | ---> | Consumer | ---> | OpenSearch |
+-------+      +----------+      +------------+
                                  slow writes
```

Symptoms:

```text
consumer lag rising
consumer CPU not saturated
OpenSearch indexing queue high
bulk rejections rising
read model stale
```

Mitigation:

```text
1. Do not blame Kafka first.
2. Check downstream p95/p99 and rejection rate.
3. Pause non-critical consumers if they share downstream capacity.
4. Reduce batch size if downstream is choking.
5. Add backpressure and controlled catch-up.
```

---

### Failure 3: Hot Partition During Launch

```text
key = product_id
product_id = SNKR-2026
```

Symptoms:

```text
one partition has huge lag
one consumer is hot
other consumers idle
adding consumers does not help
```

Mitigation:

```text
1. Stop autoscaling churn.
2. Confirm partition-level lag skew.
3. Roll back producer key if possible.
4. Route new events to corrected topic if needed.
5. Protect critical consumers before analytics/search.
```

---

### Failure 4: Retention Deletes Needed Data

```text
retention:       24 hours
consumer outage: 36 hours
```

Result:

```text
consumer cannot replay 12 hours of records
```

Mitigation:

```text
set retention from recovery objective
alert on lag age approaching retention
snapshot read models
keep authoritative data outside Kafka when required
```

---

### Failure 5: Schema Change Breaks Consumers

Symptoms:

```text
producer deploy succeeds
consumer deserialization errors spike
DLQ fills with same schema version
lag rises across all partitions
```

Mitigation:

```text
schema registry compatibility checks
additive changes first
consumer contract tests
no field-number reuse in protobuf
no semantic change under same field name
```

---

## SRE Diagnostic Toolkit

Topic description:

```bash
kafka-topics --bootstrap-server broker:9092 \
  --describe --topic orders
```

Consumer group lag:

```bash
kafka-consumer-groups --bootstrap-server broker:9092 \
  --describe --group search-indexer
```

Look at:

```text
TOPIC
PARTITION
CURRENT-OFFSET
LOG-END-OFFSET
LAG
CONSUMER-ID
HOST
```

Broker health signals:

```text
under-replicated partitions
offline partitions
ISR shrink rate
produce request latency
fetch request latency
broker disk usage
controller changes
request handler idle percent
```

Consumer health signals:

```text
lag by partition
lag age
processing latency
poll interval
rebalance count
DLQ rate
retry count
downstream latency
```

Producer health signals:

```text
record send rate
record error rate
record retry rate
request latency
batch size
compression rate
buffer available bytes
```

Golden question during incidents:

```text
Is Kafka the bottleneck, or is Kafka showing that something downstream is slow?
```

---

## Decision Framework

```text
+-------------------------------+------------------------------+
| Requirement                   | Recommended direction        |
+-------------------------------+------------------------------+
| user needs immediate result   | synchronous RPC              |
| one background job            | task queue                   |
| many subscribers need event   | pub/sub                      |
| replay history matters        | Kafka-style durable log      |
| ordered events per entity     | Kafka with correct key       |
| simple managed retry jobs     | SQS                          |
| rich routing and work queues  | RabbitMQ                     |
| CDC backbone                  | Kafka + Debezium             |
| low-value lossy telemetry     | relaxed acks / telemetry bus |
+-------------------------------+------------------------------+
```

Ask before choosing Kafka:

```text
Do we need replay?
Do multiple independent consumers need the same stream?
What is the ordering key?
What lag is acceptable?
What is retention based on?
Can consumers handle duplicates?
How will schemas evolve?
Who operates broker health, lag, DLQs, and replay?
```

If those questions are not answered, Kafka will answer them during a P1, wearing iron boots.

---

## Real-World Architecture Example

E-commerce order pipeline:

```text
+--------+      +----------+      +----------+
| Client | ---> | Checkout | ---> | OrdersDB |
+--------+      +----------+      +----------+
                      |
                      | outbox / CDC
                      v
                  +--------+
                  | Kafka  |
                  +--------+
                    |   |   |
                    |   |   +----------------+
                    |   |                    v
                    |   |              +-----------+
                    |   |              | Analytics |
                    |   |              +-----------+
                    |   |
                    |   +--------------------+
                    |                        v
                    |                  +------------+
                    |                  | Search     |
                    |                  +------------+
                    |
                    +----------------------+
                                           v
                                     +-----------+
                                     | Email     |
                                     +-----------+
```

Correct critical path:

```text
checkout must verify:
  payment decision
  inventory reservation
  order write

checkout should not wait for:
  email
  analytics
  search indexing
  recommendations
```

But async does not mean unimportant.

```text
Email lag affects customer trust.
Search lag affects support and discovery.
Fraud lag may affect risk.
Analytics lag affects business visibility.
```

Each consumer needs a freshness SLO.

---

# SRE Troubleshooting Scenario: Kafka Launch Meltdown

```text
INCIDENT REPORT
Severity: P1
Service: E-commerce checkout and order pipeline
Event: Celebrity sneaker launch

ARCHITECTURE:

  Checkout API -> OrdersDB -> Outbox CDC -> Kafka topic: order-events
                                          -> fraud-service
                                          -> inventory-projector
                                          -> search-indexer
                                          -> email-sender

TOPIC:
  order-events
  partitions: 48
  replication factor: 3
  min.insync.replicas: 2

BASELINE:
  produce rate:              8,000 records/sec
  fraud lag:                 < 5,000 records
  inventory lag:             < 2,000 records
  search lag:                < 50,000 records
  email lag:                 < 10,000 records
  rebalance rate:            near zero
  DLQ rate:                  near zero

CURRENT:
  produce rate:              55,000 records/sec
  fraud lag:                 80,000 records stable
  inventory lag:             9,200,000 records growing
  search lag:                31,000,000 records growing
  email lag:                 4,800,000 records growing
  rebalance rate:            140/hour
  DLQ rate:                  low

PARTITION LAG SAMPLE:
  partition 03:       18,000
  partition 04:       21,000
  partition 05:    8,900,000  <-- bad
  partition 06:       19,000
  partition 07:       17,000

RECENT CHANGES:
  1. Producer key changed from order_id to product_id.
  2. Launch product_id is SNKR-2026.
  3. Consumers autoscaled from 24 to 96.
  4. Search indexer writes one document at a time to OpenSearch.
  5. Email sender retries immediately on provider timeout.
```

## Question 1: What is the root cause?

Root cause:

```text
The producer partition key changed from order_id to product_id. During a launch,
most events have the same product_id, so they hash to one hot partition. One
partition can have only one active consumer per group, so inventory lag grows
on that partition even though many consumers exist.
```

The bad key turned horizontal parallelism into a single-lane bridge.

## Question 2: Why did autoscaling consumers not fix it?

```text
Topic partitions: 48
Consumers:        96
Useful consumers per group for this topic: at most 48
Hot partition owner: exactly 1
```

More consumers cannot split one partition. Autoscaling may increase rebalances,
which pauses partition processing and worsens lag.

## Question 3: Why is search lag worse than inventory lag?

Search has two likely bottlenecks:

```text
1. It shares the same hot-partition problem for launch events.
2. It writes one document at a time to OpenSearch.
```

OpenSearch may be the real downstream bottleneck.

Check:

```bash
curl -s localhost:9200/_cat/thread_pool/write?v
curl -s localhost:9200/_cluster/health?pretty
curl -s localhost:9200/_cat/shards?v
```

## Question 4: What do you do right now?

Immediate mitigation:

```text
1. Stop autoscaling churn.
2. Confirm partition-level lag and hot key.
3. Roll back producer key to order_id if compatible.
4. If rollback cannot safely mix streams, create corrected topic and cut over new events.
5. Prioritize inventory and fraud over search and analytics.
6. Slow or pause search indexing if it competes with critical consumers.
7. Add email retry backoff with jitter to stop provider hammering.
8. Preserve all records; do not skip offsets without audit.
```

## Question 5: What should not be done?

```text
Do not:
  - delete topic data to reduce lag
  - skip offsets silently
  - keep scaling consumers blindly
  - increase partitions during P1 without migration plan
  - route stale inventory projection into checkout correctness
  - run full-speed OpenSearch backfill while cluster is rejecting writes
```

## Question 6: Long-term fix

```text
Partition key contract:
  key order lifecycle events by order_id

Hot-key testing:
  simulate launch product skew before release

Consumer priority:
  fraud and inventory get protected capacity

Search indexing:
  use bulk writes, backpressure, and freshness SLO

Email retry:
  bounded retries, exponential backoff, jitter, idempotent sent markers

Monitoring:
  lag by partition, lag age, rebalance rate, DLQ rate, downstream write p99
```

---

## Key Takeaways

```text
1. A queue assigns work; Kafka stores an ordered, replayable log.
2. Kafka ordering is per partition, not global.
3. Partition key choice is correctness and capacity design.
4. Consumer lag is business delay.
5. Total lag hides hot partitions.
6. At-least-once delivery requires idempotent consumers.
7. Exactly-once is scoped and does not magically cover external side effects.
8. DLQs are evidence lockers, not trash cans.
9. Retention must exceed realistic recovery time.
10. Kafka is justified when replay, fanout, throughput, and ordering are worth the operational cost.
```

---

## Gap Fill: Message Queues and Kafka

```text
1. A task queue is best when ______ job should be handled by ______ worker.
2. Kafka is best described as a distributed, replicated, partitioned ______.
3. Kafka preserves order within a ______, not across an entire topic.
4. Consumer lag equals ______ minus ______.
5. A hot partition often means the producer chose a bad ______.
6. At-least-once delivery requires consumers to be ______.
7. A DLQ should preserve original topic, partition, offset, key, headers, payload, and ______.
8. Log compaction keeps the latest value per ______ eventually.
9. If a consumer outage exceeds topic retention, the consumer may be unable to ______.
10. Kafka exactly-once does not automatically make external side effects happen ______.
```

Answers:

```text
1. one, one
2. commit log
3. partition
4. log-end offset, committed offset
5. partition key
6. idempotent
7. error
8. key
9. replay
10. exactly once
```
