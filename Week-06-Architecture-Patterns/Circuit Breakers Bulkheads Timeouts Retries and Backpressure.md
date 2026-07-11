# Week 6, Topic 5 — Circuit Breakers, Bulkheads, Timeouts, Retries, and Backpressure

> Distributed systems do not fail one service at a time. They fail in chains — a slow database becomes a full thread pool, which becomes retry storms, which becomes open circuit breakers on unrelated paths, which becomes a checkout outage. This module teaches the five mechanisms that stop those chains, how they compose, and how to configure them in production without making things worse.

---

## Learning Objectives

```
╔════════════════════════════════════════════════════════════════╗
║   AFTER THIS TOPIC, YOU WILL BE ABLE TO:                       ║
╟────────────────────────────────────────────────────────────────╢
║                                                                ║
║   1. Explain circuit breaker state machine (closed,            ║
║      open, half-open), transition triggers, and why            ║
║      half-open probing must be rate-limited                    ║
║                                                                ║
║   2. Design bulkhead isolation for thread pools,               ║
║      connection pools, and semaphores — and know when          ║
║      each isolation boundary belongs at which layer            ║
║                                                                ║
║   3. Allocate timeout budgets across a microservice            ║
║      call chain so parent deadlines propagate to               ║
║      children (gRPC deadlines, context cancellation)           ║
║                                                                ║
║   4. Configure retries with exponential backoff and            ║
║      full jitter, and articulate when retries amplify          ║
║      outages vs when they are mandatory (payments)             ║
║                                                                ║
║   5. Distinguish hedging from retry, choose between            ║
║      them, and explain tail-latency trade-offs                 ║
║                                                                ║
║   6. Implement backpressure propagation: bounded               ║
║      queues, shed load at ingress, and reactive                ║
║      demand signaling                                          ║
║                                                                ║
║   7. Configure Resilience4j, Istio DestinationRule,            ║
║      and Envoy outlier detection with exact YAML               ║
║      and explain what each knob does                           ║
║                                                                ║
║   8. Connect AWS ALB/NLB idle and request timeouts             ║
║      (Week 1) to application-level deadline budgets            ║
║                                                                ║
║   9. Diagnose cascading failure incidents: identify            ║
║      retry amplification, bulkhead saturation, and             ║
║      missing timeout propagation from metrics and logs         ║
╚════════════════════════════════════════════════════════════════╝
```

**Prerequisite mental model.** Every outbound call is a loan against your capacity. Timeouts are the due date. Retries are refinancing — sometimes necessary, often catastrophic at scale. Circuit breakers stop you from lending to a bankrupt borrower. Bulkheads ensure one bad loan doesn't consume your entire balance sheet. Backpressure is the market signal that says "stop lending."

---

## Wrong Mental Models (Destroy These First)

```
╔═════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Retries fix transient failures"                 ║
╟─────────────────────────────────────────────────────────────────────╢
║   PARTIALLY WRONG. Retries fix YOUR transient failures on a         ║
║   healthy dependency. On a DEGRADED dependency, retries             ║
║   multiply load: 1000 clients × 3 retries = 4000 requests           ║
║   against a service that was failing at 1000. You turned a          ║
║   partial outage into a total outage. Retries require:              ║
║   (a) idempotency, (b) jittered backoff, (c) retry budgets,         ║
║   (d) circuit breaker upstream.                                     ║
╠═════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "Circuit breaker = stop calling the service"     ║
╟─────────────────────────────────────────────────────────────────────╢
║   INCOMPLETE. A circuit breaker is a STATE MACHINE with three       ║
║   states. OPEN means fail-fast (return cached/default/error         ║
║   immediately). HALF-OPEN means probe with LIMITED traffic          ║
║   to test recovery. CLOSED means normal. The dangerous mistake:     ║
║   opening the circuit but still queuing requests behind a           ║
║   full thread pool — the queue IS the problem.                      ║
╠═════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "Set one global timeout and you're done"         ║
╟─────────────────────────────────────────────────────────────────────╢
║   WRONG. A 30-second HTTP client timeout on a 5-hop chain           ║
║   means each hop can consume 30 seconds independently if            ║
║   deadlines don't propagate. Total user wait: 150 seconds.          ║
║   Correct model: ONE end-to-end budget, subdivided per hop,         ║
║   with parent context cancellation on expiry.                       ║
╠═════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "Bulkheads are only for thread pools"            ║
╟─────────────────────────────────────────────────────────────────────╢
║   WRONG. Bulkheads exist at every resource boundary:                ║
║   thread pools, connection pools, semaphores, K8s CPU/memory        ║
║   limits, Kafka partition isolation, separate clusters,             ║
║   separate ALB target groups. Any shared pool without a             ║
║   limit is a bulkhead violation waiting to happen.                  ║
╠═════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Backpressure = slow down the consumer"          ║
╟─────────────────────────────────────────────────────────────────────╢
║   TOO NARROW. Backpressure is a SIGNAL propagated UPSTREAM:         ║
║   "I cannot accept more work." It must reach the producer           ║
║   (HTTP 429, gRPC RESOURCE_EXHAUSTED, TCP zero-window,              ║
║   Kafka consumer pause, reactive Streams request(n)).               ║
║   Slowing the consumer without signaling upstream =                 ║
║   unbounded queue growth = OOM.                                     ║
╠═════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #6: "Hedging is just aggressive retry"               ║
╟─────────────────────────────────────────────────────────────────────╢
║   WRONG. Retry waits for failure, then tries again (sequential      ║
║   or delayed). Hedging sends a DUPLICATE in-flight request          ║
║   before the first completes (parallel). Hedging cuts tail          ║
║   latency but DOUBLES load on the dependency. Use hedging           ║
║   only on idempotent reads with low fan-out — never on              ║
║   writes, never during incidents.                                   ║
╠═════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #7: "The load balancer handles resilience"           ║
╟─────────────────────────────────────────────────────────────────────╢
║   WRONG. ALB/NLB health checks and connection draining are          ║
║   necessary but insufficient. ALB idle timeout (60s default)        ║
║   kills long-polling and WebSockets if misconfigured. NLB           ║
║   passes through TCP — no retry, no circuit breaker.                ║
║   Application-level patterns (this module) are mandatory            ║
║   ON TOP OF infrastructure timeouts.                                ║
╚═════════════════════════════════════════════════════════════════════╝
```

---

## Core Teaching

### Foundation

> Staff / Principal stretch sections are marked below. Mastery gate: Staff required; Principal optional.

### The Cascading Failure Problem

```
WHY THIS MODULE EXISTS:
━━━━━━━━━━━━━━━━━━━━━━━

  A single slow dependency does not cause an outage.
  AMPLIFICATION causes the outage.

  THE AMPLIFICATION CHAIN:

    1. payments-db latency: 50ms → 2000ms (disk stall)
    2. payments-svc threads block waiting on DB
    3. payments-svc thread pool saturates (200/200 busy)
    4. New requests queue at payments-svc (or at ALB)
    5. checkout-svc calls payments-svc, blocks on HTTP client
    6. checkout-svc thread pool saturates
    7. checkout-svc retries payments-svc (3× per request)
    8. payments-svc receives 3× load while already saturated
    9. fraud-svc calls payments-svc for validation — also blocked
   10. Entire payment path is down; unrelated catalog reads
       may still work — but checkout is dead

  ╔══════════════════════════════════════════════════════════════╗
  ║   AMPLIFICATION FACTORS IN PRODUCTION:                       ║
  ╟──────────────────────────────────────────────────────────────╢
  ║   Retries without jitter     → N_clients × retry_count       ║
  ║   No timeout propagation     → sum(hop_timeouts)             ║
  ║   Shared thread pool         → one slow call blocks all      ║
  ║   No circuit breaker         → calls continue to dead svc    ║
  ║   Unbounded queues           → memory exhaustion (OOMKill)   ║
  ║   Retry on non-idempotent    → duplicate charges             ║
  ╚══════════════════════════════════════════════════════════════╝

  THE FIVE DEFENSES (this module):

    Circuit Breaker  → stop calling known-bad dependencies
    Bulkhead         → limit blast radius of slow calls
    Timeout          → bound wait time; release resources
    Retry (+ jitter) → recover from transient faults SAFELY
    Backpressure     → signal upstream before queues explode
```

### Circuit Breakers — The State Machine

