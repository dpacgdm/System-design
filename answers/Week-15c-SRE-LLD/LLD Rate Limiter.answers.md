# Answer Key — LLD Rate Limiter (SRE-thick)

> Open only after attempting the learner module and 20-min micro-drill.

## Grading bar (Staff)

| Criterion | Points | Pass |
|-----------|-------:|------|
| Algorithm choice + why-not-others | 4 | Named default + 1 rejected alternative with reason |
| Atomic refill+take story | 5 | Mutex / Lua / single-flight — not "check then decrement" |
| Fail-open vs fail-closed explicit | 4 | Policy named + when each is wrong |
| Hot key / sharding | 4 | Not one global Redis key |
| Multi-DC honesty | 3 | Eventual vs strict; no magic global exact |
| Operability (metrics/alerts) | 5 | Store errors + deny ratio + fail-open sustained |
| Layering (gateway/mesh/app) | 3 | Avoid silent multiply |
| Blind transfer | 4 | Burst + sleep bypass named |
| **Staff pass** | **/32** | **≥22** and no automatic fail |

**Automatic fails:** unbounded in-memory map as "distributed limiter"; ignore Redis failure; claim exact global multi-DC without leader/CRDT story; no `retryAfter`/jitter on deny.

---

## Expert model — preferred design

### Default algorithm: token bucket

**Why:** APIs need controlled burst (login spikes, mobile reconnect) without allowing sustained over-rate. Refill rate `R` enforces long-term average; capacity `C` caps burst.

**Reject sliding log as default:** O(requests in window) memory; at 50k QPS per key-class, logs explode.

**Reject pure fixed window alone:** boundary burst (2× limit across window edge).

**Accept sliding counter as cheap approximate** when ±5–10% error is OK and memory is tight.

### Key schema

```text
rl:{namespace}:{id}           # Redis HASH or STRING holding tokens + ts
rl:cfg:{policyVersion}        # optional policy blob
namespaces: api:user | api:ip | api:key | tenant:id | route:id
```

Composite keys for layered limits: check `tenant` then `user` then `route` — **document which is evaluated first** and whether deny short-circuits.

### Local token bucket (critical section)

```text
synchronized(bucket) or stripedLock(key):
  elapsed = now_monotonic - lastRefill
  tokens = min(C, tokens + elapsed * R)
  lastRefill = now_monotonic
  if tokens >= cost:
    tokens -= cost
    return Allow(remaining=floor(tokens))
  else:
    need = cost - tokens
    retryAfter = need / R  (+ jitter 0–20%)
    return Deny(retryAfter)
```

**Clock:** monotonic for local refill intervals. Wall clock only when comparing distributed window IDs.

### Redis Lua (atomic)

Script steps (Staff exemplar):

1. `GET` tokens + last_ms (or HMGET)
2. Compute refill with `ARGV.now_ms` passed from server (or Redis `TIME` — document skew)
3. Cap at capacity
4. If enough: DECRBY cost; SET new tokens+ts; return allow + remaining
5. Else: return deny + retry_ms
6. `PEXPIRE` key to `idle_ttl` so abandoned keys die

**Why Lua:** check-then-set from client races under concurrency.

### Decision record (API)

```text
allowed: bool
reason: OK | EMPTY_BUCKET | POLICY_DISABLED | STORE_ERROR_FAIL_OPEN | STORE_ERROR_FAIL_CLOSED
remaining: long
retryAfter: Duration
policyVersion: string
```

Emit reason on metrics with **low cardinality** labels (`namespace`, `reason`) — never raw user id as label.

---

## Failure table (complete Staff answers)

