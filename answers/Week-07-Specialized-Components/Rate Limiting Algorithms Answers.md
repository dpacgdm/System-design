# Answer Key — Rate Limiting Algorithms

> Open only after attempting the learner file questions.

## Expert Analysis

### Question 1: The Exact Failure Chain

```
FAILURE CHAIN (step by step):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STEP 1 — Acme batch job starts (2:47 PM)
  500 worker processes, each assigned rotating sub-api-key
  Design intent: stay under 60 exports/hour PER KEY
  Actual aggregate: 500 × 60 = 30,000 exports/hour minimum

STEP 2 — Per-key rate limit PASSES (2:47-2:52 PM)
  App Redis sliding window: rl:sw:acme_sub_key_N:window
  Each of 500 keys independently under 60/hour
  rate_limit_middleware logs rate_limit_pass for every request
  NO tenant-level key exists (removed in yesterday's deploy)

STEP 3 — API Gateway usage plan PARTIALLY effective
  Each sub-api-key is NOT registered in usage plan (bug)
  Keys authenticate via JWT custom claim, bypass usage plan
  Gateway limit never triggers

STEP 4 — WAF not triggered
  Acme egress: 200 IPs across workers (under 3000/5min/IP each)
  Edge limit irrelevant

STEP 5 — RDS overload (2:52 PM)
  30k export queries/hour × avg 45 sec query = connection hoarding
  DB connection pool bulkhead: 80 connections, all busy
  Query queue depth grows, p99 latency → 90 seconds

STEP 6 — Circuit breaker flickers (2:54 PM)
  failure_rate > 50% → OPEN
  wait 30s → HALF-OPEN
  Unlimited probes: each half-open attempt runs FULL export query
  10 probes × 45 sec queries = still saturates pool
  CLOSED briefly → immediate re-saturate → OPEN again (flicker)

STEP 7 — Innocent tenants affected (2:58 PM)
  SmallCorp export request:
    → Passes WAF ✓
    → Passes API Gateway ✓
    → Passes app rate limit ✓ (under 60/hour)
    → Acquires bulkhead slot... WAITS... timeout 30s
    → Circuit half-open probe competing for same DB pool
    → bulkhead_rejected OR query timeout
    → Returns 503 service_unavailable

BLAST RADIUS FAILURES:
  ┌────────────────────────────┬──────────────────────────────────────┐
  │ Missing control            │ Consequence                          │
  ├────────────────────────────┼──────────────────────────────────────┤
  │ Tenant aggregate limit     │ 500 keys × individual limit = bypass │
  │ Usage plan on all keys     │ Sub-keys unregistered                │
  │ Half-open probe rate limit │ DB never recovers                    │
  │ Bulkhead per tenant on DB  │ One tenant exhausts shared pool      │
  │ WAF (expected)             │ Not wrong — IP dimension insufficient│
  └────────────────────────────┴──────────────────────────────────────┘
```

### Question 2: Immediate Mitigation (Priority Order)

```
MINUTE 0-2 — STOP THE BLEEDING (Acme traffic)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ACTION 1: Block Acme tenant at application layer (fastest precise cut)
    redis-cli --tls SET 'rl:override:tenant:acme_corp' 'BLOCK' EX 3600
    # Middleware checks override key first → 429 all Acme keys

  ACTION 2: If middleware deploy needed, WAF IP set on Acme known ranges:
    aws wafv2 update-ip-set \
      --name acme-emergency-block \
      --addresses 198.51.100.0/24 ... \
      --scope REGIONAL

  ACTION 3: Kill Acme batch job (customer contact parallel):
    # Revoke JWT client credentials in Cognito
    aws cognito-idp admin-user-global-sign-out --user-pool-id $POOL --username acme_batch_service

MINUTE 2-5 — PROTECT SHARED RDS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ACTION 4: Force circuit breaker OPEN (stop half-open flicker):
    # Feature flag or admin endpoint:
    curl -X POST http://export-svc.internal/admin/circuit/rds -d '{"state":"OPEN","reason":"incident"}'

  ACTION 5: Scale RDS read replica? NO — exports are write-heavy to temp tables
    DO NOT: failover RDS (adds chaos)
    DO NOT: restart Redis (loses counters, fail-open risk)

MINUTE 5-10 — RESTORE OTHER TENANTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ACTION 6: Enable queue mode for exports (if feature exists):
    POST /export returns 202 Accepted + job ID
    Worker pool drains at fixed 10 concurrent (leaky bucket)

  ACTION 7: Communicate status internally:
    "Acme batch blocked, circuit held OPEN, SmallCorp should recover in 5 min"

WHAT NOT TO DO:
  ✗ Raise global rate limits ("let more through") — worsens RDS
  ✗ Disable rate limiting entirely — retry storm
  ✗ Return 429 to SmallCorp — they are not the problem; fix is 503→recovery
  ✗ Delete Redis keys without plan — fail-open
  ✗ Force circuit CLOSED manually — immediate re-saturate
```

