# Week 6, Topic 1: Message Queues and Kafka

Last verified: 2026-05-16

---

# Part 1: Orientation

## 1. What this chapter is trying to teach

Messaging systems exist because real systems cannot put every action inside one request.
A beginner sees a message broker and thinks it is a queue.
A production engineer sees time, failure, ownership, ordering, duplication, and recovery.
Kafka is not a bigger task queue.
SQS is not a smaller Kafka.
RabbitMQ is not Kafka with exchanges.
Redis Streams is not free Kafka because Redis is already nearby.
NATS is not a durable audit log unless configured and operated for that purpose.
The first goal is to understand semantics.
The second goal is to map semantics to production failure.
The third goal is to design systems that degrade without lying.
This chapter uses one running architecture named MegaShop.
MegaShop is a Fortune 500 style e-commerce platform.
MegaShop is a teaching model, not a claim about one company's private internals.
The platform has checkout, payments, inventory, search, email, fraud, warehouses, and analytics.
Every concept in this chapter is explained through that platform.
The chapter is beginner-friendly.
The chapter is also SRE-focused.
Each major concept explains what it is.
Each major concept explains why it exists.
Each major concept explains how it works internally.
Each major concept includes a MegaShop example.
Each major concept includes failure modes.
Each major concept includes SRE diagnosis.
Each major concept includes interview framing.
The target is not memorization.
The target is operational understanding.

## 2. MegaShop: the running architecture

MegaShop accepts customer orders across web, mobile, and partner APIs.
A checkout request touches several authoritative systems.
The order database is authoritative for order existence.
The payment ledger or payment provider is authoritative for payment status.
The inventory service is authoritative for stock reservation.
Search is a projection.
Analytics is a projection.
Email is a notification side effect.
Warehouse fulfillment is a downstream business process.
Fraud can be advisory or blocking depending risk policy.
A naive synchronous design forces checkout to wait for everything.

```text
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
```

This design makes optional systems part of user-facing availability.
If email is slow, checkout becomes slow.
If search indexing fails, checkout becomes fragile.
If analytics blocks, a user cannot buy a product.
The design confuses correctness with reaction.
A better design keeps authority in the critical path and moves reactions behind durable messaging.

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
                   |    +---------------> Search Indexer
                   +--------------------> Email Sender
```

Checkout now waits for the work that must be correct now.
Email, search, analytics, recommendations, and warehouse notification can happen later.
Later does not mean unimportant.
Later means separately observable.
If email is delayed, customer trust suffers.
If search is delayed, support and discovery suffer.
If fraud is delayed, risk posture may suffer.
Async work needs its own SLOs.

## 3. Critical path versus side-effect path

A critical path contains work that must complete before returning a correct response.
A side-effect path contains work that can complete after the response.
The split must be a product and correctness decision.
It cannot be decided by fashion.
MegaShop checkout critical path usually includes cart validation.
It includes price verification against the pricing authority.
It includes inventory reservation when overselling is not allowed.
It includes payment authorization when business policy requires payment confidence.
It includes writing the authoritative order record.
It includes recording a durable event or outbox row.
MegaShop checkout side-effect path usually includes receipt email.
It includes search indexing.
It includes analytics ingestion.
It includes recommendations refresh.
It includes warehouse notification if fulfillment can tolerate short delay.
It includes fraud enrichment when fraud is advisory.
Some workflows are exceptions.
If fraud policy blocks high-risk orders, fraud belongs in the critical path.
If warehouse reservation must be immediate, warehouse belongs in the critical path.
If a legal email token is required before completion, email may become critical.
Messaging does not decide correctness.
Architecture decides correctness, then messaging implements the chosen timing.

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

The critical-path rule is simple.
If returning success without the action would be a lie, keep it synchronous or make the asynchronous state explicit.
If returning success while the action continues is honest, it can move behind messaging.
A correct UI may say order placed and confirmation email pending.
A dishonest UI says everything complete when the order is still awaiting payment truth.
The architecture must not lie to the user.

## 4. The four things messaging decouples

Messaging decouples time.
The producer can finish before the consumer starts.
Messaging decouples failure.
A consumer outage does not need to fail the producer.
Messaging decouples ownership.
A producer can publish a business fact and downstream teams can own reactions.
Messaging decouples load.
A broker can absorb bursts while consumers drain at sustainable rates.
Every decoupling creates a corresponding obligation.
Time decoupling creates lag.
Failure decoupling creates delayed failure visibility.
Ownership decoupling creates schema contracts.
Load decoupling creates backlog and retention risk.
MegaShop gets value because checkout no longer waits for analytics.
MegaShop gets risk because analytics may lag silently for hours.
MegaShop gets value because search can rebuild from events.
MegaShop gets risk because replay can repeat unsafe side effects.
The SRE view is therefore not optional.
For every message path, ask what happens when consumers stop for one minute.
Ask what happens when consumers stop for one hour.
Ask what happens when consumers stop longer than retention.
Ask what happens when the same event is processed twice.
Ask what happens when an old event is replayed.
Ask what happens when a producer changes schema.
Ask what happens when one key receives most traffic.

---

# Part 2: Messaging Models

## 5. The three models people confuse

The word queue is often used carelessly.
There are at least three different models.
A task queue distributes work.
A publish-subscribe topic fans out messages.
A durable event log stores replayable history.
They all move messages.
They do not provide the same contract.
Choosing the wrong model creates design debt.
Using Kafka as a simple email job queue can be overkill.
Using SQS as a replayable event backbone can be insufficient.
Using pub/sub without schema ownership creates hidden coupling.
The correct design starts with semantics, not tooling.

```text
+--------------------+-----------------------------+------------------------------+
| Model              | Main question               | Typical example              |
+--------------------+-----------------------------+------------------------------+
| Task queue         | Which worker handles job?   | Send receipt email           |
| Publish/subscribe  | Who reacts to this event?   | OrderPlaced fanout           |
| Durable event log  | Who can replay history?     | order-events in Kafka        |
+--------------------+-----------------------------+------------------------------+
```

## 6. Task queue semantics

A task queue distributes units of work to workers.
The core semantic is one job is assigned to one worker at a time.
This does not mean the side effect can never happen twice.
It means the broker attempts to prevent concurrent processing of the same job.
MegaShop uses a task queue for receipt emails.
The job is SendReceiptEmail for order ord_123.
A worker receives the job.
The queue hides the job from other workers during the visibility timeout.
The worker calls the email provider.
The worker acknowledges the job.
The broker removes the job.
If the worker crashes before acknowledgement, the job becomes visible again.
Another worker may process it.
The queue protects availability of work.
The worker must protect idempotency of side effects.
Those are different responsibilities.
A task queue is usually best for background jobs.
It is good for image processing.
It is good for email delivery.
It is good for webhook retries.
It is good for report generation.
It is not ideal for long replayable history.
It is not ideal when many independent consumers need the same stream.
It is not ideal for rebuilding projections from historical facts.

```text
+----------+      +-------------+      +----------+
| Producer | ---> | Task Queue  | ---> | Worker A |
+----------+      +-------------+      +----------+
                         |
                         +------->     +----------+
                                       | Worker B |
                                       +----------+
```

Task queue design questions:
What is the job identity.
What makes the job complete.
How long should visibility timeout be.
How many retries are safe.
Which errors are retryable.
Which errors should go directly to DLQ.
What is the idempotency key.
What metric defines user impact.
MegaShop does not alert only on queue depth.
MegaShop alerts on oldest job age.
Oldest job age tells how long a user-facing side effect has been delayed.

## 7. Task queue failure timeline

The most important task queue failure is crash after side effect before ack.

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

## 8. Task queue operational metrics

Queue depth is not enough.
Depth is the number of waiting jobs.
Oldest age is the age of the oldest waiting job.
Arrival rate is jobs entering per second.
Drain rate is jobs completing per second.
Retry rate is jobs failing and returning.
DLQ rate is jobs permanently failing.
Worker saturation indicates whether workers are at capacity.
Downstream latency indicates whether the dependency is the bottleneck.
MegaShop email queue can have one million jobs during a sale and still be healthy if oldest age is low.
MegaShop payment settlement queue can have one thousand jobs and be unhealthy if oldest age is high.
Interpretation requires both rate and age.

```text
+------------------+--------------------+------------------+
| Signal           | Healthy example    | Dangerous example|
+------------------+--------------------+------------------+
| Queue depth      | high but falling   | low but rising   |
| Oldest age       | below SLO          | above SLO        |
| Retry rate       | low                | spike            |
| DLQ rate         | near zero          | sustained growth |
| Drain rate       | above arrival      | below arrival    |
+------------------+--------------------+------------------+
```

SRE interpretation:
If arrival rate exceeds drain rate, backlog grows.
If oldest age exceeds SLO, users are feeling delay.
If retry rate spikes, downstream or data quality may be failing.
If DLQ grows, some jobs require repair or code changes.
If workers are idle but backlog grows, the queue or polling path may be broken.
If workers are saturated and downstream is healthy, add workers.
If workers are saturated because downstream is slow, adding workers may worsen the outage.

## 9. Publish and subscribe semantics

Publish and subscribe fan out messages to multiple consumers.
The producer publishes a message once.
Many subscribers can receive or read it.
MegaShop publishes OrderPlaced.
Email sends a receipt.
Search indexes the order.
Analytics records revenue.
Fraud updates risk signals.
Warehouse prepares fulfillment.
The order service does not call every consumer directly.
The event decouples publisher from consumers.
This is powerful because new consumers can be added later.
It is risky because the publisher may not know every dependency.
A producer schema change can break a consumer it does not know exists.
Pub/sub reduces direct code coupling.
It does not remove semantic coupling.
Event contracts become the coupling surface.

```text
+-----------+      +-------------+      +----------+
| Publisher | ---> | OrderPlaced | ---> | Email    |
+-----------+      +-------------+      +----------+
                         |
                         +------->     +----------+
                         |             | Search   |
                         |             +----------+
                         |
                         +------->     +----------+
                                       | Analytics|
                                       +----------+
```

Good pub/sub events are facts.
OrderPlaced is a fact.
PaymentCaptured is a fact.
InventoryReserved is a fact.
SendEmail is not a fact.
SendEmail is a command.
ReserveInventory is a command.
Do not name commands as events.
Do not name events as commands.
That mistake creates confused ownership.
If a consumer receives OrderPlaced, it decides its reaction.
If a consumer receives SendEmail, someone is telling it what to do.
Both patterns can be valid.
They are not the same.

## 10. Pub/sub hidden coupling

Hidden coupling is the main pub/sub trap.
The order service may publish OrderPlaced.
Fraud may depend on customer_id.
Analytics may depend on total_cents.
Search may depend on line_items.
Warehouse may depend on destination_region.
A producer removes destination_region because checkout no longer uses it.
Warehouse breaks.
The publisher did not call warehouse directly.
The dependency still existed.
Pub/sub moves coupling from function calls to event contracts.
The correct response is schema ownership.
Every event needs an owner.
Every event needs compatibility rules.
Every event needs consumer discovery.
Every breaking change needs a migration plan.
Every high-value event needs a deprecation policy.
MegaShop treats OrderPlaced as a public platform contract.
It is versioned.
It has schema compatibility checks.
It has documented semantics.
It has known critical consumers.
It has retention and replay policy.
A casual JSON event is not enough for a Fortune 500 system.

## 11. Durable log semantics

A durable log stores records for a retention window.
Consumers track their own positions.
Kafka is mainly a durable event log.
A record is not removed because one consumer reads it.
The record remains until retention or compaction removes it.
MegaShop order-events can be consumed by fraud, search, analytics, email, and warehouse.
Each consumer group has its own offset.
Fraud can be current.
Search can be behind.
Analytics can replay from the beginning.
This independence is the reason Kafka is powerful.
Replay is the defining capability.
If search index is corrupted, MegaShop can rebuild it.
If analytics logic had a bug, MegaShop can reprocess history.
If a new feature needs historical order events, it can backfill.
Replay is also dangerous.
If old OrderPlaced events are replayed into an unsafe email consumer, old receipts are sent again.
If old payment commands are replayed unsafely, customers may be charged twice.
Durable history requires replay-safe consumers.

```text
Topic: order-events

+-------------+-----------------+------------+---------+-----------+
| OrderPlaced | PaymentCaptured | ItemPacked | Shipped | Delivered |
+-------------+-----------------+------------+---------+-----------+
      0               1              2           3          4

Consumer positions:

