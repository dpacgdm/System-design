# Answer Key — Observability

> Open only after attempting the learner file questions.

## Expert Analysis

### Q1: Cardinality Forensics

**A junior engineer ships a PR adding two new labels to your `http_requests_total` metric: `user_id` and `request_id`. The PR description says: "These will help debug user-specific issues." The PR has one approval and CI is green. You're the senior reviewer.**

**Calculate the cardinality impact. Reject or accept the PR. If reject, propose the right way to achieve the engineer's actual goal.**

#### The Answer

**(a) Calculate the impact.**

Current metric:
```
http_requests_total{
  service,    // 12 services
  route,      // ~80 routes
  method,     // 5
  status      // 7
}
```
Current cardinality: 12 × 80 × 5 × 7 = **33,600 series**. Reasonable.

Proposed addition:
- `user_id`: 12M MAU (active users in 30-day window)
- `request_id`: unique per request, ~50M new values per day

Cardinality if `user_id` added: 33,600 × 12,000,000 = **403 billion** active series.
Cardinality if `request_id` added: 33,600 × 50,000,000 (new per day, churning) = **1.7 trillion series/day**.

Either label single-handedly makes the metric un-ingestable on any TSDB. `request_id` is catastrophic — it's effectively unique per scrape, meaning every series exists for one scrape and disappears, which is the worst possible pattern for a TSDB (massive churn cost without queryability).

At Datadog's pricing (~$0.05 per 100 unique tag combos per month) the user_id version alone bills at roughly **$200,000/month** for this one metric. Prometheus/Mimir would simply OOM.

**(b) Reject. Reasoning the engineer will understand:**

> "Adding `user_id` to a metric multiplies its cardinality by the number of active users (~12M). This metric currently has 33,600 series; the change would create 400+ billion series. Our entire Prometheus fleet has ~3.2M active series across all metrics. Your one PR is six orders of magnitude over the entire fleet's current footprint."
>
> "`request_id` is even worse — it churns once per request, which TSDBs handle worse than steady-state cardinality."

**(c) The engineer's actual goal: "debug user-specific issues."**

This goal is legitimate. The wrong tool was metrics. The right tools, in priority order:

1. **Traces, with `user.id` as a span attribute** (not a metric label). Trace search by `user.id == "X"` answers "what happened for this user?" Cost is bounded by sample rate, not by user count. This is the canonical use case for distributed tracing.

2. **Wide events** (Honeycomb-style or structured logs in Loki/CloudWatch Insights) — one event per request with `user_id`, `request_id`, `route`, `duration_ms`, `status`, etc. Query "show me all events for user X in last 1h" or "p99 latency for top 1000 users last week."

3. **Structured logs with user_id as a field** — every request log line has `user_id="..."`. Loki indexes labels, not fields, so `user_id` lives in the log body, not as an index. Query is "give me all logs for service=checkout-svc where user_id='X'" — fast within a small time window, slow over weeks. Acceptable for incident triage, not for ongoing analytics.

The right PR:
- Add `user.id` as an attribute on the OpenTelemetry span in the request handler.
- Add a structured log field on the request-completion log line.
- Do NOT add as metric labels.

**(d) The follow-up systemic fix.**

A single PR caught is luck. Build the rule into CI:

```yaml
# .github/workflows/cardinality-check.yml
- name: Cardinality lint
  run: |
    # Parse all metric definitions in the diff
    # For each new label, check it against allowlist
    # Reject if label name matches denylist patterns:
    #   user_id, *_id (except small bounded sets), email,
    #   ip_address, session_id, trace_id, request_id,
    #   url (use route_pattern instead)
    # Calculate estimated cardinality from sample data
    # Fail if any metric > 100k estimated series
```

Plus a runtime guardrail: Prometheus's `body_size_limit` and per-target sample limits. The TSDB itself enforces "this scrape exceeds N series, drop the rest" so a runaway label can't take down the whole fleet.

**Self-score check:** Got the math, the rejection, the right alternative for the engineer's goal, the systemic CI fix, AND the runtime guardrail in case CI is bypassed. **3/3.**

---

### Q2: Burn-Rate Alert Design from Scratch

