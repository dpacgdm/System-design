# Week 6, Topic 1: Message Queues and Kafka

Last verified: 2026-05-15

---

## Message Queues: What They Actually Are

A message queue is not "a database table with extra steps."  
Kafka is not "RabbitMQ but bigger."  
SQS is not "Kafka without brokers."  
Redis Streams is not "free Kafka because Redis is already running."

These systems all move messages, but they solve different problems.

A synchronous call says:

```text
Do this now. I am waiting.
```

A queued message says:

```text
Do this work later. Someone else can pick it up.
```

An event says:

```text
This business fact happened. Other systems may react.
```

A durable log says:

```text
This history is important. Consumers can replay it at their own pace.
```

That distinction matters. If you confuse them, you will design a system that
passes the interview whiteboard and fails the first launch event.

---

## Why Messaging Exists

Imagine checkout without messaging:

```text
Client
  |
  v
Checkout API
  |
  +--> Orders DB
  +--> Payment Provider
  +--> Inventory Service
  +--> Email Service
  +--> Search Index
  +--> Analytics Pipeline
  +--> Warehouse System
  |
  v
Response to user
```

If email is slow, checkout is slow.  
If analytics is down, checkout may fail.  
If search indexing has a bad deploy, users cannot buy shoes. That is architectural comedy with a pager attached.

With messaging:

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
                   |  |  +--> Analytics
                   |  +-----> Search Indexer
                   +--------> Email Sender
```

The checkout path keeps only the work that must be immediately correct. Optional or delayed work moves behind an asynchronous boundary.

This buys:

```text
1. DECOUPLING
   Checkout does not need email/search/analytics to be healthy.

2. BUFFERING
   Spikes can queue instead of instantly crushing consumers.

3. RETRY
   Failed work can be retried without user involvement.

4. FANOUT
   Many consumers can react to one business fact.

5. REPLAY
   Some systems can rebuild state from retained history.
```

But you pay with:

```text
1. DUPLICATES
   Most real systems deliver at least once.

2. LAG
   Async work may be minutes behind.

3. ORDERING LIMITS
   Ordering is usually scoped, not global.

4. REPLAY RISK
   Replaying old messages can repeat side effects.

5. DEBUGGING COMPLEXITY
   The user request is over, but the workflow is still running.

6. OPERATIONAL STATE
   Queues, offsets, DLQs, retention, lag, consumers, schemas, and brokers all need care.
```

Messaging is not a free lunch. It is a lunch that arrives later, sometimes twice, occasionally poisoned, and you still need to tip the broker.

---

## The Three Messaging Models People Confuse

```text
1. Task Queue
2. Publish/Subscribe
3. Durable Event Log
```

They look similar from far away. Up close, they behave very differently.

---

## 1. Task Queue: One Job, One Worker

A task queue distributes work.

```text
One job should be handled by one worker.
```

Examples:

```text
SendReceiptEmail(order_id=123)
ResizeImage(image_id=abc)
ProcessCsvImport(import_id=999)
RetryWebhookDelivery(webhook_id=555)
GenerateMonthlyInvoice(customer_id=42)
```

Basic shape:

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

### How a task queue works in practice

```text
1. Producer enqueues job.
2. Queue stores job durably or semi-durably.
3. Worker receives job.
4. Queue hides job from other workers for a timeout window.
5. Worker processes job.
6. Worker acknowledges success.
7. Queue deletes or marks job complete.
```

If worker dies before acknowledgement:

```text
1. Worker receives job.
2. Worker crashes.
3. Visibility timeout expires.
4. Queue makes job visible again.
5. Another worker receives the same job.
```

This is why workers must be idempotent.

### SQS-style example

```text
Queue: email-jobs
Visibility timeout: 60 seconds
Max receive count: 5
DLQ: email-jobs-dlq
```

Job body:

```json
{
  "job_id": "job_123",
  "type": "SendReceiptEmail",
  "order_id": "ord_456",
  "customer_id": "cust_789",
  "template": "receipt_v3",
  "idempotency_key": "receipt:ord_456:receipt_v3"
}
```

Worker logic:

```text
receive message
check idempotency key
send email if not already sent
record sent marker
ack/delete message
```

If the worker sends email and crashes before ack, the queue redelivers. Without the sent marker, the customer receives duplicate receipts.

### Task queue strengths

```text
1. SIMPLE WORK DISTRIBUTION
   One job goes to one worker.

2. NATURAL RETRY MODEL
   Failed jobs can be retried with backoff.

3. DLQ SUPPORT
   Poison jobs can be isolated after bounded attempts.

4. WORKER AUTOSCALING
   Queue depth can drive worker count.

5. LOW CONCEPTUAL OVERHEAD
   Good for background jobs.
