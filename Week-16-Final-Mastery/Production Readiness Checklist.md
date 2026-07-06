# Production Readiness Checklist — Final Mastery

> Production readiness review (PRR) is the final gate before customer traffic. This checklist covers pre-launch validation, monitoring, runbooks, load testing, rollback, on-call, launch day execution, and post-launch 30/60/90-day reviews. No Tier 0 or Tier 1 system ships without passing every BLOCK item.

---

## Learning Objectives

```
╔══════════════════════════════════════════════════════════════════════╗
║   AFTER THIS CHECKLIST, YOU WILL BE ABLE TO:                         ║
╟──────────────────────────────────────────────────────────────────────╢
║                                                                      ║
║   1. Execute a production readiness review with 50+ concrete         ║
║      pass/fail items — not a subjective "feels ready"                ║
║                                                                      ║
║   2. Validate monitoring, alerting, and runbook completeness         ║
║      before launch — not after the first page                        ║
║                                                                      ║
║   3. Define load test pass criteria and rollback triggers            ║
║      tied to SLO metrics, not gut feel                               ║
║                                                                      ║
║   4. Run launch day and post-launch reviews (30/60/90) with          ║
║      structured checklists that catch drift and debt                 ║
║                                                                      ║
║   5. Staff and train on-call before traffic — with escalation        ║
║      paths tested, not documented in theory only                     ║
╚══════════════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔═══════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Staging passed — we're ready for prod"            ║
╟───────────────────────────────────────────────────────────────────────╢
║   WRONG. Staging lacks prod traffic shape, data volume, and           ║
║   failure modes. PRR validates prod-specific readiness.               ║
╠═══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "We'll add alerts after launch"                    ║
╟───────────────────────────────────────────────────────────────────────╢
║   WRONG. Launch without symptom-based alerts = flying blind.          ║
║   First customer impact becomes your detection mechanism.             ║
╠═══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "Rollback plan = redeploy previous version"        ║
╟───────────────────────────────────────────────────────────────────────╢
║   INCOMPLETE. Rollback must handle schema migrations, feature         ║
║   flags, cache invalidation, and async message compatibility.         ║
╠═══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "Soft launch = no PRR needed"                      ║
╟───────────────────────────────────────────────────────────────────────╢
║   WRONG. 1% of prod traffic on an unmonitored system still            ║
║   burns error budget and can cause data corruption.                   ║
╠═══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Launch day is the finish line"                    ║
╟───────────────────────────────────────────────────────────────────────╢
║   WRONG. 30/60/90-day reviews catch config drift, cost overrun,       ║
║   and action item rot from architecture and incident reviews.         ║
╚═══════════════════════════════════════════════════════════════════════╝
```

---

## How to Use This Checklist

```
╔══════════════════════════════════════════════════════════════════════╗
║   WHEN TO RUN PRR                                                    ║
╟──────────────────────────────────────────────────────────────────────╢
║   • 2–4 weeks before planned launch (time to fix BLOCK items)        ║
║   • After major architecture change on live system                   ║
║   • Before increasing traffic tier (beta → GA, 1% → 100%)            ║
╠══════════════════════════════════════════════════════════════════════╣
║   WHO PARTICIPATES                                                   ║
╟──────────────────────────────────────────────────────────────────────╢
║   Service owner (author), SRE reviewer, security (Tier 0/1),         ║
║   on-call primary, product owner for launch criteria                 ║
╠══════════════════════════════════════════════════════════════════════╣
║   PASS CRITERIA                                                      ║
╟──────────────────────────────────────────────────────────────────────╢
║   All [BLOCK] items pass. [MAJOR] items pass or have signed          ║
║   risk acceptance with remediation date. [MINOR] can slip to 30-day. ║
╚══════════════════════════════════════════════════════════════════════╝
```

---

## Section 1: Pre-Launch Checklist (50+ Items)

### Architecture & Design

```
[ ] BLOCK: Architecture review approved (unconditional or conditions met)
[ ] BLOCK: Design doc current — reflects what was actually built
[ ] BLOCK: All accepted SPOFs documented with runbooks
[ ] ADRs complete for irreversible decisions
[ ] Dependency list current with owner contacts
[ ] Data flow diagrams match implementation
[ ] Feature flags for all risky / new code paths
[ ] Kill switch tested — disable feature without redeploy
[ ] Multi-tenancy isolation verified if applicable
[ ] API versioning in place for external consumers
```

### Code & Build

