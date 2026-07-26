# Design Recommendation System

A recommendation system is a latency-bound decision engine that transforms user, item, context, and policy signals into ranked candidates.
The hard parts are not only model quality; they are freshness, feedback loops, abuse, cold start, tenancy, explainability, and safe experimentation.
This module is distinct from a generic search design: recommendation optimizes personalized utility under exposure and feedback constraints.

---

## 1. Learning Objectives

After this module, you will be able to:

1. Decompose recommendations into candidate generation, feature hydration, ranking, filtering, blending, and logging.
2. Design retrieval strategies for collaborative filtering, content-based recall, graph traversal, embeddings/ANN, trending, and editorial/business rules.
3. Use an online feature store safely by linking feature definitions to training data and bounded serving freshness (see `Week-14-Collaboration-and-AI-Designs/Design Feature Store.md`).
4. Size latency budgets across candidate services, ranking models, online stores, and fallbacks.
5. Identify feedback loops, popularity bias, filter bubbles, cold start, abuse/gaming, and multi-tenant catalog hazards.
6. Design A/B tests and guardrails that measure user impact without breaking trust, privacy, or tenant isolation.
7. Run an incident bridge for a recommendation quality and serving-latency regression.

---

## 2. Wrong Mental Models

### Mental model 1: Recommendations are just ranking

Correction: Ranking can only order what recall produced. Bad candidate generation creates invisible false negatives that no ranker can repair.

### Mental model 2: CTR is the only objective

Correction: CTR can reward clickbait, loops, abuse, or low-margin items. Objectives need conversion, retention, diversity, fairness, trust, latency, and business constraints.

### Mental model 3: The model owns correctness

Correction: Feature freshness, logging, exposure policy, dedupe, inventory state, and tenant isolation can dominate model quality.

### Mental model 4: More candidates always improve quality

Correction: More candidates increase recall but also feature fanout, ranking latency, and tail risk. Candidate count is a latency and cost decision.

### Mental model 5: A/B tests make decisions automatically

Correction: Experiments can be underpowered, biased by novelty, contaminated across tenants, or unsafe if guardrail metrics are missing.

### Mental model 6: Cold start is only a user problem

Correction: Users, items, tenants, sellers, regions, and seasons all cold-start differently.

### Mental model 7: Abuse is solved by moderation

Correction: Gaming the recommender often uses valid actions: fake clicks, review rings, inventory stuffing, keyword spam, and paid traffic.

### Mental model 8: Multi-tenant catalogs are one big item table

Correction: Tenant-specific availability, pricing, policy, ranking objectives, and quotas must be enforced in retrieval, ranking, caches, and logs.

---

## 3. Requirements and Constraints

### Functional requirements

- Return personalized recommendations for home feed, product detail page, cart, email, and search-adjacent surfaces.
- Support anonymous users, new users, returning users, and enterprise tenants with private catalogs.
- Mix candidate sources: collaborative, content-based, embedding ANN, trending, inventory-aware, sponsored, and editorial.
- Filter out unavailable, policy-blocked, tenant-ineligible, unsafe, duplicate, and already-purchased items.
- Rank candidates with real-time and batch features.
- Log request, candidate, exposure, rank, score, feature versions, and outcome events for training and audit.
- Run experiments by surface, tenant, geography, device, user cohort, and model version.

### Non-functional requirements

- p99 latency target: 150 ms for home page recommendations after edge/API overhead.
- Availability target: recommendations degrade to safe fallback rather than block checkout or product pages.
- Feature freshness: critical stock/price/policy under 30 seconds; behavioral aggregates under 5 minutes; embeddings under 24 hours unless marked stale.
- Multi-tenant isolation: tenant catalog boundaries are enforced before ranking and again before response.
- Observability: quality, freshness, latency, cost, abuse, and experiment metrics must be sliceable by surface/model/tenant without unbounded cardinality.
- Privacy: training and serving must not leak one tenant's users, items, or outcomes into another tenant's catalog unless explicitly allowed.

### Abuse, cost, and safety constraints

- Attackers can generate clicks, add-to-cart events, reviews, dwell time, and seller metadata that look legitimate.
- Sellers can game titles, images, prices, stock, category labels, and promotions.
- Tenants can create huge catalogs or high-cardinality features that exhaust shared online stores.
- Model serving cost must be measured per 1,000 recommendation responses, per candidate source, and per tenant/surface.
- Fallbacks must prefer safe, available, policy-compliant items over stale personalized items.

## 4. Critical Paths

### 4.1 Online read path

