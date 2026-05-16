# Week 6, Topic 1: Message Queues and Kafka

Last verified: 2026-05-16

---

# Part 1: The Running Architecture

## 1. MegaShop: The system used throughout this chapter

MegaShop is a Fortune 500 scale e-commerce platform used as the running example.
MegaShop is not a claim about any single company internals.
It combines patterns seen in large retail, logistics, payments, streaming, and marketplace systems.
The platform sells physical goods across many countries.
It has flash sales, marketplace sellers, warehouses, fraud checks, search, recommendations, payments, and analytics.
Its most important user workflow is checkout.
Checkout cannot be treated as a toy request.
Checkout touches money, inventory, customer trust, warehouse commitments, and legal records.
A beginner often sees checkout as one API call.
A production SRE sees checkout as a workflow with authority boundaries.
The order database is authoritative for order existence.
The payment provider or payment ledger is authoritative for payment state.
The inventory service is authoritative for reservation state.
Search is a projection.
Analytics is a projection.
Email is a notification side effect.
The warehouse system is a fulfillment side effect with business consequences.
The fraud service may be either advisory or blocking depending risk policy.
Messaging exists because not every downstream reaction belongs in the user request path.
The first architecture is fully synchronous.

```text
+----------+      +----------+      +----------+      +----------+
|  Client  | ---> | Checkout | ---> | Payment  | ---> | Inventory|
+----------+      +----------+      +----------+      +----------+
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
```

This diagram is easy to read and dangerous to operate.
If email slows down, checkout slows down.
If search indexing fails, checkout can fail.
If analytics blocks, users cannot buy goods.
The architecture has confused critical work with side effects.
The correct design keeps authority in the synchronous path and moves reactions behind a durable boundary.

```text
+----------+      +----------+      +----------+
|  Client  | ---> | Checkout | ---> | OrdersDB |
+----------+      +----------+      +----------+
                       |
                       | OrderPlaced
                       v
                  +----------+
                  |  Kafka   |
                  +----------+
                   |    |    |
                   |    |    +----------> Analytics
                   |    +---------------> Search
                   +--------------------> Email
```

The user receives a response after the authoritative work is safe.
Search, email, analytics, and warehouse work can continue after the request.
This does not make them unimportant.
It makes their delay observable as lag rather than user-facing request latency.
The whole chapter explains this trade.

---

## 2. The core problem messaging solves

Messaging is not primarily about speed.
Messaging is about decoupling time, failure, ownership, and load.
A synchronous call requires producer and consumer to be alive together.
A message allows producer and consumer to operate at different times.
A synchronous call returns success or failure now.
A message may succeed now and fail later during consumer processing.
A synchronous call usually has one caller and one callee.
A message can have many independent consumers.
A synchronous call is easy to trace inside one request.
A message turns the request into a workflow.
MegaShop checkout should not wait for email.
MegaShop checkout may need to wait for payment authorization.
MegaShop checkout may need to wait for inventory reservation.
MegaShop checkout should not wait for analytics.
MegaShop checkout should not trust search as the source of price truth.
The design question is not whether messaging is fashionable.
The design question is which work must be synchronous and which work can be delayed.
Messaging changes failure visibility.
Without messaging, failure appears as API latency or API error.
With messaging, failure appears as lag, DLQ growth, stale projections, duplicate side effects, or missed events.
A queue can protect a dependency from a burst.
A queue can also hide a business outage for hours.
A broker can isolate email failure from checkout.
A broker can also let email fall behind until support tickets arrive.
The SRE lens is therefore mandatory.
For every message path ask what happens when consumers stop for one minute.
Ask what happens when consumers stop for one hour.
Ask what happens when consumers stop beyond retention.
Ask what happens when the same event is processed twice.
Ask what happens when an old event is replayed six months later.
Ask what happens when a producer deploy changes event schema.
Ask what happens when one key gets 90 percent of traffic.
Messaging is a power tool.
A power tool can build the warehouse.
A power tool can also remove fingers.

---

## 3. Critical path versus side-effect path

A critical path contains work that must complete before the user can receive a correct answer.
A side-effect path contains work that can happen after the user-facing decision is made.
MegaShop checkout critical path includes cart validation.
It includes price verification against the pricing authority.
It includes inventory reservation when overselling is not allowed.
It includes payment authorization when the business requires immediate payment confidence.
It includes writing the authoritative order.
It includes recording enough durable state to recover downstream work.
MegaShop checkout side-effect path includes receipt email.
It includes search indexing.
It includes analytics ingestion.
It includes recommendations update.
It includes warehouse notification if the warehouse can tolerate short delay.
It may include fraud model enrichment if fraud is not blocking.
A beginner mistake is to put every useful action in the critical path.
A senior mistake is to put too much behind async without defining freshness and correctness.
Both are bad.
The correct split is explicit.

```text
+----------------------+-----------------------------+
| Must be synchronous  | Can usually be asynchronous |
+----------------------+-----------------------------+
| price verification   | receipt email               |
| payment decision     | analytics                   |
| inventory reserve    | search indexing             |
| order write          | recommendations refresh     |
| idempotency record   | warehouse notification      |
+----------------------+-----------------------------+
```

There are exceptions.
If warehouse commitment must happen before checkout confirmation, it belongs in the critical path.
If fraud policy blocks high-risk orders, fraud belongs in the critical path for those orders.
If email contains a legal one-time token required to continue, email may become critical.
Architecture is not a fixed recipe.
Architecture is an explicit statement of business truth.
Messaging is appropriate only after deciding which truth can lag.

---

# Part 2: Messaging Models

## 4. Task queues from first principles

A task queue distributes units of work to workers.
The semantic goal is simple.
One job should be handled by one worker.
This does not mean the job can never run twice.
It means the system is designed so one logical job is assigned to one worker at a time.
MegaShop uses a task queue for receipt emails.
The checkout service does not want to send email inline.
It creates a job saying send receipt email for order ord_123.
A worker later picks up the job.

```text
+----------+      +-------------+      +----------+
| Checkout | ---> | Email Queue | ---> | Worker A |
+----------+      +-------------+      +----------+
                         |
                         +------->     +----------+
                                       | Worker B |
                                       +----------+
```

A task queue usually has acknowledgement semantics.
The queue gives a job to a worker.
The queue hides that job from other workers for a time window.
The worker processes the job.
The worker acknowledges success.
The queue removes the job.
If the worker crashes before acknowledgement, the queue can redeliver.
This is not a rare edge case.
This is the normal safety behavior of a queue.
Therefore task workers must be idempotent.
MegaShop email worker uses a sent marker.
The marker key is receipt:ord_123:receipt_v3.
If that marker exists, the worker does not send again.
If that marker does not exist, the worker sends email and records the marker.
The queue protects delivery.
The worker protects side effects.
Those are different responsibilities.

