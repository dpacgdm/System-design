# Week 6, Topic 2: Event-Driven Architecture

Last verified: 2026-05-15

Event-driven architecture is a way of building systems around durable facts that
happened. Instead of every service asking every other service to do work inside
one synchronous request, a service records a business fact and other services
react to that fact.

The promise:

```text
looser coupling
shorter critical paths
independent consumers
replayable workflows
```

The price:

```text
eventual consistency
duplicate delivery
schema governance
consumer lag
harder debugging
replay safety
```

If the system cannot tolerate delayed or repeated processing, event-driven
design must be narrowed or combined with synchronous correctness checks.

---

## 1. Learning objectives

```text
After this topic, you should be able to:

1. Distinguish events, commands, queries, messages, notifications, and CDC rows.
2. Design event payloads with IDs, timestamps, versions, correlation, and causation.
3. Compare event notification, event-carried state transfer, event sourcing, and CQRS.
4. Choose choreography or orchestration for multi-service workflows.
5. Explain how async boundaries affect consistency, latency, and availability.
6. Diagnose stale read models, duplicate events, ghost consumers, schema drift,
   replay damage, and event storms.
7. Build incident response around authoritative state, not stale projections.
```

---

## 2. What people get wrong

### Wrong model 1: events are async commands

A command asks for an action.

```text
ReserveInventory
CapturePayment
SendEmail
```

An event states that something already happened.

```text
InventoryReserved
PaymentCaptured
EmailRequested
```

If the message says `CreateInvoice`, it is probably a command. If it says
`InvoiceCreated`, it is an event.

This distinction matters because events are facts. Consumers should not decide
whether the fact is true; they decide how to react.

### Wrong model 2: event-driven means no coupling

Event-driven systems still have coupling. It moves into:

```text
schema contracts
event names
ordering expectations
consumer assumptions
retention windows
idempotency rules
business workflows
```

Hidden coupling is worse than explicit coupling because it fails later and
farther away.

### Wrong model 3: eventual consistency is harmless

Eventual consistency is a product decision.

Safe examples:

```text
recommendation updates
analytics dashboards
search index freshness
email delivery
```

Dangerous examples:

```text
payment balance
inventory reservation during checkout
fraud hold
medical allergy record
account permission changes
```

### Wrong model 4: replay is always safe

Replay re-runs history. That is powerful only when consumers are designed for it.

Unsafe replay can:

```text
send duplicate emails
charge customers twice
ship duplicate packages
overwrite corrected data with old state
trigger webhooks again
```

---

## 3. Event anatomy

A production event should carry identity, context, and versioning.

```text
event_id:        evt_01J7...
event_type:      OrderPlaced
schema_version:  3
aggregate_type:  Order
aggregate_id:    ord_123
occurred_at:     2026-05-15T10:15:30Z
published_at:    2026-05-15T10:15:31Z
correlation_id:  req_abc
causation_id:    cmd_xyz
traceparent:     00-...
producer:        checkout-service
payload:         business data
```

Why each field matters:

```text
event_id:
  dedupe and audit

aggregate_id:
  ordering and routing

schema_version:
  compatibility

occurred_at:
  business time

published_at:
  pipeline delay

correlation_id:
  trace a user workflow

causation_id:
  explain why this event exists
```

Clean event flow:

```text
+----------+      +------------+      +---------+
| Command  | ---> | Service DB | ---> | Event   |
+----------+      +------------+      +---------+
                                      happened
```

---

## 4. Events, commands, queries, and CDC

```text
+--------------+---------------------------+-------------------------+
| Type         | Meaning                   | Example                 |
+--------------+---------------------------+-------------------------+
| Command      | please do this            | CapturePayment          |
| Event        | this happened             | PaymentCaptured         |
| Query        | tell me current state     | GetOrderStatus          |
| Notification | something may interest you| OrderChanged            |
| CDC record   | database row changed      | orders row updated      |
+--------------+---------------------------+-------------------------+
```

CDC is not automatically a business event.

```text
CDC:
  column status changed from PENDING to PAID

Business event:
  PaymentCaptured for order ord_123
```

CDC is excellent for moving committed database changes. Business events are
better for describing domain meaning.

---

## 5. Event notification

Event notification sends a small event that tells consumers something changed.

```text
+--------+      +---------+      +----------+
| Orders | ---> | Event   | ---> | Consumer |
+--------+      +---------+      +----------+

Event:
  OrderPlaced { order_id: ord_123 }
```

Consumer fetches details if needed.

Strengths:

```text
small payloads
less duplicated data
consumers fetch freshest details
```

