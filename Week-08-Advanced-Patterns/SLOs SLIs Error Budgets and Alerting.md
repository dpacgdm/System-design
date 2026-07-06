# Week 8, Topic 2 — SLOs, SLIs, Error Budgets, and Alerting

> Reliability is not a property you install. It is a budget you spend deliberately. This module teaches how to measure user experience (SLIs), set targets that matter (SLOs), translate targets into allowed failure (error budgets), and alert on budget consumption (multi-window burn rates) — without waking on-call for noise. It connects directly to Week 6 circuit breakers: breakers protect dependencies; SLOs protect users.

---

## Learning Objectives

```
╔══════════════════════════════════════════════════════════════════╗
║   AFTER THIS TOPIC, YOU WILL BE ABLE TO:                         ║
╟──────────────────────────────────────────────────────────────────╢
║                                                                  ║
║   1. Select SLIs from user journeys — not from what your         ║
║      metrics happen to expose — and distinguish availability,    ║
║      latency, quality, and freshness SLIs                        ║
║                                                                  ║
║   2. Set SLO targets using tiering, historical baselines,        ║
║      and business constraints — and explain why 100% is wrong    ║
║                                                                  ║
║   3. Compute error budgets in minutes, requests, and dollars     ║
║      and use budget policy to govern releases and incidents      ║
║                                                                  ║
║   4. Design multi-window burn-rate alerts (14.4×, 6×, 3×, 1×)    ║
║      with PromQL and AWS CloudWatch Metric Math equivalents      ║
║                                                                  ║
║   5. Apply alerting philosophy: page on symptom, ticket on       ║
║      cause, runbook on everything, silence on vanity metrics     ║
║                                                                  ║
║   6. Structure on-call rotations, escalation, and triage         ║
║      SLAs for fast burns vs slow burns                           ║
║                                                                  ║
║   7. Classify incidents by severity (SEV1–SEV4) tied to SLO      ║
║      impact and error budget consumption                         ║
║                                                                  ║
║   8. Configure AWS CloudWatch alarms for SLO-style alerting      ║
║      including composite alarms and anomaly detection            ║
║                                                                  ║
║   9. Connect circuit breaker state (Week 6) to SLO degradation   ║
║      — when OPEN is good, when it hides budget burn, and how     ║
║      to alert on both                                            ║
╚══════════════════════════════════════════════════════════════════╝
```

**Prerequisite mental model.** An SLI is what users experience. An SLO is what you promise. An error budget is how much brokenness you can afford before you must stop shipping and start fixing. Alerting is not "something went wrong in the datacenter" — it is "we are spending the budget too fast, and a user will notice unless we act."

**Cross-module map:**

```
╔════════════════════════════════════════════════════════════════════╗
║   PRIOR MODULE              │  SLO / ALERTING CONNECTION           ║
╠════════════════════════════════════════════════════════════════════╣
║  Week 6: Circuit Breakers   │ Breakers fail-fast to protect        ║
║                               │ the fleet; SLOs measure whether    ║
║                               │ users still got served. An OPEN    ║
║                               │ breaker can IMPROVE availability   ║
║                               │ SLI (fast fallback) while          ║
║                               │ DEGRADING quality SLI (degraded    ║
║                               │ checkout). Alert on both.          ║
╠════════════════════════════════════════════════════════════════════╣
║  Week 6: Timeouts/Retries     │ Retry storms burn latency AND      ║
║                               │ availability budgets. Burn-rate    ║
║                               │ alerts catch storms before CPU     ║
║                               │ alerts do.                         ║
╠════════════════════════════════════════════════════════════════════╣
║  Week 5: Kafka ISR shrink     │ Leading indicator: page only       ║
║                               │ when correlated to SLO risk.       ║
║                               │ Otherwise: ticket.                 ║
╠════════════════════════════════════════════════════════════════════╣
║  Week 8 T1: Observability     │ Metrics/logs/traces FEED SLIs.     ║
║                               │ This module is the RELIABILITY     ║
║                               │ layer on top of the data layer.    ║
╚════════════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔═══════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Uptime = reliability"                             ║
╟───────────────────────────────────────────────────────────────────────╢
║   WRONG. A service can be "up" (HTTP 200, health check green)         ║
║   while users cannot complete checkout in under 30 seconds.           ║
║   Uptime measures YOUR process. SLIs measure USER outcomes.           ║
║   Fix: define SLIs from user journeys, not from /healthz.             ║
╠═══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "Alert when error_rate > SLO threshold"            ║
╟───────────────────────────────────────────────────────────────────────╢
║   WRONG for paging. A 5-minute window at 0.2% error rate when         ║
║   SLO is 99.9% (0.1% budget) fires constantly on noise AND misses     ║
║   slow burns at 0.05% sustained for 25 days.                          ║
║   Fix: multi-window burn-rate alerting.                               ║
╠═══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "100% availability is the goal"                    ║
╟───────────────────────────────────────────────────────────────────────╢
║   IMPOSSIBLE and harmful. Chasing 100% freezes deploys, blocks        ║
║   risky but valuable features, and hides the trade-off conversation.  ║
║   Fix: error budget policy. "We can ship until budget is 50% gone."   ║
╠═══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "More alerts = safer system"                       ║
╟───────────────────────────────────────────────────────────────────────╢
║   INVERTED. Alert fatigue causes real incidents to be ignored.        ║
║   The on-call who silences 40 Slack alerts/day will miss the one      ║
║   slow-burn that becomes a SEV1.                                      ║
║   Fix: fewer pages, more tickets, mandatory runbooks.                 ║
╠═══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Circuit breaker open = incident"                  ║
╟───────────────────────────────────────────────────────────────────────╢
║   INCOMPLETE. OPEN on fraud-svc with checkout fallback may be         ║
║   CORRECT behavior — availability SLI holds, quality SLI drops.       ║
║   Page when USER-FACING SLO burns, not when internal state flips.     ║
║   Exception: breaker open on CRITICAL path with no fallback.          ║
╠═══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #6: "SLOs are an SRE team deliverable"                 ║
╟───────────────────────────────────────────────────────────────────────╢
║   WRONG ownership model. Product sets user expectations.              ║
║   Engineering measures and meets them. SRE designs alerting.          ║
║   Everyone owns the error budget.                                     ║
╚═══════════════════════════════════════════════════════════════════════╝
```

---

## Core Teaching

### SLI, SLO, SLA, SLR — Definitions That Actually Hold Up

```
╔══════════════════════════════════════════════════════════════════╗
║   THE VOCABULARY (USE PRECISELY)                                 ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║   SLI (Service Level Indicator)                                  ║
║   ─────────────────────────────                                  ║
║   A quantitative measure of some aspect of the service.          ║
║   Always a ratio: good_events / valid_events                     ║
║   (sometimes valid_events is implicit).                          ║
║                                                                  ║
║   SLO (Service Level Objective)                                  ║
║   ─────────────────────────────                                  ║
║   A target value or range for an SLI over a measurement          ║
║   window. Internal. Engineering commitment.                      ║
║   Example: "99.9% of checkout requests succeed over 30 days."    ║
║                                                                  ║
║   SLA (Service Level Agreement)                                  ║
║   ─────────────────────────────                                  ║
║   A business contract with customers. Includes remedies          ║
║   (credits, penalties). ALWAYS looser than internal SLO.         ║
║   Example: "99.5% monthly uptime or 10% credit."                 ║
║   Never alert on SLA directly — alert on SLO with margin.        ║
║                                                                  ║
║   SLR (Service Level Requirement)                                ║
║   ───────────────────────────────                                ║
║   Product-level desire before engineering analysis.              ║
║   "Checkout should feel instant." → becomes SLI + SLO.           ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
```

**The relationship:**

```
Product SLR  →  Engineering SLI  →  SLO target  →  Error budget
                    ↓                              ↓
              Instrumentation                  Alerting policy
                    ↓                              ↓
              Dashboards                       On-call response
```

---

### SLI Selection — Start From the User Journey

The Google SRE workbook's core rule: **SLIs should measure user-perceived reliability**, not server health.

```
SLI SELECTION WORKFLOW
━━━━━━━━━━━━━━━━━━━━━━

Step 1: Map the critical user journey
  Example — E-commerce checkout:
    Browse → Add to cart → Apply promo → Pay → Confirmation email

Step 2: For each step, ask:
  "If this step fails or is slow, does the user care?"
  "Can they recover without contacting support?"

Step 3: Classify the SLI type

  ┌─────────────────────────────────────────────────────────────┐
  │ SLI TYPE      │ USER QUESTION           │ EXAMPLE           │
  ├─────────────────────────────────────────────────────────────┤
  │ Availability  │ Did it work?            │ HTTP 2xx/3xx rate │
  │ Latency       │ Was it fast enough?     │ % req < 500ms     │
  │ Quality       │ Was the result correct? │ % orders match    │
  │ Freshness     │ Was data current?       │ % reads < 60s old│
  └─────────────────────────────────────────────────────────────┘

Step 4: Define the ratio precisely

  availability_sli =
    count(requests where status NOT IN {500,502,503,504,429})
    ────────────────────────────────────────────────────────────
    count(requests where status NOT IN {400,401,403,404,422})
    ↑ exclude client errors from denominator — not your fault

Step 5: Validate you CAN measure it
  - Do you have the metric at the edge (where user sees it)?
  - Is cardinality bounded?
  - Can you slice by region/tier for diagnosis?
```

