# Distributed Systems & System Design Mastery

Structured curriculum for distributed systems and system design.  
Depth target: **staff / principal reasoning in text** — interview-grade and incident-grade — **without pretending text replaces operating real systems**.

**Status (2026-07-26):** Audit loop 2 scores stand; **interview SD partial gaps filled** (ads, trending, ticketing, flights, discovery, recsys, agents).  
See [`00-Curriculum/AUDIT_SAMPLE.md`](00-Curriculum/AUDIT_SAMPLE.md).  
Design-week compression was **skipped** (topics retained). Clone Ops Sims and dual drills were removed.

| Dimension | Baseline | Loop-1 | Loop-2 |
|-----------|---------:|-------:|-------:|
| Pedagogy | 65% | 93% | **98%** |
| Depth | uneven/~70% | 93% | **98%** |
| Coverage | 85% | 95% | **98%** |
| Production realism (no labs) | 60% | 95% | **98%** |
| Assessment / retention integrity | 60% | 95% | **98%** |
| Honesty | 30% | 96% | **98%** |

Scoring rules: [`00-Curriculum/QUALITY_RUBRIC.md`](00-Curriculum/QUALITY_RUBRIC.md)  
How to study: [`00-Curriculum/LEARNING_PATH.md`](00-Curriculum/LEARNING_PATH.md)  
Module shape: [`00-Curriculum/MODULE_CONTRACT_V2.md`](00-Curriculum/MODULE_CONTRACT_V2.md)

---

## Limits (read this)

**This repo can substitute for:**

- Mental rehearsal of incident bridges and cascade reasoning  
- System design interview depth and trade-off practice  
- Runbook / post-incident thinking under time pressure (text Ops Sims)

**This repo cannot substitute for:**

- Muscle memory on real Postgres / Kafka / Kubernetes / cloud consoles  
- Discovering that IAM, quotas, and messy org politics break your design  
- The feeling of a real pager at 03:47

We maximize realism **without labs** via telemetry packs, wrong configs, timed decision points, and separated answer keys — not via vanity line counts.

---

## How to use

1. Follow [`LEARNING_PATH.md`](00-Curriculum/LEARNING_PATH.md) week order and mastery gates.  
2. Study the module; attempt **Ops Sim / retention questions** before any key.  
3. Keys live only under [`answers/`](answers/) — opening early invalidates your score.  
4. Process / tutor-log material lives under [`00-Curriculum/meta/`](00-Curriculum/meta/) — **not** on the learning path.  
5. Northstar Commerce continuity: [`Ops-Sims/fictional-company/NORTHSTAR.md`](Ops-Sims/fictional-company/NORTHSTAR.md).  
6. Design modules must clear [`templates/DESIGN_MODULE_GATES.md`](templates/DESIGN_MODULE_GATES.md).

### Module contract (v2)

See [`MODULE_CONTRACT_V2.md`](00-Curriculum/MODULE_CONTRACT_V2.md).  
**Answers are never in the learner file.**

---

## Curriculum map

| Week | Focus | Retention |
|------|-------|-----------|
| 1 | Transport, DNS, CDN | [Week-01](Retention-Tests/Week-01.md) |
| 2–3 | Storage + distributed theory | [Weeks 2–3](Retention-Tests/Weeks-02-and-03.md) |
| 4 | Replication, sharding, Raft | [Week-04](Retention-Tests/Week-04.md) |
| 5 | Database internals | [Week-05](Retention-Tests/Week-05.md) |
| 6 | Architecture patterns | [Week-06](Retention-Tests/Week-06.md) |
| 7 | Specialized components (+ **service discovery**) | [Week-07](Retention-Tests/Week-07.md) |
| 8 | Advanced patterns + observability | [Week-08](Retention-Tests/Week-08.md) |
| **08b** | **Trust, cost, multi-tenancy** | [Week-08b](Retention-Tests/Week-08b.md) |
| **08c** | **Operations hardening: migration, testing, abuse, client/edge resilience** | [Week-08c](Retention-Tests/Week-08c.md) |
| 9 | Feed + chat + **trending hashtags** | [Week-09](Retention-Tests/Week-09.md) |
| 10 | Media + mobility + **ad platform** | [Week-10](Retention-Tests/Week-10.md) |
| 11 | Commerce + payments + **Ticketmaster** | [Week-11](Retention-Tests/Week-11.md) |
| 12 | Search + crawling + **Google Flights** | [Week-12](Retention-Tests/Week-12.md) |
| 13 | Infrastructure designs | [Week-13](Retention-Tests/Week-13.md) |
| 14 | Collaboration + AI + **recsys + agentic workflows** | [Week-14](Retention-Tests/Week-14.md) · [SD-Gaps](Retention-Tests/Week-SD-Gaps.md) |
| 15 | Mock interviews | Rubric in week folder; keys under `answers/` |
| 16 | Final mastery | [Final test](Week-16-Final-Mastery/Final%20Retention%20Test%20All%20Topics.md) |

---

## Interview gap fill (2026-07-26)

Added first-class modules for themes that were only partial before:

- `Service Discovery` (Week 7)
- `Design Trending Hashtags` (Week 9)
- `Design Ad Platform` (Week 10) — ranking, frequency capping, pacing
- `Design Ticketmaster` (Week 11)
- `Design Google Flights` (Week 12)
- `Design Recommendation System` + `Design Agentic Workflow Platform` (Week 14)
- Retention: [`Retention-Tests/Week-SD-Gaps.md`](Retention-Tests/Week-SD-Gaps.md)

Pair with [`dpacgdm/DSA`](https://github.com/dpacgdm/DSA) for Meta/Netflix **coding** rounds; this repo covers the **system design** rounds.

## Tooling (structure only)

```bash
python3 tools/audit_curriculum.py     # section presence heuristics — NOT a quality score
python3 tools/check_boxes.py .        # ASCII alignment (cosmetic)
python3 tools/split_expert_answers.py # extract co-located expert analysis into answers/
```

Cosmetic tooling must never be cited as proof of quality.

---

## Reading spine

*Designing Data-Intensive Applications* (Kleppmann) — specific pages cited per module, not generically.
