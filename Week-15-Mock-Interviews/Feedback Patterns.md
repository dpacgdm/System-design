# Feedback Patterns — System Design Mastery

## Learning Objectives

```
╔════════════════════════════════════════════════════════════════╗
║   AFTER THIS MODULE, YOU WILL BE ABLE TO:                      ║
╟────────────────────────────────────────────────────────────────╢
║                                                                ║
║   1. Give structured, actionable feedback on mock              ║
║      system design interviews using the 8-dimension rubric     ║
║                                                                ║
║   2. Receive feedback without defensiveness — extract          ║
║      the signal and ignore the noise                           ║
║                                                                ║
║   3. Use Situation-Behavior-Impact (SBI) adapted for           ║
║      system design: quote specific moments, not vibes          ║
║                                                                ║
║   4. Calibrate feedback to target level (L4/L5/L6/Principal)   ║
║      so expectations match the role                            ║
║                                                                ║
║   5. Convert feedback into a 2-week study plan mapped          ║
║      to specific curriculum modules (Weeks 1–14)               ║
║                                                                ║
║   6. Run effective peer mock sessions with clear               ║
║      roles, timing, and written deliverables                   ║
╚════════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔══════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Good feedback = telling them what to build"  ║
╟──────────────────────────────────────────────────────────────────╢
║   WRONG. Feedback describes WHAT HAPPENED in the interview       ║
║   and its IMPACT on the score — not your preferred architecture. ║
║   "You should have used Cassandra" is advice, not feedback.      ║
╠══════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "If they didn't hire me, the feedback         ║
║   was wrong"                                                     ║
╟──────────────────────────────────────────────────────────────────╢
║   WRONG. Interview feedback and hiring decisions diverge.        ║
║   A Lean No can still produce excellent growth feedback.         ║
║   Extract the dimension gaps, not the verdict.                   ║
╠══════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "Praise builds confidence; criticism hurts"   ║
╟──────────────────────────────────────────────────────────────────╢
║   WRONG. Vague praise ("great job!") teaches nothing.            ║
║   Vague criticism ("needs more depth") is unusable.              ║
║   Specific positive feedback reinforces repeatable behaviors.    ║
╠══════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "The interviewer knows my design is better"   ║
╟──────────────────────────────────────────────────────────────────╢
║   WRONG. In a mock, the rubric IS the bar. If you cannot         ║
║   defend a decision under probe, the score reflects that —       ║
║   regardless of what you'd ship at your current company.         ║
╠══════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Feedback once is enough"                     ║
╟──────────────────────────────────────────────────────────────────╢
║   WRONG. System design skill is iterative. One mock without      ║
║   written feedback, self-review, and a study plan is theater.    ║
║   The loop is: mock → score → feedback → study → re-mock.        ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## The Feedback Framework: SBI for System Design

Standard Situation-Behavior-Impact (SBI) works for performance reviews. System design interviews need a fourth element: **Rubric Dimension**.

```
╔════════════════════════════════════════════════════════════════════╗
║   SBI-R FRAMEWORK (Situation → Behavior → Impact → Rubric)         ║
╠════════════════════════════════════════════════════════════════════╣
║                                                                    ║
║   S — SITUATION (WHEN / WHERE in the interview)                    ║
║       Anchor to clock time or phase:                               ║
║       "At minute 12, during capacity estimation..."                ║
║       "When probed on cache failure at minute 35..."               ║
║                                                                    ║
║   B — BEHAVIOR (WHAT they said or did — quote if possible)         ║
║       Observable, not inferred:                                    ║
║       "You said 'we'll shard the database' without calculating     ║
║        shard count or partition key."                              ║
║       NOT: "You don't understand sharding."                        ║
║                                                                    ║
║   I — IMPACT (EFFECT on score, prod readiness, interviewer trust)  ║
║       Tie to rubric and production reality:                        ║
║       "This dropped Capacity Estimation to 2 — the interviewer     ║
║        couldn't verify your sharding design would work at scale."  ║
║                                                                    ║
║   R — RUBRIC DIMENSION (WHICH of the 8 dimensions)                 ║
║       Always name the dimension explicitly:                        ║
║       "Dimension 2: Capacity Estimation"                           ║
║                                                                    ║
╚════════════════════════════════════════════════════════════════════╝
```

### SBI-R Template (Copy-Paste for Peer Mocks)

```
SITUATION:  At minute [__], during [requirements / math / architecture / deep dive / failure modes]...
BEHAVIOR:   You [said / did / skipped] "[exact quote or action]"
IMPACT:     This [helped / hurt] because [interviewer could/couldn't follow / design would break in prod because...]
DIMENSION:  [1–8 name] — suggested score adjustment: [none / note for final scoring]
NEXT:       Try instead: "[exact phrase or action for next mock]"
```

### Example: Strong SBI-R (Positive)

```
SITUATION:  At minute 3, before drawing any boxes...
BEHAVIOR:   You asked "Is this read-heavy or write-heavy? What's the
             acceptable p99 for timeline load?" and waited for answers.
IMPACT:     Interviewer could steer the design driver early. Requirements
             dimension scored 4 — you set the ceiling for the rest of the session.
DIMENSION:  1 — Requirements & Scope
NEXT:       Repeat this opening on every mock; add consistency model question
             for stateful systems.
```

### Example: Strong SBI-R (Constructive)

```
SITUATION:  At minute 28, when asked to deep dive on feed fan-out...
BEHAVIOR:   You repeated the high-level diagram and said "Kafka handles
             the fan-out" without explaining partition key, ordering, or
             celebrity user handling.
IMPACT:     Deep Dive scored 2 — interviewer couldn't assess whether you'd
             survive a Justin Bieber post. Hiring signal paused here.
DIMENSION:  5 — Deep Dive
NEXT:       Pick ONE fan-out strategy, state write amplification math, name
             hybrid approach for celebrities. Study: Week 9 Design Twitter Feed.
```

---

## Dimension-Specific Feedback Templates

Use these verbatim as starting points. Replace bracketed placeholders with interview specifics.

### Dimension 1: Requirements & Scope

```
POSITIVE TEMPLATE:
"At minute [X], you summarized requirements back: '[quote]'. That confirmed
 scope with the interviewer and prevented designing [wrong feature]. Score: 3–4."

CONSTRUCTIVE TEMPLATE:
"You started drawing at minute [X] without clarifying [read/write ratio /
 consistency / geographic scope]. Result: you designed [over-scoped feature]
 that wasn't asked for. Ask: 'Before I design, what's P0 vs defer-to-v2?'"

PROBE IF MISSING:
"What are the top 3 things this system must do well?"
"What's acceptable latency for [critical operation]?"
```

### Dimension 2: Capacity Estimation

```
POSITIVE TEMPLATE:
"You derived [X] write QPS from DAU × actions/day × peak factor, then connected
 it to [shard count / cache size]. Math drove the architecture — score 4."

CONSTRUCTIVE TEMPLATE:
"You said 'millions of QPS' without showing work. At [stated DAU], peak write
 QPS is closer to [Y]. Recalculate before choosing [Kafka partitions / DB shards]."

SANITY CHECK PHRASE:
"Walk me through that calculation again — I want to see peak factor."
```

### Dimension 3: API & Data Model

```
POSITIVE TEMPLATE:
"You defined [endpoint] with [request/response fields] and chose [partition key]
 because [access pattern]. Data model matched read path — score 3–4."