```
CIRCUIT BREAKER = FAIL-FAST PROXY IN FRONT OF A DEPENDENCY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Instead of:
    Client ──(wait 30s)──► Dead Service ──► timeout ──► error

  With circuit breaker OPEN:
    Client ──► Circuit Breaker ──► immediate error / fallback
                    │
                    └── (does NOT call dead service)


THE THREE STATES:
━━━━━━━━━━━━━━━━━

                    failure rate > threshold
         ┌──────────────────────────────────────┐
         │                                      │
         ▼                                      │
    ┌─────────┐   success    ┌───────────┐      │
    │ CLOSED  │◄─────────────│ HALF-OPEN │      │
    │         │              │           │      │
    │ Normal  │──failure────►│  Probing  │──────┘
    │ traffic │  rate high   │  limited  │  probe fails
    └─────────┘              │  traffic  │
         ▲                   └───────────┘
         │                         │
         │    wait duration        │ probe succeeds
         │    elapses              │ (enough successes)
         └─────────────────────────┘


STATE: CLOSED (normal operation)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  All requests pass through to the dependency.
  The breaker COUNTS outcomes:
    - failures (exceptions, 5xx, timeouts)
    - slow calls (latency > slowCallDurationThreshold)
    - successes

  Sliding window (count-based OR time-based):
    Resilience4j default: count-based, window size 100 calls
    Istio/Envoy: passive outlier detection over interval

  Transition to OPEN when:
    failureRate >= failureRateThreshold  (e.g., 50%)
    OR slowCallRate >= slowCallRateThreshold (e.g., 80%)
    over the configured window.


STATE: OPEN (fail-fast)
━━━━━━━━━━━━━━━━━━━━━━━

  All requests are REJECTED immediately without calling
  the dependency.

  Return value options (application decides):
    - Propagate error (CallNotPermittedException)
    - Cached/stale response
    - Default/degraded response
    - Queue for async retry (dangerous if queue unbounded)

  Duration: waitDurationInOpenState (e.g., 60 seconds)
  After this, transition to HALF-OPEN automatically.


STATE: HALF-OPEN (recovery probing)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  A LIMITED number of probe requests are allowed through.
  This is critical: if you allow full traffic during
  recovery testing, you may re-trip the breaker immediately.

  Resilience4j: permittedNumberOfCallsInHalfOpenState (e.g., 10)
  If probes succeed → CLOSED
  If any probe fails → OPEN (reset wait timer)

  THE HALF-OPEN TRAP:
    Setting permittedNumberOfCallsInHalfOpenState too high
    (e.g., 1000) during a partial recovery floods the
    still-weak dependency and re-opens the circuit.
    Start with 5-10 probes.


COUNT-BASED vs TIME-BASED SLIDING WINDOW:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Count-based (Resilience4j default):
    Last N calls determine failure rate.
    Pros: stable under variable traffic.
    Cons: slow to react at low traffic (need N calls).

  Time-based:
    All calls in last T seconds.
    Pros: reacts to time-windowed spikes.
    Cons: noisy at low traffic (3 failures in 10s = 100%).

  PRODUCTION RULE:
    High-traffic path → count-based, window 50-200
    Low-traffic path → time-based OR minimum call threshold
    Resilience4j: minimumNumberOfCalls before evaluating
    (prevents opening on first failure)


AUTOMATIC vs MANUAL STATE TRANSITION:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Automatic (default): thresholds drive transitions.
  Manual: operator forces OPEN during known maintenance.
  Forced open should still respect waitDuration before
  half-open — or operator must explicitly reset.

  Resilience4j:
    circuitBreaker.transitionToOpenState()
    circuitBreaker.transitionToClosedState()
    circuitBreaker.reset()  // clears metrics + closes
```

### Bulkheads — Isolation Boundaries

```
BULKHEAD = COMPARTMENT THAT LIMITS FLOOD DAMAGE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Named after ship bulkheads: one compartment floods,
  the ship stays afloat.

  WITHOUT BULKHEAD:
    ┌─────────────────────────────────────────────┐
    │           Shared Thread Pool (200)          │
    │                                             │
    │    ┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐  │
    │    │  pay  │ │ fraud │ │catalog│ │notify │  │
    │    └───│───┘ └───│───┘ └───│───┘ └───│───┘  │
    │        └─────────┴─────────┴─────────┘      │
    │                                             │
    │           ALL 200 threads blocked           │
    │             on slow payments-db             │
    └─────────────────────────────────────────────┘
    Result: catalog reads fail too.

  WITH BULKHEAD (thread pool per dependency):
    ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
    │ payments     │ │ fraud        │ │ catalog      │
    │ pool (50)    │ │ pool (30)    │ │ pool (100)   │
    │ [SATURATED]  │ │ [idle: 28]   │ │ [idle: 97]   │
    └──────────────┘ └──────────────┘ └──────────────┘
    Result: catalog still serves. Payments fail fast
    when pool exhausted (reject, don't queue forever).


BULKHEAD TYPES:
━━━━━━━━━━━━━━━

  1. THREAD POOL ISOLATION (Hystrix-style, Resilience4j)
     Dedicated executor per dependency.
     maxThreadPoolSize, queueCapacity.
     When pool + queue full → reject immediately.

  2. SEMAPHORE ISOLATION (lighter weight)
     Limit concurrent calls without separate threads.
     maxConcurrentCalls (e.g., 25).
     Caller thread executes work — no context switch overhead.
     Cannot set per-call timeout on semaphore path
     (timeout must be on the call itself).

  3. CONNECTION POOL ISOLATION
     Separate HTTP connection pools per downstream:
       payments-client: maxConnections=20
       catalog-client:  maxConnections=100
     Prevents one slow service from exhausting all
     outbound connections.

  4. PROCESS / CONTAINER ISOLATION (K8s)
     Separate deployments per domain:
       payments-svc:  replicas=10, CPU limit 2, memory 4Gi
       catalog-svc:   replicas=20, CPU limit 1, memory 2Gi
     OOM in payments pod does not kill catalog pods.

  5. CLUSTER / INFRASTRUCTURE ISOLATION
     Separate Kafka cluster for analytics vs payments.
     Separate RDS instance for payments vs catalog.
     The ultimate bulkhead — highest cost, strongest isolation.


THREAD POOL vs SEMAPHORE — DECISION:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Thread pool:
    ✓ True timeout enforcement (cancel blocked thread's work)
    ✓ Isolates blocking I/O from caller thread
    ✗ Thread overhead (~1MB stack per thread)
    ✗ Context switching cost
    Use when: blocking HTTP/JDBC calls, need hard timeout

  Semaphore:
    ✓ Near-zero overhead
    ✓ Good for non-blocking / async (reactive)
    ✗ Caller thread still blocked if dependency blocks
    ✗ No built-in timeout isolation
    Use when: async/reactive stack, high fan-out, low latency


QUEUE CAPACITY IS A BULKHEAD KNOB:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  threadPool.queueCapacity = 0  → fail immediately when pool full
                                  (BEST for latency-sensitive paths)

  threadPool.queueCapacity = 100 → accept 100 waiting tasks
                                   (DANGEROUS: 100 × 30s timeout
                                    = 3000 thread-seconds of backlog)

  PRODUCTION RULE FOR PAYMENTS:
    queueCapacity = 0 or very small (≤ 10)
    Prefer fail-fast + circuit breaker over queuing
```

### Timeouts and Deadline Budgets

```
TIMEOUT = THE HARD STOP THAT RELEASES RESOURCES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Without timeout:
    Thread blocked forever → pool exhaustion → cascade

  With timeout:
    Thread released after T → pool slot freed → system survives


THE TIMEOUT BUDGET PROBLEM:
━━━━━━━━━━━━━━━━━━━━━━━━━━

  User-facing SLO: checkout must complete in 3 seconds (p99).

  Call chain:
    mobile-app → api-gateway → checkout-svc → payments-svc
              → fraud-svc → payments-db

  NAIVE (wrong):
    Each service sets client timeout = 30s
    Total possible wait: 5 hops × 30s = 150s
    User abandoned at 3s; servers still working for 147s more

  CORRECT (deadline propagation):
    api-gateway sets deadline = now + 3000ms
    Passes deadline in gRPC metadata / HTTP header
    Each hop subtracts elapsed time:
      checkout-svc: remaining = 3000 - 50 (gateway overhead) = 2950ms
      payments-svc: remaining = 2950 - 100 = 2850ms
      fraud-svc:      remaining = 2850 - 200 = 2650ms
    Any hop with remaining ≤ 0 → fail immediately (DEADLINE_EXCEEDED)


DEADLINE PROPAGATION MECHANISMS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  gRPC:
    context.withDeadlineAfter(3, SECONDS)
    Propagates automatically in metadata (grpc-timeout header)

  Go:
    ctx, cancel := context.WithTimeout(parentCtx, 2500*time.Millisecond)
    defer cancel()
    Child calls inherit parent deadline (min of parent and local)

  Java (Resilience4j + gRPC):
    Context deadline from incoming call applied to outgoing

  HTTP (no native standard — conventions):
    X-Request-Deadline: 2026-07-06T10:15:03.000Z (absolute)
    OR X-Timeout-Ms: 2850 (remaining)
    Each hop MUST parse, subtract elapsed, forward remainder


PER-HOP BUDGET ALLOCATION:
━━━━━━━━━━━━━━━━━━━━━━━━━━

  Total budget B = 3000ms

  Allocation strategies:

  EQUAL SPLIT (simple, suboptimal):
    5 hops → 600ms each
    Problem: fraud-svc usually 50ms, payments-db usually 200ms
    Wastes budget on fast hops, starves slow hops

  WEIGHTED BY p99 LATENCY (better):
    gateway overhead:   50ms  (fixed)
    checkout-svc:      200ms  (local work)
    payments-svc:      400ms  (orchestration)
    fraud-svc:         300ms  (external API)
    payments-db:       500ms  (query)
    buffer:            200ms  (jitter absorption)
    ─────────────────────────
    Total:            1650ms  (headroom for retries within budget)

  DYNAMIC (best):
  Remaining budget passed per call. Fast hops finish early;
  slow hops get whatever is left. No wasted allocation.


TIMEOUT vs DEADLINE:
━━━━━━━━━━━━━━━━━━━

  Timeout: relative duration from NOW ("wait max 500ms")
  Deadline: absolute point in time ("must finish by T")

  Deadline is superior for chains because:
    - All hops share one clock
    - No sum-of-timeouts bug
    - Parent cancellation propagates to children

  Implementation: always prefer deadline propagation.
  Per-hop timeout = min(local_limit, remaining_deadline)


CONNECTING TO WEEK 1 — AWS LOAD BALANCER TIMEOUTS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  These are INFRASTRUCTURE bulkheads and timeouts.
  They do NOT replace application deadlines but interact
  with them — misalignment causes subtle bugs.

  ALB (Application Load Balancer):
    idle_timeout: default 60 seconds
      → Closes idle TCP connection after 60s no data
      → Kills long-polling, SSE, WebSockets if not configured
      → Fix: increase idle_timeout (max 4000s) for WS paths
    request timeout (target group attribute):
      → Max time for target to respond (1-4000s)
      → Independent of idle_timeout
    connection draining: deregistration_delay (default 300s)
      → In-flight requests complete during deploy

  NLB (Network Load Balancer):
    idle_timeout: default 350 seconds (TCP)
      → Layer 4 — no HTTP awareness
      → No request timeout at LB layer
      → Application MUST enforce its own deadlines
    Preserves source IP; passes through TCP semantics

  THE STACK (timeouts at each layer):
    ┌─────────────────────────────────────────────────────┐
    │ mobile-app network timeout          10s             │
    │ ALB idle_timeout                    60s             │
    │ ALB target group request timeout    30s (configured)│
    │ api-gateway deadline                3s              │
    │ checkout-svc → payments client      2.5s (remaining)│
    │ payments-svc → fraud client         2s (remaining)  │
    │ fraud-svc → external API            1.5s (remaining)│
    └─────────────────────────────────────────────────────┘

  RULE: each layer's timeout must be ≤ parent's timeout.
  If ALB request timeout = 30s but api-gateway deadline = 3s,
  the gateway fails at 3s (good). If reversed (gateway 30s,
  ALB 3s), ALB returns 504 while gateway still waiting — bad.
```

