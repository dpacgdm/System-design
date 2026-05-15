# Week 6, Topic 5: Circuit Breakers, Bulkheads, Timeouts, Retries, and Backpressure

Last verified: 2026-05-15

Resilience patterns stop one slow or failing dependency from consuming the whole system. They do not make dependencies reliable. They make failure bounded, visible, and survivable.

This topic covers five patterns that belong together:

```text
timeouts
retries
circuit breakers
bulkheads
backpressure/load shedding
```

Used well, they keep partial failure partial. Used badly, they create retry storms, false recovery, hidden data loss, and customer-visible weirdness.

---

## 1. Learning objectives

```text
After this topic, you should be able to:

1. Design timeout budgets across a request chain.
2. Explain why retries amplify load.
3. Use circuit breakers to fail fast during dependency failure.
4. Use bulkheads to isolate resource pools.
5. Apply backpressure and load shedding before queues become unbounded.
6. Diagnose retry storms, breaker flapping, fallback overload, and queue collapse.
7. Decide which dependencies should fail open, fail closed, degrade, or shed.
```

---

## 2. What people get wrong

### Wrong model 1: retries make systems more reliable

Retries help only when failures are transient and the dependency has capacity to recover.

Bad retry shape:

```text
Dependency is overloaded
  -> callers retry
  -> more requests hit dependency
  -> dependency gets worse
  -> callers retry more
```

Retries without budgets are tiny denial-of-service machines you built yourself.

### Wrong model 2: timeout value is just a config number

Timeouts are architecture. A child call cannot safely have a timeout longer than the parent request budget.

```text
User-facing SLO: 1000 ms

Gateway:       100 ms
Orders:        200 ms
Inventory:     250 ms
Payment:       350 ms
Buffer:        100 ms
```

If payment timeout is 5 seconds inside a 1 second user request, the timeout is fiction.

### Wrong model 3: fallback means everything is okay

Fallback is degraded behavior. It needs correctness rules.

Safe fallback:

```text
recommendations unavailable -> show empty recommendations
```

Dangerous fallback:

```text
pricing unavailable -> use stale price at checkout
```

Some systems fail open. Some fail closed. You must decide deliberately.

---

## 3. Timeouts

A timeout bounds how long a caller waits.

```text
+--------+      +----------+
| Caller | ---> | Service  |
+--------+      +----------+
       waits up to N ms
```

Timeouts must cover:

```text
DNS lookup
TCP connection
TLS handshake
request write
server processing
response read
connection pool wait
```

Common mistake:

```text
HTTP timeout = 500ms
connection pool wait = unbounded
```

The request can still hang before the HTTP call even begins.

Timeout budget example:

```text
End-to-end target: 1000 ms

API gateway:          80 ms
checkout service:    150 ms
inventory call:      200 ms
payment call:        350 ms
database writes:     150 ms
buffer:               70 ms
```

If any child timeout exceeds remaining parent budget, the system will waste work after the caller is gone.

---

## 4. Retries

Retries are useful for:

```text
connection reset
brief network blip
leader election blip
transient 503 with Retry-After
optimistic lock conflict
```

Retries are dangerous for:

```text
validation errors
permanent 4xx
payment capture without idempotency
large writes to overloaded storage
requests that already timed out upstream
```

Retry amplification:

```text
Client retries:   3
Gateway retries:  2
Service retries:  3
DB retries:       2

Worst attempts:
  3 * 2 * 3 * 2 = 36
```

Better retry policy:

```text
bounded attempts
exponential backoff
jitter
respect Retry-After
retry only safe operations
stop retrying when parent deadline is near
```

Jitter matters:

```text
without jitter:
  every client retries at 100ms, 200ms, 400ms

with jitter:
  retries spread across time
```

---

## 5. Circuit breaker

A circuit breaker stops sending traffic to a dependency that appears unhealthy.

States:

```text
Closed:
  normal traffic flows

Open:
  fail fast or fallback

Half-open:
  allow a small test set to check recovery
```

Diagram:

```text
+--------+      +----------------+      +----------+
| Caller | ---> | CircuitBreaker | ---> | Service  |
+--------+      +----------------+      +----------+
                      |
                      v
                  fallback
```

Why it helps:

```text
- protects caller threads
- reduces pressure on broken dependency
- gives dependency time to recover
- makes degradation explicit
```

Failure modes:

```text
breaker threshold too sensitive:
  flaps open and closed

breaker too slow:
  dependency melts before breaker opens

fallback expensive:
  fallback becomes new bottleneck

shared breaker:
  one endpoint failure blocks unrelated endpoint
```

Breaker metrics:

```text
state
open count
half-open success/failure
calls permitted
calls rejected
failure rate
slow-call rate
fallback latency
```

---

## 6. Bulkheads

Bulkheads isolate resources so one failing dependency cannot consume all workers.

```text
+-------------+
| API process |
+-------------+
   |     |     |
   v     v     v
Payment Search Email
pool    pool   pool
```

If search is slow, payment still has its own pool.

Bulkheads can isolate:

```text
thread pools
connection pools
queues
CPU workers
rate limits
Kubernetes deployments
message consumers
```

Bad design:

```text
one shared HTTP client pool for payment, email, search, analytics
```

If analytics hangs, payment can starve.

Good design:

```text
payment pool: critical, small, protected
search pool: optional, bounded
analytics pool: async, shed first
```

---

## 7. Backpressure and load shedding

