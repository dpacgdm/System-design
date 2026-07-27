# FAANG Culture Maps — Meta, Netflix, Google (SRE lens)

### Foundation

Culture questions are not trivia about memos. Interviewers test whether your **defaults match how that company ships and operates**. Same story; different emphasis.

---

## Learning Objectives

1. Map one story to Meta, Netflix, and Google SRE signals without rewriting history.
2. Avoid culture karaoke (“Freedom & Responsibility…”) while still hitting the underlying signal.
3. Spot company-specific red flags in your answers.
4. Prepare 3 “bridge sentences” that retarget a story mid-interview.

---

## Wrong Mental Models

```text
1. "Memorize the culture doc."
   Wrong. Parroting is detectable. Demonstrate the behavior.

2. "One story fits all companies."
   Half-wrong. Same facts; different foregrounded tradeoff.

3. "Netflix wants ruthlessness."
   Wrong. They want candor + high performance + ownership — not cruelty theater.

4. "Google only wants algorithms."
   Wrong for SRE loops: Google wants principled reliability, measurement, and clear thinking under constraints.
```

---

## Core Maps

### Foundation — Signal cheat sheet

| Company | What they amplify | What fails fast |
|---------|-------------------|-----------------|
| **Meta** | Move with impact, bias to action, peer partnership, end-to-end ownership | Slow perfectionism, siloed “not my code”, no user impact |
| **Netflix** | Candor, context not control, high talent density, owning outcomes | Politics, hiding bad news, waiting for permission on clear calls |
| **Google (SRE)** | Measurement, error budgets, principled risk, blameless learning | Heroics without prevention, hand-wavy capacity, blame |

---

### Staff — Same incident, three tellings (template)

**Base facts (example skeleton — replace with yours):**  
SEV involving checkout latency; you paused a risky flag; you aligned product on error budget; you shipped a durable fix.

**Meta foreground:** user/$$ impact, speed of mitigation, cross-team drive to close loop.  
**Netflix foreground:** candid pushback with context, ownership of the call, talent-dense collaboration.  
**Google SRE foreground:** SLO/error budget math, why the mitigation was safe, postmortem → prevention.

**Bridge sentences (memorize structure, not script):**

- Meta: “The user-visible failure was X; I drove Y in Z minutes because…”  
- Netflix: “I disagreed with shipping as-is; I gave context A/B and owned the rollback call…”  
- Google: “Error budget burn hit X%; I chose mitigation M because it preserved invariant I…”

---

### Principal stretch — Culture without cosplay

Principal answers show you can **translate incentives**:

- Meta: growth/experimentation pressure vs integrity  
- Netflix: speed vs operational load on a small expert team  
- Google: product velocity vs multi-tenant platform risk  

Name the incentive, your countermeasure, and the metric that proved it worked.

---

## Failure Catalog — Culture answer kills

| Failure | Why it dies |
|---------|-------------|
| Quoting culture doc verbatim | No evidence of behavior |
| “I always agree with leadership” | No judgment |
| “I refused and escalated angrily” | No collaboration |
| Hiding uncertainty | Netflix/Google especially punish this |
| Reliability absolutism (“never ship”) | Ignores error budgets / business |

---

## Decision Framework — Which emphasis?

| If the prompt sounds like… | Lean… |
|----------------------------|-------|
| Impact / move fast / peers | Meta |
| Candor / ownership / context | Netflix |
| Metrics / SLOs / principled risk | Google SRE |
| Unclear | Ask: “Do you want reliability judgment, collaboration, or conflict handling?” then pick |

---

## Ops Sim (questions only)

**Time box:** 20 minutes  

**Q1:** Take one real story. Write three openings (≤50 words) — Meta / Netflix / Google.  

**Q2:** Interviewer: “Did you move too slow?” Answer for Meta and for Google — both Staff-pass.  

**Q3:** Interviewer: “Sounds like you blamed product.” Repair in ≤60 seconds.  

**Q4:** List 5 phrases to ban in Netflix loops; replace each.  

> Answer key: [`../answers/Week-15b-Behavioral-SRE-Leadership/FAANG Culture Maps Meta Netflix Google Answers.md`](../answers/Week-15b-Behavioral-SRE-Leadership/FAANG%20Culture%20Maps%20Meta%20Netflix%20Google%20Answers.md)

---

## Key Takeaways

1. Same facts; different foreground.  
2. Signal > slogans.  
3. Candor without contempt; speed without recklessness; measurement without paralysis.  
4. Prepare bridge sentences, not scripts.

---

## Targeted Reading

- Netflix Culture Memo (read for signals, don’t recite)  
- Meta eng blog posts on experimentation / reliability (skimming)  
- Google SRE Book — Embracing Risk / Eliminating Toil
