# Answer Key — Outbox Pattern and CDC

> Open only after attempting the learner file questions.

## Expert Analysis
```plaintext
QUESTION 1 — TABLE DESIGN REVIEW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Junior engineer proposes:

    CREATE TABLE outbox (
      id BIGSERIAL PRIMARY KEY,
      payload JSONB,
      published BOOLEAN DEFAULT false
    );

  Tear this apart. Cover: UUID vs BIGSERIAL for event_id,
  missing aggregate_id/key, boolean vs published_at,
  indexes, partitioning, metadata, publish_attempts.


QUESTION 2 — POLLING VS CDC FOR PAYMENTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  payments-svc: 800 events/sec, p99 publish latency 200ms SLO,
  PCI scope, Postgres on RDS, team has no Connect experience.

  Walk through the decision. Include: RDS logical replication
  support, slot monitoring on RDS, whether polling can hit 200ms,
  security audit angle (Debezium DB user permissions).


QUESTION 3 — IDEMPOTENCY PROOF
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  fulfillment-svc uses:

    def handle(event):
        create_shipment(event.order_id)
        db.commit()
        consumer.commit()

  No dedup table. "create_shipment checks if exists."

  Give three scenarios where duplicates still cause harm.
  Rewrite with transactional dedup.


QUESTION 4 — SCHEMA BREAK
━━━━━━━━━━━━━━━━━━━━━━━

  Team drops column discount_code from orders table AND from
  OrderCreated Avro schema same deploy. Fulfillment halts.
  Slot bloat begins. Sequence your recovery steps and
  prevention for next time.


QUESTION 5 — AWS DMS VS DEBEZIUM (PRINCIPAL)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  VP mandates "managed AWS only." Architect proposes DMS
  Postgres → Kinesis → Lambda → MSK for outbox events.

  Argue for and against vs Debezium on MSK Connect.
  Include: latency, ops headcount, event shape, failure
  modes, cost, and what you'd accept as a compromise.
```

---

## Appendix A: Reference Outbox DDL (Production-Ready)

```sql
-- Full production template (Postgres 15+)

CREATE TABLE outbox (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    aggregate_type    TEXT NOT NULL,
    aggregate_id      TEXT NOT NULL,
    event_type        TEXT NOT NULL,
    payload           JSONB NOT NULL,
    metadata          JSONB NOT NULL DEFAULT '{}',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    published_at      TIMESTAMPTZ,
    publish_attempts  INT NOT NULL DEFAULT 0,
    last_error        TEXT,
    CONSTRAINT outbox_payload_size CHECK (octet_length(payload::text) < 1048576)
) PARTITION BY RANGE (created_at);

CREATE TABLE outbox_default PARTITION OF outbox DEFAULT;

CREATE INDEX outbox_pending_idx ON outbox (created_at, id)
    WHERE published_at IS NULL;

CREATE INDEX outbox_aggregate_idx
    ON outbox (aggregate_type, aggregate_id, created_at DESC);

COMMENT ON TABLE outbox IS 'Transactional outbox. Owner: checkout-team. Oncall: #checkout-platform';
COMMENT ON COLUMN outbox.id IS 'event_id for Kafka headers and consumer dedup';

-- Debezium user (minimal privileges)
-- CREATE USER debezium WITH REPLICATION LOGIN PASSWORD '...';
-- GRANT SELECT ON outbox TO debezium;
-- CREATE PUBLICATION dbz_outbox FOR TABLE outbox;
```

---

## Appendix B: Polling Publisher Pseudocode (Production Shape)

```python
# Illustrative — not copy-paste without error handling

POLL_INTERVAL = 0.2
BATCH_SIZE = 100

def publish_loop():
    while running:
        with db.transaction() as txn:
            rows = txn.execute("""
                SELECT id, aggregate_id, event_type, payload, metadata
                FROM outbox
                WHERE published_at IS NULL
                  AND created_at > now() - interval '7 days'
                ORDER BY created_at, id
                LIMIT %s
                FOR UPDATE SKIP LOCKED
            """, [BATCH_SIZE]).fetchall()

            if not rows:
                txn.rollback()
                sleep(POLL_INTERVAL)
                continue

        ids = [r.id for r in rows]
        try:
            for row in rows:
                producer.produce(
                    topic=route_topic(row.event_type),
                    key=row.aggregate_id.encode(),
                    value=serialize(row.payload),
                    headers=build_headers(row),
                )
            producer.flush(timeout=30)
            with db.transaction() as txn:
                txn.execute("""
                    UPDATE outbox SET published_at = clock_timestamp()
                    WHERE id = ANY(%s) AND published_at IS NULL
                """, [ids])
        except Exception as e:
            with db.transaction() as txn:
                txn.execute("""
                    UPDATE outbox SET publish_attempts = publish_attempts + 1,
                                      last_error = %s
                    WHERE id = ANY(%s)
                """, [str(e)[:500], ids])
            sleep(backoff())
```

---

## Appendix C: Debezium Outbox Message Shape

```json
// After Event Router SMT — what fulfillment-svc receives

// Topic: orders.events
// Key: "ord_7f3a2b1c"
// Headers: id=550e8400-e29b-41d4-a716-446655440000, eventType=OrderCreated

{
  "order_id": "ord_7f3a2b1c",
  "customer_id": "cus_991",
  "total_cents": 4999,
  "line_items": [
    { "sku": "WIDGET-1", "qty": 2 }
  ]
}

// Raw Debezium envelope (WITHOUT router — don't expose to domain consumers):

{
  "before": null,
  "after": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "aggregate_type": "order",
    "aggregate_id": "ord_7f3a2b1c",
    "event_type": "OrderCreated",
    "payload": "{...}",
    "created_at": 1717689600123456
  },
  "source": { "lsn": 123456789, "table": "outbox", ... },
  "op": "c"
}
```

---

## Appendix D: Glossary

```plaintext
OUTBOX          Application table written atomically with business data
CDC             Change Data Capture — streaming DB mutations from WAL
WAL             Write-Ahead Log — Postgres durable transaction log
LSN             Log Sequence Number — position in WAL
SLOT            Replication slot — WAL retention bookmark for CDC consumer
DEBEZIUM        Open-source CDC platform; Kafka Connect source connectors
SMT             Single Message Transform — Kafka Connect record mapper
EVENT ROUTER    Debezium SMT mapping outbox rows to domain Kafka records
DMS             AWS Database Migration Service — managed replication
MSK CONNECT     Managed Kafka Connect on Amazon MSK
AT-LEAST-ONCE   Delivery guarantee: no loss, duplicates possible
EFFECTIVELY-ONCE At-least-once + idempotent consumer = single effect
DUAL-WRITE      Anti-pattern: write DB and broker independently
```

---

*End of module. Continuity: Week 5 Part 7 (slots), Part 13–14 (CQRS/CDC failures); Week 6 Kafka Part 9 (outbox), Part 12 (Tuesday Black Hole); Week 6 EDA (event contracts). Next: Saga patterns and compensation in distributed workflows.*