fraud-service        -> offset 4
search-indexer       -> offset 2
analytics-pipeline   -> offset 0
```

## 12. Choosing the model before the tool

The correct sequence is semantics first, tool second.
If one job should go to one worker, choose a task queue.
If one event should fan out to many subscribers, choose pub/sub.
If retained history and replay matter, choose a durable event log.
SQS can be excellent for task queues.
RabbitMQ can be excellent for routing-heavy work queues.
Kafka can be excellent for durable high-throughput event logs.
Redis Streams can be suitable for modest stream workloads.
NATS can be suitable for low-latency messaging patterns.
Kinesis can be suitable for AWS-managed shard streams.
MegaShop uses more than one messaging pattern.
Receipt email jobs may use a task queue.
Order events may use Kafka.
Some internal notifications may use pub/sub.
A mature architecture does not force every problem into one broker.
Tool uniformity is not the same as architectural clarity.

---

# Part 3: Kafka Internals

## 13. Kafka as a distributed commit log

Kafka is a distributed, replicated, partitioned commit log.
Distributed means the system runs across brokers.
Replicated means data has copies.
Partitioned means topics are split into ordered shards.
Commit log means records are appended and read by position.
Kafka does not behave like a normal mutable application table.
Kafka appends records to partitions.
Each partition has offsets.
Offsets increase as records are appended.
Consumers read records by offset.
Kafka is optimized for sequential I/O, batching, compression, and parallelism.
This makes it excellent for high-volume event streams.
It also means the partition model is central.
Ordering exists within a partition.
Parallelism exists across partitions.
The same unit gives both correctness and capacity.
That is the most important Kafka tradeoff.

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

## 14. Topics

A topic is a named stream of records.
MegaShop has an order-events topic.
It may also have payment-events, inventory-events, shipment-events, and customer-events.
A topic name should communicate ownership and meaning.
A topic named events is almost useless.
A topic named commerce.orders.events.v1 communicates domain and version.
Topic design includes retention.
It includes partition count.
It includes replication factor.
It includes cleanup policy.
It includes schema policy.
It includes ACLs.
It includes ownership.
A topic is an operational resource.
It is not just a string in producer code.
Changing topic settings can affect durability, storage, cost, recovery, and consumer behavior.
MegaShop treats order-events as a high-criticality topic.
It has longer retention than clickstream telemetry.
It has stricter schema compatibility.
It has stronger alerting.
It has more careful ACLs.
Not all topics deserve the same treatment.
Topic policy follows business value.

## 15. Partitions

A partition is an ordered shard of a topic.
Kafka uses partitions for scale and ordering.
A topic with one partition has total order but limited parallelism.
A topic with many partitions has more parallelism but no global ordering.
MegaShop order-events might have forty-eight partitions.
All events in partition seventeen are ordered relative to each other.
Events in partition seventeen and partition eighteen have no total order.
A partition is assigned to a leader broker.
Followers replicate from the leader.
Consumers in one group divide partitions among themselves.
Partition count influences maximum consumer parallelism.
If a group has ten consumers and a topic has six partitions, four consumers are idle for that topic.
If a topic has too few partitions, consumers cannot scale enough.
If a topic has too many partitions, metadata, recovery, and rebalancing overhead increase.
Partition count should be planned.
It is not a confetti setting.

## 16. Offsets

An offset is a position inside one partition.
Offset zero is the first record in that partition.
Offset one is the next record in that partition.
Offsets are not global across the topic.
Partition zero offset ten and partition one offset ten are unrelated positions.
Consumers track offsets per partition.
A consumer group commits offsets to remember progress.
The committed offset usually points to the next record to process.
If committed offset is 103, records before 103 are considered processed by that group.
This does not prove side effects succeeded.
It only proves the group recorded progress.
The distinction matters.
A consumer can commit early and lose business work.
A consumer can commit late and duplicate business work.
Offset management is where correctness meets operations.

```text
Partition 2

+-----+-----+-----+-----+-----+
| 100 | 101 | 102 | 103 | 104 |
+-----+-----+-----+-----+-----+
              ^
              |
          processing
```

## 17. Brokers, leaders, followers, and ISR

A broker is a Kafka server.
A cluster is a group of brokers.
Each partition has a leader.
The leader handles writes for that partition.
Followers replicate from the leader.
ISR means in-sync replicas.
An in-sync replica is caught up enough to count for durability.
With replication factor three, a partition has three replicas.
One is leader.
Two are followers.
If all are caught up, ISR has all three.
If one follower lags, ISR shrinks.
ISR shrink means reduced durability margin.
Under-replicated partitions mean replicas are not fully caught up.
Offline partitions mean no leader is available.
MegaShop pages quickly on offline partitions for order-events.
It also alerts on sustained under-replication.
For low-value telemetry, severity may be lower.
Severity follows business impact.

```text
+-----------+        +-----------+        +-----------+
| Broker 1  |        | Broker 2  |        | Broker 3  |
+-----------+        +-----------+        +-----------+
| P0 leader |        | P1 leader |        | P2 leader |
| P1 follow |        | P2 follow |        | P0 follow |
| P2 follow |        | P0 follow |        | P1 follow |
+-----------+        +-----------+        +-----------+
```

## 18. Replication factor and min.insync.replicas

Replication factor controls how many copies Kafka maintains.
A replication factor of three is common for important topics.
min.insync.replicas controls how many replicas must be in ISR for certain acknowledged writes.
Producer acks interact with min.insync.replicas.
For important MegaShop order events, a common baseline is replication.factor=3, min.insync.replicas=2, and acks=all.
That means at least two in-sync replicas are required before an acknowledged write succeeds.
If only one replica is in sync, writes fail.
This is painful.
It is also honest.
The system refuses to claim durable success when durability conditions are not met.
For debug telemetry, weaker durability might be acceptable.
For order events, silent loss is usually unacceptable.
Durability settings should follow consequence.

```text
+---------------------+-------------------------------+
| Setting             | Meaning                       |
+---------------------+-------------------------------+
| replication.factor=3| keep three copies when healthy|
| min.insync.replicas=2| need two safe replicas        |
| acks=all            | producer waits for safe write |
+---------------------+-------------------------------+
```

## 19. Controller and metadata

Kafka clients need metadata to know which broker leads each partition.
The cluster maintains metadata about topics, partitions, leaders, replicas, and ISR.
When leadership changes, metadata changes.
Producers and consumers refresh metadata.
Metadata problems can appear as request failures, stale leader errors, or client retries.
A broker can be up while some partition leaders are moving.
A controller change can cause temporary disruption.
Modern Kafka uses a metadata quorum instead of ZooKeeper in newer deployments.
The operational idea remains similar for this chapter.
Clients must know where partition leaders live.
Partition leadership must be stable enough for clients to operate.
Excessive leadership churn is a signal.
MegaShop tracks controller changes and leader election rates.
A spike during a broker incident can explain producer and consumer errors.

---

# Part 4: Producers

## 20. Producer write path from application to broker

A producer is a client that writes records.
MegaShop checkout produces OrderPlaced events.
The application creates an event.
The producer serializes key and value.
The producer chooses a partition.
The producer accumulates the record into a batch.
The producer sends the batch to the leader broker.
The leader appends the batch.
Followers replicate.
The leader responds based on acknowledgement settings.
This path has buffers and timeouts.
Producer success does not happen at object creation.
It happens when Kafka acknowledges according to configuration.
A beginner may think sending to Kafka is one instant operation.
A production engineer knows the send has batching, metadata, broker routing, retries, and durability semantics.

```text
+-------------+      +-------------+      +-------------+
| Application | ---> | Producer    | ---> | Leader      |
| creates evt |      | batches evt |      | appends log |
+-------------+      +-------------+      +-------------+
                                             |
                                             v
                                        +----------+
                                        | Followers|
                                        +----------+
```

## 21. Producer batching

Batching is central to Kafka throughput.
A producer groups records per topic-partition.
Larger batches reduce request overhead.
Compression works better on larger batches.
Batching can add small latency because the producer may wait briefly.
linger.ms controls how long the producer may wait to form a batch.
batch.size controls target batch size.
MegaShop low-latency payment events may use smaller linger.
MegaShop high-volume analytics events may use larger batching.
The tradeoff is latency versus throughput.
Batching does not change event semantics.
It changes transport efficiency.
A system with high produce rate and tiny batches wastes CPU and network.
A system with huge linger may add unacceptable delay.
The correct setting depends on SLO.

## 22. Producer acknowledgements

Producer acknowledgements decide when a write is considered successful.
acks=0 means the producer does not wait.
acks=1 means the leader acknowledges after local append.
acks=all means the leader waits for the in-sync replica condition.
MegaShop order-events should usually use acks=all.
The reason is simple.
Order events are business facts.
A lost OrderPlaced event can break search, warehouse, analytics, email, and audits.
acks=1 can acknowledge a record that is lost during leader failure.
acks=all with min.insync.replicas reduces this risk.
It can convert silent loss into visible write failure.
Visible failure can be retried or surfaced.
Silent loss becomes a reconciliation problem.
The best durability setting is not always the strongest.
It is the setting whose cost matches business consequence.

```text
acks=1 failure

T0  Producer sends record
T1  Leader appends record
T2  Leader sends success
T3  Leader dies before follower replication
T4  New leader lacks record
T5  Producer believes record exists
```

## 23. Producer idempotence

Producer retries can create duplicate appends.
The producer sends a batch.
The broker writes it.
The acknowledgement is lost.
The producer retries.
Without idempotence, the broker may append the same batch again.
Idempotent producer uses producer IDs and sequence numbers.
The broker can detect duplicate retry attempts for a partition.
This protects Kafka from duplicate producer writes caused by retry ambiguity.
It does not protect downstream side effects.
If a consumer processes a valid event twice, producer idempotence does nothing.
Producer idempotence protects the path into Kafka.
Consumer idempotence protects the path out of Kafka.
Both matter.
MegaShop enables producer idempotence for business events.
It still builds idempotent consumers.

```text
Without idempotent producer

+----------+      +--------+
| Producer | ---> | Broker |
+----------+      +--------+
     |               |
     | send batch    |
     | ack lost      |
     | retry batch   |
     v               v
 duplicate append possible
```

## 24. Producer Python example

Python examples in this chapter are conceptual.
Exact client APIs vary by library.
The important parts are key selection, event identity, serialization, and delivery handling.
MegaShop uses order_id as key for order lifecycle events.
That keeps all events for one order in order.
The producer should not ignore delivery errors.
A fire-and-forget business producer is unsafe.
The application should observe failures.
It should retry according to policy.
It should avoid claiming success when durable publication failed.
Often the outbox pattern is better than direct publish inside request code.
Still, producer code clarifies semantics.

```python
import json
from datetime import datetime, timezone

def build_order_placed(order):
    return {
        "event_id": f"evt_order_placed_{order['id']}",
        "event_type": "OrderPlaced",
        "schema_version": 1,
        "aggregate_type": "Order",
        "aggregate_id": order["id"],
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "payload": {
            "order_id": order["id"],
            "customer_id": order["customer_id"],
            "total_cents": order["total_cents"],
            "currency": order["currency"],
        },
    }

def publish_order_placed(producer, order):
    event = build_order_placed(order)
    key = event["aggregate_id"].encode("utf-8")
    value = json.dumps(event).encode("utf-8")
    producer.produce(
        topic="commerce.orders.events.v1",
        key=key,
        value=value,
        headers={
            "event_type": event["event_type"],
            "schema_version": str(event["schema_version"]),
        },
    )
    producer.flush()
```

The important detail is not the specific library call.
The important detail is key=order_id.
The second important detail is event_id.
The third important detail is schema_version.
The fourth important detail is observing delivery failure.
A business event producer that drops errors is a data-loss machine.

## 25. Producer failure handling

Producer failure handling must distinguish transient failure from durable uncertainty.
A broker timeout does not always mean the record was not written.
It may mean the acknowledgement was lost.
Idempotent producer helps with retry duplicates.
The application still needs a correctness strategy.
For request-path business events, the outbox pattern is often safer.
The application writes order and outbox event in the same database transaction.
A relay or CDC connector publishes later.
This avoids database and Kafka dual-write inconsistency.
Direct producing from request code can be acceptable for some non-authoritative events.
It is risky for authoritative business facts unless failure handling is rigorous.
MegaShop uses outbox for OrderPlaced.
MegaShop may directly publish non-critical telemetry.
Again, consequence decides design.

---

# Part 5: Consumers

## 26. Consumer read path

A consumer reads records from assigned partitions.
A consumer group coordinates partition ownership.
A poll call fetches records.
The application processes records.
The consumer commits offsets when work is safe.
MegaShop search-indexer consumes order-events.
It transforms OrderPlaced into a search document.
It writes the document to OpenSearch.
It commits offsets after the write is safe.
If it commits before writing, records can be lost from the projection.
If it writes before committing and crashes, records can be processed again.
Therefore the search write must be idempotent.
Using order_id as document ID makes repeated indexing overwrite the same document.
That is a good idempotency pattern.

```text
+-------------+      +-------------+      +------------+
| Kafka       | ---> | Consumer    | ---> | OpenSearch |
| Partition   |      | Application |      | Index      |
+-------------+      +-------------+      +------------+
                          |
                          v
                    commit offset
