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

## Ops Sim: Northstar Seller API Sliding-Window Collapse

> Open only after attempting the learner-side drill.

### Executive diagnosis

The limiter keys on NAT IP and uses a global Redis hash tag. A top seller consumes the shared bucket, smaller sellers receive 429s, and Redis hot-slot latency makes the gateway fail open for writes.

A principal response separates the trigger from the amplifier and states the invariant before proposing capacity or repair. The answer should not say only "scale it" or "roll it back"; it must explain why this system failed this way.

### Evidence map

- `seller_api_429_rate{seller="small"}: 0.2% -> 37%`
- `seller_api_qps{seller="mega"}: 800 -> 18000`
- `redis_cmd_duration_seconds{cmd="EVALSHA",p99}: 0.004 -> 1.2`
- `rate_limiter_allowed_total{key="ip:203.0.113.7"}: +9M`
- `gateway_worker_queue_depth: 40 -> 6200`
- `quota_tokens_remaining{seller="mega"}: unknown`
- Config clue: `gateway.rate_limit_key: client_ip`
- Config clue: `tenant_quota.enabled: false`
- Red herring: a fleet average or generic health check that does not include the damaged slice.

### First 15 minutes: sequencing

1. Declare severity, name the invariant, and assign an incident commander.
2. Freeze deploys, config flips, schema changes, broad failovers, and bulk replay touching this path.
3. Stop the active amplifier before adding capacity: retry storms, unsafe repair, global fallback, bad routing, or telemetry blow-up.
4. Roll back or override the specific dangerous config while preserving source-of-truth writes.
5. Shed noncritical surfaces: dashboards, notifications, search, decorative metadata, analytics, or advisory enrichment as appropriate.
6. Verify with the sliced SLI and scarce-resource metric; do not declare recovery from a global average.
7. Start an affected-record ledger before any replay or customer-visible repair.

### Bad fixes

- `increase global limit`: rewards the noisy tenant and worsens fairness for smaller sellers.
- `ban the NAT IP`: punishes unrelated tenants sharing infrastructure instead of the abusive seller identity.
- `fail open on all writes`: optimizes conversion by violating money or write-safety invariants.
- `move limit checks after database writes`: lets expensive writes happen before admission control, so quota no longer protects the database.

### Capacity and blast radius

A principal answer gives at least one bound. Compute the affected slice, backlog or queue depth, derivative, safe downstream throughput, and time-to-exhaustion or time-to-drain. If those values are unknown, the safe move is to throttle and measure before scale/failover/replay.

Examples of the expected math:
- current backlog / safe drain rate = minimum repair duration
- free disk or pool headroom / growth rate = time-to-exhaustion
- affected tenants, SKUs, auctions, regions, orders, or carts from source-of-truth keys
- downstream provider/API/database quota that caps replay concurrency

### Repair and reconciliation

Source of truth: seller_id/app_id quotas and seller API write ledger.

Build the affected set from authoritative records in the incident window, not from cache, search, dashboards, or customer anecdotes alone. Repair must use stable idempotency or operation keys, be throttled to downstream headroom, and write an audit trail. Derived projections can be rebuilt after the invariant is safe.

### Durable fixes

- seller_id/app_id token buckets
- sharded limiter keys
- bounded local fallback
- separate read/write limiter policy

Acceptance criteria:
- The exact bad config from the drill is blocked or requires senior review.
- A staging drill reproduces the old failure and verifies safe rollback/replay.
- The dashboard contains the sliced SLI and the scarce-resource metric together.
- The alert fires before customer impact or before the scarce resource reaches exhaustion.

### Org and runbook

By T+10 include incident command, the owning service team, the relevant platform/data owner, product/business owner, and support. Add payments, security, finance, warehouse, seller-ops, or customer-success when money, trust, physical fulfillment, or enterprise promises are involved.

Pre-authorized: rollback bad config, pause unsafe repair, shed noncritical work, throttle retry/replay, quarantine unhealthy replicas/consumers/pods, and communicate degraded mode. Escalate: destructive state changes, durability downgrades, broad failover, consistency weakening, manual ledger/customer remediation outside policy, or accepting derived data as truth.

### Principal-depth checklist

- Root mechanism, trigger, and amplifier are distinct.
- Evidence uses real metric/config names from the drill.
- First action protects the invariant, not the prettiest graph.
- Bad fixes are rejected with concrete failure modes.
- Capacity math precedes scale/failover/replay.
- Repair has source of truth, idempotency, throttle, and audit.
- Durable fixes include alerts, tests, config guardrails, and ownership.

---


---
