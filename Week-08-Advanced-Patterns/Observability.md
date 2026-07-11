# Observability: Metrics, Logs, and Traces

---

## Learning Objectives
```
After this topic, you will be able to:

1. Distinguish the THREE PILLARS (metrics, logs, traces) by what
   they answer, and explain why each fails when used for the
   wrong question
2. Apply the USE method (resources) and RED method (services)
   to choose what to measure for any given system
3. Compute cardinality of a metric BEFORE adding it, and
   refuse changes that would explode the time-series database
4. Define an SLO from a user-facing SLI, derive the error
   budget, and design burn-rate alerts that fire at the right
   urgency
5. Trace a request end-to-end across services using OpenTelemetry,
   understanding span context propagation, sampling, and
   the cost model
6. Diagnose alerting pathologies: alert fatigue, flapping,
   leading vs lagging indicators, page-on-symptom vs page-on-cause
7. Map observability to real systems (Prometheus, Grafana,
   Datadog, Honeycomb, Jaeger, Loki) with cost models and
   gotchas for each
8. Build the dashboards an incident commander actually uses
   under pressure — not the ones engineers like to look at
   in steady state
```

---

## Wrong Mental Models (Destroy These First)

```
MENTAL MODEL #1: "More dashboards = better observability"
  WRONG. Dashboards answer known questions. Observability means arbitrary
  ad-hoc queries on high-cardinality data when the unknown breaks.

MENTAL MODEL #2: "Log everything — storage is cheap"
  WRONG. Unbounded logs explode cost and drown signal. Structured logs
  with sampling and retention tiers beat verbose println debugging.

MENTAL MODEL #3: "Metrics cardinality doesn't matter at our scale"
  WRONG. user_id or request_id labels destroy Prometheus/CloudWatch.
  Cardinality is a design constraint, not an ops afterthought.

MENTAL MODEL #4: "100% trace sampling in production"
  WRONG. Full tracing at high RPS melts collectors and storage. Tail-based
  sampling + error-biased sampling captures incidents without bankrupting you.

MENTAL MODEL #5: "Alert on every threshold breach"
  WRONG. Symptom-based multi-window burn rates (see SLOs module) beat
  static CPU thresholds that page at 3 AM for self-healing blips.
```

---

## Core Teaching

### 2.1 — Why Observability Is Different From Monitoring

```
╔════════════════════════════════════════════════════════════════╗
║   MONITORING vs OBSERVABILITY — THE DISTINCTION                ║
╟────────────────────────────────────────────────────────────────╢
║                                                                ║
║   MONITORING:                                                  ║
║   "Watch the things you ALREADY KNOW could break."             ║
║   → CPU > 90% → alert.                                         ║
║   → Disk > 85% → alert.                                        ║
║   → HTTP 5xx rate > 1% → alert.                                ║
║   → Pre-defined dashboards, pre-defined alerts.                ║
║   → Answers: "Is X healthy?" where X is known in advance.      ║
║                                                                ║
║   OBSERVABILITY:                                               ║
║   "Be able to ask QUESTIONS YOU DIDN'T KNOW TO ASK."           ║
║   → "Why are 3 specific users in São Paulo getting 503s        ║
║     only when they hit the /checkout endpoint with             ║
║     basket size > 12?"                                         ║
║   → You couldn't have written that alert in advance.           ║
║   → Requires HIGH-CARDINALITY, HIGH-DIMENSIONALITY data        ║
║     queryable arbitrarily.                                     ║
║                                                                ║
║   THE TEST:                                                    ║
║   When something breaks in a way you've never seen before,     ║
║   can you DIAGNOSE it from the data you already collected?     ║
║   → Yes → observable.                                          ║
║   → No → you have monitoring, not observability.               ║
║                                                                ║
║   THE TRAP:                                                    ║
║   "We have 2,000 dashboards" is monitoring.                    ║
║   "We can pivot from a failing trace to the host's memory      ║
║   pressure to the related deploy event in three clicks"        ║
║   is observability.                                            ║
╚════════════════════════════════════════════════════════════════╝
```

**Where you've already seen observability gaps (connecting prior weeks):**

```
╔════════════════════════════════════════════════════════════════╗
║   PRIOR REFERENCE             │  OBSERVABILITY CONNECTION      ║
╠════════════════════════════════════════════════════════════════╣
║  Week 4 T1: split-brain       │ You needed a metric that       ║
║  detection                    │ counted "two leaders for the   ║
║                               │ same partition." Without it,   ║
║                               │ the bug was invisible until    ║
║                               │ data corruption surfaced.      ║
╠════════════════════════════════════════════════════════════════╣
║  Week 4 T3 (Raft): election   │ etcd_server_leader_changes_    ║
║  storms                       │ seen_total. The metric that    ║
║                               │ made the storm visible. With-  ║
║                               │ out it, IOPS bottleneck would  ║
║                               │ have looked like "etcd just    ║
║                               │ slow."                         ║
╠════════════════════════════════════════════════════════════════╣
║  Week 5 T1: replication slot  │ pg_replication_slots' slot     ║
║  bloat                        │ pending bytes. The leading     ║
║                               │ indicator. The "lagging"       ║
║                               │ indicator was disk-full.       ║
║                               │ Distance between them = your   ║
║                               │ MTTR.                          ║
╠════════════════════════════════════════════════════════════════╣
║  Week 5 T2: ISR shrinkage     │ kafka.server UnderMin-         ║
║                               │ IsrPartitionCount. Alert before║
║                               │ producers see errors. The      ║
║                               │ entire mitigation strategy     ║
║                               │ depends on alert lead time.    ║
╠════════════════════════════════════════════════════════════════╣
║  Week 5 T2: broker request    │ The LEADING indicator we       ║
║  queue saturation             │ proposed in the Tuesday        ║
║                               │ incident postmortem. 60-90s    ║
║                               │ lead time over the lagging     ║
║                               │ "customer error rate" alert.   ║
╚════════════════════════════════════════════════════════════════╝
```

The pattern: **every previous incident's MTTR was bounded by the gap between when a leading indicator could have fired and when the lagging customer-impact alert actually fired.** Observability is the discipline of closing that gap.

---

### 2.2 — The Three Pillars: What Each Answers (And What Each CAN'T)

```
╔════════════════════════════════════════════════════════════════╗
║   THE THREE PILLARS                                            ║
╠════════════════════════════════════════════════════════════════╣
║                                                                ║
║   METRICS                                                      ║
║   ─────────                                                    ║
║   What:  Numeric measurements over time, aggregated.           ║
║   Shape: counter, gauge, histogram, summary.                   ║
║   Cost:  Cheap. ~$0.10/series/month at most vendors.           ║
║   Cardinality: LOW. Each unique label combination = a series.  ║
║                                                                ║
║   ANSWERS WELL:                                                ║
║   → "What is the p99 latency of /checkout right now?"          ║
║   → "How many requests/sec is service X handling?"             ║
║   → "Is this trending in the wrong direction?"                 ║
║   → "Did this metric change after the deploy at 14:32?"        ║
║                                                                ║
║   FAILS AT:                                                    ║
║   ✗ "WHY is p99 high?"                                         ║
║   ✗ "Is THIS specific user's request slow?"                    ║
║   ✗ Anything requiring cardinality > a few thousand.           ║
║                                                                ║
║   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━    ║
║                                                                ║
║   LOGS                                                         ║
║   ────                                                         ║
║   What:  Discrete events, usually text, timestamped.           ║
║   Shape: line-oriented, JSON-structured, or binary.            ║
║   Cost:  EXPENSIVE per byte ingested.                          ║
║   Cardinality: ARBITRARY. Each event is unique.                ║
║                                                                ║
║   ANSWERS WELL:                                                ║
║   → "What did service X do at 14:32:07.428?"                   ║
║   → "Show me every error containing 'timeout' from this pod."  ║
║   → "What was the exact stack trace of that exception?"        ║
║                                                                ║
║   FAILS AT:                                                    ║
║   ✗ "What is the rate of errors?" (compute from logs is slow   ║
║     and expensive — that's what metrics are for)               ║
║   ✗ Aggregating across services without a correlation ID.      ║
║   ✗ Anything at scale: the cost is in YOUR LOG VOLUME, and     ║
║     teams blow $1M+/year on logs they never read.              ║
║                                                                ║
║   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━    ║
║                                                                ║
║   TRACES                                                       ║
║   ──────                                                       ║
║   What:  Causally-linked spans of work across services.        ║
║   Shape: tree of spans, each with start/end and metadata.      ║
║   Cost:  Per-span cost; sampling is REQUIRED at scale.         ║
║   Cardinality: ARBITRARY per span.                             ║
║                                                                ║
║   ANSWERS WELL:                                                ║
║   → "WHERE in the request did latency come from?"              ║
║   → "What downstream services did this request hit?"           ║
║   → "Why did THIS specific request fail?"                      ║
║   → "Show me every trace where the DB call took > 500ms."      ║
║                                                                ║
║   FAILS AT:                                                    ║
║   ✗ Aggregate questions ("error rate") — that's metrics.       ║
║   ✗ Without proper context propagation, trace is broken at     ║
║     each service boundary.                                     ║
║   ✗ Async/queued work: connecting "produce" and "consume"      ║
║     spans needs explicit linking.                              ║
║                                                                ║
╚════════════════════════════════════════════════════════════════╝
```

