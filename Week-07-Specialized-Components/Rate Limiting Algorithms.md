# Week 7, Topic 2 — Rate Limiting Algorithms

> Rate limiting is admission control: deciding which requests enter your system and which get turned away before they consume threads, connections, or downstream quota. This module covers every major algorithm (token bucket, leaky bucket, fixed/sliding windows), distributed implementations on Redis and DynamoDB, AWS edge limits (WAF, API Gateway, ALB), coordination with circuit breakers (Week 6), failure modes, and exact production configs.

---

## Learning Objectives

```
╔══════════════════════════════════════════════════════════════════╗
║   AFTER THIS TOPIC, YOU WILL BE ABLE TO:                         ║
╟──────────────────────────────────────────────────────────────────╢
║                                                                  ║
║   1. Explain token bucket, leaky bucket, fixed window,           ║
║      and sliding window algorithms — their math, burst           ║
║      behavior, memory cost, and correctness under clock          ║
║      skew                                                        ║
║                                                                  ║
║   2. Implement distributed rate limiting with Redis              ║
║      (Lua scripts, sliding window log, token bucket)             ║
║      and DynamoDB (conditional writes, TTL cleanup)              ║
║                                                                  ║
║   3. Configure AWS WAF rate-based rules, API Gateway             ║
║      throttling (account, stage, usage plan), and                ║
║      CloudFront + WAF at the edge — with exact JSON/YAML         ║
║                                                                  ║
║   4. Choose the right limit dimension: per-IP, per-API           ║
║      key, per-user, per-tenant, per-endpoint, global             ║
║                                                                  ║
║   5. Coordinate rate limits with circuit breakers,               ║
║      bulkheads, and backpressure (Week 6) so 429 at              ║
║      ingress does not fight open circuits downstream             ║
║                                                                  ║
║   6. Return correct HTTP semantics: 429 vs 503,                  ║
║      Retry-After, X-RateLimit-* headers, idempotent              ║
║      rejection vs partial failure                                ║
║                                                                  ║
║   7. Diagnose rate-limit incidents: false positives              ║
║      (NAT/shared IP), limit too low, Redis hot keys,             ║
║      clock drift, retry amplification against 429                ║
║                                                                  ║
║   8. Design multi-tier rate limiting: edge (WAF) →               ║
║      gateway (API GW) → service (app) → dependency               ║
║      (third-party API quota)                                     ║
╚══════════════════════════════════════════════════════════════════╝
```

**Prerequisite mental model.** Every request consumes capacity somewhere — CPU, DB connections, partner API quota, or dollars. Rate limiting is the valve that prevents one client (or one bug) from draining the tank for everyone else. It is not authentication, not authorization, and not a substitute for capacity planning — but without it, capacity planning fails at the first traffic spike.

---

## Wrong Mental Models (Destroy These First)

```
╔══════════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Rate limiting = blocking bad actors"                 ║
╟──────────────────────────────────────────────────────────────────────────╢
║   TOO NARROW. Rate limiting protects EVERYONE from overload —            ║
║   including your best customer during a flash sale, your own             ║
║   batch job that forgot to throttle, and a misconfigured                 ║
║   client retry loop. Security (WAF block lists) is a subset;             ║
║   fairness and capacity protection are the primary goals.                ║
╠══════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "429 means the user did something wrong"              ║
╟──────────────────────────────────────────────────────────────────────────╢
║   WRONG. HTTP 429 Too Many Requests is a CAPACITY signal, not            ║
║   a moral judgment. Well-behaved clients hit 429 when limits             ║
║   are too tight, NAT collapses many users into one IP, or                ║
║   a dependency quota is shared. Always include Retry-After               ║
║   and rate-limit headers so clients can backoff correctly.               ║
╠══════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "Token bucket and leaky bucket are the same"          ║
╟──────────────────────────────────────────────────────────────────────────╢
║   WRONG. Token bucket ALLOWS BURST up to bucket capacity then            ║
║   enforces average rate. Leaky bucket SMOOTHS output — excess            ║
║   requests queue (or drop), never depart faster than leak rate.          ║
║   Token bucket: "save up credits, spend in bursts."                      ║
║   Leaky bucket: "steady drip, no bursts out the spout."                  ║
╠══════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "Fixed window is good enough"                         ║
╟──────────────────────────────────────────────────────────────────────────╢
║   DANGEROUSLY INCOMPLETE. Fixed window allows 2× burst at                ║
║   window boundaries (999 req at 0:59 + 999 req at 1:00 =                 ║
║   1998 in 2 seconds with limit 1000/min). Sliding window fixes           ║
║   this at higher memory/Redis cost. Know the boundary bug.               ║
╠══════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "One global limit protects the service"               ║
╟──────────────────────────────────────────────────────────────────────────╢
║   WRONG. A single global counter lets one noisy tenant consume           ║
║   the entire budget. Production needs layered limits:                    ║
║   global safety ceiling + per-tenant + per-user + per-endpoint.          ║
║   The expensive endpoint (/search, /export) needs tighter limits         ║
║   than health checks.                                                    ║
╠══════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #6: "Redis INCR is atomic, so distributed RL is easy"     ║
╟──────────────────────────────────────────────────────────────────────────╢
║   OVERSIMPLIFIED. INCR without TTL discipline leaks keys forever.        ║
║   INCR + EXPIRE is not atomic in one round trip unless scripted.         ║
║   Hot keys on viral content saturate a single Redis shard.               ║
║   Fail-open vs fail-closed when Redis is down is a product decision      ║
║   that must be explicit — defaulting to "allow all" causes outages.      ║
╠══════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #7: "ALB rate-limits my traffic"                          ║
╟──────────────────────────────────────────────────────────────────────────╢
║   WRONG. Application Load Balancers do NOT implement request             ║
║   rate limiting. They have connection limits, idle timeouts,             ║
║   and HTTP desync protections — but per-client RPS throttling            ║
║   belongs at WAF, API Gateway, CloudFront, or your application.          ║
╠══════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #8: "Rate limit and circuit breaker are redundant"        ║
╟──────────────────────────────────────────────────────────────────────────╢
║   WRONG. They operate at different layers and timescales:                ║
║   Rate limit = PROACTIVE admission control ("you may not enter").        ║
║   Circuit breaker = REACTIVE fail-fast ("dependency is sick,             ║
║   stop calling it"). Rate limit at ingress protects your                 ║
║   fleet; circuit breaker protects dependencies from retry storms.        ║
║   Both must agree on 429/503 semantics and Retry-After.                  ║
╚══════════════════════════════════════════════════════════════════════════╝
```

---

## Core Teaching

### Why Rate Limiting Exists

```
THE FUNDAMENTAL PROBLEM: UNBOUNDED DEMAND

  Your payment API handles 2,000 RPS comfortably.
  A marketing email goes out. 500,000 users click "Pay Now" in 60 seconds.
  That's 8,333 RPS average — 4× capacity.

  Without rate limiting:
    → Thread pools saturate (Week 6 bulkheads)
    → DB connection pool exhausted
    → Latency climbs from 50ms to 30s
    → Clients retry (3× amplification)
    → Total load: 8,333 × 3 = 25,000 RPS equivalent
    → Cascading failure across checkout, fraud, notifications

  With rate limiting at ingress:
    → First 2,000 RPS accepted per second
    → Excess receives HTTP 429 + Retry-After: 1
    → Well-behaved clients backoff (jitter)
    → Origin stays at 2,000 RPS, p99 latency stable
    → Some users wait 2-3 seconds — acceptable vs total outage

WHAT RATE LIMITING IS NOT:
━━━━━━━━━━━━━━━━━━━━━━━━

  ✗ Authentication        — knowing WHO the client is
  ✗ Authorization         — knowing WHAT they may do
  ✗ Quota/billing         — monthly API call entitlements (related but separate)
  ✗ DDoS absorption       — WAF + CDN + scrubbing centers at scale
  ✗ Load balancing        — distributing accepted requests across instances

WHAT RATE LIMITING IS:
━━━━━━━━━━━━━━━━━━━━━

  ✓ Admission control     — reject before work starts
  ✓ Fairness              — no single client monopolizes capacity
  ✓ Cost protection       — third-party APIs billed per call
  ✓ Abuse mitigation      — credential stuffing, scraping, brute force
  ✓ Stability under spike — graceful degradation vs collapse
```

### The Rate Limiting Stack (Multi-Tier)

