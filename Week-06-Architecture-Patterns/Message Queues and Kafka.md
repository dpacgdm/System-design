# Week 6, Topic 1: Message Queues and Kafka

Last verified: 2026-05-16

---

## 0. The Core Idea

A messaging system moves work or facts between components without requiring the producer and consumer to complete the work in the same call stack.

That sounds simple. It is not.

Messaging changes the shape of failure.

Without messaging:

```text
Caller waits.
Failure is immediate.
The stack trace is close to the user request.
```

With messaging:

```text
Caller may already be gone.
Failure may appear minutes later.
The broken workflow may be split across services, topics, offsets, retries,
DLQs, projections, and dashboards.
```

Messaging is useful because it lets systems decouple time, ownership, failure, and load.

Messaging is dangerous because it introduces duplicates, lag, replay, ordering limits, schema compatibility, and operational state.

Correct mental model:

```text
Messaging does not remove work.
Messaging moves work across time and failure domains.
```

---

## 1. Learning Objectives

After this topic, you should be able to:

```text
1. Explain task queues, pub/sub, and durable logs without mixing their semantics.
2. Explain why Kafka is a distributed, replicated, partitioned commit log.
3. Decide when to use SQS, RabbitMQ, Kafka, Redis Streams, NATS, Kinesis, or RPC.
4. Explain Kafka topics, partitions, offsets, brokers, leaders, followers, ISR,
   producers, consumers, consumer groups, retention, and compaction.
5. Design partition keys that preserve required ordering without creating hot partitions.
6. Explain producer durability: acks, retries, idempotence, batching, compression,
   min.insync.replicas, and replication factor.
7. Explain consumer correctness: offset commits, at-least-once processing,
   idempotency, rebalances, max.poll.interval.ms, and DLQs.
8. Calculate consumer lag growth, catch-up time, storage retention risk, and
   downstream bottlenecks.
9. Diagnose poison messages, hot partitions, rebalance storms, retention loss,
   connector lag, schema breaks, and downstream saturation.
10. Build an SRE-grade incident response for Kafka-backed pipelines.
```

---

## 2. What People Get Wrong

### Wrong Model 1: "A queue and Kafka are basically the same."

They both move messages. That is where the similarity ends.

A task queue asks:

```text
Which worker should do this job?
```

Kafka asks:

```text
Where does this record belong in the log, and which consumers have read how far?
```

Task queue:

```text
+----------+      +-------------+      +----------+
| Producer | ---> | Task Queue  | ---> | Worker A |
+----------+      +-------------+      +----------+
                         |
                         +------->     +----------+
                                       | Worker B |
                                       +----------+
```

Kafka durable log:

```text
Topic: order-events
Partition 0

+---------+---------+---------+---------+---------+
| off 100 | off 101 | off 102 | off 103 | off 104 |
+---------+---------+---------+---------+---------+
      ^                   ^
      |                   |
 fraud-service       search-indexer
 committed offset    committed offset
```

In a task queue, a job is normally removed after successful processing. In Kafka, records remain until retention or compaction removes them.

### Wrong Model 2: "Async means faster."

Async can make the user-facing path faster. It does not make the total work smaller.

Synchronous checkout:

```text
Client -> Checkout -> OrdersDB -> Payment -> Email -> Search -> Analytics
```

Async checkout:

```text
Client -> Checkout -> OrdersDB -> Publish event -> Response
                                      |
                                      v
                              Email/Search/Analytics later
```

The second path is faster for the user. The system still has to do email, search, analytics, retries, and monitoring.

### Wrong Model 3: "Consumer lag means Kafka is slow."

Consumer lag often means the consumer or downstream dependency is slow.

```text
Kafka can deliver:       100,000 records/sec
Consumer can parse:       90,000 records/sec
OpenSearch can index:     15,000 records/sec

Actual progress:          15,000 records/sec
Lag growth:               85,000 records/sec
```

Kafka is the scoreboard. The fire may be elsewhere.

### Wrong Model 4: "Exactly-once means no duplicate business effects."

Kafka transactions can coordinate Kafka reads, Kafka writes, and offset commits within Kafka.

They do not automatically make these exactly once:

```text
payment charge
email send
warehouse shipment
third-party webhook
PostgreSQL write outside the Kafka transaction
```