| Failure | Behavior | Signal | First safe action |
|---------|----------|--------|-------------------|
| Redis timeout | FAIL_OPEN (soft APIs) or FAIL_CLOSED (auth SMS / login) | `ratelimit_store_errors`, latency spike | Page if fail-open sustained >N min; flip to local degraded token bucket with conservative limit |
| Redis split-brain | Divergent counts per region | Regional deny ratios diverge | Prefer regional limits; accept soft global; or use regional + async reconcile |
| Clock jump forward | Sudden full burst capacity | Refill spike / allow burst metric | Cap refill delta to max_elapsed (e.g. 1 window) |
| Clock jump back | Temporary starve | Deny spike with full tokens unexpected | Same clamp; monotonic local |
| Config limit=0 | Global deny | Deny ratio → 100%, canary first | Instant config rollback; require canary tenant |
| Soft mode ignored | Overload continues | Origin CPU up while limiter "allows" | Soft must still emit; clients need hard 429 path for true protection |
| Hot key | Redis CPU one shard | Latency on one hash slot | Shard key `hash(id)%N` or local+async; isolate elephant users |
| Gateway × app double limit | Unexpected 429 | Compare gateway vs app deny | Document effective limit = min; or only enforce at one layer + observe at other |
| Negative remaining race | Over-admit under concurrency | Unit tests failing under parallel | Prove atomic section |

---

## Operability exemplar

**Metrics:**
- `ratelimit_decisions_total{namespace,result,reason}`
- `ratelimit_store_latency_ms` histogram
- `ratelimit_fail_open_total`
- `ratelimit_remaining` summary (sampled)
- Top denied namespaces via logs/sampled — not unbounded label cardinality