```
[ ] BLOCK: Code review complete for all launch-scope changes
[ ] BLOCK: No known P0/P1 bugs open in launch scope
[ ] CI pipeline green: unit, integration, contract tests
[ ] Static analysis / linter gates passing
[ ] Dependency vulnerability scan — no critical CVEs unmitigated
[ ] Secrets not in source code (verified by scan)
[ ] Build reproducible; artifact signed and pinned by digest
[ ] Rollback artifact available (previous N versions)
[ ] Database migration scripts idempotent and reversible (or forward-only ADR)
[ ] Config schema validated at startup — fail fast on bad config
```

### Infrastructure

```
[ ] BLOCK: Production environment provisioned via IaC (Terraform/CDK/etc.)
[ ] BLOCK: Multi-AZ for Tier 0/1 compute and data
[ ] Resource limits set (CPU, memory, pod count, connection pools)
[ ] Auto-scaling policies configured and tested
[ ] Network: private subnets, security groups, no public database endpoints
[ ] TLS certificates valid; auto-renewal configured
[ ] DNS records configured with appropriate TTL for cutover
[ ] CDN / WAF configured for public endpoints
[ ] Backup jobs scheduled and restore tested
[ ] DR failover tested or scheduled within 90 days of launch
[ ] Cost tags applied for attribution
[ ] Quota limits checked (AWS service limits, API rate caps)
```

### Data

```
[ ] BLOCK: Schema migration tested on prod-sized dataset in staging
[ ] BLOCK: Backup and point-in-time recovery verified
[ ] Data retention and deletion policies implemented
[ ] PII encrypted at rest; access logged
[ ] Partition / shard key validated against prod traffic shape
[ ] Index strategy validated — no full table scans on hot paths
[ ] Cache warming plan for cold start
[ ] Seed data / reference data loaded and verified
[ ] Reconciliation job for dual-write migration if applicable
[ ] GDPR/CCPA deletion path tested end-to-end
```

### Security

```
[ ] BLOCK: Threat model reviewed; findings remediated or accepted
[ ] BLOCK: Pen test complete for Tier 0 (or scheduled within 30 days with risk accept)
[ ] Authentication enforced on all endpoints
[ ] Authorization tested: horizontal and vertical privilege escalation
[ ] Rate limiting on public and authenticated endpoints
[ ] Audit logging for admin and sensitive data access
[ ] IAM least privilege for service accounts
[ ] Security incident contact in runbook
[ ] Bug bounty / vulnerability disclosure path documented
```

### Testing

```
[ ] BLOCK: Load test passed against capacity targets (see Section 4)
[ ] BLOCK: Failure injection / chaos test on critical path
[ ] Integration tests cover top 5 user journeys
[ ] Contract tests for all external API consumers/providers
[ ] Soak test: sustained load for ≥ 4 hours without memory leak
[ ] Rollback tested in staging/pre-prod (see Section 5)
[ ] Synthetic monitoring probes configured and passing
[ ] Canary deployment tested in staging
[ ] Browser / client compatibility verified for user-facing UI
[ ] Accessibility requirements met if applicable
```

### Documentation & Process

```
[ ] BLOCK: Runbooks complete (see Section 3)
[ ] On-call playbook linked in PagerDuty / ops wiki
[ ] Launch plan document with timeline and owners
[ ] Rollback plan document with triggers (see Section 5)
[ ] Communication plan: status page, support macros, exec contacts
[ ] Change management ticket / CAB approval if required
[ ] Legal / compliance sign-off if regulated data
[ ] Customer documentation / API docs published
[ ] Internal training for support team complete
```

### Organization & Launch Criteria

```
[ ] BLOCK: On-call rotation staffed and trained (see Section 6)
[ ] Product owner sign-off on launch scope
[ ] Engineering manager sign-off on readiness
[ ] SRE sign-off on operability
[ ] Launch criteria defined: metrics that must hold for 24h to call success
[ ] Rollback criteria defined: metrics that trigger abort (see Section 5)
[ ] Hypercare period scheduled (elevated staffing post-launch)
[ ] Post-launch review dates booked (30/60/90 day)
```

---

## Section 2: Monitoring and Alerting Readiness

### Metrics (RED + USE)

```
[ ] BLOCK: Rate (requests/s) per service and endpoint
[ ] BLOCK: Errors (4xx, 5xx) by type and endpoint
[ ] BLOCK: Duration (p50, p95, p99) per endpoint
[ ] Utilization: CPU, memory, disk, connection pool saturation
[ ] Saturation: queue depth, thread pool, DB connections
[ ] Business metrics: orders/min, signups, revenue proxy
[ ] Dependency metrics: per-downstream latency and error rate
[ ] Infrastructure: pod restarts, OOM kills, eviction events
[ ] SLO dashboard live with SLI calculations correct
[ ] Error budget remaining visible to team
```

