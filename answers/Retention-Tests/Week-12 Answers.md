# Answer Key - Week-12

> Open only after attempting `Retention-Tests/Week-12.md`.

---

## Part 1: Rapid-Fire Model Answers

**Q1:** The public web/product graph is larger than finite fetch capacity. Crawl budget is allocated by authority/PageRank, freshness/change rate, sitemap hints, host capacity/politeness, recrawl urgency, and spam/trap risk.

**Q2:** Host politeness limits crawler request rate per host and respects robots/crawl-delay. A bug can overload a seller site, trigger blocking/legal escalation, and make that domain stale in your index.

**Q3:** Inverted index maps term to posting lists/doc ids and powers candidate retrieval. Forward index maps doc id to fields such as title, URL, snippet, price, and signals used after retrieval.

**Q4:** The indexing pipeline is unhealthy: CDC/indexer lag, bulk failures, merge backlog, or alias/cutover issues. Crawl success only says pages were fetched, not that searchable segments are current.

**Q5:** Doc-id sharding distributes documents and fans queries to shards; term sharding partitions by terms but makes multi-term queries complex. Hot head terms can overload shards, so systems use stopword removal, head-term tiers, caching, or replica scaling.

**Q6:** Blue/green generations let you build and validate a new index offline, then atomically switch an alias. They avoid live merge storms and allow instant rollback to known-good generation.

**Q7:** Consumer lag means catalog updates are not yet searchable. Search freshness SLO is violated even if Postgres and crawler are healthy.

**Q8:** Without generation in the key, cached results from v42 can be served after v43 cutover or vice versa. This mixes deleted/old doc ids with the wrong index and makes rollback/cutover appear broken.

**Q9:** Index lag, delete apply lag, bulk error rate, query zero-result rate, top-query CTR/conversion, hot shard CPU, cache hit ratio, ranking canary metrics, and freshness probes.

**Q10:** Per-host URL/day limits, canonicalization, depth limits, Bloom/dedup filters, unique-content-flat detectors, and trap-specific rules stop infinite URL expansion.

**Q11:** Stale known-good data is bounded and explainable; corrupted partial data may omit products, show deleted/legal content, or rank nonsensically. Correctness can require serving v42 while v43 is repaired.

**Q12:** More replicas multiply indexing writes and segment merge work because each replica must receive/merge changes. Read capacity improves, but bulk rebuilds get slower/costlier.

**Q13:** Missing tenant filters leak one seller's products into another tenant's search or ads. It is both a data isolation and relevance/security incident.

**Q14:** `stale-if-error` can keep legally removed/deleted results visible after the index correctly deleted them. It is safe only when stale content is acceptable under policy.

**Q15:** Rebuilding on serving clusters consumes CPU, IO, heap, and merge bandwidth needed for user queries. Offline build isolates cost and lets serving nodes load validated snapshots.

---

## Part 2: Compound Scenario - Expert Analysis

### Contributing Factors

| Factor | Tag | Evidence |
|--------|-----|----------|
| v43 incomplete | Index | Expected 512M docs, actual 487M |
| Bulk mapping failures | Index | `mapper_parsing_exception` on `price_range`, 7.8% error rate |
| Delete stream delayed | Index | Delete apply lag p99 4.5h |
| Alias split brain by region | Operations | v43 in two regions, v42 in one |
| Cache key missing generation | Query cache | `query+locale` only; deleted ids present in cache |
| stale-if-error on results | Query cache | 1h stale results during index outage |
| Ranking canary overlap | Ranking | v17 at 25% during reindex |
| Ads doc ids unstable | Ads/doc-id | v43 sequential doc ids, ad cache built on v42 |
| Rebuild on serving cluster | Operations | Hot shards, merges 6x, p99 2.1s |
| Crawler trap disabled | Crawl | Calendar URLs +900%, unlimited trusted sellers |

### T+0 Order