For external side effects, the practical design is:

```text
at-least-once delivery + idempotency + unique constraints + reconciliation
```

### Wrong Model 5: "More partitions always means more scale."

More partitions can increase parallelism only if traffic spreads across them.

```text
48 partitions
96 consumers
1 hot key

The hot key still lands on one partition.
One partition still has one active consumer per group.
```

More partitions also increase metadata, file handles, leader balancing, recovery time, and rebalancing cost.

---

## 3. Why Messaging Exists

A checkout system without messaging often grows into this:

```text
+--------+      +----------+
| Client | ---> | Checkout |
+--------+      +----------+
                      |
      +---------------+---------------+---------------+
      |               |               |               |
      v               v               v               v
+----------+    +----------+    +-----------+    +-----------+
| OrdersDB |    | Payment  |    | Inventory |    | Email     |
+----------+    +----------+    +-----------+    +-----------+
                      |
                      v
                +-----------+
                | Analytics |
                +-----------+
```

This is simple until email slows down, analytics fails, or inventory has a temporary spike.

A better boundary:

```text
Synchronous path:
  validate cart
  authorize or reserve payment if required
  reserve inventory if required
  write authoritative order

Asynchronous path:
  send email
  update search
  analytics
  recommendations
  warehouse notification
```

Architecture:

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
                   |  +-----> Search
                   +--------> Email
```

The user-facing path now depends only on things that must be immediately correct.

---

## 4. Three Messaging Models

### 4.1 Task Queue

A task queue distributes jobs to workers.

```text
One job should be handled by one worker.
```

Examples:

```text
SendReceiptEmail(order_id=123)
ResizeImage(image_id=abc)
ProcessCsvImport(import_id=999)
RetryWebhookDelivery(webhook_id=555)
GenerateInvoice(customer_id=42)
```

Worker lifecycle:

```text
1. Producer enqueues job.
2. Worker receives job.
3. Queue hides job from other workers.
4. Worker processes job.
5. Worker acknowledges success.
6. Queue deletes or marks job complete.
```

Failure case:

```text
1. Worker receives job.
2. Worker performs side effect.
3. Worker crashes before ack.
4. Queue redelivers job.
5. Side effect repeats unless worker is idempotent.
```

SQS-style configuration:

```text
Queue: email-jobs
Visibility timeout: 60 seconds
Max receive count: 5
DLQ: email-jobs-dlq
```

Message:

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

Good use cases:

```text
background jobs
email delivery
file processing
webhook retries
small async workflows
```

Poor use cases:

```text
long replayable history
many independent consumers reading same stream
CDC backbone
event sourcing
```

### 4.2 Publish/Subscribe

Pub/sub fans out messages.

```text
One published event can be received by many subscribers.
```

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

Good use cases:

```text
OrderPlaced fanout
UserSignedUp notifications
ProductPriceChanged propagation
SecurityEvent broadcast
```

Main risk:

```text
The publisher may not know how many systems depend on the event.
```

This makes schema governance and event ownership mandatory.

### 4.3 Durable Event Log

A durable event log stores ordered records for a retention window.

```text
Topic: order-events

+-------------+-----------------+------------+---------+-----------+
| OrderPlaced | PaymentCaptured | ItemPacked | Shipped | Delivered |
+-------------+-----------------+------------+---------+-----------+
      0               1              2           3          4
```

Consumers track their own offsets:

```text
fraud-service:        offset 4
search-indexer:       offset 2
analytics-pipeline:   offset 0
```

Good use cases:

```text
rebuild search index
CDC fanout
analytics ingestion
stream processing
fraud scoring
read model projections
system integration backbone
```

Poor use cases:

```text
simple one-off background job
arbitrary priority queue
request-response workflow
human approval queue
```

---

## 5. Kafka Core Model

Kafka is a distributed, replicated, partitioned commit log.

```text
DISTRIBUTED
  Data is spread across brokers.

REPLICATED
  Data is copied for durability and availability.

PARTITIONED
  Topics are split into ordered shards.

COMMIT LOG
  Records are appended and read by offset.
