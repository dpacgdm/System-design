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

## Scoring rubric

| Score | Description |
| --- | --- |
| Meets bar | Names mechanism, protects invariant, sequences mitigation safely, includes evidence and numeric blast-radius/capacity reasoning. |
| Borderline | Finds the symptom but misses one of rollback, capacity, customer slice, or rejected bad fix. |
| Miss | Optimizes a dashboard, repairs from derived state, weakens trust/idempotency, or ignores affected slice evidence. |
