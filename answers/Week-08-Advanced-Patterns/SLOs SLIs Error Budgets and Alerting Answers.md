# Answer Key — SLOs SLIs Error Budgets and Alerting

> Open only after attempting the learner file questions.

## Expert Analysis

### Q1: Design Complete SLO for Saved-Cart Feature

**Prompt:** Your team launches saved-cart (GET/PUT/DELETE /cart). Define SLIs, SLOs, four-tier burn-rate alerts with PromQL, false-positive tuning, and error budget policy.

**Answer outline:**

**(a) SLIs from user experience:**
- Write availability: PUT/DELETE success (exclude 4xx)
- Read latency: GET < 300ms (Doherty threshold)

**(b) SLOs (Tier-2):**
- Availability: 99.5% / 30d → 216 min budget
- Latency: 99% < 300ms / 30d → 432 min budget

**(c) Four-tier burn table:**

| Tier | Long | Short | Burn | Action |
|------|------|-------|------|--------|
| 1 | 1h | 5m | 14.4× | Page |
| 2 | 6h | 30m | 6× | Page (BH) |
| 3 | 24h | 2h | 3× | Ticket |
| 4 | 3d | 6h | 1× | Slack |

**(d) PromQL Tier 1 availability:**

```yaml
- alert: SavedCartAvailabilityFastBurn
  expr: |
    (
      sum(rate(http_requests_total{service="cart-svc",method=~"PUT|DELETE",status=~"5.."}[5m]))
      / sum(rate(http_requests_total{service="cart-svc",method=~"PUT|DELETE"}[5m]))
    ) > (14.4 * 0.005)
    and
    (
      sum(rate(http_requests_total{service="cart-svc",method=~"PUT|DELETE",status=~"5.."}[1h]))
      / sum(rate(http_requests_total{service="cart-svc",method=~"PUT|DELETE"}[1h]))
    ) > (14.4 * 0.005)
    and
    sum(rate(http_requests_total{service="cart-svc",method=~"PUT|DELETE"}[5m])) > 1
  for: 2m
  labels:
    severity: page
    slo: saved_cart_availability
```

**(e) Five false-positive tunings:**
1. Minimum traffic floor (> 1 req/s)
2. Authenticated users only
3. Deploy suppression (5 min)
4. Exclude batch traffic (X-Source header)
5. Client-version bugs are real positives, not false — but add version label for diagnosis

**(f) Budget policy:** normal ops above 50%; scrutiny 25–50%; freeze below 25%.

**Self-score: 3/3** — full math, PromQL, tuning, policy.

---

### Q2: Circuit Breaker OPEN — Page or Not?

**Prompt:** At 02:00, `fraud-svc` circuit breaker transitions OPEN on 80% of checkout-svc pods. Checkout availability SLI = 99.98% (30d). Manual review queue +400/min. Page?

**Answer:**

Do NOT page on breaker state alone.

Analysis:
- Availability SLI: healthy (fallback works)
- Quality SLI: undefined today — gap
- Latency SLI: likely improved (skipped fraud call)
- Business impact: manual review backlog — ticket severity

Actions:
1. Slack alert: "fraud breaker OPEN, queue +400/min"
2. Ticket: investigate fraud-svc root cause (business hours)
3. Page ONLY if: queue depth exceeds processing capacity OR availability SLI begins burning OR fallback error rate increases

Immediate: verify fallback path success rate > 99.9% independently.

Post-incident: add quality SLI for `% checkout without manual_review_flag`.

---

### Q3: Recalibrate SLO After 90 Days

**Prompt:** Checkout availability achieved 99.97% for 90 days. Zero customer complaints. Burn alerts never fired. Too loose?

**Answer:**

Yes — SLO is likely too loose OR alerts too conservative.

Data to gather:
- Actual SLI: 99.97% → budget consumption ~30% of allowable
- Near-misses: any 6× burns that were close?
- Business: would 99.95% (tighter) change product decisions?

