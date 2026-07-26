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

## Principal Depth Addendum - What Great Answers Notice

### Telemetry interpretation

1. Compare global CTR with tenant-level CTR, conversion, hides, refunds, and support contacts.
2. Break latency down into retrieval, feature hydration, ranking, blending, policy, cache, and logging.
3. Overlay the ranker rollout with candidate-source config changes.
4. Inspect whether ANN recall, sponsored blend, or trending source changed at the same time.
5. Compare feature freshness and null/default rates for ranker-v42 dependencies.
6. Check response cache hit rate and key cardinality by tenant and surface.
7. Verify experiment assignment stability for logged-in users across sessions and devices.
8. Inspect exposure logs for position distribution, model score distribution, and source mix.
9. Compare click velocity with downstream add-to-cart, purchase, return, and report rates.
10. Read guardrails by tenant, catalog, seller cohort, device, region, and traffic source.

The important diagnosis is that "ranker rollout" does not mean "model bug."
The model can be fine while the serving contract around it is unsafe.
Here the incident combines capacity fanout, tenant cache-key leakage, stale inventory, and abuse exposure.
A principal answer treats ranking quality, correctness, and cost as one serving system.

### Mitigation sequencing

1. Stop or scope the rollout before more users are exposed.
2. Preserve logs, assignments, and feature snapshots for analysis.
3. Restore tenant-safe cache keys or bypass the unsafe cache for affected surfaces.
4. Enforce tenant/catalog/policy eligibility before candidate generation and before response.
5. Reduce maxRawCandidates and rankTopK to last-known-good values.
6. Cap or disable the suspicious source, such as gamed trending or sponsored blend.
7. Tighten inventory freshness and remove unavailable items from commerce surfaces.
8. Fall back to known-safe tenant-curated, editorial, or prior model responses.
9. Recompute dashboards using clean exposure windows and tenant slices.
10. Reopen rollout only after gates pass in shadow/canary mode.

This order protects correctness first, then relieves load, then restores quality.
Adding feature-store capacity before lowering unbounded fanout is a temporary subsidy for a bad configuration.
Continuing the test because CTR is higher teaches the experiment platform to reward harm.

### Bad fixes and hidden regressions

- Optimizing for global CTR can ship clickbait, leakage, or abuse.
- Disabling all personalization globally may damage healthy tenants and hide the faulty source.
- Flushing every recommendation cache without fixing key dimensions can recreate the leak immediately.
- Rebucketing users silently corrupts experiment analysis.
- Raising source deadlines steals time from ranking and policy gates.
- Removing inventory checks improves latency while recommending unavailable products.
- Removing abuse checks lets adversarial clicks become training data.
- Training a larger model cannot recover candidates that recall never produced.
- Increasing ANN replicas does not fix cache isolation or stale policy.
- Treating enterprise impact as an "edge segment" violates tenant contracts.

### Candidate-source design depth

Candidate sources should be owned products with budgets and contracts.
Co-visitation supplies item-to-item relevance and reacts to recent behavior.
Collaborative filtering supplies personalized recall but needs cold-start fallbacks.
Content embeddings supply semantic recall and new-item coverage.
Editorial or tenant-curated lists provide safe fallback and contractual control.
Trending supplies freshness but needs abuse resistance and regional/tenant scoping.
Sponsored candidates are eligible only after policy, inventory, and trust checks.

Each source needs:

- a max candidate count;
- a per-source deadline;
- freshness target and index version;
- dedupe key;
- tenant/catalog eligibility contract;
- owner and rollback switch;
- metrics for yield, quality, cost, and abuse.

Ranking should never be asked to clean up an unlimited candidate firehose.
Filtering illegal or unavailable items after ranking is useful defense-in-depth, not the primary gate.

### Feature Store contract

The Feature Store is not just a low-latency key-value cache.
It is the contract between training, serving, ownership, and observability.
Feature definitions need version, owner, TTL, default behavior, point-in-time offline join, online materialization path, and deprecation plan.
Pairwise features need special scrutiny because their cost is candidates times feature count.
Critical policy and inventory features should often be treated as gates outside the model.

Feature alarms should page on:

- materialization lag above the model's tolerance;
- null/default rate jumps;
- offline/online skew;
- schema or enum drift;
- p99 hydration latency;
- missing tenant dimension;
- feature values that move without upstream business explanation.

### Experiment and learning integrity

Exposure logs must include every item shown and every item withheld by filters when feasible.
They should record model version, feature versions, source versions, policy version, cache status, position, score, variant, and request context.
Non-clicks matter because ranking learns from impressions, not only clicks.
Assignment should use the stable subject for the decision: user for personalization, tenant for tenant-wide policy, item or seller for marketplace interventions when interference is expected.

When guardrails fail, stop the harmful path and mark the experiment.
Do not delete assignments.
Do not relabel variants.
Do not blend post-stop traffic into the original effect estimate.
Trustworthy experimentation is an operational safety mechanism, not only an analytics method.

### Durable release gates

1. Offline eval against holdout, tenant slices, cold-start slices, and abuse-heavy slices.
2. Feature freshness/skew review for every model dependency.
3. Candidate-source load test at p99 fanout and p999 traffic bursts.
4. Tenant isolation tests for retrieval, cache, features, logs, and training export.
5. Inventory and policy correctness tests under stale catalog updates.
6. Abuse simulation for click farms, seller metadata churn, and sponsored bid spikes.
7. Shadow launch with exposure logging but no user-visible ranking changes.
8. Canary by tenant, surface, region, and traffic percentage.
9. Predeclared rollback/fallback for each source and ranker version.
10. Cost review by source, model, tenant, and feature class.

### Organizational model

Relevance owns candidate and ranking quality.
Marketplace or trust owns abuse and seller integrity.
Catalog owns availability and policy correctness.
Platform owns Feature Store, serving latency, caches, and experiment infrastructure.
Tenant-facing product owns contractual slices and enterprise rollout decisions.
SRE owns capacity, alerts, and kill-switch drills.

A mature organization makes those boundaries explicit before launch.
Otherwise, every recommender incident becomes an argument about whether it was "model quality," "infra," or "business policy."
The correct answer is usually that the serving contract allowed those concerns to become inseparable at runtime.
