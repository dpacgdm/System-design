# Principal SRE System Design Checklist — Final Mastery

> This checklist is the gate before a design reaches production. Use it when authoring a new system, reviewing a peer's design doc, or preparing for a principal-level design review. Every item maps to a real failure mode seen in production — not interview theater.

---

## Learning Objectives

```
╔════════════════════════════════════════════════════════════════════╗
║   AFTER THIS CHECKLIST, YOU WILL BE ABLE TO:                       ║
╟────────────────────────────────────────────────────────────────────╢
║                                                                    ║
║   1. Run a principal-grade design review without relying on        ║
║      intuition — every gap has a named checklist item              ║
║                                                                    ║
║   2. Ask the 20+ pre-design questions that prevent 80% of          ║
║      late-stage rework (scope creep, wrong consistency model)      ║
║                                                                    ║
║   3. Validate capacity, reliability, security, operability,        ║
║      cost, and migration dimensions before sign-off                ║
║                                                                    ║
║   4. Distinguish "architecturally interesting" from                ║
║      "production-survivable" using explicit sign-off criteria      ║
║                                                                    ║
║   5. Give conditional approvals with specific remediation          ║
║      requirements — not vague "needs more work" feedback           ║
╚════════════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔═══════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Design review = architecture diagram review"      ║
╟───────────────────────────────────────────────────────────────────────╢
║   WRONG. Diagrams are 20% of the review. Capacity math, failure       ║
║   modes, runbooks, cost model, and migration path are the other 80%.  ║
╠═══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "We'll figure out ops after launch"                ║
╟───────────────────────────────────────────────────────────────────────╢
║   WRONG. Operability is a design constraint. If you cannot            ║
║   debug it at 3 AM without the author, it is not ready.               ║
╠═══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "Security is a separate review"                    ║
╟───────────────────────────────────────────────────────────────────────╢
║   INCOMPLETE. Security architecture (authn/z, encryption, blast       ║
║   radius) must be in the design doc. A separate pen test does         ║
║   not fix a broken trust boundary.                                    ║
╠═══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "99.99% everywhere"                                ║
╟───────────────────────────────────────────────────────────────────────╢
║   WRONG. Tier services. Not every component needs the same            ║
║   SLO. Over-engineering availability burns cost and complexity.       ║
╠═══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Migration is a Phase 2 problem"                   ║
╟───────────────────────────────────────────────────────────────────────╢
║   WRONG. If you cannot describe the cutover, rollback, and            ║
║   dual-write strategy now, the design is incomplete.                  ║
╚═══════════════════════════════════════════════════════════════════════╝
```

---

## How to Use This Checklist

```
╔════════════════════════════════════════════════════════════════════╗
║   WHEN TO USE                                                      ║
╟────────────────────────────────────────────────────────────────────╢
║   • Authoring a new system design doc (self-review before submit)  ║
║   • Reviewing a peer's design as designated reviewer               ║
║   • Preparing for architecture review board (ARB) presentation     ║
║   • Final mock interview self-assessment (Week 16 capstone)        ║
╠════════════════════════════════════════════════════════════════════╣
║   HOW TO WORK THROUGH IT                                           ║
╟────────────────────────────────────────────────────────────────────╢
║   1. Read the design doc once without the checklist                ║
║   2. Work section-by-section; mark [x] only with evidence          ║
║   3. Every unchecked item = a comment in the review                ║
║   4. Blockers (marked BLOCK) must be resolved before sign-off      ║
║   5. Score sign-off criteria at the end; no partial passes         ║
╠════════════════════════════════════════════════════════════════════╣
║   EVIDENCE STANDARD                                                ║
╟────────────────────────────────────────────────────────────────────╢
║   "Considered" is not "done." Each [x] requires:                   ║
║   → A sentence in the design doc, OR                               ║
║   → A linked runbook/dashboard/ADR, OR                             ║
║   → Verbal confirmation recorded in review notes                   ║
╚════════════════════════════════════════════════════════════════════╝
```

---

## Section 1: Pre-Design Questions (Ask Before Drawing)

Complete all 20+ before committing to architecture. Skipping these produces elegant diagrams that solve the wrong problem.

### Business & Scope