**Alerts:**
1. `fail_open_rate > 1% for 5m` → page SRE (you're unprotected)
2. `store_error_rate > 5% for 3m`
3. `deny_ratio` burn vs baseline (attack or bad config)
4. Canary policy deny anomaly before global push

**Config rollout:** versioned policy → canary 1% tenants → bake 30–60m → widen. Never push `limit=0` without two-person review.

**Load shed link:** Rate limit protects fairness per key; load shed protects **server survival** when total admission is still too high. Both required.

---

## Layering (must say)

```text
Edge/WAF (IP / bot) → API Gateway (API key plan) → Mesh/sidecar (optional) → App (user/tenant)
```

Silent multiply: gateway 100 rps × app 100 rps ≠ 100. **Effective** limit is the tightest that actually sees the traffic. Interview answer: pick one enforcement plane for hard limits; others observe or soft.

---

## Multi-DC honesty

| Goal | Approach | Cost |
|------|----------|------|
| Soft regional fairness | Per-region Redis; limit ≈ global/N or full per region | Over-admit globally up to N× |
| Strict global | Central limiter or consensus | Latency + availability coupled to central |
| Approximate global | Local + async sync / CRDT counters | Bounds error; complex |

Staff answer: "For API abuse soft limits I use regional token buckets; for login SMS I fail-closed and accept central dependency or prepaid local quotas."

---

## 20-min micro-drill — Staff key

### Key schema
`rl:tb:{ns}:{id}` → HASH `{tokens, ts}` + TTL 2× window idle.

### Lua steps
1. Load tokens/ts  
2. Refill clamp  
3. Take or deny  
4. Persist + PEXPIRE  
5. Return tuple

### FAIL_OPEN policy
On `MOVED`/`TIMEOUT`/`OOM`: allow once, increment `fail_open`, include `reason=STORE_ERROR_FAIL_OPEN` in logs sample; if fail-open rate high → page and optionally switch CLOSED for dangerous routes via flag.

### Metrics (minimum)
decisions, store_latency, fail_open_total, deny_ratio by namespace.

### One alert
`fail_open_total` rate > threshold for 5m on production.

---

## Sketch critique answers

**Local cache says allow, Redis would deny:** short TTL decision cache creates over-admit window. Prefer caching **denies** briefly (negative) more safely than allows; or don't cache allows >10–50ms; or only cache remaining estimates with soft mode.

**Lua version mismatch:** rolling deploy of script SHA — use `SCRIPT LOAD` + pinned SHA; dual-run old/new during canary; never EVAL of divergent source ad hoc from many app versions without pin.

**Tenant limit mid-window:** either (a) apply new limit on next refill using new C/R (tokens may exceed new C — clamp on read), or (b) epoch policy version in key so old buckets die. Document which.

---

## Blind transfer — Staff answer

**Missed:** sustained average. Token bucket with C=100 allows 100 immediately, then if refill is fast *or* if they sleep only until partial refill, a clever client can stay near the burst envelope repeatedly. Worse: if refill rate is high (e.g. 100/s) sleep 1ms barely matters. Even with slow refill, **many clients** each bursting 100 melts origin.

**Fixes:**
1. Set `C` to true burst budget (e.g. 20) and `R` to sustained (e.g. 10/s) — not C=R×window with huge C.
2. Add **concurrent request** limit / queue depth (separate from rate).
3. Tenant aggregate + route bulkheads.
4. Detect square-wave clients (burst entropy) → tighter policy / ban.
5. Load shed at server when total CPU/concurrency burns regardless of per-key allow.

---

## Worked interview narration (45 min beats)

**0–5:** Restate: multi-key, algorithms, fail modes, observability. Ask QPS, multi-DC, hard vs soft.

**5–15:** API + token bucket math example: C=60, R=1/s → average 1 rps, burst 60.

**15–30:** Local then Redis Lua; concurrency; hot keys.

**30–40:** Failure table + fail-open; metrics/alerts.

**40–45:** Multi-DC honesty + layering; invite critique.

Comms: check-in at ~15 and ~30; headline numbers first.

---

## Below-bar vs Staff examples

**Below bar:** "Use Redis INCR with expiry per minute."  
**Staff:** Names boundary burst, atomicity gap on INCR+EXPIRE race, hot keys, fail-open, and when token bucket beats fixed window.

**Below bar:** "Fail open always for availability."  
**Staff:** Route-class policy; SMS/login fail-closed; page on sustained fail-open.

---

## Principal stretch prompts (optional)

1. Design rate limits that are **fair across tenants** when one tenant has 10k keys.  
2. Prove error bounds for sliding window counter vs log.  
3. Integrate with adaptive concurrency limit (TCP-BBR-like) — how do they interact?

### Stretch sketch answers

1. Hierarchical counters: leaf keys + tenant rollup updated via Lua or async; enforce tenant first.  
2. Sliding counter error ≤ one bucket width of traffic; log exact.  
3. Rate limit caps identity abuse; AIMD concurrency caps server overload — evaluate concurrency after rate allow.

---

## Self-check mapping

| Learner checkbox | Evidence in answer |
|------------------|--------------------|
| Algorithm + why | Token bucket default section |
| Atomic refill+take | Local sync + Lua |
| Fail-open/closed | Failure table + policy |
| Hot key + multi-DC | Hot key row + Multi-DC honesty |
| Metrics/alerts | Operability exemplar |
| Layering | Layering section |

---

## Common interviewer follow-ups (prep)

**Q:** Where do you put the limiter?  
**A:** Prefer edge for IP/bot; app for user/tenant semantics; avoid double hard-enforce without math.

**Q:** How do you test?  
**A:** Concurrency tests on local bucket; Redis integration with parallel clients; chaos timeout → fail mode; load test square-wave clients.

**Q:** Distributed exact count?  
**A:** Expensive; usually unnecessary for soft API limits. Use when regulatory/billing.

---

## Scoring worksheet (print)

```text
Algorithm ____ /4
Atomicity ____ /5
Fail mode ____ /4
Hot key ____ /4
Multi-DC ____ /3
Ops ____ /5
Layering ____ /3
Blind ____ /4
TOTAL ____ /32
Auto-fail? Y/N ____
Comms dims (from Timed OS): all ≥3? ____
```

---

## Tie-ins

- HLD companion: Week-10 Design Rate Limiter  
- Abuse: Week-08c  
- Backpressure: Week-08b  
- Timed OS: SRE LLD battery requires this + one of cache/pool

---

## Minimal Redis mental code (narrate, don't invent APIs)

```text
KEYS[1] = bucket key
ARGV[1] = now_ms
ARGV[2] = capacity
ARGV[3] = refill_per_ms
ARGV[4] = cost
ARGV[5] = idle_ttl_ms
-- load, refill, check, store, return {allowed, remaining, retry_ms}
```

Pin SHA. Unit-test refill clamp on huge `now` jumps.

---

## End state claim

Staff-ready on this module when: you can whiteboard Lua+local, fill failure table cold, and explain why burst clients still melt you — without opening keys.