**Good SLIs vs bad SLIs:**

```
╔═════════════════════════════════════════════════════════════════╗
║   BAD SLI                          │ WHY BAD                    ║
╠═════════════════════════════════════════════════════════════════╣
║   CPU utilization < 80%            │ User doesn't see CPU       ║
║   Pod restart count                │ Restarts may be invisible  ║
║   /healthz returns 200             │ App can be "healthy" but   ║
║                                    │ returning stale data       ║
║   Database connection pool free    │ Internal resource metric   ║
║   Kafka consumer lag (alone)       │ Lag ≠ user impact unless   ║
║                                    │ tied to freshness SLI      ║
╠═════════════════════════════════════════════════════════════════╣
║   GOOD SLI                         │ WHY GOOD                   ║
╠═════════════════════════════════════════════════════════════════╣
║   % checkout POSTs returning 2xx   │ Direct user outcome        ║
║   % search results in < 200ms      │ Perceived performance      ║
║   % video starts within 2s         │ Quality-of-experience      ║
║   % dashboard data < 5 min stale   │ Freshness for analytics    ║
╚═════════════════════════════════════════════════════════════════╝
```

**Where to measure — the edge vs the service debate:**

```
MEASURE AT THE EDGE when:
  - User-facing latency includes CDN, LB, TLS
  - You care about end-to-end experience
  - Synthetic probes exercise the full path

MEASURE AT THE SERVICE when:
  - Edge includes third-party CDN you can't control
  - You need to attribute blame between services
  - SLO is per-team ownership boundary

BEST PRACTICE: BOTH
  - Edge SLI for customer-facing SLO
  - Service SLI for team accountability
  - Alert on edge; diagnose with service-level breakdown
```

**RED method as SLI shorthand (services):**

```
For each user-facing service:

  Rate     = requests/sec (context, not an SLI alone)
  Errors   = failed requests / total  → Availability SLI
  Duration = requests below threshold / total → Latency SLI

Example for checkout-svc:
  errors_sli   = 1 - (5xx_rate + timeout_rate)
  latency_sli  = histogram_share(le=0.8, checkout_duration_seconds)
```

**USE method for supporting infrastructure (NOT user SLIs):**

```
Utilization, Saturation, Errors on resources:
  - Postgres: disk util, replication lag, query errors
  - Redis: memory util, evictions, rejected connections
  - Kafka: under-min-ISR partitions, request queue time

These are CAUSE metrics. They feed runbooks.
They do NOT replace user-facing SLIs.
They MAY page as leading indicators when strongly correlated
to imminent SLO violation (Kafka under-min-ISR → producer errors
in 60–90s).
```

---

### SLI Specification Template

Use this template for every SLI you define:

```yaml
sli:
  name: checkout_availability
  description: >
    Proportion of checkout attempts that complete successfully
    from the user's perspective.
  user_journey: checkout → payment → confirmation
  type: availability
  
  good_events:
    predicate: |
      HTTP POST /api/v1/checkout
      AND status_code IN [200, 201]
      AND response.body.order_id IS NOT NULL
  
  valid_events:
    predicate: |
      HTTP POST /api/v1/checkout
      AND status_code NOT IN [400, 401, 403, 422]  # client errors excluded
      AND NOT (status_code = 429 AND retry_after IS NULL)  # optional: exclude rate-limit without guidance
  
  measurement_point: edge  # ALB access logs + synthetic probes
  
  labels_for_diagnosis:
    - region
    - deployment_version
    - payment_method
    # NOT user_id — cardinality explosion
  
  data_source:
    primary: prometheus histogram/counter from edge-svc
    secondary: CloudWatch ALB TargetResponseTime + HTTPCode_Target_5XX_Count
  
  known_gaps:
    - Mobile app offline queue not captured until sync
    - Stripe webhook failures counted separately (async SLI)
```

---

### SLO Target Setting — The Art and the Math

```
╔════════════════════════════════════════════════════════════════╗
║   SLO TARGET SELECTION FACTORS                                 ║
╠════════════════════════════════════════════════════════════════╣
║                                                                ║
║   1. USER EXPECTATIONS (product input)                         ║
║      Payments: "must never fail" → 99.95%+ availability        ║
║      Recommendations: "nice to have" → 99% may suffice         ║
║                                                                ║
║   2. HISTORICAL BASELINE (data input)                          ║
║      If p99 latency has been 280ms for 6 months, setting       ║
║      SLO at 200ms guarantees permanent budget burn.            ║
║      SLO should be slightly BELOW historical worst-case good   ║
║      week, not aspirational fantasy.                           ║
║                                                                ║
║   3. DEPENDENCY CHAIN (architecture input)                     ║
║      5-hop chain at 99.9% each → 99.5% end-to-end theoretical  ║
║      Compound: 0.999^5 = 0.995 (roughly)                       ║
║      Per-service SLO must be HIGHER than user-facing SLO.      ║
║                                                                ║
║   4. COST OF FAILURE (business input)                          ║
║      $8M/day GMV checkout vs internal admin tool               ║
║      Tier-0 vs Tier-3 classification                           ║
║                                                                ║
║   5. COST OF ACHIEVING (engineering input)                     ║
║      99.9% → 99.99% is 10× harder, not 0.09% harder            ║
║      Each nine costs exponentially more infra + toil           ║
║                                                                ║
╚════════════════════════════════════════════════════════════════╝
```

**The nines table — memorize:**

```
╔═════════════════════════════════════════════════════════════════╗
║   SLO        │ ALLOWED BAD   │ PER MONTH (30d) │ PER YEAR       ║
╠═════════════════════════════════════════════════════════════════╣
║   90%        │ 10%           │ 3 days          │ 36.5 days      ║
║   99%        │ 1%            │ 7.2 hours       │ 3.65 days      ║
║   99.9%      │ 0.1%          │ 43.2 min        │ 8.76 hours     ║
║   99.95%     │ 0.05%         │ 21.6 min        │ 4.38 hours     ║
║   99.99%     │ 0.01%         │ 4.32 min        │ 52.6 min       ║
║   99.999%    │ 0.001%        │ 26 sec          │ 5.26 min       ║
╚═════════════════════════════════════════════════════════════════╝

Calculation:
  allowed_bad_fraction = 1 - SLO
  minutes_per_month = 30 × 24 × 60 × allowed_bad_fraction
                     = 43,200 × allowed_bad_fraction
```

**Service tiering example:**

```
TIER 0 — Revenue-critical (checkout, payments, auth)
  Availability: 99.95% (21.6 min/month budget)
  Latency: 99% < 800ms (checkout p99 SLO)
  Page: any fast burn on either SLI
  Error budget policy: freeze risky deploys at 25% remaining

TIER 1 — Core product (search, cart, product catalog)
  Availability: 99.9% (43.2 min/month)
  Latency: 99% < 500ms for reads
  Page: fast burn; ticket: slow burn

TIER 2 — Supporting (saved cart, wishlist, recommendations)
  Availability: 99.5% (216 min/month)
  Latency: 99% < 300ms
  Ticket: most burns; page only if cascading to Tier 0

TIER 3 — Internal (admin dashboards, batch reports)
  Availability: 99% (7.2 hours/month)
  Latency: best effort
  Ticket/Slack only; no pages unless blocking Tier 0
```

**Latency SLOs — percentile choice:**

```
DO NOT set SLO on mean latency. Ever.
  Mean hides tail. Users hit the tail.

Common choices:
  p95 for "typical worst case"
  p99 for user-facing APIs
  p99.9 for large-scale systems where tail matters at volume

Latency SLI formula:
  latency_sli = count(requests where duration < threshold) / count(valid_requests)

Example:
  "99% of checkout requests complete in < 800ms over 30 days"
  threshold = 800ms
  SLI = requests_under_800ms / total_checkout_requests

Separate availability and latency into TWO SLIs.
  A fast 500 is not success.
  A slow 200 is not success for latency SLI.
  A request can fail BOTH SLIs simultaneously.
```

**SLO window selection:**

```
ROLLING 30-DAY WINDOW (recommended default):
  - Smooths weekly seasonality
  - Aligns with monthly business cycles
  - Burn-rate math in Google workbook assumes 30 days

CALENDAR MONTH:
  - Easier for SLA reporting to finance
  - Cliff effect at month boundary

ROLLING 7-DAY:
  - More aggressive; good for new services finding baseline
  - Budget is smaller; burns faster

FIXED QUARTER:
  - Enterprise/regulated environments
  - Slow feedback loop — avoid for operational alerting
```

---

### Error Budgets — Policy, Not Just Math

```
╔══════════════════════════════════════════════════════════════════╗
║   ERROR BUDGET = 1 - SLO                                         ║
║   The deliberately allocated amount of UNRELIABILITY.            ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║   SLO 99.9% → budget 0.1% = 43.2 minutes/month of failure        ║
║                                                                  ║
║   YOU ARE SUPPOSED TO SPEND IT.                                  ║
║   Budget funds:                                                  ║
║     - Risky deploys                                              ║
║     - Chaos experiments                                          ║
║     - Dependency upgrades                                        ║
║     - Feature launches without infinite QA                       ║
║                                                                  ║
║   When budget is EXHAUSTED:                                      ║
║     - Stop feature releases                                      ║
║     - Focus engineering on reliability work                      ║
║     - Escalate to leadership                                     ║
║                                                                  ║
║   When budget is UNDER-SPENT (quarter end, >50% remaining):      ║
║     - SLO may be too loose — tighten next quarter                ║
║     - Or: take more calculated risks                             ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
```