```
[ ] What user journey does this system own end-to-end?
[ ] What is explicitly OUT of scope for v1?
[ ] What is the business event if this system is down for 1 hour? 4 hours? 24 hours?
[ ] Who is the executive sponsor and what decision are they waiting on?
[ ] What is the launch deadline — hard (regulatory) or soft (market window)?
[ ] Are there contractual SLAs with customers that constrain the design?
[ ] What is the cost of delay vs cost of over-engineering?
[ ] Is this greenfield, brownfield replacement, or incremental extraction?
```

### Users & Access Patterns

```
[ ] Who are the callers — humans, services, batch jobs, third parties?
[ ] What is the read:write ratio for the primary data path?
[ ] What are peak vs average QPS? What event causes 10× spikes?
[ ] What geographic distribution do users have (single region vs global)?
[ ] Are there mobile/offline/low-bandwidth clients with different needs?
[ ] What is the acceptable staleness for reads (seconds, minutes, hours)?
```

### Data & Consistency

```
[ ] What data is authoritative — and where does truth live?
[ ] Which operations require linearizable consistency vs eventual?
[ ] What is the retention policy (hot, warm, cold, legal hold)?
[ ] Are there GDPR/CCPA deletion requirements with propagation SLAs?
[ ] What is the maximum acceptable data loss window (RPO)?
[ ] Can the system tolerate duplicate processing (idempotency requirement)?
```

### Dependencies & Constraints

```
[ ] What existing systems MUST this integrate with (non-negotiable)?
[ ] What team owns each dependency — and what is their SLO?
[ ] Are there technology mandates (cloud, language, data store)?
[ ] Are there compliance frameworks (SOC2, PCI, HIPAA, FedRAMP)?
[ ] What is the team size and operational maturity for day-2 ops?
[ ] Is multi-tenancy required? What is the isolation model?
```

### Success Criteria

```
[ ] What does "done" look like for v1 — measurable, not aspirational?
[ ] What are the top 3 non-functional requirements with numeric targets?
[ ] What is the single hardest requirement (the design driver)?
[ ] How will we know the system is working in production (SLIs)?
[ ] What is the rollback trigger — what metric says "abort launch"?
```

---

## Section 2: Capacity Planning Checklist

```
╔════════════════════════════════════════════════════════════════════╗
║   CAPACITY PLANNING — BLOCK if math is missing                     ║
╚════════════════════════════════════════════════════════════════════╝

[ ] QPS estimated for read, write, and background jobs (peak and sustained)
[ ] Storage calculated: raw data × replication factor × growth horizon
[ ] Bandwidth estimated: ingress + egress + cross-AZ replication
[ ] Memory/cache sizing justified against working set, not "we'll use Redis"
[ ] Connection pool limits calculated (DB, HTTP, message broker)
[ ] Message queue throughput and consumer lag budget defined
[ ] Search/index size estimated separately from primary storage
[ ] Growth rate applied (3× over 18 months is a common planning horizon)
[ ] Headroom factor stated (typically 2–3× on peak for burst absorption)
[ ] Bottleneck identified: CPU, memory, disk IOPS, network, or lock contention
[ ] Scaling trigger defined: at what metric do we add capacity?
[ ] Cost projection tied to capacity (not hand-waved as "cloud scales")
[ ] Load test plan references these numbers as pass/fail criteria
[ ] Cold start / empty cache scenario modeled (worst-case latency)
[ ] Backfill/reindex job capacity does not starve live traffic
```

### Capacity Math Template

```
┌───────────────────────────────────────────────────────────────────┐
│  CAPACITY WORKSHEET (fill in design doc)                          │
├───────────────────────────────────────────────────────────────────┤
│  Peak QPS (writes):        _______  × 3 headroom = _______        │
│  Peak QPS (reads):         _______  × 3 headroom = _______        │
│  Avg payload size:         _______ bytes                          │
│  Daily new data:           _______ GB  × 365 × 3yr = _______ TB   │
│  Replication factor:       _______  → total storage = _______ TB  │
│  Cache working set:        _______ GB  (___% of hot data)         │
│  DB connections needed:    _______  (QPS × latency / concurrency) │
│  Monthly infra cost est:   $_______  (linked spreadsheet)         │
└───────────────────────────────────────────────────────────────────┘
```

---

## Section 3: Reliability Checklist

### SLOs & Error Budgets

