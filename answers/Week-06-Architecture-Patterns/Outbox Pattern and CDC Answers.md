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

---

# Incident Deep-Dive: The Slot That Ate Tuesday

## Question 1: Failure Chain — Symptom vs Root Cause

```plaintext
ROOT CAUSE (upstream):
  clickstream-edge deploy: acks=all + broker saturation
  → ISR shrinkage on SHARED MSK cluster
  → produce failures to orders.outbox topic

MECHANISM (outbox/CDC specific):
  Debezium cannot ack Kafka → confirmed_flush_lsn frozen
  → Postgres retains WAL for slot debezium_outbox_orders
  → pg_wal disk growth

SYMPTOMS (customer-visible):
  fulfillment-svc lag → tracking not created
  (checkout succeeded — outbox INSERT committed in Phase 1)

OUTBOX PATTERN SUCCESS:
  Orders persisted atomically with outbox rows during checkout
  5xx window. No dual-write loss of orders vs events in DB.
  Events exist in outbox table (and WAL) even while Kafka publish
  stalled.

OUTBOX PATTERN FAIL (operational):
  Phase 2 publish stalled. Eventual consistency never "eventuated"
  within SLO. CDC coupling exposed checkout DB to Kafka health
  via replication slot — the Week 5 Part 7 footgun.

SYMPTOM vs ROOT:
  Symptom: fulfillment lag, missing tracking, disk growth
  Root: broker saturation (trigger) + slot without cap (amplifier)
  Contributing: no polling fallback, slot not on checkout dashboard
```

## Question 2: 30-Minute Stabilization Playbook

```plaintext
T+0 (14:15) — ASSESS (parallel)
  □ kafka-topics --describe orders.outbox → ISR state
  □ curl Connect /connectors/orders-outbox-pub/status
  □ psql: replication slot query (retained_wal, active)
  □ df -h on orders primary data volume
  □ SELECT COUNT(*) FROM outbox WHERE created_at > now()-'1 hour'

T+2 — STOP THE BLEEDING (disk)
  If disk > 85% OR projected full < 2h:
    PAUSE Debezium connector (reduces flapping, NOT slot release)
    START emergency polling publisher Deployment
      (image: outbox-publisher-fallback, pre-staged?)
    Polling reads: WHERE published_at IS NULL OR use created_at
    watermark since Debezium last known good offset time
    Producer: acks=1 temporarily? NO — keep acks=all if ISR OK
    Rate limit: 500 msg/s to avoid second broker spike

  DO NOT drop slot yet if polling can publish and disk stable <90%

T+5 — KAFKA PATH
  Confirm UnderReplicatedPartitions = 0 for orders.outbox
  If not: continue Kafka module ISR recovery

T+8 — SLOT DECISION TREE
  Disk < 88% AND polling draining fulfillment lag:
    Keep slot. Debezium paused. Polling is temporary transport.

  Disk > 88% OR projected full < 60 min:
    DROP SLOT: SELECT pg_drop_replication_slot('debezium_outbox_orders');
    WAL freed at next checkpoint (~minutes)
    ACCEPT: must re-snapshot or no_data + backlog replay
    Polling publishes all unpublished semantics via published_at
    OR created_at > incident_start watermark

T+15 — VERIFY DRAIN
  fulfillment lag decreasing
  retained_wal stable or dropping
  Sample: order_id from support ticket exists in outbox,
  event_id in Kafka (kafka-console-consumer --partition)

T+20 — CUSTOMER SUPPORT SCRIPT
  "Orders were saved. Tracking updates delayed 30-90 min.
   No duplicate charges. Escalate if tracking missing after 2h."

T+30 — HANDOFF
  Document: slot dropped? Y/N. Polling active? Y/N.
  Duplicate risk window → finance on dedup report.
```

## Question 3: Proving No Duplicate Fulfillments

