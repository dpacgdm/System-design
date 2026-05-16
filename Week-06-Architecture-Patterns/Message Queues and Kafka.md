# Week 6, Topic 1: Message Queues and Kafka

Last verified: 2026-05-16

---

## Step 1: Learning Objectives

```text
+--------------------------------------------------------------------------+
| AFTER THIS TOPIC, YOU WILL BE ABLE TO:                                   |
+--------------------------------------------------------------------------+
|                                                                          |
| 1. Explain why messaging systems exist using real correctness and         |
|    reliability boundaries, not vague words like decoupling.              |
|                                                                          |
| 2. Distinguish task queues, publish/subscribe, and durable event logs     |
|    by the contract they provide and the failure modes they create.        |
|                                                                          |
| 3. Explain Kafka as a distributed, replicated, partitioned, append-only   |
|    commit log, including what that means on disk and over the network.    |
|                                                                          |
| 4. Trace a record from Python application code through serialization,     |
|    partition selection, producer batching, broker append, replication,    |
|    acknowledgement, consumer fetch, processing, and offset commit.        |
|                                                                          |
| 5. Explain the correctness impact of producer settings: acks, retries,    |
|    enable.idempotence, max.in.flight, linger.ms, batch.size,              |
|    compression.type, delivery.timeout.ms, and transactional.id.           |
|                                                                          |
| 6. Explain the correctness impact of consumer settings: group.id,         |
|    enable.auto.commit, auto.offset.reset, max.poll.records,               |
|    max.poll.interval.ms, session.timeout.ms, heartbeat.interval.ms,       |
|    isolation.level, and partition assignment strategy.                    |
|                                                                          |
| 7. Design partition keys using ordering, skew, future partition changes,  |
|    downstream locality, replay behavior, and incident blast radius.       |
|                                                                          |
| 8. Diagnose hot partitions, poison messages, lag growth, lag age,         |
|    rebalance storms, ISR shrink, DLQ spikes, retention risk, schema       |
|    breaks, connector lag, and downstream bottlenecks.                     |
|                                                                          |
| 9. Build idempotent consumers for search, ledgers, payments, email,       |
|    webhooks, warehouse requests, analytics, and cache invalidation.       |
|                                                                          |
| 10. Defend Kafka against alternatives such as SQS, RabbitMQ, Redis        |
|     Streams, NATS, Kinesis, and synchronous RPC using exact semantics.    |
|                                                                          |
+--------------------------------------------------------------------------+
```

---

## Step 2: Core Teaching

# Part A: Why Messaging Exists

Most people introduce messaging with the phrase "decoupling." That word is not wrong, but it is too soft. In production, messaging exists because real systems need to separate **when work is accepted** from **when every downstream reaction completes**.

MegaShop is the running architecture for this chapter. It is a Fortune 500 style e-commerce platform used for teaching. It sells physical goods globally, runs flash sales, accepts card payments, reserves inventory, sends customer notifications, updates search indexes, feeds fraud models, notifies warehouses, and publishes analytics.

Checkout is the core workflow. A checkout request touches money, inventory, fulfillment, customer trust, legal records, support tooling, search projections, and analytics. If every downstream action happens inside one synchronous request, checkout becomes hostage to every dependency.

```text
FULLY SYNCHRONOUS CHECKOUT

+----------+      +----------+      +----------+      +-----------+
|  Client  | ---> | Checkout | ---> | Payment  | ---> | Inventory |
+----------+      +----------+      +----------+      +-----------+
                       |
                       v
                  +----------+
                  | OrdersDB |
                  +----------+
                       |
                       v
                  +----------+
                  |  Email   |
                  +----------+
                       |
                       v
                  +----------+
                  |  Search  |
                  +----------+
                       |
                       v
                  +----------+
                  | Analytics|
                  +----------+

WHAT BREAKS:
  - Email provider latency becomes checkout latency.
  - Search index outage becomes checkout outage.
  - Analytics overload blocks revenue.
  - A non-critical side effect becomes part of user-facing availability.
```

A better design separates the critical path from side effects.

```text
CHECKOUT WITH A DURABLE ASYNC BOUNDARY

+----------+      +----------+      +----------+
|  Client  | ---> | Checkout | ---> | OrdersDB |
+----------+      +----------+      +----------+
                       |
                       | durable fact: OrderPlaced
                       v
                  +----------+
                  |  Kafka   |
                  +----------+
                    |   |   |
                    |   |   +----------> analytics-pipeline
                    |   +--------------> search-indexer
                    +------------------> email-sender

WHAT CHANGES:
  - Checkout waits for authoritative work.
  - Email/search/analytics become freshness problems instead of request latency.
  - Downstream teams consume facts independently.
  - The system must now observe lag, retries, DLQs, and replay safety.
```

The order database is authoritative for order existence. The payment ledger or provider is authoritative for payment state. The inventory service is authoritative for inventory reservation. Search is a projection. Analytics is a projection. Email is a notification side effect. Kafka is not automatically the source of truth. Kafka is a durable propagation and replay layer.

```text
+----------------------+------------------------------+--------------------------+
| System               | Role                         | Can it lag?              |
+----------------------+------------------------------+--------------------------+
| OrdersDB             | order existence authority    | no, not for checkout     |
| Payment provider     | payment authority            | no, not for payment      |
| Inventory service    | reservation authority        | usually no              |
| Kafka order-events   | propagation/replay layer     | yes, within SLO          |
| Search index         | derived projection           | yes                      |
| Analytics warehouse  | derived projection           | yes                      |
| Email provider       | notification side effect     | yes                      |
+----------------------+------------------------------+--------------------------+
```

Principal engineer rule:

```text
If returning success without an action would be a lie, that action belongs in the critical path or the response must expose pending state.

If returning success while the action continues is honest, the action can move behind messaging.
```

---

# Part B: Critical Path vs Side-Effect Path

A critical path contains operations that must finish before the system can honestly return success. A side-effect path contains work that can finish later without making the response false.

```text
MEGASHOP CHECKOUT CRITICAL PATH

1. Validate client idempotency key.
2. Validate cart contents.
3. Verify price against pricing authority.
4. Reserve inventory if overselling is not allowed.
5. Authorize payment if policy requires immediate payment confidence.
6. Write authoritative order row.
7. Write durable outbox row for OrderPlaced.
8. Commit transaction.
9. Return success with honest order state.
```

```text
MEGASHOP CHECKOUT SIDE-EFFECT PATH

1. Send receipt email.
2. Update search index.
3. Feed analytics pipeline.
4. Refresh recommendation features.
5. Update support timeline projection.
6. Notify warehouse if fulfillment can tolerate delay.
7. Enrich fraud model if fraud is advisory.
```

The same subsystem can move between paths depending business rules. Fraud is asynchronous for low-risk orders but synchronous for high-risk orders. Warehouse notification can be asynchronous for normal goods but synchronous for scarce inventory. Email is usually asynchronous, but if the product requires an email token before account activation, it may become critical.

```text
+--------------------------+--------------------------------+--------------------------+
| Operation                | Usually critical?              | Why                      |
+--------------------------+--------------------------------+--------------------------+
| order write              | yes                            | source of truth          |
| payment authorization    | yes, when required             | money risk               |
| inventory reservation    | yes, when oversell is harmful  | stock correctness        |
| receipt email            | no                             | notification             |
| search indexing          | no                             | projection               |
| analytics ingestion      | no                             | reporting/projection     |
| support timeline update  | no                             | operator projection      |
+--------------------------+--------------------------------+--------------------------+
```

What breaks when this is not explicit:

```text
FAILURE: Email provider outage blocks checkout.
CAUSE: Email was incorrectly placed in critical path.
SYMPTOM: Checkout p99 rises with email provider p99.
FIX: Move email behind durable message; add email freshness SLO.
SRE WATCH: email queue oldest age, provider timeout rate, DLQ rate.
```

---

# Part C: Three Messaging Models

Messaging systems are often described with one word: queue. That is too imprecise. Three models matter.

```text
+--------------------+------------------------------+-----------------------------+
| Model              | Core question                | MegaShop example            |
+--------------------+------------------------------+-----------------------------+
| Task queue         | Which worker handles job?    | SendReceiptEmail            |
| Publish/subscribe  | Who reacts to event?         | OrderPlaced fanout          |
| Durable event log  | Who can replay history?      | commerce.orders.events.v1   |
+--------------------+------------------------------+-----------------------------+
```

