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

## Principal Depth Addendum - Workflow Safety Review

### Reading the incident telemetry

1. Start with side effects: duplicate emails, coupon credits, CRM status changes, and tenant complaints.
2. Compare workflow starts/min with tool calls/workflow and model calls/workflow.
3. Check whether TTFT, ITL, GPU utilization, and provider errors changed.
4. Overlay planner prompt version, connector version, policy version, and approval config.
5. Inspect repeated observations, repeated tool arguments, and loop termination reasons.
6. Group external effects by deterministic business intent, not by random operation id.
7. Compare approval queue depth with timeout behavior and auto-approval count.
8. Review auth denies by tenant, resource, scope, and connector action.
9. Sample memory retrieval traces for missing tenant filters or stale provenance.
10. Preserve raw traces while restricting access to sensitive prompt/tool data.

The principal diagnosis is that this is a workflow control-plane incident.
Healthy token serving does not make a tool side effect safe.
The harmful work appears after planning, retry, approval, memory, and connector policy interact.
That boundary matters because adding LLM capacity would let the platform perform bad actions faster.

### Mitigation sequencing

1. Pause mutating CRM, coupon, and email actions for affected tenants and workflow types.
2. Disable approval timeout auto-approve for all high-risk action classes.
3. Stop rollout of the new planner prompt and CRM connector.
4. Keep read-only summarization if tenant isolation and auth checks remain safe.
5. Freeze retries for unknown-success operations until status is reconciled.
6. Export workflow runs, external operation ids, approvals, and tool arguments for dedupe.
7. Query external systems by deterministic intent where possible.
8. Repair customer-visible effects through approved finance/support processes.
9. Notify tenant owners with scoped facts and expected remediation.
10. Resume with synthetic tenants, low budgets, and dry-run mode first.

This order stops new harm while preserving evidence.
Deleting workflow state may make dashboards quieter, but it destroys the only map for deduplication and customer repair.

### Bad fixes and why they are unsafe

- Increasing model-serving capacity increases the rate of unsafe loops.
- Retrying with new UUIDs guarantees duplicate external operations.
- Disabling auth denies converts a safety system into an availability hack.
- Auto-approving faster hides approval backlog by creating side effects.
- Deleting traces prevents idempotency grouping and audit reconstruction.
- Global shutdown of read-only workflows may hurt customers without reducing mutating risk.
- Making prompts more polite does not enforce tool policy.
- Trusting tool output to authorize the next tool call creates prompt-injection escalation.
- Allowing memory to override policy lets stale or cross-tenant context become authority.
- Treating connector success as workflow success ignores read-after-write verification.

### Idempotency and retry design

Mutating steps need an operation identity that represents business intent.
It must survive worker crashes, model retries, queue redelivery, and provider timeouts.
Random UUIDs are useful for trace uniqueness, not for side-effect dedupe.

Good idempotency keys include:

- tenant or account boundary;
- stable workflow run and step id;
- target resource;
- action type;
- approved change request or exact diff hash;
- recipient or customer when communication or money is involved;
- connector version when provider semantics differ.

Unknown success should follow a status-lookup path.
If the provider lacks idempotency and status lookup, the step should become non-retryable pending human inspection.
The workflow engine must distinguish retryable transport errors from ambiguous side-effect errors.

### Approval contract

Approval is not a boolean flag on a tool.
It is a signed decision over exact actor, tenant, resource, action, arguments, risk reason, expiry, and idempotency key.
Changing the email body, coupon amount, CRM field, recipient set, or evidence should invalidate approval.
High-risk timeout fails closed or escalates to another queue.
Low-risk preauthorized actions may use policy-based auto-approval only when reversible, bounded, and audited.

Approvers need to see:

- customer or tenant impact;
- exact before/after diff;
- model/tool trace summary;
- source evidence and confidence;
- policy reason requiring approval;
- rollback or repair plan;
- duplicate-detection key;
- links to previous related actions.

### Memory and tool-output boundaries

Memory is evidence with provenance, not command authority.
Tool output is untrusted observation, even when it came from an internal connector.
Prompt assembly must enforce tenant, user, project, resource, sensitivity, TTL, and deletion filters before the model sees context.
Secrets should be represented by vault references and redacted from traces.
Stale sandbox memory must not authorize production changes.
Cross-tenant retrieval attempts are severity-one isolation incidents, even if a later API layer blocks the write.

### Evals that would have caught this

1. Planner loop eval with repeated observations and no new state.
2. Retry eval where provider times out after committing a side effect.
3. Approval timeout eval for high-risk actions.
4. Tenant memory isolation eval with similar customer names across tenants.
5. Auth deny eval for missing delegated purpose and wrong tenant.
6. Prompt-injection eval embedded in CRM notes or email replies.
7. Connector dry-run eval that compares proposed diff with policy.
8. Cost regression eval for max model/tool calls per workflow.
9. Canary eval using synthetic tenants and fake external providers.
10. Audit completeness eval for actor, tenant, resource, approval, and idempotency fields.

### Durable platform fixes

1. Separate read-only, reversible, and irreversible tool tiers.
2. Require deterministic idempotency for every mutating connector before production.
3. Add per-tenant, per-workflow, per-tool, and per-action budgets.
4. Make loop detection a runtime invariant, not only a prompt instruction.
5. Add action-class kill switches independent of model-serving controls.
6. Store approval-bound diffs and reject argument drift.
7. Enforce tenant filters in the retrieval layer and test deny cases continuously.
8. Run new connectors in shadow/dry-run mode before live mutation.
9. Add reconciliation jobs for ambiguous provider timeouts.
10. Page on side-effect rate, duplicate intent, approval auto-close, and tool-call explosion.

### Organizational ownership

AI platform owns orchestration, planner rollout, eval gates, memory retrieval, and workflow budgets.
Security owns tool authorization, delegated scopes, tenant isolation, and audit requirements.
Connector owners own provider semantics, idempotency support, dry-run behavior, and rollback.
Product owns which actions are allowed, reversible, or approval-required.
Support and finance own customer repair for duplicate credits or communications.
SRE owns incident command, kill-switch drills, and capacity alarms.

The operating principle is simple: the model proposes, the platform disposes.
If a prompt change can bypass idempotency, approval, or tenant policy, those controls were never controls.
