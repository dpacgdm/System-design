# Answer Key - Retention Test SD Gaps

> Open only after attempting `Retention-Tests/Week-SD-Gaps.md`.

## Part 1: Rapid-fire model answers

**A01.** Inspect resolver/JVM DNS cache TTL such as `networkaddress.cache.ttl`, local caches, and persistent connection pools; bad fix is repeated DNS changes without client cache/drain plan.

**A02.** Use last-known-good endpoints for a bounded time by path, with endpoint identity/version checks, outlier ejection, jittered refresh, and fail-closed for auth/policy-critical routes.

**A03.** Fixed synchronized fallback polling/full catalog fetches amplified the registry leader stall.

**A04.** Readiness, not liveness, missed critical dependency capacity such as DB pools and worker queues.

**A05.** Check remote-zone spare capacity/headroom and cap spillover before shifting az-b demand.

**A06.** Short TTLs increase registry/DNS QPS and can synchronize refresh storms during brownout.

**A07.** Inspect EndpointSlices, pod readiness/termination timestamps, kube-proxy/eBPF sync, and connections to draining endpoints.

**A08.** Watch reconnects, watch lag, compaction index errors, full poll rate, and client cache age separate discovery from backend failure.

**A09.** DNS changes do not break existing TCP/HTTP connections; clients may keep using old endpoints until connection lifetime/drain expires.

**A10.** Use exponential backoff with full jitter, retry budgets, and circuit breaking around discovery refresh.

**A11.** Discovery finds endpoint sets and metadata; load balancing chooses among them. They overlap in health, weights, zone, and outlier policy.

**A12.** Ready endpoint count, endpoint cache age, watch lag/reconnects, registry p99, requests to unhealthy/draining endpoints, and zone route ratio.

**A13.** The ranker can only score candidates it receives; recall false negatives are invisible downstream.

**A14.** Conversion and tenant slice regressions are guardrail failures; stop or scope rollback despite CTR lift.

**A15.** Examples: co-visitation/popularity loop, collaborative/cold start, content/metadata spam, ANN/index freshness, trending/flash abuse, graph/fanout spam.

**A16.** The online Feature Store provides low-latency bounded-freshness feature vectors with owner/version/default semantics.

**A17.** Training-serving skew is a mismatch between offline training features and online serving features/defaults/freshness.

**A18.** Tenant/catalog/policy/region/experiment context is missing, causing cross-tenant leakage.

**A19.** Check ASN/IP/device/account age, conversion quality, referrer diversity, review graph, seller cohorts, and downstream outcomes.

**A20.** rankTopK multiplies model scoring and feature hydration work, so it directly controls p99 and unit cost.

**A21.** Use anonymous/cohort defaults for users, content/editorial exposure for items, isolated catalog priors for tenants, and regional trend priors for regions.

**A22.** Log requests, candidates, exposure, position, scores, feature versions, variants, non-clicks, and outcomes.

**A23.** Feature freshness, null rate, default rate, drift, online/offline skew, and materialization lag by model dependency.

**A24.** Search ranks explicit intent/query matches; recommendations infer personalized utility and must control exposure feedback loops.

**A25.** LLM serving optimizes token generation; agent workflows manage durable steps, tools, side effects, memory, approvals, evals, and audits.

**A26.** The orchestrator enforces state, schemas, auth, idempotency, budgets, retries, approvals, and kill switches.

**A27.** Random UUID makes each retry a new operation; external tools cannot deduplicate unknown-success attempts.

**A28.** Tool output is untrusted data/observation, never policy or instruction.

**A29.** Scope, tenant/user/project owner, provenance, TTL, sensitivity, version, validation time, and deletion policy.

**A30.** Mutating, money, email/bulk comms, cloud, data delete/update, support export, and high-blast-radius actions.

**A31.** High-risk timeout must fail closed/escalate; auto-approval turns queue backlog into side effects.

**A32.** Tool simulation, idempotency/retry, auth deny, prompt injection, memory isolation, cost loop, approval timeout, and connector canary evals.