## Task Queue

A task queue distributes jobs. One logical job should be handled by one worker at a time. That does not mean the job can never run twice. It means the broker tries to prevent concurrent processing of the same job while preserving delivery if a worker dies.

```text
TASK QUEUE FLOW

+----------+      +-------------+      +----------+
| Producer | ---> | Task Queue  | ---> | Worker A |
+----------+      +-------------+      +----------+
                         |
                         +------->     +----------+
                                       | Worker B |
                                       +----------+

JOB EXAMPLE:
  SendReceiptEmail(order_id=ord_123, template=receipt_v3)
```

What it means:

```text
1. Producer creates a job.
2. Queue stores the job.
3. Worker receives the job.
4. Queue hides the job for a visibility timeout or lease period.
5. Worker performs the job.
6. Worker acknowledges success.
7. Queue removes or completes the job.
```

What breaks:

```text
CRASH AFTER SIDE EFFECT BEFORE ACK

T0  Worker receives SendReceiptEmail(ord_123).
T1  Worker calls email provider.
T2  Provider accepts email.
T3  Worker crashes before ACK.
T4  Visibility timeout expires.
T5  Queue redelivers job.
T6  Another worker sends duplicate email.

BROKER DID NOT FAIL:
  The broker preserved work.

APPLICATION FAILED:
  The worker did not make the side effect idempotent.
```

Correct worker design:

```text
1. Build idempotency key: receipt:ord_123:receipt_v3:customer_456.
2. Check durable sent marker.
3. If marker exists, ACK without sending again.
4. If marker does not exist, send email with provider idempotency if available.
5. Record sent marker.
6. ACK job.
```

SRE diagnostics:

```text
+------------------+--------------------------------------+--------------------------+
| Signal           | Meaning                              | Response                 |
+------------------+--------------------------------------+--------------------------+
| queue depth      | waiting job count                    | compare to drain rate    |
| oldest age       | user-visible delay                   | alert on SLO             |
| retry rate       | transient or code failure            | classify error           |
| DLQ rate         | bounded attempts exhausted           | triage and replay        |
| worker CPU       | worker-side saturation               | scale if sink can cope   |
| provider p99     | downstream bottleneck                | backoff, throttle        |
+------------------+--------------------------------------+--------------------------+
```

Use task queues when one job should be handled by one worker. Do not use them as your primary replayable history if many consumers need independent replay.

## Publish/Subscribe

Publish/subscribe fans out events. One published event can be consumed by many independent subscribers.

```text
PUB/SUB FLOW

+----------+      +-------------+      +----------+
| Orders   | ---> | OrderPlaced | ---> | Email    |
+----------+      +-------------+      +----------+
                         |
                         +------->     +----------+
                         |             | Search   |
                         |             +----------+
                         |
                         +------->     +----------+
                                       | Analytics|
                                       +----------+
```

What it means:

```text
1. Producer publishes a business fact.
2. Broker or topic exposes it to subscribers.
3. Subscribers independently react.
4. Producer does not need direct code references to every consumer.
```

Event vs command:

```text
EVENT:
  OrderPlaced
  PaymentCaptured
  InventoryReserved
  These are facts that already happened.

COMMAND:
  SendReceiptEmail
  CapturePayment
  ReserveInventory
  These are requests for someone to do work.
```

What breaks:

```text
HIDDEN COUPLING

Producer publishes OrderPlaced.
Search depends on line_items.
Fraud depends on customer_id and device_id.
Analytics depends on total_cents and currency.
Warehouse depends on destination_region.
Producer removes destination_region because checkout no longer uses it.
Warehouse breaks.

CAUSE:
  Coupling moved from code calls to event schema.

FIX:
  Event ownership, schema compatibility, consumer discovery, and migration policy.
```

Use pub/sub when many systems react to one fact. Do not confuse lack of direct calls with lack of dependency.

## Durable Event Log

A durable event log stores retained history. Consumers track their own positions. Kafka is primarily this model.

```text
DURABLE LOG FLOW

Topic: commerce.orders.events.v1

+-------------+-------------------+-------------------+---------+-----------+
| OrderPlaced | PaymentAuthorized | InventoryReserved | Packed  | Shipped   |
+-------------+-------------------+-------------------+---------+-----------+
      0                1                   2              3          4

Consumer positions:
  fraud-service        offset 5
  search-indexer       offset 3
  analytics-pipeline   offset 1
```

What it means:

```text
1. Records remain after one consumer reads them.
2. Different consumer groups have independent offsets.
3. New consumers can replay history if retention permits.
4. Broken projections can be rebuilt from retained facts.
```

What breaks:

```text
UNSAFE REPLAY

Search replay is safe when document id = order_id.
Analytics replay is safe when event_id dedupe exists.
Email replay is unsafe without sent markers.
Payment command replay is unsafe without provider idempotency.
Warehouse request replay is unsafe without fulfillment_request_id.

DURABLE HISTORY DOES NOT MAKE CONSUMERS SAFE.
```

Use a durable log when replay, fanout, high throughput, and independent consumers matter. Do not use it just because it sounds advanced.

---

# Part D: Kafka Core Model

Kafka is a distributed, replicated, partitioned, append-only commit log.

```text
+----------------+----------------------------------------------------------+
| Word           | Meaning                                                  |
+----------------+----------------------------------------------------------+
| distributed    | records are spread across brokers                        |
| replicated     | partitions have multiple copies                          |
| partitioned    | topics are split into ordered shards                     |
| append-only    | records are appended, not updated in place               |
| commit log     | records are read by offset positions                     |
+----------------+----------------------------------------------------------+
```

Kafka is optimized for sequential writes, batching, compression, high-throughput fanout, and replay. Kafka is not a relational database. Kafka is not a global FIFO queue. Kafka is not a magical exactly-once side-effect engine.

```text
Topic: commerce.orders.events.v1

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

Most important rule:

```text
Kafka preserves order within a partition.
Kafka does not preserve total order across a multi-partition topic.
```

This is not a footnote. It controls partition-key design, consumer scaling, replay behavior, and incident diagnosis.

---

# Part E: Kafka Record Anatomy

A Kafka record has topic, partition, offset, key, value, timestamp, and headers. The producer supplies key, value, and headers. Kafka assigns partition and offset after partitioning and append.

```text
+------------+-------------------------------------------------------------+
| Component  | Meaning                                                     |
+------------+-------------------------------------------------------------+
| topic      | named stream, such as commerce.orders.events.v1             |
| partition  | ordered shard chosen by partitioner                         |
| offset     | position within that partition                              |
| key        | bytes used for partitioning and often ordering scope         |
| value      | serialized payload                                          |
| timestamp  | producer or broker timestamp                                |
| headers    | metadata such as event_type, schema_version, correlation_id  |
+------------+-------------------------------------------------------------+
```

Production event envelope:

```json
{
  "event_id": "evt_01HY_ORDER_PLACED_123",
  "event_type": "OrderPlaced",
  "schema_version": 3,
  "aggregate_type": "Order",
  "aggregate_id": "ord_123",
  "occurred_at": "2026-05-16T10:15:30Z",
  "published_at": "2026-05-16T10:15:31Z",
  "correlation_id": "req_abc",
  "causation_id": "cmd_checkout_123",
  "producer": "checkout-service",
  "payload": {
    "order_id": "ord_123",
    "customer_id": "cust_456",
    "total_cents": 129900,
    "currency": "USD"
  }
}
```

Why this metadata exists:

```text
event_id:
  Dedupe, audit, DLQ replay, support investigation.

schema_version:
  Lets consumers dispatch old and new schema handlers.

aggregate_id:
  Candidate partition key and ordering scope.

occurred_at:
  Business time.

published_at:
  Pipeline time. Difference from occurred_at shows publication delay.

correlation_id:
  Connects API request, logs, events, and downstream processing.

causation_id:
  Explains why this event exists.
```

Without this envelope, incidents become archaeology.

---

# Part F: Topic Design

A topic is not just a string. A topic is a production resource with ownership, retention, schema, security, partitioning, and operational policy.

```text
BAD TOPIC NAME:
  events