**Your team is launching a new "saved-cart" feature. Define the SLO from first principles, derive the error budget, design a complete burn-rate alerting policy with multiple windows, write the PromQL, and identify the false-positive scenarios you'll need to tune around.**

**Constraints:**
- Feature is read-write: GET /cart, PUT /cart, DELETE /cart
- Customer expectation: cart loads "instantly," saves "reliably"
- Lower tier than checkout (this isn't payments)
- Limited engineering time for noise tuning

#### The Answer

**(a) Define the SLI.**

Two distinct user experiences require two SLIs:

1. **Availability SLI** (saves don't fail):
```
sli_availability =
  count(requests where method ∈ {PUT, DELETE} AND status < 500)
  ─────────────────────────────────────────────────────────────
  count(requests where method ∈ {PUT, DELETE})
```
   - Excludes 4xx (client errors are not our fault).
   - Excludes GET (read availability less critical; fall back to local state).

2. **Latency SLI** (loads feel instant):
```
sli_latency =
  count(requests where method == GET AND duration < 300ms)
  ────────────────────────────────────────────────────────
  count(requests where method == GET)
```
   - 300ms based on Doherty threshold (perceived as instant under 400ms).
   - Excludes errors (a fast 500 isn't success).

**(b) Set the SLO.**

This is a tier-2 feature. SLOs are set lower than checkout (99.9%) but high enough that engineers care.

- **Availability SLO: 99.5% over 30 days.** Error budget: 0.5% = 216 minutes/month of failures.
- **Latency SLO: 99% of GETs <300ms over 30 days.** Error budget: 1% = 432 minutes/month of slow requests.

These are STARTING values. After 60 days of data, recalibrate based on actual achievable performance and customer complaints.

**(c) Multi-window burn-rate alerts.**

Following the Google SRE workbook formula. For a 30-day SLO, use four alert tiers:

| Tier | Long Window | Short Window | Burn Rate | Budget % consumed | Severity |
|---|---|---|---|---|---|
| 1 (catastrophic) | 1h | 5m | 14.4× | 2% in 1h | Page |
| 2 (severe) | 6h | 30m | 6× | 5% in 6h | Page |
| 3 (sustained) | 24h | 2h | 3× | 10% in 24h | Ticket |
| 4 (slow burn) | 3d | 6h | 1× | 10% in 3d | Slack |

Both the long AND short window must breach to fire. Short window catches "is this happening RIGHT NOW," long window catches "is this REAL or noise."

**(d) PromQL for Tier 1 (availability):**

```yaml
- alert: SavedCartAvailabilityFastBurn
  expr: |
    (
      (
        sum(rate(http_requests_total{
          service="cart-svc",
          method=~"PUT|DELETE",
          status=~"5.."
        }[5m]))
        /
        sum(rate(http_requests_total{
          service="cart-svc",
          method=~"PUT|DELETE"
        }[5m]))
      ) > (14.4 * 0.005)
    )
    and
    (
      (
        sum(rate(http_requests_total{
          service="cart-svc",
          method=~"PUT|DELETE",
          status=~"5.."
        }[1h]))
        /
        sum(rate(http_requests_total{
          service="cart-svc",
          method=~"PUT|DELETE"
        }[1h]))
      ) > (14.4 * 0.005)
    )
  for: 2m
  labels:
    severity: page
    slo: saved_cart_availability
    runbook: https://wiki/runbooks/saved-cart
  annotations:
    summary: "Saved-cart write SLO burning at 14.4x rate"
    description: |
      Errors on PUT/DELETE /cart exceeded 7.2% over both
      5m and 1h windows. At this rate, the 30-day error
      budget will be exhausted in ~50 hours.
      
      Triage steps:
      1. Open trace view: service=cart-svc, status>=500, last 15m
      2. Check downstream: Postgres, Redis dashboards
      3. Check recent deploys: kubectl rollout history
```

PromQL for latency follows identical shape with `histogram_quantile` and the latency SLI numerator.

**(e) False positives to tune around.**

Five anticipated noise sources and the tuning:

1. **Low traffic in early-morning windows.** At 04:00 UTC, RPS may be 2/sec. A single error spikes the rate dramatically. The 5-minute window isn't enough denominator.
   - **Tune:** add `sum(rate(...)) > 1` denominator clause. Don't fire if traffic is below a floor; the SLO doesn't apply at low volume because user impact is minimal.

2. **Bot traffic creating 4xx.** Cart endpoints get scraped by bots; some bots send malformed PUT bodies → 400. We exclude 4xx from numerator already, but bot 5xx (e.g. proxy errors) can spike.
   - **Tune:** filter requests by `user_authenticated="true"` if available. The SLO is about authenticated humans.

3. **Deploys.** Each deploy triggers brief 503 spikes as old pods drain.
   - **Tune:** suppress alerts for 5 minutes after a deploy event. Integrate with deploy webhook.

4. **Periodic batch jobs that spam the cart endpoint.** A nightly cleanup batch generated 10K DELETE/min and trips error rate.
   - **Tune:** scope SLI to user-facing traffic only via header `X-Source != "batch"`. Document the contract.

5. **Coordinated client failure (e.g. mobile app version with bug).** Real production failure but limited blast radius.
   - **NOT a false positive.** Should fire. We may want a SECONDARY label `client_app_version` on the metric for diagnosis (bounded set, ~50 versions, OK cardinality), but the alert fires correctly.

**(f) The boring follow-up actions.**

- Deploy dashboards alongside alerts. Each alert links to a Grafana dashboard with the relevant panels.
- Write the runbook BEFORE merging the alert. No alert without a runbook is a paging-fatigue source.
- Set up burn-rate dashboard showing all four tiers' current burn rate. Helps oncall see "we're burning at 0.8× — fine. Or at 4× — about to fire."
- Recalibrate after 30 days. Burn rates that fire incessantly need their underlying SLOs raised; burn rates that never fire over a quarter mean the SLO is too loose.

**Self-score check:** Two SLIs derived from user experience, full math, full PromQL with all labels, five tuning scenarios with concrete fixes, plus the meta-rule about recalibration. **3/3.**

---

### Q3: The Trace-Sampling Cost Decision

**Your tracing bill is $42K/month at 5% head sampling. Finance wants 50% reduction. Engineering wants better debuggability. The platform team proposes four options. Choose, defend, name the hedge.**

**Option I:** Drop head sampling to 1%. Save $34K/month. Same infrastructure.
**Option II:** Switch to tail sampling: 100% of errors, 100% of >p95, 0.5% of normal. Adds OpenTelemetry collector with tail-sampling processor (3 nodes, $1.5K/month). Estimated trace volume reduction: 90%.
**Option III:** Migrate from Tempo to Honeycomb. $36K/month at projected volume but with wide-events / faceted query capability. Eliminates separate metric/log/trace silos for ad-hoc investigation.
**Option IV:** Keep 5% head but reduce retention from 14 days to 3 days. Saves $26K/month.

#### The Answer

**(a) For each option: what failure mode does it prevent? What does it NOT prevent?**

**Option I (drop to 1%):**
- *Prevents:* nothing new. Just costs less.
- *Doesn't prevent:* anything. ACTIVELY makes investigation harder. At 1% sampling, low-volume endpoints (the ones in trouble in the Q3.3 scenario above, ~830 calls/min) generate ~8 sampled traces/min. Adequate for fast burns, marginal for slow burns. At 1%, an endpoint with 10 calls/min generates 0.1 traces/min — effectively unusable.
- *The hidden cost:* postmortem-time investigation. Two minutes saved at incident time costs 30 minutes of "we don't have traces for this period."

**Option II (tail sampling):**
- *Prevents:* losing the interesting traces. Errors and slow traces are 100% retained — the ONLY ones that matter for debugging. Normal traces sampled at 0.5% still give you statistical baseline.
- *Doesn't prevent:* the categorical "we never instrumented this code path" issue. Tail sampling can't keep what was never produced.
- *Catch:* requires running the OTel collector with sufficient memory. Tail sampling buffers spans for the trace duration window (e.g., 30s). Memory cost ~ peak_spans_per_30s × span_size. For 50K spans/sec, ~30s, ~2KB/span = ~3GB buffer. Cluster sizing needs validation.

**Option III (Honeycomb):**
- *Prevents:* the silo problem. Most of our incidents involve flipping between metrics → traces → logs to find context. Honeycomb's wide-events model collapses these into one queryable surface. The "p99 spiked, group by deploy_sha and region and basket_size" use case is FREE in Honeycomb, IMPOSSIBLE in our current stack.
- *Doesn't prevent:* the Postgres-side investigation in our scenario. Wide events are app-side; we still need pg_stat_statements and EXPLAIN.
- *Migration cost:* re-instrumentation effort ~6 eng-weeks. Training cost.

**Option IV (reduce retention):**
- *Prevents:* nothing.
- *Doesn't prevent:* anything. AND breaks postmortems on incidents > 3 days old. We just demonstrated a 70-hour slow burn whose investigation REQUIRED the trace from Tuesday afternoon to validate "this started after the FlashFriday launch." With 3-day retention, we lose that capability. False economy.

**(b) Compounding vs one-time.**

- I and IV: one-time cost cuts. Same problem next quarter.
- II: compounding. Tail sampling is the right architecture; cost scales with TRAFFIC, not with naive sample rate. Better as we grow.
- III: compounding capability. Honeycomb's investigative model gets MORE useful as our system gets more complex.

**(c) The choice.**

**Option II.** With Option III as the next step in 6 months.

**Reasoning:**
1. Option II achieves the cost goal (estimated $34K savings) WITHOUT degrading debuggability. In fact, it IMPROVES debuggability — we keep 100% of the traces that matter, vs. our current 5% random sample that misses many error traces.
2. Option II is reversible. If the OTel collector causes operational pain, revert to head sampling in a config change.
3. Option III is the better long-term answer but costs us 6 eng-weeks now. That's not zero. Defer until we've stabilized Option II and have data on whether Honeycomb's investigative model would have shortened our recent incidents.
4. Options I and IV are false economies. Reject.

**(d) The hedge.**

Three risks to monitor:

1. **OTel collector reliability.** The collector becomes a single point of failure for traces. Mitigation: deploy 3 collectors with load balancing; alert on collector pod restarts; budget 0.5 eng for ongoing operation.

2. **Tail sampling miss rate.** Some interesting traces aren't "errors" or ">p95" — they're "normal-looking but wrong." Mitigation: tag known-investigation-worthy paths (e.g. checkouts > $1000) with `sampling.priority=1` to force inclusion regardless of duration/error.

3. **Cost projection wrong.** If tail sampling reduces volume by less than 90%, savings are smaller. Mitigation: pilot for 2 weeks on cart-svc before fleet-wide rollout. Measure actual reduction.

**The smallest reversible follow-up if wrong:** revert to head sampling at 5% (one config flag) and accept the bill. We can always re-attempt after fixing whatever the issue was.

**Self-score check:** Picked the best technical answer (II), justified against all alternatives, identified the future best (III) and why now isn't time, named three concrete hedges with mitigations, and the reversal path. **3/3.**

---

### Q4: Designing the On-Call Dashboard

**You are taking on-call rotation for a service you didn't build. The current team has 47 dashboards in Grafana, 12 of which mention "checkout." The runbook says "open the dashboards." Three minutes into a P1 page, you have 47 tabs open and no idea which graph matters. Design what the on-call dashboard SHOULD look like — top to bottom, panel by panel.**

#### The Answer

**(a) The principle.**

A dashboard during an incident has ONE job: answer "what is broken, where, and is it getting better or worse?" in <60 seconds, with no scrolling on a standard laptop screen.

Dashboards are NOT for steady-state browsing. They are for stressed humans at 2am.

**(b) The structure: 6 panels max, in priority order.**

```
╔════════════════════════════════════════════════════════════════╗
║   ┌─────────────────────────────┬──────────────────────────┐   ║
║   │ 1. SLO BURN STATUS          │ 2. DEPLOYS LAST 24h      │   ║
║   │ (single stat / bar gauge)   │ (annotation timeline)    │   ║
║   │ Current burn rate per SLO   │ "Did we ship something?" │   ║
║   ├─────────────────────────────┼──────────────────────────┤   ║
║   │ 3. RED FOR THE SERVICE                                 │   ║
║   │ (3 stats side-by-side)                                 │   ║
║   │ Rate / Error % / p99 latency                           │   ║
║   │ Sparklines for last 1h trend                           │   ║
║   ├────────────────────────────────────────────────────────┤   ║
║   │ 4. RED PER DOWNSTREAM DEPENDENCY                       │   ║
║   │ (table: one row per service we call)                   │   ║
║   │ Identifies WHICH downstream is the long pole           │   ║
║   ├─────────────────────────────┬──────────────────────────┤   ║
║   │ 5. SATURATION (USE)         │ 6. RECENT ALERTS         │   ║
║   │ DB, Redis, Kafka, pod CPU/  │ (last 1h, this service   │   ║
║   │ memory, network             │ and its dependencies)    │   ║
║   └─────────────────────────────┴──────────────────────────┘   ║
╚════════════════════════════════════════════════════════════════╝
```

**(c) Each panel detailed.**

**Panel 1 — SLO BURN STATUS** (top-left, can't miss it)
- Current 1h burn rate per SLO
- Color: green (<1×), amber (1-6×), red (>6×)
- Big number, plus arrow indicating whether burn rate is rising or falling over last 5 min
- Click-through: links to SLO detail page

**Panel 2 — DEPLOYS LAST 24h**
- Vertical lines on a timeline showing deploys to this service AND its dependencies
- "Did we ship something correlated with the spike?" is the #1 first-five-minutes hypothesis. Make it answerable in one glance.

**Panel 3 — RED for the service**
- Rate: requests/sec (line graph, last 1h)
- Errors: error % (line graph, last 1h, log scale)
- Duration: p50, p99 lines (last 1h)
- Each panel should be wide enough to see trend. Sparklines for compactness.
- Anomaly highlighting: shade where current value exceeds 2σ of last 7 days

**Panel 4 — RED per downstream dependency**
- One row per downstream service: cart-svc, pricing-svc, payments-svc, ...
- Columns: rate, error %, p99 from CALLER's perspective
- This is the "where in the call graph" panel. The slow one stands out.
- The data: from OpenTelemetry span attributes capturing downstream call duration. Indexed by `peer.service`.

**Panel 5 — SATURATION**
- DB connection pool usage
- Redis CPU and ops/sec
- Kafka consumer lag (per partition, NOT averaged)
- Pod CPU / memory across the fleet (heat map)
- Goal: if RED panel is bad, this panel shows WHY (resource saturation).

**Panel 6 — RECENT ALERTS**
- Any alert that fired in last 1h, this service or its 1-hop dependencies
- Includes Slack-only alerts, NOT just pages
- Helps surface: "the slow burn fired 50 hours ago and was ignored" — visible at a glance during the page

**(d) What to REMOVE.**

The other 41 dashboards: archive. Most are:
- Per-engineer "I made this for a project last year" (delete)
- "All metrics from service X" — useless during incident, useful for ad-hoc work (move to "exploration" folder, not Tier 1)
- "Pretty graphs for the leadership review" (separate folder, not on-call)

**(e) The discipline.**

- Designate ONE Tier-1 dashboard per service. Linked from the runbook. Updated as the service evolves.
- Dashboard reviews quarterly: which panel was actually used in the last 5 incidents? Remove panels nobody looked at.
- New panels require a "what incident does this help diagnose?" justification.

**(f) The connection to the scenario above.**

In our slow-burn incident, this dashboard would have shown:
- Panel 1: amber (burn rate 3-6× for 50 hours). Visible to anyone looking.
- Panel 4: pricing-svc row showing p99 of pg call climbing day-over-day.
- Panel 6: the 50-hour-old slow-burn alert visible.

The page at 12:14 would have triaged in 30 seconds, not 4 minutes. The slow burn from Thursday morning would have been investigated on first sight, not dismissed.

**Self-score check:** Defined the principle, drew the layout, specified each panel with data sources, addressed what to delete, the discipline of maintenance, AND tied back to the scenario showing how this dashboard would have helped. **3/3.**

---

### Q5: The Ten-Million-Dollar Logging Bill

**Your CFO escalates: AWS CloudWatch Logs bill last month was $1.2M. Annualized $14.4M. Engineering has 60 days to cut 70% without "losing observability." Diagnose the spend, propose the strategy, defend the trade-offs, name what you'll lose.**

#### The Answer

**(a) Diagnose where the spend goes.**

CloudWatch Logs cost components (rough order):
1. Ingestion: $0.50/GB
2. Storage: $0.03/GB-month
3. Insights queries: $0.005/GB scanned

At $1.2M/month, very likely 80%+ is ingestion. Run an audit:

```bash
aws logs describe-log-groups --query \
  'logGroups[*].[logGroupName,storedBytes]' \
  --output table | sort -k2 -n -r | head -20
```

Hypothetical findings (representative of real systems):
- `/aws/lambda/event-processor`: 4.8 TB/month, $2400 ingest. Logs every event including PII-redacted bodies. INFO level.
- `/aws/eks/prod/application/checkout-svc`: 9.2 TB/month, $4600 ingest. DEBUG level enabled "temporarily" in 2023.
- `/aws/eks/prod/application/cart-svc`: 12.4 TB/month, $6200. Logs entire request body on every PUT.
- ALB access logs: 8.1 TB/month. Also stored in S3 (duplicate).
- VPC Flow Logs: 14 TB/month. No one uses them.
- Hundreds of "I'll clean it up later" namespaces: 22 TB/month aggregate.

Pattern: 6-10 log groups account for 70-80% of spend.

**(b) The strategy: a five-action plan.**

**Action 1: Sampling and Level (saves ~40%)**

For high-volume services:
- Drop DEBUG and TRACE levels at the agent (Fluent Bit / Vector / OTel Collector). Don't ship them.
- Sample INFO at 10% on hot paths (request-completion lines).
- ALWAYS keep WARN and ERROR.

Implementation:
```yaml
# Vector config
[transforms.sample_info]
  type = "sample"
  inputs = ["application_logs"]
  rate = 10  # keep 1 in 10
  key_field = "trace_id"
  exclude.severity = ["WARN", "ERROR", "FATAL"]
```

Sampling by `trace_id` ensures all logs from the SAME request are kept or dropped together. Critical for trace-log correlation.

Implication: high-volume info logs no longer 100% present. To compensate, ensure all important business events emit at WARN level or use structured wide events.

**Action 2: Move "data" out of logs (saves ~20%)**

Many log groups are using CloudWatch as a data lake:
- ALB access logs → S3 (already there) + Athena for query. Stop CloudWatch ingestion.
- VPC Flow Logs → S3 with Glacier-after-7-days. Stop CloudWatch ingestion.
- Audit logs → dedicated S3 with object lock for compliance. Cheaper retention.

Athena query cost on S3 ~$5/TB scanned vs CloudWatch Insights $5/GB scanned. 1000× cheaper for analytical workloads.

**Action 3: Delete what nobody reads (saves ~15%)**

Audit log group access:
```bash
# Use CloudTrail to find log groups with no GetLogEvents in last 90 days
# Tag them "candidate-for-deletion"
# Notify owners; delete after 30 days
```

22 TB/month of orphaned logs from old services, dev/staging spam, decommissioned features. Owner-by-owner email campaign.

**Action 4: Retention tiering (saves ~10%)**

Default CloudWatch retention is "Never expire." Set per log group:
- Application INFO/DEBUG: 7 days
- Application WARN/ERROR: 30 days
- Audit/security: 90 days hot, 7 years cold (S3 + Glacier)
- Access logs: 30 days hot, 1 year cold

CloudWatch storage is small relative to ingest, but housekeeping is healthy.

**Action 5: Re-route queries to a cheaper backend for ad-hoc work (saves ~10% indirect)**

Insights queries scan ingest-priced data. Pipe a copy of structured logs to Loki (self-hosted on EKS) or to S3+Athena. Ops keep CloudWatch as the source of truth for SLOs/alerts; investigators use the cheaper backend.

Cost of running Loki: ~$8K/month for fleet at this scale. Saves ~$80K/month in Insights query bills + recovers freedom to query.

**Total projected reduction:** ~70% if all five actions ship. Conservative estimate: ~55-65%, hitting the floor of CFO's target.

**(c) What we'll lose.**

Be honest:

1. **Sampled INFO logs mean some forensic detail is gone.** If a customer reports an issue and the relevant trace was sampled out, we can't reconstruct exactly what happened in the INFO trail. Mitigation: ERROR is still 100%. Most useful forensic data is in traces (now tail-sampled, keeping all errors).

2. **Athena for ALB logs is slower than CloudWatch Insights.** Investigators wait 30s vs 5s. Acceptable trade for 1000× cost reduction.

3. **VPC Flow Logs analysis becomes "open S3 bucket, run Athena query."** Slightly more friction. Network team acknowledges; they queried these <10× last year.

4. **Decommissioned log groups are gone.** Anyone wanting their logs back from a service shut down 2 years ago is out of luck. Communicate the deletion campaign clearly.

**(d) The political dimension (the part nobody teaches).**

A 70% logging cost reduction touches dozens of teams. The CFO can't impose this; engineering has to own it. The plan needs:

1. A 4-week comms campaign before any deletion. Every owner gets notified, with a cost figure for THEIR log groups, BEFORE the change.
2. An exec sponsor from engineering (CTO or VP Eng). Cuts the "but I might need that someday" objections.
3. A reversible test phase. Roll out sampling on 3 services for 2 weeks. Validate: did any incident MTTR get worse? If yes, roll back THAT service.
4. Post-rollout: monthly "logs cost dashboard" by team. Internal cost transparency keeps it from creeping back.

**(e) The hedge.**

What if 70% reduction degrades incident response and we don't realize it for a month?

- KPI: track MTTR for P1 incidents over the rollout period. If MTTR rises >25% vs. trailing 90-day baseline, halt and reassess.
- Keep the OLD ingestion config saved as a "break glass" — flip a flag to restore full logging on a specific service if needed.
- Quarterly review: was the right level of logging restored to anywhere we cut too aggressively?

**Self-score check:** Diagnosis with concrete cost components, 5-action plan with specific tools/configs, percentage estimates, honest enumeration of what we lose, the political reality, and a measured hedge with KPI. **3/3.**

---




---

## Ops Sim: Northstar Cardinality Fire During Checkout P1

> Open only after attempting the learner-side drill.

### Executive diagnosis

A debug deploy adds `order_id` to a hot histogram and sets trace sampling to 100% with no expiry. The observability plane self-DOSes during a real checkout incident.

A principal response separates the trigger from the amplifier and states the invariant before proposing capacity or repair. The answer should not say only "scale it" or "roll it back"; it must explain why this system failed this way.

### Evidence map

- `prometheus_tsdb_head_series: 24M -> 1.4B`
- `mimir_ingester_memory_bytes: 68GB -> 410GB`
- `otelcol_exporter_queue_size: 2k -> 1.2M`
- `trace_spans_received_per_second: 90k -> 4.8M`
- `loki_distributor_bytes_received_total: +4TB/hour`
- `alertmanager_notifications_failed_total: +190`
- Config clue: `metric.label_allowlist: disabled`
- Config clue: `checkout_request_duration.labels: [route,status,order_id,tenant_id]`
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

- `scale observability ingest before dropping bad labels`: spends capacity ingesting toxic high-cardinality data and delays restoring the protected golden signals the bridge needs.
- `keep 100% traces until the incident ends`: keeps the telemetry fire burning and crowds out the signals needed for mitigation.
- `query by order_id in metrics`: creates unbounded series cardinality where exemplars/logs/traces should carry IDs.
- `turn off all alerts because they are noisy`: blinds the bridge; the fix is protected golden signals, not silence.

### Capacity and blast radius

A principal answer gives at least one bound. Compute the affected slice, backlog or queue depth, derivative, safe downstream throughput, and time-to-exhaustion or time-to-drain. If those values are unknown, the safe move is to throttle and measure before scale/failover/replay.

Examples of the expected math:
- current backlog / safe drain rate = minimum repair duration
- free disk or pool headroom / growth rate = time-to-exhaustion
- affected tenants, SKUs, auctions, regions, orders, or carts from source-of-truth keys
- downstream provider/API/database quota that caps replay concurrency

### Repair and reconciliation

Source of truth: orders/payments source systems plus a small protected observability control stream.

Build the affected set from authoritative records in the incident window, not from cache, search, dashboards, or customer anecdotes alone. Repair must use stable idempotency or operation keys, be throttled to downstream headroom, and write an audit trail. Derived projections can be rebuilt after the invariant is safe.

### Durable fixes

- metric label allowlists and cardinality budgets
- tail sampling with expiry
- protected SLO signal pipeline
- PII/cardinality admission checks

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

