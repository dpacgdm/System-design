# Answer Key — LLD Worker Pool / Task Executor (SRE-thick)

> Open only after attempting the learner module and 20-min micro-drill.

## Grading bar (Staff)

| Criterion | Points | Pass |
|-----------|-------:|------|
| Bounded queue + reject policy | 5 | No unbounded silent queue |
| Sizing rationale CPU vs IO | 4 | Formula + measure |
| Deadlock (same-pool wait) | 5 | Named + mitigation |
| Timeouts / cancellation | 4 | Deadline + interrupt/cooperative story |
| Shutdown + k8s grace | 4 | stopAccepting → drain → force |
| Multi-tenant / fairness (basic) | 3 | Or explicitly deferred with risk |
| Operability | 5 | queue depth, wait, rejects, runtime |
| Blind transfer | 4 | Idle CPU + max workers diagnosis |
| **Staff pass** | **/34** | **≥24** and no automatic fail |

**Automatic fails:** `Executors.newCachedThreadPool()` as production default; unbounded queue with "we'll monitor"; tasks waiting synchronously on same pool with no deadlock callout; no rejection metric.

---

## Expert model

### Core

```text
n workers (threads)
ArrayBlockingQueue<Runnable> capacity Q
RejectPolicy policy
AtomicInteger active
idle workers block on queue.take()
submit: offer/put/reject per policy
```

### SubmitOptions

- `timeout` / deadline propagated as `CancellationToken` or `Deadline` in context
- `priority` optional — default FIFO for predictability
- `tenant` for fair queues / metrics

### RejectPolicy Staff guidance

| Policy | Use | Avoid when |
|--------|-----|------------|
| ABORT | Default request path | Caller ignores 503 |
| CALLER_RUNS | Best-effort soft shed | Caller is servlet thread pool — deadlock risk |
| BLOCK_BOUNDED | Rare internal | Turns latency into sync stall |
| DROP_OLDEST | Metrics/logs | Billing, money, auth |
| DROP_NEWEST | Protect in-flight | Need newest events |

**Meter every reject.** Unmetered drop is a silent outage.

---

## Sizing

### CPU-bound
`n ≈ availableCores` (or cores+1). Oversubscribe → context-switch tax.

### IO-bound
`n ≈ cores * (1 + wait/compute)`. Example: 20% compute 80% wait → ~5× cores. **Then load-test.**

### Queue depth Q
Worst-case added wait ≈ `Q / service_rate` under saturation.  
If p99 SLO budget for queue wait is 50ms and service_rate is 2000 tasks/s: `Q ≈ 0.05 * 2000 = 100` (order-of-magnitude; validate).

### Little's Law
`L = λW`. Growing `L` (queue+active) with flat λ ⇒ W regressed (slow dependency). Growing L with rising λ ⇒ admission control.

---

## Deadlock — mandatory story

```text
Request thread pool P (size 50)
Handler submits fan-out tasks to P and waits .get()
Each task needs another P thread
50 requests × 2 tasks → need 100 threads → deadlock / stall
```

**Fixes:**
1. Separate pools: `acceptPool` vs `fanOutPool`
2. Async composition (callbacks / reactive) without blocking join on same pool
3. Semaphore for fan-out concurrency separate from thread count
4. Never `future.get()` on tasks of the pool you're running on

**CALLER_RUNS hazard:** under saturation, work runs on servlet threads → can deadlock with other blocking.

---

## Timeouts & cancellation

1. **Deadline** on task from submit time (or parent request deadline remaining).
2. Cooperative: task checks `token.isCancelled()` between units of work.
3. Interrupt: `future.cancel(true)` for interruptible blocking.
4. Blocking IO that ignores interrupt: use socket/read timeouts; document unclean cancel.
5. Downstream calls: **always** have their own timeouts — pool timeout ≠ dependency timeout.

---

## Graceful shutdown (k8s aligned)

```text
preStop: sleep 2–5s (LB denylist) OR fail readiness immediately
stopAccepting = true
reject new submit with clear error
drain: wait up to grace for active (+ optionally queued)
policy choice:
  - DRAIN_QUEUE: finish queued within grace
  - CANCEL_QUEUED: drop queued, finish active only
after grace: interrupt/cancel remaining; metric abandoned_on_shutdown
exit
terminationGracePeriodSeconds > preStop + pool grace + buffer
```

Mismatch = SIGKILL mid-write → corruption / partial side effects.

---

## Fairness / multi-tenant

Naive shared FIFO: tenant A floods → tenant B latency dies.

Options:
- Per-tenant subqueues + weighted round-robin
- Per-tenant concurrency caps (semaphore)
- Separate pools for classes of work (interactive vs batch)
- Priority with aging to prevent starvation

Staff minimum: name the risk + one mitigation; Principal builds WRR.

---

## Failure modes

