# Answer Key - Design LLM Serving Platform

> Open only after attempting the learner file questions.

This key is written for principal/staff-level self-review.
A passing answer should name the irreversible decisions, trust boundaries, highest-amplification actors, unit economics, and smallest safe blast-radius boundary.
It should also say what to turn off first during an incident without corrupting the correctness-critical path.

## Principal Model Answer - What Excellent Looks Like

1. Separates prefill and decode scheduling.
2. Budgets KV cache explicitly.
3. Routes by model, prompt length, adapter, SLA, and data policy.
4. Defines token-based quotas and billing.
5. Provides fallback under GPU saturation without breaking isolation.

## Ops Sim / Incident Model Answer

### Latency spike diagnosis

1. TTFT p99 at 4s with GPU util 98% and queue depth 2000 indicates admission/scheduling saturation.
2. Prefix caching v3.1 is suspicious because cache key bugs can create wrong hits, extra validation, or KV block leaks.
3. Split metrics by model, tenant, prompt length, SLA tier, and cache hit/miss/error.
4. Check whether traffic shifted toward long prompts; prefill-heavy traffic raises TTFT even if decode ITL is stable.
5. Check KV cache fragmentation/leak and eviction/preemption rate after deploy.

### Mitigation

1. Disable prefix caching v3.1 by model/pool first, not globally if canary scope exists.
2. Shed or queue free-tier long-context traffic and preserve premium TTFT lanes.
3. Cap max prompt/max output temporarily for overloaded shared pools.
4. Scale GPU replicas only after confirming model weights/cache warmup will not worsen queueing.
5. Drain affected scheduler shard and route new requests to healthy pools.

### Prevention

1. Prefix cache keys include tenant, model, adapter, system prompt/version, safety policy, and tokenizer version.
2. Canary cache changes with shadow correctness checks, not only latency checks.
3. Admission control on total tokens and KV blocks.
4. Separate prefill and decode metrics in SLOs.
5. Game day with long-prompt traffic shift and cache-disabled fallback.

---

## Design Gates (mandatory) - Principal-Depth Model Responses

### Gate 1 - Authn/z trust boundary

1. Principal inventory: API customers, end users through apps, tenant admins, model router, GPU workers, scheduler, safety filters, billing service, model registry, support/admin actors
2. First untrusted boundary: inference API gateway before router/scheduler
3. Final authorization decision: API gateway and model entitlement policy by tenant/model/SLA/tool permissions
4. Accepted identity artifacts: API key/OAuth token, tenant-scoped model entitlement, workload identity for GPU services, signed model artifact identity, admin break-glass token
5. Service-to-service trust: mTLS/SPIFFE workload identity plus short-lived service tokens
6. Public clients never choose tenant/user/object IDs without server-side policy checks.
7. Admin/support access requires break-glass approval, reason codes, scoped duration, and immutable audit logs.
8. Background workers carry job identity and original actor context where user intent matters.
9. Capability or signed URL tokens are scoped to one object, operation, expiry, and content hash where applicable.
10. Identity or policy outage behavior: inference for unauthorized models/tools fails closed; paid dedicated tenants do not spill into lower isolation pools; safe cached responses only where product allows
11. Read-only degraded mode is acceptable only for explicitly public or previously authorized cached data.
12. Writes, deletes, money movement, admin actions, and privacy-sensitive reads fail closed.
13. Audit events include actor, subject, tenant/context, decision, policy version, request ID, and source IP/device.
14. Cross-region failover preserves auth state; it never bypasses policy to restore availability.
15. A good answer draws this trust boundary before drawing caches, queues, or databases.
16. Model summary: Authorization covers model, adapter, context window, tools, data policy, and SLA tier; routing is a policy decision.

### Gate 2 - Abuse and misuse

1. Highest amplification actor: long prompts and high max_tokens requests consuming KV cache/GPU decode slots, plus prefix-cache bugs poisoning many tenants
2. Authenticated abuse surfaces: prompt floods, long-context requests, streaming retries, tool calls, batch jobs, LoRA adapter uploads, prefix-cache keys, model downloads
3. Quota dimensions: per-tenant tokens/min, concurrent sequences, prompt length, max output tokens, KV cache blocks, tool calls, model tier, region/GPU pool, global prefill budget
4. Global safety caps are separate from per-principal quotas so one bug cannot consume the fleet.
5. Entity-key limits protect hot keys even when all callers are legitimate.
6. Worker concurrency limits protect downstream stores from replay storms and fan-out storms.
7. Retry budgets are finite, jittered, and tied to user intent or idempotency keys.
8. Retry hazard: clients reconnecting streaming generations and resubmitting long prompts while scheduler queue is saturated
9. Telemetry separating flash crowd from abuse: TTFT/ITL by model/tier, queue depth, KV cache usage, prefill/decode mix, prefix cache hit/error, tokens/sec/GPU, eviction/preemption, safety/tool errors
10. Organic spikes preserve normal identity diversity; attacks show skewed principals, IPs, clients, or entities.
11. Abuse controls emit allow/deny/throttle decisions into a stream suitable for forensics.
12. Degradation sheds optional work before it rejects correctness-critical operations.
13. Runbooks say when to pause producers, disable retries, or drop optional enrichments.
14. A good answer includes both prevention and incident-time containment.
15. A weak answer only says add rate limiting without keys, budgets, or kill switches.
16. Model summary: Token budgets and KV cache budgets are the real rate limits; request count alone is meaningless.