1. Freeze further ranking/crawler/reindex changes.
2. Roll back `catalog-live` alias globally to last known-good v42 if v43 is incomplete/corrupt.
3. Disable ranking canary v17 or return it to 0% to remove confounders.
4. Stop or throttle crawler trap source so frontier/index pressure stops growing.
5. Start targeted cache purge/version bump for affected query result caches after alias is consistent.
6. Fix indexer mapping and rebuild v43/v44 offline.

### T+5 Cache Decision

Safe: purge or version-bump query caches for affected result keys/generations once alias target is consistent and origin/query capacity is protected. Also disable stale-if-error for deleted/legal-sensitive result classes.

Dangerous: global purge of every cache without query capacity check. That can stampede OpenSearch while it is already yellow/hot and worsen latency.

### T+15 Mapping Action

Create a corrected mapping for `price_range` in a new index generation (v44) or compatible field mapping if possible. Do not mutate a broken live index in place if documents were rejected. Replay CDC from a known offset/snapshot into v44 and validate counts/deletes before alias cutover.

### T+60 Cutover Gates

- Expected vs actual doc count within tolerance by tenant/category.
- Delete apply lag under SLO and legal-delete test probes pass.
- Bulk error rate near zero.
- Query relevance/CTR canary healthy against fixed ranking baseline.
- Cache key includes generation or caches are pre-versioned.
- Ads doc ids stable (`hash(canonical_url)` or redirect mapping), and ad join cache rebuilt.
- All regions ready, with atomic or orchestrated alias switch and rollback plan.
- Hot shard CPU/heap/merge pressure within safe bounds.

### Crawl Green vs Search Freshness

Crawl green means fetchers completed requests. Search freshness also requires parsing, dedup, indexing, segment merge, alias publication, cache invalidation, and query serving. Here crawl completion is normal while CDC lag, bulk errors, and delete lag are severe.

### Missing Generation in Cache Keys

A cached result for `query+locale` can contain doc ids from v42. After v43 cutover, the same key returns old ids that may be deleted, missing, or point to different docs if ids are unstable. During rollback, v43 results can also survive and pollute v42. Including `index_generation` prevents cross-generation mixing.

### Bad-Fix Gallery

| Bad fix | Failure mode |
|---------|--------------|
| Force merge all shards now | Heavy IO/CPU on already hot serving cluster; worsens p99 |
| Purge every cache globally | Query stampede into yellow/hot OpenSearch |
| Keep v43 and patch deleted docs manually | v43 is incomplete and mapping-broken; manual patch misses systemic errors |
| Raise crawler capacity | Crawl is not the bottleneck; adds more index pressure/trap URLs |
| Deploy ranking v17 to 100% | Adds confounding relevance change during corruption incident |

### Capacity/Gating Answer

v43 missing 25M docs means about 4.9% of expected corpus absent (`25M / 512M`). That alone should fail doc-count parity gates. Delete lag at 4.5h during 12M deletes means millions of deleted products can remain visible. Validation gates: doc counts by tenant/category, delete tombstone probes, sample diff vs source of truth, bulk error threshold, CDC lag threshold, query golden set, and alias consistency check across regions.

### Org/Runbook Changes

- No ranking deploys during reindex cutover windows.
- Reindex cutover requires signed gates: doc parity, delete lag, cache version, ads doc-id compatibility, regional alias consistency.
- Crawler policy changes require trap detector active and per-host limits, even for trusted sellers.
- Serving-cluster rebuilds prohibited for major generations except emergency approved by search SRE.
- One owner for cutover orchestration; separate owners for index build, query cache, ranking, ads, and crawler.

---

## Scoring Guide - 85% Gate

| Area | Points |
|------|--------|
| Rapid-fire correctness | 30 |
| Contributing factor evidence | 18 |
| Timed incident sequence | 14 |
| Cache/generation explanation | 12 |
| Bad-fix analysis | 10 |
| Validation/capacity gates | 8 |
| Org/runbook controls | 8 |

Pass gate: **85%+**. Critical misses: treating crawl health as search freshness, ignoring generationless cache keys, or cutting over an incomplete index.
