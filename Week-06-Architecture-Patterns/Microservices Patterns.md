# Week 6, Topic 3: Microservices Patterns

Last verified: 2026-05-15

Microservices are independently deployable services around business capabilities. They are not a folder structure and not a prize for splitting a monolith too early.

## Learning objectives

```text
1. Explain service boundaries, ownership, contracts, and deployment independence.
2. Identify distributed monolith symptoms.
3. Use API gateway, BFF, service discovery, sidecars, and versioned contracts safely.
4. Diagnose cascading failures across services.
```

## Core model

```text
+--------+      +-------------+
| Client | ---> | API Gateway |
+--------+      +-------------+
                    |     |
                    v     v
              +------+  +---------+
              |Users |  | Orders  |
              +------+  +---------+
                         |       |
                         v       v
                    +--------+ +----------+
                    |Payment | |Inventory |
                    +--------+ +----------+
```

## What people get wrong

```text
Wrong: one table per service automatically creates microservices.
Wrong: every function should become a service.
Wrong: microservices remove coupling.
Right: they move coupling into APIs, data ownership, network calls, and operations.
```

## Good boundaries

```text
- business capability
- clear owner team
- independent lifecycle
- explicit API contract
- private database ownership
- observable SLO
```

## Failure modes

```text
Distributed monolith:
  every deploy requires every team.

Sync call chain explosion:
  one user request triggers 20 services.

Shared database coupling:
  schema migration breaks many services.

Retry storm:
  one dependency fails and every caller retries.

Ownership fog:
  nobody owns the user-visible workflow end to end.
```

## Diagnostics

```text
Check:
  - dependency graph depth
  - per-service p95/p99
  - error budget burn by service
  - retry rate
  - circuit breaker opens
  - deploy correlation
  - database ownership violations
```

## Scenario

A checkout request calls cart, pricing, coupons, inventory, payment, fraud, shipping, recommendations, email, and analytics synchronously. Payment is healthy, but recommendations p99 jumps to 8s and checkout fails.

Expert answer:

```text
The architecture put optional work in the critical path. Move recommendations,
email, and analytics async. Keep payment/inventory correctness explicit. Add
call budgets, timeouts, bulkheads, and dependency classification.
```

## Key takeaways

```text
1. Microservices buy independent change at the cost of distributed operations.
2. Service boundaries should follow business ownership.
3. A shared database creates hidden coupling.
4. Optional dependencies must not block critical user flows.
5. Observability and ownership are part of the architecture.
```