### Gate 3 - Multi-tenant isolation

1. Tenancy model: tenant/SLA tier, model, adapter/LoRA, GPU pool, region, data policy, billing account
2. Tenant/context propagation: tenant_id, model_id, adapter_id, SLA tier, prompt token count, safety policy, request_id, and billing meter in router, scheduler, cache, logs, and traces
3. Shared resource reservations: dedicated GPU pools for premium, shared pool quotas, KV cache block budgets, batch job lanes, model download bandwidth, safety filter capacity
4. Every cache key, queue message, object prefix, metric label, and support export carries tenant/context explicitly.
5. Missing tenant/context is a policy error, not a default-to-global behavior.
6. Async jobs include context in the payload and in the worker authorization decision.
7. Support tools filter by tenant/context server-side and log the exact export scope.
8. Noisy-neighbor control: disable one model version, one tenant, one adapter, prefix cache for one model, tool calls, or a shared pool admission lane
9. Large tenants or hot entities can be isolated into dedicated shards/cells/topics without global migration.
10. Backfills and replays run in tenant-scoped lanes with byte and concurrency budgets.
11. Observability cardinality is bounded so one tenant cannot bankrupt metrics ingestion.
12. Isolation test: tenant A prompt/KV/prefix cache/tool output cannot be read or reused by tenant B through cache, logs, billing, or support replay
13. Disaster recovery restores tenant boundaries, not only bytes.
14. A good answer names logical isolation and physical capacity isolation.
15. A weak answer says tenant_id column and stops there.
16. Model summary: Tenant and model/SLA tier are isolation boundaries; prefix cache and adapters are high-risk cross-tenant surfaces.

### Gate 4 - Unit cost at target scale

1. Business unit: one generated output token or request by model/SLA tier
2. Rough unit-cost model: GPU seconds per input/output token plus idle headroom; long prompts have large prefill cost and long outputs consume decode memory bandwidth
3. Dominant line items: H100/A100 GPU hours, idle reservations, model replicas, KV cache memory, EFA/network, model storage/load time, safety/tool calls, observability traces
4. Include replication, idle headroom, cross-AZ/region transfer, observability, and replay capacity.
5. Separate fixed control-plane cost from variable data-plane cost.
6. Track p50 and p99 cost because tail work often drives autoscaling and queue depth.
7. Chargeback/showback attributes cost by tenant/context, feature, endpoint, and deploy version.
8. Cost alert before margin/SLO breach: gross margin per 1,000 tokens by model/tier and GPU utilization at p99 TTFT/ITL
9. Capacity planning includes event-day peak multiplier, not only daily average.
10. Cost regressions need rollback criteria just like latency regressions.
11. Graceful cost reduction: shorten max_tokens for free tier, disable batch jobs, reduce context window, turn off prefix cache, route to smaller model, queue low-tier tenants; never mix tenant data to save cache
12. Never reduce cost by weakening correctness, auth, audit, or durability guarantees.
13. Cold storage, compaction, tiering, sampling, and caching are explicit levers with owners.
14. A good answer can defend an order-of-magnitude number on a whiteboard.
15. A weak answer lists cloud products without pricing the business unit.
16. Model summary: GPU memory and decode bandwidth dominate; batching improves cost only until TTFT/ITL SLOs break.

### Gate 5 - Failure blast radius

1. Smallest intended failure boundary: tenant, model version, GPU pool, scheduler shard, prefix-cache namespace, region
2. Shared dependencies between critical and optional paths: GPU pool, router, model registry, prefix cache, safety filters, billing, tool gateway
3. Fail closed: unauthorized model/tool access, tenant data isolation, admin changes, safety policy errors for high-risk tools
4. Serve stale or degraded: model availability page, cached safe completions only by explicit product policy, billing dashboard lag
5. Disable first: prefix cache v3.1, batch/offline jobs, free-tier long context, optional tools, lower-priority tenants, speculative decoding
6. Runbook hazard that widens blast radius: globally increasing batch size, disabling safety filters, allowing premium overflow into shared pool without isolation, or flushing model cache during peak
7. Bulkheads separate user-facing serving from analytics, backfill, replay, and support tooling.
8. Feature flags are scoped by cell/region/tenant/entity, with a global kill only for known-safe toggles.
9. Queues have dead-letter and replay throttles; replay is never unbounded during recovery.
10. Caches have namespace-level invalidation; global flushes require incident commander approval.
11. Autoscaling must not scale a bad retry loop faster than dependencies can absorb it.
12. Game day: prefix-cache deploy causes TTFT p99 4s, GPU util 98%, queue 2000, with diagnosis separating cache bug from traffic mix shift
13. Alerts fire on leading indicators inside the boundary before customers see platform-wide impact.
14. A good answer says what remains working when one shard/cell/topic fails.
15. A weak answer treats multi-region replication as a substitute for blast-radius design.
16. Model summary: A bad model/cache/scheduler decision is scoped to one model or pool and never leaks prompts across tenants.

