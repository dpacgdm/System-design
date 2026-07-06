# Incident Review Checklist — Final Mastery

> Incidents are inevitable. How you respond in the first 15 minutes — and how you learn afterward — separates mature operations from recurring outages. This checklist covers triage through blameless postmortem and action item quality. Use it during live incidents and within 48 hours after resolution.

---

## Learning Objectives

```
╔════════════════════════════════════════════════════════════════════╗
║   AFTER THIS CHECKLIST, YOU WILL BE ABLE TO:                       ║
╟────────────────────────────────────────────────────────────────────╢
║                                                                    ║
║   1. Execute a structured first-15-minutes triage — not panic      ║
║      or premature root-cause chasing                               ║
║                                                                    ║
║   2. Separate mitigation (restore service) from root cause         ║
║      (prevent recurrence) and communicate both clearly             ║
║                                                                    ║
║   3. Run a blameless post-incident review that produces            ║
║      durable fixes — not "be more careful" action items            ║
║                                                                    ║
║   4. Write action items that pass quality criteria: specific,      ║
║      owned, dated, and verifiable                                  ║
║                                                                    ║
║   5. Reconstruct an accurate timeline from logs, metrics,          ║
║      and human accounts — the foundation of every good PIR         ║
╚════════════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔═════════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Find root cause first, then fix"                    ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG during active incident. Mitigate first — rollback,              ║
║   scale, failover, feature flag off. Root cause is post-incident.       ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "Who caused this?"                                   ║
╟─────────────────────────────────────────────────────────────────────────╢
║   TOXIC. Blame prevents honest postmortems. Systems fail;               ║
║   people operate systems. Fix the system, not the scapegoat.            ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "We fixed it — no postmortem needed"                 ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. SEV2+ requires PIR. Undocumented incidents repeat.             ║
║   The fix without understanding is a patch on a broken process.         ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "Action item: improve monitoring"                    ║
╟─────────────────────────────────────────────────────────────────────────╢
║   USELESS. Action items must be specific: "Add burn-rate alert on       ║
║   checkout success SLI at 14.4× over 1h window; owner @alice; 3/15."    ║
╠═════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Stay quiet until we know everything"                ║
╟─────────────────────────────────────────────────────────────────────────╢
║   WRONG. Communicate early and often with what you KNOW and what        ║
║   you DON'T know. Silence breeds rumor and executive escalation.        ║
╚═════════════════════════════════════════════════════════════════════════╝
```

---

## How to Use This Checklist

```
╔══════════════════════════════════════════════════════════════════════╗
║   DURING INCIDENT (live)                                             ║
╟──────────────────────────────────────────────────────────────────────╢
║   Sections 1–4: Triage, Investigation, Communication, Mitigation     ║
║   Incident Commander (IC) owns checklist; Scribe marks items         ║
║   Update every 15 minutes until mitigated                            ║
╠══════════════════════════════════════════════════════════════════════╣
║   AFTER INCIDENT (within 48 hours)                                   ║
╟──────────────────────────────────────────────────────────────────────╢
║   Sections 5–8: PIR, Action Items, Timeline, Follow-up               ║
║   PIR facilitator ≠ IC (fresh perspective)                           ║
║   Draft timeline before group PIR meeting                            ║
╠══════════════════════════════════════════════════════════════════════╣
║   SEVERITY REFERENCE (align with org policy)                         ║
╟──────────────────────────────────────────────────────────────────────╢
║   SEV1: Complete outage or data loss; all hands; exec comms          ║
║   SEV2: Major degradation; error budget burn; customer impact        ║
║   SEV3: Minor degradation; workaround exists; next business day      ║
║   SEV4: Cosmetic / internal only; ticket tracking                    ║
╚══════════════════════════════════════════════════════════════════════╝
```

---

## Section 1: Triage Checklist (First 15 Minutes)

The goal of triage is: assign roles, assess impact, start mitigation — NOT find root cause.

### Minute 0–5: Declare and Staff

```
[ ] Incident declared in official channel (#incidents or PagerDuty)
[ ] Severity assigned (SEV1–SEV4) based on user/business impact
[ ] Incident Commander (IC) assigned — one person coordinates, does not debug
[ ] Scribe assigned — documents timeline, decisions, commands run
[ ] Subject Matter Experts (SMEs) paged for affected services
[ ] Communication Lead assigned (SEV1/SEV2) — customer and exec updates
[ ] Incident bridge/video call link posted and pinned
[ ] Previous related incidents searched (same service, same symptom?)
[ ] Error budget / SLO dashboard opened — quantify impact
[ ] "Working theory" stated as hypothesis — NOT confirmed root cause
```

