# Design Agentic Workflow Platform

An agentic workflow platform runs LLM-backed agents that plan, call tools, observe results, update state, and sometimes ask humans for approval.
It is not the same system as an LLM serving platform.
LLM serving focuses on low-latency token generation, batching, model routing, and GPU economics; agent workflows focus on orchestration, tool side effects, memory, approvals, evals, and blast-radius control.

---

## 1. Learning Objectives

After this module, you will be able to:

1. Design a platform for tool-calling agents with durable workflow state, idempotent side effects, and bounded autonomy.
2. Separate planner, orchestrator, executor, tool gateway, memory store, eval service, and human approval surfaces.
3. Explain why tool calls need authn/z, scoped credentials, audit logs, and policy gates (see `Week-08b-Trust-Cost-Multi-Tenancy/AuthN AuthZ OAuth mTLS and Secrets.md`).
4. Control cost and latency across multi-step agent loops, model calls, tool calls, retries, and human waits.
5. Design memory that improves workflows without leaking secrets, cross-tenant data, or stale instructions.
6. Build evals and guardrails for task success, tool correctness, safety, regression, and operational quality.
7. Run an incident response for a bad tool or planner bug that could create real-world side effects.

---

## 2. Wrong Mental Models

### Mental model 1: Agent platform equals chat UI

Correction: Chat is only one interface. The platform is a durable workflow engine around LLM calls, tools, memory, approval, and audit.

### Mental model 2: The planner should directly call tools

Correction: Direct side effects from model output are unsafe. A deterministic orchestrator/tool gateway must validate schema, auth, idempotency, policy, and budgets.

### Mental model 3: Memory is always helpful

Correction: Memory can store stale instructions, secrets, tenant data, or false conclusions. It needs scope, TTL, provenance, and deletion.

### Mental model 4: Retries are harmless

Correction: Retrying a tool that sends email, refunds money, or changes infrastructure can duplicate side effects unless idempotency and operation keys exist.

### Mental model 5: Human-in-loop is a button

Correction: Approvals require context, diff, risk score, timeout behavior, escalation, audit, and revocation.

### Mental model 6: Evals are just prompt tests

Correction: Agent evals need tool traces, side-effect simulation, regression suites, cost/latency budgets, and adversarial cases.

### Mental model 7: Bad tools are rare edge cases

Correction: A permissive tool can turn a model mistake into data deletion, spend, spam, privacy breach, or production outage.

### Mental model 8: Auth to tools can reuse the user's session blindly

Correction: The platform must enforce delegated scopes, tenant boundaries, purpose limits, and audit separate from the model's text.

---

## 3. Requirements and Constraints

### Functional requirements

- Accept workflow requests through API, UI, schedule, event, or webhook.
- Let agents use approved tools such as ticketing, email, calendar, code search, database query, cloud APIs, CRM, and internal runbooks.
- Support planner-based agents, fixed DAG workflows, and hybrid workflows where the planner chooses among bounded steps.
- Persist every step, model call, tool call, observation, approval, and final artifact.
- Provide memory with tenant, user, project, workflow, and task scopes.
- Require human approval for high-risk operations.
- Run evals before tool or prompt changes reach production.
- Attribute cost by tenant, workflow type, model, tool, and actor.

### Non-functional requirements

- Workflow state is durable and resumable after process failure.
- Tool side effects are idempotent or explicitly non-retryable.
- Tool credentials are short-lived, scoped, auditable, and revocable.
- p95 interactive workflows should show first useful progress within 2 seconds; long workflows stream status and checkpoints.
- Platform must cap loop count, token budget, tool budget, wall-clock time, and spend per workflow.
- Tenant isolation applies to prompts, memory, tool outputs, logs, traces, eval datasets, and support views.

### Abuse and safety constraints

- Users can prompt agents to exfiltrate data or bypass policy.
- Tool outputs can contain prompt injection or malicious links.
- A compromised connector can lie about actions taken.
- A benign planner bug can call an expensive tool in a loop.
- Human approvers can be fatigued by vague or excessive approval requests.
- Logs can leak secrets if raw prompts/tool outputs are stored without redaction and access control.