---

## Evaluator Rubric and Red Flags

1. Names the core correctness invariant for multi-tenant LLM serving platform: a request is served only by an entitled model/policy and tenant data in prompts, KV cache, logs, and tools never crosses tenant boundaries
2. Quantifies the dominant scale driver instead of hand-waving capacity.
3. Explains why the fast path is safe under retry, failover, and partial dependency failure.
4. Shows the data lifecycle: hot serving, durable source of truth, compaction/tiering, and replay/repair.
5. Draws control plane and data plane separately where that separation matters.
6. Documents idempotency, deduplication, and ordering where duplicates or loss are unacceptable.
7. Includes observability tied to user impact, not only host metrics.
8. Provides a mitigation order that stops customer pain before root-cause cleanup.
9. States what is intentionally out of scope for V1 and why it is safe to defer.
10. Mentions cost and abuse as first-class design constraints.
11. Uses scoped kill switches rather than global toggles for unknown failure modes.
12. Protects support/admin paths with the same rigor as user-facing APIs.
13. Proves tenant/context isolation through tests and operational controls.
14. Connects incident symptoms to plausible root causes and rejects red herrings.
15. Leaves the system reconciled after rollback; rollback alone is rarely repair.

Common red flags:

1. Treating caches, queues, or CDN as the source of truth when multi-tenant LLM serving platform needs durable reconciliation.
2. Using average QPS when hot keys, celebrities, tenants, regions, prompts, or cells drive the p99.
3. Assuming authenticated users cannot be abusive.
4. Letting background jobs share unlimited capacity with user-serving paths.
5. Failing open on auth, payment, privacy, admin, or data-integrity paths.
6. Global cache flushes, unthrottled replays, or emergency shard changes during peak traffic.
7. No plan for stale data, duplicate events, delayed callbacks, or partial writes.
8. No explicit owner for policy, schema, quota, and configuration changes.
9. No evidence that the design was tested under the exact incident shape.
10. No cost metric at the same granularity as the scaling decision.

Minimum pass bar:

1. Can explain the happy path in under two minutes.
2. Can explain the top three failure modes in under two minutes.
3. Can state the primary data invariant without naming a cloud product.
4. Can point to the exact gate that catches the incident before production.
5. Can say which customer-visible feature is sacrificed first during overload.
6. Can say which action is never allowed during mitigation because it risks data loss or privacy breach.
7. Can produce one line of capacity math for the dominant workload.
8. Can name one blast-radius boundary and one game day that validates it.

---

## Additional Verification Checklist

1. Verify dashboards expose user-impact SLOs for multi-tenant LLM serving platform.
2. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
3. Verify the runbook has a rollback step and a separate reconciliation step.
4. Verify each queue or stream has bounded retry and dead-letter handling.
5. Verify every emergency command is scoped to the smallest safe boundary.
6. Verify post-incident cleanup drains backlog without violating customer promises.
7. Verify schema/config changes cannot bypass review or automated policy checks.
8. Verify tenant/context labels are present in logs without leaking secrets or PII.
9. Verify load tests include skewed traffic, not only uniform distributions.
10. Verify cost dashboards break down the business unit by feature and tenant/context.
11. Verify dashboards expose user-impact SLOs for multi-tenant LLM serving platform.
12. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
13. Verify the runbook has a rollback step and a separate reconciliation step.
14. Verify each queue or stream has bounded retry and dead-letter handling.
15. Verify every emergency command is scoped to the smallest safe boundary.
16. Verify post-incident cleanup drains backlog without violating customer promises.
17. Verify schema/config changes cannot bypass review or automated policy checks.
18. Verify tenant/context labels are present in logs without leaking secrets or PII.
19. Verify load tests include skewed traffic, not only uniform distributions.
20. Verify cost dashboards break down the business unit by feature and tenant/context.
21. Verify dashboards expose user-impact SLOs for multi-tenant LLM serving platform.
22. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
23. Verify the runbook has a rollback step and a separate reconciliation step.
24. Verify each queue or stream has bounded retry and dead-letter handling.
25. Verify every emergency command is scoped to the smallest safe boundary.
26. Verify post-incident cleanup drains backlog without violating customer promises.
27. Verify schema/config changes cannot bypass review or automated policy checks.
28. Verify tenant/context labels are present in logs without leaking secrets or PII.
29. Verify load tests include skewed traffic, not only uniform distributions.
30. Verify cost dashboards break down the business unit by feature and tenant/context.
31. Verify dashboards expose user-impact SLOs for multi-tenant LLM serving platform.
32. Verify canaries exercise auth, quota, cache miss, dependency failure, and replay paths.
33. Verify the runbook has a rollback step and a separate reconciliation step.
34. Verify each queue or stream has bounded retry and dead-letter handling.
35. Verify every emergency command is scoped to the smallest safe boundary.
36. Verify post-incident cleanup drains backlog without violating customer promises.


---
