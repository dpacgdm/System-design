# Distributed Systems & System Design Mastery

A structured, production-grade curriculum for distributed systems and system design.
Depth target: principal engineer / staff SRE — not surface-level interview prep.

**Status (2026-07-06):** **9.8/10 quality audit** — all 16 weeks, full 12-section gold standard on teaching modules, expanded retention tests. Reference: [CDN Fundamentals](Week-01-Transport-Application-Protocols-DNS-CDN/CDN%20Fundamentals.md).

---

## How to Use This Repo

1. Read modules in week order — topics chain intentionally (TCP HOL → HTTP/2 → HTTP/3 → CDN).
2. Each module: learn the full teaching section before opening retention tests.
3. Worked answer files are for self-check after attempting scenarios yourself.
4. Process notes live in `00-Curriculum/` only — topic files are learning content.

### Topic File Standard (12 sections)

| # | Section | Purpose |
|---|---------|---------|
| 1 | Learning objectives | What you can do after |
| 2 | Wrong mental models | Destroy misconceptions first |
| 3 | Core teaching | Mechanisms, diagrams, math |
| 4 | Concrete examples | Real systems, real configs |
| 5 | Production patterns | How teams actually ship this |
| 6 | Failure modes | What breaks in prod |
| 7 | SRE diagnostic toolkit | Commands, metrics, log patterns |
| 8 | Decision framework | When to use X vs Y |
| 9 | Incident scenario | Multi-symptom, no hand-holding |
| 10 | Expert analysis | Full worked response |
| 11 | Key takeaways | 5 bullets max |
| 12 | Targeted reading | Specific pages, not "read DDIA" |

---

## Curriculum Map (All Weeks Complete)

| Week | Focus | Modules | Retention |
|------|-------|---------|-----------|
| 1 | Transport, DNS, CDN | 6 | [Week-01](Retention-Tests/Week-01.md) |
| 2 | Storage fundamentals | 3 | [Weeks 2–3](Retention-Tests/Weeks-02-and-03.md) |
| 3 | Distributed systems theory | 3 | (combined w/ Week 2) |
| 4 | Replication, sharding, Raft | 5 + worked answers | [Week-04](Retention-Tests/Week-04.md) |
| 5 | Database internals | 4 + worked answers | [Week-05](Retention-Tests/Week-05.md) |
| 6 | Architecture patterns | 6 | [Week-06](Retention-Tests/Week-06.md) |
| 7 | Specialized components | 5 | [Week-07](Retention-Tests/Week-07.md) |
| 8 | Advanced patterns + observability | 6 | [Week-08](Retention-Tests/Week-08.md) |
| 9 | WhatsApp + Twitter feed designs | 2 + compound scenario | — |
| 10 | YouTube + Uber designs | 2 + compound scenario | — |
| 11 | Payment + e-commerce designs | 2 + compound scenario | — |
| 12 | Google Search + web crawler | 2 + compound scenario | — |
| 13 | KV store + Kafka + config store | 3 + compound scenario | — |
| 14 | Google Docs + LLM + feature store | 3 + compound scenario | — |
| 15 | Mock interviews | 7 | — |
| 16 | Final mastery | 6 (checklists + capstone) | [Final test](Week-16-Final-Mastery/Final%20Retention%20Test%20All%20Topics.md) |

---

## Meta / Process

- [Handoff Doc](00-Curriculum/Handoff%20Doc.md) — learner profile, scores, growth areas
- [Roadmap Completion Tracker](00-Curriculum/Roadmap%20Completion%20Tracker.md) — quality audit + tooling

### Quality tooling

```bash
py tools/audit_curriculum.py    # section compliance scan
py tools/fix_gold_standard.py   # header normalization
py tools/push_98_quality.py     # targeted section inserts
py tools/fix_boxes.py .         # ASCII box width normalization
```

---

## Reading Spine

Primary: *Designing Data-Intensive Applications* (Kleppmann) — specific chapter pages
are cited per module, not generically.