```

### Task queue problems

```text
PROBLEM 1: DUPLICATES

  Worker may perform side effect and crash before ack.
  Queue redelivers.
  Side effect repeats unless worker is idempotent.

PROBLEM 2: POISON JOBS

  One bad job fails forever.
  Without max receive count, it loops forever.

PROBLEM 3: RETRY STORMS

  Downstream email provider fails.
  Thousands of workers retry immediately.
  Provider gets hammered while already broken.

PROBLEM 4: INVISIBLE BACKLOG AGE

  Queue length alone is not enough.
  10,000 jobs might be fine at 50,000 jobs/sec.
  10,000 jobs might be terrible at 5 jobs/sec.

PROBLEM 5: PRIORITY INVERSION

  Low-value jobs can sit ahead of urgent jobs unless queues are separated.
```

---

## 2. Publish/Subscribe: One Event, Many Subscribers

Pub/sub fans out messages.

```text
One published message may be consumed by many subscribers.
```

Example:

```text
OrderPlaced
  -> Email service sends receipt
  -> Search service indexes order
  -> Analytics records purchase
  -> Fraud service updates risk profile
  -> Warehouse prepares fulfillment
```

Shape:

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
                      |           | Fraud    |
                      |           +----------+
                      |
                      +------->   +----------+
                                  | Analytics|
                                  +----------+
```

### Pub/sub strengths

```text
1. FANOUT
   Add new consumers without changing publisher logic.

2. FAILURE ISOLATION
   Slow analytics should not block email.

3. TEAM AUTONOMY
   Teams can own their own subscriptions.

4. EVENT-DRIVEN EXTENSIBILITY
   New workflows can react to existing facts.
```

### Pub/sub problems

```text
PROBLEM 1: HIDDEN COUPLING

  Consumers depend on event fields and meanings.
  Producer changes schema and breaks consumers.

PROBLEM 2: UNKNOWN BLAST RADIUS

  One event may trigger 20 systems.
  A harmless change becomes a warehouse incident.

PROBLEM 3: ORDERING IS NOT AUTOMATIC

  PaymentCaptured may arrive before OrderPlaced if design is careless.

PROBLEM 4: CONSUMER LAG IS BUSINESS LAG

  Email, search, fraud, or inventory projection can be stale while API is green.
```

---

## 3. Durable Event Log: Replayable History

A durable log stores ordered records for a retention period. Consumers track where they are.

Kafka belongs in this category.

```text
Topic: order-events

+-------------+-----------------+--------------+---------+-----------+
| OrderPlaced | PaymentCaptured | ItemPacked   | Shipped | Delivered |
+-------------+-----------------+--------------+---------+-----------+
      0               1                2            3          4
```

Different consumers have different offsets:

```text
fraud-service:        offset 4
search-indexer:       offset 2
analytics-pipeline:   offset 0
```

The log does not remove a record because one consumer read it. The record remains until retention or compaction removes it.

### Durable log strengths

```text
1. REPLAY
   Rebuild search, analytics, projections, and derived state.

2. INDEPENDENT CONSUMER GROUPS
   Each consumer tracks its own progress.

3. HIGH THROUGHPUT
   Append-only writes and sequential reads are efficient.

4. ORDERING PER PARTITION
   Correct key choice gives ordered event streams per entity.

5. CDC BACKBONE
   Database changes can flow into many downstream systems.
```

### Durable log problems

```text
PROBLEM 1: RETENTION LIMITS

  If consumers are down longer than retention, replay data disappears.

PROBLEM 2: REPLAY DAMAGE

  Replaying events can resend emails, webhooks, shipments, or payments if consumers are unsafe.

PROBLEM 3: PARTITION KEY MISTAKES

  Bad key creates hot partitions or breaks ordering.

PROBLEM 4: OFFSET CONFUSION

  Committed offset does not necessarily mean business side effect succeeded.
```

---

## Kafka: The Core Idea

Kafka is a distributed, replicated, partitioned commit log.

```text
DISTRIBUTED
  Data spread across brokers.

REPLICATED
  Data copied for durability and availability.

PARTITIONED
  Each topic split into ordered shards.

COMMIT LOG
  Records appended and read by offset.
```

Kafka is optimized for:

```text
high-throughput writes
high-throughput reads
replayable streams
many independent consumers
partition-level ordering
```

Kafka is not optimized for:

```text
arbitrary per-message priority
simple one-off background jobs
global ordering across all records
deleting each message after one consumer reads it
human-friendly debugging without tooling
```

---

## Kafka Vocabulary