```

## 27. Consumer groups in depth

A consumer group lets multiple consumer instances share partitions.
Within a group, each partition is owned by one active consumer.
Different groups are independent.
MegaShop has fraud-service group.
MegaShop has search-indexer group.
MegaShop has analytics-pipeline group.
Each group reads the same topic at its own pace.
Adding consumers helps only until consumer count reaches partition count.
If order-events has forty-eight partitions, search-indexer can use at most forty-eight active partition owners.
More consumers may be useful for standby or other topics.
They do not increase parallelism for that topic.
This is why partition count is a capacity decision.
It is also why hot partitions are painful.
One hot partition cannot be split inside one group.

```text
Topic: order-events
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

## 28. Consumer configuration

Consumer settings control correctness and stability.
group.id defines the consumer group.
enable.auto.commit controls automatic offset commit.
auto.offset.reset controls start position when no offset exists.
max.poll.records controls batch size.
max.poll.interval.ms controls how long processing may take between polls.
session.timeout.ms controls failure detection.
heartbeat.interval.ms controls heartbeat frequency.
fetch.min.bytes and fetch.max.wait.ms tune throughput and latency.
For side-effecting consumers, enable.auto.commit=false is usually safer.
Manual commit lets the application commit after durable work.
MegaShop search-indexer commits after OpenSearch write success.
MegaShop analytics may commit after writing to object storage or data warehouse.
MegaShop email sender commits after idempotent send handling.
Wrong configuration can create outages.
Too large max.poll.records can make processing exceed max.poll.interval.ms.
Too small fetch sizes can reduce throughput.
Too short session timeout can trigger rebalances during short pauses.
Configuration must match processing behavior.

```text
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

## 29. Offset commit correctness

Offset commits are correctness boundaries.
Commit before processing can lose business work.
Process before commit can duplicate work.
At-most-once chooses possible loss.
At-least-once chooses possible duplication.
Most business systems prefer at-least-once with idempotency.
MegaShop order projections prefer duplicate-safe processing over missing records.
If search indexes the same order twice using order_id as document ID, final state is correct.
If ledger inserts the same event twice without unique event_id, final state is wrong.
Every consumer must define safe duplicate behavior.
The broker cannot infer business correctness.
Offset commit only records read progress.
It does not prove external side effects are correct.

```text
Commit before processing

poll offset 102
commit offset 103
crash before side effect

Result:
Kafka believes 102 is done.
Business effect may be missing.
```

```text
Process before commit

poll offset 102
write side effect
crash before commit

Result:
Kafka redelivers 102.
Business effect may repeat.
```

## 30. Consumer Python example

A dense consumer example shows the real pattern.
The consumer parses the event.
It checks schema version.
It computes an idempotency key.
It writes the side effect safely.
It commits after success.
It sends malformed records to DLQ with context.
The exact client library can vary.
The conceptual flow should not vary.

```python
import json

def process_order_for_search(event, search_client):
    order_id = event["payload"]["order_id"]
    document = {
        "order_id": order_id,
        "customer_id": event["payload"]["customer_id"],
        "total_cents": event["payload"]["total_cents"],
        "currency": event["payload"]["currency"],
    }
    search_client.index(
        index="orders",
        id=order_id,
        document=document,
    )

def handle_record(record, search_client, dlq_producer):
    try:
        event = json.loads(record.value)
        if event.get("event_type") != "OrderPlaced":
            return "skip"
        if event.get("schema_version") not in (1, 2):
            raise ValueError("unsupported schema version")
        process_order_for_search(event, search_client)
        return "success"
    except Exception as exc:
        dlq_payload = {
            "original_topic": record.topic,
            "original_partition": record.partition,
            "original_offset": record.offset,
            "key": record.key.decode("utf-8") if record.key else None,
            "error_class": type(exc).__name__,
            "error_message": str(exc),
            "payload": record.value.decode("utf-8", errors="replace"),
        }
        dlq_producer.produce(
            topic="search-indexer-dlq",
            key=record.key,
            value=json.dumps(dlq_payload).encode("utf-8"),
        )
        return "dlq"
```

This example uses order_id as OpenSearch document ID.
Repeated indexing is safe because the same document is overwritten.
That is idempotency through deterministic identity.
A ledger consumer needs stronger protection.
A payment consumer needs provider idempotency.
An email consumer needs sent markers.
Different side effects require different duplicate controls.

## 31. Idempotency patterns by side effect

Idempotency is not one technique.
It depends on the side effect.
For search indexing, use deterministic document ID.
For ledger entries, use unique event_id.
For email, use notification sent marker.
For webhook delivery, use event_id plus destination_id.
For payment provider calls, use provider idempotency key.
For warehouse shipment, use shipment request id and reconciliation.
For cache invalidation, duplicate invalidation is usually harmless.
For analytics counters, duplicate processing can overcount unless event_id dedupe exists.
MegaShop designs idempotency per consumer.
The key principle is stable business identity.
Do not dedupe by timestamp.
Do not dedupe by random attempt ID.
Dedupe by the logical operation.
If the operation is send receipt for order ord_123 using template v3, that is the key.
If the operation is ledger entry for PaymentCaptured evt_789, event_id is the key.
If the operation is webhook delivery of event evt_789 to seller seller_42, event_id plus destination is the key.

```text
+--------------------+--------------------------------------+
| Side effect        | Idempotency strategy                 |
+--------------------+--------------------------------------+
| Search index       | document id = order_id               |
| Ledger entry       | unique event_id                      |
| Email receipt      | order_id + template + recipient      |
| Webhook delivery   | event_id + destination_id            |
| Payment capture    | provider idempotency key             |
| Cache invalidation | naturally repeatable operation       |
+--------------------+--------------------------------------+
```

---

# Part 6: Correctness Semantics

## 32. At-most-once delivery

At-most-once means a record may be lost from the business perspective.
A consumer can commit offset before processing.
If it crashes before side effect, Kafka will not redeliver.
This can be acceptable for low-value telemetry.
It is unacceptable for orders, payments, inventory, ledgers, or security events.
MegaShop may tolerate at-most-once for sampled debug events.
MegaShop does not tolerate at-most-once for OrderPlaced.
The phrase at-most-once sounds safe because it avoids duplicates.
It is dangerous because it permits loss.
In business workflows, missing work is often worse than duplicate attempts.
A duplicate attempt can be deduped.
Missing work may never be discovered until a customer complains.

## 33. At-least-once delivery

At-least-once means the system does not intentionally lose records but may process duplicates.
This is the most common production posture for business events.
The consumer processes first.
The consumer commits later.
If it crashes after processing but before commit, Kafka redelivers.
This requires idempotency.
MegaShop uses at-least-once for search indexing.
It uses at-least-once for analytics with event_id dedupe.
It uses at-least-once for email with sent markers.
It uses at-least-once for warehouse notification with request IDs.
The duplicate is not a bug by itself.
The bug is duplicate side effect damage.
At-least-once is honest.
It says retries and crashes happen.
Design your side effects accordingly.

## 34. Effectively-once processing

Effectively-once means infrastructure may deliver duplicates but business state changes once.
This is usually achieved with idempotency and unique constraints.
Example ledger table:
event_id is primary key.
If PaymentCaptured evt_123 is processed twice, only one ledger entry exists.
The second attempt conflicts and is skipped.
This gives effectively-once business result.
It is not because Kafka delivered exactly once.
It is because the consumer and database enforce uniqueness.
MegaShop uses effectively-once patterns for money-related projections.
A good design layers broker guarantees with application invariants.
The broker provides delivery.
The database enforces state correctness.
The reconciliation job verifies external truth.

## 35. Exactly-once scope

Exactly-once is meaningful only with scope.
Kafka transactions can help when reading from Kafka and writing to Kafka.
Example:
raw-orders topic is consumed by a stream processor.
The processor writes enriched-orders topic.
Offsets and produced records can be committed transactionally.
This prevents output without offset commit.
It prevents offset commit without output.
It does not make Stripe charge exactly once.
It does not make email send exactly once.
It does not make a warehouse API exactly once.
It does not make an arbitrary PostgreSQL write exactly once unless the design includes that database in a safe transaction pattern.
A principal engineer always asks exactly once where.
Exactly once for which state.
Exactly once under which failure.
Exactly once observed by which system.
Without scope, exactly-once is marketing fog.

## 36. Reconciliation

Reconciliation is the process of comparing systems of record and repairing differences.
Messaging systems need reconciliation because asynchronous workflows can drift.
MegaShop compares OrdersDB against payment provider settlements.
It compares OrdersDB against warehouse shipment requests.
It compares order-events against search index freshness.
It compares outbox rows against Kafka publication status.
Reconciliation catches failures that idempotency and retries did not fully prevent.
For payments, reconciliation is mandatory.
A timeout from a payment provider is ambiguous.
The provider may have captured payment.
The provider may have rejected payment.
The response may have been lost.
Retrying blindly can double charge.
Reconciliation queries provider truth using stable references.
Messaging does not remove reconciliation.
It often makes reconciliation more important.

---

# Part 7: Partitioning and Ordering

## 37. Why partition key is architecture

The partition key determines where a record lands.
It also determines the ordering scope.
This makes it an architecture decision.
MegaShop order lifecycle needs per-order ordering.
OrderPlaced should come before PaymentCaptured for the same order.
PaymentCaptured should come before Shipped for the same order.
Keying by order_id preserves that order.
Keying randomly does not.
Keying by product_id may create hot partitions.
Keying by customer_id preserves customer order but may concentrate large customers.
There is no universally correct key.
There is only a key that matches required ordering and distribution.
The design review must explicitly state the ordering requirement.
If nobody can state the ordering requirement, the Kafka design is not ready.

## 38. Good key example: order_id

Order lifecycle events should often key by order_id.
MegaShop event sequence:
OrderPlaced order_123.
PaymentAuthorized order_123.
InventoryReserved order_123.
Packed order_123.
Shipped order_123.
All should land on the same partition.
Consumers see them in order for that order.
This helps search projection.
This helps warehouse workflow.
This helps audit reconstruction.
It does not create total ordering across all orders.
Order_123 events and order_456 events may interleave differently across partitions.
That is usually fine.
The business requirement is per-order order, not global order.
Global ordering would limit scale.
Choosing order_id gives the needed ordering without unnecessary bottleneck.

```text
Partition 8

+-------------+-------------------+-------------------+--------+---------+
| OrderPlaced | PaymentAuthorized | InventoryReserved | Packed | Shipped |
+-------------+-------------------+-------------------+--------+---------+
```

## 39. Bad key example: product_id during flash sale

Product ID seems reasonable if events involve products.
During a flash sale, it is dangerous.
MegaShop launches SNKR-2026.
Most orders include the same product_id.
Producer key is product_id.
All launch events hash to one partition.
That partition receives massive traffic.
Other partitions are mostly idle.
Consumer group parallelism collapses.
Inventory projection falls behind.
Search projection falls behind.
Adding consumers does not split one partition.
This is the classic hot partition failure.
The key was logically attractive and operationally harmful.
The correct key depends on ordering need.
If order lifecycle ordering matters, use order_id.
If product metrics do not need total order, use bucketed product key.

```text
Before launch

Partition 0:  10K/sec
Partition 1:   9K/sec
Partition 2:  11K/sec
Partition 3:  10K/sec

During launch with key=product_id

Partition 0:   3K/sec
Partition 1:   2K/sec
Partition 2: 180K/sec
Partition 3:   4K/sec
```

## 40. Bucketed keys

Bucketed keys spread load when strict ordering for the original key is not required.
Example:
product_id plus hash(order_id) modulo thirty-two.
The logical product is split across buckets.
SNKR-2026:00 goes to one partition.
SNKR-2026:01 goes to another.
SNKR-2026:02 goes to another.
This improves distribution.
It sacrifices total order for product_id.
That trade is acceptable only if total product ordering is not required.
Bucket count should be chosen with expected skew in mind.
Too few buckets may still hot spot.
Too many buckets can complicate downstream aggregation.
The consumer may need to aggregate across buckets.
MegaShop uses bucketing for high-volume product analytics.
MegaShop does not use bucketing for order lifecycle.
Different streams have different keys.

```text
key = product_id + ':' + bucket