**Error budget policy document (template):**

```
POLICY: Checkout Error Budget (99.9% / 30-day rolling)

BUDGET: 43.2 minutes of downtime equivalent per month

CONSUMPTION TRACKING:
  - Real-time dashboard: budget remaining %
  - Weekly email to eng + product
  - Post-incident: deduct actual impact from budget

THRESHOLDS:
  > 50% remaining (green):
    Normal operations. Deploy freely with standard canaries.

  25–50% remaining (yellow):
    Extra scrutiny on deploys. Require SRE approval for
    changes touching checkout path. No experimental flags > 5%.

  10–25% remaining (orange):
    Deploy freeze for non-fix changes.
    Daily standup on reliability until budget recovers.

  < 10% remaining (red):
    Hard deploy freeze except incident fixes.
    Product notified. Reliability work prioritized.

  0% (exhausted):
    All hands reliability review.
    Postmortem for every budget-consuming event that month.

RECOVERY:
  Budget recovers continuously on rolling window —
  not instant. A 30-minute outage consumes ~70% of monthly
  budget; recovery takes ~21 days of perfect performance.
```

**Translating budget to business terms:**

```
For Glasswing ($8M/day GMV, checkout SLO 99.9%):

  43.2 min/month budget ≈ 0.1% of checkout attempts may fail

  If checkout attempts = 500K/day:
    Allowed failures ≈ 500/day
    At $160 average order value and 70% conversion after checkout start:
      ~$56K/day theoretical revenue at risk IF all failures
      were lost sales (upper bound — many retry)

  Use this for executive communication:
    "This incident consumed 18% of our monthly error budget
     in 12 minutes — equivalent to ~$400K exposure."
```

---

### Burn Rate — The Math That Makes Alerting Work

```
BURN RATE DEFINITION
━━━━━━━━━━━━━━━━━━━━

  burn_rate = (current error rate) / (error budget rate)

  error budget rate = 1 - SLO
                      ─────────────
                      measurement window in same units

  For 99.9% over 30 days:
    budget rate = 0.001 per 30 days
                = 0.001 / (30 × 24 × 60) per minute
                ≈ 2.31 × 10⁻⁷ per minute

  burn_rate = 1  → consuming budget exactly on pace to exhaust
                   at end of window
  burn_rate = 14.4 → consuming 14.4× faster → budget gone in ~2 days
  burn_rate = 6  → budget gone in ~5 days
  burn_rate = 0  → perfect reliability (budget accumulating)
```

**Why naive thresholds fail:**

```
NAIVE: alert if error_rate > 0.1% for 5 minutes

Problem A — FALSE POSITIVES:
  At 99.9% SLO, budget = 0.1%.
  A 5-minute spike to 0.15% consumes:
    0.15% × (5/43200) ≈ 0.0017% of monthly budget — negligible.
  But you page 50 times/month on transient blips.

Problem B — FALSE NEGATIVES:
  Sustained 0.05% error rate for 25 days:
    Consumes 50% of budget silently.
    Never exceeds 0.1% in any 5-minute window.
    No page until budget exhausted on day 28.

Problem C — WRONG DENOMINATOR:
  Low traffic at 3am: 2 errors in 10 requests = 20% error rate.
  High traffic at noon: 200 errors in 100K = 0.2% — same alert threshold,
  vastly different significance.
```

**Multi-window burn rate — the Google SRE workbook approach:**

```
╔════════════════════════════════════════════════════════════════╗
║   TIER │ LONG WIN │ SHORT WIN │ BURN │ BUDGET USED │ ACTION    ║
╠════════════════════════════════════════════════════════════════╣
║   1    │ 1h       │ 5m        │ 14.4×│ 2% in 1h    │ PAGE      ║
║   2    │ 6h       │ 30m       │ 6×   │ 5% in 6h    │ PAGE/BH   ║
║   3    │ 24h      │ 2h        │ 3×   │ 10% in 24h  │ TICKET    ║
║   4    │ 3d       │ 6h        │ 1×   │ 10% in 3d   │ SLACK     ║
╚════════════════════════════════════════════════════════════════╝

BH = page during business hours only (optional tier)

BOTH windows must breach simultaneously:
  - Short window: "is this happening RIGHT NOW?"
  - Long window: "is this REAL or a blip?"
  - Combined: ~10× fewer false positives vs single window
```

**Deriving the magic numbers (14.4, 6, 3, 1):**

```
Goal: fire when consuming X% of monthly budget in alert window T

For 30-day window, budget fraction B = 1 - SLO

Tier 1 example:
  Alert if we consume 2% of monthly budget in 1 hour.
  
  budget_consumed_in_1h = burn_rate × (1h / 30d) × B
  0.02 = burn_rate × (1 / 720) × 0.001   [for 99.9% SLO]
  
  Solving: burn_rate = 0.02 × 720 / 0.001 = 14.4

Tier 2:
  5% in 6h → burn_rate = 0.05 × (720/6) / 0.001 = 6

Tier 4:
  10% in 3d (72h) → burn_rate = 0.10 × (720/72) / 0.001 = 1

These are STARTING POINTS. Tune after 30–60 days of data.
```

**PromQL — availability fast burn (Tier 1):**

```yaml
# SLO: 99.9% availability, 30-day window, error budget = 0.1%
# Tier 1: 14.4× burn, 5m + 1h windows

groups:
  - name: checkout_slo
    rules:
      - record: checkout:availability_sli_5m
        expr: |
          1 - (
            sum(rate(http_requests_total{route="/checkout",status=~"5.."}[5m]))
            /
            sum(rate(http_requests_total{route="/checkout",status!~"4.."}[5m]))
          )

      - record: checkout:availability_sli_1h
        expr: |
          1 - (
            sum(rate(http_requests_total{route="/checkout",status=~"5.."}[1h]))
            /
            sum(rate(http_requests_total{route="/checkout",status!~"4.."}[1h]))
          )

      - alert: CheckoutAvailabilityFastBurn
        expr: |
          (
            (1 - checkout:availability_sli_5m) > (14.4 * 0.001)
            and
            (1 - checkout:availability_sli_1h) > (14.4 * 0.001)
            and
            sum(rate(http_requests_total{route="/checkout"}[5m])) > 0.5
          )
        for: 2m
        labels:
          severity: page
          slo: checkout_availability
          tier: "1"
          runbook: https://wiki.example.com/runbooks/checkout-fast-burn
        annotations:
          summary: "Checkout availability burning at ≥14.4× (fast burn)"
          description: |
            Error rate exceeded 1.44% (14.4 × 0.1% budget) in both
            5m and 1h windows. At this rate, 30-day error budget
            exhausts in ~2 days.
            
            TRIAGE (mandatory):
            1. Open Grafana: Checkout SLO dashboard
            2. Check 5xx breakdown by status code and deployment
            3. Open traces: service=checkout-svc, status>=500, 15m
            4. Check circuit breaker states (Week 6 dashboard)
            5. If unclear in 10 min → escalate in #incidents
          dashboard: https://grafana.example.com/d/checkout-slo
```

**PromQL — latency fast burn (Tier 1):**

```yaml
      - record: checkout:latency_sli_5m
        expr: |
          sum(rate(http_request_duration_seconds_bucket{
            route="/checkout",le="0.8"
          }[5m]))
          /
          sum(rate(http_request_duration_seconds_count{
            route="/checkout",status!~"5.."
          }[5m]))

      - alert: CheckoutLatencyFastBurn
        expr: |
          (
            (1 - checkout:latency_sli_5m) > (14.4 * 0.01)
            and
            (1 - checkout:latency_sli_1h) > (14.4 * 0.01)
          )
        for: 2m
        labels:
          severity: page
          slo: checkout_latency
```

Note: latency SLO 99% → budget = 1% = 0.01 in formulas.

**Recording rules for burn-rate dashboard:**

```yaml
      - record: checkout:burn_rate_1h
        expr: |
          (1 - checkout:availability_sli_1h) / 0.001

      - record: checkout:error_budget_remaining
        expr: |
          1 - (
            (1 - avg_over_time(checkout:availability_sli_1h[30d]))
            / 0.001
          )
```

---

### Alerting Philosophy — Pages, Tickets, and Silence

```
╔══════════════════════════════════════════════════════════════════╗
║   THE ALERTING HIERARCHY                                         ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║   PAGE (PagerDuty/Opsgenie — wakes a human)                      ║
║   ─────────────────────────────────────────                      ║
║   Criteria: user-visible SLO at risk within minutes              ║
║   Volume target: < 2 pages/on-call shift (excluding SEV1)        ║
║   Every page MUST have runbook + dashboard link                  ║
║                                                                  ║
║   TICKET (Jira/Linear — next business day)                       ║
║   ────────────────────────────────────────                       ║
║   Criteria: slow burn, leading indicator, non-urgent drift       ║
║   Examples: 6× burn, pg_stat drift, disk 70%                     ║
║                                                                  ║
║   SLACK/EMAIL (informational)                                    ║
║   ───────────────────────────                                    ║
║   Criteria: awareness, daily summaries, budget reports           ║
║   Examples: 1× slow burn, deploy notifications                   ║
║                                                                  ║
║   DASHBOARD ONLY (no notification)                               ║
║   ────────────────────────────────                               ║
║   Criteria: diagnostic context, historical trends                ║
║   Examples: CPU graphs, pool utilization                         ║
║                                                                  ║
║   SILENCE (delete the alert)                                     ║
║   ──────────────────────────                                     ║
║   Criteria: no action defined, no runbook, no owner              ║
║   "Alert that fires with no runbook" is technical debt.          ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
```

