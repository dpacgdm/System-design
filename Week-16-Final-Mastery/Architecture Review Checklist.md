# Architecture Review Checklist — Final Mastery

> Architecture review is where designs meet reality. This checklist guides reviewers — and authors preparing for review — through a structured, component-level audit. Use it for ARB sessions, cross-team design reviews, and Week 16 capstone self-assessment.

---

## Learning Objectives

```
╔════════════════════════════════════════════════════════════════════╗
║   AFTER THIS CHECKLIST, YOU WILL BE ABLE TO:                       ║
╟────────────────────────────────────────────────────────────────────╢
║                                                                    ║
║   1. Prepare a design doc and presentation that survives           ║
║      principal-level scrutiny — not just passes a meeting          ║
║                                                                    ║
║   2. Review every component, data flow, and dependency with        ║
║      a systematic checklist — not ad-hoc diagram critique          ║
║                                                                    ║
║   3. Identify single points of failure, scaling ceilings, and      ║
║      API contract gaps before they become production incidents     ║
║                                                                    ║
║   4. Produce structured review outcomes: approve, conditional,     ║
║      or reject — with specific, actionable remediation items       ║
║                                                                    ║
║   5. Validate that data flows match stated consistency and         ║
║      security requirements end-to-end                              ║
╚════════════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔═════════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Review the diagram, approve the design"             ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Diagrams hide failure modes. Review data flows,                ║
║   consistency boundaries, and failure propagation paths.                ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "Scalability = add more servers"                     ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Review for stateful bottlenecks, hot partitions,               ║
║   O(n²) fan-out, and coordination overhead that linear scaling          ║
║   cannot fix.                                                           ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "Dependencies are someone else's problem"            ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Your SLO is the product of your dependencies' SLOs.            ║
║   Review every external call as a reliability contract.                 ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "API contracts can evolve later"                     ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Breaking changes after launch are migrations. Review           ║
║   versioning, idempotency, pagination, and error semantics now.         ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Conditional approve = soft reject"                  ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Conditional approval requires explicit items, owners,          ║
║   dates, and a re-review trigger. Vague conditions are rejections.      ║
╚═════════════════════════════════════════════════════════════════════════╝
```

---

## How to Use This Checklist

```
╔═══════════════════════════════════════════════════════════════════════╗
║   ROLES                                                               ║
╟───────────────────────────────────────────────────────────────────────╢
║   Author:     Self-review before submitting; attach completed         ║
║               checklist as appendix                                   ║
║   Reviewer:   Mark each item [x] with evidence or file comment        ║
║   Moderator:  Ensure all sections covered; enforce outcome template   ║
╠═══════════════════════════════════════════════════════════════════════╣
║   TIMING                                                              ║
╟───────────────────────────────────────────────────────────────────────╢
║   Pre-review:  Author completes Sections 1–2 (prep + summary)         ║
║   Review mtg:  Sections 3–8 (60–90 min for Tier 1 systems)            ║
║   Post-review: Section 9 outcome recorded within 24 hours             ║
╠═══════════════════════════════════════════════════════════════════════╣
║   SEVERITY TAGS IN COMMENTS                                           ║
╟───────────────────────────────────────────────────────────────────────╢
║   [BLOCK]   Must fix before launch                                    ║
║   [MAJOR]   Must fix before GA; OK for limited beta                   ║
║   [MINOR]   Fix in v1.1; document as known limitation                 ║
║   [NIT]     Style/clarity; non-blocking                               ║
╚═══════════════════════════════════════════════════════════════════════╝
```

---

## Section 1: Review Preparation (Author)

### Design Doc Requirements

```
[ ] Executive summary: problem, solution, key trade-offs (1 page max)
[ ] Requirements: functional (ranked P0/P1/P2) and non-functional (with numbers)
[ ] Architecture diagram: components, data stores, external dependencies
[ ] Data flow diagrams for top 3 user journeys (happy path + failure path)
[ ] API specifications or links to OpenAPI/Proto definitions
[ ] Data model / schema with access patterns documented
[ ] Capacity estimation worksheet completed
[ ] Failure mode analysis (FMEA or equivalent)
[ ] Security threat model summary
[ ] Migration plan (if replacing existing system)
[ ] Open questions section — honest list of unresolved items
[ ] ADRs linked for major technology and pattern decisions
```

### Review Meeting Preparation