**A33.** Roll out by tenant, tool, action type, workflow type, cell, and read-only versus mutating mode.

**A34.** Persisted operation keys prevent duplicate external effects across retries and worker crashes.

**A35.** Validate actor, tenant, audience, scopes, delegated purpose, resource policy, service identity, audit, and fail-closed behavior.

**A36.** Planner loops show calls/workflow, tool calls, aborts, cost/run, approval backlog; serving latency shows TTFT/ITL/GPU/KV metrics.

---

## Part 2: Compound Scenario A - Model Answer

Trigger: registry leader stall pauses watches.
Amplifiers: no-jitter 5s full polling, unlimited cross-zone spillover, az-c readiness flapping, stale endpoint caches.
Symptoms: checkout 5xx, registry p99, cache age, route ratio collapse.
First safe mitigation: emergency client config to restore jitter/backoff, cap full polls, extend bounded stale cache for safe paths, and cap cross-zone spillover by measured headroom.
Bad fixes: full cache flush, fleet restart, global DNS failover, or doubling callers.
Capacity: 35,000 / 5 = 7,000 polls/sec; 7,000 * 300 KB = 2,100,000 KB/sec ~= 2.1 GB/sec before overhead/retries.
Health: readiness should include local critical pool capacity but avoid over-deep checks; use brownout for optional features.
Tests: registry watch outage game day, jitter enforcement, poll quotas, zone spillover caps, drain behavior, and alerting on cache age/watch lag.

---

## Part 3: Compound Scenario B - Model Answer

Global CTR is unsafe because enterprise conversion and latency guardrails fail; CTR may represent clickbait or tenant leakage.
Mitigation: stop rollout for affected tenant/surface, restore tenant-safe cache key, reduce maxRawCandidates/rankTopK, tighten inventory freshness, cap slow ANN and use safe fallback, then analyze experiment logs.
Math: 18k * 300 = 5.4M candidate-scores/sec; 18k * 80 = 1.44M/sec; excess is 3.96M/sec plus features.
Feature checks: freshness, null/default rate, skew, version, online p99, materialization lag, and dependency graph for ranker.
Guardrails: conversion, latency, trust/hides, abuse, tenant slices, inventory complaints, cost, and error rate.
Tests: tenant cache isolation, cross-catalog denial, abuse click farm simulation, sponsored blend cap, and A/B sticky assignment.

---

## Part 4: Compound Scenario C - Model Answer

Trigger: support connector/planner rollout.
Amplifiers: random UUID idempotency, timeout auto-approve, missing tenant memory filter, high loop/tool budgets, missing side-effect evals.
First kill switch: pause mutating coupon/email/support connector actions for affected tenant and workflow class; keep read-only workflows if safe. Do not delete workflow state because it is needed for dedupe, repair, and audit.
Math: 3,600/min = 60 starts/sec; 60 * 24 = 1,440 model calls/sec at p95-shaped load.
Keys: email = tenant/run/step/recipient/template; coupon = tenant/customer/remediation campaign/approval id; CRM = tenant/account/field/action/step.
Timeout: fail closed or escalate, never approve high-risk actions automatically.
Auth/memory/evals: enforce delegated scopes and tenant filters, approval-bound diffs, prompt-injection/tool evals, idempotency tests, auth deny tests, cost loop tests.

---

## Part 5: Transfer Prompt Notes

Good answers compare stale discovery endpoints to stale recommendation features by invariant: availability may tolerate bounded stale routing, but policy/tenant/money/trust paths fail closed.
Good answers keep tenant context in discovery metadata, recommender cache keys, and agent memory retrieval.
Good answers reject global cache flushes, global recommender disablement without scoping, and global workflow deletion because all erase evidence or widen blast radius.

---

## Part 6: Mixed Short Scenario Notes

**S1.**
Do not lower TTL to 1 second during registry brownout; it increases synchronized refresh pressure.
Require exponential backoff with full jitter, bounded last-known-good cache, per-client registry budgets, and a cap on full catalog polls.
Freshness is useful only if the control plane can serve it.

