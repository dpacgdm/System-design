# Week 6, Topic 1: Message Queues and Kafka

Last verified: 2026-05-16

---

## 1. Learning Objectives

```text
After this topic, you will be able to:

1. Explain why messaging systems exist using critical-path and side-effect boundaries.
2. Distinguish task queues, publish/subscribe, and durable logs by exact semantics.
3. Explain Kafka as a distributed, replicated, partitioned append-only commit log.
4. Trace a Kafka record from Python producer code through serializer, partitioner,
   accumulator, network send, broker request handling, leader append, follower
   replication, ISR acknowledgement, segment file, and consumer fetch.
5. Explain topics, partitions, offsets, leaders, followers, ISR, replicas, brokers,
   consumer groups, group coordinators, offset commits, retention, compaction,
   transactions, and Schema Registry without hand-waving.
6. Choose partition keys using ordering, load distribution, hot-key risk, replay,
   downstream locality, and future partition expansion tradeoffs.
7. Explain producer correctness knobs: acks, retries, delivery.timeout.ms,
   request.timeout.ms, enable.idempotence, max.in.flight, linger.ms, batch.size,
   compression.type, transactional.id, and min.insync.replicas.
8. Explain consumer correctness knobs: enable.auto.commit, auto.offset.reset,
   max.poll.records, max.poll.interval.ms, session.timeout.ms, heartbeat.interval.ms,
   partition.assignment.strategy, isolation.level, pause/resume, and manual commits.
9. Diagnose consumer lag by partition, lag age, offset movement, consumer throughput,
   downstream p99, rebalance rate, DLQ rate, broker health, and connector lag.
10. Design idempotent consumers for search, ledgers, payments, email, webhooks,
    warehouse requests, cache invalidation, and analytics.
11. Explain at-most-once, at-least-once, effectively-once, and Kafka exactly-once
    with exact failure timelines and scope boundaries.
12. Design retry topics, DLQs, quarantine flows, replay tools, outbox tables,
    CDC connectors, and reconciliation jobs that are safe during real incidents.
13. Evaluate Kafka against SQS, RabbitMQ, Redis Streams, NATS, Kinesis, and RPC
    by semantics instead of popularity.
14. Defend a Kafka architecture in a principal-level system design interview.
15. Operate Kafka-backed systems safely during P1 incidents without deleting data,
    skipping offsets blindly, melting downstream systems, or inventing false certainty.
```

---

## 2. The Running System: MegaShop

MegaShop is the running architecture for this chapter.
MegaShop is a Fortune 500 style e-commerce platform.
MegaShop is a teaching model, not a claim about any specific company's private internals.
MegaShop sells physical goods globally.
MegaShop runs flash sales.
MegaShop has marketplace sellers.
MegaShop has fraud scoring.
MegaShop has warehouses.
MegaShop has payment providers.
MegaShop has customer email and push notification systems.
MegaShop has search indexing.
MegaShop has analytics pipelines.
MegaShop has data lake ingestion.
MegaShop has operational dashboards and on-call rotations.
MegaShop's most important workflow is checkout.
Checkout is not a toy API call.
Checkout touches money.
Checkout touches inventory.
Checkout touches customer trust.
Checkout touches fulfillment.
Checkout touches legal records.
Checkout touches downstream projections.
The order database is authoritative for order existence.
The payment ledger or provider is authoritative for payment status.
The inventory service is authoritative for inventory reservation.
Search is a projection.
Analytics is a projection.
Email is a notification side effect.
Warehouse request state is a downstream workflow.
Fraud can be blocking or advisory depending policy.
Kafka is not the source of truth for all of these.
Kafka is a durable propagation layer for business facts and commands.
The difference between authority and propagation is the first serious lesson.

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

This fully synchronous design is easy to draw.
It is also a trap.
If email slows down, checkout slows down.
If search indexing fails, checkout fails.
If analytics is overloaded, users cannot buy goods.
The system has confused the critical path with side effects.
A better design separates immediate correctness from delayed reactions.

```text
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
```

Checkout waits only for work that must be correct now.
Search can lag.
Email can retry.
Analytics can catch up.
Warehouse can consume the order event after commit.
The user response can be honest if it says the order was placed and confirmation is pending.
The user response is dishonest if it implies all projections and notifications are already complete.
Messaging lets systems delay work.
Messaging does not let systems lie.

---

## 3. Critical Path vs Side-Effect Path

A critical path contains work that must finish before returning a correct response.
A side-effect path contains work that can finish later without making the response false.
MegaShop checkout critical path usually includes cart validation.
It includes price verification against the pricing authority.
It includes inventory reservation when overselling is unacceptable.
It includes payment authorization when business policy requires it.
It includes writing the authoritative order record.
It includes writing an idempotency record for the client request.
It includes writing an outbox event or equivalent durable publication intent.
MegaShop side-effect path usually includes receipt email.
It includes search indexing.
It includes recommendations refresh.
It includes analytics ingestion.
It includes customer support timeline update.
It includes warehouse notification if warehouse can tolerate short delay.
It includes fraud enrichment when fraud is advisory.
The split is a correctness decision.
The split is not a technology preference.
The split can differ per product.
A high-risk order may require synchronous fraud decision.
A low-risk order may allow asynchronous fraud enrichment.
A digital download may require license generation before response.
A physical product may allow warehouse notification after response.
The system must define what success means.

```text
+--------------------------+--------------------------------+
| Must usually be immediate| Can usually be delayed         |
+--------------------------+--------------------------------+
| idempotency check        | receipt email                  |
| price verification       | analytics event ingestion      |
| payment authorization    | search projection update       |
| inventory reservation    | recommendation refresh         |
| authoritative order write| customer timeline projection   |
| outbox insert            | non-blocking fraud enrichment  |
+--------------------------+--------------------------------+
```

Principal engineer rule:
If returning success without the action would be a lie, the action belongs in the critical path or the response must expose pending state.
If returning success while the action continues is honest, the action can move behind messaging.
Async is not a correctness eraser.
Async is a timing decision.

---

## 4. What Messaging Decouples

Messaging decouples time.
The producer can finish before the consumer starts.
Messaging decouples failure.
A consumer outage does not need to fail the producer.
Messaging decouples ownership.
A producer can publish a fact and downstream teams can own reactions.
Messaging decouples load.
A broker can absorb bursts while consumers drain at sustainable rates.
Every decoupling creates an obligation.
Time decoupling creates lag.
Failure decoupling creates delayed failure visibility.
Ownership decoupling creates schema governance.
Load decoupling creates backlog and retention risk.
MegaShop gets value because checkout no longer waits for analytics.
MegaShop gets risk because analytics can silently lag for hours.
MegaShop gets value because search can rebuild from events.
MegaShop gets risk because replay can resend emails unless consumers are safe.
MegaShop gets value because order events can fan out to many teams.
MegaShop gets risk because one producer schema change can break many consumers.
A broker is not a free lunch.
It is a boundary where hidden failure can accumulate.

```text
+----------------+----------------------+-----------------------------+
| Decoupling     | Benefit              | New risk                    |
+----------------+----------------------+-----------------------------+
| Time           | async processing     | stale projections           |
| Failure        | isolate outages      | delayed detection           |
| Ownership      | independent teams    | schema and semantic drift   |
| Load           | absorb bursts        | backlog and retention loss  |
+----------------+----------------------+-----------------------------+
```

SRE question:
What metric tells us this async path is failing before customers tell us?

---

## 5. Three Messaging Models

People say queue when they mean different contracts.
The three common models are task queue, publish/subscribe, and durable event log.
They all move messages.
They do not have the same semantics.
Using the wrong model creates systems that look reasonable and fail strangely.
A task queue asks which worker should perform this job.
Publish/subscribe asks which subscribers should react to this event.
A durable log asks who can read and replay this history.
MegaShop uses all three patterns in different places.
Receipt email can be a task queue.
OrderPlaced fanout can be pub/sub.
order-events in Kafka can be a durable log.
The tool follows the semantic need.
The semantic need does not follow the tool.

```text
+--------------------+------------------------------+-----------------------------+
| Model              | Core semantic                | MegaShop example            |
+--------------------+------------------------------+-----------------------------+
| Task queue         | one job to one worker        | SendReceiptEmail            |
| Publish/subscribe  | one event to many reactions  | OrderPlaced fanout          |
| Durable event log  | retained replayable history  | commerce.orders.events.v1   |
+--------------------+------------------------------+-----------------------------+
```

---

## 6. Task Queue: What It Is

A task queue stores jobs for workers.
The goal is work distribution.
One logical job should be assigned to one worker at a time.
This does not mean the side effect happens exactly once.
It means the broker tries to prevent concurrent processing of the same job.
MegaShop uses task queues for receipt email.
Checkout creates SendReceiptEmail(order_id=ord_123).
A worker receives the job.
The broker hides the job from other workers.
The worker sends the email.
The worker acknowledges success.
The broker removes the job.
If the worker crashes before acknowledgement, the broker can redeliver.
Redelivery is not a bug.
Redelivery is how the system avoids losing work.
Duplicate side effects must be controlled by the worker.
The broker protects delivery.
The application protects correctness.

```text
+----------+      +-------------+      +----------+
| Producer | ---> | Task Queue  | ---> | Worker A |
+----------+      +-------------+      +----------+
                         |
                         +------->     +----------+
                                       | Worker B |
                                       +----------+
```

Task queue is a good fit for background jobs.
It is good for image resize.
It is good for email delivery.
It is good for report generation.
It is good for webhook retries.
It is bad as a long replayable event backbone.
It is bad when many independent consumers need the same message history.

---

## 7. Task Queue Failure: Crash After Side Effect

This is the failure every beginner misses.

```text
T0  Worker receives SendReceiptEmail(ord_123).
T1  Worker calls email provider.
T2  Email provider accepts the message.
T3  Worker process crashes before ACK.
T4  Visibility timeout expires.
T5  Queue redelivers the same job.
T6  Another worker sends the same email.
```

The broker behaved correctly.
The broker did not know the email provider accepted the side effect.
The worker failed to make the side effect idempotent.
The fix is a durable sent marker or provider idempotency.
For email, use a marker such as receipt:ord_123:template_v3:customer_456.
For webhooks, use event_id plus destination_id.
For payment, use provider idempotency key.
For ledgers, use unique event_id.
Do not dedupe by timestamp.
Do not dedupe by process ID.
Do not dedupe by retry attempt ID.
Dedupe by business operation identity.

```text
+----------------------+-----------------------------------------+
| Side effect          | Safe idempotency key                    |
+----------------------+-----------------------------------------+
| receipt email        | order_id + template_id + recipient      |
| seller webhook       | event_id + seller_id + endpoint_id      |
| payment capture      | payment_intent_id + capture_attempt     |
| ledger entry         | event_id                                |
| search document      | order_id                                |
+----------------------+-----------------------------------------+
```

The queue can redeliver.
The business must not double charge, double ship, or double notify unless duplicates are acceptable.

---

## 8. Task Queue Operations

A task queue is operated by rate, age, retries, and DLQ state.
Queue depth alone is insufficient.
A queue with one million jobs can be healthy if it drains quickly.
A queue with one thousand jobs can be unhealthy if the oldest job is two hours old.
MegaShop email queue has a freshness SLO.
Example: 99 percent of receipt emails should be sent within five minutes.
That is not the same as checkout SLO.
Checkout may be green while email is delayed.
The correct incident statement is orders are safe and confirmations are delayed.
The incorrect statement is everything is fine.
Async failure is still failure.
It is just not always request failure.

```text
+------------------+------------------------------+-----------------------------+
| Metric           | What it means                | Failure hint                |
+------------------+------------------------------+-----------------------------+
| queue depth      | jobs waiting                 | backlog size                |
| oldest age       | user-visible delay           | freshness violation         |
| arrival rate     | producer pressure            | burst or normal load        |
| drain rate       | worker progress              | capacity                    |
| retry rate       | transient or code failures   | downstream/data issue       |
| DLQ rate         | permanent failures           | repair required             |
+------------------+------------------------------+-----------------------------+
```