```
TYPICAL AWS PRODUCTION STACK:

  Internet
     │
     ▼
  ┌───────────────────────────────────────────────────────────┐
  │  CloudFront + AWS WAF (edge)                              │
  │  → Geo block, bot control, rate-based rule per IP (5 min) │
  │  → Blocks before traffic hits origin region               │
  └──────────────────────────┬────────────────────────────────┘
                             │
                             ▼
  ┌───────────────────────────────────────────────────────────┐
  │  API Gateway / ALB + WAF (regional)                       │
  │  → API GW: stage throttle + usage plan per API key        │
  │  → WAF on ALB: rate-based + custom rules                  │
  └──────────────────────────┬────────────────────────────────┘
                             │
                             ▼
  ┌───────────────────────────────────────────────────────────┐
  │  Service mesh / sidecar (Envoy, optional)                 │
  │  → Local rate limit filter per route                      │
  └──────────────────────────┬────────────────────────────────┘
                             │
                             ▼
  ┌───────────────────────────────────────────────────────────┐
  │  Application (Redis-backed sliding window / token bucket) │
  │  → Per-user, per-tenant, per-endpoint granularity         │
  └──────────────────────────┬────────────────────────────────┘
                             │
                             ▼
  ┌───────────────────────────────────────────────────────────────┐
  │  Outbound dependency limits (bulkhead + partner quota)        │
  │  → Stripe, SendGrid, OpenAI tokens/min                        │
  └───────────────────────────────────────────────────────────────┘

RULE: Limits get STRICTER and MORE GRANULAR as you go deeper.
      Edge limits are coarse (IP, cheap). App limits are fine (user ID).
```

### Algorithm 1: Token Bucket

```
TOKEN BUCKET — THE MOST COMMON PRODUCTION ALGORITHM
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CONCEPT:
  A bucket holds at most B tokens (burst capacity).
  Tokens arrive at rate R per second (refill rate).
  Each request consumes 1 token (or N for expensive ops).
  If bucket empty → reject (429) or queue (leaky variant).

PARAMETERS:
  capacity (B)  — maximum burst size
  refill_rate (R) — tokens added per second (steady-state limit)

STATE:
  tokens: float (current count, 0..B)
  last_refill: timestamp

REFILL ON EACH REQUEST:
  now = current_time()
  elapsed = now - last_refill
  tokens = min(B, tokens + elapsed * R)
  last_refill = now

ALLOW REQUEST:
  if tokens >= cost:
    tokens -= cost
    return ALLOW
  else:
    return DENY

ASCII DIAGRAM:

  Refill pipe (+R/sec)
       │
       ▼
  ┌─────────────────┐
  │  Token Bucket   │  capacity = B (e.g., 100 tokens)
  │  ████████░░░░   │  current = 8 tokens
  └────────┬────────┘
           │ 1 token per request
           ▼
        Request ──► ALLOW if token available
                 ──► DENY  if empty

BEHAVIOR OVER TIME (R=10/sec, B=50):

  Idle 5 sec  → bucket fills to 50 (capped)
  Burst 50 req instantly → all allowed, bucket = 0
  Request 51 → DENY (must wait for refill)
  After 0.1 sec → 1 token → 1 request allowed
  Steady 10 req/sec → sustainable indefinitely

WHY TOKEN BUCKET WINS IN PRODUCTION:
  → Allows natural HTTP burstiness (browser opens 6 parallel connections)
  → Smooth average rate with configurable burst tolerance
  → Used by: AWS API Gateway burst/rate model, many SDK "retry budgets"
  → Simple to explain to API consumers: "100 burst, 10/sec sustained"

MATH — SUSTAINED RATE vs BURST:
  Sustained throughput ≤ R
  Maximum burst ≤ B
  Time to recover full bucket after empty: B / R seconds

EXAMPLE CONFIG (payments API):
  R = 50 req/sec per merchant API key
  B = 100 (allow 2× burst for 2 seconds)
  Interpretation: merchant can send 100 requests immediately,
  then must stay at 50/sec or wait for refill
```

#### Token Bucket — Pseudocode and Edge Cases

```python
class TokenBucket:
    def __init__(self, capacity: float, refill_rate: float):
        self.capacity = capacity
        self.refill_rate = refill_rate  # tokens per second
        self.tokens = capacity
        self.last_refill = time.monotonic()

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

    def allow(self, cost: float = 1.0) -> bool:
        self._refill()
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False

    def retry_after_seconds(self, cost: float = 1.0) -> float:
        """How long until `cost` tokens available."""
        self._refill()
        if self.tokens >= cost:
            return 0.0
        deficit = cost - self.tokens
        return deficit / self.refill_rate
```

```
EDGE CASES:
━━━━━━━━━━━

  1. CLOCK SKEW (distributed):
     Use monotonic clocks locally; in Redis use TIME or server clock.
     Never rely on client timestamps for refill.

  2. FLOAT DRIFT:
     Store tokens as integer micro-units (tokens × 1_000_000) in Redis
     to avoid floating-point races.

  3. MULTI-COST REQUESTS:
     /export may cost 10 tokens; /health costs 0.01.
     Weighted token bucket prevents cheap endpoints from starving
     expensive capacity planning.

  4. WARM START:
     New API key starts with full bucket (B) — generous but can spike.
     Alternative: start at B/2 to prevent immediate burst abuse.
```

### Algorithm 2: Leaky Bucket

```
LEAKY BUCKET — SMOOTH OUTPUT, STRICT DEPARTURE RATE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CONCEPT:
  Requests enter a queue (bucket).
  Queue leaks at fixed rate R (one request processed per 1/R seconds).
  If queue full → reject incoming (or drop oldest).

TWO VARIANTS:

  Variant A — Queue + worker (traffic shaping):
    Accept requests into queue up to capacity Q.
    Worker drains queue at rate R.
    Output to backend is perfectly smooth at R.

  Variant B — No queue (drop on overflow):
    Same as token bucket deny mode but refill is continuous leak metaphor.
    Often implemented identically to token bucket with zero burst.

ASCII DIAGRAM:

  Requests in (bursty)
       │
       ▼
  ┌─────────────────┐
  │  Queue (Q max)  │  ████░░░░░░  4/10 slots
  └────────┬────────┘
           │ leak at R=2 req/sec
           ▼
      Backend (smooth 2 RPS)

TOKEN BUCKET vs LEAKY BUCKET:

  ┌────────────────────┬─────────────────────┬─────────────────────┐
  │ Property           │ Token Bucket        │ Leaky Bucket        │
  ├────────────────────┼─────────────────────┼─────────────────────┤
  │ Burst at output    │ YES (up to B)       │ NO (smooth R)       │
  │ Queuing            │ Usually no queue    │ Often queues        │
  │ Backend protection │ Moderate            │ Strong (smooth)     │
  │ Latency under burst│ Low (immediate)     │ Higher (queued)     │
  │ Typical use        │ API rate limits     │ Network shaping     │
  └────────────────────┴─────────────────────┴─────────────────────┘

WHEN TO USE LEAKY BUCKET:
  → Protecting a downstream with hard throughput cap (legacy mainframe,
    partner webhook endpoint that returns 503 on any burst)
  → Video encoding pipeline — frame processing at fixed rate
  → When you WANT to absorb burst into queue rather than reject

WHEN NOT TO USE:
  → Public HTTP APIs where queueing increases tail latency unpredictably
  → Serverless (Lambda) — no persistent queue between invocations
```

### Algorithm 3: Fixed Window Counter

```
FIXED WINDOW — SIMPLEST, BOUNDARY BUG
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CONCEPT:
  Divide time into windows of size W (e.g., 60 seconds).
  Count requests per key per window.
  If count > limit L → reject.

IMPLEMENTATION:
  key = f"{client_id}:{floor(unix_time / W)}"
  count = INCR(key)
  if count == 1: EXPIRE(key, W)
  if count > L: DENY

ASCII:

  Window 1 (0:00-0:59)     Window 2 (1:00-1:59)
  ┌──────────────────┐       ┌──────────────────┐
  │ count: 847/1000  │       │ count: 12/1000   │
  └──────────────────┘       └──────────────────┘

THE BOUNDARY BUG (critical interview + production topic):

  Limit: 1000 requests per minute

  0:00:00 - 0:00:59 → 1000 requests (at limit)
  0:01:00 - 0:01:01 → 1000 requests (new window, at limit)

  In 2 seconds (0:59 - 1:01): 2000 requests allowed = 2× limit

  ╔══════════════════════════════════════════════════════════════╗
  ║   Requests/sec                                               ║
  ║   1000│     ╱╲                                               ║
  ║       │    ╱  ╲                                              ║
  ║    500│───╱    ╲───                                          ║
  ║       │  ↑ window boundary spike                             ║
  ║       ╰────────────────────────                              ║
  ╚══════════════════════════════════════════════════════════════╝

PROS:
  → One Redis key per window per client — minimal memory
  → Extremely fast (single INCR)
  → Good enough for low-stakes limits (login attempt counter)

CONS:
  → 2× burst at boundaries
  → Uneven user experience at minute rollovers

MITIGATION WITHOUT FULL SLIDING WINDOW:
  → Dual window: check current AND previous window, weight overlap
    (see Sliding Window Counter below)
```

### Algorithm 4: Sliding Window Log

