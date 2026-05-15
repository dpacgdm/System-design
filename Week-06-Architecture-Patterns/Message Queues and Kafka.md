# Week 6, Topic 1: Message Queues and Kafka

Last verified: 2026-05-15

> Goal: Teach asynchronous messaging the way a production SRE actually needs
> it: not as a buzzword, not as "just add Kafka", but as a set of delivery,
> ordering, durability, replay, and failure-isolation tradeoffs.

---

## 0. ASCII diagram quality gate

All diagrams in this file intentionally use plain ASCII only.

Rules used:

```text
- Use +---+ boxes, | pipes, and -> arrows only.
- Keep diagrams narrow enough to read in GitHub Markdown.
- Avoid dense multi-directional arrows unless the flow truly needs them.
- Prefer multiple small diagrams over one giant nervous spider.
- Every diagram must teach one idea.
```

---

## 1. Learning objectives

After this topic, you will be able to:

```text
1. Explain the difference between a task queue, pub/sub, and a durable log.
2. Decide when to use direct RPC, SQS, RabbitMQ, Kafka, Redis Streams, or NATS.
3. Explain Kafka topics, partitions, offsets, leaders, followers, and replicas.
4. Explain why Kafka is not a normal queue.
5. Design partition keys that preserve ordering without creating hot partitions.
6. Diagnose consumer lag using offsets, throughput, and downstream bottlenecks.
7. Explain at-most-once, at-least-once, effectively-once, and exactly-once scope.
8. Identify poison messages, retry storms, rebalance storms, and DLQ misuse.
9. Operate Kafka safely during incidents without causing data loss or lag explosions.
10. Defend a messaging architecture in a system design interview and in a P1 review.
```

---

## 2. Why this topic exists

Synchronous systems are easy to reason about until they are not.

```text
Client -> API -> Payment -> Inventory -> Email -> Analytics -> Search
```

If every dependency is called inline, user latency becomes the sum of the
slow path, and availability becomes the product of many dependencies.

```text
If each dependency is 99.9% available:

Payment   99.9%
Inventory 99.9%
Email     99.9%
Analytics 99.9%
Search    99.9%

End-to-end availability:
  0.999 ^ 5 = 0.995
  about 99.5%
```

That looks small until it becomes customer-visible downtime. One optional
email service should not block checkout. One slow analytics sink should not
turn order placement into wet cement.

A message system lets you decouple time, ownership, and failure.

```text
             synchronous path
User -> API ---------------------> Database
          |
          | async events
          v
       Message system -> Email
                      -> Analytics
                      -> Search
                      -> Fraud review
```

But this trade is not free. You buy decoupling with delayed work, duplicate
messages, ordering traps, schema drift, replay risk, hidden lag, and more
operational state.

A queue is not a broom. Kafka is not holy water. Messaging moves failure; it
rarely deletes it.

---

## 3. What people get wrong

### Wrong model 1: "Kafka is a queue"

Kafka can be used for queue-like workloads, but its core abstraction is a
partitioned durable log.

A traditional queue says:

```text
Take this job. One worker should process it. Then remove it.
```

Kafka says:

```text
Append this record to an ordered partition. Consumers may read it at offsets.
Retention decides when it disappears.
```

Clean mental model:

```text
Queue:

+---------+     +---------+     +---------+
| job-1   | --> | job-2   | --> | job-3   |
+---------+     +---------+     +---------+
     |              |              |
     v              v              v
  worker A       worker B       worker C

A processed job is gone from the queue.
```

```text
Kafka log:

Topic: orders
Partition 0:

+---------+---------+---------+---------+
| off 101 | off 102 | off 103 | off 104 |
+---------+---------+---------+---------+
     ^         ^
     |         |
 fraud     search-indexer
 offset    offset

Records stay until retention or compaction removes them.
Each consumer tracks its own position.
```

### Wrong model 2: "Async means faster"

Async usually makes the user-facing path faster by moving work out of line.
It does not make total work disappear.

```text
Before:
  checkout latency = DB + payment + email + search + analytics

After:
  checkout latency = DB + payment + publish event

But the system still must do:
  email + search + analytics
```

Async reduces coupling. It may increase total complexity.

### Wrong model 3: "Consumer lag is just a Kafka problem"

Consumer lag is often a downstream problem wearing a Kafka hat.

