# Mock Interview 01 — Design a Social News Feed (Twitter/X Home Timeline)

> **Week 15** — Timed 45-minute mock interview with interviewer script, model answer, and rubric

---

## Learning Objectives

```
╔════════════════════════════════════════════════════════════════╗
║   AFTER THIS MOCK INTERVIEW, YOU WILL BE ABLE TO:              ║
╟────────────────────────────────────────────────────────────────╢
║                                                                ║
║   1. Complete a full 45-minute feed design interview under     ║
║      time pressure — requirements through failure modes        ║
║                                                                ║
║   2. Execute fan-out on write vs read vs hybrid trade-offs     ║
║      with production numbers (300M DAU, celebrity thresholds)  ║
║                                                                ║
║   3. Size AWS infrastructure from back-of-envelope math:       ║
║      QPS, Redis memory, Kafka partitions, Cassandra RF         ║
║                                                                ║
║   4. Score your own performance on the 8-dimension rubric      ║
║      with problem-specific criteria for feed systems           ║
║                                                                ║
║   5. Diagnose feed-specific failure modes: hot keys,           ║
║      consumer lag, cache stampede, celebrity fan-out storms    ║
║                                                                ║
║   6. Deliver a principal-grade answer that would survive       ║
║      one year in production on AWS                             ║
╚════════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "I'll design everything Twitter has"            ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG IN 45 MINUTES. Scope to home timeline read/write.          ║
║   DMs, search, trending, ads, Spaces — all out unless the          ║
║   interviewer expands scope. Breadth without depth fails.          ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "Push fan-out is the obvious answer"            ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG WITHOUT THE CAVEAT. Push alone dies on celebrity posts.    ║
║   Saying "Redis sorted sets" without hybrid threshold and          ║
║   celebrity pull-merge is a below-bar answer at L5+.               ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "CDN caches the home feed"                      ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Home timeline is authenticated, per-user, ranked.         ║
║   CloudFront caches tweet MEDIA (S3 origin) — never timeline JSON. ║
║   See Week-01 CDN Fundamentals: Vary: Cookie destroys hit ratio.   ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "Kafka = real-time delivery"                    ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Kafka guarantees durable ordered delivery to consumers.   ║
║   Consumer lag of 30s = tweets appear 30s late in feeds.           ║
║   Fan-out lag is a user-visible SLO, not an ops nice-to-have.      ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "I'll mention failure modes if I have time"     ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG AT L6+. Reserve minutes 40–45 OR start failure modes       ║
║   at minute 35 proactively. Feed systems fail in predictable       ║
║   ways — celebrity posts, hot Redis keys, partition skew.          ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #6: "One database holds everything"                 ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Feed systems use polyglot persistence by access pattern:  ║
║   Redis ZSET for hot timelines, Cassandra/DynamoDB for tweets,     ║
║   PostgreSQL/Aurora for follow graph, S3 for media.                ║
╚════════════════════════════════════════════════════════════════════╝
```

---

## Interview Setup — 45-Minute Timed Format

```
╔════════════════════════════════════════════════════════════════════╗
║   MOCK INTERVIEW 01 — SOCIAL NEWS FEED                             ║
╠════════════════════════════════════════════════════════════════════╣
║   Duration:     45 minutes (strict)                                ║
║   Format:       Whiteboard / Excalidraw / shared doc               ║
║   Role:         Candidate designs; partner reads Interviewer Script║
║   Level target: L5 (Senior) to L6 (Staff) / Principal SRE          ║
║   Platform:     AWS (us-east-1 primary, multi-AZ)                  ║
╠════════════════════════════════════════════════════════════════════╣
║   MATERIALS NEEDED:                                                ║
║   • Timer (phone or tab)                                           ║
║   • Blank diagram space                                            ║
║   • This doc — Interviewer Script for partner                      ║
║   • Interview Rubric.md — for scoring after                        ║
╠════════════════════════════════════════════════════════════════════╣
║   RULES FOR CANDIDATE:                                             ║
║   • Narrate thinking out loud                                      ║
║   • Ask clarifying questions before designing                      ║
║   • State assumptions explicitly                                   ║
║   • Check in at phase transitions                                  ║
║   • Do NOT read Model Answer until after scoring                   ║
╠════════════════════════════════════════════════════════════════════╣
║   RULES FOR INTERVIEWER:                                           ║
║   • Read script lines verbatim at phase open                       ║
║   • Do NOT lead to preferred architecture                          ║
║   • Inject constraints at marked minutes                           ║
║   • Take notes on specific quotes for debrief                      ║
║   • Leave 3 minutes for candidate questions at end                 ║
╚════════════════════════════════════════════════════════════════════╝
```

### Minute-by-Minute Schedule

```
╔══════════════════════════════════════════════════════════════════════╗
║   MINUTE   PHASE              │ CANDIDATE DELIVERABLE                ║
╠══════════════════════════════════════════════════════════════════════╣
║   0–5      Clarification      │ FR/NFR list, scope boundary,         ║
║                               │ assumptions confirmed                ║
╠══════════════════════════════════════════════════════════════════════╣
║   5–10     Estimation         │ Read/write QPS, storage, bandwidth,  ║
║                               │ bottleneck identified                ║
╠══════════════════════════════════════════════════════════════════════╣
║   10–15    API & Data Model   │ 3–5 endpoints, schemas, partition    ║
║                               │ keys, access patterns                ║
╠══════════════════════════════════════════════════════════════════════╣
║   15–25    Architecture       │ Component diagram, sync/async paths, ║
║                               │ critical path walkthrough            ║
╠══════════════════════════════════════════════════════════════════════╣
║   25–40    Deep Dive          │ Fan-out strategy, celebrity problem, ║
║                               │ configs (threshold, TTL, partitions) ║
╠══════════════════════════════════════════════════════════════════════╣
║   40–45    Failure + Wrap     │ 3–5 failure modes, degradation,      ║
║                               │ candidate questions                  ║
╚══════════════════════════════════════════════════════════════════════╝

PACING NOTES:

  Behind at minute 12:  Skip bandwidth math; keep QPS + storage.
  Behind at minute 22:  Abbreviate API; draw architecture immediately.
  Ahead at minute 28:   Interviewer injects celebrity constraint early.
  Ahead at minute 35:   Candidate should start failure modes unprompted.
```

---

## Interviewer Script

Read the **Opening** verbatim. Then follow phase scripts. Inject **Constraints** at marked times regardless of candidate progress.

### Opening (Minute 0)

```
INTERVIEWER SAYS:

"Thanks for joining. This is a 45-minute system design interview.
I'll present a problem, you'll drive the design, and I'll ask
follow-up questions along the way. There is no single right answer —
I'm evaluating how you think through trade-offs at scale.

Feel free to use the whiteboard. Ask clarifying questions before
you dive in. Narrate your thinking — silence makes it hard for me
to follow.

Ready? Here is the problem:

Design the home timeline for a social platform like Twitter or X.
When a user opens the app, they see a reverse-chronological feed
of posts from accounts they follow. Users can post text and media,
follow/unfollow, and scroll through paginated results.

Assume 300 million daily active users, global, mobile-first.
The system runs on AWS.

I'll stay quiet for the first few minutes while you clarify scope.
Let me know when you're ready to move to numbers."
```

### Phase 1 — Clarification Probes (Minutes 0–5)

```
IF CANDIDATE ASKS FEW QUESTIONS (after 2 min silence):

  "What would you need to know before you start drawing boxes?"

IF CANDIDATE OVER-SCOPES (mentions DMs, search, ads):

  "Good ideas for v2. If you had to ship an MVP in 6 months,
   what would you cut?"

IF CANDIDATE ASKS GOOD QUESTIONS — ACKNOWLEDGE AND ANSWER:

  Q: "Chronological or algorithmic feed?"
  A: "Start with chronological. Ranking is a nice-to-have we can
      discuss if you have time."

  Q: "Read vs write ratio?"
  A: "Very read-heavy. Users scroll far more than they post."

  Q: "Consistency requirements?"
  A: "Eventual consistency is fine for feed — a few seconds delay
      for a new post to appear is acceptable. Post confirmation
      must be durable."

  Q: "Media handling?"
  A: "Posts can include images and short video. Keep media on the
      critical path only as references — full media pipeline is
      out of scope unless you want to mention it briefly."

  Q: "Delete and block?"
  A: "Yes — users can delete their posts and block others. Deleted
      posts should disappear from feeds, eventually if not instantly."

  Q: "Multi-region?"
  A: "Single primary region for MVP — us-east-1. Mention multi-region
      only if you think it's required."

  Q: "Latency target?"
  A: "p99 feed load under 300 milliseconds. Fan-out propagation
      under 5 seconds for 99th percentile of followers."

IF CANDIDATE DOES NOT ASK ABOUT SCALE:

  "How many posts per day are you designing for?"

TRANSITION AT MINUTE 5:

  "Good — let's talk numbers. Walk me through your capacity
   estimates."
```

