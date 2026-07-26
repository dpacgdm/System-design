# Answer Key - Design Recommendation System

> Open only after attempting `Week-14-Collaboration-and-AI-Designs/Design Recommendation System.md`.

## Principal Model Answer

A strong design separates recall, ranking, policy, experimentation, and logging.
It treats the Feature Store as the contract for reusable features, but still distinguishes freshness-critical catalog/policy signals from eventually consistent behavior signals.
It rejects global CTR as the only success metric and includes tenant slices, conversion, trust, latency, abuse, and cost guardrails.

## Ops Sim Model Answer

### Trigger and amplifiers

- Trigger: ranker-v42 rollout plus broader candidate/ranking configuration change.
- Amplifier: maxRawCandidates 2000 and rankTopK 250 overload ANN, feature hydration, and ranker.
- Amplifier: inventory freshness of 10 minutes allows unavailable or stale items into recommendations.
- Amplifier: tenant cache key missing tenant/catalog/policy leaks or mixes eligibility.
- Amplifier: click velocity cap disabled lets gaming signals inflate new sellers.
- Amplifier: session-based experiment key creates logged-in assignment conflicts.

### Why global CTR is misleading

Global CTR rises while checkout conversion and enterprise tenant CTR fall.
That pattern suggests clickbait, sponsored overexposure, tenant harm, or irrelevant traffic rather than useful recommendations.
The rollout should be judged by predeclared guardrails: conversion, refunds, hides, dwell quality, latency, trust reports, and tenant slices.

### Suspicious config

- `perSourceDeadlineMs: 60` consumes too much of a 150 ms p99 when sources run plus feature hydration/ranking.
- `maxRawCandidates: 2000` and `rankTopK: 250` multiply downstream cost.
- `inventoryFreshnessMaxAge: 10m` violates trust for commerce availability.
- `assignmentKey: session_id` is not sticky for logged-in users across devices/sessions.
- `cacheKey: surface:item_id` omits tenant, catalog, region, policy, and experiment context.
- missing conversion/trust/tenant guardrails lets global CTR drive unsafe rollout.

### Capacity math

At 20k QPS and rankTopK 250: 5,000,000 candidate-scores/sec.
At rankTopK 80: 1,600,000 candidate-scores/sec.
The change adds 3.4M candidate-scores/sec plus feature values and model cost, explaining p99 feature/ranker pressure.

### First mitigation order

1. Stop rollout at current percentage or roll affected tenant/surface back to last-known-good ranker.
2. Restore tenant-safe cache key and enforce tenant catalog policy before retrieval and after ranking.
3. Cap sponsored blend and disable/cap the suspected gamed new-seller source.
4. Tighten inventory freshness for commerce surfaces and fallback stale inventory to safe items only.
5. Reduce rankTopK/maxRawCandidates to previous known-good values to relieve p99.

### Preserve A/B validity

Mark the experiment as stopped for safety with reason code, keep assignment logs, avoid silently rebucketing users, and analyze only clean pre-stop windows.
Do not continue harmful exposure for statistical purity.

### Feature Store checks

Check feature freshness, null rate, default usage, online/offline skew, materialization lag, model dependency graph, and feature version changes for ranker-v42.
Inventory and tenant policy are correctness gates, not optional stale features.

### Abuse versus organic trend

Compare click velocity by ASN/IP/device/account age/referrer, conversion after click, add-to-cart, returns, review graph, seller cohort, and tenant slice.
Organic trends show broader identity diversity and downstream conversion; abuse shows skewed sources and weak downstream quality.

### Correct cache key

Use tenant_id, catalog_id, surface, region/locale, policy_version, experiment_id/variant when response differs, user/cohort for personalized caches, and item_id only inside tenant-scoped item caches.

### Safe fallback

For affected enterprise tenant: last-known-good model, tenant-curated/trending available items, strict inventory freshness, no cross-tenant candidates, sponsored blend capped or disabled, and exposure logging preserved.