**Symptom vs cause — the principal's rule:**

```
PAGE ON SYMPTOM:
  ✓ Checkout error rate burning budget at 14.4×
  ✓ Checkout p99 latency SLO violation
  ✓ Synthetic probe failure on payment flow
  ✓ Error budget < 10% remaining

TICKET ON CAUSE (usually):
  ✓ Postgres CPU > 70%
  ✓ Redis memory > 80%
  ✓ Kafka under-min-ISR (unless no symptom alert exists — then page as leading)
  ✓ Circuit breaker OPEN on non-critical path with fallback

NEVER PAGE:
  ✗ CPU > 90% with no SLO impact
  ✗ Pod restarted (Kubernetes handled it)
  ✗ Certificate expires in 30 days (ticket at 14 days)
  ✗ Disk 75% (ticket unless growth rate → full in 4h)
```

**Alert quality checklist — every alert must pass:**

```
□ Can I draw a line from this alert to user impact?
□ Is there a runbook with first 3 diagnostic steps?
□ Is there a dashboard linked in the annotation?
□ Is severity correct (page vs ticket)?
□ Is there a "for: X" or multi-window guard against flapping?
□ Is there a minimum traffic threshold?
□ Is there an owner team label?
□ When did we last review this alert? (quarterly)
□ What is the false-positive rate? (track ack-without-action)
```

**The five alerting pathologies:**

```
1. ALERT FATIGUE
   Cause: paging on cause metrics
   Fix: SLO-based paging only; demote the rest

2. FLAPPING
   Cause: threshold oscillation
   Fix: for: 2m, multi-window burn rates, hysteresis

3. PAGE-ON-CAUSE
   Cause: "DB CPU high" without user correlation
   Fix: symptom-first; cause in runbook step 2

4. NO RUNBOOK
   Cause: alert added under pressure, never documented
   Fix: no merge without runbook URL in annotation

5. SILENT FAILURE
   Cause: failure mode not in alert set
   Fix: user-facing SLOs + synthetic monitoring + low-volume
        "counter hasn't incremented" alerts
```

---

### On-Call — Structure, Expectations, and Sustainability

```
ON-CALL IS A SERVICE TO THE PRODUCT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Rotation design:
  - Primary: 7-day rotation, handoff Monday 10:00 local
  - Secondary: backup for escalation / primary unreachable
  - Shadow: new engineer for 2 rotations before solo
  - Manager: not in rotation; available for SEV1 escalation

Handoff requirements:
  - Written handoff doc: open incidents, flaky alerts, in-flight deploys
  - Review error budget status for Tier-0 services
  - Acknowledge all open tickets assigned to on-call

Response SLAs (Tier-0 SLO pages):
  ┌────────────────────────────────────────────────────────────┐
  │ Severity │ Acknowledge │ Mitigation start │ Update cadence │
  ├────────────────────────────────────────────────────────────┤
  │ SEV1     │ 5 min       │ 15 min           │ 15 min         │
  │ SEV2     │ 15 min      │ 30 min           │ 30 min         │
  │ SEV3     │ 1 hour      │ 4 hours          │ 2 hours        │
  │ SEV4     │ 4 hours     │ next day         │ daily          │
  └────────────────────────────────────────────────────────────┘

Slow-burn triage SLA (Slack/ticket alerts):
  - Acknowledge within 2 hours during business hours
  - Written triage note within 30 min of ack:
    "Investigated / not investigated because X / escalated because Y"
  - If burn rate > 3× for 4+ hours → escalate to page

On-call load targets:
  - < 2 pages per 12-hour night shift (excluding SEV1)
  - If exceeded 2 weeks running → alert review mandatory
  - "Hero culture" is a bug — recurring pages = fix the system

Compensation and sustainability:
  - Time off after SEV1 (> 4 hours overnight)
  - No feature work during on-call week (or 50% capacity)
  - Quarterly review of page volume per rotation
```

**Incident commander vs on-call:**

```
ON-CALL ENGINEER:
  - First responder
  - Runs triage runbook
  - Gathers data, applies known fixes
  - Escalates if stuck > 15 min on SEV1

INCIDENT COMMANDER (SEV1/SEV2):
  - Coordinates cross-team response
  - External communication (status page, support)
  - Tracks timeline, assigns workstreams
  - NOT necessarily the best debugger — the best coordinator

Runbook for on-call first 5 minutes:
  1. Ack page in PagerDuty (< 5 min)
  2. Open linked dashboard — confirm alert is real (not flapping)
  3. Check #deploys channel — correlate with recent change
  4. Post in #incidents: "Investigating CheckoutFastBurn, IC: self"
  5. Follow runbook diagnostic steps
  6. If customer impact confirmed → declare SEV level
  7. If not resolved in SLA → escalate to secondary + IC pool
```

---

### Incident Severity — Tied to SLO Impact

```
╔══════════════════════════════════════════════════════════════════╗
║   SEVERITY DEFINITIONS (SLO-ALIGNED)                             ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║   SEV1 — CRITICAL                                                ║
║   ───────────────                                                ║
║   Active or imminent Tier-0 SLO violation affecting ALL or       ║
║   most users. Error budget burning at 14.4×+.                    ║
║   Examples: checkout down, auth broken, data corruption          ║
║   Response: all-hands, status page, exec notification            ║
║   Error budget: may consume 25–100% in one incident              ║
║                                                                  ║
║   SEV2 — MAJOR                                                   ║
║   ─────────────                                                  ║
║   Significant degradation: subset of users or partial Tier-0     ║
║   SLO miss. 6× burn rate.                                        ║
║   Examples: one region down, payment method failing, p99 3×      ║
║   Response: dedicated bridge, hourly updates                     ║
║   Error budget: 5–25% consumed                                   ║
║                                                                  ║
║   SEV3 — MINOR                                                   ║
║   ─────────────                                                  ║
║   Limited impact, workaround exists, Tier-1+ affected.           ║
║   3× burn or slow degradation.                                   ║
║   Examples: recommendations broken, slow cart for 10% users      ║
║   Response: business-hours fix, ticket + Slack                   ║
║   Error budget: 1–5% consumed                                    ║
║                                                                  ║
║   SEV4 — LOW                                                     ║
║   ────────────                                                   ║
║   Minimal user impact, internal-only, cosmetic.                  ║
║   Examples: admin dashboard stale, non-critical batch delayed    ║
║   Response: normal sprint priority                               ║
║   Error budget: negligible                                       ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
```

**Severity decision tree:**

```
START: Alert fired or customer report received

├─ Is Tier-0 SLO actively violated RIGHT NOW?
│  ├─ YES, all users → SEV1
│  └─ YES, subset → SEV2
│
├─ Is burn rate ≥ 14.4× on Tier-0?
│  └─ YES → SEV1 (imminent)
│
├─ Is burn rate ≥ 6× on Tier-0?
│  └─ YES → SEV2
│
├─ Is there a workaround for most users?
│  ├─ NO → bump one severity level
│  └─ YES → SEV3
│
└─ Internal-only impact?
   └─ YES → SEV4
```

**Severity ↔ error budget accounting:**

```
After every SEV1/SEV2 incident, calculate:

  impact_minutes = duration × affected_user_fraction
  
  budget_consumed = impact_minutes / allowed_minutes_per_month
  
  Example:
    12-min checkout degradation, 100% users
    budget_consumed = 12 / 43.2 = 27.8% of monthly budget

Record in postmortem. Feed weekly reliability review.
Product sees: "March budget: 62% remaining after 2 incidents."
```

---

### AWS CloudWatch Alarms for SLO-Style Alerting

```
CLOUDWATCH vs PROMETHEUS — WHEN TO USE WHICH
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CloudWatch native when:
  - AWS-native metrics (ALB, API Gateway, Lambda, RDS)
  - Organization standard is AWS Observability
  - Metric Streams → third-party (optional)

Prometheus/Grafana when:
  - Kubernetes workload metrics
  - Custom application metrics with complex PromQL
  - Multi-cloud unified alerting

Many teams: CloudWatch for infra + ALB edge SLIs,
             Prometheus for service-level SLIs,
             Alertmanager + PagerDuty for unified routing.
```

**ALB metrics as edge SLI source:**

```
Key metrics:
  HTTPCode_Target_5XX_Count     → availability numerator (bad)
  RequestCount                  → denominator
  TargetResponseTime            → latency (statistic: p99)
  HTTPCode_Target_4XX_Count     → usually exclude from SLO

Availability SLI from ALB (5-minute granularity):
  sli = 1 - (Target5XX / (RequestCount - Target4XX))

CloudWatch Metric Math:
  m1 = HTTPCode_Target_5XX_Count (Sum, 5min)
  m2 = RequestCount (Sum, 5min)
  m3 = HTTPCode_Target_4XX_Count (Sum, 5min)
  availability = 1 - (m1 / (m2 - m3))
```