### Logging & Tracing

```
[ ] Structured JSON logs with: timestamp, level, service, trace_id, request_id
[ ] Log levels appropriate (no DEBUG in prod by default)
[ ] PII redaction in logs verified
[ ] Log aggregation pipeline delivering (ELK, CloudWatch, etc.)
[ ] Log retention meets compliance and debug needs
[ ] Distributed tracing on critical paths (sample rate ≥ 1% or tail-based)
[ ] Trace retention sufficient for incident investigation
[ ] Correlation ID propagated across all service hops
```

### Alerting

```
[ ] BLOCK: SLO burn-rate alerts configured (multi-window)
[ ] BLOCK: Every page alert has runbook link
[ ] BLOCK: Alert routes to correct on-call rotation
[ ] No alert fires in steady state (7-day burn-in in staging/pre-prod)
[ ] Symptom alerts page; cause alerts ticket
[ ] Alert severity matches incident severity definitions
[ ] Escalation policy tested (PagerDuty/Opsgenie schedule)
[ ] Alert noise budget: < 2 pages/week in steady state target
[ ] Synthetic check failures page within 5 minutes
[ ] Dead man's switch for critical batch jobs
[ ] Dashboard URLs in runbooks and PagerDuty notes
```

---

## Section 3: Runbook Requirements

Every runbook must include all sections below. One runbook per alert is ideal.

```
RUNBOOK TEMPLATE CHECKLIST:
[ ] Service overview: what it does, tier, owner team
[ ] Architecture diagram link
[ ] Dependencies list with escalation contacts
[ ] SLO targets and dashboard link
[ ] Common alerts: symptom → likely cause → fix steps
[ ] Deploy procedure: step-by-step with rollback reference
[ ] Rollback procedure: step-by-step with verification
[ ] Scale procedure: manual and auto-scaling triggers
[ ] Failover procedure (if multi-region)
[ ] Data repair procedure (if applicable)
[ ] Escalation path: L1 → L2 → service owner → exec
[ ] Communication template for customer impact
[ ] Last tested date and tester name
```

### Required Runbooks (Minimum Set)

```
[ ] BLOCK: Deploy and rollback
[ ] BLOCK: Scale up / scale down
[ ] BLOCK: Top 3 alert responses (from most likely pages)
[ ] BLOCK: Database failover or restore
[ ] BLOCK: Dependency outage (fallback activation)
[ ] Security incident response contact
[ ] Data corruption detection and quarantine
[ ] Feature flag kill switch activation
```

---

## Section 4: Load Testing Criteria

```
╔══════════════════════════════════════════════════════════════════════╗
║   LOAD TEST PASS CRITERIA — ALL MUST PASS                            ║
╠══════════════════════════════════════════════════════════════════════╣
║   Environment: pre-prod with prod-equivalent instance sizes          ║
║   Duration: ≥ 1 hour at peak; ≥ 4 hours soak at 70% peak             ║
╚══════════════════════════════════════════════════════════════════════╝

[ ] Peak load: ___ QPS (from capacity plan) sustained 60 min
[ ] Spike load: 3× peak for 15 min — system recovers without manual intervention
[ ] p99 latency ≤ ___ ms at peak (SLO target)
[ ] Error rate ≤ ___% at peak (SLO target)
[ ] No memory leak: memory stable over 4-hour soak
[ ] No connection leak: pool utilization stable over soak
[ ] Database CPU ≤ 70% at peak; replication lag < ___ ms
[ ] Cache hit rate ≥ ___% at steady state
[ ] Auto-scaling triggered and completed within ___ min
[ ] Cost at peak within ___% of model projection
[ ] Results documented with graphs linked in PRR ticket
[ ] Bottleneck identified and within acceptable headroom
```

### Load Test Anti-Patterns

```
✗ Testing against mock dependencies that don't simulate latency/failures
✗ Single-shot spike with no sustained period
✗ Testing at 10% of projected peak and calling it "validated"
✗ No pass/fail criteria defined before test — moving goalposts after
✗ Load test from single client IP — doesn't exercise connection limits fairly
```

---

## Section 5: Rollback Plan