```

Kafka vocabulary:

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
  Position in a partition.

PRODUCER
  Client writing records.

CONSUMER
  Client reading records.

CONSUMER GROUP
  Set of consumers sharing partitions.

LEADER
  Broker handling reads/writes for a partition.

FOLLOWER
  Broker replicating from leader.

ISR
  In-sync replicas.

RETENTION
  Rule for how long records remain.

COMPACTION
  Keeps latest value per key eventually.
```

Topic layout:

```text
Topic: order-events

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
Kafka preserves order inside one partition.
Kafka does not preserve total order across a topic.
```

That sentence should be tattooed on every Kafka design review.

---

## 6. Kafka Record Anatomy

A production record is not just a payload.

```text
record
  topic:      order-events
  partition: 7
  offset:    8819231
  key:       order_123
  value:     serialized event payload
  headers:   metadata
  timestamp: producer or broker timestamp
```

Event payload:

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

Meaning:

```text
event_id
  dedupe and audit

aggregate_id
  ordering and partition key candidate

schema_version
  compatibility

occurred_at
  when the business fact happened

published_at
  when the event entered the pipeline

correlation_id
  trace the workflow

causation_id
  explain why this event exists
```

Without this metadata, incident response becomes a lantern walk through a swamp.

---

## 7. Producer Write Path

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
1. Producer serializes the record.
2. Producer selects topic.
3. Producer selects partition.
4. Producer batches records for efficiency.
5. Producer sends batch to partition leader.
6. Leader appends batch to local log.
7. Followers replicate from leader.
8. Producer receives acknowledgement based on durability settings.
```

Partition selection:

```text
If key exists:
  partition = hash(key) % partition_count

If no key exists:
  producer distributes using sticky or round-robin behavior depending client/version
```

No key means no per-entity ordering guarantee.

---

## 8. Producer Configuration

Business-critical producer baseline:

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

Interpretation:

```text
acks=all
  Wait for durability condition before success.

enable.idempotence=true
  Prevent duplicate sequence writes caused by producer retries.

retries
  Retry transient broker errors.

max.in.flight.requests.per.connection
  Controls concurrent unacknowledged requests.

compression.type
  Reduces network and disk load.

linger.ms
  Wait briefly to build better batches.

batch.size
  Maximum batch size per partition.

delivery.timeout.ms
  Total send deadline including retries.

request.timeout.ms
  Broker request timeout.
```

Tradeoffs:

```text
Lower latency:
  lower linger.ms, smaller batches

Higher throughput:
  batching, compression, enough partitions

Higher durability:
  acks=all, replication.factor=3, min.insync.replicas=2

Higher availability during replica trouble:
  may conflict with strict durability
```

---

## 9. Producer Acknowledgements and Durability

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

Common durable setup:

```text
replication.factor=3
min.insync.replicas=2
acks=all
```

This means:

```text
There are three replicas when healthy.
At least two in-sync replicas must participate for acknowledged writes.
```

If ISR drops below minimum:

```text
writes fail instead of pretending to be durable
```

That is operationally painful and architecturally honest.

---

## 10. Replication, Leaders, Followers, ISR

Replication factor 3:

```text
Partition 7

+----------+      +--------+
| Broker 1 | ---> | Leader |
+----------+      +--------+

+----------+      +----------+
| Broker 2 | ---> | Follower |
+----------+      +----------+

+----------+      +----------+
| Broker 3 | ---> | Follower |
+----------+      +----------+
```

Healthy ISR:

```text
leader: Broker 1
ISR:    Broker 1, Broker 2, Broker 3
```

One follower lagging:

```text
leader: Broker 1
ISR:    Broker 1, Broker 2
Broker 3 removed from ISR
```

SRE interpretation:

```text
ISR shrink:
  durability is getting worse

under-replicated partition:
  at least one replica is not in sync

offline partition:
  no leader is available; clients are impacted
```

Do not treat under-replication as dashboard confetti. It is the storage layer whispering before it starts shouting.

---

## 11. Consumer Read Path

Consumer group assignment:

```text
Topic: order-events, 6 partitions
Consumer group: search-indexer

Partition 0 -> Consumer A
Partition 1 -> Consumer A
Partition 2 -> Consumer B
Partition 3 -> Consumer B
Partition 4 -> Consumer C
Partition 5 -> Consumer C
```

Rule:

```text
Within one consumer group, one partition has at most one active consumer.
```

If a topic has 6 partitions and a group has 10 consumers:

```text
6 consumers process partitions.
4 consumers are idle for this topic.
```

Different groups are independent:

```text
                 +---------------+
                 | order-events  |
                 +---------------+
                    |     |     |
                    v     v     v
                 fraud search analytics
                 group group  group