**CloudWatch alarm — fast burn equivalent:**

```json
{
  "AlarmName": "CheckoutAvailability-FastBurn-5m",
  "AlarmDescription": "Checkout 5xx rate exceeds 14.4× error budget (1.44%) over 5m. Runbook: https://wiki/runbooks/checkout",
  "Metrics": [
    {
      "Id": "errors",
      "MetricStat": {
        "Metric": {
          "Namespace": "AWS/ApplicationELB",
          "MetricName": "HTTPCode_Target_5XX_Count",
          "Dimensions": [
            {"Name": "LoadBalancer", "Value": "app/checkout-alb/abc123"}
          ]
        },
        "Period": 300,
        "Stat": "Sum"
      },
      "ReturnData": false
    },
    {
      "Id": "total",
      "MetricStat": {
        "Metric": {
          "Namespace": "AWS/ApplicationELB",
          "MetricName": "RequestCount",
          "Dimensions": [
            {"Name": "LoadBalancer", "Value": "app/checkout-alb/abc123"}
          ]
        },
        "Period": 300,
        "Stat": "Sum"
      },
      "ReturnData": false
    },
    {
      "Id": "error_rate",
      "Expression": "errors / IF(total > 100, total, 100)",
      "Label": "5xx Error Rate",
      "ReturnData": true
    }
  ],
  "Threshold": 0.0144,
  "ComparisonOperator": "GreaterThanThreshold",
  "EvaluationPeriods": 2,
  "DatapointsToAlarm": 2,
  "TreatMissingData": "notBreaching",
  "AlarmActions": ["arn:aws:sns:us-east-1:123456789:checkout-pages"]
}
```

**Composite alarm — multi-window equivalent:**

CloudWatch lacks native AND across different period lengths in one alarm.
Use composite alarms:

```json
{
  "AlarmName": "CheckoutAvailability-FastBurn-Composite",
  "AlarmRule": "ALARM(CheckoutFastBurn-5m) AND ALARM(CheckoutFastBurn-1h)",
  "AlarmActions": ["arn:aws:sns:us-east-1:123456789:checkout-pages"]
}
```

Create two underlying alarms:
- `CheckoutFastBurn-5m`: Period=300, threshold=0.0144, EvaluationPeriods=2
- `CheckoutFastBurn-1h`: Period=3600, threshold=0.0144, EvaluationPeriods=1

**Lambda SLO alarm pattern:**

```json
{
  "AlarmName": "PaymentProcessor-Errors-FastBurn",
  "Metrics": [
    {
      "Id": "errors",
      "MetricStat": {
        "Metric": {
          "Namespace": "AWS/Lambda",
          "MetricName": "Errors",
          "Dimensions": [
            {"Name": "FunctionName", "Value": "payment-processor"}
          ]
        },
        "Period": 300,
        "Stat": "Sum"
      },
      "ReturnData": false
    },
    {
      "Id": "invocations",
      "MetricStat": {
        "Metric": {
          "Namespace": "AWS/Lambda",
          "MetricName": "Invocations",
          "Dimensions": [
            {"Name": "FunctionName", "Value": "payment-processor"}
          ]
        },
        "Period": 300,
        "Stat": "Sum"
      },
      "ReturnData": false
    },
    {
      "Id": "error_rate",
      "Expression": "100 * errors / invocations",
      "ReturnData": true
    }
  ],
  "Threshold": 1.44,
  "ComparisonOperator": "GreaterThanThreshold"
}
```

**CloudWatch Anomaly Detection — slow burn helper:**

```
For metrics without clear thresholds (latency drift):

  1. Enable anomaly detection on TargetResponseTime p99
  2. Alarm when metric exceeds band for 6 consecutive periods
  3. Route to TICKET, not page (high false-positive rate)
  4. Combine with SLO burn-rate for page decision

Anomaly detection is NOT a replacement for burn-rate alerting.
It is a triage accelerator for slow burns.
```

**Metric Streams → Prometheus pattern:**

```
If unified PromQL is required but metrics originate in CloudWatch:

  CloudWatch Metric Streams → Kinesis Firehose → Prometheus remote write
  
  Then use standard burn-rate PromQL on ALB metrics.
  
  Cost consideration: high-cardinality custom metrics in CloudWatch
  are expensive ($0.30/metric/month). Prefer embedded metric format
  with bounded dimensions.
```

**SNS → PagerDuty integration:**

```
SNS topic: checkout-pages
  → PagerDuty CloudWatch integration
  → Service: Checkout (Tier-0)
  → Escalation: primary 5min → secondary 10min → manager 20min

SNS topic: checkout-tickets
  → Jira automation OR Slack webhook
  → No PagerDuty routing
```

---

### Connecting to Week 6 Circuit Breakers

Circuit breakers and SLOs operate at different layers but must align.

```
╔════════════════════════════════════════════════════════════════╗
║   CIRCUIT BREAKER STATE  │  SLO IMPACT                         ║
╠════════════════════════════════════════════════════════════════╣
║   CLOSED (normal)        │  Baseline SLI measurement           ║
║   OPEN (fail-fast)       │  Depends on fallback:               ║
║                          │    Good fallback → availability OK  ║
║                          │    No fallback → availability ↓     ║
║                          │    Degraded path → quality SLI ↓    ║
║   HALF-OPEN (probing)    │  Latency variance; watch p99        ║
║   slowCallRate tripped   │  Latency SLI burns before errors    ║
╚════════════════════════════════════════════════════════════════╝
```

**Scenario: fraud-svc circuit breaker OPEN**

```
From Week 6 incident pattern:

  checkout-svc → fraud-svc: breaker OPEN after failure rate > 50%
  Fallback: MANUAL_REVIEW flag, checkout continues

  Availability SLI: HOLDS (checkout returns 200)
  Quality SLI: DEGRADED (orders flagged for manual review)
  Latency SLI: may IMPROVE (skip 2s fraud call)

  WRONG alert: "fraud-svc circuit breaker OPEN" → page
  RIGHT alert: "checkout quality SLI degraded" OR
               "manual_review_queue_depth > threshold" → ticket
  PAGE only if: fallback fails AND checkout availability burns
```

**When circuit breaker OPEN should page:**

```
Page if ALL of:
  1. Breaker on CRITICAL path (payments, auth)
  2. No fallback OR fallback also failing
  3. User-facing availability or latency SLO burning

Ticket if:
  - Breaker OPEN with working fallback
  - Degraded mode documented and within quality SLO

Dashboard (always):
  - resilience4j_circuitbreaker_state{name="*"}
  - Correlation panel: breaker state vs checkout SLI
```

**Retry storms and SLO burn — the cascade:**

```
From Week 6:

  payments-db slow → payments-svc retries 3× → pool saturated
  → checkout-svc timeouts → 504s at edge

  Circuit breaker should: OPEN on payments-db, fail-fast
  SLO alert should: fire on checkout availability burn-rate
  Leading indicator: payments-svc retry count, pool saturation

  Alert layering:
    L1 (page): checkout availability 14.4× burn
    L2 (ticket): payments-svc retry_rate > 3× baseline
    L3 (dashboard): circuit breaker state, bulkhead utilization

  Fix order:
    1. Stop the bleeding (OPEN breaker, shed load)
    2. Verify SLO recovery (burn rate declining)
    3. Root cause (DB query, missing timeout)
```

**slowCallRateThreshold and latency SLO:**

```
Week 6 config:
  slowCallRateThreshold: 80%
  slowCallDurationThreshold: 2s

This trips BEFORE error rate spikes — good.

Tie to SLO:
  If fraud-svc p99 normally 50ms, SLO threshold 300ms:
    Set slowCallDurationThreshold = 500ms (not 2s)
    Align breaker sensitivity with latency SLO headroom

  Mismatch example:
    slowCallDurationThreshold = 2s
    latency SLO = 99% < 800ms end-to-end
    Breaker stays CLOSED while latency SLI burns for hours
    → exactly the "slow burn" failure mode
```

**Bulkhead saturation as leading indicator:**

```
Week 6: bulkhead queueCapacity=0 on payment paths

Metric: resilience4j_bulkhead_available_concurrent_calls = 0
        sustained for 60s

This is NOT an SLO — it is a leading indicator.

Alert policy:
  - Ticket if bulkhead saturated + latency SLI burn < 3×
  - Page if bulkhead saturated + latency SLI burn ≥ 6×
  - Never page on bulkhead alone
```

---

## Concrete Examples

### Example 1: Checkout Availability — Full Stack

```
SERVICE: checkout-svc (Tier-0)
USER JOURNEY: POST /api/v1/checkout → payment → confirmation

SLI (availability):
  good = HTTP 200/201 with order_id in response
  valid = all requests except 4xx client errors
  measure_at = ALB (edge) + checkout-svc (attribution)

SLO: 99.95% over rolling 30 days
  budget = 0.05% = 21.6 minutes/month

ALERT TIERS:
  Tier 1: 14.4×, 5m+1h → page
  Tier 2: 6×, 30m+6h → page (business hours)
  Tier 3: 3×, 2h+24h → ticket
  Tier 4: 1×, 6h+3d → Slack

INSTRUMENTATION:
  Prometheus: http_requests_total{route="/checkout",status="..."}
  CloudWatch: ALB HTTPCode_Target_5XX_Count / RequestCount
  Synthetic: Route53 health check + canary every 60s

RUNBOOK FIRST STEPS:
  1. Grafana checkout-slo dashboard → confirm burn rate
  2. kubectl rollout history checkout-svc → recent deploy?
  3. Traces: checkout-svc, status>=500, last 15m
  4. Circuit breaker panel → any OPEN on critical deps?
  5. Postgres + Redis dashboards → cause investigation
```