---

## 4. Critical Paths

### 4.1 Workflow submission path

```text
request -> authn/z -> tenant/workspace policy -> workflow admission
        -> initial memory retrieval -> planner/model call -> proposed plan
        -> orchestrator validates plan -> step queue -> tool gateway
        -> observation -> state update -> next step or approval -> final artifact
```

The orchestrator owns state transitions.
The planner proposes next actions, but the orchestrator decides whether an action is allowed, already done, too expensive, too risky, or waiting for approval.

### 4.2 Orchestration versus planner

Planner responsibilities:

- decompose the user goal into candidate steps
- choose among allowed tools based on observations
- summarize uncertainty and ask for missing inputs
- propose when a human should approve

Orchestrator responsibilities:

- persist workflow state and step transitions
- enforce max iterations, budgets, deadlines, and tool policies
- validate tool schemas and arguments
- supply idempotency keys and retry policy
- route approval requests
- emit audit logs and metrics
- stop or quarantine unsafe workflows

A planner bug should produce a rejected step, not a production side effect.

### 4.3 Tool call path

```text
planner proposes {tool, args, reason}
  -> schema validation
  -> policy check: actor, tenant, resource, action, risk
  -> idempotency key allocation
  -> dry-run or read-before-write when available
  -> human approval if risk threshold crossed
  -> tool execution through connector
  -> result verification and observation sanitization
  -> durable step completion
```

Tool results are untrusted input to the next model call.
A page body, ticket comment, email, or database value can contain prompt injection telling the agent to ignore policy.
The platform must mark tool outputs as data, not instructions.

### 4.4 Memory path

Memory types:

- Ephemeral scratchpad: current workflow reasoning or state, not exposed as durable truth.
- Task memory: facts collected during one workflow run.
- Project memory: preferences and runbook facts scoped to a workspace/project.
- User memory: user preferences with consent and deletion.
- Tenant memory: approved organizational facts and policies.
- Retrieval corpus: documents indexed with ACLs and provenance.

Memory rules:

- every memory item has scope, owner, provenance, creation time, last validation time, TTL, and sensitivity label
- memories are retrieved only after auth and tenant filtering
- high-risk instructions cannot be written to memory without review
- tool observations with secrets are redacted or stored in secret-aware vault references
- stale memory is evidence, not instruction

### 4.5 Human-in-loop path

Human approval should include:

- proposed action and resource diff
- actor and delegated authority
- tenant/workspace and customer impact
- risk classification
- idempotency key and rollback plan
- model/tool trace summary
- timeout behavior
- escalation owner
- immutable audit entry

### 4.6 Idempotent Side Effects

#### Tool side effect: `send_email`

- Idempotency key: message_id or campaign operation key.
- Duplicate risk: duplicate email/spam.
- Retry policy: retry only transport/5xx unknowns when the external tool supports idempotency lookup.
- Verification: read-after-write or external status query before marking complete.
- Human approval: required when blast radius crosses policy threshold.

#### Tool side effect: `create_ticket`

- Idempotency key: external_id from workflow step.
- Duplicate risk: duplicate support tickets.
- Retry policy: retry only transport/5xx unknowns when the external tool supports idempotency lookup.
- Verification: read-after-write or external status query before marking complete.
- Human approval: required when blast radius crosses policy threshold.

#### Tool side effect: `refund_payment`

- Idempotency key: payment provider idempotency key.
- Duplicate risk: duplicate money movement.
- Retry policy: retry only transport/5xx unknowns when the external tool supports idempotency lookup.
- Verification: read-after-write or external status query before marking complete.
- Human approval: required when blast radius crosses policy threshold.

#### Tool side effect: `run_sql_update`

- Idempotency key: migration/change request id.
- Duplicate risk: duplicate data mutation.
- Retry policy: retry only transport/5xx unknowns when the external tool supports idempotency lookup.
- Verification: read-after-write or external status query before marking complete.
- Human approval: required when blast radius crosses policy threshold.

