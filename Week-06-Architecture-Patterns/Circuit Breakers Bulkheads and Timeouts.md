# Week 6, Topic 5: Circuit Breakers, Bulkheads, Timeouts, Retries, and Backpressure

Last verified: 2026-05-15

Resilience patterns stop one slow dependency from consuming the whole system.

## Learning objectives

```text
1. Explain timeout budgets and retry amplification.
2. Use circuit breakers to fail fast when a dependency is unhealthy.
3. Use bulkheads to isolate resource pools.
4. Apply backpressure and load shedding safely.
```

## Timeout budget

```text
User SLO: 1000 ms

API gateway:       100 ms
Order service:     250 ms
Payment service:   400 ms
Inventory service: 200 ms
Buffer:             50 ms
```

Timeouts must fit inside the caller's budget. A child timeout longer than the parent timeout is nonsense.

## Retry amplification

```text
Client retries: 3
API retries:    3
Service retries:3
DB retries:     3

Worst case attempts:
  3 * 3 * 3 * 3 = 81
```

Retries can turn a small outage into a siege engine.

## Circuit breaker

```text
Closed -> requests flow
Open   -> fail fast
Half-open -> test small number of requests
```

```text
+--------+      +----------------+      +----------+
| Caller | ---> | CircuitBreaker | ---> | Service  |
+--------+      +----------------+      +----------+
                      |
                      v
                  fallback
```

## Bulkhead

```text
+-------------+
| App process |
+-------------+
 |     |     |
 v     v     v
Pay   Search Email
pool  pool   pool
```

If search is slow, it should not consume payment threads.

## Backpressure

Backpressure tells upstream to slow down before queues explode.

```text
Queue depth high -> reject, shed, or slow producers
```

## Failure modes

```text
Retry storm:
  clients retry faster than dependency can recover.

Circuit breaker flapping:
  thresholds too sensitive; traffic pulses open/closed.

Fallback overload:
  fallback cache or database becomes new bottleneck.

No jitter:
  every client retries at the same time.
```

## Diagnostics

```text
Watch:
  - timeout rate
  - retry attempts per request
  - circuit open count
  - half-open success rate
  - bulkhead queue depth
  - rejected requests
  - downstream p99
```

## Scenario

Search service p99 becomes 12s. Checkout calls search for recommendations and starts timing out.

Expert answer:

```text
Search is optional and should be outside checkout critical path. Add timeout,
circuit breaker, and fallback. Put search calls in a separate bulkhead. Disable
recommendations during checkout incidents.
```

## Key takeaways

```text
1. Timeouts are architecture, not config dust.
2. Retries need limits, backoff, and jitter.
3. Circuit breakers protect callers and dependencies.
4. Bulkheads isolate resource exhaustion.
5. Backpressure is better than silent queue growth.
```
