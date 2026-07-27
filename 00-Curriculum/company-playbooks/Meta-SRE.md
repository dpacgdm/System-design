# Meta SRE / Production Engineering — Loop Playbook

**Use with:** Timed Interview OS · Week-15b culture maps · Week-15c LLD  
**Tone target:** Impact-owned, user-numbered, bias to reversible action, partnership with product.

---

## What Meta-style loops usually probe

| Loop | What "good" looks like | Common fail |
|------|------------------------|-------------|
| Coding | Clean, correct, tests, edge cases; narrate | Silent coding; missed edges |
| System design | Product constraints + scale numbers + operability | Pure abstract boxes |
| Behavioral | End-to-end ownership; peer conflict with outcome | "We" fog; no impact metric |
| Reliability / PE | Incidents, capacity, safe rollout, toil reduction | Heroics without prevention |

Titles vary (SRE, Production Engineer, Infrastructure). Treat reliability + large-scale systems as the core.

---

## Timeboxing defaults

| Interview | Minutes | Forced beats |
|-----------|--------:|--------------|
| Coding | 35–45 | Restate → approach → code → tests |
| SD | 35–45 | Requirements → capacity → API/data → deep dive → failures |
| Behavioral | 30–45 | STAR-L ×2; Meta-shaped openings |
| LLD | 25–40 | Rate limiter / cache / pool — concurrency + ops |

---

## Signal amplification (Meta)

Lead with **user/business impact numbers**, then your **owned decision**, then speed of learning.

**Bridge sentence pattern:**  
"I owned X end-to-end; the user impact was Y; I shipped Z behind a flag in N days and measured…"

**Avoid:** waiting for perfect design; "not my team's code"; culture karaoke about Move Fast.

---

## System design — Meta-flavored rubric extras

1. **Product clarity first:** feed vs messaging vs ads constraints differ — ask.
2. **Scale honesty:** DAU → QPS → storage; don't invent Meta-scale unless they set it.
3. **Rollout:** flags, canaries, staged exposure — Meta interviewers like safe velocity.
4. **Cross-team:** dependencies, ownership boundaries, what you'd build vs reuse.
5. **Ops:** metrics, alarms, overload — tie to Week-08 / 08b / 08c.

Deep-dive favorites for SRE: caching, rate limits, queues, multi-region, consistency under partition.

---

## Behavioral — Meta story packing

| Prompt class | Foreground |
|--------------|------------|
| Conflict | Partnership + data + reversible proposal |
| Failure | Fast detect → mitigate → prevent; numbers |
| Ambiguity | You set a milestone and shipped a slice |
| Impact | Before/after metric you moved |

Rewrite openings using Week-15b Story Bank with Meta column filled.

---

## LLD expectations

Expect **rate limiter**, **cache**, or **concurrency pool** style questions. Pass bar = Week-15c Staff: atomicity, failure modes, metrics — not class-diagram theater.

---

## Day-of checklist

```text
[ ] 3 Meta-shaped story openings (≤40 words each)
[ ] 1 SD mock scored Meets Bar + comms ≥3
[ ] 1 LLD (limiter or cache) Staff pass
[ ] Impact numbers on every story card
[ ] No answer keys mid-mock
```

---

## Red flags to purge from answers

- "I waited for architecture review for six weeks" (without forcing progress)
- "Someone else's service caused it" (no ownership of mitigation)
- Perfect uptime cosplay with no tradeoffs
- Ignoring mobile / global latency when the prompt is consumer-scale

---

## Practice prompts (Meta-shaped)

1. Design a news-feed ranking fanout path for N M DAU — focus reliability under deploy.
2. Tell me about a time you unblocked a launch without owning the product team.
3. Whiteboard an LRU cache used on the request path; discuss stampede after a config push.
4. SEV: edge cache purge storm hits checkout — first 15 minutes.

---

## Post-loop notes template

```text
Company: Meta
What they probed:
Where I was slow:
Story that landed / didn't:
Follow-up to drill:
```
