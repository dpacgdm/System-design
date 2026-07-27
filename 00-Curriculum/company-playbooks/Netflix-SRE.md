# Netflix SRE / Cloud Infrastructure — Loop Playbook

**Use with:** Timed Interview OS · Week-15b culture maps · Week-15c LLD  
**Tone target:** Context-rich decisions, candor, high ownership, resilience judgment (not chaos theater).

---

## What Netflix-style loops usually probe

| Loop | What "good" looks like | Common fail |
|------|------------------------|-------------|
| Coding | Clarity, pragmatism, edge honesty | Over-engineering |
| System design | Playback/edge/data plane realism; failure as default | Ignoring regional/CDN reality |
| Behavioral | Candor, context not control, owning outcomes | Politics; hiding bad news |
| Reliability | Chaos-informed thinking, graceful degradation | "We page and heroically fix" only |

Expect strong emphasis on **distributed failure**, **multi-region**, and **operability**.

---

## Timeboxing defaults

| Interview | Minutes | Forced beats |
|-----------|--------:|--------------|
| Coding | 35–45 | Approach clarity > clever tricks |
| SD | 45–60 | Requirements → failure modes early → degradation |
| Behavioral | 45 | Candor prompts + disagreement |
| LLD | 30–45 | Concurrency + backpressure |

---

## Signal amplification (Netflix)

Lead with **context you gave/sought**, **the call you owned**, and **what you made resilient**.

**Bridge sentence pattern:**  
"Given context X (SLO, audience, cost), I chose Y over Z because failure mode F was unacceptable; here's how we degraded…"

**Avoid:** permission-seeking when the call was yours; cruelty cosplay as candor; buzzword "chaos" without a hypothesis.

---

## System design — Netflix-flavored rubric extras

1. **Failure first:** what breaks at the edge, in the region, in the dependency.
2. **Degradation paths:** personalized → popular → static; never binary dead.
3. **Data plane vs control plane:** separate fate.
4. **Multi-region active:** consistency vs availability tradeoffs said out loud.
5. **Observability:** what you'd watch in the first 5 minutes of an incident.

Tie to: queues, bulkheads, caches, rate limits, Week-08 geo/clocks.

---

## Behavioral — Netflix story packing

| Prompt class | Foreground |
|--------------|------------|
| Candor | Hard feedback with care + outcome |
| Disagreement | Context shared; you still owned a call |
| Failure | Fast truth on the bridge; no blame theater |
| Freedom | You acted without waiting; you informed |

Candor ≠ aggression. Staff bar: specific dialogue + relationship intact + result.

---

## LLD expectations

Worker pools, caches, rate limits under **overload** — reject policies, fail-open honesty, dependency timeouts. Week-15c Worker Pool blind transfer is on-brand.

---

## Day-of checklist

```text
[ ] 3 Netflix-shaped openings (context → call → resilience)
[ ] SD mock with explicit degradation path
[ ] Behavioral candor story Staff pass
[ ] LLD pool or limiter under failure table
[ ] No culture karaoke ("Freedom & Responsibility" as a slogan)
```

---

## Red flags to purge

- Waiting for consensus on a clear reliability risk
- Hiding a SEV from partners "until we know more" for too long
- Designing only the happy path for streaming/edge
- Claiming chaos experiments without safety / hypothesis / abort criteria

---

## Practice prompts (Netflix-shaped)

1. Design a regional playback authorization path that fails open or closed — defend.
2. Tell me about a time you gave hard feedback that changed on-call quality.
3. Whiteboard a worker pool for fan-out to mid-tier; avoid deadlock; shed load.
4. Dependency latency triples in one AZ — walk degradation for a read-heavy API.

---

## Post-loop notes template

```text
Company: Netflix
What they probed:
Where I was slow:
Story that landed / didn't:
Follow-up to drill:
```
