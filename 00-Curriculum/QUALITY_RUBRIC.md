# Quality Rubric — Human Scoring (Not Tooling)

This rubric defines what **9.8** means in this repo.  
`tools/audit_curriculum.py` checks **structure only**. It does **not** award quality scores.

**Scoring scale (per dimension):** 1.0–10.0  
**Module pass bar:** ≥ 9.0 on every applicable dimension  
**Curriculum “9.8 claim” bar:** audited sample average ≥ 9.5 **and** no dimension below 9.0

---

## Dimensions

### 1. Conceptual coverage (module / week)

| Score | Meaning |
|------:|---------|
| ≤6 | Major staff/principal topics missing or hand-waved |
| 7–8 | Core topic present; adjacent concerns thin |
| 9.0–9.4 | Topic complete for interview + ops reasoning; cross-links explicit |
| 9.5–9.8 | Includes security/cost/tenancy/abuse where relevant; no silent gaps |
| 9.9–10 | External expert would not add a required section |

### 2. Depth (not length)

| Score | Meaning |
|------:|---------|
| ≤6 | Definitions and diagrams without failure physics |
| 7–8 | Mechanisms present; numbers sparse or decorative |
| 9.0–9.4 | Mechanisms + math + configs + failure amplification |
| 9.5–9.8 | Every non-obvious claim has evidence a principal would demand; filler removed |
| 9.9–10 | Could brief a staff eng in 20 minutes from the module alone |

**Anti-pattern:** long ASCII boxes that restate the same idea. Length ≠ depth.

### 3. Pedagogical design

| Score | Meaning |
|------:|---------|
| ≤6 | Dump of facts; answers spoil questions; no path |
| 7–8 | Objectives + wrong models; weak progression |
| 9.0–9.4 | Prerequisites, teach → drill → retain; answers separated |
| 9.5–9.8 | Difficulty tiers; stop/go gates; spaced retention hooks |
| 9.9–10 | A stranger can self-study without a tutor and not cheat themselves |

### 4. Production realism (without labs)

| Score | Meaning |
|------:|---------|
| ≤6 | Generic “it fails” stories |
| 7–8 | Named symptoms; weak telemetry |
| 9.0–9.4 | Telemetry packs, configs (incl. wrong ones), timed decisions, bad-fix gallery |
| 9.5–9.8 | Ops Sim with T+0/T+5/T+15/T+60, capacity worksheet, org constraints |
| 9.9–10 | Feels like a sealed incident packet from a real bridge call |

### 5. Assessment / retention integrity

| Score | Meaning |
|------:|---------|
| ≤6 | No test, or answers in the same scroll as questions |
| 7–8 | Questions exist; keys leak or retention gaps |
| 9.0–9.4 | Separate keys; retention every week; rubrics with error types |
| 9.5–9.8 | Spaced mix (recent/mid/old); mastery gates; compound integration |
| 9.9–10 | Blind-gradable by a third party with the rubric alone |

### 6. Honesty

| Score | Meaning |
|------:|---------|
| ≤3 | Vanity self-scores from format linters |
| 5–7 | Acknowledges limits vaguely |
| 9.0–9.4 | README states what text substitutes for and what it does not |
| 9.5–9.8 | Published sample audit with evidence; tooling demoted |
| 9.9–10 | External reviewers’ scores published alongside self-scores |

---

## Module checklist (pass/fail)

A teaching or design module **passes** only if:

- [ ] Learning objectives are observable behaviors (not “understand X”)
- [ ] Wrong mental models come before teaching
- [ ] Core mechanism includes at least one quantitative argument
- [ ] Failure catalog has trigger → amplifier → blast radius
- [ ] Ops Sim present (or explicit pointer to week Ops Sim)
- [ ] **No expert analysis / model answers in the learner file**
- [ ] Answer key exists under `answers/` with matching name
- [ ] Targeted reading cites specific pages/sections
- [ ] Security, cost, or tenancy touched when the topic warrants it
- [ ] No personal tutor-log / process notes in the module

---

## Audited sample protocol (for claiming ≥9.5)

1. Pick 10 teaching modules (mix early/mid), 4 retention tests, 2 mocks, 1 capstone scenario file.
2. Two scorers (or one scorer + cooling-off re-score) apply this rubric.
3. Publish results in `00-Curriculum/AUDIT_SAMPLE.md`.
4. Only then may README say the audited sample meets the bar.

**Forbidden:** deriving a quality score from section counts, ASCII box alignment, or line counts.