**The decision tree (memorize):**

```
You have a question. Which pillar?

┌─ "Is something broken right now? Trending bad?"
│  └─► METRICS. Always start here.
│
├─ "I see something is broken (from metrics). WHERE?"
│  └─► TRACES. Find the slow/failing span.
│
├─ "I found the broken span. WHAT EXACTLY happened?"
│  └─► LOGS for that span's service+timestamp.
│
└─ "I need historical aggregate of a high-cardinality dimension"
   (e.g., "p99 latency by user_id for top 1000 users")
   └─► WIDE EVENTS / HONEYCOMB-STYLE. The fourth pillar
       people pretend doesn't exist. See Part 2.6.

THE ANTI-PATTERN: 
Using logs to answer "is the error rate elevated?" 
You're paying $10/GB to do what metrics do for $0.10/series.
You also can't alert on it cleanly.
```

---

### 2.3 — Metrics Deep Dive: The Four Types and What They Cost

```
╔════════════════════════════════════════════════════════════════╗
║   METRIC TYPES                                                 ║
╠════════════════════════════════════════════════════════════════╣
║                                                                ║
║   COUNTER  — monotonically increasing                          ║
║   ─────────                                                    ║
║   Example:  http_requests_total{method="GET",status="200"}     ║
║   Resets to 0 on process restart.                              ║
║   Use rate() / increase() to query.                            ║
║                                                                ║
║   COMMON BUG: alerting on the raw counter value.               ║
║     BAD:   http_requests_total > 1000000                       ║
║     GOOD:  rate(http_requests_total[5m]) > 100                 ║
║                                                                ║
║   ───────────────────────────────────────────────────────────  ║
║                                                                ║
║   GAUGE  — point-in-time value, can go up or down              ║
║   ─────                                                        ║
║   Example:  memory_bytes_used                                  ║
║                                                                ║
║   COMMON BUG: scraping interval matters. A gauge sampled       ║
║   every 60s will MISS spikes shorter than 60s. The gauge       ║
║   represents "the value at scrape time," not "the average"     ║
║   or "the max."                                                ║
║                                                                ║
║   ───────────────────────────────────────────────────────────  ║
║                                                                ║
║   HISTOGRAM  — bucketed distribution                           ║
║   ─────────                                                    ║
║   Example:  http_request_duration_seconds_bucket{le="0.005"}   ║
║                                                                ║
║   ACTUALLY emits as MULTIPLE counter time-series:              ║
║     _bucket with le="0.005", le="0.01", ..., le="+Inf"         ║
║     _sum   total observed values                               ║
║     _count number of observations                              ║
║                                                                ║
║   Use histogram_quantile() to compute percentiles:             ║
║     histogram_quantile(0.99,                                   ║
║       sum by (le) (rate(http_request_duration_bucket[5m])))    ║
║                                                                ║
║   COMMON BUG: bucket boundaries set wrong.                     ║
║   Default Prometheus buckets are 5ms-10s. If your service      ║
║   responds in microseconds, 99% of observations fall into the  ║
║   le="0.005" bucket — every percentile reads as "<=5ms" with   ║
║   no resolution.                                               ║
║                                                                ║
║   ALWAYS pick buckets that match your actual distribution.     ║
║   Look at p50, p99, p999. Place boundaries near each.          ║
║                                                                ║
║   ───────────────────────────────────────────────────────────  ║
║                                                                ║
║   SUMMARY  — pre-computed quantiles                            ║
║   ────────                                                     ║
║   Example:  http_request_duration_seconds{quantile="0.99"}     ║
║                                                                ║
║   Computed CLIENT SIDE. Pre-aggregated.                        ║
║                                                                ║
║   THE FATAL FLAW: summaries CANNOT be aggregated across        ║
║   instances. If service A has 10 pods, each emitting a         ║
║   p99, you cannot compute the FLEET-WIDE p99 from those 10     ║
║   p99s. (Math fact: percentiles are not averageable.)          ║
║                                                                ║
║   USE HISTOGRAMS. Almost always. Summaries only when you       ║
║   need exact quantiles within a single instance and never      ║
║   need to aggregate.                                           ║
║                                                                ║
╚════════════════════════════════════════════════════════════════╝
```

---

### 2.4 — Cardinality: The Cost Model You Must Understand

This is the single most expensive observability mistake teams make.

```
╔════════════════════════════════════════════════════════════════╗
║   CARDINALITY = NUMBER OF UNIQUE TIME SERIES                   ║
╠════════════════════════════════════════════════════════════════╣
║                                                                ║
║   A metric with labels:                                        ║
║     http_requests_total{                                       ║
║       method,    // GET, POST, PUT, DELETE, PATCH = 5          ║
║       status,    // 200, 201, 400, 401, 404, 500, 503 = 7      ║
║       endpoint,  // /api/v1/users, /api/v1/orders, ... = 50    ║
║       region     // us-east-1, us-west-2, eu-west-1 = 3        ║
║     }                                                          ║
║                                                                ║
║   Cardinality = 5 × 7 × 50 × 3 = 5,250 series.                 ║
║   Cost: ~$5/month at typical pricing. Fine.                    ║
║                                                                ║
║   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━    ║
║   THE EXPLOSION:                                               ║
║   Engineer adds user_id label "to debug a user-specific bug":  ║
║                                                                ║
║     http_requests_total{                                       ║
║       method, status, endpoint, region,                        ║
║       user_id      // 2 million unique users                   ║
║     }                                                          ║
║                                                                ║
║   Cardinality = 5,250 × 2,000,000 = 10.5 BILLION series.       ║
║   Cost: ~$10M/month. Or your TSDB just falls over.             ║
║                                                                ║
║   This is not a hypothetical. It is the #1 cause of            ║
║   observability outages. Prometheus OOMs. Datadog bills        ║
║   shock the CFO. Both have happened to your future employer.   ║
║                                                                ║
║   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━    ║
║   THE RULES:                                                   ║
║                                                                ║
║   1. NEVER use unbounded values as labels:                     ║
║      ✗ user_id, request_id, trace_id, session_id               ║
║      ✗ email addresses                                         ║
║      ✗ raw URL paths (use route patterns: /users/:id)          ║
║      ✗ timestamps                                              ║
║      ✗ IP addresses (unless bounded to your fleet)             ║
║                                                                ║
║   2. BOUNDED values OK as labels:                              ║
║      ✓ method (5-10 values)                                    ║
║      ✓ status_code (~30 values)                                ║
║      ✓ region, az (small fixed set)                            ║
║      ✓ service, version (small set)                            ║
║      ✓ route patterns (your endpoint set)                      ║
║                                                                ║
║   3. Per-user data → traces or wide events, NEVER metrics.     ║
║                                                                ║
║   4. ESTIMATE cardinality before merging the PR:               ║
║      Multiply the cardinality of every label.                  ║
║      Reject anything > 10,000 per metric without explicit      ║
║      review.                                                   ║
║                                                                ║
║   5. Add a CI check: count distinct values per label in        ║
║      sample traffic. Refuse PRs that introduce labels with     ║
║      cardinality > N.                                          ║
║                                                                ║
╚════════════════════════════════════════════════════════════════╝
```

**Real example: the Datadog bill that paid for itself in lessons**

```
A real company (anonymized) deployed a feature flag service.
Every flag eval emitted a metric:
  flag_eval_total{flag_name, user_id, variant, env}

  flag_name: 200 flags
  user_id:   8 million users  ← THE BOMB
  variant:   3 variants
  env:       4 environments

  Cardinality = 200 × 8,000,000 × 3 × 4 = 19.2B series.

Datadog ingested for 6 hours before alerts fired.
That month's bill: $847,000 over budget.

The fix:
  flag_eval_total{flag_name, variant, env}      ← 2,400 series
  
  user_id moved to TRACES, sampled at 0.1%.
  
Cost reduction: $847k → $30. Same observability outcome.
The user-level question becomes "show traces where flag X
was evaluated for user Y" — a trace search, not a metric query.
```

