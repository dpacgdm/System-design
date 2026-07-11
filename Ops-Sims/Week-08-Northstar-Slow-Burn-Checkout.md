# Ops Sim: Week 08 - Northstar Slow-Burn Checkout

**Time box:** 60 minutes
**Severity:** P1
**Service / domain:** SLO burn, observability, clocks, causality, CRDT/cart merge, geospatial delivery promises
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
  - Checkout p99 worsens slowly over six hours, mostly for enterprise sellers in EU.
  - Global availability stays green while payment auth success for the slice falls below contract.
  - Some carts show deleted items again, coupons expire inconsistently, and same-day delivery ETA is stale.

WHAT ON-CALL SEES:
  - Error budget burn alert is absent because labels dropped region and tenant_tier.
  - Metrics backend is slow after an order_id label deploy.
  - NTP offset in one node pool is 95 seconds; cart merge uses device wall-clock LWW.

BUSINESS CONSTRAINT:
  Preserve payment, inventory, and pricing correctness. It is acceptable to disable same-day delivery and coupon experiments for affected slices.
```

---

## 2. Telemetry pack

```text
SYSTEMS INVOLVED:
  - checkout-api
  - coupon service
  - cart-sync
  - same-day delivery ETA
  - metrics/tracing/logging platform
  - mobile clients

METRICS:
  global_checkout_availability: 99.94%
  enterprise_eu_checkout_availability: 98.62%
  payment_auth_success_rate{tier=enterprise,region=eu}: 92.8%
  checkout_latency_p99_ms{enterprise,eu}: 420 -> 4100 over 6h
  slo_burn_rate_5m: missing
  active_metric_series: 22M -> 980M
  metrics_query_timeout_rate: 41%
  trace_sampling_rate: 1.0 no expiry
  ntp_offset_seconds{pool=checkout-eu-b}: p99=95
  coupon_reject_before_expiry_total: +18k
  cart_deleted_item_reappeared_total: +44k
  courier_location_age_seconds_p95: 122
  same_day_eta_error_p95_minutes: 23
  support_vip_tickets: +310/hour

LOG LINES:
  slo: dropped labels region,tenant_tier during dashboard refactor
  metrics: high-cardinality label order_id on checkout_request_duration
  coupon: token issued in future by 88s; rejecting
  cart-sync: LWW chose device_ts future +120s for removed item
  dispatch: matched courier location_age=181s
  checkout: payment timeout tenant_tier=enterprise region=eu
```

---

## 3. Config pack

```yaml
slo.labels_kept: [service]
alerts.multiwindow_burn_rate: false
metrics.labels: [service,route,status,order_id]
tracing.incident_sampling_rate: 1.0
tracing.override_expires_at: null
coupon.validation_clock: local_wall_clock
cart_merge.strategy: last_write_wins_wall_clock
geo.max_location_age_seconds: 300
same_day.fail_closed_on_stale_location: false
```

---

## 4. Timeline & decision points

| Time | Event | Your move (write before reading further) |
|------|-------|------------------------------------------|
| T+0 | Slow-burn P1 suspected from VIP support tickets, not dashboards. | |
| T+10 | Global SLO is green; sliced enterprise EU SLI is red. | |
| T+20 | Metrics backend query timeouts hide root-cause dashboards. | |
| T+35 | Clock skew, cart merge, and stale courier telemetry are all found in affected slice. | |
| T+60 | Same-day and coupon experiment are disabled for EU enterprise; checkout p99 improves. | |
| T+180 | Telemetry is stable; repair for carts/coupons/delivery promises begins. | |

---

## 5. Questions

**Q01:** Which slice defines the incident despite global availability being green?

**Q02:** Which telemetry failure slowed diagnosis, and what fallback evidence remains trustworthy?

**Q03:** Separate root cause, amplifiers, and independent correctness defects.

**Q04:** What is the first 15-minute mitigation sequence?

**Q05:** Which features should degrade, and which invariants must not degrade?

**Q06:** Why is 100% tracing plus order_id metric labels a bad incident response?

**Q07:** How does clock skew affect coupon validity and trace interpretation?

**Q08:** Why is LWW cart merge unsafe for delete/readd conflicts?

**Q09:** What geospatial freshness guard protects same-day delivery promises?

**Q10:** Write the durable SLO/observability/clock/cart/geo fixes and acceptance tests.

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

**Answer key:** [../answers/Ops-Sims/Week-08-Northstar-Slow-Burn-Checkout Answers.md](../answers/Ops-Sims/Week-08-Northstar-Slow-Burn-Checkout%20Answers.md)