**S2.**
If registry metadata affects service identity, stale records can become auth bugs.
Read-only low-risk paths may use last-known-good endpoints only while certificate identity still validates.
Mutating, tenant-sensitive, or identity-changing paths fail closed when identity metadata is stale or unverifiable.

**S3.**
Check feature materialization lag, null/default rates, stream checkpoint status, online/offline skew, feature version, and model dependency graph.
Do not roll back the model first if the binary is unchanged and feature freshness/nulls moved with conversion.

**S4.**
Statistical significance globally does not override guardrail failures.
Stop or scope rollback for the harmed tenant/surface, preserve experiment logs, and require trust/retention/tenant guardrails before shipping.

**S5.**
Missing dimensions include tenant_id, catalog_id, policy_version, region/locale, surface, experiment variant when relevant, and personalization context when cached.
Safest mitigation is disable or bypass that cache for affected tenant/surface and recheck tenant eligibility before response.

**S6.**
Use a deterministic key such as tenant + invoice_id + recipient + workflow_run + step_id or approved operation id.
After timeout, query provider status by that key before retrying; do not create a new operation id.

**S7.**
Memory needs environment, scope, provenance, TTL, validation time, sensitivity, and owner.
Policy must treat memory as evidence, not authority, and require production approval rules regardless of stale sandbox memory.

**S8.**
Investigate workflow orchestration, planner loops, tool deadlines, and connector retries first.
Healthy TTFT and modest GPU utilization argue against LLM serving as the primary bottleneck.

**S9.**
Auto-approval may be acceptable only for low-risk, reversible, preauthorized actions with exact bounded diffs.
Money, customer comms, deletes, production changes, data exports, and cross-tenant actions fail closed or escalate on timeout.

**S10.**
Discovery: disable a bad client-library config or cap one service/zone's registry polling.
Recommendations: disable one candidate source, model version, tenant/surface rollout, or sponsored blend.
Agents: pause one mutating tool/action for one tenant/workflow class.
Scoped switches preserve safe traffic and evidence while stopping the amplifier.

---

## Part 7: Deep Coverage for New Gap Topics

### G1. Service Discovery - principal answer shape

A strong answer begins by separating discovery-plane symptoms from data-plane symptoms.
Registry watch lag, leader churn, compaction errors, cache age, and full catalog QPS are discovery-plane signals.
Checkout 5xx, inventory latency, and requests to draining pods are downstream manifestations.
The timeline matters more than any single graph.
If watch lag and fallback polling rise before checkout errors, discovery amplification is probably causal.
If backend saturation rises first with stable registry load, discovery may only be a victim.

Safe sequencing:

1. freeze discovery-affecting deploys;
2. stop restart/cache-flush/DNS churn;
3. restore jitter and backoff;
4. cap full catalog polling;
5. use bounded last-known-good endpoints by path;
6. cap cross-zone spillover by measured headroom;
7. brown out optional dependencies;
8. repair readiness and drain semantics after load stabilizes.

Capacity math should be explicit.
Clients divided by fallback interval equals registry polls/sec.
Polls/sec times catalog payload equals control-plane bytes/sec.
Retries, TLS, serialization, and connection churn multiply that number.
A small fallback interval can therefore saturate a registry that normally handles only watch deltas.

Bad fixes:

- full cache flush;
- fleet restart;
- lower TTL during brownout;
- global DNS failover for service-to-service routing;
- deeper liveness checks for dependency failures;
- unlimited cross-zone routing;
- outlier ejection on one transient error;
- adding callers before fixing the shared control plane.

Durable fixes include jitter tests, registry quotas, emergency client config, snapshot caches, readiness templates, drain conformance tests, spillover budgets, and game days.
Org ownership should be named: platform owns client library and registry; service teams own readiness and safe stale policies; SRE owns runbooks and game days; security owns identity invariants for stale endpoints.

### G2. Trending Hashtags - principal answer shape

