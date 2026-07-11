# Answer Key - Transfer Designs Northstar

> Open only after attempting the transfer drill.

## Q1 - Domain inventory

Failures map to feed fanout lag, search/index alias inconsistency, recalled-item tombstone lag, payment/risk feature freshness, Kafka hot partition by seller, config-store regional split-brain, collaborative editor transform mismatch, feature-store online/offline skew, LLM stale prompt/policy context, and GPU tenant starvation.

## Q2 - Safety first

Fail closed or degrade recalled/policy items, high-value checkout risk, and document writes that cannot merge safely. Feed ranking, personalization, AI replies, and noncritical recommendations can degrade to chronological/static/safe templates. Search can serve with recall filter from source-of-truth denylist even if ranking is stale.

## Q3 - Feed/search consistency

Introduce a high-priority recall denylist checked at read time by feed/search/product pages, independent of lagging derived indexes. Shorten or bypass feed cache for recalled SKUs, enable pull-on-read fallback for celebrity sellers, prioritize tombstones, and ensure aliases point consistently before enabling flags.

## Q4 - Payment risk

Risk features need class-based freshness. High-value or high-risk transactions require fresh features or manual/retry; missing/stale should fail closed or step-up auth, not allow. Low-value low-risk transactions may use bounded-stale features with limits and audit tags.

## Q5 - Kafka/config

Keying by `seller_id` sends a top seller to one partition, so 54% of events can bottleneck one partition. Add subkey/bucket for hot sellers or split topics. Config split-brain comes from regional stale watches and long client TTL without monotonic version enforcement. Use versioned configs, quorum reads for safety flags, expiring overrides, and readiness checks for index aliases.

## Q6 - Collaborative docs

Stop accepting writes where transform versions differ. Preserve operation logs, snapshot affected docs, replay through one validated transform version in a staging/reconciliation path, and expose conflict resolution to sellers when automatic merge is unsafe. Never replay all ops through an older service without compatibility proof.

## Q7 - Feature store/LLM

Online/offline skew means training/serving assumptions diverge; risk decisions become inconsistent. LLM prompt cache using search index with 6h TTL quotes stale prices and old policy. Require online/offline skew checks, source price from product authority or freshness-bounded service, policy version pinning with rollout gates, and per-tenant GPU caps.

## Q8 - Bad fixes

Disable risk checks: allows fraud/chargebacks. Global feed cache delete: stampedes fanout and origin; targeted denylist/cache purge is safer. Product pages from search index: derived stale source; use product DB/source of truth. Force flag true: unsafe if v43 alias not ready everywhere. Old doc transform replay: corrupts ops. LLM disclaimer: does not fix unsafe/stale claims. More GPU no caps: one tenant keeps starving others. Random UUID partitioning breaks ordering/locality; use deliberate bucketing.

## Q9 - T+60 partial recovery

Re-enable personalization only for categories with recall denylist enforced, index age within budget, consistent config version, and rollback owner present. Re-enable LLM replies only with current policy, fresh price source, prompt cache invalidated, and tenant caps. Re-enable doc writes after transform version convergence and conflict queue drain/reconciliation plan.

## Q10 - Durable architecture

Feed: hybrid fanout with pull fallback and recall denylist. Search: alias readiness gates, high-priority tombstones, shard-key review. Risk: freshness contracts and fail-closed tiers. Config: monotonic versioned flags with regional health. Docs: CRDT/OT version compatibility gates. Feature store: online/offline skew monitoring. LLM: source-of-truth retrieval, policy pinning, cache invalidation, per-tenant quotas. Org: named owners for each derived view and safety gate.

## Q11 - Principal decision record

Source of truth: product/recall DB for item safety, ledger/risk authority for checkout, doc operation log for collaboration, policy registry for LLM safety. Derived views: feed/search/feature store/LLM context with explicit freshness budgets. Rollback owners: search/feed lead for recall visibility, risk lead for checkout decisions, docs lead for merge safety, AI platform for LLM. Any derived view beyond freshness budget must be bypassed or labeled non-authoritative.



## Recovery gates and rollback owners

| Area | Re-enable gate | Rollback owner |
|------|----------------|----------------|
| Feed personalization | recall denylist enforced at read time; fanout lag inside budget; cache TTL reduced | Feed lead |
| Search ranking | alias consistency verified; tombstones prioritized; hot shard below SLO | Search lead |
| Checkout risk | feature freshness by transaction class; missing features fail closed for high value | Risk lead |
| Config flags | monotonic version observed in all regions; override has expiry | Platform config owner |
| Seller docs | transform versions converged; conflict queue triaged; op log snapshotted | Collaboration lead |
| LLM replies | current policy loaded; prompt cache invalidated; price source authoritative | AI platform lead |
| GPU serving | tenant caps enforced; queue p99 inside SLO | AI infra lead |

## Design-review prevention checklist

- Every derived view names its source of truth and freshness budget.
- Safety filters are read-time gates, not only asynchronous index updates.
- High-cardinality or hot-key dimensions have bucketing plans before launch.
- Config flags that affect safety use versioned, monotonic rollout with regional health.
- LLM context includes source, timestamp, policy version, and invalidation path.
- Tenant fairness is enforced for both compute tokens and human support/runbook attention.
