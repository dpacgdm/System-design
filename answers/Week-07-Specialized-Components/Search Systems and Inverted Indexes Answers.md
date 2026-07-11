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

## Ops Sim: Northstar Marketplace Alias Swap Blackout

> Open only after attempting the learner-side drill.

### Executive diagnosis

A synonym analyzer change built `products_v47`, but the alias flipped before doc counts, query canaries, and merge backlog were healthy. Search reads a half-populated inverted index.

A principal response separates the trigger from the amplifier and states the invariant before proposing capacity or repair. The answer should not say only "scale it" or "roll it back"; it must explain why this system failed this way.

### Evidence map

- `search_zero_result_rate: 0.8% -> 24%`
- `catalog_index_docs{index="products_v47"}: 91M expected=240M`
- `indexing_lag_seconds{pipeline="catalog"}: 90 -> 14400`
- `search_latency_seconds{p99}: 0.18 -> 3.7`
- `bulk_rejected_total: +780k`
- `segment_merge_throttle_time_seconds: +9200`
- Config clue: `alias_swap.require_doc_count_match: false`
- Config clue: `backfill.max_bulk_concurrency: 64`
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

- `scale query nodes before rolling alias back`: adds aggregate capacity but does not split the already-hot partition or poisoned key.
- `force merge during peak`: spends IO on segment cleanup while ingest and query paths are already throttled.
- `delete v46 to save disk`: can destroy replay evidence or resurrect/de-synchronize state before repair is safe.
- `trust sampled search success only`: uses a derived view as truth, so it can miss or invent records during repair.

### Capacity and blast radius

A principal answer gives at least one bound. Compute the affected slice, backlog or queue depth, derivative, safe downstream throughput, and time-to-exhaustion or time-to-drain. If those values are unknown, the safe move is to throttle and measure before scale/failover/replay.

Examples of the expected math:
- current backlog / safe drain rate = minimum repair duration
- free disk or pool headroom / growth rate = time-to-exhaustion
- affected tenants, SKUs, auctions, regions, orders, or carts from source-of-truth keys
- downstream provider/API/database quota that caps replay concurrency

### Repair and reconciliation

Source of truth: catalog database plus dual-write/replay offsets and index alias state.

Build the affected set from authoritative records in the incident window, not from cache, search, dashboards, or customer anecdotes alone. Repair must use stable idempotency or operation keys, be throttled to downstream headroom, and write an audit trail. Derived projections can be rebuilt after the invariant is safe.

### Durable fixes

- alias gates on doc count and query canaries
- dual-write or replayable catalog pipeline
- backfill throttles tied to merge debt
- rollback-tested index versioning

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

