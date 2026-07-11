# Answer Key — Week-08

> Open only after attempting the learner file questions.

# WEEK 8 RETENTION TEST — ANSWERS

---

# Part 1: Rapid-Fire

---

**Q1 (Clocks — Lamport vs Physical Time):**
**Yes, e2 can causally precede e1** — B's clock is 5 units ahead, so e2 at local 104 may correspond to an earlier physical instant than e1 at local 100. Physical timestamps across servers are not comparable without synchronized clocks. **Lamport clocks guarantee:** if A→B causally, then L(A)<L(B). **They do NOT guarantee:** if L(A)<L(B) then A→B (concurrent events can have arbitrary order).

---

**Q2 (Clocks — TrueTime Commit Wait):**
TrueTime returns an **uncertainty interval** [earliest, latest]. Commit wait pauses until `commit_timestamp > TT.now().latest` — ensuring no transaction commits with a timestamp that could appear "before" a already-committed transaction to an external observer → **external consistency (linearizability)**. If uncertainty spikes 10× (bad NTP/GPS), commit wait grows proportionally — **write latency increases ~80ms+** per transaction, potentially stalling Spanner writes cluster-wide.

---

**Q3 (Vector Clocks — Concurrent Detection):**
Incoming `{A:2, B:4}` vs local `{A:3, B:2}`: A is lower (2<3) but B is higher (4>2) — **neither dominates** → events are **concurrent**. For grow-only set CRDT: **union merge** — take `max(local[A], incoming[A])` per component, then union the sets. Concurrent adds on different replicas both survive.

---

**Q4 (CRDTs — LWW Danger):**
**"Final" wins** (T=999 < T=1000... wait: LWW picks HIGHER timestamp, so **"Draft" wins** at T=1000). User B's "Final" is silently lost. LWW-register is dangerous without logical clocks because **physical clock skew causes arbitrary data loss** — the "losing" edit may actually be the more recent human intent. Fix: use **version vectors or Hybrid Logical Clocks** for LWW tie-breaking.

---

**Q5 (CRDTs — OR-Set):**
After merge: **"alice" is present**. OR-Set tags each add with a unique tag; remove adds a tombstone for that specific tag, not the element globally. Re-add creates a new tag that survives merge. Plain set with tombstones: remove tombstones **global element ID** — concurrent re-add after remove creates **ambiguous state** (tombstone vs new add conflict). OR-Set wins because add/remove operate on **unique op IDs**, not element names.

---

**Q6 (Geospatial — Geohash Boundary):**
A 3km radius circle **crosses geohash cell boundaries** — a single 6-char cell covers ~1.2km×0.6km. Drivers in adjacent cells within 3km of the rider would be **missed**. Standard fix: compute the **8 neighboring cells** (9-cell grid including center) for the query bounding box, query all cells, then **filter by exact haversine distance** post-fetch.

---

**Q7 (Geospatial — GIST Index):**
GIST index prunes by **bounding box** — eliminates geometries whose MBR (minimum bounding rectangle) cannot intersect the query circle. Without index: full table scan, compute distance for every row. **SRID 4326** (WGS84 lat/lon): distance in degrees — inaccurate for "3km radius" (must use `geography` type or `ST_DWithin` with meters). **SRID 3857** (Web Mercator): distance distorted at high latitudes — 3km in Helsinki ≠ 3km in equator on Mercator plane.

---

**Q8 (Observability — Cardinality Fix):**
Metric 1: `http_request_duration_seconds` **without user_id label** — histogram with standard buckets, aggregate p99 via `histogram_quantile`. Metric 2: **exemplars** or **trace_id sampling** — attach trace ID to 1% of histogram observations for drill-down. For single-user debug: **structured logs with request_id** in Loki (indexed by request_id, not user_id) — lookup by trace ID when user reports slowness.

---

**Q9 (Observability — RED vs USE):**
| Metric | Method | Action |
|--------|--------|--------|
| `container_cpu_cfs_throttled_seconds_total` | **USE** (Utilization) | CPU limit too low — increase CPU request/limit or reduce work |
| `grpc_server_handled_total{code}` | **RED** (Rate/Errors) | Error rate by gRPC status — alert on `code!="OK"` ratio |
| `node_disk_io_time_seconds_total` | **USE** (Utilization) | Disk saturated — move workload, add IOPS, or shard data |

