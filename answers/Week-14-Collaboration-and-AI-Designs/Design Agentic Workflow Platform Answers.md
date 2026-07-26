# Answer Key - Design Agentic Workflow Platform

> Open only after attempting `Week-14-Collaboration-and-AI-Designs/Design Agentic Workflow Platform.md`.

## Principal Model Answer

A strong answer treats the platform as a durable workflow and side-effect control plane.
It keeps LLM serving concerns separate from orchestration, tool authorization, idempotency, memory, human approval, evals, and blast-radius management.
The model may suggest actions, but deterministic platform components enforce every irreversible decision.

## Ops Sim Model Answer

### Trigger and amplifiers

- Trigger: new planner prompt plus CRM connector rollout.
- Amplifier: maxIterations 40 and stopOnRepeatedObservation false create planner loops.
- Amplifier: retry_all_timeouts with random UUID idempotency keys duplicates side effects.
- Amplifier: no approval for CRM credits/status changes and approval timeout auto-approves.
- Amplifier: tenantFilterRequired false allows cross-tenant retrieval attempts, even if downstream blocks some.
- Amplifier: missing tool side-effect/auth evals lets connector reach production untested.

### First safe mitigation

Pause the new CRM connector and send_email mutating actions for affected tenants/workflow types, disable timeout auto-approve, stop planner-2026-07-26 rollout, and keep read-only summarization if safe.
Do not disable audit logging or delete workflow state.

### Unsafe config

- `maxIterations: 40`: too high without loop detection.
- `stopOnRepeatedObservation: false`: permits repeated tool/model loops.
- `retry_all_timeouts`: retries unknown side effects without status lookup.
- `idempotencyKey: random_uuid`: each retry looks like a new operation.
- `requiresApproval: false`: unsafe for credits/status changes.
- `onTimeout: approve`: converts approval backlog into automatic side effects.
- `tenantFilterRequired: false`: memory isolation bug.
- high tool/cost budgets: lets loops become expensive incidents.
- eval suite missing side-effect, auth, memory, and adversarial tests.

### Capacity math

4,100 starts/min ~= 68.3 starts/sec.
At p95 27 model calls/workflow, p95-shaped load is about 1,845 model calls/sec.
This is a workflow loop/cost incident even if raw LLM serving GPUs are healthy.

### Idempotency

Random UUID breaks idempotency because retries produce new keys, so the external system cannot identify duplicate intent.
Email key should be tenant + workflow_run + step_id + recipient + template/purpose.
CRM update key should be tenant + customer/account + field/action + workflow step or approved change request.
Coupon key should be tenant + customer + campaign/remediation id + approval id.

### Approval timeout

High-risk actions should fail closed or remain waiting/escalate on timeout, never auto-approve.
Approval must bind to exact diff, resource, actor, tenant, idempotency key, and expiry.

### Actions requiring approval

Coupon credits, CRM status changes with customer impact, bulk emails, cloud changes, data mutations, deletes, and any cross-tenant/support export require approval.
Approver sees diff, blast radius, policy reason, source evidence, rollback/repair plan, and audit record.

### Repair

Quarantine affected workflow runs, export idempotency groups, query external tools by deterministic intent where possible, dedupe emails in customer comms, reverse unauthorized coupons through approved financial/customer process, and notify tenant owners.
Preserve raw audit logs with restricted access for forensics.

### Serving versus workflow

The symptoms are tool calls/workflow, idempotency misses, approval queue, duplicate side effects, and planner loops.
Those point to orchestration/tool policy, not token latency, KV cache, batching, or GPU capacity from the LLM Serving Platform module.

### Week 08b checks

Validate actor, tenant, audience, scopes, delegated purpose, resource policy, service identity, support/admin break-glass, audit fields, and fail-closed behavior for mutating tools.
Tool credentials must be short-lived and least-privilege, not broad user sessions blindly replayed by the agent.

### Missing evals

Tool side-effect simulation, retry/idempotency evals, approval timeout evals, prompt-injection via tool output, memory tenant isolation, authz deny cases, loop detection, cost budget regression, and connector canary/shadow tests.

