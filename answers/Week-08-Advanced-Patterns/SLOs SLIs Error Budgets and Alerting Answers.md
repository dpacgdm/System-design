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

## Ops Sim: Northstar Error Budget Blind Spot

### Q1 - Layer & root cause

The SLO model hid contractual slices and alerted on resources instead of user-visible checkout outcomes.

A strong answer separates the trigger from retry, cache, routing, or observability amplifiers and states the invariant that cannot be violated.

### Q2/Q3 - Evidence

- `global_checkout_availability: 99.95%`
- `enterprise_eu_checkout_availability: 98.7%`
- `payment_auth_success_rate_enterprise_eu: 93%`
- `cpu_batch_workers: 96% noisy alert`
- `page_count_cpu_alerts_24h: 340`
- `alertmanager: route=cpu_high severity=page`
- `slo: slice labels dropped tenant_tier,region`
- `synthetic: using cached mock payment token`
- Config clue: `objective_global: 99.9`
- Config clue: `enterprise_checkout_objective: 99.99`

### Q4 - Red herrings

Do not trust fleet averages, shallow health checks, or resource alerts that are not tied to the affected user slice. Downstream lag and retries may be symptoms to control, but they do not automatically identify the first cause.

### Q5/Q6 - Safe first 15 minutes

1. Declare severity, name the invariant, and assign subsystem owners.
2. Freeze new deploys, rollouts, rebalances, schema changes, or bulk replays touching the path.
3. Stop the active amplifier called out in the config/timeline.
4. Shed or degrade noncritical work before weakening checkout, payment, inventory, or tenant isolation.
5. Verify with the primary SLI, the scarce-resource metric, and the lag/error derivative.
6. Start an affected-record ledger for repair before any manual replay.

### Q7 - Bad fixes

- `trust global average`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.
- `page on CPU without user symptom`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.
- `use synthetic that skips dependency`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.
- `reset error budget manually`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.

### Q8 - Capacity / blast radius

Quantify current usage, safe ceiling, growth rate, and time-to-exhaustion for queue/lag, connection or thread pools, disk/WAL/compaction, and affected business records. Scaling is only safe if the downstream dependency has headroom.

### Q9 - Correctness invariant

Accepted orders, money movement, inventory reservations, tenant isolation, and source-of-truth state must remain conservative. If the outcome is uncertain, mark it uncertain and reconcile instead of guessing.

### Q10 - Data repair

Use source-of-truth rows, stable idempotency keys, LSNs/offsets, and the incident window to define the repair set. Replay with duplicate suppression, throttle to downstream headroom, and record customer-visible corrections.

### Q11 - Durable fixes

- user-centric SLIs by critical slice.
- multi-window burn-rate alerts.
- page on actionable symptoms.
- synthetics covering real dependencies.

Acceptance criteria: the old failure is reproduced in a drill, the new guardrail pages before customer impact, and the unsafe configuration cannot be enabled without review.

### Q12/Q13 - Alerting and runbook

Page on SLO burn, correctness failures, lag derivative, and scarce-resource exhaustion in the affected slice. By T+10 include incident commander, service owner, data/platform owner, product/business owner, support, and security/payments if trust or money is involved. Pre-authorized: stop unsafe rollouts, shed noncritical work, conservative fallback. Senior approval: durability downgrade, destructive repair, broad failover, or accepting derived data as truth.

---
