# Week 6, Topic 3: Microservices Patterns

Last verified: 2026-05-15

Microservices are independently deployable services organized around business capabilities. They are not a folder layout, not one table per API, and not a shortcut to scale.

The real promise is independent change and ownership. The real cost is distributed failure, network latency, contract governance, observability, and operational coordination.

---

## 1. Learning objectives

```text
After this topic, you should be able to:

1. Define a microservice using ownership, deployment, and business capability.
2. Identify distributed monolith symptoms.
3. Design service boundaries around business capabilities and data ownership.
4. Explain API gateway, BFF, service discovery, sidecars, and service mesh.
5. Diagnose cascading failures, retry storms, shared-database coupling, and bad boundaries.
6. Decide when a modular monolith is better than microservices.
```

---

## 2. What people get wrong

### Wrong model 1: splitting code creates microservices

A service is not a directory. A service is an independently deployable unit with its own ownership, runtime, contract, and operational responsibility.

```text
Not enough:
  /users
  /orders
  /payments

Required:
  independent deploy
  clear owner
  private data ownership
  observable SLO
  explicit API/event contract
```

### Wrong model 2: microservices reduce complexity

Microservices often reduce local code complexity and increase system complexity.

```text
Monolith complexity:
  function calls
  one database
  one deploy

Microservice complexity:
  network calls
  partial failure
  versioned APIs
  distributed tracing
  eventual consistency
  deployment coordination
```

### Wrong model 3: each service gets one table

A service owns data because it owns business behavior, not because someone sliced tables evenly.

Bad boundary:

```text
UserService owns users table
ProfileService owns profiles table
SettingsService owns settings table

Every user page now needs all three synchronously.
```

Better boundary:

```text
Account service owns user account lifecycle.
Profile read model can be built asynchronously if needed.
```

---

## 3. Core architecture

```text
+--------+      +-------------+
| Client | ---> | API Gateway |
+--------+      +-------------+
                    |     |
                    v     v
               +------+ +--------+
               |User  | |Orders  |
               +------+ +--------+
                          |    |
                          v    v
                    +-------+ +----------+
                    |Payment| |Inventory |
                    +-------+ +----------+
```

A good service boundary has:

```text
business capability
clear owning team
private database or private schema ownership
explicit API or event contract
independent deployment path
observable health and SLO
```

A bad service boundary has:

```text
shared database tables
chatty synchronous dependencies
unclear ownership
constant lockstep deployments
no independent rollback
```

---

## 4. Common patterns

### API Gateway

```text
+--------+      +-------------+      +----------+
| Client | ---> | API Gateway | ---> | Services |
+--------+      +-------------+      +----------+
```

Responsibilities:

```text
routing
authentication edge checks
rate limiting
request shaping
TLS termination
coarse observability
```

Danger:

```text
Gateway becomes a business-logic junk drawer.
```

### BFF: Backend for Frontend

```text
Mobile app -> Mobile BFF -> services
Web app    -> Web BFF    -> services
```

Use when mobile and web need different aggregation shapes. Avoid making every BFF a second monolith.

### Service discovery

```text
+---------+      +------------+      +---------+
| Service | ---> | Discovery  | ---> | Endpoint|
+---------+      +------------+      +---------+
```

Examples include Kubernetes Services, DNS, Consul, Eureka, and mesh control planes.

### Sidecar and service mesh

```text
+-------------+       +-------------+
| App         | <---> | Sidecar     |
+-------------+       +-------------+
                         |
                         v
                    network policy
                    retries
                    mTLS
                    telemetry
```

A mesh can standardize networking behavior. It can also create an opaque failure plane if teams do not understand it.

---

## 5. Data ownership

The strongest rule:

```text
A service should not casually write another service's database.
```

Bad:

```text
+--------+      +------------------+
| Orders | ---> | payments database|
+--------+      +------------------+
```

Better:

```text
+--------+      CapturePayment      +----------+
| Orders | -----------------------> | Payments |
+--------+                          +----------+
```

Or async:

```text
+--------+      OrderPlaced      +----------+
| Orders | -------------------> | Payments |
+--------+                       +----------+
```

If two services write the same table, ownership is unclear and incidents become archaeology.

---

## 6. Distributed monolith symptoms

