# Testing Distributed Systems Answers

Open only after attempting the learner file Ops Sim.

## Northstar Replay Gate Finds Duplicate Captures

### Q1 - Which test layer found the issue, and why would a normal load test likel

Name the narrow failing layer first, then show why
adjacent healthy systems do not disprove it. The root
cause should be phrased as a mechanism with an invariant,
not as a team name or product name.

### Q2 - Which signals prove this is an idempotency/retry problem rather than a P

Use the telemetry pack in slices. A strong answer cites at
least three metrics, one log/config fact, and one
misleading global signal that would hide the affected
customer group.

### Q3 - Should the launch proceed because ledger duplicate business effects are 

The first fifteen minutes should freeze additional blast
radius, preserve evidence, scope or disable the dangerous
path, and avoid destructive cleanup. Do not optimize for
green dashboards before protecting correctness.

### Q4 - Write the fix and the contract change for old mobile clients.

Reject fixes that weaken authentication, authorization,
idempotency, source-of-truth repair, or tenant boundaries.
Also reject broad global changes when the evidence points
to a cell, tier, client version, route, or operation
class.

### Q5 - What deterministic simulation state would reproduce this trace without r

The capacity or blast-radius answer must do arithmetic
from the prompt: rates, percentages, queue depth, lag,
stale windows, or duplicate counts. Fleet averages are not
enough.

### Q6 - What game-day should be run after the fix, including abort criteria

The durable fix should include an automated test or game-
day, a config or protocol change, telemetry, an owner, and
a clear acceptance threshold.

### Q7 - Which bad fixes should be rejected even if p99 latency improves

The org/runbook answer should name incident command,
service owner, security or fraud if relevant,
product/support, and the approval boundary for risky
mitigations.

### Q8 - What acceptance thresholds unblock launch

The final answer should turn the incident into launch
criteria: what must be true before the next rollout and
which bad state is now impossible or quickly detected.

## Worked response outline

- Primary diagnosis: replay found retry/idempotency drift
  that a latency-focused canary hides. The new library
  generates operation IDs per attempt.
- Do not launch because ledger duplicate business effects
  are zero; the external PSP boundary already saw
  duplicate keys, and the invariant is exactly-once
  external business effect, not just internal ledger
  state.
- Fix by deriving one stable operation ID from the user
  checkout intent and carrying it through every retry,
  mobile version, ledger write, PSP call, and replay
  comparison.
- Simulation model: states are request sent, PSP accepted
  but client timed out, retry scheduled, operation ID
  reused or regenerated, ledger dedupe decision, and PSP
  call outcome.
- Game-day: inject slow success and connection hangs in
  pay-ledger for one cell; abort on duplicate external
  attempts, SLO burn threshold, or retry budget overflow.

## Principal-depth model answer

### Q1 - Test layer and why load testing misses it

This is a replay/contract/simulation gate, not a normal load
test. The failing behavior depends on a precise ordering:

1. PSP accepts attempt 1.
2. The client or edge observes a timeout at 2400ms.
3. Retry library schedules another attempt.
4. The library generates a fresh `operation_id`.
5. Ledger dedupe saves internal state but the PSP boundary
   sees a second external key.

A load test can improve p99 and still miss the bug because it
usually measures throughput, latency, and 5xx rate. It does
not assert "one user checkout intent creates at most one
external PSP business attempt across timeouts, retries, app
versions, and replayed traces."

### Q2 - Evidence that this is idempotency/retry drift

Use the packet as a chain, not isolated facts:

- `replay_decision_diff_ratio{route=checkout_submit}: 0.19%`
  exceeds the 0.05% launch gate.
- `duplicate_capture_attempt_total{sink=psp_sandbox}: 312`
  proves the external boundary sees duplicates.
- `duplicate_business_effect_total{ledger}: 0` proves the
  internal ledger is not the only invariant.
- `retry-lib: generated operation_id on each attempt` names
  the mechanism.
- `pay-ledger-sandbox: duplicate PSP key rejected for 307
  operations` shows downstream dedupe is saving the system by
  accident or provider behavior, not by contract.
- `contract-verifier: mobile v2025.10 payload lacks
  client_operation_id` explains why old clients need a
  compatibility rule.
- `retry_attempts_per_request_p99: 7` and `timeout_budget`
  exhaustion show the high-risk path is timeout/retry heavy.

The PSP is not the root cause because the replay produces the
duplicate sequence in a fenced sandbox from known traces. The
new library changed operation identity semantics.

### Q3 - Launch decision and invariant

Do not launch. The ledger's zero duplicate business effects
are necessary but insufficient. The launch invariant is:

> One checkout intent must map to one stable operation identity
> and at most one external PSP capture/authorize attempt,
> regardless of retry timing, transport timeout, or mobile
> version.

The external PSP key is part of the money-movement boundary.
If the provider rejects a duplicate today, that is still a
failed launch gate because it creates provider risk, customer
notification risk, reconciliation noise, and possible
chargeback/settlement ambiguity.

### Q4 - Fix and compatibility contract

The fix is not "fewer retries" alone. It is identity first,
then retry policy:

- Derive `client_operation_id` from the checkout intent, not
  each HTTP attempt.
- Scope it by tenant, buyer account, cart/order draft id, and
  payload semantic hash.
- Persist the idempotency record before making the PSP call.
- Carry the same id through mobile, BFF, pay-ledger, outbox,
  PSP request, replay comparison, and support tooling.
- Treat payload-hash mismatch for an existing key as a
  conflict, not a retry.
- Keep total retry budget lower than user-facing timeout
  expectations, and apply jitter/backoff.

For old mobile clients that lack `client_operation_id`, the
server must mint a stable server-side operation id from a
compatible intent fingerprint and return it. The contract
should require all new clients to send the field, while old
clients are gated by app version, route, and server-generated
compatibility until sunset.

### Q5 - Deterministic simulation state

The minimal state machine is:

1. `IntentCreated(cart_hash, buyer, tenant)`.
2. `AttemptStarted(operation_id_source)`.
3. `PspAcceptedButResponseDelayed`.
4. `ClientTimeoutObserved`.
5. `RetryScheduled`.
6. `OperationIdReused` or `OperationIdRegenerated`.
7. `LedgerDedupeLookup`.
8. `PspRequestSent`.
9. `LedgerCommitOrPending`.
10. `ReplayComparatorObservesExternalAttemptCount`.

The simulation should vary timeout point, PSP accept/reject,
mobile version, network reset, app restart, and replay seed.
It does not need 4.2M events; it needs the causal states that
produce "accepted externally but timed out locally."

### Q6 - Post-fix game-day

Game-day design:

- Scope: one staging cell or one production shadow path with
  PSP sandbox/fenced provider.
- Hypothesis: stable operation ids prevent duplicate external
  attempts during slow-success and connection-hang sequences.
- Injection: force PSP success after client timeout, TCP reset
  after provider accept, app process restart, and replay of
  old mobile payloads.
- Roles: incident commander, payments owner, mobile owner,
  replay/tooling owner, finance/risk observer, support
  comms.
- Evidence: operation id reuse rate, duplicate PSP key count,
  ledger duplicate business effect count, retry attempts,
  timeout budget usage, and replay diff by app version.

Abort immediately on any duplicate external attempt, any
nonzero duplicate ledger business effect, PSP sandbox QPS over
budget, retry p99 above contract, or inability to attribute
events to operation ids.

### Q7 - Bad fixes to reject

Reject these even if p99 improves:

- Launching because `canary_checkout_p99` improves from 240ms
  to 185ms; latency is not the money invariant.
- Deduping only inside the ledger; the PSP side effect has
  already escaped.
- Dropping old mobile support without a server compatibility
  plan; old clients remain in the field.
- Using a random UUID per retry with a downstream "best effort"
  reconciliation job.
- Increasing retry attempts beyond the total budget.
- Removing replay fences to get a cleaner test; that risks
  live email or PSP side effects.
- Ignoring a 0.19% decision diff because it is "small"; the
  launch gate says 0.05%, and money effects require zero.

### Q8 - Acceptance thresholds

Unblock launch only when:

- duplicate external PSP attempts are exactly 0 across the
  replay corpus and targeted simulation seeds;
- duplicate ledger business effects remain exactly 0;
- replay decision diff is below 0.05% and all remaining diffs
  are explained and approved;
- `idempotency_key_missing_total` for launch-eligible clients
  is 0, with a compatibility path for known old versions;
- retry attempts fit within total budget and p99 does not hide
  retry storms;
- replay fences prove no live email/PSP side effect escapes;
- dashboards slice results by app version, network type,
  payment provider, tenant, and operation-id source;
- the game-day has a signed runbook and named owners for
  rollback, customer messaging, finance reconciliation, and
  mobile sunset.

## Scoring rubric

| Score | Description |
| --- | --- |
| Meets bar | Names mechanism, protects invariant, sequences mitigation safely, includes evidence and numeric blast-radius/capacity reasoning. |
| Borderline | Finds the symptom but misses one of rollback, capacity, customer slice, or rejected bad fix. |
| Miss | Optimizes a dashboard, repairs from derived state, weakens trust/idempotency, or ignores affected slice evidence. |


---