BETTER TOPIC NAME:
  commerce.orders.events.v1

WHY BETTER:
  commerce  -> domain
  orders    -> aggregate
  events    -> semantic type
  v1        -> compatibility boundary
```

Topic design review:

```text
+----------------------+---------------------------------------------------+
| Question             | Example answer                                    |
+----------------------+---------------------------------------------------+
| owner                | commerce-platform                                 |
| semantic type        | domain events                                     |
| schema format        | Avro or Protobuf                                  |
| compatibility        | backward compatible                               |
| partition key        | order_id                                          |
| promised ordering    | per order                                         |
| retention            | 14 days                                           |
| cleanup policy       | delete                                            |
| replication factor   | 3                                                 |
| min ISR              | 2                                                 |
| sensitivity          | customer/order data; restricted consumers         |
| criticality          | high                                              |
+----------------------+---------------------------------------------------+
```

What breaks without topic design:

```text
1. No owner means no one handles schema changes.
2. No retention policy means recovery windows are accidental.
3. No partition-key review means hot partitions surprise you during launches.
4. No ACL review means sensitive data leaks to casual consumers.
5. No criticality class means payment facts and debug noise get the same alerting.
```

Topic creation is not complete until the runbook exists.

---

# Part G: Partitions and Offsets

A partition is an ordered shard. An offset is a position inside that shard. Offsets are not global.

```text
Partition 0 offsets: 0, 1, 2, 3, 4
Partition 1 offsets: 0, 1, 2, 3, 4

Partition 0 offset 3 and Partition 1 offset 3 are unrelated records.
```

Why partitions exist:

```text
1. Parallel writes across partitions.
2. Parallel reads across partitions.
3. Per-key ordering inside a chosen partition.
4. Storage spread across brokers.
```

What breaks with too few partitions:

```text
Topic has 4 partitions.
Consumer group has 20 consumers.
Only 4 consumers actively process this topic.
16 consumers are idle for this topic.
Lag cannot improve beyond 4 active partition owners.
```

What breaks with too many partitions:

```text
1. More metadata.
2. More open files.
3. More leader elections during broker failure.
4. More rebalance work.
5. More operational overhead.
6. Potentially slower recovery.
```

Partition count is a capacity and operations decision. It should be sized from throughput, growth, ordering, and failure-recovery expectations.

---

# Part H: Log Segments and Index Files

A Kafka partition is stored as log segment files, not one infinite file. Each segment has a base offset. Kafka also maintains indexes.

```text
Partition directory example

+------------------------------------------------------------+
| 00000000000000000000.log        record batches             |
| 00000000000000000000.index      offset -> byte position    |
| 00000000000000000000.timeindex  timestamp -> offset        |
| 00000000000000004200.log        record batches             |
| 00000000000000004200.index      offset -> byte position    |
| 00000000000000004200.timeindex  timestamp -> offset        |
+------------------------------------------------------------+
```

How this works:

```text
1. Producer sends record batch.
2. Leader appends batch to active segment file.
3. Offset index allows Kafka to seek near a requested offset.
4. Time index allows lookup by timestamp.
5. Segment rolls when size or time threshold is reached.
6. Old segments become eligible for deletion or compaction.
```

What this explains:

```text
RETENTION SURPRISE:
  Kafka often deletes whole segments, not individual records one by one.
  If a segment still contains records that are not eligible, it may remain.

DISK SURPRISE:
  Disk usage includes log files, indexes, replication, overhead, and compaction lag.

REPLAY SURPRISE:
  Timestamp lookup is practical because Kafka has time indexes.
```

SRE interpretation:

```text
Disk usage depends on:
  - record rate
  - compressed record size
  - retention
  - replication factor
  - segment size
  - index overhead
  - compaction lag
  - uneven partition distribution
```

---

# Part I: Brokers, Replicas, ISR, and Leader Election

A broker is a Kafka server. A partition has replicas. One replica is leader. Followers replicate from the leader. Producers write to leaders. Consumers usually fetch from leaders unless follower fetching is deliberately used.

```text
+-----------+        +-----------+        +-----------+
| Broker 1  |        | Broker 2  |        | Broker 3  |
+-----------+        +-----------+        +-----------+
| P0 leader |        | P0 follow |        | P0 follow |
| P1 follow |        | P1 leader |        | P1 follow |
| P2 follow |        | P2 follow |        | P2 leader |
+-----------+        +-----------+        +-----------+
```

ISR means in-sync replicas. A replica in ISR is caught up enough to count for durability. With replication factor 3 and min.insync.replicas 2, acks=all writes require at least two in-sync replicas.

```text
HEALTHY:
  P0 leader = Broker 1
  P0 replicas = Broker 1, Broker 2, Broker 3
  P0 ISR = Broker 1, Broker 2, Broker 3

DEGRADED:
  P0 leader = Broker 1
  P0 replicas = Broker 1, Broker 2, Broker 3
  P0 ISR = Broker 1, Broker 2

DANGEROUS WITH min.insync.replicas=2:
  P0 leader = Broker 1
  P0 ISR = Broker 1
  acks=all writes should fail
```

Leader election:

```text
CLEAN ELECTION:
  Leader dies.
  Kafka elects an in-sync follower.
  Committed data is preserved.

UNCLEAN ELECTION:
  Leader dies.
  No in-sync follower is available.
  Kafka elects an out-of-sync replica if allowed.
  Availability may return, but acknowledged data can be lost.
```

MegaShop order-events disables unclean leader election for critical topics. Losing availability is bad. Losing acknowledged order facts is worse.

SRE signals:

```text
+-------------------------------+------------------------------------------+
| Signal                        | Meaning                                  |
+-------------------------------+------------------------------------------+
| under-replicated partitions   | replicas are not fully caught up         |
| offline partitions            | no leader; client impact                 |
| ISR shrink rate               | durability margin is shrinking           |
| leader election rate          | broker instability or maintenance churn  |
| produce request latency       | broker/disk/ISR/quota pressure           |
+-------------------------------+------------------------------------------+
```

---

# Part J: Producer Write Path

A producer write is not a single action. It is a pipeline.

```text
PRODUCER WRITE PATH

+-------------+      +------------+      +-------------+      +-------------+
| Application | ---> | Serializer | ---> | Partitioner | ---> | Accumulator |
+-------------+      +------------+      +-------------+      +-------------+
                                                                  |
                                                                  v
+-------------+      +-------------+      +-------------+      +-------------+
| Ack/Error   | <--- | Replication | <--- | Leader Log  | <--- | Sender      |
+-------------+      +-------------+      +-------------+      +-------------+
```

Step by step:

```text
1. Application creates event object.
2. Serializer turns key and value into bytes.
3. Partitioner chooses topic partition.
4. Producer accumulator groups records into batches by partition.
5. Sender thread sends ProduceRequest to leader broker.
6. Broker authenticates and authorizes request.
7. Broker verifies it is leader for the partition.
8. Broker appends record batch to log.
9. Followers replicate from leader.
10. Leader waits according to acks and ISR requirements.
11. Producer receives success or error.
12. Application callback or flush observes result.
```

What breaks:

```text
FIRE AND FORGET BUSINESS EVENT

Checkout writes order row.
Producer tries to publish OrderPlaced.
Publish fails.
Application ignores error.
User receives success.
Search, email, analytics, and warehouse never see the order.

CAUSE:
  Producer error was treated as noise.

FIX:
  Use outbox for authoritative events or make publish failure part of response logic.
```

---

# Part K: Producer Configuration

Producer settings are correctness settings, not only performance settings.

```text
+-----------------------------------+-----------------------------------------+
| Setting                           | What it controls                        |
+-----------------------------------+-----------------------------------------+
| acks                              | when write is successful                |
| enable.idempotence                | duplicate append protection             |
| retries                           | retry transient failures                |
| max.in.flight.requests.per.conn   | concurrent unacked requests             |
| linger.ms                         | wait to build batches                   |
| batch.size                        | target batch size per partition         |
| compression.type                  | network and storage efficiency          |
| delivery.timeout.ms               | total send deadline                     |
| request.timeout.ms                | broker request timeout                  |
| transactional.id                  | transaction identity and fencing        |
+-----------------------------------+-----------------------------------------+
```

Business-critical baseline example:

```properties
acks=all
enable.idempotence=true
compression.type=lz4
linger.ms=5
batch.size=65536
delivery.timeout.ms=120000
request.timeout.ms=30000
max.in.flight.requests.per.connection=5
```

Interpretation:

```text
acks=all:
  Wait for ISR durability condition.