| Failure | Symptom | Fix |
|---------|---------|-----|
| Unbounded queue | Latency climbs; CPU looks fine early | Bound + reject |
| Pool too small | High queue wait; CPU idle (if IO wait elsewhere?) | Resize or fix downstream |
| Pool too large | CPU thrash; DB connection storm | Cap; bulkhead deps |
| Same-pool deadlock | Threads all WAITING; progress zero | Split pools |
| ThreadLocal leak | Wrong auth/tenant on later task | Clear in finally |
| No timeout | Stuck active forever | Deadline + cancel |
| Priority starvation | Low-pri never runs | Aging / fair share |
| Shutdown kill | Partial writes | Align k8s grace |

---

## Operability exemplar

**Metrics:**
- `pool_active_workers`
- `pool_queue_depth`
- `pool_queue_wait_ms` (p50/p95/p99)
- `pool_task_runtime_ms`
- `pool_rejects_total{policy}`
- `pool_timeouts_total`
- `pool_abandoned_on_shutdown`

**Alerts:**
1. Queue depth SLO / wait p99 burn
2. Reject rate > 0 sustained on critical pool
3. Task runtime regression after deploy
4. Active at max + queue growing + dependency latency up (cascade)

**Runbooks:** flip reject policy; shed load feature; scale pods; rollback deploy; disable noisy tenant.

---

## 20-min micro-drill — Staff key

**Scenario:** IO-bound fan-out HTTP to 8 deps.

**Sizing:** start `n = cores * 4` (hypothesis), measure; cap by DB/http client max connections.

**Queue:** bound so wait p99 < remaining latency budget (e.g. Q=100–500 — justify).

**Reject:** ABORT → 503 Retry-After; never CALLER_RUNS on servlet threads.

**Deadlock avoidance:**  
- Pool A: request handlers (or use server's container threads carefully)  
- Pool B: fan-out workers  
Handler must not block waiting on Pool A tasks.

**Metrics:** queue_depth, queue_wait_p95, rejects  
**Alert:** rejects > threshold OR wait_p99 > budget for 5m

---

## Blind transfer — Staff answer

**Clue decode:** CPU idle + `active_workers == max` + `queue_depth` flat.

Workers are busy but not burning CPU ⇒ **blocked on IO / locks / dependency**, not compute-bound insufficient CPU.

**Where bottleneck hides:**
1. Downstream dependency latency / thread pool / connection pool exhaustion
2. Lock contention inside tasks (app lock, synchronized DB)
3. DNS / connect hang without timeout
4. Accidental sleep/backoff storms
5. External rate limit causing waits

**Not:** "add more workers" as first fix (may worsen connection storms). First: task runtime breakdown, dependency p99, thread dump (WAITING vs RUNNABLE), connection pool metrics.

---

## Sketch critique answers

**Servlet pool == worker pool?** Dangerous. Separate or fully async.

**Task calls downstream with no timeout?** Pool threads stick; active max forever; looks like this blind transfer.

**Tenant A floods?** Shared FIFO starvation — fair queues or per-tenant caps.

---

## Below-bar vs Staff

**Below bar:** "newFixedThreadPool(100) and LinkedBlockingQueue."  
**Staff:** Questions 100; bounds queue; reject policy; deadlock; metrics; IO vs CPU.

**Below bar:** "We'll scale the pool when load increases."  
**Staff:** Autoscale pods maybe; unbounded in-process growth hides overload and melts dependencies.

---

## Principal stretch

1. Work-stealing vs fixed workers for mixed task sizes.  
2. Adaptive concurrency (AIMD) instead of static n.  
3. Dual deadlines: queue admission deadline vs run deadline.

### Stretch sketches

1. ForkJoin good for compute dawgs; IO often better fixed + bounded queue.  
2. AIMD: increase n while p99 healthy; decrease on overload — combine with shed.  
3. Reject early if deadline already insufficient for queue wait estimate.

---

## Interview narration beats (45)

0–5: requirements, reject vs block  
5–15: API + sizing math  
15–25: deadlock + timeouts  
25–35: shutdown/k8s  
35–45: metrics + blind diagnosis  

---

## Scoring worksheet

```text
Bound/reject ____ /5
Sizing ____ /4
Deadlock ____ /5
Timeouts ____ /4
Shutdown ____ /4
Fairness ____ /3
Ops ____ /5
Blind ____ /4
TOTAL ____ /34
Auto-fail? ____
```

---

## Tie-ins

- Week-08b backpressure / load shed  
- Message queues: consumer worker pools  
- Rate limiter: admission before pool submit  
- Cache loader: use bounded pool for loads  

---

## Thread dump cheat sheet (for ops realism)

| State | Likely |
|-------|--------|
| RUNNABLE high CPU | Compute / spin / GC survivor |
| WAITING on queue | Idle worker OK |
| BLOCKED on lock | Lock convoy |
| WAITING on future/dep | Downstream / deadlock pattern |

---

## Code-shaped mental model (Java-ish)

```text
ThreadPoolExecutor(
  core = n,
  max = n,              // fixed
  keepAlive = 0,
  queue = ArrayBlockingQueue(Q),
  handler = AbortPolicy // metered wrapper
)
```

Wrap submit to record queue wait = startRun - enqueueTime.

---

## End state claim

Staff-ready when you refuse unbounded queues, split pools to avoid deadlock, align k8s grace, and diagnose "idle CPU + max active" as dependency/block — not missing cores.
