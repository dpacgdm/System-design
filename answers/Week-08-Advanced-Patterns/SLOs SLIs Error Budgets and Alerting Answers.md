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
