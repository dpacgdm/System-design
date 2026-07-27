# LLD: Worker Pool / Task Executor (SRE-thick)

**Contract:** MODULE_CONTRACT_V2 · **Archetype:** Design · **Tier:** Core (SRE LLD)  
**Prep:** [TIMED_INTERVIEW_OS](../00-Curriculum/TIMED_INTERVIEW_OS.md) · [Queues](../Week-06-Architecture-Patterns/Message%20Queues%20and%20Kafka.md) · [Backpressure](../Week-06-Architecture-Patterns/Circuit%20Breakers%20Bulkheads%20Timeouts%20Retries%20and%20Backpressure.md)  
**Timebox:** 45 min · **Drill:** 20 min micro  
**Sealed:** [answers/Week-15c-SRE-LLD/LLD Worker Pool.answers.md](../answers/Week-15c-SRE-LLD/LLD%20Worker%20Pool.answers.md)

---

## Why this is SRE LLD

Every service hides a pool: request threads, async executors, cron runners, queue consumers. Mis-sized pools cause **latency death spirals**, **deadlocks**, and **silent queue growth**. This module is concurrency + operability, not "use ExecutorService."

---

## Problem statement

Design a worker pool that:

- Accepts tasks with timeout / deadline / priority (optional)
- Bounds concurrency and queue depth
- Applies rejection / backpressure policy when saturated
- Supports graceful shutdown (drain vs cancel)
- Exposes queue depth, active workers, wait time, reject count

Stretch: work-stealing; per-tenant fair shares; separate CPU vs IO pools.

---

## Requirements

| Dimension | Target | Tradeoff |
|-----------|--------|----------|
| Throughput | Saturate useful concurrency | Oversubscribe ≠ faster (context switch) |
| Latency | Queue wait visible in SLOs | Unbounded queue hides overload |
| Reliability | No task silently dropped without metric | Reject vs block caller |
| Shutdown | In-flight complete within grace | Force kill after deadline |
| Isolation | Slow task doesn't starve forever | Need timeout + interrupt policy |

---

## Interfaces

```text
interface WorkerPool {
  Future<R> submit(Task<R> task, SubmitOptions opts);
  void shutdown(Duration grace);
  PoolStats stats();
}

record SubmitOptions(Duration timeout, Priority priority, String tenant);
enum RejectPolicy { ABORT, CALLER_RUNS, BLOCK_BOUNDED, DROP_OLDEST, DROP_NEWEST }

class Task<R> {
  R run(CancellationToken token) throws Exception;
}
```

Internal:

```text
workers: Thread[n]
queue: BlockingQueue<Runnable>  // ArrayBlockingQueue capacity Q
active: AtomicInteger
```

---

## Sizing model (say this out loud)

- **CPU-bound:** `n ≈ cores` (or cores+1)
- **IO-bound:** `n ≈ cores * (1 + wait/compute)` — estimate, then measure
- **Queue depth Q:** bounds *worst-case wait* ≈ `(Q / service_rate)`; tie to SLO
- **Never** unbounded `LinkedBlockingQueue` in production paths without a story

Little's Law: `L = λW` — if queue grows, either λ too high or W (service time) regressed.

---

## Concurrency hazards

1. **Deadlock:** pool tasks wait on other pool tasks (same pool) — classic. Fix: separate pools or async handoff; never sync-wait on same pool.
2. **ThreadLocal leaks:** clear on task end; especially with request context / MDC.
3. **Interrupt policy:** timeout must interrupt or cooperative cancel; document if blocking IO ignores interrupt.
4. **Lock convoy:** synchronized work inside tasks → effective parallelism ≪ n.
5. **Priority inversion:** naive priority queue + starvation — aging / fair queues for multi-tenant.

---

## Rejection & backpressure

| Policy | When | Risk |
|--------|------|------|
| ABORT (reject) | Default API | Caller must retry with jitter |
| CALLER_RUNS | Soft load shed | Caller thread blocked — can deadlock servlet pool |
| BLOCK_BOUNDED | Rare | Turns async into sync under load |
| DROP_OLDEST | Telemetry / best-effort | Data loss — metric required |
| DROP_NEWEST | Protect in-flight | New work lost |

**SRE rule:** rejection is a **feature** if metered and alarmed; silent unbounded queue is an outage delayed.

---

## Graceful shutdown

```text
1. stopAccepting = true
2. reject new submit
3. interrupt idle workers / signal poison
4. wait grace for active + queued (policy: drain queue or cancel queued)
5. after grace: cancel remaining, log abandoned count
6. export final stats
```

Hook to k8s `preStop` + `terminationGracePeriodSeconds`.

---

## Operability

**Metrics:** `active_workers`, `queue_depth`, `queue_wait_p95`, `task_runtime_p95`, `rejects`, `timeouts`, `abandoned_on_shutdown`.  
**Logs:** slow-task samples with task type (cardinality-safe).  
**Alerts:** queue_depth SLO burn; reject rate; task_runtime regression after deploy.  
**Runbooks:** shrink/grow pool; flip reject policy; disable feature writing tasks.

---

## Sketch → critique

```text
Handler → pool.submit(task, timeout=2s, ABORT)
  → worker runs with deadline
  → on RejectedExecution → 503 + Retry-After
Shutdown → preStop → pool.shutdown(grace=25s)
```

**Critique:** servlet pool == worker pool? task calls downstream with no timeout? tenant A floods queue?

---

## 20-min micro-drill

Design IO-bound pool for fan-out calls: sizing formula, queue bound tied to p99, reject policy, deadlock avoidance with two pools (accept vs fan-out), 3 metrics + 1 alert.

---

## Self-check

- [ ] Bounded queue + explicit reject policy
- [ ] Sizing rationale (CPU vs IO)
- [ ] Deadlock with same-pool wait called out
- [ ] Timeouts / cancellation
- [ ] Shutdown + k8s grace alignment
- [ ] Queue depth in SLO/alerts

---

## Blind transfer

p99 latency climbs; CPU idle; queue_depth flat; active_workers at max. Where is the bottleneck hiding?