---

### 2.5 — The USE Method (Resources) and RED Method (Services)

Two mental frameworks; together they cover most of what you should measure.

```
╔════════════════════════════════════════════════════════════════╗
║   USE METHOD — for every RESOURCE                              ║
║   (Brendan Gregg, originally for kernel/system)                ║
╠════════════════════════════════════════════════════════════════╣
║                                                                ║
║   For each resource (CPU, memory, disk, network, file          ║
║   descriptors, threads, DB connections, ...):                  ║
║                                                                ║
║   U — UTILIZATION  (% time the resource was busy)              ║
║   S — SATURATION   (queue depth / wait time when over capacity)║
║   E — ERRORS       (errors specifically from this resource)    ║
║                                                                ║
║   Example for CPU:                                             ║
║     U: cpu_usage_percent                                       ║
║     S: load_average_1m  (queue beyond CPU count)               ║
║     E: hardware error counters, throttling events              ║
║                                                                ║
║   Example for Postgres connection pool:                        ║
║     U: connections_in_use / max_connections                    ║
║     S: time_blocked_waiting_for_connection                     ║
║     E: connection_failures, timeout errors                     ║
║                                                                ║
║   Example for Kafka broker disk:                               ║
║     U: disk_busy_percent  (iostat %util)                       ║
║     S: disk_io_queue_depth, await_ms                           ║
║     E: read/write errors, EIO counts                           ║
║                                                                ║
║   USE catches: "the system is bottlenecked at X."              ║
╚════════════════════════════════════════════════════════════════╝

╔════════════════════════════════════════════════════════════════╗
║   RED METHOD — for every SERVICE                               ║
║   (Tom Wilkie, for request-driven architectures)               ║
╠════════════════════════════════════════════════════════════════╣
║                                                                ║
║   For each service / endpoint:                                 ║
║                                                                ║
║   R — RATE       (requests per second)                         ║
║   E — ERRORS     (failed requests per second, or fraction)     ║
║   D — DURATION   (latency distribution)                        ║
║                                                                ║
║   Example for /api/v1/checkout:                                ║
║     R: rate(http_requests_total{route="/checkout"}[5m])        ║
║     E: rate(http_requests_total{route="/checkout",             ║
║              status=~"5.."}[5m]) /                             ║
║        rate(http_requests_total{route="/checkout"}[5m])        ║
║     D: histogram_quantile(0.99,                                ║
║          rate(http_duration_bucket{route="/checkout"}[5m]))    ║
║                                                                ║
║   RED catches: "this user-facing thing is slow or failing."    ║
║                                                                ║
║   GOLDEN SIGNALS (Google SRE book) = RED + Saturation.         ║
║   Same thing, slightly different framing.                      ║
╚════════════════════════════════════════════════════════════════╝
```

**The instrumentation contract.** Every service should automatically expose RED. Every host should automatically expose USE for its main resources. This is not optional. This is the floor.

---

### 2.6 — The Fourth Pillar: Wide Events (Honeycomb-Style)

This category is younger than the other three, increasingly important, and rarely taught.

```
╔════════════════════════════════════════════════════════════════╗
║   WIDE EVENTS                                                  ║
╠════════════════════════════════════════════════════════════════╣
║                                                                ║
║   One event per unit of work (request, job, query).            ║
║   Each event has dozens to hundreds of FIELDS:                 ║
║     timestamp, duration, user_id, request_id, region,          ║
║     route, status, basket_size, payment_method, ab_variant,    ║
║     deploy_sha, hostname, kernel_version, client_app_version,  ║
║     downstream_pg_query_count, downstream_pg_total_ms,         ║
║     cache_hit_ratio, ... (50-200 fields typical)               ║
║                                                                ║
║   Stored in a column store optimized for fast aggregation      ║
║   over arbitrary dimensions.                                   ║
║                                                                ║
║   THE SUPERPOWER:                                              ║
║   You can ask questions you didn't think of in advance.        ║
║                                                                ║
║   Example: "p99 latency just spiked. Group by deploy_sha,      ║
║   region, basket_size, payment_method — show me which          ║
║   combination accounts for the spike."                         ║
║                                                                ║
║   With METRICS this is impossible (cardinality explosion).     ║
║   With LOGS this requires expensive full-text scans.           ║
║   With TRACES this is the right tool — wide events ARE         ║
║   trace spans, just stored for direct querying.                ║
║                                                                ║
║   THE COST MODEL:                                              ║
║   Per-event cost. Sample aggressively (head sampling 1-10%,    ║
║   tail sampling preserves errors).                             ║
║   Vendors: Honeycomb, Datadog (RUM/APM events), AWS            ║
║   CloudWatch Logs Insights (with structured logs).             ║
║                                                                ║
║   THE PRINCIPLE:                                               ║
║   For high-cardinality investigation, do NOT add labels to     ║
║   metrics. Add fields to events. Different tool, different     ║
║   cost model, different query semantics.                       ║
╚════════════════════════════════════════════════════════════════╝
```

---

### 2.7 — Distributed Tracing: Context Propagation, Sampling, OpenTelemetry

```
╔════════════════════════════════════════════════════════════════╗
║   THE TRACE MODEL                                              ║
╠════════════════════════════════════════════════════════════════╣
║                                                                ║
║   A TRACE is a tree of SPANS.                                  ║
║   Each SPAN represents a unit of work.                         ║
║                                                                ║
║   Trace ID:   abc123 (one per request, propagates everywhere)  ║
║                                                                ║
║   ┌─ span: HTTP POST /checkout (span-1, parent=null)           ║
║   │  duration: 247ms, status: 200                              ║
║   │                                                            ║
║   │  ┌─ span: validate-cart (span-2, parent=span-1)            ║
║   │  │  duration: 12ms                                         ║
║   │  │                                                         ║
║   │  │  └─ span: pg-query SELECT cart (span-3, parent=span-2)  ║
║   │  │     duration: 8ms                                       ║
║   │  │                                                         ║
║   │  ├─ span: charge-payment (span-4, parent=span-1)           ║
║   │  │  duration: 198ms  ◄── the long pole                     ║
║   │  │                                                         ║
║   │  │  └─ span: stripe-api (span-5, parent=span-4)            ║
║   │  │     duration: 195ms ◄── why                             ║
║   │  │                                                         ║
║   │  └─ span: kafka-produce (span-6, parent=span-1)            ║
║   │     duration: 14ms                                         ║
║                                                                ║
║   The tree shows you exactly where time went.                  ║
║   "Stripe took 195ms" is the answer to "why was checkout slow."║
║                                                                ║
╚════════════════════════════════════════════════════════════════╝
```

**Context propagation — the part everyone gets wrong:**

```
  Service A receives a request. It calls Service B via HTTP,
  which calls Service C via gRPC, which publishes to Kafka,
  which is consumed by Service D.

  For all of these to appear in ONE trace, the trace_id and
  parent span_id must be PROPAGATED across every boundary.

  HTTP:     traceparent header (W3C Trace Context standard)
            traceparent: 00-{trace_id}-{span_id}-{flags}

  gRPC:     traceparent in metadata (same standard)

  Kafka:    headers on the producer record:
              record.headers.add("traceparent", value)
            Consumer reads header, uses it as parent span.
            Without this, the Kafka boundary BREAKS the trace.

  Async queues / DB triggers / cron jobs: even harder. Each
  boundary requires explicit instrumentation.

  THE FAILURE MODE:
  Half-instrumented systems produce TRACE FRAGMENTS — short
  trees that end abruptly at the un-instrumented boundary.
  Useless for the "where did time go" question across the
  whole request.

  THE FIX:
  OpenTelemetry's auto-instrumentation libraries handle most
  HTTP/gRPC/SQL/Kafka cases. Use them everywhere; treat
  manual instrumentation as the exception.
```

**Sampling — the cost reality:**

