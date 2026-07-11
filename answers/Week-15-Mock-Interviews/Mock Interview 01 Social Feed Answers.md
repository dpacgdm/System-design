# Answer Key - Mock Interview 01 Social Feed

> Open only after attempting the learner file questions.

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