### Retries — Safe Recovery vs Amplification

```
RETRY = "TRY AGAIN AFTER FAILURE"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Appropriate when:
    - Operation is IDEMPOTENT (or has idempotency key)
    - Failure is TRANSIENT (network blip, 503, connection reset)
    - Dependency is NOT saturated (circuit breaker closed)
    - Retry budget prevents storm

  Inappropriate when:
    - Non-idempotent write without dedup key (duplicate charge)
    - Dependency returning 429 (rate limited — backoff MORE)
    - Circuit breaker OPEN (retry hammers dead service)
    - Latency SLO cannot absorb retry delay


EXPONENTIAL BACKOFF:
━━━━━━━━━━━━━━━━━━

  delay = baseDelay × 2^attempt

  attempt 0: 100ms
  attempt 1: 200ms
  attempt 2: 400ms
  attempt 3: 800ms
  attempt 4: 1600ms

  Cap at maxDelay (e.g., 30s).
  Total wait before giving up depends on maxAttempts.


JITTER — WHY IT IS MANDATORY:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Without jitter: 10,000 clients fail at T=0, all retry at
  T=100ms, T=200ms, T=400ms — SYNCHRONIZED RETRY STORM.

  FULL JITTER (AWS recommended):
    delay = random(0, min(maxDelay, baseDelay × 2^attempt))

  EQUAL JITTER:
    delay = (baseDelay × 2^attempt) / 2 + random(0, that/2)

  DECORRELATED JITTER:
    delay = random(baseDelay, previousDelay × 3)

  Production: use FULL JITTER unless you have evidence
  equal jitter is better for your traffic shape.


RETRY BUDGET:
━━━━━━━━━━━━

  Limit retries as fraction of total requests.

  Google SRE: retry budget = 10% of request volume
    If 1000 RPS normal, max 100 RPS can be retries.
    When budget exhausted → fail fast, don't retry.

  Resilience4j: maxAttempts + waitDuration caps total retry time
  Istio: retries.attempts + per-try timeout

  RETRY STORM MATH:
    1000 clients, 3 retries each, no jitter, simultaneous failure
    = 1000 + 3000 + 9000 = 13,000 requests in seconds
    against a service failing at 1000 RPS capacity


RETRIABLE vs NON-RETRIABLE ERRORS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  RETRY:
    HTTP 408, 429 (with longer backoff), 500, 502, 503, 504
    gRPC UNAVAILABLE, DEADLINE_EXCEEDED (if budget remains)
    Connection reset, connection timeout (TCP)

  DO NOT RETRY:
    HTTP 400, 401, 403, 404, 409, 422
    gRPC INVALID_ARGUMENT, NOT_FOUND, ALREADY_EXISTS
    Business logic failures (insufficient funds)

  GRAY ZONE:
    HTTP 500 from your own bug → retry won't help
    HTTP 503 with Retry-After header → honor header
```

### Hedging vs Retry

```
HEDGING = SEND DUPLICATE REQUEST BEFORE FIRST COMPLETES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Retry:     Request ──fail──► wait ──► Request again
  Hedging:   Request ────────────────►
             Request (duplicate) ────► (whichever returns first wins)

  From "The Tail at Scale" (Dean & Barroso, Google):
    Tail latency dominates p99 at large scale.
    If 1% of servers are 10× slow, fan-out of 100 backends
    means 63% of requests hit at least one slow server.

  Hedging reduces tail latency by racing duplicates.


WHEN HEDGING HELPS:
━━━━━━━━━━━━━━━━━━

  - Idempotent READ operations
  - Low fan-out (1-3 replicas, not 100)
  - Dependency has spare capacity
  - p99 latency matters more than average load
  - Hedged delay > typical latency (don't hedge immediately)

  Example: read from 3 replicas, hedge after 50ms
    T=0:   send to replica A
    T=50ms: if no response, also send to replica B
    T=51ms: A responds → cancel B (if possible)


WHEN HEDGING HURTS:
━━━━━━━━━━━━━━━━━

  - WRITE operations (double write risk)
  - Dependency already saturated (doubles load during incident)
  - High fan-out (hedge 100 shards = 200 requests)
  - Non-idempotent side effects even on "read" (audit log)

  THE INCIDENT PATTERN:
    Service degraded → latency rises → hedging kicks in
    → 2× load on degraded service → worse latency
    → more hedging → positive feedback loop → collapse


HEDGING CONFIGURATION (conceptual):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  hedgeDelay: 50ms        // wait before sending duplicate
  maxHedgedRequests: 1   // only one duplicate per original
  hedgeOnPercentile: p95  // only hedge if historical p95 > threshold

  Istio does NOT have native hedging in DestinationRule.
  Implement in application or custom Envoy filter.
  gRPC: no built-in hedging; application-level.


RETRY vs HEDGING DECISION:
━━━━━━━━━━━━━━━━━━━━━━━━

  ┌────────────────────┬─────────────────┬─────────────────┐
  │                    │ Retry           │ Hedging         │
  ├────────────────────┼─────────────────┼─────────────────┤
  │ Trigger            │ After failure   │ Before failure  │
  │ Timing             │ Sequential      │ Parallel        │
  │ Load multiplier    │ On failure only │ Always (tail)   │
  │ Idempotency need   │ Writes need key │ Reads only      │
  │ Tail latency       │ Increases       │ Decreases       │
  │ Incident behavior  │ Amplifies       │ Amplifies worse │
  └────────────────────┴─────────────────┴─────────────────┘
```

### Backpressure — Signaling Upstream

```
BACKPRESSURE = "I CANNOT ACCEPT MORE WORK RIGHT NOW"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Without backpressure:
    Producer ──(fast)──► Unbounded Queue ──(slow)──► Consumer
                              │
                              └── grows until OOM

  With backpressure:
    Producer ◄──(slow down)── Consumer
    Producer ──(rate limited)──► Bounded Queue ──► Consumer


BACKPRESSURE MECHANISMS BY LAYER:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  TCP:
    Receive window shrinks → sender blocks
    Zero-window = hard backpressure

  HTTP/2:
    Flow control per stream and connection
    WINDOW_UPDATE frames

  gRPC:
    HTTP/2 flow control underneath
    Server: maxConcurrentCalls limit
    Status RESOURCE_EXHAUSTED → client backs off

  Reactive Streams (RxJava, Project Reactor):
    request(n) — subscriber demands n items
    Publisher cannot emit more than demanded

  Application:
    Bounded queue + reject when full (ThreadPoolExecutor)
    HTTP 429 Too Many Requests
    HTTP 503 Service Unavailable + Retry-After

  Message queues:
    Consumer pauses (Kafka: pause partitions)
    Lag grows → alert → scale consumers OR throttle producers
    SQS: visibility timeout + max receive count → DLQ

  Kubernetes:
    CPU throttling (CFS quota)
    OOMKill when memory limit exceeded
    HPA scales on CPU/lag/custom metrics


BACKPRESSURE PROPAGATION CHAIN:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  payments-db slow
       │
       ▼
  payments-svc thread pool full
       │
       ├──► should: return 503 to checkout-svc immediately
       │              (backpressure signal)
       │
       └──► wrong: accept request, queue internally, timeout at 30s
                    checkout-svc doesn't know to stop sending

  checkout-svc receives 503:
       │
       ├──► should: circuit breaker opens, fail checkout fast
       │              shed load at API gateway (429 to clients)
       │
       └──► wrong: retry 3× immediately (amplifies)


LOAD SHEDDING vs BACKPRESSURE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Load shedding: DROP requests when overloaded
    (admission control at ingress)
    "I'd rather fail 10% than fail 100% slowly"

  Backpressure: SLOW DOWN producers
    (rate reduction upstream)
    "Send less, I'll tell you when I can take more"

  Production uses BOTH:
    Gateway: rate limit per client (proactive)
    Service: shed when queue depth > threshold (reactive)
    Circuit breaker: stop calling downstream (reactive)


ADAPTIVE CONCURRENCY LIMITS (advanced):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  TCP Vegas / BBR inspiration for microservices:
    Measure RTT and in-flight requests
    If RTT rising → reduce concurrency limit
    If RTT stable → slowly increase limit

  Netflix/concurrency-limits library:
    Gradient-based limit adjustment
    Replaces static bulkhead sizes with dynamic limits
```

### How the Five Patterns Compose

```
THE RESILIENCE STACK (order matters):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Ingress request
       │
       ▼
  ┌─────────────────┐
  │ Rate limit /    │  ← shed load before entering system
  │ admission ctrl  │
  └────────┬────────┘
           ▼
  ┌─────────────────┐
  │ Deadline check  │  ← fail if budget already exhausted
  │ (remaining ms)  │
  └────────┬────────┘
           ▼
  ┌─────────────────┐
  │ Circuit breaker │  ← fail fast if dependency known bad
  │ (per dependency)│
  └────────┬────────┘
           ▼
  ┌─────────────────┐
  │ Bulkhead        │  ← limit concurrent calls to dependency
  │ (pool/semaphore)│
  └────────┬────────┘
           ▼
  ┌─────────────────┐
  │ Timeout/deadline│  ← bound this specific call
  │ on outbound call│
  └────────┬────────┘
           ▼
  ┌─────────────────┐
  │ Retry + jitter  │  ← only if breaker closed, idempotent,
  │ (if applicable) │     within remaining budget
  └────────┬────────┘
           ▼
     Dependency call


FAILURE RESPONSE HIERARCHY:
━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. Success
  2. Degraded (cached/default response)
  3. Fail fast (circuit open, bulkhead full, deadline exceeded)
  4. Fail slow (timeout after waiting) ← WORST; avoid this layer
```