```text
request(user, surface, tenant, context)
  -> identity/auth/tenant policy
  -> request context normalization
  -> parallel candidate generation
  -> candidate merge + dedupe + business filters
  -> feature hydration from online store and request context
  -> ranker model inference
  -> policy recheck + diversification + sponsored blending
  -> response + exposure logging
```

Latency budget example for p99 150 ms:

| Stage | Budget | Notes |
|---|---:|---|
| API/auth/context | 10 ms | includes tenant policy lookup from hot cache |
| Candidate generation fanout | 35 ms | parallel; slow sources cut off |
| Merge/filter/dedupe | 8 ms | includes tenant catalog and inventory filter |
| Feature hydration | 25 ms | online store batch gets and request features |
| Ranking inference | 40 ms | model or ensemble; p99 protected by admission |
| Blending/diversity | 12 ms | category caps, sponsored rules, safety policy |
| Logging enqueue | 5 ms | async durable buffer, no blocking on warehouse |
| Slack | 15 ms | network variance and retries within budget |

A design that uses all sources synchronously with no cutoffs is not a production design.
Every candidate source must declare a deadline, max candidates, fallback behavior, and owner.

### 4.2 Offline and nearline paths

```text
raw events -> validation -> sessionization -> feature pipelines -> offline store
raw catalog -> policy/inventory joins -> item features -> embeddings/indexes
training data -> point-in-time joins -> train/evaluate -> model registry
approved model -> shadow/canary -> online ranker
outcomes -> attribution -> feedback features -> monitoring
```

Feature Store link: online features should come from the same feature definitions used for training whenever feasible.
The online store serves latest bounded-freshness values; the offline store provides point-in-time correct historical retrieval.
If a feature is computed differently online and offline, it needs explicit skew monitoring and owner approval.

### 4.3 Consistency boundaries

Strong consistency is required for:

- tenant catalog eligibility
- legal/policy block lists
- price and inventory when recommendation implies availability
- experiment assignment once the user is bucketed
- user privacy opt-out and deletion state

Eventual consistency is acceptable for:

- behavioral aggregates such as 7-day clicks
- embeddings refreshed hourly/daily
- trending windows
- diversity counters within a session if final response is policy-safe

The key interview sentence: recommendation quality can be eventually consistent; trust and eligibility cannot.

### 4.4 Candidate Generation Sources

#### Source: Co-visitation

- Mechanism: users who viewed/bought X also viewed Y.
- Strength: fast item-to-item recall.
- Risk: popularity loops and stale inventory.
- Required metadata: tenant, surface, freshness time, source version, and max candidates.
- Deadline behavior: return partial candidates or empty list before blocking ranker SLA.

#### Source: Collaborative filtering

- Mechanism: latent user-item factors.
- Strength: personalized recall.
- Risk: cold start and sparse users.
- Required metadata: tenant, surface, freshness time, source version, and max candidates.
- Deadline behavior: return partial candidates or empty list before blocking ranker SLA.

#### Source: Content-based

- Mechanism: category, text, brand, image, attributes.
- Strength: new item support.
- Risk: metadata gaming.
- Required metadata: tenant, surface, freshness time, source version, and max candidates.
- Deadline behavior: return partial candidates or empty list before blocking ranker SLA.

#### Source: Embedding ANN

- Mechanism: nearest neighbors in learned vector space.
- Strength: semantic recall.
- Risk: index freshness and tenant leakage.
- Required metadata: tenant, surface, freshness time, source version, and max candidates.
- Deadline behavior: return partial candidates or empty list before blocking ranker SLA.

#### Source: Trending

- Mechanism: recent velocity by region/surface.
- Strength: anonymous fallback.
- Risk: flash abuse and seasonality.
- Required metadata: tenant, surface, freshness time, source version, and max candidates.
- Deadline behavior: return partial candidates or empty list before blocking ranker SLA.

#### Source: Graph

- Mechanism: seller/category/user relation traversal.
- Strength: explainable paths.
- Risk: fanout and graph spam.
- Required metadata: tenant, surface, freshness time, source version, and max candidates.
- Deadline behavior: return partial candidates or empty list before blocking ranker SLA.

#### Source: Editorial

- Mechanism: curated campaigns.
- Strength: business control.
- Risk: manual stale lists.
- Required metadata: tenant, surface, freshness time, source version, and max candidates.
- Deadline behavior: return partial candidates or empty list before blocking ranker SLA.

#### Source: Sponsored

- Mechanism: ads or promoted products.
- Strength: monetization.
- Risk: trust and auction separation.
- Required metadata: tenant, surface, freshness time, source version, and max candidates.
- Deadline behavior: return partial candidates or empty list before blocking ranker SLA.

