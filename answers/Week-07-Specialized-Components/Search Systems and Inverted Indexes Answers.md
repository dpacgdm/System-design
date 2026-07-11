# Answer Key — Search Systems and Inverted Indexes

> Open only after attempting the learner file questions.

## Expert Analysis
### Root Cause Analysis

```
ROOT CAUSE 1 — AUTOSCALER TERMINATED DATA NODES DURING PEAK (PRIMARY)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  At 13:50 UTC, autoscaler reduced data nodes 6 → 4 during active traffic.
  nodes node-5 and node-6 terminated at 13:52.
  12 replica shards became UNASSIGNED → cluster YELLOW at 13:58.
  Remaining nodes absorbed shard primaries but replicas not reallocated
  because: (a) disk on node-2 at 91% — high watermark blocks allocation,
  (b) only 4 data nodes with 12 primary + 12 replica = 24 shard copies,
       insufficient capacity for rack/zone awareness rules.

  Impact: Loss of read scaling (replicas serve search), redundancy gone,
  rebalancing I/O caused latency spike.


ROOT CAUSE 2 — INDEXER MAPPING REJECTION (SECONDARY, USER-VISIBLE)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  New supplier integration sends price as string "129.99" not float 129.99.
  Indexer bulk requests fail mapper_parsing_exception.
  Kafka lag 847K → new products (including Nike SKU) not indexed.
  This explains "product not findable" — NOT the yellow cluster alone.

  Partial brand facet failure: indexer poison-pill batch may have caused
  consumer stall; older docs intact but incremental updates stalled.
  Nike filter showing 0: possible bad agg cache OR separate bug — check
  if Nike docs exist: GET products/_count { "query": { "term": { "brand": "Nike" } } }
  If count > 0 but facet 0 → agg cache/query bug. If count 0 → indexing failure.


ROOT CAUSE 3 — INCOMPLETE INDEX MIGRATION (LATENT)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  products-v8 created with new scaled_float mapping at 11:00 but alias
  still points to products-v7. Template change doesn't retroactively fix v7.
  Not direct cause of today's incident but blocked clean price migration.


CONTRIBUTING: DISK PRESSURE ON NODE-2
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  91% disk → high watermark → replica allocation blocked → stuck yellow
```

### Immediate Mitigation (0–15 Minutes)

```
1. STOP AUTOSCALER DOWNSCALE
   Disable cost cron or set min data nodes = 6 immediately.
   aws autoscaling update-policy / manual scale UP to 6 data nodes.

2. FREE DISK ON NODE-2
   DELETE old indices past retention (logs-2024.05.* if safe).
   OR increase EBS volume size via AWS console (online resize).
   Target: node-2 disk < 85%.

3. FIX INDEXER POISON PILL
   Deploy indexer hotfix: coerce price to float before bulk index.
   OR temporary ingest pipeline:
     PUT _ingest/pipeline/fix_price
     { "processors": [{ "convert": { "field": "price", "type": "float", "ignore_missing": true } }] }
   Skip/reprocess DLQ batch after fix.

4. SCALE INDEXER CONSUMERS
   4 → 8 pods to drain 847K lag once errors stop.

5. COMMUNICATE
   Status page: "Search results may be incomplete for newly added products.
   Browsing and checkout unaffected." (PG is source of truth for cart/checkout)
```

### Customer Impact

```
SEVERITY: SEV-2 (degraded, partial data stale — not full outage)

  • Search latency elevated — poor UX but functional for cached catalog
  • New/updated products missing from search — REVENUE IMPACT on new launches
  • Brand facets potentially wrong — navigation degraded
  • Checkout/detail pages OK if served from PG/Redis (CQRS read path split)
  • Yellow cluster: single node failure away from RED on affected shards
```

### 24-Hour Fix Plan

```
HOUR 0-2:   Restore 6 data nodes, disk cleanup, confirm green/yellow resolved
HOUR 2-4:   Indexer fix deployed, lag draining, validate new SKU searchable
HOUR 4-8:   Complete products-v8 migration:
              - Reindex v7 → v8 with ingest pipeline
              - Validate doc counts and price field types
              - Alias swap products → v8
HOUR 8-24:  Post-incident hardening (see prevention)
            Reconciliation job: compare PG product count vs ES count
            Replay Kafka from known-good offset if any permanent gap
```

### Prevention (Post-Incident Actions)

```
1. Autoscaler guardrails: min nodes = peak baseline, scale-down only if
   CPU < 30% for 30 min AND cluster green AND business hours check

2. Indexer schema validation: JSON schema in CI for CDC documents,
   reject at producer (supplier API) not at ES

3. Dead letter queue + alert on first mapper_parsing_exception

4. Kafka lag alert: > 10,000 messages for 5 min → page

5. Cluster health alert: yellow > 5 min → page (not just red)

6. Disk watermark alert: any node > 80%

7. Mapping changes: mandatory reindex + alias swap runbook in same PR

8. CQRS reconciliation: hourly doc count delta PG vs ES (Week 5 invariant)

9. Game day: simulate node loss + indexer stall quarterly
```

---

## Ops Sim: Northstar Marketplace Index Blackout

### Q1 - Layer & root cause

Analyzer change caused zero results while unsafe live reindexing overloaded the cluster.

A strong answer separates the trigger from retry, cache, routing, or observability amplifiers and states the invariant that cannot be violated.

### Q2/Q3 - Evidence

- `search_zero_result_rate: 2% -> 38%`
- `catalog_indexing_lag_seconds: 12 -> 2400`
- `opensearch_shard_size_gb_p95: 120`
- `segment_count_p95: 980`
- `refresh_time_p99_ms: 40 -> 1100`
- `search-api: zero results query=designer sale analyzer=syn_v9`
- `ingest: rejected execution queue full`
- `cluster: shard relocation throttled due to disk watermark`
- Config clue: `analyzer_version: syn_v9`
- Config clue: `shards_per_index: 96`

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

- `full reindex live during peak`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.
- `use search as inventory truth`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.
- `raise shard size limits`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.
- `redirect all traffic to autocomplete`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.

### Q8 - Capacity / blast radius

Quantify current usage, safe ceiling, growth rate, and time-to-exhaustion for queue/lag, connection or thread pools, disk/WAL/compaction, and affected business records. Scaling is only safe if the downstream dependency has headroom.

### Q9 - Correctness invariant

Accepted orders, money movement, inventory reservations, tenant isolation, and source-of-truth state must remain conservative. If the outcome is uncertain, mark it uncertain and reconcile instead of guessing.

### Q10 - Data repair

Use source-of-truth rows, stable idempotency keys, LSNs/offsets, and the incident window to define the repair set. Replay with duplicate suppression, throttle to downstream headroom, and record customer-visible corrections.

### Q11 - Durable fixes

- versioned analyzers with shadow queries.
- atomic alias swaps.
- rollover at sane shard sizes.
- zero-result and indexing-lag alerts.

Acceptance criteria: the old failure is reproduced in a drill, the new guardrail pages before customer impact, and the unsafe configuration cannot be enabled without review.

### Q12/Q13 - Alerting and runbook

Page on SLO burn, correctness failures, lag derivative, and scarce-resource exhaustion in the affected slice. By T+10 include incident commander, service owner, data/platform owner, product/business owner, support, and security/payments if trust or money is involved. Pre-authorized: stop unsafe rollouts, shed noncritical work, conservative fallback. Senior approval: durability downgrade, destructive repair, broad failover, or accepting derived data as truth.

---