CONSTRUCTIVE TEMPLATE:
"APIs were listed as 'CRUD for users' without shapes. The hot query
 [get feed for user X] has no table/index to serve it. Define access
 patterns BEFORE storage engine."

REDIRECT PHRASE:
"Show me the schema for the query you mentioned — how is it indexed?"
```

### Dimension 4: High-Level Architecture

```
POSITIVE TEMPLATE:
"Diagram had [N] labeled components with numbered flow on the critical path.
 Sync vs async split was clear. Score 3–4."

CONSTRUCTIVE TEMPLATE:
"[N]-box diagram with no arrows or labels — interviewer couldn't follow
 request lifecycle. Simplify to 5–8 components; walk one read and one write."

MISSING COMPONENT CALLOUT:
"You have persistent data but no object store / no cache / no LB — was that
 intentional? If not, add before deep dive."
```

### Dimension 5: Deep Dive

```
POSITIVE TEMPLATE:
"On [fan-out / ledger / consistent hash], you went [3] levels deep:
 [algorithm], [config], [edge case: hot key / celebrity]. Production-grade — score 4."

CONSTRUCTIVE TEMPLATE:
"Deep dive stayed at technology names ('Redis', 'Elasticsearch') without
 mechanics. Interviewer asked [X] three times — you didn't reach implementation
 depth. Next mock: prep one deep dive per problem type."

DEPTH LADDER PROMPT:
"What's the partition key? What happens on rebalance? What's the p99 under 10× traffic?"
```

### Dimension 6: Trade-offs & Alternatives

```
POSITIVE TEMPLATE:
"For [decision], you said 'I chose X because [requirement]; cost is [Y];
 I'd flip to Z if [condition].' That's a complete trade-off — score 4."

CONSTRUCTIVE TEMPLATE:
"'We'll use microservices' with no alternative considered. Name one rejected
 option and what you gave up: operational complexity, latency, consistency."

CHALLENGE PHRASE:
"What's the biggest weakness in your design?"
```

### Dimension 7: Failure Modes & Reliability

```
POSITIVE TEMPLATE:
"You named [cache stampede / split brain / poison message] with detection
 ([metric/alert]) and mitigation ([degradation path]). Score 3–4."

CONSTRUCTIVE TEMPLATE:
"No failure modes until minute 40 when prompted. 'Replicate for HA' isn't
 analysis — pick 3 things that break FIRST in YOUR design."

REQUIRED PROMPT:
"What breaks first if the cache layer dies completely?"
```

### Dimension 8: Communication & Structure

```
POSITIVE TEMPLATE:
"You checked in at minute [15]: 'Does this direction make sense?' and
 summarized decisions at transitions. Collaborative — score 4."

CONSTRUCTIVE TEMPLATE:
"[5+] minute silent drawing at minute [20–25]. Interviewer lost thread.
 Narrate out loud; use time boxes: '5 more minutes on API, then architecture.'"

TIME BOX PHRASE:
"We're at minute 25 — I want to ensure we reach deep dive. OK to move on?"
```

---

## Positive Feedback Patterns (Say This, Not That)

Twenty-plus examples. **Say this** is actionable praise tied to rubric behavior.

| # | Say This (Specific) | Not That (Vague) | Dimension |
|---|---------------------|------------------|-----------|
| 1 | "Your opening question on read/write ratio changed the storage choice — keep that." | "Good start." | 1 |
| 2 | "Summarizing requirements at minute 4 prevented scope creep — do every time." | "Nice requirements." | 1 |
| 3 | "You stated MVP vs v2 explicitly; that saved 10 minutes." | "Good scoping." | 1 |
| 4 | "Peak QPS math with 3× factor was correct and you sanity-checked egress." | "Good math." | 2 |
| 5 | "Connecting storage growth to shard count in year 3 — that's L6 signal." | "Numbers were fine." | 2 |
| 6 | "You separated hot path QPS from batch jobs — often missed." | "Detailed estimates." | 2 |
| 7 | "Partition key `user_id` matches the feed query — data model drove design." | "Good schema." | 3 |
| 8 | "Pagination cursor on the API showed you've shipped this before." | "APIs looked OK." | 3 |
| 9 | "Choosing DynamoDB for writes + Elasticsearch for search — polyglot done right." | "Good database choice." | 3 |
| 10 | "Numbered steps 1–6 on the read path — I could follow without asking." | "Clear diagram." | 4 |
| 11 | "Placing CDN at edge before ALB — correct for static asset NFR." | "Good architecture." | 4 |
| 12 | "Async fan-out via queue kept sync path under 100ms — well separated." | "Nice design." | 4 |
| 13 | "Celebrity hybrid fan-out: on-write for normal, on-read for >1M followers." | "Handled scale." | 5 |
| 14 | "Idempotency keys on payment API — you went to prod depth unprompted." | "Deep dive was strong." | 5 |
| 15 | "Explained Raft quorum on config store — interviewer didn't need to probe." | "Knew distributed systems." | 5 |
| 16 | "Named fan-out on write cost (1000 writes/post) AND when you'd flip." | "Good trade-offs." | 6 |
| 17 | "Acknowledged ops cost of running Kafka + Flink — rare at L5." | "Considered alternatives." | 6 |
| 18 | "Cache stampede mitigation: request coalescing + jitter — specific to design." | "Thought about failures." | 7 |
| 19 | "Graceful degradation: stale feed OK, payments must fail closed — correct." | "Good reliability." | 7 |
| 20 | "SLO: 99.9% feed load <200ms with error budget tied to deploy cadence." | "Mentioned monitoring." | 7 |
| 21 | "Minute-20 time check kept us on track for deep dive." | "Good communication." | 8 |
| 22 | "When I added multi-region constraint, you adapted without defensiveness." | "Flexible." | 8 |
| 23 | "You asked ME a clarifying question about compliance — collaborative." | "Engaged well." | 8 |
| 24 | "Transition summary at minute 15 locked in decisions before architecture." | "Well structured." | 8 |

---

## Constructive Feedback Patterns (Say This, Not That)

Twenty-plus examples. Constructive = SBI-R + one concrete next action.

| # | Say This (Actionable) | Not That (Harmful/Vague) | Dimension |
|---|----------------------|--------------------------|-----------|
| 1 | "Minute 0: you drew boxes before asking scale. Ask 5 questions first." | "You skipped requirements." | 1 |
| 2 | "You assumed global users when problem said US-only — confirm geography." | "Wrong assumptions." | 1 |
| 3 | "NFR 'fast' isn't measurable — ask for p99 latency target." | "Weak non-functionals." | 1 |
| 4 | "1B QPS for 1M DAU — off by 1000×. Recheck ops/user/day." | "Bad math." | 2 |
| 5 | "No bandwidth calc; egress cost drives CDN decision — add Step 4." | "Incomplete estimation." | 2 |
| 6 | "Skipped write QPS; this is write-heavy chat — reads mislead design." | "Estimation weak." | 2 |
| 7 | "One giant `posts` table; feed query needs fan-out table or index strategy." | "Schema too simple." | 3 |
| 8 | "SQL chosen by default; 100:1 read/write + flexible schema → consider NoSQL." | "Wrong database." | 3 |
| 9 | "No idempotency on POST /payment — double-charge risk in prod." | "API incomplete." | 3 |
| 10 | "20 unlabeled boxes — cut to 7 and label each in one line." | "Messy diagram." | 4 |
| 11 | "No load balancer in front of stateless tier — single point of failure." | "Architecture gaps." | 4 |
| 12 | "All sync HTTP for notifications — WebSocket or push needed for chat." | "Won't scale." | 4 |
| 13 | "Deep dive on login, not feed — interviewer redirected twice; prep hard part." | "Shallow." | 5 |
| 14 | "'Kafka' without partitions, keys, or consumer groups — go 2 levels deeper." | "Hand-wavy." | 5 |
| 15 | "Consistent hashing mentioned but virtual nodes / rebalancing skipped." | "Buzzwords." | 5 |
| 16 | "Single solution presented; name one alternative you rejected." | "No trade-offs." | 6 |
| 17 | "Defensive when challenged on CAP — engage: 'Under partition, I'd choose...'" | "Poor attitude." | 6 |
| 18 | "Flip-flopped SQL→NoSQL without new requirement — explain trigger." | "Inconsistent." | 6 |
| 19 | "Zero failure modes until prompted — list 3 before minute 35." | "No reliability." | 7 |
| 20 | "'Add retries' for payment timeout — need idempotency + DLQ, not blind retry." | "Naive mitigation." | 7 |
| 21 | "Silent 7 minutes at minute 22 — narrate or lose interviewer." | "Bad communication." | 8 |
| 22 | "Argued 'that's how we do it at work' — interview rubric ≠ your prod." | "Defensive." | 8 |
| 23 | "Ran out of time — skip perfect math at minute 20, prioritize architecture." | "Poor time mgmt." | 8 |
| 24 | "Ignored my hint on cache failure — treat probes as collaboration." | "Didn't listen." | 8 |

---

## Red Flag Phrases Interviewers Use (And What They Mean)

When you hear these, the interviewer is signaling a rubric gap. Map to dimension and response.

```
╔════════════════════════════════════════════════════════════════════╗
║   INTERVIEWER PHRASE          │ MEANING              │ DIMENSION   ║
╠════════════════════════════════════════════════════════════════════╣
║   "Walk me through that       │ Math unclear or      │ 2           ║
║    again?"                    │ wrong                │             ║
║   "What happens at scale?"    │ No capacity link     │ 2, 4        ║
║   "Let's take a step back"    │ Lost the thread      │ 8           ║
║   "What's the hardest part?"  │ You avoided core     │ 1, 5        ║
║   "What if X goes down?"      │ Failure modes gap    │ 7           ║
║   "What else did you         │ Trade-offs gap       │ 6            ║
║    consider?"                 │                      │             ║
║   "How would you query that?" │ Data model gap       │ 3           ║
║   "Is that always true?"      │ Overconfident claim  │ 5, 6        ║
║   "What would you cut?"       │ Over-scoped          │ 1           ║
║   "Let's dive deeper into Y"  │ High-level only on Y │ 5           ║
║   "How do you know it works?" │ No detection/SLO     │ 7           ║
║   "What about consistency?"   │ CAP/consistency gap  │ 3, 6        ║
║   "Interesting — tell me more"│ Skeptical; prove it  │ 5, 6        ║
║   "We have 5 minutes left"    │ Time risk; prioritize│ 8           ║
╚════════════════════════════════════════════════════════════════════╝
```

### How to Respond When You Hear a Red Flag Phrase

```
HEAR: "Walk me through that again?"
DO:   Pause. Rewrite on board. State assumptions aloud. Correct if wrong.
      "Let me recalculate — I used 10 ops/user/day, peak 3×, 10M DAU..."