#### Tool side effect: `cloud_scale_change`

- Idempotency key: change ticket and desired state version.
- Duplicate risk: oscillation or cost spike.
- Retry policy: retry only transport/5xx unknowns when the external tool supports idempotency lookup.
- Verification: read-after-write or external status query before marking complete.
- Human approval: required when blast radius crosses policy threshold.

#### Tool side effect: `post_chat_message`

- Idempotency key: channel + workflow step id.
- Duplicate risk: spam and confusion.
- Retry policy: retry only transport/5xx unknowns when the external tool supports idempotency lookup.
- Verification: read-after-write or external status query before marking complete.
- Human approval: required when blast radius crosses policy threshold.

#### Tool side effect: `merge_code`

- Idempotency key: commit SHA + approval id.
- Duplicate risk: wrong code deployed.
- Retry policy: retry only transport/5xx unknowns when the external tool supports idempotency lookup.
- Verification: read-after-write or external status query before marking complete.
- Human approval: required when blast radius crosses policy threshold.

#### Tool side effect: `delete_object`

- Idempotency key: object version + approval id.
- Duplicate risk: irreversible data loss.
- Retry policy: retry only transport/5xx unknowns when the external tool supports idempotency lookup.
- Verification: read-after-write or external status query before marking complete.
- Human approval: required when blast radius crosses policy threshold.

---

## 5. Data Model and Capacity Math

### 5.1 Core entities

```text
WorkflowRun(run_id, tenant_id, actor_id, goal, status, risk, budget, created_at, updated_at)
WorkflowStep(step_id, run_id, type, status, attempt, idempotency_key, started_at, completed_at)
ModelCall(call_id, run_id, step_id, model, prompt_hash, input_tokens, output_tokens, latency_ms, cost)
ToolCall(tool_call_id, run_id, step_id, tool, args_hash, auth_context, idempotency_key, status)
Observation(observation_id, step_id, source, sanitized_payload_ref, sensitivity, created_at)
Approval(approval_id, step_id, approver, decision, reason, expires_at, audit_ref)
MemoryItem(memory_id, scope, subject, content_ref, provenance, ttl, sensitivity, version)
EvalRun(eval_id, suite, prompt_version, tool_version, result, regressions)
```

### 5.2 State machine

```text
created -> admitted -> planning -> waiting_for_tool -> waiting_for_approval
        -> executing_tool -> observing -> completed
        -> failed_retryable -> failed_terminal -> cancelled -> quarantined
```

State transitions are compare-and-swap updates by run_id and step_id.
A worker crash after tool execution but before state update must be repaired by idempotency lookup, not by blind re-execution.

### 5.3 Capacity worksheet

Assume:

- 5,000 workflow starts per minute at peak
- average 7 model calls per workflow
- average 4 tool calls per workflow
- p95 model call latency 1.2 seconds
- p95 tool call latency 800 ms
- 20% workflows require one human approval with median wait 12 minutes
- average 6,000 input tokens and 900 output tokens per workflow

Derived checks:

```text
workflow starts/sec = 5,000 / 60 ~= 83/sec
model calls/sec = 83 * 7 ~= 581/sec
tool calls/sec = 83 * 4 ~= 332/sec
approval backlog at steady state = 83/sec * 20% * 12m * 60 ~= 11,952 waiting approvals
input tokens/min = 5,000 * 6,000 = 30,000,000
output tokens/min = 5,000 * 900 = 4,500,000
```

Approval queues and tool connectors may dominate platform capacity even when model serving has spare tokens/sec.

### 5.4 Cost and latency budget

Interactive budget example:

| Stage | Budget | Control |
|---|---:|---|
| Admission/auth/context | 100 ms | local policy cache with fail-closed writes |
| Initial memory retrieval | 250 ms | top-k and ACL-filtered vector search |
| Planner first model call | 1,200 ms | small/fast model where safe |
| Tool schema/policy check | 100 ms | deterministic gateway |
| First safe tool/read call | 500 ms | timeout and fallback |
| Stream status to user | 2,000 ms | first visible progress target |