```
[ ] SLIs defined from user journeys — not from /healthz endpoints
[ ] SLO targets tiered by service criticality (Tier 0/1/2/3)
[ ] Error budget computed in minutes/requests per measurement window
[ ] Error budget policy documented: what happens at 50%, 75%, 100% consumed
[ ] SLAs (external) are looser than SLOs (internal) — gap is intentional
[ ] Latency SLO includes tail (p99 or p999), not just median
[ ] Freshness SLI defined for async/cached paths
[ ] Quality SLI defined where degraded mode is acceptable (e.g., fallback)
[ ] SLO dashboard exists or is planned before launch
[ ] Burn-rate alerts configured (multi-window: 1h, 6h, 24h, 72h)
```

### High Availability

```
[ ] Single points of failure identified and eliminated or accepted with ADR
[ ] Multi-AZ deployment for Tier 0/1 services
[ ] Health checks distinguish "process up" from "serving correctly"
[ ] Graceful degradation path documented for each dependency failure
[ ] Circuit breakers on all synchronous cross-service calls
[ ] Timeouts and retry budgets set (no unbounded retries)
[ ] Bulkhead isolation: failure in one tenant/queue doesn't flood others
[ ] Load shedding strategy when at capacity (429/503 with retry-after)
[ ] Chaos/failure injection plan for pre-launch validation
[ ] Dependency failure modes tested (not just happy path)
```

### Disaster Recovery

```
[ ] RTO (Recovery Time Objective) defined and achievable
[ ] RPO (Recovery Point Objective) defined and tested
[ ] Backup frequency and restore procedure documented with RTO proof
[ ] Cross-region failover strategy for Tier 0 (active-active vs active-passive)
[ ] Runbook for region loss exists and has been drilled
[ ] Data replication lag monitored and alerted
[ ] Failover does not require manual steps that take > RTO
[ ] Split-brain prevention mechanism documented
[ ] DR test scheduled within 90 days of launch
```

---

## Section 4: Security Checklist

```
[ ] Threat model completed (STRIDE or equivalent) — linked in design doc
[ ] Authentication mechanism defined for every entry point
[ ] Authorization model defined (RBAC, ABAC, or resource-level)
[ ] Principle of least privilege for service accounts and IAM roles
[ ] Secrets management: no secrets in code, env vars, or config repos
[ ] Encryption in transit (TLS 1.2+) for all external and internal hops
[ ] Encryption at rest for PII, credentials, and payment data
[ ] Input validation at trust boundaries (API gateway + service)
[ ] Rate limiting and abuse protection on public endpoints
[ ] Audit logging for security-relevant events (auth, admin, data access)
[ ] Blast radius analysis: what does compromise of this service expose?
[ ] Dependency vulnerability scanning in CI pipeline
[ ] Network segmentation: private subnets, security groups, no public DBs
[ ] Supply chain: pinned dependencies, signed artifacts, SBOM
[ ] Incident response contact and escalation for security events
```

---

## Section 5: Operability Checklist

```
[ ] Structured logging with correlation IDs across service boundaries
[ ] Metrics: RED (Rate, Errors, Duration) for every service
[ ] Distributed tracing on critical paths (sample rate defined)
[ ] Dashboards for SLO, capacity, and dependency health
[ ] Alerts page on symptom (SLO burn), ticket on cause (CPU high)
[ ] Every alert has a runbook link — no orphan pages
[ ] Runbooks cover: deploy, rollback, scale, common failures, escalation
[ ] Feature flags for risky changes (kill switch without redeploy)
[ ] Config externalized — no config baked into images
[ ] Deployment strategy documented (rolling, blue-green, canary)
[ ] Rollback tested and completes within defined SLO impact window
[ ] On-call rotation staffed before launch
[ ] Escalation path defined (L1 → L2 → service owner → exec)
[ ] Debug endpoints gated (not public) or removed in production
[ ] Log retention and PII redaction policy documented
```

---

## Section 6: Cost Checklist

```
[ ] Cost model spreadsheet linked (compute, storage, network, managed services)
[ ] Cost per transaction/request calculated at expected scale
[ ] Cost at 10× scale projected — does architecture still make sense?
[ ] Reserved vs on-demand vs spot strategy documented
[ ] Data egress costs modeled (cross-region, CDN, API responses)
[ ] Idle resource cost identified (dev/staging parity vs cost)
[ ] Cost attribution tags defined for chargeback/showback
[ ] Cost anomaly alerting configured
[ ] Cheaper alternatives considered and rejected with reasoning (ADR)
[ ] FinOps review scheduled for systems > $10K/month projected
```