HEAR: "What else did you consider?"
DO:   Name rejected alternative + cost. Don't flip — defend or explain pivot.
      "I considered fan-out on read — simpler writes but 500ms read at scale..."

HEAR: "Let's dive deeper into [X]"
DO:   Stop other topics. Draw second diagram for X. Go 3 levels deep.
      Algorithm → config → edge case.

HEAR: "What if the cache fails completely?"
DO:   Symptom → detection → degradation → recovery. Not "we'll restart."
      "Users see stale feed; origin absorbs 10× traffic; circuit breaker to..."
```

---

## Self-Feedback Protocol After Mock Interviews

Run this within 30 minutes of finishing. Do not wait for peer/interviewer notes.

```
╔═════════════════════════════════════════════════════════════════════╗
║   SELF-FEEDBACK PROTOCOL (30 MINUTES POST-MOCK)                     ║
╠═════════════════════════════════════════════════════════════════════╣
║                                                                     ║
║   STEP 1: SCORE YOURSELF (10 min)                                   ║
║   Use Interview Rubric worksheet. Score all 8 dimensions 1–4.       ║
║   Be harsh — self-scores average 0.5–1.0 above external scores.     ║
║                                                                     ║
║   STEP 2: TIMESTAMP REVIEW (10 min)                                 ║
║   If recorded: note minute marks where you lost momentum.           ║
║   If not: sketch timeline from memory:                              ║
║     0–5 req | 5–10 math | 10–15 API | 15–25 arch | 25–40 dive       ║
║                                                                     ║
║   STEP 3: THREE SBI-R STATEMENTS (5 min)                            ║
║   Write 1 positive + 2 constructive about YOURSELF.                 ║
║   Quote your own words where possible.                              ║
║                                                                     ║
║   STEP 4: ONE LEVER (5 min)                                         ║
║   Lowest dimension = next week's focus. ONE module from map below.  ║
║                                                                     ║
║   STEP 5: REDO DRILL (optional, same day)                           ║
║   15-min redo of ONLY the failed section (e.g., estimation only).   ║
║                                                                     ║
╚═════════════════════════════════════════════════════════════════════╝
```

### Self-Feedback Questions (Answer in Writing)

```
1. Which dimension scored lowest? Why — one specific moment?
2. Did I reach deep dive before minute 30?
3. Did I state 3+ failure modes without prompting?
4. Can I redo estimation from memory in 3 minutes?
5. Would I trust this design in production for 1 year?
6. Where did I go silent >3 minutes?
7. Did I summarize requirements back to interviewer?
8. When probed, did I engage or defend?
9. What one phrase will I use to open the NEXT mock?
10. What curriculum module will I study this week?
```

---

## Peer Feedback Protocol (Study Partner Mocks)

```
╔═════════════════════════════════════════════════════════════════════╗
║   PEER MOCK SESSION STRUCTURE (60 MINUTES)                          ║
╠═════════════════════════════════════════════════════════════════════╣
║                                                                     ║
║   ROLES:                                                            ║
║     Candidate — designs; drives first 5 min                         ║
║     Interviewer — holds rubric; probes; does NOT lead design        ║
║     Observer (optional) — takes timestamp notes only                ║
║                                                                     ║
║   MINUTE  0–2  │ Interviewer states problem + target level (L5)     ║
║   MINUTE  2–47 │ Interview (45 min)                                 ║
║   MINUTE 47–52 │ Candidate asks 2 questions                         ║
║   MINUTE 52–60 │ Feedback delivery (structured, written after)      ║
║                                                                     ║
║   SWAP ROLES next session. Same problem twice = wasted signal.      ║
║                                                                     ║
╚═════════════════════════════════════════════════════════════════════╝
```

### Interviewer Responsibilities

```
BEFORE:
  [ ] Pick problem from Week 9–14 (or compound scenario)
  [ ] Set target level (L4/L5/L6)
  [ ] Print/open scoring worksheet
  [ ] Prepare 2 constraint injections (minute 15, minute 30)

DURING:
  [ ] Let candidate drive first 5 minutes
  [ ] Note exact quotes with timestamps
  [ ] Redirect to hard part if avoided
  [ ] Do NOT teach during interview — save for feedback block

