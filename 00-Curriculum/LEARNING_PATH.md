# Learning Path

**Audience gate:** This curriculum assumes ~**3+ years** backend or SRE experience.  
If you cannot comfortably explain TCP vs UDP, read an `EXPLAIN ANALYZE` plan, or reason about replication lag, complete a fundamentals course first - do not start at Week 1 and hope.

**Format:** Text-only operational simulation. This is the best substitute we can build **without labs**. It trains diagnosis, sequencing, and design judgment. It does **not** replace muscle memory on real clusters.

---

## How to study (non-negotiable)

1. Read the teaching module **once** end-to-end (questions only at the end).
2. Attempt the **Ops Sim** under time pressure before opening `answers/`.
3. End of week: **Retention test** (questions file only).
4. Score yourself with the answer key using the error-type rubric.
5. Run one **weekly transfer drill** after the retention test. The drill must be a novel failure that recombines the week's mechanisms with older mechanisms; it must not be a renamed or remixed version of the module's taught incident.
6. **Mastery gate:** do not start Week N until Retention N-1 is >= **85%** on rapid-fire, >= **80%** on the compound scenario, and you can narrate the incident sequence without notes.
7. **Staff gate:** do not attempt Principal stretch prompts until the Staff tier for the same module is passing.
8. Never scroll into expert analysis in the same sitting as the first attempt.

---

## Tier definitions

| Tier | Meaning | Required for progress? | Evidence |
|------|---------|------------------------|----------|
| **Foundation** | Core vocabulary, invariants, failure modes, and first-safe mitigations. You should be able to answer these cold and fast. | Yes, every week. | Rapid-fire >=85%, no unsafe first action in the scenario, clear layer/protocol identification. |
| **Staff** | Cross-layer diagnosis, capacity math, sequencing under incident pressure, and tradeoff explanations expected of L5/L6 design/on-call ownership. | Yes before Principal. | Compound scenario >=80%, at least one correct capacity/blast-radius calculation, rejects bad fixes with mechanism. |
| **Principal stretch** | Optional deep systems depth, organizational blast-radius design, economic tradeoffs, and ambiguous multi-team prevention plans. | No for week-to-week progress, but required for final mastery distinction. | Can defend constraints, invariants, and irreversible choices under a novel transfer drill. |

**Gate ordering is strict:** Foundation -> Staff -> Principal stretch. If Staff evidence is missing, do not count Principal answers even if they sound sophisticated.

---

## Spaced retention mix

Each retention test (from Week 4 onward) should feel like:

| Slice | Share | Content |
|-------|------:|---------|
| Recent | ~30% | Current week |
| Mid | ~40% | Prior 2-3 weeks |
| Old | ~30% | Anything earlier (including Week 1 networking) |

Retention thresholds:

| Result | Action |
|--------|--------|
| Foundation rapid-fire >=85% and compound >=80% | Proceed to next week after transfer drill. |
| Rapid-fire 70-84% or compound 65-79% | Re-drill weak modules within 48h; no Principal stretch yet. |
| Rapid-fire <70% or compound <65% | Stop progression; reread modules and redo Ops Sims. |
| Unsafe mitigation, durability loss, or security bypass proposed first | Automatic Staff failure even if facts are correct. |

---

## Weekly transfer drills

A transfer drill is mandatory because real incidents are not copies of the lesson incident.

Minimum bar:

1. Uses a **novel failure** not taught in that week's module.
2. Recombines at least **three mechanisms** across weeks already studied.
3. Includes telemetry, wrong config, T+ timeline, bad fixes, capacity or blast-radius math, and org/runbook prompts.
4. Forces the learner to distinguish root cause, amplifier, and symptom.
5. Has a sealed answer key under `answers/`.

Northstar transfer checkpoints:

| Checkpoint | File | Concept range |
|------------|------|---------------|
| Foundations | `Ops-Sims/Transfer-Foundations-Northstar.md` | Weeks 1-4 |
| Patterns | `Ops-Sims/Transfer-Patterns-Northstar.md` | Weeks 5-8 and 08b |
| Designs | `Ops-Sims/Transfer-Designs-Northstar.md` | Weeks 9-14 |

---

## Week map

| Week | Focus | Gate before next |
|------|-------|------------------|
| 1 | Transport, HTTP, DNS, CDN | Retention-01 >=85% rapid-fire, >=80% compound + transfer drill |
| 2 | SQL, NoSQL taxonomy, caching | Combined 02-03 gate |
| 3 | CAP/PACELC, consistency, consistent hashing | Combined 02-03 gate + transfer drill |
| 4 | Replication, sharding, Raft | Retention-04 Staff pass + Foundations transfer |
| 5 | DB scaling patterns, Cassandra internals | Retention-05 Staff pass |
| 6 | Queues, EDA, microservices, saga, outbox, resilience | Retention-06 Staff pass |
| 7 | LB, rate limit, search, IDs, feature flags, service discovery | Retention-07 Staff pass |
| 8 | Clocks, CRDTs, geo, observability, SLOs | Retention-08 Staff pass |
| **08b** | **Trust (authn/z), cost/FinOps, multi-tenancy** | **Retention-08b Staff pass + Patterns transfer** |
| **08c** | **Operations hardening: migration, testing, abuse, client/edge resilience** | **Retention-08c Staff pass + hardening transfer** |
| 9 | WhatsApp + Twitter feed + compound | Retention-09 |
| 10 | YouTube + Uber + compound | Retention-10 |
| 11 | Payments + e-commerce + compound | Retention-11 |
| 12 | Search + crawler + compound | Retention-12 |
| 13 | KV store + Kafka + config store + compound | Retention-13 |
| 14 | Docs + LLM serving + feature store + recommendation system + agentic workflow platform + compound | Retention-14 + SD gaps retention + Designs transfer |
| 15 | Timed mocks + rubric | Self-score >= "Meets Bar" on 3/5 |
| 16 | Capstone + checklists + final retention | Capstone rubric |

---

## Fictional company continuity

Ops Sims from Week 4 onward preferentially use **Northstar Commerce** (see `Ops-Sims/fictional-company/NORTHSTAR.md`) so failures compound across weeks the way real platforms do.

---

## Stop / go criteria (honest)

| Signal | Action |
|--------|--------|
| Rapid-fire <70% | Re-read weak modules; re-test in 48h |
| Scenario sequencing wrong but facts right | Drill Ops Sims only for 2 days |
| Staff gate failed | Repeat compound and transfer drill before any Principal stretch |
| Capacity checks repeatedly missed | Do every capacity worksheet in `templates/` before continuing |
| Transfer drill looks like the taught incident with nouns changed | Reject it; write a genuinely novel recombination |
| You open answer keys early "just to peek" | You are not measuring learning - restart that week |

---

## What this path substitutes for

- Mental rehearsal of incident bridges
- System design interview depth
- Cross-layer cascade reasoning
- Runbook / post-incident thinking

## What it does not substitute for

- Actually operating Postgres/Kafka/k8s under pager
- Team dynamics and real stakeholder pressure
- Tooling fluency and muscle memory
- Discovering that your beautiful design dies on a real IAM policy