---

**Q10 (Observability — Tail vs Head Sampling):**
**Tail-based sampling** finds the Android p99 regression faster. Head-based 1% samples **before knowing outcome** — slow Android traces have 1% probability of capture; with 0.2% error rate, error traces are almost never captured. Tail sampling retains **all spans >2s and all errors** — immediately surfaces the 620ms inventory wait on affected Android checkout paths without waiting for statistical luck.

---

**Q11 (SLOs — Error Budget Math):**
99.9% monthly = **0.1% error budget** = 43.2 minutes/month of downtime equivalent (30 days × 24h × 60min × 0.001). Burn rate 14.4× for 5 min consumes `14.4 × (5/43200) × 100 = 1.67%` of monthly budget in 5 minutes — **page immediately** (critical burn-rate tier). Alert tier: **P1 page** — at 14.4× burn, entire monthly budget exhausts in ~2 days if sustained.

---

**Q12 (SLOs — Multi-Window Burn):**
1h window at 14.4× catches **sudden catastrophic burns** (deploy broke everything). 6h window at 6× catches **slow burns** (gradual regression like this incident). Requiring **both** prevents: (a) false pages from 5-minute spikes that self-heal (1h alone), and (b) missing slow regressions that never trigger short-window thresholds (6h alone). AND gate = **high confidence the burn is real and sustained**.

---

**Q13 (Observability — GraphQL Partial Failures):**
**RED "Errors" dimension on application-level success rate** — not HTTP status codes. Alert on `graphql_requests_total{has_errors="true"} / graphql_requests_total` or parse response body for non-empty `errors` array. Standard 5xx monitoring sees HTTP 200 and reports healthy while users receive partial data (missing fields, null product names). **Structured logs** with `graphql.errors.count > 0` in Loki catch individual broken responses.

---

**Q14 (Observability — Leading vs Lagging):**
`UnderReplicatedPartitions` is **leading** — fires during broker stress before produce failures cascade to checkout. `checkout_success_rate` is **lagging** — drops only after customers already fail. Typical lead time with lagging-only alert: **5–15 minutes** (time for ISR shrink → produce fail → user retry → metric drop). Leading indicator for Postgres slot bloat: **`pg_replication_slots.retained_bytes`** or **`pg_wal_directory_size_bytes`** — grows minutes to hours before disk-full kills the primary.

---

# Part 2: Compound SRE Scenario

---

## Question 1: Six Contributing Factors — Ranked by Customer Impact

```
╔═══════════════════════════════════════════════════════════════════════╗
║  RANK │ FACTOR                    │ TAG              │ IMPACT         ║
╠═══════════════════════════════════════════════════════════════════════╣
║   1   │ LOR + degraded 1c pods    │ Load balancing   │ Android p99    ║
║       │ (c5a.xlarge hot, 3× traffic)│ + AZ impairment │ +620ms wait   ║
╠═══════════════════════════════════════════════════════════════════════╣
║   2   │ checkout_express_path 25% │ Feature flag     │ Skips tax;     ║
║       │ Android-heavy cohort      │                  │ wrong totals   ║
╠═══════════════════════════════════════════════════════════════════════╣
║   3   │ cart_crdt_batch_sync 30s  │ CRDT/sync        │ Stale cart     ║
║       │ Android only              │                  │ at payment     ║
╠═══════════════════════════════════════════════════════════════════════╣
║   4   │ Head-based 1% trace       │ Observability    │ 4h MTTR;       ║
║       │ sampling until 15:50      │ gap              │ missed root    ║
╠═══════════════════════════════════════════════════════════════════════╣
║   5   │ p99 alert = P2 Slack only │ Observability    │ No page until  ║
║       │ (not tied to conversion)  │ gap              │ CFO at 16:40   ║
╠═══════════════════════════════════════════════════════════════════════╣
║   6   │ inventory p99 metric hides│ Observability    │ False "healthy"║
║       │ pod-level skew (45ms avg) │ gap              │ delayed fix    ║
╠═══════════════════════════════════════════════════════════════════════╣
║   7   │ Spanner uncertainty       │ Clock/time       │ RED HERRING    ║
║       │ (fraud-svc only)          │ (misdirection)   │ for checkout   ║
╚═══════════════════════════════════════════════════════════════════════╝
```