```
SLIDING WINDOW LOG — PRECISE, MEMORY EXPENSIVE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CONCEPT:
  Store timestamp of every request in the window.
  On new request: remove entries older than (now - W), count remainder.
  If count >= L → reject; else append now.

REDIS IMPLEMENTATION (sorted set):
  key = f"rl:{client_id}"
  ZREMRANGEBYSCORE key 0 (now - W)
  count = ZCARD key
  if count >= L: DENY
  ZADD key now now  # score=member=timestamp
  EXPIRE key W

ACCURACY: Perfect — true sliding window, no boundary bug.

COST:
  O(log N) per request, N = requests in window
  Memory: 8 bytes × L per client (if at limit)
  At L=1000/min and 1M active clients → significant Redis RAM

WHEN TO USE:
  → Strict fairness requirements (OAuth token endpoint, financial APIs)
  → Small L (e.g., 10 login attempts per 15 min)
  → High-value endpoints where boundary bug is unacceptable

WHEN NOT TO USE:
  → 100k RPS global traffic with L=10000 — use approximate counter
```

### Algorithm 5: Sliding Window Counter (Hybrid)

```
SLIDING WINDOW COUNTER — BEST BALANCE FOR MOST APIS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CONCEPT (Redis/Gateway common pattern):
  Maintain TWO fixed window counters: current and previous.
  Weight previous window by overlap fraction.

FORMULA:
  elapsed_in_current = now % W
  overlap_fraction = (W - elapsed_in_current) / W
  estimated_count = current_count + previous_count * overlap_fraction

  if estimated_count >= L: DENY

EXAMPLE (W=60s, L=1000):
  Previous window (minute 1): 800 requests
  Current window (minute 2, at second 15): 300 requests
  Overlap fraction for previous: (60-15)/60 = 0.75
  Estimated: 300 + 800 × 0.75 = 900 → ALLOW

  At second 55 of current window:
  Estimated: 700 + 800 × (5/60) = 700 + 67 = 767 → ALLOW

  At second 59 with current=500:
  Estimated: 500 + 800 × (1/60) ≈ 513 — still smooth

ACCURACY: ~99% for most traffic; slight over-count possible, never 2× boundary.

MEMORY: 2 keys per client per window granularity — cheap at scale.

THIS IS WHAT AWS API GATEWAY THROTTLE APPROXIMATES INTERNALLY
(combined with token bucket burst).
```

### Distributed Rate Limiting — The Hard Parts

```
PROBLEM: 50 API servers, each with local counter → limit × 50

SOLUTION OPTIONS:

  ┌────────────────────────┬──────────────┬─────────────┬──────────────┐
  │ Approach               │ Accuracy     │ Latency     │ Failure mode │
  ├────────────────────────┼──────────────┼─────────────┼──────────────┤
  │ Central Redis          │ Exact*       │ +1-3ms RTT  │ Redis down?  │
  │ DynamoDB conditional   │ Strong       │ +5-20ms     │ Throttle $   │
  │ Local + sync (gossip)  │ Approximate  │ ~0ms local  │ Drift        │
  │ Sticky + local counter │ Per-node     │ ~0ms        │ Uneven LB    │
  └────────────────────────┴──────────────┴─────────────┴──────────────┘
  *Exact with single Redis primary; race at extreme QPS without Lua

FAIL-OPEN vs FAIL-CLOSED:

  Fail-open (Redis down → allow all):
    → Availability favored; outage risk if abuse/spike during Redis failure
    → Use when: internal service, low abuse risk, Redis is multi-AZ cluster

  Fail-closed (Redis down → reject all):
    → Safety favored; brief 503/429 storm during Redis failover
    → Use when: public API, billing protection, known attack surface

  PRODUCTION HYBRID:
    → Fail-open with EMERGENCY global limit at WAF (always up)
    → App-level fail-closed for expensive endpoints only
    → Document the decision in runbook

HOT KEY PROBLEM:

  Viral tweet links to /api/v1/feed?item=12345
  All users share same "resource limit key"
  Single Redis shard melts at 500k ops/sec

  FIXES:
    → Shard key: rl:{id}:{random(0..15)} — 16 counters, limit/16 each
    → Local cache of decision for 100ms (accept slight over-admission)
    → Rate limit per user, not per resource URL

CLOCK SKEW ACROSS NODES:
  Use Redis TIME or DynamoDB timestamps as source of truth.
  Never compare wall clocks across EC2 instances for window boundaries.
```

### Redis Distributed Rate Limiting — Production Patterns

#### Pattern A: Fixed Window with Atomic INCR (Lua)

```lua
-- KEYS[1] = rate limit key
-- ARGV[1] = limit
-- ARGV[2] = window seconds
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[2])
end
if current > tonumber(ARGV[1]) then
  return 0  -- deny
end
return 1  -- allow
```

```
WHY LUA:
  INCR then EXPIRE as two separate commands → race if process crashes
  between them → key without TTL → memory leak forever.
  Lua script executes atomically on Redis primary.

KEY NAMING:
  rl:fixed:{tenant_id}:{endpoint}:{window_epoch}
  Example: rl:fixed:acme:POST_payments:28901234

  window_epoch = floor(unix_time / W) — bucket identifier
```

#### Pattern B: Sliding Window Log (Sorted Set Lua)

```lua
-- Sliding window log — precise
-- KEYS[1] = key, ARGV[1] = now_ms, ARGV[2] = window_ms, ARGV[3] = limit
local window_start = ARGV[1] - ARGV[2]
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, window_start)
local count = redis.call('ZCARD', KEYS[1])
if count >= tonumber(ARGV[3]) then
  return 0
end
redis.call('ZADD', KEYS[1], ARGV[1], ARGV[1])
redis.call('PEXPIRE', KEYS[1], ARGV[2])
return 1
```

#### Pattern C: Token Bucket in Redis (Hash + Lua)

```lua
-- Token bucket stored as hash: tokens, last_refill_ms
-- ARGV: now_ms, capacity, refill_rate_per_ms, cost
local bucket = redis.call('HMGET', KEYS[1], 'tokens', 'last_refill')
local tokens = tonumber(bucket[1]) or tonumber(ARGV[2])
local last = tonumber(bucket[2]) or tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local rate = tonumber(ARGV[3])
local now = tonumber(ARGV[1])
local cost = tonumber(ARGV[4])

local elapsed = now - last
tokens = math.min(capacity, tokens + elapsed * rate)
last = now

if tokens >= cost then
  tokens = tokens - cost
  redis.call('HMSET', KEYS[1], 'tokens', tokens, 'last_refill', last)
  redis.call('PEXPIRE', KEYS[1], math.ceil(capacity / rate) + 1000)
  return 1
else
  redis.call('HMSET', KEYS[1], 'tokens', tokens, 'last_refill', last)
  return 0
end
```

```
ELASTICACHE DEPLOYMENT NOTES:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Cluster mode enabled:
    → Use hash tags: rl:{tenant_id}:bucket — co-locate tenant keys
    → Hot tenant still hot — consider dedicated shard or local cache

  Multi-AZ with automatic failover:
    → Failover ~1-30 seconds
    → Decide fail-open vs fail-closed BEFORE failover happens
    → Use connection pooling (redis-py, ioredis) with retry on MOVED/ASK

  Memory sizing:
    Sliding log at 1M users × 100 entries × 16 bytes ≈ 1.6 GB minimum
    Token bucket hash ≈ 64 bytes × 1M users ≈ 64 MB

  Eviction policy:
    → NEVER use allkeys-lru on rate limit data unless you accept silent limit loss
    → Use noeviction + memory alerts OR volatile-ttl with EXPIRE on every key
```

### DynamoDB Rate Limiting

```
WHEN DYNAMODB OVER REDIS:
  → Serverless architecture, no ElastiCache cluster to operate
  → Rate limit state must survive region-wide Redis failure
  → Already on DynamoDB for API keys / tenant config — colocate state
  → Lower QPS per key (<1000/sec per partition) acceptable

PARTITION KEY DESIGN:
  pk = TENANT#acme#ENDPOINT#payments
  sk = WINDOW#202607061430  (minute granularity for fixed window)

ITEM:
  {
    "pk": "TENANT#acme#ENDPOINT#payments",
    "sk": "WINDOW#202607061430",
    "count": 847,
    "ttl": 1751816400
  }

CONDITIONAL WRITE (atomic increment with ceiling):

  UpdateItem:
    Key: { pk, sk }
    UpdateExpression: "ADD #c :one"
    ConditionExpression: "attribute_not_exists(#c) OR #c < :limit"
    ExpressionAttributeNames: { "#c": "count" }
    ExpressionAttributeValues: { ":one": 1, ":limit": 1000 }

  ConditionalCheckFailedException → DENY (429)

  FIRST REQUEST IN WINDOW:
    Use UpdateItem with if_not_exists(#c, :zero) + ADD

TTL ATTRIBUTE:
  Enable TTL on `ttl` field — auto-delete old windows
  Cost: zero manual cleanup jobs

TOKEN BUCKET ON DYNAMODB (less common):
  Single item per client: tokens, last_refill
  UpdateItem with condition on version (optimistic locking)
  Higher conflict rate at high QPS — prefer Redis for token bucket

THROTTLING:
  DynamoDB on-demand handles bursts; provisioned needs capacity planning
  Hot partition on single global counter → split counters:

    pk = GLOBAL#counter#shard_{hash(request_id) % 16}
    effective_limit = sum(shards) / 16 per shard limit

LATENCY:
  5-15ms typical UpdateItem
  Too slow for inline per-request on 50k RPS without edge pre-filter
  Pattern: WAF coarse filter → DynamoDB fine limit
```

