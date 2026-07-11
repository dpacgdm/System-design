# Answer Key - Week 08 - Northstar Slow-Burn Checkout: SLO, Time, and Telemetry Trap

> Open only after attempting the learner-side drill.

### Executive diagnosis

Enterprise EU checkout burns silently because SLO labels were dropped. During diagnosis, order_id metrics and 100% traces blind dashboards; coupon clock skew and cart LWW create real checkout failures.

A principal response separates the trigger from the amplifier and states the invariant before proposing capacity or repair. The answer should not say only "scale it" or "roll it back"; it must explain why this system failed this way.

### Evidence map

- `global_checkout_availability: 99.94%`
- `enterprise_eu_checkout_availability: 98.62%`
- `active_metric_series: 22M -> 980M`
- `metrics_query_timeout_rate: 41%`
- `coupon_future_iat_reject_rate: 12%`
- `cart_resurrection_rate: 3.8%`
- Config clue: `slo.drop_labels: [region,tier]`
- Config clue: `metric.labels.include_order_id: true`
- Red herring: a fleet average or generic health check that does not include the damaged slice.

### First 15 minutes: sequencing

1. Declare severity, name the invariant, and assign an incident commander.
2. Freeze deploys, config flips, schema changes, broad failovers, and bulk replay touching this path.
3. Stop the active amplifier before adding capacity: retry storms, unsafe repair, global fallback, bad routing, or telemetry blow-up.
4. Roll back or override the specific dangerous config while preserving source-of-truth writes.
5. Shed noncritical surfaces: dashboards, notifications, search, decorative metadata, analytics, or advisory enrichment as appropriate.
6. Verify with the sliced SLI and scarce-resource metric; do not declare recovery from a global average.
7. Start an affected-record ledger before any replay or customer-visible repair.

### Bad fixes

- `wait for global SLO`: lets a contractual slice burn because aggregate math looks healthy.
- `keep 100% tracing while dashboards fail`: uses a derived view as truth, so it can miss or invent records during repair.
- `accept client coupon times globally`: improves a visible symptom while weakening the incident invariant or repair boundary.
- `merge carts by latest timestamp`: orders events by time observation rather than happens-before causality.

### Capacity and blast radius

A principal answer gives at least one bound. Compute the affected slice, backlog or queue depth, derivative, safe downstream throughput, and time-to-exhaustion or time-to-drain. If those values are unknown, the safe move is to throttle and measure before scale/failover/replay.

Examples of the expected math:
- current backlog / safe drain rate = minimum repair duration
- free disk or pool headroom / growth rate = time-to-exhaustion
- affected tenants, SKUs, auctions, regions, orders, or carts from source-of-truth keys
- downstream provider/API/database quota that caps replay concurrency

### Repair and reconciliation

Source of truth: sliced enterprise order/payment records, coupon issuer logs, server cart event history.

Build the affected set from authoritative records in the incident window, not from cache, search, dashboards, or customer anecdotes alone. Repair must use stable idempotency or operation keys, be throttled to downstream headroom, and write an audit trail. Derived projections can be rebuilt after the invariant is safe.

### Durable fixes

- sliced SLO pages for enterprise promises
- telemetry cardinality guardrails
- bounded server-time coupon validation
- observed-remove cart merge and checkout holds

Acceptance criteria:
- The exact bad config from the drill is blocked or requires senior review.
- A staging drill reproduces the old failure and verifies safe rollback/replay.
- The dashboard contains the sliced SLI and the scarce-resource metric together.
- The alert fires before customer impact or before the scarce resource reaches exhaustion.

### Org and runbook

By T+10 include incident command, the owning service team, the relevant platform/data owner, product/business owner, and support. Add payments, security, finance, warehouse, seller-ops, or customer-success when money, trust, physical fulfillment, or enterprise promises are involved.

Pre-authorized: rollback bad config, pause unsafe repair, shed noncritical work, throttle retry/replay, quarantine unhealthy replicas/consumers/pods, and communicate degraded mode. Escalate: destructive state changes, durability downgrades, broad failover, consistency weakening, manual ledger/customer remediation outside policy, or accepting derived data as truth.

### Principal-depth checklist

- Root mechanism, trigger, and amplifier are distinct.
- Evidence uses real metric/config names from the drill.
- First action protects the invariant, not the prettiest graph.
- Bad fixes are rejected with concrete failure modes.
- Capacity math precedes scale/failover/replay.
- Repair has source of truth, idempotency, throttle, and audit.
- Durable fixes include alerts, tests, config guardrails, and ownership.

## Principal model response

### Root cause and invariant

This is an observability and correctness incident. The initial
trigger is SLO label loss: `slo.drop_labels: [region,tier]`
removes the enterprise EU slice from normal alerting. The
diagnosis is then slowed by cardinality explosion from
`order_id` metrics and 100% traces. Underneath that, coupon
client-time fallback and cart LWW merge create real checkout
failures.