```

Each group has its own offsets and lag.

---

## 12. Consumer Configuration

Side-effecting consumer baseline:

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

Interpretation:

```text
group.id
  Offset namespace and consumer group identity.

enable.auto.commit=false
  Application decides when offsets are safe to commit.

auto.offset.reset=earliest
  If no committed offset exists, start from beginning.

max.poll.records
  Batch size returned per poll.

max.poll.interval.ms
  Maximum time between polls before consumer is considered stuck.

session.timeout.ms
  Time before broker considers consumer dead.

heartbeat.interval.ms
  Heartbeat frequency.

fetch.min.bytes / fetch.max.wait.ms
  Throughput vs latency tradeoff.
```

Dangerous default:

```text
enable.auto.commit=true
```

For consumers with external side effects, auto-commit can mark work complete before business processing is safe.

---

## 13. Offset Commit Semantics

Offset:

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
Kafka thinks offset 102 is done.
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
Kafka redelivers offset 102.
Business work may happen twice.
```

This is at-least-once.

Most real systems choose:

```text
at-least-once + idempotent consumer
```

---

## 14. Idempotent Consumer Pattern

Bad consumer:

```python
def handle(event):
    send_receipt_email(event.order_id)
    commit_offset(event)
```

Crash after sending email but before committing offset:

```text
Kafka redelivers.
Customer receives duplicate email.
```

Better consumer:

```python
def handle(event):
    dedupe_key = f"receipt:{event.order_id}:receipt_v3"

    with transaction():
        inserted = insert_notification_marker_if_absent(dedupe_key)
        if inserted:
            send_receipt_email(event.order_id)

    commit_offset(event)
```

Database-backed dedupe:

```sql
BEGIN;

INSERT INTO processed_events(event_id, processed_at)
VALUES ('evt_123', now())
ON CONFLICT DO NOTHING;

-- Only apply business effect if insert succeeded.

COMMIT;
```

For ledgers:

```text
ledger_entries.event_id must be unique
```

For payment providers:

```text
send stable provider idempotency key
```

For webhooks:

```text
dedupe by event_id + destination_id
```

Idempotency is not decoration. It is the seatbelt.

---

## 15. Delivery Guarantees

```text
+------------------+-----------------------------+--------------------------+
| Guarantee        | Meaning                     | Typical implementation   |
+------------------+-----------------------------+--------------------------+
| At-most-once     | may lose, no duplicate work | commit before processing |
| At-least-once    | duplicates possible         | process before commit    |
| Effectively-once | business state once         | idempotency + constraints|
| Exactly-once     | scoped transaction claim    | Kafka transactions       |
+------------------+-----------------------------+--------------------------+
```

Exactly-once scope:

```text
Kafka topic A -> Kafka Streams -> Kafka topic B
  Kafka transactions can help.

Kafka topic A -> Consumer -> Stripe
  Kafka cannot make Stripe exactly once.

Kafka topic A -> Consumer -> Email provider
  Kafka cannot un-send an email.
```

Correct statement:

```text
Kafka exactly-once is scoped. External side effects still require idempotency and reconciliation.
```

---

## 16. Kafka Transactions

Kafka transactions are useful for consume-transform-produce pipelines.

```text
Topic A -> Processor -> Topic B
```

A transaction can include:

```text
records produced to Topic B
offsets consumed from Topic A
```

This prevents:

```text
output written but offset not committed
offset committed but output missing
```

It does not solve:

```text
payment charged twice
email sent twice
row inserted twice in external DB without unique key
warehouse shipment created twice
```

Those need business-level idempotency.

---

## 17. Partition-Key Design

Partition key determines ordering and load distribution.

Formula:

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
Partition 2: 180K/sec  <-- hot
Partition 3:   4K/sec
Partition 4:   3K/sec
```

Adding consumers cannot split one hot partition.

### Bucketed key

If strict product-level ordering is not required:

```text
key = product_id + ':' + hash(order_id) % 32
```

Tradeoff:

```text
better distribution
no total order for product_id
```

Decision rule:

```text
Choose the smallest entity that truly requires ordering.
```

Examples:

```text
order lifecycle:
  key = order_id