```text
BROKER
  Kafka server.

CLUSTER
  Group of brokers.

TOPIC
  Named stream of records.

PARTITION
  Ordered shard of a topic.

OFFSET
  Position of a record inside one partition.

PRODUCER
  Client that writes records.

CONSUMER
  Client that reads records.

CONSUMER GROUP
  Set of consumers sharing partitions for a workload.

LEADER
  Broker handling reads/writes for a partition.

FOLLOWER
  Broker replicating from leader.

ISR
  In-sync replicas. Replicas caught up enough to be eligible for durability.

RETENTION
  Rule for how long records stay.

COMPACTION
  Keeps latest value per key eventually.
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

Ordering guarantee:

```text
Kafka preserves order within a partition.
Kafka does not preserve total order across a topic.
```

This is not a footnote. It is the soul contract.

---

## Kafka Record Anatomy

A Kafka record is not just a payload.

```text
record
  topic:      order-events
  partition: 7
  offset:    8819231
  key:       order_123
  value:     serialized event payload
  headers:   metadata
  timestamp: broker or producer timestamp
```

Production event payload:

```json
{
  "event_id": "evt_01HY...",
  "event_type": "OrderPlaced",
  "schema_version": 3,
  "aggregate_type": "Order",
  "aggregate_id": "order_123",
  "occurred_at": "2026-05-15T10:15:30Z",
  "published_at": "2026-05-15T10:15:31Z",
  "correlation_id": "req_abc",
  "causation_id": "cmd_create_order_123",
  "producer": "checkout-service",
  "payload": {
    "order_id": "order_123",
    "customer_id": "customer_9",
    "total_cents": 129900,
    "currency": "USD"
  }
}
```

Why the metadata matters:

```text
event_id
  dedupe and audit

aggregate_id
  partition key and ordering

schema_version
  compatibility

occurred_at
  when the business fact happened

published_at
  event pipeline delay

correlation_id
  trace one user workflow

causation_id
  why this event exists
```

Without these fields, incident debugging becomes folklore with grep.

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

Detailed flow:

```text
1. Producer serializes record.
2. Producer chooses topic.
3. Producer chooses partition.
4. Producer batches records.
5. Producer sends batch to partition leader.
6. Leader appends batch to local log.
7. Followers replicate from leader.
8. Producer receives acknowledgement based on config.
```

### Producer partition choice

If a key exists:

```text
partition = hash(key) % partition_count
```

If no key exists:

```text
producer may distribute records using sticky or round-robin behavior
```

No key means no per-entity ordering guarantee.

---

## Producer Configuration: What Actually Matters

Example producer settings for important business events:

```properties
acks=all
enable.idempotence=true
retries=2147483647
max.in.flight.requests.per.connection=5
compression.type=lz4
linger.ms=10
batch.size=65536
delivery.timeout.ms=120000
request.timeout.ms=30000
```

What these mean:

```text
acks=all
  Wait for in-sync replica requirement before success.

enable.idempotence=true
  Prevent duplicate sequence writes from producer retries.

retries
  Retry transient broker errors.

max.in.flight.requests.per.connection
  Controls concurrent unacknowledged requests per connection.

compression.type
  Reduces network and disk usage. lz4/snappy/zstd are common.

linger.ms
  Wait briefly to form larger batches.

batch.size
  Target batch size per partition.

delivery.timeout.ms
  Total time producer will try before failing send.
```

Tradeoff:

```text
Low latency wants small linger and small batches.
High throughput wants batching and compression.
Durability wants acks=all and enough ISR.
```

---

## Producer Acknowledgements

### acks=0

```text
Producer -> Broker
Producer does not wait.
```

Result:

```text
fastest
can silently lose records
```

Use only for loss-tolerant telemetry.

### acks=1

```text
Producer -> Leader append -> Ack
```

Risk:

```text
Leader accepts record.
Leader dies before followers replicate.
New leader does not have record.
Record is lost.
```

### acks=all

```text
Producer -> Leader append
         -> Followers in ISR replicate
         -> Ack after durability condition
```

Safer baseline:

```text
replication.factor=3
min.insync.replicas=2
acks=all
```

Meaning:

```text
There are three copies when healthy.
At least two in-sync replicas must acknowledge for a successful write.
```

If ISR falls below minimum:

```text
write fails
```

That is unpleasant, but honest. Silent data loss is worse.

---

## Kafka Replication and ISR

Partition with replication factor 3:

```text
Partition 7

+----------+      +------------+
| Broker 1 | ---> | Leader     |
+----------+      +------------+

+----------+      +------------+
| Broker 2 | ---> | Follower   |
+----------+      +------------+

