# WEEK 12 RETENTION TEST

Covers **Weeks 1-12** with emphasis on Google Search, web crawling, and index corruption.

---

## Rules

```text
RULES OF ENGAGEMENT

1. Answer from memory. Do not open the answer key or design modules.
2. Rapid-fire: 2-4 sentences per question.
3. Ops Sim: answer as incident lead, separating evidence from guesses.
4. Write "I do not remember" when needed.
5. Open the answer key only after completing the test.
```

---

## Part 1: Rapid-Fire Concept Recall (15 Questions)

**Q1 (Current - crawling):** Why can a crawler not "crawl everything daily"? Name three signals used to allocate crawl budget.

**Q2 (Current - politeness):** What is host politeness, and how can a bug in politeness enforcement create both technical and legal/customer problems?

**Q3 (Current - indexing):** Distinguish inverted index and forward index. Which is used for candidate retrieval and which for snippets/title fields?

**Q4 (Current - freshness):** Crawl dashboards are green but search results are stale. What pipeline stage is likely unhealthy?

**Q5 (Current - sharding):** Compare doc-id sharding with term sharding for search serving. What happens with hot head terms?

**Q6 (Current - index generations):** Why do mature systems use blue/green index generations or aliases during reindex?

**Q7 (Mid - Kafka/CDC):** Product catalog updates flow Postgres -> CDC -> Kafka -> OpenSearch. What does consumer lag mean for search freshness?

**Q8 (Mid - caching/CDN):** Why must query cache keys include index generation or equivalent versioning during cutover?

**Q9 (Mid - observability):** Name three leading indicators for search quality before support reports "bad results."

**Q10 (Mid - rate limits):** A crawler discovers an infinite calendar URL trap. How do rate limits and dedup filters protect the frontier?

**Q11 (Old - CAP):** During index corruption, why might you serve stale-but-known-good index data instead of partially fresh corrupted data?

**Q12 (Old - replication):** More query replicas improve read capacity but can increase indexing write amplification. Explain the trade-off.

**Q13 (Old - auth/tenancy):** In multi-tenant seller search, what goes wrong if `tenant_id` is missing from index documents or filters?

**Q14 (Old - CDN):** Why is `stale-if-error` dangerous for deleted or legally removed search results?

**Q15 (Old - cost):** What is the cost implication of rebuilding a large index on the serving cluster instead of an offline batch cluster?

---

## Part 2: Compound Ops Sim - Northstar Index Corruption

```text
INCIDENT REPORT

Severity: P1
Company: Northstar Commerce
Systems:
  - crawler-frontier for seller pages and public catalog pages
  - catalog-indexer CDC consumers
  - OpenSearch catalog-live alias
  - query-api and query-result cache
  - ads service that references stable doc ids

Business event:
  Holiday catalog refresh: 80M product updates, 12M deletes, and a
  ranking model canary scheduled in the same maintenance window.

Timeline:
  03:00 - Reindex generation `catalog-v43` starts.
  04:10 - Ranking canary goes to 25%.
  04:25 - Support reports deleted products in top results.
  04:31 - Search p99 rises from 140ms to 2.1s.
  04:40 - Ads CTR drops 18%.
  04:47 - `catalog-live` alias points to v43 in two regions but v42 in one.
```

### Telemetry Pack

```text
Crawler:
  crawl_completed_total: normal
  robots_denied_total: normal
  frontier_queue_depth: +4%
  crawl_trap_detector_unique_urls: +900% for seller calendar pages

Indexer:
  cdc_consumer_lag_seconds: 55 -> 2,800
  bulk_index_error_rate: 0.1% -> 7.8%
  delete_event_apply_lag_p99: 6 min -> 4.5 h
  index_generation=v43 docs: expected 512M, actual 487M
  failed bulk reason: mapper_parsing_exception on new `price_range`

OpenSearch:
  cluster status: yellow
  hot shard CPU: 98%
  segment merges: 6x normal
  query cache hit ratio: 82% -> 39%
  catalog-live alias:
    us-east-1 -> catalog-v43
    eu-west-1 -> catalog-v43
    ap-northeast-1 -> catalog-v42

Query/API:
  result_cache key: query+locale (no index_generation)
  stale-if-error enabled 1h
  top deleted-product result ids present in cache
  p99 query latency: 140ms -> 2.1s

Ads:
  ad doc_id join cache built against v42
  v43 uses sequential doc ids from bulk job
  CTR: -18%
```

### Config Pack

```text
Reindex:
  build_on_serving_cluster=true
  alias_cutover_mode=per_region
  pre_cutover_doc_count_gate=disabled
  delete_stream_priority=normal

Ranking:
  canary_model=v17
  canary_size=25%
  deploy_window overlaps reindex

Cache:
  query_cache_ttl=30m
  stale_if_error=1h
  cache_key=query+locale

Crawler:
  max_urls_per_host_per_day=unlimited for trusted sellers
  calendar_trap_rule=disabled
```

### Decision Points

**T+0:** What do you freeze or roll back first: ranking model, alias, crawler, cache, or indexer? Give the order.

**T+5:** Deleted products still appear after alias rollback in some regions. What cache action is safe, and what cache action is dangerous?

**T+15:** Indexer lag is high because bulk errors reject `price_range`. What schema/index mapping action do you take?

**T+60:** You need to cut over to a corrected index. What gates must pass before changing `catalog-live`?

### Scenario Questions

1. Identify at least six contributing factors and tag them as crawl, index, query cache, ranking, ads/doc-id, or operations.
2. Explain why crawl green does not prove search freshness.
3. Explain how missing index generation in cache keys causes deleted products after rollback/cutover.
4. **Bad-fix gallery:** Analyze (a) force merge all shards now, (b) purge every CDN/query cache globally without origin capacity check, (c) keep v43 and patch deleted docs manually, (d) raise crawler capacity, (e) deploy ranking v17 to 100%.
5. **Capacity question:** If v43 is missing 25M docs and delete lag is 4.5h during 80M updates/12M deletes, what validation checks would have stopped cutover?
6. **Org/runbook question:** What change-management rules prevent ranking deploys, reindex cutovers, and crawler policy changes from overlapping unsafely?

---

## Self-Score Error-Type Table

| Error type | Count | Notes to review |
|------------|-------|-----------------|
| Crawl/index freshness confusion | | |
| Inverted/forward index error | | |
| Alias/generation error | | |
| Cache invalidation/versioning error | | |
| Ranking vs indexing confusion | | |
| Ads/doc-id stability error | | |
| Capacity/gating error | | |
| Runbook/change-management gap | | |

---

> **Answer key (do not open until you attempt the test):**  
> [`../answers/Retention-Tests/Week-12 Answers.md`](../answers/Retention-Tests/Week-12%20Answers.md)