### Detail on Rank 1 (Primary Root Cause)

**inventory-svc in us-east-1c after AZ network event:**

```
12:30-13:15: AZ network impairment
  → 8 inventory pods on c5a.xlarge in 1c degraded
  → TCP retransmits, gRPC latency elevated on these pods
  → Pods pass health checks (process alive) but are SLOW

16:25: ALB LOR (least-outstanding-requests)
  → LOR routes to pods with fewest in-flight requests
  → Degraded 1c pods respond SLOWLY → queue drains slowly
  → LOR sees them as "least outstanding" → sends MORE traffic
  → POSITIVE FEEDBACK LOOP: slow pods get 3× traffic

LOR Feedback Loop Diagram:

  Normal LOR behavior:
    Fast pod (12ms) → queue drains fast → LOR skips it temporarily
    Slow pod (800ms) → queue stays full → LOR sees "low outstanding"
      → sends MORE requests → pod gets SLOWER

  After AZ event in 1c:
    8 degraded pods appear "least outstanding" (requests stuck inside)
    LOR floods them with 3× traffic share
    Healthy 32 pods underutilized

  Fix: Round-robin OR cap max connections per target
    OR remove degraded pods via health check on p99 latency
```

### Detail on Rank 2 (Feature Flag — Express Path)

```
checkout_express_path enabled Monday at 25%:
  → Android users over-represented in flag cohort (product decision)
  → Express path skips tax-svc gRPC call
  → Saves ~80ms on healthy path BUT:
    - Total shown to user excludes tax
    - Payment amount mismatches user expectation
  → Under inventory latency stress, express path users
    hit degraded 1c pods MORE because shorter overall
    deadline completes more attempts → more inventory calls
```

### Detail on Rank 3 (CRDT Batch Sync)

```
cart_crdt_batch_sync: 100% Android, 0% iOS:
  → Android holds local OR-Set state up to 30s before push
  → Spouse adds item on iOS (realtime) → server has it
  → Android user pays before batch sync at T+30
  → Payment submitted against stale local cart
  → "Wrong total" and "missing items" reports at 16:35
```

---

## Question 2: The Inventory Paradox

**How both 620ms (trace) and 45ms (metric) can be true:**

Traces capture **specific slow requests** — tail sampling at 15:50 retained checkout spans where inventory took 620ms (likely routed to degraded 1c pod). Service-level p99 metric aggregates **all pods equally**:

```
40 pods total:
  32 healthy pods (c5.4xlarge, non-1c): p99 = 12ms
  8 degraded pods (c5a.xlarge, 1c): p99 = 800ms

If LOR sends only 20% traffic to degraded pods:
  Aggregate p99 ≈ percentile_99([80% × 12ms, 20% × 800ms])
  ≈ 45-60ms (aggregate hides tail)

But Android cohort (25% express flag) may hash/route to 
specific checkout pods that preferentially hit 1c inventory 
via gRPC client-side subsetting → 620ms on THOSE traces.
```

**Two metric/aggregation bugs:**

**Bug 1: Service-level aggregation masks pod skew.**
`histogram_quantile(0.99, sum by (service)(rate(...)))` — no `pod` or `az` label. Slow minority pods invisible. **Fix:** p99 by `pod`, `availability_zone`, and `instance_type` labels.

**Bug 2: gRPC client-side load balancing subsetting.**
checkout-svc gRPC channel picks subset of inventory backends — if subset is sticky to 1c pods after AZ event, **affected checkout pods see 620ms** while cluster average is 45ms. Trace reflects caller perspective; metric reflects server-side aggregate.

---

## Question 3: Page or Not? — The Case for Paging

**Case FOR paging (despite low error budget burn):**

```
Conversion drop 3% since noon = REVENUE IMPACT.
At $2M/day GMV, 3% = $60k/day lost.
Error budget burn is LOW because SLI is "successful checkout"
  — checkouts SUCCEED but SLOWLY (p99 800ms vs 250ms SLO).
  Slow success ≠ error in SLI → budget not consumed.
  
This is a classic SLO BLIND SPOT: latency SLO exists (P2 Slack)
  but is not wired to page or to error budget.
  
Multi-window burn on 5xx alone misses slow-burn latency regressions.
CFO signal is a LEADING business metric — should trigger incident
  bridge at 1% conversion drop, not 3%.
```

