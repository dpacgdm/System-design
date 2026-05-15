# Week 6, Topic 6: Outbox Pattern and CDC

Last verified: 2026-05-15

The outbox pattern solves one of the most common reliability bugs in distributed systems: writing state to a database and publishing a message as two separate actions.

If those two actions are not atomic, the system can lie.

```text
Database says order exists.
Kafka has no OrderCreated event.
```

Or:

```text
Kafka says order exists.
Database rolled back.
```

The outbox pattern makes the database transaction the source of truth, then uses CDC or a relay to publish committed facts.

---

## 1. Learning objectives

```text
After this topic, you should be able to:

1. Explain the dual-write problem.
2. Design an outbox table and transactional write path.
3. Explain CDC, replication slots, connectors, and event relays.
4. Distinguish database row changes from business events.
5. Diagnose connector lag, WAL retention, duplicate publishing, schema drift,
   and replay hazards.
6. Build idempotent consumers for outbox-driven events.
7. Decide when outbox is needed and when simpler polling is enough.
```

---

## 2. The dual-write problem

Bad pattern:

```text
1. Write order to database.
2. Publish OrderCreated to Kafka.
```

Failure case A:

```text
DB commit succeeds.
Kafka publish fails.

Result:
  order exists
  no event exists
  search, email, fraud, analytics never hear about it
```

Failure case B:

```text
Kafka publish succeeds.
DB transaction rolls back.

Result:
  event exists
  order does not
  consumers react to a lie
```

Failure case C:

```text
DB commit succeeds.
Kafka publish succeeds.
App times out before seeing success.
Client retries.

Result:
  duplicates unless idempotency exists
```

The problem is not Kafka. The problem is trying to atomically update two independent systems without a protocol.

---

## 3. Outbox core model

Write business row and outbox row in the same local database transaction.

```text
+---------+        one DB transaction        +---------------+
| orders  | <------------------------------> | outbox_events |
+---------+                                  +---------------+
                                                    |
                                                    | CDC or relay
                                                    v
                                                +-------+
                                                | Kafka |
                                                +-------+
```

SQL shape:

```sql
BEGIN;

INSERT INTO orders(id, customer_id, status, total_cents)
VALUES ('ord_123', 'cust_7', 'created', 129900);

INSERT INTO outbox_events(
  event_id,
  aggregate_type,
  aggregate_id,
  event_type,
  schema_version,
  payload,
  created_at
)
VALUES (
  'evt_123',
  'Order',
  'ord_123',
  'OrderCreated',
  1,
  '{"order_id":"ord_123","customer_id":"cust_7","total_cents":129900}',
  now()
);

COMMIT;
```

If the transaction commits, both rows exist. If it rolls back, neither exists.

The publish step becomes asynchronous and retryable.

---

## 4. Outbox table design

Minimal shape:

```text
event_id
aggregate_type
aggregate_id
event_type
schema_version
payload
created_at
```

Useful production shape:

```text
event_id              unique identifier for dedupe
aggregate_type        Order, Payment, Customer
aggregate_id          ord_123
sequence              per-aggregate ordering if needed
event_type            OrderCreated
schema_version        payload contract version
payload               event body
headers               trace/correlation metadata
created_at            DB transaction time
published_at          optional relay marker
publish_attempts      relay retry tracking
last_publish_error    relay debugging
```

Key design rules:

```text
- event_id must be globally unique
- aggregate_id should align with ordering needs
- payload should be versioned
- outbox cleanup must be planned
- consumers must still be idempotent
```

---

## 5. CDC vs polling relay

### Polling relay

```text
+-------------+      SELECT unpublished       +---------------+
| Relay       | ----------------------------> | outbox_events |
+-------------+                               +---------------+
      |
      | publish
      v
   +-------+
   | Kafka |
   +-------+
```

Strengths:

```text
simple to understand
works without database log access
easy for low volume
```

Problems:

```text
polling load
locking and batching complexity
published_at update creates write load
ordering can be tricky
relay crashes can duplicate publishes
```

### CDC relay

```text
+----------+      WAL/binlog       +-----------+      +-------+
| Database | --------------------> | Connector | ---> | Kafka |
+----------+                       +-----------+      +-------+
```

Strengths:

```text
reads committed database log
less polling load
natural integration with Debezium-style pipelines
preserves commit order within limits
```

Problems:

```text
connector lag
replication slot WAL retention
schema-change coordination
operational complexity
```

---

## 6. CDC is not automatically a business event

CDC row change:

```text
orders.status changed from pending to paid
```

Business event:

```text
PaymentCaptured
```

CDC tells you what changed. A business event tells you what it means.

Outbox lets the application write a business event as data, and CDC transports it reliably.

---

## 7. Ordering

Ordering is usually needed per aggregate, not globally.

```text
Order ord_123:
  OrderCreated -> PaymentCaptured -> Shipped
```

Outbox can include a per-aggregate sequence:

```text
aggregate_id: ord_123
sequence: 1  OrderCreated
sequence: 2  PaymentCaptured
sequence: 3  Shipped
```

Kafka partition key should usually match the aggregate requiring order.

```text
key = aggregate_id
```

This preserves per-order ordering while distributing different orders across partitions.

---

## 8. Consumer idempotency

Outbox prevents missing events. It does not prevent duplicate delivery.

Consumer must handle:

```text
same event published twice
same event replayed later
consumer crash after side effect before offset commit
```

Pattern:

```sql
BEGIN;

INSERT INTO processed_events(event_id)
VALUES ('evt_123')
ON CONFLICT DO NOTHING;

-- If inserted, apply business effect.
-- If conflict, skip duplicate.

COMMIT;
```

For external systems, use provider idempotency keys.

```text
payment_idempotency_key = event_id or business operation id
email_dedupe_key        = order_id + email_type
webhook_dedupe_key      = event_id
```

---

## 9. Production failure patterns

### Failure 1: connector lag creates stale read models

Shape:

```text
+----------+      +-----------+      +-------+      +-------------+
| OrdersDB | ---> | Connector | ---> | Kafka | ---> | SearchIndex |
+----------+      +-----------+      +-------+      +-------------+
                    lagging                         stale
```

Symptoms:

```text
orders exist in primary database
outbox rows exist
Kafka topic delayed
search/email/analytics stale
API write path healthy
```

Mitigation:

```text
1. Declare database authoritative.
2. Check connector errors and lag.
3. Check replication slot WAL retention.
4. Pause non-critical consumers if downstream is saturated.
5. Backfill at controlled rate after primary is safe.
```

### Failure 2: replication slot retains too much WAL

PostgreSQL replication slots retain WAL needed by a lagging connector.

Symptoms:

```text
WAL disk usage grows
connector inactive or lagging
primary disk pressure increases
```

Diagnostic query:

```sql
SELECT
  slot_name,
  active,
  restart_lsn,
  confirmed_flush_lsn,
  pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) AS retained_bytes
FROM pg_replication_slots;
```

Dangerous move:

```text
Dropping a slot without understanding whether downstream can recover.
```

Mitigation:

```text
restore connector
increase disk temporarily if needed
throttle write load if primary is at risk
re-snapshot downstream if slot must be dropped
```

### Failure 3: duplicate publish

Relay publishes an event and crashes before marking it published. On restart, it publishes again.

Mitigation:

```text
idempotent consumers
event_id uniqueness
producer idempotence where applicable
consumer dedupe table
```

### Failure 4: outbox table bloat

Outbox grows forever.

Symptoms:

```text
outbox table large
indexes bloated
polling relay slows down
vacuum pressure increases
```

Mitigation:

```text
partition outbox by time
archive or delete published rows after retention
index relay query carefully
avoid long transactions blocking vacuum
```

### Failure 5: schema drift

Producer writes event payload version 3. Consumer only understands version 2.

Mitigation:

```text
schema compatibility checks
additive changes
versioned event handlers
consumer rollout before producer breaking changes
DLQ with schema error classification
```

---

## 10. SRE diagnostic toolkit

Outbox backlog:

```sql
SELECT count(*)
FROM outbox_events
WHERE created_at < now() - interval '5 minutes';
```

Oldest unpublished or unprocessed event:

```sql
SELECT min(created_at)
FROM outbox_events
WHERE published_at IS NULL;
```

Replication slot:

```sql
SELECT slot_name, active,
       pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) AS retained_bytes
FROM pg_replication_slots;
```

Kafka consumer lag:

```bash
kafka-consumer-groups --bootstrap-server broker:9092 \
  --describe --group search-indexer
```

Track:

```text
outbox insert rate
connector lag
WAL retained bytes
publish error rate
DLQ rate
consumer lag age
projection freshness
outbox cleanup duration
```

---

## 11. Decision framework

```text
+-------------------------------+-----------------------------+
| Situation                     | Pattern                     |
+-------------------------------+-----------------------------+
| low volume internal jobs      | polling table may be enough |
| DB write must emit event      | transactional outbox        |
| many downstream consumers     | outbox + broker             |
| need DB change stream         | CDC                         |
| need business event semantics | app-written outbox event    |
| external side effects         | idempotency + reconciliation|
+-------------------------------+-----------------------------+
```

Use outbox when losing the event would make the system incorrect.

---

## 12. Incident scenario: missing search orders

Architecture:

```text
+----------+      +---------------+      +-----------+      +-------+
| OrdersDB | ---> | outbox_events | ---> | Connector | ---> | Kafka |
+----------+      +---------------+      +-----------+      +-------+
                                                            |
                                                            v
                                                       +-------------+
                                                       | SearchIndex |
                                                       +-------------+
```

Symptoms:

```text
orders created successfully: yes
orders visible in DB: yes
outbox rows: increasing
connector lag: 45 minutes
Kafka topic rate: low
search index freshness: 45 minutes behind
WAL retained bytes: growing quickly
```

Expert diagnosis:

```text
The authoritative write path is healthy. The CDC connector is lagging or stuck,
so read models are stale. Search missing orders is a projection freshness issue,
not order loss.
```

Mitigation:

```text
1. Protect primary database disk from WAL growth.
2. Inspect connector errors and restart only if safe.
3. Check replication slot retained bytes.
4. Stop non-critical backfills competing for the connector/downstream.
5. Communicate search freshness delay.
6. Rebuild or replay search at controlled rate.
```

Long-term:

```text
connector lag alert
WAL retention alert
outbox table partitioning
schema compatibility gates
consumer idempotency tests
projection freshness SLO
```

---

## 13. Key takeaways

```text
1. Outbox solves the database-plus-broker dual-write problem.
2. Write business data and outbox event in one local transaction.
3. CDC transports committed facts but still needs operations.
4. CDC row changes are not always business events.
5. Consumers must be idempotent because duplicate delivery still happens.
6. Connector lag is business freshness lag.
7. Replication slots can threaten primary disk if ignored.
8. Outbox cleanup and replay strategy are part of the design.
```