---

## Section 7: Migration & Evolution Checklist

```
[ ] Current state documented (what exists today, what pain it causes)
[ ] Target state clearly differentiated from current state
[ ] Migration strategy chosen: strangler fig, dual-write, big-bang, or shadow
[ ] Data migration plan: schema mapping, validation, reconciliation
[ ] Cutover criteria defined (metric thresholds, not calendar dates)
[ ] Rollback plan for migration (not just for launch)
[ ] Dual-run period defined with comparison/validation tooling
[ ] Traffic shifting mechanism (DNS, feature flag, weighted routing)
[ ] Backward compatibility during transition period
[ ] Deprecation timeline for old system documented
[ ] Team training plan for new operational model
[ ] ADRs for irreversible decisions (database choice, partition key)
[ ] API versioning strategy for consumers during migration
```

---

## Section 8: Failure Mode Analysis Checklist

Every Tier 0/1 design must enumerate failure modes before sign-off. This is not optional at principal level.

```
[ ] Failure mode table completed: component × failure × detection × mitigation
[ ] Cascading failure paths traced (retry storm, cache stampede, split brain)
[ ] Partial failure modes: degraded vs hard-down behavior defined
[ ] Dependency timeout values sum to less than client-facing timeout
[ ] Retry budget prevents amplification (max 2 retries with jitter)
[ ] Bulkhead prevents one tenant/queue from exhausting shared pool
[ ] Data corruption scenarios: duplicate writes, lost writes, ordering violations
[ ] Split-brain and network partition behavior documented
[ ] Human operational failures: wrong config, wrong region, fat-finger deploy
[ ] Game day or failure injection planned for top 3 failure modes
```

### Failure Mode Table Template

```
┌─────────────┬──────────────┬─────────────────┬──────────────────────┐
│  Component  │  Failure     │  Detection      │  Mitigation          │
├─────────────┼──────────────┼─────────────────┼──────────────────────┤
│  Primary DB │  AZ loss     │  Health + lag   │  Auto failover < 60s │
│  Cache      │  Full miss   │  Hit rate drop  │  Circuit to DB; shed │
│  Queue      │  Consumer lag│  Depth alert    │  Scale consumers     │
│  External   │  503 timeout │  Dep error SLI  │  Fallback + breaker  │
└─────────────┴──────────────┴─────────────────┴──────────────────────┘
```

---

## Section 9: Cross-Curriculum Integration Map

```
╔════════════════════════════════════════════════════════════════════╗
║   PRIOR MODULE              │  PRINCIPAL DESIGN CONNECTION         ║
╠════════════════════════════════════════════════════════════════════╣
║  Week 3: CAP / Consistency  │ Pick consistency model BEFORE        ║
║                               │ storage choice; document trade-off ║
╠════════════════════════════════════════════════════════════════════╣
║  Week 6: Saga / Outbox      │ Distributed tx boundary = design     ║
║                               │ driver for payment/order flows     ║
╠════════════════════════════════════════════════════════════════════╣
║  Week 7: Rate Limiting      │ Abuse protection at edge AND         ║
║                               │ service; include in capacity math  ║
╠════════════════════════════════════════════════════════════════════╣
║  Week 8: SLOs / Error Budget│ Every Tier 0 design ships with       ║
║                               │ SLIs, burn alerts, budget policy   ║
╠════════════════════════════════════════════════════════════════════╣
║  Week 13: Kafka / KV Store  │ Reference architectures for          ║
║                               │ messaging and storage depth        ║
╠════════════════════════════════════════════════════════════════════╣
║  Week 15: Interview Rubric  │ Same 8 dimensions — this checklist   ║
║                               │ is the production gate on top      ║
╚════════════════════════════════════════════════════════════════════╝
```

---

## Section 10: Principal-Level Sign-Off Criteria

All criteria must pass for unconditional approval. Conditional approval requires explicit remediation items with owners and dates.