+----------+      +------------+
| Broker 3 | ---> | Follower   |
+----------+      +------------+
```

ISR means in-sync replicas.

```text
ISR = replicas close enough to the leader to be considered safe
```

Healthy:

```text
leader: broker 1
ISR:    broker 1, broker 2, broker 3
```

Follower lagging:

```text
leader: broker 1
ISR:    broker 1, broker 2
broker 3 removed from ISR
```

With:

```text
replication.factor=3
min.insync.replicas=2
acks=all
```

Writes can continue while two replicas are in sync. If ISR drops to one, writes fail.

SRE meaning:

```text
ISR shrink rate is a durability warning.
Under-replicated partitions are not cosmetic.
Offline partitions are a user-impacting emergency.
```

---

## How Kafka Reads Work

Consumer group assignment:

```text
Topic: orders, 6 partitions
Consumer group: search-indexer

Partition 0 -> Consumer A
Partition 1 -> Consumer A
Partition 2 -> Consumer B
Partition 3 -> Consumer B
Partition 4 -> Consumer C
Partition 5 -> Consumer C
```

Important rule:

```text
Within one consumer group, a partition is owned by at most one active consumer.
```

If there are 6 partitions and 10 consumers:

```text
6 active consumers
4 idle consumers
```

Adding consumers beyond partition count does not increase parallelism for that topic in that group.

Different consumer groups read independently:

```text
                 +---------------+
                 | order-events  |
                 +---------------+
                    |     |     |
                    v     v     v
                 fraud search analytics
                 group group  group
```

Each group has its own committed offsets.

---

## Consumer Configuration: What Actually Matters

Example consumer settings:

```properties
group.id=search-indexer
enable.auto.commit=false
auto.offset.reset=earliest
max.poll.records=500
max.poll.interval.ms=300000
session.timeout.ms=45000
heartbeat.interval.ms=15000
fetch.min.bytes=1048576
fetch.max.wait.ms=100
```

What these mean:

```text
group.id
  Identifies consumer group and offset namespace.

enable.auto.commit=false
  Application controls when offsets are committed.

auto.offset.reset=earliest
  Where to start if no committed offset exists.

max.poll.records
  Batch size returned to application.

max.poll.interval.ms
  Max time between polls before consumer is considered stuck.

session.timeout.ms
  How long broker waits before declaring consumer dead.

heartbeat.interval.ms
  Heartbeat frequency.

fetch.min.bytes / fetch.max.wait.ms
  Throughput vs latency tuning.
```

Bad default smell:

```text
enable.auto.commit=true for side-effecting consumers
```

Auto-commit can mark messages done before business work is safe.

---

## Offset Commit Semantics

Offset position:

```text
Partition 2

+-----+-----+-----+-----+-----+
| 100 | 101 | 102 | 103 | 104 |
+-----+-----+-----+-----+-----+
              ^
              |
          processing
```

### Commit before processing

```text
1. poll offset 102
2. commit offset 103
3. process record
4. crash before side effect
```

Result:

```text
Kafka thinks offset 102 is complete.
Business work may be missing.
```

This is at-most-once from the business perspective.

### Process before commit

```text
1. poll offset 102
2. process record
3. commit offset 103
4. crash before commit
```

Result:

```text
Kafka will redeliver offset 102.
Business work may happen twice unless idempotent.
```

This is at-least-once.

Most production systems choose at-least-once plus idempotency.

---

## Idempotent Consumer Pattern

Bad consumer:

```python
def handle(event):
    ledger.insert({
        "event_id": event.id,
        "account_id": event.account_id,
        "amount": event.amount
    })
```

If the event is delivered twice, ledger has duplicate rows.

Better consumer:

```sql
BEGIN;

INSERT INTO processed_events(event_id, processed_at)
VALUES ('evt_123', now())
ON CONFLICT DO NOTHING;

-- Only continue if the insert created a row.

INSERT INTO ledger_entries(event_id, account_id, amount_cents)
VALUES ('evt_123', 'acct_9', 5000);

COMMIT;
```

Even better:

```text
ledger_entries.event_id has a unique constraint
processed_events.event_id has a unique constraint
external provider receives an idempotency key
```

For email:

```text
unique key = order_id + template_name + recipient
```

For payment:

```text
unique key = payment_intent_id or business operation ID
```

For webhooks:

```text
unique key = event_id + destination_id
```

Rule:

```text
The consumer owns duplicate safety. The broker will not save you from bad side effects.
```

---

## Delivery Guarantees

```text
AT-MOST-ONCE

  May lose messages.
  Usually commits before processing.
  Useful for low-value metrics, never for payments/orders.

AT-LEAST-ONCE

  Does not intentionally lose messages.
  May process duplicates.
  Requires idempotent consumers.

EFFECTIVELY-ONCE

  Infrastructure may deliver duplicates,
  but business state changes once.
  Built with idempotency, unique constraints, and transactions.

EXACTLY-ONCE

  Scoped guarantee.
  Kafka transactions can coordinate Kafka reads, Kafka writes, and offsets.
  External side effects still need idempotency and reconciliation.
