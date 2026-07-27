# Google SRE — Loop Playbook

**Use with:** Timed Interview OS · Week-15b culture maps · Week-15c LLD  
**Tone target:** Measured risk, SLO/error-budget fluency, precise mechanisms, blameless prevention.

---

## What Google SRE-style loops usually probe

| Loop | What "good" looks like | Common fail |
|------|------------------------|-------------|
| Coding | Correctness, complexity, clean structure | Messy invariants |
| System design / reliability | SLOs, capacity, consistency, failure domains | Hand-wavy "just shard" |
| Behavioral | Principled tradeoffs; learning systems | Heroics; blame |
| Troubleshooting | Hypotheses + disconfirming evidence | Tunnel vision |

Expect comfort with **The SRE Book** ideas without quoting chapters as answers.

---

## Timeboxing defaults

| Interview | Minutes | Forced beats |
|-----------|--------:|--------------|
| Coding | 45 | Tests + complexity |
| SD / reliability | 45 | SLO → capacity → design → failure |
| Behavioral | 30–45 | Judgment under constraints |
| LLD | 30–45 | Correctness under concurrency |

---

## Signal amplification (Google SRE)

Lead with **SLO / error budget math**, **blast radius**, and **prevention**.

**Bridge sentence pattern:**  
"Against SLO S, burn rate B implied exhaustion in T; I chose mitigation M that preserved invariant I; prevention was P."

**Avoid:** "five nines" without cost; heroics as culture; blame; vague "distributed consensus" drops.

---

## System design — Google-flavored rubric extras

1. **SLI/SLO/SLA** distinguished; error budget as release governor.
2. **Capacity plan:** peak, headroom, failure capacity (N-1).
3. **Consistency model** named; stale windows quantified when possible.
4. **Control vs data plane**; blast radius of config.
5. **Toil** awareness: automatable operational work called out.

Deep dives: consensus-ish systems, KV, rate limit, caching, migration (08c), multi-tenant (08b).

---

## Behavioral — Google story packing

| Prompt class | Foreground |
|--------------|------------|
| Disagreement | Budget math vs feature pressure |
| Failure | Wrong hypothesis withdrawn; evidence |
| Toil | Measured hours → automation → recurrence proof |
| Influence | Principles + docs + reversible change |

---

## LLD expectations

High bar on **correctness**: atomic rate limit, cache races, pool deadlocks. Prefer precise vocabulary (invariant, quorum, deadline) used accurately.

---

## Day-of checklist

```text
[ ] Error-budget story ready with numbers
[ ] SD mock names SLIs/SLOs explicitly
[ ] LLD rate limiter Staff (atomicity + fail mode)
[ ] Troubleshooting drill: hypothesis → disconfirm
[ ] No fake precision (made-up "Google numbers")
```

---

## Red flags to purge

- Heroic all-nighter as the *lesson* (lesson should be prevention)
- "We don't need SLOs because we move fast"
- Consensus name-drop without what breaks if a node dies
- Ignoring cost/toil of your beautiful design

---

## Practice prompts (Google-shaped)

1. Define SLIs for a global KV read path; set SLO; walk burn-rate alert policy.
2. Whiteboard rate limiter with Redis failure modes and error-budget impact of fail-open.
3. Tell me about a time you said no to a launch using budget math.
4. Migration: dual-write cutover — invariants, abort criteria, observability (Week-08c).

---

## Concepts to be fluent in (non-karaoke)

| Concept | Must be able to say |
|---------|---------------------|
| Error budget | Remaining unreliability; governs release risk |
| Burn rate | Speed of budget consumption; multi-window alerts |
| Toil | Manual, repetitive, automatable ops work |
| Blameless | Fix systems/incentives; still name owning actions |
| N-1 capacity | Serve peak with one failure domain down |

---

## Post-loop notes template

```text
Company: Google SRE
What they probed:
Where I was slow:
Story that landed / didn't:
Follow-up to drill:
```