### HTTP Semantics — 429, 503, Headers

```
STATUS CODE CHOOSER:

  HTTP 429 Too Many Requests
    → Client exceeded a rate limit or quota
    → Client SHOULD retry after Retry-After
    → Use for: API usage plans, per-user limits, login throttling

  HTTP 503 Service Unavailable
    → Server temporarily unable to handle request (overload, maintenance)
    → Use for: global admission control, circuit breaker open, bulkhead full
    → Include Retry-After when transient

  DO NOT USE 403 for rate limiting
    → 403 implies authorization failure — clients won't backoff correctly

STANDARD HEADERS (de facto, IETF draft RateLimit headers):

  RateLimit-Limit: 1000
  RateLimit-Remaining: 742
  RateLimit-Reset: 1751816460      (Unix timestamp when window resets)
  Retry-After: 12                   (seconds until retry allowed)

  Legacy (Stripe, GitHub, many APIs):
  X-RateLimit-Limit: 5000
  X-RateLimit-Remaining: 4997
  X-RateLimit-Reset: 1751816460

RESPONSE BODY (JSON API example):

  HTTP/1.1 429 Too Many Requests
  Content-Type: application/json
  Retry-After: 2
  RateLimit-Limit: 100
  RateLimit-Remaining: 0
  RateLimit-Reset: 1751816462

  {
    "error": {
      "code": "rate_limit_exceeded",
      "message": "Rate limit of 100 requests per minute exceeded.",
      "retry_after_seconds": 2
    }
  }

CLIENT CONTRACT:
  → Honor Retry-After with FULL JITTER (Week 6): sleep random(0, Retry-After)
  → Do NOT retry 429 synchronously in a tight loop (retry storm)
  → Exponential backoff on repeated 429
```

### Coordination with Circuit Breakers (Week 6)

```
THE RESILIENCE STACK — RATE LIMITING'S PLACE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  From Week 6 "How the Five Patterns Compose":

  Ingress request
       │
       ▼
  ┌─────────────────┐
  │ Rate limit /    │  ← THIS MODULE (proactive shed)
  │ admission ctrl  │
  └────────┬────────┘
           ▼
  ┌─────────────────┐
  │ Deadline check  │
  └────────┬────────┘
           ▼
  ┌─────────────────┐
  │ Circuit breaker │  ← Week 6 (reactive fail-fast)
  └────────┬────────┘
           ▼
  ┌─────────────────┐
  │ Bulkhead        │
  └────────┬────────┘
           ▼
       Dependency

COORDINATION RULES:
━━━━━━━━━━━━━━━━

  1. INGRESS 429 vs DOWNSTREAM CIRCUIT OPEN:
     Circuit open on payments-svc → checkout returns 503 (degraded path)
     NOT 429 — user did not exceed THEIR limit; dependency is sick.
     Mixing these confuses client SDKs and monitoring.

  2. HALF-OPEN PROBING MUST BE RATE-LIMITED (Week 6 LO #1):
     Circuit transitions OPEN → HALF-OPEN
     Allow only N probe requests per interval (e.g., 5 per 10 sec)
     Without probe rate limit, half-open instantly re-overloads dependency

  3. RETRY BUDGET AT GATEWAY (Week 6 Pattern 3):
     Normal: 10,000 req/min
     Retry budget: 1,000 req/min (tracked via X-Retry-Attempt header)
     Retries against 429 must consume retry budget, not normal budget

  4. BACKPRESSURE SIGNAL CHAIN:
     Dependency returns 429 (partner API, e.g., SendGrid)
       → Service backs off (exponential + jitter)
       → Circuit breaker counts 429 as failure OR slow-call (config choice)
       → Ingress rate limit to clients INDEPENDENT of partner 429
     DO NOT propagate partner 429 as client 429 unless quota is shared

  5. BULKHEAD + RATE LIMIT COMPOSITION:
     Bulkhead: max 50 concurrent calls to fraud-svc
     Rate limit: max 200 calls/sec to fraud-svc
     Both can trigger — bulkhead full → 503, rate limit → 429
     Document which fires first in your stack

  6. LOAD SHEDDING HIERARCHY (Week 6):
     Gateway rate limit (proactive)
     Service shed when queue depth > threshold (reactive)
     Circuit breaker stop calling downstream (reactive)
     All three may return 429/503 — metric labels must distinguish layer

METRIC LABELS (mandatory for incident debug):

  rate_limit_rejected_total{layer="waf", dimension="ip"}
  rate_limit_rejected_total{layer="api_gateway", dimension="api_key"}
  rate_limit_rejected_total{layer="app", dimension="user_id"}
  circuit_breaker_state{dependency="payments-svc"}
  bulkhead_rejected_total{pool="fraud-check"}
```

---

## Concrete Examples

### Example 1: AWS WAF Rate-Based Rule (CloudFront + ALB)

```
SCENARIO: Public e-commerce site, block IPs exceeding 2000 req / 5 min

AWS WAF RATE-BASED RULE BEHAVIOR:
  → Aggregates by source IP (or forwarded IP with custom header)
  → Evaluation window: 5 minutes (fixed by AWS, not configurable)
  → When count > threshold → BLOCK (or COUNT for shadow mode)
  → Automatically clears when rate drops — no manual unblock for most cases

CLOUDFORMATION (exact config):

  RateBasedRule:
    Type: AWS::WAFv2::RuleGroup
    Properties:
      Name: rate-limit-per-ip
      Scope: CLOUDFRONT
      Capacity: 50
      Rules:
        - Name: BlockHighVolumeIPs
          Priority: 1
          Statement:
            RateBasedStatement:
              Limit: 2000
              AggregateKeyType: IP
          Action:
            Block: {}
          VisibilityConfig:
            SampledRequestsEnabled: true
            CloudWatchMetricsEnabled: true
            MetricName: RateLimitBlockPerIP

CLI — CREATE WEB ACL WITH RATE RULE:

  aws wafv2 create-web-acl \
    --name ecommerce-edge-acl \
    --scope CLOUDFRONT \
    --default-action Allow={} \
    --rules '[{
      "Name": "RateLimit2000Per5Min",
      "Priority": 0,
      "Statement": {
        "RateBasedStatement": {
          "Limit": 2000,
          "AggregateKeyType": "IP"
        }
      },
      "Action": {"Block": {}},
      "VisibilityConfig": {
        "SampledRequestsEnabled": true,
        "CloudWatchMetricsEnabled": true,
        "MetricName": "RateLimitBlock"
      }
    }]' \
    --visibility-config SampledRequestsEnabled=true,CloudWatchMetricsEnabled=true,MetricName=ecommerceWAF \
    --region us-east-1

IMPORTANT LIMITS:
  → Minimum rate limit: 100 (values below rejected)
  → Scope DOWNSTREAM (regional WAF on ALB): same 5-minute window
  → Rate-based rules consume WAF capacity units (WCU)
  → COUNT action first in production — observe false positives from NAT

NAT FALSE POSITIVE:
  5000 users behind carrier-grade NAT share one IP
  → 2000/5min may block innocent users
  → Mitigation: higher threshold at edge, finer limits at app (API key/user)
```

### Example 2: API Gateway Throttling (REST API)

```
API GATEWAY THROTTLE MODEL = TOKEN BUCKET
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  rate  — steady-state requests per second
  burst — maximum concurrent bucket capacity

  Account-level defaults (REST API):
    Steady: 10,000 RPS across all APIs in region
    Burst:  5,000 (can exceed steady briefly)

  Per-stage overrides (deployed API):
    Default: inherit account pool OR set stage limits

  Per-method overrides:
    GET /health  — high burst (cheap)
    POST /payments — low burst (expensive)

STAGE-LEVEL CONFIG (AWS CLI):

  aws apigateway update-stage \
    --rest-api-id abc123xyz \
    --stage-name prod \
    --patch-operations \
      op=replace,path=/throttle/rateLimit,value=5000 \
      op=replace,path=/throttle/burstLimit,value=2500

METHOD-LEVEL CONFIG:

  aws apigateway update-method \
    --rest-api-id abc123xyz \
    --resource-id rsrc456 \
    --http-method POST \
    --patch-operations \
      op=replace,path=/throttle/rateLimit,value=100 \
      op=replace,path=/throttle/burstLimit,value=50

USAGE PLAN (per API key — SaaS pattern):

  aws apigateway create-usage-plan \
    --name enterprise-tier \
    --throttle burstLimit=500,rateLimit=200 \
    --quota limit=1000000,period=MONTH \
    --api-stages apiId=abc123xyz,stage=prod

  Client sends: x-api-key: {key}
  Gateway enforces plan limits BEFORE Lambda/HTTP integration

429 RESPONSE FROM API GATEWAY:

  { "message": "Too Many Requests" }

  Headers: x-amzn-ErrorType: TooManyRequestsException
  No Retry-After by default — client must implement backoff

WORKED EXAMPLE — WILL I GET THROTTLED?

  Stage: rate=100, burst=200
  Client sends 200 requests instantly → all succeed (burst)
  Client sends 201st instantly → 429
  Client sends 100/sec sustained → succeeds (rate=100)
  Client idle 10 sec → bucket refills to 200 → burst again available
```