Long-running workflows need progress SLOs rather than only completion latency.
Cost budgets should cap max model calls, max tokens, max tool calls, and max wall-clock time per workflow and tenant.

---

## 6. Failure and Abuse Catalog

### Failure 1: Planner loop

- Trigger: model keeps asking for more tools.
- Amplifier: no iteration budget.
- Blast radius: cost spike and tool overload.
- Evidence: inspect run trace, step state, idempotency key, auth decision, tool result, and budget counters.
- Safer mitigation: pause the smallest workflow/tool/tenant slice and preserve audit state for replay or repair.

### Failure 2: Duplicate side effect

- Trigger: worker retries after timeout.
- Amplifier: no idempotency lookup.
- Blast radius: duplicate email/refund/ticket.
- Evidence: inspect run trace, step state, idempotency key, auth decision, tool result, and budget counters.
- Safer mitigation: pause the smallest workflow/tool/tenant slice and preserve audit state for replay or repair.

### Failure 3: Prompt injection via tool output

- Trigger: web page says ignore policy.
- Amplifier: tool output treated as instruction.
- Blast radius: data exfiltration or unsafe action.
- Evidence: inspect run trace, step state, idempotency key, auth decision, tool result, and budget counters.
- Safer mitigation: pause the smallest workflow/tool/tenant slice and preserve audit state for replay or repair.

### Failure 4: Memory leak across tenants

- Trigger: retrieval filter missing tenant.
- Amplifier: shared vector index.
- Blast radius: privacy breach.
- Evidence: inspect run trace, step state, idempotency key, auth decision, tool result, and budget counters.
- Safer mitigation: pause the smallest workflow/tool/tenant slice and preserve audit state for replay or repair.

### Failure 5: Stale memory

- Trigger: old runbook fact retrieved.
- Amplifier: no TTL/provenance.
- Blast radius: wrong remediation.
- Evidence: inspect run trace, step state, idempotency key, auth decision, tool result, and budget counters.
- Safer mitigation: pause the smallest workflow/tool/tenant slice and preserve audit state for replay or repair.

### Failure 6: Approval fatigue

- Trigger: too many vague approvals.
- Amplifier: human rubber-stamps.
- Blast radius: unsafe change approved.
- Evidence: inspect run trace, step state, idempotency key, auth decision, tool result, and budget counters.
- Safer mitigation: pause the smallest workflow/tool/tenant slice and preserve audit state for replay or repair.

### Failure 7: Connector credential over-scope

- Trigger: tool token has admin rights.
- Amplifier: agent chooses broad action.
- Blast radius: large blast radius.
- Evidence: inspect run trace, step state, idempotency key, auth decision, tool result, and budget counters.
- Safer mitigation: pause the smallest workflow/tool/tenant slice and preserve audit state for replay or repair.

### Failure 8: Eval blind spot

- Trigger: prompt passes golden tests.
- Amplifier: no tool side-effect simulation.
- Blast radius: production-only regression.
- Evidence: inspect run trace, step state, idempotency key, auth decision, tool result, and budget counters.
- Safer mitigation: pause the smallest workflow/tool/tenant slice and preserve audit state for replay or repair.

### Failure 9: Tool result spoofing

- Trigger: connector returns success incorrectly.
- Amplifier: no verification.
- Blast radius: workflow completes falsely.
- Evidence: inspect run trace, step state, idempotency key, auth decision, tool result, and budget counters.
- Safer mitigation: pause the smallest workflow/tool/tenant slice and preserve audit state for replay or repair.

### Failure 10: Cost runaway

- Trigger: expensive model used for every step.
- Amplifier: no per-run budget.
- Blast radius: tenant spend spike.
- Evidence: inspect run trace, step state, idempotency key, auth decision, tool result, and budget counters.
- Safer mitigation: pause the smallest workflow/tool/tenant slice and preserve audit state for replay or repair.

### Failure 11: Human wait pileup