---

## 5. Task queue failure timeline

The dangerous task queue case is crash after side effect before ack.

```text
T0  Worker receives SendReceiptEmail ord_123.
T1  Worker calls email provider.
T2  Email provider accepts the email.
T3  Worker crashes before deleting queue message.
T4  Visibility timeout expires.
T5  Queue redelivers the same job.
T6  Another worker sends the same receipt again.
```

The queue did the right thing.
The worker design was incomplete.
The fix is not to disable redelivery.
The fix is idempotency.
A correct worker stores durable completion state.
The completion state must be checked before the side effect.
For email, store notification_sent.
For webhooks, store delivery attempt state per destination.
For payments, use provider idempotency keys.
For ledgers, use unique event IDs.
Task queues also need bounded retries.
A malformed job should not retry forever.
A downstream outage should not cause immediate retry storms.
A good task queue setup includes max receive count.
It includes a DLQ.
It includes retry delay.
It includes alerting on oldest job age.
It includes alerting on DLQ rate.
It includes worker saturation metrics.
MegaShop treats queue age as more important than queue depth.
One million email jobs may be fine during Black Friday if workers drain quickly.
Ten thousand payment settlement jobs may be catastrophic if oldest age is two hours.
Depth is inventory.
Age is user pain.

---

## 6. Task queue operational interpretation

An SRE should not look only at message count.
A queue with one hundred thousand jobs can be healthy.
A queue with one hundred jobs can be unhealthy.
Interpret queue state using rate and age.

```text
incoming rate:        20,000 jobs/min
processing rate:      25,000 jobs/min
queue depth:          100,000 jobs
oldest age:           4 minutes
status:               recovering
```

Now compare.

```text
incoming rate:        100 jobs/min
processing rate:      20 jobs/min
queue depth:          1,000 jobs
oldest age:           50 minutes
status:               failing
```

MegaShop email queue has an SLO.
Ninety-nine percent of receipt emails should be sent within five minutes.
That is not the checkout SLO.
That is the notification freshness SLO.
This distinction matters in incidents.
If checkout succeeds but email is delayed, orders are not lost.
Customer trust may still be harmed.
Support needs a clear statement.
The SRE should say orders are safe and confirmations are delayed.
The SRE should not say the system is fine.
Async failure is still failure.
It is just a different kind.

---

## 7. Publish and subscribe from first principles

Publish and subscribe is fanout.
One published event can be consumed by many subscribers.
MegaShop emits OrderPlaced.
Email consumes it.
Search consumes it.
Analytics consumes it.
Fraud consumes it.
Warehouse consumes it.
The order service should not know every future consumer.
If a new recommendation service needs order events, it should subscribe.
The publisher should publish a stable business fact.
Consumers should react independently.

```text
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

The word event matters.
An event says something happened.
OrderPlaced is an event.
SendEmail is a command.
CapturePayment is a command.
PaymentCaptured is an event.
Do not name commands as events.
Do not name events as commands.
That mistake creates confused ownership.
If a consumer receives OrderPlaced, it decides its reaction.
If a consumer receives SendEmail, someone is telling it what to do.
Both patterns can be valid.
They are not the same.

---

## 8. Pub/sub hidden coupling

Pub/sub reduces direct code coupling.
It does not remove semantic coupling.
Consumers depend on event names.
Consumers depend on field meanings.
Consumers depend on ordering expectations.
Consumers depend on retention windows.
Consumers depend on producer correctness.
MegaShop search indexer depends on OrderPlaced carrying order_id, customer_id, created_at, and line items.
MegaShop analytics depends on total amount and currency.
MegaShop fraud depends on customer_id, payment method, IP country, and device risk fields.
If the order service removes customer_id from OrderPlaced, fraud breaks.
The order service may not even know fraud consumes the event.
This is hidden coupling.
The solution is not to avoid pub/sub.
The solution is event ownership and schema governance.
Every event needs an owner.
Every event needs compatibility rules.
Every event needs deprecation policy.
Every event needs consumer discovery.
Every breaking change needs a migration plan.
A production event is a contract.
It is not a casual JSON postcard.

---

## 9. Durable event logs from first principles

A durable log stores history.
Kafka is primarily a durable event log.
This is different from a task queue.
In a task queue, successful processing usually removes the job.
In a durable log, records remain until retention or compaction removes them.
Consumers track their own positions.
MegaShop order-events topic contains order lifecycle records.

```text
Topic: order-events

+-------------+-----------------+------------+---------+-----------+
| OrderPlaced | PaymentCaptured | ItemPacked | Shipped | Delivered |
+-------------+-----------------+------------+---------+-----------+
      0               1              2           3          4
```

Fraud may read through offset 4.
Search may be at offset 2.
Analytics may be at offset 0.
That is allowed.
Each consumer group has its own progress.
This is why Kafka is excellent for replay.
If search index is corrupted, MegaShop can rebuild from order-events.
If analytics logic had a bug, MegaShop can reprocess history.
If a new recommendation model needs historical orders, it can backfill.
Replay is powerful.
Replay is also dangerous.
If email consumer replays old OrderPlaced events without dedupe, customers receive old receipts again.
If payment consumer replays old CapturePaymentRequested commands unsafely, customers can be charged twice.
Replay safety is not optional.
A durable log makes history available.
It does not make consumers wise.

---

## 10. Kafka as a commit log

Kafka is a distributed, replicated, partitioned commit log.
Distributed means data lives across brokers.
Replicated means copies exist for durability and availability.
Partitioned means each topic is split into ordered shards.
Commit log means records are appended and read by position.
Kafka does not update records in place like a normal application table.
Kafka appends records to partitions.
A partition is an ordered file-like sequence.
An offset is a position in that sequence.

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
```

Kafka preserves order inside a partition.
Kafka does not preserve total order across all partitions in a topic.
This rule controls almost every Kafka design decision.
If MegaShop keys order lifecycle events by order_id, all events for one order stay ordered.
If MegaShop uses random keys, order lifecycle order is not guaranteed.
If MegaShop keys by product_id during a sneaker launch, one product can melt one partition.
The partition is Kafka's unit of ordering.
The partition is also Kafka's unit of parallelism.
That double role is the central tradeoff.

---

## 11. Kafka cluster anatomy

A Kafka cluster contains brokers.
A broker stores partitions.
Each partition has one leader.
Producers write to the leader.
Consumers read from the leader in most common configurations.
Followers replicate from the leader.

