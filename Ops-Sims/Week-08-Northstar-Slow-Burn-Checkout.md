# Ops Sim: Week 08 - Northstar Slow-Burn Checkout: SLO, Time, and Telemetry Trap

**Time box:** 60 minutes  
**Severity:** P1  
**Service / domain:** SLO alerting, observability cardinality, clock skew, CRDT cart sync  
**Northstar system:** Northstar Commerce

## Practice rules

1. Answer from memory of the Standalone Ops Sim teaching section; do not re-read mid-drill.
2. Write decisions in order: T+0, T+5, T+15, T+30, T+60, and follow-up.
3. Tie every claim to a metric, log line, trace, query output, or config key from this packet.
4. Name the correctness invariant before proposing scale, failover, replay, or data repair.
5. Do not open the answer key until your response is written.

---

## What is happening

```text
WHAT USERS SEE:
  - Enterprise EU checkout burns while global availability looks acceptable.
  - Source-of-truth records and derived projections disagree.
  - Support reports cluster in the named slice, not the full fleet.
  - A proposed generic mitigation would hide or worsen the invariant risk.

WHAT ON-CALL SEES:
  - Telemetry cardinality hides dashboards, and coupon/cart edge cases create real checkout failures.
  - Fleet-average dashboards understate the incident.
  - The config fragment below changed recently or lacks a guardrail.
  - Repair must wait for a bounded affected set and idempotent operation key.

BUSINESS CONSTRAINT:
  Honor enterprise checkout correctness and customer trust; telemetry, coupons, and cart sync can be degraded conservatively.
```

## Root-cause mechanics

Enterprise EU checkout burns silently because SLO labels were dropped. During diagnosis, order_id metrics and 100% traces blind dashboards; coupon clock skew and cart LWW create real checkout failures.

Break it into these forces before answering:
- trigger: the release/config/data shape that started the failure
- amplifier: retry, cache, routing, projection, or observability behavior that widened it
- scarce resource: the metric that reaches a limit first
- invariant: what must remain conservative even while users see degraded experience
- repair boundary: the source of truth and operation id used after mitigation

## Change clues

- The suspicious production lever is `slo.drop_labels: [region,tier]`; tie it to the first bad minute before changing capacity.
- The dashboard that stayed calm does not expose `global_checkout_availability` for the damaged slice.
- The runbook move closest to "wait for global SLO" needs an explicit no-go decision on the bridge.
- The repair path is allowed only after the source-of-truth query and operation key are written down.

## Telemetry card

```text
METRICS:
  - global_checkout_availability: 99.94%
  - enterprise_eu_checkout_availability: 98.62%
  - active_metric_series: 22M -> 980M
  - metrics_query_timeout_rate: 41%
  - coupon_future_iat_reject_rate: 12%
  - cart_resurrection_rate: 3.8%
  - payment_auth_success_rate{enterprise,eu}: 92.8%
  - slo_burn_rate_5m{enterprise_eu}: 38

LOG LINES:
  - slo: enterprise_eu burn=38 global=1.1 labels dropped
  - Week 08 - Northstar Slow-Burn Checkout: SLO, Time, and Telemetry Trap: derived projection disagrees with source of truth
  - Week 08 - Northstar Slow-Burn Checkout: SLO, Time, and Telemetry Trap: unsafe repair or fallback proposed on bridge
  - Week 08 - Northstar Slow-Burn Checkout: SLO, Time, and Telemetry Trap: affected-slice metric exceeds fleet average
  - Week 08 - Northstar Slow-Burn Checkout: SLO, Time, and Telemetry Trap: capacity check missing before replay/scale

TRACE / QUERY / INSPECTION NOTES:
  - Inspect sliced SLOs, active series, coupon iat skew, and cart merge conflicts.
  - Before/after config diff aligns with the first bad metric.
  - The affected set is bounded by time window plus business key.
  - One generic health check remains green and is a red herring.
```

## Config card

```yaml
slo.drop_labels: [region,tier]
metric.labels.include_order_id: true
trace_sampling.rate: 1.0
coupon.use_client_time_fallback: true
cart.merge_strategy: lww_timestamp
```

## Decision table

| Time | Event | Your move |
|------|-------|-----------|
| T+0 | Enterprise EU burn is visible only in support and ad hoc slice. | Promote sliced SLO to incident. |
| T+5 | Dashboards fail from cardinality blow-up. | Drop telemetry poison first. |
| T+15 | Coupon clock skew and cart LWW appear in traces. | Disable unsafe fallbacks. |
| T+30 | Enterprise checkout stabilizes. | Prioritize enterprise repair ledger. |
| T+60 | Coupon/cart corrections remain. | Repair with source-of-truth records. |
| T+24h | Week 8 review asks for continuity. | Tie SLO, time, and CRDT guardrails together. |

## Recovery tools

- Roll back or disable the specific dangerous config from the packet.
- Shed decorative, derived, notification, or analytics work before weakening source-of-truth correctness.
- Throttle retry/replay using the narrowest downstream capacity limit.
- Keep an affected-record ledger before customer-visible repair.
- Verify recovery with the sliced SLI plus the scarce-resource metric, not a fleet average.

## Do-not-do list

For each proposal, name the concrete failure mode it creates.

- wait for global SLO
- keep 100% tracing while dashboards fail
- accept client coupon times globally
- merge carts by latest timestamp

## Questions

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

## Self-score

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

**Answer key:** [answers/Ops-Sims/Week-08-Northstar-Slow-Burn-Checkout Answers.md](../answers/Ops-Sims/Week-08-Northstar-Slow-Burn-Checkout%20Answers.md)