---

## Concrete Examples

### Resilience4j — Complete Configuration

```java
// application.yml — Resilience4j for payments-svc calling fraud-svc
resilience4j:
  circuitbreaker:
    instances:
      fraudService:
        registerHealthIndicator: true
        slidingWindowType: COUNT_BASED
        slidingWindowSize: 100
        minimumNumberOfCalls: 20
        permittedNumberOfCallsInHalfOpenState: 5
        automaticTransitionFromOpenToHalfOpenEnabled: true
        waitDurationInOpenState: 30s
        failureRateThreshold: 50
        slowCallRateThreshold: 80
        slowCallDurationThreshold: 2s
        recordExceptions:
          - java.io.IOException
          - java.util.concurrent.TimeoutException
          - org.springframework.web.client.HttpServerErrorException
        ignoreExceptions:
          - com.example.BusinessValidationException

  retry:
    instances:
      fraudService:
        maxAttempts: 3
        waitDuration: 100ms
        enableExponentialBackoff: true
        exponentialBackoffMultiplier: 2
        enableRandomizedWait: true          # full jitter
        randomizedWaitFactor: 0.5
        retryExceptions:
          - java.io.IOException
          - org.springframework.web.client.HttpServerErrorException
        ignoreExceptions:
          - com.example.BusinessValidationException

  bulkhead:
    instances:
      fraudService:
        maxConcurrentCalls: 25
        maxWaitDuration: 0                  # fail immediately when full

  timelimiter:
    instances:
      fraudService:
        timeoutDuration: 2s
        cancelRunningFuture: true

  thread-pool-bulkhead:
    instances:
      paymentsDb:
        maxThreadPoolSize: 30
        coreThreadPoolSize: 10
        queueCapacity: 0                    # no queuing — fail fast
        keepAliveDuration: 20ms
```

```java
// Java usage — decorator order matters
@CircuitBreaker(name = "fraudService", fallbackMethod = "fraudFallback")
@Retry(name = "fraudService")
@Bulkhead(name = "fraudService", type = Bulkhead.Type.SEMAPHORE)
@TimeLimiter(name = "fraudService")
public CompletableFuture<FraudResult> checkFraud(PaymentRequest req) {
    return CompletableFuture.supplyAsync(() ->
        fraudClient.check(req), bulkheadExecutor);
}

public CompletableFuture<FraudResult> fraudFallback(
        PaymentRequest req, CallNotPermittedException ex) {
    // Circuit open — degraded path: allow with manual review flag
    return CompletableFuture.completedFuture(
        FraudResult.manualReviewRequired(req.getId()));
}
```

```
RESILIENCE4J DECORATOR ORDER (outermost first):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  CircuitBreaker → Retry → Bulkhead → TimeLimiter → actual call

  Why:
    - CircuitBreaker outside Retry: don't retry when circuit open
    - Retry outside Bulkhead: each retry attempt acquires bulkhead slot
      (alternative: Bulkhead outside Retry to count retries as one slot)
    - TimeLimiter innermost: applies per-attempt timeout

  PRODUCTION DEBATE:
    Bulkhead outside Retry (one slot for all attempts):
      Prevents retry from consuming N bulkhead slots
    Retry outside Bulkhead (N slots for N attempts):
      Each attempt independently limited
    For payments: Bulkhead outside Retry.
```

### Istio DestinationRule — Circuit Breaking and Outlier Detection

```yaml
# istio/destination-rule-payments.yaml
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: payments-svc
  namespace: production
spec:
  host: payments-svc.production.svc.cluster.local
  trafficPolicy:
    connectionPool:
      tcp:
        maxConnections: 100
        connectTimeout: 2s
        tcpKeepalive:
          time: 30s
          interval: 10s
      http:
        http1MaxPendingRequests: 50
        http2MaxRequests: 100
        maxRequestsPerConnection: 2
        maxRetries: 2
        idleTimeout: 30s
        h2UpgradePolicy: UPGRADE
    outlierDetection:
      consecutive5xxErrors: 5
      consecutiveGatewayErrors: 3
      interval: 10s
      baseEjectionTime: 30s
      maxEjectionPercent: 50
      minHealthPercent: 50
      splitExternalLocalOriginErrors: true
    loadBalancer:
      simple: LEAST_REQUEST
  subsets:
    - name: v1
      labels:
        version: v1
    - name: v2
      labels:
        version: v2
```

```
ISTIO DESTINATIONRULE KNOBS EXPLAINED:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  connectionPool.tcp.maxConnections: 100
    → Bulkhead at sidecar level. Total TCP connections
      from this client's Envoy to payments-svc pods.

  http.http1MaxPendingRequests: 50
    → Queue of requests waiting for connection.
    → When full: 503 UF (upstream connection failure)
      or 429 depending on config.

  http.maxRetries: 2
    → Sidecar-level retries on idempotent methods (GET, HEAD,
      PUT, DELETE, OPTIONS, TRACE) for connect/reset/503.
    → POST retries NOT automatic (correct for payments).

  outlierDetection.consecutive5xxErrors: 5
    → Passive circuit breaker: eject pod from load balancing
      after 5 consecutive 5xx from that endpoint.

  outlierDetection.baseEjectionTime: 30s
    → Ejected pod excluded for 30s (doubles on re-ejection).

  outlierDetection.maxEjectionPercent: 50
    → Never eject more than half the endpoints.
    → Prevents killing entire service during incident.

  outlierDetection.minHealthPercent: 50
    → Stop ejecting if healthy endpoints would drop below 50%.
```

```yaml
# istio/virtual-service-payments-retry.yaml
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: payments-svc
  namespace: production
spec:
  hosts:
    - payments-svc
  http:
    - route:
        - destination:
            host: payments-svc
            subset: v1
          weight: 100
      timeout: 3s
      retries:
        attempts: 2
        perTryTimeout: 1s
        retryOn: connect-failure,refused-stream,unavailable,cancelled,503
        retryRemoteLocalities: false
```

```
ISTIO TIMEOUT MATH:
━━━━━━━━━━━━━━━━━

  route timeout: 3s        → total budget for route including retries
  perTryTimeout: 1s        → each attempt max 1s
  attempts: 2               → up to 2 tries

  Worst case: 2 × 1s = 2s (within 3s route timeout)
  If perTryTimeout × attempts > route timeout:
    route timeout wins (request cancelled)
```

### Envoy Outlier Detection (Standalone)

```yaml
# envoy-cluster-payments.yaml (standalone Envoy, not Istio)
clusters:
  - name: payments_cluster
    type: STRICT_DNS
    connect_timeout: 2s
    lb_policy: LEAST_REQUEST
    circuit_breakers:
      thresholds:
        - priority: DEFAULT
          max_connections: 100
          max_pending_requests: 50
          max_requests: 200
          max_retries: 3
    outlier_detection:
      consecutive_5xx: 5
      consecutive_gateway_failure: 3
      interval: 10s
      base_ejection_time: 30s
      max_ejection_percent: 50
      enforcing_consecutive_5xx: 100
      enforcing_success_rate: 0
    health_checks:
      - timeout: 2s
        interval: 10s
        unhealthy_threshold: 3
        healthy_threshold: 2
        http_health_check:
          path: /health/ready
          expected_statuses:
            - start: 200
              end: 299
    load_assignment:
      cluster_name: payments_cluster
      endpoints:
        - lb_endpoints:
            - endpoint:
                address:
                  socket_address:
                    address: payments-svc.internal
                    port_value: 8080
```

```
ENVOY CIRCUIT BREAKERS vs OUTLIER DETECTION:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  circuit_breakers (cluster level):
    Limits total connections, pending requests, active requests.
    Applies to ALL endpoints in cluster collectively AND per-priority.
    When tripped: 503 with flags "UO" (upstream overflow).

  outlier_detection (per-endpoint):
    Ejects individual bad hosts from load balancing pool.
    Passive — based on observed 5xx/latency, not health checks.
    Complements active health checks (detects "sick but responding").

  USE BOTH:
    circuit_breakers → protect THIS client from overload
    outlier_detection → protect FROM bad endpoints
    health_checks → detect completely dead endpoints
```

### gRPC Deadlines and Propagation

```protobuf
// payments.proto
service PaymentService {
  rpc ProcessPayment(PaymentRequest) returns (PaymentResponse);
  rpc GetPaymentStatus(PaymentStatusRequest) returns (PaymentStatusResponse);
}
```

```go
// Go — deadline propagation through call chain
func (s *CheckoutServer) ProcessCheckout(ctx context.Context, req *pb.CheckoutRequest) (*pb.CheckoutResponse, error) {
    // Parent deadline from gateway (if present)
    deadline, ok := ctx.Deadline()
    if !ok {
        var cancel context.CancelFunc
        ctx, cancel = context.WithTimeout(ctx, 3*time.Second)
        defer cancel()
        deadline, _ = ctx.Deadline()
    }

    remaining := time.Until(deadline)
    if remaining < 500*time.Millisecond {
        return nil, status.Error(codes.DeadlineExceeded, "insufficient budget")
    }

    // Subtract local processing budget
    fraudCtx, cancel := context.WithTimeout(ctx, remaining-time.Millisecond*200)
    defer cancel()

    fraudResult, err := s.fraudClient.CheckFraud(fraudCtx, req.FraudCheck)
    if err != nil {
        if status.Code(err) == codes.DeadlineExceeded {
            return nil, status.Error(codes.DeadlineExceeded, "fraud check timeout")
        }
        return nil, err
    }

    payCtx, cancel := context.WithTimeout(ctx, time.Until(deadline)-time.Millisecond*100)
    defer cancel()

    payment, err := s.paymentClient.ProcessPayment(payCtx, req.Payment)
    if err != nil {
        return nil, err
    }

    return &pb.CheckoutResponse{PaymentId: payment.Id}, nil
}
```