AFTER (within 24 hours):
  [ ] Send written feedback: scores + 3 SBI-R + 1 study module
  [ ] Total score /32 and hire signal band
```

### Feedback Delivery Script (Live, 8 Minutes)

```
MINUTE 52–54: "Overall you scored [X]/32. Strongest: [dimension]. Gap: [dimension]."
MINUTE 54–57: Deliver 2 constructive + 1 positive SBI-R (read verbatim from notes)
MINUTE 57–59: "One thing for next mock: [exact behavior change]"
MINUTE 59–60: Candidate repeats back the ONE lever — confirms understanding
```

### Peer Feedback Quality Bar

```
GOOD PEER FEEDBACK:
  → Timestamped quotes
  → Rubric dimension named
  → One curriculum module assigned
  → Delivered within 24 hours in writing

BAD PEER FEEDBACK:
  → "You did great, maybe more depth on Kafka"
  → Technology prescription without rubric link
  → No score, no next action
  → Debate about "correct" architecture for 30 minutes
```

---

## Feedback Calibration by Level

Same behavior scores differently by target level. Calibrate language.

### L4 (Entry Senior) — Expected 16–22

```
CALIBRATION:
  Praise: Solid architecture, clear communication, order-of-magnitude math
  Gap language: "At L4, failure modes when prompted is OK — aim for 1 unprompted"
  Don't penalize: Missing operational cost in trade-offs; single-region default
  Do penalize: Cannot walk request path; no data model; hostile communication

FEEDBACK PHRASE:
"For L4 this is on track at [score]. To reach L5, proactively name 3 failure
 modes and connect estimation to shard count."
```

### L5 (Senior) — Expected 20–26

```
CALIBRATION:
  Praise: Proactive requirements, 2–3 trade-offs, deep dive with correct algorithm
  Gap language: "L5 bar requires unprompted failure modes — you had 0 until minute 40"
  Don't penalize: Missing multi-region unless NFR requires it
  Do penalize: Hand-wavy deep dive; no alternatives; estimation errors >10×

FEEDBACK PHRASE:
"L5 hire signal needs Deep Dive ≥3 and Failure Modes ≥3. You're at 2 and 2.
 Next mock: prep fan-out OR ledger depth from Week 9/11."
```

### L6 (Staff) — Expected 24–29

```
CALIBRATION:
  Praise: Math drives infra sizing; cascade failures; ops cost in trade-offs
  Gap language: "L6 expects SLO/error budget reasoning — monitoring mention isn't enough"
  Don't penalize: Not knowing every AWS service name
  Do penalize: Requirements don't drive decisions; generic failure list

FEEDBACK PHRASE:
"Architecture meets L5. For L6: add 'when I'd flip' on 2 decisions and
 tie failure detection to SLI definitions — Week 8 SLOs module."
```

### Principal / L7 — Expected 27–32

```
CALIBRATION:
  Praise: Framework thinking; migration v1→v2; cost modeling; challenges premise
  Gap language: "Principal bar: organizational trade-off missing — who owns this service?"
  Don't penalize: Simpler diagram if reasoning is deeper
  Do penalize: No security/compliance woven in; cannot teach problem class

FEEDBACK PHRASE:
"Strong L6. Principal gap: no migration path from monolith and no infra $ estimate.
 Add v1 ship plan and 5-year TCO sketch in next mock."
```

### Level Calibration Table

| Total Score | L4 Signal | L5 Signal | L6 Signal | Principal Signal |
|-------------|-----------|-----------|-----------|------------------|
| 8–14 | Not ready | Not ready | Not ready | Not ready |
| 15–19 | Developing | Not ready | Not ready | Not ready |
| 20–24 | Strong L4 / borderline | Developing | Not ready | Not ready |
| 25–28 | Exceeds L4 | Meets / Strong L5 | Developing L6 | Not ready |
| 29–32 | — | Exceeds L5 | Meets / Strong L6 | Meets / Strong |

---

## Common Candidate Defense Patterns (And How to Respond)

When receiving feedback, candidates often deflect. Recognize the pattern; use the response.

```
╔═══════════════════════════════════════════════════════════════════════╗
║   DEFENSE PATTERN              │ RESPONSE (AS CANDIDATE)              ║
╠═══════════════════════════════════════════════════════════════════════╣
║   "At my company we..."        │ "Interview rubric ≠ prod. What's     ║
║                                │  the score on THIS answer?"          ║
║   "You didn't give me enough   │ "Fair — next mock I'll ask 5         ║
║    constraints"                │  clarifying questions first."        ║
║   "That technology works fine" │ "Choice OK if defended. I didn't     ║
║                                │  explain partition strategy — gap."  ║
║   "I would have gotten there"  │ "Clock matters. Practice reaching    ║
║                                │  deep dive by minute 28."            ║
║   "That's too detailed for     │ "Deep dive IS the interview at       ║
║    an interview"               │  L5+. I'll prep one path deeper."    ║
║   "Interviewer was wrong"        │ "Extract dimension gap anyway.     ║
║                                │  Mock partner ≠ real bar."           ║
║   "I knew that, just forgot"   │ "Forgotten in stress = not           ║
║                                │  interview-ready. Add to drill."     ║
║   "Everyone uses [X]"          │ "Commodity choice still needs        ║
║                                │  trade-off and failure modes."       ║
╚═══════════════════════════════════════════════════════════════════════╝
```

### As Feedback Giver: Handling Defensiveness

```
IF candidate argues architecture for >2 minutes:
  "I'm not scoring the design — I'm scoring whether you demonstrated
   [dimension]. Let's note the score and move to next mock prep."

IF candidate dismisses peer feedback:
  "Use the rubric in Interview Rubric.md. If you disagree with score,
   score yourself and compare — gap is learning data."

IF candidate blames problem statement:
  "Real interviews have ambiguous prompts. Skill is clarifying — that's
   Dimension 1."
```

---

## Written Feedback Templates (3 Complete Examples)

### Example A: Developing Candidate (Total 17/32) — Design Twitter Feed, L5 Target

```
MOCK INTERVIEW FEEDBACK
Candidate: [Name]          Date: [Date]
Problem: Design Twitter Feed (home timeline)    Target: L5
Interviewer: [Name]        Duration: 45 min

SCORES:
  1. Requirements & Scope         2  — Started drawing at min 1; no read/write question
  2. Capacity Estimation          2  — Stated "10K QPS" without derivation
  3. API & Data Model             3  — Basic endpoints; weak fan-out schema
  4. High-Level Architecture      3  — Readable diagram; cache + DB present
  5. Deep Dive                    2  — Fan-out hand-waved; celebrity problem missed
  6. Trade-offs & Alternatives    2  — Single approach; no rejected alternative
  7. Failure Modes & Reliability  2  — Only "DB fails" when prompted at min 41
  8. Communication & Structure    3  — Clear voice; poor time mgmt (no deep dive until min 33)
TOTAL: 17/32 — Developing for L5 (bar: 20+)

TOP STRENGTH: Architecture diagram was legible with labeled components (Dim 4).

TOP GAP: Requirements and estimation in first 10 minutes (Dim 1, 2).

SBI-R #1 (Constructive):
  S: At minute 1, before clarifying scale or read/write ratio...
  B: You began drawing Client → LB → API → DB.
  I: Interviewer couldn't confirm design driver; Requirements scored 2.
  R: Dim 1 — Next: open with "Is timeline read-heavy? p99 target?"