### Minute 5–10: Assess Impact

```
[ ] Which user journeys are affected? (Not "API is slow" — "checkout fails")
[ ] Which regions / tenants / customer segments?
[ ] When did impact start? (First alert vs first customer report)
[ ] Is impact spreading or stable?
[ ] Data at risk? (Corruption, loss, exposure — escalate immediately)
[ ] Revenue / SLA / regulatory impact estimated
[ ] Dependencies: upstream or downstream of failure?
[ ] Recent changes: deploys, config, infra, traffic shift in last 4 hours?
[ ] Is this a recurrence of a known issue with existing runbook?
```

### Minute 10–15: Initial Mitigation

```
[ ] Safest fast mitigation identified (rollback > restart > scale > fix forward)
[ ] Mitigation action assigned to single owner — IC approves execution
[ ] Customer-facing status page updated (SEV1/SEV2)
[ ] Internal stakeholders notified (support, sales, exec for SEV1)
[ ] If data exposure suspected: security team engaged immediately
[ ] Concurrent debugging allowed ONLY if it doesn't delay mitigation
[ ] Next update time communicated (e.g., "update in 15 min")
[ ] War room kept focused: IC redirects root-cause rabbit holes
```

---

## Section 2: Investigation Checklist

Run in parallel with mitigation. IC ensures investigation doesn't block restore.

### Observability

```
[ ] SLO / error budget dashboard: which SLI degraded first?
[ ] Golden signals: latency, traffic, errors, saturation per service
[ ] Recent deploy markers correlated with impact start time
[ ] Distributed traces sampled for failing requests
[ ] Logs searched with correlation ID from failing request
[ ] Infrastructure metrics: CPU, memory, disk, network, connection count
[ ] Dependency dashboards: each downstream service health
[ ] Queue depth / consumer lag for async paths
[ ] Database: slow queries, lock waits, replication lag, connection exhaustion
[ ] CDN / DNS / load balancer health and routing
[ ] Third-party status pages checked (AWS, Stripe, Cloudflare, etc.)
```

### Change Correlation

```
[ ] Deploys in last 24 hours listed with timestamps
[ ] Config changes (feature flags, env vars, secrets rotation)
[ ] Infrastructure changes (scaling, instance type, network ACL)
[ ] Data migrations or batch jobs started recently
[ ] Traffic pattern change (marketing event, bot, DDoS)
[ ] Certificate expiry or DNS TTL change
[ ] On-call handoff notes from previous shift
```

### Hypothesis Testing

```
[ ] Single variable changed to test hypothesis (not five at once)
[ ] Hypothesis recorded before test: "If X, then Y should improve"
[ ] Test result recorded: confirmed, rejected, inconclusive
[ ] Rollback of experimental fix if test fails
[ ] IC approves any production change during incident
[ ] All commands logged in incident doc (who, what, when)
```

---

## Section 3: Communication Checklist

### Internal Communication

```
[ ] Single source of truth: incident doc or Slack thread pinned
[ ] Updates every 15 min (SEV1) or 30 min (SEV2) from IC or Comms Lead
[ ] Update format: Impact / Actions taken / Next steps / ETA (if known)
[ ] Technical details in incident channel; summary in exec channel
[ ] "What we don't know" stated explicitly — builds trust
[ ] New participants briefed on current state — IC does 2-min recap
[ ] Decision log: who decided what and why (especially rollback vs fix-forward)
[ ] Handoff documented if IC or SME rotates off
```

### External Communication (SEV1/SEV2)

```
[ ] Status page updated within 15 min of confirmed customer impact
[ ] Status: Investigating → Identified → Monitoring → Resolved
[ ] Customer support given talking points — not raw technical jargon
[ ] Social media / community team aligned on message
[ ] Regulatory notification assessed (GDPR 72h, PCI, etc.)
[ ] Post-resolution: all-clear communicated; duration and impact summary
[ ] SLA credit process initiated if contractual breach
[ ] No blame language; no speculation on root cause in external comms
```

### Communication Templates

