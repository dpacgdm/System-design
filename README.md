# Distributed Systems & System Design Mastery

Structured curriculum for distributed systems and system design — **SRE / staff interview depth in text**.  
Does **not** pretend text replaces operating real systems.

**Status (2026-07-27):** Audit loop 2 (pedagogy/depth/coverage **98%**) retained.  
**SRE best track added:** behavioral (15b), Timed Interview OS, thick SRE LLD (15c), company playbooks.  
See [`00-Curriculum/AUDIT_SAMPLE.md`](00-Curriculum/AUDIT_SAMPLE.md).

| Dimension | Loop-2 | Notes |
|-----------|-------:|-------|
| Pedagogy / Depth / Coverage | **98%** | Gates in AUDIT_SAMPLE |
| SRE interview execution | **Best-effort track** | 15b + Timed OS + 15c + playbooks — calibrate before claiming ready |

Scoring: [`00-Curriculum/QUALITY_RUBRIC.md`](00-Curriculum/QUALITY_RUBRIC.md)  
Path: [`00-Curriculum/LEARNING_PATH.md`](00-Curriculum/LEARNING_PATH.md)  
Timed mocks: [`00-Curriculum/TIMED_INTERVIEW_OS.md`](00-Curriculum/TIMED_INTERVIEW_OS.md)

---

## Limits

**Substitutes for:** incident mental rehearsal, SD interview depth, runbook thinking, behavioral/LLD interview structure.  
**Does not substitute for:** live pager muscle memory, IAM/quota reality, real stakeholder pressure.

---

## How to use

1. Follow [`LEARNING_PATH.md`](00-Curriculum/LEARNING_PATH.md) gates.  
2. Ops Sim / retention **before** any key under [`answers/`](answers/).  
3. Before interviews: Timed OS calibration checklist (behavioral + SD + LLD + company playbook).  
4. Meta material: [`00-Curriculum/meta/`](00-Curriculum/meta/) — not on the learning path.  
5. Northstar: [`Ops-Sims/fictional-company/NORTHSTAR.md`](Ops-Sims/fictional-company/NORTHSTAR.md).

---

## Curriculum map

| Week | Focus | Retention / gate |
|------|-------|------------------|
| 1 | Transport, DNS, CDN | [Week-01](Retention-Tests/Week-01.md) |
| 2–3 | Storage + distributed theory | [Weeks 2–3](Retention-Tests/Weeks-02-and-03.md) |
| 4 | Replication, sharding, Raft | [Week-04](Retention-Tests/Week-04.md) |
| 5 | Database internals | [Week-05](Retention-Tests/Week-05.md) |
| 6 | Architecture patterns | [Week-06](Retention-Tests/Week-06.md) |
| 7 | Specialized components | [Week-07](Retention-Tests/Week-07.md) |
| 8 | Advanced patterns + observability | [Week-08](Retention-Tests/Week-08.md) |
| **08b** | Trust, cost, multi-tenancy | [Week-08b](Retention-Tests/Week-08b.md) |
| **08c** | Ops hardening | [Week-08c](Retention-Tests/Week-08c.md) |
| 9–14 | Design problems | Week retention + Designs transfer |
| **15** | Timed SD mocks | Rubric + Timed OS |
| **15b** | Behavioral SRE / leadership | [Week-Behavioral](Retention-Tests/Week-Behavioral.md) |
| **15c** | SRE LLD (limiter, cache, pool) | [Week-15c](Retention-Tests/Week-15c.md) |
| Playbooks | Meta / Netflix / Google SRE | [`company-playbooks/`](00-Curriculum/company-playbooks/) |
| 16 | Final mastery | Capstone + final retention |

---

## Tooling (structure only — not a quality score)

```bash
python3 tools/audit_curriculum.py
python3 tools/check_boxes.py .
python3 tools/split_expert_answers.py
```

---

## Reading spine

*Designing Data-Intensive Applications* (Kleppmann) — pages cited per module.