---

## 5. Data Model and Capacity Math

### 5.1 Core entities

```text
UserProfile(user_id, tenant_id, privacy_state, cohorts, embeddings, updated_at)
Item(item_id, tenant_id, seller_id, category, attributes, status, price_version, inventory_state)
Interaction(user_id, item_id, event_type, surface, timestamp, request_id, experiment_id)
CandidateSet(request_id, source, item_id, raw_score, source_version)
FeatureVector(request_id, item_id, feature_names, feature_versions, values)
RecommendationResponse(request_id, ranked_items, model_version, policy_version, latency_ms)
ExperimentAssignment(user_id_or_session, experiment_id, variant, assigned_at)
```

### 5.2 Online store keys

Use batch-friendly, tenant-scoped keys:

```text
user_feature:   tenant_id#user_id#feature_view -> values, updated_at, ttl, version
item_feature:   tenant_id#item_id#feature_view -> values, updated_at, ttl, version
pair_feature:   tenant_id#user_id#item_id#feature_view -> values when truly needed
source_cache:   tenant_id#surface#source#context_bucket -> candidate ids, generated_at
experiment:     tenant_id#subject#experiment_id -> variant, assigned_at
```

Pair features are expensive. Use them only when they materially improve rank quality because they multiply by user x candidate count.

### 5.3 Capacity worksheet

Assume:

- 20,000 recommendation requests per second at peak
- 4 surfaces per active session over a short window
- 6 candidate sources per request
- 800 raw candidates fetched per request
- 250 candidates after dedupe/filter
- 80 candidates sent to ranker
- 120 features per candidate with batch hydration
- 150 ms p99 response target

Derived checks:

```text
candidate source calls/sec = 20,000 * 6 = 120,000 calls/sec
raw candidates/sec = 20,000 * 800 = 16,000,000 candidates/sec
ranked candidates/sec = 20,000 * 80 = 1,600,000 candidate-scores/sec
feature values/sec logical = 1,600,000 * 120 = 192,000,000 feature values/sec
if batch get returns 80 candidate vectors per request, online store requests/sec ~= 20,000 plus source-specific lookups
```

This is why feature hydration must be batched, cached, and pruned.
A ranker with 40 ms budget cannot perform 80 separate network calls per request.

### 5.4 Feature cards

#### Feature: `user_7d_click_count`

- Family: behavior.
- Freshness target: 5m.
- Hazard: feedback loop if bots click.
- Store: define in the Feature Store registry with owner, TTL, default semantics, and offline point-in-time retrieval.
- Monitor: freshness, null rate, distribution drift, and model dependency impact.

#### Feature: `user_30d_purchase_category_histogram`

- Family: behavior.
- Freshness target: 1h.
- Hazard: privacy and sparse-user leakage.
- Store: define in the Feature Store registry with owner, TTL, default semantics, and offline point-in-time retrieval.
- Monitor: freshness, null rate, distribution drift, and model dependency impact.

#### Feature: `item_1h_view_velocity`

- Family: trend.
- Freshness target: 2m.
- Hazard: abuse via paid traffic.
- Store: define in the Feature Store registry with owner, TTL, default semantics, and offline point-in-time retrieval.
- Monitor: freshness, null rate, distribution drift, and model dependency impact.

#### Feature: `item_inventory_state`

- Family: catalog.
- Freshness target: 30s.
- Hazard: must not recommend unavailable items.
- Store: define in the Feature Store registry with owner, TTL, default semantics, and offline point-in-time retrieval.
- Monitor: freshness, null rate, distribution drift, and model dependency impact.

#### Feature: `item_price_version`

- Family: catalog.
- Freshness target: 30s.
- Hazard: stale price trust issue.
- Store: define in the Feature Store registry with owner, TTL, default semantics, and offline point-in-time retrieval.
- Monitor: freshness, null rate, distribution drift, and model dependency impact.

#### Feature: `seller_quality_score`

- Family: trust.
- Freshness target: 1h.
- Hazard: review ring gaming.
- Store: define in the Feature Store registry with owner, TTL, default semantics, and offline point-in-time retrieval.
- Monitor: freshness, null rate, distribution drift, and model dependency impact.

#### Feature: `user_embedding`

- Family: model.
- Freshness target: 24h.
- Hazard: cold users use cohort embedding.
- Store: define in the Feature Store registry with owner, TTL, default semantics, and offline point-in-time retrieval.
- Monitor: freshness, null rate, distribution drift, and model dependency impact.

#### Feature: `item_embedding`