### Phase 2 — Estimation Probes (Minutes 5–10)

```
IF CANDIDATE SKIPS ESTIMATION:

  "Before architecture — what's the read QPS? Write QPS? Storage?"

IF CANDIDATE ONLY ESTIMATES USERS:

  "How many timeline reads per user per day? Derive QPS from that."

IF CANDIDATE GETS ORDER OF MAGNITUDE:

  "What's the bottleneck — reads, writes, or storage?"

IF CANDIDATE FINISHES EARLY:

  "How much Redis memory for hot timelines? Rough estimate."

TRANSITION AT MINUTE 10:

  "Makes sense. Define the API and data model — key endpoints
   and how you'd store the data."
```

### Phase 3 — API & Data Model Probes (Minutes 10–15)

```
IF CANDIDATE IS VAGUE ON APIS:

  "What does the client call to load the first page of the feed?"

IF CANDIDATE HAS ONE BIG TABLE:

  "How do you fetch a user's home timeline — what's the query?"

IF CANDIDATE DOES NOT MENTION PARTITION KEYS:

  "What's the partition key for tweets? For the follow graph?"

IF CANDIDATE MENTIONS REDIS ZSET:

  "What's stored in the sorted set — tweet ID, score — what score?"

TRANSITION AT MINUTE 15:

  "Let's draw the architecture. Walk me through post and read paths."
```

### Phase 4 — Architecture Probes (Minutes 15–25)

```
IF CANDIDATE DRAWS TOO MANY BOXES:

  "Focus on the critical path for loading the home timeline."

IF CANDIDATE HAS NO ASYNC PATH:

  "When a user posts, do you fan-out synchronously in the API?"

IF CANDIDATE HAS NO CACHE:

  "Where does the precomputed timeline live?"

IF CANDIDATE HAS NO LOAD BALANCER:

  "How do mobile clients reach your services?"

─── CONSTRAINT INJECTION AT MINUTE 15 ───

  "Quick constraint: we need 99.99% availability on the read path.
   Does your design change?"

IF CANDIDATE FINISHES ARCHITECTURE EARLY:

  "Walk me through exactly what happens when @alice posts and
   @bob refreshes his feed 2 seconds later."

TRANSITION AT MINUTE 25:

  "Let's go deeper on the hardest part — how tweets get from
   author to follower's timeline. Fan-out on write vs read —
   what's your approach and why?"
```

### Phase 5 — Deep Dive Probes (Minutes 25–40)

```
THIS IS THE HIRING SIGNAL. REDIRECT IF CANDIDATE AVOIDS FAN-OUT.

IF CANDIDATE ONLY SAYS "USE REDIS":

  "A user with 500 followers posts — how many writes?"

IF CANDIDATE CHOOSES PURE PUSH:

  "A celebrity with 50 million followers posts. What happens?"

IF CANDIDATE CHOOSES PURE PULL:

  "A user follows 800 accounts. Feed load — how many queries?"

─── CONSTRAINT INJECTION AT MINUTE 25 ───

  "Celebrity scenario: @nova has 50 million followers and posts
   breaking news. Walk me through exactly what your system does."

IF CANDIDATE DESCRIBES HYBRID — PROBE DEEPER:

  "What's your celebrity threshold number? How did you pick it?"
  "At read time, how do you merge celebrity tweets with the cache?"
  "What's in Kafka — topic name, partition key, consumer group?"

IF CANDIDATE MENTIONS KAFKA — PROBE:

  "How many partitions? What happens when one partition lags?"
  "Post API returned 201 — follower doesn't see tweet for 60 seconds.
   Where do you look?"

─── CONSTRAINT INJECTION AT MINUTE 30 ───

  "Redis cluster fails over — one shard unavailable for 90 seconds.
   What do users see?"

IF TIME PERMITS (minute 35+):

  "How do you handle delete — tweet removed from all follower timelines?"
  "New follow — does the followee's recent posts appear immediately?"
  "Ranking — if we add ML ranking later, where does it sit?"

TRANSITION AT MINUTE 40:

  "We have a few minutes left. What breaks in production? How do
   you detect and mitigate?"
```

### Phase 6 — Failure Modes & Wrap (Minutes 40–45)

```
IF CANDIDATE SKIPS FAILURE MODES:

  "Name three things that would cause a P1 incident in this system."

IF CANDIDATE SAYS "DATABASE GOES DOWN":

  "Be specific — which database, what symptom, what's the blast radius?"

IF CANDIDATE GIVES GOOD FAILURE MODES — PROBE ONE:

  "Walk me through the on-call alert to mitigation for that one."

CLOSING (Minute 44):

  "That's time. Do you have any questions for me about the role
   or the team?"

POST-INTERVIEW (do not share with candidate during session):

  Score using Section 13 rubric. Fill self-scoring worksheet together
  in debrief if paired practice.
```

---

## Candidate Expectations by Phase

What strong L5/L6 candidates should deliver at each timed phase.

### Minutes 0–5: Clarification

```
STRONG L5/L6 BEHAVIOR:

  ✓ Ask 6–10 targeted questions before drawing
  ✓ Propose ranked functional requirements (P0/P1/P2)
  ✓ Quantify NFRs: p99 latency, availability, fan-out delay
  ✓ Explicit scope boundary:
      IN:  home timeline, post, follow, paginated read, delete
      OUT: DMs, search, trending, notifications (unless asked)
  ✓ State assumptions aloud:
      "I'm assuming 300M DAU, read-heavy, eventual consistency
       on feed visibility, chronological MVP"
  ✓ Identify design driver:
      "Read latency at scale with write fan-out is the core tension"
  ✓ Summarize back to interviewer for confirmation

WEAK SIGNALS:

  ✗ Jump straight to microservices diagram
  ✗ Design Instagram Stories / TikTok For You Page
  ✗ Ignore delete/block requirements
  ✗ No latency or availability targets
```

### Minutes 5–10: Estimation

```
STRONG L5/L6 BEHAVIOR:

  ✓ Derive from 300M DAU:
      ~150M post/read daily active (50% DAU post or engage)
      ~20 timeline loads/user/day → 6B reads/day
      ~0.5 posts/user/day (posting cohort) → ~75M posts/day
  ✓ Peak factor 2–3× on reads (evening peak)
  ✓ Read QPS: ~140K avg, ~400K peak
  ✓ Write QPS: ~870 avg, ~2.5K peak (posts only)
  ✓ Fan-out writes: posts × avg followers (separate calculation)
  ✓ Storage: tweet size × volume × replication × 5 years
  ✓ Identify bottleneck: READ PATH + FAN-OUT WRITE AMPLIFICATION
  ✓ Connect math to design:
      "400K read QPS → precomputed timelines in Redis, not pull"

WEAK SIGNALS:

  ✗ "Lots of users, we'll shard"
  ✗ Only calculate posts, not timeline reads
  ✗ Miss fan-out amplification entirely
  ✗ Numbers off by 1000× without sanity check
```

### Minutes 10–15: API & Data Model

```
STRONG L5/L6 BEHAVIOR:

  ✓ Define core APIs:
      POST /v1/posts
      GET  /v1/timeline/home?cursor=&limit=
      POST /v1/users/{id}/follow
      DELETE /v1/posts/{id}
  ✓ Cursor-based pagination (not offset)
  ✓ Snowflake tweet IDs (time-sortable)
  ✓ Separate stores by access pattern:
      tweets_by_id → DynamoDB/Cassandra (PK: tweet_id)
      user_timeline → Cassandra (PK: author_id, SK: created_at)
      home_timeline → Redis ZSET (key: home_timeline:{user_id})
      follow_graph → Aurora PostgreSQL or DynamoDB adjacency
  ✓ Denormalize follower_count on user for celebrity routing
  ✓ Mention idempotency key on POST for retry safety

WEAK SIGNALS:

  ✗ Single "posts" table with no access pattern analysis
  ✗ Offset pagination for feed
  ✗ No partition key discussion
  ✗ Store full tweet body in timeline ZSET (bloated)
```

### Minutes 15–25: Architecture

