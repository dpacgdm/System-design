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

## Expanded Ops Sim Worked Analysis

### 1. Signal inventory

- Separate issuer health from verifier health. Cognito Hosted UI can be green while checkout rejects every new access token.
- The primary metrics are `jwt_unknown_kid_total`, JWKS cache hit ratio, JWKS fetch status, token `aud` denies, and verifier latency.
- Session Redis being healthy rules out session lookup as the first layer; it does not prove token validation is safe.
- mTLS being flat tells you workload identity is not the initial trigger, but sidecars still matter if a rollback changes trust bundles.

### 2. Timeline reconstruction

- T0 is the first token signed with the new kid, not the first customer 401.
- T0+cache_TTL is when stale verifiers start failing if they did not prefetch the new JWKS.
- T0+stampede is when pods all miss cache and overwhelm the identity endpoint.
- The incident commander should mark key publication, first signing, cache expiry, first 429, and first 401 on one timeline.

### 3. Root cause statement

- The likely root cause is unsafe key-rotation sequencing plus verifier cache behavior: services began seeing kid B before most verifiers had a resilient copy of kid B.
- Contributing factors are missing single-flight, no stale-if-error for public keys, insufficient pre-publication window, and no rotation game day.
- Do not call this 'Cognito down' unless issuer metrics prove token minting failed.
- Do not call this 'checkout down' without naming token verification as the failing dependency.

### 4. First 15 minutes

- Pause further key lifecycle movement: no old-key retirement and no additional token classes moved to kid B.
- Publish a known-good JWKS bundle containing old and new public keys through the fastest safe config channel.
- Enable or force single-flight/background refresh if runtime supports it; otherwise roll a small verifier hotfix by cell.
- Canary one checkout cell, verify unknown_kid and JWKS 429s drop, then continue rollout.

### 5. What not to do

- Do not disable signature validation. That converts an availability incident into a token-forgery incident.
- Do not ignore `aud`; accepting a seller-admin token at checkout is a confused-deputy vulnerability.
- Do not force global logout unless security confirms compromise. It creates login storms and does not repair verifiers.
- Do not delete old public keys before every old-token TTL has aged out or been explicitly revoked.

### 6. mTLS differential diagnosis

- For checkout-api to pay-ledger, compare client cert SAN/SPIFFE ID, server cert SAN, trust-bundle version, root/intermediate expiry, and sidecar authorization policy.
- A one-AZ failure suggests bundle skew, SDS delivery lag, or a partially rolled sidecar config.
- Scaling pods before checking cert distribution can increase handshake load and amplify failure.
- The rollback unit is the mesh config revision or trust bundle in the affected cell, not necessarily the application deployment.

### 7. Secrets rotation differential diagnosis

- Old PgBouncer connections working while new ones fail means the credential was valid for existing sessions but not for fresh auth.
- Check `setSecret`, `testSecret`, and `finishSecret` stages against the exact app user, database host, TLS mode, and PgBouncer path.
- Safe recovery is dual credentials or rollback AWSCURRENT, then canary fresh connections through PgBouncer.
- The acceptance test is not a direct psql as admin; it is a new app connection through the same pooler path.

### 8. Authorization object boundary

- Authentication says who the caller is; authorization says whether this caller can act on this tenant, order, refund, or support export.
- Every object lookup needs tenant context either in route scope, token claim, policy input, or server-side session.
- Support tools are high risk because they bypass normal product UI guardrails.
- Missing tenant context fails closed and preserves an audit event; it never performs a broad lookup by object id alone.

### 9. Capacity and control-plane limits

- JWKS endpoints, policy bundles, cert distribution, and secret managers are control-plane dependencies; they need cache and fail-safe design.
- A verifier fleet with 800 pods and no single-flight can convert one cache miss into 800 fetches per key.
- Set budgets for JWKS QPS, cert issuance QPS, secret rotation concurrency, and policy-bundle propagation time.
- Alert on derivative and cache-miss fanout, not only on identity provider 5xx.

### 10. Telemetry queries

- Slice 401s by reason: unknown kid, invalid signature, wrong audience, expired token, missing scope, mTLS deny, policy deny.
- Sample token headers only after redaction; preserve kid, alg, iss, aud, token_use, and issued-at bins.
- Join traces with verifier cache_hit and fetch_status to prove latency is in verification.
- Keep raw security evidence under incident retention rules; do not paste sensitive tokens into chat.

