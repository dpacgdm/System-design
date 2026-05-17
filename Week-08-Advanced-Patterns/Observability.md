# Week 5, T3 — Observability: Metrics, Logs, Traces, SLOs

---

## 1. Learning Objectives

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

## 2. Core Teaching

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
##       - What dashboards to open                               ║
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

## 3. Production Scenario: "The Slow-Burn Latency Mystery"

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

## 4. Five In-Depth Questions (with Full Principal-Grade Answers)

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


