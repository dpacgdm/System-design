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