### Bad fixes to reject

- Continue rollout because global CTR is up.
- Disable all personalization globally instead of scoping by tenant/surface/source.
- Raise feature store capacity without reducing rankTopK/source fanout.
- Flush all caches without fixing tenant key dimensions.
- Remove abuse checks to reduce latency.
- Rebucket experiment users silently.

### Future gates

Every future ranker must pass offline evaluation, shadow traffic, tenant-isolation tests, feature freshness/skew checks, abuse simulation, p99 load test with candidate fanout, cost estimate, guardrail dashboard review, and rollback/fallback drill.

---

## Design Gates - Model Responses

### Gate 1 - Candidate generation

- A strong answer lists at least four sources and explains why each exists: co-visitation for item-to-item relevance, collaborative filtering for personalization, content/embedding ANN for semantic recall and cold items, trending/editorial for anonymous fallback, and sponsored only after trust/policy checks.
- Each source has a deadline, max candidates, source version, owner, and fallback behavior.
- Candidate sources run in parallel with cutoffs; slow sources return partial/empty results rather than consume the whole page budget.
- Dedupe, tenant eligibility, policy, inventory, and already-purchased filters run before ranking.
- A weak answer sends all candidates from all sources to ranking synchronously with no max fanout.

### Gate 2 - Ranking and features

- A strong answer separates request, user, item, pair, context, policy, and experiment features.
- Online serving features reference the Feature Store registry where possible, including owner, TTL, version, default semantics, null monitoring, and point-in-time offline retrieval.
- Critical catalog/policy features have much tighter freshness requirements than behavioral aggregates.
- Pair features are admitted only after capacity review because they multiply by candidate count.
- Missing-feature defaults are model-owned and monitored; silent zero-fill is a red flag.

### Gate 3 - Feedback and experimentation

- A strong answer defines primary objective and guardrails before launch: CTR, conversion, retention, hide/report, latency, trust, tenant slices, cost, and abuse.
- Exposure logging includes shown candidates, positions, scores, model version, feature versions, experiment variant, and non-click outcomes.
- Assignment is sticky at the chosen subject level; logged-in users should not bounce variants by session.
- Popularity and position bias are addressed with exploration, debiasing features, counterfactual logs, or holdouts.
- Harmful guardrail movement stops or scopes the experiment even if global CTR wins.

### Gate 4 - Abuse and gaming

- A strong answer treats authenticated sellers and tenants as possible adversaries.
- It monitors click velocity, identity diversity, conversion-after-click, review graph shape, inventory stuffing, title/metadata churn, bid spikes, and ASN/device skew.
- Abuse limits are scoped by seller, tenant, item, feature view, and candidate source.
- Trust and policy gates are not overridden by engagement or sponsored value.
- Forensics preserve raw logs; global deletion of behavioral history is a red flag.

### Gate 5 - Multi-tenant catalogs

- Tenant context appears in retrieval, candidate caches, feature keys, ranking policy, experiment assignment, logs, training data, and support tools.
- Cache keys include tenant_id, catalog_id, surface, region/locale, policy_version, and experiment/personalization dimensions when they affect response.
- Eligibility is checked before ranking to avoid scoring illegal candidates and after ranking to catch bugs.
- Large tenants get capacity budgets or physical isolation for candidate sources and online features.
- Cross-tenant leakage is a severity-one privacy/contract incident, not a quality bug.

### Gate 6 - Latency and cost

- A strong answer budgets p99 across auth/context, candidate fanout, filtering, feature hydration, ranking, blending, and logging.
- It computes unit cost per 1,000 recommendation responses and attributes it by tenant, surface, source, and model version.
- It degrades by cutting optional sources, lowering rankTopK, using last-known-good safe fallbacks, and preserving policy/inventory gates.
- It rejects adding capacity as the only response to unbounded candidate fanout.
- It monitors p99 and p999 because tail fanout drives user-visible latency and autoscaling cost.