### 11. Blast radius and degradation

- Fail closed for payment, checkout writes, admin actions, support export, and private data reads.
- Public catalog browsing can degrade to anonymous or cached content if it does not leak identity.
- If checkout auth is degraded, queue non-critical seller operations but keep security boundaries intact.
- Cell rollout and cell rollback keep a bad verifier config from becoming global.

### 12. Organizational ownership

- Identity platform owns key lifecycle and JWKS publication.
- Checkout owns verifier library version, runtime cache behavior, and customer impact.
- Security owns compromise criteria, deny-list decisions, and evidence handling.
- Incident command owns sequencing and prevents availability fixes from weakening trust.

### 13. Durable runbook

- Publish new keys two verifier cache TTLs before first signing.
- Run canary tokens through every verifier class before production signing.
- Keep old public keys until max access-token TTL plus clock skew unless compromise requires deny.
- Game-day quarterly: key add, key rollover, JWKS 429, stale cache, emergency kid deny.

### 14. Acceptance criteria

- During a game day, checkout 401 rate rises less than 0.5% and unknown_kid returns to baseline within two minutes.
- JWKS 429s do not exceed the control-plane budget because single-flight and background refresh work.
- Wrong audience remains rejected throughout the incident.
- A fresh PgBouncer connection and an mTLS checkout->pay-ledger call both pass after rotation.

## Additional Ops Sim Drills

### Runbook drill: JWKS 429 storm

- Inject 429s from the JWKS endpoint while a new kid is active.
- Expected behavior: verifiers use cached known-good keys and background refresh with bounded concurrency.
- Fail condition: request-path fetches pile up and checkout latency rises before 401s.
- Operator action: check cache hit ratio and single-flight metrics before touching application replica count.

### Runbook drill: wrong audience token

- Mint a valid seller-admin token and send it to checkout-api.
- Expected behavior: checkout rejects with wrong_audience and logs a redacted audit event.
- Fail condition: policy accepts the token because issuer and signature are valid.
- Owner: security and service platform jointly maintain the verifier conformance suite.

### Runbook drill: mTLS root rollover

- Roll a new mesh root into one cell and keep another cell on the old bundle.
- Expected behavior: dual-bundle trust during overlap, then clean retirement after workload cert TTL.
- Telemetry: handshake failure reason, SDS push version, sidecar config revision, and principal mapping.
- Fail condition: one AZ sees unknown authority while health checks stay green.

### Runbook drill: secret dual credential

- Rotate DB credentials with old and new passwords accepted during overlap.
- Expected behavior: old pooled sessions drain while fresh PgBouncer connections succeed with new secret.
- Telemetry: fresh connection success, auth failures by user, pool reuse ratio, and AWSCURRENT version.
- Fail condition: testSecret uses a privileged direct connection instead of the application path.

### Policy propagation budget

- AuthZ policy changes need a maximum propagation time and a stale-policy behavior.
- Checkout writes and admin actions fail closed if policy freshness exceeds budget.
- Low-risk public reads may serve cached policy only if no private object is exposed.
- Metric: policy_bundle_age_seconds by service and cell.

### Abuse intersection

- Attackers can abuse auth endpoints through login storms, token introspection storms, and replayed webhooks.
- Rate limits must include principal, IP, tenant, endpoint, and expensive verification path.
- A valid token is not permission to create unbounded work.
- Webhook signatures require timestamp windows and idempotency keys.

### Data-class fail behavior

- Fail closed: money movement, private user data, support exports, admin writes, tenant routing changes.
- Fail degraded: public catalog, read-only stale non-sensitive pages, queued seller analytics.
- Fail open is acceptable only for explicitly public, non-mutating content.
- The runbook should list examples, not just principles.

### Post-incident artifacts

- Publish key lifecycle timeline, verifier cache defects, affected token classes, and exact customer impact.
- Add conformance tests for issuer/audience/expiry/kid and service-to-service principal mapping.
- Record security decision: no signature validation bypass was used.
- Create owner-dated actions for cache, game day, and emergency deny-list.


---