Operational rule:
Scale workers only if downstream can handle more work.
If email provider is rate-limiting, adding workers can worsen the outage.

---

## 9. Publish/Subscribe: What It Is

Publish/subscribe fans out messages.
One published event can be consumed by many subscribers.
MegaShop publishes OrderPlaced.
Email sends receipt.
Search indexes order.
Analytics records revenue.
Fraud updates risk signals.
Warehouse starts fulfillment preparation.
The order service should not directly call every downstream system.
The event becomes the integration boundary.
This improves team independence.
It also creates hidden dependencies.
The publisher may not know every consumer.
A schema change can break a team the publisher did not consider.
Pub/sub reduces code coupling.
It does not remove semantic coupling.
The event contract becomes the coupling surface.

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

Good event names are facts.
OrderPlaced is a fact.
PaymentCaptured is a fact.
InventoryReserved is a fact.
SendEmail is a command.
ReserveInventory is a command.
Do not call commands events.
Do not call events commands.
Names encode ownership.

---

## 10. Pub/Sub Failure: Hidden Consumers

MegaShop order service publishes OrderPlaced.
The search team consumes line_items.
The fraud team consumes customer_id and device_id.
The analytics team consumes total_cents and currency.
The warehouse team consumes destination_region.
The order team removes destination_region because checkout no longer uses it.
Warehouse breaks.
The order service never called warehouse directly.
The dependency still existed.
Pub/sub moved the dependency into the event contract.
The fix is event governance.
Each event has an owner.
Each event has a schema.
Each event has compatibility rules.
Each event has deprecation policy.
Each critical event has consumer discovery.
Each breaking change has a migration plan.
For public platform events, casual JSON is not enough.
Events are APIs that happen over time.

```text
Producer change risk:

+-------------+        +----------+
| OrderPlaced | -----> | Search   | needs line_items
+-------------+        +----------+
       |
       +-------------> | Fraud    | needs customer_id, device_id
       |
       +-------------> | Warehouse| needs destination_region
```

A producer cannot safely change a public event by looking only at producer code.

---

## 11. Durable Event Log: What It Is

A durable event log stores ordered records for a retention window.
Kafka is primarily this model.
Consumers read from the log at their own pace.
One consumer reading a record does not delete it for others.
Each consumer group tracks its own offset.
MegaShop order-events topic stores order lifecycle facts.
Fraud may be current.
Search may be five minutes behind.
Analytics may replay from yesterday.
This is normal.
The same retained history can support many independent consumers.
Replay is the defining strength.
If search index is corrupted, rebuild from order-events.
If analytics logic had a bug, reprocess history.
If a new recommendation model needs past order facts, backfill from history.
Replay is also dangerous.
If email replay is unsafe, old receipts are sent again.
If payment command replay is unsafe, customers may be charged again.
Durable history requires replay-safe consumers.

```text
Topic: commerce.orders.events.v1

+-------------+-------------------+-------------------+---------+-----------+
| OrderPlaced | PaymentAuthorized | InventoryReserved | Packed  | Shipped   |
+-------------+-------------------+-------------------+---------+-----------+
      0                1                   2              3          4

Consumer progress:

fraud-service        offset 5
search-indexer       offset 3
analytics-pipeline   offset 1
```

Durable log is excellent for history.
It is overkill for one simple background job.

---

## 12. Kafka as a Distributed Commit Log

Kafka is a distributed, replicated, partitioned, append-only commit log.
Distributed means records live across multiple brokers.
Replicated means records have multiple copies.
Partitioned means each topic is split into ordered shards.
Append-only means records are appended, not updated in place.
Commit log means records are read by position.
The position is called an offset.
Kafka is optimized for sequential disk access.
Kafka is optimized for batching.
Kafka is optimized for compression.
Kafka is optimized for high-throughput fanout.
Kafka is not a relational database.
Kafka is not a global queue.
Kafka is not an object store.
Kafka is not a magic exactly-once side-effect machine.
Kafka's core abstraction is simple.
Append records to partitions.
Replicate them.
Let consumers read and track progress.
Everything else is built around that.

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

Kafka preserves order within one partition.
Kafka does not preserve total order across a multi-partition topic.
This rule drives partition-key design, consumer behavior, replay, and incident diagnosis.

---

## 13. Kafka Record Anatomy

A Kafka record is not just a payload.
It has topic.
It has partition.
It has offset.
It has key.
It has value.
It has timestamp.
It has headers.
The key usually determines partition.
The value contains the serialized event or command.
Headers carry metadata for routing, tracing, schema, or diagnostics.
Partition and offset are assigned by Kafka.
MegaShop events use an envelope.
The envelope makes every event observable and replayable.
Without event_id, dedupe is weak.
Without schema_version, compatibility is guesswork.
Without correlation_id, tracing is painful.
Without occurred_at and published_at, delay analysis is blurry.
Without aggregate_id, ordering scope is unclear.

```text
+----------------+---------------------------------------------+
| Field          | Purpose                                     |
+----------------+---------------------------------------------+
| event_id       | dedupe, audit, replay, DLQ repair           |
| event_type     | handler selection and business meaning      |
| schema_version | compatibility handling                      |
| aggregate_type | entity type, such as Order                  |
| aggregate_id   | entity identity and partition key candidate |
| occurred_at    | when business fact happened                 |
| published_at   | when event entered stream                   |
| correlation_id | trace request or workflow                   |
| causation_id   | explain why this event exists               |
| payload        | event-specific data                         |
+----------------+---------------------------------------------+
```

Example event:

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
  "payload": {
    "order_id": "ord_123",
    "customer_id": "cust_456",
    "total_cents": 129900,
    "currency": "USD"
  }
}
```

---

## 14. Topic Design

A topic is a named stream of records.
Topic design is architecture.
The name communicates domain.
The schema communicates contract.
The partition count communicates scale plan.
The retention setting communicates recovery window.
The cleanup policy communicates history semantics.
The replication factor communicates durability posture.
The ACLs communicate security boundaries.
The owner communicates accountability.
MegaShop avoids vague topic names.
Bad name: events.
Better name: commerce.orders.events.v1.
The better name says domain is commerce.
The better name says aggregate is orders.
The better name says data is events.
The better name says version is v1.
Topic design questions:
Who owns the topic.
Who produces to it.
Who consumes from it.
What business fact does it represent.
What schema governs it.
What key is used.
What ordering is promised.
What retention is needed.
What cleanup policy is used.
What criticality class applies.
What PII exists.
What runbook exists.

```text
+----------------------+--------------------------------------+
| Topic attribute      | Example                              |
+----------------------+--------------------------------------+
| name                 | commerce.orders.events.v1           |
| owner                | commerce-platform                    |
| key                  | order_id                             |
| retention            | 14 days                              |
| cleanup.policy       | delete                               |
| replication.factor   | 3                                    |
| min.insync.replicas  | 2                                    |
| schema format        | Avro or Protobuf                     |
| criticality          | high                                 |
+----------------------+--------------------------------------+
```

A topic without an owner is future incident debris.

---

## 15. Partition Design

A partition is an ordered shard of a topic.
Kafka uses partitions for ordering and parallelism.
One partition gives total topic order and limited parallelism.
Many partitions give more parallelism and no total topic order.
A consumer group can have at most one active consumer per partition.
Partition count limits maximum parallelism per group.
If a topic has 24 partitions, one group can actively use at most 24 consumers for that topic.
If the group has 60 consumers, 36 are idle for that topic.
More partitions can increase capacity.
More partitions also increase metadata overhead.
More partitions can increase recovery time.
More partitions can complicate rebalancing.
More partitions can change key mapping when added later.
Partition count is not a random big number.
It should be based on throughput, growth, ordering, recovery, and operational overhead.
MegaShop order-events might use 48 partitions after capacity modeling.
A small internal config topic may use far fewer.

```text
+------------------------+--------------------------------------+
| Partition choice       | Consequence                          |
+------------------------+--------------------------------------+
| too few partitions     | limited consumer parallelism         |
| too many partitions    | metadata and rebalance overhead      |
| bad partition key      | hot partition or ordering failure    |
| random key             | good spread, weak entity ordering    |
| entity key             | good entity order, possible skew     |
+------------------------+--------------------------------------+
```

---

## 16. Offsets

An offset is a position within one partition.
Offsets are monotonically increasing within a partition.
Offsets are not global across a topic.
Partition 0 offset 100 and partition 1 offset 100 are unrelated positions.
Consumers commit offsets per partition per consumer group.
A committed offset usually means the next record to read.
If committed offset is 103, records up to 102 are considered done by that group.
Considered done does not mean business side effects succeeded.
It only means the group stored progress.
This distinction is essential.
Commit too early and you can lose business work.
Commit too late and you can duplicate work.
Correct consumers commit after durable side effects.
Correct side effects are idempotent.

```text
Partition 2

+-----+-----+-----+-----+-----+
| 100 | 101 | 102 | 103 | 104 |
+-----+-----+-----+-----+-----+
              ^
              |
          processing

Committed offset after success should become 103.
```

Offset is read progress.
Offset is not business truth.

---

## 17. Kafka Log Segment Internals

A Kafka partition is stored as log segments on disk.
Each segment contains records.
Kafka also maintains index files for efficient lookup.
The log file stores record batches.
The offset index maps offsets to positions in the log file.
The time index maps timestamps to offsets.
This is why Kafka can seek by offset efficiently.
This is why Kafka can find offsets by timestamp for replay.
A partition is not one giant file forever.
Kafka rolls segments based on size or time.
Old segments become eligible for deletion or compaction depending policy.
Retention deletes whole segments when eligible.
Compaction rewrites segments to keep latest values by key eventually.
Understanding segments explains retention surprises.
If records in a segment are not fully eligible, the segment may remain.
If retention is based on time, segment timestamps matter.
If compaction is used, old duplicate keys may remain until cleaner processes them.

```text
Partition directory

+------------------------------------------------------------+
| 00000000000000000000.log        records                    |
| 00000000000000000000.index      offset -> byte position    |
| 00000000000000000000.timeindex  timestamp -> offset        |
| 00000000000000004200.log        records                    |
| 00000000000000004200.index      offset -> byte position    |
| 00000000000000004200.timeindex  timestamp -> offset        |
+------------------------------------------------------------+
```

SRE implication:
Disk usage is not just number of messages.
Disk usage depends on segment size, retention, replication, compression, indexes, and compaction lag.

---

## 18. Brokers, Leaders, Followers, and ISR

A broker is a Kafka server.
A cluster is a group of brokers.
Each partition has replicas.
One replica is leader.
Other replicas are followers.
Producers write to the leader.
Followers replicate from the leader.
Consumers usually read from leaders unless follower fetching is deliberately configured.
ISR means in-sync replicas.
A replica in ISR is caught up enough to count for durability.
With replication factor 3, a healthy partition has one leader and two followers.
If one follower lags, ISR shrinks.
If ISR shrinks below min.insync.replicas, acks=all writes can fail.
That is intentional.
It prevents Kafka from claiming durable success when not enough replicas are safe.
SREs must treat ISR shrink as meaningful.
It is storage safety margin shrinking.

```text
+-----------+        +-----------+        +-----------+
| Broker 1  |        | Broker 2  |        | Broker 3  |
+-----------+        +-----------+        +-----------+
| P0 leader |        | P0 follow |        | P0 follow |
| P1 follow |        | P1 leader |        | P1 follow |
| P2 follow |        | P2 follow |        | P2 leader |
+-----------+        +-----------+        +-----------+
```

Healthy ISR:
P0 ISR = Broker 1, Broker 2, Broker 3.
Follower lagging:
P0 ISR = Broker 1, Broker 2.
Danger:
P0 ISR = Broker 1 only when min.insync.replicas=2.
Writes with acks=all should fail.

---

## 19. Leader Election and Unclean Election

When a broker fails, partitions that had leaders on that broker need new leaders.
Kafka should elect a new leader from in-sync replicas.
If an in-sync follower becomes leader, committed data is preserved under the durability model.
If no in-sync follower exists, Kafka faces a hard choice.
Stay unavailable.
Or elect an out-of-sync replica and risk data loss.
This is the unclean leader election tradeoff.
For critical topics, unclean leader election is usually disabled.
Availability loss is painful.
Silent data loss is worse.
MegaShop order-events should prefer availability interruption over losing acknowledged business facts.
Low-value telemetry might choose differently.
This is another example of consequence-driven architecture.

```text
Clean election:

Leader dies
  -> ISR follower becomes new leader
  -> committed data preserved

Unclean election:

Leader dies
  -> no ISR follower available
  -> out-of-sync replica becomes leader
  -> data loss possible
```

Interview framing:
A senior answer says leader election is not merely failover.
It is a durability and availability tradeoff.

---

## 20. Rack Awareness

Rack awareness spreads replicas across failure domains.
A failure domain can be rack, availability zone, or datacenter depending deployment.
If all replicas for a partition live on the same rack, one rack failure can take them all out.
With rack awareness, Kafka tries to place replicas across racks.
MegaShop critical topics should use rack-aware placement.
Rack awareness is not magic.
It depends on correct broker configuration.
It depends on enough brokers per rack.
It depends on partition reassignment during topology changes.
It depends on monitoring skew.
A cluster can be replicated and still vulnerable if replicas are badly placed.
Replication count is not enough.
Replica placement matters.

```text
Bad placement:

Rack A: Broker 1, Broker 2, Broker 3
P7 replicas: Broker 1, Broker 2, Broker 3
Rack A failure loses all P7 replicas.

Better placement:

Rack A: Broker 1
Rack B: Broker 2
Rack C: Broker 3
P7 replicas: Broker 1, Broker 2, Broker 3
```

---

## 21. Producer Write Path

A producer write is a pipeline.
Application constructs the event.
Serializer converts key and value into bytes.
Partitioner chooses partition.
Producer accumulator groups records into batches.
Sender thread sends batches to leader brokers.
Broker receives ProduceRequest.
Leader validates request.
Leader appends batch to log.
Followers fetch from leader.
Leader waits for acknowledgement condition.
Producer receives success or error.
Application callback observes result.
Every step can fail.
Every step has configuration.
Ignoring producer errors is data loss by policy.

```text
+-------------+      +------------+      +-------------+      +--------+
| Application | ---> | Serializer | ---> | Partitioner | ---> | Batch  |
+-------------+      +------------+      +-------------+      +--------+
                                                              |
                                                              v
+-------------+      +-------------+      +-------------+      +--------+
| Ack/Error   | <--- | Replication | <--- | Leader Log  | <--- | Sender |
+-------------+      +-------------+      +-------------+      +--------+
```

MegaShop order producer cannot fire-and-forget.
If publish fails and order commit succeeds, downstream systems miss the order.
This is why outbox is usually preferred for authoritative business events.

---

## 22. Producer Accumulator and Batching

The producer accumulator holds unsent records grouped by topic-partition.
Batches improve throughput.
Batching reduces request overhead.
Batching improves compression.
Batching can increase latency.
linger.ms controls how long the producer may wait for a fuller batch.
batch.size controls target batch size per partition.
compression.type controls compression algorithm.
High-throughput analytics events can tolerate more batching.
Low-latency order-state events may use smaller linger.
The right setting depends on SLO.
A tiny batch size wastes network and CPU.
A huge linger can delay critical facts.
A producer with insufficient memory buffer can block or error under load.
Producer metrics must expose buffer exhaustion.

```text
Records before batching:

r1 -> request
r2 -> request
r3 -> request
r4 -> request

Records after batching:

[r1 r2 r3 r4] -> one request
```

SRE signal:
If producer buffer available bytes falls and record queue time rises, broker or network path may be slow.

---

## 23. Producer Acknowledgements

acks controls when producer considers a write successful.
acks=0 means no broker acknowledgement.
acks=1 means leader acknowledged local append.
acks=all means leader waits for in-sync replica condition.
For MegaShop order-events, acks=all is the normal production choice.
For debug telemetry, acks=1 or lower durability may be acceptable.
The key is business consequence.
A lost OrderPlaced creates downstream inconsistency.
A lost debug sample may be acceptable.
acks=1 failure timeline:

```text
T0  Producer sends OrderPlaced(ord_123).
T1  Leader appends record.
T2  Leader sends success.
T3  Leader crashes before followers replicate.
T4  New leader lacks record.
T5  Producer believes record exists.
T6  Search, email, analytics, and warehouse never see it.
```

acks=all with replication.factor=3 and min.insync.replicas=2 changes this.
Kafka should only acknowledge when at least two replicas are in sync.
If not enough replicas are safe, producer gets an error.
Visible write failure is painful.
Silent acknowledged loss is worse.

---

## 24. Producer Idempotence

Producer idempotence protects against duplicate appends caused by retry ambiguity.
The producer sends a batch.
The broker writes the batch.
The acknowledgement is lost.
The producer retries.
Without idempotence, the broker may append duplicate records.
With idempotence, producer sequence numbers let broker reject duplicate retry.
This is scoped to producer writes into Kafka.
It does not make consumer side effects idempotent.
It does not stop a consumer from sending email twice.
It does not stop a payment provider call from repeating.
It does not dedupe two different valid events with different event IDs.
MegaShop enables idempotent producer behavior for critical event producers.
MegaShop still designs consumers to handle duplicates.
Producer idempotence and consumer idempotence solve different halves of the pipeline.

```text
Without idempotent producer:

send batch B
broker appends B
ack lost
producer retries B
broker appends B again

With idempotent producer:

send batch B with sequence 42
broker appends sequence 42
ack lost
producer retries sequence 42
broker recognizes duplicate
```

---

## 25. Producer Ordering and max.in.flight

Producer retries can affect ordering if multiple requests are in flight.
Suppose batch A and batch B go to the same partition.
Batch A fails transiently.
Batch B succeeds.
Batch A retries later.
Without correct idempotent producer semantics and ordering controls, log order can be surprising.
Modern Kafka idempotent producers are designed to preserve ordering within constraints.
The principle remains important.
Ordering guarantees are not magic.
They depend on producer configuration, partition, retries, and broker behavior.
For order lifecycle events, MegaShop avoids multiple producers racing for the same order stream when possible.
If multiple services emit events for the same aggregate, ordering must be explicitly designed.
One common pattern is a workflow service that owns sequence transitions.
Another pattern is per-aggregate version checks.
Another pattern is event sourcing with optimistic concurrency.
Kafka partition order alone cannot fix business-level races before the event reaches Kafka.

---

## 26. Producer Error Classes

Producer errors are not all equal.
Some are retriable.
Some are fatal.
Some indicate authorization failure.
Some indicate record too large.
Some indicate unknown topic.
Some indicate insufficient replicas.
Some indicate serialization failure before the record even reaches Kafka.
Operational response depends on class.
If records are too large, retrying does not help.
If ISR is below min.insync.replicas, retry may succeed after replicas recover.
If ACL denies write, retrying wastes time.
If schema registry rejects incompatible schema, rollback producer.
MegaShop producer alerting groups errors by class.
A single producer_error_rate metric is not enough.

```text
+----------------------------+--------------------------------------+
| Error type                 | Likely response                      |
+----------------------------+--------------------------------------+
| authorization failure      | fix ACL or service identity          |
| record too large           | change schema or topic limits        |
| serialization failure      | fix producer code/schema             |
| not enough replicas        | inspect ISR and broker health        |
| timeout                    | inspect broker/network/acks          |
| schema incompatibility     | rollback or migrate schema           |
+----------------------------+--------------------------------------+
```

---

## 27. Python Producer Example

This example is conceptual.
Client libraries differ.
The important details are stable event identity, stable partition key, schema version, headers, and delivery observation.

```python
import json
from datetime import datetime, timezone

class PublishError(Exception):
    pass

def utc_now():
    return datetime.now(timezone.utc).isoformat()

def build_order_placed(order, correlation_id):
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
        "payload": {
            "order_id": order["id"],
            "customer_id": order["customer_id"],
            "total_cents": order["total_cents"],
            "currency": order["currency"],
        },
    }

def publish_order_placed(producer, order, correlation_id):
    event = build_order_placed(order, correlation_id)
    key = event["aggregate_id"].encode("utf-8")
    value = json.dumps(event, separators=(",", ":")).encode("utf-8")
    delivery = producer.produce(
        topic="commerce.orders.events.v1",
        key=key,
        value=value,
        headers={
            "event_type": event["event_type"],
            "schema_version": str(event["schema_version"]),
            "correlation_id": correlation_id,
        },
    )
    producer.flush()
    return delivery
```

What this teaches:
The key is order_id.
The event has event_id.
The schema version is explicit.
The correlation ID is preserved.
The producer does not silently ignore delivery.
For authoritative order publication, MegaShop would still prefer outbox over direct publish in the request path.

---

## 28. Broker Produce Request Path

A broker receiving a produce request does several things.
It authenticates the client.
It authorizes write permission.
It validates topic and partition.
It verifies the target broker is leader for that partition.
It appends the record batch to the log.
It updates relevant in-memory state.
It waits for required replicas depending acks.
It returns success or error.
If the broker is not leader, the producer must refresh metadata and retry against the correct leader.
If disk is slow, produce latency rises.
If request handlers are saturated, produce latency rises.
If ISR is shrinking, acks=all can fail.
If quotas are exceeded, the broker can throttle.
SREs must connect producer errors to broker-side signals.

```text
+----------+      +------------+      +-----------+      +---------+
| Producer | ---> | Broker API | ---> | Log append| ---> | Replicas|
+----------+      +------------+      +-----------+      +---------+
                       |                 |                 |
                       v                 v                 v
                  authz check       disk latency      ISR condition
```

---

## 29. Consumer Read Path

A consumer reads from assigned partitions.
The consumer sends fetch requests to brokers.
Brokers return batches from log segments.
The client deserializes records.
Application code processes records.
Offsets are committed after safe processing.
MegaShop search-indexer reads OrderPlaced.
It transforms the order into a search document.
It writes to OpenSearch.
It commits after OpenSearch write is safe.
If commit happens before OpenSearch write, the projection can miss data.
If write happens before commit and process crashes, Kafka redelivers.
Therefore the OpenSearch write must be idempotent.
Using order_id as document ID makes indexing repeatable.

```text
+----------+      +----------+      +-------------+      +------------+
| Kafka    | ---> | Consumer | ---> | Transform   | ---> | OpenSearch |
| partition|      | poll     |      | event -> doc|      | index      |
+----------+      +----------+      +-------------+      +------------+
                       |
                       v
                 commit offset
```

Consumer correctness is where Kafka mechanics meet business state.

---

## 30. Consumer Groups

A consumer group is a named set of consumers that share partition ownership.
Each partition is assigned to at most one active consumer within the group.
Different groups are independent.
MegaShop has search-indexer group.
MegaShop has fraud-service group.
MegaShop has analytics-pipeline group.
All can consume commerce.orders.events.v1 independently.
Search can lag while fraud is current.
Analytics can replay while email continues.
This independence is powerful.
It also means every group needs its own freshness SLO.
A global topic health status is insufficient.

```text
Topic: commerce.orders.events.v1
Partitions: 6
Consumer group: search-indexer

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

If there are 6 partitions and 10 consumers, only 6 can be active for this topic.
More consumers do not split one partition.

---

## 31. Group Coordinator and Rebalancing

Kafka uses group coordination to assign partitions.
A group coordinator tracks group membership.
Consumers join the group.
The assignor chooses partition ownership.
Consumers send heartbeats.
If a consumer leaves or fails, the group rebalances.
Rebalancing is normal.
Rebalance storms are incidents.
During rebalances, partition ownership changes.
Depending protocol and assignor, processing may pause.
A deploy that restarts many consumers can create repeated rebalances.
Autoscaling based only on lag can create more rebalances.
A slow consumer can exceed max.poll.interval.ms and be removed from the group.
MegaShop treats rebalance rate as an operational signal.
Lag plus rebalance spike means stability problem, not just capacity problem.