+----------------+      +-------------+
| SNKR-2026:00   | ---> | Partition 4 |
+----------------+      +-------------+
| SNKR-2026:01   | ---> | Partition 9 |
+----------------+      +-------------+
| SNKR-2026:02   | ---> | Partition 2 |
+----------------+      +-------------+
```

## 41. Adding partitions later

Adding partitions to a Kafka topic is not a magic fix.
New records may distribute differently after partition count changes.
Existing records do not move.
Key-to-partition mapping changes when partition count changes.
This can affect ordering assumptions if producers use hash modulo partition count.
For a key, records before expansion may be in one partition.
Records after expansion may go to another partition.
That can break per-key ordering across the expansion point.
Some clients and partitioners have strategies, but the risk must be understood.
Increasing partitions during a P1 should be treated carefully.
It may not fix a current hot partition.
It may create ordering surprises.
MegaShop prefers creating a corrected topic and controlled migration for major key changes.
Partition count should be planned with growth and ordering in mind.

---

# Part 8: Lag, Backpressure, and Rebalancing

## 42. Consumer lag from first principles

Consumer lag is the distance between log end offset and committed offset.
It is measured per partition per consumer group.
Lag is not inherently bad.
Lag is bad when it violates business freshness or retention safety.
MegaShop search can tolerate short lag.
MegaShop fraud may tolerate less lag.
MegaShop analytics may tolerate more lag.
A single lag threshold for all consumers is crude.
Lag must be interpreted with rate and business context.

```text
log end offset:       1,000,000
committed offset:       850,000
lag:                   150,000
```

Lag growth formula:
producer rate minus consumer progress rate.
If producer rate is fifty thousand records per second and consumer progress is thirty-five thousand, lag grows by fifteen thousand per second.
After ten minutes, lag is nine million.
If producers stop and consumers process thirty-five thousand per second, catch-up takes about two hundred fifty-seven seconds.
If producers continue faster than consumers, catch-up never happens.

## 43. Lag age versus lag count

Lag count is records behind.
Lag age is time behind.
Age usually maps better to user impact.
Five million records behind can be ten seconds behind on a huge stream.
Five million records behind can be fourteen hours behind on a small stream.
MegaShop alerts on order search freshness in minutes.
It does not only alert on raw record count.
Lag age can be estimated from event timestamps or broker offsets with timestamp lookup.
A consumer that is one hour behind is causing stale business views.
A consumer that is ten seconds behind may be healthy during a surge.
The SRE question is not how many records are behind.
The SRE question is how old the work is and which business process depends on it.

## 44. Lag patterns

All partitions lagging suggests broad capacity or dependency trouble.
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

## 45. Backpressure

Backpressure prevents uncontrolled backlog growth.
If a consumer's downstream dependency is saturated, the consumer should not keep pushing at full speed.
Backpressure can pause partitions.
It can reduce batch size.
It can shed low-priority work.
It can move records into delayed retry topics.
It can slow producers if the architecture supports it.
MegaShop search-indexer applies backpressure when OpenSearch rejects writes.
It does not retry immediately forever.
It pauses or slows indexing.
It protects OpenSearch from collapse.
Backpressure turns an unbounded failure into a controlled delay.
Without backpressure, Kafka becomes a high-speed pipe into a broken sink.

## 46. Rebalancing in depth

A rebalance changes partition ownership in a consumer group.
Rebalances happen when consumers join or leave.
They also happen when consumers are considered dead.
A consumer can be considered dead if it misses heartbeats.
A consumer can be considered stuck if it exceeds max.poll.interval.ms.
During rebalance, partitions may pause.
Frequent rebalances reduce throughput.
MegaShop saw this when autoscaler reacted to lag by adding many pods.
New pods joined.
The group rebalanced.
Processing paused.
Lag grew.
Autoscaler added more pods.
The cycle continued.
Lag-only autoscaling can create oscillation.
Good autoscaling considers lag, processing rate, rebalance rate, and downstream capacity.
Mitigations include static membership.
Mitigations include cooperative rebalancing.
Mitigations include smaller deploy waves.
Mitigations include reducing batch processing duration.
Mitigations include separating polling from slow side effects.

---

# Part 9: Retention, Replay, Schema, and DLQ

## 47. Retention as recovery policy

Retention determines how long Kafka keeps records.
It is not a random storage setting.
It is a recovery policy.
MegaShop asks how long search can be broken before rebuild must still be possible.
It asks how long analytics can be down.
It asks how long a consumer bug might go unnoticed.
It asks whether the source of truth can backfill missing data.
If retention is shorter than outage duration, Kafka cannot provide replay.
Example:
retention is twenty-four hours.
analytics consumer is down thirty-six hours.
twelve hours of events may be unavailable from Kafka.
If OrdersDB can backfill, recovery may still be possible.
If Kafka was the only history, data is lost.
Order-events deserve longer retention than low-value click telemetry.
Storage cost buys recovery time.

```text
retention window: 24 hours
consumer outage: 36 hours
unavailable window: 12 hours
```

## 48. Compaction as latest-state retention

Compaction keeps the latest value per key eventually.
It is useful when latest state matters more than every event.
Feature flags are a good example.
Account settings are a good example.
Current user profile can be a good example.
Payment ledger history is not a good example.
Security audit history is not a good example.
Order lifecycle history is usually not a good example.
Compaction is eventual.
Old records may remain for some time.
A tombstone can mark a key for deletion.
Compaction is not immediate cleanup.
Compaction is not audit storage.
MegaShop uses compacted topics for configuration-like state.
MegaShop uses non-compacted retained topics for order history streams.

```text
Before compaction

key=user_1 value=A
key=user_1 value=B
key=user_1 value=C

After compaction

key=user_1 value=C
```

## 49. Replay safety

Replay means processing historical records again.
Replay is one of Kafka's strongest capabilities.
Replay is also one of its sharpest blades.
Safe replay examples:
rebuild search index with deterministic document IDs.
recompute analytics with event_id dedupe.
rebuild materialized views from facts.
Unsafe replay examples:
send receipt emails again.
charge payments again.
create warehouse shipments again.
call third-party webhooks again without dedupe.
MegaShop marks some consumers as replay-safe.
It marks some consumers as live-only unless replay mode is explicitly enabled.
A replay-safe consumer separates state rebuilding from side effects.
For example, search indexing is replay-safe because document ID is order_id.
Email sending is not replay-safe unless sent markers suppress duplicates.
Replay procedure must include target consumer group, start offset, rate limit, and side-effect policy.

## 50. Schema evolution in depth

Schema evolution is the process of changing event structure safely.
Kafka does not understand business meaning by itself.
It stores bytes.
Consumers interpret those bytes.
Breaking changes include removing required fields.
They include renaming fields without migration.
They include changing field type.
They include changing semantic meaning.
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

## 51. DLQ operating model

A DLQ stores records that could not be processed after bounded attempts.
A DLQ is an operations system, not a dumping ground.
A useful DLQ record preserves original topic.
It preserves original partition.
It preserves original offset.
It preserves key.
It preserves headers.
It preserves payload.
It preserves schema version.
It records error class.
It records error message.
It records failed timestamp.
It records consumer group.
It records application version.
It records correlation_id if available.
MegaShop has DLQ dashboards.
It has DLQ ownership.
It has replay tools.
It has retention policy for DLQ records.
It has severity rules.
Payment DLQ is urgent.
Search DLQ may be important but less immediately critical.
Low-value analytics DLQ may be lower severity.
Severity follows business consequence.

```text
+--------------------+-------------------------------+
| DLQ field          | Why it matters                |
+--------------------+-------------------------------+
| original_topic     | route replay                  |
| original_partition | preserve source position      |
| original_offset    | audit exact record            |
| key                | diagnose partitioning         |
| headers            | preserve metadata             |
| payload            | inspect failed data           |
| error_class        | classify failure              |
| consumer_group     | identify failing workload     |
+--------------------+-------------------------------+
```

## 52. Retry topics

Immediate retry is often harmful.
If downstream is unavailable, immediate retry increases load.
If the record is malformed, retry will never fix it.
Retry design should classify errors.
Validation errors usually go to DLQ quickly.
Transient provider errors can use delayed retry.
Capacity errors can use backpressure.
MegaShop uses retry topics for email provider timeouts.
The first retry waits one minute.
The next waits five minutes.
The next waits thirty minutes.
Then the record goes to DLQ.
Each retry preserves original event identity.
Each retry increments attempt count.
Retry metadata must not destroy original payload.

```text
+------------+      +----------+      +----------+      +-----+
| Main Topic | ---> | Retry 1m | ---> | Retry 5m | ---> | DLQ |
+------------+      +----------+      +----------+      +-----+
```

---

# Part 10: Outbox, CDC, and Integration

## 53. The dual-write problem

The dual-write problem happens when an application writes to a database and publishes to Kafka separately.
MegaShop checkout writes an order to OrdersDB.
It also needs to publish OrderPlaced.
If those are separate operations, failures can split truth.
DB commit can succeed and Kafka publish can fail.
Then order exists but event is missing.
Kafka publish can succeed and DB transaction can roll back.
Then event exists for an order that does not.
Both states are bad.
Distributed transactions are often avoided because they add coupling and operational complexity.
The transactional outbox pattern solves this with a local database transaction.
Write the order row and outbox event row atomically.
Publish from outbox later.

## 54. Transactional outbox

The outbox table stores events inside the same database transaction as business state.
MegaShop checkout inserts order row.
MegaShop checkout inserts outbox row.
Both commit together.
A relay or CDC connector reads the outbox and publishes to Kafka.
If publisher is down, outbox rows remain.
If database transaction rolls back, no outbox row exists.
This prevents divergence between order state and event existence.
Outbox does not remove duplicate delivery.
Consumers still need idempotency.
Outbox does not remove schema governance.
Outbox does not remove replay risk.
Outbox solves one specific but critical problem:
database state and event publication should not disagree.

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

## 55. CDC and Kafka Connect

CDC means change data capture.
A CDC connector reads committed database changes.
Debezium is a common CDC tool in Kafka systems.
For PostgreSQL, CDC reads WAL through replication mechanisms.
For MySQL, CDC reads binlog.
CDC is useful because it observes committed truth.
It is also operationally sensitive.
Connector lag means events are delayed.
Replication slots can retain WAL.
Retained WAL can fill disk.
A snapshot can overload the primary database.
Schema changes can break connector pipelines.
MegaShop monitors connector lag separately from consumer lag.
Outbox backlog means events are not leaving the database.
Kafka consumer lag means events reached Kafka but consumers are behind.
Those are different failures.

```text
+----------+      +-----------+      +-------+      +----------+
| OrdersDB | ---> | Connector | ---> | Kafka | ---> | Consumer |
+----------+      +-----------+      +-------+      +----------+
     |                 |                |              |
     | outbox backlog  | source lag     | topic lag    | group lag
```

## 56. CDC operational diagnosis

PostgreSQL replication slot retained bytes are critical.
If connector is down, WAL may accumulate.
If disk fills, OrdersDB is at risk.
A Kafka pipeline can become a database outage.
MegaShop checks replication slots during CDC incidents.
It checks active state.
It checks restart_lsn.
It checks confirmed_flush_lsn.
It checks retained bytes.
If retained bytes grow quickly, the response must protect the primary database.
Dropping a slot may force re-snapshot.
Re-snapshot may overload the database.
Restarting connector may be safe or unsafe depending failure mode.
SREs must understand the recovery trade.

```sql
SELECT
  slot_name,
  active,
  restart_lsn,
  confirmed_flush_lsn
FROM pg_replication_slots;
```

---

# Part 11: Operations, Security, and Capacity

## 57. Kafka security model

Kafka security includes encryption, authentication, authorization, quotas, and data classification.
TLS encrypts traffic.
SASL authenticates clients.
ACLs authorize operations.
Quotas limit noisy tenants.
Topic naming communicates ownership.
Schema governance prevents accidental breakage.
MegaShop has many teams.
The analytics team should not write payment events.
A random service should not read PII topics.
A runaway producer should not saturate broker network.
A topic with excessive retention should not consume all disk.
Security is not an afterthought.
It is part of multi-tenant platform design.

## 58. Topic classification

Not all topics have equal value.
MegaShop classifies topics by criticality.
Order and payment events are critical.
Inventory events are high criticality.
Search projection events are important.
Clickstream telemetry is lower criticality.
Debug events are lower criticality.
Critical topics get longer retention.
They get stronger durability.
They get stricter ACLs.
They get faster paging.
They get compatibility gates.
Lower criticality topics may get cheaper storage and weaker paging.
Uniform policy across all topics wastes money and hides priority.
Classification turns Kafka from a shared junk drawer into a governed platform.

## 59. Capacity planning

Kafka capacity depends on message size, produce rate, replication factor, compression, partition count, broker disk, broker network, and consumer throughput.
MegaShop flash sale planning starts with expected orders per second.
It estimates event size.
It estimates compression ratio.
It multiplies by replication factor.
It checks broker network and disk.
It checks consumer capacity.
It checks downstream systems.
Kafka can be healthy while OpenSearch is the bottleneck.
Kafka can accept events faster than consumers can use them.
That creates lag.
Capacity planning must include the slowest required step.

```text
message size:        2 KB
produce rate:        100,000 records/sec
raw ingress:         200 MB/sec
replication factor:  3
raw replicated write: about 600 MB/sec
compression ratio:   4:1
compressed write:    about 150 MB/sec
```

## 60. Retention storage math

Retention storage is often surprising.
If compressed ingress is fifty MB per second and retention is seven days, the raw retained compressed data is large.
Seven days is six hundred four thousand eight hundred seconds.
Fifty MB per second times that duration is about thirty TB.
With replication factor three, storage is about ninety TB.
This ignores overhead and safety margin.
Retention is therefore expensive.
It buys recovery.
MegaShop uses longer retention for critical business facts.
It uses shorter retention for high-volume low-value telemetry.
Cost and recovery are traded deliberately.

```text
compressed ingress: 50 MB/sec
retention:          604,800 sec
replication:        3