customer notifications:
  key = customer_id

account ledger:
  key = account_id

analytics clickstream:
  key = session_id, user_id, or random depending query need

hot product launch metrics:
  key = product_id + bucket if product ordering is not required
```

---

## 18. Consumer Lag

Lag:

```text
lag = log end offset - committed offset
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

Lag count vs lag age:

```text
5,000,000 records behind at 500,000/sec:
  10 seconds behind

5,000,000 records behind at 100/sec:
  13.9 hours behind
```

Lag age is often closer to business impact than raw lag count.

Lag patterns:

```text
ALL PARTITIONS LAG
  consumer fleet too small
  downstream dependency slow
  bad consumer deploy
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

---

## 19. Rebalancing

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

Triggers:

```text
consumer crash
rolling deploy
autoscaler flapping
long GC pause
network pause
processing exceeds max.poll.interval.ms
```

Failure loop:

```text
slow processing
  -> missed poll interval
  -> rebalance
  -> partitions pause
  -> lag grows
  -> same slow work resumes
```

Mitigations:

```text
static membership
cooperative rebalancing
bounded processing time
pause/resume partitions under downstream pressure
deploy in small waves
avoid autoscaler flapping
separate polling from slow side effects
```

SRE smell:

```text
Every deploy causes lag spike.
```

That means deployment is also a consumption outage.

---

## 20. Retention and Compaction

Kafka records are removed by retention, not by consumer acknowledgement.

Time retention:

```properties
retention.ms=604800000
```

Size retention:

```properties
retention.bytes=107374182400
```

Retention failure:

```text
retention:       24 hours
consumer outage: 36 hours
missing replay:  12 hours
```

A consumer cannot replay deleted records.

### Compaction

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

Good use cases:

```text
feature flag state
latest user profile
account settings
service configuration
```

Bad use cases:

```text
payment audit trail
security event history
legal record history
full order lifecycle history
```

Compaction is not immediate deletion. It is not an audit log.

---

## 21. Schema Evolution

Kafka moves bytes. Teams own meaning.

Formats:

```text
JSON
  readable, loose, larger, runtime failures common

Avro
  compact, schema-registry friendly, common in Kafka ecosystems

Protobuf
  compact, typed, field numbers matter

JSON Schema
  readable with validation
```

Breaking changes:

```text
remove required field
rename field without compatibility plan
change type string -> int
change meaning under same field name
reuse protobuf field number
change enum behavior without old consumer support
```

Safe evolution:

```text
1. Add optional new field.
2. Deploy consumers that understand old and new fields.
3. Start writing new field.
4. Backfill if needed.
5. Stop reading old field.
6. Remove only after retention and compatibility window.
```

Protobuf example:

```proto
message OrderPlaced {
  string order_id = 1;
  int64 total_cents = 2;
  string currency = 3;

  reserved 4;
  reserved "old_coupon_code";
}
```

Never reuse field numbers. Old bytes can become new lies.

---

## 22. Retry Topics and DLQs

Bad retry pattern:

```text
consumer fails
consumer immediately retries
consumer fails
consumer immediately retries
```

If downstream is already failing, immediate retries are a hammer hitting a cracked bell.

Better pattern:

```text
main topic
  -> consumer
     -> retry-1m
        -> retry-5m
           -> retry-30m
              -> DLQ
```

Diagram:

```text
+------------+      +----------+
| Main Topic | ---> | Consumer |
+------------+      +----------+
                        |
                        v
                   +----------+
                   | Retry 1m |
                   +----------+
                        |
                        v
                   +----------+
                   | Retry 5m |
                   +----------+
                        |
                        v
                   +-----+
                   | DLQ |
                   +-----+