- Family: model.
- Freshness target: 24h.
- Hazard: new items need content embedding.
- Store: define in the Feature Store registry with owner, TTL, default semantics, and offline point-in-time retrieval.
- Monitor: freshness, null rate, distribution drift, and model dependency impact.

#### Feature: `session_last_category`

- Family: context.
- Freshness target: request.
- Hazard: over-personalization within session.
- Store: define in the Feature Store registry with owner, TTL, default semantics, and offline point-in-time retrieval.
- Monitor: freshness, null rate, distribution drift, and model dependency impact.

#### Feature: `tenant_policy_blocklist`

- Family: policy.
- Freshness target: immediate.
- Hazard: fail closed on missing policy.
- Store: define in the Feature Store registry with owner, TTL, default semantics, and offline point-in-time retrieval.
- Monitor: freshness, null rate, distribution drift, and model dependency impact.

#### Feature: `surface_position_bias`

- Family: logging.
- Freshness target: offline.
- Hazard: needed for unbiased training.
- Store: define in the Feature Store registry with owner, TTL, default semantics, and offline point-in-time retrieval.
- Monitor: freshness, null rate, distribution drift, and model dependency impact.

#### Feature: `experiment_variant`

- Family: control.
- Freshness target: sticky.
- Hazard: contamination if recomputed.
- Store: define in the Feature Store registry with owner, TTL, default semantics, and offline point-in-time retrieval.
- Monitor: freshness, null rate, distribution drift, and model dependency impact.

---

## 6. Failure and Abuse Catalog

### Failure 1: Candidate source timeout

- Trigger: ANN or graph service slow.
- Amplifier: ranker receives narrow list.
- Blast radius: diversity and relevance collapse.
- Evidence: slice by surface, tenant, source, model, feature version, and experiment variant.
- Safer mitigation: disable or cap the smallest faulty source/feature/model before falling back globally.

### Failure 2: Feature store stale

- Trigger: stream materialization lag.
- Amplifier: ranker scores old behavior.
- Blast radius: CTR/conversion drop.
- Evidence: slice by surface, tenant, source, model, feature version, and experiment variant.
- Safer mitigation: disable or cap the smallest faulty source/feature/model before falling back globally.

### Failure 3: Training-serving skew

- Trigger: offline feature SQL differs.
- Amplifier: model learns unavailable signal.
- Blast radius: quality regression after deploy.
- Evidence: slice by surface, tenant, source, model, feature version, and experiment variant.
- Safer mitigation: disable or cap the smallest faulty source/feature/model before falling back globally.

### Failure 4: Feedback loop

- Trigger: ranker overexposes popular items.
- Amplifier: more clicks reinforce exposure.
- Blast radius: long-tail disappears.
- Evidence: slice by surface, tenant, source, model, feature version, and experiment variant.
- Safer mitigation: disable or cap the smallest faulty source/feature/model before falling back globally.

### Failure 5: Click fraud

- Trigger: bot or seller farm clicks items.
- Amplifier: behavioral features inflate.
- Blast radius: bad items rank high.
- Evidence: slice by surface, tenant, source, model, feature version, and experiment variant.
- Safer mitigation: disable or cap the smallest faulty source/feature/model before falling back globally.

### Failure 6: Review ring

- Trigger: coordinated seller reviews.
- Amplifier: trust feature polluted.
- Blast radius: unsafe sellers promoted.
- Evidence: slice by surface, tenant, source, model, feature version, and experiment variant.
- Safer mitigation: disable or cap the smallest faulty source/feature/model before falling back globally.

### Failure 7: Cold-start user

- Trigger: anonymous or new account.
- Amplifier: no history.
- Blast radius: generic/repetitive feed.
- Evidence: slice by surface, tenant, source, model, feature version, and experiment variant.
- Safer mitigation: disable or cap the smallest faulty source/feature/model before falling back globally.

### Failure 8: Cold-start item

- Trigger: new listing.
- Amplifier: no interactions.
- Blast radius: item never gets exposure.
- Evidence: slice by surface, tenant, source, model, feature version, and experiment variant.
- Safer mitigation: disable or cap the smallest faulty source/feature/model before falling back globally.

### Failure 9: Tenant leakage

- Trigger: candidate cache key omits tenant.
- Amplifier: items cross catalog.
- Blast radius: privacy and contract breach.
- Evidence: slice by surface, tenant, source, model, feature version, and experiment variant.
- Safer mitigation: disable or cap the smallest faulty source/feature/model before falling back globally.

### Failure 10: Inventory stale

- Trigger: catalog CDC lag.
- Amplifier: unavailable items recommended.
- Blast radius: trust and conversion drop.
- Evidence: slice by surface, tenant, source, model, feature version, and experiment variant.
- Safer mitigation: disable or cap the smallest faulty source/feature/model before falling back globally.