```text
Producer rate:        50,000 events/sec
Consumer read rate:   50,000 events/sec
Downstream DB writes: 12,000 events/sec

Real throughput:      12,000 events/sec
Lag growth:           38,000 events/sec
```

Kafka is the smoke alarm. The fire may be OpenSearch, PostgreSQL, Redis, an
HTTP dependency, CPU, schema validation, poison messages, or a bad deploy.

### Wrong model 4: "Exactly once means the business action happens once"

Kafka transactions can provide strong guarantees inside Kafka read-process-write
pipelines. They do not automatically make an external payment gateway, email
provider, database update, or HTTP side effect happen exactly once.

```text
Kafka -> consumer -> payment provider

Kafka can control Kafka offsets and Kafka writes.
It cannot magically un-send a payment request.
```

For external effects, you still need idempotency keys, dedupe tables, unique
constraints, reconciliation, and replay discipline.

### Wrong model 5: "More partitions always means more scale"

More partitions can increase parallelism, but they also increase metadata,
file handles, memory, rebalancing cost, leader movement, recovery time, and
operational surface area.

```text
Good reason to add partitions:
  consumer parallelism is capped by partition count

Bad reason to add partitions:
  we are scared and want a bigger number
```

---

## 4. The three messaging mental models

Most confusion disappears when you separate these three shapes.

### 4.1 Task queue

Use when the work item should be handled by one worker.

```text
              +-----------+
Producer ---> |   Queue   | ---> Worker A
              +-----------+ ---> Worker B
                            ---> Worker C

One job goes to one worker.
```

Examples:

```text
- Send one email
- Resize one image
- Process one uploaded file
- Retry one webhook delivery
```

What you care about:

```text
acknowledgement
visibility timeout
retry count
dead-letter queue
worker concurrency
idempotent job execution
```

Good tools:

```text
SQS, RabbitMQ, Celery-backed queues, Sidekiq, Resque
```

Kafka can do this, but it is often heavier and less ergonomic for pure task
queues.

### 4.2 Pub/sub

Use when many subscribers should receive the same message.

```text
                +-------------+
Publisher ----> |   Topic     | ----> Email service
                +-------------+ ----> Analytics service
                                ----> Search service
```

Examples:

```text
- OrderCreated notification
- UserSignedUp notification
- ProductPriceChanged notification
```

What you care about:

```text
fanout
subscriber isolation
delivery retry
subscription filtering
schema compatibility
```

Good tools:

```text
SNS, Google Pub/Sub, RabbitMQ exchanges, Kafka topics
```

### 4.3 Durable event log

Use when the event history itself is valuable.

```text
Topic: order-events

+--------+--------+--------+--------+--------+
| off 1  | off 2  | off 3  | off 4  | off 5  |
+--------+--------+--------+--------+--------+
   |        |        |        |        |
 created  paid   packed  shipped delivered

Consumers can replay from any retained offset.
```

Examples:

```text
- Rebuild search index from order events
- Feed real-time fraud scoring
- Train analytics and ML pipelines
- Reprocess events after a bug fix
- Stream CDC from PostgreSQL into read models
```

What you care about:

```text
retention
replay
ordering per key
schema evolution
offset management
consumer lag
partition strategy
operational recovery
```

Good tools:

```text
Kafka, Redpanda, Pulsar, Kinesis, Event Hubs
```

---

## 5. Comparing the common options

### 5.1 Direct RPC

```text
Service A -> Service B
```

Strengths:

```text
simple mental model
immediate response
clear success/failure
natural for queries and commands requiring immediate result
```

Problems:

```text
caller waits
dependency failure propagates
retry storms are easy
not replayable
poor fit for fanout side effects
```

Use it for:

```text
payment authorization
inventory reservation
login
read queries
commands that need an immediate answer
```

Do not use it for:

```text
email after checkout
analytics tracking
search indexing
slow non-critical fanout
```

### 5.2 Database polling

```text
App -> DB table: pending_jobs
Worker polls every N seconds
```

Strengths:

```text
simple
transactional with local database
good for low volume jobs
```

Problems:

```text
polling load
lock contention
poor fanout
hard replay semantics
job table becomes tiny queue system you now operate
```

Use it for:

```text
small internal workflows
admin jobs
low-throughput outbox dispatchers
```

Do not use it for:

```text
high-volume event streaming
many independent consumers
large replay pipelines
```

### 5.3 SQS-style managed queue

```text
Producer -> SQS Queue -> Workers
```

Strengths:

```text
managed durability
visibility timeout
dead-letter queues
simple worker scaling
low operational burden
```

Problems:

```text
limited ordering unless FIFO queue is used
not a replay log
message retention is finite
less natural for many independent replaying consumers
```

Use it for:

```text
task queues
background jobs
webhook retry
image processing
single-consumer work distribution
```

### 5.4 RabbitMQ-style broker

```text
Publisher -> Exchange -> Queue A -> Consumer A
                      -> Queue B -> Consumer B
```

Strengths:

```text
rich routing
exchanges and bindings
acknowledgements
per-queue semantics
excellent task-queue ergonomics
```

Problems:

```text
not designed as a long-retention replay log
large backlogs can hurt broker health
routing topology can become hidden architecture
```

Use it for:

```text
work queues
routing-heavy messaging
per-service queues
moderate-volume enterprise messaging
```

### 5.5 Kafka-style durable log

```text
Producer -> Topic partitions -> Consumer group A
                            -> Consumer group B
                            -> Consumer group C
```

Strengths:

```text
high-throughput append log
replayable history
many independent consumer groups
partition-level ordering
retention and compaction
excellent CDC and event-streaming backbone
```

Problems:

```text
not ergonomic for simple task queues
partition key design is critical
consumer lag can hide business delay
operationally heavy at scale
exactly-once scope is often misunderstood
```

Use it for:

```text
event streams
CDC pipelines
analytics ingestion
search indexing
fraud pipelines
stream processing
large fanout with replay
```

Do not use it for:

```text
one small background email queue
synchronous request-response
tiny cron-like workloads
jobs requiring arbitrary per-message priority
```

---

## 6. Kafka core model

Kafka has four core nouns:

```text
topic      = named stream of records
partition  = ordered shard of a topic
offset     = position of a record inside one partition
consumer   = process that reads records and tracks progress
```

Clean model:

```text
Topic: orders

Partition 0:  off 0   off 1   off 2   off 3
              +-----+ +-----+ +-----+ +-----+
              | A   | | B   | | C   | | D   |
              +-----+ +-----+ +-----+ +-----+

Partition 1:  off 0   off 1   off 2   off 3
              +-----+ +-----+ +-----+ +-----+
              | E   | | F   | | G   | | H   |
              +-----+ +-----+ +-----+ +-----+
```

Ordering is per partition, not per topic.

```text
Guaranteed:
  A before B before C within partition 0

Not guaranteed:
  global order across partition 0 and partition 1
```

A Kafka record is usually more than a payload.

```text
record = {
  topic: "orders",
  partition: 7,
  offset: 991881,
  key: "customer-123",
  timestamp: "2026-05-15T10:15:30Z",
  headers: {
    trace_id: "...",
    schema_version: "3",
    idempotency_key: "..."
  },
  value: {
    event_type: "OrderPlaced",
    order_id: "ord_123",
    amount_cents: 129900
  }
}
```

The key is not decoration. It usually decides partition placement and ordering.

```text
partition = hash(record.key) % partition_count
```

If the key is `customer_id`, all events for one customer usually go to the same
partition and preserve customer-level ordering.

---

## 7. Kafka write path

Simplified write path:

```text
+----------+       +----------+       +----------+
| Producer | ----> | Leader   | ----> | Follower |
| client   |       | broker   |       | broker   |
+----------+       +----------+       +----------+
      |                 |
      |                 v
      |            append to log
      |
      v
 receive ack after configured durability condition
```

Detailed flow:

```text
1. Producer serializes record.
2. Producer chooses partition from key or partitioner.
3. Producer batches records for efficiency.
4. Producer sends batch to the partition leader.
5. Leader appends the batch to its local log.
6. Followers replicate the batch.
7. Leader acknowledges based on acks setting.
8. Consumer can read once the record is visible according to log state.
```

### acks=0

```text
Producer sends and does not wait.

Producer -> Broker

Fast, but record can vanish silently.
```

Use rarely. This is for telemetry where losing data is acceptable.

### acks=1

```text
Producer waits for leader append.

Producer -> Leader append -> ack
```

Risk:

```text
Leader accepts record.
Leader crashes before followers copy it.
New leader does not have record.
Record is lost.
```

### acks=all

```text
Producer waits for leader plus in-sync replica requirement.

Producer -> Leader
          -> Follower in ISR
          -> ack after required replicas confirm
```

Better durability, higher latency.

Important pair:

```text
acks=all
min.insync.replicas=2
replication.factor=3
```

This means a write should not be acknowledged unless enough replicas are in sync.
If ISR shrinks below the minimum, writes fail instead of pretending to be durable.
That is painful during an incident, but honest pain is better than silent data loss.

---

## 8. Kafka read path and consumer groups

A consumer group lets many consumers share work.

```text
Topic: orders, 4 partitions

+-------------+       +-------------+
| Partition 0 | ----> | Consumer A  |
+-------------+       +-------------+

+-------------+       +-------------+
| Partition 1 | ----> | Consumer A  |
+-------------+       +-------------+

+-------------+       +-------------+
| Partition 2 | ----> | Consumer B  |
+-------------+       +-------------+

+-------------+       +-------------+
| Partition 3 | ----> | Consumer B  |
+-------------+       +-------------+
```

Within one consumer group, one partition is assigned to at most one active
consumer at a time.

This gives parallelism, but the upper bound is partition count.

```text
partitions: 4
consumers:  8

Useful active consumers in one group: 4
Idle consumers: 4
```

Different consumer groups are independent.

```text
                 +------------------+
                 | Topic: orders    |
                 +------------------+
                    |       |      |
                    v       v      v
                  fraud   search analytics
                  group   group  group
```

Each group has its own offsets.

```text
fraud offset:     10,000
search offset:     8,500
analytics offset:  1,200
```

This is one reason Kafka is powerful: slow analytics should not block fraud if
they are separate groups.

---

## 9. Offsets and commits

An offset is a position in a partition.

```text
Partition 2:

+-------+-------+-------+-------+-------+
|  100  |  101  |  102  |  103  |  104  |
+-------+-------+-------+-------+-------+
                    ^
                    |
              committed offset
```

Offset commits are progress markers. They are not proof that business work is
correct unless you commit at the right time.

### Bad: commit before processing

```text
1. poll record at offset 102
2. commit offset 103
3. process record
4. process crashes

Result:
  Kafka thinks offset 102 is done.
  Business side effect may be missing.
```

This is at-most-once behavior.

### Safer: process before commit

```text
1. poll record at offset 102
2. process record
3. commit offset 103
4. crash after processing but before commit

Result:
  record may be processed again.
```

This is at-least-once behavior. It requires idempotent consumers.

### Idempotent consumer pattern

```text
Consumer receives event_id = evt_123

BEGIN;
  INSERT INTO processed_events(event_id)
  VALUES ('evt_123')
  ON CONFLICT DO NOTHING;

  if row inserted:
    apply business change
  else:
    skip duplicate
COMMIT;
```

The key idea:

```text
Duplicates are normal.
Damage is optional.
```

---

## 10. Delivery guarantees

### At-most-once

```text
May lose messages.
Never intentionally processes one twice.
```

Good for:

```text
some metrics
some clickstream data
loss-tolerant telemetry
```

Bad for:

```text
orders
payments
inventory
security events
```

### At-least-once

```text
Should not lose messages.
May process duplicates.
```

This is the workhorse model for many production systems.

Needs:

```text
idempotency keys
dedupe tables
unique constraints
safe retries
reconciliation
```

### Effectively-once

```text
The infrastructure may deliver duplicates, but business state changes once.
```

Example:

```text
PaymentCaptured event is delivered twice.
Both attempts use same payment_id.
Database unique constraint allows one ledger entry.
Second attempt is a no-op.
```

### Exactly-once

Treat this phrase carefully.

Kafka can coordinate consumer offsets and Kafka writes in transactions for
read-process-write pipelines. That does not automatically control external side
effects.

```text
Kafka topic A -> stream processor -> Kafka topic B

This can be transactional inside Kafka.
```

```text
Kafka topic A -> consumer -> external payment API

Payment provider is outside Kafka.
You need idempotency and reconciliation.
```

Interview-grade sentence:

```text
Kafka exactly-once is a scoped guarantee, not a business guarantee.
For external side effects, I design for at-least-once delivery with idempotent
handlers and reconciliation.
```