```text
+-----------+        +-----------+        +-----------+
| Broker 1  |        | Broker 2  |        | Broker 3  |
+-----------+        +-----------+        +-----------+
| P0 leader |        | P1 leader |        | P2 leader |
| P1 follow |        | P2 follow |        | P0 follow |
| P2 follow |        | P0 follow |        | P1 follow |
+-----------+        +-----------+        +-----------+
```

Replication spreads risk.
If Broker 1 dies, partitions that had leaders on Broker 1 need new leaders.
If followers are in sync, leadership can move safely.
If followers are not in sync, availability and durability tradeoffs appear.
Kafka exposes this through ISR.
ISR means in-sync replicas.
A replica in ISR is close enough to the leader to be considered safe for durability.
When ISR shrinks, the durability margin shrinks.
When partitions are under-replicated, the system is less safe.
When partitions are offline, clients are impacted.
SREs must treat ISR shrink as a meaningful warning.
It is not dashboard decoration.

---

## 12. Kafka record anatomy

A Kafka record has a key, value, headers, timestamp, partition, and offset.
The key usually drives partition selection.
The value is the serialized payload.
Headers carry metadata.
The timestamp may come from producer or broker configuration.
Partition and offset are assigned by Kafka.
MegaShop OrderPlaced event should not be a loose blob.
A production event needs identity, versioning, and traceability.

```text
+----------------+--------------------------------------+
| Field          | Purpose                              |
+----------------+--------------------------------------+
| event_id       | dedupe, audit, DLQ replay            |
| event_type     | consumer routing and meaning         |
| schema_version | compatibility handling               |
| aggregate_id   | ordering scope and partition key     |
| occurred_at    | business time                        |
| published_at   | pipeline time                        |
| correlation_id | trace one workflow                   |
| causation_id   | explain why event exists             |
+----------------+--------------------------------------+
```

Python-style event creation:

```python
from dataclasses import dataclass
from datetime import datetime, timezone

@dataclass
class OrderPlaced:
    event_id: str
    order_id: str
    customer_id: str
    total_cents: int
    currency: str
    occurred_at: str
    schema_version: int = 1

def build_event(order):
    now = datetime.now(timezone.utc).isoformat()
    return OrderPlaced(
        event_id=f'evt_{order.id}',
        order_id=order.id,
        customer_id=order.customer_id,
        total_cents=order.total_cents,
        currency=order.currency,
        occurred_at=now,
    )
```

A beginner may ask why this metadata matters.
The answer appears during incidents.
Without event_id, dedupe is weak.
Without schema_version, compatibility is guesswork.
Without correlation_id, tracing is painful.
Without occurred_at and published_at, delay diagnosis is blurry.

---

## 13. Producer write path

A Kafka producer does not simply throw bytes at the cluster.
It serializes records.
It chooses partitions.
It batches records.
It sends batches to partition leaders.
The leader appends to its log.
Followers replicate from the leader.
The producer receives acknowledgement based on configuration.

```text
+----------+      +-----------+      +-----------+
| Producer | ---> | Leader    | ---> | Follower  |
+----------+      | Broker    |      | Broker    |
                  +-----------+      +-----------+
                       |
                       v
                 append to log
```

The producer has an internal buffer.
Records accumulate into batches per partition.
Batching is one reason Kafka can be fast.
Without batching, one hundred thousand records per second can become one hundred thousand network requests.
With batching, many records share one request.
Compression works better on batches than single records.
Batching trades a little latency for much higher throughput.
MegaShop checkout events should not use unsafe fire-and-forget settings.
Orders are business records.
A lost OrderPlaced event can make search, warehouse, analytics, and notification inconsistent.
Producer durability settings matter.

---

## 14. Producer durability settings

Important settings include acks, retries, idempotence, linger, batch size, compression, and delivery timeout.

```text
+-----------------------------------+-------------------------------------+
| Setting                           | Meaning                             |
+-----------------------------------+-------------------------------------+
| acks                              | when write counts as successful     |
| enable.idempotence                | protect producer retry duplicates   |
| retries                           | retry transient broker failures     |
| linger.ms                         | wait briefly to fill batches        |
| batch.size                        | target batch size per partition     |
| compression.type                  | reduce network and storage          |
| delivery.timeout.ms               | total send deadline                 |
+-----------------------------------+-------------------------------------+
```

Business-critical baseline:

```properties
acks=all
enable.idempotence=true
compression.type=lz4
linger.ms=10
batch.size=65536
delivery.timeout.ms=120000
request.timeout.ms=30000
```

acks=0 means the producer does not wait for broker acknowledgement.
This is fast and unsafe.
acks=1 means the leader acknowledges after local append.
This can lose records if the leader dies before followers replicate.
acks=all means the leader waits for in-sync replica requirements.
This is safer for business events.
For MegaShop orders, acks=all is usually appropriate.
For low-value click telemetry, a cheaper durability level may be acceptable.
Architecture is about matching cost to consequence.

---

## 15. acks failure timeline

acks=1 failure timeline:

```text
T0  Producer sends OrderPlaced ord_123.
T1  Leader appends record.
T2  Leader sends success to producer.
T3  Leader crashes before follower replication.
T4  New leader is elected without the record.
T5  Producer believes write succeeded.
T6  Event is gone.
```

This is why acks=1 can be dangerous for business facts.
acks=all with min.insync.replicas changes the failure mode.

```text
replication.factor=3
min.insync.replicas=2
acks=all
```

Now Kafka should not acknowledge unless enough replicas are in sync.
If ISR drops below two, writes fail.
That creates visible unavailability instead of silent loss.
Visible failure is painful.
Silent data loss is poison.
MegaShop would rather fail order event publication loudly than believe the event exists when it does not.
The exact decision depends on business impact.
For orders, durability is precious.
For debug logs, loss may be acceptable.

---

## 16. Idempotent producer

Producer retries can create duplicates if the broker writes a batch but the acknowledgement is lost.
Timeline without idempotent producer:

```text
T0  Producer sends batch B.
T1  Broker writes batch B.
T2  Ack is lost on network.
T3  Producer retries batch B.
T4  Broker writes batch B again.
```

The log now has duplicate records.
Idempotent producer adds producer IDs and sequence numbers.
The broker can detect duplicate retry attempts for a partition.
This protects Kafka from duplicate appends caused by producer retry.
It does not protect downstream side effects.
If the same valid event is delivered twice to a consumer, the consumer still needs idempotency.
If a payment API is called twice, Kafka producer idempotence does not save the payment.
This distinction is often missed.
Producer idempotence protects writes into Kafka.
Consumer idempotence protects business effects after Kafka.
Both can be required.
They solve different problems.

---