```sql
-- 1. Duplicate event_ids in fulfillment processed_events
SELECT event_id, COUNT(*) FROM fulfillment.processed_events
WHERE processed_at > '2026-07-06 13:45:00+00'
GROUP BY 1 HAVING COUNT(*) > 1;
-- Expect 0 rows

-- 2. Duplicate shipments per order (business invariant)
SELECT order_id, COUNT(*) FROM fulfillment.shipments
WHERE created_at > '2026-07-06 13:45:00+00'
GROUP BY 1 HAVING COUNT(*) > 1;

-- 3. Orders in outbox during incident without fulfillment
SELECT o.id, o.event_type, o.created_at
FROM outbox o
LEFT JOIN fulfillment.processed_events p ON p.event_id = o.id
WHERE o.created_at BETWEEN '13:45' AND '15:00'
  AND o.event_type = 'OrderCreated'
  AND p.event_id IS NULL;
-- Should drain to zero after recovery

-- 4. Kafka duplicate count (audit)
-- Compare producer idempotence seq vs consumer dedup inserts
-- Metric: fulfillment_duplicate_suppressed_total (counter)
```

```plaintext
STATE MACHINE INTERACTION:
  fulfillment-svc on OrderCreated:
    INSERT shipment ON CONFLICT (order_id) DO NOTHING
    OR processed_events gate then INSERT

  Duplicate OrderCreated from polling+Debezium overlap:
    Second insert blocked by event_id dedup OR order_id UPSERT

  OrderCreatedV1 replay from re-snapshot:
    Same event_id if outbox.id stable → dedup wins
    NEW event_ids if re-snapshot generates new outbox READ ops
    → CRITICAL: Debezium snapshot emits same row id → same event_id
    → dedup handles re-snapshot correctly IF event_id = outbox.id
```

## Question 4: Monitoring That Pages at 13:58

```plaintext
ALERT 1 — Slot retained WAL (PRIMARY owner: checkout-svc on-call)
  SQL exporter every 60s:
    pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) AS bytes
  PromQL: pg_replication_slot_retained_bytes{slot="debezium_outbox_orders"}
  WARN  > 10 GB for 5 min
  PAGE  > 25 GB OR growth rate > 1 GB/min for 3 min
  Would have fired ~13:58 at 2GB/10min crossing 10GB threshold
  if baseline was 8GB — tune: alert on RATE not just absolute

ALERT 2 — Debezium flush lag
  CloudWatch KafkaConnect: SourceRecordWriteRate dropping to 0
  WHILE slot active
  PAGE: millisecond_behind_source > 30000 for 2 min

ALERT 3 — confirmed_flush_lsn stale
  Custom: compare flush LSN timestamp vs now()
  PAGE: no advance for 5 min

ALERT 4 — Fulfillment lag (symptom backup)
  kafka.consumer.lag{group="fulfillment-svc"} > 10000 for 5 min

ALERT 5 — pg_wal disk (DBA)
  PAGE: volume > 70% with derivative positive 30 min

OWNERSHIP:
  Alerts 1-3 → checkout platform (they own outbox + customer SLO)
  Alert 4 → fulfillment team
  Alert 5 → DBA with checkout copied

  Principle: slot on checkout DB = checkout monitors slot.
  "Data platform owns Debezium" but "checkout owns primary disk."
```

## Question 5: Long-Term Architecture Recommendation

```plaintext
CONTEXT:
  2k events/sec peak, 4 backend + 1 data engineer
  Tuesday: shared broker fate + slot coupling hurt

RECOMMENDATION: HYBRID WITH CIRCUIT BREAKER

  PRIMARY: Debezium MSK Connect (latency, ops once learned)
  FALLBACK: polling publisher as ALWAYS-DEPLOYED standby
    (replicas=0 normally, HPA or manual scale to 3 on alert)
  HARDENING:
   - max_slot_wal_keep_size = 80GB on orders primary
   - published_at + polling path even on CDC — dual mark
     (polling updates published_at when used; CDC relies on
     partition drop). Simplifies fallback watermark.
   - Separate MSK cluster OR dedicated brokers for
     orders.outbox vs click.stream (principal answer:
     isolate blast radius — $85k/yr from Kafka module math)
   - Idempotent consumers non-negotiable (already)

  NOT full polling primary: 2k/sec achievable but headroom
  tight with 500ms SLO during spikes.

  NOT DMS: team lacks DMS ops; need Event Router flexibility.

  NOT Debezium-only without fallback: Tuesday proved coupling.

  90-DAY ROADMAP:
   Week 1: slot alerts + max_slot_wal_keep_size
   Week 2: deploy dormant polling fallback, game day
   Week 4: broker isolation proposal
   Week 8: published_at hybrid marking for cleaner fallback
```

---



---