---

## 11. Partition key design

Partition key is one of the most important choices in Kafka.

### Good key: preserves required ordering

For order lifecycle:

```text
key = order_id

OrderCreated -> PaymentAuthorized -> Packed -> Shipped
```

All events for one order land on the same partition.

```text
Partition 9:

+---------------+-------------------+--------+---------+
| OrderCreated  | PaymentAuthorized | Packed | Shipped |
+---------------+-------------------+--------+---------+
```

### Bad key: destroys ordering

If key is random:

```text
OrderCreated       -> partition 1
PaymentAuthorized  -> partition 7
Packed             -> partition 3
Shipped            -> partition 5
```

Now the consumer cannot rely on Kafka partition ordering for one order.

### Bad key: creates hot partition

If key is product_id during a celebrity launch:

```text
key = product_id
product_id = SNKR-2026
traffic = 180,000 events/sec

All launch events go to one partition.
```

Clean view:

```text
Partition 0:   2K/s
Partition 1:   3K/s
Partition 2: 180K/s  <-- hot
Partition 3:   2K/s
```

Fix options:

```text
1. Key by order_id if order-level ordering is enough.
2. Key by customer_id if customer-level ordering is required.
3. Use product_id plus bucket if product-level ordering is not required.
4. Split hot entities onto dedicated topics only with clear ownership.
```

Bucketed key:

```text
key = product_id + ':' + hash(order_id) % 32
```

This spreads load but sacrifices strict total ordering for the product.
That is often acceptable for analytics. It is often not acceptable for ledger
updates.

---

## 12. Consumer lag

Consumer lag is the distance between the latest produced offset and the
consumer group's committed offset.

```text
Log end offset:       1,000,000
Committed offset:       850,000
Lag:                   150,000 records
```

Lag by itself is not enough. You need lag slope and business delay.

```text
Producer rate:  20,000 records/sec
Consumer rate:  15,000 records/sec
Lag growth:      5,000 records/sec

After 10 minutes:
  5,000 * 600 = 3,000,000 records behind
```

If the consumer can process 15,000 records/sec:

```text
Catch-up time:
  3,000,000 / 15,000 = 200 seconds
```

But if producers keep writing at 20,000/sec, the consumer never catches up.
You need more throughput or less input.

### Useful lag questions

```text
Is lag growing everywhere or one partition?
Is lag caused by consumer CPU, downstream latency, or poison messages?
Did a deploy change processing time?
Did a rebalance freeze partitions?
Is the consumer committing offsets too slowly or too early?
Is the lag business-critical or analytics-only?
```

### Lag patterns

```text
All partitions lag:
  consumer fleet too small
  downstream dependency slow
  broker/network issue
  bad deploy

One partition lags:
  hot key
  poison message
  skewed partition assignment
  single slow downstream entity

Lag sawtooth:
  periodic batch job
  GC pauses
  rebalance churn
  scheduled downstream throttling
```

---

## 13. Rebalancing

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

Rebalancing is normal, but churn is dangerous.

Causes:

```text
consumer crash
new consumer joins
consumer misses heartbeat
processing exceeds max poll interval
network pause
GC pause
rolling deploy
autoscaler flapping
```

Failure shape:

```text
Consumer takes too long processing batch.
It does not poll in time.
Group marks it dead.
Rebalance starts.
Partitions pause.
Lag grows.
New assignment starts.
Same slow batch repeats.
```

SRE smell:

```text
consumer group rebalances spike
lag grows during deploy
processing time p99 approaches max.poll.interval.ms
```

Safe design:

```text
- keep processing bounded
- use pause/resume for slow downstreams
- use static membership where appropriate
- avoid autoscaler flapping
- deploy consumers in small waves
- watch rebalance rate during releases
```

---

## 14. Production failure patterns

### Failure 1: consumer lag from slow downstream

What happens:

```text
Kafka is healthy.
Consumer code is healthy enough to poll.
Downstream database or API is slow.
Lag grows.
```

Diagram:

```text
Kafka -> Consumer -> OpenSearch
          fast       slow
```

Symptoms:

```text
consumer lag rising
consumer CPU low or moderate
downstream p95/p99 high
consumer throughput falls
business read model stale
```

Detect:

```bash
kafka-consumer-groups --bootstrap-server broker:9092 \
  --describe --group search-indexer
```