Trending is not just a top-N counter.
It is a ranking system under adversarial pressure, freshness constraints, regional context, and safety policy.
Telemetry should distinguish raw mention volume, unique-account velocity, identity diversity, graph spread, deletion/moderation rate, report rate, language/region mix, bot signals, and downstream engagement quality.
A principal answer notices when global trend growth hides a coordinated spike from new accounts, a small ASN set, or one geography.

Good sequencing during a bad trend incident:

1. freeze the new trend scorer or suspect source weights;
2. preserve raw event logs for trust review;
3. cap or remove the suspect hashtag from sensitive surfaces;
4. require unique-author and graph-diversity thresholds;
5. apply policy and safety classification before ranking;
6. fall back to regional/editorial safe lists if needed;
7. analyze whether counters, sketches, or stream jobs lagged or double-counted;
8. reintroduce with tighter source and cohort budgets.

Capacity details matter.
Trending pipelines commonly use stream aggregation, sketches, time windows, dedupe, and heavy-hitter algorithms.
If the system recomputes full windows for every request, read latency and cost explode.
If the stream processor lags, "fresh" trends may actually be stale.
If unique-user dedupe is too expensive and skipped, bot farms can dominate with cheap volume.

Bad fixes:

- ranking by raw count only;
- globally banning the word without understanding region and language;
- turning off moderation to reduce latency;
- relying only on report volume, which arrives late;
- using one global trend list for every market;
- deleting evidence before trust investigation;
- treating paid or coordinated promotion as organic velocity.

Durable gates should include abuse simulation, graph-diversity checks, policy prefilters, regional safety review, stream-lag alerts, counter backfill tests, and editorial override audit.
Ownership spans relevance, trust and safety, platform streaming, policy, regional product, and incident response.

### G3. Ad Platform - principal answer shape

An ad platform answer should separate auction correctness, pacing, budget safety, targeting privacy, ranking quality, billing, and reporting.
Telemetry is multi-ledger: request QPS, bid rate, win rate, clearing price, spend, budget remaining, pacing error, conversion attribution, policy rejects, latency, and revenue.
If revenue rises while advertiser ROI, conversion quality, or policy complaints degrade, the system may be extracting short-term spend through bad allocation.

Safe mitigation sequence:

1. pause the suspect bidder/model/rule for affected campaigns or exchanges;
2. cap spend and pacing while preserving serving for healthy campaigns;
3. verify budget ledgers and idempotency of billable events;
4. restore policy and privacy filters before auction;
5. compare click/conversion quality by advertiser, publisher, device, and traffic source;
6. reconcile impression, click, and billing logs;
7. notify account teams if budgets or billing may be wrong.

Capacity is shaped by fanout and deadlines.
Each ad request may query targeting, budget, frequency cap, policy, candidate retrieval, auction, pricing, and logging.
The bidder has a hard p99 budget because late bids are worthless.
Adding candidates can improve revenue but also increase tail latency and drop bids.
Budget ledgers need strong enough consistency to avoid overspend under concurrent auctions.
Reporting can be eventually consistent, but billing and spend caps cannot be hand-wavy.

Bad fixes:

- disable budget checks to improve fill;
- trust client-side click events without fraud controls;
- raise bids globally to recover revenue;
- aggregate all advertisers into one ROI metric;
- turn off policy classification to meet latency;
- retry billing events without idempotency;
- backfill reports in a way that changes invoices silently.

Durable fixes include auction replay tests, ledger reconciliation, idempotent billable-event keys, pacing simulations, fraud holdouts, privacy review, advertiser-slice guardrails, and kill switches by campaign, bidder, exchange, and creative class.
Org ownership includes ads ranking, marketplace economics, billing, privacy/legal, trust, data platform, and account management.

### G4. Ticketmaster / high-demand ticketing - principal answer shape

Ticketing systems are inventory, fairness, and payment systems under burst traffic.
The central invariant is that seats are not oversold and users are treated according to the published queue and hold policy.
Telemetry should include waiting-room entrants, queue assignment, bot scores, seat-map reads, hold creation, hold expiry, payment auth, checkout conversion, inventory version conflicts, and support complaints.
Average latency is nearly useless during an on-sale; p99, queue fairness, and inventory conflict rate are decisive.

