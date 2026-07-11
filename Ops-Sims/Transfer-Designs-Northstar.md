# Transfer Drill: Designs Northstar - The Relevance Split-Brain

**Time box:** 75 minutes
**Concept range:** Weeks 9-14
**Novel failure:** Feed, search, payments, Kafka/config, docs collaboration, feature store, and LLM serving interact during a marketplace personalization launch.

## Rules

1. Treat this as a system design incident, not a module recall quiz.
2. Keep user safety, money correctness, and data ownership explicit.
3. Every design choice must name consistency boundary and rollback plan.
4. Do not open the answer key until finished.

---

## 1. Scenario stem

```text
Northstar launches personalized marketplace search and AI seller replies.
The product combines:
  - Twitter-style home feed for buyers
  - Google-search-like marketplace retrieval
  - Payment risk scoring at checkout
  - Kafka event backbone
  - Config store for experiment flags
  - Google-Docs-style collaborative seller campaign editor
  - Feature store for ranking/risk features
  - LLM serving platform for seller replies

Launch goal:
  increase conversion without showing unsafe, unavailable, or policy-violating items.

Incident:
  Buyers see recalled items promoted in feeds.
  Search results disagree with product pages.
  Some checkouts are blocked for low-risk buyers and allowed for high-risk buyers.
  Seller campaign docs show lost edits.
  AI replies quote stale prices.
```

---

## 2. Telemetry pack

```text
FEED / CHAT-LIKE FANOUT:
  home feed fanout workers lag: 0 -> 38m
  celebrity seller followers: 19M
  feed cache TTL: 20m
  push fanout success: 81%
  pull-on-read fallback enabled: false

SEARCH / CRAWLING:
  product index age p99: 4m -> 2h 15m
  deleted/recalled SKU tombstones pending: 3.2M
  query p99: 180ms -> 2.4s
  shard hotness: shard-07 CPU 96%, median 42%
  index alias points to: products-v42
  recall pipeline writes to: products-v43

PAYMENTS / RISK:
  feature freshness for risk_score:
    p50=45s, p99=47m
  checkout decisions using feature_store_online: 99.2%
  fallback when feature missing: allow
  chargeback spike: 0.4% -> 2.8%
  false block complaints: 14,000/hour

KAFKA / CONFIG STORE:
  ranking-events topic partitions: 24
  key: seller_id
  top seller owns 54% of events
  config store quorum: 3 of 5
  config client cache TTL: 15m
  bad flag:
    use_products_v43_for_recall_filter: true in 2 regions, false in 1
  config watch lag: 22m in eu-west-1

COLLAB DOCS:
  seller campaign editor uses OT/CRDT hybrid
  region us-east accepted ops 1001-1044
  region eu-west accepted ops 1001-1031 during partition
  merge conflict queue: 0 -> 28,000
  lost edit reports: 3,700
  server transform version mismatch: v7 vs v8

FEATURE STORE / LLM:
  offline features updated hourly
  online features updated from Kafka
  online/offline skew check disabled for launch
  LLM prompt context cache TTL: 6h
  price source in prompt: search index
  safety policy version: policy-2026-06 in LLM, policy-2026-07 in product API
  GPU queue p99: 1.2s -> 19s
  tenant enterprise-sapphire consumes 72% GPU tokens
```

---

## 3. Wrong config pack

```yaml
feed:
  cache_ttl: 20m
  pull_on_read_fallback: false
  celebrity_seller_mode: push_only

search:
  live_alias: products-v42
  recall_filter_alias: products-v43
  tombstone_priority: normal
  shard_key: seller_id

risk:
  missing_feature_default: allow
  max_feature_age_for_checkout: 60m
  require_fresh_features_for_high_value: false

config:
  client_cache_ttl: 15m
  require_monotonic_flag_version: false
  region_override_allowed_without_expiry: true

docs:
  transform_version_us: v8
  transform_version_eu: v7
  accept_writes_during_transform_mismatch: true

llm:
  prompt_context_cache_ttl: 6h
  price_context_source: search_index
  policy_version: policy-2026-06
  per_tenant_gpu_cap: none
```

---

## 4. T+ timeline

| Time | Event | Your move |
|------|-------|-----------|
| T+0 | Recalled items appear in feed/search; checkout risk errors rise. | |
| T+5 | Config differs by region; feed lag and search lag diverge. | |
| T+15 | Seller docs report lost edits; LLM replies stale prices and old policy. | |
| T+60 | Business wants to keep personalization on for unaffected categories. | |

---

## 5. Bad fixes

1. Disable all checkout risk checks to reduce false blocks.
2. Delete all feed caches globally and let fanout catch up naturally.
3. Point product pages to search index because search is faster than DB.
4. Force config flag true everywhere without checking alias readiness.
5. Replay all doc operations through the old transform service.
6. Let LLM continue with a disclaimer that prices may be stale.
7. Add more GPU capacity without tenant caps.
8. Repartition Kafka by random UUID immediately.

---

## 6. Capacity / blast-radius worksheet

```text
Ranking hot key:
  top seller share = 54%
  partitions = 24
  if keyed by seller_id, can one seller use more than one partition? ______

Config staleness:
  client cache TTL = 15m
  watch lag eu-west = 22m
  worst visible stale flag window approx = ______

Feature freshness:
  max feature age for checkout = 60m
  observed p99 = 47m
  high-value checkout freshness required? ______

GPU fairness:
  enterprise-sapphire token share = 72%
  remaining tenants share = ______
```

---

## 7. Questions

**Q1 - Domain inventory:** Identify at least eight subsystem failures and the design module themes they map to.

**Q2 - Safety first:** Which user/money/policy paths must be failed closed or degraded first? Which can stay eventually consistent?

**Q3 - Feed/search consistency:** How do you stop recalled items from appearing without destroying the whole feed system?

**Q4 - Payment risk:** What freshness contract should risk features have? How should missing/stale features behave by transaction class?

**Q5 - Kafka/config:** Explain hot partitioning and regional config split-brain. What design changes prevent repeat?

**Q6 - Collaborative docs:** How do you handle transform version mismatch and lost-edit reports without corrupting seller documents?

**Q7 - Feature store/LLM:** How do online/offline skew, prompt context TTL, policy versioning, and tenant GPU fairness interact?

**Q8 - Bad fix rejection:** Reject all bad fixes with safer alternatives.

**Q9 - T+60 partial recovery:** What can be re-enabled for unaffected categories, and what evidence gates each re-enable?

**Q10 - Durable design:** Propose a revised architecture across feed, search, risk, config, docs, feature store, LLM, and org ownership.

**Q11 - Principal stretch:** Give a decision record for the consistency boundaries: source of truth, derived views, freshness budget, and rollback owner.

---

## 8. Self-score

| Error type | Did it happen? | Note |
|------------|----------------|------|
| Derived index treated as source of truth | | |
| Risk fail-open accepted | | |
| Config split-brain ignored | | |
| Collaboration merge safety missed | | |
| LLM stale context minimized | | |
| Tenant GPU fairness missed | | |

**Answer key:** [`../answers/Ops-Sims/Transfer-Designs-Northstar Answers.md`](../answers/Ops-Sims/Transfer-Designs-Northstar%20Answers.md)
