# Module Contract v2

Replaces the old “mandatory 12 sections + 2000+ lines” quota.  
**Depth is compression + evidence, not padding.**

---

## Required sections (teaching modules, Weeks 1–8 and 08b)

| # | Section | Purpose | Anti-pattern |
|---|---------|---------|--------------|
| 1 | Learning objectives | Observable “you will be able to…” | Vague “understand” |
| 2 | Wrong mental models | Destroy misconceptions first | Skipping to happy path |
| 3 | Core mechanism | How it works + math | Buzzword tour |
| 4 | Production anatomy | Metrics, logs, configs you’d actually see | Tool name-drops only |
| 5 | Failure catalog | Trigger → amplifier → blast radius | “It can fail” |
| 6 | Decision framework | When X vs Y with constraints | Absolute rules |
| 7 | Ops Sim (questions only) | Timed multi-symptom drill | Answers in-file |
| 8 | Key takeaways | ≤7 bullets | Essay recap |
| 9 | Targeted reading | Specific pages/URLs | “Read DDIA” |

**Optional tiers** (mark clearly):

- `### Foundation` — must know cold  
- `### Staff` — expected in L5/L6 design + on-call  
- `### Principal stretch` — optional depth

---

## Required sections (design modules, Weeks 9–14)

| # | Section | Purpose |
|---|---------|---------|
| 1 | Learning objectives | |
| 2 | Wrong mental models | |
| 3 | Requirements & constraints | Functional + non-functional + abuse/cost |
| 4 | Critical paths | Write path, read path, consistency boundary |
| 5 | Data model & capacity math | Forced worksheet |
| 6 | Failure & abuse catalog | Incl. security/tenancy where relevant |
| 7 | Ops Sim / interview drill | Questions only |
| 8 | Takeaways + reading | |

---

## Answer keys

- Learner files **end at questions**.  
- Keys live under `answers/<Week-Folder>/<Same-Title> Answers.md`.  
- Retention keys: `answers/Retention-Tests/<name> Answers.md`.  
- Opening a key before attempting is self-sabotage; README states this.

---

## Length guidance (not a quota)

| Topic type | Typical target |
|------------|----------------|
| Narrow mechanism (e.g., TIME_WAIT) | 600–1200 lines |
| Broad teaching module | 1200–2000 lines |
| Full system design | 1500–2500 lines |
| Ops Sim / retention (questions) | 200–500 lines |
| Answer key | As long as needed |

If a file exceeds ~2500 lines, suspect padding — compress before adding more.

---

## Ops Sim minimum bar

Every Ops Sim must include:

1. **Telemetry pack** (numbers, not adjectives)  
2. **Config pack** (including the wrong config)  
3. **Timeline** with T+0 / T+5 / T+15 / T+60 decision points  
4. **At least one bad fix** the learner must reject  
5. **Capacity or blast-radius question**  
6. **Org/comms or runbook question** when severity warrants it  

Template: [`templates/OPS_SIM_TEMPLATE.md`](../templates/OPS_SIM_TEMPLATE.md)