```java
// Java gRPC — client deadline
ManagedChannel channel = ManagedChannelBuilder
    .forTarget("payments-svc:9090")
    .usePlaintext()
    .build();

PaymentServiceGrpc.PaymentServiceBlockingStub stub =
    PaymentServiceGrpc.newBlockingStub(channel)
        .withDeadlineAfter(2500, TimeUnit.MILLISECONDS);

// Server — check remaining time
public void processPayment(PaymentRequest req,
        StreamObserver<PaymentResponse> responseObserver) {
    Context context = Context.current();
    Deadline deadline = context.getDeadline();
    if (deadline != null && deadline.isExpired()) {
        responseObserver.onError(
            Status.DEADLINE_EXCEEDED.withDescription("expired on arrival").asRuntimeException());
        return;
    }
    // ... process with awareness of remaining time
}
```

```
gRPC DEADLINE SEMANTICS:
━━━━━━━━━━━━━━━━━━━━━━

  Deadline is absolute timestamp propagated in grpc-timeout header.
  Format: timeout in nanoseconds from send time.

  Server SHOULD cancel work when deadline expires:
    Context.current().addListener(() -> { cancel DB query; }, executor);

  DEADLINE_EXCEEDED vs CANCELLED:
    DEADLINE_EXCEEDED: timeout budget exhausted
    CANCELLED: client explicitly cancelled or parent cancelled

  NEVER ignore deadline on server:
    Processing after deadline = wasted resources + cascade fuel
```

### AWS ALB and NLB — Timeout Configuration

```bash
# ALB — modify idle timeout (default 60s)
aws elbv2 modify-load-balancer-attributes \
  --load-balancer-arn arn:aws:elasticloadbalancing:us-east-1:123456789:loadbalancer/app/checkout-alb/abc123 \
  --attributes Key=idle_timeout.timeout_seconds,Value=120

# ALB — target group request timeout (deregistration + request handling)
aws elbv2 modify-target-group-attributes \
  --target-group-arn arn:aws:elasticloadbalancing:us-east-1:123456789:targetgroup/payments-tg/def456 \
  --attributes \
    Key=deregistration_delay.timeout_seconds,Value=30 \
    Key=load_balancing.algorithm.type,Value=least_outstanding_requests

# NLB — modify idle timeout (default 350s for TCP)
aws elbv2 modify-load-balancer-attributes \
  --load-balancer-arn arn:aws:elasticloadbalancing:us-east-1:123456789:loadbalancer/net/payments-nlb/ghi789 \
  --attributes Key=tcp.idle_timeout.seconds,Value=120
```

```yaml
# Terraform — ALB with aligned timeouts
resource "aws_lb" "checkout" {
  name               = "checkout-alb"
  load_balancer_type = "application"
  idle_timeout       = 65  # slightly above app deadline for graceful close

  # subnets, security groups...
}

resource "aws_lb_target_group" "checkout_api" {
  name     = "checkout-api-tg"
  port     = 8080
  protocol = "HTTP"
  vpc_id   = var.vpc_id

  health_check {
    path                = "/health/ready"
    interval            = 10
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
    matcher             = "200"
  }

  deregistration_delay = 30
}

# Application deadline: 3s
# ALB idle_timeout: 65s (for keep-alive connections between requests)
# ALB does NOT have per-request timeout at LB level for HTTP —
# use target response timeout via service mesh or app config
# Connection: Week 1 HTTP keep-alive + ALB connection reuse
```

```
ALB vs NLB FOR PAYMENTS PATH:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ALB (Layer 7):
    ✓ HTTP health checks, path-based routing
    ✓ Connection draining on deploy
    ✓ Request counting for outlier-ish behavior
    ✓ WAF integration
    ✗ Adds ~1-5ms latency (proxy processing)
    Use: HTTP/HTTPS microservices behind api-gateway

  NLB (Layer 4):
    ✓ Ultra-low latency (~100μs), preserves source IP
    ✓ Static IP / Elastic IP support
    ✓ Handles millions of connections
    ✗ No HTTP awareness, no per-request timeout
    ✗ No retry, no circuit breaker
    Use: gRPC/TCP direct, extreme throughput, fixed IP needs

  RESILIENCE IMPLICATION:
    NLB deployments MUST implement ALL patterns from this
    module in application/mesh layer. The LB will happily
    forward traffic to dying backends until app stops sending.
```

### Spring Cloud Circuit Breaker (Resilience4j Backend)

```yaml
# bootstrap.yml
spring:
  cloud:
    circuitbreaker:
      resilience4j:
        enabled: true

# application.yml
resilience4j.circuitbreaker:
  configs:
    default:
      slidingWindowSize: 50
      failureRateThreshold: 50
      waitDurationInOpenState: 30s
  instances:
    paymentService:
      baseConfig: default
      slowCallDurationThreshold: 1s
      slowCallRateThreshold: 70
```

```java
@Service
public class CheckoutService {
    private final CircuitBreakerFactory circuitBreakerFactory;
    private final PaymentClient paymentClient;

    public PaymentResult processPayment(PaymentRequest req) {
        CircuitBreaker cb = circuitBreakerFactory.create("paymentService");
        return cb.run(
            () -> paymentClient.charge(req),
            throwable -> PaymentResult.degraded(req.getId())
        );
    }
}
```

### Node.js — opossum Circuit Breaker

```javascript
const CircuitBreaker = require('opossum');

const options = {
  timeout: 3000,                  // per-call timeout
  errorThresholdPercentage: 50,   // open at 50% failures
  resetTimeout: 30000,            // half-open after 30s
  volumeThreshold: 10,            // minimum calls before tripping
  rollingCountTimeout: 10000,     // 10s rolling window
  rollingCountBuckets: 10,
};

const breaker = new CircuitBreaker(callFraudService, options);

breaker.fallback((req) => ({
  status: 'MANUAL_REVIEW',
  paymentId: req.paymentId,
}));

breaker.on('open', () => console.log('Circuit OPEN — fraud service'));
breaker.on('halfOpen', () => console.log('Circuit HALF-OPEN — probing'));
breaker.on('close', () => console.log('Circuit CLOSED — recovered'));

async function callFraudService(req) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 2500);
  try {
    const res = await fetch('http://fraud-svc:8080/check', {
      method: 'POST',
      body: JSON.stringify(req),
      signal: controller.signal,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  } finally {
    clearTimeout(timeoutId);
  }
}
```

---

### Staff

## Production Patterns

### Pattern 1: Fail Fast with Degraded Response

```
CHECKOUT WITHOUT PAYMENT VALIDATION (circuit open):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Normal path:
    checkout → fraud-svc (pass) → payments-svc (charge) → confirm

  Degraded path (fraud circuit OPEN):
    checkout → fraud circuit breaker → MANUAL_REVIEW flag
            → payments-svc (charge with flag) → confirm + email review

  KEY: degraded path must be DESIGNED beforehand.
  Fallback is not "return 500" — it's a business decision.
  Payments team + risk team must approve degraded flows.
```

### Pattern 2: Bulkhead Per Tenant Tier

```
MULTI-TENANT BULKHEAD (SaaS):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Enterprise tenants → dedicated pool (50 threads)
  Standard tenants   → shared pool (100 threads)
  Free tier          → shared pool (20 threads, strict rate limit)

  Prevents free-tier traffic spike from starving enterprise.
  Implementation: route by tenant tier header to different
  Resilience4j bulkhead instances.
```

### Pattern 3: Retry Budget at Gateway

```
API GATEWAY RETRY BUDGET:
━━━━━━━━━━━━━━━━━━━━━━━━

  Kong/Envoy rate limiting:
    normal_requests: 10000/min
    retry_budget: 1000/min (10%)

  Track retry via header: X-Retry-Attempt: 1
  Gateway drops retries when budget exhausted.
  Returns 503 with Retry-After: 30

  Prevents client retry storm from entering the system.
```

### Pattern 4: Cascading Deadline via Service Mesh

```
MESH-WIDE TIMEOUT POLICY:
━━━━━━━━━━━━━━━━━━━━━━━━

  VirtualService timeout = outer bound
  Application deadline = inner bound (tighter)

  checkout VirtualService: timeout 5s
  checkout app deadline: 3s (fails before mesh timeout)
  payments VirtualService: timeout 2s
  payments app deadline: 1.5s

  Mesh timeout is safety net, not primary control.
  App deadline provides meaningful error messages.
```

### Pattern 5: Bulkhead + Circuit Breaker Dashboard

```
GRAFANA ROW (per dependency):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Panel 1: circuit_breaker_state (0=closed, 1=open, 2=half-open)
  Panel 2: bulkhead_available_concurrent_calls
  Panel 3: bulkhead_max_allowed_concurrent_calls
  Panel 4: calls_seconds (p50, p95, p99)
  Panel 5: retry_calls_total
  Panel 6: failure_rate

  Alert: state==1 (open) for > 60s → page payments on-call
  Alert: available_concurrent_calls == 0 for > 30s → page
```

### Pattern 6: Idempotency Keys for Payment Retries

```
PAYMENT RETRY WITH IDEMPOTENCY:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Client sends:
    POST /payments
    Idempotency-Key: 550e8400-e29b-41d4-a716-446655440000
    Body: { amount: 99.99, currency: "USD", ... }

  payments-svc:
    1. Check idempotency store (Redis/DynamoDB)
    2. If key exists → return stored response (no re-charge)
    3. If new → process, store result with key, TTL 24h
    4. Safe to retry on 503/timeout

  WITHOUT idempotency key:
    NEVER retry POST /payments at client or mesh level.
```