### Example 3: Application-Level Redis Limit (Node.js / Express)

```javascript
const REDIS_KEY = (userId, window) => `rl:sw:${userId}:${window}`;

const SLIDING_WINDOW_LUA = `
  local current_key = KEYS[1]
  local previous_key = KEYS[2]
  local limit = tonumber(ARGV[1])
  local weight = tonumber(ARGV[2])
  local window = tonumber(ARGV[3])
  local current = tonumber(redis.call('GET', current_key) or '0')
  local previous = tonumber(redis.call('GET', previous_key) or '0')
  local estimate = current + previous * weight
  if estimate >= limit then return 0 end
  redis.call('INCR', current_key)
  redis.call('EXPIRE', current_key, window * 2)
  return 1
`;

async function rateLimitMiddleware(req, res, next) {
  const userId = req.auth.sub;
  const W = 60, L = 1000;
  const now = Math.floor(Date.now() / 1000);
  const window = Math.floor(now / W);
  const elapsed = now % W;
  const weight = (W - elapsed) / W;
  const allowed = await redis.eval(
    SLIDING_WINDOW_LUA, 2,
    REDIS_KEY(userId, window), REDIS_KEY(userId, window - 1),
    L, weight, W
  );
  if (!allowed) {
    res.set('Retry-After', String(W - elapsed));
    return res.status(429).json({ error: 'rate_limit_exceeded' });
  }
  next();
}
```

### Example 4: ALB — What It Does and Does Not Do

```
ALB DOES NOT provide per-client request rate limiting.

ALB LIMITS THAT EXIST (not rate limiting):
  → Max targets per ALB: 1000
  → Idle timeout: default 60s (configurable 1-4000s)
  → LCU scaling — billing/capacity unit, not a rate cap

HOW TO RATE LIMIT TRAFFIC TO ALB:
  Option A: AWS WAF in front of ALB (regional Web ACL)
  Option B: CloudFront → ALB (edge WAF)
  Option C: Application middleware (Redis, Envoy sidecar)
  Option D: API Gateway → HTTP integration → ALB

  aws wafv2 associate-web-acl \
    --web-acl-arn arn:aws:wafv2:us-east-1:123456789012:regional/webacl/ecommerce-alb-acl/abc \
    --resource-arn arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/prod-alb/50dc6c495c0c9188
```

### Example 5: Third-Party API Quota (Outbound Rate Limit)

```
OUTBOUND PATTERN — TOKEN BUCKET + CIRCUIT BREAKER:

  stripeLimiter = TokenBucket(rate=90, capacity=100)

  if not stripeLimiter.allow():
    return 503 with Retry-After
  response = await stripe.charges.create(...)
  if response.status == 429:
    circuitBreaker.recordFailure()
    throw RateLimitError(stripe)

  5 consecutive Stripe 429 → circuit OPEN
  Half-open: 3 probe calls per minute (rate-limited probes)
```

---

## Production Patterns

### Pattern 1: Layered Rate Limiting (Defense in Depth)

```
TYPICAL SAAS API — THREE LAYERS:

  Layer 1 — WAF (edge):
    10,000 req / 5 min / IP (DDoS absorption, scrapers)
    Cost: ~$0 marginal per request
    Granularity: coarse

  Layer 2 — API Gateway (usage plan):
    Enterprise API key: 200 RPS, burst 500
    Free tier API key: 10 RPS, burst 20
    Cost: gateway invocation fee
    Granularity: per customer contract

  Layer 3 — Application (Redis):
    Per-user within tenant: 50 RPS
    Per-endpoint weights: POST /export costs 10× GET /status
    Cost: Redis RTT ~1ms per request
    Granularity: finest

WHY THREE LAYERS:
  WAF blocks attack traffic before it bills you for Lambda
  Gateway enforces commercial contract without app code deploy
  App enforces fair-use within a tenant (one user hogging quota)

FAILURE ISOLATION:
  WAF misconfig → tune threshold, COUNT mode first
  Gateway throttle → customer sees 429, your ECS CPU unaffected
  Redis down → fail-open at app OR fail-closed on expensive routes only
```

### Pattern 2: Rate Limit Key Selection

```
DIMENSION CHOOSER:

  ┌─────────────────────┬────────────────────┬─────────────────────────┐
  │ Dimension           │ Best for           │ Caveat                  │
  ├─────────────────────┼────────────────────┼─────────────────────────┤
  │ Source IP           │ Anonymous public   │ NAT collision           │
  │ API key             │ B2B SaaS partners  │ Key sharing/leaks       │
  │ User ID (JWT sub)   │ Authenticated API  │ Requires auth first     │
  │ Tenant ID           │ Multi-tenant fair  │ One tenant = many users │
  │ IP + User-Agent     │ Bot detection      │ Spoofable               │
  │ Endpoint path       │ Expensive ops      │ Combine with user key   │
  │ Global              │ Absolute ceiling   │ Last resort safety net  │
  └─────────────────────┴────────────────────┴─────────────────────────┘

COMPOUND KEY (recommended):
  rl:{tenant_id}:{user_id}:{endpoint_class}

  endpoint_class = bucket routes:
    "read"  → GET /products/*, GET /search
    "write" → POST /orders, PUT /cart
    "heavy" → POST /export, POST /report/generate

  Limits:
    read:  1000/min
    write: 100/min
    heavy: 5/min
```

### Pattern 3: Shadow Mode (COUNT Before BLOCK)

```
ROLLING OUT A NEW RATE LIMIT:

  Week 1: WAF rule action = COUNT
    → Metrics increment, no blocks
    → Compare CountedRequests to AllowedRequests
    → Identify how many legitimate users would be blocked

  Week 2: Block only on /api/v1/scrape-sensitive paths
    → Action = Block on narrow scope

  Week 3: Block globally with tuned threshold

AWS WAF COUNT ACTION:

  "Action": {"Count": {}}

  CloudWatch metric: RateLimitBlock (SampledRequests with rule match)

  Query in CloudWatch Logs Insights (WAF logs):

    fields @timestamp, httpRequest.clientIp, action, terminatingRuleId
    | filter terminatingRuleId = "RateLimit2000Per5Min"
    | stats count() by httpRequest.clientIp
    | sort count desc
    | limit 20

  If top IP is your corporate NAT → threshold too low
```

### Pattern 4: Adaptive Rate Limits (Load-Based)

```
STATIC LIMIT PROBLEM:
  Limit 1000 RPS always — but at 3 AM you have 10× headroom
  During incident, 1000 RPS still overloads degraded DB

ADAPTIVE APPROACH:
  Read dependency health (DB latency, CPU, circuit state)
  Dynamically scale limit:

    base_limit = 1000
    if db_p99_ms > 500:  effective = base * 0.5
    if circuit_open:     effective = base * 0.1
    if cpu < 30%:        effective = min(base * 1.5, hard_ceiling)

IMPLEMENTATION:
  Control plane writes limit to Redis every 10s: rl:global:dynamic_limit
  Data plane reads limit on each request (cached locally 1s)

NETFLIX/concurrency-limits INSPIRATION:
  Gradient of RTT vs in-flight → adjust concurrency
  Rate limit is admission; adaptive limit is feedback control

CAUTION:
  Oscillation if feedback too aggressive — use smoothing (EMA)
  Document in runbook — on-call must know limit is not constant
```

### Pattern 5: Rate Limit Bypass for Internal Traffic

```
PROBLEM:
  Edge WAF rate-limits by IP
  Internal cron jobs, health aggregators share egress IP with users

SOLUTIONS:

  A) Separate VPC endpoint / internal ALB (no WAF rate rule)
     Health checks: /health from internal SG only

  B) Custom header + WAF rule priority:
     Rule 0 (Allow): if X-Internal-Token matches secret in custom header
     Rule 1 (Block): rate-based rule for everyone else

  C) IP allowlist in WAF IP set:
     aws wafv2 create-ip-set --name corp-egress --addresses 203.0.113.0/24

  NEVER: disable rate limiting globally for "testing"
  ALWAYS: bypass is explicit, audited, narrow
```

### Pattern 6: GraphQL and Batch Endpoint Limits

```
GRAPHQL AMPLIFICATION:
  One HTTP request → 50 resolver calls
  Rate limit by HTTP request count is meaningless

FIX — COST-BASED LIMITING:
  Parse query depth/complexity before execution
  cost = field_count × depth_factor
  Deduct `cost` tokens from bucket, not 1 per HTTP request

  Example: Apollo Server @cost directive
    query { user { posts { comments { author { name } } } } } }
    cost = 50 → deduct 50 tokens

BATCH API (/api/v1/batch):
  Limit: max 20 sub-requests per batch
  Token cost = sub-request count
  Prevents 1 HTTP call = 1000 internal DB queries
```

### Pattern 7: Login and Credential Stuffing Limits