```

Interview-safe sentence:

```text
Kafka exactly-once is not magic business exactly-once. For external effects, I design for at-least-once delivery with idempotent handlers and reconciliation.
```

---

## Kafka Transactions: What They Do and Do Not Do

Kafka transactions help when a processor reads from Kafka and writes back to Kafka.

```text
Topic A -> Stream Processor -> Topic B
```

Transaction can include:

```text
consume records from Topic A
produce records to Topic B
commit offsets for Topic A
```

This avoids:

```text
output written but offset not committed
or offset committed but output missing
```

But this does not cover:

```text
Kafka -> consumer -> PostgreSQL
Kafka -> consumer -> Stripe
Kafka -> consumer -> Email provider
Kafka -> consumer -> Warehouse API
```

Those external systems need their own idempotency and reconciliation.

---

## Partition Keys: Where Kafka Designs Win or Die

Partition key controls ordering and load distribution.

Common formula:

```text
partition = hash(key) % partition_count
```

### Good key: order_id for order lifecycle

```text
OrderPlaced(order_123)
PaymentCaptured(order_123)
Packed(order_123)
Shipped(order_123)
```

All land on same partition:

```text
Partition 8
+-------------+-----------------+--------+---------+
| OrderPlaced | PaymentCaptured | Packed | Shipped |
+-------------+-----------------+--------+---------+
```

This preserves order lifecycle.

### Bad key: product_id during a launch

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
Partition 4:   3K/sec
```

Adding consumers does not fix this. One partition has one active consumer per group.

### Bucketed key

If total order for product is not required:

```text
key = product_id + ':' + hash(order_id) % 32
```

Result:

```text
SNKR-2026:00 -> partition A
SNKR-2026:01 -> partition B
SNKR-2026:02 -> partition C
...
```

Tradeoff:

```text
better distribution
no strict total ordering for product_id
```

Decision rule:

```text
Pick the smallest entity that truly needs ordering.
```

Examples:

```text
Order lifecycle:
  key = order_id

Customer notification ordering:
  key = customer_id

Account ledger:
  key = account_id

Analytics clickstream:
  key = random or session_id depending needs

Hot product launch metrics:
  key = product_id + bucket if exact product ordering is unnecessary
```

---

## Consumer Lag: The Metric Everyone Misreads

Consumer lag is:

```text
log end offset - committed offset
```

Example:

```text
Log end offset:       1,000,000
Committed offset:       850,000
Lag:                   150,000 records
```

Lag growth:

```text
Producer rate:   50,000 records/sec
Consumer rate:   35,000 records/sec
Lag growth:      15,000 records/sec

After 10 minutes:
  15,000 * 600 = 9,000,000 records behind
```

Catch-up if producers stop:

```text
Lag:             9,000,000 records
Consumer rate:      35,000 records/sec
Catch-up time:          257 seconds
```

Catch-up if producers continue:

```text
Producer rate: 50,000/sec
Consumer rate: 35,000/sec

No catch-up. Lag keeps growing.
```

### Lag count vs lag age

```text
5,000,000 records behind at 500,000/sec:
  10 seconds behind

5,000,000 records behind at 100/sec:
  13.9 hours behind
```

For users, lag age usually matters more than raw count.

### Lag patterns

```text
ALL PARTITIONS LAG
  consumer fleet too small
  downstream dependency slow
  bad deploy
  broker/network issue

ONE PARTITION LAGS
  hot key
  poison message
  skewed partition assignment

SAWTOOTH LAG
  rebalances
  GC pauses
  scheduled batch jobs
  downstream throttling windows
```

Never rely only on total lag. Total lag can hide one burning partition under a blanket of averages.

---

## Rebalancing

A rebalance changes partition ownership in a consumer group.

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

Common rebalance triggers:

```text
consumer crash
rolling deploy
autoscaler flapping
long GC pause
network pause
consumer processing exceeds max.poll.interval.ms
```

Bad loop:

```text
slow processing
  -> consumer misses poll interval
  -> group marks consumer dead
  -> rebalance starts
  -> partitions pause
  -> lag grows
  -> new consumer gets same slow work
```

Mitigation patterns:

```text
static membership
cooperative rebalancing
bounded processing time
pause/resume partitions under downstream pressure
deploy in small waves
avoid autoscaler flapping
separate poll loop from long processing
```

SRE smell:

```text
Lag spikes during every deploy.
```

That means deployment is not just deployment. It is a consumption outage.

---

## Retention and Compaction

Kafka records are removed by retention, not by acknowledgement.

Time retention:

```properties
retention.ms=604800000
```

Seven days.

Size retention:

```properties
retention.bytes=107374182400
```

Keep roughly 100 GB per partition or topic depending configuration context.

Danger:

```text
retention:       24 hours
consumer outage: 36 hours
missing replay:  12 hours
```

The consumer cannot replay what Kafka has already deleted.

