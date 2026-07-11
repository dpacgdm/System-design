# Ops Sim: Week 06 - Northstar CDC Slot Meltdown

**Time box:** 55 minutes
**Severity:** P1
**Service / domain:** Outbox, CDC, Kafka, Debezium, Postgres WAL, fulfillment events
**Northstar system:** Northstar Commerce

## Rules

1. Answer from memory of the relevant week modules.
2. Work in order: T+0 -> T+10 -> T+20 -> T+60 -> recovery.
3. Name evidence and capacity assumptions for every claim.
4. Do not open the answer key until finished.

---

## 1. Scenario stem

```text
WHAT USERS SEE:
  - Paid orders exist in Postgres but do not reach fulfillment for 18 minutes.
  - Order confirmation email arrives twice for customers touched by manual republish.
  - Checkout writes are still accepted, but WAL disk free is falling fast.

WHAT ON-CALL SEES:
  - Replication slot retained WAL grows from 14GB to 410GB in 42 minutes.
  - Debezium task flaps between RUNNING and FAILED after a schema change.
  - A legacy mobile checkout path writes orders without an outbox row.

BUSINESS CONSTRAINT:
  No accepted paid order may disappear. Duplicate emails are tolerable; duplicate fulfillment or payment effects are not.
```

---

## 2. Telemetry pack

```text
SYSTEMS INVOLVED:
  - checkout-postgres primary
  - northstar_outbox replication slot
  - Debezium order-events connector
  - Kafka order.events topic
  - fulfillment, email, search consumers

METRICS:
  orders_paid_total: +510k/hour
  outbox_rows_pending: 0 -> 226k
  outbox_oldest_age_seconds: 12 -> 2840
  pg_replication_slot_retained_bytes: 14GB -> 410GB
  postgres_wal_disk_free_percent: 31 -> 6
  debezium_source_lag_seconds: 5 -> 2600
  connector_restarts: +19/30m
  kafka_order_events_duplicate_key_rate: 0.03% -> 6.8%
  fulfillment_missing_paid_orders: 19,400
  email_duplicate_sends: +31,000
  search_projection_lag_seconds: 20 -> 3900
  manual_republish_rate: 42k/min

LOG LINES:
  debezium: ERROR column order_total_cents not optional; schema history incompatible
  orders-api: inserted paid order without outbox row path=legacy-mobile-v3
  postgres: replication slot northstar_outbox retained WAL; disk usage above 90%
  manual-publisher: producing event order_id=ns-8844 idempotency_key=null
  fulfillment: duplicate external shipment request suppressed=false
```

---

## 3. Config pack

```yaml
outbox.require_row_same_transaction: false
debezium.snapshot.mode: always
debezium.slot.name: northstar_outbox
publisher.enable_idempotent_producer: false
manual_republish.deduplicate_by_order_id: false
postgres.wal_keep_size: 0
alert.slot_retained_bytes_gb: 500
fulfillment.external_operation_key: null
```

---

## 4. Timeline & decision points

| Time | Event | Your move (write before reading further) |
|------|-------|------------------------------------------|
| T+0 | P1: fulfillment missing paid orders; WAL retained bytes rising. | |
| T+5 | Manual republish begins and duplicate emails spike. | |
| T+15 | Connector schema failure identified; disk free below 10%. | |
| T+30 | Legacy mobile path without outbox rows is confirmed. | |
| T+60 | Connector fixed; outbox and legacy gaps need backfill without duplicates. | |
| T+180 | Disk is safe, but downstream consumers still have replay debt. | |

---

## 5. Questions

**Q01:** Find the root cause chain across OLTP, outbox, CDC, and Kafka.

**Q02:** Which evidence proves this is not only a Kafka consumer lag problem?

**Q03:** What do you stop in the first 5 minutes, and what do you leave running?

**Q04:** How do you protect Postgres disk without losing the slot recovery point?

**Q05:** How do you backfill legacy orders that never created outbox rows?

**Q06:** Why is manual publish without operation ids unsafe even if order_id is present?

**Q07:** What capacity math determines safe replay rate?

**Q08:** Which consumers can lag, and which must be protected from duplicate side effects?

**Q09:** What alerts should have fired before disk reached 10% free?

**Q10:** Write the permanent contract for checkout write + outbox row + emitted event.

**Q11 - Bad-fix gallery:** Reject each proposal and name the failure mode:
- delete or drop the state that preserves replay/reconciliation
- globally weaken consistency/correctness to improve p99
- replay everything at unlimited speed
- trust derived/cache/search/telemetry data as source of truth

**Q12 - Capacity / blast radius:** Estimate the scarce resource and time-to-exhaustion for the incident. Include one numeric check from the telemetry pack.

**Q13 - Org / runbook:** Who joins by T+10? Which actions are pre-authorized, and which require explicit senior approval?

---

## 6. Self-score

| Error type | Count | Notes |
|------------|-------|-------|
| Wrong root cause | | |
| Unsafe first action | | |
| Capacity miss | | |
| Correctness/invariant miss | | |
| Telemetry misread | | |
| Repair/replay mistake | | |
| Org/runbook gap | | |

**Answer key:** [../answers/Ops-Sims/Week-06-Northstar-CDC-Slot-Meltdown Answers.md](../answers/Ops-Sims/Week-06-Northstar-CDC-Slot-Meltdown%20Answers.md)