storage = 50 * 604,800 * 3 MB
storage = 90,720,000 MB
storage = about 90 TB
```

## 61. Observability architecture

Kafka observability must cover the whole pipeline.
Broker metrics show cluster health.
Producer metrics show write behavior.
Consumer metrics show read progress.
Connector metrics show source movement.
Downstream metrics show sink capacity.
Business metrics show user impact.
A lag graph without downstream latency is incomplete.
A broker dashboard without consumer lag is incomplete.
A DLQ graph without replay ownership is incomplete.
MegaShop dashboard places order-events consumer lag next to OpenSearch write rejection rate.
It places outbox backlog next to connector status.
It places email lag next to provider timeout rate.
It places fraud lag next to risk decision delay.
The goal is causal diagnosis, not metric decoration.

## 62. Command interpretation

Kafka commands are useful only if interpreted correctly.
Topic description shows leaders, replicas, and ISR.
Consumer group description shows current offset, log end offset, and lag.
A single large lag value is not enough.
You must inspect partition distribution.
You must map partition owner to host.
You must compare consumer logs.
You must compare downstream latency.
MegaShop trains SREs to ask what changed.
Producer key change.
Consumer deploy.
Broker disk pressure.
OpenSearch rejection.
Schema deployment.
Connector restart.
The command output is the beginning of diagnosis, not the end.

```text
kafka-consumer-groups --bootstrap-server broker:9092 \
  --describe --group search-indexer

TOPIC         PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG      HOST
order-events 0          1000000         1001000         1000     worker-1
order-events 1          900000          1600000         700000   worker-2
order-events 2          999500          1000000         500      worker-3
```

Interpretation:
Partition one dominates lag.
Likely hot key, poison message, or slow worker.
Scaling all consumers blindly is not justified.
Check logs for repeated offset on worker-2.
Check key distribution for partition one.
Check downstream calls from worker-2.

---

# Part 12: Production Failure Modes

## 63. Failure mode: Poison message blocks a partition

A poison message is a record that repeatedly fails a consumer.
It may be malformed.
It may violate schema.
It may trigger an application bug.
It may reference missing downstream state.
It can block one partition because consumers process in order.
MegaShop search-indexer sees offset 8819231 repeatedly.
Partition five lag grows.
Other partitions stay healthy.
DLQ is empty because the consumer keeps retrying in memory.
The fix is controlled quarantine.
Capture original topic, partition, offset, key, headers, payload, schema version, and error.
Move the record to DLQ or quarantine.
Advance only with audit.
Decide whether later records can be processed without violating order.
Add bounded retries.
Add schema validation.
Add replay tooling.

## 64. Failure mode: Downstream bottleneck appears as Kafka lag

Kafka lag can be caused by a slow sink.
MegaShop search-indexer writes to OpenSearch.
OpenSearch starts rejecting bulk writes.
Consumer lag grows.
Consumer CPU is moderate.
Broker fetch latency is normal.
The bottleneck is OpenSearch.
Adding Kafka brokers does not help.
Adding consumers may worsen OpenSearch pressure.
The fix is backpressure.
Pause non-critical indexing.
Use bulk writes.
Throttle catch-up.
Protect critical consumers.
Alert on downstream p99 and rejection rate.

## 65. Failure mode: Hot partition during launch

MegaShop changes key from order_id to product_id.
SNKR-2026 launch sends most events with the same product_id.
All those events land on one partition.
One consumer owns that partition.
Inventory projection falls behind.
Search projection falls behind.
Autoscaling consumers does not fix one partition.
Autoscaling may increase rebalance churn.
The fix is to stop churn.
Confirm partition-level lag.
Roll back key if safe.
Route new events to corrected topic if necessary.
Use order_id for order lifecycle.
Use bucketed product_id only where total product order is not required.

## 66. Failure mode: Retention expires before recovery

Analytics consumer is down for thirty-six hours.
Topic retention is twenty-four hours.
Twelve hours of records are gone from Kafka.
Recovery now depends on another source of truth.
If no source exists, data is lost.
The fix is not during the incident.
The fix is retention design before the incident.
Retention must exceed realistic detection and recovery time.
Critical topics need longer retention.
Low-value telemetry can use shorter retention.
Backfill paths must be tested.

## 67. Failure mode: Schema change breaks consumers

Producer removes total_cents from OrderPlaced.
Analytics consumer fails loudly.
Fraud consumer silently treats amount as zero.
Silent semantic failure is worse than crash.
Compatibility checks should block unsafe changes.
Consumer contract tests should run before producer deploy.
Schema registry policy should enforce allowed changes.
Old records must remain readable after new code deploy.
Retention means consumers may read old schemas long after deployment.
Versioned handlers are safer than assumptions.

## 68. Failure mode: Rebalance storm during deploy

Search-indexer deploy restarts too many pods at once.
Consumer group rebalances repeatedly.
Partitions pause during assignment.
Lag grows.
Autoscaler sees lag and adds pods.
More pods cause more rebalances.
The fix is smaller waves.
Use static membership where appropriate.
Use cooperative rebalancing.
Do not autoscale on lag alone.
Include downstream capacity and rebalance rate.

## 69. Failure mode: DLQ becomes unmanaged storage

Records go to DLQ.
No team owns the DLQ.
No replay tool exists.
No dashboard exists.
No retention policy exists.
DLQ grows for weeks.
The system has not recovered.
It has only hidden failure in another topic.
The fix is ownership.
Every DLQ needs alerting.
Every DLQ needs classification.
Every DLQ needs replay policy.
Every DLQ needs cleanup policy.

## 70. Failure mode: Connector lag threatens primary database

Debezium connector stops.
PostgreSQL replication slot retains WAL.
Primary disk fills.
Order database availability is threatened.
A Kafka pipeline has become a database incident.
The fix is careful.
Restart connector if safe.
Increase disk if needed.
Throttle writes only if necessary.
Do not drop slot without understanding re-snapshot consequences.
Protect the source of truth first.

---

# Part 13: Full MegaShop Incident Walkthrough

## 71. Incident report

Incident severity is P1.
Event is celebrity sneaker launch.
Topic is order-events.
Partition count is forty-eight.
Replication factor is three.
min.insync.replicas is two.
Produce rate baseline is eight thousand records per second.
Produce rate current is fifty-five thousand records per second.
Fraud lag is eighty thousand and stable.
Inventory lag is nine million two hundred thousand and growing.
Search lag is thirty-one million and growing.
Email lag is four million eight hundred thousand and growing.
Rebalance rate is one hundred forty per hour.
DLQ rate is low.
Partition lag sample shows partition five has eight million nine hundred thousand lag.
Other sampled partitions have around twenty thousand.
Recent change changed producer key from order_id to product_id.
Launch product_id is SNKR-2026.
Consumers autoscaled from twenty-four to ninety-six.
Search writes one document at a time to OpenSearch.
Email retries immediately on provider timeout.

```text
+----------+      +----------+      +----------+      +-------+
| Checkout | ---> | OrdersDB | ---> | Outbox   | ---> | Kafka |
+----------+      +----------+      +----------+      +-------+
                                                           |
               +-------------------+-----------------------+-------------------+
               |                   |                       |                   |
               v                   v                       v                   v
        +-------------+     +---------------+       +--------------+     +-----------+
        | Fraud       |     | Inventory     |       | Search       |     | Email     |
        | Consumer    |     | Projector     |       | Indexer      |     | Sender    |
        +-------------+     +---------------+       +--------------+     +-----------+