```
[ ] Reviewers identified: primary, security, SRE, affected team leads
[ ] Design doc shared ≥ 3 business days before review
[ ] Pre-read acknowledgment from all required reviewers
[ ] Presentation deck ≤ 15 slides (diagram + deep dive on hardest path)
[ ] Timeboxed agenda: 10 min present, 50 min review, 10 min outcome
[ ] Decision maker identified (who can approve/reject)
[ ] Previous review feedback addressed with change log
```

---

## Section 2: Review Kickoff (Moderator)

```
[ ] Problem statement restated — reviewers align on what is being solved
[ ] Scope confirmed: v1 vs future, in-scope vs out-of-scope
[ ] Design driver identified: the requirement that most constrains architecture
[ ] Review focus areas flagged by author (known weak spots)
[ ] Review type confirmed: new system, major change, migration, deprecation
[ ] Tier assigned: Tier 0 (revenue/critical), Tier 1, Tier 2, Tier 3
```

---

## Section 3: Component-by-Component Review

For each component in the architecture diagram, verify:

### Compute (Services, Workers, Functions)

```
[ ] Single responsibility — component does one thing well
[ ] Stateless where possible; session/state externalized if stateful
[ ] Horizontal scaling path documented (what metric triggers scale-out)
[ ] Resource limits defined (CPU, memory, concurrency, thread pools)
[ ] Startup time acceptable for scaling event (< 30s for Tier 0)
[ ] Graceful shutdown: in-flight requests complete, connections drain
[ ] Health check validates dependency connectivity, not just process liveness
[ ] Deployment unit identified (container, Lambda, VM) with rationale
[ ] Language/runtime choice justified for team and operational constraints
[ ] Background job isolation from request path (separate pools/queues)
```

### Data Stores (Databases, Caches, Object Storage)

```
[ ] Store choice matches access pattern (OLTP, OLAP, KV, graph, time-series)
[ ] Primary key / partition key design reviewed for hot spots
[ ] Index strategy: query patterns supported without full table scans
[ ] Replication factor and consistency model stated
[ ] Backup and restore tested; RPO/RTO achievable
[ ] Connection pooling and max connections sized for fleet
[ ] Cache invalidation strategy documented (TTL, event-driven, write-through)
[ ] Cache stampede protection (probabilistic early expiration, locking)
[ ] Data lifecycle: TTL, archival, deletion (including compliance)
[ ] Multi-tenant isolation if applicable (schema, row-level, or DB-level)
```

### Messaging (Queues, Streams, Pub/Sub)

```
[ ] At-least-once vs exactly-once semantics stated and handled
[ ] Consumer idempotency implemented for at-least-once delivery
[ ] Dead letter queue (DLQ) configured with alerting and replay procedure
[ ] Message ordering guarantees stated (partition key if order required)
[ ] Backpressure handling: producer throttling when consumer lag grows
[ ] Retention policy sized for replay and recovery scenarios
[ ] Schema evolution strategy (Avro/Protobuf with compatibility mode)
[ ] Fan-out pattern justified (direct publish vs exchange vs stream processing)
```

### Gateways & Load Balancers

```
[ ] TLS termination point identified; cert rotation automated
[ ] Rate limiting at edge (per IP, per user, per API key)
[ ] Request routing rules documented (path, header, weighted)
[ ] WAF rules for OWASP Top 10 on public endpoints
[ ] DDoS protection layer identified (CDN, shield, cloud-native)
[ ] Timeout configuration at gateway matches downstream budgets
[ ] Request/response size limits enforced
```

### External Dependencies

```
[ ] Each dependency listed with owner team and their SLO
[ ] Fallback behavior when dependency unavailable
[ ] Circuit breaker configuration (threshold, half-open probe)
[ ] Timeout < client timeout (avoid cascading hang)
[ ] Retry policy: max attempts, backoff, idempotency requirement
[ ] Dependency version pinned; upgrade policy documented
[ ] Vendor lock-in risk assessed; exit strategy for critical deps
```

---

## Section 4: Data Flow Validation

Trace each critical user journey end-to-end:

```
[ ] Request path: client → gateway → service → store → response
[ ] Write path: where is durability confirmed before ACK to client?
[ ] Read path: cache → primary → replica fallback order documented
[ ] Async path: event published → consumed → side effect idempotent
[ ] Cross-service transaction boundary identified (Saga, 2PC, or eventual)
[ ] Data transformation points logged for debuggability
[ ] PII flow mapped: where entered, stored, transmitted, deleted
[ ] Consistency guarantee at each hop stated (strong, eventual, causal)
[ ] Latency budget allocated per hop (sum ≤ SLO target)
[ ] Error propagation: how failures surface to client (status codes, messages)
```

### Data Flow Review Template

```
┌─────────────────────────────────────────────────────────────────┐
│  JOURNEY: _________________________  SLO: _______  Tier: _____  │
├─────────────────────────────────────────────────────────────────┤
│  Hop 1: _________ → _________  latency budget: ___ms            │
│         consistency: _________  failure mode: ______________    │
│  Hop 2: _________ → _________  latency budget: ___ms            │
│         consistency: _________  failure mode: ______________    │
│  Hop 3: _________ → _________  latency budget: ___ms            │
│         consistency: _________  failure mode: ______________    │
│  Total budget: ___ms  vs SLO: ___ms  [ ] PASS  [ ] FAIL         │
└─────────────────────────────────────────────────────────────────┘
```

---

## Section 5: Dependency Analysis

```
[ ] Dependency graph drawn (direct and transitive)
[ ] Critical path dependencies identified (longest chain for SLO)
[ ] Circular dependencies eliminated or explicitly managed
[ ] Shared dependencies flagged (one outage affects N services)
[ ] Dependency SLO multiplied to compute composite availability
[ ] Sync vs async coupling justified for each dependency
[ ] Contract tests or consumer-driven tests planned
[ ] Dependency failure injection in staging/pre-prod
[ ] Escalation contact for each dependency team documented
[ ] Alternative provider or self-host fallback for Tier 0 deps
```

### Composite Availability Check

```
If service A depends on B (99.9%) and C (99.95%):
  Composite ≤ 99.9% × 99.95% ≈ 99.85%
  [ ] Stated SLO does not exceed composite availability
  [ ] Mitigations if composite is below target (cache, fallback, async)
```

---

## Section 6: Scalability Review

```
[ ] Stateless tier scales horizontally without code changes
[ ] Database sharding/partitioning strategy for write scale
[ ] Read scale: replicas, caching, or CQRS — not just "add read replicas"
[ ] Hot key / hot partition mitigation (salting, key splitting)
[ ] Fan-out pattern bounded (no O(followers) synchronous calls)
[ ] Batch processing decoupled from online path
[ ] Auto-scaling policies defined with min/max and cooldown
[ ] Scale-down safe: no data loss, no connection storm
[ ] Multi-region scale strategy if global (write routing, conflict resolution)
[ ] Cost curve at 10× and 100× scale — linear or superlinear?
[ ] Load test results attached with bottleneck identified
[ ] Scaling ceiling documented: "breaks at ___ QPS because ___"
```

---

## Section 7: Single Points of Failure (SPOF) Audit

```
[ ] Every component in diagram classified: SPOF, HA, or N/A
[ ] SPOFs either eliminated or accepted with signed risk ADR
[ ] Load balancer itself is not a SPOF (multi-AZ, anycast, or cloud-managed)
[ ] DNS failover or low-TTL strategy for regional failure
[ ] Database: multi-AZ, automatic failover, split-brain prevention
[ ] Message broker: cluster mode, replication factor ≥ 3 for Tier 0
[ ] Configuration store: replicated, not a single etcd node
[ ] Secrets manager: HA, not env vars on one machine
[ ] IdP / auth service: fallback or cached token validation
[ ] Third-party SaaS: fallback or degraded mode documented
[ ] "Human in the loop" steps identified as operational SPOFs
[ ] Runbook exists for each accepted SPOF failure scenario
```

### SPOF Register Template

```
┌──────────────┬──────────┬─────────────────────┬──────────────────────┐
│  Component   │  SPOF?   │  Mitigation         │  Residual Risk       │
├──────────────┼──────────┼─────────────────────┼──────────────────────┤
│  __________  │  Y / N   │  _________________  │  __________________  │
│  __________  │  Y / N   │  _________________  │  __________________  │
│  __________  │  Y / N   │  _________________  │  __________________  │
└──────────────┴──────────┴─────────────────────┴──────────────────────┘
```

---