## 17. Replication and ISR in depth

Replication factor defines how many copies Kafka maintains.
Replication factor three is common for important topics.
One replica is the leader.
Other replicas are followers.
Followers fetch data from the leader.
ISR is the set of replicas considered in sync.
Healthy state:

```text
Partition 7
Leader: Broker 1
Replicas: Broker 1, Broker 2, Broker 3
ISR: Broker 1, Broker 2, Broker 3
```

One follower lagging:

```text
Partition 7
Leader: Broker 1
Replicas: Broker 1, Broker 2, Broker 3
ISR: Broker 1, Broker 2
```

SRE interpretation:

```text
ISR shrink means safety margin is reduced.
Under-replicated partition means at least one replica is not caught up.
Offline partition means no leader is available.
```

Do not wait for offline partitions to care.
Under-replication is the early warning.
ISR shrink during broker disk pressure can indicate the cluster is falling behind replication.
ISR shrink during network loss can indicate rack or zone connectivity trouble.
ISR shrink during produce spikes can indicate brokers cannot keep up.
MegaShop pages on sustained under-replicated partitions for order topics.
It may only ticket under-replication on low-value telemetry topics.
Severity follows business value.

---

## 18. Consumer groups

A consumer group is a set of consumers sharing work for a topic.
Within one group, each partition is assigned to at most one active consumer.

```text
Topic: order-events, 6 partitions
Group: search-indexer

Partition 0 -> Consumer A
Partition 1 -> Consumer A
Partition 2 -> Consumer B
Partition 3 -> Consumer B
Partition 4 -> Consumer C
Partition 5 -> Consumer C
```

If the group has ten consumers and the topic has six partitions, four consumers are idle for that topic.
More consumers than partitions does not increase parallelism.
Different groups are independent.

```text
                 +---------------+
                 | order-events  |
                 +---------------+
                    |     |     |
                    v     v     v
                 fraud search analytics
                 group group  group
```

Fraud lag can be low while analytics lag is high.
Search can be broken without blocking email.
That independence is one of Kafka's strengths.
It also means every consumer group needs its own SLO.
MegaShop tracks fraud freshness separately from search freshness.
A single total Kafka health status is too blunt.

---

## 19. Consumer configuration

Important consumer settings include group.id, auto commit, poll limits, session timeout, heartbeat interval, and fetch tuning.

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

group.id defines the offset namespace.
enable.auto.commit controls whether the client commits offsets automatically.
auto.offset.reset controls where to start when no committed offset exists.
max.poll.records limits batch size.
max.poll.interval.ms controls how long processing may take between polls.
session.timeout.ms controls when the group considers a consumer dead.
heartbeat.interval.ms controls heartbeat frequency.
fetch.min.bytes and fetch.max.wait.ms tune throughput versus latency.
A common dangerous default is auto commit for side-effecting consumers.
Auto commit can mark work complete before the database write, email send, or index update is actually safe.
MegaShop disables auto commit for consumers that mutate external systems.
Offsets are committed after durable side effects complete.
That creates at-least-once behavior.
At-least-once requires idempotency.

---

## 20. Offset commits

An offset is a position in a partition.
Kafka stores committed offsets per consumer group.
The committed offset is the next record the group expects to read.

```text
Partition 2

+-----+-----+-----+-----+-----+
| 100 | 101 | 102 | 103 | 104 |
+-----+-----+-----+-----+-----+
              ^
              |
          processing
```

Commit before processing:

```text
T0  Consumer polls offset 102.
T1  Consumer commits offset 103.
T2  Consumer begins processing.
T3  Consumer crashes before side effect.
```

Kafka thinks 102 is complete.
Business work is missing.
This is at-most-once from the business perspective.
Process before commit:

```text
T0  Consumer polls offset 102.
T1  Consumer processes event.
T2  Consumer writes durable side effect.
T3  Consumer crashes before commit.
```

Kafka redelivers 102.
Business work may repeat.
This is at-least-once.
MegaShop chooses at-least-once for order projections because missing work is worse than duplicate attempts.
Duplicate attempts are controlled with idempotency.

---

## 21. Idempotent consumers with Python

Idempotency means processing the same event twice creates the same final business state as processing it once.
For email, idempotency means one receipt per order and template.
For a ledger, idempotency means one ledger entry per event.
For a webhook, idempotency means one successful delivery record per destination and event.
Bad email consumer:

```python
def handle(event):
    send_email(event.order_id)
    commit_offset(event)
```

Crash after send before commit creates duplicate email.
Better pattern:

```python
def handle(event):
    key = f'receipt:{event.order_id}:receipt_v3'
    with db.transaction() as tx:
        inserted = tx.insert_once('notification_sent', key)
        if inserted:
            send_email(event.order_id)
    commit_offset(event)
```

This example still hides a subtle issue.
If send_email succeeds but the transaction fails afterward, the marker may be missing.
A safer production design may store a pending marker before sending and a sent marker after provider success.
The exact design depends on provider idempotency support.
For payments, always use provider idempotency keys.
For internal databases, use unique constraints.
For external APIs, reconcile.
Idempotency is not a single library.
It is a business-specific correctness design.

---

## 22. Delivery semantics

Delivery semantics describe what the messaging system and application together can guarantee.
At-most-once may lose messages.
At-least-once may process messages more than once.
Effectively-once means business state changes once even if processing repeats.
Exactly-once is a scoped transactional guarantee, not a magic spell.

```text
+------------------+-----------------------------+--------------------------+
| Guarantee        | Meaning                     | Typical implementation   |
+------------------+-----------------------------+--------------------------+
| At-most-once     | may lose work               | commit before processing |
| At-least-once    | may duplicate work          | process before commit    |
| Effectively-once | business effect once        | idempotency and constraints|
| Exactly-once     | scoped transaction          | Kafka transactions       |
+------------------+-----------------------------+--------------------------+
```

MegaShop uses at-least-once for search indexing.
If the same order is indexed twice, the document is overwritten by order_id.
MegaShop uses effectively-once for ledger entries.
The ledger table has a unique event_id.
MegaShop does not trust Kafka exactly-once to protect payment provider calls.
Payment calls use provider idempotency keys and reconciliation reports.
The correct interview sentence is precise.
Kafka exactly-once can help inside Kafka read-process-write pipelines.
External side effects still need idempotency and reconciliation.

---

## 23. Kafka transactions

Kafka transactions are useful when a process reads from Kafka and writes to Kafka.
Example:

```text
raw-orders topic -> stream processor -> enriched-orders topic
```

