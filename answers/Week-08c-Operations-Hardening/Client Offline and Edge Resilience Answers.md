# Client Offline and Edge Resilience Answers

Open only after attempting the learner file Ops Sim.

## Northstar Mobile Offline Queue Duplicates Checkout

### Q1 - Which operations should have been offline queueable, revalidated, or onl

Name the narrow failing layer first, then show why
adjacent healthy systems do not disprove it. The root
cause should be phrased as a mechanism with an invariant,
not as a team name or product name.

### Q2 - Which signals prove the duplicate is client idempotency/retry behavior r

Use the telemetry pack in slices. A strong answer cites at
least three metrics, one log/config fact, and one
misleading global signal that would hide the affected
customer group.

### Q3 - How does QUIC connection migration help, and what app-level problem rema

The first fifteen minutes should freeze additional blast
radius, preserve evidence, scope or disable the dangerous
path, and avoid destructive cleanup. Do not optimize for
green dashboards before protecting correctness.

### Q4 - Write the first 15-minute mitigation that stops new risk without corrupt

Reject fixes that weaken authentication, authorization,
idempotency, source-of-truth repair, or tenant boundaries.
Also reject broad global changes when the evidence points
to a cell, tier, client version, route, or operation
class.

### Q5 - What should the server do with stale price and inventory versions during

The capacity or blast-radius answer must do arithmetic
from the prompt: rates, percentages, queue depth, lag,
stale windows, or duplicate counts. Fleet averages are not
enough.

### Q6 - What conflict UX should buyers and sellers see

The durable fix should include an automated test or game-
day, a config or protocol change, telemetry, an owner, and
a clear acceptance threshold.

### Q7 - What mobile flag and cache TTL design would make rollback reliable

The org/runbook answer should name incident command,
service owner, security or fraud if relevant,
product/support, and the approval boundary for risky
mitigations.

### Q8 - Name durable telemetry and tests before relaunch.

The final answer should turn the incident into launch
criteria: what must be true before the next rollout and
which bad state is now impossible or quickly detected.

## Worked response outline

- Primary diagnosis: mobile offline queue treats checkout
  submit as queueable with a new idempotency key per
  retry; QUIC migration helps transport but the app
  timeout creates a new business operation.
- Ledger duplicate business effects being zero is good but
  not sufficient; PSP duplicate authorize attempts are
  still external risk and customer harm.
- Immediate move: remotely disable offline checkout
  submit, force server to reject stale price/inventory for
  money decisions, preserve pending operation IDs, and
  avoid deleting local queues blindly.
- Fix: stable client_operation_id per checkout intent,
  server idempotency record scoped to
  tenant/account/operation/payload hash, bounded retry
  with jitter, and user-visible pending until server
  confirms.
- Rollback design: critical mobile flags have short TTL,
  safe default false, server override, app-version gates,
  and telemetry for stale flag versions.

## Scoring rubric

| Score | Description |
| --- | --- |
| Meets bar | Names mechanism, protects invariant, sequences mitigation safely, includes evidence and numeric blast-radius/capacity reasoning. |
| Borderline | Finds the symptom but misses one of rollback, capacity, customer slice, or rejected bad fix. |
| Miss | Optimizes a dashboard, repairs from derived state, weakens trust/idempotency, or ignores affected slice evidence. |
