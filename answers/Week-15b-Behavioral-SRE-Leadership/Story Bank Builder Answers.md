# Answer Key — Story Bank Builder

## Gold-standard card example (Card #1 SEV)

TITLE: Checkout retry storm after breaker disabled
TAGS: failure, reliability, ambiguity
SITUATION: 19:00 flash browse spike; payment-authorize p99 920ms; checkout errors 4%; breaker.maxFailures raised to effectively off.
TASK: I was primary on-call for checkout SRE.
ACTIONS:
- At T+0 declared SEV2; pinned roles (comms, primary, fixer)
- At T+3 ruled out DB CPU (45%); found config diff
- At T+6 reverted breaker; reduced retries 12→3
- Rejected immediate horizontal pod scale-as-first-move (would amplify dependency)
RESULT: errors <0.3% by T+12; no data corruption; postmortem severity confirmed SEV2
LESSON: config policy + unit test for breaker defaults; load test retry matrix
LANDMINES:
- Differently: check config diff at T+1 not T+5
- Others: app eng applied known patch I reviewed
- My idea: yes on revert order; partner suggested retry reduction

## Card QA checklist (must all pass)
[ ] Stakes number in Situation
[ ] I-decision verbs in Actions (≥2)
[ ] Rejected alternative
[ ] Result evidence
[ ] Durable lesson
[ ] ≥3 landmines answered
[ ] Sanitized secrets

## Fail examples
- “We restarted pods and it got better” → no mechanism, no ownership
- “SEV1 where I watched” → wrong card for leadership prompts