```
  At scale, capturing every trace is unaffordable.
  
  HEAD SAMPLING:
  At trace start, decide: keep this trace or drop it?
  Decision propagates via the traceparent flags bit.
  Pros: simple, cheap (no buffering).
  Cons: rare events (errors!) are also dropped at the
        sample rate. p99 traces invisible.

  TAIL SAMPLING:
  Buffer ALL spans for some window (e.g. 30s).
  At trace end, decide: was this interesting?
    - Keep: errors, slow traces (>p95), specific endpoints.
    - Drop: normal traces.
  Pros: keeps the traces that MATTER.
  Cons: requires buffering infrastructure (OTel collector
        with tail-sampling processor). Memory-bounded.

  THE RIGHT ANSWER FOR PRODUCTION:
  Tail sample. Keep:
    - 100% of error traces
    - 100% of traces > p95 latency
    - 1-5% of normal traces (statistical baseline)

  Some vendors (Honeycomb) do this by default with a
  "dynamic sampling" feature.
```

---

### 2.8 — SLOs and Error Budgets: The Math That Drives Alerting

The Google SRE book's most-often-misapplied concept. Get it right and your alerts go from "noisy" to "actionable."

```
╔════════════════════════════════════════════════════════════════╗
║   SLI / SLO / ERROR BUDGET                                     ║
╠════════════════════════════════════════════════════════════════╣
║                                                                ║
║   SLI (Service Level Indicator):                               ║
║   A measurement of user experience as a RATIO of               ║
║   "good events / total events."                                ║
║                                                                ║
║   Example SLIs for /checkout:                                  ║
║     Availability:  successful_requests / total_requests        ║
║     Latency:       requests_below_500ms / total_requests       ║
║                                                                ║
║   SLO (Service Level Objective):                               ║
║   A target for the SLI over a window.                          ║
║                                                                ║
║     "99.9% of requests succeed over a rolling 30-day window."  ║
║     "99% of requests complete in <500ms over 30 days."         ║
║                                                                ║
║   ERROR BUDGET:                                                ║
║   1 - SLO. The ALLOWED failure rate.                           ║
║                                                                ║
║     SLO 99.9% → error budget 0.1%                              ║
║     30 days × 24h × 60min × 0.001 = 43.2 minutes/month         ║
║                                                                ║
║   You are ALLOWED to spend the budget. That is the point.      ║
║   100% reliability is impossible and trying for it makes       ║
║   you slow at shipping features.                               ║
║                                                                ║
╚════════════════════════════════════════════════════════════════╝
```

**Burn-rate alerting — the right way to alert on SLOs:**

```
THE NAIVE APPROACH (wrong):
  Alert if error_rate > 0.1% for 5 minutes.

  Problems:
  - 0.1% over 5 min ≠ 0.1% over 30 days. Tiny windows are noisy.
  - Alert fires on transient blips that don't actually consume
    significant budget.
  - Can MISS a slow burn that consumes the entire 30-day budget
    over 25 days at 0.05% sustained.

THE BURN RATE APPROACH:
  Burn rate = how fast you're consuming budget relative to its
  natural rate.

    Natural burn rate = 1 (consume 100% of budget in 30 days)
    2x burn = consume budget in 15 days
    14.4x burn = consume budget in ~2 days
    36x burn = consume budget in 20 hours

  Define MULTI-WINDOW alerts:

  FAST BURN (page immediately):
    Alert if (1h burn rate > 14.4) AND (5m burn rate > 14.4)
    Catches: severe outages. Fires within minutes.
    "At this rate, budget gone in 2 days."

  MEDIUM BURN (page during business hours):
    Alert if (6h burn rate > 6) AND (30m burn rate > 6)
    "At this rate, budget gone in ~5 days."

  SLOW BURN (ticket; investigate next day):
    Alert if (3d burn rate > 1) AND (6h burn rate > 1)
    "At this rate, budget gone before window closes."

  WHY MULTI-WINDOW:
  The SHORT window detects the spike fast.
  The LONG window prevents flapping (a brief spike returns
  to normal; long window stays low; alert silenced).
  Both must trigger. Reduces false positives by ~10x.

  WHY THESE NUMBERS (14.4, 6, 1):
  They correspond to consuming a specific fraction of monthly
  budget in the alert window:
    14.4x for 1h consumes 2% of monthly budget in 1h
    6x for 6h consumes 5% of monthly budget in 6h
  These are Google SRE workbook recommendations.
```

**Worked PromQL example:**

```yaml
# 30-day SLO: 99.9% availability for /checkout
# Error budget: 0.1%

# 5m and 1h burn rates, fast-burn alert:
- alert: CheckoutFastBurn
  expr: |
    (
      (
        sum(rate(http_requests_total{route="/checkout",status=~"5.."}[5m]))
        /
        sum(rate(http_requests_total{route="/checkout"}[5m]))
      ) > (14.4 * 0.001)
    )
    and
    (
      (
        sum(rate(http_requests_total{route="/checkout",status=~"5.."}[1h]))
        /
        sum(rate(http_requests_total{route="/checkout"}[1h]))
      ) > (14.4 * 0.001)
    )
  for: 2m
  labels:
    severity: page
    slo: checkout_availability
  annotations:
    summary: "Checkout burning error budget at 14.4x rate"
    description: |
      At current rate, 30-day error budget will be exhausted
      in ~2 days. Investigate /checkout 5xx errors immediately.
```

---

### 2.9 — Alerting Pathologies and How to Avoid Them

```
╔════════════════════════════════════════════════════════════════╗
║   THE FIVE COMMON PATHOLOGIES                                  ║
╠════════════════════════════════════════════════════════════════╣
║                                                                ║
║   1. ALERT FATIGUE                                             ║
║   ───────────────                                              ║
║   Symptom: on-call ignores pages because most are noise.       ║
║   Cause: paging on cause (CPU > 90%) instead of symptom        ║
║   (user-facing error rate). CPU at 92% with no user impact     ║
║   is not a page.                                               ║
║   Fix: Page only on USER-VISIBLE SLO violations. Cause-level   ║
║   alerts are tickets/Slack, not pages.                         ║
║                                                                ║
║   2. FLAPPING                                                  ║
║   ──────────                                                   ║
║   Symptom: alert fires, resolves, fires, resolves, every       ║
║   30 seconds.                                                  ║
║   Cause: metric oscillates around the threshold.               ║
║   Fix: 'for: Xm' clause requires sustained breach. Multi-      ║
║   window burn rate (above) is largely immune.                  ║
║                                                                ║
║   3. PAGE-ON-CAUSE INSTEAD OF SYMPTOM                          ║
║   ────────────────────────────────                             ║
║   Symptom: get paged "DB CPU high"; user impact unknown.       ║
║   Cause: alerting on internal metric without verifying it      ║
║   matters.                                                     ║
║   Fix: alert on the SYMPTOM (checkout latency); the CAUSE      ║
║   (DB CPU) is a runbook diagnostic, not a separate page.       ║
║   Exception: leading indicators with high confidence of        ║
║   imminent customer impact (Kafka under-min-ISR — there's      ║
║   no symptom-level alert that fires earlier).                  ║
║                                                                ║
║   4. NO RUNBOOK / NO ACTIONABLE NEXT STEP                      ║
║   ───────────────────────────────────────                      ║
║   Symptom: pager reads "service X unhealthy" — what now?       ║
║   Fix: every alert MUST link to a runbook with at least:       ║
║       - What does this mean?                                   ║
║                                                                ║
║       - First three diagnostic queries                         ║
║       - Common causes and fixes                                ║
║       - Escalation path                                        ║
║                                                                ║
║   5. SILENT FAILURES (no alert at all)                         ║
║   ─────────────────────                                        ║
║   Symptom: incident discovered by customer ticket.             ║
║   Cause: the failure mode wasn't anticipated in the alert      ║
║   set. Common: data quality issues, partial outages,           ║
║   downstream services degraded but service-X "up."             ║
║   Fix:                                                         ║
║     - Alert on USER-FACING SLOs (catches the unanticipated).   ║
║     - Synthetic monitoring (probes that exercise key flows).   ║
║     - "Has this counter incremented at all in 1h?" alerts      ║
║       for low-volume flows that should never go silent.        ║
║                                                                ║
╚════════════════════════════════════════════════════════════════╝
```

**Symptom-based alerting is the principal's discipline.** From the Google SRE book: every page should correspond to a user-visible problem worth waking someone up for. If you can't draw a line from the alert to something a user noticed (or will notice within minutes), it's not a page.

---

### 2.10 — Real Systems: Prometheus, Grafana, Loki, Tempo, Datadog, Honeycomb

