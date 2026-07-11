# Abuse Bots and Fraud Defense Answers

Open only after attempting the learner file Ops Sim.

## Northstar Card Testing and Cache Poisoning Combo

### Q1 - Classify the two abuse mechanisms and name the protected invariants.

Name the narrow failing layer first, then show why
adjacent healthy systems do not disprove it. The root
cause should be phrased as a mechanism with an invariant,
not as a team name or product name.

### Q2 - Which signals prove card testing despite only modest global traffic grow

Use the telemetry pack in slices. A strong answer cites at
least three metrics, one log/config fact, and one
misleading global signal that would hide the affected
customer group.

### Q3 - Which limiter hierarchy should replace the current IP/global bucket

The first fifteen minutes should freeze additional blast
radius, preserve evidence, scope or disable the dangerous
path, and avoid destructive cleanup. Do not optimize for
green dashboards before protecting correctness.

### Q4 - What cache poisoning or personalization leak evidence exists, and what i

Reject fixes that weaken authentication, authorization,
idempotency, source-of-truth repair, or tenant boundaries.
Also reject broad global changes when the evidence points
to a cell, tier, client version, route, or operation
class.

### Q5 - What should risk-api do on timeout for payment authorize versus public c

The capacity or blast-radius answer must do arithmetic
from the prompt: rates, percentages, queue depth, lag,
stale windows, or duplicate counts. Fleet averages are not
enough.

### Q6 - Which mitigations preserve flash-sale revenue while protecting PSP capac

The durable fix should include an automated test or game-
day, a config or protocol change, telemetry, an owner, and
a clear acceptance threshold.

### Q7 - What evidence must be preserved for fraud/security without leaking secre

The org/runbook answer should name incident command,
service owner, security or fraud if relevant,
product/support, and the approval boundary for risky
mitigations.

### Q8 - Name bad fixes to reject and durable tests to add.

The final answer should turn the incident into launch
criteria: what must be true before the next rollout and
which bad state is now impossible or quickly detected.

## Worked response outline

- Primary diagnosis: card testing plus cache poisoning/key
  explosion. Modest global RPS hides PSP decline mix, per-
  card velocity, per-account velocity, and CDN variant
  explosion.
- Immediate move: weight payment authorize heavily, add
  card/device/account/ASN/tenant buckets, require risk
  step-up or hold for high risk, and disable public
  caching of seller price-preview.
- Risk API fail mode should not be one default everywhere.
  Payment authorize should use conservative step-up/hold
  on risk timeout; public catalog read may degrade with
  lower personalization.
- Preserve evidence: token/session facts after redaction,
  card fingerprints not PAN, device hashes, limiter
  decisions, PSP codes, cache keys, bot scores, and
  affected tenant/customer slices.
- Reject blocking all anonymous catalog traffic, disabling
  auth checks, returning 500 on limits, or leaving
  emergency CAPTCHA/rules without owner and expiry.

## Scoring rubric

| Score | Description |
| --- | --- |
| Meets bar | Names mechanism, protects invariant, sequences mitigation safely, includes evidence and numeric blast-radius/capacity reasoning. |
| Borderline | Finds the symptom but misses one of rollback, capacity, customer slice, or rejected bad fix. |
| Miss | Optimizes a dashboard, repairs from derived state, weakens trust/idempotency, or ignores affected slice evidence. |
