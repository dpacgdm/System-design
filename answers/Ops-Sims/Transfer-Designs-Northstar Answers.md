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

## Principal model response

### Incident thesis

The designs transfer is about authority boundaries. Feed,
search, risk, config, docs, feature store, LLM, and GPU
serving are all derived or distributed views with different
freshness budgets. A principal answer does not ask "which
component is broken first?" It asks:

- which decisions are safety-critical;
- which data source is authoritative for each decision;
- which derived views are stale or split-brained;
- which surfaces can degrade without violating trust;
- which owners can re-enable each surface.

### Source-of-truth map

- Recalled item safety: product/recall database or a dedicated
  denylist, checked at read time.
- Feed/search visibility: derived indexes, never sufficient
  for recall enforcement by themselves.
- Checkout payment/risk: ledger and risk authority with
  freshness by transaction class.
- Kafka seller events: event log plus keying/bucketing
  contract.
- Config flags: monotonic versioned config with regional
  health and quorum/consistency rules for safety flags.
- Collaborative docs: operation log and transform/CRDT version
  compatibility.
- Feature store: online serving features with freshness and
  skew checks against offline training assumptions.
- LLM replies: policy registry and product price authority,
  not stale prompt cache.
- GPU serving: tenant scheduler and quota state.

### T+0 to T+15 sequence

1. Declare incident for safety-critical stale derived views.
2. Assign feed/search, catalog/recall, checkout risk, Kafka,
   config platform, docs/collab, ML/feature store, AI platform,
   GPU infra, support, and product owners.
3. Freeze alias flips, config force-enables, global cache
   purges, LLM policy changes, and risky replay.
4. Install read-time recall denylist in product pages, feed,
   search, and recommendations before relying on async
   tombstones.
5. Fail closed or step up high-value checkout when risk
   features are stale/missing.
6. Disable doc writes where transform versions differ; preserve
   op logs and snapshots.
7. Invalidate or bypass stale LLM prompt cache; source current
   price/policy from authority.
8. Enforce tenant GPU caps so one tenant cannot starve safety
   or production workloads.

### Telemetry and math

Feed/search:

- Measure recall denylist misses at read time, tombstone age,
  fanout lag, index alias version, and zero-result/error rate.
- A feed cache purge can create origin/fanout stampede; use a
  targeted denylist and cache-key invalidation for recalled
  SKUs first.

Kafka/config:

- If 54% of events share one `seller_id`, a seller-keyed topic
  can bottleneck one partition regardless of cluster size.
  Bucket hot sellers or split the workload while preserving
  ordering boundaries that matter.
- Config split-brain is proven by region/version mismatch and
  long client TTL. Safety flags need monotonic version checks,
  not "latest observed locally."

Docs:

- Transform version mismatch means two valid operations can
  merge incorrectly. Replay must use a validated version path,
  not old code for convenience.

Feature/LLM:

- Online/offline skew means training-time assumptions and
  serving decisions diverge. High-value risk decisions should
  require fresh online features or step-up.
- A 6h LLM prompt cache can quote stale price or old policy;
  disclaimers do not fix false claims.

GPU:

- Queue p99 by tenant and cap utilization by tenant are
  fairness signals. Adding GPUs without quotas preserves
  starvation if one tenant can consume all capacity.

### Bad-fix physics

- Disabling risk checks improves conversion by accepting fraud
  and chargeback risk.
- Global feed cache deletion can overload fanout and still miss
  recalled items if read-time safety is absent.
- Serving product pages from search index uses a derived stale
  source for safety and price.
- Forcing config flag true before alias readiness creates a
  regional split-brain.
- Replaying doc ops through older transform code can corrupt
  collaborative state permanently.
- LLM disclaimers do not prevent stale policy or price claims.
- More GPUs without tenant caps allows the same noisy neighbor
  to starve everyone.
- Random UUID partitioning breaks locality and ordering while
  hiding the hot-key model from operators.

### T+30 partial recovery criteria

Re-enable feed/search personalization only for categories
where:

- read-time recall denylist is enforced;
- tombstone lag and fanout lag are inside budget;
- index alias/version is consistent in all regions;
- cache TTL is bounded and targeted purge succeeded;
- recall miss rate is zero in canaries.

Re-enable checkout risk automation only when:

- high-value transactions have fresh features;
- missing features step up or fail closed;
- online/offline skew is below threshold;
- audit tags record stale-feature use for low-risk decisions.

Re-enable docs writes only when:

- transform versions converge;
- conflict queue is snapshotted and triaged;
- op replay passes deterministic test cases;
- user-facing conflict UX is ready for ambiguous merges.

Re-enable LLM replies only when:

- prompt cache is invalidated;
- current policy version is pinned;
- product price is sourced from authority with timestamp;
- tenant GPU caps are enforced.

### Durable architecture bar

- Every derived view has source-of-truth, freshness budget,
  bypass path, owner, and alert.
- Safety filters execute at read time, not only during async
  indexing.
- Index/alias rollout gates require doc count parity, query
  canaries, and rollback test.
- Kafka hot-key review includes top-N producer dimensions,
  bucket strategy, and ordering contract.
- Config store supports monotonic versions, regional health,
  override expiry, and safety-flag consistency.
- Collaboration service versions transformation protocols and
  blocks incompatible writes.
- Feature store enforces skew and freshness by decision class.
- LLM context carries source, timestamp, policy version, and
  invalidation reason.
- Tenant fairness applies to compute, queues, GPUs, and human
  support/runbook attention.

### What to say in the design review

The design passes only if each team can answer: "What happens
when my derived view is stale?" Feed/search should say recall
denylist at read time. Risk should say fail closed by
transaction class. Config should say monotonic version and
regional health gate. Docs should say block incompatible
transform writes. LLM should say authoritative retrieval and
policy pinning. GPU should say tenant caps. Anything else is a
latent incident, not a launch plan.