```
╔════════════════════════════════════════════════════════════════╗
║   THE OBSERVABILITY STACK CHOICES                              ║
╠════════════════════════════════════════════════════════════════╣
║                                                                ║
║   PROMETHEUS (metrics, OSS)                                    ║
║   ─────────────────────────                                    ║
║   Model:     PULL — scrapes targets every 15-60s.              ║
║   Storage:   local TSDB, single-node by default.               ║
║   Query:     PromQL.                                           ║
║   Scale:     ~1M active series per node. Beyond → federation,  ║
║              Thanos, Mimir, Cortex (long-term storage layers). ║
║   Cost:      free (compute/storage you run).                   ║
║                                                                ║
║   GOTCHA #1: Pull model means scraping interval = sampling     ║
║   resolution. 15s scrape can miss 10s spikes.                  ║
║                                                                ║
║   GOTCHA #2: Default rate() formula needs >= 4 samples in      ║
║   the window. rate(metric[1m]) with 30s scrape interval can    ║
║   be flaky.                                                    ║
║                                                                ║
║   GOTCHA #3: histogram_quantile() interpolates within          ║
║   buckets. If bucket boundaries are wrong, the answer is       ║
║   wrong by orders of magnitude.                                ║
║                                                                ║
║   ───────────────────────────────────────────────────────────  ║
║                                                                ║
║   GRAFANA (visualization, OSS + cloud)                         ║
║   ─────────────────────────────────────                        ║
║   Backend-agnostic dashboards. Connects to Prometheus,         ║
║   Loki, Tempo, Datadog, Cloudwatch, Postgres, ...              ║
║                                                                ║
║   PRINCIPAL'S RULE: dashboards are FOR INCIDENTS, NOT for      ║
║   "looking pretty in steady state." Every dashboard should     ║
║   answer ONE specific question that helps an oncall during     ║
║   an incident.                                                 ║
║                                                                ║
║   ───────────────────────────────────────────────────────────  ║
║                                                                ║
║   LOKI (logs, OSS)                                             ║
║   ────────────────                                             ║
║   Designed for cheap log storage. Indexes only labels (not     ║
║   full-text). Query with LogQL.                                ║
║                                                                ║
║   GOTCHA: low ingestion cost; high query cost on text scans.   ║
║   Rule: index by structured labels (service, level), grep      ║
║   for text in known small windows.                             ║
║                                                                ║
║   ───────────────────────────────────────────────────────────  ║
║                                                                ║
║   TEMPO / JAEGER (traces, OSS)                                 ║
║   ────────────────────────────                                 ║
║   Tempo: object-store-backed, cheap retention.                 ║
║   Jaeger: older, more featureful UI, more ops.                 ║
║                                                                ║
║   ───────────────────────────────────────────────────────────  ║
║                                                                ║
║   DATADOG (commercial, full-stack)                             ║
║   ────────────────────────────────                             ║
║   All three pillars + APM + RUM. Excellent UX. Cost grows      ║
║   superlinearly with cardinality and log volume.               ║
║                                                                ║
║   GOTCHA: custom metric pricing per ~100 unique tag combos.    ║
║   "Free" labels are ANYTHING but free past a threshold.        ║
║                                                                ║
║   ───────────────────────────────────────────────────────────  ║
║                                                                ║
║   HONEYCOMB (commercial, wide events)                          ║
║   ────────────────────────────────────                         ║
║   The Wide Events specialist. Different mental model:          ║
║   ALL columns are query-able, NONE is "an index choice."       ║
║   For high-cardinality investigation work, frequently the      ║
║   right answer.                                                ║
║                                                                ║
║   ───────────────────────────────────────────────────────────  ║
║                                                                ║
║   AWS CLOUDWATCH                                               ║
║   ────────────────                                             ║
║   Default for AWS shops. Much improved (Logs Insights,         ║
║   Metric Streams, X-Ray for tracing). Costs and ergonomics     ║
║   trail dedicated stacks.                                      ║
║                                                                ║
╚════════════════════════════════════════════════════════════════╝
```

---

## Failure Modes

```
FAILURE 1: CARDINALITY EXPLOSION
  Symptom:  Prometheus/CloudWatch OOM or cost spike after a deploy.
  Cause:    a label with unbounded values (user_id, request_id, full URL path).
  Math:     series = product of label cardinalities. Adding user_id (1M) to a
            metric with 20 existing series = 20M series.
  Fix:      remove high-cardinality labels; use exemplars/traces for per-request
            detail; enforce a cardinality budget in CI.

FAILURE 2: SAMPLING GAPS
  Symptom:  a real P1 error class is invisible in traces.
  Cause:    head-based sampling (decide at ingress) drops 99% BEFORE knowing the
            request errored.
  Fix:      tail-based sampling (decide after the trace completes) + always-keep
            on error/slow spans.

FAILURE 3: LOG COST RUNAWAY
  Symptom:  observability bill doubles; no incident.
  Cause:    debug logging left on in prod, or logging full payloads per request.
  Fix:      log levels by environment, structured fields not blobs, retention
            tiers, sampling of high-volume info logs.

FAILURE 4: ALERT FATIGUE / FLAPPING
  Symptom:  oncall ignores pages; real incident missed.
  Cause:    threshold alerts on self-healing metrics (single-spike CPU),
            no multi-window logic.
  Fix:      alert on user-facing SYMPTOMS via SLO burn rate (see SLOs module),
            multi-window (fast + slow), with hysteresis.

FAILURE 5: TRACE PROPAGATION BREAK
  Symptom:  traces stop at a service boundary; "orphan" spans.
  Cause:    a hop drops trace context headers (traceparent), or an async queue
            loses correlation IDs.
  Fix:      propagate W3C traceparent everywhere incl. queues; assert context in
            integration tests.

FAILURE 6: CLOCK SKEW IN SPANS/LOGS
  Symptom:  child span "starts before" parent; log ordering nonsensical.
  Cause:    unsynced host clocks (ties to Week 8 clocks module).
  Fix:      NTP/chrony discipline; rely on span parent/child causality, not raw
            wall-clock ordering.
```

---

## SRE Diagnostic Toolkit

```
THE THREE PILLARS — WHAT EACH ANSWERS
  Metrics  -> "IS something wrong, and how bad?" (cheap, aggregate, alertable)
  Traces   -> "WHERE in the request path?" (per-request causal chain)
  Logs     -> "WHY exactly did this instance fail?" (detail, expensive at scale)

SERVICE HEALTH — RED METHOD (per service/endpoint)
  Rate:     rate(http_requests_total[5m])
  Errors:   rate(http_requests_total{status=~"5.."}[5m])
  Duration: histogram_quantile(0.99,
              rate(http_request_duration_seconds_bucket[5m]))

RESOURCE HEALTH — USE METHOD (per resource)
  Utilization, Saturation (queue depth / run-queue), Errors.
  node_cpu_seconds_total, node_load1, disk IO await, network drops.

LOGS (structured, queryable)
  CloudWatch Logs Insights:
    fields @timestamp, @message, service, level, trace_id
    | filter level = "ERROR"
    | stats count() by service, bin(5m)
  Loki (LogQL): {service="checkout",level="error"} | json | line_format ...
  Rule: index by low-cardinality LABELS; grep text in small time windows.

TRACES
  Verify propagation end-to-end (W3C traceparent). In X-Ray/Jaeger/Tempo:
  pivot from a slow/error span -> host metrics -> deploy event in 3 clicks.
  Tail-based sampling; always keep error and slow traces.

CARDINALITY GUARDRAIL (do this BEFORE shipping a metric)
  estimated_series = product of (distinct values of each label)
  Refuse user_id, request_id, raw path, or unbounded IDs as metric labels.
  Put per-request identity in traces/logs, not metrics.

INCIDENT WORKFLOW
  1. SLO burn-rate alert fires (symptom).  2. Dashboard: which service/endpoint?
  3. Trace: which hop adds latency/errors? 4. Logs: exact error on that hop.
  5. Correlate to deploy/config change.
```

---

## Decision Framework