## Section 8: API Contract Review

```
[ ] REST/gRPC/GraphQL choice justified for consumers
[ ] OpenAPI/Proto spec complete: all endpoints, schemas, errors
[ ] Versioning strategy: URL path, header, or content negotiation
[ ] Breaking change policy and deprecation timeline
[ ] Idempotency: POST/PUT support Idempotency-Key or natural keys
[ ] Pagination: cursor-based for large sets (not offset for deep pages)
[ ] Rate limit headers: X-RateLimit-Remaining, Retry-After on 429
[ ] Error response schema consistent (code, message, request_id)
[ ] Authentication: scheme documented (Bearer, mTLS, API key)
[ ] Authorization: scope/role requirements per endpoint
[ ] Request validation: 400 with field-level errors
[ ] Timeout guidance for clients documented
[ ] Webhook delivery: retry, signature verification, idempotency
[ ] Backward compatibility test suite or contract tests in CI
```

---

## Section 9: Trade-Off & Alternative Review

Principal reviewers verify the author chose deliberately — not by default or hype.

```
[ ] At least 2 viable alternatives considered for the primary storage choice
[ ] At least 2 viable alternatives considered for the messaging pattern
[ ] Sync vs async decision justified with latency and consistency trade-off
[ ] SQL vs NoSQL choice tied to access patterns — not familiarity
[ ] Build vs buy analysis for non-core components
[ ] Explicit "what we gave up" section — not just "what we chose"
[ ] ADR exists for each major fork-in-the-road decision
[ ] Revisit triggers defined: "re-evaluate if QPS exceeds ___ or team grows to ___"
[ ] Complexity budget: component count justified against team size
[ ] Operational cost of choice documented (not just infra cost)
```

### Trade-Off Documentation Template

```
┌───────────────────────────────────────────────────────────────────┐
│  DECISION: Use Cassandra for time-series event store              │
├───────────────────────────────────────────────────────────────────┤
│  Alternatives: TimescaleDB, DynamoDB, Kafka + S3                  │
│  Chose because: write-heavy, TTL native, team has C* expertise    │
│  Gave up: ad-hoc SQL analytics, strong cross-partition tx         │
│  Revisit if: query patterns shift to heavy aggregation            │
└───────────────────────────────────────────────────────────────────┘
```

---

## Section 10: Failure Mode & Resilience Review

```
[ ] Failure mode table present in design doc (see Principal SRE checklist)
[ ] Each Tier 0 path has documented degraded mode — not hard fail
[ ] Retry amplification analyzed: what if all clients retry simultaneously?
[ ] Cache failure: thundering herd to database prevented
[ ] Queue backlog: consumer lag alert + DLQ + replay runbook
[ ] Regional failure: traffic reroutes within RTO
[ ] Deploy failure: canary detects regression before full rollout
[ ] Config error: schema validation rejects bad config at startup
[ ] Certificate expiry: automated renewal with 30-day warning alert
[ ] Dependency slow (not down): timeout + circuit breaker tested
[ ] Game day scheduled for top 3 failure scenarios before GA
```

---

## Section 11: Review Outcome Templates

### APPROVE — Unconditional

```
╔════════════════════════════════════════════════════════════════════╗
║   ARCHITECTURE REVIEW — APPROVED                                   ║
╠════════════════════════════════════════════════════════════════════╣
║   System: _________________________  Tier: _____  Date: ________   ║
║   Reviewers: ___________________________________________________   ║
║                                                                    ║
║   All BLOCK and MAJOR items resolved. Design is approved for       ║
║   implementation and production readiness review per schedule.     ║
║                                                                    ║
║   Commendations (optional):                                        ║
║   • _____________________________________________________________  ║
║                                                                    ║
║   Follow-up (non-blocking):                                        ║
║   • [MINOR] _____________________________________________________  ║
║                                                                    ║
║   Next gate: Production Readiness Review — target date: ________   ║
╚════════════════════════════════════════════════════════════════════╝
```

### CONDITIONAL APPROVE