### Pattern 7: Adaptive Load Shedding at Ingress

```
INGRESS SHEDDING (Envoy rate limit filter):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Normal: accept 100% traffic
  When downstream p99 > 2s for 30s:
    Shed 10% of new requests (429)
  When circuit breakers open on > 2 dependencies:
    Shed 25%
  When bulkhead utilization > 90%:
    Shed 50%

  Shed deterministic subset (hash client_id % 100 < shed%)
  so same clients get consistent experience.
```

### Pattern 8: Chaos Engineering for Resilience Validation

```
STEADY-STATE HYPOTHESES (before chaos):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  H1: When fraud-svc latency = 5s, checkout p99 < 3s
      (bulkhead + timeout + circuit breaker work)

  H2: When payments-svc is down, checkout returns degraded
      response in < 500ms (circuit open, no thread blocking)

  H3: Retry storm does not increase payments-svc RPS > 2×
      (retry budget + jitter work)

  Experiment: toxiproxy latency injection on fraud-svc
  Verify: metrics match hypotheses
```

### Pattern 9: Connection Pool Sizing Formula

```
HTTP CONNECTION POOL SIZING:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  maxConnectionsPerRoute = expected_concurrent_requests × 1.2

  For payments-svc called by checkout-svc:
    checkout replicas: 20
    threads per replica: 50
    max concurrent to payments: 20 (bulkhead)
    pool per replica: 20 × 1.2 = 24 connections

  Total connections to payments-svc:
    20 replicas × 24 = 480 connections
    payments-svc must handle 480 inbound connections
    (size DB pool accordingly: pool < max_connections - overhead)
```

### Pattern 10: Graceful Degradation Cache

```
STALE-WHILE-REVALIDATE FOR READ PATHS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  catalog-svc calls recommendation-svc
  Circuit open → return cached recommendations (max 1h stale)
  Better stale suggestions than empty cart page.

  NOT acceptable for: payment balances, fraud scores.
  Acceptable for: product recommendations, search suggestions.
```

---

## Failure Modes

### Failure 1: Retry Storm During Partial Outage

```
SCENARIO:
  payments-db primary fails over to replica (45s).
  payments-svc returns 503 for 45 seconds.
  checkout-svc has retry: maxAttempts=5, no jitter.
  50 checkout replicas × 200 threads × 5 retries = 50,000
  extra requests to payments-svc in seconds.
  payments-svc (now on replica, already stressed) collapses.
  Failover completes but service stays down due to retry load.

HOW TO DETECT:
  → payments-svc RPS spikes 5-10× during DB failover
  → Retry metrics (resilience4j_retry_calls_total) spike
  → All clients retry at same intervals (sawtooth pattern)
  → X-Retry-Attempt header or trace shows deep retry chains

FIX:
  → Full jitter on all retries
  → Circuit breaker opens after N failures (stops retry source)
  → Retry budget at gateway (10% cap)
  → Exponential backoff with maxDelay ≥ expected outage duration
  → Idempotency keys on payment writes
```

### Failure 2: Circuit Breaker Flapping (Half-Open Storm)

```
SCENARIO:
  fraud-svc recovers slowly (latency 2s, normally 50ms).
  Circuit opens after failure threshold.
  waitDurationInOpenState: 10s → half-open.
  permittedNumberOfCallsInHalfOpenState: 100 (too high).
  100 probe requests hit recovering fraud-svc.
  fraud-svc overwhelmed → probes fail → circuit re-opens.
  Cycle repeats every 10s. Circuit never closes.
  Checkout alternates between "fraud unavailable" and
  "fraud slow" — user-visible flapping.

HOW TO DETECT:
  → circuit_breaker_state metric oscillates 1→2→1→2
  → Half-open call count spikes every 10s
  → fraud-svc latency normalizes but circuit stays open

FIX:
  → permittedNumberOfCallsInHalfOpenState: 5-10 (not 100)
  → slowCallRateThreshold: trip on latency, not just errors
  → waitDurationInOpenState: 60s+ for slow-recovering deps
  → Require N consecutive successes in half-open before close
```

### Failure 3: Bulkhead Queue Causing Latency Death Spiral

```
SCENARIO:
  payments-svc bulkhead: maxThreads=50, queueCapacity=500.
  payments-db slows to 2s per query.
  50 threads busy, 500 requests queue.
  New requests wait in queue: position 400 × 2s = 800s wait.
  ALB health check still passes (health endpoint fast).
  Users see 30s timeouts (client limit) but server still
  processing stale queued requests for minutes.
  Memory pressure from 500 queued request objects.

HOW TO DETECT:
  → Thread pool active=50, queue size growing
  → Latency p99 >> p50 (queue wait dominates)
  → Success rate normal but latency terrible
  → Age of oldest queued request metric (if exposed)

FIX:
  → queueCapacity=0 for latency-sensitive paths
  → Reject when pool full (503 immediately)
  → Shed load at ingress when queue depth > threshold
  → Separate health check thread pool from request pool
```

### Failure 4: Missing Deadline Propagation

```
SCENARIO:
  api-gateway deadline: 3s, propagated correctly.
  checkout-svc ignores incoming deadline, sets own 30s timeout.
  payments-svc ignores deadline, sets 30s timeout.
  fraud-svc external API call: 25s timeout.
  User sees 3s timeout from gateway.
  BUT: payments-svc, fraud-svc, external API still running.
  1000 abandoned requests/minute still consuming resources.
  Thread pools exhaust from zombie work.

HOW TO DETECT:
  → Traces show child spans continuing after parent ended
  → Server-side work after client disconnect (logs after 3s)
  → Thread pool saturation with low external RPS
  → grpc-timeout header missing on downstream calls

FIX:
  → Enforce deadline propagation in all gRPC interceptors
  → Cancel DB queries on context cancellation
  → HTTP: parse X-Request-Deadline header in middleware
  → Monitor "cancelled after parent deadline" metric
```

### Failure 5: ALB Idle Timeout Killing Long Requests

```
SCENARIO (Week 1 connection):
  checkout flow includes 3DS authentication redirect (user
  completes challenge in bank app, 90 seconds).
  ALB idle_timeout: 60s (default).
  Connection idle during user interaction → ALB closes TCP.
  User returns, client reuses connection → RST.
  Checkout fails with "connection reset" — intermittent,
  correlates with slow users, not load.

HOW TO DETECT:
  → Errors are TCP RST, not HTTP 5xx
  → Correlates with long user think-time flows
  → ALB flow logs show connection_reset_reason
  → No application error logs (request never arrived)

FIX:
  → Increase ALB idle_timeout for checkout path (300s)
  → OR separate ALB/listener for long-flow endpoints
  → Client: retry on connection reset with idempotency key
  → WebSocket/SSE paths: idle_timeout must exceed max idle
```

### Failure 6: Hedging Doubling Load During Incident

```
SCENARIO:
  recommendation-svc degraded (p99: 2s, normal: 100ms).
  catalog-svc hedges after 200ms on all reads.
  Load on recommendation-svc doubles.
  p99 rises to 4s. More hedging triggers.
  Positive feedback until recommendation-svc OOM.

HOW TO DETECT:
  → recommendation-svc RPS 2× catalog-svc RPS
  → Hedged request metric climbing with latency
  → Circuit breaker on catalog NOT open (recommendation
    still returns 200, just slow)

FIX:
  → Disable hedging when downstream p99 > threshold
  → Circuit breaker on slowCallRate, not just errors
  → maxHedgedRequests: 1 with strict hedgeDelay
  → Never hedge during elevated error rates
```

### Failure 7: Mesh Retry on Non-Idempotent POST

```
SCENARIO:
  Istio VirtualService: retries attempts=3 on 503.
  checkout-svc POST /payments returns 503 (timeout).
  Envoy retries POST 3 times.
  payments-svc receives 3 identical charge requests.
  Customer charged 3× (no idempotency key).

HOW TO DETECT:
  → Duplicate transactions with same payload, different trace IDs
  → x-envoy-attempt-count > 1 on server logs
  → Istio access logs show multiple upstream_rq per downstream

FIX:
  → Remove POST from retryOn list
  → Idempotency-Key header + server-side dedup
  → retries only on connect-failure, refused-stream
  → Application-level retry with idempotency, not mesh retry
```

### Failure 8: Backpressure Not Propagating

```
SCENARIO:
  notification-svc overwhelmed (email provider rate limit).
  Returns 429 but checkout-svc ignores 429, retries immediately.
  Kafka consumer on notification topic: unbounded internal queue.
  Consumer heap grows, GC pauses, consumer stops polling.
  Kafka rebalance, duplicate notifications sent.

HOW TO DETECT:
  → Consumer heap usage climbing linearly
  → poll() interval exceeding max.poll.interval.ms
  → 429 responses without Retry-After honored
  → Consumer lag growing while processing rate flat

FIX:
  → Honor Retry-After on 429 (exponential backoff)
  → Bounded queue in consumer with pause partitions
  → Circuit breaker on email provider
  → Scale consumers OR throttle producers at source
```

### Failure 9: Thundering Herd on Circuit Close

```
SCENARIO:
  payments-svc down for 5 minutes. Circuit open everywhere.
  payments-svc recovers. All circuits transition to half-open
  simultaneously (same waitDurationInOpenState).
  Thousands of probe requests hit payments-svc at once.
  payments-svc overwhelmed, fails probes, circuits re-open.

HOW TO DETECT:
  → Synchronized half-open transitions across services
  → RPS spike at exact recovery timestamp
  → All circuit breakers show half-open simultaneously

FIX:
  → Jitter waitDurationInOpenState per instance:
    60s + random(0, 30s)
  → Gradual traffic restoration (canary by caller)
  → half-open permits: 5, not unlimited
```

### Failure 10: Timeout Cascades from Clock Skew