### Example 2: Search Latency SLI

```
SERVICE: search-svc (Tier-1)
USER JOURNEY: GET /api/v1/search?q=...

SLI (latency):
  good = duration < 200ms
  valid = status != 5xx (errors excluded from latency SLI)
  
SLO: 99% of requests < 200ms over 30 days
  budget = 1% slow requests

Why 200ms:
  Historical p99 = 165ms for 90 days
  Doherty threshold: < 400ms feels responsive
  200ms gives headroom without being unachievable

PromQL latency SLI:
  sum(rate(http_request_duration_seconds_bucket{route="/search",le="0.2"}[5m]))
  /
  sum(rate(http_request_duration_seconds_count{route="/search",status!~"5.."}[5m]))

Burn threshold for Tier 1:
  (1 - latency_sli) > (14.4 * 0.01)   # 14.4% slow in window

Common failure: caching layer cold after deploy
  → latency SLI burns, availability holds
  → ticket at Tier 3 unless checkout depends on search (it doesn't)
```

### Example 3: Async Pipeline Freshness SLI

```
SERVICE: order-confirmation email (Tier-1, async)
USER JOURNEY: checkout completes → email within 5 minutes

SLI (freshness):
  good = email_sent_timestamp - order_created_timestamp < 300s
  valid = orders where email_required = true

SLO: 99.5% of confirmation emails within 5 minutes (30-day)

Measurement:
  NOT HTTP metrics — event timestamps:
    order_created event (Kafka)
    email_sent event (Kafka)
  Join on order_id in metrics pipeline or batch SLI calculator

Alert:
  freshness_sli_1h < 0.995 for 2h → ticket
  freshness_sli_1h < 0.99 for 1h → page (massive backlog)

Why separate from checkout availability:
  Checkout can succeed while email queue backs up.
  User sees "order confirmed" but no email → support tickets.
  Quality/freshness SLI catches this.
```

### Example 4: Saved-Cart Feature (Tier-2)

```
From Observability.md Q2 — expanded:

SLIs:
  1. Write availability: PUT/DELETE success rate (exclude 4xx)
  2. Read latency: GET < 300ms

SLOs:
  Availability: 99.5% (216 min/month budget)
  Latency: 99% < 300ms (432 min/month budget)

Four-tier burn alerting with full PromQL (see Expert Analysis Q1).

False-positive tuning:
  - Minimum traffic floor: 1 req/s
  - Exclude batch traffic: header X-Source != batch
  - Deploy suppression: 5 min after rollout
  - Authenticated users only for write SLI
```

### Example 5: Multi-Region SLO

```
GLOBAL SLO vs PER-REGION SLO:

  Global: 99.9% checkout availability (customer-facing)
  Per-region: 99.5% minimum (allows single-region outage
              if traffic fails over)

Alert routing:
  us-east-1 burn 14.4× → page US on-call
  eu-west-1 burn 6× only → ticket (region has 20% traffic)
  global burn 14.4× → page global IC

CloudWatch:
  Dimensions: LoadBalancer + AvailabilityZone
  Composite: global AND only when > 50% traffic affected
```

### Example 6: Circuit Breaker + SLO Dashboard Panel

```
Grafana row: "Checkout Resilience (Week 6 × Week 8)"

Panel 1: checkout:availability_sli_1h (SLO line at 0.999)
Panel 2: checkout:burn_rate_1h (threshold lines at 1, 6, 14.4)
Panel 3: checkout:error_budget_remaining (%)
Panel 4: resilience4j_circuitbreaker_state{service="checkout-svc"}
Panel 5: sum by (name) (resilience4j_circuitbreaker_slow_call_rate)
Panel 6: resilience4j_bulkhead_available_concurrent_calls

Correlation insight:
  When breaker OPEN on fraud-svc AND availability SLI healthy
  AND manual_review_queue increasing → quality degradation,
  not availability incident.
```

---

## Production Patterns

### Pattern 1: SLO-as-Code Repository Layout

```
slo/
├── tiers.yaml              # Tier definitions and default targets
├── services/
│   ├── checkout/
│   │   ├── slis.yaml       # SLI definitions
│   │   ├── slo.yaml        # Targets and windows
│   │   ├── alerts.yaml     # Burn-rate alert rules
│   │   └── runbook.md      # Linked from annotations
│   ├── cart/
│   └── search/
├── prometheus/
│   └── rules/              # Generated recording + alert rules
└── cloudwatch/
    └── alarms/             # Generated CFN/Terraform JSON

CI pipeline:
  1. Lint SLI definitions (valid PromQL, bounded labels)
  2. Simulate alert against last 30d data (unit test)
  3. Require runbook.md exists for every page-level alert
  4. Deploy to staging Prometheus → validate → prod
```

### Pattern 2: Error Budget Review Meeting

```
Weekly 30-minute meeting (eng + product + SRE):

Agenda:
  1. Budget status per Tier-0 service (5 min)
     - Remaining %, burn trend, incidents consumed
  2. Near-misses: slow burns triaged but not fixed (5 min)
  3. Deploy freeze status: any service in orange/red? (5 min)
  4. SLO recalibration candidates (10 min)
     - Too loose: budget never consumed → tighten
     - Too tight: constant yellow → loosen or invest
  5. Action items from last week (5 min)

Output: written notes in #reliability, Jira tickets for fixes
```

### Pattern 3: Deploy Gate via Error Budget

```
In CI/CD pipeline (ArgoCD / Spinnaker hook):

  pre_deploy_check:
    query: checkout:error_budget_remaining
    if < 0.25:
      block: true
      message: "Checkout error budget at 23%. Deploy freeze."
      override: requires SRE-manager approval + incident ticket

  post_deploy_canary:
    watch: checkout:burn_rate_5m for 15 minutes
    if burn_rate > 3:
      auto_rollback: true
```

### Pattern 4: Synthetic Monitoring as SLI Supplement

```
CloudWatch Synthetics canary (or Datadog synthetics):

  Script: full checkout flow every 60s from 3 regions
  Metrics:
    Success → contributes to synthetic SLI
    Duration → latency SLI cross-check
    Broken at edge when app metrics look fine (DNS, CDN, WAF)

Alert:
  Synthetic failure rate > 0 for 3 consecutive runs → page
  (even if application metrics haven't caught up yet)

Cost: ~$0.0012/canary run × 3 regions × 1440/day ≈ $5/day
Cheap insurance against "metrics green, users red"
```

### Pattern 5: Alertmanager Routing Tree

```yaml
route:
  receiver: default-slack
  group_by: [alertname, slo]
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  routes:
    - match:
        severity: page
      receiver: pagerduty-tier0
      continue: false
    - match:
        severity: ticket
      receiver: jira-automation
    - match:
        severity: slack
      receiver: slack-observability
    - match:
        slo: checkout_availability
      receiver: pagerduty-checkout
      routes:
        - match:
            tier: "1"
          receiver: pagerduty-checkout-urgent

receivers:
  - name: pagerduty-checkout-urgent
    pagerduty_configs:
      - service_key: <key>
        severity: critical
  - name: jira-automation
    webhook_configs:
      - url: https://jira.example.com/automation/webhook
```

### Pattern 6: Runbook Template

```markdown
# Runbook: CheckoutAvailabilityFastBurn

## What this means
Checkout 5xx error rate is consuming error budget ≥14.4× faster
than sustainable. Users are likely seeing failed checkouts.

## Severity
SEV1 if error rate > 1% and rising. SEV2 if 0.5–1%.

## First 5 minutes
1. [Dashboard](https://grafana/d/checkout-slo) — confirm burn
2. #deploys — any checkout-svc deploy in last 2h?
3. Traces: `service=checkout-svc status>=500` last 15m
4. Circuit breakers: any OPEN on payments, fraud, inventory?
5. ALB target health — all targets healthy?

## Diagnostic queries
​```promql
# 5xx by status
sum by (status) (rate(http_requests_total{route="/checkout",status=~"5.."}[5m]))
# Error rate by deployment
sum by (version) (rate(http_requests_total{route="/checkout",status=~"5.."}[5m]))
  / sum by (version) (rate(http_requests_total{route="/checkout"}[5m]))
​```

## Common causes
| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Spike after deploy | bad rollout | rollback |
| 504 dominant | downstream timeout | check payments-svc, circuit breakers |
| 500 + PG errors | database | check Aurora, connection pool |
| Single AZ | AZ failure | confirm failover, drain bad AZ |

## Escalation
- 10 min no progress → @checkout-team-lead
- 20 min no progress → incident commander pool
- Customer impact confirmed → status page update

## Post-incident
- Calculate budget consumed
- File postmortem if SEV1/SEV2
- Update this runbook if new failure mode
```

### Pattern 7: SLO Dashboard Layout (Incident Commander View)