```
┌─────────────────────────────────────────────────────────────────┐
│  INTERNAL UPDATE (every 15 min)                                 │
├─────────────────────────────────────────────────────────────────┤
│  SEV: ___  IC: ___  Duration: ___  SLO impact: ___              │
│  IMPACT: ___________________________________________________    │
│  ACTIONS: __________________________________________________    │
│  NEXT: _____________________________________________________    │
│  ETA: ____________  UNKNOWN: ________________________________   │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  STATUS PAGE (customer-facing)                                  │
├─────────────────────────────────────────────────────────────────┤
│  We are investigating elevated error rates affecting [feature]. │
│  Some users may experience [symptom]. We will update in 30 min. │
└─────────────────────────────────────────────────────────────────┘
```

---

## Section 4: Mitigation vs Root Cause

```
╔═════════════════════════════════╦════════════════════════════╗
║ MITIGATION (during incident)    ║ ROOT CAUSE (post-incident) ║
╠═════════════════════════════════╬════════════════════════════╣
║ Restore service ASAP            ║ Understand why it happened ║
║ Rollback, scale, failover, flag ║ Five whys, timeline, gaps  ║
║ Accept temporary hacks          ║ Durable fix + prevention   ║
║ "Stop the bleeding"             ║ "Prevent recurrence"       ║
║ IC prioritizes                  ║ PIR facilitator leads      ║
╚═════════════════════════════════╩════════════════════════════╝

MITIGATION CHECKLIST:
[ ] Service restored to within SLO (or degraded mode documented)
[ ] Mitigation verified: error rate down, latency normal, synthetic checks pass
[ ] Temporary fix documented as TEMP — ticket filed for proper fix
[ ] Monitoring confirms stable for agreed soak period (15–60 min)
[ ] Incident downgraded or resolved in tracking system
[ ] IC confirms: "Users are whole" before standing down bridge

ROOT CAUSE (defer until mitigated):
[ ] Do NOT block resolution on root cause analysis
[ ] Note leading theories for PIR — do not commit in external comms
[ ] Preserve evidence: logs, metrics snapshots, heap dumps before TTL expiry
[ ] Freeze deploys to affected services until PIR complete (or IC exception)
```

---

## Section 5: Incident Commander (IC) Role Checklist

The IC coordinates — they do not debug. One person must hold this role at all times.

```
[ ] IC is NOT the person doing root-cause debugging
[ ] IC maintains incident doc as single source of truth
[ ] IC assigns tasks to SMEs — does not self-assign debug work
[ ] IC enforces: mitigate before deep-dive
[ ] IC calls time on rabbit holes: "park that for PIR"
[ ] IC approves all production changes during incident
[ ] IC sets and meets update cadence (15/30 min)
[ ] IC decides: rollback vs fix-forward vs scale
[ ] IC declares incident resolved — not first engineer to see green metrics
[ ] IC ensures handoff if rotation exceeds 4 hours
[ ] IC schedules PIR before standing down (SEV1/SEV2)
[ ] IC confirms scribe captured timeline with timestamps
```

### Severity Escalation Criteria

```
ESCALATE TO SEV1 when:
[ ] Complete loss of Tier 0 user journey (checkout, login, messaging)
[ ] Confirmed or suspected data loss / corruption / exposure
[ ] Impact expanding without mitigation in sight after 30 min
[ ] Regulatory or contractual notification required

DE-ESCALATE when:
[ ] SLO restored and stable for agreed soak period (15–60 min)
[ ] No active customer impact; monitoring only
[ ] Workaround in place with acceptable degraded SLO
```

---

## Section 6: Post-Incident Review (PIR / Blameless Postmortem)

Schedule within 5 business days for SEV1/SEV2; within 10 for SEV3.

### PIR Preparation

```
[ ] Timeline draft completed (see Section 7)
[ ] Incident doc exported: chat logs, commands, graphs linked
[ ] Participants invited: IC, SMEs, scribe, affected team leads, optional exec
[ ] Pre-read sent 24 hours before meeting
[ ] Facilitator confirmed (neutral; not the person who wrote the buggy code)
[ ] Ground rules restated: blameless, focus on systems, psychological safety
[ ] SEV level and error budget consumed documented
```

### PIR Meeting Agenda (60–90 min)