```
SCENARIO:
  Deadline propagated as absolute timestamp.
  api-gateway clock 5s ahead of payments-svc clock.
  payments-svc calculates negative remaining budget.
  All requests fail immediately with DEADLINE_EXCEEDED.
  Intermittent — depends on which gateway replica.

HOW TO DETECT:
  → DEADLINE_EXCEEDED on arrival (duration < 1ms in trace)
  → Correlates with specific gateway replicas
  → NTP drift alerts on affected nodes

FIX:
  → NTP/chrony on all nodes (mandatory)
  → Use relative timeout as fallback if skew detected
  → Monitor clock offset between services
```

---

## SRE Diagnostic Toolkit

```
CIRCUIT BREAKER METRICS (Resilience4j / Micrometer):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Prometheus queries
resilience4j_circuitbreaker_state{name="fraudService"}
# 0=closed, 1=open, 2=half-open, -1=disabled

resilience4j_circuitbreaker_failure_rate{name="fraudService"}
resilience4j_circuitbreaker_slow_call_rate{name="fraudService"}
resilience4j_circuitbreaker_buffered_calls{name="fraudService"}
resilience4j_circuitbreaker_not_permitted_calls_total{name="fraudService"}

# Alert: circuit open > 60s
resilience4j_circuitbreaker_state == 1

# Alert: fail-fast rate spike (circuit doing its job but
#         indicates downstream trouble)
rate(resilience4j_circuitbreaker_not_permitted_calls_total[5m]) > 10


BULKHEAD METRICS:
━━━━━━━━━━━━━━━━

resilience4j_bulkhead_available_concurrent_calls{name="fraudService"}
resilience4j_bulkhead_max_allowed_concurrent_calls{name="fraudService"}
resilience4j_bulkhead_concurrent_calls{name="fraudService"}

# Utilization
resilience4j_bulkhead_concurrent_calls
  / resilience4j_bulkhead_max_allowed_concurrent_calls > 0.9


RETRY METRICS:
━━━━━━━━━━━━━

resilience4j_retry_calls_total{name="fraudService",kind="successful_without_retry"}
resilience4j_retry_calls_total{name="fraudService",kind="successful_with_retry"}
resilience4j_retry_calls_total{name="fraudService",kind="failed_with_retry"}
resilience4j_retry_calls_total{name="fraudService",kind="failed_without_retry"}


ISTIO / ENVOY METRICS:
━━━━━━━━━━━━━━━━━━━━━

# Upstream request failures
istio_requests_total{response_code="503",destination_service="payments-svc"}
rate(istio_requests_total{response_code="503"}[5m])

# Upstream overflow (circuit breaker tripped at sidecar)
envoy_cluster_upstream_rq_overflow{cluster_name="outbound|8080||payments-svc"}

# Outlier ejections
envoy_cluster_outlier_detection_ejections_active{cluster_name="..."}
envoy_cluster_outlier_detection_ejections_total{cluster_name="..."}

# Retry count from access logs
# x-envoy-attempt-count header in Istio access logs
kubectl logs -n production -l app=checkout-svc -c istio-proxy | \
  grep "payments-svc" | awk '{print $NF}' | sort | uniq -c


THREAD POOL DIAGNOSTICS (Java):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# JMX via jconsole / Prometheus JMX exporter
java.lang:type=Threading
  ThreadCount, PeakThreadCount

# Custom executor metrics
executor.active_threads{pool="payments"}
executor.queue.size{pool="payments"}
executor.rejected_total{pool="payments"}

# Thread dump when pool saturated
jcmd <pid> Thread.print > /tmp/threaddump.txt
# Look for: all pool threads in TIMED_WAITING on socket read
#           or BLOCKED waiting for connection from pool


gRPC DEADLINE DIAGNOSTICS:
━━━━━━━━━━━━━━━━━━━━━━━━━

# grpc-java metrics
grpc.server.call.duration (histogram)
grpc.server.call.sent_total{status="DEADLINE_EXCEEDED"}

# Check deadline propagation in trace (Jaeger/Tempo)
# Parent span ended at T=3s, child span ended at T=30s
# → deadline NOT propagated

# grpcurl with deadline
grpcurl -max-time 2 \
  -d '{"payment_id": "123"}' \
  payments-svc:9090 \
  payments.PaymentService/GetPaymentStatus


AWS ALB DIAGNOSTICS:
━━━━━━━━━━━━━━━━━━━

# Target health
aws elbv2 describe-target-health \
  --target-group-arn $TG_ARN \
  --query 'TargetHealthDescriptions[*].[Target.Id,TargetHealth.State,TargetHealth.Reason]'

# ALB access logs — 504 Gateway Timeout
# elb_status_code=504, target_status_code=-
# → target didn't respond within idle/request window

# 502 Bad Gateway
# target_status_code=-, elb_status_code=502
# → target closed connection or RST

# CloudWatch metrics
aws cloudwatch get-metric-statistics \
  --namespace AWS/ApplicationELB \
  --metric-name TargetResponseTime \
  --dimensions Name=LoadBalancer,Value=app/checkout-alb/abc123 \
  --start-time 2026-07-06T10:00:00Z \
  --end-time 2026-07-06T11:00:00Z \
  --period 60 \
  --statistics p99

# HTTPCode_Target_5XX_Count spike during incident
# HTTPCode_ELB_504_Count for timeout at LB layer


CURL — TIMEOUT AND RETRY BEHAVIOR:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Measure with tight timeout
curl -w "\nconnect: %{time_connect}s\nttfb: %{time_starttransfer}s\ntotal: %{time_total}s\ncode: %{http_code}\n" \
  -o /dev/null -s \
  --max-time 3 \
  https://api.example.com/checkout

# Verbose connection reuse (ALB keep-alive)
curl -v --max-time 3 https://api.example.com/checkout 2>&1 | \
  grep -iE "connection|timeout|reset"

# Retry simulation (curl retry — use for testing only)
curl --retry 3 --retry-delay 1 --retry-all-errors \
  --max-time 5 \
  https://api.example.com/payments/health


KUBERNETES — RESOURCE PRESSURE AS BULKHEAD FAILURE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Pod CPU throttling (bulkhead at cgroup level)
kubectl top pods -n production -l app=payments-svc

# OOMKilled events
kubectl get events -n production --field-selector reason=OOMKilling

# Check if HPA is scaling (backpressure response)
kubectl get hpa -n production payments-svc-hpa -w

# Container restart loop from OOM
kubectl describe pod -n production payments-svc-xxx | \
  grep -A5 "Last State"


LOG PATTERNS FOR CASCADE DETECTION:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  "CallNotPermittedException" / "CircuitBreaker 'X' is OPEN"
    → Circuit breaker working; check downstream

  "BulkheadFullException" / "pool is full"
    → Bulkhead saturated; check downstream latency

  "DEADLINE_EXCEEDED" with duration < 100ms
    → Deadline propagation or clock skew

  "DEADLINE_EXCEEDED" with duration ≈ timeout
    → Legitimate timeout; downstream too slow

  "Connection pool exhausted" / "Timeout waiting for connection"
    → Connection pool bulkhead; size pools or reduce concurrency

  "x-envoy-attempt-count: 3" on payment POST logs
    → Mesh retrying non-idempotent — INCIDENT RISK

  "Retrying request, attempt 2 of 3" synchronized across pods
    → Missing jitter


DISTRIBUTED TRACE ANALYSIS:
━━━━━━━━━━━━━━━━━━━━━━━━━━

  Healthy trace (3s budget):
    api-gateway    [========] 3000ms deadline
    checkout-svc     [======] 2800ms remaining at start
    fraud-svc          [==] 300ms
    payments-svc       [===] 500ms
    payments-db         [=] 150ms

  Cascade trace (broken):
    api-gateway    [========] 3000ms deadline, FAILED at 3000ms
    checkout-svc     [================] still running at 8000ms ← BUG
    payments-svc       [================] still running
    payments-db          [================]

  Look for: child spans exceeding parent duration
```

---

## Decision Framework