### Failure 11: Experiment contamination

- Trigger: assignment not sticky.
- Amplifier: user sees both variants.
- Blast radius: invalid A/B result.
- Evidence: slice by surface, tenant, source, model, feature version, and experiment variant.
- Safer mitigation: disable or cap the smallest faulty source/feature/model before falling back globally.

### Failure 12: Model rollback without feature rollback

- Trigger: old model expects old defaults.
- Amplifier: score distribution shifts.
- Blast radius: latency or quality incident.
- Evidence: slice by surface, tenant, source, model, feature version, and experiment variant.
- Safer mitigation: disable or cap the smallest faulty source/feature/model before falling back globally.

### Failure 13: Unbounded source fanout

- Trigger: new source returns 10k candidates.
- Amplifier: feature hydration explodes.
- Blast radius: p99 breaks.
- Evidence: slice by surface, tenant, source, model, feature version, and experiment variant.
- Safer mitigation: disable or cap the smallest faulty source/feature/model before falling back globally.

### Failure 14: Sponsored blend bug

- Trigger: ad quota overrides organic safety.
- Amplifier: low-trust items promoted.
- Blast radius: user trust loss.
- Evidence: slice by surface, tenant, source, model, feature version, and experiment variant.
- Safer mitigation: disable or cap the smallest faulty source/feature/model before falling back globally.

### Failure 15: Metric cardinality blowup

- Trigger: raw item_id labels.
- Amplifier: observability bill and outage.
- Blast radius: blind incident response.
- Evidence: slice by surface, tenant, source, model, feature version, and experiment variant.
- Safer mitigation: disable or cap the smallest faulty source/feature/model before falling back globally.

---

## 7. Design Gates

### Gate 1 - Candidate generation

- What are the candidate sources?
- What is each source's deadline and max candidate count?
- Which sources are personalized, contextual, trending, editorial, or sponsored?
- How do you prevent one source from dominating recall?
- What is the fallback when ANN or graph recall is unavailable?

### Gate 2 - Ranking and features

- Which features are request, user, item, pair, context, and policy features?
- Which features come from the Feature Store online path?
- What is the freshness SLA for each critical feature?
- How do you detect training-serving skew?
- What defaults are safe under missing features?

### Gate 3 - Feedback and experimentation

- What is the objective function and guardrail set?
- How do you log exposures, non-clicks, positions, and variants?
- How do you prevent popularity loops and position bias?
- How do you keep experiment assignment sticky?
- What metrics can stop the experiment early?

### Gate 4 - Abuse and gaming

- Which actors can manipulate clicks, reviews, metadata, inventory, or bids?
- What anomaly features detect gaming without punishing organic spikes?
- Which quotas limit one seller or tenant from poisoning shared features?
- Which mitigations are scoped and reversible?
- How are trust and policy signals separated from engagement signals?

### Gate 5 - Multi-tenant catalogs

- Where is tenant context enforced before retrieval?
- Where is it rechecked after ranking?
- Which caches include tenant, catalog, region, and policy version?
- How are large tenants isolated physically or by capacity lane?
- How do training datasets avoid cross-tenant leakage?

### Gate 6 - Latency and cost

- What is the p99 budget by stage?
- What source is cut off first?
- What is unit cost per 1,000 recommendation responses?
- How do you attribute cost by tenant and surface?
- What fallback preserves trust under overload?

### 7.1 Design Drill Cards

#### Drill 1: product detail with co-visitation pressure

- Scenario: co-visitation source becomes slow or biased for the product detail surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 2: cart with trending pressure

- Scenario: trending source becomes slow or biased for the cart surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 3: email with graph pressure

- Scenario: graph source becomes slow or biased for the email surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 4: search zero-result with sponsored pressure

- Scenario: sponsored source becomes slow or biased for the search zero-result surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 5: tenant storefront with editorial pressure

- Scenario: editorial source becomes slow or biased for the tenant storefront surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 6: home feed with ANN pressure

- Scenario: ANN source becomes slow or biased for the home feed surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 7: product detail with co-visitation pressure

- Scenario: co-visitation source becomes slow or biased for the product detail surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 8: cart with trending pressure

- Scenario: trending source becomes slow or biased for the cart surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 9: email with graph pressure

- Scenario: graph source becomes slow or biased for the email surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 10: search zero-result with sponsored pressure

- Scenario: sponsored source becomes slow or biased for the search zero-result surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 11: tenant storefront with editorial pressure