```
STRONG L5/L6 BEHAVIOR:

  ✓ 6–8 labeled components max on first pass
  ✓ Sync path: Client → CloudFront (media) → ALB → Timeline API
  ✓ Async path: Post API → Kafka → Fan-out Workers → Redis
  ✓ Separate Post Service and Timeline Service
  ✓ Graph Service for follow lookups
  ✓ Tweet Store (Cassandra/DynamoDB) as source of truth
  ✓ ElastiCache Redis Cluster for hot timelines
  ✓ MSK (Kafka) for tweet.created events
  ✓ Numbered steps on read and write critical paths
  ✓ Respond to 99.99% constraint:
      Multi-AZ, read replicas, cache-first, graceful degradation

WEAK SIGNALS:

  ✗ Monolith with "a database"
  ✗ Synchronous fan-out in Post API request
  ✗ CDN caching home timeline JSON
  ✗ No message queue between post and fan-out
```

### Minutes 25–40: Deep Dive

```
STRONG L5/L6 BEHAVIOR:

  ✓ Choose hybrid fan-out with explicit threshold (10K–100K)
  ✓ Push: ZADD home_timeline:{follower_id} score=timestamp
  ✓ Celebrity: write user_timeline only + celebrity_recent cache
  ✓ Read merge: ZREVRANGE home + pull celebrity ZSETs, merge-sort
  ✓ Kafka topic tweet.created, key=author_id, 256+ partitions
  ✓ Consumer group fan-out-v3, idempotent ZADD
  ✓ Trim timelines to 800 entries (ZREMRANGEBYRANK)
  ✓ Active-user-only fan-out (optional, shows production depth)
  ✓ Hydrate tweet bodies: Redis tweet:{id} → Cassandra batch
  ✓ Quantify celebrity scenario:
      Pure push = 50M writes; hybrid = 1 write + cached reads
  ✓ Hot key mitigation for celebrity_recent:{id}

WEAK SIGNALS:

  ✗ Pure push without celebrity caveat
  ✗ "Use a queue" without topic/partition design
  ✗ Cannot explain merge at read time
  ✗ Deep dive on user registration instead of fan-out
```

### Minutes 40–45: Failure Modes & Wrap

```
STRONG L5/L6 BEHAVIOR:

  ✓ 3–5 feed-specific failures unprompted:
      - Kafka consumer lag → stale feeds
      - Celebrity post without hybrid → fan-out storm
      - Redis hot key on celebrity_recent
      - Cache stampede on cold timeline rebuild
      - Fan-out worker poison message / partition skew
  ✓ Each with: symptom, detection metric, mitigation, degradation
  ✓ Mention SLO: fan_out_lag_seconds, timeline_p99_latency
  ✓ Graceful degradation: serve chronological, skip ranking
  ✓ Ask interviewer 1–2 thoughtful questions

WEAK SIGNALS:

  ✗ "We replicate for HA" only
  ✗ No user-visible symptom described
  ✗ No monitoring/alerting mentioned
```

---

## Problem Statement

```
╔════════════════════════════════════════════════════════════════════╗
║   DESIGN: HOME TIMELINE FOR A SOCIAL NEWS FEED                     ║
╠════════════════════════════════════════════════════════════════════╣
║                                                                    ║
║   PRODUCT:  Global social platform (Twitter/X-like)                ║
║             Mobile-first, 300M DAU                                 ║
║                                                                    ║
║   CORE USER JOURNEY:                                               ║
║     1. User opens app → sees home timeline of posts from           ║
║        accounts they follow, newest first (chronological)          ║
║     2. User scrolls → paginated load of older posts                ║
║     3. User creates post (text + optional media attachment)        ║
║     4. Followers see new post in their home timeline               ║
║     5. User can follow/unfollow, delete own posts, block users     ║
║                                                                    ║
║   SCALE (given):                                                   ║
║     • 300M DAU                                                     ║
║     • Global user base, AWS us-east-1 primary                      ║
║     • Very read-heavy workload                                     ║
║                                                                    ║
║   LATENCY (given if asked):                                        ║
║     • p99 feed load: < 300ms                                       ║
║     • Fan-out propagation: < 5s for 99th percentile follower       ║
║                                                                    ║
║   CONSISTENCY (given if asked):                                    ║
║     • Post ack must be durable (no silent loss)                    ║
║     • Feed visibility is eventually consistent (seconds OK)        ║
║                                                                    ║
║   OUT OF SCOPE (unless interviewer expands):                       ║
║     • Direct messages                                              ║
║     • Search, trending, hashtags                                   ║
║     • Ad insertion, "For You" algorithmic feed                     ║
║     • Notifications push pipeline (mention briefly OK)             ║
║     • Multi-region active-active                                   ║
╚════════════════════════════════════════════════════════════════════╝
```

---

## Capacity Estimation Reference

Worked math the interviewer uses to validate candidate estimates. Assumptions are defensible — candidate need not match exactly but must be within 2–3×.

### Step 1: User Activity Assumptions

```
GIVEN:
  DAU = 300M

ASSUME:
  100% of DAU load timeline at least once/day
  Average 20 timeline page loads per DAU per day (scroll sessions)
  10% of DAU post at least once per day (30M posters)
  Average 1.5 posts per posting user per day
  Average follower count for fan-out math: 300 (median user)
  Average followees per reader: 200

DERIVED DAILY VOLUMES:

  Timeline reads/day  = 300M × 20 = 6B reads/day
  Posts/day           = 30M × 1.5  = 45M posts/day
  New follows/day     ≈ 300M × 0.05 = 15M (rough, for backfill load)
```

### Step 2: QPS Calculations

```
AVERAGE QPS (÷ 86,400):

  Timeline read QPS  = 6B / 86400 ≈ 69,400/sec
  Post write QPS     = 45M / 86400 ≈ 520/sec

PEAK QPS (× 3 peak factor for evening / event spike):

  Timeline read QPS  ≈ 208,000/sec peak
  Post write QPS     ≈ 1,560/sec peak

FAN-OUT WRITE QPS (push path only):

  Non-celebrity posts: ~99.9% of posts
  Avg followers pushed: 300
  Fan-out ZADD/sec = 1,560 × 0.999 × 300 ≈ 468,000/sec average
  Peak fan-out     ≈ 1.4M Redis writes/sec

  THIS is why hybrid fan-out is mandatory — not the 520 post QPS.

SANITY CHECK:

  "468K timeline writes/sec is the design driver, not read QPS.
   Reads hit precomputed Redis — 208K ZREVRANGE/sec is manageable
   on a 50–100 node ElastiCache cluster with sharding."
```

### Step 3: Storage Estimates

```
TWEET METADATA (Cassandra/DynamoDB):

  Per tweet record:
    tweet_id:     8 bytes
    author_id:    8 bytes
    text:         ~560 bytes (280 chars × 2 UTF-16 max, avg 200)
    media_ids:    ~40 bytes (nullable)
    created_at:   8 bytes
    metadata:     ~100 bytes
    Total:        ~750 bytes raw → ~1.5 KB with indexes/overhead

  Daily tweet storage:
    45M × 1.5 KB = 67.5 GB/day raw
    × RF=3 (Cassandra) = 202 GB/day replicated
    × 365 × 5 years ≈ 370 TB (5-year tweet store)

  With compaction, tombstones, indexes: plan 500 TB Cassandra cluster

HOME TIMELINE (Redis — hot only):

  Per user timeline ZSET:
    800 tweet IDs × (8 byte ID + 8 byte score) + overhead ≈ 16 KB

  Hot users in cache (30% of DAU active daily with warm timeline):
    90M users × 16 KB = 1.44 TB Redis memory

  Add tweet body cache (top 1M viral tweets × 2 KB): +2 GB
  Add celebrity caches (10K celebrities × 100 tweets × 16 bytes): negligible

  ElastiCache: ~2 TB working set → r7g.2xlarge cluster (~15 shards)

MEDIA (S3):

  20% of posts include media, avg 500 KB stored (compressed)
  45M × 0.2 × 500 KB = 4.5 TB/day new S3 objects
  CloudFront egress dominates cost — not timeline DB
```

### Step 4: Bandwidth

```
FEED API RESPONSE:

  50 tweets per page, hydrated:
    50 × (tweet_id + author + text snippet + media URL + counts)
    ≈ 50 × 800 bytes = 40 KB per page (JSON compressed ~12 KB gzip)

  Egress at peak:
    208K reads/sec × 12 KB = 2.5 GB/sec ≈ 20 Gbps

  ALB + API tier handles 20 Gbps — large but feasible with
  100+ Timeline Service pods behind ALB.

KAFKA THROUGHPUT:

  tweet.created event: ~200 bytes
  1,560/sec × 200 bytes = 312 KB/sec produce ( trivial )

  Fan-out internal messages (if per-follower topics — DON'T):
    Would be 468K msgs/sec — BAD design.
    Correct: consumer reads tweet event, fans out in worker memory.
```

