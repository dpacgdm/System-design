# LLD: Rate Limiter (SRE-thick)

**Contract:** MODULE_CONTRACT_V2 · **Archetype:** Design · **Tier:** Core (SRE LLD)  
**Prep:** [TIMED_INTERVIEW_OS](../00-Curriculum/TIMED_INTERVIEW_OS.md) · [Abuse / bots](../Week-08c-Operations-Hardening/Abuse%20Bots%20and%20Fraud%20Defense.md) · [Rate Limiting Algorithms](../Week-07-Specialized-Components/Rate%20Limiting%20Algorithms.md) (HLD companion)  
**Timebox:** 45 min whiteboard · **Drill:** 20 min micro below  
**Sealed:** [answers/Week-15c-SRE-LLD/LLD Rate Limiter.answers.md](../answers/Week-15c-SRE-LLD/LLD%20Rate%20Limiter.answers.md)

---

## Why this is SRE LLD (not toy OOD)

Interviewers ask rate limiters because they force **shared-state concurrency**, **clocks**, **fairness vs availability**, and **operability**. A class diagram without hot keys, Redis failure, or clock skew is incomplete for SRE loops.

---

## Problem statement

Design an in-process + distributed rate limiter for:

- Per-user / per-IP / per-API-key / per-tenant limits
- Multiple algorithms selectable by policy
- Soft vs hard enforcement modes
- Observable decisions (allow/deny + reason + remaining)

Non-goals: full WAF; full bot ML; global fairness across regions without a consistency story.

---

## Requirements (force tradeoffs)

| Dimension | Target | Tradeoff |
|-----------|--------|----------|
| Accuracy | ±1–5% under normal load | Exact counts need stronger consistency |
| Latency | <1ms local; <5ms Redis path | Remote check adds RTT |
| Availability | Prefer allow-on-store-fail (configurable) | Fail-open vs fail-closed |
| Fairness | Per-key isolation | Hot keys still need sharding |
| Multi-DC | Eventually consistent OK for soft limits | Strict global needs leader or CRDT story |

---

## Algorithms (implementable mental models)

### Token bucket
- Capacity `C`, refill `R` tokens/sec
- Allow if tokens ≥ cost; else deny
- Good for bursts; SRE: burst ≠ free — document burst size

### Sliding window log
- Store timestamps; count in window
- Accurate; memory heavy at high QPS

### Sliding window counter
- Weighted previous + current bucket
- Approximate; cheap

### Leaky bucket
- Smooths to constant rate; queue depth matters

**SRE pick default:** token bucket for APIs; sliding counter for cheap approximate; log only for audit-critical.

---

## Interfaces (whiteboard-ready)

```text
interface RateLimiter {
  Decision check(Key key, int cost, Instant now);
  void configure(Policy policy);
}

record Decision(boolean allowed, String reason, long remaining, Duration retryAfter);
record Key(String namespace, String id); // e.g. "api:user:42"
record Policy(Algorithm algo, long limit, Duration window, Mode mode, OnStoreFail failMode);
enum Mode { HARD, SOFT } // SOFT: allow + emit metric
enum OnStoreFail { FAIL_OPEN, FAIL_CLOSED, DEGRADED_LOCAL }
```

Local store:

```text
class LocalTokenBucket {
  long tokens;
  Instant lastRefill;
  synchronized Decision tryTake(int cost, Instant now);
}
```

Distributed:

```text
class RedisTokenBucket {
  // EVAL script: refill + take atomically
  Decision tryTake(Key key, Policy p, int cost);
}
```

---

## Concurrency & correctness

1. **Atomicity:** refill+consume must be one critical section (mutex / Redis Lua / single-flight).
2. **Clock:** use monotonic for local intervals; wall clock for distributed windows — document skew budget.
3. **Thundering herd:** on deny, return `retryAfter` jittered.
4. **Hot key:** shard by `hash(key) % N` or local + async reconcile; never one Redis key for "global".
5. **Double-check:** edge gateway + service mesh + app — avoid multiplying limits silently (document layering).

---

## Failure modes (must discuss)

| Failure | Behavior | Signal |
|---------|----------|--------|
| Redis timeout | FAIL_OPEN or CLOSED per policy | `ratelimit_store_errors` |
| Redis split | divergent counts | regional dashboards diverge |
| Clock jump forward | sudden burst capacity | refill spike metric |
| Clock jump back | temporary starve | deny spike |
| Config push bad limit=0 | global deny | canary config |
| Soft mode ignored by client | overload continues | client MUST honor 429 |

---

## Operability

**Metrics:** allow/deny by key namespace, store latency, fail-open count, remaining histogram, top denied keys (cardinality-safe).  
**Logs:** sample denies with reason; never log raw PII keys at full rate.  
**Alerts:** deny ratio spike; store error rate; fail-open sustained.  
**Config:** versioned policies; canary tenant before global.  
**Load shed companion:** rate limit ≠ load shed — link to Week-08b.

---

## Sketch → critique

```text
API Gateway → RateLimiter.check(userKey)
  → Local cache of Decision (short TTL) → Redis Lua token bucket
  → if deny: 429 + Retry-After
  → if store fail: FAIL_OPEN + metric + page if sustained
```

**Critique prompts:** What if local cache says allow but Redis would deny? What if Lua script version mismatches? What if tenant limit updates mid-window?

---

## 20-min micro-drill

Design **only** Redis Lua token bucket + FAIL_OPEN policy + metrics. Skip UI. Produce: key schema, script steps, failure table (5 rows), one alert.

---

## Self-check

- [ ] Named algorithm + why not the others
- [ ] Atomic refill+take
- [ ] Fail-open/closed explicit
- [ ] Hot key + multi-DC honesty
- [ ] Metrics/alerts for store failure
- [ ] Layering with gateway/mesh called out

---

## Blind transfer

Your limiter allows bursts of 100. A batch client sends 100, sleeps 1ms, repeats. Production melts. What did you miss?