**Case AGAINST paging (at 12:55):**

At 12:55, only Android p99 creeping — no conversion drop yet, no error spike. Single-platform regression with plausible hypothesis (TLS, flag). **P2 Slack reasonable for first 2 hours** IF tail sampling and pod-level dashboards existed.

**Verdict:** Should have **escalated to P1 at 15:50** when tail sampling found 620ms inventory wait with 45ms metric paradox — that's dispositive evidence of infrastructure skew, not client bug. **Wire conversion drop >1% to automatic P1** regardless of error budget.

### SLO Design Gap — Latency vs Availability

```
Current SLI stack:
  Availability: successful_checkouts / attempts → 99.9% (PAGES on 5xx burn)
  Latency:      checkout_p99 < 250ms           → P2 Slack at 800ms only

The incident consumed LATENCY budget without triggering AVAILABILITY budget:
  - Every checkout succeeded (slowly)
  - Users abandoned before error (conversion drop)
  - Error budget burn: ~0%
  - Revenue impact: 3% conversion × $2M/day = $60k/day

Fix: Multi-dimensional SLO with composite alert:
  PAGE if: (latency_p99 > 500ms for 10m) AND (conversion_drop > 1%)
  OR: latency consumes dedicated 10% latency-error-budget
```

---

## Question 4: Spanner — Red Herring Analysis

**Yes, Spanner is a red herring for checkout latency.**

```
checkout-svc → inventory-svc, tax-svc, payments-svc
fraud-svc → Spanner (NOT on checkout critical path for express flag)
Spanner uncertainty elevated 14:18-14:45
checkout-svc does NOT use Spanner
```

**Timing coincidence explained by shared infrastructure:**

```
14:18: NTP drift alert on 3 inventory-svc hosts in us-east-1c
  → Same AZ as AWS network event 12:30-13:15
  → NTP auto-remediation causes clock step
  → Spanner TrueTime in us-central1 sees elevated uncertainty
     (Google infrastructure clock sync reacts to regional events)
  → fraud-svc Spanner p99 +6ms (real for fraud, irrelevant for checkout)

Correlated root: us-east-1c infrastructure instability
  → affected inventory pods (checkout impact)
  → affected NTP sync (clock alerts)
  → correlated Spanner uncertainty (different service, same cloud event)
```

**Do NOT chase Spanner for checkout.** Fix inventory pod skew in 1c.

---

## Question 5: CRDT Cart — Wrong Total at Payment

**Failed ordering guarantees:**

```
Timeline:
  T+0:   Spouse adds item X on iOS (realtime WebSocket sync)
         → cart vector clock: {ios:5, android:3}
         → OR-Set includes item X

  T+15:  User on Android adds item Y locally
         → Android batch sync flag: won't push until T+30

  T+20:  checkout_express_path skips tax-svc
         → total = subtotal only (no tax line item)
         → user expects tax-inclusive price

  T+25:  User taps Pay
         → checkout reads cart snapshot
         → Android local cart: {Y} only (X not synced yet)
         → Server cart: {X, Y} but checkout reads stale Android state

  T+30:  Android batch sync fires — too late, payment submitted
```

**Three guarantees failed:**

1. **Causal consistency (vector clock):** Android batch sync broke happens-before — payment at T+25 did not wait for sync point at T+30.
2. **OR-Set merge before checkout:** Checkout did not read server-authoritative cart state — used client-local CRDT without sync barrier.
3. **Express path semantic consistency:** Skipping tax-svc means total ≠ displayed price users expect — not a CRDT bug but compounds "wrong total" report.

**Fix pattern:** Checkout must **force sync barrier** — `GET /cart?sync=true` waits until vector clock catches up or timeout, reject payment if `cart_version` stale.

### Vector Clock Analysis of the Failure

```
Server cart state after spouse adds item X (iOS):
  OR-Set: {X, Y}
  Vector clock: {ios:5, android:3}

Android local state at T+25 (payment):
  OR-Set: {Y}  (X not received — batch sync pending)
  Vector clock: {ios:3, android:4}

Merge would detect CONCURRENCY:
  {ios:5, android:3} vs {ios:3, android:4}
  → neither dominates → concurrent edits
  → OR-Set merge: {X, Y} (correct state)

But checkout read Android LOCAL state without merge:
  → charged for {Y} only
  → spouse sees {X, Y} on their device → "wrong total" dispute

Failed invariant: "payment reads server-merged cart state"
  not "payment reads client-local CRDT snapshot"
```