A Kafka transaction can include produced records and consumed offsets.
This prevents output without offset commit.
It also prevents offset commit without output.
That is useful for stream processing.
It does not include Stripe.
It does not include an email provider.
It does not include a warehouse API.
It does not include an arbitrary PostgreSQL write unless an external transaction strategy is built.
MegaShop uses Kafka transactions for some stream transformations.
MegaShop does not use Kafka transactions as a replacement for payment idempotency.
A beginner may hear exactly-once and relax.
A principal SRE hears exactly-once and asks scope.
Scope is everything.
Exactly once where.
Exactly once for which side effect.
Exactly once under which failure.
Exactly once observed by which system.
Without scope, exactly-once is marketing fog.

---

## 24. Partition key design

The partition key controls both ordering and distribution.
Kafka typically maps key to partition by hashing.

```text
partition = hash(key) % partition_count
```

If MegaShop keys order lifecycle events by order_id, all events for one order stay together.

```text
Partition 8
+-------------+-----------------+--------+---------+
| OrderPlaced | PaymentCaptured | Packed | Shipped |
+-------------+-----------------+--------+---------+
```

This preserves per-order order.
If MegaShop keys by product_id during a flash sale, one product can dominate one partition.

```text
Partition 0:   3K/sec
Partition 1:   2K/sec
Partition 2: 180K/sec
Partition 3:   4K/sec
```

This is a hot partition.
Adding consumers does not fix it.
One partition has one active owner per group.
The fix is better key design.
If per-order ordering matters, key by order_id.
If per-customer notification order matters, key by customer_id.
If product-level total order is not required, bucket product keys.

```text
key = product_id + ':' + hash(order_id) % 32
```

Bucketing spreads load but sacrifices total order for product_id.
That trade must be explicit.
Partition key is not metadata.
It is lane assignment for the event highway.

---

## 25. Hot partition diagnosis

A hot partition appears when one partition gets disproportionate traffic or work.
Symptoms:

```text
one partition lag dominates total lag
one consumer is CPU or I/O hot
other consumers are idle
adding consumers does not improve throughput
broker hosting that leader has high network or disk load
```

MegaShop sneaker launch example:

```text
product_id = SNKR-2026
producer key = product_id
most launch events use same key
all those events hash to one partition
inventory-projector falls behind
```

Wrong mitigation:

```text
scale consumers from 24 to 96
```

Why wrong:

```text
the hot partition still has one owner
more consumers can increase rebalance churn
```

Correct mitigation:

```text
stop autoscaling churn
confirm partition-level lag
roll back partition key if safe
route new events to corrected topic if needed
prioritize critical consumers
```

Permanent prevention:

```text
partition-key review before launch
hot-key load testing
per-partition lag alerts
producer contract tests
```

---

## 26. Consumer lag math

Consumer lag is the distance between the newest record and the consumer group's committed offset.

```text
lag = log end offset - committed offset
```

Example:

```text
log end offset:     1,000,000
committed offset:     850,000
lag:                 150,000 records
```

Lag growth depends on rates.

```text
producer rate: 50,000 records/sec
consumer rate: 35,000 records/sec
lag growth:    15,000 records/sec
```

After ten minutes:

```text
15,000 * 600 = 9,000,000 records behind
```

If producers stop:

```text
lag: 9,000,000
consumer rate: 35,000/sec
catch-up time: 257 seconds
```

If producers continue at 50,000/sec and consumers process 35,000/sec, there is no catch-up.
Lag grows forever.
Lag count can mislead.
Five million records behind at 500,000/sec is ten seconds behind.
Five million records behind at 100/sec is almost fourteen hours behind.
Business impact usually follows lag age.
MegaShop alerts on freshness by workflow, not only raw record count.

---

## 27. Lag pattern interpretation

All partitions lagging usually means broad capacity or dependency trouble.
Possible causes include consumer fleet too small.
Another cause is slow downstream dependency.
Another cause is bad consumer deploy.
Another cause is broker or network trouble.
One partition lagging means a different class of problem.
Possible causes include hot key.
Another cause is poison message.
Another cause is skewed partition assignment.
Sawtooth lag means periodic interruption.
Possible causes include rebalances.
Another cause is GC pauses.
Another cause is batch jobs.
Another cause is downstream throttling windows.
MegaShop dashboard must show lag by partition.
A single total lag graph hides one-partition disasters.
Example output:

```text
partition 00 lag:      1,200
partition 01 lag:      1,100
partition 02 lag:  8,500,000
partition 03 lag:        900
```

This is not a general capacity problem.
This is partition-specific.
The SRE should ask what key dominates partition 02.
The SRE should inspect consumer logs for repeated offset.
The SRE should compare processing latency by partition owner.
Scaling the whole group before answering those questions is guesswork.

---

## 28. Rebalancing

A rebalance changes which consumer owns which partitions.
Rebalances are normal when consumers join or leave.
Rebalance storms are incidents.

```text
Before:
Partition 0 -> Consumer A
Partition 1 -> Consumer A
Partition 2 -> Consumer B
Partition 3 -> Consumer B

After:
Partition 0 -> Consumer A
Partition 1 -> Consumer B
Partition 2 -> Consumer C
Partition 3 -> Consumer C
```

Triggers include consumer crash.
They include rolling deploy.
They include autoscaler flapping.
They include long GC pause.
They include network pause.
They include processing longer than max.poll.interval.ms.
A bad loop looks like this:

```text
slow processing
  -> missed poll interval
  -> rebalance
  -> partitions pause
  -> lag grows
  -> same slow work resumes
```

Mitigations include static membership.
They include cooperative rebalancing.
They include bounded processing time.
They include pause and resume under downstream pressure.
They include small-wave deployments.
They include avoiding autoscaler flapping.
Every deploy causing consumer lag spike is a smell.
Deployment should not be a scheduled consumption outage.

---

## 29. Retention

Kafka retention decides how long records remain.
Retention is not controlled by consumer acknowledgement.
A consumer reading a record does not delete it.
Time retention example:

```properties
retention.ms=604800000
```

That is seven days.
Size retention example:

```properties
retention.bytes=107374182400
```

That is roughly one hundred GB, depending topic and partition context.
Retention must be designed from recovery needs.
If analytics can be down for three days, one-day retention is unsafe.
If search rebuild takes two days, one-day retention is unsafe.
If legal replay requires one year, Kafka may not be the only storage layer.
Retention failure example:

```text
retention:       24 hours
consumer outage: 36 hours
missing replay:  12 hours
```

The consumer cannot read data Kafka deleted.
MegaShop sets longer retention for order-events than for click telemetry.
Business facts deserve more recovery time than low-value noise.
Retention is storage cost converted into recovery ability.

---

## 30. Compaction