### Step 5: Bottleneck Summary

```
╔══════════════════════════════════════════════════════════════════════╗
║   BOTTLENECK RANKING (design must address #1 and #2)                 ║
╠══════════════════════════════════════════════════════════════════════╣
║   1. Fan-out write amplification (468K Redis writes/sec)             ║
║   2. Timeline read latency at 208K peak QPS (cache hit critical)     ║
║   3. Celebrity posts (50M followers = 50M writes if naive push)      ║
║   4. Graph lookup for fan-out (follower list pagination)             ║
║   5. Tweet hydration (N+1 if not batched)                            ║
╚══════════════════════════════════════════════════════════════════════╝
```

---

## API & Data Model Reference

### REST API (Reference)

```
POST /v1/posts
  Headers: Authorization: Bearer {jwt}, Idempotency-Key: {uuid}
  Body: {
    "text": "Hello world",
    "media_ids": ["m_abc123"],        // optional, pre-uploaded
    "reply_to": null                   // out of scope v1
  }
  Response 201: {
    "post_id": "1847293018472930123",
    "created_at": "2026-07-06T14:32:01.234Z",
    "author_id": "u_998877"
  }

GET /v1/timeline/home
  Query: cursor={post_id}&limit=50
  Response 200: {
    "posts": [ { PostObject }, ... ],
    "next_cursor": "1847293018472930123",
    "has_more": true
  }

POST /v1/users/{user_id}/follow
  Response 204

DELETE /v1/users/{user_id}/follow
  Response 204

DELETE /v1/posts/{post_id}
  Response 204

POST /v1/media/upload
  Returns media_id + S3 presigned PUT URL (client uploads direct to S3)
  CloudFront serves via https://media.example.com/{content_hash}.jpg
```

### Data Model — DynamoDB / Cassandra

```
TABLE: posts (DynamoDB)
  PK: post_id (String, snowflake)
  Attributes: author_id, text, media_ids[], created_at_ms, deleted BOOL
  GSI: author_id-created_at_ms (for user profile timeline fallback)

TABLE: posts_by_author (Cassandra CF)
  PK: author_id
  CK: created_at_ms (DESC clustering)
  Columns: post_id, text, media_ids, deleted
  Purpose: pull path, backfill on follow, celebrity user_timeline

TABLE: follow_graph (Aurora PostgreSQL or DynamoDB)
  PK: follower_id
  SK: followee_id
  Attributes: created_at
  GSI inverted: followee_id → follower_id (for fan-out pagination)
  
  Fan-out query:
    SELECT followee_id FROM follows WHERE follower_id = ?
  
  Follower enumeration (fan-out worker):
    SELECT follower_id FROM follows WHERE followee_id = ?
    PAGINATE 5000 per page — NEVER load 50M into memory

REDIS KEYS (ElastiCache Cluster Mode):

  home_timeline:{user_id}        ZSET  score=created_at_ms  member=post_id
  user_timeline:{author_id}      ZSET  (author's own posts)
  celebrity_recent:{author_id}   ZSET  trimmed to 100, TTL 86400s
  tweet:{post_id}                STRING JSON  TTL 3600s
  followees:{user_id}            SET of followee_ids  TTL 3600s
  blocked:{user_id}                SET  TTL none (small)
  fanout:dedupe:{post_id}        STRING "1"  TTL 604800s  (idempotency)

TRIM POLICY:
  ZREMRANGEBYRANK home_timeline:{id} 0 -801   // keep newest 800
```

### ID Generation

```
POST_ID: Snowflake (64-bit)
  [41-bit timestamp ms | 5-bit datacenter | 5-bit worker | 12-bit sequence]
  Generated by Post Service (per-pod worker ID from DynamoDB lease)

  Properties:
    Time-sortable → usable as ZSET score (or store explicit created_at_ms)
    No single-DB auto-increment bottleneck
    ~4096 IDs/ms per worker
```

---

## Architecture Reference Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│              HOME TIMELINE — AWS PRODUCTION ARCHITECTURE (REFERENCE)         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────┐   media GET    ┌─────────────────────────────────────────┐  │
│  │ Mobile / │───────────────►│ CloudFront → S3 (media.example.com)      │  │
│  │ Web      │                │ Cache-Control: public, max-age=31536000    │  │
│  └────┬─────┘                └─────────────────────────────────────────┘  │
│       │ HTTPS REST                                                          │
│       ▼                                                                     │
│  ┌─────────────┐    ┌──────────────────────────────────────────────────┐  │
│  │ Route 53    │───►│ ALB (L7, us-east-1, 3 AZ)                         │  │
│  └─────────────┘    └───────────┬──────────────────────┬───────────────┘  │
│                                 │                      │                   │
│                    ┌────────────▼──────────┐  ┌─────────▼──────────────┐   │
│                    │ Timeline Service     │  │ Post Service           │   │
│                    │ (EKS, 80 pods)       │  │ (EKS, 40 pods)         │   │
│                    │ GET /timeline/home   │  │ POST /posts            │   │
│                    └────────────┬─────────┘  └─────────┬──────────────┘   │
│                                 │                        │                 │
│         READ PATH               │                        │ WRITE PATH       │
│         ─────────               │                        │ ──────────       │
│                                 │                        │                 │
│  1. ZREVRANGE home_timeline     │                        │ 1. Persist post │
│  2. Merge celebrity ZSETs       │                        │ 2. Produce Kafka│
│  3. Batch hydrate tweet:{id}    │                        │ 3. Return 201   │
│  4. Filter blocked/deleted      │                        │                 │
│  5. Return JSON                 │                        │                 │
│                                 │                        │                 │
│         ┌───────────────────────▼────────────────────────▼───────────┐    │
│         │ ElastiCache Redis Cluster Mode (15 shards, r7g.2xlarge)     │    │
│         │   home_timeline:* | user_timeline:* | celebrity_recent:*  │    │
│         │   tweet:* (hydration cache)                                │    │
│         └───────────────────────▲──────────────────────────────────┘    │
│                                 │ fan-out ZADD (async)                     │
│         ┌───────────────────────┴──────────────────────────────────┐    │
│         │ Fan-out Worker Pool (EKS, 200 pods, autoscaling on lag)    │    │
│         │   Consumer group: fan-out-v3                               │    │
│         │   MSK topic: tweet.created (512 partitions)                │    │
│         └───────────────────────▲──────────────────────────────────┘    │
│                                 │                                          │
│         ┌───────────────────────┴──────────────┐  ┌──────────────────┐   │
│         │ Graph Service (EKS, 30 pods)          │  │ MSK (Kafka 3.5)  │   │
│         │   follower list pagination            │  │ 512 partitions   │   │
│         └───────────────────────▲──────────────┘  │ acks=all         │   │
│                                 │                  └────────▲─────────┘   │
│         ┌───────────────────────┴──────────────┐             │             │
│         │ Aurora PostgreSQL (follow graph)     │             │             │
│         │   db.r6g.8xlarge, 1 writer + 3 RO  │             │             │
│         └────────────────────────────────────┘             │             │
│                                                             │             │
│         ┌───────────────────────────────────────────────────┴─────────┐   │
│         │ Keyspaces (Cassandra-compatible) / DynamoDB                  │   │
│         │   posts table — source of truth                              │   │
│         │   posts_by_author — user timeline, celebrity pull            │   │
│         └─────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  OPTIONAL (mention if time):                                                │
│    Ranking Service ← Feature Store (DynamoDB) ← offline Spark on EMR       │
│    tweet.deleted topic → delete propagation workers                          │
│    timeline.backfill topic → new-follow backfill                             │
└─────────────────────────────────────────────────────────────────────────────┘

WRITE PATH (numbered):

  1. Client POST /v1/posts → ALB → Post Service
  2. Post Service: generate snowflake ID, write DynamoDB (WCU provisioned)
  3. Post Service: produce to MSK tweet.created (key=author_id, acks=all)
  4. Post Service: ZADD user_timeline:{author_id} (author sees own post)
  5. Return 201 to client (< 80ms p99 target)
  6. Fan-out worker consumes event:
       IF author.follower_count <= 50,000: paginate followers, pipeline ZADD
       ELSE: ZADD celebrity_recent:{author_id} only
  7. Followers see post on next timeline load (or push notification out of scope)

