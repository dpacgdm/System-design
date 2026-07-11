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

## Principal-depth model answer

### Q1 - Abuse classes and invariants

There are two mechanisms:

1. Card testing against `POST /checkout/payment-authorize`.
   The protected invariant is that Northstar does not provide
   cheap, high-velocity guesses against PSP/card networks, and
   legitimate buyers are not crowded out by adversarial
   authorization attempts.
2. CDN cache poisoning/key explosion and personalization leak
   on `/seller/price-preview`. The protected invariant is that
   seller-specific or buyer-specific pricing is never served
   from a shared public cache, and attackers cannot turn cache
   key dimensions into an origin DoS.

Authentication is not enough. Many requests have valid buyer
sessions created within 90 seconds; valid sessions can still
be abusive when velocity, device family, BIN range, account
creation pattern, and endpoint economics are wrong.

### Q2 - Signals proving card testing

The global RPS only rises 18%, so a fleet graph will understate
the incident. The proof is in high-risk dimensions:

- `psp_decline_rate{amount_bucket=small}: 2.1% -> 38%`
  matches card-testing behavior.
- `payment_attempts_per_card_hash_p95: 2 -> 47/10m`
  shows repeated attempts against the same card fingerprint.
- `account_payment_velocity_p99: 4 -> 61/10m` shows account
  velocity, not normal shopping.
- `ip_unique_accounts_p95: 3 -> 480/10m` shows IP-only
  limits are blind to account churn.
- `rate_limit_decision_total{bucket=global_requests,
  decision=allow}: 97%` proves the current limiter is
  allowing the attack.
- Trace notes say attempts use different IPs but the same BIN
  ranges and device hash family.
- `risk-api: feature timeout, default=allow` explains why
  suspicious payments are permitted when risk is overloaded.

### Q3 - Limiter hierarchy

Replace the single IP/global bucket with a weighted,
hierarchical limiter:

- endpoint weight: payment authorize costs far more than
  product browse;
- tenant and route budget: flash-sale catalog can continue
  while payment attempts are constrained;
- account velocity: attempts per account and account age;
- card fingerprint/BIN hash velocity, never raw PAN;
- device fingerprint family and emulator/headless signal;
- ASN/proxy/VPN reputation and IP subnet;
- payment provider quota and decline-rate feedback;
- seller or campaign slice when abuse targets a sale;
- allowlist/step-up controls for trusted high-value buyers.

The limiter should return explicit friction states: allow,
step-up, hold/manual review, throttle, or deny. Returning 500
or silently timing out creates retries and hides evidence.

### Q4 - Cache poisoning and personalization leak

Evidence:

- `cdn_origin_miss_ratio{route=price-preview}: 8% -> 54%`
  shows origin pressure from cache churn.
- `cache_key_cardinality: 41k -> 7.8M` is key explosion.
- `cache_hit_served_with_set_cookie_total: 19` proves shared
  cache served something with personalized/session semantics.
- Config `vary_allowlist: ['*']` accepts attacker-controlled
  dimensions into the cache key.
- Trace says price-preview includes seller-specific discount
  and `Set-Cookie`.

Containment:

1. Change `/seller/price-preview` to `private, no-store` or a
   correctly keyed private endpoint before purge.
2. Stop accepting arbitrary `Vary`; allowlist only stable,
   low-cardinality dimensions.
3. Purge scoped bad variants after the fixed policy is live.
4. Separate public catalog preview from personalized seller or
   buyer pricing.
5. Add cache logs to the evidence bundle without leaking
   cookies or auth tokens.

### Q5 - Risk timeout policy

Payment authorize must not default allow on risk timeout.
Safe behavior is class-based:

- For money movement, fail closed into step-up, hold, or
  pending review when risk features are unavailable.
- For low-risk public catalog reads, degrade personalization
  or serve a bounded public view.
- For seller/admin actions, require fresh risk/auth context
  or deny until service recovers.

This preserves revenue better than a global block because
catalog browsing can continue while high-cost payment attempts
receive friction.

### Q6 - Flash-sale preserving mitigations

Do not block all anonymous browsing. Instead:

- weight `POST /checkout/payment-authorize` heavily;
- require step-up for new accounts, high card velocity, risky
  device families, and suspicious BIN/device clusters;
- rate-limit by card/account/device/ASN in addition to IP;
- reserve PSP capacity for established buyers and low-risk
  checkout sessions;
- degrade price-preview personalization while serving public
  product pages;
- disable public caching for personalized price-preview;
- cap origin miss rate and protect origin pools with
  backpressure;
- coordinate with PSP/risk on temporary thresholds and
  evidence format.

### Q7 - Evidence preservation

Preserve:

- hashed card fingerprint, BIN range, PSP response code, and
  provider request id;
- device hash family, IP/ASN, account id, tenant, session age,
  and auth result;
- limiter decision, risk score/features used, timeout result,
  and friction state;
- CDN request id, normalized cache key, Vary headers,
  cache-status, and whether Set-Cookie was present;
- affected seller/customer slices and timestamps.

Do not preserve raw PAN, CVV, bearer tokens, session cookies,
full JWTs, or unredacted PII in incident docs. Security/fraud
owns the evidence chain; support gets customer-safe slices and
approved wording.

### Q8 - Bad fixes and durable tests

Reject:

- all anonymous catalog block during a flash sale;
- disabling auth or risk checks to reduce latency;
- global IP-only bans that miss distributed bots and harm NAT
  users;
- returning 500 for limits;
- purging cache before fixing headers;
- leaving emergency CAPTCHA/rules without owner, expiry, and
  false-positive monitoring;
- logging raw payment or token data for "debugging."

Durable acceptance criteria:

- payment-authorize has a higher endpoint cost than browse in
  limiter tests;
- simulation covers distributed IPs with same card/device
  family and proves velocity limits trigger;
- risk timeout tests assert payment step-up/hold, not allow;
- cache-policy tests fail if personalized route is public or
  `Vary` admits arbitrary headers;
- canary tracks false positives, PSP decline mix, origin miss
  ratio, key cardinality, and good-buyer conversion;
- runbook names fraud, security, payments, edge/CDN, support,
  and product owners.

## Scoring rubric

| Score | Description |
| --- | --- |
| Meets bar | Names mechanism, protects invariant, sequences mitigation safely, includes evidence and numeric blast-radius/capacity reasoning. |
| Borderline | Finds the symptom but misses one of rollback, capacity, customer slice, or rejected bad fix. |
| Miss | Optimizes a dashboard, repairs from derived state, weakens trust/idempotency, or ignores affected slice evidence. |
