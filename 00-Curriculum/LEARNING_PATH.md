# Learning Path

**Audience gate:** This curriculum assumes ~**3+ years** backend or SRE experience.  
If you cannot comfortably explain TCP vs UDP, read an `EXPLAIN ANALYZE` plan, or reason about replication lag, complete a fundamentals course first — do not start at Week 1 and hope.

**Format:** Text-only operational simulation. This is the best substitute we can build **without labs**. It trains diagnosis, sequencing, and design judgment. It does **not** replace muscle memory on real clusters.

---

## How to study (non-negotiable)

1. Read the teaching module **once** end-to-end (questions only at the end).  
2. Attempt the **Ops Sim** under time pressure before opening `answers/`.  
3. End of week: **Retention test** (questions file only).  
4. Score yourself with the answer key using the error-type rubric.  
5. **Mastery gate:** do not start Week N until Retention N−1 is ≥ **85%** on rapid-fire and you can narrate the compound scenario without notes.  
6. Never scroll into expert analysis in the same sitting as the first attempt.

---

## Spaced retention mix

Each retention test (from Week 4 onward) should feel like:

| Slice | Share | Content |
|-------|------:|---------|
| Recent | ~30% | Current week |
| Mid | ~40% | Prior 2–3 weeks |
| Old | ~30% | Anything earlier (including Week 1 networking) |

---

## Week map

| Week | Focus | Gate before next |
|------|-------|------------------|
| 1 | Transport, HTTP, DNS, CDN | Retention-01 ≥85% |
| 2 | SQL, NoSQL taxonomy, caching | Combined 02–03 gate |
| 3 | CAP/PACELC, consistency, consistent hashing | Combined 02–03 gate |
| 4 | Replication, sharding, Raft | Retention-04 |
| 5 | DB scaling patterns, Cassandra internals | Retention-05 |
| 6 | Queues, EDA, microservices, saga, outbox, resilience | Retention-06 |
| 7 | LB, rate limit, search, IDs, feature flags | Retention-07 |
| 8 | Clocks, CRDTs, geo, observability, SLOs | Retention-08 |
| **08b** | **Trust (authn/z), cost/FinOps, multi-tenancy** | **Retention-08b** |
| 9 | WhatsApp + Twitter feed + compound | Retention-09 |
| 10 | YouTube + Uber + compound | Retention-10 |
| 11 | Payments + e-commerce + compound | Retention-11 |
| 12 | Search + crawler + compound | Retention-12 |
| 13 | KV store + Kafka + config store + compound | Retention-13 |
| 14 | Docs + LLM serving + feature store + compound | Retention-14 |
| 15 | Timed mocks + rubric | Self-score ≥ “Meets Bar” on 3/5 |
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
| Capacity checks repeatedly missed | Do every capacity worksheet in `templates/` before continuing |
| You open answer keys early “just to peek” | You are not measuring learning — restart that week |

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