```
[ ] Timeline walkthrough — group corrects errors (15 min)
[ ] Impact assessment: users, revenue, SLO, duration (5 min)
[ ] What went well — detection, response, comms, runbooks (10 min)
[ ] What went poorly — gaps, delays, wrong assumptions (15 min)
[ ] Root cause analysis — five whys to systemic cause (20 min)
[ ] Action items drafted live — owner and date assigned (15 min)
[ ] Review action item quality against criteria (Section 6) (10 min)
[ ] Sign-off: EM or director approves action item list (5 min)
```

### Blameless Principles

```
[ ] No names attached to failure — roles and systems instead
[ ] "Why did the system allow this?" not "why did person X do this?"
[ ] Assume everyone acted with reasonable information at the time
[ ] Human error is a symptom — fix the process/tooling that allowed it
[ ] Near-misses celebrated — they reveal gaps before customers notice
[ ] PIR document shared broadly — learning is the product
```

### Five Whys Template

```
Problem: Checkout failed for 47 minutes

Why 1: Payment service returned 503
Why 2: Connection pool exhausted
Why 3: Pool size static at 50; traffic 3× after marketing email
Why 4: Auto-scaling added API pods but not pool config per pod
Why 5: Pool size in code constant — not tied to instance size or load

Systemic cause: Capacity config not in load test; pool not in dashboards
Action: Dynamic pool sizing + alert on pool wait time p99 > 100ms
```

---

## Section 7: Action Item Quality Criteria

Every action item must pass ALL five criteria. Reject vague items in the PIR meeting.

```
╔════════════════════════════════════════════════════════════════════╗
║   ACTION ITEM QUALITY — ALL FIVE REQUIRED                          ║
╠════════════════════════════════════════════════════════════════════╣
║   S — Specific:   Exact change, not "improve" or "review"          ║
║   M — Measurable: Done when verifiable (alert exists, test passes) ║
║   O — Owned:      One DRI (Directly Responsible Individual)        ║
║   T — Time-bound: Due date; not "soon" or "Q3"                     ║
║   L — Leverage:   Prevents recurrence class — not one-off patch    ║
╚════════════════════════════════════════════════════════════════════╝

ACTION ITEM CATEGORIES:
[ ] Detection:    alert, synthetic check, SLO burn rate
[ ] Prevention:   code fix, validation, circuit breaker, rate limit
[ ] Mitigation:   runbook, rollback automation, feature flag
[ ] Process:      review gate, deploy freeze policy, training
[ ] Recovery:     backup test, failover drill, restore procedure
```

### Good vs Bad Action Items

```
GOOD:
✓ "Add PagerDuty alert when checkout-pool-wait p99 > 100ms for 5 min.
   Owner: @alice. Due: 2026-03-20. Verify: trigger in staging."

✓ "Runbook: payment-svc connection exhaustion — scale + pool bump steps.
   Owner: @bob. Due: 2026-03-15. Verify: game day execution."

✓ "Load test must include 3× traffic spike before major marketing launches.
   Owner: @carol. Due: 2026-03-30. Verify: added to launch checklist."

BAD:
✗ "Be more careful with deploys." — Not specific, not measurable, blame-adjacent.

✗ "Improve monitoring." — What metric? What threshold? Who?

✗ "Team to discuss pool sizing." — No owner, no date, no deliverable.

✗ "Fix the bug." — Already done in incident; not recurrence prevention.

✗ "Document incident." — PIR doc is the deliverable; this is meta, not action.
```

### Action Item Register Template

```
┌────┬─────────────────────────────┬─────────┬────────────┬──────────┐
│ ID │  Action                     │  Owner  │  Due       │  Status  │
├────┼─────────────────────────────┼─────────┼────────────┼──────────┤
│ 1  │  _________________________  │  ______ │  ________  │  Open    │
│ 2  │  _________________________  │  ______ │  ________  │  Open    │
│ 3  │  _________________________  │  ______ │  ________  │  Open    │
└────┴─────────────────────────────┴─────────┴────────────┴──────────┘
Review in weekly ops meeting until all Closed with verification evidence.
```

---

## Section 8: Timeline Reconstruction Template

Build timeline BEFORE PIR meeting. Use UTC timestamps. Include sources.