```

Useful DLQ record:

```json
{
  "original_topic": "order-events",
  "original_partition": 5,
  "original_offset": 8819231,
  "key": "order_123",
  "headers": {
    "schema_version": "3",
    "correlation_id": "req_abc"
  },
  "payload": {
    "event_id": "evt_123"
  },
  "error_class": "SchemaValidationError",
  "error_message": "missing required field total_cents",
  "failed_at": "2026-05-16T00:30:00Z",
  "consumer_group": "search-indexer"
}
```

DLQ rules:

```text
preserve original record context
classify error
make replay intentional
alert on DLQ rate
own DLQ cleanup
never use DLQ as a landfill
```

---

## 23. Kafka Connect, CDC, and Outbox

Naive dual write:

```text
1. Write order to PostgreSQL.
2. Publish OrderPlaced to Kafka.
```

Failure:

```text
DB commit succeeds.
Kafka publish fails.
Order exists, event missing.
```

Transactional outbox:

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

CDC connector reads committed DB changes.

Operational traps:

```text
connector lag means event lag
replication slots can retain WAL and fill disk
snapshotting can overload primary
schema changes can break connector
consumers still need idempotency
```

PostgreSQL replication slot check:

```sql
SELECT
  slot_name,
  active,
  restart_lsn,
  confirmed_flush_lsn,
  pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) AS retained_bytes
FROM pg_replication_slots;
```

If retained bytes grow fast, the connector is now a database availability risk.

---

## 24. Security and Multi-Tenancy

Kafka security is part of the design.

Controls:

```text
TLS
  encrypt broker/client traffic

SASL
  authenticate clients

ACLs
  authorize read/write/admin operations

quotas
  prevent noisy producers or consumers from starving others

topic naming policy
  avoid accidental data exposure

schema governance
  prevent incompatible producer changes
```

Multi-tenant risks:

```text
one producer floods broker
one consumer group causes huge fetch load
one topic consumes disk through retention
one team writes PII into broad fanout topic
```

Controls:

```text
producer quotas
consumer quotas
retention by topic class
PII topic classification
ACL reviews
separate clusters for critical workloads if needed
```

---

## 25. Kafka vs SQS vs RabbitMQ vs Redis Streams vs NATS vs Kinesis

```text
+--------------+--------------------------+-----------------------------+
| System       | Best at                  | Watch out for               |
+--------------+--------------------------+-----------------------------+
| SQS          | managed task queues      | limited replay/log model    |
| RabbitMQ     | routing and work queues  | huge backlogs hurt broker   |
| Kafka        | durable event streams    | partition/key complexity    |
| Redis Streams| lightweight streams      | memory/persistence limits   |
| NATS         | low-latency messaging    | durability varies by mode   |
| Kinesis      | managed shard streams    | shard throughput limits     |
+--------------+--------------------------+-----------------------------+
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
work queue semantics dominate
per-service queues are natural
```

Use Kafka when:

```text
replay matters
many independent consumers need the same stream
high throughput exists
partition-level ordering matters
CDC/event backbone is needed
```

Use Redis Streams when:

```text
the stream is modest
Redis is already accepted operationally
retention and replay needs are limited
```

Use NATS when:

```text
low-latency messaging matters
subjects and request/reply fit
persistence mode is deliberately chosen
```

Use Kinesis when:

```text
managed AWS stream is preferred
shard throughput constraints are acceptable
AWS integration matters
```

---

## 26. Capacity Worksheet

### Producer ingress

```text
message size:        2 KB
produce rate:        100,000 records/sec
raw ingress:         200 MB/sec
replication factor:  3
raw replicated write: about 600 MB/sec before compression
```

If compression ratio is 4:1:

```text
compressed ingress:      50 MB/sec
replicated compressed:   about 150 MB/sec
```

### Consumer bottleneck

```text
Kafka fetch capacity:     100,000 records/sec
consumer CPU capacity:     80,000 records/sec
OpenSearch index capacity: 20,000 records/sec

Actual progress:           20,000 records/sec
```

If producer rate is 100,000/sec:

```text
lag growth = 100,000 - 20,000
           = 80,000 records/sec
```

### Retention storage

```text
compressed ingress: 50 MB/sec
retention:          7 days
replication:        3

storage = 50 MB/sec * 604,800 sec * 3
        = 90,720,000 MB
        = about 90 TB
```

This is why retention is an architecture decision, not a checkbox.

---

## 27. SRE Diagnostic Toolkit

Describe topic:

```bash
kafka-topics --bootstrap-server broker:9092 \
  --describe --topic order-events