Safe incident sequencing:

1. protect inventory writes and hold ledgers first;
2. keep the waiting room or queue in front of scarce paths;
3. shed seat-map refreshes or marketing pages before checkout;
4. extend holds only through a documented policy;
5. cap retries and require idempotent checkout attempts;
6. isolate bot-heavy cohorts or suspicious networks;
7. communicate status and policy clearly to users;
8. reconcile seats, payments, and confirmations before declaring recovery.

Capacity has multiple hot spots.
Seat maps are read-heavy but can stampede on a few events.
Hold creation is write-contended by section or seat.
Payment providers add external tail latency and unknown-success outcomes.
Queue tokens must be tamper-resistant and bound to user/session/event.
Inventory partitions should match contention patterns, not arbitrary IDs.

Bad fixes:

- bypass the queue for logged-in users during overload;
- cache seat availability without version checks for checkout;
- retry payment authorization with new operation ids;
- extend all holds indefinitely;
- disable bot checks to increase throughput;
- accept orders before inventory commit;
- manually edit seat inventory without reconciliation.

Durable fixes include waiting-room load tests, seat-hold state machines, idempotent order/payment keys, bot-defense drills, event-level capacity budgets, customer comms templates, and reconciliation jobs.
Ownership should include ticketing inventory, payments, anti-abuse, customer support, venue/partner operations, and SRE.

### G5. Flights / travel search - principal answer shape

Flights design is a freshness, pricing, search, and booking-consistency problem.
Search results can be cached and approximate; booking and payment must be validated against airline or GDS authority.
Telemetry should split search latency, cache hit rate, fare freshness, availability misses, booking failures, price-change rate, provider errors, and customer refund/support contacts.
A principal answer explicitly separates "shown fare" from "bookable fare."

Safe mitigation during stale or failing flight results:

1. mark stale providers or routes as degraded;
2. reduce cache TTL only if provider and cache capacity can support it;
3. add "price may change" UX when freshness is weak;
4. validate availability and fare at booking;
5. fall back to fewer providers or cached browse results for search;
6. preserve booking idempotency across payment/provider timeouts;
7. monitor route, airline, cabin, and region slices;
8. reconcile failed bookings and customer charges.

Capacity is fanout-driven.
A single user query can fan out by airline, route, dates, cabin, nearby airports, currency, and provider.
Tail latency from one provider should not block all results.
Caching needs keys that include origin, destination, dates, passengers, cabin, region, currency, and policy dimensions.
Prefetch and fare calendars can reduce load but risk stale recommendations.
Provider quotas are hard capacity constraints, not suggestions.

Bad fixes:

- treat cache hit rate as success when booking failures rise;
- bypass final fare validation to reduce checkout latency;
- lower TTL globally during provider outage;
- retry booking with a new payment/order id after unknown success;
- hide provider errors inside empty-result pages;
- mix currencies or passenger rules in cache keys;
- train ranking on stale fares as if they were available.

Durable gates include provider-contract tests, stale-fare guardrails, booking idempotency, payment reconciliation, route-slice dashboards, quota-aware fanout, cache-key audits, and degraded-mode UX review.
Ownership includes search/relevance, supplier integrations, payments, customer support, data platform, and SRE.

### G6. Recommendation Systems - principal answer shape

Recommendation incidents often combine model quality, serving infrastructure, marketplace trust, and experimentation.
A principal answer refuses to accept global CTR as the only metric.
It reads conversion, retention, hides, reports, latency, cost, inventory complaints, abuse, and tenant slices.
It also checks whether the model changed, the feature definitions changed, candidate sources changed, or cache keys changed.

Safe sequencing:

1. stop the harmful rollout or scope it by tenant/surface;
2. preserve assignments, exposures, scores, features, and source versions;
3. restore tenant-safe cache keys and policy gates;
4. reduce candidate fanout and rankTopK;
5. disable gamed or stale sources;
6. tighten inventory freshness for commerce;
7. use last-known-good or editorial fallback;
8. analyze only clean experiment windows.