```
Row 1 — THE HEADLINE (large stat panels):
  - Error budget remaining (%)
  - Current burn rate (1h)
  - Availability SLI (30d rolling)
  - Latency SLI (30d rolling)

Row 2 — BURN RATES (time series):
  - burn_rate_5m, _1h, _6h, _24h with threshold lines

Row 3 — SLI COMPONENTS (breakdown):
  - Error rate by status code
  - Latency histogram heatmap
  - Traffic volume (denominator sanity)

Row 4 — RESILIENCE (Week 6):
  - Circuit breaker states
  - Bulkhead utilization
  - Retry rates by downstream

Row 5 — INFRASTRUCTURE (cause — collapsed by default):
  - Postgres, Redis, Kafka key metrics

Design rule: IC can assess situation in 15 seconds from Row 1–2.
```

---

## Failure Modes

### Failure 1: Alert Fatigue → Missed SEV1

```
SYMPTOM:
  On-call receives 15 pages/night. Starts acking without investigating.
  Real SEV1 buried in noise at 03:47.

CAUSE:
  - Legacy alerts (HTTPErrorRateHigh, P99High) duplicate SLO alerts
  - Cause-level pages (PostgresCPUHigh) not demoted
  - No alert review in 18 months

DETECTION:
  Track "actionable page rate" — pages that led to incident ticket
  Target: > 70% actionable

FIX:
  1. Inventory all alerts; classify page/ticket/slack/delete
  2. Remove duplicate legacy alerts
  3. Enforce runbook requirement in CI
  4. Monthly alert review: any alert acked 5× without action → delete

PREVENT:
  Alert budget: max 20 page-level rules per Tier-0 service
```

### Failure 2: Slow Burn Ignored Until SEV1

```
SYMPTOM:
  CheckoutSlowBurn fired for 50 hours on Slack. Dismissed.
  Then CheckoutFastBurn pages. 12-minute outage.

CAUSE:
  - Slow-burn alerts routed to Slack without triage SLA
  - No runbook for latency slow burn
  - On-call assumed "promo traffic, will normalize"

DETECTION:
  Post-incident: time from first slow-burn to first user impact

FIX:
  1. Mandatory triage note within 30 min of slow-burn ack
  2. Escalation: burn > 3× for 4h without triage → auto-page
  3. Runbook for latency slow burn (traces → long pole → DB)

PREVENT:
  Weekly review of all slow-burn alerts: triaged? escalated? closed?
```

### Failure 3: SLO Set Aspirational → Permanent Budget Burn

```
SYMPTOM:
  Team permanently in orange deploy freeze. Morale collapse.
  SLO says 99.99%; historical best month was 99.92%.

CAUSE:
  SLO set by executive mandate without baseline data

DETECTION:
  budget_remaining < 25% for 3 consecutive months without major incidents

FIX:
  Recalibrate SLO to 99.9% (achievable) with plan to tighten quarterly
  Present data: "99.99% requires $2M infra investment"

PREVENT:
  SLO proposals must include 90-day historical SLI chart
```

### Failure 4: Low-Traffic False Positive

```
SYMPTOM:
  Saved-cart alert pages at 04:00. Two errors in 8 requests = 25% error rate.
  On-call investigates nothing — no real user impact.

CAUSE:
  No minimum traffic threshold on burn-rate alert

FIX:
  Add: sum(rate(...[5m])) > 1 to alert expr
  Or: use min_over_time on denominator

PREVENT:
  Alert unit test with synthetic low-traffic scenario
```

### Failure 5: Circuit Breaker Masks Availability SLI

```
SYMPTOM:
  fraud-svc breaker OPEN. Checkout returns 200 with MANUAL_REVIEW.
  Availability SLI perfect. 10,000 orders stuck in review queue.
  Support overwhelmed. Not an "incident" by SLO metrics.

CAUSE:
  Only availability SLI defined; no quality/degraded-mode SLI

FIX:
  Add quality SLI: % orders completing without manual_review flag
  Alert: quality SLI burn OR queue_depth > threshold

PREVENT:
  For every circuit breaker fallback, define the DEGRADED SLI
```

### Failure 6: Multi-Window Composite Misconfigured in CloudWatch

```
SYMPTOM:
  Composite alarm never fires — 5m alarm flapping alone,
  1h alarm never reaches threshold independently.

CAUSE:
  Composite uses OR instead of AND
  Or: 1h alarm EvaluationPeriods too strict

FIX:
  Verify AlarmRule: ALARM(A) AND ALARM(B)
  Test with historical data replay (CloudWatch alarm testing)

PREVENT:
  Infrastructure-as-code review for all composite alarms
```

### Failure 7: Error Budget Not Connected to Product Decisions

```
SYMPTOM:
  Engineering stops deploys (budget at 10%).
  Product launches feature via config flag bypassing freeze.
  Budget exhausted. SEV1 next day.

CAUSE:
  Error budget policy not signed by product leadership
  No enforcement mechanism on feature flags

FIX:
  Product VP sign-off on budget policy
  Feature flag system checks budget API before enabling >5% rollout

PREVENT:
  Quarterly cross-functional reliability review with product
```

---

## SRE Diagnostic Toolkit

### PromQL Queries — SLI and Budget

```promql
# Rolling 30-day availability SLI
avg_over_time(checkout:availability_sli_1h[30d])

# Error budget remaining (availability, 99.9% SLO)
1 - ((1 - avg_over_time(checkout:availability_sli_1h[30d])) / 0.001)

# Current burn rate (1h window)
(1 - checkout:availability_sli_1h) / 0.001

# Burn rate comparison across windows (dashboard)
(1 - checkout:availability_sli_5m) / 0.001   # short
(1 - checkout:availability_sli_1h) / 0.001   # medium
(1 - checkout:availability_sli_6h) / 0.001   # long

# Latency SLI (99% < 800ms)
sum(rate(http_request_duration_seconds_bucket{route="/checkout",le="0.8"}[1h]))
/ sum(rate(http_request_duration_seconds_count{route="/checkout",status!~"5.."}[1h]))

# Top error contributors by downstream
sum by (downstream) (rate(http_client_errors_total{caller="checkout-svc"}[5m]))

# Circuit breaker correlation
resilience4j_circuitbreaker_state{name=~".*"} == 1  # OPEN = 1

# Retry storm detection
sum(rate(http_client_retries_total{service="checkout-svc"}[5m]))
/ sum(rate(http_client_requests_total{service="checkout-svc"}[5m]))
```

### CloudWatch Insights — ALB Edge SLI

```
# 5xx rate last hour (ALB access logs)
fields @timestamp, request_url, target_status_code
| filter request_url like /checkout/
| filter target_status_code >= 500
| stats count(*) as errors by bin(5m)

# Compare with total
fields @timestamp, request_url, target_status_code
| filter request_url like /checkout/
| stats count(*) as total by bin(5m)
```

### Alert Testing Checklist

```
Before merging new SLO alert:

□ Run promtool check rules on alerts.yaml
□ Query 30d history: how many times would this have fired?
□ Confirm each firing correlates with known incident or near-miss
□ Verify minimum traffic guard prevents 3am false pages
□ Dry-run notification to #alerts-test Slack channel
□ Confirm runbook link resolves
□ Load test: inject 5xx at 2% — alert fires within 5 min
□ Decay test: stop injection — alert clears within 15 min
```

### On-Call Triage Flowchart

```
Alert received
    │
    ├─ Is it a page? ──NO──► Ack ticket/Slack, triage within SLA
    │       │
    │      YES
    │       │
    │       ▼
    │   Open dashboard + runbook
    │       │
    │       ├─ False positive? ──YES──► Document, silenced fix, return
    │       │
    │       NO
    │       │
    │       ▼
    │   Confirm user impact (SLO burning?)
    │       │
    │       ├─ NO impact ──► Downgrade, investigate as ticket
    │       │
    │       YES
    │       │
    │       ▼
    │   Declare SEV level
    │       │
    │       ├─ SEV1/2 ──► Open bridge, IC, status page
    │       └─ SEV3 ──► Fix in business hours unless worsening
    │
    └─ Follow runbook until resolved or escalated
```

---

## Decision Framework

### SLI Selection Decision Tree

```
What user journey is this?
    │
    ├─ Synchronous API call
    │   ├─ Availability SLI (errors)
    │   └─ Latency SLI (% under threshold)
    │
    ├─ Async pipeline (email, webhook, batch)
    │   └─ Freshness SLI (time from trigger to completion)
    │
    ├─ Data display (dashboard, report)
    │   └─ Freshness SLI (staleness bound)
    │
    └─ Correctness-critical (payments, inventory)
        ├─ Availability SLI
        ├─ Quality SLI (correct result)
        └─ Latency SLI

Where to measure?
    Edge if user-facing E2E matters
    Service if team ownership boundary needed
    Both if you can afford the instrumentation
```

### SLO Target Selection

```
┌─────────────────────────────────────────────────────────────┐
│ Question                          │ Guidance                 │
├─────────────────────────────────────────────────────────────┤
│ What's the revenue impact?        │ High → 99.95%+           │
│ What's 90-day historical p99?     │ SLO threshold ≥ p99 × 1.5│
│ How many dependency hops?         │ More hops → higher per-hop SLO│
│ Is there an SLA with penalties?   │ SLO ≥ SLA + 0.05% margin │
│ Is the team new to SLOs?          │ Start loose, tighten Q2  │
└─────────────────────────────────────────────────────────────┘
```

### Alert Severity Assignment