```
WHICH PILLAR FOR WHICH QUESTION

  ┌────────────────────────────────┬───────────┬────────────────────────────┐
  │ Question                       │ Pillar    │ Why                        │
  ├────────────────────────────────┼───────────┼────────────────────────────┤
  │ Are we within SLO right now?   │ Metrics   │ cheap, aggregate, alertable│
  │ Which service/hop is slow?     │ Traces    │ per-request causal chain   │
  │ Why did THIS request fail?     │ Logs      │ full detail on one event   │
  │ Novel question in an incident  │ Traces +  │ high-cardinality, ad-hoc   │
  │ we didn't predict              │ wide logs │ pivots                     │
  └────────────────────────────────┴───────────┴────────────────────────────┘

WHAT TO ALERT ON
  Page on user-facing SYMPTOMS via SLO burn rate (see
  "SLOs SLIs Error Budgets and Alerting.md"), NOT on causes like CPU%.
  Cause metrics belong on dashboards for diagnosis, not on the pager.

SAMPLING STRATEGY
  Low traffic       -> keep everything.
  High traffic      -> tail-based sampling + always-keep error/slow traces.
  Never             -> 100% trace retention at high RPS (cost + collector melt).

VENDOR / STACK CHOICE
  ┌───────────────────────┬────────────────────────────────────────────────┐
  │ AWS-native            │ CloudWatch (metrics/logs) + X-Ray (traces)     │
  │ Kubernetes / OSS      │ Prometheus + Grafana + Loki + Tempo            │
  │ High-cardinality      │ Honeycomb / Datadog (cost-aware; watch custom  │
  │ investigation         │ metric + log volume pricing)                   │
  └───────────────────────┴────────────────────────────────────────────────┘

COST DISCIPLINE
  Metrics cost scales with CARDINALITY; logs with VOLUME; traces with
  RETENTION x sampling. Budget each independently and review monthly.
```

---

## Incident Scenario

### 3.1 — The System

```
PRODUCT:
  E-commerce platform "Glasswing." 12M MAU, ~$8M/day GMV.
  Checkout SLO: 99.9% availability over 30 days, p99 < 800ms.

ARCHITECTURE:

  ┌───────────────────────────────────────────────────────────┐
  │  EDGE                                                     │
  │  CloudFront → ALB → 240 × edge-svc pods (Go)              │
  │     Each pod: 1 vCPU, 512 MB, behind k8s Service          │
  │     Routes /api/v1/checkout → checkout-svc                │
  ├───────────────────────────────────────────────────────────┤
  │  APPLICATION TIER                                         │
  │  checkout-svc:    80 pods, Go, calls 7 downstream svcs    │
  │  cart-svc:        40 pods, Go                             │
  │  pricing-svc:     32 pods, Go (Redis-heavy)               │
  │  inventory-svc:   24 pods, Java                           │
  │  payments-svc:    16 pods, Go (Stripe API)                │
  │  fraud-svc:       12 pods, Python (ML)                    │
  │  promo-svc:       16 pods, Go (Redis-heavy)               │
  │  user-svc:        24 pods, Go                             │
  ├───────────────────────────────────────────────────────────┤
  │  DATA TIER                                                │
  │  Postgres:         primary + 2 replicas (Aurora)          │
  │  Redis:            6-node cluster, total 96GB             │
  │  Kafka:            12 brokers (from previous module)      │
  │  Elasticsearch:    9 nodes                                │
  └───────────────────────────────────────────────────────────┘

OBSERVABILITY STACK:
  Metrics:   Prometheus (Mimir for long-term), 15s scrape,
             ~3.2M active series.
  Logs:      Loki, ~600 GB/day ingest.
  Traces:    Tempo + OpenTelemetry, head-sampled at 5%.
  Dashboards: Grafana, ~180 dashboards (most unused).
  Alerting:  Alertmanager → PagerDuty.

ALERTS DEFINED FOR CHECKOUT:
  - CheckoutFastBurn (SLO 14.4x, 5m+1h windows) → page
  - CheckoutSlowBurn (SLO 6x, 30m+6h windows) → ticket
  - CheckoutP99High (>1500ms for 10m) → page (legacy, redundant)
  - HTTPErrorRateHigh (>0.5% for 5m) → page (legacy)
  - PostgresCPUHigh, RedisCPUHigh, KafkaLagHigh → Slack
```

### 3.2 — The Timeline

```
DAY 0 (Tuesday)
─────────────────
14:30  Marketing launches "FlashFriday" promo. Predictable
       traffic uptick: +35% RPS over baseline. Capacity
       reviewed and signed off by SRE last week.
       Checkout p99 baseline: 280ms.
       Checkout availability MTD: 99.97%.

19:00  Traffic peaks: 4,200 RPS. Checkout p99: 312ms.
       Within SLO. No alerts.

23:00  Traffic ebbs to 1,800 RPS. p99: 290ms. Normal night.


DAY 1 (Wednesday)
─────────────────
09:00  Morning ramp begins. p99: 295ms. Nothing notable.

14:00  p99 has crept to 340ms. Within SLO (800ms). No alert.

18:00  p99: 380ms. Still within SLO. Nothing fires.


DAY 2 (Thursday)
─────────────────
10:00  p99: 410ms. CheckoutSlowBurn fires (SLO 6x).
       Slack-only alert. SRE-on-call sees it but no page.
       Triages briefly: "no obvious cause; will watch."
       Logs the alert in #observability and moves on.

14:00  p99: 470ms. PostgresCPUHigh Slack alert fires.
       PG primary CPU: 78% (threshold 70%). DBA-on-call
       acknowledges, opens dashboard. CPU has been climbing
       slowly since Tuesday afternoon. Top queries look
       normal-ish. Adds to next-day investigation list.

16:30  p99: 510ms. RedisCPUHigh on cluster node-3.
       Slack-only. No one looks immediately.

22:00  p99: 580ms. Quiet night. No human attention.


DAY 3 (Friday)
─────────────────
08:00  p99: 620ms. The slow-burn alert has been firing
       on-and-off for 22h. No one has dug in.

11:30  p99: 720ms. Approaching SLO threshold of 800ms.

12:14  THE PAGE
       ───────
       Multiple alerts fire within 90 seconds:
       - CheckoutFastBurn (14.4x in last 5m)
       - CheckoutP99High (1620ms for 10m)
       - HTTPErrorRateHigh (0.7%, mostly 504s)
       - Customer complaints in #support: "checkout broken"
       - Twitter mentions ticking up

       SRE-on-call paged. Status:
       - Checkout p99: 1620ms (SLO 800ms — violated)
       - Checkout p99.9: 4800ms (timeouts at edge starting)
       - Error rate: 0.7%, climbing
       - Affected fraction of traffic: ALL checkouts
       - 30-day error budget: 78% consumed by 12:14, this
         single hour will consume the rest if not fixed
       - Compliance audit reminder: NO. (Different module.)

  YOU ARE ON-CALL. The page hits. What do you do?
```

### 3.3 — The Walkthrough (Principal-Grade)