```
ENDPOINT: POST /auth/login

ALGORITHM: Sliding window log (strict, small L)
  5 attempts per 15 minutes per (IP + username)
  20 attempts per 15 minutes per IP (catch password spraying)

RESPONSE:
  429 with generic message — do NOT reveal which limit triggered
  Same response time for valid/invalid password (timing attack)

  HTTP/1.1 429 Too Many Requests
  Retry-After: 900

  { "error": "too_many_attempts", "message": "Try again later." }

COORDINATION:
  WAF rate rule on /auth/* (1000/5min/IP) — coarse
  App sliding window — fine
  AWS Cognito: built-in Advanced Security adaptive auth (optional)

AFTER LIMIT:
  Do NOT delete user account
  Optional: CAPTCHA challenge at 3rd attempt (fail open on CAPTCHA provider down?)
```

### Pattern 8: Multi-Region Rate Limiting

```
PROBLEM:
  Redis in us-east-1, users in eu-west-1
  Every request +20ms RTT for rate check

OPTIONS:

  A) Regional Redis replicas — LOCAL READ, GLOBAL WRITE
     Not accurate — each region allows limit independently
     Effective global limit ≈ N_regions × limit (BAD for hard caps)

  B) Global Redis (ElastiCache Global Datastore)
     Single source of truth, cross-region RTT on every check
     Acceptable for write-light APIs

  C) Regional limit = global_limit / N_regions with sync correction
     Each region: 1000/3 ≈ 333 RPS
     Periodic sync via DynamoDB global table for true-up

  D) Edge rate limit (CloudFront/WAF) + regional app limit
     Edge handles 80% of abuse; regional Redis for fine control

RECOMMENDATION:
  Public API: WAF global + regional Redis per-user
  Internal: single-region Redis sufficient
```

---

## Failure Modes

### Failure 1: NAT / Shared IP False Positives

```
SCENARIO:
  Mobile carrier CGNAT: 50,000 users → one public IPv4
  WAF rate rule: 2000 req / 5 min / IP
  Normal usage: 4000 req / 5 min aggregate
  Result: entire carrier's users blocked intermittently

SYMPTOMS:
  Support tickets cluster by mobile carrier / country
  WAF logs show single IP with huge request count, all 403
  Correlated spike in CloudFront 403, NOT origin 429

DETECTION:
  aws wafv2 get-sampled-requests --web-acl-arn ... --rule-metric-name RateLimitBlock
  Top blocked IP has diverse User-Agents and session cookies

FIX:
  → Raise WAF threshold (2000 → 20000) OR switch to COUNT-only at edge
  → Move authenticated limits to user/API-key dimension in app
  → Use AWS WAF ForwardedIPConfig with X-Forwarded-For ONLY if you
    trust the header chain (CloudFront → origin adds verified header)

PREVENTION:
  Never use IP-only limits as sole control for authenticated APIs
  Load test with simulated NAT (many users, one IP) before launch
```

### Failure 2: Redis Hot Key Meltdown

```
SCENARIO:
  Rate limit key: rl:global:flash_sale_item_999
  500,000 RPS on product drop
  Single Redis key receives 500k INCR/sec
  Redis CPU 100%, latency 500ms, rate limit checks block request threads

SYMPTOMS:
  Redis EngineCPUUtilization > 90%
  redis latency doctor shows hot key
  API p99 spikes even though "rate limiting should protect us"
  ElastiCache failover triggered by CPU

DETECTION:
  redis-cli --hotkeys (Redis 4.0+ with memory policies)
  CloudWatch: CurrItems + CPU correlated with marketing event

FIX (immediate):
  → Delete hot key (fail-open briefly) OR raise limit locally in app
  → Enable local cache: accept decision for 50ms without Redis round trip
  → Shard: rl:flash_sale:{rand(0..31)} limit/32 per shard

FIX (long-term):
  → Rate limit per USER not per resource
  → Pre-queue flash sale (virtual waiting room — Queue-it, CloudFront Function)

PREVENTION:
  Load test Redis rate limit path at expected peak QPS
  Monitor redis commands/sec per key (custom metric via key prefix sampling)
```

### Failure 3: Fixed Window Boundary Burst

```
SCENARIO:
  Limit: 1000 req/min per API key (fixed window)
  Partner batch job sends 1000 req at 0:59:58, 1000 req at 1:00:01
  2000 requests in 3 seconds — origin DB pegged

SYMPTOMS:
  Periodic DB CPU spikes at exact minute boundaries
  rate_limit_rejected_total flat (both windows under 1000 individually)
  Origin overload WITHOUT 429 to client

DETECTION:
  Graph origin RPS with 1-second granularity — spikes at :00
  Compare to rate limit window size (60s alignment)

FIX:
  → Migrate to sliding window counter or token bucket
  → Add secondary limit: max 50 req/sec (burst cap) regardless of minute window

PREVENTION:
  Code review checklist: fixed window requires secondary burst cap
```

### Failure 4: Retry Storm Against 429

```
SCENARIO:
  Client SDK retries 429 immediately, 3 times, no jitter
  1000 clients × 100 RPS each = 100k RPS
  All get 429 → retry 3× = 400k RPS hitting API Gateway
  Gateway throttle exhausted — even good clients blocked

SYMPTOMS:
  rate_limit_rejected_total explodes
  X-Retry-Attempt header present on 80%+ of requests
  Client IP diversity (not single attacker)
  Correlates with client SDK release

DETECTION:
  Log X-Retry-Attempt, count distribution
  Metric: retry_ratio = retries / total_requests

FIX:
  → Gateway retry budget (Week 6 Pattern 3): drop retries when budget exhausted
  → Return 503 with Retry-After: 30 for retry budget exceeded
  → Contact client team — fix SDK backoff

PREVENTION:
  SDK documentation mandates full jitter on 429
  Server-side: separate retry budget from normal budget
  Integration tests simulate 429 response, assert backoff behavior
```

### Failure 5: Fail-Open During Redis Outage

```
SCENARIO:
  ElastiCache failover, 15 seconds unavailable
  App configured fail-open (allow all when Redis down)
  Attacker OR flash crowd hits during window
  Origin overwhelmed, outage extends beyond Redis recovery

SYMPTOMS:
  Redis: ReplicationLag, Failover events in ElastiCache events
  Origin 5xx spike coincident with Redis gap
  rate_limit_rejected_total drops to ZERO during incident (ironic)

DETECTION:
  Alert: redis_health == 0 AND origin_rps > 2× baseline

FIX:
  → Emergency WAF rule: lower rate threshold globally (manual runbook step)
  → Switch fail-closed for POST/PUT (writes blocked, reads fail-open)
  → Scale origin horizontally (HPA already triggered too late)

PREVENTION:
  Multi-AZ Redis with automatic failover
  WAF as always-on coarse limit (independent of Redis)
  Explicit fail-open/fail-closed matrix per endpoint class in runbook
```

### Failure 6: Clock Skew Window Drift

```
SCENARIO:
  App servers use local wall clock for window_epoch
  Server A clock 2 seconds ahead of Server B
  Same user hits A then B — double budget in overlap zone

SYMPTOMS:
  Intermittent "should have been blocked" reports
  Hard to reproduce — requires cross-server routing
  Worse after NTP drift event

FIX:
  → Use Redis TIME as authority: local clock never used for windows
  → Or: DynamoDB conditional writes with service timestamp

PREVENTION:
  Chrony/NTP monitoring on all instances
  Integration test: mock clock skew, assert limit still holds
```

### Failure 7: Rate Limit vs Circuit Breaker Semantic Collision

```
SCENARIO:
  payments-svc circuit OPEN
  checkout-svc returns 429 "rate limit exceeded" (wrong code)
  Mobile app shows "slow down" message instead of "payment unavailable"
  Users retry payments aggressively — amplifies half-open probes

SYMPTOMS:
  429 on endpoint that has no user-facing rate limit configured
  circuit_breaker_state{payments}=1 correlated with checkout 429

FIX:
  → Map circuit open → 503 + error code payment_service_unavailable
  → Reserve 429 exclusively for ingress/user quota exceeded

PREVENTION:
  Error code catalog in API spec
  Lint rule: 429 only from rate limit middleware, never from circuit breaker
```

### Failure 8: DynamoDB Conditional Check Hot Partition

```
SCENARIO:
  Global counter: pk=GLOBAL, sk=CURRENT_MINUTE
  50k RPS increment same item
  DynamoDB throttling on single partition (3000 RCU/WCU hard per partition)

SYMPTOMS:
  User: Amazon.DynamoDB.ProvisionedThroughputExceededException
  Rate limiter throws → fail-open or 500 depending on code
  CloudWatch: ThrottledRequests on table

FIX:
  → Shard counters across 16+ partition keys
  → Or migrate hot path to Redis

PREVENTION:
  Never single-item global counter at high QPS
  Load test DynamoDB rate limit path before serverless launch
```

---

## SRE Diagnostic Toolkit