```

## 72. Incident diagnosis

The primary root cause is partition-key change.
Key changed from order_id to product_id.
During launch most records share SNKR-2026.
Those records hash to one partition.
One partition has one active owner per consumer group.
Adding consumers cannot split that partition.
Inventory lag grows because its hot partition cannot drain fast enough.
Search lag is worse because it also writes one document at a time to OpenSearch.
Email lag may be amplified by immediate retries against a timing-out provider.
The low DLQ rate means records are not mostly failing permanently.
The high rebalance rate indicates autoscaling or deploy churn is making consumption less stable.
Kafka brokers may be healthy.
The pipeline is still unhealthy.
The correct diagnosis connects producer key, partition lag, consumer group semantics, downstream capacity, and retry behavior.

## 73. Incident mitigation

Stop autoscaling churn.
Confirm partition-level lag.
Find dominant keys on the hot partition if tooling allows.
Roll back producer key to order_id if compatible.
If rollback cannot preserve ordering safely, cut over new events to a corrected topic.
Prioritize fraud and inventory consumers.
Throttle or pause search indexing if it competes for critical resources.
Change email retry behavior to exponential backoff with jitter.
Do not delete topic data.
Do not skip offsets silently.
Do not increase partitions in panic without migration plan.
Do not trust stale projections for checkout correctness.
Do not run full-speed backfill into a saturated OpenSearch cluster.
Communicate that checkout authority is separate from projection freshness.
Keep support informed about delayed email and search freshness.

## 74. Incident prevention

Partition-key changes require architecture review.
Flash-sale hot-key tests must run before launch.
Per-partition lag alerts must exist.
Lag-age alerts must exist.
Consumer autoscaling must account for rebalance rate.
Search indexing must use bulk writes and backpressure.
Email retry policy must use bounded retries with jitter.
Critical and non-critical consumers need separate capacity protection.
Schema compatibility checks must gate producer deploys.
DLQ replay tooling must be tested.
Retention must exceed expected recovery windows.
Incident review should produce engineering controls, not just a story.

---

# Part 14: Interview and Review

## 75. How to answer Kafka in system design interviews

Start with the business event.
Do not start with Kafka.
Ask what event is produced.
Ask who consumes it.
Ask what ordering is required.
Ask what duplicate behavior is acceptable.
Ask how long consumers can lag.
Ask whether replay is required.
Ask which system is authoritative.
Ask what happens if consumers are down for a day.
Ask how schema evolves.
Ask how DLQ records are repaired.
Then choose Kafka if replay, fanout, throughput, and per-key ordering justify it.
State that Kafka is not a normal queue.
State that ordering is per partition.
State that partition key is central.
State that at-least-once requires idempotency.
State that exactly-once has scope.
State that consumer lag is business delay.
This framing sounds senior because it connects mechanics to failure.

## 76. Decision matrix

Use synchronous RPC when the caller needs an immediate decision.
Use a task queue when one job should go to one worker.
Use SQS when managed simple retries are enough.
Use RabbitMQ when routing-heavy work queues are needed.
Use pub/sub when many subscribers react to the same event.
Use Kafka when replayable event history matters.
Use Kafka when high-throughput fanout matters.
Use Kafka when per-key ordering matters.
Use Kafka plus Debezium when CDC fanout matters.
Use Redis Streams for modest Redis-native stream workloads.
Use NATS for low-latency messaging when durability mode is understood.
Use Kinesis for AWS-managed shard streams.
Do not use Kafka for one simple background job.
Do not use Kafka if the team cannot operate it.
Do not use Kafka when consumers cannot tolerate duplicates.
Do not use Kafka when ordering requirements are unknown.

```text
+-------------------------------+------------------------------+
| Requirement                   | Better fit                   |
+-------------------------------+------------------------------+
| immediate user answer         | synchronous RPC              |
| one background job            | task queue                   |
| simple managed retry          | SQS                          |
| routing-heavy work queue      | RabbitMQ                     |
| replayable event history      | Kafka                        |
| CDC fanout                    | Kafka plus Debezium          |
| low-latency messaging         | NATS                         |
| AWS managed stream            | Kinesis                      |
+-------------------------------+------------------------------+
```

## 77. Retention questions

1. Why is Kafka not just a bigger task queue?
2. What does a task queue guarantee and not guarantee?
3. Why can a worker send an email twice even with one job?
4. What is the difference between an event and a command?
5. Why does pub/sub create hidden coupling?
6. What makes a durable log different from a queue?
7. Why is replay valuable?
8. Why is replay dangerous?
9. What is a Kafka partition?
10. What is an offset?
11. What is ISR?
12. What does ISR shrink imply?
13. What does replication.factor=3 provide?
14. What does min.insync.replicas=2 do?
15. What can go wrong with acks=1?
16. What does acks=all protect against?
17. What does producer idempotence protect?
18. What does producer idempotence not protect?
19. Why does key selection control ordering?
20. Why can product_id be a bad key during launch?
21. Why does adding consumers not fix one hot partition?
22. What is consumer lag?
23. Why is lag age often more important than lag count?
24. What does one-partition lag suggest?
25. What does all-partitions lag suggest?
26. What causes rebalance storms?
27. Why is auto commit dangerous for side-effecting consumers?
28. What is at-least-once delivery?
29. What is effectively-once processing?
30. Why is Kafka exactly-once scoped?
31. What is a DLQ for?
32. Why is a DLQ not a trash can?
33. What is the outbox pattern?
34. What dual-write failure does outbox prevent?
35. What is CDC connector lag?
36. Why can a replication slot threaten PostgreSQL availability?
37. When should Kafka be chosen over SQS?
38. When should RabbitMQ be preferred over Kafka?
39. What metrics diagnose downstream bottleneck versus Kafka bottleneck?
40. Why must schema evolution consider old records?

## 78. Gap fill

1. A task queue is best when one logical job should go to one ______.
2. Kafka preserves order within a ______.
3. Consumer lag equals log end offset minus ______ offset.
4. The partition key controls ordering and ______.
5. A hot partition cannot be fixed by blindly adding ______.
6. At-least-once delivery requires ______ consumers.
7. Kafka exactly-once has ______.
8. The outbox pattern prevents database and broker ______ writes.
9. CDC connector lag means event ______.
10. A DLQ should preserve original topic, partition, offset, key, headers, payload, and ______.

Answers:
1. worker
2. partition
3. committed
4. distribution
5. consumers
6. idempotent
7. scope
8. dual
9. lag
10. error

## 79. Final mental model

Messaging is not a performance trick.
Messaging is a correctness and operations boundary.
Task queues distribute work.
Pub/sub distributes reactions.
Durable logs preserve history.
Kafka is powerful because it combines durable history, high throughput, partitioned ordering, and independent consumer groups.
Kafka is dangerous because the same features create lag, replay risk, ordering traps, schema coupling, and operational complexity.
For MegaShop, Kafka is justified for order-events because many systems need the same business facts.
Replay matters for rebuilding search and analytics.
Per-order ordering matters for lifecycle projections.
High throughput matters during launches.
The system can invest in schemas, DLQs, observability, and idempotent consumers.
For a simple send-email-later job, a task queue may be better.
The principal-level answer is not Kafka everywhere.
The principal-level answer is semantic fit plus operational readiness.

---

# Part 15: Alternative Systems in Depth

## 80. SQS in depth

SQS is a managed task queue.
It is best when one message should be processed by one worker.
It removes broker operations from the application team.
MegaShop can use SQS for email jobs, report generation, and webhook retries.
SQS standard queues provide high throughput and at-least-once delivery.
Standard queues can deliver duplicates.
Standard queues do not guarantee strict ordering.
SQS FIFO queues provide ordering within message groups.
FIFO queues have throughput tradeoffs.
Visibility timeout is central.
A worker receives a message.
SQS hides it for the visibility timeout.
If the worker deletes the message before timeout, the job completes.
If the worker does not delete it, the message becomes visible again.
This is why duplicate processing is normal.
SQS DLQ redrive policy controls when messages move to DLQ.
SQS is not a replayable event log.
It is not intended for many independent consumers replaying history.
If MegaShop needs to rebuild search from order history, SQS is the wrong main abstraction.
If MegaShop needs to send one receipt email later, SQS is excellent.

```text
+----------+      +-----------+      +----------+
| Producer | ---> | SQS Queue | ---> | Worker   |
+----------+      +-----------+      +----------+
                         |
                         v
                    visibility
                    timeout
```

## 81. RabbitMQ in depth

RabbitMQ is a broker with strong routing concepts.
It uses exchanges, queues, and bindings.
A producer publishes to an exchange.
Bindings route messages from exchange to queues.
Consumers read from queues.
This is excellent for routing-heavy workloads.
MegaShop seller notifications might route by region, seller tier, or event type.
RabbitMQ can model that naturally.
RabbitMQ is often a better fit than Kafka for complex work queues.
RabbitMQ is not primarily a long-retention replay log.
Huge backlogs can hurt broker performance.
If MegaShop wants many teams to replay order history for days, Kafka is usually better.
If MegaShop wants flexible routing of support tasks to queues, RabbitMQ can be better.
The choice is not about which tool is more prestigious.
The choice is about semantics.

```text
+----------+      +----------+      +---------+
| Producer | ---> | Exchange | ---> | Queue A |
+----------+      +----------+      +---------+
                       |
                       +------->    +---------+
                                    | Queue B |
                                    +---------+