---

## Question 6: Observability Fix Package

### Three Leading Alerts

```
Alert 1: Pod-level latency skew (would fire ~13:00)
  expr: |
    histogram_quantile(0.99,
      sum by (service, pod, az) (rate(grpc_server_handling_seconds_bucket[5m]))
    )
    /
    histogram_quantile(0.99,
      sum by (service) (rate(grpc_server_handling_seconds_bucket[5m]))
    ) > 3
  for: 10m
  labels: {severity: page}
  annotation: "Pod {{ $labels.pod }} in {{ $labels.az }} is 3× 
    slower than service p99 — check LOR skew post-AZ event"

Alert 2: Conversion drop (would fire ~13:30)
  expr: |
    (checkout_conversion_rate_1h - checkout_conversion_rate_1h offset 1d)
    / checkout_conversion_rate_1h offset 1d < -0.01
  for: 15m
  labels: {severity: page}
  annotation: "Checkout conversion dropped >1% vs same hour yesterday"

Alert 3: AZ-imbalanced target traffic (would fire ~13:00)
  expr: |
    max by (az) (rate(alb_target_request_count[5m]))
    /
    min by (az) (rate(alb_target_request_count[5m])) > 2.5
  for: 10m
  labels: {severity: ticket}
  annotation: "ALB traffic skew >2.5× between AZs — LOR may be 
    feeding degraded AZ"
```

### Two Dashboard Panels

```
Panel 1: "Inventory Latency Heatmap"
  Query: p99 grpc_server_handling_seconds by (pod, az, instance_type)
  Visualization: heatmap — would show 1c c5a.xlarge pods red at 800ms
  while others green at 12ms

Panel 2: "Checkout Funnel by Platform"
  Queries:
    - checkout_attempt_total{platform="android"} success rate
    - checkout_attempt_total{platform="ios"} success rate
    - checkout_p99{platform} overlay
  Would show Android divergence starting 12:55, iOS flat
```

### One Sampling Policy Change

```
BEFORE: head-based 1% (misses slow traces)
AFTER:  tail-based sampling in Tempo:
  - Always keep: status=error
  - Always keep: duration > 500ms (50% of 250ms SLO budget)
  - Always keep: attribute platform=android AND duration > 200ms
  - Random sample: 5% of remainder

Policy name: checkout-critical-tail-sampling
Expected MTTR impact: 4h → <30min
  (620ms inventory span would be captured at 12:56 on first slow Android checkout)
```

### Mitigation Timeline (If These Existed)

```
╔════════════════════════════════════════════════════════════════╗
║  T+0 (12:55)  │ Alert 2: Android p99 panel red                 ║
║  T+5 (13:00)  │ Alert 3: 1c traffic skew fires                 ║
║  T+10 (13:05) │ Alert 1: inventory pod 3× slower — PAGE        ║
║  T+15 (13:10) │ Tail trace shows 620ms inventory in 1c         ║
║  T+20 (13:15) │ Cordon 1c c5a.xlarge inventory pods            ║
║  T+30 (13:25) │ Conversion drop prevented (never reaches 3%)   ║
╚════════════════════════════════════════════════════════════════╝
```

### Immediate Mitigation Commands (16:40)

```bash
# Cordon degraded 1c inventory pods
kubectl cordon -l app=inventory-svc,topology.kubernetes.io/zone=us-east-1c,\
  node.kubernetes.io/instance-type=c5a.xlarge

# Drain gracefully (respects ALB deregistration delay)
kubectl drain --ignore-daemonsets --delete-emptydir-data \
  -l app=inventory-svc,topology.kubernetes.io/zone=us-east-1c,\
  node.kubernetes.io/instance-type=c5a.xlarge

# Force cart sync before payment (hotfix flag)
curl -X PATCH https://flags.internal/api/v1/flags/cart_crdt_batch_sync \
  -d '{"android_sync_interval_sec": 5}'

# Disable express path until tax parity verified
curl -X PATCH https://flags.internal/api/v1/flags/checkout_express_path \
  -d '{"rollout_percentage": 0}'

# Verify inventory latency equalizes
kubectl top pods -l app=inventory-svc --sort-by=cpu
# Watch p99 by AZ in Grafana inventory heatmap panel
```