enable.idempotence=true:
  Prevent duplicate appends caused by producer retry ambiguity.

linger.ms=5:
  Allow tiny delay to form better batches.

compression.type=lz4:
  Reduce network and disk with low CPU overhead.

delivery.timeout.ms=120000:
  Bound total time a send may take before failure.
```

Do not copy settings blindly. Low-latency order events, high-volume clickstream, and batch analytics have different tradeoffs.

---

# Part L: Producer Acknowledgements

acks decides when the producer is told a write succeeded.

```text
acks=0
  Producer does not wait for broker acknowledgement.
  Fastest.
  Can silently lose records.

acks=1
  Leader acknowledges after local append.
  Can lose records if leader dies before followers replicate.

acks=all
  Leader waits for ISR condition.
  Safer for important events.
  Can fail when ISR is insufficient.
```

acks=1 failure timeline:

```text
T0  Producer sends OrderPlaced(ord_123).
T1  Leader appends record locally.
T2  Leader returns success.
T3  Leader crashes before follower replication.
T4  New leader is elected without the record.
T5  Producer believes record exists.
T6  Downstream consumers never see it.
```

acks=all with replication.factor=3 and min.insync.replicas=2:

```text
T0  Producer sends record.
T1  Leader appends record.
T2  At least one follower in ISR replicates.
T3  ISR durability condition is satisfied.
T4  Leader returns success.
```

If ISR falls below 2, the write fails. That is not Kafka being annoying. It is Kafka refusing to lie about durability.

---

# Part M: Producer Idempotence and Ordering

Producer idempotence handles retry ambiguity.

```text
WITHOUT IDEMPOTENCE

T0  Producer sends batch B.
T1  Broker appends batch B.
T2  Ack is lost.
T3  Producer retries batch B.
T4  Broker appends batch B again.

RESULT:
  Duplicate records in Kafka.
```

```text
WITH IDEMPOTENCE

T0  Producer sends batch B with producer id and sequence number.
T1  Broker appends sequence 42.
T2  Ack is lost.
T3  Producer retries sequence 42.
T4  Broker recognizes duplicate sequence.

RESULT:
  Duplicate append avoided.
```

Scope warning:

```text
Producer idempotence protects Kafka from duplicate appends caused by producer retry.
It does not protect email, payment, warehouse, search, or database side effects.
Consumer idempotency is still required.
```

Ordering warning:

```text
Ordering depends on partition, producer behavior, retries, and concurrent in-flight requests.
Business ordering can also be broken before Kafka if multiple services race to emit events for the same aggregate.
Kafka partition order is not a replacement for workflow ownership.
```

---

# Part N: Python Producer Example

This example is conceptual. Exact APIs differ by client library. The important parts are stable event identity, stable partition key, schema version, headers, and error visibility.

```python
import json
from datetime import datetime, timezone

class PublishFailed(Exception):
    pass

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def build_order_placed(order: dict, correlation_id: str) -> dict:
    return {
        "event_id": f"evt_order_placed_{order['id']}",
        "event_type": "OrderPlaced",
        "schema_version": 3,
        "aggregate_type": "Order",
        "aggregate_id": order["id"],
        "occurred_at": utc_now(),
        "published_at": utc_now(),
        "correlation_id": correlation_id,
        "causation_id": f"cmd_checkout_{order['id']}",
        "producer": "checkout-service",
        "payload": {
            "order_id": order["id"],
            "customer_id": order["customer_id"],
            "total_cents": order["total_cents"],
            "currency": order["currency"],
        },
    }

def publish_order_placed(producer, order: dict, correlation_id: str) -> None:
    event = build_order_placed(order, correlation_id)
    key = event["aggregate_id"].encode("utf-8")
    value = json.dumps(event, separators=(",", ":")).encode("utf-8")

    producer.produce(
        topic="commerce.orders.events.v1",
        key=key,
        value=value,
        headers={
            "event_type": event["event_type"],
            "schema_version": str(event["schema_version"]),
            "correlation_id": event["correlation_id"],
        },
        on_delivery=lambda err, msg: (_raise(err) if err else None),
    )
    producer.flush()

def _raise(err):
    if err is not None:
        raise PublishFailed(str(err))
```

What this teaches:

```text
1. key = order_id preserves per-order ordering.
2. event_id supports dedupe and audit.
3. schema_version supports compatibility.
4. correlation_id supports tracing.
5. delivery errors must be observed.
6. For authoritative order events, outbox is usually safer than direct publish.
```

---

# Part O: Consumer Read Path

Consumer processing is where Kafka delivery meets business correctness.

```text
CONSUMER READ PATH

+----------+      +----------+      +-------------+      +------------+
| Kafka    | ---> | Consumer | ---> | Transform   | ---> | Side Effect|
| partition|      | poll     |      | event -> op |      | system     |
+----------+      +----------+      +-------------+      +------------+
                       |
                       v
                 commit offset
```

Step by step:

```text
1. Consumer joins group.
2. Group coordinator assigns partitions.
3. Consumer fetches record batches.
4. Client deserializes records.
5. Application validates schema and event type.
6. Application performs side effect.
7. Application commits offset after work is safe.
```

What breaks:

```text
COMMIT BEFORE SIDE EFFECT

T0  Consumer polls offset 102.
T1  Consumer commits offset 103.
T2  Consumer starts writing search document.
T3  Consumer crashes before write succeeds.
T4  Consumer restarts from offset 103.
T5  Offset 102 is skipped forever.

RESULT:
  Search projection misses an order.
```

Preferred model for business events:

```text
Process first.
Make side effect idempotent.
Commit after safe processing.
Accept possible duplicate attempts.
Prevent duplicate business damage.
```

---

# Part P: Consumer Groups and Rebalancing

A consumer group shares partitions across consumers. Each partition is assigned to at most one active consumer in that group.

```text
Topic: commerce.orders.events.v1
Partitions: 6
Group: search-indexer

+-------------+      +------------+
| Partition 0 | ---> | Consumer A |
| Partition 1 | ---> | Consumer A |
+-------------+      +------------+

+-------------+      +------------+
| Partition 2 | ---> | Consumer B |
| Partition 3 | ---> | Consumer B |
+-------------+      +------------+

+-------------+      +------------+
| Partition 4 | ---> | Consumer C |
| Partition 5 | ---> | Consumer C |
+-------------+      +------------+
```

If a topic has 6 partitions and a group has 10 consumers, only 6 consumers can actively process that topic. The rest are idle for that topic.

Rebalancing:

```text
1. Consumer joins or leaves group.
2. Coordinator detects membership change.
3. Partitions are reassigned.
4. Consumers revoke old partitions and acquire new ones.
5. Processing may pause depending protocol and assignor.
```

Rebalance storm failure:

```text
T0  Lag rises.
T1  Autoscaler adds many consumers.
T2  Group rebalances.
T3  Processing pauses.
T4  Lag rises more.
T5  Autoscaler adds more consumers.
T6  Rebalance loop continues.
```

Mitigation:

```text
1. Deploy in small waves.
2. Use cooperative rebalancing where appropriate.
3. Use static membership where appropriate.
4. Do not autoscale on lag alone.
5. Include downstream capacity and rebalance rate in scaling decisions.
```

---

# Part Q: __consumer_offsets

Kafka stores committed offsets in an internal compacted topic named __consumer_offsets. This means offset commits are themselves Kafka records.

```text
Offset commit key:
  group = search-indexer
  topic = commerce.orders.events.v1
  partition = 17

Offset commit value:
  committed_offset = 8819232
  metadata = optional client metadata
  commit_timestamp = 2026-05-16T10:20:00Z
```

Why this matters:

```text
1. group.id is a production identity.
2. Changing group.id creates a new offset namespace.
3. New groups start according to auto.offset.reset.
4. auto.offset.reset=latest can skip history.
5. auto.offset.reset=earliest can replay huge history.
6. Offset commit latency can cause duplicate processing after crashes.
```

Production rule:

```text
Never change group.id casually.
Changing group.id is a replay or cutover operation.
```

---

# Part R: Consumer Configuration

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
isolation.level=read_committed
```

