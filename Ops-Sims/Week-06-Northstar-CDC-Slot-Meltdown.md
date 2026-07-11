# Ops Sim: Week 06 - Northstar CDC Slot Meltdown: WAL Cliff and Idempotent Backfill

**Time box:** 60 minutes  
**Severity:** P1  
**Service / domain:** Postgres WAL, logical replication slots, Debezium, fulfillment replay  
**Northstar system:** Northstar Commerce

## Runbook rules

1. Answer from memory of the Standalone Ops Sim teaching section; do not re-read mid-drill.
2. Write decisions in order: T+0, T+5, T+15, T+30, T+60, and follow-up.
3. Tie every claim to a metric, log line, trace, query output, or config key from this packet.
4. Name the correctness invariant before proposing scale, failover, replay, or data repair.
5. Do not open the answer key until your response is written.

---

## Incident stem

```text
WHAT USERS SEE:
  - Paid orders are durable but fulfillment events stall; disk free falls fast.
  - Source-of-truth records and derived projections disagree.
  - Support reports cluster in the named slice, not the full fleet.
  - A proposed generic mitigation would hide or worsen the invariant risk.

WHAT ON-CALL SEES:
  - Debezium slot retention and manual non-idempotent replay collide.
  - Fleet-average dashboards understate the incident.
  - The config fragment below changed recently or lacks a guardrail.
  - Repair must wait for a bounded affected set and idempotent operation key.

BUSINESS CONSTRAINT:
  No accepted paid order disappears or triggers duplicate fulfillment; email/search can lag.
```

## Operational physics

A Debezium connector stalls after DDL while a manual repair job publishes non-idempotent fulfillment events. The logical slot is the recovery point and the disk threat.

Break it into these forces before answering:
- trigger: the release/config/data shape that started the failure
- amplifier: retry, cache, routing, projection, or observability behavior that widened it
- scarce resource: the metric that reaches a limit first
- invariant: what must remain conservative even while users see degraded experience
- repair boundary: the source of truth and operation id used after mitigation

## Deployment clues

- The suspicious production lever is `debezium.snapshot.mode: always`; tie it to the first bad minute before changing capacity.
- The dashboard that stayed calm does not expose `pg_replication_slot_retained_bytes` for the damaged slice.
- The runbook move closest to "drop the slot" needs an explicit no-go decision on the bridge.
- The repair path is allowed only after the source-of-truth query and operation key are written down.

## Observed evidence

```text
METRICS:
  - pg_replication_slot_retained_bytes: 14GB -> 430GB
  - postgres_wal_disk_free_percent: 32 -> 5
  - debezium_source_lag_seconds: 6 -> 2860
  - fulfillment_missing_paid_orders: 23100
  - manual_republish_events_total: +310k
  - fulfillment_duplicate_external_call_total: +6200
  - outbox_oldest_age_seconds: 3010
  - connector_restart_total: +27/30m

LOG LINES:
  - manual-republish: fulfillment event operation_id=null order_id=ns-8844
  - Week 06 - Northstar CDC Slot Meltdown: WAL Cliff and Idempotent Backfill: derived projection disagrees with source of truth
  - Week 06 - Northstar CDC Slot Meltdown: WAL Cliff and Idempotent Backfill: unsafe repair or fallback proposed on bridge
  - Week 06 - Northstar CDC Slot Meltdown: WAL Cliff and Idempotent Backfill: affected-slice metric exceeds fleet average
  - Week 06 - Northstar CDC Slot Meltdown: WAL Cliff and Idempotent Backfill: capacity check missing before replay/scale

TRACE / QUERY / INSPECTION NOTES:
  - Inspect slot LSN, WAL growth rate, outbox age, and fulfillment operation ids.
  - Before/after config diff aligns with the first bad metric.
  - The affected set is bounded by time window plus business key.
  - One generic health check remains green and is a red herring.
```

## Config under suspicion

```yaml
debezium.snapshot.mode: always
slot.max_retained_wal_bytes: unlimited
manual_republish.dedupe_key: none
fulfillment.operation_key: null
schema.history.recovery: disabled
```

## Timeline

| Time | Event | Your move |
|------|-------|-----------|
| T+0 | WAL disk free falls while paid orders miss fulfillment. | Preserve slot and source of truth. |
| T+5 | Manual republish creates duplicate fulfillment calls. | Stop unsafe replay. |
| T+15 | Schema history failure is confirmed. | Add WAL headroom and patch connector. |
| T+30 | Connector resumes. | Backfill with operation ids. |
| T+60 | Replay debt remains. | Throttle fulfillment drain. |
| T+24h | Data platform reviews runbook. | Add slot and backfill drills. |

## Controls you can pull

- Roll back or disable the specific dangerous config from the packet.
- Shed decorative, derived, notification, or analytics work before weakening source-of-truth correctness.
- Throttle retry/replay using the narrowest downstream capacity limit.
- Keep an affected-record ledger before customer-visible repair.
- Verify recovery with the sliced SLI plus the scarce-resource metric, not a fleet average.

## Bad fixes

For each proposal, name the concrete failure mode it creates.

- drop the slot
- let manual republish continue
- replay at maximum Kafka throughput
- use search as the missing-order source

## Principal prompts

**Q01.** What exact layer owns the failure and why is the most obvious graph a red herring?

**Q02.** Which config line is wrong, and what failure physics does it create?

**Q03.** Select three metrics and two log/inspection clues that prove your diagnosis.

**Q04.** What is the safe T+0 to T+5 announcement and freeze/rollback decision?

**Q05.** What do you stop first: trigger, amplifier, or repair job? Explain sequencing.

**Q06.** What invariant must remain true if every dashboard is stale?

**Q07.** Which bad fix is most tempting in this incident, and why does it make recovery worse?

**Q08.** What numeric capacity or blast-radius check is required before scale/failover/replay?

**Q09.** What is the source-of-truth query or ledger for the affected set?

**Q10.** Which derived systems may lag, and which external side effects require idempotency?

**Q11.** Write the durable config/architecture change and its acceptance test.

**Q12.** Who joins by T+10, and what is pre-authorized versus escalated?

## Score after answer key

| Error type | Count | Notes |
|------------|-------|-------|
| Wrong layer/root cause | | |
| Evidence gap | | |
| Unsafe first action | | |
| Capacity/blast-radius miss | | |
| Correctness invariant miss | | |
| Repair/replay mistake | | |
| Org/runbook gap | | |

**Pass bar:** correct mechanism, safe sequencing, explicit rejection of the bad fix, one numeric capacity check, and a repair plan grounded in source of truth.

**Answer key:** [answers/Ops-Sims/Week-06-Northstar-CDC-Slot-Meltdown Answers.md](../answers/Ops-Sims/Week-06-Northstar-CDC-Slot-Meltdown%20Answers.md)