---

## Question 7: Post-Incident Changes (With Acceptance Criteria)

### LB / Pod Sizing (oncall-platform)

**Change:** Homogenize inventory-svc to single instance type (c5.4xlarge) OR enable **topology spread constraints** with maxSkew=1 across AZs. Disable ALB LOR for gRPC backends — use round-robin with connection limits per target.

**Acceptance:** After AZ impairment simulation, p99 skew between AZs < 1.5× for 30 min; no pod receives >1.5× mean traffic for >5 min.

### Flag / Canary (oncall-product)

**Change:** `checkout_express_path` requires tax parity validation in staging; max 1% canary for 24h with conversion monitoring before any increase. Android-over-indexed cohorts require explicit sign-off.

**Acceptance:** Flag rollout pipeline blocks >5% without conversion baseline; auto-rollback if conversion drops >0.5% vs control.

### Observability (oncall-sre)

**Change:** Deploy tail sampling policy (defined in Q6) + pod-level p99 alerts + conversion drop P1 page.

**Acceptance:** Synthetic slow-path test (inject 500ms delay on 1 pod) pages within 10 min; MTTR in game-day < 30 min.

### CRDT Client Sync (oncall-app)

**Change:** `cart_crdt_batch_sync` max interval 5s on Android; checkout payment flow calls `POST /cart/sync` blocking until vector clock catches up or 3s timeout.

**Acceptance:** 0 "wrong cart total" reports in 7-day canary with shared family cart load test; payment rejected if cart_version stale.

---

```
╔════════════════════════════════════════════════════════════════════════╗
║  # │ CHANGE                              │ OWNER         │ TYPE        ║
╠════════════════════════════════════════════════════════════════════════╣
║  1 │ Homogenize inventory instance types │ oncall-platform│ LB/sizing  ║
║    │ OR use topology-aware routing       │               │             ║
╠════════════════════════════════════════════════════════════════════════╣
║  2 │ ALB: disable LOR for gRPC backends  │ oncall-platform│ LB         ║
║    │ use weighted round-robin instead    │               │             ║
╠════════════════════════════════════════════════════════════════════════╣
║  3 │ checkout_express_path: require tax  │ oncall-product │ Flags      ║
║    │ parity gate + 1% canary with conv   │               │             ║
║    │ monitoring before 25% rollout       │               │             ║
╠════════════════════════════════════════════════════════════════════════╣
║  4 │ cart: sync barrier before payment   │ oncall-app    │ CRDT        ║
║    │ reject stale vector clock           │               │             ║
╠════════════════════════════════════════════════════════════════════════╣
║  5 │ Tail sampling + pod-level p99 alerts│ oncall-sre    │ Observ.     ║
║  6 │ Wire conversion drop >1% to P1 page │ oncall-sre    │ SLOs        ║
╚════════════════════════════════════════════════════════════════════════╝
```

---

## Scoring Guide (Self-Check)

```text
Part 1 (Q1–Q14):   11/14+ → Week 8 advanced patterns retained
Part 2 (scenario):  Principal depth on slow-burn / multi-signal diagnosis

Overall:
  Ready for Week 9  → 85%+ across parts
  Review Week 8     → below 70% on Part 1
  Review Observability → below 60% on Q8–Q10, Q13–Q14
```


---

## Part X/Y Expansion Answers (Week-08)

Score rapid-fire QX*: 1 point each for mechanism + one concrete consequence.
Score Y*: require correct layer, reject timeout-only fix, ordered mitigation with capacity check, durable fix with acceptance criteria.

**QX common bar:** name the mechanism, the failure mode it prevents or causes, and one metric/config to verify.

**Y1:** Payment-authorize timeout too aggressive + retries without breaker → retry storm amplifier; primary layer is dependency resilience / client policy, not cache/Kafka.
**Y2:** Raising timeout without capping concurrency/retries extends hold time and deepens pool exhaustion.
**Y3:** T+0 enable breaker/bulkhead and cut retries; T+5 shed noncritical; T+15 verify AZ capacity before shifting traffic.
**Y4:** Default-safe client policy (timeouts, bounded retries, breaker) + load test acceptance: error budget burn <2x under injected 500ms dependency delay.