```
MINUTE 0 (12:14) — TRIAGE
━━━━━━━━━━━━━━━━━━━━━━━━

  The temptation: open every dashboard.
  The discipline: ONE question first. "Where in the request
  is the time going?"

  This is a TRACE question, not a metrics question.

  Open the trace view. Filter:
    service.name = checkout-svc
    duration > 1000ms
    timestamp > now-15m

  Hopefully ~50-200 traces. Open one. Look at the span tree.

  HYPOTHETICAL TRACE (the one you find):

   POST /checkout (1842ms total)
   ├─ validate-cart            (28ms)
   ├─ get-pricing             (1648ms) ◄── 90% of total
   │  ├─ redis-get             (4ms)
   │  ├─ pricing-rules-eval    (12ms)
   │  └─ pg-query "SELECT ... FROM promo_eligibility ..."
   │                          (1620ms) ◄── here
   ├─ check-inventory          (52ms)
   ├─ charge-payment           (110ms)
   └─ kafka-produce            (8ms)

  In 90 seconds you've located the problem:
  - It's in pricing-svc
  - Specifically in a Postgres query against
    promo_eligibility table
  - That single query is 1620ms; everything else is fast

  Without traces, this triage takes 20-30 minutes of metric-
  pivoting and dashboard-clicking. With traces, 90 seconds.


MINUTE 2 (12:16) — CONFIRM IT'S NOT A SINGLE OUTLIER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Open 5 more slow traces. All show the same long pole:
  pg-query against promo_eligibility, 1.4-1.8s.

  Quick check on aggregate. Wide-event query (or PromQL on
  pricing-svc's pg query duration histogram):

    histogram_quantile(0.99, sum by (query_name, le)(
      rate(pg_query_duration_seconds_bucket
            {service="pricing-svc"}[5m])
    ))

  Result: query_name="promo_eligibility_lookup" p99 = 1610ms.
  Other pricing queries: all <50ms.

  This is the single source of pain. NOT a generic database
  issue. NOT a network issue. ONE query.


MINUTE 4 (12:18) — WHY IS THIS QUERY SLOW?
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Open Postgres-side dashboards.

  pg_stat_statements for the offending query:
    calls       executions/min   mean_time   total_time
    1.2M (24h)  830/min          850ms       17.2 min/min
                                             (CPU saturated)

  Compare to 4 days ago (when fine):
    calls       executions/min   mean_time
    140k (24h)  97/min           14ms

  TWO things changed:
  1. Call rate up ~8.5x (from 97/min to 830/min)
  2. Mean time up ~60x (from 14ms to 850ms)

  The 60x latency increase per call is the bigger anomaly.
  Call rate alone (8.5x) shouldn't cause 60x latency unless
  the query plan changed.


MINUTE 6 (12:20) — THE EXPLAIN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  EXPLAIN (ANALYZE, BUFFERS) on the slow form of the query:

    Seq Scan on promo_eligibility  (cost=0.00..245001 rows=1)
      Filter: ((user_id = $1) AND (promo_code = $2))
      Rows Removed by Filter: 14,847,000
    Planning Time: 0.31 ms
    Execution Time: 1,610.87 ms

  Sequential scan of 14.8M rows. There MUST be an index.
  Check:
    \d promo_eligibility
    Indexes:
      "promo_eligibility_pkey" PRIMARY KEY (id)
      "ix_promo_user_code" btree (user_id, promo_code)
                             ◄── exists, but PG isn't using it

  Why is the planner not using the index?
  
  Check pg_stats:
    SELECT * FROM pg_stats 
    WHERE tablename = 'promo_eligibility' 
      AND attname IN ('user_id', 'promo_code');

   - user_id:    n_distinct = 12,401 (table actually has 8M)
   - promo_code: n_distinct = 47 (actually has 8,200)
   - last_analyze:    Tuesday 01:14 UTC

  STATS ARE WRONG AND STALE.

  What happened:
  - Marketing's FlashFriday promo created ~8,200 new
    promo codes Tuesday morning.
  - Promo eligibility rows: ~14M new entries.
  - autovacuum/autoanalyze threshold for this table:
    autovacuum_analyze_scale_factor=0.1 (default),
    autovacuum_analyze_threshold=50 (default).
    So analyze fires when 10% of rows change.
  - Original table size: 800k rows. 10% = 80k.
  - But the table now has 15M rows. The threshold scales
    relative to current size: 10% of 15M = 1.5M.
  - 14M new rows DID exceed even the new threshold.
  - But: the table is also being heavily updated, and
    autovacuum has been DEFERRING analysis because of
    higher-priority dead-tuple cleanup on hotter tables.
  - Net effect: no successful ANALYZE since Tuesday 01:14.

  Postgres planner sees n_distinct=47 for promo_code,
  estimates the index won't be selective, picks a seq scan
  "because the table seems small" based on stale stats.

  The plan flipped on Tuesday afternoon as table grew.
  The slow-burn started then. You watched it build for 70
  hours before it crossed your SLO.


MINUTE 8 (12:22) — DECIDE THE FIX
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Three options:

  A. ANALYZE promo_eligibility immediately.
     → Updates statistics. Planner re-evaluates plan on
       next query.
     → Risk: LOCK requirements minimal (ShareUpdateExclusive,
       compatible with reads/writes).
     → Time: ~30s for an 15M row table on this hardware.
     → Reversibility: trivial.

  B. CREATE INDEX CONCURRENTLY ix_promo_user_code_v2
     (user_id, promo_code) INCLUDE (...).
     → New, fresh index with current cardinality stats.
     → Time: ~3-5 minutes.
     → Risk: low (CONCURRENTLY).
     → Probably unnecessary if the existing index is fine
       once stats update.

  C. Hint the planner with SET LOCAL enable_seqscan=off.
     → Tactical fix per session/transaction.
     → Doesn't address root cause.
     → Useful only if A is somehow blocked.

  PRINCIPAL'S CALL: A. Run ANALYZE.

  Reasoning:
  - The fastest reversible fix at the actual root cause.
  - Customer impact compounds every minute we wait.
  - We can do B as a follow-up to make the system more
    resilient if needed.

  COMMAND:
    psql -h pg-primary -d glasswing -c \
      "ANALYZE VERBOSE promo_eligibility;"


MINUTE 9-12 (12:23-12:26) — EXECUTE AND VERIFY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  12:23:00  ANALYZE starts.
  12:23:32  ANALYZE complete.
            "analyzing public.promo_eligibility"
            "scanned 30000 of 1834928 pages, containing
             14847982 live rows..."
            New stats land: n_distinct(promo_code) = 8,143.

  12:23:35  Run a sample query manually:
            EXPLAIN ANALYZE SELECT ... FROM promo_eligibility
              WHERE user_id = X AND promo_code = Y;
            
            Index Scan using ix_promo_user_code  (cost=0.43..8.45)
              Index Cond: ((user_id = X) AND (promo_code = Y))
            Execution Time: 0.42 ms

            Index used. Plan healthy. ~1.6s → 0.4ms.

  12:23:50  pricing-svc traces show the query at <5ms.
  12:24:30  checkout p99: 1620ms → 1100ms → 580ms → 320ms.
  12:25:00  Error rate: 0.7% → 0.1% → 0.0%.
  12:26:00  All alerts cleared. Page resolved.

  Total customer impact: 12 minutes from page to recovery.
  Total impact from first SLO violation: ~15 minutes.
  Total from first slow-burn signal (Thursday 10:00): 50 hours.


MINUTE 30 (12:44) — FOLLOW-UP ACTIONS WHILE STILL ON BRIDGE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Don't leave the bridge yet. The system is fixed but
  fragile. Take immediate follow-ups:

  1. Set table-level autovacuum_analyze_scale_factor for
     promo_eligibility to 0.02 (2% instead of 10%).
     ALTER TABLE promo_eligibility SET (
       autovacuum_analyze_scale_factor = 0.02,
       autovacuum_analyze_threshold = 1000
     );

  2. Schedule daily ANALYZE on top-10 query-volume tables
     via cron. Belt-and-suspenders.

  3. Open a postmortem doc. Set the meeting for Monday.

  4. Create three Jira tickets (next section).
```

### 3.4 — Mitigation Timeline Summary

```
╔════════════════════════════════════════════════════════════════╗
║   TIME    │ ACTION                          │ FIXES            ║
╠════════════════════════════════════════════════════════════════╣
║   0:00    │ Open trace view, filter slow    │ Locate WHERE     ║
║   12:14   │ traces, find common long-pole   │ time is going    ║
╠════════════════════════════════════════════════════════════════╣
║   2:00    │ Confirm aggregate (PromQL on    │ Confirm not      ║
║   12:16   │ pg_query_duration histogram by  │ outlier — it's   ║
║           │ query name)                     │ systemic         ║
╠════════════════════════════════════════════════════════════════╣
║   4:00    │ pg_stat_statements + EXPLAIN    │ Diagnose query   ║
║   12:18   │ ANALYZE on slow query           │ plan flipped     ║
╠════════════════════════════════════════════════════════════════╣
║   6:00    │ pg_stats + check last_analyze   │ Identify cause:  ║
║   12:20   │                                 │ stale statistics ║
╠════════════════════════════════════════════════════════════════╣
║   8:00    │ Decide intervention: ANALYZE    │ Reversibility +  ║
║   12:22   │ over CREATE INDEX or hint       │ root-cause focus ║
╠════════════════════════════════════════════════════════════════╣
║   9:00    │ Run ANALYZE VERBOSE             │ Refresh planner  ║
║   12:23   │ promo_eligibility               │ statistics       ║
╠════════════════════════════════════════════════════════════════╣
║   10:30   │ Verify with EXPLAIN ANALYZE     │ Confirm plan     ║
║   12:24   │ + watch checkout p99 dashboard  │ flipped back     ║
╠════════════════════════════════════════════════════════════════╣
║   12:00   │ Page resolved, alerts clear     │ Recovery         ║
║   12:26   │                                 │                  ║
╠════════════════════════════════════════════════════════════════╣
║   30:00   │ Tighten autoanalyze threshold   │ Prevent recur    ║
║   12:44   │ on promo_eligibility (table-    │ on this table    ║
║           │ level setting)                  │                  ║
╚════════════════════════════════════════════════════════════════╝
```

### 3.5 — The Postmortem Findings (the observability lessons)