### Log compaction

Compaction keeps the latest value per key eventually.

```text
key=user_1 value=A
key=user_1 value=B
key=user_1 value=C
```

After compaction:

```text
key=user_1 value=C
```

Good uses:

```text
latest user profile
feature flag state
account settings
service configuration
```

Bad uses:

```text
payment ledger audit trail
security event history
legal compliance history
full order event history
```

Compaction is not immediate. It is not a deletion guarantee. It is not an audit log.

---

## Schema Evolution

Kafka moves bytes. Your organization must govern meaning.

Common formats:

```text
JSON
  human-readable, loose, larger, runtime errors common

Avro
  compact, schema registry friendly, common in Kafka ecosystems

Protobuf
  compact, strongly typed, field numbers matter

JSON Schema
  readable with schema validation
```

Breaking changes:

```text
remove required field
rename field without compatibility layer
change type from string to int
change field meaning under same name
reuse protobuf field number
change enum semantics without old consumer support
```

Safe evolution:

```text
add optional field
write new field while still writing old field
deploy consumers that understand both
backfill if needed
stop using old field
remove only after retention and compatibility window
```

Protobuf warning:

```proto
message OrderPlaced {
  string order_id = 1;
  int64 total_cents = 2;
  string currency = 3;

  reserved 4;
  reserved "old_field_name";
}
```

Never reuse field numbers. That is how old bytes become new lies.

---

## Kafka Connect, CDC, and Outbox

Kafka often becomes the backbone for database change streams.

Naive dual write:

```text
1. Write order to PostgreSQL.
2. Publish OrderPlaced to Kafka.
```

Failure:

```text
DB commit succeeds, Kafka publish fails.
Order exists, event missing.
```

Outbox pattern:

```text
+----------+        same DB transaction        +---------------+
| orders   | <-------------------------------> | outbox_events |
+----------+                                   +---------------+
                                                     |
                                                     | CDC connector
                                                     v
                                                 +-------+
                                                 | Kafka |
                                                 +-------+
```

CDC connector such as Debezium reads committed changes and publishes events.

Operational traps:

```text
connector lag means event lag
replication slot can retain WAL and fill disk
schema changes can break connector
snapshotting can overload primary
downstream consumers still need idempotency
```

---

## Kafka vs SQS vs RabbitMQ vs Redis Streams vs NATS

```text
+--------------+-------------------------+---------------------------+
| System       | Best at                 | Watch out for             |
+--------------+-------------------------+---------------------------+
| SQS          | managed task queues     | limited replay/log model  |
| RabbitMQ     | routing, work queues    | huge backlogs hurt broker |
| Kafka        | durable event streams   | partition/key complexity  |
| Redis Streams| lightweight streams     | memory/persistence limits |
| NATS         | low-latency messaging   | durability depends mode   |
| Kinesis      | managed shard stream    | shard throughput limits   |
+--------------+-------------------------+---------------------------+
```

Use SQS when:

```text
one job should go to one worker
managed simplicity matters
visibility timeout and DLQ are enough
```

Use RabbitMQ when:

```text
routing rules matter
per-service queues are natural
work queue semantics dominate
```

Use Kafka when:

```text
replay matters
many independent consumers need the same history
high throughput stream exists
partition-level ordering matters
CDC/event backbone is needed
```

Use Redis Streams when:

```text
workload is modest
Redis is already operationally accepted
retention needs are limited
```

Use NATS when:

```text
low-latency messaging matters
subjects and request/reply are useful
persistence requirements are understood
```

---

## Kafka's Strengths

```text
1. HIGH THROUGHPUT
   Sequential I/O, batching, compression, and partition parallelism.

2. REPLAY
   Consumers can rebuild derived state.

3. MANY CONSUMER GROUPS
   Fraud, email, search, analytics, and warehouse can consume independently.

4. PARTITION-LEVEL ORDERING
   Correct key gives ordered stream per entity.

5. DURABILITY
   Replication and producer acknowledgements protect committed records.

6. ECOSYSTEM
   Connect, Debezium, Schema Registry, Kafka Streams, Flink, ksqlDB.
```

---

## Kafka's Problems

```text
PROBLEM 1: PARTITION KEY MISTAKES

  Wrong key creates hot partitions or broken ordering.
  Fixing later often means new topic and migration.

PROBLEM 2: LAG HIDES BUSINESS DELAY

  API may be green while search, email, fraud, or inventory projection is stale.

PROBLEM 3: EXACTLY-ONCE MISUNDERSTANDING

  Kafka transactions do not magically make external side effects exactly once.

PROBLEM 4: SCHEMA DRIFT

  Producer changes can break consumers after deploy.

PROBLEM 5: REBALANCE STORMS

  Deploys, GC, and autoscaling can repeatedly pause consumption.

PROBLEM 6: OPERATIONAL WEIGHT

  Brokers, partitions, ISR, disk, retention, ACLs, quotas, schemas, connectors,
  and consumers all need monitoring and ownership.

PROBLEM 7: REPLAY CAN BE DANGEROUS

  Replaying events into unsafe consumers can duplicate emails, webhooks,
  shipments, or payments.
```