```
╔═════════════════════════════════════════════════════════════════════╗
║   ARCHITECTURE REVIEW — CONDITIONALLY APPROVED                      ║
╠═════════════════════════════════════════════════════════════════════╣
║   System: _________________________  Tier: _____  Date: ________    ║
║                                                                     ║
║   Approved for LIMITED scope (beta / internal / shadow traffic)     ║
║   until ALL conditions below are met and re-reviewed.               ║
║                                                                     ║
║   CONDITIONS (all required):                                        ║
║   ┌────┬──────────────────────────────┬──────────┬──────────────┐   ║
║   │ #  │  Remediation                 │  Owner   │  Due Date    │   ║
║   ├────┼──────────────────────────────┼──────────┼──────────────┤   ║
║   │ 1  │  __________________________  │  ______  │  __________  │   ║
║   │ 2  │  __________________________  │  ______  │  __________  │   ║
║   │ 3  │  __________________________  │  ______  │  __________  │   ║
║   └────┴──────────────────────────────┴──────────┴──────────────┘   ║
║                                                                     ║
║   Re-review trigger: ___________________________________________    ║
║   Re-review date: __________  Reviewer: _________________________   ║
╚═════════════════════════════════════════════════════════════════════╝
```

### REJECT

```
╔════════════════════════════════════════════════════════════════════╗
║   ARCHITECTURE REVIEW — REJECTED                                   ║
╠════════════════════════════════════════════════════════════════════╣
║   System: _________________________  Tier: _____  Date: ________   ║
║                                                                    ║
║   Design is NOT approved for implementation. Fundamental gaps      ║
║   require revision and new review session.                         ║
║                                                                    ║
║   BLOCKING ISSUES:                                                 ║
║   1. [BLOCK] ____________________________________________________  ║
║   2. [BLOCK] ____________________________________________________  ║
║   3. [BLOCK] ____________________________________________________  ║
║                                                                    ║
║   Required for resubmission:                                       ║
║   • Revised design doc addressing all BLOCK items                  ║
║   • Updated capacity and failure mode sections                     ║
║   • Minimum _____ business days before re-review                   ║
║                                                                    ║
║   Reviewer guidance: ____________________________________________  ║
╚════════════════════════════════════════════════════════════════════╝
```

---

## Good vs Bad: Architecture Review

### Good Review Behavior

```
✓ "Walk me through the write path for checkout — when is the order durable?"
✓ "Partition key is user_id — what happens when one influencer drives 40% of traffic?"
✓ "Dependency on fraud-svc has no fallback. That makes fraud-svc a Tier 0 SPOF for checkout."
✓ "Conditional approve: add DLQ and replay runbook for payment events. Owner: @bob, 2 weeks."
```

### Bad Review Behavior

```
✗ "I would have used a different database." — Preference without trade-off.
✗ "Looks fine to me." — No evidence any section was reviewed.
✗ "This won't scale." — No specific bottleneck or number cited.
✗ Debating for 45 minutes on naming conventions. — NIT-level, not review scope.
✗ Approving with 5 unresolved BLOCK items. — Conditional with no conditions listed.
```

---

## Reviewer Self-Check (Before Issuing Outcome)

```
[ ] I reviewed data flows for all P0 user journeys — not just the diagram
[ ] I verified capacity numbers — not just that a section exists
[ ] I identified at least one concern (even on good designs)
[ ] My outcome matches evidence: no approve with open BLOCK items
[ ] Conditional items have owner, date, and re-review trigger
[ ] Comments are actionable: specific component, metric, or path
[ ] I recorded commendations for patterns worth replicating
[ ] Review notes published within 24 hours of meeting
```

---

## Key Takeaways

```
1. Review data flows, not just boxes. Consistency and failure propagation
   hide in the arrows.

2. Every dependency is a contract. Your SLO cannot exceed your dependencies'
   composite availability without mitigation.

3. SPOF audit is mandatory. Accepted SPOFs require signed ADRs and runbooks.

4. API contracts are architecture. Versioning, idempotency, and errors are
   design decisions — not implementation details.

5. Outcomes must be explicit: approve, conditional with owners/dates, or
   reject with blocking issues. Ambiguity is a rejection.
```

---

## Targeted Reading

```
→ "Software Architecture: The Hard Parts" (Ford, Richards, Sadalage) — trade-off analysis
→ "Release It!" (Nygard) — stability patterns, bulkheads, circuit breakers
→ Week 6: Microservices Patterns, Saga, Outbox (this curriculum)
→ Week 13: Design Distributed KV Store, Kafka — component review examples
→ AWS Architecture Center — reference architectures for comparison
```