Also check downstream:

```text
OpenSearch indexing queue
PostgreSQL write latency
HTTP dependency p99
Redis command latency
```

Immediate mitigation:

```text
1. Stop blaming Kafka first.
2. Identify slow dependency.
3. Reduce batch size if downstream is overloaded.
4. Shed non-critical consumers if they compete for the same dependency.
5. Pause low-priority indexing if critical consumers need capacity.
```

Long-term fix:

```text
- separate critical and non-critical consumer groups
- add backpressure
- rate limit downstream writes
- bulk efficiently
- define lag SLO by business workflow
```

### Failure 2: poison message blocks a partition

What happens:

```text
One record always crashes the consumer.
The consumer retries the same offset forever.
That partition stops progressing.
Other partitions look fine.
```

Diagram:

```text
Partition 4:

+------+---------+------+------+
| 100  |   101   | 102  | 103  |
+------+---------+------+------+
          ^
          |
      poison record
```

Symptoms:

```text
one partition lag grows
same offset in logs repeatedly
same event_id fails repeatedly
consumer restarts or retries forever
```

Immediate mitigation:

```text
1. Capture the bad record payload and headers.
2. Move it to DLQ with original topic, partition, offset, and error.
3. Advance past it only with audit trail.
4. Keep processing later records if ordering rules allow it.
```

Dangerous move:

```text
Blindly skip offsets without preserving the bad record.
That creates an invisible data-loss pocket.
```

Long-term fix:

```text
- schema validation before publish
- contract tests
- DLQ replay tool
- idempotent handlers
- alert on repeated failure for same offset
```

### Failure 3: retry storm

What happens:

```text
Downstream fails.
Consumers retry immediately.
Retries amplify load.
Downstream cannot recover.
Lag grows.
```

Clean shape:

```text
Consumer -> API fails
Consumer -> retry now
Consumer -> retry now
Consumer -> retry now

API gets more traffic while already broken.
```

Fix:

```text
- exponential backoff with jitter
- retry topic with delay
- circuit breaker for downstream
- DLQ after bounded attempts
- do not retry permanent validation errors
```

### Failure 4: bad partition key creates hot partition

What happens:

```text
One key receives most events.
One partition gets most traffic.
Adding consumers does not help because one partition has one owner.
```

Symptoms:

```text
one partition has huge lag
one consumer hot
broker hosting leader for hot partition has high network or disk
other consumers idle
```

Immediate mitigation:

```text
1. Confirm skew by partition metrics.
2. Reduce producer rate for hot key if possible.
3. Move non-critical consumers away from impacted brokers.
4. Avoid repartitioning in panic unless playbook exists.
```

Long-term fix:

```text
- redesign key
- bucket hot key
- split topic by workload
- model ordering requirement explicitly
```

### Failure 5: retention deletes data before replay

What happens:

```text
Consumer is down longer than topic retention.
Old records expire.
Consumer returns and cannot replay missing data.
```

Example:

```text
retention:       24 hours
consumer outage: 36 hours
lost replay:     12 hours
```

Fix:

```text
- set retention based on worst-case recovery time
- alert when consumer lag age approaches retention
- store authoritative data elsewhere
- snapshot read models for faster rebuilds
```

### Failure 6: compaction misunderstood as deletion

Log compaction keeps the latest value per key eventually. It is not immediate
delete semantics.

```text
key=user-1 value=A
key=user-1 value=B
key=user-1 value=C

After compaction, Kafka may keep only C for user-1.
```

Use compaction for:

```text
latest user profile
latest feature flag
latest account settings
```

Do not use it as your only audit log if every historical change matters.

### Failure 7: schema change breaks consumers

What happens:

```text
Producer deploys new event field or removes old field.
Old consumer cannot deserialize or misinterprets payload.
```

Safer evolution:

```text
- add optional fields first
- do not rename without compatibility plan
- do not change meaning of existing fields
- version schemas
- test old consumers against new events
```

SRE smell:

```text
deserialization errors spike right after producer deploy
lag begins in all partitions
DLQ fills with same schema version
```

---

## 15. SRE diagnostic toolkit

### Kafka topic and partition shape

```bash
kafka-topics --bootstrap-server broker:9092 \
  --describe --topic orders
```

Look for:

```text
partition count
replication factor
leader distribution
ISR count
under-replicated partitions
```

### Consumer group lag

```bash
kafka-consumer-groups --bootstrap-server broker:9092 \
  --describe --group fraud-service
```

Interpretation:

```text
CURRENT-OFFSET  = committed group offset
LOG-END-OFFSET  = newest available offset
LAG             = LOG-END-OFFSET - CURRENT-OFFSET
CONSUMER-ID     = assigned consumer
HOST            = consumer host
```

### Broker health questions

```text
Are partitions under-replicated?
Are offline partitions present?
Is ISR shrinking?
Is produce latency rising?
Is fetch latency rising?
Is disk nearly full?
Is controller stable?
```

### Consumer health questions

```text
Is processing p99 rising?
Is poll interval close to max.poll.interval.ms?
Are rebalances frequent?
Are errors concentrated by schema version?
Are retries bounded?
Is DLQ growing?
```

### Key metrics to dashboard

```text
broker request latency
produce request rate
fetch request rate
under-replicated partitions
offline partitions
ISR shrink/expand rate
consumer lag by group and partition
consumer lag age
rebalance rate
consumer processing latency
DLQ records/sec
producer error rate
producer record retry rate
```

Dashboards should show lag by partition, not only total lag. Total lag hides
single-partition disasters.

---

## 16. Decision framework

```text
+------------------------------+-------------------------------+
| Requirement                  | Likely choice                 |
+------------------------------+-------------------------------+
| One job, one worker          | SQS, RabbitMQ, task queue     |
| Rich routing                 | RabbitMQ                      |
| Many consumers, replay       | Kafka, Pulsar, Kinesis        |
| CDC backbone                 | Kafka                         |
| Simple managed queue         | SQS                           |
| Ultra-low-latency ephemeral  | NATS                          |
| Small app background jobs    | Sidekiq, Celery, SQS          |
| Rebuild read models          | Kafka-style durable log       |
| Strict immediate response    | Direct RPC                    |
+------------------------------+-------------------------------+
```

Kafka is the right answer when the log matters.

Ask:

```text
Do I need replay?
Do multiple independent consumers need the same event?
Do I need partition-level ordering?
Will consumer lag be an acceptable operational state?
Can I operate schema evolution?
Can I handle duplicates?
Can I design a sane partition key?
```

If the answer to most of those is no, Kafka may be cathedral-grade machinery
for a garden shed.

---

## 17. Real-world architecture example

E-commerce checkout:

```text
                         synchronous
+--------+      +------+      +----------+
| Client | ---> | API  | ---> | OrdersDB |
+--------+      +------+      +----------+
                    |
                    | OrderPlaced event
                    v
              +------------+
              | Kafka      |
              | orders     |
              +------------+
                |    |    |
                |    |    +--> Analytics consumer
                |    +-------> Search indexer
                +------------> Email consumer
```

Correct boundary:

```text
Must be synchronous:
  validate cart
  reserve inventory if required by product rules
  authorize payment if checkout cannot proceed without it
  write authoritative order

Can be asynchronous:
  send email
  update search index
  analytics
  recommendations
  warehouse notification if delay is acceptable
```

If email is down:

```text
Order should still be placed.
Email consumer lag grows.
Customer can still view order from authoritative DB.
```

If payment is down:

```text
Do not place paid order unless business allows pending payment.
This is not a Kafka problem. This is a consistency policy.
```

---

## 18. Hardcore SRE scenario

Incident:

```text
Severity: P1
System: E-commerce platform
Event: celebrity shoe launch
Topic: orders.events
Partitions: 48
Replication factor: 3
Critical consumers: fraud-service, inventory-projector, search-indexer
```

Architecture:

```text
+---------+      +----------+      +-------------+
| Checkout| ---> | OrdersDB | ---> | Outbox/CDC  |
+---------+      +----------+      +-------------+
                                      |
                                      v
                                 +---------+
                                 | Kafka   |
                                 +---------+
                                  |   |   |
                                  |   |   +--> search-indexer
                                  |   +------> inventory-projector
                                  +----------> fraud-service
```

Baseline:

```text
produce rate:               8,000 events/sec
fraud lag:                  < 5,000 records
inventory-projector lag:    < 2,000 records
search-indexer lag:         < 50,000 records
rebalance rate:             near zero
DLQ rate:                   near zero
```