- Trigger: approval service slow.
- Amplifier: workflows hold locks.
- Blast radius: backlog and stale decisions.
- Evidence: inspect run trace, step state, idempotency key, auth decision, tool result, and budget counters.
- Safer mitigation: pause the smallest workflow/tool/tenant slice and preserve audit state for replay or repair.

### Failure 12: Audit log secret leak

- Trigger: raw prompts stored.
- Amplifier: broad support access.
- Blast radius: credential exposure.
- Evidence: inspect run trace, step state, idempotency key, auth decision, tool result, and budget counters.
- Safer mitigation: pause the smallest workflow/tool/tenant slice and preserve audit state for replay or repair.

### Failure 13: Bad tool rollout

- Trigger: new cloud API connector.
- Amplifier: global enable.
- Blast radius: production resources changed incorrectly.
- Evidence: inspect run trace, step state, idempotency key, auth decision, tool result, and budget counters.
- Safer mitigation: pause the smallest workflow/tool/tenant slice and preserve audit state for replay or repair.

### Failure 14: Auth confused deputy

- Trigger: agent uses user's broad session.
- Amplifier: resource policy skipped.
- Blast radius: cross-resource action.
- Evidence: inspect run trace, step state, idempotency key, auth decision, tool result, and budget counters.
- Safer mitigation: pause the smallest workflow/tool/tenant slice and preserve audit state for replay or repair.

### Failure 15: Unsafe fallback

- Trigger: model unavailable.
- Amplifier: platform executes cached plan.
- Blast radius: stale dangerous action.
- Evidence: inspect run trace, step state, idempotency key, auth decision, tool result, and budget counters.
- Safer mitigation: pause the smallest workflow/tool/tenant slice and preserve audit state for replay or repair.

---

## 7. Design Gates

### Gate 1 - Serving versus workflow boundary

- Which part is LLM serving and which part is workflow orchestration?
- Can the platform swap model providers without changing tool side-effect semantics?
- Where are tokens/sec concerns separated from tool correctness concerns?
- What is the first useful progress SLO versus completion SLO?

### Gate 2 - Tool auth and policy

- Who is the actor: user, service, delegated workflow, or scheduled automation?
- What scopes and tenant boundaries does each tool call carry?
- Which actions fail closed when auth policy is unavailable?
- How are credentials issued, rotated, revoked, and audited?
- How does this apply Week 08b authn/z, service identity, and tenancy principles?

### Gate 3 - Idempotency and side effects

- Which tools mutate external state?
- What is each idempotency key?
- How do retries distinguish unknown success from failure?
- Which tools are non-retryable without human inspection?
- What verification marks a side effect complete?

### Gate 4 - Memory and context

- What memory scopes exist?
- Which memory is allowed into prompts?
- How are secrets redacted?
- How are provenance, TTL, and deletion enforced?
- How do you test cross-tenant retrieval isolation?

### Gate 5 - Human-in-loop

- Which actions require approval?
- What context does the approver see?
- What happens on timeout?
- How is approval bound to the exact action and diff?
- How do you avoid approval fatigue?

### Gate 6 - Evals and release

- Which offline and shadow evals run before prompt/tool changes?
- How are tool side effects simulated?
- What adversarial cases are included?
- What is the rollback plan for a bad prompt/tool?
- Which production metrics detect regression quickly?

### Gate 7 - Cost, latency, and blast radius

- What budgets cap loops, tokens, tools, wall-clock time, and spend?
- What is isolated by tenant, workflow type, tool, and cell?
- What kill switches exist for one tool versus all workflows?
- What remains available when a tool is paused?
- How is a bad tool prevented from reaching every tenant?

### 7.1 Tool Risk Drill Cards

#### Drill 1: ticketing tool risk

- Scenario: an agent wants to use the ticketing tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 2: database query tool risk

- Scenario: an agent wants to use the database query tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 3: cloud scaling tool risk

- Scenario: an agent wants to use the cloud scaling tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 4: calendar tool risk

- Scenario: an agent wants to use the calendar tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 5: CRM update tool risk