---

## Performance and Capacity Thinking

Kafka throughput depends on:

```text
partition count
message size
producer batching
compression
replication factor
acks setting
broker disk/network
consumer processing rate
downstream dependency rate
```

Example:

```text
message size:        2 KB
produce rate:        100,000 records/sec
raw ingress:         200 MB/sec
replication factor:  3
broker write load:   about 600 MB/sec before compression effects
```

If compression ratio is 4:1:

```text
compressed ingress:  50 MB/sec
replicated writes:   about 150 MB/sec
```

Consumer bottleneck example:

```text
Kafka can deliver:       100,000 records/sec
Consumer can parse:       80,000 records/sec
OpenSearch can index:     20,000 records/sec

Actual progress:          20,000 records/sec
Lag growth at 100K input: 80,000 records/sec
```

The bottleneck is not Kafka. It is OpenSearch.

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
other partitions healthy
DLQ may be empty if failures never escape retry loop
```

Immediate mitigation:

```text
1. Capture topic, partition, offset, key, headers, payload, schema version, error.
2. Move record to DLQ or quarantine store.
3. Advance only with audit trail.
4. Decide whether later records can safely process out of order.
```

Permanent fix:

```text
schema validation
bounded retries
DLQ replay tool
consumer contract tests
idempotent side effects
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
consumer CPU moderate
OpenSearch write queue high
bulk rejections rising
read model stale
```

Mitigation:

```text
1. Check downstream p99 and rejection rate.
2. Pause non-critical consumers sharing the same dependency.
3. Use bulk writes instead of one-at-a-time writes.
4. Add backpressure.
5. Catch up at a controlled rate.
```

---

### Failure 3: Hot Partition During Launch

```text
key = product_id
product_id = SNKR-2026
```

Symptoms:

```text
one partition has massive lag
one consumer hot
other consumers idle
adding consumers does not help
rebalance rate may rise due autoscaling churn
```

Mitigation:

```text
1. Stop autoscaling churn.
2. Confirm partition-level lag skew.
3. Roll back producer key if safe.
4. Route new events to corrected topic if needed.
5. Prioritize critical consumers.
```

Permanent fix:

```text
key by order_id if order lifecycle ordering is required
bucket product_id if product-level total order is not required
load-test hot-key events before launch
```

---

### Failure 4: Retention Deletes Needed Data

```text
retention:       24 hours
consumer outage: 36 hours
```

Result:

```text
consumer cannot replay 12 hours of data
```

Mitigation:

```text
set retention from recovery objectives
alert on lag age approaching retention
snapshot read models
store authoritative data elsewhere
```

---

### Failure 5: Schema Change Breaks Consumers

Symptoms:

```text
producer deploy succeeds
consumer deserialization errors spike
DLQ fills with same schema version
lag rises across partitions
```

Mitigation:

```text
schema compatibility checks
consumer-driven contract tests
additive changes first
reserved protobuf fields
versioned event handlers
```

---

### Failure 6: Rebalance Storm During Deploy

Symptoms:

```text
consumer group rebalances spike
lag rises during every rollout
processing pauses repeatedly
some consumers show max.poll.interval violations
```

Mitigation:

```text
deploy in smaller waves
use static membership
increase poll interval only if processing is legitimately long
reduce batch processing time
separate polling from long downstream writes
```

---

### Failure 7: DLQ Becomes a Trash Can

Bad DLQ record:

```json
{"error":"failed"}
```

Useful DLQ record:

```json
{
  "original_topic": "order-events",
  "original_partition": 5,
  "original_offset": 8819231,
  "key": "order_123",
  "headers": {...},
  "payload": {...},
  "error_class": "SchemaValidationError",
  "error_message": "missing required field total_cents",
  "failed_at": "2026-05-15T10:18:00Z",
  "consumer_group": "search-indexer"
}
```

DLQ without replay tooling is a drawer full of tiny ghosts.

---

## SRE Diagnostic Toolkit

Describe topic:

```bash
kafka-topics --bootstrap-server broker:9092 \
  --describe --topic order-events
```

Consumer group lag:

```bash
kafka-consumer-groups --bootstrap-server broker:9092 \
  --describe --group search-indexer