At 20:08:

```text
produce rate:               55,000 events/sec
fraud lag:                  90,000 records and stable
inventory-projector lag:    7,800,000 records and growing
search-indexer lag:         24,000,000 records and growing
DLQ rate:                   0
rebalance rate:             120/hour
```

Partition lag sample:

```text
partition 03:       12,000
partition 04:       10,500
partition 05:    7,400,000  <-- bad
partition 06:       11,000
partition 07:       13,200
```

Recent change:

```text
Producer partition key changed from order_id to product_id.
Launch product_id = SNKR-2026.
Inventory projector requires per-order ordering, not per-product ordering.
Search indexer calls OpenSearch synchronously for every event.
Consumers were autoscaled from 24 to 96 during the incident.
```

Questions:

```text
1. What is the root cause?
2. Why did autoscaling consumers not fix inventory lag?
3. Which system is the bottleneck for search-indexer?
4. What is the immediate mitigation?
5. What should not be done?
6. What is the long-term architecture fix?
```

Expected expert answer:

```text
Root cause:
  The partition key change created a hot partition. All launch events for
  SNKR-2026 land on one partition. One partition can be owned by only one
  consumer in a group, so adding consumers does not increase throughput for
  that partition.

Why autoscaling failed:
  48 partitions cap useful consumer parallelism at 48 per group. The hot
  partition still has one owner. Autoscaling to 96 increased group churn and
  rebalance rate, which made lag worse.

Search-indexer bottleneck:
  OpenSearch is likely the downstream bottleneck if Kafka fetch is fine but
  processing time is dominated by synchronous indexing calls. Check indexing
  queue, bulk rejection, JVM heap, and p99 indexing latency.

Immediate mitigation:
  1. Stop further autoscaling churn.
  2. Roll back producer partition key to order_id if safe.
  3. If rollback changes ordering expectations, create a corrected topic and
     route new events there with an explicit cutover marker.
  4. Pause non-critical search indexing if it competes with inventory.
  5. Protect inventory projector because it affects customer-visible stock.
  6. Communicate that search freshness is degraded, not order authority.

Do not:
  - randomly increase partitions during P1 without a migration plan
  - skip offsets without preserving records
  - delete topic data to reduce lag
  - treat total lag as enough evidence
  - assume exactly-once semantics will fix an external indexing backlog

Long-term fix:
  - partition by the entity that requires ordering
  - load test launch-key skew
  - alert on per-partition lag skew
  - separate critical and non-critical consumers
  - use bulk indexing and backpressure for search
  - add schema and producer-key contract checks before deployment
```

---

## 19. Key takeaways

```text
1. Kafka is a durable partitioned log, not a normal task queue.
2. Ordering is per partition, so partition-key design is correctness design.
3. Consumer lag is a business delay signal, not merely a Kafka metric.
4. At-least-once plus idempotency is the default safe production posture.
5. Exactly-once has scope; external side effects still need dedupe and repair.
6. More consumers do not help one hot partition.
7. DLQs are evidence lockers, not trash cans.
8. Retention must exceed realistic recovery and replay windows.
9. Messaging decouples failures, but it also creates new operational state.
10. Choose Kafka when replay, fanout, and durable ordering are worth the cost.
```

---

## 20. Targeted reading

Read these with a purpose, not as link collecting:

```text
Kafka documentation:
  - Introduction and core concepts
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

Extraction questions:

```text
1. What is the smallest ordering guarantee my feature truly needs?
2. Which side effects must be synchronous and which can lag?
3. What is the maximum safe lag age for each consumer group?
4. How will I replay without duplicating business effects?
5. What dashboards prove the messaging layer is healthy?
```

---

## 21. Self-review checklist

```text
[ ] Did I distinguish task queue, pub/sub, and durable log?
[ ] Did I explain Kafka mechanics without pretending it is magic?
[ ] Did every diagram teach one idea and stay visually clean?
[ ] Did I include ordering, partitioning, lag, retries, DLQ, and replay?
[ ] Did I avoid overclaiming exactly-once semantics?
[ ] Did I include realistic SRE commands and diagnosis paths?
[ ] Did I connect this to prior topics: replication, sharding, consistency,
    caching, database scaling, and read models?
[ ] Did I avoid adding hands-on labs inside this roadmap file?
```
