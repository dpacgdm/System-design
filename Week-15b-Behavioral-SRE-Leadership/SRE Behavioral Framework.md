# SRE Behavioral Framework (STAR-L)

### Foundation

Behavioral rounds fail SREs who only recite outages. Interviewers score **judgment under uncertainty**, **ownership of blast radius**, **influence without authority**, and **whether you learn in public**. This module is the operating system for every story you tell.

---

## Learning Objectives

After this module you will be able to:

1. Convert any incident/project story into **STAR-L** (Situation, Task, Action, Result, Lesson) in ≤3 minutes.
2. Separate **what you owned** from **what the team did** without sounding either lone-wolf or passenger.
3. Map every story to SRE signals: error budgets, toil, reliability vs feature pressure, postmortem honesty, cross-team coordination.
4. Detect and fix weak answers: hero narrative, blame, vague “we”, missing numbers, no learning.
5. Self-score a behavioral answer on a Staff bar before opening any model key.

---

## Wrong Mental Models

```text
1. "Behavioral is soft; wing it."
   Wrong. FAANG behavioral is patterned signal detection. Unstructured stories fail Staff.

2. "I need a perfect success story."
   Wrong. The highest-signal stories include failure, conflict, or partial wins — with ownership and learning.

3. "List everything I did."
   Wrong. Interviewers want decision quality: options considered, tradeoffs, what you personally changed.

4. "Blame the other team carefully."
   Wrong. Blame is an automatic fail. Describe system incentives and your next move.

5. "STAR is enough."
   Wrong for SRE. Without Lesson (and often Leading indicators / follow-through), you sound like a ticket-closer not a principal.
```

---

## Core Mechanism — STAR-L

### Foundation — The five beats

| Beat | Purpose | SRE flavor |
|------|---------|------------|
| **S** Situation | Context, stakes, constraints | SEV, SLO burn, customer/$$ impact, time box |
| **T** Task | Your job, not the team's | Explicit scope of ownership |
| **A** Action | Decisions + why | Alternatives rejected; sequence; who you aligned |
| **R** Result | Evidence | Metrics, MTTR, error budget, recurrence |
| **L** Lesson | What changed after | Guardrail, runbook, design, coaching |

**Time budgets (30-minute behavioral):**

| Segment | Time |
|---------|-----:|
| Clarify prompt | 30–45s |
| STAR-L delivery | 2.5–4 min |
| Follow-ups | rest of block |
| Never exceed 5 min monologue without a check-in | — |

---

### Staff — Ownership grammar

Use precise pronouns:

- **I** for decisions, tradeoffs, pushes, designs, mistakes.
- **We** for shared execution after you set direction.
- Name collaborators by role when coordination matters: “payments eng lead”, “product director”.

**Ownership test:** If you remove every “I”, does the story still have an agent? If not, rewrite.

**Blast-radius test:** Did you state what could get worse if you chose the wrong mitigation? Staff answers include that sentence.

---

### Principal stretch — Multi-scale storytelling

Principal answers move across three scales in one story:

1. **Minutes:** incident action  
2. **Weeks:** durable fix / process  
3. **Quarters:** org or architecture incentive change  

If you only have minutes-scale, you max out at Mid. If you only have quarters-scale with no personal action, you sound executive-vague.

---

## Production Anatomy — What interviewers listen for

```text
SIGNAL PACK (score these live while practicing)

  Clarity:      Can a stranger follow the timeline?
  Stakes:       Numbers (users, $, SLO, SEV) within first 45s
  Agency:       Clear "I decided / I pushed / I was wrong"
  Tradeoffs:    At least one rejected alternative with reason
  Systems:      Mechanism, not vibes ("semi-sync lag" not "DB issues")
  Humans:       Who needed what information when
  Evidence:     Result tied to metric or concrete outcome
  Learning:     Durable change, not "I'll be more careful"
  Humility:     Credit others; claim mistakes without self-flagellation
  Calibration:  Scope matches level (Staff ≠ fixed a typo)
```

---

## Failure Catalog — Behavioral answer failure modes

| Trigger | Amplifier | Blast radius |
|---------|-----------|--------------|
| No stakes | Abstract jargon | Interviewer tunes out |
| Pure hero | No tradeoffs | Sounds unsafe / uncoachable |
| Pure victim | Blame | Culture fail |
| Endless Situation | No Action | Time runs out |
| Result without Lesson | Recurrence likely | “Would hire as IC2 firefighter only” |
| Fake numbers | Follow-up probe | Integrity kill shot |
| Design lecture in behavioral | Wrong round mode | Wastes clock |

---

## Decision Framework — Which story to pull

| Prompt type | Prefer story with… | Avoid |
|-------------|--------------------|-------|
| Conflict | Disagreement + principled compromise | “I won the argument” |
| Failure | Your miss + repair + prevention | Company outage you watched |
| Leadership | Influence without authority | “I was the manager so I ordered” |
| Ambiguity | Incomplete data + reversible first move | Paralysis or reckless ship |
| Customer obsession | User harm quantified + fix | Internal metrics only |
| On-call / reliability | Error budget / SEV judgment | Macho “I never sleep” |

---

## Ops Sim: Behavioral Pressure Box (questions only)

**Time box:** 25 minutes  
**Severity:** Interview P0 (offer-critical)  
**Domain:** Staff SRE behavioral  

### Rules

1. Answer out loud or typed as if spoken.  
2. Do not open `answers/`.  
3. Keep each answer ≤4 minutes equivalent (~500–650 words max).  

### Prompts

**Q1:** Tell me about a time you disagreed with a decision that affected production reliability.

**Q2:** Describe an incident where your first diagnosis was wrong. What did you do next?

**Q3:** Give an example of reducing toil. What did you stop doing, and how did you prove it stayed gone?

**Q4:** Tell me about influencing a team that did not report to you during a SEV.

**Q5 (bad-fix gallery):** Here are three opening lines — rewrite each into a Staff opening (≤40 words):  
(a) “We had some issues with the database.”  
(b) “I’m the kind of person who always takes ownership.”  
(c) “Management forced us to ship.”

### Self-score

| Signal | Pass? |
|--------|-------|
| Stakes in ≤45s | |
| Clear I-ownership | |
| One rejected alternative | |
| Numeric or concrete Result | |
| Durable Lesson | |

> Answer key: [`../answers/Week-15b-Behavioral-SRE-Leadership/SRE Behavioral Framework Answers.md`](../answers/Week-15b-Behavioral-SRE-Leadership/SRE%20Behavioral%20Framework%20Answers.md)

---

## Key Takeaways

1. STAR without Lesson is firefighter cosplay.  
2. Ownership is grammar + blast radius, not volume.  
3. Numbers early; mechanisms over vibes.  
4. Conflict stories need incentives, not villains.  
5. Timebox monologues; invite follow-ups.  
6. Practice out loud — reading is not behavioral prep.

---

## Targeted Reading

- Google SRE Book — Postmortem Culture (blameless)  
- Allspaw — “Human Factors” / incident analysis essays  
- Company eng blogs on error budgets (Google, Netflix chaos/reliability posts) — for vocabulary, not to parrot culture memos