SBI-R #2 (Constructive):
  S: At minute 30, deep dive on timeline generation...
  B: You said "we'll push to Redis" without write amplification math.
  I: Deep Dive 2 — celebrity post would melt write path.
  R: Dim 5 — Study: Week 9 Design Twitter Feed; prep hybrid fan-out.

SBI-R #3 (Positive):
  S: At minute 18, architecture walkthrough...
  B: You numbered read path steps 1–5 with cache check before DB.
  I: Interviewer followed without confusion; Dim 4 scored 3.
  R: Keep numbered flows in every mock.

HIRE SIGNAL: Lean No for L5 — revisit in 2 weeks after focused study.

NEXT FOCUS (2 weeks):
  Week 1: Week 9 Design Twitter Feed + redo requirements opening drill daily
  Week 2: Re-mock same problem; target Requirements ≥3, Deep Dive ≥3

STUDY MODULES:
  → Week 9: Design Twitter Feed.md
  → Week 2: Caching Patterns.md (fan-out cache)
  → Week 4: Sharding.md (if scaling writes)
```

### Example B: Interview-Ready Candidate (Total 23/32) — Design Payment System, L5 Target

```
MOCK INTERVIEW FEEDBACK
Candidate: [Name]          Date: [Date]
Problem: Design Payment System               Target: L5
Interviewer: [Name]        Duration: 45 min

SCORES:
  1. Requirements & Scope         3  — Good clarifiers; missed idempotency NFR initially
  2. Capacity Estimation          3  — TPS + storage OK; no bandwidth
  3. API & Data Model             4  — Idempotency keys, ledger schema, strong
  4. High-Level Architecture      3  — Clear; saga orchestrator present
  5. Deep Dive                    3  — Double-entry ledger depth good; weak on reconciliation
  6. Trade-offs & Alternatives    3  — Sync vs async payment; named cost
  7. Failure Modes & Reliability  3  — Duplicate charge, timeout, DLQ — unprompted
  8. Communication & Structure    4  — Time checks, summaries, collaborative
TOTAL: 23/32 — Interview-ready for L5

TOP STRENGTH: API & Data Model (Dim 3) — production-grade idempotency design.

TOP GAP: Reconciliation deep dive when interviewer probed at minute 38.

SBI-R #1 (Constructive):
  S: Minute 38, probe on nightly reconciliation...
  B: You described "batch job compares totals" without discrepancy handling.
  I: Deep Dive stayed at 3; L6 would need dispute workflow + audit trail.
  R: Dim 5 — Study Week 11 Design Payment System reconciliation section.

SBI-R #2 (Positive):
  S: Minute 6, after requirements...
  B: You asked "Exactly-once or at-least-once for payment events?"
  I: Set consistency bar early; shaped ledger + outbox correctly.
  R: Dim 1 — Repeat on all stateful designs.

SBI-R #3 (Positive):
  S: Minute 42, unprompted failure modes...
  B: You listed duplicate webhook, partial saga, poison message with DLQ.
  I: Failure Modes 3 — meets L5 bar.
  R: Dim 7 — Add detection metrics next mock.

HIRE SIGNAL: Yes for L5

NEXT FOCUS: Deep dive reconciliation + SLO/error budget language (Week 8).

STUDY MODULES:
  → Week 11: Design Payment System (reconciliation)
  → Week 6: Saga Pattern.md, Outbox Pattern and CDC.md
  → Week 8: SLOs SLIs Error Budgets and Alerting.md
```

### Example C: Strong L6 Candidate (Total 28/32) — Design Distributed KV Store, L6 Target

```
MOCK INTERVIEW FEEDBACK
Candidate: [Name]          Date: [Date]
Problem: Design Distributed KV Store           Target: L6
Interviewer: [Name]        Duration: 45 min

SCORES:
  1. Requirements & Scope         4  — Consistency/latency CAP trade explicit
  2. Capacity Estimation          4  — QPS → nodes; memory per partition
  3. API & Data Model             3  — get/put/delete; versioning light
  4. High-Level Architecture      4  — Consistent hash ring, replication shown
  5. Deep Dive                    4  — Quorum R/W, read repair, hinted handoff
  6. Trade-offs & Alternatives    4  — CP vs AP; when to flip; ops cost
  7. Failure Modes & Reliability  4  — Split brain, gossip failure, cascade
  8. Communication & Structure    3  — Strong; 4-min silent stretch at min 20
TOTAL: 28/32 — Strong L6

TOP STRENGTH: Deep Dive (Dim 5) — production-grade quorum and repair paths.

TOP GAP: Communication — silent ring diagram without narration.

SBI-R #1 (Constructive):
  S: Minute 20–24, drawing consistent hash ring...
  B: No verbal explanation while drawing; interviewer waited.
  I: Dim 8 dropped to 3; risk in real interview if clock is tight.
  R: Narrate: "I'm placing virtual nodes on the ring because..."

SBI-R #2 (Positive):
  S: Minute 32, W/R quorum discussion...
  B: You quantified stale read probability under N=3, W=2, R=2.
  I: Exceeds bar — Principal-level depth on consistency.
  R: Dim 5 — This is teachable material; keep it.

SBI-R #3 (Positive):
  S: Minute 15, constraint injection "network partition"..."
  B: You chose CP for config keys, AP for session cache with explanation.
  I: Trade-offs Dim 6 scored 4 — requirement-driven CAP.
  R: Framework applies to all partition problems.

HIRE SIGNAL: Strong Yes for L6; borderline Principal (needs migration + cost narrative)

NEXT FOCUS: Principal polish — v1/v2 migration, infra cost, narrate while drawing.

STUDY MODULES:
  → Week 13: Design Distributed Key-Value Store.md
  → Week 4: Consistent Hashing.md, Consensus Raft.md
  → Week 3: CAP Theorem.md, Consistency Models.md
```

---

## Improvement Planning: Feedback → 2-Week Study Plan

```
╔════════════════════════════════════════════════════════════════════╗
║   2-WEEK IMPROVEMENT LOOP                                          ║
╠════════════════════════════════════════════════════════════════════╣
║                                                                    ║
║   INPUT:  Mock feedback with lowest 2 dimensions + total score     ║
║                                                                    ║
║   WEEK 1 — BUILD (60% study, 40% drill)                            ║
║     Day 1–2: Read primary module for gap #1                        ║
║     Day 3:   Retention test questions for that week                ║
║     Day 4–5: Read primary module for gap #2                        ║
║     Day 6:   15-min redo drill (failed section only)               ║
║     Day 7:   Half mock (20 min): requirements + math ONLY          ║
║                                                                    ║
║   WEEK 2 — INTEGRATE (40% study, 60% mock)                         ║
║     Day 8–9:  Problem-specific design doc (same problem as mock)   ║
║     Day 10:   Full 45-min mock (same problem)                      ║
║     Day 11:   Compare scores: target +3 on weakest dimension       ║
║     Day 12:   New problem mock (adjacent domain)                   ║
║     Day 13:   Written self-feedback                                ║
║     Day 14:   Set next 2-week focus or declare interview-ready     ║
║                                                                    ║
╚════════════════════════════════════════════════════════════════════╝
```

### Sample 2-Week Plan (Gap: Deep Dive + Failure Modes on Social Feed)

```
WEEK 1:
  Mon-Tue: Week 9 Design Twitter Feed.md (fan-out sections)
  Wed:     Retention-Tests Week-09 (when available) or self-quiz
  Thu-Fri: Week 6 Circuit Breakers...md + Week 8 SLOs...md
  Sat:     15-min drill: explain celebrity fan-out on whiteboard
  Sun:     20-min partial mock: architecture + failure modes only