```text
+-------------+      join       +-------------------+
| Consumer A  | --------------> | Group Coordinator |
+-------------+                 +-------------------+
+-------------+      heartbeat          |
| Consumer B  | ------------------------+
+-------------+                         |
+-------------+      assignment         v
| Consumer C  | <---------------- partitions
+-------------+
```

Mitigations:
Use cooperative rebalancing where appropriate.
Use static membership where appropriate.
Deploy in smaller waves.
Keep processing time below max.poll.interval.ms.
Do not autoscale on lag without downstream capacity and rebalance awareness.

---

## 32. Consumer Configuration

Important consumer settings affect correctness and stability.

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

group.id defines offset namespace.
enable.auto.commit controls automatic progress recording.
auto.offset.reset controls start point when no committed offset exists.
max.poll.records controls batch size.
max.poll.interval.ms controls allowed time between polls.
session.timeout.ms controls failure detection window.
heartbeat.interval.ms controls heartbeat frequency.
fetch.min.bytes and fetch.max.wait.ms trade latency for throughput.
isolation.level=read_committed hides aborted transactional records.
For side-effecting consumers, auto commit is dangerous.
Auto commit can record progress before business work is durable.
MegaShop disables auto commit for consumers that mutate external systems.
Manual commit happens after safe processing.
That creates at-least-once delivery.
At-least-once requires idempotency.

---

## 33. Offset Commit Failure Timelines

Commit before processing creates loss.

```text
T0  Consumer polls offset 102.
T1  Consumer commits offset 103.
T2  Consumer starts processing offset 102.
T3  Consumer crashes before writing search document.
T4  Consumer restarts from committed offset 103.
T5  Offset 102 is never processed.
```

Process before commit creates duplicates.

```text
T0  Consumer polls offset 102.
T1  Consumer writes search document for order ord_123.
T2  Consumer crashes before committing offset 103.
T3  Consumer restarts from offset 102.
T4  Consumer writes search document again.
```

The second pattern is usually preferred for business workflows.
Duplicate attempts can be controlled.
Missing work may remain invisible.
The search document write is idempotent if id=order_id.
A ledger insert is idempotent if event_id is unique.
An email send is idempotent if sent marker exists before retry.
A payment capture is idempotent if provider idempotency key is stable.

---

## 34. __consumer_offsets

Kafka stores committed consumer offsets in an internal topic named __consumer_offsets.
This topic is compacted.
It stores group, topic, partition, and offset metadata.
Offset commits are Kafka records.
This matters because offset storage can have its own latency and failure modes.
If offset commits fail, consumers may reprocess data.
If a group is deleted, its offsets can disappear.
If auto.offset.reset is earliest, a new group may replay from beginning.
If auto.offset.reset is latest, a new group may skip historical data.
MegaShop treats consumer group names as stable production identities.
Changing group.id is not a harmless refactor.
Changing group.id creates a new offset namespace.
A new offset namespace can replay or skip depending configuration.

```text
Consumer group key:

(group = search-indexer,
 topic = commerce.orders.events.v1,
 partition = 17)

Committed value:

(offset = 8819232,
 metadata = app-specific optional text,
 commit_timestamp = ...)
```

Production rule:
Never change group.id without an explicit replay or cutover plan.

---

## 35. Python Consumer Example

This example shows safe structure.
It is conceptual and omits library-specific boilerplate.

```python
import json

class PermanentError(Exception):
    pass

class TransientError(Exception):
    pass

def build_search_document(event):
    payload = event["payload"]
    return {
        "order_id": payload["order_id"],
        "customer_id": payload["customer_id"],
        "total_cents": payload["total_cents"],
        "currency": payload["currency"],
        "occurred_at": event["occurred_at"],
    }

def handle_order_placed(record, search_client, dlq_producer):
    try:
        event = json.loads(record.value)
        if event["event_type"] != "OrderPlaced":
            return "ignored"
        if event["schema_version"] not in (2, 3):
            raise PermanentError("unsupported schema version")
        doc = build_search_document(event)
        search_client.index(
            index="orders",
            id=doc["order_id"],
            document=doc,
        )
        return "processed"
    except PermanentError as exc:
        publish_dlq(record, exc, dlq_producer)
        return "dlq"

def publish_dlq(record, exc, producer):
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

The search write is safe because document ID is deterministic.
The DLQ preserves original context.
The consumer should commit after processed or intentionally DLQ-handled records.
It should not commit records lost in unknown state.

---

## 36. At-Most-Once

At-most-once means the system may lose work but avoids duplicate processing.
A consumer commits before processing.
If it crashes, Kafka will not redeliver.
This can be acceptable for low-value sampled telemetry.
This is unacceptable for orders, payments, inventory, security, and ledgers.
MegaShop does not use at-most-once for OrderPlaced.
At-most-once sounds comforting because duplicates are avoided.
The price is possible loss.
In business systems, loss is often worse than duplicate attempt.
A duplicate can be deduped.
Missing work can stay hidden until a customer complains.

```text
At-most-once timeline:

poll record
commit offset
crash before side effect
record is skipped forever
```

Use only when loss is explicitly acceptable.

---

## 37. At-Least-Once

At-least-once means the system tries not to lose work but may duplicate attempts.
The consumer processes first.
The consumer commits after safe processing.
If it crashes after processing but before commit, Kafka redelivers.
This is the most common production model for business event consumers.
MegaShop uses at-least-once for search indexing.
It uses at-least-once for analytics with event_id dedupe.
It uses at-least-once for email with sent markers.
It uses at-least-once for warehouse requests with request IDs.
At-least-once is honest about failure.
It assumes crashes happen.
It assumes acknowledgements can be lost.
It assumes retries happen.
The application must make duplicate attempts safe.

```text
At-least-once timeline:

poll record
write side effect
crash before commit
record is redelivered
side effect must be idempotent
```

---

## 38. Effectively-Once

Effectively-once means duplicates may occur in transport but final business state changes once.
This is usually achieved through idempotency keys and database constraints.
Example ledger table:

```sql
CREATE TABLE ledger_entries (
  event_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  amount_cents BIGINT NOT NULL,
  currency TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL
);
```

If PaymentCaptured evt_123 is processed twice, only one row can exist.
The database enforces the invariant.
Kafka did not magically deliver once.
The business state is protected by application and database design.
MegaShop uses effectively-once for ledger projections.
It still reconciles with provider truth.
Effectively-once is a system property.
It is not a broker checkbox.

---

## 39. Kafka Transactions and Exactly-Once Scope

Kafka transactions are useful for read-process-write pipelines inside Kafka.
A processor consumes from topic A.
It writes to topic B.
It commits consumed offsets as part of the transaction.
This prevents output without offset commit.
It prevents offset commit without output.
This is valuable for stream processing.
It does not include Stripe.
It does not include email providers.
It does not include warehouse APIs.
It does not include arbitrary database writes unless separately coordinated.
Exactly-once must always state scope.
Exactly once where.
Exactly once for what state.
Exactly once under what failure.
Exactly once as observed by which system.
MegaShop uses Kafka transactions for selected stream transforms.
MegaShop does not use Kafka transactions as a substitute for payment idempotency.

```text
Kafka transaction scope example:

Input topic A offset 100
Output topic B record X
Offset commit for A:100

All committed together inside Kafka transaction.
```

External side effects still require idempotency and reconciliation.

---

## 40. Idempotency by Side Effect

Idempotency means repeated processing produces the same final business result.
The technique differs per side effect.
Search indexing uses deterministic document ID.
Ledger writes use unique event_id.
Email uses sent markers.
Webhook delivery uses event_id plus destination_id.
Payment capture uses provider idempotency key.
Warehouse request uses stable fulfillment request ID.
Cache invalidation is often naturally repeatable.
Analytics counters require event_id dedupe or batch-level dedupe.
MegaShop designs idempotency per consumer.
There is no universal idempotency library.
There are only stable business identities.

```text
+---------------------+--------------------------------------+
| Side effect         | Idempotency control                  |
+---------------------+--------------------------------------+
| Search index        | document id = order_id               |
| Ledger              | unique event_id                      |
| Email               | sent marker per order/template/user  |
| Webhook             | event_id + destination_id            |
| Payment             | provider idempotency key             |
| Warehouse           | fulfillment_request_id               |
| Analytics           | event_id dedupe table/window         |
+---------------------+--------------------------------------+
```

Rule:
If you cannot explain duplicate behavior, the consumer is not production-ready.

---

## 41. Partition Key Design

Partition key controls ordering and distribution.
Kafka maps key to partition through a partitioner.
A common conceptual model is hash(key) modulo partition count.
The exact client behavior can vary.
The design lesson is stable.
The key chooses the lane.
All records for the same key usually land on the same partition.
That preserves per-key order.
That can also create hot partitions.
MegaShop order lifecycle should usually key by order_id.
That keeps OrderPlaced, PaymentAuthorized, InventoryReserved, Packed, and Shipped ordered for one order.
MegaShop product analytics during a launch should not blindly key by product_id.
One hot product can dominate one partition.
A partition key is not metadata.
It is a capacity and correctness decision.

```text
Good for order lifecycle:

key = order_id

Partition 8
+-------------+-------------------+-------------------+--------+---------+
| OrderPlaced | PaymentAuthorized | InventoryReserved | Packed | Shipped |
+-------------+-------------------+-------------------+--------+---------+
```

---

## 42. Hot Partition Failure

A hot partition receives disproportionate traffic.
MegaShop changes key from order_id to product_id.
SNKR-2026 launch sends most orders for one product.
All those events hash to one partition.
One partition has one active consumer per group.
Inventory-projector falls behind.
Search-indexer falls behind.
Other consumers are idle.
Adding consumers does not split that one hot partition.
Autoscaling may increase rebalance churn.
The fix is key design.
For order lifecycle, use order_id.
For product analytics, use product_id plus bucket if total product order is not required.
For customer notification order, use customer_id.
For account ledger, use account_id.
Choose the smallest entity that truly requires ordering.

```text
During launch with key=product_id:

+-------------+-------------+
| Partition   | Traffic     |
+-------------+-------------+
| 0           |   3K/sec    |
| 1           |   2K/sec    |
| 2           | 180K/sec    |
| 3           |   4K/sec    |
+-------------+-------------+
```

SRE diagnosis:
One partition lag dominates total lag.
One consumer host is hot.
Other consumers are idle.
Scaling group does not help.

---

## 43. Bucketed Keys

Bucketed keys spread a hot logical key across multiple partitions.
Example key:
product_id + ':' + hash(order_id) % 32.
SNKR-2026 becomes SNKR-2026:00 through SNKR-2026:31.
This spreads load.
It sacrifices total ordering for product_id.
That trade is acceptable only if total product order is not required.
For metrics aggregation, bucketed product key may be fine.
For a strict product-level state machine, it may be wrong.
Bucket count must be chosen deliberately.
Too few buckets can still hot spot.
Too many buckets complicate aggregation.
Downstream consumers may need to merge buckets.
MegaShop uses bucketed keys for high-volume analytics streams.
MegaShop does not use bucketed keys for order lifecycle.

```text
+----------------+      +-------------+
| SNKR-2026:00   | ---> | Partition 4 |
| SNKR-2026:01   | ---> | Partition 9 |
| SNKR-2026:02   | ---> | Partition 2 |
| SNKR-2026:03   | ---> | Partition 7 |
+----------------+      +-------------+
```

Architecture question:
What ordering are you intentionally giving up?

---

## 44. Adding Partitions Later

Adding partitions is not a harmless scaling button.
Existing records do not move.
New records may map differently.
For hash-based partitioning, changing partition count can change key mapping.
Records for the same key before expansion may be in one partition.
Records for the same key after expansion may go to another partition.
That can break cross-expansion per-key ordering assumptions.
Some partitioners offer sticky or custom behavior.
The risk still must be reviewed.
During a P1 hot partition incident, adding partitions may not fix current lag.
Old hot records remain in the old partition.
New hot records may or may not redistribute depending key and partitioner.
MegaShop treats partition expansion as a migration.
For major key changes, a corrected topic and controlled cutover may be safer.

```text
Before expansion:
key ord_123 -> partition 7

