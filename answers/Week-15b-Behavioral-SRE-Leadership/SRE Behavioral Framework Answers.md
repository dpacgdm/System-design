# Answer Key — SRE Behavioral Framework

Open only after the Ops Sim.

## Grading bar
Use Behavioral Rubric (32 points). Staff pass ≥22. Automatic fails apply.

---

## Q1 — Disagreement affecting reliability (worked Staff exemplar)

**Situation:** Northstar checkout SLO 99.95% / p99 300ms. Two days before a marketing launch, error budget was 38% consumed with 28 days left. Product wanted a new recommendation fanout on the checkout path estimated at +25ms p99.

**Task:** I owned the reliability recommendation for launch go/no-go on that path.

**Action:** I quantified burn: if p99 moved 25ms and tail amplified retries, we projected budget exhaustion in ~11 days. Alternatives I considered: (1) ship fully — rejected; (2) delay launch 2 weeks — politically hard; (3) ship behind flag off checkout critical path with cached fallback — chosen. I wrote a one-pager with burn math, proposed ownership of the flag default, and aligned product on a 48h bake with auto-disable on burn-rate alert. I conceded launch date for non-critical surfaces.

**Result:** Launch hit date on non-critical surfaces; checkout p99 +4ms; no SEV; budget intact.

**Lesson:** Added “critical-path latency budget” check to launch template; burn-rate alert on checkout.

**Why Staff:** numbers early, I-decisions, rejected alternatives, durable lesson.
**Below bar version:** “I told them reliability matters and they listened.”

---

## Q2 — Wrong first diagnosis (worked)

**Situation:** SEV2 — elevated 500s on payment-authorize. I first hypothesized dependency DB CPU.

**Task:** Bridge lead for payments reliability.

**Action:** CPU was only 45%. Disconfirming evidence: thread pool rejections + retry amplification. I announced on the bridge: “Withdrawing DB hypothesis; investigating client retries.” Found `retries=12` with breaker disabled in a config diff 41 minutes prior. I rolled config, confirmed queue depth drop, then verified DB was healthy (avoided useless failover).

**Result:** Errors normalized in 9 minutes after config revert; avoided failover side effects.

**Lesson:** Runbook now checks client retry/breaker config before datastore failover; config diff is in the first 5-minute checklist.

**Principal stretch:** Added CI policy blocking breaker disable without approval.

---

## Q3 — Toil reduction (worked)

**Situation:** On-call spent ~6h/week manually repartitioning hot Kafka consumers after sales spikes.

**Task:** I owned on-call pain for the commerce stream platform.

**Action:** Measured toil hours from ticket tags. Built autoscaler on consumer lag + CPU with guardrails; documented failure mode if lag was due to poison messages (separate park topic). Shadow-ran 2 weeks.

**Result:** Manual repartition tickets → 0 for 90 days; pages related to lag down 70%.

**Lesson:** Toil isn’t automated until you prove non-recurrence; added monthly report.

---

## Q4 — Influence without authority (worked)

**Situation:** Search team’s deploy cadence caused CDN cache stampedes affecting checkout static assets on shared edge config — not their SEV.

**Task:** I did not manage search; I owned checkout availability.

**Action:** Brought evidence (correlation of purge storms to checkout TTFB). Proposed separate cache keys + purge ACL. Offered to implement the edge config PR myself. Escalated only after providing a reversible patch.

**Result:** Change merged; purge storms no longer coupled; relationship intact (joint postmortem note).

**Lesson:** Influence = evidence + doing the work + reversible proposal.

---

## Q5 — Opening rewrites

(a) “At 14:02 checkout p99 hit 1.8s against a 300ms SLO; ~4% of checkouts failed; I owned bridge mitigation.”  
(b) Delete trait claims; replace with one owned decision from a card.  
(c) “Product had a hard date; I translated risk into error-budget exhaustion in 6 days and proposed a flagged partial ship I would operate.”

---

## Follow-up landmines (prep)

| Probe | Strong move |
|-------|-------------|
| “What would you do differently?” | Name a earlier measurement you skipped |
| “Who else deserves credit?” | Credit specifically; keep your decisions |
| “Were you too cautious?” | Show optionality you preserved |