Compaction keeps the latest value per key eventually.
It is not the same as time retention.
Example:

```text
key=user_1 value=A
key=user_1 value=B
key=user_1 value=C
```

After compaction, Kafka may keep:

```text
key=user_1 value=C
```

Compaction is useful for latest-state topics.
Examples include feature flags.
Examples include account settings.
Examples include current user profile.
Examples include service configuration.
Compaction is not appropriate for full audit history.
Payment ledger events should not be compacted away if every historical movement matters.
Security audit events should not rely only on compaction.
Compaction is eventual.
Old records may remain for some time.
A tombstone can mark a key for deletion in compacted topics.
Beginners often think compaction means immediate cleanup.
It does not.
Compaction is a background log cleaning strategy.
Use it when latest value per key is the goal.
Avoid it when every historical event is the goal.

---

## 31. Schema evolution

Kafka transports bytes.
Teams own meaning.
Schema evolution is the discipline of changing event structure without breaking consumers.
MegaShop has many consumers for OrderPlaced.
Search needs line items.
Fraud needs customer and device risk fields.
Analytics needs amount and currency.
Warehouse needs destination region.
Removing a field can break one of them.
Breaking changes include removing required fields.
They include renaming fields without migration.
They include changing string to integer.
They include changing field meaning under the same name.
They include reusing protobuf field numbers.
Safe evolution is staged.
Add optional field.
Deploy consumers that understand old and new fields.
Start writing new field.
Backfill if needed.
Stop reading old field.
Remove only after retention and compatibility window.
Protobuf example:

```proto
message OrderPlaced {
  string order_id = 1;
  int64 total_cents = 2;
  string currency = 3;
  reserved 4;
  reserved 'old_coupon_code';
}
```

Never reuse protobuf field numbers.
Old bytes can become new lies.

---

## 32. Retry topics

Immediate retry is often wrong.
If OpenSearch is rejecting writes, retrying immediately increases pressure.
If an email provider times out, immediate retries can become a storm.
A better pattern uses delayed retry topics.

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

The first failure goes to a one-minute retry.
The next failure goes to a five-minute retry.
Repeated failure eventually goes to DLQ.
Permanent validation errors should not be retried forever.
Transient downstream errors can use backoff.
Retry policy must classify errors.
MegaShop does not retry malformed schema events the same way it retries a temporary 503.
Retry without classification is a blender.
It mixes bugs, outages, and bad data into one noisy paste.

---

## 33. DLQ design

A DLQ is a dead-letter queue or topic.
It stores records that could not be processed after bounded attempts.
A DLQ is not a trash can.
A DLQ is an evidence locker.
Bad DLQ payload:

```json
{'error': 'failed'}
```

Useful DLQ payload includes original topic.
It includes original partition.
It includes original offset.
It includes key.
It includes headers.
It includes payload.
It includes schema version.
It includes error class.
It includes error message.
It includes failed timestamp.
It includes consumer group.
It includes application version.
It includes correlation_id.
DLQ operations require ownership.
Someone must monitor DLQ rate.
Someone must classify errors.
Someone must repair data or code.
Someone must replay intentionally.
Someone must delete or archive after policy.
A DLQ without replay tooling is a museum of broken promises.
MegaShop treats DLQ growth in payment and inventory consumers as high severity.
It treats DLQ growth in low-value analytics as lower severity but still actionable.
Severity follows business consequence.

---

## 34. Outbox pattern

The dual-write problem appears when an application writes to a database and publishes to Kafka separately.
Bad pattern:

```text
1. Write order to PostgreSQL.
2. Publish OrderPlaced to Kafka.
```

Failure one:

```text
DB commit succeeds.
Kafka publish fails.
Order exists, event missing.
```

Failure two:

```text
Kafka publish succeeds.
DB transaction rolls back.
Event exists for an order that does not.
```

Transactional outbox fixes this by writing business row and outbox row in the same database transaction.

```text
+----------+        same DB transaction        +---------------+
| orders   | <-------------------------------> | outbox_events |
+----------+                                   +---------------+
                                                     |
                                                     | CDC or relay
                                                     v
                                                 +-------+
                                                 | Kafka |
                                                 +-------+
```

The database transaction is atomic.
The publish is asynchronous.
If publisher fails, the outbox row remains.
A relay or CDC connector can retry.
MegaShop uses outbox for order events because missing OrderPlaced is unacceptable.
Outbox does not remove duplicate delivery.
Consumers still need idempotency.

---

## 35. CDC and Kafka Connect

CDC means change data capture.
A connector reads committed database changes and sends them downstream.
Debezium is a common CDC tool in Kafka ecosystems.
CDC can read PostgreSQL WAL or MySQL binlog.
CDC is powerful because it observes committed changes.
CDC is dangerous because it becomes part of the recovery path.
Connector lag means event lag.
Replication slots can retain WAL.
Retained WAL can fill disk.
A snapshot can overload the primary database.
Schema changes can break connector pipelines.
MegaShop monitors connector lag separately from consumer lag.
Outbox backlog means events are not leaving the database.
Kafka consumer lag means events reached Kafka but consumers are behind.
Those are different failures.
PostgreSQL slot query:

```sql
SELECT slot_name, active, restart_lsn, confirmed_flush_lsn
FROM pg_replication_slots;
```

If a replication slot is inactive and retained WAL grows, the connector threatens database availability.
The fix is not always dropping the slot.
Dropping the slot may force a re-snapshot.
A re-snapshot may overload the primary.
SRE response must weigh database safety against downstream freshness.

---

## 36. Kafka versus alternatives

SQS is best for simple managed task queues.
RabbitMQ is best for routing-heavy brokered work queues.
Kafka is best for replayable high-throughput event streams.
Redis Streams can fit modest Redis-native stream workloads.
NATS can fit low-latency messaging and request-reply patterns.
Kinesis can fit managed AWS shard streams.

```text
+--------------+--------------------------+-----------------------------+
| System       | Best at                  | Watch out for               |
+--------------+--------------------------+-----------------------------+
| SQS          | managed task queues      | limited replay semantics    |
| RabbitMQ     | routing and work queues  | huge backlogs hurt broker   |
| Kafka        | durable event streams    | partition-key complexity    |
| Redis Streams| lightweight streams      | memory and retention limits |
| NATS         | low-latency messaging    | durability mode matters     |
| Kinesis      | AWS managed streams      | shard throughput limits     |
+--------------+--------------------------+-----------------------------+
```

Choose SQS for one job to one worker.
Choose Kafka when replay and many independent consumers matter.
Choose RabbitMQ when routing semantics dominate.
Do not choose Kafka because it sounds senior.
Do not choose SQS when the event log is the product.
Tool choice follows semantics.
Semantics follow business needs.