```text
- every release requires many services to deploy together
- one user request calls 15 services synchronously
- services share one database
- rollback requires cross-team choreography
- no service can run locally or in isolation
- contracts are undocumented
- failures cascade across the graph
- every service has to know every other service's data model
```

Distributed monolith diagram:

```text
+---+ -> +---+ -> +---+ -> +---+
| A |    | B |    | C |    | D |
+---+ <- +---+ <- +---+ <- +---+
  |        |        |        |
  +--------+--------+--------+
           shared database
```

This has the operational pain of microservices and the coupling of a monolith.

---

## 7. Failure patterns

### Failure 1: synchronous call chain explosion

```text
Client -> API -> A -> B -> C -> D -> E
```

If each hop has p99 of 200ms, the chain can easily exceed a user SLO even without errors.

Symptoms:

```text
high tail latency
trace spans show deep dependency chain
small downstream latency causes large user impact
```

Fix:

```text
collapse unnecessary boundaries
parallelize independent calls
move optional work async
cache carefully
set timeout budgets
```

### Failure 2: retry storm

```text
A calls B
B slows down
A retries
more A calls pile up
B gets worse
```

Fix:

```text
bounded retries
jittered backoff
circuit breaker
bulkhead isolation
load shedding
```

### Failure 3: shared database coupling

A schema change by one service breaks another service that reads the same table.

Fix:

```text
private ownership
public API or events
expand-contract migrations
backward-compatible schemas
```

### Failure 4: ownership fog

A user-visible workflow fails, but each service says it is healthy.

Fix:

```text
end-to-end SLO
workflow owner
trace-based debugging
incident commander
service dependency map
```

---

## 8. SRE diagnostic toolkit

Ask these first:

```text
Which user workflow is broken?
Which service owns that workflow?
Which dependency is slow or failing?
Did a deploy happen?
Is failure localized by version, region, tenant, or endpoint?
```

Signals:

```text
request rate by service
error rate by service and dependency
p95/p99 latency by hop
retry rate
circuit breaker state
connection pool saturation
queue depth
trace critical path
```

Trace inspection:

```text
root span: checkout POST /orders
  orders-service: 120ms
  inventory-service: 1.8s
  payment-service: 300ms
  recommendation-service: 4.2s
```

If recommendation is optional, it should not hold checkout hostage.

---

## 9. Decision framework

```text
+-----------------------------+------------------------------+
| Situation                   | Better choice                |
+-----------------------------+------------------------------+
| one team, early product     | modular monolith             |
| unclear domain boundaries   | modular monolith first       |
| independent teams/domains   | microservices candidate      |
| strict shared transactions  | monolith or careful saga     |
| optional fanout side effects| event-driven services        |
| independent scaling needs   | microservices candidate      |
+-----------------------------+------------------------------+
```

Microservices are justified when independent ownership and deployment are worth the distributed-systems tax.

---

## 10. Incident scenario: checkout dependency chain

Architecture:

```text
+--------+      +----------+      +-------+      +---------+
| Client | ---> | Checkout | ---> | Cart  | ---> | Pricing |
+--------+      +----------+      +-------+      +---------+
                     |
                     v
                 +---------+
                 | Payment |
                 +---------+
                     |
                     v
                +------------+
                | Inventory  |
                +------------+
                     |
                     v
              +----------------+
              | Recommendations|
              +----------------+
```

Symptoms:

```text
checkout p95: 7.8s
payment p95: 280ms
inventory p95: 350ms
recommendations p95: 5.9s
checkout error rate: 11%
recommendation errors: 40%
```

Expert diagnosis:

```text
A non-critical dependency is inside the critical checkout path. The business path
should require payment and inventory decisions, not recommendations. This is a
boundary and dependency-classification failure.
```

Mitigation:

```text
1. Disable recommendations in checkout.
2. Add a short timeout and fallback.
3. Move recommendation update async.
4. Add dependency classification: critical, degraded, optional.
5. Add trace-based alerting for critical path p99.
```

---

## 11. Key takeaways

```text
1. Microservices are about ownership and independent change.
2. Splitting code without splitting ownership creates a distributed monolith.
3. Private data ownership is a service boundary rule.
4. Optional dependencies must not block critical workflows.
5. Observability is part of the architecture, not a dashboard afterthought.
6. A modular monolith is often the correct first architecture.
```