```
╔═════════════════════════════════════════════════════════════════════╗
║   INCIDENT TIMELINE — INC-_______  SEV: ___  Service: ____________  ║
╠═════════════════════════════════════════════════════════════════════╣
║   Duration: _______  SLO budget consumed: _______  IC: _________    ║
╚═════════════════════════════════════════════════════════════════════╝

┌─────────────┬────────────────────────────────┬──────────────┐
│ TIME (UTC)  │ EVENT                          │ SOURCE       │
├─────────────┼────────────────────────────────┼──────────────┤
│ T-60min     │ Deploy v2.3.1 to payment-svc   │ CI/CD log    │
│ T-0 (start) │ First alert: error_rate > 5%   │ PagerDuty    │
│ T+3min      │ IC assigned; bridge opened     │ Incident doc │
│ T+8min      │ Impact confirmed: checkout 503 │ SLO dash     │
│ T+12min     │ Status page: Investigating     │ Statuspage   │
│ T+18min     │ Theory: connection pool        │ SME analysis │
│ T+25min     │ Rollback v2.3.0 initiated      │ IC decision  │
│ T+32min     │ Error rate declining           │ Metrics      │
│ T+47min     │ SLO restored; Monitoring       │ Synthetics   │
│ T+60min     │ Incident resolved; bridge end  │ IC           │
└─────────────┴────────────────────────────────┴──────────────┘

DETECTION LAG:  Time from first customer impact to first alert: _______
RESPONSE LAG:  Time from alert to IC assigned: _______
MITIGATION LAG: Time from IC to service restored: _______
TOTAL MTTR:    _______

GAPS IDENTIFIED:
• _________________________________________________________________
• _________________________________________________________________
```

---

## Section 9: PIR Document Template

```
╔══════════════════════════════════════════════════════════════════════╗
║   POST-INCIDENT REVIEW — INC-_______                                 ║
╠══════════════════════════════════════════════════════════════════════╣
║   Date: _______  Facilitator: _______  SEV: ___  Duration: _____     ║
║   Services: _________________________  IC: ______________________    ║
║   Error budget consumed: _______%  Customer impact: _______________  ║
╠══════════════════════════════════════════════════════════════════════╣
║   EXECUTIVE SUMMARY (3–5 sentences)                                  ║
║   ________________________________________________________________   ║
╠══════════════════════════════════════════════════════════════════════╣
║   TIMELINE: (link to Section 8 template)                             ║
║   ROOT CAUSE (systemic, not individual):                             ║
║   ________________________________________________________________   ║
║   CONTRIBUTING FACTORS:                                              ║
║   • _____________________________________________________________    ║
║   WHAT WENT WELL / WHAT WENT POORLY: (see PIR agenda)                ║
║   ACTION ITEMS: (link to register)                                   ║
║   LESSONS LEARNED (shareable across teams):                          ║
║   • _____________________________________________________________    ║
╚══════════════════════════════════════════════════════════════════════╝
```

---

## Section 10: Post-PIR Follow-Up

```
[ ] PIR document published within 48 hours of meeting
[ ] Action items entered in tracking system (Jira, Linear, etc.)
[ ] Action items reviewed in weekly ops meeting until closed
[ ] Closed items require verification evidence (link to PR, alert, runbook)
[ ] Error budget report updated with incident consumption
[ ] Recurring incident pattern checked (3rd time = escalation to eng director)
[ ] Runbook updated if incident exposed gap
[ ] Game day or drill scheduled if failover/restore was untested
[ ] PIR shared in engineering all-hands or incident review forum
[ ] Customer-facing postmortem published if SLA breach (SEV1 contractual)
```

---

## Key Takeaways

```
1. First 15 minutes: declare, staff, assess, mitigate — not root-cause hunt.

2. Mitigation restores users; root cause analysis prevents recurrence. Sequence matters.

3. Blameless is not optional — it's how you get honest timelines and systemic fixes.

4. Action items need SMART + Leverage. "Improve monitoring" is not an action item.

5. Timeline reconstruction is the PIR foundation. UTC, sources, detection/response/mitigation lags.
```

---

## Targeted Reading

```
→ Google SRE Book, Ch 15 (Postmortem Culture), Ch 10 (Emergency Response)
→ Etsy Debriefing Facilitation Guide — blameless postmortem facilitation
→ PagerDuty Incident Response Documentation — IC role, severity definitions
→ Week 8: SLOs, SLIs, Error Budgets — tie incidents to budget policy
→ Week 9–14 Compound Scenarios — practice incident narratives
```