- Scenario: editorial source becomes slow or biased for the tenant storefront surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 12: home feed with ANN pressure

- Scenario: ANN source becomes slow or biased for the home feed surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 13: product detail with co-visitation pressure

- Scenario: co-visitation source becomes slow or biased for the product detail surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 14: cart with trending pressure

- Scenario: trending source becomes slow or biased for the cart surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 15: email with graph pressure

- Scenario: graph source becomes slow or biased for the email surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 16: search zero-result with sponsored pressure

- Scenario: sponsored source becomes slow or biased for the search zero-result surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 17: tenant storefront with editorial pressure

- Scenario: editorial source becomes slow or biased for the tenant storefront surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 18: home feed with ANN pressure

- Scenario: ANN source becomes slow or biased for the home feed surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 19: product detail with co-visitation pressure

- Scenario: co-visitation source becomes slow or biased for the product detail surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 20: cart with trending pressure

- Scenario: trending source becomes slow or biased for the cart surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 21: email with graph pressure

- Scenario: graph source becomes slow or biased for the email surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 22: search zero-result with sponsored pressure

- Scenario: sponsored source becomes slow or biased for the search zero-result surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 23: tenant storefront with editorial pressure

- Scenario: editorial source becomes slow or biased for the tenant storefront surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 24: home feed with ANN pressure

- Scenario: ANN source becomes slow or biased for the home feed surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 25: product detail with co-visitation pressure

- Scenario: co-visitation source becomes slow or biased for the product detail surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 26: cart with trending pressure

- Scenario: trending source becomes slow or biased for the cart surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 27: email with graph pressure

- Scenario: graph source becomes slow or biased for the email surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 28: search zero-result with sponsored pressure

- Scenario: sponsored source becomes slow or biased for the search zero-result surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 29: tenant storefront with editorial pressure

- Scenario: editorial source becomes slow or biased for the tenant storefront surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 30: home feed with ANN pressure

- Scenario: ANN source becomes slow or biased for the home feed surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 31: product detail with co-visitation pressure

- Scenario: co-visitation source becomes slow or biased for the product detail surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 32: cart with trending pressure

- Scenario: trending source becomes slow or biased for the cart surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 33: email with graph pressure

- Scenario: graph source becomes slow or biased for the email surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 34: search zero-result with sponsored pressure

- Scenario: sponsored source becomes slow or biased for the search zero-result surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 35: tenant storefront with editorial pressure

- Scenario: editorial source becomes slow or biased for the tenant storefront surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 36: home feed with ANN pressure

- Scenario: ANN source becomes slow or biased for the home feed surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 37: product detail with co-visitation pressure

- Scenario: co-visitation source becomes slow or biased for the product detail surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 38: cart with trending pressure

- Scenario: trending source becomes slow or biased for the cart surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 39: email with graph pressure

- Scenario: graph source becomes slow or biased for the email surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

#### Drill 40: search zero-result with sponsored pressure

- Scenario: sponsored source becomes slow or biased for the search zero-result surface during peak traffic.
- Name the candidate cutoff, fallback source, and diversity guardrail.
- State which feature freshness metric proves the fallback is safe.
- State how tenant catalog eligibility is enforced before and after ranking.
- State one abuse/gaming hypothesis and one organic-spike hypothesis.

---

## 8. Ops Sim / Interview Drill

Questions only. Do not open the answer key until you finish.

### Scenario

Northstar Commerce launches a new recommendation ranker for home feed and product detail pages.
One large marketplace tenant reports irrelevant promoted items, while global CTR initially rises.
At the same time, p99 recommendation latency breaches the 150 ms target and checkout conversion drops.

### Telemetry pack

```text
global CTR:                         +6.5%
checkout conversion:                -3.8%
enterprise tenant CTR:              -11.0%
home feed p99 latency:              142 ms -> 310 ms
candidate source calls/sec:         120k -> 190k
ANN p99:                            22 ms -> 95 ms
feature store p99 batch get:        18 ms -> 64 ms
item_inventory_state staleness p95: 25 s -> 7 min
new seller click velocity:          +900% from 2 ASNs
sponsored blend share:              8% -> 23%
tenant catalog cache hit:           96% -> 71%
experiment assignment conflicts:    0.2% -> 6.1%
```

### Config pack