The invariant is:

> Enterprise checkout decisions must use authoritative server
> time and cart causal state, and enterprise SLO burn must page
> even when global availability is green.

### Telemetry interpretation

- `global_checkout_availability: 99.94%` is misleading.
- `enterprise_eu_checkout_availability: 98.62%` and
  `slo_burn_rate_5m{enterprise_eu}: 38` define the incident.
- `active_metric_series: 22M -> 980M` explains why normal
  dashboards time out.
- `metrics_query_timeout_rate: 41%` means the telemetry system
  has become an amplifier.
- `coupon_future_iat_reject_rate: 12%` points at clock/time
  validation.
- `cart_resurrection_rate: 3.8%` points at LWW merge semantics.
- `payment_auth_success_rate{enterprise,eu}: 92.8%` shows
  money-path customer impact.

### First 15 minutes

T+0 to T+5:

1. Declare P1 based on enterprise EU burn, not global SLO.
2. Assign incident command, checkout owner, observability,
   coupon/auth-time owner, cart/sync owner, payments,
   enterprise support, and product.
3. Freeze deploys/configs touching SLO labels, metric labels,
   trace sampling, coupon validation, and cart merge.
4. Restore or synthesize the enterprise EU SLO slice on the
   bridge from logs/source data if dashboards are timing out.

T+5 to T+15:

5. Remove high-cardinality `order_id` metric label and reduce
   trace sampling with tail/error sampling so queries work.
6. Keep low-cardinality safety metrics: tier, region, route,
   payment provider, coupon decision, cart merge outcome.
7. Disable client-time fallback for coupon decisions; require
   server-issued time or bounded skew.
8. Disable LWW checkout cart merge for affected clients; hold
   checkout with conflict UX when causal state is ambiguous.
9. Build affected ledger from enterprise EU orders, coupon
   rejects, cart resurrection, and payment auth attempts.

### Capacity and blast-radius checks

Observability:

- Active series grew `980M / 22M ~= 44.5x`. Query timeout at
  41% means observability itself is no longer reliable.
- The fix must reduce cardinality before expecting dashboards
  to guide fine-grained repair.

SLO:

- Enterprise EU availability at 98.62% is 1.38% failed or bad
  requests in the slice. For 60k enterprise EU checkouts/hour,
  that is `60000 * 0.0138 = 828` impacted checkouts/hour.
- A 38x five-minute burn means the monthly error budget for
  that slice is being consumed fast enough to justify incident
  response even if global burn is 1.1x.

Cart/coupon:

- Coupon future-iat reject at 12% and cart resurrection at
  3.8% are not monitoring artifacts; they are correctness
  paths that require source-of-truth repair.

### Bad-fix rejection

- Waiting for global SLO ignores a paying contractual slice.
- Keeping 100% tracing while queries time out preserves a
  debugging wish at the expense of incident visibility.
- Accepting client coupon timestamps globally invites fraud
  and clock-skew errors.
- Merging carts by latest wall-clock timestamp resurrects
  deleted items and violates causality.
- Refunding or cancelling from dashboards alone is unsafe when
  metrics are poisoned by cardinality and label loss.

### Repair and reconciliation

Use source-of-truth records:

- orders/payments ledger for completed or pending checkout;
- coupon issuer logs and server timestamp decisions for coupon
  rejects;
- cart event log with device/session actor metadata for merge
  conflicts;
- enterprise tenant list and region/tier routing logs for
  slice membership.

For affected orders, classify as succeeded, payment pending,
coupon rejected due to bad time fallback, cart conflict held,
or needs manual review. Customer-visible remediation should
match class: do not promise duplicate charge or success
without ledger proof.

### Durable fixes

- SLO alerts require region, tier, and customer-contract labels
  and must fail closed if a critical label disappears.
- Metric cardinality budgets reject `order_id`, exception
  message, JWT, or user ids as labels.
- Trace sampling uses tail/error sampling during incidents,
  not 100% blanket sampling on hot paths.
- Coupon validation uses server-issued time, bounded skew, and
  replay tests for future/past `iat`.
- Cart sync uses causal metadata or observed-remove semantics,
  not LWW wall-clock timestamps for checkout decisions.
- Dashboards put sliced SLO, cardinality, payment auth,
  coupon skew, and cart conflict signals on one incident page.
- Game-day disables a critical label and verifies the fallback
  alert path pages before support reports the issue.

### T+60 durable acceptance criteria

- Enterprise EU SLO pages with the global SLO still green.
- Cardinality guard blocks the bad label in CI and runtime.
- Coupon tests cover device clock skew, offline token reuse,
  and server-time fallback.
- Cart tests cover remove/add conflict, stale offline queue,
  and checkout hold before payment.
- Support runbook distinguishes enterprise checkout failures,
  coupon rejects, cart conflict holds, and payment auth
  pending states.

---