After expansion:
key ord_123 -> partition 19

Ordering across old and new partitions is no longer automatic.
```

---

## 45. Consumer Lag

Consumer lag is the distance between log end offset and committed offset.
It is measured per partition per consumer group.
Lag is not automatically bad.
Lag is bad when it violates freshness, retention safety, or downstream business expectations.
MegaShop search can tolerate seconds or minutes depending feature.
Fraud may tolerate less.
Analytics may tolerate more.
Email has a customer-trust freshness target.
The same raw lag count can mean different impact.
Five million records behind on a huge stream may be seconds.
Five million records behind on a small stream may be hours.
Lag age often matters more than lag count.

```text
log end offset:       1,000,000
committed offset:       850,000
lag:                   150,000 records
```

Rate math:

```text
produce rate:      50,000 records/sec
consumer rate:     35,000 records/sec
lag growth:        15,000 records/sec
10 minute growth:   9,000,000 records
```

If consumer capacity is below producer rate, catch-up never happens.

---

## 46. Lag Pattern Diagnosis

All partitions lagging suggests broad capacity or dependency trouble.
One partition lagging suggests hot key, poison record, or slow partition owner.
Sawtooth lag suggests periodic interruption.
Flat high lag with equal offsets may indicate stuck consumers.
Lag with high downstream p99 suggests sink bottleneck.
Lag with high rebalance rate suggests group instability.
Lag with broker fetch latency suggests Kafka-side issue.
Lag with producer spike suggests burst absorption.
MegaShop always graphs lag by partition.
A total lag graph can hide the true shape.

```text
Partition lag sample:

+-----------+-------------+
| Partition | Lag         |
+-----------+-------------+
| 00        |       1,200 |
| 01        |       1,100 |
| 02        |   8,500,000 |
| 03        |         900 |
+-----------+-------------+
```

This is not a generic scaling problem.
This is a partition-specific incident.
Check key distribution.
Check repeated offset.
Check consumer host health.
Check downstream calls from that host.

---

## 47. Backpressure

Backpressure prevents uncontrolled pressure on downstream systems.
Kafka can buffer.
Kafka cannot make OpenSearch faster.
If a consumer writes into a saturated database at full speed, retries can amplify failure.
Backpressure options include pause partitions.
Reduce batch size.
Throttle catch-up.
Move transient failures to delayed retry topics.
Shed non-critical consumers.
Protect critical paths.
MegaShop search-indexer backs off when OpenSearch rejects bulk writes.
It does not immediately retry forever.
It does not run full-speed replay into an unhealthy cluster.
Backpressure converts a destructive failure into a controlled delay.

```text
+-------+      +----------+      +------------+
| Kafka | ---> | Consumer | ---> | OpenSearch |
+-------+      +----------+      +------------+
                  pause             saturated
                  resume
                  throttle
```

SRE rule:
Do not treat lag reduction as the only goal.
Safe recovery matters more than cosmetic lag collapse.

---

## 48. Retention

Retention decides how long Kafka keeps records.
Retention is a recovery policy.
It is also a storage cost decision.
Consumer acknowledgement does not delete a Kafka record.
Records remain until retention or compaction removes them.
MegaShop order-events retention must exceed realistic detection and recovery windows.
If analytics can be broken for three days, one-day retention is unsafe.
If search rebuild takes two days, one-day retention is unsafe.
If legal history is required for years, Kafka retention may not be enough and data lake or database storage is required.
Retention failure:

```text
retention:       24 hours
consumer outage: 36 hours
missing replay:  12 hours
```

If another source of truth exists, backfill may be possible.
If Kafka was the only history, data is gone.
Retention is storage cost converted into recovery ability.

---

## 49. Retention Storage Math

Storage math prevents fantasy architecture.
Assume average compressed record size is 500 bytes.
Assume produce rate is 100,000 records/sec.
Compressed ingress is about 50 MB/sec.
Seven days is 604,800 seconds.
Single-copy storage is about 30 TB.
Replication factor 3 makes it about 90 TB before overhead.
Indexes, filesystem overhead, safety margin, and uneven partitions add more.
Retention choices are expensive.
The cost may be justified for order history.
It may not be justified for low-value click noise.

```text
record size:        500 bytes compressed
rate:               100,000/sec
ingress:            50 MB/sec
retention:          604,800 sec
replication factor: 3
storage:            50 * 604,800 * 3 MB
storage:            about 90 TB
```

Interview signal:
A strong candidate calculates storage instead of saying Kafka scales.

---

## 50. Compaction

Compaction keeps the latest value per key eventually.
It is useful for latest-state topics.
Feature flags can use compaction.
Account settings can use compaction.
Current user profile can use compaction.
Payment audit history should not depend on compaction.
Order lifecycle history should usually not be compacted away.
Security events should not be compacted if every event matters.
Compaction is eventual.
Old records can remain until cleaner runs.
Tombstones can eventually remove keys from compacted topics.
Compaction is not immediate deletion.
Compaction is not a privacy guarantee by itself.
MegaShop uses compacted topics for configuration-like state.
MegaShop uses delete-retained topics for event history.

```text
Before compaction:

key=user_1 value=A
key=user_1 value=B
key=user_1 value=C

After compaction eventually:

key=user_1 value=C
```

Question:
Do you need latest state or every historical fact?

---

## 51. Schema Formats

Kafka stores bytes.
Schema tools give meaning to bytes.
JSON is readable but loose.
Avro is compact and common with Schema Registry.
Protobuf is compact and strongly structured but field numbers matter.
JSON Schema provides validation with readable payloads.
The format matters less than compatibility discipline.
MegaShop uses schema compatibility gates for public topics.
A producer cannot remove a required field casually.
A producer cannot change currency from string to object without migration.
A producer cannot reuse Protobuf field numbers.
A producer cannot change semantic meaning under the same field name safely.
Consumer compatibility matters because old records remain in Kafka.
A newly deployed consumer may read old records.
An old consumer may read new records during rollout.
Both directions matter depending compatibility policy.

```text
+-------------+-----------------------+-----------------------------+
| Format      | Strength              | Risk                        |
+-------------+-----------------------+-----------------------------+
| JSON        | readable              | weak contracts              |
| Avro        | registry friendly     | schema discipline required  |
| Protobuf    | compact typed         | field number mistakes       |
| JSON Schema | readable validation   | larger payloads             |
+-------------+-----------------------+-----------------------------+
```

---

## 52. Schema Evolution

Safe schema evolution is staged.
Add optional field.
Deploy consumers that understand old and new shape.
Start producing new field.
Backfill if needed.
Stop reading old field.
Remove only after compatibility and retention windows.
Breaking changes include removing required fields.
Breaking changes include renaming fields without dual-write period.
Breaking changes include changing type.
Breaking changes include changing meaning.
Breaking changes include reusing Protobuf field numbers.
MegaShop treats schema as a platform contract.
OrderPlaced is consumed by many teams.
The producer team cannot reason only from checkout code.

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

Never reuse reserved field numbers.
Old bytes can become new lies.

---

## 53. Schema Break Failure

A producer deploy removes total_cents from OrderPlaced.
Search still works because it does not need total_cents.
Analytics crashes loudly.
Fraud silently treats missing amount as zero.
Silent semantic failure is worse than crash.
The system now makes incorrect risk decisions.
The schema registry might catch structural incompatibility.
It may not catch semantic misuse.
Consumer contract tests are needed.
Critical consumers should have compatibility test suites.
Producer deployment should know downstream contract impact.
DLQ spike is one detection path.
Business metric drift is another.
Fraud approval rate anomaly can reveal semantic failure.
Schema governance is not bureaucracy.
It is blast-radius control.

---

## 54. Retry Topics

Not every failure should be retried the same way.
Malformed schema is not fixed by retrying.
OpenSearch 503 may be transient.
Payment provider timeout may be ambiguous.
Authorization failure may require configuration fix.
Retry policy must classify errors.
Immediate retry can amplify outages.
Delayed retry can give dependencies time to recover.
MegaShop email sender uses retry topics.
First retry after one minute.
Second retry after five minutes.
Third retry after thirty minutes.
Then DLQ.
Each retry preserves original event_id and attempt metadata.
Each retry avoids losing original context.

```text
+------------+      +----------+      +----------+      +-----------+      +-----+
| Main Topic | ---> | Retry 1m | ---> | Retry 5m | ---> | Retry 30m| ---> | DLQ |
+------------+      +----------+      +----------+      +-----------+      +-----+
```

Retries are medicine only at the right dose.

---

## 55. DLQ Design

A DLQ stores records that cannot be processed after bounded attempts.
A DLQ is not a trash can.
A DLQ is an evidence locker.
A useful DLQ record includes original topic.
It includes original partition.
It includes original offset.
It includes key.
It includes headers.
It includes payload.
It includes schema version.
It includes consumer group.
It includes error class.
It includes error message.
It includes application version.
It includes failed timestamp.
It includes correlation_id.
A DLQ without replay tooling is unfinished engineering.
A DLQ without owner is hidden failure.
MegaShop pages on payment DLQ growth.
MegaShop alerts on search DLQ growth.
MegaShop tickets low-value analytics DLQ growth.
Severity follows business consequence.

```json
{
  "original_topic": "commerce.orders.events.v1",
  "original_partition": 17,
  "original_offset": 8819231,
  "key": "ord_123",
  "consumer_group": "search-indexer",
  "error_class": "SchemaValidationError",
  "error_message": "missing total_cents",
  "schema_version": 4,
  "correlation_id": "req_abc"
}
```

---

## 56. DLQ Replay Safety

Replay is a production operation.
It should not be a panic button.
Before replay, classify DLQ records.
Group by error class.
Group by event type.
Group by schema version.
Group by producer version.
Fix code or data.
Verify idempotency.
Replay with rate limits.
Monitor downstream p99.
Monitor DLQ re-entry rate.
Track replay success count.
Archive records only after policy.
Do not replay malformed records into the same broken consumer.
Do not replay millions of records into a saturated dependency.
Do not replay side-effecting consumers unless duplicate behavior is controlled.
MegaShop replay tool requires explicit target topic, consumer group, rate limit, and reason.

---

## 57. Transactional Outbox

The dual-write problem appears when a service writes database state and Kafka separately.
MegaShop checkout writes OrdersDB.
It also needs OrderPlaced in Kafka.
If database commit succeeds and Kafka publish fails, order exists but event is missing.
If Kafka publish succeeds and database transaction rolls back, event exists for nonexistent order.
Transactional outbox solves this with one database transaction.
Checkout writes order row.
Checkout writes outbox row.
Both commit together.
A relay or CDC connector publishes the outbox event to Kafka later.
If publisher fails, outbox row remains.
If database transaction rolls back, no outbox row exists.
Outbox prevents local database and event publication divergence.
Outbox does not prevent duplicate delivery.
Consumers still need idempotency.

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

---

## 58. Outbox Table Design

A practical outbox table needs stable event identity.
It needs aggregate identity.
It needs event type.
It needs schema version.
It needs payload.
It needs created_at.
It needs published_at or status.
It needs retry metadata if relay is polling.
It needs indexes for unpublished rows.
It needs cleanup policy after successful publication.
It needs monitoring on oldest unpublished row age.
MegaShop does not treat outbox rows as invisible internals.
Outbox backlog means business events are delayed.
Outbox backlog can be customer-impacting even if checkout succeeds.

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

SRE metric:
oldest unpublished outbox row age.

---

## 59. CDC and Kafka Connect

CDC means change data capture.
A connector reads committed database changes and publishes them downstream.
Debezium is a common CDC tool in Kafka ecosystems.
PostgreSQL CDC reads WAL through replication mechanisms.
MySQL CDC reads binlog.
CDC is powerful because it observes committed database truth.
CDC is risky because connector lag becomes event lag.
Replication slots can retain WAL.
Retained WAL can fill database disk.
Snapshotting can overload the primary database.
Schema changes can break connector tasks.
Kafka Connect task failure can stop publication.
MegaShop monitors outbox backlog and connector lag separately.
Outbox backlog means events are not leaving the database.
Kafka consumer lag means events reached Kafka but consumers are behind.
These are different incidents.

```text
+----------+      +-----------+      +-------+      +----------+
| OrdersDB | ---> | Connector | ---> | Kafka | ---> | Consumer |
+----------+      +-----------+      +-------+      +----------+
     |                 |                |              |
     v                 v                v              v
 outbox age       source lag        broker health   group lag
