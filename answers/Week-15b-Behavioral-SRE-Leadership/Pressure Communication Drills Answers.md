# Answer Key — Pressure Communication Drills

## Drill A exemplar (60s)
Headline: I stopped a checkout flag that was burning the monthly error budget in hours.
Stakes: p99 1.8s vs 300ms SLO; 4% failures.
Action: killed flag; verified cell capacity; watched burn rate.
Result: recovered in 11 minutes.
Lesson: burn-rate alert + launch checklist item.

## Drill B scoring
Require Communication scorecard all ≥3; if interrupt recovery <3, fail session even if content is good.

## Drill C note
Verbal rate limiter design should use pyramid: requirements → single box algorithm → failure modes → scale — stop and check-in before distributed edge cases.

## Common fixes
- Cut preamble
- Numbers before architecture
- Label beats when resuming after interrupt