WEEK 2:
  Mon:     Re-read Week 9 compound scenario Social Platform Meltdown
  Tue:     Full mock: Design Twitter Feed
  Wed:     Compare scores — target Deep Dive 2→3, Failure Modes 2→3
  Thu:     Full mock: Design WhatsApp (transfer chat failure patterns)
  Fri:     Document 5 SBI-R statements from both mocks
  Sat-Sun: Buffer / redo weakest drill

SUCCESS CRITERIA:
  Deep Dive ≥3 AND Failure Modes ≥3 on re-mock
  Total score ≥21 (interview-ready band)
```

---

## Weak Signal → Curriculum Module Map (Weeks 1–14)

Use this table after every mock. Find your weak signal; study the mapped modules.

### Dimension 1: Requirements & Scope

| Weak Signal | Study Modules |
|-------------|---------------|
| Jumped to diagram without questions | Week 9 Design Twitter Feed (requirements section), Week 15 Interview Rubric.md |
| Over-scoped (DMs, search, trending) | Week 9 Design Twitter Feed, Week 14 Design Google Docs (scope cuts) |
| Missed consistency requirement | Week 3 Consistency Models.md, Week 11 Design Payment System |
| Ignored mobile/offline constraints | Week 9 Design WhatsApp.md |
| No MVP vs v2 boundary | Week 14 Design LLM Serving Platform.md (v1 inference vs training) |

### Dimension 2: Capacity Estimation

| Weak Signal | Study Modules |
|-------------|---------------|
| No estimation attempted | Week 15 Interview Rubric.md (estimation template), Week 1 CDN Fundamentals (traffic math) |
| QPS off by >10× | Week 9 Design Twitter Feed, Week 10 Design YouTube.md |
| Missing storage growth | Week 2 SQL Deep Dive.md, Week 5 Database Scaling Patterns.md |
| Missing bandwidth / egress | Week 1 CDN Fundamentals.md, Week 10 Design YouTube.md |
| Math not connected to shards | Week 4 Sharding.md, Week 5 Database Scaling Patterns.md |

### Dimension 3: API & Data Model

| Weak Signal | Study Modules |
|-------------|---------------|
| Vague REST without endpoints | Week 1 REST vs GraphQL vs gRPC.md |
| SQL default without access patterns | Week 2 SQL Deep Dive.md, Week 2 NoSQL Taxonomy.md |
| No partition key for scale | Week 4 Sharding.md, Week 5 Cassandra Architecture.md |
| Missing idempotency | Week 11 Design Payment System, Week 6 Saga Pattern.md |
| No ID generation strategy | Week 7 Unique ID Generation.md |
| Search query unserved | Week 7 Search Systems and Inverted Indexes.md, Week 12 Design Google Search |

### Dimension 4: High-Level Architecture

| Weak Signal | Study Modules |
|-------------|---------------|
| Kitchen-sink diagram | Week 15 Interview Rubric.md (architecture checklist) |
| Missing CDN/edge | Week 1 CDN Fundamentals.md, Week 1 DNS Resolution.md |
| Missing load balancer | Week 7 Load Balancing Deep Dive.md |
| Missing cache layer | Week 2 Caching Patterns.md, Week 1 CDN Fundamentals.md |
| No async / queue path | Week 6 Message Queues and Kafka.md, Week 6 Event-Driven Architecture.md |
| Wrong protocol (poll vs push) | Week 1 WebSockets.md, Week 9 Design WhatsApp.md |
| No rate limiting | Week 7 Rate Limiting Algorithms.md |

### Dimension 5: Deep Dive

| Weak Signal | Study Modules |
|-------------|---------------|
| Feed fan-out shallow | Week 9 Design Twitter Feed.md |
| Chat ordering / delivery | Week 9 Design WhatsApp.md, Week 8 Lamport Clocks Vector Clocks and Causality.md |
| Payment / ledger depth | Week 11 Design Payment System, Week 6 Saga Pattern.md |
| Consistent hash / KV | Week 3 Consistent Hashing.md, Week 13 Design Distributed Key-Value Store.md |
| Kafka / streaming | Week 6 Message Queues and Kafka.md, Week 13 Design Kafka.md |
| Search / ranking | Week 7 Search Systems and Inverted Indexes.md, Week 12 Design Google Search |
| Video / CDN pipeline | Week 10 Design YouTube.md, Week 1 CDN Fundamentals.md |
| Geospatial / dispatch | Week 8 Geospatial Systems.md, Week 10 Design Uber |
| Realtime collaboration | Week 8 CRDTs and Conflict Resolution.md, Week 14 Design Google Docs.md |
| ML serving / feature store | Week 14 Design LLM Serving Platform.md, Week 14 Design Feature Store.md |
| Consensus / config | Week 4 Consensus Raft.md, Week 13 Design Configuration Store.md |

### Dimension 6: Trade-offs & Alternatives

| Weak Signal | Study Modules |
|-------------|---------------|
| No alternatives named | Week 3 CAP Theorem.md, Week 15 Interview Rubric.md (trade-off framework) |
| Generic "SQL vs NoSQL" | Week 2 NoSQL Taxonomy.md, Week 3 Consistency Models.md |
| Microservices unjustified | Week 6 Microservices Patterns.md |
| Sync vs async unclear | Week 6 Event-Driven Architecture.md |
| Push vs pull CDN | Week 1 CDN Fundamentals.md |
| Fan-out write vs read | Week 9 Design Twitter Feed.md |

### Dimension 7: Failure Modes & Reliability

| Weak Signal | Study Modules |
|-------------|---------------|
| No failure modes | Week 8 SLOs SLIs Error Budgets and Alerting.md, Week 15 Interview Rubric.md |
| Generic "DB down" | Week 6 Circuit Breakers Bulkheads Timeouts Retries and Backpressure.md |
| Cache stampede | Week 2 Caching Patterns.md, Week 1 CDN Fundamentals.md |
| Split brain / quorum | Week 4 Consensus Raft.md, Week 4 Replication Strategies.md |
| Poison messages | Week 6 Message Queues and Kafka.md |
| Cascade failures | Week 6 Circuit Breakers...md, Week 9 Compound Scenario Social Platform Meltdown |
| No SLO / monitoring | Week 8 Observability.md, Week 8 SLOs SLIs Error Budgets and Alerting.md |
| Data loss scenarios | Week 4 Replication Strategies.md, Week 13 Compound Scenario Consensus and Data Loss |

### Dimension 8: Communication & Structure

| Weak Signal | Study Modules |
|-------------|---------------|
| Long silent periods | Week 15 Interview Rubric.md (time template), this module |
| Random topic jumping | Week 15 Interview Rubric.md (structured progression) |
| Defensive under probe | This module (defense patterns section) |
| Ran out of time | Week 15 Interview Rubric.md (minute-by-minute template) |
| Ignored interviewer hint | Week 15 Mock Interview practice (when available) |

### Cross-Cutting Weak Signals

| Weak Signal | Study Modules |
|-------------|---------------|
| Multi-region / DR weak | Week 4 Replication Strategies.md, Week 1 CDN Fundamentals.md |
| Feature flags / rollout | Week 7 Feature Flags and Progressive Delivery.md |
| CDC / event consistency | Week 6 Outbox Pattern and CDC.md |
| Compound incident reasoning | Week 9–14 Compound Scenario modules |
| Rate / abuse / DDoS | Week 7 Rate Limiting Algorithms.md, Week 1 CDN Fundamentals.md |

---

## Feedback Anti-Patterns (What NOT to Say)

```
╔══════════════════════════════════════════════════════════════════════╗
║   ANTI-PATTERN                    │ WHY IT FAILS                     ║
╠══════════════════════════════════════════════════════════════════════╣
║   "You should use Cassandra"        │ Prescriptive tech, not rubric  ║
║   "That was wrong"                  │ No behavior, no learning       ║
║   "Needs more depth"                │ Unmeasurable                   ║
║   "Good job overall!"               │ No repeatable behavior named   ║
║   "I wouldn't worry about it"       │ Dismisses real gap             ║
║   "Everyone struggles with that"    │ Normalizes avoidable gap       ║
║   "Your design is better than mine" │ False comfort; rubric scores   ║
║   "You think too much"              │ Attacks thinking style         ║
║   "Just read DDIA"                  │ Not actionable                 ║
║   "You failed"                      │ Verdict without dimensions     ║
║   Debating architecture 30+ min    │ Feedback session ≠ design review║
║   Comparing to FAANG internal doc   │ Unfair bar; not interview skill║
║   Personal criticism                │ "You always..." — toxic        ║
║   Score without evidence            │ Number without SBI-R quotes    ║
╚══════════════════════════════════════════════════════════════════════╝
```

### Giver Checklist (Before Sending Feedback)

```
[ ] Every constructive point has SBI-R with timestamp
[ ] Every dimension score has at least one note
[ ] At least one positive SBI-R (specific behavior)
[ ] One curriculum module assigned per gap dimension
[ ] No technology prescription unless tied to undefended gap
[ ] Total /32 and hire signal band stated
[ ] ONE next mock behavior change (exact phrase)
[ ] Delivered within 24 hours of mock
```

---

## Recording and Reviewing Your Own Mocks

```
╔═════════════════════════════════════════════════════════════════════╗
║   SELF-RECORDING PROTOCOL                                           ║
╠═════════════════════════════════════════════════════════════════════╣
║                                                                     ║
║   SETUP:                                                            ║
║     → Zoom/Meet solo room OR phone camera on whiteboard             ║
║     → Record audio + screen/board (not face required)               ║
║     → Visible timer in frame                                        ║
║     → Post problem statement on second monitor                      ║
║                                                                     ║
║   REVIEW PASS 1 (10 min): MUTE — score dimensions cold              ║
║     Pause at minutes 5, 15, 25, 35 — score partial                  ║
║                                                                     ║
║   REVIEW PASS 2 (15 min): Transcript or notes                       ║
║     Mark: silence >60s, "um"/circular explanation, missed probes    ║
║                                                                     ║
║   REVIEW PASS 3 (10 min): One skill only                            ║
║     Example: only listen for trade-off language                     ║
║                                                                     ║
║   OUTPUT: 3 timestamps to fix + 1 drill for next session            ║
║                                                                     ║
╚═════════════════════════════════════════════════════════════════════╝
```

### What to Look For on Recording

| Timestamp | Watch For | Red Flag |
|-----------|-----------|----------|
| 0–5 min | Clarifying questions | First box drawn before minute 2 |
| 5–10 min | Estimation on board | Numbers stated without derivation |
| 10–15 min | API fields / schema | "Standard CRUD" only |
| 15–25 min | Diagram narration | Silent drawing >3 min |
| 25–40 min | Depth on probe | Same diagram rescaled |
| 40–45 min | Failure modes | "We'll handle later" |

### Solo Mock Without Partner

```
1. Pick problem + target level
2. Set 45-min timer with 5-min phase alerts
3. Record yourself
4. At minute 25, pause recording — write probe question you'd ask
5. Resume; answer probe
6. Score with rubric; write feedback AS IF you were peer interviewer
7. Compare self-score to "cold" re-watch score — calibration data
```

---

## Quick Reference: Feedback One-Liners by Dimension

```
REQ:     "Confirm read/write ratio and p99 before boxes."
MATH:    "Show DAU → QPS → shards on the board."
API:     "Define the hot query's schema and partition key."
ARCH:    "Seven boxes max; number the critical read path."
DIVE:    "Go three levels: algorithm, config, edge case."
TRADE:   "Name what you rejected and what it cost you."
FAIL:    "Three failures unprompted: detection + degradation."
COMM:    "Check in every 10 minutes; summarize at transitions."
```

---

## Key Takeaways

```
1. Feedback must be SBI-R: Situation, Behavior, Impact, Rubric dimension —
   with timestamps and quotes, not vibes.