```

Useful fields:

```text
TOPIC
PARTITION
CURRENT-OFFSET
LOG-END-OFFSET
LAG
CONSUMER-ID
HOST
CLIENT-ID
```

Broker health:

```text
under-replicated partitions
offline partitions
ISR shrink rate
ISR expand rate
produce request latency
fetch request latency
broker disk usage
network throughput
controller changes
request handler idle percent
```

Producer health:

```text
record send rate
record error rate
record retry rate
request latency
batch size
compression rate
buffer available bytes
metadata age
```

Consumer health:

```text
lag by partition
lag age
processing latency
poll latency
commit latency
rebalance count
DLQ records/sec
retry count
downstream p99
```

Golden incident question:

```text
Is Kafka the bottleneck, or is Kafka showing that another system is slow?
```

---

## Decision Matrix

```text
+-------------------------------+------------------------------+
| Requirement                   | Use                          |
+-------------------------------+------------------------------+
| immediate user answer         | synchronous RPC              |
| one background job            | task queue                   |
| many subscribers              | pub/sub                      |
| replayable event history      | Kafka-style log              |
| simple managed retries        | SQS                          |
| rich broker routing           | RabbitMQ                     |
| CDC backbone                  | Kafka + Debezium             |
| low-latency ephemeral bus     | NATS                         |
| modest Redis-native stream    | Redis Streams                |
+-------------------------------+------------------------------+
```

Use Kafka when:

```text
- replay matters
- multiple independent consumers need the stream
- high throughput exists
- per-key ordering matters
- retention is useful
- teams can operate lag, schemas, brokers, and DLQs
```

Do not use Kafka when:

```text
- you only need one simple background job queue
- the team cannot operate it
- ordering requirements are unknown
- consumers cannot tolerate duplicates
- retention/replay has no product value
```

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

Synchronous path:

```text
validate cart
reserve inventory if required
authorize payment if required
write order
publish durable fact through outbox/CDC
```

Async path:

```text
send confirmation email
update search index
record analytics
notify warehouse
refresh recommendations
```

Correctness rule:

```text
Search index is not authoritative for checkout price.
Analytics is not authoritative for order existence.
Email confirmation is not authoritative for payment status.
OrdersDB/payment ledger are authoritative.
```

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
The producer partition key changed from order_id to product_id. During the launch,
most events have the same product_id, so they hash to one hot partition. One
partition can have only one active consumer per group, so inventory lag grows on
that partition even though many consumers exist.
```

The bad key turned horizontal parallelism into a one-lane bridge.

## Question 2: Why did autoscaling consumers not fix it?

```text
Topic partitions: 48
Consumers:        96
Useful consumers per group for this topic: at most 48
Hot partition owner: exactly 1
```

Autoscaling beyond partition count cannot split one partition. It may increase rebalance churn and make lag worse.

## Question 3: Why is search lag worse than inventory lag?

Search has two bottlenecks:

```text
1. Same hot-partition event skew.
2. One-document-at-a-time OpenSearch writes.
```

Check OpenSearch:

```bash
curl -s localhost:9200/_cluster/health?pretty
curl -s localhost:9200/_cat/thread_pool/write?v
curl -s localhost:9200/_cat/shards?v
```

If OpenSearch is rejecting or queuing writes, Kafka is not the main bottleneck.

## Question 4: What do you do immediately?

```text
1. Stop autoscaling churn.
2. Confirm partition-level lag and hot key.
3. Roll back producer key to order_id if compatible.
4. If rollback cannot safely mix streams, create corrected topic and cut over new events.
5. Prioritize fraud and inventory over search and analytics.
6. Slow or pause search indexing if it competes for critical resources.
7. Add email retry backoff with jitter.
8. Preserve all records; do not skip offsets without audit.
```

## Question 5: What should not be done?

```text
Do not:
  - delete topic data to reduce lag
  - skip offsets silently
  - keep scaling consumers blindly
  - increase partitions during P1 without migration plan
  - trust stale inventory projection for checkout correctness
  - run full-speed OpenSearch backfill while OpenSearch is rejecting writes
```

## Question 6: Long-term fix

```text
Partition key contract:
  order lifecycle events key by order_id

Hot-key testing:
  simulate launch product skew before release

Consumer priority:
  fraud and inventory get protected capacity

Search indexing:
  bulk writes, backpressure, freshness SLO

Email retry:
  bounded retries, exponential backoff, jitter, sent markers

Monitoring:
  lag by partition, lag age, rebalance rate, DLQ rate, downstream write p99

Schema governance:
  compatibility checks before producer deploy
```

---

## Key Takeaways

```text
1. A task queue assigns work; Kafka stores replayable ordered history.
2. Kafka ordering is per partition, not global.
3. Partition key choice is correctness and capacity design.
4. Consumer lag is business delay.
5. Lag age matters more than raw lag count.
6. At-least-once delivery requires idempotent consumers.
7. Kafka exactly-once does not magically cover external side effects.
8. DLQs need full original record context and replay tooling.
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