Recommendation:
- Tighten SLO: 99.9% → 99.95% (not 99.99% — cost jump)
- Add Tier 3 alerts if missing (3× burn)
- Keep 30-day rolling window
- Present to product: "We have headroom to promise tighter reliability"

Do NOT tighten latency SLO without latency baseline analysis.

---

### Q4: AWS CloudWatch vs Prometheus for Global SLO

**Prompt:** Multi-region checkout behind Route 53 latency routing. Single global SLO or per-region? Where to alert?

**Answer:**

Both:
- **Global SLO** (99.9%): customer-facing, measured at each regional ALB, aggregated weighted by traffic
- **Per-region SLO** (99.5%): allows single-region failure with failover

Alerting:
- Global burn 14.4× → page global on-call
- Single region burn 14.4× with < 20% traffic → ticket unless global impact
- Route 53 health check failure → page (edge failure invisible to app metrics)

CloudWatch: per-region composite alarms
Prometheus: federated metrics with region label, global recording rule

---

### Q5: Error Budget Exhausted Mid-Sprint

**Prompt:** Day 12 of month. Checkout budget at 5%. Product wants major feature launch Friday. Your call?

**Answer:**

Policy says red zone (< 10%): hard deploy freeze except incident fixes.

Conversation with product (data-driven):
- "85% of budget consumed by two incidents — postmortem actions incomplete"
- "Launch consumes estimated 2–5% budget based on canary history"
- "Risk: single incident exhausts budget → SLA breach → credits"

Options:
1. Delay launch to next month (preferred)
2. Launch to 1% canary with enhanced burn monitoring + auto-rollback
3. Launch if feature has independent rollback AND SRE staffed for 72h

Never: full rollout in red zone without executive exception documented.

---

## Ops Sim: Northstar Enterprise Checkout SLO Blind Spot

> Open only after attempting the learner-side drill.

### Executive diagnosis

The global checkout SLO is green because the recording rule dropped tier and region labels. Enterprise EU burns its monthly error budget while only support tickets notice.

A principal response separates the trigger from the amplifier and states the invariant before proposing capacity or repair. The answer should not say only "scale it" or "roll it back"; it must explain why this system failed this way.

### Evidence map

- `checkout_availability_global: 99.94%`
- `checkout_availability{tier="enterprise",region="eu"}: 98.61%`
- `slo_burn_rate_5m{global}: 1.1`
- `slo_burn_rate_5m{enterprise_eu}: 38`
- `payment_auth_success{enterprise_eu}: 92.8%`
- `alert_evaluations_missed_total: 0`
- Config clue: `slo.labels: [service]`
- Config clue: `slo.drop_labels: [tier,region,tenant_id]`
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

- `wait for global SLO to page`: lets a contractual slice burn because aggregate math looks healthy.
- `mute support tickets as anecdotal`: throws away a valid detection channel for slice-specific failures.
- `shift traffic without payment-region capacity`: improves a visible symptom while weakening the incident invariant or repair boundary.
- `change the SLO after the incident starts`: rewrites the promise during the outage instead of honoring the existing one.

### Capacity and blast radius

A principal answer gives at least one bound. Compute the affected slice, backlog or queue depth, derivative, safe downstream throughput, and time-to-exhaustion or time-to-drain. If those values are unknown, the safe move is to throttle and measure before scale/failover/replay.

Examples of the expected math:
- current backlog / safe drain rate = minimum repair duration
- free disk or pool headroom / growth rate = time-to-exhaustion
- affected tenants, SKUs, auctions, regions, orders, or carts from source-of-truth keys
- downstream provider/API/database quota that caps replay concurrency

### Repair and reconciliation

Source of truth: sliced checkout SLIs by tier/region/tenant plus payment authorization records.

Build the affected set from authoritative records in the incident window, not from cache, search, dashboards, or customer anecdotes alone. Repair must use stable idempotency or operation keys, be throttled to downstream headroom, and write an audit trail. Derived projections can be rebuilt after the invariant is safe.

### Durable fixes

- multi-window burn alerts for key slices
- label-retention tests for SLO rules
- error-budget policy per customer promise
- support signal escalation runbook

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

---


---