```

---

## 60. PostgreSQL Replication Slot Risk

A PostgreSQL replication slot preserves WAL needed by a CDC connector.
If the connector stops, WAL can accumulate.
If WAL accumulates enough, disk can fill.
If database disk fills, the source of truth is at risk.
A Kafka pipeline can become a database incident.
The source database must be protected first.
Dropping the replication slot may free WAL.
Dropping the slot may force a re-snapshot.
A re-snapshot may overload the primary database.
Restarting connector may be enough.
Increasing disk may be urgent.
There is no one-line fix.
SREs must understand the failure mode.

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
active=false plus growing retained_bytes is dangerous.
retained_bytes near disk limit is a database availability incident.

---

## 61. Kafka Connect Operations

Kafka Connect runs connectors as workers and tasks.
A connector defines the integration.
Tasks perform parallel work.
A failed task can stop part of the pipeline.
A connector can be running but lagging.
A connector can be paused.
A connector can fail because of schema incompatibility.
A connector can fail because source credentials expired.
A sink connector can fail because downstream rejects writes.
MegaShop monitors connector state and task state.
It monitors source lag.
It monitors error rate.
It monitors dead letter behavior if configured.
It monitors worker rebalance behavior.
Connect is not just glue.
It is production infrastructure.

```text
+------------------+-------------------------------+
| Signal           | Meaning                       |
+------------------+-------------------------------+
| connector state  | RUNNING, PAUSED, FAILED       |
| task state       | per-task health               |
| source lag       | delay from source database    |
| error rate       | bad records or downstream     |
| worker rebalance | Connect cluster instability   |
+------------------+-------------------------------+
```

---

## 62. Security and Multi-Tenancy

Kafka clusters often serve many teams.
Security is not optional.
TLS encrypts traffic.
SASL authenticates clients.
ACLs authorize operations.
Quotas prevent noisy neighbors.
Topic naming communicates ownership.
Schema governance prevents producer breakage.
Data classification protects sensitive fields.
MegaShop prevents random services from reading payment topics.
MegaShop prevents analytics tools from reading raw PII without approval.
MegaShop limits producers that exceed quotas.
MegaShop classifies topics by criticality and sensitivity.
A shared Kafka cluster without quotas and ACLs is an outage and data leak waiting room.

```text
+-------------+--------------------------------------+
| Control     | Protects                             |
+-------------+--------------------------------------+
| TLS         | traffic confidentiality              |
| SASL        | client identity                      |
| ACLs        | read/write/admin authorization       |
| quotas      | cluster fairness                     |
| schemas     | compatibility                        |
| naming      | ownership and discovery              |
+-------------+--------------------------------------+
```

---

## 63. Topic Classification

Not all topics deserve identical policy.
Payment events are critical.
Order events are critical.
Inventory events are high criticality.
Search projection events are important.
Clickstream events may be lower criticality.
Debug telemetry may be best-effort.
Critical topics get stronger durability.
Critical topics get longer retention.
Critical topics get stricter ACLs.
Critical topics get faster paging.
Critical topics get compatibility gates.
Lower-value topics may accept lower retention and lower severity alerts.
Uniform policy wastes money and hides priority.
MegaShop classifies topics before production.

```text
+----------------------+-------------+-----------+----------------+
| Topic class          | Retention   | Paging    | Durability     |
+----------------------+-------------+-----------+----------------+
| payment/order facts  | long        | urgent    | strict         |
| inventory events     | medium-long | urgent    | strict         |
| search projections   | medium      | high      | normal-strict  |
| clickstream          | short/medium| ticket    | normal         |
| debug telemetry      | short       | best effort| relaxed       |
+----------------------+-------------+-----------+----------------+
```

---

## 64. Capacity Planning

Kafka capacity planning needs rates, sizes, replication, compression, partitions, brokers, and consumers.
Start with producer rate.
Estimate average compressed message size.
Multiply by replication factor.
Estimate retention storage.
Estimate peak burst.
Estimate consumer throughput.
Estimate downstream capacity.
The slowest required sink determines effective progress.
Kafka can accept events faster than OpenSearch can index them.
That creates lag.
Kafka can buffer the lag until retention runs out.
Buffering is not solving.
It is buying time.

```text
average compressed record: 500 bytes
produce rate:              100,000 records/sec
ingress:                   50 MB/sec
replication factor:        3
cluster write volume:      about 150 MB/sec
retention:                 7 days
storage:                   about 90 TB before overhead
```

Capacity review question:
Which downstream system drains the stream the slowest?

---

## 65. Observability Model

Kafka observability has layers.
Broker metrics show cluster health.
Producer metrics show write behavior.
Consumer metrics show processing progress.
Connector metrics show integration health.
Downstream metrics show sink capacity.
Business metrics show user impact.
A lag graph alone is incomplete.
A broker dashboard alone is incomplete.
A DLQ count alone is incomplete.
MegaShop pairs search-indexer lag with OpenSearch p99 and rejection rate.
MegaShop pairs outbox age with connector status.
MegaShop pairs email lag with provider timeout rate.
MegaShop pairs fraud lag with risk decision delay.
The goal is causal diagnosis.
The goal is not dashboard decoration.

```text
+------------+------------------------------+
| Layer      | Example signals              |
+------------+------------------------------+
| Broker     | ISR, disk, request latency   |
| Producer   | error rate, retry rate       |
| Consumer   | lag, processing latency      |
| Connector  | task state, source lag       |
| Downstream | p99, rejections, saturation  |
| Business   | freshness, missed workflow   |
+------------+------------------------------+
```

---

## 66. Broker Metrics

Broker metrics reveal storage and request-path health.
Watch under-replicated partitions.
Watch offline partitions.
Watch ISR shrink rate.
Watch request handler idle percentage.
Watch produce request latency.
Watch fetch request latency.
Watch disk usage.
Watch disk I/O wait.
Watch network throughput.
Watch controller changes.
Watch leader election rate.
Watch quota throttling.
Under-replicated partitions mean safety margin is reduced.
Offline partitions mean clients are impacted.
Produce latency can indicate broker disk, network, quota, or ISR problems.
Fetch latency can affect consumers.
Disk near full is existential.
A Kafka broker without disk is no broker at all.

---

## 67. Producer Metrics

Producer metrics reveal write path health.
Watch record send rate.
Watch record error rate.
Watch retry rate.
Watch request latency.
Watch record queue time.
Watch buffer available bytes.
Watch batch size.
Watch compression ratio.
Watch metadata age.
Watch throttle time.
A rising retry rate can indicate broker trouble.
Rising queue time can indicate broker or network slowness.
Low batch size at high rate can indicate inefficient producer settings.
High throttle time can indicate quota pressure.
Producer errors must be grouped by error class.
A record-too-large error needs schema or limit change.
An authorization error needs ACL fix.
A timeout may need broker diagnosis.

---

## 68. Consumer Metrics

Consumer metrics reveal freshness and processing health.
Watch lag by partition.
Watch lag age.
Watch records consumed per second.
Watch processing latency.
Watch poll latency.
Watch commit latency.
Watch rebalance rate.
Watch assigned partition count.
Watch DLQ rate.
Watch retry rate.
Watch downstream p99.
Watch downstream rejection rate.
Lag without processing latency is incomplete.
Processing latency without downstream metrics is incomplete.
Rebalance rate explains sawtooth lag.
DLQ rate explains permanent failure.
Retry rate explains transient pain.
Lag age explains business freshness.

---

## 69. Command: Describe Topic

Command:

```bash
kafka-topics --bootstrap-server broker:9092 \
  --describe --topic commerce.orders.events.v1
```

Example output:

```text
Topic: commerce.orders.events.v1  PartitionCount: 48  ReplicationFactor: 3
Topic: commerce.orders.events.v1  Partition: 0  Leader: 1  Replicas: 1,2,3  Isr: 1,2,3
Topic: commerce.orders.events.v1  Partition: 1  Leader: 2  Replicas: 2,3,1  Isr: 2,3
Topic: commerce.orders.events.v1  Partition: 2  Leader: 3  Replicas: 3,1,2  Isr: 3,1,2
```

Interpretation:
Partition 1 has replica 1 missing from ISR.
The partition still has a leader.
The partition may still serve reads and writes.
Durability margin is reduced.
If min.insync.replicas=2, acks=all can still succeed because ISR has two replicas.
If another ISR member falls out, writes can fail.
Investigate broker 1 health, disk, network, and replication lag.

---

## 70. Command: Describe Consumer Group

Command:

```bash
kafka-consumer-groups --bootstrap-server broker:9092 \
  --describe --group search-indexer
```

Example output:

```text
TOPIC                       PARTITION CURRENT-OFFSET LOG-END-OFFSET LAG     CONSUMER-ID HOST
commerce.orders.events.v1   0         1000000        1001200        1200    c-1         worker-1
commerce.orders.events.v1   1         900000         1600000        700000  c-2         worker-2
commerce.orders.events.v1   2         999500         1000000        500     c-3         worker-3
```

Interpretation:
Partition 1 dominates lag.
Do not scale blindly.
Check whether worker-2 is slow.
Check logs for repeated offset.
Check key distribution for partition 1.
Check downstream calls from worker-2.
Check whether partition 1 contains a hot key.
Check whether a poison record is blocking progress.

---

## 71. Runbook: All Partitions Lagging

Confirm producer rate.
Confirm consumer progress rate.
Check if lag is growing or shrinking.
Check downstream dependency p99.
Check downstream rejection rate.
Check consumer CPU and memory.
Check consumer error rate.
Check rebalance rate.
Check broker fetch latency.
Check recent consumer deployments.
Check schema errors and DLQ rate.
If downstream is saturated, apply backpressure.
If consumer CPU is saturated and downstream is healthy, scale up to partition count.
If broker fetch latency is high, inspect broker health.
If producer burst is temporary and drain rate exceeds arrival rate, communicate catch-up time.
Do not declare recovery until lag age is back within SLO.

---

## 72. Runbook: One Partition Lagging

Identify lagging partition.
Identify current consumer host for that partition.
Inspect logs for repeated offset.
Inspect key distribution if available.
Check whether one key dominates.
Check processing time for that partition.
Check downstream calls from that consumer.
Check whether the partition has a poison record.
If poison record, quarantine with audit.
If hot key, rollback producer key or cut over to corrected topic.
If slow host, drain or restart carefully.
Do not add consumers blindly.
Do not skip offsets silently.
Do not delete topic data.

---

## 73. Runbook: ISR Shrink

Identify affected topics.
Classify topic criticality.
List affected partitions.
Check broker disk usage.
Check network errors.
Check replication fetcher lag.
Check broker CPU and I/O wait.
Check recent broker restart.
Check rack or zone health.
For critical topics, raise severity if sustained.
If ISR drops below min.insync.replicas, expect acks=all producer failures.
Do not ignore under-replication because clients still appear healthy.
Confirm ISR recovery after mitigation.
Review replica placement if failures are correlated.

---

## 74. Runbook: DLQ Spike

Identify DLQ topic.
Identify producing consumer group.
Group records by error_class.
Group records by schema_version.
Group records by event_type.
Group records by producer version if present.
Sample payloads safely.
Check recent producer deploy.
Check recent consumer deploy.
Determine retryable vs permanent errors.
Pause replay until root cause is understood.
Fix code or data.
Replay with rate limits after validation.
Track re-DLQ rate.
Close incident only after backlog, cause, and prevention are addressed.

---

## 75. Runbook: Connector Lag

Check connector state.
Check task states.
Check source database health.
Check source lag.
Check replication slot retained bytes.
Check connector logs for schema errors.
Check Kafka produce errors.
Check target topic health.
Protect source database first.
If WAL retained bytes threaten disk, escalate as database risk.
Restart connector only if failure mode is understood.
Dropping a replication slot can force re-snapshot.
Re-snapshot can overload the primary.
Communicate projection freshness impact separately from source-of-truth health.

---

## 76. Runbook: Retention Risk

Calculate lag age.
Calculate retention remaining.
Identify consumer groups at risk.
Prioritize critical consumers.
Pause non-critical backfills.
Increase retention temporarily if safe and storage allows.
Scale consumers only if downstream can handle more load.
Consider alternate backfill source.
Communicate risk of unreplayable data.
If data expires, document exact gap.
After incident, adjust retention and lag-age alerting.
A retention miss is a design failure unless explicitly accepted.

---

## 77. Runbook: Producer Error Spike

Group errors by type.
Check authorization errors.
Check record-too-large errors.
Check serialization errors.
Check schema registry errors.
Check not-enough-replicas errors.
Check request timeout errors.
Check broker produce latency.
Check ISR health.
Check quota throttling.
If producer uses outbox, check outbox backlog age.
If producer is direct in request path, check user impact.
Do not drop producer errors silently.
Do not claim order success if durable publication is required and failed.

---

## 78. Failure Mode: Poison Message

A poison message repeatedly fails a consumer.
It can block one partition.
MegaShop search-indexer repeatedly fails at offset 8819231.
Partition 17 lag grows.
Other partitions drain normally.
DLQ may remain empty if the consumer retries in memory forever.
The dangerous response is silent skip.
The correct response is quarantine with audit.
Capture topic, partition, offset, key, headers, payload, schema, error, and consumer version.
Move the record to DLQ or quarantine.
Advance only intentionally.
Fix validation.
Add bounded retries.
Add replay tool.

```text
Partition 17