READ PATH (numbered):

  1. Client GET /v1/timeline/home → ALB → Timeline Service
  2. ZREVRANGE home_timeline:{user_id} 0 799 (single shard)
  3. SMEMBERS followees → filter is_celebrity → 5–15 celebrity IDs typical
  4. For each celebrity: ZREVRANGE celebrity_recent:{id} 0 99 (cached hot keys)
  5. Merge-sort by score (created_at_ms), take top 50 (+ over-fetch for deletes)
  6. Pipeline MGET tweet:{post_id} — miss → batch GetItem DynamoDB
  7. Filter: deleted flag, blocked authors
  8. Return JSON (< 200ms p99 target excluding client RTT)
```

---

## Deep Dive — Fan-Out on Write vs Read vs Hybrid

This section is the expected deep-dive territory for minutes 25–40.

### Fan-Out on Write (Push)

```
DEFINITION:
  When author posts, write post_id into every follower's home_timeline ZSET.

PRODUCTION IMPLEMENTATION (AWS):

  MSK topic: tweet.created
    partitions: 512
    replication.factor: 3
    min.insync.replicas: 2
    retention.ms: 604800000 (7 days)

  Fan-out worker (ECS/EKS):
    CELEBRITY_THRESHOLD = 50_000 followers
    FOLLOWER_PAGE_SIZE  = 5_000
    REDIS_PIPELINE_SIZE = 1_000 ZADD per pipeline round-trip
    ACTIVE_USER_DAYS    = 30  (skip fan-out to inactive users)

  Pseudocode:

    def handle_post(event):
        author = graph_service.get_user(event.author_id)
        zadd(user_timeline:{author.id}, event.post_id, event.ts)
        zremrangebyrank(user_timeline:{author.id}, 0, -801)

        if author.follower_count > CELEBRITY_THRESHOLD:
            zadd(celebrity_recent:{author.id}, event.post_id, event.ts)
            zremrangebyrank(celebrity_recent:{author.id}, 0, -101)
            return

        cursor = None
        while True:
            batch, cursor = graph_service.get_followers(
                author.id, limit=FOLLOWER_PAGE_SIZE, cursor=cursor)
            active = filter_last_active(batch, within_days=30)
            redis_pipeline_zadd(active, event.post_id, event.ts)
            if cursor is None:
                break

WRITE AMPLIFICATION MATH (300M DAU platform):

  Avg post: 520/sec × 300 followers = 156K ZADD/sec (manageable)
  Peak post: 1,560/sec × 300 = 468K ZADD/sec (Redis cluster scale event)
  Celebrity (pure push): 1 post × 50M = 50M ZADD (HOURS of work — unacceptable)

ADVANTAGES:
  Read is O(log N + page_size) — independent of follow count
  Predictable p99 for GET /timeline/home
  Natural cursor pagination via ZREVRANGEBYSCORE

DISADVANTAGES:
  Write amplification linear in follower count
  Wasted work for inactive followers (mitigate: active-only fan-out)
  Delete must propagate to all fan-out copies (async tweet.deleted)
  Follow → backfill 800 posts; unfollow → purge or lazy filter
```

### Fan-Out on Read (Pull)

```
DEFINITION:
  home_timeline not precomputed. On each feed load, fetch recent posts
  from each followee and merge-sort.

READ COST:

  User follows 200 accounts:
    200 × ZREVRANGE user_timeline:{followee} 0 99
    = 200 Redis/Cassandra queries per feed load

  At 208K peak feed QPS:
    208K × 200 = 41.6M queries/sec — NOT VIABLE at scale

  Power user with 5,000 follows:
    p99 latency explodes; product constraint usually caps follows at 5K

ADVANTAGES:
  Write is O(1) — one insert regardless of follower count
  Celebrity posts are free (one write)
  No fan-out workers, no Kafka consumer lag on delivery path

DISADVANTAGES:
  Read scales with followee count — violates 300ms p99 at 200+ followees
  Impossible to cache timeline (invalidates on any followee post globally)
  Merge CPU at read time: 200 lists × 100 posts = 20K candidates

WHEN PULL IS CORRECT:
  Celebrity accounts (in hybrid model)
  "Lists" or small curated graphs (< 50 members)
  MVP before fan-out infra exists (first 1M users)
```

### Hybrid Approach (Production Standard)

```
POLICY:

  IF follower_count <= 50,000:
      PUSH to each active follower's home_timeline
  ELSE:
      PULL at read time from celebrity_recent:{author_id}

THRESHOLD DERIVATION:

  Max acceptable fan-out per post: 50,000 ZADD ≈ 50ms pipeline at 1M ops/sec
  At 1,560 posts/sec peak: 50K × 1,560 = 78M ZADD/sec worst case IF
    every poster had 50K followers — they don't (power law).

  Realistic: 0.01% of posts from 50K+ accounts:
    0.156 posts/sec × 50K = 7,800 ZADD/sec from near-celebrities

  Set threshold at 50K; tune via load test. Twitter historically ~100K.

READ-TIME MERGE:

  candidates = ZREVRANGE home_timeline:{user} 0 799     // ~800 ids
  for celeb in user.followed_celebrities:                  // ~10 avg
      candidates += ZREVRANGE celebrity_recent:{celeb} 0 99
  merged = merge_sort_by_score(candidates)[:50]

  Cost: 1 + 10 = 11 Redis ops per feed load — acceptable

CELEBRITY CACHE — HOT KEY MITIGATION:

  celebrity_recent:nova sits on ONE Redis slot (CRC16 hash)
  50M followers reading = massive QPS to single key

  Mitigations (name at least two in interview):
    1. Local in-process cache (Caffeine) on Timeline pods — 5s TTL
    2. Read replicas: ElastiCache replica nodes per shard
    3. Application-layer request coalescing (single-flight pattern)
    4. Pre-warm CDN-style edge cache for top-100 celebrity timelines
    5. Split celebrity_recent:{id}:{version} with read-your-writes stickiness

KAFKA PARTITION STRATEGY:

  Key = author_id → ordering per author preserved
  Risk: spam account on single partition → hot partition
  Mitigation:
    Rate limit: 100 posts/hour/user at API Gateway (WAF + custom)
    Alert: kafka_consumer_lag{partition} > 30s
    Scale consumers to min(lag, 512 partitions)
```

### Delete, Follow, Block Edge Cases

```
DELETE POST:

  1. Soft delete in DynamoDB (deleted=true)
  2. Produce tweet.deleted to Kafka
  3. Delete worker:
       ZREM user_timeline:{author}
       For non-celebrity: paginate followers, pipeline ZREM home_timeline:{follower}
       For celebrity: ZREM celebrity_recent:{author} (single key)
  4. DEL tweet:{post_id} from Redis
  5. At hydrate: if deleted, skip (tombstone safety net)

  Alternative (cheaper): lazy filter at hydrate only — stale IDs in ZSET
  acceptable for 5 min; async ZREM catches up.

NEW FOLLOW:

  1. Insert follow edge in Aurora
  2. Produce timeline.backfill { follower_id, followee_id }
  3. Backfill worker: ZREVRANGE user_timeline:{followee} 0 799
     → pipeline ZADD to home_timeline:{follower}
  4. Add followee to followees:{follower} SET

BLOCK:

  Store blocked:{user_id} SET in Redis
  Filter at read time — no timeline purge required (cheaper)
  Blocked user's posts never appear even if still in ZSET
```

---

## Failure Modes

Five or more feed-specific failures with detection and mitigation.

### Failure 1: Celebrity Post Without Hybrid Routing

```
FAILURE:
  @nova (50M followers) posts; misconfigured threshold routes to push fan-out.

SYMPTOM:
  Fan-out consumer lag spikes to millions; Redis CPU 100%; feeds site-wide
  show posts from 6+ hours ago; Post API still returns 201.

DETECTION:
  • kafka_consumer_lag{group="fan-out-v3", partition="*"} > 60s
  • redis_cpu_utilization{shard="*"} > 90%
  • fan_out_queue_depth spike
  • Synthetic: post from test celebrity account, measure propagation SLO

BLAST RADIUS:
  All users — global feed staleness. Post path unaffected.

