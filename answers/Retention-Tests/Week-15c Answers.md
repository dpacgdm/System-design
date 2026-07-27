# Answer Key — Retention Week-15c SRE LLD

> Open only after the retention attempt.

## Grading
Rapid-fire: 1 point each (8). Applied: 3 each (9). Compound: 6. Blind: 3 each (6).  
**Staff pass ≥ 22 / 29.** Automatic fail: unbounded queue as "fine"; fail-open with no caveat; no deadlock callout on Q7/Q12.

---

## Part 1

**Q1:** Fixed window allows ~2× limit at boundary (end of window N + start of N+1).

**Q2:** Two clients can both observe tokens≥cost and both decrement → over-admit. Need atomic refill+take (mutex / Lua / single-flight).

**Q3:** FAIL_CLOSED: high-cost abuse paths (SMS, login, irreversible). FAIL_OPEN: soft fairness where availability > strict quota — but page if sustained.

**Q4:** Any of: map size ≤ capacity; bijection map↔list nodes; MRU/LRU ends consistent; expired treated as miss on access.

**Q5:** Prevents thundering herd on **one** key. Does not prevent origin melt when **many** keys expire in the same second.

**Q6:** Hides overload as latency; memory growth; delayed failure; no backpressure to callers.

**Q7:** Tasks running on pool P block waiting for other tasks also scheduled on P → threads exhaust → deadlock/stall.

**Q8:** Workers blocked on IO/locks/dependencies — not CPU shortage. Thread dump + dependency p99 before growing the pool.

---

## Part 2

**Q9 exemplar:**
- Key `rl:tb:{ns}:{id}` HASH tokens/ts  
- Steps: load → refill clamp → check cost → store + PEXPIRE idle → return allow/deny+retry  
- Pin script SHA

**Q10 exemplar:**
- get hit&fresh → return  
- miss → inflight.computeIfAbsent → all waiters share future  
- on success put; on failure no put (optional short negative); remove inflight in finally  
- load timeout required

**Q11 exemplar:**
- `n ≈ cores*(1+wait/compute)` then measure  
- `Q` from wait budget ≈ Q/service_rate under SLO  
- Reject ABORT → 503; avoid CALLER_RUNS on servlet threads; separate fan-out pool

---

## Part 3 — Q12

**(a) Mechanisms:**
1. Synchronized TTL expiry → cache stampede every ~2m onto DB  
2. FAIL_OPEN during Redis blip → admission spike / no protection  
3. Shared executor handler+fan-out → deadlock or thread exhaustion → 503s  

**(b) First safe mitigations (order):**
1. Stabilize: shed/load protect DB (bulkhead, reduce fan-out), stop deploy churn  
2. Flip critical routes to FAIL_CLOSED or local conservative limiter during Redis blip; page on fail-open  
3. Jitter TTLs / single-flight / temporarily lengthen TTL  
4. Split pools; kill sync waits on same pool  

**(c) Durable pool fix:** dedicated fan-out pool (or async) with bounded queue + ABORT; never join fan-out on the accept/handler pool.

---

## Part 4

**Q13:** Burst envelope / sustained average ignored; need smaller C, honest R, concurrency limits, tenant aggregates, load shed — square-wave clients.

**Q14:** Canary TTL; watch origin QPS + hit ratio; gradual steps; auto-revert on origin burn; don't global-push 5m→5s.

---

## Score sheet

```text
RF ____ /8
Applied ____ /9
Compound ____ /6
Blind ____ /6
TOTAL ____ /29
```