```
[ ] BLOCK: Rollback procedure documented and tested in pre-prod
[ ] BLOCK: Rollback completes within ___ min (defined per tier)
[ ] BLOCK: Rollback triggers defined before launch (automatic or manual)

ROLLBACK TRIGGERS (define numeric thresholds):
[ ] Error rate > ___% for ___ minutes post-launch
[ ] p99 latency > ___ ms for ___ minutes
[ ] SLO burn rate > ___× for ___ minutes
[ ] Synthetic check failure > ___ consecutive probes
[ ] Manual trigger: IC or service owner authority

ROLLBACK PROCEDURE CHECKLIST:
[ ] Previous version artifact identified and deployable
[ ] Database: backward compatible OR forward-only migration with ADR
[ ] Feature flags: disable new paths without redeploy
[ ] Cache: invalidation or TTL strategy on rollback
[ ] Message schema: consumers handle previous version messages
[ ] Config: previous config version restorable
[ ] DNS / traffic shift: revert weight or route
[ ] Verification: synthetics pass, error rate normal, SLO green
[ ] Communication: status page and internal notification template
[ ] Post-rollback: incident declared if customer impact occurred
```

---

## Section 6: On-Call Readiness

```
[ ] BLOCK: Primary and secondary on-call assigned for launch window
[ ] BLOCK: On-call rotation staffed for ≥ 4 weeks post-launch
[ ] BLOCK: PagerDuty/Opsgenie schedule live and tested
[ ] On-call engineer completed service orientation (architecture walkthrough)
[ ] On-call engineer has access: logs, metrics, deploy, feature flags, DB read
[ ] Escalation policy tested — page routes to human within 5 min
[ ] Runbooks reviewed by on-call primary — questions resolved
[ ] Game day or shadow incident completed in last 30 days
[ ] Handoff document for launch week hypercare
[ ] Manager backup identified if primary unavailable
[ ] On-call compensation / time-off policy communicated
[ ] "No deploy Friday" or change freeze policy communicated for launch week
```

---

## Section 7: Launch Day Checklist

### T-24 Hours

```
[ ] Launch go/no-go meeting completed; all BLOCK items green
[ ] Rollback procedure reviewed by deploy engineer
[ ] On-call primary and secondary confirmed available
[ ] Hypercare staffing confirmed (war room optional for Tier 0)
[ ] Status page draft prepared (not published)
[ ] Support team briefed with FAQ and escalation path
[ ] Change ticket approved; deploy window confirmed
[ ] Communication to stakeholders: launch time, contact, rollback criteria
```

### T-0: Deploy

```
[ ] Deploy started in change window
[ ] Canary / blue-green: 1% → 5% → 25% → 100% with soak between stages
[ ] Each stage: error rate, latency, synthetics checked before proceeding
[ ] Deploy engineer and IC monitoring dashboards live
[ ] No unrelated changes in flight (change freeze active)
[ ] Database migrations complete and verified before traffic shift
[ ] Feature flags: new paths enabled incrementally
[ ] Rollback trigger thresholds actively monitored
```

### T+1 Hour to T+24 Hours

```
[ ] SLO dashboard green for 1 hour before calling canary success
[ ] No unplanned pages; any page investigated and resolved
[ ] Business metrics nominal (conversion, signup, etc.)
[ ] Log volume and cost within expected bounds
[ ] Customer support ticket volume normal — no spike in errors
[ ] Status page: Resolved or no publication needed
[ ] Launch retrospective scheduled (within 48 hours)
[ ] Hypercare continues per plan (typically 48–72 hours Tier 0)
[ ] Error budget consumption documented
[ ] Launch declared success OR rollback executed per triggers
```

---

## Section 8: Post-Launch Reviews (30 / 60 / 90 Day)

### 30-Day Review

```
[ ] SLO attainment: met / missed — error budget consumed ___
[ ] Incident count and severity since launch
[ ] All launch PIR action items status
[ ] Alert noise: pages per week; runbook gaps identified
[ ] Cost vs model: within ___%; anomalies explained
[ ] Performance vs load test: prod traffic shape differences
[ ] Customer feedback / support ticket themes
[ ] Technical debt incurred for launch — prioritized backlog
[ ] On-call feedback: runbook accuracy, access gaps
[ ] Security: any findings from post-launch scan
[ ] Decision: continue scaling traffic / hold / remediate
```

### 60-Day Review

```
[ ] SLO trend: improving / stable / degrading
[ ] Capacity headroom: ___% until next scaling event
[ ] DR drill completed or scheduled
[ ] Dependency SLO breaches affecting composite
[ ] MAJOR items from architecture review — closed or status
[ ] Cost optimization opportunities identified
[ ] Autoscaling tuning based on prod patterns
[ ] Runbook updates from incidents applied
[ ] Team bus factor: cross-training progress
[ ] Feature flag debt: flags that should be removed
```

