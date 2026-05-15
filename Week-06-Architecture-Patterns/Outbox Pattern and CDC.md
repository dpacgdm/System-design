# Week 6, Topic 6: Outbox Pattern and CDC

Last verified: 2026-05-15

The outbox pattern solves the dual-write problem between a database transaction and event publishing.

## Learning objectives

```text
1. Explain why writing DB plus publishing Kafka directly is unsafe.
2. Design an outbox table.
3. Use CDC to publish committed changes.
4. Diagnose connector lag, duplicate publishing, and replay hazards.
```

## Dual-write problem

Bad pattern:

```text
1. INSERT order into database
2. Publish OrderCreated to Kafka
```

Failure cases:

```text
DB succeeds, Kafka fails:
  order exists, event missing

Kafka succeeds, DB rolls back:
  event exists for order that does not
```

## Outbox model

```text
+----------+      same transaction      +---------------+
| orders   | <------------------------> | outbox_events |
+----------+                            +---------------+
       |                                      |
       | CDC                                  v
       |                                +-----------+
       +------------------------------> | Kafka     |
                                        +-----------+
```

In one database transaction:

```sql
BEGIN;

INSERT INTO orders(id, customer_id, status)
VALUES ('ord_123', 'cust_1', 'created');

INSERT INTO outbox_events(event_id, aggregate_id, event_type, payload)
VALUES ('evt_123', 'ord_123', 'OrderCreated', '{...}');

COMMIT;
```

CDC reads committed rows and publishes events.

## Outbox table shape

```text
event_id
aggregate_type
aggregate_id
event_type
schema_version
payload
created_at
published_at optional
```

## Failure modes

```text
Connector lag:
  DB commits are safe, but events are delayed.

Duplicate publish:
  connector restarts and emits same event again.

Schema drift:
  consumers cannot parse new payload.

Outbox table bloat:
  cleanup missing or too slow.

Ordering surprise:
  events across aggregates are not globally ordered.
```

## Diagnostics

```sql
SELECT count(*)
FROM outbox_events
WHERE created_at < now() - interval '5 minutes';
```

```sql
SELECT slot_name, active, restart_lsn, confirmed_flush_lsn
FROM pg_replication_slots;
```

```bash
kafka-consumer-groups --bootstrap-server broker:9092 \
  --describe --group downstream-consumer
```

## Scenario

Orders are in PostgreSQL, but search index is missing recent orders. Kafka is healthy, but Debezium connector lag is 45 minutes.

Expert answer:

```text
Authoritative orders are safe. Async read models are stale. Check replication slot
lag, connector errors, schema registry errors, and downstream backpressure. Do
not backfill at full speed against a saturated primary. Reconcile search after
CDC catches up.
```

## Key takeaways

```text
1. Outbox avoids unsafe DB plus broker dual writes.
2. CDC publishes committed facts, not application guesses.
3. Consumers must still be idempotent.
4. Connector lag is business freshness lag.
5. Cleanup and replay must be designed from day one.
```