```
RATE LIMIT DEBUGGING:
━━━━━━━━━━━━━━━━━━━━

# Test if YOU are rate limited (curl)
curl -sI -w "\nHTTP_CODE:%{http_code}\n" \
  -H "Authorization: Bearer $TOKEN" \
  https://api.example.com/v1/orders | \
  grep -iE "HTTP|429|retry-after|ratelimit|x-ratelimit"

# Interpret headers:
#   HTTP/2 429
#   Retry-After: 14
#   RateLimit-Remaining: 0
#   RateLimit-Reset: 1751816460

# Burst test (see when 429 starts) — run from load test host, not prod laptop
for i in $(seq 1 250); do
  curl -s -o /dev/null -w "%{http_code}\n" \
    -H "x-api-key: $KEY" https://api.example.com/v1/health &
done | sort | uniq -c
# Output:
#   200 200
#    50 429
# → burst limit ≈ 200


AWS WAF — SAMPLED REQUESTS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━

aws wafv2 get-sampled-requests \
  --web-acl-arn "$WAF_ARN" \
  --rule-metric-name RateLimitBlock \
  --scope CLOUDFRONT \
  --time-window StartTime=$(date -u -d '5 min ago' +%Y-%m-%dT%H:%M:%SZ),EndTime=$(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --max-items 100 \
  --region us-east-1

# Look for: action=BLOCK, terminatingRuleId=RateLimit...


CLOUDWATCH — WAF BLOCK RATE:

aws cloudwatch get-metric-statistics \
  --namespace AWS/WAFV2 \
  --metric-name BlockedRequests \
  --dimensions Name=Rule,Value=RateLimit2000Per5Min Name=WebACL,Value=ecommerce-edge-acl \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 \
  --statistics Sum


API GATEWAY — THROTTLE METRICS:

aws cloudwatch get-metric-statistics \
  --namespace AWS/ApiGateway \
  --metric-name Count \
  --dimensions Name=ApiName,Value=prod-api Name=Stage,Value=prod \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 \
  --statistics Sum

# 429 from API Gateway appears in execution logs:
#   "status":"429", "errorMessage":"Too Many Requests"

aws logs filter-log-events \
  --log-group-name API-Gateway-Execution-Logs_abc123/prod \
  --filter-pattern '{ $.status = 429 }' \
  --start-time $(($(date +%s)*1000 - 3600000))


REDIS — INSPECT RATE LIMIT KEYS:

redis-cli -h $REDIS_HOST --tls KEYS 'rl:*' | head -20
# Never KEYS in prod at scale — use SCAN:

redis-cli --tls SCAN 0 MATCH 'rl:sw:*' COUNT 100

# Check specific user counter:
redis-cli --tls GET 'rl:sw:user_88421:28901234'
redis-cli --tls TTL 'rl:sw:user_88421:28901234'

# Monitor command rate:
redis-cli --tls INFO stats | grep instantaneous_ops_per_sec

# Latency doctor (ElastiCache):
aws elasticache describe-events --source-identifier my-redis-cluster


PROMETHEUS QUERIES:
━━━━━━━━━━━━━━━━━━

# 429 rate by layer
sum(rate(http_requests_total{status="429"}[5m])) by (layer)

# Rate limit reject ratio
sum(rate(rate_limit_rejected_total[5m]))
/
sum(rate(http_requests_total[5m]))

# Redis rate limit check latency
histogram_quantile(0.99,
  sum(rate(redis_rate_limit_duration_seconds_bucket[5m])) by (le))

# Circuit breaker vs rate limit correlation
rate_limit_rejected_total and on() circuit_breaker_state == 1
# If both high — check semantic collision (Failure 7)


LOG PATTERNS (CloudWatch Logs Insights):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

fields @timestamp, client_ip, user_id, status, retry_after, layer
| filter status = 429
| stats count() by user_id, layer
| sort count desc
| limit 50

# Identify top limited users vs top limited IPs:
fields @timestamp, client_ip, user_id
| filter status = 429 and layer = "waf"
| stats count() by client_ip

fields @timestamp, client_ip, user_id
| filter status = 429 and layer = "app"
| stats count() by user_id


COMMON "WHY AM I GETTING 429?" CHECKLIST:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  CHECK 1: Which layer returned 429?
    WAF → blocked before origin (no origin access log entry)
    API GW → x-amzn-ErrorType: TooManyRequestsException
    App → RateLimit-* headers present, origin log shows 429

  CHECK 2: Is it IP or user limit?
    Same user, different IP → still 429 = user limit
    Different user, same IP → 429 = IP limit (NAT issue)

  CHECK 3: Window boundary burst?
    Graph client request times — burst at minute rollover?

  CHECK 4: Retry amplification?
    grep X-Retry-Attempt in access logs — high values?

  CHECK 5: Redis healthy?
    redis PING, ElastiCache events, failover in last 15 min?

  CHECK 6: Wrong status code from circuit breaker?
    429 body says "rate_limit" but dependency circuit open?
```

### Hands-On Exercises (Section 7)

```
EXERCISE 1: Measure API Gateway Burst Behavior
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  # Create test stage with rate=10, burst=20
  # Send 25 rapid requests:
  seq 25 | xargs -P25 -I{} curl -s -o /dev/null -w "%{http_code}\n" \
    -H "x-api-key: $TEST_KEY" https://$API_ID.execute-api.us-east-1.amazonaws.com/test/ping

  # Record: how many 200 vs 429?
  # Wait 2 seconds, send 10 more — how many succeed?
  # Document token bucket refill behavior


EXERCISE 2: WAF COUNT Mode Analysis
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  # Deploy rate rule with Count action
  # Generate traffic from single IP (load tester)
  # Query sampled requests after 10 minutes
  # Calculate: would Block have affected legitimate traffic?


EXERCISE 3: Implement Token Bucket Locally
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  # Python one-liner test:
  python3 -c "
  from time import sleep
  # paste TokenBucket class from Core Teaching
  b = TokenBucket(10, 2)  # capacity 10, 2/sec refill
  for i in range(15):
    print(i, b.allow())
  sleep(1)
  for i in range(5):
    print('after sleep', i, b.allow())
  "

  # Verify: first 10 True, then False, after sleep more True


EXERCISE 4: Redis Sliding Window Under Load
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  # redis-benchmark -h $HOST --tls -n 10000 -t eval
  # Run rate limit Lua script in loop from 10 parallel workers
  # Measure: at what ops/sec does p99 latency exceed 5ms?


EXERCISE 5: Distinguish 429 from 503 in Your Stack
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  # Trigger app rate limit (exceed user quota) → expect 429 + Retry-After
  # Trigger circuit breaker (kill dependency) → expect 503 + different body
  # Document exact response shapes for on-call runbook
```

---

## Decision Framework

```
ALGORITHM CHOOSER:
━━━━━━━━━━━━━━━━━━

  ┌──────────────────────────────┬─────────────────────────────────────────┐
  │ Requirement                  │ Choose                                  │
  ├──────────────────────────────┼─────────────────────────────────────────┤
  │ Allow controlled burst       │ Token bucket                            │
  │ Smooth output to downstream  │ Leaky bucket (queue + worker)           │
  │ Simplest implementation      │ Fixed window (+ burst cap if critical)  │
  │ Strict fairness, small L     │ Sliding window log                      │
  │ High RPS, good enough        │ Sliding window counter                  │
  │ Serverless, no Redis         │ DynamoDB conditional + TTL              │
  │ Edge DDoS / scraper block    │ AWS WAF rate-based rule                 │
  │ Per-customer API contract    │ API Gateway usage plan                  │
  └──────────────────────────────┴─────────────────────────────────────────┘


STORAGE BACKEND CHOOSER:
━━━━━━━━━━━━━━━━━━━━━━━━

  ┌────────────────────────────┬──────────┬───────────┬────────────────────┐
  │ Backend                    │ Latency  │ Ops burden│ Best for           │
  ├────────────────────────────┼──────────┼───────────┼────────────────────┤
  │ In-process (local)         │ ~0       │ None      │ Single instance dev│
  │ Redis (ElastiCache)        │ 1-3ms    │ Medium    │ Production default │
  │ DynamoDB                   │ 5-20ms   │ Low       │ Serverless         │
  │ API Gateway native         │ 0*       │ None      │ Per-key SaaS       │
  │ WAF native                 │ 0*       │ None      │ Per-IP edge        │
  └────────────────────────────┴──────────┴───────────┴────────────────────┘
  *Enforced before your code runs


FAIL-OPEN vs FAIL-CLOSED:
━━━━━━━━━━━━━━━━━━━━━━━━

  Public write API + Redis down     → FAIL-CLOSED (503)
  Public read API + Redis down      → FAIL-OPEN with WAF backstop
  Internal microservice               → FAIL-OPEN (mesh mTLS trust)
  Payment endpoint                    → FAIL-CLOSED always
  Login endpoint                      → FAIL-CLOSED (security)


LIMIT DIMENSION FLOWCHART:

  Is traffic authenticated?
    NO  → WAF rate rule by IP (coarse) + CAPTCHA on sensitive paths
    YES → API key or JWT sub
          Is this B2B with contract?
            YES → API Gateway usage plan (commercial limit)
            NO  → App Redis limit by user_id

  Is endpoint expensive (>$0.01/request or >100ms p99)?
    YES → Add endpoint-class weight + lower burst
    NO  → Standard bucket

  Is there a flash sale / viral event expected?
    YES → Waiting room + per-user queue + pre-warm Redis
    NO  → Standard layered limits
```