```
1. THE SLOW BURN ALERT FIRED 50 HOURS BEFORE THE PAGE.
   It went to Slack and was triaged-and-dismissed. Twice.
   The on-call who saw it on Thursday morning didn't dig
   in because:
   - p99 was still within SLO
   - "Probably promo traffic, will normalize"
   - No clear runbook for slow-burn triage
   
   ACTION: slow-burn alerts MUST link to a runbook with
   mandatory steps:
     a) Open trace view, find slowest spans
     b) Identify the long-pole component
     c) If unclear in 15 min, escalate to Slack
   Triage SLA: every slow-burn must produce a written
   triage note in the alert thread within 30 min.

2. POSTGRES PLAN-FLIP ALERTS DID NOT EXIST.
   The query went from 14ms to 850ms over 60 hours.
   pg_stat_statements had the data the entire time.
   No alert watched mean_time per top-N queries.
   
   ACTION: alert when any query in pg_stat_statements'
   top-50 by total_time has its mean_time increase > 5x
   week-over-week.
   This is a leading indicator of plan flips and stat
   staleness — exactly the failure we just had.

3. AUTOANALYZE BACKLOG WAS INVISIBLE.
   pg_stat_user_tables.last_analyze: 70 hours ago.
   No alert.
   
   ACTION: alert when last_analyze on any top-50 table
   exceeds 24h. Slack only (not page).

4. THE TRACING SAMPLING RATE NEARLY HID THIS.
   We head-sample 5%. With ~830 calls/min of the slow
   query, we kept ~42/min slow traces. Enough — barely.
   At 100 calls/min we'd have had ~5/min, still findable.
   At 10 calls/min: ~0.5/min — possibly missed.
   
   ACTION: switch to tail sampling. Keep 100% of traces
   above p95 latency, 100% of error traces, 1% of normal.
   The "interesting" traces are always preserved.

5. WE HAVE 180 GRAFANA DASHBOARDS. THE INCIDENT USED 3.
   Most dashboards are unused. They add friction (which
   one to open?) without value.
   
   ACTION: dashboard inventory. Anything not opened in
   30 days → archived. Curate a "Tier 1: oncall" set
   of <15 dashboards covering known SLO failure modes.

6. NO ONE COULD ANSWER "WHEN DID THIS START?" WITHOUT
   EYEBALLING A GRAPH.
   The slow-burn was visible if you knew to look at the
   right time scale. We had no automated "change point
   detection" surfacing "this metric started drifting on
   Tuesday afternoon."
   
   ACTION: stretch goal — automated regression detection
   on top-50 SLI components week-over-week. (This is what
   New Relic, Honeycomb, and Datadog Watchdog charge for.
   For now, weekly review meeting.)

THE LESSON:
  Detecting a slow burn is a different SKILL than detecting
  a fast one. Fast burns have clear signatures and obvious
  pages. Slow burns require either (a) someone who actually
  triages slow-burn alerts with discipline, or (b) systems
  that surface anomalies the on-call hasn't asked about.
  Most teams have neither. Build (a) immediately; build
  toward (b) over time.
```

---



---

> **Answer key (do not open until you attempt the Ops Sim / questions):**  
> [`../answers/Week-08-Advanced-Patterns/Observability Answers.md`](../answers/Week-08-Advanced-Patterns/Observability Answers.md)

## Ops Sim: Northstar Cardinality Meltdown

**Time box:** 45 minutes
**Severity:** P1
**Service / domain:** Metrics backend, tracing, logging, checkout dashboards, alert pipelines
**Northstar system:** Northstar Commerce

### Rules

1. Answer from memory of the Observability teaching section; do not re-read mid-drill.
2. Write decisions in order (T+0 -> T+60).
3. Name evidence (metric, log line, trace, or config key) for every claim.
4. Do not open `answers/` until finished.

### 1. Scenario stem

```text
WHAT USERS SEE:
  - Checkout is degraded but dashboards load slowly or not at all.
  - On-call cannot slice payment errors by region during the incident.
  - Support tickets mention retries, stale state, or inconsistent checkout behavior.

WHAT ON-CALL SEES:
  - A deploy adds raw order_id and tenant_id labels to hot metrics.
  - Trace sampling is raised to 100% and not bounded.
  - A well-meaning mitigation is already making one dependency hotter.

BUSINESS CONSTRAINT:
  Preserve checkout correctness and money/inventory invariants. Degrade freshness, dashboards,
  recommendations, or noncritical notifications before risking duplicate effects.
```

### 2. Telemetry pack

```text
METRICS:
  active_series: 18M -> 1.7B
  ingest_samples_per_sec: 900k -> 38M
  metrics_query_p99_seconds: 2 -> 95
  checkout_error_rate: unknown in dashboards
  trace_spans_per_sec: 80k -> 4.5M
  log_ingest_gb_per_hour: 220 -> 3900
  cardinality_top_label: order_id
  alert_evaluation_missed: +780

LOG LINES:
  metrics: cardinality explosion metric=checkout_request_duration order_id=*
  tracing: sampling_rate=1.0 no_expiry
  logs: cart_payload contains email and address
  alertmanager: evaluation timed out

TRACES / LAG / EXPLAIN:
  critical request -> suspect dependency -> queue/retry/lag -> user-visible symptom
  compare hot slice vs fleet average before deciding to scale or fail over
```

### 3. Config pack

```yaml
metric_labels: [service,route,status,tenant_id,order_id]
incident_sampling_rate: 1.0
override_expires_at: null
debug_payload_logging: true
pii_redaction_cart_payload: partial
```

### 4. Timeline & decision points

| Time | Event | Your move (write before reading further) |
|------|-------|------------------------------------------|
| T+0 | Page fires: Checkout is degraded but dashboards load slowly or not at all. | |
| T+5 | Someone proposes: add order_id as metric label. | |
| T+15 | Evidence confirms: High-cardinality labels and unbounded sampling overloaded telemetry and hid the checkout incident. | |
| T+30 | Product asks to preserve the launch/revenue path despite risk. | |
| T+60 | New traffic is stable; old ambiguous records still need repair. | |

### 5. Questions

**Q1 - Layer & root cause:** Which layer owns the primary symptom? What is the exact mechanism?

**Q2 - Trigger vs amplifier:** What started the incident, and what made it worse after T+0?

**Q3 - Evidence:** Pick three metrics, two log lines, and one config key that prove your diagnosis.

**Q4 - Red herring:** Which fleet average, healthy check, or scary downstream metric could mislead the room?

**Q5 - First 5 minutes:** What do you announce, freeze, disable, or rate-limit immediately?

**Q6 - First 15 minutes:** Write the ordered mitigation sequence. Include rollback and verification after each step.

**Q7 - Bad fix gallery:** Reject these proposals and name the failure mode:
- add order_id as metric label
- set 100% tracing indefinitely
- log full payloads
- page only from overloaded metrics backend

**Q8 - Capacity / blast radius:** Estimate scarce resources before scaling or failover:
- queue depth or lag derivative
- connection/thread/pool headroom
- disk/WAL/compaction/ingest time-to-fill where relevant
- affected orders, users, tenants, or events requiring reconciliation

**Q9 - Correctness invariant:** What must remain true even while experience degrades?

**Q10 - Data repair:** Which source of truth defines the affected set? How do you replay without duplicate side effects?

**Q11 - Durable fix:** Propose architecture/config changes and acceptance criteria for:
- bounded labels and exemplars
- tail-based sampling with expiry
- PII-safe structured logs
- separate telemetry health signals

**Q12 - Alerting:** Which symptom alert should have paged earlier? Which noisy alert should be demoted?

**Q13 - Org / runbook:** Who joins by T+10, what is pre-authorized, and what needs senior approval?

### 6. Self-score (after answer key)

| Error type | Did it happen? | Note |
|------------|----------------|------|
| Knowledge gap | | |
| Misread / wrong layer | | |
| Sequencing error | | |
| Capacity miss | | |
| Consistency/invariant miss | | |
| Org/runbook miss | | |

**Answer key:** [../answers/Week-08-Advanced-Patterns/Observability Answers.md](../answers/Week-08-Advanced-Patterns/Observability%20Answers.md)

---
## Key Takeaways

```
1. Observability = arbitrary questions on high-cardinality data.
2. Cardinality is a design constraint — compute before new labels.
3. Page on symptom burn rates, not CPU thresholds.
4. Structured logs + trace context propagation are baselines.
5. Tail-based trace sampling captures incidents affordably.
```

---

## Targeted Reading

- Google SRE Book Ch 6
- USE/RED methods (Gregg, Wilkie)
- SLOs SLIs Error Budgets and Alerting.md (Week 8)