+---------+---------+---------+---------+
| 8819230 | 8819231 | 8819232 | 8819233 |
+---------+---------+---------+---------+
              ^
              |
          poison record
```

---

## 79. Failure Mode: Downstream Bottleneck

Kafka lag often exposes downstream slowness.
MegaShop search-indexer writes to OpenSearch.
OpenSearch rejects bulk writes.
Consumer lag grows.
Kafka brokers are healthy.
Consumer CPU is moderate.
OpenSearch p99 is high.
OpenSearch write queue is high.
Adding consumers worsens OpenSearch pressure.
The correct response is backpressure.
Pause non-critical consumers.
Throttle catch-up.
Use bulk indexing if not already.
Fix downstream capacity.
Then drain backlog safely.

```text
+-------+      +----------+      +------------+
| Kafka | ---> | Consumer | ---> | OpenSearch |
+-------+      +----------+      +------------+
                                  saturated sink
```

---

## 80. Failure Mode: Rebalance Storm

A rebalance storm repeatedly changes partition ownership.
MegaShop deploy restarts many consumers.
Group rebalances.
Processing pauses.
Lag grows.
Autoscaler sees lag and adds pods.
More pods trigger more rebalances.
Lag grows more.
This is self-inflicted instability.
Mitigation:
Deploy in smaller waves.
Use static membership where useful.
Use cooperative rebalancing where useful.
Avoid lag-only autoscaling.
Limit max.poll.records if processing is too long.
Separate polling from slow downstream writes if needed.
Monitor rebalance rate.
A deploy should not be a scheduled consumption outage.

---

## 81. Failure Mode: Retention Loss

Analytics consumer is down for thirty-six hours.
Topic retention is twenty-four hours.
Kafka deletes older segments.
Consumer cannot replay twelve hours.
If OrdersDB or data lake can backfill, recovery is possible.
If Kafka was the only history, data is lost.
This is not a Kafka bug.
This is a retention design failure.
Prevention:
Set retention from recovery objectives.
Alert on lag age approaching retention.
Test backfill procedures.
Keep authoritative history elsewhere when legally or financially required.

---

## 82. Failure Mode: Schema Drift

Producer adds required field without default.
Old consumers fail.
Producer removes total_cents.
Fraud treats missing amount as zero.
Analytics reports incorrect revenue.
Search may still work.
Different consumers fail differently.
Structural compatibility is not enough.
Semantic compatibility matters.
Prevention:
Use schema compatibility gates.
Use consumer contract tests.
Use staged rollout.
Use versioned handlers.
Do not reuse Protobuf field numbers.
Do not change meaning under same field name.

---

## 83. Failure Mode: DLQ Landfill

Records go to DLQ.
Nobody owns the DLQ.
No replay tool exists.
No dashboard exists.
No retention policy exists.
DLQ grows for weeks.
Main consumer looks healthy.
Business work is still missing.
The system moved failure to another topic.
It did not recover.
Prevention:
DLQ ownership.
DLQ alerting.
DLQ classification.
DLQ replay process.
DLQ cleanup policy.
DLQ business severity mapping.

---

## 84. Failure Mode: Primary Database Threatened by CDC

Debezium connector stops.
PostgreSQL replication slot retains WAL.
Disk usage grows.
OrdersDB primary approaches full disk.
Checkout is at risk.
The Kafka integration has become a database availability incident.
Protect source of truth first.
Restart connector if safe.
Increase disk if needed.
Avoid dropping slot unless re-snapshot impact is understood.
Throttle writes only if business continuity requires it.
Communicate that order authority differs from downstream projection lag.

---

## 85. Full Incident: MegaShop Sneaker Launch

Severity is P1.
Event is celebrity sneaker launch.
Topic is commerce.orders.events.v1.
Partitions are 48.
Replication factor is 3.
min.insync.replicas is 2.
Baseline produce rate is 8,000 records/sec.
Current produce rate is 55,000 records/sec.
Fraud lag is 80,000 and stable.
Inventory lag is 9,200,000 and growing.
Search lag is 31,000,000 and growing.
Email lag is 4,800,000 and growing.
Rebalance rate is 140 per hour.
DLQ rate is low.
Partition 05 has 8,900,000 lag.
Other sampled partitions have around 20,000 lag.
Recent producer change switched key from order_id to product_id.
Launch product_id is SNKR-2026.
Consumers autoscaled from 24 to 96.
Search writes one document at a time to OpenSearch.
Email retries immediately on provider timeout.

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

---

## 86. Incident Diagnosis

The primary root cause is partition-key change.
Key changed from order_id to product_id.
During launch, most events share product_id SNKR-2026.
Those events hash to one partition.
One partition has one active owner per group.
Adding consumers cannot split one partition.
Inventory lag grows because its hot partition cannot drain.
Search lag is worse because OpenSearch writes are inefficient.
Email lag is amplified by immediate retries during provider timeout.
Low DLQ rate means records are not mostly permanently malformed.
High rebalance rate means autoscaling or deploy churn is worsening stability.
Kafka may be healthy as infrastructure.
The Kafka-backed pipeline is unhealthy as a business system.
Correct diagnosis links key choice, per-partition lag, consumer group semantics, downstream capacity, and retry policy.

---

## 87. Incident Mitigation

Stop autoscaling churn.
Freeze non-essential deploys.
Confirm per-partition lag.
Identify hot keys if tooling allows.
Roll back producer key to order_id if safe.
If rollback cannot safely mix ordering, cut over new records to corrected topic.
Prioritize fraud and inventory consumers.
Throttle search indexing.
Switch search to bulk writes if safe.
Add email retry backoff with jitter.
Preserve all records.
Do not delete topic data.
Do not skip offsets silently.
Do not increase partitions in panic without migration plan.
Do not trust stale projections for checkout correctness.
Communicate order authority separately from projection freshness.

---

## 88. Incident Recovery Validation

Recovery is not just lower lag.
Recovery requires lag age within SLO.
Fraud freshness must be acceptable.
Inventory projection must be caught up or authority must bypass projection.
Search freshness must meet product requirements.
Email backlog must drain or customer communication must be clear.
DLQ must be stable and classified.
Rebalance rate must return to baseline.
OpenSearch p99 and rejection rate must normalize.
Outbox age must normalize.
No data gaps should exist.
If offsets were skipped with audit, business impact must be documented.
If records expired, the exact window must be documented.
Recovery ends when business correctness and freshness are restored.

---

## 89. Incident Prevention

Partition-key changes require architecture review.
Flash-sale hot-key testing must exist.
Per-partition lag alerting must exist.
Lag-age alerting must exist.
Autoscaling must include rebalance rate and downstream capacity.
Search indexing must use bulk writes and backpressure.
Email retries must use bounded exponential backoff with jitter.
Critical consumers need protected capacity.
Schema changes must pass compatibility gates.
DLQ replay tooling must be tested.
Retention must exceed recovery objectives.
Post-incident review must create engineering controls.
A postmortem that only says monitor more is weak.

---

## 90. Kafka vs SQS

SQS is a managed task queue.
It is excellent when one job should go to one worker.
It has visibility timeout.
It has DLQ redrive policies.
It has simple operational burden.
It is not a durable event log for many independent replaying consumers.
Kafka is strong when many consumers need retained history.
Kafka is strong when replay matters.
Kafka is strong when high-throughput fanout matters.
Kafka is strong when per-key ordering matters.
MegaShop receipt email can use SQS.
MegaShop order history fanout can use Kafka.
Using Kafka for every background job is unnecessary operational tax.
Using SQS as the main event-history backbone is semantic mismatch.

```text
+----------------------+------------------+
| Requirement          | Better fit       |
+----------------------+------------------+
| one worker per job   | SQS              |
| simple managed retry | SQS              |
| replayable history   | Kafka            |
| many consumer groups | Kafka            |
| per-key ordering log | Kafka            |
+----------------------+------------------+
```

---

## 91. Kafka vs RabbitMQ

RabbitMQ is strong for routing-heavy work queues.
It has exchanges, queues, and bindings.
It can route by topic patterns.
It is useful for command-style work distribution.
It is not primarily a long-retention replay log.
Huge backlogs can hurt broker performance.
Kafka is stronger for retained high-throughput event history.
MegaShop might use RabbitMQ for seller workflow routing.
MegaShop might use Kafka for order event history.
The choice depends on semantics.
RabbitMQ asks how to route this message to queues.
Kafka asks how to append this record to a partitioned log.

```text
+----------+      +----------+      +---------+
| Producer | ---> | Exchange | ---> | Queue A |
+----------+      +----------+      +---------+
                       |
                       +------->    +---------+
                                    | Queue B |
                                    +---------+