### Question 3: Half-Open Probe Rate Limiting

```
WHY UNLIMITED HALF-OPEN MADE IT WORSE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  HALF-OPEN purpose: test if dependency recovered with MINIMAL load
  Export query: 45 seconds, 1 DB connection each

  Unlimited half-open:
    Breaker opens → 30s wait → half-open
    50 concurrent requests already queued in export-svc
    ALL 50 become "probes" — each grabs DB connection
    50 × 45 sec >> pool size 80 → pool exhausted for 45+ sec
    Queries fail → breaker reopens
    30s later → repeat

  Flickering state machine:
    OPEN → HALF-OPEN → fail → OPEN → HALF-OPEN → fail
    RDS never gets sustained idle period to recover
    Innocent requests arrive during half-open, compete with probes

CORRECT HALF-OPEN CONFIG (Resilience4j-style):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  permittedNumberOfCallsInHalfOpenState: 3   (not 50, not unlimited)
  maxWaitDurationInHalfOpenState: 10s
  waitDurationInOpenState: 60s               (longer cool-down during incident)

  Export-specific override:
    Half-open probes: HEAD /health on RDS (SELECT 1) — NOT full export
    Full export only when circuit CLOSED

  Probe rate limit (explicit):
    max 3 probe exports per 10 minutes per tenant
    Probes use dedicated bulkhead: 2 connections (not shared pool)

  WEEK 6 CONNECTION:
    "half-open probing must be rate-limited" — LO #1
    Probes are a DIFFERENT traffic class than normal requests
    Metric: circuit_breaker_half_open_probes_total (should be ≤3/min)
```

### Question 4: Long-Term Architecture

```
TENANT-LEVEL AGGREGATE LIMIT (mandatory):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Redis key hierarchy:
    rl:tenant:acme_corp:hourly_exports   → limit 500/hour (contract)
    rl:key:acme_sub_*:hourly_exports     → limit 60/hour (fair-use per key)

  Check ORDER (fail fast on expensive check):
    1. Tenant aggregate (cheap INCR, one key per tenant)
    2. Per-key limit
    3. Token weight for export size

  Sub-key rotation cannot bypass tenant key — all sub-keys map to tenant_id
  in JWT claim: { "tenant_id": "acme_corp", "key_id": "sub_447" }

API GATEWAY FIX:
━━━━━━━━━━━━━━━━

  ALL keys (including sub-keys) registered in usage plan OR
  Single API key per tenant with app issuing short-lived tokens
  Remove unregistered JWT-only bypass

  aws apigateway create-usage-plan-key \
    --usage-plan-id enterprise-plan \
    --key-id $SUB_KEY_ID \
    --key-type API_KEY
  # Automate in key provisioning pipeline — no manual bypass

BULKHEAD PER TENANT ON DB:
━━━━━━━━━━━━━━━━━━━━━━━━━━

  Resilience4j bulkhead instances:
    bulkhead_acme: max 20 concurrent DB queries
    bulkhead_shared: max 60 concurrent (all other tenants)

  Acme saturates THEIR bulkhead → Acme gets 429
  SmallCorp bulkhead unaffected

CIRCUIT BREAKER + RATE LIMIT COORDINATION:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  RDS circuit OPEN:
    → All tenants: POST /export returns 503 (not 429)
    → Queue exports in SQS for retry when circuit closes
    → Half-open: SELECT 1 probes only, 3 max per 60s

  Tenant rate limit exceeded:
    → That tenant: 429
    → Other tenants: unaffected
    → Circuit breaker: UNAFFECTED (don't conflate)

  Dashboard row (Grafana):
    Panel: rate_limit_rejected by tenant
    Panel: bulkhead_available by tenant
    Panel: circuit_breaker_state rds
    Panel: rds_connection_pool_used

PREVENTION CONTROLS:
━━━━━━━━━━━━━━━━━━

  1. Load test: simulate 500 sub-keys before any deploy
  2. CI check: every api_key must appear in usage plan table
  3. Cannot delete tenant aggregate limit without architecture review
  4. Runbook: Acme-class customer batch jobs require 24h notice
  5. Adaptive limit: when RDS p99 > 1s, reduce ALL tenant limits 50%
```

