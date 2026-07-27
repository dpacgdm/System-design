# Answer Key — FAANG Culture Maps

## Q1 — Three openings
Meta: lead with user/$ impact and speed of mitigation.  
Netflix: lead with candid disagreement + owned decision.  
Google: lead with SLO/error budget math and safe mitigation invariant.

## Q2 — Too slow?
Meta Staff: acknowledge opportunity cost; show parallelization / flagged ship you proposed.  
Google Staff: defend measurement if risk was real; show reversible steps you took to regain speed.

## Q3 — Blame repair
“I described their incentive poorly. Product was optimizing launch date; I failed to translate reliability into their metric early. Here’s how I repaired…”

## Q4 — Banned → replacements
“Freedom and responsibility” → show a decision you owned with context.  
“We move fast” → cite impact + mitigation time.  
“I crush toil” → show pages deleted and proof.  
“Blameless” → show what you changed in the system.  
“Synergy” → delete.


---

## Worked retarget of one incident (skeleton filled)

**Facts:** Flag rollback during checkout SLO burn; conflict with product on launch.

**Meta opening:** “Checkout errors hit 4% and we were losing ~$Y/min; I drove a flag kill in 6 minutes and protected launch on non-critical surfaces the same day.”

**Netflix opening:** “I disagreed with shipping the fanout onto checkout as-is. I put the burn math on the table, owned the rollback default, and stayed accountable for the bake alerts.”

**Google opening:** “Error budget burn projected exhaustion in 11 days at the proposed latency delta. I chose a flagged non-critical-path ship to preserve the checkout invariant.”

## Red-flag repairs

| Bad | Repair |
|-----|--------|
| Quoting culture memo | Replace with behavior evidence |
| “I don’t do politics” | Show incentive translation |
| Absolutist reliability | Use error budgets |