Problems:

```text
extra read load on source service
source service becomes dependency during processing
replay can hammer source APIs
consumer result depends on current state, not event-time state
```

Use when consumers need only a signal or can safely fetch current state.

---

## 6. Event-carried state transfer

The event includes enough state for consumers to update their own models.

```text
OrderPlaced {
  order_id: ord_123,
  customer_id: cust_7,
  total_cents: 129900,
  items: [...]
}
```

Flow:

```text
+--------+      +------------------+      +-------------+
| Orders | ---> | OrderPlaced data | ---> | SearchIndex |
+--------+      +------------------+      +-------------+
```

Strengths:

```text
consumers do not call source service
better replay throughput
source service isolated
```

Problems:

```text
larger payloads
schema evolution harder
PII may spread
consumers may store stale copies
```

Use when read models need reliable reconstruction and source-service fanout
would be dangerous.

---

## 7. Event sourcing

Event sourcing stores state as a sequence of events.

```text
Account stream

+----------------+----------------+----------------+
| AccountOpened  | MoneyDeposited | MoneyWithdrawn |
+----------------+----------------+----------------+
```

Current state is derived by replaying events.

```text
balance = 0
AccountOpened      -> balance = 0
MoneyDeposited 100 -> balance = 100
MoneyWithdrawn 30  -> balance = 70
```

Strengths:

```text
full audit history
replayable state
temporal debugging
natural for ledgers and workflows
```

Problems:

```text
schema evolution over all history
replay cost
event immutability discipline
hard deletes and privacy requirements
consumer projection bugs
```

Event sourcing is not required for event-driven architecture. Most systems use
normal databases plus emitted events or outbox/CDC.

---

## 8. CQRS with events

CQRS separates write model and read model.

```text
Write side

+-----+      +----------+
| API | ---> | OrdersDB |
+-----+      +----------+
                 |
                 | events
                 v
              +-------+
              | Kafka |
              +-------+
                 |
                 v
Read side     +-------------+
              | SearchIndex |
              +-------------+
```

This helps when the write model is normalized and correct, while the read path
needs fast denormalized views.

Tradeoff:

```text
Writes are authoritative immediately.
Reads from projections are eventually consistent.
```

Critical rule:

```text
Do not use stale projections for decisions requiring fresh authority.
```

Example:

```text
Search page can show stale product data briefly.
Checkout must verify current price and inventory against authoritative systems.
```

---

## 9. Choreography vs orchestration

### Choreography

Services react to each other's events.

```text
+--------+   OrderPlaced   +-----------+
| Orders | --------------> | Inventory |
+--------+                 +-----------+
                                  |
                                  | InventoryReserved
                                  v
                              +---------+
                              | Payment |
                              +---------+
```

Strengths:

```text
loose central control
services autonomous
natural event flow
```

Problems:

```text
workflow hidden across services
cycles are easy
incident diagnosis is harder
ownership can blur
```

### Orchestration

A coordinator owns workflow state.

```text
+--------------+
| Orchestrator |
+--------------+
   |      |      |
   v      v      v
Orders Inventory Payment
```

Strengths:

```text
clear workflow state
central timeout policy
easier recovery
better for complex business workflows
```

Problems:

```text
coordinator is critical
workflow logic centralizes
can become a mini-monolith
```

Use orchestration when the workflow is long-running, customer-visible, or needs
explicit compensation.

---

## 10. Production failure patterns

### Failure 1: stale read model

Shape:

```text
+----------+      +-------+      +-------------+
| OrdersDB | ---> | Kafka | ---> | SearchIndex |
+----------+      +-------+      +-------------+
                     lag             stale
```

Symptoms:

```text
orders exist in primary DB
search does not show them
consumer lag rising
support reports missing records
API writes look healthy
```

Mitigation:

```text
1. Declare source of truth.
2. Protect write path if healthy.
3. Communicate projection freshness issue.
4. Check consumer lag and downstream bottleneck.
5. Rebuild or replay projection only at safe rate.
```

### Failure 2: duplicate event causes duplicate side effect

Example:

```text
PaymentCaptured delivered twice
Email consumer sends two receipts
```

Worse:

```text
PaymentCaptureRequested delivered twice
Payment consumer charges twice
```

Mitigation:

```text
idempotency keys
processed_events table
unique business constraints
external provider idempotency
reconciliation jobs
```

### Failure 3: schema drift

Symptoms:

```text
producer deploy succeeds
consumer deserialization errors rise
DLQ fills with one schema version
lag grows across partitions
```

Mitigation:

```text
schema registry compatibility
consumer-driven contract tests
additive fields before required fields
no meaning changes under same field name
versioned event types when semantics change
```

### Failure 4: replay damage

Unsafe consumer:

```text
on OrderPlaced:
  send email
```

Replay result:

```text
old customers receive duplicate emails
```

Safer consumer:

```text
on OrderPlaced:
  if notification(order_id, type) not sent:
    send email
    record sent marker
```

### Failure 5: event storm

One user action emits too many downstream events.

```text
ProfileUpdated
  -> SearchUpdated
  -> RecommendationInvalidated
  -> FeedInvalidated
  -> CachePurged
  -> AuditLogged
  -> MetricsUpdated
```

If every consumer emits more events, the system becomes a popcorn machine in a
server rack.

Mitigation:

```text
bounded fanout
event taxonomy
consumer ownership
rate limits
batch invalidations
```

---

## 11. SRE diagnostic toolkit

Trace a workflow by correlation ID:

```text
request_id=req_123
correlation_id=req_123
causation_id=cmd_456
```

Kafka lag:

```bash
kafka-consumer-groups --bootstrap-server broker:9092 \
  --describe --group search-indexer
```

Outbox backlog:

```sql
SELECT count(*)
FROM outbox_events
WHERE created_at < now() - interval '5 minutes';
```

Projection freshness:

```text
max(source.updated_at) - max(projection.updated_at)
```

Signals to dashboard:

```text
event publish rate
consumer lag by group
consumer lag age
DLQ rate
schema error rate
duplicate event rate
projection freshness
end-to-end workflow duration
```

---

## 12. Decision framework

```text
+------------------------------+-------------------------------+
| Need                         | Pattern                       |
+------------------------------+-------------------------------+
| Notify others something happened | event notification        |
| Rebuild read model without source calls | event-carried state |
| Full audit state from history | event sourcing                |
| Complex workflow with compensation | orchestration saga        |
| Simple independent reactions | choreography                  |
| Strong immediate decision    | synchronous command/query     |
+------------------------------+-------------------------------+
```

Ask:

```text
Is this event a fact or a command?
Who owns the schema?
What ordering is required?
How much lag is acceptable?
Can consumers process duplicates?
Can this be replayed safely?
Which state is authoritative during incidents?
```

---

## 13. Incident scenario: checkout confirmation gap

Architecture:

```text
+----------+      +----------+      +--------+
| Checkout | ---> | OrdersDB | ---> | Outbox |
+----------+      +----------+      +--------+
                                      |
                                      v
                                  +-------+
                                  | Kafka |
                                  +-------+
                                  |   |   |
                                  v   v   v
                               Email Search Analytics
```

Symptoms:

```text
checkout success rate:       99.3%
order rows in DB:            normal
email confirmations:         delayed 45 minutes
search index freshness:      delayed 30 minutes
email-consumer lag:          12M records
search-consumer lag:         8M records
analytics lag:               90M records
DLQ:                         low
```

Recent change:

```text
analytics consumer began calling a slow enrichment API
all consumers share the same downstream PostgreSQL read replica for enrichment
replica lag rose to 20 minutes
```

Expert diagnosis:

```text
The authoritative write path is healthy. Async consumers are bottlenecked by a
shared enrichment dependency. The incident is a freshness and notification delay,
not order loss.
```

Mitigation:

```text
1. Preserve checkout write path.
2. Disable or degrade analytics enrichment.
3. Give email and search priority over analytics.
4. Stop replay/backfill jobs competing for the same replica.
5. Communicate delayed confirmation clearly.
6. Add per-consumer dependency isolation.
```

Long-term fixes:

```text
separate enrichment pools
consumer priority classes
projection freshness SLOs
idempotent notification send markers
schema and replay tests
```

---

## 14. Key takeaways

```text
1. Events are facts; commands request actions.
2. Event-driven architecture moves coupling into schemas and workflows.
3. Async boundaries create lag, duplicates, and replay risk.
4. Read models are projections, not authority.
5. Choreography spreads control; orchestration centralizes workflow state.
6. Replay is useful only when consumers are replay-safe.
7. Every important event needs identity, versioning, and trace context.
8. During incidents, first identify the authoritative state.
```

---

## 15. Targeted reading

```text
Designing Data-Intensive Applications:
  Chapter 11: Stream Processing
  Chapter 5: Replication

Enterprise Integration Patterns:
  Message, Command Message, Event Message, Message Channel

Microservices.io:
  Event-driven architecture
  Saga pattern
  Transactional outbox
```
