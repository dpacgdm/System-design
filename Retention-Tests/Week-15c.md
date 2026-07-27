# Retention — Week-15c SRE LLD

Questions only. Do not open `answers/`. Timed preferred: **40 minutes**.

## Rules
1. Sketch APIs and concurrency; prose without structure scores below bar.
2. Name failure modes with signals, not vibes.
3. Score with module grading bars after.

---

## Part 1 — Rapid-fire

**Q1:** Token bucket vs fixed window — one failure mode unique to fixed window.
**Q2:** Why is check-then-decr from the app (no Lua/mutex) wrong under concurrency?
**Q3:** When is FAIL_CLOSED correct for a rate limiter? When is FAIL_OPEN?
**Q4:** Name two invariants of an LRU cache (map + doubly linked list).
**Q5:** What does single-flight prevent, and what does it *not* prevent when many keys expire together?
**Q6:** Why is unbounded `LinkedBlockingQueue` dangerous in a production worker pool?
**Q7:** State the classic same-pool deadlock pattern in one sentence.
**Q8:** CPU idle, `active_workers` at max, `queue_depth` flat — what class of bottleneck?

---

## Part 2 — Applied sketches

**Q9:** Redis token bucket key schema + 5 Lua steps (bullets). Include idle TTL.
**Q10:** Sketch `getOrLoad` including inflight map and failure behavior.
**Q11:** Size an IO-bound fan-out pool: give `n` formula, how you pick `Q`, and reject policy for a latency-sensitive HTTP API.

---

## Part 3 — Compound

**Q12:** Northstar checkout pods use in-process LRU (TTL 2m) + Redis rate limiter (FAIL_OPEN) + shared executor for handler and fan-out. Symptom: intermittent 503s, origin DB CPU spikes every ~2m, Redis timeouts during a regional blip. Walk: (a) three contributing mechanisms, (b) first safe mitigations in order, (c) one durable design fix for the pool.

---

## Part 4 — Blind transfers

**Q13:** Rate limiter allows bursts of 100; batch client sends 100, sleeps 1ms, repeats — production melts. What was missed?
**Q14:** Config push TTL 5m → 5s — origin burns. Safer rollout?

> Answers: [`../answers/Retention-Tests/Week-15c Answers.md`](../answers/Retention-Tests/Week-15c%20Answers.md)