```

Example output shape:

```text
Topic: order-events  PartitionCount: 48  ReplicationFactor: 3
Topic: order-events  Partition: 0  Leader: 1  Replicas: 1,2,3  Isr: 1,2,3
Topic: order-events  Partition: 1  Leader: 2  Replicas: 2,3,1  Isr: 2,3
```

Interpretation:

```text
Partition 1 has ISR 2,3 instead of 2,3,1.
One replica is out of sync.
Watch under-replicated partitions and ISR shrink.
```

Consumer group:

```bash
kafka-consumer-groups --bootstrap-server broker:9092 \
  --describe --group search-indexer
```

Example:

```text
TOPIC         PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG      HOST
order-events 0          1000000         1001000         1000     worker-1
order-events 1          900000          1600000         700000   worker-2
order-events 2          999500          1000000         500      worker-3
```

Interpretation:

```text
Partition 1 dominates lag.
Likely hot key, poison message, or slow partition owner.
Do not scale blindly until partition skew is understood.
```

Broker health signals:

```text
under-replicated partitions
offline partitions
ISR shrink rate
produce request latency
fetch request latency
broker disk usage
network throughput
controller changes
request handler idle percent
```

Producer signals:

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

Consumer signals:

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

Golden question:

```text
Is Kafka the bottleneck, or is Kafka exposing that another system is slow?
```

---

## 28. Production Failure Patterns

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
same offset appears repeatedly in logs
one partition lag grows
consumer restarts or retries forever
other partitions healthy
DLQ may be empty because retry never escapes loop
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
2. Pause non-critical consumers sharing the dependency.
3. Use bulk writes instead of one-at-a-time writes.
4. Add backpressure.
5. Catch up at controlled rate.
```

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

### Failure 7: DLQ Becomes a Trash Can

Bad DLQ record:

```json
{"error":"failed"}
```

Useful DLQ record includes:

```text
original topic
original partition
original offset
key
headers
payload
schema version
error class
error message
failed timestamp
consumer group
```

DLQ without replay tooling is just a museum of broken promises.

---

## 29. Decision Matrix

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
replay matters
multiple independent consumers need the stream
high throughput exists
per-key ordering matters
retention is useful
teams can operate lag, schemas, brokers, DLQs, and replays
```

Do not use Kafka when:

```text
you only need one simple background job queue
consumers cannot tolerate duplicates
ordering requirements are unknown
team cannot operate Kafka
retention and replay have no product value
```

---

## 30. Real-World Architecture Example

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
commit outbox event
```

Async path:

```text
send confirmation email
update search index
record analytics
notify warehouse
refresh recommendations
```

Authority rule:

```text
OrdersDB is authoritative for order existence.
Payment ledger/provider is authoritative for payment status.
Inventory service is authoritative for stock reservation.
Search is a projection.
Analytics is a projection.
Email is a notification side effect.
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

## Diagnosis

Root cause:

```text
The producer partition key changed from order_id to product_id. During the launch,
most events have the same product_id, so they hash to one hot partition. One
partition can have only one active consumer per group. Inventory lag grows on
that partition even though many consumers exist.
```

Autoscaling failure:

```text
Topic partitions: 48
Consumers:        96
Useful consumers: at most 48
Hot partition:    one active owner
```

Search-specific problem:

```text
Search has hot-partition lag plus one-document-at-a-time OpenSearch writes.
OpenSearch may be the true downstream bottleneck.
```

Check OpenSearch:

```bash
curl -s localhost:9200/_cluster/health?pretty
curl -s localhost:9200/_cat/thread_pool/write?v
curl -s localhost:9200/_cat/shards?v
```

Immediate mitigation:

```text
1. Stop autoscaling churn.
2. Confirm partition-level lag and hot key.
3. Roll back producer key to order_id if compatible.
4. If rollback cannot safely mix streams, cut over new events to corrected topic.
5. Prioritize fraud and inventory over search and analytics.
6. Slow or pause search indexing if it competes for critical resources.
7. Add email retry backoff with jitter.
8. Preserve all records; do not skip offsets without audit.
```

Do not:

```text
- delete topic data to reduce lag
- skip offsets silently
- keep scaling consumers blindly
- increase partitions during P1 without migration plan
- trust stale inventory projection for checkout correctness
- run full-speed OpenSearch backfill while OpenSearch is rejecting writes
```

Long-term fix:

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

## Gap Fill

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