Explanation:

```text
group.id:
  Consumer group identity and offset namespace.

enable.auto.commit=false:
  Application decides when work is safe.

auto.offset.reset=earliest:
  Start from beginning if no offset exists.
  Dangerous if accidental new group causes huge replay.

auto.offset.reset=latest:
  Start from newest if no offset exists.
  Dangerous if accidental new group misses history.

max.poll.records:
  Batch size. Too high can exceed processing interval.

max.poll.interval.ms:
  Max time between polls before consumer is considered stuck.

session.timeout.ms:
  Failure detection window.

heartbeat.interval.ms:
  Heartbeat frequency.

isolation.level=read_committed:
  Hide aborted transactional records.
```

Failure example:

```text
max.poll.records too high.
Consumer gets 10,000 records.
Processing takes 12 minutes.
max.poll.interval.ms is 5 minutes.
Consumer is removed from group.
Group rebalances.
Records are reassigned.
Duplicates and lag spike appear.
```

---

# Part S: Python Consumer Example

```python
import json
from typing import Any

class PermanentError(Exception):
    pass

class TransientError(Exception):
    pass

def build_search_document(event: dict[str, Any]) -> dict[str, Any]:
    payload = event["payload"]
    return {
        "order_id": payload["order_id"],
        "customer_id": payload["customer_id"],
        "total_cents": payload["total_cents"],
        "currency": payload["currency"],
        "occurred_at": event["occurred_at"],
    }

def process_order_placed(record, search_client, dlq_producer) -> str:
    try:
        event = json.loads(record.value)
        if event.get("event_type") != "OrderPlaced":
            return "ignored"
        if event.get("schema_version") not in (2, 3):
            raise PermanentError("unsupported schema version")
        doc = build_search_document(event)
        search_client.index(index="orders", id=doc["order_id"], document=doc)
        return "processed"
    except PermanentError as exc:
        publish_dlq(record, exc, dlq_producer)
        return "dlq"

def publish_dlq(record, exc: Exception, producer) -> None:
    payload = {
        "original_topic": record.topic,
        "original_partition": record.partition,
        "original_offset": record.offset,
        "key": record.key.decode("utf-8") if record.key else None,
        "headers": dict(record.headers or []),
        "error_class": type(exc).__name__,
        "error_message": str(exc),
        "payload": record.value.decode("utf-8", errors="replace"),
    }
    producer.produce(
        topic="search-indexer.dlq.v1",
        key=record.key,
        value=json.dumps(payload).encode("utf-8"),
    )
```

Why this is safe for search:

```text
1. Search document ID is order_id.
2. Reprocessing same event overwrites same document.
3. Permanent schema errors go to DLQ with original context.
4. Offset should be committed after processed or intentionally DLQ-handled.
```

Why this is not enough for payments:

```text
Search overwrite is naturally idempotent.
Payment capture is not.
Payment needs provider idempotency key and reconciliation.
```

---

# Part T: Delivery Guarantees

## At-Most-Once

At-most-once may lose work. It avoids duplicates by committing before processing or otherwise not retrying after uncertainty.

```text
T0  Consumer polls offset 102.
T1  Consumer commits offset 103.
T2  Consumer crashes before side effect.
T3  Consumer restarts from 103.
T4  Offset 102 is lost from business processing.
```

Use for low-value telemetry only when loss is acceptable. Do not use for orders, payments, inventory, security, or ledger facts.

## At-Least-Once

At-least-once avoids intentional loss but may duplicate attempts.

```text
T0  Consumer polls offset 102.
T1  Consumer writes side effect.
T2  Consumer crashes before commit.
T3  Consumer restarts from 102.
T4  Consumer writes side effect again.
```

This is the default serious posture for many business consumers. It requires idempotency.

## Effectively-Once

Effectively-once means transport may duplicate but business state changes once.

```sql
CREATE TABLE ledger_entries (
  event_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  amount_cents BIGINT NOT NULL,
  currency TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL
);
```

If PaymentCaptured evt_123 is delivered twice, only one ledger row can exist. The database invariant protects business state.

## Kafka Exactly-Once

Kafka transactions can coordinate Kafka reads, Kafka writes, and offset commits inside Kafka.

```text
Kafka transaction can include:
  - output records to topic B
  - consumed offsets from topic A

Kafka transaction cannot automatically include:
  - Stripe charge
  - email send
  - warehouse shipment
  - arbitrary external API
```

Correct sentence:

```text
Kafka exactly-once is scoped. External side effects still require idempotency and reconciliation.
```

---

# Part U: Idempotency Patterns

```text
+---------------------+--------------------------------------+--------------------------+
| Side effect         | Idempotency strategy                 | Failure prevented        |
+---------------------+--------------------------------------+--------------------------+
| Search index        | document id = order_id               | duplicate documents      |
| Ledger entry        | unique event_id                      | double accounting        |
| Email receipt       | order_id + template + recipient      | duplicate receipt        |
| Webhook delivery    | event_id + destination_id            | duplicate seller call    |
| Payment capture     | provider idempotency key             | double charge            |
| Warehouse request   | fulfillment_request_id               | duplicate shipment       |
| Analytics event     | event_id dedupe                      | double counting          |
| Cache invalidation  | naturally repeatable operation       | usually harmless repeat  |
+---------------------+--------------------------------------+--------------------------+
```

Idempotency key rules:

```text
1. Use business operation identity.
2. Do not use timestamp.
3. Do not use retry attempt ID.
4. Do not use process ID.
5. Store dedupe state durably when side effect is durable.
6. Reconcile external providers after ambiguous outcomes.
```

Payment ambiguity example:

```text
T0  Consumer sends capture request to provider.
T1  Provider captures money.
T2  Network timeout occurs before response reaches consumer.
T3  Consumer does not know if capture happened.
T4  Blind retry without idempotency may double charge.

SAFE DESIGN:
  - stable provider idempotency key
  - query provider by payment_intent_id
  - internal state PAYMENT_UNKNOWN or RECONCILING
  - ledger uniqueness by event_id
```

---

# Part V: Partition Key Design

Partition key controls ordering and load distribution.

```text
Conceptual model:
  partition = hash(key) % partition_count
```

Kafka client details can vary, but the design point remains: key selection chooses the lane.

Good key for order lifecycle:

```text
key = order_id

Partition 8
+-------------+-------------------+-------------------+--------+---------+
| OrderPlaced | PaymentAuthorized | InventoryReserved | Packed | Shipped |
+-------------+-------------------+-------------------+--------+---------+

PROMISE:
  Events for one order are ordered.

NON-PROMISE:
  All orders are globally ordered.
```

Bad key for flash-sale order stream:

```text
key = product_id
product_id = SNKR-2026

+-------------+-------------+
| Partition   | Traffic     |
+-------------+-------------+
| 0           |   3K/sec    |
| 1           |   2K/sec    |
| 2           | 180K/sec    |
| 3           |   4K/sec    |
+-------------+-------------+

RESULT:
  One hot partition.
  One active consumer per group for that partition.
  Scaling consumers does not split it.
```

Bucketed key:

```text
key = product_id + ':' + hash(order_id) % 32

BENEFIT:
  Spreads one hot product across buckets.

COST:
  No strict total ordering for product_id.
```

Design question:

```text
What is the smallest entity that truly requires ordering?
```

---

# Part W: Adding Partitions Later

Adding partitions is not a harmless button.
Existing records do not move. New records may map differently. Key-to-partition mapping can change when partition count changes.

```text
Before expansion:
  partition_count = 12
  key ord_123 -> partition 7

After expansion:
  partition_count = 48
  key ord_123 -> partition 19

POSSIBLE RESULT:
  old records for ord_123 in partition 7
  new records for ord_123 in partition 19
  per-order ordering across expansion boundary is no longer automatic
```

Implication:

```text
1. Partition expansion needs review.
2. Hot partition incidents are not always fixed by adding partitions.
3. Existing hot backlog remains where it is.
4. Major key changes may require a new topic and controlled migration.
```

---