```
╔═════════════════════════════════════════════════════════════════════╗
║   SIGN-OFF GATE — ALL MUST PASS FOR UNCONDITIONAL APPROVAL          ║
╠═════════════════════════════════════════════════════════════════════╣
║                                                                     ║
║   [ ] BLOCK: Capacity math present and reviewed                     ║
║   [ ] BLOCK: SLOs defined with error budget policy                  ║
║   [ ] BLOCK: No unmitigated single points of failure on Tier 0      ║
║   [ ] BLOCK: Security threat model reviewed by security team        ║
║   [ ] BLOCK: Runbooks exist for deploy, rollback, and top-3 failures║
║   [ ] BLOCK: Rollback tested in staging/pre-prod                    ║
║   [ ] BLOCK: Migration/rollback plan if replacing existing system   ║
║   [ ] BLOCK: On-call rotation staffed and trained                   ║
║   [ ] BLOCK: Cost model reviewed and within budget envelope         ║
║   [ ] BLOCK: Load test passed against capacity targets              ║
║                                                                     ║
╠═════════════════════════════════════════════════════════════════════╣
║   REVIEWER SIGN-OFF                                                 ║
╠═════════════════════════════════════════════════════════════════════╣
║   Design author:     _________________  Date: _______               ║
║   Primary reviewer:  _________________  Date: _______               ║
║   Security reviewer: _________________  Date: _______               ║
║   SRE reviewer:      _________________  Date: _______               ║
║                                                                     ║
║   Decision:  [ ] Approve  [ ] Conditional  [ ] Reject               ║
║   Conditions (if any): _________________________________________    ║
╚═════════════════════════════════════════════════════════════════════╝
```

---

## Good vs Bad: Design Review Comments

### Good Review Comments

```
✓ "Capacity section missing cross-AZ replication bandwidth. At 50K writes/s
   × 1KB × 3 replicas = 150 MB/s — confirm network headroom on db.r6g.4xlarge."

✓ "SLO says 99.9% but no error budget policy. Add: freeze deploys at 75%
   consumed; postmortem required at 100%."

✓ "Payment path has no idempotency key. Duplicate POST on retry will double-charge.
   Require Idempotency-Key header with 24h dedup window."

✓ "Conditional approve: resolve dual-write reconciliation gap before cutover.
   Owner: @alice, due: 2026-03-15."
```

### Bad Review Comments

```
✗ "Looks good overall." — No actionable feedback; approves without evidence.

✗ "Have you considered Kafka?" — Technology suggestion without trade-off analysis.

✗ "Needs more scalability." — Vague; no specific bottleneck or number.

✗ "Security team should review." — Delegates without identifying specific gaps.

✗ "Why not microservices?" — Style preference, not production requirement.
```

---

## Self-Assessment Protocol

After completing a design doc, score yourself before requesting review:

```
1. Pre-design: Did I answer all 20+ questions with written evidence?
2. Capacity: Can I redo the math from memory in 5 minutes?
3. Reliability: Are SLOs tied to user journeys with error budget policy?
4. Security: Is there a threat model entry for every trust boundary?
5. Operability: Could on-call resolve top-3 failures without calling me?
6. Cost: Is there a spreadsheet, not a sentence?
7. Migration: Is cutover + rollback described step-by-step?
8. Failure modes: Are there ≥ 5 modes with detection AND mitigation?
9. Sign-off: Would I stake my on-call rotation on this design?
10. Principal bar: Would I approve this if someone else authored it?
```

If any answer is "no" — fix before submitting. Reviewers should not be your first quality gate.

---

## Key Takeaways

```
1. Pre-design questions prevent wrong-architecture rework — invest 30 minutes
   before drawing boxes.

2. Capacity math is not optional. "Cloud auto-scales" is not a capacity plan.

3. Reliability = SLOs + error budgets + tested DR — not "we have 3 AZs."

4. Operability is designed in: runbooks, alerts, and rollback are launch blockers.

5. Principal sign-off means evidence, not consensus. Every BLOCK item must
   pass or ship with explicit risk acceptance signed by an exec.
```

---

## Targeted Reading

```
→ Google SRE Book, Ch 4 (SLOs), Ch 7 (Launch), Ch 14 (Capacity Planning)
→ "Designing Data-Intensive Applications" (Kleppmann) — consistency, replication
→ Week 8: SLOs, SLIs, Error Budgets and Alerting (this curriculum)
→ Week 15: Interview Rubric — same dimensions, production lens
→ AWS Well-Architected Framework — Operational Excellence, Reliability, Security
```