### Bad fixes to reject

- Increase model-serving capacity to solve planner loops.
- Delete workflow logs to stop retries.
- Disable all auth denies to make workflows complete.
- Auto-approve approvals faster.
- Retry failed CRM updates with new UUIDs.
- Global shutdown of all read-only workflows if scoped mutating tool pause suffices.

### Future blast-radius boundaries

Roll out connectors by tenant, tool, action class, workflow type, and cell.
Separate read-only from mutating tools; require per-action kill switches; enforce low initial budgets; canary with synthetic tenants; and keep approval fail-closed.

---

## Design Gates - Model Responses

### Gate 1 - Serving versus workflow boundary

- LLM serving owns token latency, batching, model routing, KV cache, and provider availability.
- Workflow orchestration owns durable state, step transitions, tool policy, retries, idempotency, approval, memory, and audit.
- A model provider swap should not change which tools are allowed or how side effects dedupe.
- Healthy TTFT with exploding tool calls/workflow points to orchestration/planner failure, not GPU serving.
- First useful progress SLO is separate from workflow completion latency.

### Gate 2 - Tool auth and policy

- Every tool call identifies actor, tenant, resource, action, delegated purpose, risk tier, and workflow id.
- Credentials are short-lived, least-privilege, scoped to tool/action/resource, and auditable.
- Week 08b checks apply: issuer, audience, scopes, tenant, service identity, break-glass, and fail-closed behavior for sensitive paths.
- Tool output cannot expand authorization; only policy can.
- Policy outage fails closed for writes, deletes, money, external comms, admin/support export, and privacy-sensitive reads.

### Gate 3 - Idempotency and side effects

- Mutating tools require deterministic idempotency keys tied to user intent or approved operation, not random retry ids.
- Unknown success is resolved with external status lookup before retry.
- Some actions are non-retryable without human inspection if the external system has no idempotency support.
- Completion requires verification such as read-after-write, provider operation status, or signed result.
- Duplicate-safe design is required before enabling retries.

### Gate 4 - Memory and context

- Memory is scoped by tenant, user, project, workflow, or task and includes provenance, TTL, sensitivity, owner, version, and validation time.
- Retrieval enforces ACL and tenant filters before prompt assembly.
- Tool observations are untrusted data and prompt injection is tested explicitly.
- Secrets are redacted or stored as vault references; raw prompt/tool logs have restricted access.
- Stale memory cannot override current policy or approval requirements.

### Gate 5 - Human-in-loop

- Approval is required for high-risk mutations: money, deletes, external customer comms, production infra, support exports, and broad data changes.
- The approver sees exact diff, actor, resource, tenant, risk reason, model/tool trace summary, idempotency key, rollback/repair plan, and expiry.
- Approval binds to that exact action; changing args invalidates it.
- Timeout fails closed or escalates for high-risk actions.
- Approval volume and clarity are monitored to prevent rubber-stamping.

### Gate 6 - Evals and release

- Required evals include prompt golden cases, tool schema validation, side-effect simulation, idempotency retry cases, auth deny cases, memory isolation, prompt injection, cost loops, and approval timeout behavior.
- New tools run in dry-run or shadow mode before mutating production.
- Eval results are tied to prompt version, model version, connector version, and policy version.
- Regression gates block rollout when tool accuracy, safety, cost, or latency exceeds thresholds.
- Production canaries use synthetic tenants and low budgets before real tenants.

### Gate 7 - Cost, latency, and blast radius

- Budgets cap model calls, tool calls, tokens, wall-clock duration, approval wait, and spend per workflow and tenant.
- Isolation dimensions include tenant, workflow type, connector, action class, cell, and read-only versus mutating mode.
- Kill switches exist for one tool action, one connector, one prompt version, one tenant, or one workflow class.
- Degradation preserves read-only summaries where safe while pausing mutating side effects.
- A bad connector should not reach every tenant before one canary and one eval suite catch it.
