# Story Bank Builder — SRE Edition

### Foundation

You cannot invent deep stories under clock. Build a **bank of 10** before mocks. Each card is reusable across prompts via retargeting.

---

## Learning Objectives

1. Fill 10 story cards with enough facts to survive 15 minutes of follow-ups.  
2. Tag each card with signals (conflict, failure, leadership, ambiguity, toil, customer).  
3. Retarget one card to ≥3 prompts without lying.  
4. Kill weak cards (no stakes, no agency, no lesson).

---

## Wrong Mental Models

```text
1. "I need 30 stories."
   Wrong. 8–12 deep cards beat 30 shallow ones.

2. "Only SEV1 counts."
   Wrong. A well-owned SEV3 with org learning can beat a SEV1 you watched.

3. "I'll remember details live."
   Wrong. Write numbers down now. Memory lies under stress.
```

---

## Core Teaching — Story card schema

### Foundation — Required fields

```text
TITLE:
COMPANY/TEAM:
WHEN (quarter/year):
SIGNAL TAGS: [conflict|failure|leadership|ambiguity|toil|customer|mentorship|influence]

SITUATION (5 lines max):
  - System + users/QPS/$/SLO
  - What broke or what decision loomed
  - Constraint (time, political, technical)

TASK (my ownership):
  - One sentence

ACTIONS (3–6 bullets, I-led):
  - Decision → why → alternative rejected
  - Who I aligned
  - Sequence

RESULT (evidence):
  - Metric before/after OR concrete outcome
  - What still hurt

LESSON / DURABLE CHANGE:
  - Guardrail, design, runbook, coaching

FOLLOW-UP LANDMINES (prep answers):
  - What would you do differently?
  - What did others do?
  - Was this your idea?
  - Any disagreement?
```

---

### Staff — Mandatory card set (fill all 10)

| # | Card type | Minimum bar |
|---|-----------|-------------|
| 1 | SEV / reliability incident you owned | Numbers + wrong first hypothesis OK |
| 2 | Conflict with peer/partner team | Incentive-aware, no villain |
| 3 | Said no / slowed ship for reliability | Error budget or risk framing |
| 4 | Toil reduction | Proof it stayed gone |
| 5 | Influence without authority | Clear ask + outcome |
| 6 | Mentorship / raising the bar | Their outcome, not your feelings |
| 7 | Ambiguous problem | Reversible first move |
| 8 | Failure / mistake you made | Repair + prevention |
| 9 | Cross-region / multi-system cascade | Sequencing judgment |
| 10 | Customer-visible harm | Empathy + fix + prevention |

---

### Principal stretch — Portfolio diversity check

Your bank fails Principal if:

- All stories are from the same quarter  
- All stories are pages you answered alone  
- Zero stories include product/business tension  
- Zero stories include being wrong  

---

## Failure Catalog — Weak cards

| Weakness | Fix |
|----------|-----|
| No metric | Recover from dashboards/postmortems now |
| “We” soup | Rewrite Actions with I-decisions |
| No Lesson | Add the durable change or discard card |
| Confidential | Sanitize; keep mechanisms; drop secrets |
| Too junior | Pick higher-stakes ownership moment |

---

## Decision Framework — Retargeting

| Prompt | Pull card tagged… | Foreground |
|--------|-------------------|------------|
| Tell me about a conflict | #2 | Disagreement mechanics |
| Time you failed | #8 or #1 | Your miss + repair |
| Leadership | #5 or #6 | Influence / lift |
| Deadlines | #3 | Risk call |
| Hard bug | #1 or #9 | Diagnosis sequence |

---

## Ops Sim (questions only)

**Time box:** 45 minutes (writing)

**Q1:** Create cards #1, #2, #3, #8 fully using the schema.  

**Q2:** For card #1, write Meta / Netflix / Google openings (≤40 words each).  

**Q3:** Discard or upgrade any card that fails the ownership test.  

**Q4:** List follow-up landmines for card #2 and answer each in ≤4 sentences.  

> Answer key (worked examples + critique rubric): [`../answers/Week-15b-Behavioral-SRE-Leadership/Story Bank Builder Answers.md`](../answers/Week-15b-Behavioral-SRE-Leadership/Story%20Bank%20Builder%20Answers.md)

---

## Key Takeaways

1. Depth beats quantity.  
2. Write numbers before mocks.  
3. Tag for retargeting.  
4. Failure cards are assets.  
5. Sanitize secrets; keep mechanisms.

---

## Targeted Reading

- Your last 4 postmortems / IR tickets (primary source)  
- Google SRE — Postmortem Culture