- Scenario: an agent wants to use the CRM update tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 6: payment refund tool risk

- Scenario: an agent wants to use the payment refund tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 7: code search tool risk

- Scenario: an agent wants to use the code search tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 8: deployment tool risk

- Scenario: an agent wants to use the deployment tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 9: document editor tool risk

- Scenario: an agent wants to use the document editor tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 10: email tool risk

- Scenario: an agent wants to use the email tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 11: ticketing tool risk

- Scenario: an agent wants to use the ticketing tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 12: database query tool risk

- Scenario: an agent wants to use the database query tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 13: cloud scaling tool risk

- Scenario: an agent wants to use the cloud scaling tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 14: calendar tool risk

- Scenario: an agent wants to use the calendar tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 15: CRM update tool risk

- Scenario: an agent wants to use the CRM update tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 16: payment refund tool risk

- Scenario: an agent wants to use the payment refund tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 17: code search tool risk

- Scenario: an agent wants to use the code search tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 18: deployment tool risk

- Scenario: an agent wants to use the deployment tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 19: document editor tool risk

- Scenario: an agent wants to use the document editor tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 20: email tool risk

- Scenario: an agent wants to use the email tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 21: ticketing tool risk

- Scenario: an agent wants to use the ticketing tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 22: database query tool risk

- Scenario: an agent wants to use the database query tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 23: cloud scaling tool risk

- Scenario: an agent wants to use the cloud scaling tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 24: calendar tool risk

- Scenario: an agent wants to use the calendar tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 25: CRM update tool risk

- Scenario: an agent wants to use the CRM update tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 26: payment refund tool risk

- Scenario: an agent wants to use the payment refund tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 27: code search tool risk

- Scenario: an agent wants to use the code search tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 28: deployment tool risk

- Scenario: an agent wants to use the deployment tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 29: document editor tool risk

- Scenario: an agent wants to use the document editor tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 30: email tool risk

- Scenario: an agent wants to use the email tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 31: ticketing tool risk

- Scenario: an agent wants to use the ticketing tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 32: database query tool risk

- Scenario: an agent wants to use the database query tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 33: cloud scaling tool risk

- Scenario: an agent wants to use the cloud scaling tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 34: calendar tool risk

- Scenario: an agent wants to use the calendar tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 35: CRM update tool risk

- Scenario: an agent wants to use the CRM update tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 36: payment refund tool risk

- Scenario: an agent wants to use the payment refund tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 37: code search tool risk

- Scenario: an agent wants to use the code search tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 38: deployment tool risk

- Scenario: an agent wants to use the deployment tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 39: document editor tool risk

- Scenario: an agent wants to use the document editor tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 40: email tool risk

- Scenario: an agent wants to use the email tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 41: ticketing tool risk

- Scenario: an agent wants to use the ticketing tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 42: database query tool risk

- Scenario: an agent wants to use the database query tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 43: cloud scaling tool risk

- Scenario: an agent wants to use the cloud scaling tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 44: calendar tool risk

- Scenario: an agent wants to use the calendar tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

#### Drill 45: CRM update tool risk

- Scenario: an agent wants to use the CRM update tool after reading untrusted context.
- Name the actor, tenant, resource, action, and risk classification.
- State the idempotency key or why the action is non-retryable.
- State whether human approval is required and what diff/context must be shown.
- State the eval that would catch a bad planner or prompt for this case.
- State the smallest kill switch if this tool starts causing harm.

---

## 8. Ops Sim / Interview Drill

Questions only. Do not open the answer key until you finish.

### Scenario

Northstar Commerce runs an agentic workflow platform for support operations and internal SRE runbooks.
A new planner prompt and a new CRM connector were enabled for 30% of tenants.
The agent can read tickets, summarize customer history, draft emails, update CRM fields, create coupons, and open SRE tickets.
Within an hour, one enterprise tenant reports customers receiving duplicate apology emails and unauthorized coupon credits.
SRE also sees a spike in cloud-cost investigation tickets created by agents.

### Telemetry pack