Capacity math should multiply QPS by candidates scored, features hydrated, and model cost.
At 20k QPS and 250 ranked candidates, the system scores five million candidates per second before considering feature fanout.
Reducing rankTopK from 250 to 80 is not just a quality change; it can remove millions of scores per second.
Pair features and cross features deserve special review because they multiply by candidate count.

Bad fixes:

- ship because global CTR improved;
- rebucket users silently;
- add Feature Store capacity before bounding fanout;
- remove inventory or trust gates for latency;
- train on suspected abuse clicks;
- use item_id-only cache keys in multi-tenant catalogs;
- let sponsored ranking override policy.

Durable gates include offline eval, shadow launch, tenant isolation tests, feature skew checks, abuse simulation, candidate-source budgets, cost review, guardrail dashboards, and rollback drills.
Ownership includes relevance, Feature Store/platform, catalog, trust, tenant product, experimentation, and SRE.

### G7. Agentic Workflow Platforms - principal answer shape

Agentic workflow design should be evaluated as durable orchestration with controlled side effects.
The LLM is one component; the platform owns state, tool policy, idempotency, memory, approval, retries, budgets, evals, and audit.
Telemetry should split model serving from workflow behavior.
Healthy TTFT with exploding tool calls, approval backlog, duplicate emails, or coupon credits points to orchestration failure.

Safe sequencing:

1. pause mutating tools by tenant, connector, action class, or workflow type;
2. disable auto-approval for high-risk timeouts;
3. stop the new planner or connector rollout;
4. keep read-only paths if auth and memory isolation are safe;
5. freeze ambiguous retries;
6. group effects by deterministic intent;
7. reconcile external systems;
8. repair customer-visible harm through approved processes.

Capacity math should use workflow starts, model calls/workflow, tool calls/workflow, tokens, wall-clock duration, approval wait, and external-provider QPS.
Loops create multiplicative load even when user request volume is stable.
Budgets must be enforced by the orchestrator, not requested in the prompt.
Retries must classify errors into safe retry, unknown success, and non-retryable without inspection.

Bad fixes:

- add model capacity for tool loops;
- retry with random UUIDs;
- delete workflow logs;
- disable auth denies;
- auto-approve faster;
- let tool output change authorization;
- allow stale memory to override production policy;
- globally shut down read-only workflows when scoped mutating kill switches exist.

Durable gates include side-effect simulation, deterministic idempotency, status lookup for unknown success, approval-bound diffs, tenant memory isolation, prompt-injection tests, connector dry-run, loop detection, cost budgets, and audit completeness.
Ownership includes AI platform, security, connector owners, product policy, support/finance repair, and SRE.

### Cross-topic transfer patterns

The same interview instincts transfer across all seven modules.
First, identify the invariant: no unsafe routing, no cross-tenant leakage, no oversold seats, no duplicate money movement, no unauthorized tool action.
Second, read telemetry in layers rather than chasing the loudest graph.
Third, stop amplification before optimizing quality.
Fourth, prefer scoped kill switches over global shutdowns.
Fifth, preserve evidence for reconciliation and learning.
Sixth, distinguish stale-but-safe reads from stale correctness gates.
Seventh, name the owners who must make the durable fix real.

Examples:

- Discovery stale endpoints may be safe for catalog reads but unsafe for identity-changing writes.
- Flight search results may be stale for browsing but booking must revalidate.
- Recommendation behavioral features may be stale within TTL, but tenant policy cannot be stale.
- Ticket seat maps may be cached, but hold creation must be authoritative.
- Agent memory can inform, but approval and policy decide.
- Ad reports can lag, but spend caps and billing events need stronger guarantees.
- Trending counters can approximate volume, but safety filters must run before promotion.

Strong answers also reject vanity metrics.
CTR without conversion and trust is weak.
Revenue without advertiser ROI and billing correctness is weak.
Queue throughput without fairness and inventory correctness is weak.
Cache hit rate without booking success is weak.
Token latency without side-effect safety is weak.
Endpoint freshness without registry stability is weak.
Trend velocity without identity diversity is weak.