### 90-Day Review

```
[ ] Quarterly SLO review with product — targets still appropriate
[ ] Error budget policy retrospective: deploy freezes triggered?
[ ] Architecture drift: design doc vs reality — update needed?
[ ] Migration complete (if applicable): old system decommissioned?
[ ] Pen test / security review cycle complete
[ ] Load test repeated at current traffic + projected growth
[ ] On-call rotation sustainable — burnout signals checked
[ ] 90-day action items from prior reviews closed
[ ] Next quarter reliability investments prioritized
[ ] PRR checklist archived with lessons learned for next launch
```

### Post-Launch Review Template

```
╔═════════════════════════════════════════════════════════════════════╗
║   POST-LAUNCH REVIEW — ___ DAY                                      ║
╠═════════════════════════════════════════════════════════════════════╣
║   Service: ___________________  Tier: ___  Launch date: ________    ║
║   Review date: __________  Facilitator: _________________________   ║
╠═════════════════════════════════════════════════════════════════════╣
║   SLO attainment (30d):  ___%   Error budget remaining: ___%        ║
║   Incidents: SEV1 ___  SEV2 ___  SEV3 ___                           ║
║   Cost vs model: ___%   Pages/week: ___                             ║
╠═════════════════════════════════════════════════════════════════════╣
║   WENT WELL:                                                        ║
║   • _____________________________________________________________   ║
║   WENT POORLY:                                                      ║
║   • _____________________________________________________________   ║
║   ACTION ITEMS:                                                     ║
║   • _____________________________________________________________   ║
╚═════════════════════════════════════════════════════════════════════╝
```

---

## Good vs Bad: Production Readiness

### Good PRR Outcomes

```
✓ "Load test at 12K QPS: p99 180ms, error 0.02%. Pass criteria 200ms/0.1%.
   Bottleneck: Redis connection pool at 85% — acceptable with 2× headroom."

✓ "Rollback tested: v2.2.0 → v2.1.9 in 8 min including DB compat check.
   Trigger: error rate > 1% for 5 min — automated canary rollback configured."

✓ "Conditional PRR: pen test scheduled 3/20. Risk acceptance signed by CISO
   for limited beta (internal users only) until complete."
```

### Bad PRR Outcomes

```
✗ "Staging looks good." — No load test evidence, no numbers.

✗ "We'll monitor closely after launch." — Alerts not configured.

✗ "Rollback is just redeploy." — Schema migration incompatibility not addressed.

✗ "On-call TBD." — Rotation not staffed at launch.

✗ Approving with 8 open BLOCK items and no risk acceptance document.
```

---

## PRR Sign-Off

```
╔═════════════════════════════════════════════════════════════════════╗
║   PRODUCTION READINESS SIGN-OFF                                     ║
╠═════════════════════════════════════════════════════════════════════╣
║   Service: _________________________  Tier: _____  Launch: ______   ║
║                                                                     ║
║   [ ] BLOCK: All BLOCK items pass                                   ║
║   [ ] BLOCK: Load test passed with evidence                         ║
║   [ ] BLOCK: Rollback tested                                        ║
║   [ ] BLOCK: Alerts and runbooks live                               ║
║   [ ] BLOCK: On-call staffed                                        ║
║                                                                     ║
║   Service owner:  _________________  Date: _______                  ║
║   SRE reviewer:   _________________  Date: _______                  ║
║   Product owner:  _________________  Date: _______                  ║
║                                                                     ║
║   Decision: [ ] GO  [ ] NO-GO  [ ] Conditional GO                   ║
╚═════════════════════════════════════════════════════════════════════╝
```

---

## Key Takeaways

```
1. 50+ pre-launch items exist because each maps to a real launch failure mode.
   "Feels ready" is not a gate.

2. Monitoring and runbooks are launch blockers — not post-launch todos.

3. Load test with pass/fail numbers; rollback with tested procedure and triggers.

4. Launch day is scripted: canary stages, soak periods, numeric abort criteria.

5. 30/60/90-day reviews catch drift. Launch is the starting line, not the finish.
```

---

## Targeted Reading

```
→ Google SRE Book, Ch 27 (Launch Checklist), Ch 7 (Learning from Failure)
→ AWS Well-Architected Operational Excellence Pillar
→ Launch Darkly / feature flag patterns — kill switches and progressive delivery
→ Week 7: Feature Flags and Progressive Delivery (this curriculum)
→ Week 8: SLOs, SLIs, Error Budgets — launch criteria and rollback triggers
→ Week 16: Principal SRE System Design Checklist — upstream design gate
```