# Part X: Consumer Lag

Consumer lag is log end offset minus committed offset per partition per group.

```text
log end offset:       1,000,000
committed offset:       850,000
lag:                   150,000 records
```

Lag growth math:

```text
producer rate:   50,000 records/sec
consumer rate:   35,000 records/sec
lag growth:      15,000 records/sec
10 minutes:       9,000,000 records behind
```

Catch-up math if producers stop:

```text
lag:             9,000,000 records
consumer rate:      35,000 records/sec
catch-up time:          257 seconds
```

If producers continue at 50,000/sec and consumers process 35,000/sec, catch-up never happens.

Lag age:

```text
5,000,000 records behind at 500,000/sec = 10 seconds behind.
5,000,000 records behind at 100/sec     = almost 14 hours behind.
```

Business impact follows age more than count. MegaShop alerts on search freshness, email freshness, fraud freshness, and retention risk, not just raw lag.

---

# Part Y: Lag Pattern Diagnosis

```text
+----------------------+----------------------------------+--------------------------+
| Pattern              | Likely cause                     | First questions          |
+----------------------+----------------------------------+--------------------------+
| all partitions lag   | broad capacity or sink problem   | downstream p99? CPU?     |
| one partition lags   | hot key or poison record         | key skew? repeated offset?|
| sawtooth lag         | rebalance or batch behavior      | deploys? GC? autoscale?  |
| lag grows after retry| retry storm                      | provider failures?       |
| lag near retention   | recovery risk                    | can retention be extended?|
+----------------------+----------------------------------+--------------------------+
```

Command output:

```text
TOPIC                       PARTITION CURRENT-OFFSET LOG-END-OFFSET LAG      HOST
commerce.orders.events.v1   0         1000000        1001200        1200     worker-1
commerce.orders.events.v1   1         900000         1600000        700000   worker-2
commerce.orders.events.v1   2         999500         1000000        500      worker-3
```

Interpretation:

```text
Partition 1 dominates lag.
Do not scale blindly.
Check worker-2 logs.
Check repeated offset.
Check key distribution.
Check downstream calls from worker-2.
Check whether a poison record blocks progress.
```

---

# Part Z: Backpressure

Backpressure slows work to protect downstream systems. Kafka can buffer. Kafka cannot make a saturated sink healthy.

```text
+-------+      +----------+      +------------+
| Kafka | ---> | Consumer | ---> | OpenSearch |
+-------+      +----------+      +------------+
                  pause             saturated
                  resume
                  throttle
```

Bad recovery:

```text
OpenSearch rejects writes.
Consumer immediately retries every failure.
More consumers are added.
OpenSearch is hammered harder.
Lag grows anyway.
```

Good recovery:

```text
1. Detect OpenSearch p99 and rejection spike.
2. Pause or throttle non-critical consumers.
3. Use bulk writes if appropriate.
4. Reduce retry pressure.
5. Restore sink health.
6. Drain backlog at controlled rate.
7. Verify lag age returns to SLO.
```

SRE rule:
The goal is safe recovery, not visually shrinking lag at any cost.

---

# Part AA: Retention

Retention controls how long Kafka keeps records. It is a recovery policy and a storage cost decision.

```text
retention.ms=604800000  # seven days
```

Retention failure:

```text
retention:       24 hours
consumer outage: 36 hours
missing replay:  12 hours

RESULT:
  Consumer cannot replay deleted records from Kafka.
```

Storage math:

```text
average compressed record: 500 bytes
produce rate:              100,000 records/sec
ingress:                   50 MB/sec
retention:                 604,800 sec
replication factor:        3
storage:                   50 * 604,800 * 3 MB
storage:                   about 90 TB before overhead
```

Interpretation:

```text
Long retention is expensive.
Short retention reduces recovery ability.
Critical business facts deserve more retention than debug telemetry.
Legal history may require database or data lake archival, not only Kafka retention.
```

Alerting:

```text
Alert when lag age approaches retention window.
Example: page at 70 percent of retention for critical groups.
```

---

# Part AB: Compaction

Compaction keeps the latest value per key eventually.

```text
Before compaction:
  key=user_1 value=A
  key=user_1 value=B
  key=user_1 value=C

After compaction eventually:
  key=user_1 value=C
```

Use compaction for latest-state topics:

```text
1. feature flags
2. account settings
3. current user profile
4. service configuration
```

Do not use compaction when every historical event matters:

```text
1. payment ledger
2. security audit stream
3. legal event history
4. order lifecycle audit
```

Important details:

```text
1. Compaction is eventual.
2. Old records can remain until cleaner runs.
3. Tombstones can eventually delete keys.
4. Compaction is not an immediate privacy deletion guarantee.
5. Compaction is not a backup strategy.
```

---

# Part AC: Schema Evolution

Kafka stores bytes. Teams own meaning.

```text
+-------------+---------------------------+------------------------------+
| Format      | Strength                  | Risk                         |
+-------------+---------------------------+------------------------------+
| JSON        | readable                  | weak contracts               |
| Avro        | registry-friendly         | schema discipline required   |
| Protobuf    | compact and typed         | field number mistakes        |
| JSON Schema | readable validation       | larger payloads              |
+-------------+---------------------------+------------------------------+
```

Breaking changes:

```text
1. remove required field
2. rename field without transition
3. change string to int
4. change meaning under same field name
5. reuse Protobuf field number
6. narrow enum values without old consumer support
```

Safe evolution:

```text
1. Add optional new field.
2. Deploy consumers that understand old and new shape.
3. Start writing new field.
4. Backfill if required.
5. Stop reading old field.
6. Remove old field only after compatibility and retention windows.
```

Protobuf rule:

```proto
message OrderPlaced {
  string order_id = 1;
  int64 total_cents = 2;
  string currency = 3;
  string customer_id = 4;

  reserved 5;
  reserved "old_coupon_code";
}
```

Never reuse field numbers. Old bytes can become new lies.

---

# Part AD: Schema Break Incident

Incident:

```text
Producer removes total_cents from OrderPlaced.
Search continues because it does not need total_cents.
Analytics fails loudly.
Fraud treats missing amount as zero.
Risk decisions become wrong.
```

Diagnosis:

```text
1. Group DLQ records by schema_version.
2. Compare producer deploy time to error spike.
3. Check consumers that silently accepted null/default values.
4. Compare business metrics such as fraud approval rate and revenue totals.
```

Mitigation:

```text
1. Roll back producer if breaking.
2. Restore compatible field.
3. Fix consumers to handle versioned schemas.
4. Replay DLQ after fix.
5. Correct silently wrong projections through backfill.
```

Prevention:

```text
1. Schema Registry compatibility checks.
2. Consumer contract tests.
3. Producer rollout approval for public events.
4. Versioned event handlers.
5. Semantic review, not just structural validation.
```

---

# Part AE: Retry Topics

Retry policy must classify errors. Retrying every failure immediately is how small outages become bonfires.

```text
+------------------------+------------------------------+-------------------------+
| Error                  | Retry?                       | Path                    |
+------------------------+------------------------------+-------------------------+
| schema validation      | usually no                   | DLQ/quarantine          |
| OpenSearch 503         | yes with backoff             | retry topic             |
| provider timeout       | yes if idempotent            | retry + reconciliation  |
| authorization failure  | no until config fixed        | alert                   |
| record too large       | no                           | schema/design fix       |
+------------------------+------------------------------+-------------------------+
```

Retry topology:

```text
+------------+      +----------+      +----------+      +-----------+      +-----+
| Main Topic | ---> | Retry 1m | ---> | Retry 5m | ---> | Retry 30m| ---> | DLQ |
+------------+      +----------+      +----------+      +-----------+      +-----+
```

Rules:

```text
1. Preserve original event_id.
2. Preserve original topic, partition, offset, key, and headers.
3. Increment attempt count.
4. Use jitter to avoid retry herds.
5. Stop after bounded attempts.
6. Do not retry permanent errors forever.
```

---

# Part AF: DLQ Design

A DLQ is an evidence locker, not a landfill.

Useful DLQ payload:

```json
{
  "original_topic": "commerce.orders.events.v1",
  "original_partition": 17,
  "original_offset": 8819231,
  "key": "ord_123",
  "headers": {
    "event_type": "OrderPlaced",
    "schema_version": "4",
    "correlation_id": "req_abc"
  },
  "consumer_group": "search-indexer",
  "application_version": "search-indexer-2026.05.16.1",
  "error_class": "SchemaValidationError",
  "error_message": "missing total_cents",
  "failed_at": "2026-05-16T11:00:00Z",
  "payload": "...original serialized payload..."
}
```

DLQ operating model:

```text
1. Alert on DLQ rate by consumer criticality.
2. Group DLQ by error_class and schema_version.
3. Assign owner.
4. Fix code or data.
5. Replay with rate limit.
6. Track replay success and re-DLQ rate.
7. Archive or delete by policy.
```

DLQ without replay tooling is not recovery. It is deferred failure.

---

# Part AG: Transactional Outbox

The dual-write problem appears when a service writes database state and publishes to Kafka separately.

Bad pattern:

```text
1. Insert order row in OrdersDB.
2. Publish OrderPlaced to Kafka.
```

Failure 1:

```text
DB commit succeeds.
Kafka publish fails.
Order exists, event missing.
```

Failure 2:

```text
Kafka publish succeeds.
DB transaction rolls back.
Event exists for nonexistent order.
```

Outbox pattern:

```text
+----------+        same DB transaction        +---------------+
| orders   | <-------------------------------> | outbox_events |
+----------+                                   +---------------+
                                                     |
                                                     | relay or CDC
                                                     v
                                                 +-------+
                                                 | Kafka |
                                                 +-------+
```

Outbox table:

```sql
CREATE TABLE outbox_events (
  event_id TEXT PRIMARY KEY,
  aggregate_type TEXT NOT NULL,
  aggregate_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  schema_version INT NOT NULL,
  payload JSONB NOT NULL,
  created_at TIMESTAMP NOT NULL,
  published_at TIMESTAMP NULL,
  publish_attempts INT NOT NULL DEFAULT 0,
  last_error TEXT NULL
);

CREATE INDEX outbox_unpublished_idx
ON outbox_events (created_at)
WHERE published_at IS NULL;
```

SRE signal:

```text
oldest unpublished outbox row age
```

Outbox prevents database/event divergence. It does not remove duplicate delivery. Consumers still need idempotency.

---

# Part AH: CDC and Kafka Connect

CDC means change data capture. A connector reads committed database changes and publishes them to Kafka.

```text
+----------+      +-----------+      +-------+      +----------+
| OrdersDB | ---> | Connector | ---> | Kafka | ---> | Consumer |
+----------+      +-----------+      +-------+      +----------+
     |                 |                |              |
     v                 v                v              v
 outbox age       source lag        broker health   group lag
```

What breaks:

```text
CONNECTOR STOPPED

T0  Checkout continues writing orders and outbox rows.
T1  Connector stops reading database changes.
T2  Outbox age grows.
T3  Kafka has no new OrderPlaced events.
T4  Search/email/analytics lag behind even though consumer lag may be zero.
```

PostgreSQL replication slot risk:

```sql
SELECT
  slot_name,
  active,
  restart_lsn,
  confirmed_flush_lsn,
  pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) AS retained_bytes
FROM pg_replication_slots;
```

Interpretation:

```text
active=false and retained_bytes growing:
  connector is not consuming WAL.
  database disk can fill.
  source of truth is at risk.
```

Protect the database first. Do not drop slots casually. Dropping a slot can require re-snapshot, and re-snapshot can overload the primary.

---

# Part AI: Observability Model

Kafka observability has layers.

```text
+------------+--------------------------------------+----------------------------+
| Layer      | Signals                              | Meaning                    |
+------------+--------------------------------------+----------------------------+
| Broker     | ISR, disk, request latency           | cluster health             |
| Producer   | error rate, retry rate, queue time   | write path health          |
| Consumer   | lag, lag age, rebalance rate         | processing freshness       |
| Connector  | task state, source lag               | integration health         |
| Downstream | p99, rejections, saturation          | sink capacity              |
| Business   | stale search, delayed email          | customer impact            |
+------------+--------------------------------------+----------------------------+
```

A lag graph alone is incomplete. A broker dashboard alone is incomplete. A DLQ count alone is incomplete.

MegaShop dashboard pairing:

```text
search-indexer lag     + OpenSearch p99/rejections
outbox oldest age      + connector task state
email queue age        + provider timeout rate
fraud lag age          + risk decision delay
broker ISR shrink      + producer not-enough-replicas errors
```

The goal is causal diagnosis, not decorative metrics.

---

# Part AJ: Command Output Interpretation

Describe topic:

```bash
kafka-topics --bootstrap-server broker:9092 \
  --describe --topic commerce.orders.events.v1
```

Output:

```text
Topic: commerce.orders.events.v1  PartitionCount: 48  ReplicationFactor: 3
Topic: commerce.orders.events.v1  Partition: 0  Leader: 1  Replicas: 1,2,3  Isr: 1,2,3
Topic: commerce.orders.events.v1  Partition: 1  Leader: 2  Replicas: 2,3,1  Isr: 2,3
Topic: commerce.orders.events.v1  Partition: 2  Leader: 3  Replicas: 3,1,2  Isr: 3,1,2
```

Interpretation:

```text
Partition 1 has replica 1 missing from ISR.
Leader exists, so partition may still serve traffic.
Durability margin is reduced.
With min.insync.replicas=2, acks=all can still succeed.
If another ISR member falls out, writes can fail.
Investigate Broker 1 disk, network, and replication lag.
```

Describe consumer group:

```bash
kafka-consumer-groups --bootstrap-server broker:9092 \
  --describe --group search-indexer
```

Output:

```text
TOPIC                       PARTITION CURRENT-OFFSET LOG-END-OFFSET LAG      HOST
commerce.orders.events.v1   0         1000000        1001200        1200     worker-1
commerce.orders.events.v1   1         900000         1600000        700000   worker-2
commerce.orders.events.v1   2         999500         1000000        500      worker-3
```

Interpretation:

```text
Partition 1 dominates lag.
Do not scale blindly.
Check worker-2 logs.
Check repeated offset.
Check key distribution.
Check downstream calls from worker-2.
Check poison message possibility.
```

---

# Part AK: Runbooks

## All Partitions Lagging

```text
1. Check producer rate.
2. Check consumer throughput.
3. Check whether lag is growing or shrinking.
4. Check downstream p99 and rejection rate.
5. Check consumer CPU and memory.
6. Check consumer error rate.
7. Check rebalance rate.
8. Check broker fetch latency.
9. Check recent deployments.
10. Check DLQ and retry rate.

IF downstream is saturated:
  throttle or pause consumers; do not blindly scale.

IF consumer CPU is saturated and downstream is healthy:
  scale consumers up to partition count.

IF broker fetch latency is high:
  inspect broker health.
```

## One Partition Lagging

```text
1. Identify lagging partition.
2. Identify owning consumer host.
3. Check logs for repeated offset.
4. Check key distribution.
5. Check host health.
6. Check downstream calls from that host.
7. If poison record, quarantine with audit.
8. If hot key, rollback key or cut over to corrected topic.
9. Do not skip offsets silently.
10. Do not delete topic data.
```

## ISR Shrink

```text
1. Identify affected topics and partitions.
2. Classify topic criticality.
3. Check broker disk.
4. Check broker network.
5. Check replication fetcher lag.
6. Check recent broker restarts.
7. Check rack or zone health.
8. Expect acks=all failures if ISR < min.insync.replicas.
9. Confirm ISR recovery.
10. Review replica placement.
```

## DLQ Spike

```text
1. Identify DLQ topic.
2. Identify producing consumer group.
3. Group by error_class.
4. Group by schema_version.
5. Group by event_type.
6. Check producer deploys.
7. Check consumer deploys.
8. Sample payloads safely.
9. Fix code or data.
10. Replay with rate limits.
```

## Connector Lag

```text
1. Check connector state.
2. Check task states.
3. Check source database health.
4. Check replication slot retained bytes.
5. Check connector logs.
6. Check Kafka produce errors.
7. Protect source database first.
8. Avoid dropping slots without re-snapshot plan.
9. Communicate projection freshness impact.
10. Verify outbox age recovers.
```

---