```

## 82. Redis Streams in depth

Redis Streams provide stream-like data structures inside Redis.
They can support consumer groups.
They can be useful for modest stream workloads.
They are attractive when Redis is already operated well.
They are not a universal Kafka replacement.
Redis memory model, persistence configuration, replication, and retention must be understood.
MegaShop might use Redis Streams for small internal coordination streams.
MegaShop should not casually put its global order event backbone on Redis Streams without a serious durability and operations review.
Redis can be extremely fast.
Fast is not the same as correct for long-retention business history.
The question is not whether Redis can move messages.
The question is whether it satisfies replay, durability, retention, fanout, and operational requirements.

## 83. NATS in depth

NATS is known for low-latency messaging and subject-based communication.
Core NATS is often used for lightweight messaging.
JetStream adds persistence capabilities.
NATS can be excellent for request-reply, control-plane communication, and low-latency eventing.
It is not automatically the right choice for long historical event backbones.
MegaShop could use NATS for internal control messages.
MegaShop would still likely use Kafka for durable order event history if replay and large fanout are central.
NATS design requires careful understanding of durability mode.
A low-latency bus and a durable audit stream are different products even if both move messages.

## 84. Kinesis in depth

Kinesis is an AWS-managed stream service.
It is shard-based.
A shard has throughput limits.
Producers write records to shards.
Consumers read from shards.
Partition key determines shard placement.
This resembles Kafka partitioning in important ways.
Hot keys can create hot shards.
MegaShop on AWS might choose Kinesis to reduce broker operations.
Kafka might be chosen for ecosystem, portability, or existing platform investment.
Kinesis simplifies some operations and constrains others.
Shard planning matters.
Retention settings matter.
Consumer throughput mode matters.
The same semantic questions remain.
What is the key.
What is the ordering requirement.
What lag is acceptable.
What replay is required.
What happens when one key is hot.

---

# Part 16: Kafka Design Reviews

## 85. Topic design review template

Every Kafka topic should pass a design review before production.
The review starts with business meaning.
What facts does the topic contain.
Who owns the topic.
Which team owns producer code.
Which teams consume it.
Which consumers are critical.
What is the schema format.
What compatibility policy applies.
What is the partition key.
What ordering does that key preserve.
What hot-key scenarios exist.
What is the partition count.
What is the retention period.
What is the cleanup policy.
What is the replication factor.
What is the min ISR setting.
What ACLs apply.
What PII exists.
What dashboards exist.
What alerts exist.
What DLQ exists.
What replay process exists.
What backfill process exists.
If those answers do not exist, the topic is not ready.

```text
+----------------------+--------------------------------+
| Review item          | Required answer                |
+----------------------+--------------------------------+
| Owner                | team and escalation path       |
| Event meaning        | business fact or command       |
| Schema policy        | compatibility and versioning   |
| Partition key        | ordering and hot-key analysis  |
| Retention            | recovery objective             |
| Consumers            | criticality and SLO            |
| DLQ                  | ownership and replay           |
| Security             | ACLs, PII, quotas              |
+----------------------+--------------------------------+
```

## 86. Producer design review template

A producer design review verifies that the producer can safely write events.
It asks whether direct publish or outbox is used.
It asks what happens if Kafka publish fails.
It asks what happens if acknowledgement is lost.
It asks what key is used.
It asks what schema version is written.
It asks what headers are included.
It asks whether event_id is stable.
It asks whether retries are bounded by delivery timeout.
It asks whether producer errors are observable.
It asks whether the service can return success if event publication fails.
MegaShop checkout should not lose OrderPlaced.
That pushes design toward outbox.
MegaShop telemetry can tolerate some loss.
That can justify simpler direct publish.
Producer design follows business consequence.

## 87. Consumer design review template

A consumer design review verifies safe processing.
It asks what side effect occurs.
It asks whether duplicate processing is safe.
It asks what idempotency key exists.
It asks when offsets are committed.
It asks whether auto commit is disabled.
It asks what errors are retryable.
It asks what errors go to DLQ.
It asks whether DLQ records preserve context.
It asks whether replay is safe.
It asks how lag is monitored.
It asks what downstream dependency can bottleneck.
It asks how backpressure works.
It asks how deploys avoid rebalance storms.
A consumer that cannot answer these questions is not production-ready.

## 88. Event taxonomy

A mature event platform names events consistently.
Events are facts in past tense.
OrderPlaced is good.
PaymentCaptured is good.
InventoryReserved is good.
SendEmail is a command, not an event.
ReserveInventory is a command, not an event.
OrderUpdated is often too vague.
OrderStatusChanged may still be vague unless status semantics are clear.
Event names should encode business meaning.
A fact should not require consumers to diff random fields to understand meaning.
MegaShop prefers domain events over generic row-change events for business workflows.
CDC row changes are useful.
They are not automatically meaningful business events.
A row update says data changed.
A domain event says what happened.
Consumers need meaning, not just mutation.

## 89. Event envelope standard

An event envelope provides consistent metadata around payload.
MegaShop event envelope includes event_id.
It includes event_type.
It includes schema_version.
It includes aggregate_type.
It includes aggregate_id.
It includes occurred_at.
It includes published_at.
It includes producer.
It includes correlation_id.
It includes causation_id.
It includes payload.
This consistency makes observability and tooling easier.
DLQ tools can rely on event_id.
Tracing can rely on correlation_id.
Partitioning can rely on aggregate_id.
Schema handlers can rely on schema_version.
Without envelope consistency, every consumer invents its own archaeology kit.

```text
+----------------+------------------------------+
| Envelope field | Main use                     |
+----------------+------------------------------+
| event_id       | dedupe and audit             |
| event_type     | route and handler selection  |
| schema_version | compatibility                |
| aggregate_id   | ordering and partitioning    |
| correlation_id | tracing                      |
| causation_id   | workflow explanation         |
+----------------+------------------------------+
```

---

# Part 17: SRE Runbooks

## 90. Runbook: all consumer partitions lagging

Confirm producer rate and consumer progress rate.
Check whether lag is growing or shrinking.
Check downstream dependency p99.
Check consumer error rate.
Check consumer CPU and memory.
Check broker fetch latency.
Check recent deployments.
Check DLQ and retry rate.
If downstream is bottleneck, do not blindly add consumers.
If consumer CPU is bottleneck and downstream is healthy, scale consumers up to partition count.
If broker is bottleneck, inspect broker network, disk, and request latency.
Communicate freshness impact by consumer group.

## 91. Runbook: one partition lagging

Identify the lagging partition.
Identify its current consumer host.
Inspect logs for repeated offset.
Check key distribution for that partition.
Look for hot key.
Look for poison message.
Compare processing latency on that host.
Do not scale whole group blindly.
If poison record, quarantine with audit.
If hot key, consider producer key rollback or corrected topic.
If slow host, restart or drain carefully.

## 92. Runbook: ISR shrink

Identify affected topics and partitions.
Determine topic criticality.
Check broker disk usage.
Check broker network errors.
Check replication fetcher lag.
Check recent broker restart or maintenance.
Check rack or zone issues.
If order topic is affected, raise severity.
Protect broker disk.
Do not ignore sustained under-replication.
Confirm ISR recovery after mitigation.

## 93. Runbook: DLQ spike

Identify consumer group producing DLQ records.
Group DLQ by error_class.
Group DLQ by schema_version.
Group DLQ by event_type.
Check recent producer deploy.
Check recent consumer deploy.
Sample payloads safely.
Determine retryable versus permanent errors.
Pause replay until cause understood.
Fix code or data.
Replay intentionally with rate limits.

## 94. Runbook: connector lag

Check connector task status.
Check source database health.
Check replication slot retained bytes.
Check connector logs for schema errors.
Check Kafka produce errors.
Check downstream topic availability.
Protect source database first.
Restart connector only if failure mode is safe.
Plan re-snapshot carefully if slot is lost.
Communicate projection freshness impact.

## 95. Runbook: retention at risk

Calculate lag age.
Compare lag age to retention remaining.
Identify affected consumer groups.
Prioritize critical consumers.
Pause non-critical backfills.
Increase retention temporarily if safe.
Scale consumers only if downstream can handle it.
Consider alternate backfill from source of truth.
Communicate risk of unreplayable data.
After incident, adjust retention policy.

## 96. Runbook: producer errors spike

Check broker availability.
Check metadata refresh errors.
Check timeout errors.
Check authorization errors.
Check record-too-large errors.
Check schema registry errors.
Check acks and ISR state.
Check whether errors affect critical topics.
If outbox exists, verify backlog.
If direct publish path, verify caller behavior.
Do not drop errors silently.

---

# Part 18: Common Misconceptions

## 97. Misconception: Kafka will make my system eventually consistent automatically

Misconception: Kafka will make my system eventually consistent automatically.
Correction: Kafka transports records. It does not design consistency. The application must define authoritative state, projection freshness, reconciliation, and user-visible states.
MegaShop design rule:
Match tool choice to business semantics and failure consequence.

## 98. Misconception: A bigger consumer group always reduces lag

Misconception: A bigger consumer group always reduces lag.
Correction: A consumer group cannot use more active consumers than partitions for that topic. Hot partitions remain single-lane inside the group.
MegaShop design rule:
Check partition count, key distribution, and per-partition lag before scaling.

## 99. Misconception: DLQ means the problem is handled

Misconception: DLQ means the problem is handled.
Correction: DLQ means the main consumer stopped failing on that record. The business problem remains until the record is repaired, replayed, ignored with audit, or archived by policy.
MegaShop design rule:
Every DLQ must have owner, dashboard, replay procedure, and retention policy.

## 100. Misconception: Schema registry means schema evolution is solved

Misconception: Schema registry means schema evolution is solved.
Correction: Schema registry enforces structural compatibility rules. It cannot fully understand business semantics. Changing field meaning can still break consumers.
MegaShop design rule:
Schema changes require compatibility tests and consumer-aware rollout.

## 101. Misconception: Kafka retention is backup

Misconception: Kafka retention is backup.
Correction: Retention is replay storage for a window. It is not a complete backup strategy, not a legal archive by default, and not a substitute for source-of-truth databases.
MegaShop design rule:
Match tool choice to business semantics and failure consequence.

## 102. Misconception: Outbox guarantees exactly-once consumers

Misconception: Outbox guarantees exactly-once consumers.
Correction: Outbox prevents missing event publication from local database commits. Consumers can still receive duplicates and must be idempotent.
MegaShop design rule:
Outbox plus idempotent consumers plus reconciliation forms the safer pattern.

## 103. Misconception: Compaction means old data is immediately gone

Misconception: Compaction means old data is immediately gone.
Correction: Compaction is eventual cleanup by key. It is not immediate deletion and should not be used as a privacy guarantee without understanding its behavior.
MegaShop design rule:
Match tool choice to business semantics and failure consequence.

## 104. Misconception: Exactly-once means payment exactly once

Misconception: Exactly-once means payment exactly once.
Correction: Kafka exactly-once is scoped to Kafka operations. Payment providers, email APIs, and warehouses need idempotency and reconciliation.
MegaShop design rule:
Name the exact boundary of every guarantee before trusting it.

## 105. Misconception: Async means user impact is gone

Misconception: Async means user impact is gone.
Correction: Async moves user impact from request latency to freshness, notification delay, stale projections, and reconciliation risk.
MegaShop design rule:
Match tool choice to business semantics and failure consequence.

## 106. Misconception: Kafka is always the senior architecture answer

Misconception: Kafka is always the senior architecture answer.
Correction: Kafka is senior when its semantics match the problem. Using Kafka for a tiny background job may be needless operational tax.
MegaShop design rule:
Match tool choice to business semantics and failure consequence.

---

# Part 19: Principal SRE Checklist

## 107. Checklist: Producer readiness

1. Event has stable event_id.
2. Event has schema_version.
3. Event has correlation_id.
4. Partition key is documented.
5. Hot-key scenarios are tested.
6. Producer errors are observable.
7. Direct publish versus outbox decision is documented.
8. Durability settings match business consequence.
9. Schema compatibility gate exists.
10. PII classification is documented.

## 108. Checklist: Consumer readiness

1. Consumer has explicit idempotency design.
2. Offset commit timing is documented.
3. Auto commit is disabled for side effects.
4. Retryable and non-retryable errors are classified.
5. DLQ contains full original context.
6. Replay policy is documented.
7. Backpressure behavior is implemented.
8. Downstream dependency SLO is known.
9. Consumer lag SLO is defined.
10. Deploy strategy avoids rebalance storms.

## 109. Checklist: Topic readiness

1. Owner team is documented.
2. Retention policy matches recovery objective.
3. Replication factor matches criticality.
4. min.insync.replicas matches durability goal.
5. Partition count matches throughput plan.
6. Cleanup policy is correct.
7. ACLs are least privilege.
8. Quotas are considered.
9. Dashboards exist.
10. Alerts are tied to business impact.

## 110. Checklist: Incident readiness

1. Runbooks exist for lag, DLQ, ISR, connector lag, and hot partitions.
2. Support communication templates distinguish authority from projection freshness.
3. Backfill procedures are rate limited.
4. Reconciliation jobs exist for money and fulfillment.
5. On-call knows source of truth for each workflow.
6. Dashboards show lag age, not only lag count.
7. Critical consumers have protected capacity.
8. Known dangerous actions are documented.
9. Post-incident review includes prevention controls.
10. Recovery criteria include business freshness.

## 111. Scenario questions

1. Search projection stale: Checkout is green, OrdersDB has records, search does not show new orders. Explain authority, probable lag source, and safe mitigation.
2. Payment ambiguity: Payment provider times out after Kafka event is consumed. Explain why retry without idempotency is unsafe.
3. Inventory hot key: Inventory projector has one partition with 95 percent of lag. Explain likely causes and first diagnostic commands.
4. Schema drift: Producer adds a required field and old consumers fail. Explain safe rollout.
5. Retention miss: Analytics consumer was down longer than retention. Explain recovery options.
6. DLQ replay: A bug fix is deployed for DLQ records. Explain safe replay process.
7. Connector WAL growth: Debezium connector is down and PostgreSQL WAL grows. Explain priority and risk.
8. Rebalance storm: Lag spikes during every deploy. Explain cause and mitigation.
9. Producer acks tradeoff: Compare acks=1 and acks=all for order-events.
10. Kafka versus SQS: Choose a tool for receipt email and for order history replay.

---

# Part 20: Scenario Answer Key

## 112. Answer key: Search projection stale

OrdersDB is authoritative for order existence.
Search is a projection and may lag.
Check outbox backlog first.
Check connector lag next.
Check Kafka consumer lag for search-indexer.
Check OpenSearch write rejections and p99.
Do not tell users orders are lost if OrdersDB is correct.
Communicate search freshness delay.
Protect checkout path.
Replay or backfill search at controlled rate after bottleneck is fixed.

## 113. Answer key: Payment ambiguity

A timeout does not prove payment failed.
The provider may have captured payment and lost the response.
Retrying without stable idempotency can double charge.
Use provider idempotency key.
Query provider by transaction reference.
Move workflow to PAYMENT_UNKNOWN or RECONCILING state.
Reconcile before compensating.
Ledger must have unique event or operation ID.
Customer communication must avoid false finality.

## 114. Answer key: Inventory hot key

One partition with most lag suggests hot key or poison message.
If product_id is the key during launch, hot partition is likely.
Run consumer group describe and inspect per-partition lag.
Inspect logs for repeated offset.
Inspect key distribution if tooling exists.
Stop autoscaling churn.
Do not add consumers blindly.
Rollback key or cut over to corrected topic if needed.
Use order_id or bucketed product key depending ordering requirement.

## 115. Answer key: Schema drift

Treat event schema as a contract.
Add optional fields first.
Deploy consumers that understand both old and new shape.
Start producing new field after consumers are ready.
Wait beyond retention and migration window before removing old fields.
Use schema compatibility checks.
Use consumer contract tests.
Do not reuse protobuf field numbers.
Do not change meaning under the same field name.

## 116. Answer key: Retention miss

Kafka cannot replay records already deleted by retention.
Find source of truth for missing interval.
Backfill from OrdersDB, warehouse, or data lake if available.
Mark analytics gap if no source exists.
Increase retention based on recovery objective.
Alert on lag age approaching retention.
Test recovery before relying on it.
Do not pretend Kafka is backup unless designed as such.

## 117. Answer key: DLQ replay

Group DLQ by error class and schema version.
Fix code or data before replay.
Replay with rate limits.
Replay into the same consumer only if idempotency is safe.
Preserve original metadata.
Track replay success and failure.
Do not bulk replay into a broken downstream dependency.
Archive or delete DLQ records only after policy and audit.

## 118. Answer key: Connector WAL growth

Protect the source database first.
Check replication slot active status.
Check retained WAL bytes.
Check connector task errors.
Increase disk if immediate risk exists.
Restart connector only after understanding failure.
Dropping slot may require re-snapshot.
Re-snapshot can overload the primary.
Communicate projection lag separately from order authority.

## 119. Answer key: Rebalance storm

Check rebalance rate.
Check deploy timing.
Check autoscaler events.
Check max.poll.interval.ms violations.
Deploy in smaller waves.
Use static membership when appropriate.
Use cooperative rebalancing.
Reduce processing time per poll.
Do not autoscale on lag alone.

## 120. Answer key: Producer acks tradeoff

acks=1 waits only for leader append.
It can acknowledge records that are lost if leader fails before replication.
acks=all waits for ISR durability condition.
With replication.factor=3 and min.insync.replicas=2, at least two replicas must be safe.
acks=all can reduce silent loss.
acks=all can increase latency and write failures during replica problems.
For order-events, visible failure is usually better than silent loss.
For low-value telemetry, weaker durability may be acceptable.

## 121. Answer key: Kafka versus SQS

Receipt email is one job for one worker.
SQS is often a good fit.
Order history replay requires durable log and many independent consumers.
Kafka is a better fit.
Tool choice follows semantics.
Do not use Kafka just to send one background email.
Do not use SQS as the main replay backbone for many consumers.

---

# Part 21: Dense Glossary

1. acknowledgement: A signal that a broker or worker considers an operation accepted or complete.
2. aggregate: A domain entity whose events often require ordering, such as an order or account.
3. backpressure: A mechanism that slows or stops upstream work when downstream capacity is saturated.
4. broker: A server that stores partitions and handles client requests.
5. compaction: A Kafka cleanup policy that eventually keeps the latest value per key.
6. consumer group: A named set of consumers sharing partition ownership and offsets.
7. correlation_id: An identifier that ties events and logs to one workflow or request.
8. dead-letter queue: A queue or topic for records that could not be processed after bounded attempts.
9. delivery guarantee: A statement about loss and duplication behavior across broker and application.
10. durable log: A retained ordered history that consumers can replay.
11. event: A fact that already happened.
12. idempotency: Property where repeating an operation has the same final business effect.
13. ISR: In-sync replicas that count toward Kafka durability conditions.
14. lag: Distance between newest record and a consumer group's committed progress.
15. leader: The broker that handles reads and writes for a partition.
16. offset: A position within one Kafka partition.
17. outbox: A database table storing events committed atomically with business state.
18. partition: An ordered shard of a Kafka topic.
19. partition key: The value used to select partition and define ordering scope.
20. producer: A client that writes records to Kafka.
21. projection: A derived view built from authoritative data or events.
22. pub/sub: A messaging model where one publication fans out to many subscribers.
23. rebalance: A consumer group operation that changes partition ownership.
24. replication factor: Number of copies Kafka maintains for a partition.
25. retention: Policy controlling how long records are kept.
26. schema evolution: Safe change process for event structure and meaning.
27. task queue: A queue model where one job is assigned to one worker.
28. tombstone: A null-valued record used in compacted topics to delete a key eventually.
29. visibility timeout: Task queue period during which a received job is hidden from other workers.

---

# Part 22: Final Drill Set

1. Explain why Kafka ordering is scoped to partitions and how MegaShop uses order_id to preserve order lifecycle.
2. Explain how acks=all and min.insync.replicas=2 change producer failure behavior for order-events.
3. Explain why an email consumer can send duplicates after a crash and how a sent marker prevents it.
4. Explain how one hot product_id can create a hot partition during a launch.
5. Explain why consumer lag must be interpreted with downstream p99 and partition distribution.
6. Explain why outbox prevents order row and OrderPlaced event divergence.
7. Explain why retention is a recovery objective and not a default checkbox.
8. Explain why DLQ records need original topic, partition, offset, key, headers, payload, and error.
9. Explain why Kafka exactly-once does not make Stripe, email, or warehouse APIs exactly once.
10. Explain when SQS or RabbitMQ is a better fit than Kafka.
11. Explain why Kafka ordering is scoped to partitions and how MegaShop uses order_id to preserve order lifecycle.
12. Explain how acks=all and min.insync.replicas=2 change producer failure behavior for order-events.
13. Explain why an email consumer can send duplicates after a crash and how a sent marker prevents it.
14. Explain how one hot product_id can create a hot partition during a launch.
15. Explain why consumer lag must be interpreted with downstream p99 and partition distribution.
16. Explain why outbox prevents order row and OrderPlaced event divergence.
17. Explain why retention is a recovery objective and not a default checkbox.
18. Explain why DLQ records need original topic, partition, offset, key, headers, payload, and error.
19. Explain why Kafka exactly-once does not make Stripe, email, or warehouse APIs exactly once.
20. Explain when SQS or RabbitMQ is a better fit than Kafka.
21. Explain why Kafka ordering is scoped to partitions and how MegaShop uses order_id to preserve order lifecycle.
22. Explain how acks=all and min.insync.replicas=2 change producer failure behavior for order-events.
23. Explain why an email consumer can send duplicates after a crash and how a sent marker prevents it.
24. Explain how one hot product_id can create a hot partition during a launch.
25. Explain why consumer lag must be interpreted with downstream p99 and partition distribution.
26. Explain why outbox prevents order row and OrderPlaced event divergence.
27. Explain why retention is a recovery objective and not a default checkbox.
28. Explain why DLQ records need original topic, partition, offset, key, headers, payload, and error.
29. Explain why Kafka exactly-once does not make Stripe, email, or warehouse APIs exactly once.
30. Explain when SQS or RabbitMQ is a better fit than Kafka.
31. Explain why Kafka ordering is scoped to partitions and how MegaShop uses order_id to preserve order lifecycle.
32. Explain how acks=all and min.insync.replicas=2 change producer failure behavior for order-events.
33. Explain why an email consumer can send duplicates after a crash and how a sent marker prevents it.
34. Explain how one hot product_id can create a hot partition during a launch.
35. Explain why consumer lag must be interpreted with downstream p99 and partition distribution.
36. Explain why outbox prevents order row and OrderPlaced event divergence.
37. Explain why retention is a recovery objective and not a default checkbox.
38. Explain why DLQ records need original topic, partition, offset, key, headers, payload, and error.
39. Explain why Kafka exactly-once does not make Stripe, email, or warehouse APIs exactly once.
40. Explain when SQS or RabbitMQ is a better fit than Kafka.
41. Explain why Kafka ordering is scoped to partitions and how MegaShop uses order_id to preserve order lifecycle.
42. Explain how acks=all and min.insync.replicas=2 change producer failure behavior for order-events.
43. Explain why an email consumer can send duplicates after a crash and how a sent marker prevents it.
44. Explain how one hot product_id can create a hot partition during a launch.
45. Explain why consumer lag must be interpreted with downstream p99 and partition distribution.
46. Explain why outbox prevents order row and OrderPlaced event divergence.
47. Explain why retention is a recovery objective and not a default checkbox.
48. Explain why DLQ records need original topic, partition, offset, key, headers, payload, and error.
49. Explain why Kafka exactly-once does not make Stripe, email, or warehouse APIs exactly once.
50. Explain when SQS or RabbitMQ is a better fit than Kafka.
51. Explain why Kafka ordering is scoped to partitions and how MegaShop uses order_id to preserve order lifecycle.
52. Explain how acks=all and min.insync.replicas=2 change producer failure behavior for order-events.
53. Explain why an email consumer can send duplicates after a crash and how a sent marker prevents it.
54. Explain how one hot product_id can create a hot partition during a launch.
55. Explain why consumer lag must be interpreted with downstream p99 and partition distribution.
56. Explain why outbox prevents order row and OrderPlaced event divergence.
57. Explain why retention is a recovery objective and not a default checkbox.
58. Explain why DLQ records need original topic, partition, offset, key, headers, payload, and error.
59. Explain why Kafka exactly-once does not make Stripe, email, or warehouse APIs exactly once.
60. Explain when SQS or RabbitMQ is a better fit than Kafka.
61. Explain why Kafka ordering is scoped to partitions and how MegaShop uses order_id to preserve order lifecycle.
62. Explain how acks=all and min.insync.replicas=2 change producer failure behavior for order-events.
63. Explain why an email consumer can send duplicates after a crash and how a sent marker prevents it.
64. Explain how one hot product_id can create a hot partition during a launch.
65. Explain why consumer lag must be interpreted with downstream p99 and partition distribution.
66. Explain why outbox prevents order row and OrderPlaced event divergence.
67. Explain why retention is a recovery objective and not a default checkbox.
68. Explain why DLQ records need original topic, partition, offset, key, headers, payload, and error.
69. Explain why Kafka exactly-once does not make Stripe, email, or warehouse APIs exactly once.
70. Explain when SQS or RabbitMQ is a better fit than Kafka.
71. Explain why Kafka ordering is scoped to partitions and how MegaShop uses order_id to preserve order lifecycle.
72. Explain how acks=all and min.insync.replicas=2 change producer failure behavior for order-events.
73. Explain why an email consumer can send duplicates after a crash and how a sent marker prevents it.
74. Explain how one hot product_id can create a hot partition during a launch.
75. Explain why consumer lag must be interpreted with downstream p99 and partition distribution.
76. Explain why outbox prevents order row and OrderPlaced event divergence.
77. Explain why retention is a recovery objective and not a default checkbox.
78. Explain why DLQ records need original topic, partition, offset, key, headers, payload, and error.
79. Explain why Kafka exactly-once does not make Stripe, email, or warehouse APIs exactly once.
80. Explain when SQS or RabbitMQ is a better fit than Kafka.

---

# Part 23: Final Summary

Messaging separates critical work from delayed reactions.
Task queues are for one job and one worker.
Pub/sub is for one event and many subscribers.
Durable logs are for retained replayable history.
Kafka is a distributed, replicated, partitioned commit log.
Kafka's partition is both ordering unit and parallelism unit.
Partition key design is central to correctness and capacity.
Producer durability settings decide when a write is honestly successful.
acks=all plus min.insync.replicas can trade availability for safer durability.
Producer idempotence protects against duplicate appends from producer retries.
Consumer idempotence protects business side effects from redelivery.
Offsets are progress markers, not proof of business correctness.
At-least-once delivery is common because duplicates are easier to repair than missing work.
Exactly-once must always state its scope.
Replay is powerful only when consumers are replay-safe.
Retention buys recovery time with storage cost.
Compaction keeps latest state per key and is not audit history.
Schema evolution is a contract between teams.
DLQs require ownership and replay tooling.
Outbox solves database plus broker dual-write divergence.
CDC connector lag can become source database risk.
Consumer lag is business delay.
Lag age often matters more than lag count.
Hot partitions require key analysis, not blind scaling.
Rebalance storms turn deploys into consumption outages.
Kafka should be chosen for replay, fanout, throughput, and per-key ordering.
Kafka should not be chosen for prestige.
MegaShop uses Kafka for order history because many systems consume and replay it.
MegaShop uses task queues for simple jobs where replay history is unnecessary.
The best architecture names the source of truth for every workflow.
The best SRE response distinguishes authority failure from projection freshness failure.

---

# Part 24: Pre-Production Review Questions
1. Who owns the topic.
2. Who owns the producer.
3. Who owns each consumer group.
4. What business fact does the event represent.
5. Is the message an event, command, or job.
6. What system is authoritative for the state.
7. What fields are required for consumers.
8. What fields are sensitive or regulated.
9. What schema format is used.
10. What compatibility mode is enforced.
11. What is the partition key.
12. What ordering does that key preserve.
13. What ordering does that key not preserve.
14. What hot-key scenario has been tested.
15. What is the expected peak produce rate.
16. What is the expected peak consume rate.
17. What is the average message size.
18. What is the maximum message size.
19. What compression is used.
20. What retention is required.
21. What retention is affordable.
22. What cleanup policy is used.
23. What replication factor is used.
24. What min ISR is used.
25. What producer acks setting is required.
26. What happens if Kafka write fails.
27. What happens if acknowledgement is lost.
28. Is outbox required.
29. Is CDC required.
30. What connector owns CDC.
31. What happens if connector stops.
32. What happens if WAL retained bytes grow.
33. What consumer offset policy is used.
34. Is auto commit disabled for side effects.
35. When are offsets committed.
36. What side effects can happen twice.
37. What idempotency key protects each side effect.
38. What unique constraint protects each database write.
39. What provider idempotency key protects external calls.
40. What retry policy is used.
41. Which errors are retryable.
42. Which errors go directly to DLQ.
43. What DLQ topic exists.
44. Who owns DLQ triage.
45. What replay tool exists.
46. What rate limit protects replay.
47. What dashboards exist.
48. What alerts exist.
49. What lag SLO exists.
50. What lag age SLO exists.
51. What downstream dependency SLO exists.
52. What backpressure mechanism exists.
53. What happens during deploy.
54. What rebalance rate is acceptable.
55. What autoscaling signal is used.
56. What prevents autoscaling churn.
57. What security ACLs exist.
58. What quotas exist.
59. What PII classification exists.
60. What audit requirement exists.
61. What disaster recovery path exists.
62. What backfill source exists if retention expires.
63. What support message is used during projection lag.
64. What incident runbook exists.
65. What post-incident prevention control is expected.

---

# Part 25: Anti-Patterns
1. Anti-pattern: Kafka for every async job. Correction: Use a task queue when one worker should process one simple job.
2. Anti-pattern: No event owner. Correction: Every public event needs a team responsible for schema and semantics.
3. Anti-pattern: Random partition key. Correction: Random keys destroy per-entity ordering.
4. Anti-pattern: Product key for flash-sale orders. Correction: A hot product can melt one partition.
5. Anti-pattern: Auto commit with side effects. Correction: Offsets can move before business work is safe.
6. Anti-pattern: DLQ without replay. Correction: Failure is moved, not solved.
7. Anti-pattern: Retention shorter than recovery. Correction: Consumers can fall behind beyond replay ability.
8. Anti-pattern: Schema change without consumers. Correction: Producer convenience becomes consumer outage.
9. Anti-pattern: Lag-only autoscaling. Correction: Autoscaling can create rebalance storms.
10. Anti-pattern: Ignoring downstream capacity. Correction: Kafka can buffer but not make OpenSearch faster.
11. Anti-pattern: Silent offset skip. Correction: Invisible data loss is worse than visible failure.
12. Anti-pattern: Trusting projection for authority. Correction: Search and analytics are not order truth.
13. Anti-pattern: No idempotency key. Correction: Retries become duplicate side effects.
14. Anti-pattern: No correlation ID. Correction: Incident tracing becomes guesswork.
15. Anti-pattern: No lag age alert. Correction: Raw lag count hides business freshness.
16. Anti-pattern: No topic classification. Correction: Critical and low-value events get same weak policy.
17. Anti-pattern: No outbox for authoritative events. Correction: Database truth and event stream can diverge.
18. Anti-pattern: No replay mode. Correction: Backfills trigger live side effects.
19. Anti-pattern: No quota. Correction: One team can starve the shared cluster.
20. Anti-pattern: No schema compatibility. Correction: A producer deploy can break the company.

---

# Part 26: Closing Principle

Kafka is not the center of the architecture.
Business truth is the center of the architecture.
Kafka moves facts from truth-owning systems to reacting systems.
A topic is not authoritative because it is popular.
A consumer is not correct because it is caught up.
A projection is not true because it is fast.
A retry is not safe because it eventually succeeds.
A DLQ is not recovery because it stopped the crash.
A partition key is not a detail because it decides ordering and load.
An offset is not business success because it is only read progress.
A schema is not just serialization because it is a contract.
A broker is not a magic buffer because downstream capacity still exists.
A replay is not safe unless side effects are controlled.
The best Kafka designs are boring during incidents.
They are boring because authority is clear.
They are boring because duplicates are expected.
They are boring because lag is measured.
They are boring because DLQs are owned.
They are boring because schema changes are governed.
They are boring because runbooks exist.
That kind of boring is the highest compliment in production.