```text
workflow starts/min:                 3,200 -> 4,100
model calls/workflow p95:            8 -> 27
tool calls/workflow p95:             5 -> 19
planner loop aborts/min:             2 -> 870
crm_update retries/min:              40 -> 18,000
crm_update idempotency hit rate:     92% -> 11%
duplicate email reports:             0 -> 1,450
coupon credits created:              300/hr -> 9,800/hr
human approval queue depth:          180 -> 14,200
approval timeout auto-approve count: 0 -> 2,100
tool auth denies:                    1% -> 17%
cost per workflow p95:               $0.18 -> $4.70
memory retrieval cross-tenant hits:  0 -> 37 blocked by downstream policy
```

### Config pack

```yaml
planner:
  promptVersion: planner-2026-07-26
  maxIterations: 40              # suspect
  stopOnRepeatedObservation: false # suspect
tools:
  crm_update:
    enabledForTenants: 30%
    retryPolicy: retry_all_timeouts
    idempotencyKey: random_uuid   # suspect
    requiresApproval: false       # suspect for credits/status changes
  send_email:
    idempotencyKey: random_uuid   # suspect
approvals:
  timeout: 10m
  onTimeout: approve             # suspect
memory:
  retrievalScope: workspace
  tenantFilterRequired: false     # suspect
budgets:
  maxToolCallsPerRun: 50          # suspect
  maxCostPerRunUsd: 10            # suspect
evals:
  requiredSuites: [prompt_golden] # missing tool side-effect and auth evals
```

### Timeline

- T+0: planner prompt and CRM connector rollout starts at 30% of tenants.
- T+5: tool calls/workflow and model calls/workflow climb; no customer reports yet.
- T+15: duplicate email and coupon reports arrive for one enterprise tenant.
- T+60: approval queue is saturated; timeout auto-approval is creating new side effects.

### Questions

1. Split trigger, amplifiers, symptoms, and customer impact.
2. What is the first safe mitigation? Be precise about tool, tenant, and workflow scope.
3. Which config values are unsafe and why?
4. Compute approximate model calls/sec at 4,100 starts/min and p95 27 model calls/workflow.
5. Why does `random_uuid` break idempotency for email and CRM updates? What keys should replace it?
6. How should human approval timeout behave for high-risk actions?
7. Which actions require human approval and what context must the approver see?
8. How do you repair workflows that may have produced duplicate coupons or emails?
9. How do you distinguish an LLM serving issue from an agent workflow issue here?
10. Which authn/z and tenant checks from Week 08b apply to tool calls?
11. What evals were missing before rollout?
12. Which bad fixes should be rejected? Name at least four.
13. What blast-radius boundaries should exist before the next connector rollout?