2. Positive feedback is specific behavior reinforcement; constructive
   feedback is one gap + one exact next action + one study module.

3. Calibrate to target level: L5 unprompted failure modes are required;
   L4 gets partial credit when prompted.

4. Red flag interviewer phrases map to rubric gaps — learn the responses.

5. The improvement loop is mock → written feedback → 2-week study plan →
   re-mock same problem (+3 on weakest dimension).

6. Weak signals map to curriculum modules Weeks 1–14 — use the tables,
   don't guess what to study.

7. Anti-patterns: technology prescription, vague praise, architecture
   debates, scores without evidence.

8. Record mocks; cold re-watch scores are closer to real interviewer scores
   than how you felt in the moment.
```

---

## Targeted Reading

```
→ Week-15-Mock-Interviews/Interview Rubric.md — scoring source of truth
→ "Thanks for the Feedback" (Stone & Heen) — receiving feedback under stress
→ "Radical Candor" (Kim Scott) — SBI-style care + challenge balance
→ Google SRE Book, Ch 4 (SLOs) — calibrate Failure Modes feedback
→ "Staff Engineer" (Will Larson), Ch 3 — L6+ communication expectations
→ This curriculum: problem modules Week 9–14 for deep dive feedback depth
→ Retention-Tests/ Week 1–8 — verify study plan with spaced recall
```

---

## Appendix: Blank Written Feedback Form

```
MOCK INTERVIEW FEEDBACK
Candidate: _______________  Date: ___________
Problem: _________________  Target Level: _____
Interviewer: _____________  Duration: _________

SCORES (1–4):
  1. Requirements & Scope         __  Notes: _______________________
  2. Capacity Estimation          __  Notes: _______________________
  3. API & Data Model             __  Notes: _______________________
  4. High-Level Architecture      __  Notes: _______________________
  5. Deep Dive                    __  Notes: _______________________
  6. Trade-offs & Alternatives    __  Notes: _______________________
  7. Failure Modes & Reliability  __  Notes: _______________________
  8. Communication & Structure    __  Notes: _______________________
TOTAL: ___/32

TOP STRENGTH (dimension + moment): _________________________________
TOP GAP (dimension + moment):      _________________________________

SBI-R #1 (Constructive):
  S: _______________________________________________________________
  B: _______________________________________________________________
  I: _______________________________________________________________
  R: Dimension __ — Study: _________________________________________

SBI-R #2 (Constructive):
  S: _______________________________________________________________
  B: _______________________________________________________________
  I: _______________________________________________________________
  R: Dimension __ — Study: _________________________________________

SBI-R #3 (Positive):
  S: _______________________________________________________________
  B: _______________________________________________________________
  I: _______________________________________________________________
  R: Dimension __

HIRE SIGNAL: [ ] Strong Yes  [ ] Yes  [ ] Lean  [ ] No

ONE BEHAVIOR FOR NEXT MOCK (exact phrase): __________________________

2-WEEK STUDY PLAN:
  Week 1: __________________________________________________________
  Week 2: __________________________________________________________