```

---

## 92. Kafka vs Redis Streams

Redis Streams can support stream-like workloads.
They can be useful when Redis is already operated and the workload is modest.
They are not a casual replacement for Kafka as a company-wide event backbone.
Redis persistence, memory, replication, failover, and retention must be evaluated.
Kafka is designed for durable high-throughput logs with many consumers and long retention.
Redis Streams may be simpler for localized workloads.
MegaShop might use Redis Streams for small internal coordination flows.
MegaShop should not put core order event history on Redis Streams without strong justification.
Fast is not the same as durable.
Nearby is not the same as correct.

---

## 93. Kafka vs NATS

NATS is strong for low-latency messaging and subject-based communication.
Core NATS is often used for lightweight messaging.
JetStream adds persistence.
NATS can be excellent for control-plane events and request-reply patterns.
Kafka can be better for retained event history and large replay workloads.
MegaShop might use NATS for low-latency internal control messages.
MegaShop might use Kafka for order events.
The question is durability mode, replay need, ordering, fanout, and operations.
Do not compare slogans.
Compare guarantees.

---

## 94. Kafka vs Kinesis

Kinesis is an AWS-managed shard-based stream.
A shard has throughput limits.
Partition key determines shard placement.
Hot keys can create hot shards.
Consumers read from shards.
Retention is configurable.
Operational burden is different from self-managed Kafka.
Kafka has a broad ecosystem and deployment flexibility.
Kinesis integrates deeply with AWS.
MegaShop on AWS might use Kinesis for managed streaming.
MegaShop might use Kafka for ecosystem, portability, or existing platform reasons.
The same architecture questions remain.
What is the key.
What ordering is required.
What lag is acceptable.
What replay is needed.
What happens under hot key.

---

## 95. Design Review: Topic

Every production topic needs review.
What business fact does the topic represent.
Is it event, command, or job.
Who owns it.
Who produces to it.
Who consumes from it.
Which consumers are critical.
What schema format is used.
What compatibility mode is enforced.
What partition key is used.
What ordering is promised.
What ordering is not promised.
What hot-key cases exist.
What partition count is chosen.
What retention is chosen.
What cleanup policy is chosen.
What replication factor is chosen.
What min.insync.replicas is chosen.
What ACLs apply.
What PII exists.
What dashboards exist.
What alerts exist.
What runbook exists.
No topic should enter production as a nameless pipe.

---

## 96. Design Review: Producer

A production producer review asks what happens when Kafka write fails.
It asks whether outbox is required.
It asks how event_id is generated.
It asks what key is used.
It asks whether key choice preserves required ordering.
It asks whether hot-key cases are tested.
It asks what acks setting is used.
It asks whether idempotence is enabled.
It asks how schema compatibility is checked.
It asks how producer errors are observed.
It asks whether user success can be returned before durable publish.
It asks whether retries can create duplicates.
It asks whether event publication is part of the critical path.
MegaShop checkout producer uses outbox for authoritative order events.
Telemetry producers may use direct publish.
The consequence decides the mechanism.

---

## 97. Design Review: Consumer

A production consumer review asks what side effect occurs.
It asks whether the side effect is idempotent.
It asks what idempotency key protects it.
It asks when offsets are committed.
It asks whether auto commit is disabled.
It asks which errors are retryable.
It asks which errors go to DLQ.
It asks what DLQ context is preserved.
It asks whether replay is safe.
It asks what downstream dependency can bottleneck.
It asks how backpressure works.
It asks what lag SLO exists.
It asks how deploys avoid rebalance storms.
It asks what runbook exists.
A consumer that cannot answer these is not production-ready.

---

## 98. Event Taxonomy

Events are facts.
Commands are requests.
Jobs are units of work.
OrderPlaced is an event.
PaymentCaptured is an event.
InventoryReserved is an event.
ReserveInventory is a command.
SendReceiptEmail is a job or command.
OrderUpdated is usually too vague.
A good event name tells what happened.
A weak event name makes every consumer decode meaning from fields.
MegaShop prefers domain events for business facts.
CDC row changes can be useful but are not automatically domain events.
A row update says data changed.
A domain event says why it changed.
Consumers need meaning.

---

## 99. Event Envelope Standard

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
This consistency enables generic tooling.
DLQ tooling can extract event_id.
Replay tooling can preserve aggregate_id.
Tracing can follow correlation_id.
Schema handlers can inspect schema_version.
Without envelope consistency, every consumer invents its own archaeology kit.

```text
+----------------+------------------------------+
| Envelope field | Tooling benefit              |
+----------------+------------------------------+
| event_id       | dedupe, replay, DLQ          |
| schema_version | compatibility dispatch       |
| aggregate_id   | partitioning and ordering    |
| correlation_id | tracing                      |
| causation_id   | workflow causality           |
+----------------+------------------------------+
```

---

## 100. Interview Framework

Do not start by saying use Kafka.
Start with the workflow.
Identify source of truth.
Identify events.
Identify commands.
Identify consumers.
Identify critical path.
Identify side effects.
Identify ordering requirements.
Identify duplicate behavior.
Identify retention and replay needs.
Identify schema evolution.
Identify DLQ and retry policy.
Identify observability.
Identify operational risks.
Then decide whether Kafka fits.
A principal-level answer says Kafka is justified when replay, fanout, throughput, and per-key ordering are worth the operational cost.
A weak answer says Kafka because it scales.
Scale is not a requirement until quantified.

---

## 101. Production Readiness Checklist

1. Topic owner documented.
2. Producer owner documented.
3. Consumer owners documented.
4. Event schema versioned.
5. Compatibility gate exists.
6. Partition key reviewed.
7. Hot-key test performed.
8. Retention tied to recovery objective.
9. Replication factor documented.
10. min.insync.replicas documented.
11. Producer acks documented.
12. Outbox decision documented.
13. Idempotency per consumer documented.
14. Offset commit policy documented.
15. Retry policy documented.
16. DLQ owner documented.
17. Replay process tested.
18. Lag-age alert exists.
19. Per-partition lag dashboard exists.
20. Downstream p99 dashboard exists.
21. Connector lag dashboard exists if CDC is used.
22. Security ACLs reviewed.
23. Quotas reviewed.
24. PII classification reviewed.
25. Incident runbook exists.

---

## 102. Anti-Patterns

Kafka for every background job is an anti-pattern.
Random partition key for ordered workflows is an anti-pattern.
product_id key during flash-sale order lifecycle is an anti-pattern.
Auto commit with external side effects is an anti-pattern.
DLQ without replay process is an anti-pattern.
Retention shorter than recovery objective is an anti-pattern.
Schema changes without consumer compatibility are anti-patterns.
Lag-only autoscaling is an anti-pattern.
Ignoring downstream capacity is an anti-pattern.
Silent offset skip is an anti-pattern.
Trusting search projection as order authority is an anti-pattern.
No idempotency key is an anti-pattern.
No correlation_id is an anti-pattern.
No topic owner is an anti-pattern.
No quota in shared Kafka is an anti-pattern.
No outbox for authoritative events is often an anti-pattern.
No replay-safe mode is an anti-pattern.

---

## 103. Scenario Questions

1. Checkout succeeds but search does not show new orders. Identify authority, likely async failure points, and safe customer communication.
2. A payment provider times out after the consumer sends capture request. Explain why blind retry is unsafe and how idempotency plus reconciliation helps.
3. One partition has 95 percent of inventory-projector lag. Explain hot key versus poison message diagnosis.
4. Producer switched key from order_id to product_id before a flash sale. Explain failure mechanism and mitigation.
5. DLQ grows after producer schema deploy. Explain triage order.
6. Outbox backlog age rises but Kafka consumer lag is zero. Explain where the pipeline is stuck.
7. Kafka consumer lag rises and OpenSearch p99 spikes. Explain why adding consumers may worsen the incident.
8. ISR shrinks on order-events. Explain why clients may still work while durability margin is reduced.
9. A new consumer group starts at latest and misses historical order events. Explain auto.offset.reset risk.
10. Analytics consumer is down beyond retention. Explain recovery options and what cannot be recovered from Kafka.
11. A deploy triggers repeated rebalances. Explain max.poll.interval.ms and deployment-wave mitigation.
12. A compacted topic is used for payment history. Explain why this is dangerous.
13. A producer removes a field used only by fraud. Explain hidden coupling in pub/sub.
14. A team wants Kafka for sending one welcome email. Explain why SQS may be better.
15. A team claims Kafka exactly-once solves duplicate payments. Explain scope.

---

## 104. Scenario Answer: Search Projection Stale

OrdersDB is authoritative for order existence.
Search is a projection.
Checkout can be correct while search is stale.
Check outbox backlog first.
Check connector lag second.
Check Kafka consumer lag for search-indexer third.
Check OpenSearch p99 and rejection rate fourth.
Do not tell customers orders are missing if OrdersDB is correct.
Communicate search freshness delay.
Protect checkout and order authority.
Backfill search at controlled rate after sink is healthy.
Verify by comparing OrdersDB count versus indexed document count for affected interval.

---

## 105. Scenario Answer: Payment Timeout

Timeout is ambiguous.
The provider may have captured payment.
The provider may have rejected payment.
The response may have been lost.
Blind retry can double charge.
Use stable provider idempotency key.
Query provider by transaction reference.
Move internal workflow to PAYMENT_UNKNOWN or RECONCILING.
Ledger writes must use unique event_id.
Customer communication must avoid false finality.
Reconciliation closes the loop.
Kafka does not solve provider ambiguity by itself.

---

## 106. Scenario Answer: One Partition Lagging

One partition lagging suggests hot key, poison record, or slow owner.
Run consumer group describe.
Identify partition and host.
Inspect logs for repeated offset.
Inspect key distribution if tooling exists.
Compare downstream latency from that host.
If repeated offset, quarantine poison record with audit.
If hot key, rollback producer key or cut over to corrected topic.
Do not scale consumers blindly.
Do not skip offsets silently.
Do not delete topic data.

---

## 107. Scenario Answer: Schema Break

Treat event schema as API contract.
Group failures by schema_version and error_class.
Check producer deploy time.
Check critical consumers.
Roll back producer if breaking.
Add optional fields first.
Support old and new fields during migration.
Use schema compatibility gates.
Use consumer contract tests.
Do not change semantic meaning under same field name.
Replay DLQ only after consumer fix.

---

## 108. Scenario Answer: Retention Miss

Kafka cannot replay records already deleted by retention.
Find another source of truth.
OrdersDB may backfill order facts.
Payment ledger may backfill payment facts.
Data lake may have copied events.
If no source exists, document data gap.
Increase retention based on detection and recovery time.
Alert on lag age approaching retention.
Test backfill procedure before relying on it.
Retention is part of recovery design.

---

## 109. Scenario Answer: Rebalance Storm

Rebalance storm means partition ownership changes repeatedly.
Check rebalance rate.
Check deploy timing.
Check autoscaler events.
Check max.poll.interval.ms violations.
Check processing time per batch.
Mitigate with smaller deploy waves.
Use static membership where appropriate.
Use cooperative rebalancing where appropriate.
Reduce max.poll.records if batch processing is too long.
Do not autoscale on lag alone.

---

## 110. Scenario Answer: Kafka vs SQS

Receipt email is one job for one worker.
SQS is often a better fit.
Order history replay requires retained log and many independent consumers.
Kafka is a better fit.
Kafka should be chosen for replay, fanout, throughput, and per-key ordering.
SQS should be chosen for simple managed job distribution.
The principal answer chooses by semantics.
It does not choose by resume keywords.

---

## 111. Dense Glossary

Acknowledgement means a broker or worker reports acceptance or completion.
Aggregate means a domain entity whose events may require ordering.
Backpressure means slowing work to protect downstream capacity.
Broker means a Kafka server.
Cleanup policy controls delete or compact retention behavior.
Compaction keeps latest value per key eventually.
Consumer means a client that reads records.
Consumer group means consumers sharing partition ownership and offsets.
Correlation ID links events to a workflow.
Causation ID explains why an event exists.
DLQ stores failed records after bounded attempts.
Durable log stores replayable history.
Event means a fact that happened.
Follower means replica copying from leader.
Group coordinator manages consumer group membership.
Idempotency means repeated operation has same final business result.
ISR means in-sync replicas.
Lag means distance from log end to committed offset.
Lag age means time distance from newest business event.
Leader means replica handling writes for a partition.
Offset means position inside a partition.
Outbox means local table for atomic state plus event intent.
Partition means ordered shard.
Partition key means value used for partition choice and ordering scope.
Producer means client writing records.
Projection means derived view.
Rebalance means changing partition ownership.
Replication factor means number of copies.
Retention means record lifetime policy.
Schema evolution means safe change to event structure.
Task queue means one job to one worker.
Tombstone means null value used for deletion in compacted topics.
Transactional ID identifies transactional producer state.
Visibility timeout means task queue hidden window after receive.

---

## 112. Final Mental Model

Messaging is not a performance trick.
Messaging is a correctness and operations boundary.
Task queues distribute jobs.
Pub/sub distributes reactions.
Durable logs preserve replayable history.
Kafka is powerful because it combines retained history, partitioned ordering, high throughput, replication, and independent consumer groups.
Kafka is dangerous because those same properties create lag, replay risk, ordering traps, schema coupling, and operational burden.
The partition key is both correctness and capacity design.
Offsets are progress markers, not business truth.
Consumer lag is delayed business work.
DLQ is evidence, not recovery by itself.
Outbox protects database state and event publication from divergence.
CDC connects source truth to event streams but can threaten the source if neglected.
Exactly-once must always state scope.
The best Kafka designs are boring in incidents.
They are boring because authority is clear.
They are boring because duplicates are expected.
They are boring because lag is measured.
They are boring because replay is controlled.
They are boring because schemas are governed.
That kind of boring is production excellence.
