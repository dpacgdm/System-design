# Answer Key — Feature Flags and Progressive Delivery

> Open only after attempting the learner file questions.

## Expert Analysis

```
This section intentionally contains scenario questions only.
Worked responses belong in Retention-Tests/Week-07.md when
that file is authored.

Use the seven questions above for self-assessment and mock
incident drills. A principal-grade response to Question 2
should be executable by another engineer without clarification.

PARTIAL HINTS (not full answers — retention test has worked solutions):

  Q1(a): Broken hybrid paths ≈ P(A⊕B) for independent 25% flags.
         P(both on) = 0.25×0.25 = 6.25% happy path.
         P(A only) = P(B only) = 0.25×0.75 ≈ 18.75% each → broken.
         Total broken ≈ 37.5% of users who hit new-checkout cohort
         (plus legacy users hitting new-payments-only path).

  Q2(a): Flip new-checkout first (removes largest broken surface),
         then new-payments-v2 (stops legacy users hitting v2 payments).

  Q3(a): Circuit breakers trip on failure RATE to dependency calls.
         Validation errors may be caught in-app before 5xx propagates,
         or returned as 200 with error payload — CB sees success.

  Q4(a): Prerequisite: release.new-checkout requires release.new-payments-v2.
```

---