MITIGATION (immediate):
  1. Feature flag: force_pull_only_author_ids=[nova]
  2. Pause fan-out consumers; drain to DLQ
  3. Scale Redis read replicas (doesn't fix write storm)
  4. Rate-limit nova posting at API Gateway

MITIGATION (long-term):
  Auto-detect: follower_count > threshold at post time (denormalized count)
  Circuit breaker on fan-out worker: abort if follower_page > 50K
  Game day: quarterly celebrity post drill

PREVENTION:
  follower_count cached on user record, updated async from graph
  Post Service checks BEFORE producing to fan-out topic
```

### Failure 2: Kafka Hot Partition / Consumer Lag

```
FAILURE:
  Single author spam-posts 500 times/minute; all events to one partition.

SYMPTOM:
  Followers of that author see multi-minute delays; other feeds normal.
  Partition 247 lag = 2M; others healthy.

DETECTION:
  • kafka_consumer_lag by partition (not just aggregate)
  • post_rate_by_author > 10/min AND follower_count > 100K
  • fan_out_lag_seconds{p99} SLO burn

BLAST RADIUS:
  Followers of hot author primarily; if shared consumer pool starves,
  can cascade to global lag.

MITIGATION:
  Route spam accounts to quarantine topic (manual or automated)
  Increase partitions (requires rebalance — plan maintenance)
  Dedicated consumer group for high-follower authors
  API rate limit: 100 posts/hour/user

GRACEFUL DEGRADATION:
  Pull celebrity_recent at read time bypasses fan-out lag for celebrities
```

### Failure 3: Redis Hot Key on celebrity_recent

```
FAILURE:
  50M users load feed within 5 minutes of celebrity post; all hit
  celebrity_recent:nova on shard 7.

SYMPTOM:
  Redis shard-7 CPU 99%, p99 timeline latency 4s (baseline 120ms)
  Other shards healthy. GraphQL/REST timeout errors spike.

DETECTION:
  • redis_commands_per_second by key (ElastiCache EngineCPU + hot key log)
  • timeline_p99_latency correlation with celebrity post events
  • CloudWatch anomaly on ElastiCache CurrConnections

BLAST RADIUS:
  Feed load for users following nova (~40M users) degraded.

MITIGATION:
  Enable local cache on Timeline pods (5s TTL for celebrity ZSET)
  Read from replica nodes
  Pre-expand celebrity ZSET to application memory on post event (pub/sub warm)

PREVENTION:
  Top-100 celebrity list pre-warmed in Timeline Service memory
  Request coalescing: one ZREVRANGE per pod per celebrity per 1s
```

### Failure 4: Timeline Cache Stampede (Cold User Rebuild)

```
FAILURE:
  Redis memory pressure evicts 10M cold timelines; morning login spike
  triggers simultaneous rebuild from graph + user_timelines.

SYMPTOM:
  Aurora graph DB CPU 95%; timeline p99 8s; Redis miss rate 40%
  (baseline 2%). Cascading pod OOM from rebuild threads.

DETECTION:
  • redis_cache_miss_rate{key_prefix="home_timeline"} > 10%
  • aurora_database_connections > 80% max
  • timeline_rebuild_in_flight counter spike

BLAST RADIUS:
  Users with evicted timelines — often inactive-returning users.

MITIGATION:
  Single-flight rebuild: only one goroutine per user_id rebuilds
  Return partial feed (celebrity + recent self) while rebuild async
  Shed load: 503 with Retry-After on graph service

PREVENTION:
  Never evict DAU timelines (LFU not LRU for timeline keys)
  Probabilistic early refresh before TTL
  Cap rebuild concurrency per pod: max 50 in-flight
```

### Failure 5: N+1 Tweet Hydration Storm

```
FAILURE:
  Timeline Service deploy removes batch MGET; falls back to per-tweet
  DynamoDB GetItem.

SYMPTOM:
  Feed p99 2s; DynamoDB throttling on posts table; WCU exhausted.
  50 tweets × 208K QPS = 10.4M GetItem/sec attempted.

DETECTION:
  • dynamodb_consumed_read_capacity > provisioned
  • timeline_hydrate_latency_p99 > 100ms
  • post_service_batch_size metric missing

BLAST RADIUS:
  All feed loads globally.

MITIGATION:
  Rollback deploy
  Enable tweet:{id} Redis cache TTL 3600s emergency
  Reduce page size 50 → 20 via feature flag

PREVENTION:
  Integration test: assert single BatchGetItem per feed request
  Cache-aside with pipeline MGET for 50 keys
  Local Caffeine cache 10K entries per pod for viral posts
```

### Failure 6: Fan-Out Duplicate Delivery (At-Least-Once Kafka)

```
FAILURE:
  Consumer rebalance replays last 500 messages; duplicate ZADD attempts.

SYMPTOM:
  Users occasionally see duplicate posts in feed (same post_id twice).
  Rare but reportable; ranking/scoring skew if duplicates counted.

DETECTION:
  • feed_duplicate_post_reports (client telemetry)
  • fanout_dedupe_miss counter

BLAST RADIUS:
  Minimal — UX annoyance, not data loss.

MITIGATION:
  ZADD is idempotent (same member+score overwrites — no duplicate in ZSET)
  Verify: Redis ZSET member uniqueness holds

PREVENTION:
  fanout:dedupe:{post_id}:{follower_id} SET NX EX 604800 before ZADD
  Or rely on ZSET uniqueness (preferred — simpler)
```

### Failure 7: Graph DB Slow Follower Enumeration

```
FAILURE:
  Missing index on followee_id; fan-out worker full table scan per post.

SYMPTOM:
  Fan-out lag grows linearly with posts; Aurora CPU 100%;
  New posts take 10+ minutes to propagate.

DETECTION:
  • graph_follower_query_p99 > 50ms
  • fan_out_lag vs post_rate correlation

MITIGATION:
  Add GSI followee_id-follower_id on DynamoDB or index on Aurora
  Cache follower lists for accounts with < 10K followers in Redis
  Materialized follower snapshot in S3 for top accounts (extreme)

PREVENTION:
  Load test fan-out with 50K follower account monthly
  Denormalize follower_count; paginate with keyset, never OFFSET
```

---

## Rubric Scoring Guide — This Problem

Use with Interview Rubric.md. Problem-specific criteria below.

### Dimension 1: Requirements & Scope (Feed-Specific)

```
SCORE 4 INDICATORS:
  • Names home timeline as P0; profile timeline as P2
  • Quantifies: p99 < 300ms read, < 5s fan-out propagation
  • Explicitly excludes DMs, search, ads without prompting
  • Identifies fan-out as the design driver from requirements
  • Asks about delete/block/follow edge cases

SCORE 2 RED FLAGS:
  • Designs Instagram Reels or TikTok FYP instead of follow-based feed
  • No consistency discussion (durable post vs eventual feed)
  • Assumes 300M users all post 10×/day (bad estimation driver)
```

### Dimension 2: Capacity Estimation (Feed-Specific)

```
SCORE 4 INDICATORS:
  • Separates post QPS from timeline read QPS
  • Calculates fan-out ZADD/sec (posts × avg followers)
  • Redis memory estimate for hot timelines (800 × 16KB × active users)
  • Identifies fan-out amplification as #1 bottleneck
  • Peak factor 2–3× applied to evening spike

SCORE 2 RED FLAGS:
  • Only estimates posts, ignores 20 reads/user/day
  • "468K writes/sec" sounds wrong to them but they don't sanity-check
  • No connection between math and hybrid fan-out decision
```

### Dimension 3: API & Data Model (Feed-Specific)

```
SCORE 4 INDICATORS:
  • Cursor pagination on GET /timeline/home
  • Redis ZSET for home_timeline; Cassandra/DynamoDB for posts
  • Inverted index on follow graph for fan-out pagination
  • Snowflake IDs; idempotency key on POST
  • Separate celebrity_recent key schema

SCORE 2 RED FLAGS:
  • Offset/limit pagination
  • Full tweet JSON in timeline ZSET
  • Single RDS for everything
```

### Dimension 4: High-Level Architecture (Feed-Specific)

```
SCORE 4 INDICATORS:
  • Async fan-out via Kafka between Post API and Redis
  • Post API returns 201 before fan-out completes
  • ElastiCache for timelines; Aurora for graph; DynamoDB for posts
  • CloudFront for media only — NOT feed JSON
  • Multi-AZ ALB + stateless EKS pods

SCORE 2 RED FLAGS:
  • Synchronous fan-out in request path
  • CDN caches /timeline/home
  • No queue between write and fan-out
```

### Dimension 5: Deep Dive (Feed-Specific)

```
SCORE 4 INDICATORS:
  • Hybrid fan-out with numeric threshold (10K–100K)
  • Celebrity read-merge algorithm described step-by-step
  • Kafka: topic tweet.created, key=author_id, 256+ partitions
  • Redis: ZADD/ZREVRANGE/ZREMRANGEBYRANK with trim 800
  • Hot key mitigation for celebrity_recent
  • Active-user-only fan-out or backfill on follow

SCORE 2 RED FLAGS:
  • Pure push without celebrity caveat
  • "Use Kafka" with no partition key or consumer group
  • Cannot explain O(followers) vs O(followees) cost
```

### Dimension 6: Trade-offs & Alternatives (Feed-Specific)

```
SCORE 4 INDICATORS:
  • Push vs pull vs hybrid with explicit costs
  • "When I'd flip": if median followers > 10K, lower threshold
  • Redis vs Cassandra for timelines (speed vs durability)
  • Chronological now, ranking later without re-architecting
  • Operational cost: 200 fan-out workers, MSK cluster sizing

SCORE 2 RED FLAGS:
  • "Redis is fast so we use Redis" — no alternative named
  • Cannot state downside of their hybrid approach
```

### Dimension 7: Failure Modes (Feed-Specific)

```
SCORE 4 INDICATORS:
  • Celebrity push storm (specific)
  • Kafka partition lag (specific)
  • Redis hot key on celebrity_recent
  • Cache stampede on cold rebuild
  • N+1 hydration or graph DB scan
  • Metrics: fan_out_lag_seconds, timeline_p99, redis_cpu

SCORE 2 RED FLAGS:
  • Generic "DB goes down"
  • No graceful degradation ("serve stale feed, not 500")
```

### Dimension 8: Communication (Feed-Specific)

```
SCORE 4 INDICATORS:
  • Structured: requirements → math → API → arch → fan-out → failures
  • Checks in at 5, 10, 15, 25 minute marks
  • Draws second diagram for fan-out deep dive
  • Responds to celebrity and Redis-failure injections without panic

SCORE 2 RED FLAGS:
  • Silent 5+ minutes during fan-out
  • Argues that 50M fan-out is "fine with enough Redis"
```

### Hire Signal Calibration (This Problem)

```
SCORE 28–32: Strong hire L6/Principal — hybrid fan-out production depth
SCORE 24–27: Hire L5/L6 — solid hybrid, minor gaps in failure modes
SCORE 20–23: Lean hire L5 — architecture correct, deep dive shallow
SCORE 16–19: No hire — pure push or pull without hybrid
SCORE 8–15: Strong no hire — no estimation, no async fan-out
```

---

## Expert Model Answer — Full Walkthrough

Complete 45-minute answer narrative. Read only after self-scoring.

### Minutes 0–5: Clarification

```
"Before I design, I want to confirm scope and constraints.

Questions:
1. Chronological or ranked feed? 
2. Read vs write ratio?
3. Latency targets for feed load and post propagation?
4. Consistency — durable post vs feed visibility delay?
5. Media — inline or reference URLs?
6. Delete, block, follow/unfollow in scope?
7. Multi-region or single region MVP?
8. Mobile-first — anything about offline or pull-to-refresh?

[Interviewer answers]

I'll summarize:

FUNCTIONAL (P0):
  F1. Load paginated home timeline (posts from followed accounts)
  F2. Create post (text + media reference)
  F3. Follow / unfollow
  F4. Delete own post
  F5. Block user (hide posts)

FUNCTIONAL (P1 — defer if time):
  F6. Ranked feed
  F7. Real-time push updates (WebSocket)

NON-FUNCTIONAL:
  NFR1. p99 feed load < 300ms
  NFR2. Fan-out propagation < 5s p99
  NFR3. Post durable once 201 returned
  NFR4. 99.99% availability on read path
  NFR5. 300M DAU, global, read-heavy

SCOPE CUTS:
  Out: DMs, search, trending, ads, notifications

DESIGN DRIVER:
  Read-heavy (1000:1) with expensive write fan-out — hybrid push/pull
  is the core decision.

Does that match your expectations?"
```

### Minutes 5–10: Estimation

```
"300M DAU, assume each loads feed 20×/day:

  Reads: 300M × 20 = 6B/day → 69K/sec avg → 210K/sec peak (3×)

Posts: 10% of DAU post, 1.5 posts/day:
  30M × 1.5 = 45M posts/day → 520/sec avg → 1.6K/sec peak

Fan-out (critical):
  Avg 300 followers, push for non-celebrities:
  520 × 300 ≈ 156K Redis ZADD/sec avg
  Peak: 1.6K × 300 ≈ 468K ZADD/sec

Storage:
  45M posts × 1.5 KB × 3 RF × 5 yr ≈ 370 TB Cassandra/DynamoDB
  Hot timelines: 30% DAU × 16 KB ≈ 1.4 TB Redis

Bottleneck: fan-out write amplification, not read QPS.
Reads served from precomputed Redis ZSET — 210K ZREVRANGE/sec
on 15-shard ElastiCache cluster is ~14K ops/shard/sec — fine.

Celebrity edge: one post × 50M followers = 50M writes —
mandates hybrid threshold."
```

### Minutes 10–15: API & Data Model

```
"APIs:
  POST /v1/posts — Idempotency-Key header
  GET /v1/timeline/home?cursor=&limit=50
  POST/DELETE /v1/users/{id}/follow
  DELETE /v1/posts/{id}

Data:
  posts (DynamoDB): PK post_id
  posts_by_author (Cassandra): PK author_id, CK created_at_ms
  follow_graph (Aurora): (follower_id, followee_id), GSI on followee_id
  home_timeline:{user_id} (Redis ZSET): score=created_at_ms, member=post_id
  celebrity_recent:{author_id} (Redis ZSET): trimmed 100, TTL 24h
  tweet:{post_id} (Redis STRING): JSON, TTL 3600s

Post IDs: Snowflake for time-ordering and distributed generation.

Pagination: cursor = last post_id from previous page; query
ZREVRANGEBYSCORE with max=cursor_score."
```

### Minutes 15–25: Architecture

```
[Draw architecture diagram — see Reference Architecture]

Write path:
  Post Service → DynamoDB → MSK tweet.created → Fan-out workers → Redis
  Returns 201 immediately.

Read path:
  Timeline Service → Redis home_timeline + celebrity merge → hydrate → filter

AWS:
  ALB → EKS (Timeline 80 pods, Post 40 pods, Fan-out 200 pods)
  ElastiCache Redis Cluster Mode, 15 shards
  MSK 512 partitions, acks=all
  Aurora PostgreSQL graph, DynamoDB posts
  CloudFront + S3 media only

For 99.99% read availability:
  Multi-AZ everything, cache-first, if Redis miss → rebuild async
  with partial response, DynamoDB as source of truth for posts."
```

### Minutes 25–40: Deep Dive

```
"Hybrid fan-out — threshold 50,000 followers:

PUSH (follower_count ≤ 50K):
  Fan-out worker paginates followers 5000/page from Aurora GSI.
  Pipeline ZADD home_timeline:{follower_id} 1000 per round-trip.
  Skip users inactive > 30 days (lazy rebuild on login).
  ZREMRANGEBYRANK to keep 800 newest.

PULL (follower_count > 50K):
  ZADD user_timeline + celebrity_recent only.
  At read: merge home_timeline with celebrity_recent for followed celebs.
  ~10 celebrities × 1 ZREVRANGE each.

Kafka:
  Topic tweet.created, key=author_id, 512 partitions.
  Consumer group fan-out-v3, max consumers = 512.
  Idempotent: ZSET member uniqueness.

Celebrity @nova 50M followers:
  1 Redis write to celebrity_recent:nova.
  50M reads hit hot key — mitigate with pod-local cache 5s TTL,
  read replicas, single-flight.

Delete: tweet.deleted topic → async ZREM propagation.
Follow: timeline.backfill topic → ZADD last 800 from followee.

Ranking (P1): fan-out stays chronological; Ranking Service
re-scores 800 candidates at read time < 20ms."
```

### Minutes 40–45: Failure Modes

```
"Five production failures:

1. Celebrity misrouted to push → global fan-out lag
   Detect: consumer lag + redis CPU. Fix: force pull flag.

2. Kafka hot partition from spam poster
   Detect: per-partition lag. Fix: rate limit + quarantine topic.

3. Redis hot key celebrity_recent
   Detect: shard CPU spike after celebrity post.
   Fix: local cache, read replicas.

4. Cold timeline stampede after Redis eviction
   Detect: graph DB CPU + cache miss rate.
   Fix: single-flight rebuild, partial feed response.

5. N+1 hydration regression
   Detect: DynamoDB throttling. Fix: batch MGET, rollback.

Degradation: if Ranking down → chronological; if Redis down →
pull-only from Cassandra (slow, circuit-break after p99 > 1s);
if fan-out lag → reads still work, just stale.

SLOs: timeline_p99 < 300ms, fan_out_lag_p99 < 5s."
```

---

## Post-Interview Debrief Guide

For interviewer and candidate after the session.

### Debrief Flow (20 minutes)

```
1. SCORE FIRST (5 min)
   Interviewer fills rubric silently; candidate fills self-scoring worksheet.
   Compare scores dimension-by-dimension — gaps reveal blind spots.

2. STRONGEST MOMENT (2 min)
   Interviewer cites one specific quote or decision that was excellent.
   Example: "When you said '468K ZADD/sec is the bottleneck, not read
   QPS' — that changed the entire design direction correctly."

3. BIGGEST GAP (5 min)
   Focus on ONE dimension, not ten tips.
   Map gap → curriculum module:
     Estimation weak    → Week 9 Design Twitter Feed §3.13
     Fan-out shallow    → Week 9 §3.4–3.7
     Failure modes      → Week 9 Compound Scenario
     API/data model     → Week 2 SQL/NoSQL + Week 9 §3.9

4. REPLAY ONE SECTION (5 min)
   Candidate redoes either estimation or celebrity deep dive cold.
   Target: 90 seconds, same quality as model answer.

5. NEXT MOCK FOCUS (3 min)
   Assign one constraint to nail next time:
     "Next mock: proactively start failure modes at minute 35"
     "Next mock: draw fan-out diagram before architecture"
```

### Common Debrief Patterns

```
PATTERN: "Good architecture, no numbers"
  Root cause: skipped estimation or rushed it
  Fix: 3-minute estimation drill daily for one week

PATTERN: "Good push model, celebrity broke them"
  Root cause: hybrid fan-out not internalized
  Fix: rehearse celebrity scenario until automatic (< 60 sec)

PATTERN: "Knew Redis ZSET, couldn't explain Kafka"
  Root cause: async decoupling not connected to post latency SLO
  Fix: trace write path on whiteboard 10×

PATTERN: "Silent during deep dive"
  Root cause: communication dimension, not technical
  Fix: mock with "narration required" rule — no silence > 30 sec
```

### Incident Timeline Exercise (Optional 10-min Extension)

```
COMPOUND SCENARIO FOR DEBRIEF:

  19:00 — World Cup final; @fifa (18M followers) live-posts 40 updates/min.
  19:02 — Fan-out lag 0 → 900K. Feeds globally 20 min stale.
  19:04 — Redis shard-3 CPU 98%. Key: celebrity_recent:fifa.
  19:06 — Aurora graph replica lag 45s; follower pagination slow.
  19:08 — Timeline pods OOM; hydration batch size unset after deploy.

Ask candidate to:
  1. Rank root causes (which fired first?)
  2. First three mitigations in order
  3. What monitoring should have caught this at 19:01?

Model answers tie to Failure Modes section above.
```

---

## Self-Scoring Worksheet

Complete immediately after the mock. Do not read Model Answer first.

```
╔═══════════════════════════════════════════════════════════════════════╗
║   MOCK INTERVIEW 01 — SELF SCORE                                      ║
╠═══════════════════════════════════════════════════════════════════════╣
║   Date: ___________  Partner: ___________  Duration: 45 min           ║
╠═══════════════════════════════════════════════════════════════════════╣
║   Dimension                    │ You (1-4) │ Partner │ Notes          ║
║   ─────────────────────────────┼───────────┼─────────┼────────────    ║
║   1. Requirements & Scope      │           │         │                ║
║   2. Capacity Estimation         │           │         │              ║
║   3. API & Data Model            │           │         │              ║
║   4. High-Level Architecture     │           │         │              ║
║   5. Deep Dive (fan-out)         │           │         │              ║
║   6. Trade-offs & Alternatives   │           │         │              ║
║   7. Failure Modes               │           │         │              ║
║   8. Communication & Structure   │           │         │              ║
║   ─────────────────────────────┼───────────┼─────────┼────────────    ║
║   TOTAL                          │    /32    │   /32   │              ║
╠═══════════════════════════════════════════════════════════════════════╣
║   PHASE TIMING (check boxes):                                         ║
║   [ ] Clarification done by minute 5                                  ║
║   [ ] Estimation done by minute 10                                    ║
║   [ ] API/data model done by minute 15                                ║
║   [ ] Architecture done by minute 25                                  ║
║   [ ] Deep dive started by minute 25                                  ║
║   [ ] Failure modes started by minute 40                              ║
╠═══════════════════════════════════════════════════════════════════════╣
║   FAN-OUT CHECKLIST (did you mention?):                               ║
║   [ ] Hybrid push/pull with numeric threshold                         ║
║   [ ] Celebrity problem quantified (50M writes)                       ║
║   [ ] Kafka async decoupling (topic + partition key)                  ║
║   [ ] Redis ZSET schema (home_timeline, score, trim 800)              ║
║   [ ] Read-time merge for celebrities                                 ║
║   [ ] Hot key mitigation                                              ║
╠═══════════════════════════════════════════════════════════════════════╣
║   TOP STRENGTH: ______________________________________________        ║
║   TOP GAP:      ______________________________________________        ║
║   NEXT FOCUS:   ______________________________________________        ║
║   READY FOR REAL INTERVIEW?  [ ] Yes  [ ] 1 more mock  [ ] No         ║
╚═══════════════════════════════════════════════════════════════════════╝
```

### Five Self-Assessment Questions

```
1. Which dimension scored lowest? → Next week's study focus.

2. Did I reach deep dive before minute 30?
   No → practice with timer; cut API detail.

3. Did I state hybrid fan-out before interviewer injected celebrity?
   No → memorize threshold + merge algorithm.

4. Can I redo estimation from memory in 3 minutes?
   Write: 6B reads/day, 45M posts/day, 468K ZADD/sec peak.

5. Would I trust this design in production for 1 year?
   If no — which failure mode would wake me at 3am?
```

---

## Key Takeaways

```
1. HOME TIMELINE AT SCALE IS A FAN-OUT PROBLEM — not a database
   selection problem. The interview is won or lost on push/pull/hybrid.

2. ESTIMATION MUST INCLUDE FAN-OUT WRITES — 520 post QPS × 300
   followers = 156K–468K Redis writes/sec. That number drives hybrid.

3. CELEBRITY IS NOT AN EDGE CASE — power-law graphs mean celebrity
   routing is core architecture, not an optimization.

4. POST API MUST DECOUPLE FROM FAN-OUT — Kafka/MSK between persist
   and ZADD; 201 returned in < 80ms; lag is a user-visible SLO.

5. REDIS ZSET IS THE PRODUCTION ANSWER for hot timelines — but
   trimmed (800), sharded by user_id, with Cassandra fallback for cold.

6. CDN IS FOR MEDIA — never cache authenticated timeline JSON at
   CloudFront. See Week-01 CDN Fundamentals.

7. FAILURE MODES ARE FEED-SPECIFIC — celebrity push storm, partition
   lag, hot key, stampede, N+1 hydrate. Generic "replicate DB" fails
   the rubric at L6+.

8. TIME MANAGEMENT: 25 minutes to deep dive. Architecture without
   hybrid fan-out by minute 25 is behind schedule.
```

---

## Targeted Reading

```
CURRICULUM (in order):

  → Week-09 Design Twitter Feed.md — primary reference for this mock
    §3.4–3.7 fan-out deep dive
    §3.10 Redis sorted sets
    §3.11 Kafka async pipeline
    §3.13 capacity estimates

  → Week-09 Compound Scenario Social Platform Meltdown.md
    Multi-symptom feed incident timeline

  → Week-01 CDN Fundamentals.md — why feed JSON is not CDN-cached

  → Week-02 Caching Patterns.md — cache-aside, stampede, hot keys

  → Week-06 Outbox Pattern and CDC.md — if extending to exactly-once
    post + fan-out (bonus depth)

  → Week-15 Interview Rubric.md — 8-dimension scoring calibration

EXTERNAL:

  → Twitter's original scaling posts (fan-out @ scale, 2010–2013)
  → DDIA Ch 5 (replication), Ch 6 (partitioning)
  → AWS MSK best practices — partition count, consumer scaling
  → AWS ElastiCache Redis Cluster Mode — hash slots, hot keys
  → Google SRE Book Ch 4 — SLOs for fan_out_lag_seconds

PRACTICE:

  → Re-run this mock in 7 days cold (no reading Model Answer before)
  → Mock Interview 02 (when available) — different problem, same rubric
  → Teach hybrid fan-out to a peer in 5 minutes — if you can't teach
    it, you don't know it yet
```

---

*End of Mock Interview 01 — Design a Social News Feed*