---

## Ops Sim: Northstar Seller API Token Flood

### Q1 - Layer & root cause

Global rate limits let one seller consume shared quota and hot-spot the limiter itself.

A strong answer separates the trigger from retry, cache, routing, or observability amplifiers and states the invariant that cannot be violated.

### Q2/Q3 - Evidence

- `api_requests_per_sec: 18k -> 210k`
- `seller_8844_share_of_requests: 72%`
- `redis_limiter_cpu: 94%`
- `limiter_key_ops global:seller-api=340k/sec`
- `checkout_api_p99_ms: 180 -> 1900`
- `gateway: limiter allow key=global:seller-api tenant=seller_8844`
- `export-job: retrying immediately`
- `checkout: request shed reason=gateway_thread_starvation`
- Config clue: `rate_limit_key: global:seller-api`
- Config clue: `burst_tokens: 100000`

### Q4 - Red herrings

Do not trust fleet averages, shallow health checks, or resource alerts that are not tied to the affected user slice. Downstream lag and retries may be symptoms to control, but they do not automatically identify the first cause.

### Q5/Q6 - Safe first 15 minutes

1. Declare severity, name the invariant, and assign subsystem owners.
2. Freeze new deploys, rollouts, rebalances, schema changes, or bulk replays touching the path.
3. Stop the active amplifier called out in the config/timeline.
4. Shed or degrade noncritical work before weakening checkout, payment, inventory, or tenant isolation.
5. Verify with the primary SLI, the scarce-resource metric, and the lag/error derivative.
6. Start an affected-record ledger for repair before any manual replay.

### Q7 - Bad fixes

- `block all seller API`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.
- `raise global bucket burst`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.
- `trust client backoff only`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.
- `share checkout and export pools`: widens blast radius, hides correctness risk, or converts recoverable lag into data loss/duplicates.

### Q8 - Capacity / blast radius

Quantify current usage, safe ceiling, growth rate, and time-to-exhaustion for queue/lag, connection or thread pools, disk/WAL/compaction, and affected business records. Scaling is only safe if the downstream dependency has headroom.

### Q9 - Correctness invariant

Accepted orders, money movement, inventory reservations, tenant isolation, and source-of-truth state must remain conservative. If the outcome is uncertain, mark it uncertain and reconcile instead of guessing.

### Q10 - Data repair

Use source-of-truth rows, stable idempotency keys, LSNs/offsets, and the incident window to define the repair set. Replay with duplicate suppression, throttle to downstream headroom, and record customer-visible corrections.

### Q11 - Durable fixes

- hierarchical tenant/user/endpoint quotas.
- local prefilters plus Redis counters.
- priority pools.
- retry-after enforcement.

Acceptance criteria: the old failure is reproduced in a drill, the new guardrail pages before customer impact, and the unsafe configuration cannot be enabled without review.

### Q12/Q13 - Alerting and runbook

Page on SLO burn, correctness failures, lag derivative, and scarce-resource exhaustion in the affected slice. By T+10 include incident commander, service owner, data/platform owner, product/business owner, support, and security/payments if trust or money is involved. Pre-authorized: stop unsafe rollouts, shed noncritical work, conservative fallback. Senior approval: durability downgrade, destructive repair, broad failover, or accepting derived data as truth.

---