---

## 37. Security and multi-tenancy

Kafka security is not optional in a shared platform.
Controls include TLS.
Controls include SASL authentication.
Controls include ACLs.
Controls include quotas.
Controls include topic naming policy.
Controls include schema governance.
MegaShop has many teams producing and consuming events.
One team should not write to payment topics without permission.
One analytics consumer should not read PII topics casually.
One runaway producer should not saturate broker network.
One broad-retention topic should not consume all disk.
Quotas protect shared clusters.
ACLs protect data boundaries.
Topic naming communicates ownership.
Example topic name:

```text
commerce.orders.events.v1
```

This is clearer than:

```text
events2
```

A mature Kafka platform classifies topics by criticality.
Payment and order events get stricter durability and alerting.
Low-value clickstream gets different cost and retention policy.
Not all topics deserve the same operational budget.

---

## 38. Capacity planning

Capacity planning begins with rates and sizes.
Example:

```text
message size:        2 KB
produce rate:        100,000 records/sec
raw ingress:         200 MB/sec
replication factor:  3
raw replicated write: about 600 MB/sec before compression
```

If compression ratio is four to one:

```text
compressed ingress:     50 MB/sec
replicated compressed:  150 MB/sec
```

Retention storage:

```text
compressed ingress: 50 MB/sec
retention:          7 days
replication:        3
storage:            about 90 TB
```

Consumer capacity example:

```text
Kafka fetch capacity:      100,000 records/sec
consumer CPU capacity:      80,000 records/sec
OpenSearch capacity:        20,000 records/sec
actual progress:            20,000 records/sec
```

If producers send 100,000 per second, lag grows by 80,000 per second.
Kafka is not the bottleneck.
OpenSearch is.
Capacity planning must include downstream systems.
A fast broker feeding a slow database simply creates a faster-growing backlog.

---

## 39. Observability

Kafka observability must cover brokers, producers, consumers, connectors, and downstream dependencies.
Broker signals include under-replicated partitions.
They include offline partitions.
They include ISR shrink rate.
They include produce latency.
They include fetch latency.
They include disk usage.
They include request handler idle percent.
Producer signals include send rate.
They include error rate.
They include retry rate.
They include request latency.
They include batch size.
They include compression ratio.
Consumer signals include lag by partition.
They include lag age.
They include processing latency.
They include commit latency.
They include rebalance count.
They include DLQ rate.
Connector signals include source lag.
They include task failures.
They include replication slot retained bytes.
Downstream signals include database p99, OpenSearch rejection rate, provider timeout rate, and worker saturation.
The golden incident question is simple.
Is Kafka the bottleneck, or is Kafka exposing another bottleneck.
MegaShop dashboards answer that by showing Kafka lag next to downstream p99.
A lag graph alone is half a flashlight.

---

## 40. Command output interpretation

Describe topic:

```bash
kafka-topics --bootstrap-server broker:9092 --describe --topic order-events
```

Example output:

```text
Topic: order-events  PartitionCount: 48  ReplicationFactor: 3
Topic: order-events  Partition: 0  Leader: 1  Replicas: 1,2,3  Isr: 1,2,3
Topic: order-events  Partition: 1  Leader: 2  Replicas: 2,3,1  Isr: 2,3
```

Interpretation:

```text
Partition 1 has lost replica 1 from ISR.
The partition is still available.
Durability margin is reduced.
Investigate broker 1, network, disk, and replication lag.
```

Consumer group command:

```bash
kafka-consumer-groups --bootstrap-server broker:9092 --describe --group search-indexer
```

Example output:

```text
TOPIC         PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG      HOST
order-events 0          1000000         1001000         1000     worker-1
order-events 1          900000          1600000         700000   worker-2
order-events 2          999500          1000000         500      worker-3
```

Interpretation:

```text
Partition 1 dominates lag.
Likely hot key, poison message, or slow worker-2.
Scaling all consumers blindly is not evidence-based.
```

---

## 41. Poison message failure

A poison message is a record that repeatedly crashes or fails a consumer.
It can block progress for one partition.

```text
Partition 4

+-----+---------+-----+-----+
| 100 |   101   | 102 | 103 |
+-----+---------+-----+-----+
          ^
          |
       poison
```

Symptoms include repeated logs for the same offset.
Symptoms include one partition lag growing.
Symptoms include low progress despite healthy brokers.
Symptoms include consumer restarts.
The fix is not silent skipping.
The fix is controlled quarantine.
Capture original topic.
Capture partition.
Capture offset.
Capture key.
Capture headers.
Capture payload.
Capture schema version.
Capture error class.
Capture consumer group.
Move to DLQ or quarantine.
Advance only with audit.
Build replay tooling.
Add schema validation.
Add bounded retries.
Poison messages are not trash.
They are evidence.

---

## 42. Downstream bottleneck failure

Kafka can be healthy while the pipeline is unhealthy.
MegaShop search-indexer consumes order events and writes to OpenSearch.
OpenSearch starts rejecting bulk writes.
Kafka lag grows.
The easy but wrong conclusion is Kafka is slow.
The correct diagnosis follows the path.

```text
+-------+      +----------+      +------------+
| Kafka | ---> | Consumer | ---> | OpenSearch |
+-------+      +----------+      +------------+
                                  bottleneck
```

Evidence:

```text
consumer CPU is moderate
Kafka fetch latency is normal
OpenSearch p99 is high
OpenSearch write queue is high
bulk rejection count is rising
```

Mitigation:

```text
pause non-critical indexing
reduce batch pressure if OpenSearch is choking
use bulk writes if not already
protect critical consumers
catch up at controlled rate
```

A broker can buffer pain.
It cannot erase downstream physics.

---

## 43. Retention loss failure

Retention loss happens when records expire before a consumer catches up.
Scenario:

```text
analytics retention: 24 hours
consumer outage:    36 hours
missing window:     12 hours
```

The consumer cannot replay deleted records.
If the source of truth is elsewhere, a backfill may be possible.
If Kafka was the only history, data is gone.
MegaShop does not rely on short-retention Kafka topics as the only legal order history.
Order authority lives in OrdersDB and ledger systems.
Kafka is a propagation and replay layer for downstream projections.
Some topics may also feed long-term data lake storage.
Retention should be based on recovery objectives.
Ask how long consumers can be down.
Ask how long rebuilds take.
Ask how long bugs may go unnoticed.
Ask how much storage cost is acceptable.
Then set retention.
Do not choose seven days because it sounds standard.
Default retention is not architecture.

---

## 44. Schema break failure

