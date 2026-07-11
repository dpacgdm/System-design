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