```

---

## Peer Mock Problem Rotation (12-Week Cycle)

Avoid repeating the same problem until scores ≥24. Rotate domains to transfer skills.

```
╔═══════════════════════════════════════════════════════════════════════╗
║   WEEK │ PROBLEM                          │ PRIMARY GAP TRAINING      ║
╠═══════════════════════════════════════════════════════════════════════╣
║   1    │ Design Twitter Feed              │ Fan-out, read-heavy       ║
║   2    │ Design Payment System            │ Consistency, sagas        ║
║   3    │ Design WhatsApp                  │ Ordering, real-time       ║
║   4    │ Design Distributed KV Store      │ Hashing, quorum           ║
║   5    │ Design YouTube                   │ CDN, async pipeline       ║
║   6    │ Design Uber                      │ Geospatial, matching      ║
║   7    │ Design Kafka                     │ Streaming, partitions     ║
║   8    │ Design Google Search             │ Index, crawl, rank        ║
║   9    │ Design Google Docs               │ CRDTs, collaboration      ║
║   10   │ Compound: Social Meltdown        │ Incident, cascade         ║
║   11   │ Compound: Payment Data Loss      │ DR, audit, recovery       ║
║   12   │ Full loop: weakest problem redo  │ Score validation          ║
╚═══════════════════════════════════════════════════════════════════════╝
```

After each rotation week, write one paragraph: "What transferred from problem A to B?"
Example: "Fan-out write amplification from Twitter applied to notification system in WhatsApp."

---

## Receiving Feedback: The 24-Hour Protocol

```
╔══════════════════════════════════════════════════════════════════════╗
║   HOUR 0 (immediately after mock)                                    ║
║     → Write raw emotional reaction privately (optional, delete later)║
║     → Do NOT argue with feedback giver                               ║
║     → Say only: "Thank you — I'll review the written notes."         ║
║                                                                      ║
║   HOUR 1–4 (same day)                                                ║
║     → Read written feedback once without responding                  ║
║     → Highlight every SBI-R Behavior quote — is it accurate?         ║
║     → If inaccurate, note factual dispute; if accurate, accept       ║
║                                                                      ║
║   HOUR 4–24                                                          ║
║     → Complete self-feedback protocol; compare scores to peer's      ║
║     → Gap >1 point on any dimension = discuss once, then move on     ║
║     → Draft 2-week study plan; send to partner for accountability    ║
║                                                                      ║
║   DAY 2+                                                             ║
║     → Start Week 1 study module — no re-litigation of mock           ║
╚══════════════════════════════════════════════════════════════════════╝
```

### Emotional Triggers and Rational Responses

| Trigger | Irrational Response | Rational Response |
|---------|---------------------|-------------------|
| Score below self-assessment | "They don't get it" | "Self-scores run high; what's the Behavior quote?" |
| Technology challenged | "Cassandra is fine!" | "Did I defend partition strategy under probe?" |
| Compared to other candidate | "They were easier on X" | "Rubric is dimension-based; focus my gap" |
| Lean No hire signal | "Mock partner is harsh" | "Is total <20? If yes, fundamentals first" |
| Positive feedback only | "I'm ready" | "Which dimensions weren't mentioned? Likely gaps" |

---

## Interviewer Notes Template (During Mock)

Capture these DURING the interview for high-quality written feedback later.

```
MINUTE ___ | QUOTE OR ACTION | DIMENSION | SCORE IMPRESSION (1-4)
───────────┼─────────────────┼───────────┼────────────────────────
    3      |                 |     1     |
   12      |                 |     2     |
   18      |                 |     3     |
   22      |                 |     4     |
   31      |                 |     5     |
   36      |                 |     6     |
   42      |                 |     7     |
   44      |                 |     8     |

CONSTRAINT INJECTIONS USED:
  Min 15: _________________________________________________________
  Min 30: _________________________________________________________

PROBE QUESTIONS ASKED:
  1. ______________________________________________________________
  2. ______________________________________________________________
  3. ______________________________________________________________

CANDIDATE RESPONSE TO PROBES: [ ] Engaged  [ ] Defensive  [ ] Stuck
```

---

## Additional Positive Patterns (25–30)

| # | Say This | Not That | Dimension |
|---|----------|----------|-----------|
| 25 | "You connected CAP choice to the payment NFR — textbook Dim 6." | "Good distributed systems." | 6 |
| 26 | "Outbox pattern for order→inventory — shows Week 6 module landed." | "Nice pattern." | 5 |
| 27 | "Rate limiter at API gateway before fan-out — abuse path covered." | "Thought about security." | 4, 7 |
| 28 | "You quantified cache memory: 100M keys × 1KB = 100GB — believable." | "Cache sizing OK." | 2 |
| 29 | "Vector clock mention for causality in chat — correct for WhatsApp." | "Good chat design." | 5 |
| 30 | "Migration: dual-write phase before cutover — Principal signal." | "Good rollout plan." | 6, 8 |

---

## Additional Constructive Patterns (25–30)

| # | Say This | Not That | Dimension |
|---|----------|----------|-----------|
| 25 | "Multi-region raised at min 35 but no replication lag math — add RPO/RTO." | "Weak multi-region." | 4, 7 |
| 26 | "GraphQL suggested for feed — N+1 risk; stick to BFF aggregation pattern." | "Wrong API style." | 3 |
| 27 | "Snowflake IDs mentioned without clock rollback handling — incomplete." | "ID gen weak." | 3, 5 |
| 28 | "Bulkhead missing between read and write pools — cascade risk under load." | "Missing resilience." | 7 |
| 29 | "Search index stale 24h — no incremental indexing path for new posts." | "Search incomplete." | 5 |
| 30 | "Cost: 500 nodes at $X/mo never estimated — Principal gap at L6+." | "Didn't think about cost." | 2, 6 |

---

## Feedback Scenario: Multi-Symptom Review

**Situation:** Peer mock on Design Payment System. Candidate scores 21/32. They believe they "nailed it" because architecture matched a blog post they read.

**Interviewer feedback summary:**
- Dim 5 (Deep Dive) = 2: ledger mentioned, no double-entry line items
- Dim 7 (Failure Modes) = 2: only duplicate charge; no reconciliation failure
- Dim 8 = 4: excellent communication masked depth gaps

**Wrong response:** "But the blog post's architecture is used at Stripe."

**Correct response:** "Communication scored 4 — keep time checks. Deep Dive and Failure Modes at 2 — I'll study Week 11 ledger section and redo 15-min drill on reconciliation failures before re-mock."

**Study plan extracted:**
```
Day 1–3: Week 11 Design Payment System (ledger + reconciliation)
Day 4:   Week 6 Saga Pattern (failure compensation)
Day 5:   15-min drill: draw double-entry for $10 transfer
Day 6–7: Week 8 SLOs (payment SLI: success rate, latency)
Day 8:   Re-mock same problem; target Dim 5 ≥3, Dim 7 ≥3
```

This is the loop. Architecture familiarity ≠ interview score. Rubric dimensions are independent.

---

## Glossary: Feedback Terms

```
SBI-R          Situation-Behavior-Impact-Rubric (this module's framework)
Lever          Single highest-priority behavior change for next mock
Cold review    Scoring recording without live emotional context
Constraint     Mid-interview requirement injection (multi-region, celebrity)
Probe          Interviewer question to test depth on weak signal
Transfer       Applying skill from mock A to mock B (rotation goal)
Hire signal    Band derived from total /32 + level calibration
Anti-pattern   Feedback that feels helpful but teaches nothing
```