Backpressure tells upstream to slow down. Load shedding rejects work to protect the system.

```text
+----------+      +-------+      +----------+
| Producer | ---> | Queue | ---> | Consumer |
+----------+      +-------+      +----------+
                     |
                     v
                depth too high
```

Bad behavior:

```text
queue grows forever
latency becomes hours
memory pressure rises
workers crash
restarts make it worse
```

Better behavior:

```text
queue depth high
  -> reject low-priority work
  -> slow producers
  -> return 429/503 with Retry-After
  -> preserve critical traffic
```

Load shedding policy should rank work:

```text
keep:
  payment
  order creation
  security actions

shed first:
  recommendations
  analytics
  non-critical refresh
  expensive exports
```

---

## 8. Production failure patterns

### Failure 1: retry storm during dependency outage

Shape:

```text
+---------+      +---------+
| Callers | ---> | Service |
+---------+      +---------+
     ^              |
     |              v
     +---- retry ---+
```

Symptoms:

```text
dependency errors rise
request rate to dependency increases after failure begins
latency rises everywhere
caller thread pools fill
```

Mitigation:

```text
1. Disable or reduce retries.
2. Respect Retry-After.
3. Open circuit breaker.
4. Shed optional traffic.
5. Add jittered backoff.
```

### Failure 2: circuit breaker flapping

Shape:

```text
closed -> open -> half-open -> closed -> open
```

Causes:

```text
threshold too low
half-open test volume too high
dependency recovers slowly
fallback causes extra load
```

Mitigation:

```text
increase minimum sample size
use slow-call threshold separately from failure threshold
limit half-open probes
watch dependency recovery metrics
```

### Failure 3: fallback overload

Example:

```text
primary profile service fails
fallback reads Redis
all traffic hits Redis hot keys
Redis melts
```

Mitigation:

```text
capacity-test fallback
use local cache for hot data
rate limit fallback path
fail closed if fallback is unsafe
```

### Failure 4: unbounded queue collapse

Symptoms:

```text
queue depth rises
oldest message age rises
memory pressure rises
consumer p99 rises
users see stale results
```

Mitigation:

```text
set max queue size
drop or expire low-value work
apply producer backpressure
increase consumers only if downstream has capacity
```

### Failure 5: wrong fail-open/fail-closed choice

Examples:

```text
Auth service unavailable:
  fail closed for privileged operations

Recommendation service unavailable:
  fail open with empty recommendations

Fraud service unavailable:
  depends on risk policy; maybe queue for manual review
```

---

## 9. SRE diagnostic toolkit

Timeout and retry signals:

```text
request timeout rate
retry attempts per request
retry success rate
requests after parent cancellation
```

Circuit breaker signals:

```text
breaker state
open transitions
half-open success rate
rejected calls
fallback calls
```

Bulkhead signals:

```text
pool active
pool queued
pool rejected
pool wait time
pool saturation by dependency
```

Queue/backpressure signals:

```text
queue depth
oldest item age
ingress rate
egress rate
shed count
429/503 rate
Retry-After usage
```

Trace questions:

```text
Which dependency dominates latency?
Did retries happen inside the trace?
Did work continue after caller timeout?
Was fallback used?
Which pool was saturated?
```

---

## 10. Decision framework

```text
+-----------------------------+------------------------------+
| Problem                     | Pattern                      |
+-----------------------------+------------------------------+
| dependency is slow          | timeout                      |
| transient failure           | bounded retry with jitter    |
| dependency is unhealthy     | circuit breaker              |
| one dependency starves all  | bulkhead                     |
| queue grows faster than drain | backpressure/load shedding |
| optional dependency fails   | fallback or degrade          |
| unsafe operation uncertain  | reconcile, do not retry blindly |
+-----------------------------+------------------------------+
```

Critical rule:

```text
Retries, fallbacks, and load shedding are business decisions as much as technical decisions.
```

---

## 11. Incident scenario: recommendation outage breaks checkout

Architecture:

```text
+--------+      +----------+      +---------+
| Client | ---> | Checkout | ---> | Payment |
+--------+      +----------+      +---------+
                     |
                     v
              +---------------+
              | Recommendation|
              +---------------+
```

Symptoms:

```text
checkout p95:              8.5s
payment p95:               280ms
recommendation p95:        7.2s
checkout error rate:       14%
recommendation error rate: 52%
thread pool active:        100%
retry attempts/request:    9
```

Recent change:

```text
recommendation client timeout raised from 200ms to 5s
retry count raised from 1 to 3
recommendation uses same HTTP pool as payment
```

Expert diagnosis:

```text
An optional dependency was put inside the critical checkout path with a long
timeout, aggressive retries, and shared resource pool. Recommendation failure is
starving checkout and payment calls.
```

Mitigation:

```text
1. Disable recommendation call in checkout.
2. Restore short timeout.
3. Remove retries for optional recommendation path.
4. Separate recommendation and payment bulkheads.
5. Add circuit breaker and empty fallback.
6. Add dependency classification to architecture review.
```

---

## 12. Key takeaways

```text
1. Timeouts bound waiting; retries multiply work.
2. Retries need budgets, backoff, and jitter.
3. Circuit breakers fail fast to protect callers and dependencies.
4. Bulkheads isolate resource exhaustion.
5. Backpressure is healthier than infinite queues.
6. Fallbacks need capacity and correctness rules.
7. Optional dependencies must not break critical workflows.
```