```yaml
candidateGeneration:
  sources: [ann, covisitation, trending, sponsored, editorial, graph]
  perSourceDeadlineMs: 60          # suspect for p99 budget
  maxRawCandidates: 2000           # suspect
ranking:
  modelVersion: ranker-v42
  rankTopK: 250                    # suspect
  featureBatchSize: 250
features:
  inventoryFreshnessMaxAge: 10m    # suspect
  behavioralFreshnessMaxAge: 5m
experiments:
  assignmentKey: session_id        # suspect for logged-in users
  guardrails: [latency_p99, error_rate] # missing conversion/trust/tenant slices
tenancy:
  cacheKey: surface:item_id        # suspect: missing tenant/catalog/policy
abuse:
  clickVelocityCap: disabled       # suspect
```

### Timeline

- T+0: ranker-v42 ramps to 10% globally.
- T+5: global CTR rises; rollout continues to 50%.
- T+15: enterprise tenant reports cross-catalog recommendations and irrelevant sponsored items.
- T+60: conversion drop is confirmed; feature store and ANN p99 remain elevated.

### Questions

1. Split trigger, amplifiers, symptoms, and business impact.
2. Which metric proves global CTR is misleading?
3. Which config values violate latency budget or tenant isolation?
4. Compute ranked candidate-scores/sec at 20k QPS and rankTopK 250. Compare with rankTopK 80.
5. What is the first safe mitigation: rollback model, cap a source, freeze sponsored blend, or tighten inventory freshness? Justify order.
6. How do you preserve A/B validity while stopping customer harm?
7. Which feature store checks connect this incident to `Design Feature Store.md`?
8. How do you distinguish abuse click farming from organic trend?
9. What cache key should replace `surface:item_id`?
10. What fallback recommendation set is safe for the affected enterprise tenant?
11. Which bad fixes should be rejected? Name at least three.
12. What post-incident gates must every future ranker pass?

13. Additional interview drill: choose one candidate source and specify deadline, max candidates, fallback, abuse signal, and tenant-isolation test.
14. Additional interview drill: choose one candidate source and specify deadline, max candidates, fallback, abuse signal, and tenant-isolation test.
15. Additional interview drill: choose one candidate source and specify deadline, max candidates, fallback, abuse signal, and tenant-isolation test.
16. Additional interview drill: choose one candidate source and specify deadline, max candidates, fallback, abuse signal, and tenant-isolation test.
17. Additional interview drill: choose one candidate source and specify deadline, max candidates, fallback, abuse signal, and tenant-isolation test.
18. Additional interview drill: choose one candidate source and specify deadline, max candidates, fallback, abuse signal, and tenant-isolation test.
19. Additional interview drill: choose one candidate source and specify deadline, max candidates, fallback, abuse signal, and tenant-isolation test.
20. Additional interview drill: choose one candidate source and specify deadline, max candidates, fallback, abuse signal, and tenant-isolation test.
21. Additional interview drill: choose one candidate source and specify deadline, max candidates, fallback, abuse signal, and tenant-isolation test.
22. Additional interview drill: choose one candidate source and specify deadline, max candidates, fallback, abuse signal, and tenant-isolation test.
23. Additional interview drill: choose one candidate source and specify deadline, max candidates, fallback, abuse signal, and tenant-isolation test.
24. Additional interview drill: choose one candidate source and specify deadline, max candidates, fallback, abuse signal, and tenant-isolation test.
25. Additional interview drill: choose one candidate source and specify deadline, max candidates, fallback, abuse signal, and tenant-isolation test.
26. Additional interview drill: choose one candidate source and specify deadline, max candidates, fallback, abuse signal, and tenant-isolation test.
27. Additional interview drill: choose one candidate source and specify deadline, max candidates, fallback, abuse signal, and tenant-isolation test.
28. Additional interview drill: choose one candidate source and specify deadline, max candidates, fallback, abuse signal, and tenant-isolation test.
29. Additional interview drill: choose one candidate source and specify deadline, max candidates, fallback, abuse signal, and tenant-isolation test.
30. Additional interview drill: choose one candidate source and specify deadline, max candidates, fallback, abuse signal, and tenant-isolation test.
31. Additional interview drill: choose one candidate source and specify deadline, max candidates, fallback, abuse signal, and tenant-isolation test.
32. Additional interview drill: choose one candidate source and specify deadline, max candidates, fallback, abuse signal, and tenant-isolation test.

---

## 9. Takeaways and Reading

- Candidate generation controls the universe the ranker can see.
- Feature Store integration matters because online freshness and offline point-in-time correctness shape model quality.
- Global CTR can hide tenant harm, conversion loss, abuse, and trust regressions.
- Latency budgets must include candidate fanout and feature hydration, not only model inference.
- Cold start needs separate policies for users, items, tenants, sellers, and regions.
- Multi-tenant catalog isolation is enforced at retrieval, ranking, caching, logging, and training.
- A/B tests need guardrails and slice analysis before rollout decisions.