14. Additional interview drill: choose one mutating tool and define schema validation, auth scope, idempotency key, approval rule, audit fields, and kill switch.
15. Additional interview drill: choose one mutating tool and define schema validation, auth scope, idempotency key, approval rule, audit fields, and kill switch.
16. Additional interview drill: choose one mutating tool and define schema validation, auth scope, idempotency key, approval rule, audit fields, and kill switch.
17. Additional interview drill: choose one mutating tool and define schema validation, auth scope, idempotency key, approval rule, audit fields, and kill switch.
18. Additional interview drill: choose one mutating tool and define schema validation, auth scope, idempotency key, approval rule, audit fields, and kill switch.
19. Additional interview drill: choose one mutating tool and define schema validation, auth scope, idempotency key, approval rule, audit fields, and kill switch.
20. Additional interview drill: choose one mutating tool and define schema validation, auth scope, idempotency key, approval rule, audit fields, and kill switch.
21. Additional interview drill: choose one mutating tool and define schema validation, auth scope, idempotency key, approval rule, audit fields, and kill switch.
22. Additional interview drill: choose one mutating tool and define schema validation, auth scope, idempotency key, approval rule, audit fields, and kill switch.
23. Additional interview drill: choose one mutating tool and define schema validation, auth scope, idempotency key, approval rule, audit fields, and kill switch.
24. Additional interview drill: choose one mutating tool and define schema validation, auth scope, idempotency key, approval rule, audit fields, and kill switch.
25. Additional interview drill: choose one mutating tool and define schema validation, auth scope, idempotency key, approval rule, audit fields, and kill switch.
26. Additional interview drill: choose one mutating tool and define schema validation, auth scope, idempotency key, approval rule, audit fields, and kill switch.
27. Additional interview drill: choose one mutating tool and define schema validation, auth scope, idempotency key, approval rule, audit fields, and kill switch.
28. Additional interview drill: choose one mutating tool and define schema validation, auth scope, idempotency key, approval rule, audit fields, and kill switch.
29. Additional interview drill: choose one mutating tool and define schema validation, auth scope, idempotency key, approval rule, audit fields, and kill switch.
30. Additional interview drill: choose one mutating tool and define schema validation, auth scope, idempotency key, approval rule, audit fields, and kill switch.
31. Additional interview drill: choose one mutating tool and define schema validation, auth scope, idempotency key, approval rule, audit fields, and kill switch.
32. Additional interview drill: choose one mutating tool and define schema validation, auth scope, idempotency key, approval rule, audit fields, and kill switch.
33. Additional interview drill: choose one mutating tool and define schema validation, auth scope, idempotency key, approval rule, audit fields, and kill switch.

---

## 9. Takeaways and Reading

- Agent workflow platforms are durable side-effect systems, not just model-serving wrappers.
- The planner proposes; the orchestrator and tool gateway enforce policy, idempotency, budgets, and approval.
- Tool outputs are untrusted data and can carry prompt injection.
- Memory needs scope, TTL, provenance, sensitivity, and deletion semantics.
- Human-in-loop requires exact action binding, not vague approval prompts.
- Evals must include tool traces, side-effect simulation, auth checks, cost/latency, and adversarial cases.
- Bad tools need scoped kill switches so one connector cannot harm every tenant.

Targeted reading:

- Week-14 Design LLM Serving Platform to contrast token serving with workflow orchestration.
- Week 08b trust/authn/authz/multi-tenancy modules for delegated tool credentials and tenant isolation.
- Week-06 Saga and Outbox modules for idempotent side effects and durable workflow state.
- Week-08 Observability and SLO modules for trace, audit, and budget metrics.
- Durable execution systems such as Temporal/Cadence concepts: workflows, activities, retries, and idempotency.
- OWASP guidance on prompt injection and LLM application security where applicable.

## Additional Agentic Workflow Review Cases

### Review Case 1: read-only tool becomes mutating

- Control-plane decision: connector version changed a `lookup_customer` action into a write-through sync.
- Data-plane symptom: CRM records change during workflows that were approved as read-only.
- Invariant: a tool's declared action class must match actual side effects before it can run under read-only policy.
- Falsifying metric: mutating API calls emitted by read-only workflows and connector version skew.
- Smallest boundary: disable that connector action for the affected tenant/workflow class.
- Reject: broadening read-only credentials so the workflow can keep completing.

### Review Case 2: prompt injection through ticket text

- Control-plane decision: whether ticket text can influence tool policy or only task context.
- Data-plane symptom: agent attempts to export customer data after reading a hostile ticket.
- Invariant: untrusted tool/document output is data, not instruction, and cannot expand scopes.
- Falsifying metric: policy-denied tool proposals containing phrases from untrusted observations.
- Smallest boundary: quarantine workflows using the vulnerable prompt/tool combination.
- Reject: disabling auth denies to reduce failed workflow noise.

### Review Case 3: approval queue saturation

- Control-plane decision: timeout behavior for high-risk human approvals.
- Data-plane symptom: queued approvals age out while agents continue producing requested changes.
- Invariant: money, deletes, external comms, and production changes fail closed or escalate on timeout.
- Falsifying metric: approvals_auto_approved_total by risk tier and action class.
- Smallest boundary: pause high-risk mutating actions while allowing read-only summaries.
- Reject: auto-approving old requests to clear the queue.