### Worked Decision: E-Commerce Checkout API

```
REQUIREMENTS:
  50k RPS peak, 500 RPS per merchant, burst checkout clicks
  PCI scope — payment path isolated
  Mobile app + web + partner integrations

DECISION:

  Edge (CloudFront + WAF):
    Rate-based: 5000/5min/IP (COUNT first week)
    AWS Managed Rules: Core rule set

  API Gateway:
    Partner APIs: usage plan 500 RPS, burst 1000
    Mobile app: Cognito authorizer, no API key — app limit handles

  App (Redis sliding window counter):
    Per-user: 30 checkout attempts/min
    Per-IP unauthenticated /cart: 120/min

  Outbound (Stripe):
    Token bucket 90/sec + circuit breaker
    Bulkhead: 100 concurrent Stripe calls

  Circuit breaker coordination:
    Stripe circuit OPEN → checkout 503, NOT 429
    User rate limit separate from Stripe health

  Fail-closed: POST /checkout when Redis down
  Fail-open: GET /products when Redis down (WAF protects)
```

---

## Incident Scenario

```
INCIDENT REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Severity: P1 (REVENUE)
Service: B2B Data Export API (SaaS analytics platform)
Time: Tuesday 2:47 PM UTC (peak EU business hours)

ARCHITECTURE:

  Partner clients → CloudFront → WAF → API Gateway → ECS (export-svc)
                                                      │
                                                      ├── ElastiCache Redis (rate limits)
                                                      ├── RDS PostgreSQL (query engine)
                                                      └── S3 (export file delivery)

  Rate limit configuration (as documented in runbook):
    WAF:        3000 req / 5 min / IP (Block)
    API GW:     Usage plan "Enterprise": 100 RPS, burst 200
    App Redis:  Sliding window — 60 exports / hour / api_key
                Weight: small export = 1 token, large export = 10 tokens
    Outbound:   S3 PutObject — bulkhead 50 concurrent uploads

  Week 6 resilience (export-svc):
    Circuit breaker on RDS: failure threshold 50%, wait 30s in OPEN
    Bulkhead on DB connection pool: 80 connections max
    Retry: 2× with jitter on transient 503 from RDS

TIMELINE:

  2:47 PM — PagerDuty: "export_api_error_rate > 15%" (threshold 5%)
  2:48 PM — Grafana: 429 rate jumped 0.1% → 34% in 3 minutes
  2:49 PM — Support Slack: "Acme Corp says ALL export requests failing"
  2:50 PM — On-call checks CloudWatch:
              WAF BlockedRequests: flat (not WAF)
              API Gateway 429: flat (not gateway)
              export-svc 429: SPIKE — all from rate_limit_middleware
  2:52 PM — Redis metrics: EngineCPUUtilization 97%, GET latency 450ms
  2:53 PM — redis-cli --hotkeys reveals: rl:sw:api_key_acme_corp:28901234
              (single key, 180k ops/sec)
  2:54 PM — Acme Corp launched "full portfolio re-export" batch job
              500 workers × 60 req/min = 30,000 req/min
              Their contract: 100 RPS gateway + 60 exports/hour app limit
              BUT batch uses 500 different sub-api-keys auto-rotated (bug)
  2:55 PM — Each sub-key stays under 60/hour limit individually
              Aggregate Acme traffic: 300k exports/hour — 5000× intended
  2:56 PM — Redis hot key on aggregate counter MISSING — per-key only
              RDS CPU 92%, circuit breaker on RDS → HALF-OPEN flickering
  2:57 PM — Half-open probes NOT rate-limited — each probe runs full export
              RDS queries 30-120 seconds each
  2:58 PM — Bulkhead saturated (80/80 DB connections)
              Unrelated tenants: SmallCorp, BetaInc also getting 503
  2:59 PM — SmallCorp NOT rate limited (under their quota) but DB dead

ADDITIONAL OBSERVATIONS:

  curl from on-call laptop:
    curl -sI -H "x-api-key: smallcorp_key" https://api.analytics.example.com/v1/export/status/123

    HTTP/2 503
    Retry-After: 30
    X-Error-Code: service_unavailable

    (NOT 429 — SmallCorp is innocent)

  Acme curl:
    HTTP/2 429
    Retry-After: 847
    RateLimit-Remaining: 0
    RateLimit-Reset: 1751817600

  export-svc logs:
    {"level":"warn","msg":"circuit_breaker","state":"half_open","dep":"rds"}
    {"level":"error","msg":"bulkhead_rejected","pool":"db","available":0}
    {"level":"warn","msg":"rate_limit_pass","api_key":"acme_sub_key_447",...}

  Deployment yesterday: removed tenant-level aggregate rate limit
    "Redundant — API Gateway usage plan covers it"
    Git commit: abc123f by jsmith

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Question 1:** Draw the exact failure chain from Acme's batch job to SmallCorp receiving 503. Which components failed to contain the blast radius, and why?

**Question 2:** Immediate mitigation — you have 10 minutes before executive escalation. List every action in priority order with exact commands/config changes. What do you NOT do?

**Question 3:** The circuit breaker on RDS is flickering HALF-OPEN. Explain why unlimited half-open probes made this worse. How should half-open probing have been rate-limited (Week 6)? Give exact numbers.

**Question 4:** Long-term fixes — design the rate limiting architecture so Acme can never monopolize shared RDS again, even with unlimited sub-api-keys. Include tenant-level limits, key rotation handling, and coordination with circuit breakers.

---



---

> **Answer key (do not open until you attempt the Ops Sim / questions):**  
> [`../answers/Week-07-Specialized-Components/Rate Limiting Algorithms Answers.md`](../answers/Week-07-Specialized-Components/Rate Limiting Algorithms Answers.md)

## Key Takeaways

```
╔══════════════════════════════════════════════════════════════════╗
║   IF YOU FORGET EVERYTHING ELSE, REMEMBER THESE:                 ║
╟──────────────────────────────────────────────────────────────────╢
║                                                                  ║
║   1. Token bucket for burst tolerance; sliding window            ║
║      counter for fair high-RPS APIs; fixed window only           ║
║      with a secondary burst cap — know the boundary bug.         ║
║                                                                  ║
║   2. Layer limits: WAF (IP/coarse) → API Gateway                 ║
║      (contract) → app Redis (user/tenant/endpoint).              ║
║      No single layer is sufficient.                              ║
║                                                                  ║
║   3. Distributed rate limiting needs atomic ops (Redis           ║
║      Lua, DynamoDB conditionals), explicit fail-open/            ║
║      fail-closed policy, and hot-key sharding plan.              ║
║                                                                  ║
║   4. Rate limit (429) is proactive admission control;            ║
║      circuit breaker (503) is reactive dependency                ║
║      protection — never swap status codes (Week 6).              ║
║                                                                  ║
║   5. Tenant aggregate limits are non-negotiable in               ║
║      multi-tenant systems — per-key limits alone let             ║
║      key rotation bypass quotas and take down shared             ║
║      infrastructure.                                             ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## Targeted Reading

```
REQUIRED:

  1. AWS WAF Rate-Based Rule Statement
     https://docs.aws.amazon.com/waf/latest/developerguide/waf-rule-statement-type-rate-based.html
     → Exact 5-minute window semantics, IP aggregation, minimum limit 100

  2. Amazon API Gateway Throttling
     https://docs.aws.amazon.com/apigateway/latest/developerguide/api-gateway-request-throttling.html
     → Token bucket model, stage/method/usage plan hierarchy, 429 behavior

  3. Redis rate limiting patterns (Redis Ltd. documentation)
     https://redis.io/docs/latest/develop/use/patterns/rate-limiting/
     → Fixed window, sliding window, token bucket Lua implementations

  4. IETF Draft: RateLimit Header Fields for HTTP
     https://datatracker.ietf.org/doc/html/draft-ietf-httpapi-ratelimit-headers
     → RateLimit-Limit, RateLimit-Remaining, RateLimit-Reset semantics

  5. Week 6 module: Circuit Breakers, Bulkheads, Timeouts, Retries, and Backpressure
     → Section "How the Five Patterns Compose" — rate limit at ingress
     → Half-open probe rate limiting, retry budget at gateway

OPTIONAL:

  6. Stripe API Rate Limiters documentation
     https://docs.stripe.com/rate-limits
     → Production example of dual-layer rate limiting + 429 headers

  7. Cloudflare Rate Limiting (contrast to AWS WAF)
     https://developers.cloudflare.com/waf/rate-limiting-rules/
     → Alternative edge implementation for multi-cloud comparison

  8. Martin Fowler: Patterns of Enterprise Application Architecture —
     "Throttling" section in Microservices resource management
     → Conceptual foundation for admission control vs backpressure

  9. DynamoDB Best Practices: Partition Key Design
     https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/bp-partition-key-design.html
     → Avoid hot partitions in counter-based rate limiting
```

---
