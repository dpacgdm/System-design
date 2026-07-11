# AuthN AuthZ OAuth mTLS and Secrets Answers

Open only after attempting the learner file Ops Sim.

## Checkout Auth Meltdown During Key Rotation

### Q1 - Layer and root cause

The primary symptom is API JWT validation, specifically
JWKS/key-rotation behavior in checkout-api. Cognito is
issuing tokens, session Redis is healthy, mTLS is flat,
and tenant authorization mismatches are flat. New tokens
use kid 2026-07-11-b, but most pods either lack the key
or stampede the JWKS endpoint and receive 429s.

### Q2 - Evidence

- unknown_kid jumps from 40/min to 39k/min when
  identity-ops starts signing with the new kid.
- JWKS fetch p95 rises to 2.8s and 429s hit 6.4k/min
  while singleflight is false on 62% of pods.
- Trace shows jwt validate taking 3010ms with
  cache_hit=false and fetch_status=429.
- Red herring: ALB target health and Cognito Hosted UI
  health; login can be healthy while verifiers fail.

### Q3 - First 15 minutes

1. Declare P1 and assign incident command, identity
   lead, checkout lead, and security lead.
2. Pause further rotation and stop signing additional
   token classes with the new kid if safe. Do not retire
   the old key yet.
3. Push a known-good JWKS bundle/config with old and new
   public keys plus single-flight and negative cache if
   runtime config supports it.
4. Preserve stale known keys on JWKS fetch error unless
   the key is explicitly denied for compromise.
5. Canary checkout-api, confirm unknown_kid drops, then
   roll by cell/AZ.
6. Do not disable signature validation, drop audience
   checks, or force global logout unless security
   confirms compromise requires it.

### Q4 - Bad fixes

- Disabling signature validation accepts forged tokens
  and turns availability trouble into account takeover
  risk.
- Dropping audience checks creates confused-deputy risk
  because seller-admin tokens could be accepted by
  checkout.
- Forcing global logout may be needed for confirmed
  compromise but creates login storm and does not fix
  verifier stampede.
- Rolling back identity changes helps only if it stops
  new-kid issuance; it does not validate tokens already
  issued with the new kid.

### Q5 - Blast radius

If 64% of active sessions carry old-kid access tokens
and TTL is 15 minutes, denying the old kid immediately
can reject up to 64% of current authenticated traffic
until refresh or reauth. That is worse than the current
18.7% failure unless compromise containment requires it.
Without confirmed compromise, keep old public key
trusted until old tokens age out while stopping old-key
signing.

### Q6 - Durable fix

- Publish new public key at least two verifier cache
  TTLs before signing.
- Verifier cache uses positive cache, negative cache,
  single-flight, background refresh, stale-if-error,
  issuer-scoped keys, and denied-kid override.
- Emergency deny list bypasses stale-if-error for
  confirmed compromise.
- Acceptance: rotation game day causes less than 0.5%
  401 increase, no JWKS 429 storm, unknown_kid returns
  to baseline within two minutes, and wrong audience is
  still rejected.

### Q7 - Org and runbook

By T+10 include incident command, checkout owner,
identity platform, security incident commander, customer
support, product/sale owner, and business comms if
revenue risk is material. Pre-authorized: pause
rotation, deploy verifier config, canary cache changes.
Security approval required: deny old kid early, force
logout, revoke refresh-token families, or classify a key
leak publicly.