A producer deploy changes OrderPlaced.
It removes total_cents because the team thinks price service can be queried later.
Search still works.
Analytics fails.
Fraud silently treats missing amount as zero.
This is worse than a loud failure.
Schema changes can break consumers differently.
Some consumers crash.
Some consumers send records to DLQ.
Some consumers silently compute wrong results.
Silent semantic break is the most dangerous.
Prevention requires compatibility checks.
It requires consumer contract tests.
It requires schema registry policy.
It requires event owner approval.
It requires staged migration.
Safe change example:

```text
add optional discount_cents
teach consumers to handle it
start writing it
wait beyond retention window
remove old field only after no consumer needs it
```

Breaking schema in Kafka is like changing the shape of a key after handing copies to every building.
Doors will fail at different times.

---

## 45. Rebalance storm failure

A rebalance storm repeatedly pauses consumption.
MegaShop deploys search-indexer.
Pods restart in large waves.
Consumer group rebalances repeatedly.
Partitions stop and start.
Lag grows.
Autoscaler sees lag and adds pods.
More pods cause more rebalances.
This loop can turn a deploy into an outage.
Symptoms:

```text
rebalance count spikes
lag rises during deploy
consumer logs show revoked partitions repeatedly
max.poll.interval.ms violations appear
processing time p99 is high
```

Mitigation:

```text
deploy in smaller waves
use static membership where appropriate
avoid lag-only autoscaling reactions
reduce batch processing time
pause partitions when downstream is slow
separate long side effects from poll loop
```

A rebalance is not free.
It is a coordination event with business consequences.

---

## 46. MegaShop launch incident

Incident:

```text
event: celebrity sneaker launch
produce rate baseline: 8,000 records/sec
produce rate current: 55,000 records/sec
topic: order-events
partitions: 48
replication factor: 3
```

Lag:

```text
fraud lag:      80,000 stable
inventory lag:  9,200,000 growing
search lag:     31,000,000 growing
email lag:      4,800,000 growing
```

Partition sample:

```text
partition 03:       18,000
partition 04:       21,000
partition 05:    8,900,000
partition 06:       19,000
```

Recent change:

```text
producer key changed from order_id to product_id
launch product_id is SNKR-2026
consumers autoscaled from 24 to 96
search writes one document at a time to OpenSearch
email retries immediately on provider timeout
```

Diagnosis:

```text
product_id key created a hot partition
one partition has one active owner per group
consumer autoscaling cannot split it
search also has downstream OpenSearch bottleneck
email retry policy may amplify provider trouble
```

Immediate actions:

```text
stop autoscaling churn
confirm partition-level skew
roll back key to order_id if safe
prioritize fraud and inventory
throttle search backfill
add email retry backoff
preserve records
avoid silent offset skips
```

---

## 47. Incident anti-actions

Do not delete topic data to reduce lag.
That destroys evidence and may destroy recoverability.
Do not skip offsets silently.
That creates invisible data loss.
Do not scale consumers blindly.
One hot partition cannot be split by more consumers.
Do not increase partitions during a P1 without a migration plan.
Existing keys do not magically redistribute old records.
Do not trust stale projections for checkout correctness.
Search and inventory projections may lag.
The authoritative inventory service must decide reservation truth.
Do not run full-speed backfill into a saturated downstream system.
Backfill can become the second outage.
Do not ignore email because checkout is green.
Notification delay still affects customer trust.
Do not declare recovery when lag count is low but lag age violates SLO.
Do not close incident without partition-key prevention.
Do not close incident without retry-policy prevention.
Do not close incident without schema and DLQ review if bad records appeared.
A good incident review asks why the architecture allowed the blast radius.

---

## 48. Interview framing

When asked to design Kafka for a system, do not start with partitions.
Start with business events.
Ask which events exist.
Ask who produces them.
Ask who consumes them.
Ask which consumers are critical.
Ask what ordering is required.
Ask what replay is required.
Ask what retention is required.
Ask what duplicate behavior is safe.
Ask what schemas look like.
Ask how consumers fail.
Ask how lag is monitored.
Ask what DLQ process exists.
Then choose Kafka if replay, throughput, fanout, and per-key ordering justify it.
A strong interview answer says Kafka is not a normal queue.
It says ordering is per partition.
It says the partition key is central.
It says at-least-once requires idempotency.
It says exactly-once has scope.
It says consumer lag is business delay.
It says DLQ without replay tooling is incomplete.
It says operational readiness is part of the design.
That is how the answer becomes senior.

---

## 49. Decision matrix

```text
+-------------------------------+------------------------------+
| Requirement                   | Better fit                   |
+-------------------------------+------------------------------+
| immediate user response       | synchronous RPC              |
| one background job            | task queue                   |
| managed simple retry          | SQS                          |
| routing-heavy work queues     | RabbitMQ                     |
| many subscribers              | pub/sub                      |
| replayable event history      | Kafka                        |
| CDC fanout                    | Kafka plus Debezium          |
| low-latency ephemeral bus     | NATS                         |
| Redis-native modest stream    | Redis Streams                |
| AWS-managed shard stream      | Kinesis                      |
+-------------------------------+------------------------------+
```

Use Kafka when replay matters.
Use Kafka when many independent consumers need the same stream.
Use Kafka when high throughput exists.
Use Kafka when per-key ordering matters.
Use Kafka when retention has business value.
Do not use Kafka for one simple background job.
Do not use Kafka if the team cannot operate it.
Do not use Kafka when consumers cannot tolerate duplicates.
Do not use Kafka when ordering requirements are unknown.
Do not use Kafka just because the architecture diagram looks lonely without it.

---

## 50. Key takeaways

Messaging moves work across time, ownership, and failure domains.
Task queues distribute jobs.
Pub/sub fans out events.
Durable logs preserve replayable history.
Kafka is a distributed, replicated, partitioned commit log.
Kafka ordering is per partition.
Partition key design is correctness design.
Producer durability settings decide when writes are honestly acknowledged.
ISR shrink means durability margin is shrinking.
Consumer offsets are progress markers, not proof of business correctness.
At-least-once delivery requires idempotent consumers.
Kafka exactly-once is scoped to Kafka transactions.
External side effects need idempotency and reconciliation.
Consumer lag is business delay.
Lag age often matters more than lag count.
A hot partition cannot be fixed by blindly adding consumers.
Retention must exceed realistic recovery windows.
Compaction is for latest value per key, not full audit history.
Schema evolution is an operational contract.
DLQs are evidence lockers, not trash cans.
Outbox prevents database and broker dual-write divergence.
Kafka is powerful when replay, fanout, throughput, and ordering justify the cost.
Kafka is expensive confusion when used as a simple background-job queue.