```
┌─────────────────────────────────────────────────────────────┐
│ Condition                         │ Route to                 │
├─────────────────────────────────────────────────────────────┤
│ Tier-0 burn ≥ 14.4×               │ Page (24/7)              │
│ Tier-0 burn ≥ 6×                  │ Page (or business hours) │
│ Tier-0 burn ≥ 3×                  │ Ticket (urgent)          │
│ Tier-0 burn ≥ 1× sustained 3d     │ Slack                    │
│ Tier-1/2 burn ≥ 14.4×             │ Page if Tier-0 risk      │
│ Leading indicator + SLO burn ≥ 3× │ Ticket                   │
│ Leading indicator alone           │ Slack                    │
│ Budget remaining < 10%            │ Slack + deploy freeze    │
│ Circuit breaker OPEN + fallback   │ Slack                    │
│ Circuit breaker OPEN, no fallback │ Page if availability burn│
└─────────────────────────────────────────────────────────────┘
```

### Build vs Buy for SLO Platform

```
┌─────────────────────────────────────────────────────────────┐
│ Approach              │ Pros              │ Cons             │
├─────────────────────────────────────────────────────────────┤
│ PromQL + Alertmanager │ Free, flexible    │ DIY dashboards   │
│ Google Cloud SLO      │ Native burn alerts│ GCP-only         │
│ Datadog SLO           │ Full UI, burn rate│ $$$ at scale     │
│ Nobl9               │ Multi-source SLO  │ Another tool       │
│ AWS CloudWatch Comp.  │ Native AWS        │ Weak multi-window│
└─────────────────────────────────────────────────────────────┘

Recommendation for AWS-heavy shops:
  CloudWatch for ALB/Lambda edge SLIs
  Prometheus for k8s service SLIs
  Unified PagerDuty routing
  Grafana for single-pane budget view
```

---

## Incident Scenario

### "The Slow-Burn Latency Mystery" — SLO Lens

This scenario is shared with Observability.md Topic 1. Here we analyze it purely through the SLO/alerting lens.

#### The System

```
PRODUCT: Glasswing e-commerce. $8M/day GMV.
CHECKOUT SLOs:
  Availability: 99.9% / 30-day rolling
  Latency: p99 < 800ms (99% of requests under 800ms)

ALERTS:
  CheckoutFastBurn (14.4×, 5m+1h) → page
  CheckoutSlowBurn (6×, 30m+6h) → ticket
  CheckoutLatencySlowBurn (3×, 2h+24h) → ticket
  Legacy: CheckoutP99High, HTTPErrorRateHigh → page (redundant)
```

#### Timeline — SLO Events Only

```
DAY 0 (Tuesday) 19:00
  Traffic +35% (FlashFriday promo). p99: 312ms. Budget: 100%.
  No alerts. SLI healthy.

DAY 1 (Wednesday) 14:00
  p99 creeps to 340ms. Latency SLI still 99.8% good.
  No burn alert. Correct — within SLO.

DAY 2 (Thursday) 10:00
  p99: 410ms. CheckoutSlowBurn fires (latency 6× burn).
  Routed to TICKET queue. On-call acks, no deep triage.
  Budget consumed: ~8%. Triage note: "promo load, watching."

DAY 2 (Thursday) 14:00
  PostgresCPUHigh → Slack. Cause metric. Not SLO-linked.
  On-call adds to investigation list. Budget: ~12%.

DAY 3 (Friday) 12:14 — THE PAGE
  p99: 1620ms. Availability dropping (504s at edge).
  CheckoutFastBurn fires (14.4× availability + latency).
  Budget: 78% consumed. Single hour may exhaust remainder.

  12:26 — Recovery after ANALYZE on stale Postgres stats.
  Final budget consumed: ~85% for the month.
  SEV2 declared retroactively at 12:14.
```

#### SLO/Alerting Postmortem Findings

```
FINDING 1: Slow-burn ticket ignored for 50 hours
  SLO impact: 8% budget consumed before anyone traced the long pole
  Fix: mandatory triage runbook for latency slow-burn
  Fix: auto-escalate to page if burn > 3× for 4h without triage note

FINDING 2: Legacy alerts duplicated SLO pages at 12:14
  Four alerts fired within 90 seconds for same root cause
  Fix: delete CheckoutP99High and HTTPErrorRateHigh

FINDING 3: No quality SLI for degraded checkout experience
  504s appeared only at final stage; latency SLI burned first
  Fix: add "successful checkout completion" SLI excluding timeouts

FINDING 4: Circuit breakers not on IC dashboard
  payments-svc and fraud-svc breakers were CLOSED throughout
  Failure was INSIDE pricing-svc → Postgres, not breaker-related
  Fix: add DB query latency as leading indicator ticket alert

FINDING 5: Error budget policy not enforced
  85% budget consumed on day 17 of 30 — should trigger orange freeze
  Team continued deploying Tier-2 features through the slow burn
  Fix: automated deploy gate at 25% remaining
```

#### What Good Looked Like (Counterfactual)

```
Thursday 10:00 — CheckoutSlowBurn fires
  10:05 — On-call posts triage note: "latency burn 6×, investigating"
  10:10 — Opens trace view, finds pricing-svc → Postgres long pole
  10:25 — Escalates to DBA: "query mean_time 5× week-over-week"
  10:45 — DBA identifies stale stats on promo_eligibility
  11:00 — ANALYZE scheduled for low-traffic window OR executed now
  11:15 — p99 drops 410ms → 290ms. Burn rate normalizes.
  
  Budget consumed: ~10% instead of 85%
  SEV1/2 incident: avoided entirely
  Customer impact: zero
```

---

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

## Key Takeaways

```
╔═════════════════════════════════════════════════════════════════╗
║   IF YOU FORGET EVERYTHING ELSE, REMEMBER THESE:                ║
╟─────────────────────────────────────────────────────────────────╢
║                                                                 ║
║   1. SLIs measure USER experience as ratios — good/total.       ║
║      Not CPU. Not uptime. Not /healthz.                         ║
║                                                                 ║
║   2. SLOs are internal targets with deliberate imperfection.    ║
║      100% reliability is the enemy of shipping.                 ║
║                                                                 ║
║   3. Error budgets translate reliability into policy:           ║
║      when to deploy, when to freeze, when to invest.            ║
║                                                                 ║
║   4. Alert on burn RATE with MULTI-WINDOW guards — not on       ║
║      raw error rate in a 5-minute window.                       ║
║                                                                 ║
║   5. Page on symptom (SLO burn). Ticket on cause (CPU).         ║
║      Every page needs a runbook.                                ║
║                                                                 ║
║   6. Slow burns are a DISCIPLINE problem — triage SLAs,         ║
║      escalation, and runbooks — not just math.                  ║
║                                                                 ║
║   7. Circuit breakers (Week 6) protect dependencies;            ║
║      SLOs protect users. Alert on both layers, differently.     ║
║                                                                 ║
║   8. CloudWatch composite alarms implement multi-window         ║
║      for AWS-native metrics; PromQL for k8s services.           ║
╚═════════════════════════════════════════════════════════════════╝
```

---

## Targeted Reading

```
REQUIRED:

  1. Google SRE Book — "Service Level Objectives" (Chapter 4)
     https://sre.google/sre-book/service-level-objectives/
     → SLI/SLO/error budget definitions. 30 minutes.

  2. Google SRE Workbook — "Alerting on SLOs" (Chapter 5)
     https://sre.google/workbook/alerting-on-slots/
     → Burn-rate math, multi-window alerts, 14.4× derivation. 45 minutes.

  3. Google SRE Workbook — "Emergency Response" (Chapter 8)
     https://sre.google/workbook/emergency-response/
     → On-call, incident severity, escalation. 30 minutes.

  4. AWS — "Creating CloudWatch Composite Alarms"
     https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Create_Composite_Alarm.html
     → Multi-window AND logic for ALB metrics. 20 minutes.

  5. PagerDuty — "Event Orchestration and Alert Grouping"
     https://www.pagerduty.com/resources/learn/what-is-event-orchestration/
     → Routing SLO alerts to correct teams. 15 minutes.

  6. Week 6 Module — Circuit Breakers, Bulkheads, Timeouts
     ../Week-06-Architecture-Patterns/Circuit Breakers Bulkheads Timeouts Retries and Backpressure.md
     → Resilience layer beneath SLOs. 2 hours.

OPTIONAL:

  7. Rob Ewaschuk — "Monitoring and Observability" (Stripe blog)
     → Symptom-based alerting philosophy. 20 minutes.

  8. Charity Majors — "The Observability Trap" / "SLOs Are Not for Everyone"
     → Critical perspective on SLO adoption pitfalls. 15 minutes.

  9. Nobl9 — "SLO Maturity Model"
     https://www.nobl9.com/slo-maturity-model
     → Organizational adoption stages. 15 minutes.

  10. AWS — "Defining and Measuring SLOs for Amazon EKS"
      https://aws.amazon.com/blogs/containers/
      → EKS-specific SLI patterns. 25 minutes.

PRACTICE:

  11. Week 8 Topic 1 — Observability (companion module)
      ./Observability.md
      → Metrics/logs/traces that feed SLIs. Focus on RED/USE,
        not the SLO sections (covered here in depth).

  12. Retention-Tests/Week-08.md (when authored)
      → Burn-rate design drills and incident triage scenarios.
```

---