Targeted reading:

- Week-14 Design Feature Store for online/offline feature consistency and materialization.
- Week-12 Design Google Search for retrieval, ranking, and indexing contrasts.
- Week-07 Search Systems and Inverted Indexes for recall and shard freshness mechanisms.
- Week-08 Observability and SLO modules for slice-based quality and latency guardrails.
- Papers/blogs on two-stage recommenders, approximate nearest neighbor search, position bias correction, and counterfactual evaluation.

## Additional Recommendation Review Cases

### Review Case 1: ANN index stale after catalog ingest

- Control-plane decision: whether to serve the new item embedding index or last-known-good index.
- Data-plane symptom: new catalog items appear in search but never appear in recommendations.
- Invariant: tenant-eligible available items should receive exploration exposure within the agreed cold-start window.
- Falsifying metric: item_embedding_index_age_seconds and new_item_exposure_rate by tenant.
- Smallest boundary: one tenant, index version, and recommendation surface.
- Reject: rebuilding every tenant's index during peak without isolating the stale shard.

### Review Case 2: sponsored blend overwhelms organic ranking

- Control-plane decision: sponsored blend cap and auction eligibility policy.
- Data-plane symptom: home feed diversity drops and hide/report events rise while revenue per session rises.
- Invariant: paid placement cannot bypass trust, tenant catalog, inventory, or user-safety policy.
- Falsifying metric: sponsored_share_by_position plus hide/report rate by tenant and surface.
- Smallest boundary: cap sponsored candidates on the affected surface or tenant.
- Reject: turning off all recommendations when blend cap rollback is sufficient.

### Review Case 3: point-in-time leak in training

- Control-plane decision: approve or block a training dataset generated with a changed join.
- Data-plane symptom: offline AUC jumps but online conversion falls after deployment.
- Invariant: training rows must use only features available at the observation time.
- Falsifying metric: leakage audit count and online/offline feature distribution drift.
- Smallest boundary: block the model version and dataset lineage, not every recommender.
- Reject: shipping because offline metrics improved.

### Review Case 4: anonymous traffic spike

- Control-plane decision: switch anonymous users from personalized sources to regional trending and editorial fallbacks.
- Data-plane symptom: feature store misses rise because user_id is absent or cookie churn is high.
- Invariant: anonymous users must receive policy-safe, available items without cross-user leakage.
- Falsifying metric: anonymous cache hit rate, fallback share, and conversion by region.
- Smallest boundary: anonymous cohort on the affected surface.
- Reject: creating synthetic stable user IDs that violate privacy policy.

### Review Case 5: tenant whale overloads pair features

- Control-plane decision: allow or cap a tenant-specific pair-feature rollout.
- Data-plane symptom: online store p99 rises only for requests with large candidate sets.
- Invariant: one tenant's feature fanout cannot consume shared ranker and online-store budgets.
- Falsifying metric: feature lookups per request by tenant and pair_feature_default_rate.
- Smallest boundary: disable the pair feature for that tenant/model version.
- Reject: increasing global online-store capacity without capping fanout.

### Review Case 6: experiment assignment conflict

- Control-plane decision: whether session_id or user_id owns variant assignment.
- Data-plane symptom: logged-in users see both ranking variants across devices.
- Invariant: experiment exposure must be sticky at the chosen subject level.
- Falsifying metric: assignment_conflict_rate by experiment and subject type.
- Smallest boundary: freeze the experiment and stop new exposure while preserving logs.
- Reject: rebucketing everyone silently and continuing the same analysis.

### Review Case 7: trust feature gaming

- Control-plane decision: quarantine a seller cohort from trust-sensitive features.
- Data-plane symptom: new sellers dominate recommendations after review and click velocity spikes.
- Invariant: engagement signals cannot override seller trust and policy gates.
- Falsifying metric: conversion-after-click, review graph density, and ASN/device skew.
- Smallest boundary: affected seller cohort or feature view.
- Reject: deleting all behavioral history before forensic analysis.

### Review Case 8: fallback quality under source outage

- Control-plane decision: cut off a slow graph source at 20 ms and use co-visitation fallback.
- Data-plane symptom: recommendation p99 recovers but diversity drops.
- Invariant: fallback results still obey tenant, inventory, policy, and minimum diversity constraints.
- Falsifying metric: source_timeout_rate, diversity_score, and fallback_conversion by surface.
- Smallest boundary: graph source on the impacted surface.
- Reject: waiting for the graph source past the page latency SLO.