# Part AL: Full Incident Walkthrough

Incident:

```text
P1: Celebrity sneaker launch.
Topic: commerce.orders.events.v1.
Partitions: 48.
Replication factor: 3.
min.insync.replicas: 2.
Baseline produce rate: 8,000 records/sec.
Current produce rate: 55,000 records/sec.
Fraud lag: 80,000 stable.
Inventory lag: 9,200,000 growing.
Search lag: 31,000,000 growing.
Email lag: 4,800,000 growing.
Rebalance rate: 140/hour.
DLQ rate: low.
Partition 05 lag: 8,900,000.
Other sampled partitions: around 20,000.
Recent change: producer key changed from order_id to product_id.
Launch product_id: SNKR-2026.
Search writes one document at a time to OpenSearch.
Email retries immediately on provider timeout.
```

Architecture:

```text
+----------+      +----------+      +----------+      +-------+
| Checkout | ---> | OrdersDB | ---> | Outbox   | ---> | Kafka |
+----------+      +----------+      +----------+      +-------+
                                                           |
         +---------------------+---------------------------+--------------------+
         |                     |                           |                    |
         v                     v                           v                    v
+---------------+     +-------------------+       +----------------+     +-------------+
| Fraud         |     | Inventory         |       | Search         |     | Email       |
| Consumer      |     | Projector         |       | Indexer        |     | Sender      |
+---------------+     +-------------------+       +----------------+     +-------------+
```

Diagnosis:

```text
Primary cause:
  partition key changed from order_id to product_id.

Why it broke:
  Most launch records share product_id SNKR-2026.
  They hash to one partition.
  One partition has one active owner per group.
  Adding consumers cannot split that partition.

Why search is worse:
  Search also has inefficient one-document writes to OpenSearch.

Why email is worse:
  Immediate retry policy amplifies provider timeout.

Why DLQ is low:
  Records are not mostly malformed; they are delayed.
```

Immediate mitigation:

```text
1. Stop autoscaling churn.
2. Freeze non-essential deploys.
3. Confirm per-partition lag.
4. Identify hot keys if tooling allows.
5. Roll back key to order_id if safe.
6. If rollback is unsafe, cut over to corrected topic.
7. Prioritize fraud and inventory consumers.
8. Throttle search indexing.
9. Add email retry backoff with jitter.
10. Preserve records; do not delete data.
```

Anti-actions:

```text
1. Do not delete topic data to reduce lag.
2. Do not skip offsets silently.
3. Do not scale consumers blindly.
4. Do not increase partitions in panic without migration plan.
5. Do not trust stale search projection as order truth.
6. Do not run full-speed backfill into saturated OpenSearch.
```

Recovery validation:

```text
1. Lag age returns within SLO.
2. Inventory projection freshness is safe or bypassed by authority.
3. Search p99 and rejection rate normalize.
4. Email backlog drains or customer communication is sent.
5. Rebalance rate returns to baseline.
6. DLQ remains stable and classified.
7. No data gap exists.
8. Outbox age normalizes.
```

Prevention:

```text
1. Partition-key review for producer changes.
2. Hot-key launch test.
3. Per-partition lag alerts.
4. Lag-age alerts.
5. Autoscaling based on lag, rebalance rate, and downstream capacity.
6. Search bulk writes and backpressure.
7. Email exponential backoff with jitter.
8. Critical consumer capacity protection.
9. Schema compatibility gates.
10. Tested replay and backfill tooling.
```

---

# Part AM: Kafka vs Alternatives

```text
+----------------+-----------------------------+------------------------------+
| System         | Best fit                    | Poor fit                     |
+----------------+-----------------------------+------------------------------+
| SQS            | simple managed task queue   | long replay history          |
| RabbitMQ       | routing-heavy work queues   | huge retained event logs     |
| Kafka          | durable event streams       | tiny background job only     |
| Redis Streams  | modest Redis-native streams | global durable backbone      |
| NATS           | low-latency messaging       | default audit/event history  |
| Kinesis        | AWS-managed streams         | non-AWS portability needs    |
+----------------+-----------------------------+------------------------------+
```

Decision examples:

```text
Receipt email job:
  SQS or task queue is often better.

Order event history for search, fraud, analytics, warehouse, and replay:
  Kafka is often better.

Seller workflow routing by region and tier:
  RabbitMQ may fit well.

Low-latency control-plane messages:
  NATS may fit.

AWS-native shard stream with managed operations:
  Kinesis may fit.
```

Principal answer:
Choose by semantics, not resume keywords.

---

# Part AN: Design Review Templates

## Topic Review

```text
1. What business fact or command does this topic carry?
2. Who owns the topic?
3. Who produces to it?
4. Who consumes it?
5. Which consumers are critical?
6. What schema format and compatibility mode are used?
7. What is the partition key?
8. What ordering is promised?
9. What ordering is explicitly not promised?
10. What hot-key scenarios were tested?
11. What retention is required?
12. What cleanup policy is used?
13. What replication factor and min ISR are used?
14. What ACLs and quotas apply?
15. What runbook exists?
```

## Producer Review

```text
1. What happens if Kafka write fails?
2. Is outbox required?
3. How is event_id generated?
4. What key is used?
5. What producer settings are used?
6. Are producer errors observable?
7. Is schema compatibility checked?
8. Can user success be returned before publish?
9. What happens on retry ambiguity?
10. What is the rollback plan?
```

## Consumer Review

```text
1. What side effect occurs?
2. Is the side effect idempotent?
3. What idempotency key protects it?
4. When are offsets committed?
5. Is auto commit disabled?
6. Which errors are retryable?
7. Which errors go to DLQ?
8. Is replay safe?
9. What downstream bottleneck can occur?
10. What lag SLO exists?
```

---

# Part AO: Scenario Questions

```text
1. Checkout succeeds but search does not show new orders. Identify authority and async failure points.
2. A payment provider times out after capture request. Explain safe recovery.
3. One partition has 95 percent of inventory lag. Diagnose hot key vs poison record.
4. Producer key changes from order_id to product_id before flash sale. Explain failure.
5. DLQ grows after producer schema deploy. Triage it.
6. Outbox age rises but Kafka consumer lag is zero. Locate the failure.
7. OpenSearch p99 spikes while Kafka lag grows. Explain why scaling consumers may hurt.
8. ISR shrinks but clients still work. Explain the hidden risk.
9. New consumer group starts at latest and misses history. Explain auto.offset.reset risk.
10. Analytics is down beyond retention. Explain recovery options.
```

Answer sketch:

```text
1. OrdersDB is authority; check outbox, connector, Kafka lag, OpenSearch.
2. Use provider idempotency key, query provider, reconcile, avoid blind retry.
3. Check per-partition lag, repeated offset, key distribution, host behavior.
4. Hot product maps to one partition; rollback key or migrate topic.
5. Group by schema_version/error_class; rollback/fix; replay safely.
6. Events stuck before Kafka, likely outbox relay or CDC connector.
7. Sink is bottleneck; apply backpressure and controlled catch-up.
8. Durability margin reduced; acks=all may fail if ISR shrinks further.
9. New group has no offsets; latest skips old records.
10. Backfill from source of truth if available; otherwise document gap.
```

---

# Part AP: Final Mental Model

Messaging moves work across time, ownership, load, and failure domains.
That power creates lag, duplicates, replay risk, schema coupling, and operational state.
Task queues distribute jobs.
Publish/subscribe distributes reactions.
Durable logs preserve replayable history.
Kafka is a distributed, replicated, partitioned, append-only commit log.
The partition key is both correctness and capacity design.
Offsets are progress markers, not business truth.
Producer acks define when Kafka is allowed to claim write success.
Consumer commits define where a group resumes, not whether side effects are correct.
At-least-once delivery is normal.
Idempotency makes it safe.
Exactly-once must always state scope.
Outbox protects database state and event publication from divergence.
CDC connects committed state to streams but can threaten the source database if neglected.
DLQs are evidence lockers, not trash cans.
Lag is delayed business work.
Lag age often matters more than lag count.
Backpressure protects downstream systems from Kafka-powered overload.
The best Kafka systems are boring during incidents because authority is clear, duplicates are expected, lag is measured, replay is controlled, schemas are governed, and dangerous actions are known in advance.