```
WHICH PATTERN FOR WHICH PROBLEM?
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ┌────────────────────────────┬─────────────────────────────────┐
  │ Symptom                    │ Primary pattern                 │
  ├────────────────────────────┼─────────────────────────────────┤
  │ Dependency returning errors│ Circuit breaker                 │
  │ Dependency slow but 200    │ Circuit breaker (slowCallRate)  │
  │ One dep blocking others    │ Bulkhead                        │
  │ Requests wait forever      │ Timeout / deadline              │
  │ Transient network blip     │ Retry + jitter (if idempotent)  │
  │ Tail latency on reads      │ Hedging (if idempotent, spare   │
  │                            │ capacity)                       │
  │ Producer faster than       │ Backpressure (bounded queue,    │
  │ consumer                   │ 429, pause)                     │
  │ Retry multiplying load     │ Retry budget + circuit breaker  │
  │ Queue growing unbounded    │ Backpressure + load shedding    │
  └────────────────────────────┴─────────────────────────────────┘


CIRCUIT BREAKER: WHEN TO USE vs NOT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  USE:
    ✓ External/third-party APIs (fraud, payment gateway)
    ✓ Cross-team microservice calls
    ✓ Any call that can hang or fail for extended periods
    ✓ When you have a degraded fallback designed

  SKIP (or use carefully):
    ✗ Internal in-process calls (just call the function)
    ✗ Database calls where circuit open = total outage anyway
      (prefer timeout + connection pool limits + read replica)
    ✗ When no fallback exists and fail-fast = same as fail-slow
      (still use timeout; circuit breaker adds fail-fast benefit)


BULKHEAD: THREAD POOL vs SEMAPHORE vs CONNECTION POOL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ┌──────────────────┬──────────────┬──────────────┬──────────────┐
  │                  │ Thread pool  │ Semaphore    │ Conn pool    │
  ├──────────────────┼──────────────┼──────────────┼──────────────┤
  │ Blocking I/O     │ Best         │ OK           │ Required     │
  │ Async/reactive   │ Overkill     │ Best         │ Required     │
  │ Timeout cancel   │ Yes          │ Harder       │ N/A          │
  │ Overhead         │ High         │ Low          │ Medium       │
  │ Per-dependency   │ Yes          │ Yes          │ Yes          │
  └──────────────────┴──────────────┴──────────────┴──────────────┘


RETRY: HOW MANY ATTEMPTS?
━━━━━━━━━━━━━━━━━━━━━━━━

  Dependency p99: 200ms, transient failure rate: 0.1%

  maxAttempts=3, baseDelay=100ms, full jitter:
    Covers ~99.9% of transients
    Max added latency: ~700ms (within 3s budget)

  maxAttempts=5:
    Diminishing returns past 3 for most networks
    Risk of budget exhaustion in chained calls

  RULE: maxAttempts × perAttemptTimeout < remaining deadline


HEDGING vs RETRY vs CIRCUIT BREAKER:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Latency-sensitive read, 3 replicas, healthy:
    → Hedging (after p95 delay)

  Transient 503 on idempotent write:
    → Retry with jitter (circuit closed)

  Dependency down 5 minutes:
    → Circuit breaker (stop calling)

  Dependency slow 5 minutes:
    → Circuit breaker on slowCallRate
    → NOT hedging (amplifies load)


TIMEOUT VALUES — QUICK REFERENCE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  User-facing API total:        1-5s (product decision)
  Internal sync call:           200ms-2s
  External third-party API:     2-5s (less control)
  DB query:                     100ms-1s
  Health check:                 1-3s
  ALB idle (HTTP keep-alive):   60-120s
  ALB deregistration delay:     30s (deploy drain)
  NLB TCP idle:                 120-350s
  gRPC keepalive:               30s interval, 10s timeout

  RULE: child_timeout < parent_timeout < client_timeout


WHERE TO IMPLEMENT — DECISION TREE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Start: outbound call to dependency X

  Is X in your K8s mesh?
    YES → Istio DestinationRule (connection pool, outlier)
          + application circuit breaker (business fallback)
    NO  → Application-level Resilience4j/opossum

  Is the call idempotent?
    YES → retry with jitter (app or VirtualService)
    NO  → idempotency key OR no retry

  Is latency SLO tight (< 500ms p99)?
    YES → bulkhead queueCapacity=0, fail fast
    NO  → small queue acceptable with monitoring

  Is X a third-party with variable latency?
    YES → circuit breaker + generous timeout + fallback
```

```
RESILIENCE LAYER RESPONSIBILITY MATRIX:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ┌────────────────────┬──────────┬───────────┬──────────────┐
  │ Pattern            │ App code │ Mesh/Envoy│ AWS LB       │
  ├────────────────────┼──────────┼───────────┼──────────────┤
  │ Circuit breaker    │ Primary  │ Outlier   │ No           │
  │ Bulkhead           │ Primary  │ Conn pool │ No           │
  │ Timeout/deadline   │ Primary  │ Route to  │ Idle only    │
  │                    │          │           │              │
  │ Retry              │ Primary  │ Limited   │ No           │
  │ Backpressure       │ Primary  │ Rate lim  │ No           │
  │ Health ejection    │ /health  │ Outlier   │ Target health│
  └────────────────────┴──────────┴───────────┴──────────────┘

  Application owns business logic fallbacks.
  Mesh owns connection-level protection.
  LB owns connection lifecycle and target health.
```

---

### Principal stretch

## Ops Sim: Northstar Payment Brownout Retry Furnace

**Time box:** 50 minutes  
**Severity:** P1  
**Service / domain:** Checkout payment client, retry budgets, circuit breakers, worker pools  
**Northstar system:** Northstar Commerce

### Drill rules

1. Answer from memory of the Circuit Breakers Bulkheads Timeouts Retries and Backpressure teaching section; do not re-read mid-drill.
2. Write decisions in order: T+0, T+5, T+15, T+30, T+60, and follow-up.
3. Tie every claim to a metric, log line, trace, query output, or config key from this packet.
4. Name the correctness invariant before proposing scale, failover, replay, or data repair.
5. Do not open the answer key until your response is written.

---

### Page summary

```text
WHAT USERS SEE:
  - Buyers see spinner loops and payment unknown responses.
  - Some authorizations succeed after the browser timed out.
  - Checkout pods are up but all workers are blocked on payment.
  - Inventory reservations expire while money state is unknown.

WHAT ON-CALL SEES:
  - Retry attempts per original request exceed four.
  - Circuit breaker is closed despite semantic TEMPORARY_UNAVAILABLE payloads.
  - Provider p99 is high in one region, not globally failed.
  - Adding checkout pods is proposed as first move.

BUSINESS CONSTRAINT:
  No duplicate charges and no unpaid shipments; async pending confirmation is allowed.
```

### Failure model

A regional payment provider brownout becomes a checkout outage because the client retries five times synchronously, the breaker counts HTTP 202 error payloads as success, and payment calls share the checkout worker pool.

Break it into these forces before answering:
- trigger: the release/config/data shape that started the failure
- amplifier: retry, cache, routing, projection, or observability behavior that widened it
- scarce resource: the metric that reaches a limit first
- invariant: what must remain conservative even while users see degraded experience
- repair boundary: the source of truth and operation id used after mitigation

### Diff from normal

- The suspicious production lever is `# istio/destination-rule-payments.yaml`; tie it to the first bad minute before changing capacity.
- The dashboard that stayed calm does not expose `checkout_request_duration_seconds{p99}` for the damaged slice.
- The runbook move closest to "add checkout pods first" needs an explicit no-go decision on the bridge.
- The repair path is allowed only after the source-of-truth query and operation key are written down.

### Metrics logs traces

```text
METRICS:
  - checkout_request_duration_seconds{p99}: 0.42 -> 9.7
  - checkout_worker_pool_in_use: 68 -> 240/240
  - payment_client_inflight_requests: 900 -> 11800
  - payment_client_retry_attempts_per_request: 1.1 -> 4.7
  - payment_provider_latency_seconds{region="us-east",p99}: 0.8 -> 6.9
  - payment_unknown_state_total: +14200
  - circuit_breaker_state{dependency="pay-east"}: closed
  - inventory_reservation_expired_total: +8100

LOG LINES:
  - payment-client: retrying attempt=5 original_request_id=pay-77c reason=timeout
  - payment-client: status=202 body.provider_status=TEMPORARY_UNAVAILABLE counted_success=true
  - checkout: worker_pool exhausted route=/checkout/confirm
  - provider-webhook: auth_succeeded idempotency_key=cart-77c after client timeout
  - inventory: reservation expired while payment_state=UNKNOWN

TRACE / QUERY / INSPECTION NOTES:
  - Trace shows nested payment attempts dominate checkout latency.
  - Thread dump is blocked futures in payment client.
  - Provider status page reports regional latency.
  - Idempotency ledger is already suppressing duplicate auths.
```

### Wrong config pack

```yaml
payment.timeout_ms: 8000
payment.max_attempts: 5
payment.retry_jitter: false
payment.retry_budget_percent: disabled
circuit.success_on_http_202: true
bulkhead.payment.max_concurrency: shared
```

### Triage timeline

| Time | Event | Your move |
|------|-------|-----------|
| T+0 | P0 checkout page fires; provider region is slow. | Stop multiplying provider traffic. |
| T+5 | Proposal: add 100 checkout pods. | Reject before retry budget. |
| T+15 | Breaker still closed on semantic failures. | Force dependency state to open/degraded. |
| T+30 | Unknown payment states accumulate. | Define pending UX and inventory hold. |
| T+60 | Provider recovers. | Drain unknowns from source of truth. |
| T+24h | Breaker review starts. | Write dependency contract. |

### Available runbook moves

- Roll back or disable the specific dangerous config from the packet.
- Shed decorative, derived, notification, or analytics work before weakening source-of-truth correctness.
- Throttle retry/replay using the narrowest downstream capacity limit.
- Keep an affected-record ledger before customer-visible repair.
- Verify recovery with the sliced SLI plus the scarce-resource metric, not a fleet average.

### Unsafe shortcuts

For each proposal, name the concrete failure mode it creates.

- add checkout pods first
- disable idempotency
- fail open on payment authorization
- shorten timeout without UNKNOWN state

### Questions

**Q01.** What exact layer owns the failure and why is the most obvious graph a red herring?

**Q02.** Which config line is wrong, and what failure physics does it create?

**Q03.** Select three metrics and two log/inspection clues that prove your diagnosis.

**Q04.** What is the safe T+0 to T+5 announcement and freeze/rollback decision?

**Q05.** What do you stop first: trigger, amplifier, or repair job? Explain sequencing.

**Q06.** What invariant must remain true if every dashboard is stale?

**Q07.** Which bad fix is most tempting in this incident, and why does it make recovery worse?

**Q08.** What numeric capacity or blast-radius check is required before scale/failover/replay?

**Q09.** What is the source-of-truth query or ledger for the affected set?

**Q10.** Which derived systems may lag, and which external side effects require idempotency?

**Q11.** Write the durable config/architecture change and its acceptance test.

**Q12.** Who joins by T+10, and what is pre-authorized versus escalated?

### Self-score

| Error type | Count | Notes |
|------------|-------|-------|
| Wrong layer/root cause | | |
| Evidence gap | | |
| Unsafe first action | | |
| Capacity/blast-radius miss | | |
| Correctness invariant miss | | |
| Repair/replay mistake | | |
| Org/runbook gap | | |

**Pass bar:** correct mechanism, safe sequencing, explicit rejection of the bad fix, one numeric capacity check, and a repair plan grounded in source of truth.

**Answer key:** [answers/Week-06-Architecture-Patterns/Circuit Breakers Bulkheads Timeouts Retries and Backpressure Answers.md](../answers/Week-06-Architecture-Patterns/Circuit%20Breakers%20Bulkheads%20Timeouts%20Retries%20and%20Backpressure%20Answers.md)

