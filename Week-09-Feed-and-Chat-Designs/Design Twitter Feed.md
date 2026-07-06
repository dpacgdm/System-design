# Design Twitter Feed (Home Timeline)

## Learning Objectives
```
╔════════════════════════════════════════════════════════════════╗
║   AFTER THIS MODULE, YOU WILL BE ABLE TO:                      ║
╟────────────────────────────────────────────────────────────────╢
║                                                                ║
║   1. Design a home timeline (feed) system from first           ║
║      principles: requirements, data model, read/write          ║
║      paths, and the fan-out tradeoff space                     ║
║                                                                ║
║   2. Explain fan-out on write (push), fan-out on read          ║
║      (pull), and hybrid fan-out — including when each          ║
║      wins, when each fails, and how production systems         ║
║      combine them                                              ║
║                                                                ║
║   3. Solve the celebrity problem: why a single user with       ║
║      50M followers breaks naive push models, and the           ║
║      engineering patterns (thresholds, lazy merge, local       ║
║      cache) that make hybrid fan-out work at scale             ║
║                                                                ║
║   4. Implement timeline storage with Redis sorted sets         ║
║      (ZADD, ZREVRANGE, ZRANGEBYSCORE), design Kafka            ║
║      topics for async fan-out, and layer caches correctly      ║
║      (CDN for media, Redis for timelines, app cache)           ║
║                                                                ║
║   5. Design timeline ranking pipelines (chronological vs       ║
║      ML-ranked), handle hot keys, and estimate capacity        ║
║      (writes/sec, storage, Redis memory, Kafka throughput)     ║
║                                                                ║
║   6. Map the architecture to AWS (ALB, ECS/EKS, ElastiCache,   ║
║      MSK, DynamoDB/RDS, S3, CloudFront) and diagnose a         ║
║      multi-symptom production incident on a social feed        ║
╚════════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Feed = just query posts from people I          ║
║   follow, sorted by time"                                          ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. At 500M DAU, a pull query joining follow graph +          ║
║   posts for 2,000 followees on every page load is O(followees)     ║
║   database reads. p99 latency explodes. The entire design is       ║
║   about avoiding that query at read time — via precomputation      ║
║   (push), caching (hybrid), or bounded fan-out (pull with limits). ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "Push fan-out is always better because          ║
║   reads are hot"                                                   ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Push fan-out turns ONE write into N writes. A celebrity   ║
║   with 80M followers creates 80M timeline insertions per tweet.    ║
║   Write amplification kills you. Production systems ALWAYS use     ║
║   hybrid: push for normal users, pull/lazy-merge for celebrities.  ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "Redis can hold everyone's full timeline"       ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. 500M users × 800 tweets cached × ~100 bytes/tweet ID      ║
║   = 40 TB of timeline data in Redis alone. Timelines are TRIMMED   ║
║   (top 800-1000 tweet IDs per user), cold users evicted, and       ║
║   full history lives in durable storage (Cassandra/DynamoDB).      ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "Chronological feed is simpler — skip ranking"  ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG FOR PRODUCT, RIGHT FOR MVP. Users expect relevance.        ║
║   Ranking adds a scoring pipeline, feature store, and merge step   ║
║   — but you can ship chronological first and add ranking as a      ║
║   second pass without changing the fan-out architecture.           ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Kafka guarantees the feed is real-time"        ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Kafka guarantees durable, ordered delivery to             ║
║   consumers — NOT instant visibility. Consumer lag of 30 seconds   ║
║   means tweets appear 30 seconds late. Fan-out workers, partition  ║
║   skew, and hot partitions create lag that users experience as     ║
║   "my tweet didn't show up in followers' feeds."                   ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #6: "CDN caches the feed"                           ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Home timelines are per-user, authenticated, and           ║
║   personalized (ranking, ads, "who to follow"). CDN caches         ║
║   tweet MEDIA (images/video via CloudFront + S3) and static        ║
║   assets — never the timeline JSON itself. See CDN Fundamentals    ║
║   for why Vary: Cookie destroys hit ratio on personalized content. ║
╚════════════════════════════════════════════════════════════════════╝
```

---

## Core Teaching

### 3.1 What We Are Building

```
THE PRODUCT SURFACE:

  HOME TIMELINE (also called "feed"):
    The reverse-chronological (or ranked) stream of tweets from
    accounts the user follows, plus injected content:
      → Promoted tweets (ads)
      → "Who to follow" suggestions
      → Algorithmic "For You" mix (Twitter/X today)
      → Retweets, quote tweets, replies (depending on product rules)

  USER TIMELINE (profile):
    All tweets BY a specific user. Simpler — single partition key
    (author_id). Not the focus of this module.

  LIST TIMELINE:
    Curated subset of follow graph. Same fan-out mechanics, different
    follow source.

THIS MODULE FOCUSES ON: Home Timeline at Twitter scale.
```

### 3.2 Requirements

```
FUNCTIONAL REQUIREMENTS:

  F1. User can post a tweet (text, media, poll, retweet)
  F2. Followers see the tweet in their home timeline
  F3. User can scroll paginated feed (cursor-based, not offset)
  F4. User can delete a tweet → removed from all fan-out copies
  F5. User can mute/block → tweets hidden from feed
  F6. (Optional) Feed ranked by relevance, not just time

NON-FUNCTIONAL REQUIREMENTS (Twitter-scale assumptions):

  → 500M DAU, 200M MAU posting
  → 6,000 tweets/sec average, 25,000 tweets/sec peak
  → 500B timeline reads/day (~5.8M reads/sec average)
  → Read:write ratio ≈ 1000:1 (reads dominate)
  → p99 feed load latency: < 200ms
  → Fan-out propagation: < 5 seconds for 99th percentile follower
  → Availability: 99.99% for read path
  → Durability: tweets never lost once acknowledged

THE CORE TENSION:

  Reads are 1000× more frequent than writes.
  Naive approach: optimize writes.
  Correct approach: optimize READS even if writes become expensive —
  BUT cap write amplification via hybrid fan-out.
```

### 3.3 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         TWITTER FEED — SYSTEM MAP                        │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────┐    ┌─────────────┐    ┌──────────────────────────────────┐│
│  │ Mobile / │───►│ API Gateway │───►│ Timeline Service (Feed API)      ││
│  │ Web App  │    │ + ALB       │    │  GET /v2/timeline/home           ││
│  └──────────┘    └─────────────┘    └───────────┬──────────────────────┘│
│                                                    │                     │
│                    ┌───────────────────────────────┼───────────────────┐ │
│                    │                               │                   │ │
│                    ▼                               ▼                   ▼ │
│           ┌────────────────┐            ┌─────────────────┐  ┌─────────┴──┐
│           │ Redis Cluster  │            │ Ranking Service │  │ Tweet      │
│           │ (home_timeline │            │ (ML scores)     │  │ Service    │
│           │  sorted sets)  │            └─────────────────┘  │ (hydrate   │
│           └───────▲────────┘                                  │  tweet     │
│                   │                                           │  bodies)   │
│                   │ fan-out writes                            └─────▲──────┘
│           ┌───────┴────────┐                                        │
│           │ Fan-out Worker │◄──── Kafka: tweet.created ─────────────┤
│           │ (consumer grp) │                                        │
│           └───────▲────────┘                                  ┌─────┴──────┐
│                   │                                           │ Post API   │
│           ┌───────┴────────┐                                  │ (write)    │
│           │ Graph Service  │                                  └────────────┘
│           │ (follow lists) │
│           └───────▲────────┘
│                   │
│           ┌───────┴────────┐         ┌─────────────────┐
│           │ User/Graph DB  │         │ Tweet Store     │
│           │ (follow edges) │         │ (Cassandra /    │
│           └────────────────┘         │  DynamoDB)      │
│                                      └─────────────────┘
│                                                                          │
│  Media path (CDN — see CDN Fundamentals):                               │
│  Tweet body references media_id → S3 origin → CloudFront edge → user    │
└─────────────────────────────────────────────────────────────────────────┘

TWO PATHS:

  WRITE PATH (post tweet):
    Client → Post API → persist tweet → publish tweet.created to Kafka
    → Fan-out workers consume → for each follower (or cached timeline):
       ZADD home_timeline:{follower_id} timestamp tweet_id
    → (Celebrity) skip push, mark tweet in celebrity cache for pull-merge

  READ PATH (load feed):
    Client → Timeline Service → ZREVRANGE home_timeline:{user_id}
    → get list of tweet_ids → hydrate from Tweet Service / cache
    → (if hybrid) merge with pulled celebrity tweets
    → (optional) Ranking Service re-orders
    → return JSON to client
```

### 3.4 Fan-Out on Write (Push Model)

```
DEFINITION:

  Fan-out on WRITE = when a user posts, IMMEDIATELY write the tweet ID
  into every follower's precomputed home timeline.

  "Push the tweet to followers at write time."

FLOW:

  @alice posts tweet T100 at timestamp 1712345678900
  @alice has followers: [bob, carol, dave, ... 500 users]

  Fan-out worker:
    FOR EACH follower_id IN alice.followers:
      ZADD home_timeline:{follower_id} 1712345678900 T100

  When @bob loads feed:
    ZREVRANGE home_timeline:bob 0 49 WITHSCORES
    → [T100, T99, T98, ...]  (already there — O(log N + M) read)

ADVANTAGES:

  ✓ Read path is FAST and predictable
    → Single Redis ZREVRANGE per page
    → No join across follow graph at read time
    → Scales with page size, NOT follow count

  ✓ Read-heavy workload optimized
    → 1000:1 read:write ratio favors precomputation

  ✓ Natural pagination
    → Cursor = last tweet_id + score from previous page
    → ZREVRANGEBYSCORE with max=cursor_score

DISADVANTAGES:

  ✗ Write amplification = follower count
    → @normal_user (500 followers): 500 Redis writes per tweet
    → @celebrity (50M followers): 50 MILLION writes per tweet
    → ONE tweet could take hours and terabytes of write bandwidth

  ✗ Wasted work for inactive followers
    → User hasn't opened app in 6 months
    → You still wrote to their timeline 6 months of tweets

  ✗ Follow/unfollow is expensive
    → New follow: must backfill recent tweets from followee into timeline
    → Unfollow: must remove all followee's tweets from timeline
    → Block: same as unfollow + filter

  ✗ Storage multiplication
    → Same tweet_id stored in N follower timelines
    → 6K tweets/sec × avg 300 followers = 1.8M timeline writes/sec

WHEN PUSH WORKS:

  → Follower count below CELEBRITY_THRESHOLD (typically 10K–100K)
  → Followers are active (open app regularly)
  → Write pipeline has capacity for amplification factor
  → You have async fan-out (Kafka) so post API stays fast
```

### 3.5 Fan-Out on Read (Pull Model)

```
DEFINITION:

  Fan-out on READ = home timeline is NOT precomputed. At read time,
  query recent tweets from each followed user and merge.

  "Pull tweets from followees when the user opens the app."

FLOW:

  @bob follows [@alice, @carol, @news, ... 800 accounts]

  When @bob loads feed:
    recent_tweets = []
    FOR EACH followee_id IN bob.followees:
      tweets = SELECT * FROM tweets_by_user
               WHERE user_id = followee_id
               ORDER BY created_at DESC LIMIT 100
      recent_tweets.merge(tweets)
    SORT recent_tweets BY created_at DESC
    RETURN top 50

ADVANTAGES:

  ✓ Write path is O(1)
    → Post tweet: single insert into tweets_by_user
    → No fan-out workers, no Kafka consumer lag for delivery
    → Celebrity posts are cheap — one write regardless of followers

  ✓ No wasted work for inactive users
    → Only compute when someone actually reads

  ✓ Follow is cheap
    → Insert edge in follow graph — done
    → No backfill unless user requests feed

  ✗ Read path is O(followees)
    → 800 followees = 800 queries (or 800 key lookups) per feed load
    → p99 latency scales with follow count
    → Power users with 5,000 follows kill this model

  ✗ Hard to cache
    → Timeline changes every time ANY followee posts
    → Cache key invalidation is global across follow graph

  ✗ Merge at read time is CPU-heavy
    → 800 lists × 100 tweets = 80K candidates to merge/sort

WHEN PULL WORKS:

  → Small follow graphs (< 100 followees)
  → Celebrity accounts (write amplification avoidance)
  → "Latest from this list" aggregation services
  → Prototype / MVP before fan-out infrastructure exists
```

### 3.6 Hybrid Fan-Out (Production Standard)

```
INSIGHT (from Twitter's 2010–2013 evolution):

  Neither pure push nor pure pull works at scale.
  Production systems use HYBRID:

  ┌─────────────────────────────────────────────────────────────────┐
  │  IF author.follower_count <= CELEBRITY_THRESHOLD:               │
  │      PUSH tweet to all followers' home_timeline caches          │
  │  ELSE:                                                          │
  │      STORE tweet in author's user timeline only                 │
  │      At READ time: MERGE cached timeline + celebrity pulls      │
  └─────────────────────────────────────────────────────────────────┘

TYPICAL THRESHOLD: 10,000 – 100,000 followers
  (Twitter historically used ~100K; exact number is tuned operationally)

HYBRID READ PATH:

  Step 1: ZREVRANGE home_timeline:bob 0 799
          → 800 pre-pushed tweet IDs (from normal followees)

  Step 2: FOR EACH celebrity IN bob.followed_celebrities:
            ZREVRANGE user_timeline:{celebrity_id} 0 99
          → recent tweets from celebrities (pull at read time)
          (Often cached in a shared "celebrity tweet cache")

  Step 3: MERGE two sorted lists by timestamp (merge-sort, O(n+m))

  Step 4: HYDRATE tweet bodies, apply ranking, return

WRITE PATH FOR CELEBRITY:

  @mega_star (50M followers) posts T500:
    → INSERT into user_timeline:mega_star (single write)
    → INSERT into tweets table (single write)
    → Publish to Kafka for search index, notifications, analytics
    → DO NOT fan-out to 50M home timelines
    → Optionally: write to "celebrity_recent" cache (single key)

COST COMPARISON — ONE CELEBRITY TWEET:

  Pure push:  50,000,000 Redis ZADD operations
  Hybrid:     1 Redis ZADD (user timeline) + 50M reads merge at fan read time
              BUT celebrity tweets are cached — one ZADD to celebrity cache,
              millions of reads hit ONE hot key (see Hot Keys section)

WHY HYBRID WINS:

  → 99.9% of users have < 10K followers → push works, reads stay fast
  → 0.1% of users (celebrities) generate massive fan-out → pull at read
  → Average follow graph includes ~5–20 celebrities → bounded pull cost
  → Write amplification capped at threshold × tweets/sec
```

### 3.7 The Celebrity Problem (Deep Dive)

```
THE CELEBRITY PROBLEM:

  A small fraction of users have a massive fraction of followers.
  In any social graph following a power-law distribution:

    Top 0.1% of users → 30–50% of all follow edges
    Top 1% of users   → 60–70% of all follow edges

  If you push fan-out for everyone:
    → System capacity is dictated by the SINGLE LARGEST celebrity
    → One tweet from @elonmusk = more work than 100,000 normal tweets

QUANTIFIED EXAMPLE:

  Platform: 200M users, 6,000 tweets/sec average

  Without hybrid:
    Assume 10 celebrity tweets/day from accounts with 20M+ followers
    Each celebrity tweet: 20M fan-out writes
    10 × 20M = 200M extra writes/day = 2,315 writes/sec JUST for celebrities
    Peak event (World Cup goal, election): one account posts 50 times in
    an hour → 50 × 80M = 4 BILLION fan-out writes

  With hybrid (threshold = 50K followers):
    Celebrity tweet: 1 write
    200M users × avg 15 followed celebrities × load feed 20×/day =
      read-time celebrity merges — but cached, ~O(15) Redis reads per feed load

SOLUTIONS BEYOND SIMPLE THRESHOLD:

  1. CELEBRITY THRESHOLD (baseline)
     follower_count > N → no push fan-out

  2. CELEBRITY TWEET CACHE (shared read cache)
     Key: celebrity_recent:{user_id}
     ZADD on post, TTL 24h, trimmed to 100 tweets
     All followers read SAME key → amortized cache benefit
     Problem: HOT KEY (see Failure Modes)

  3. LOCAL CELEBRITY REPLICA
     Replicate celebrity timeline to Redis nodes in each AZ/region
     Read from local replica → reduce cross-AZ traffic

  4. FAN-OUT TO ACTIVE USERS ONLY
     Track last_active timestamp per user
     Only push to users active in last 30 days
     Inactive user: rebuild timeline on next login (lazy hydration)
     Reduces wasted writes by 40–60% on many platforms

  5. TIERED FAN-OUT VIA KAFKA PRIORITY TOPICS
     Normal fan-out: kafka topic fan-out-standard (many partitions)
     Near-celebrity (10K–100K): fan-out-slow (throttled consumers)
     Celebrity: no fan-out topic — pull only

  6. EVENT-DETECTION BACKPRESSURE
     Detect: post rate from single user > 10/min AND followers > 1M
     Auto-switch to pull-only for 1 hour
     Prevents spam / compromised account from melting fan-out pool
```

### 3.8 Timeline Ranking

```
CHRONOLOGICAL vs RANKED FEED:

  Chronological:
    ORDER BY tweet_timestamp DESC
    Simple, predictable, trusted by journalists and power users
    Implemented via Redis sorted set score = Unix timestamp (ms)

  Ranked (algorithmic):
    ORDER BY relevance_score DESC
    Score computed from:
      → Recency decay: score × e^(-λ × age_hours)
      → Engagement velocity: likes + retweets + replies in first hour
      → Author affinity: how often you engage with this author
      → Content type: video boost, link penalty
      → Social proof: "liked by 3 people you follow"
      → Negative signals: muted keywords, "show less often" feedback

RANKING ARCHITECTURE (decoupled from fan-out):

  Fan-out delivers CANDIDATE tweet IDs (800–1000)
  Ranking service scores and re-orders TOP 50 for display

  ┌──────────────┐     ┌─────────────────┐     ┌──────────────────┐
  │ Timeline     │────►│ Candidate IDs   │────►│ Ranking Service  │
  │ Service      │     │ (800 tweets)    │     │ (Lightweight ML) │
  └──────────────┘     └─────────────────┘     └────────┬─────────┘
                                                         │
                                                         ▼
                                                ┌──────────────────┐
                                                │ Feature Store    │
                                                │ (user affinities,│
                                                │  tweet engagement│
                                                │  precomputed)    │
                                                └──────────────────┘

TWO-PHASE RANKING (production pattern):

  Phase 1 — HEAVY PRECOMPUTATION (offline / nearline):
    Batch jobs compute user-user affinity, topic interests, author scores
    Store in Redis / DynamoDB feature store
    Updated every 15 min – 1 hour

  Phase 2 — LIGHTWEIGHT ONLINE SCORING (feed load):
    For each candidate tweet_id:
      score = w1×recency + w2×affinity[author] + w3×engagement_rate
    Sort by score, take top 50
    Target: < 20ms for 800 candidates

SCORE AS REDIS SORTED SET:

  Option A: Fan-out stores timestamp as score (chronological)
            Ranking re-orders in application memory after hydrate

  Option B: Fan-out stores pre-computed score (requires re-scoring on engagement)
            ZADD on every like/retweet → expensive

  Option C (common): Two structures
            home_timeline:{user_id} — chronological candidates (ZSET)
            ranking overrides applied at read time in Timeline Service

  Production choice: Option A or C — keep fan-out simple, rank at read.

DEGRADATION:

  If Ranking Service is down:
    → Serve chronological from Redis (feature flag: rank_feed=false)
    → SLO: unranked feed still loads in < 200ms
    → Better stale ranking than empty feed
```

### 3.9 Data Model

```
ENTITIES:

  User:
    user_id (snowflake/bigint)
    username, display_name, avatar_url
    follower_count (denormalized, updated async)
    is_celebrity (follower_count > threshold)

  Follow Edge:
    (follower_id, followee_id, created_at)
    Stored in Graph DB or sharded SQL
    Index: follower_id → list of followee_ids
    Index: followee_id → list of follower_ids (for fan-out)

  Tweet:
    tweet_id (snowflake — time-sortable)
    author_id
    text, media_ids[], created_at
    retweet_of, quote_of (nullable)
    deleted (soft delete flag)

  Home Timeline (materialized view):
    Redis ZSET: home_timeline:{user_id}
    Member: tweet_id
    Score: created_at_ms (or ranking score)

STORAGE CHOICE BY ACCESS PATTERN:

  ┌────────────────────────┬────────────────────┬─────────────────────┐
  │ Data                   │ Access pattern     │ Store               │
  ├────────────────────────┼────────────────────┼─────────────────────┤
  │ Tweet body             │ By tweet_id        │ Cassandra/DynamoDB  │
  │ User timeline          │ By author_id, time │ Cassandra + Redis   │
  │ Home timeline          │ By user_id, time   │ Redis ZSET (hot)    │
  │ Follow graph           │ By follower/followee│ SQL/Graph DB        │
  │ Engagement counts      │ By tweet_id        │ Redis counters      │
  │ Ranking features       │ By user_id         │ Feature store/Redis │
  └────────────────────────┴────────────────────┴─────────────────────┘

TWEET ID AS SNOWFLAKE:

  64-bit ID: [timestamp_ms | datacenter | worker | sequence]
  Properties:
    → Globally unique
    → Roughly time-ordered (good for ZSET scores)
    → No coordination on single DB auto-increment

  score = tweet_id >> 22  (extract timestamp portion)
  OR score = explicit created_at_ms stored in tweet metadata
```

### 3.10 Redis Sorted Sets — Timeline Implementation

```
WHY REDIS SORTED SETS (ZSET):

  ✓ O(log N) insert (ZADD)
  ✓ O(log N + M) range query (ZRANGE/ZREVRANGE)
  ✓ Automatically sorted by score
  ✓ Trim old entries (ZREMRANGEBYRANK)
  ✓ Count entries (ZCARD)
  ✓ Single-key operation — shard by user_id

KEY SCHEMA:

  home_timeline:{user_id}     — precomputed feed (push + merged)
  user_timeline:{user_id}     — all tweets BY this user (author timeline)
  celebrity_recent:{user_id}  — hot cache for celebrity pull path
  tweet:{tweet_id}            — hydrated tweet JSON (optional L2 cache)
  followees:{user_id}         — SET of followee_ids (for pull merge list)

COMMANDS — WRITE PATH (fan-out worker):

  # Post tweet T9876543210 at score 1712345678900
  MULTI
  ZADD user_timeline:alice 1712345678900 9876543210
  ZREMRANGEBYRANK user_timeline:alice 0 -801    # keep newest 800
  EXEC

  # Fan-out to follower bob
  ZADD home_timeline:bob 1712345678900 9876543210
  ZREMRANGEBYRANK home_timeline:bob 0 -801

COMMANDS — READ PATH:

  # Get page 1 (newest 50)
  ZREVRANGE home_timeline:bob 0 49 WITHSCORES

  # Cursor pagination (score strictly less than cursor)
  ZREVRANGEBYSCORE home_timeline:bob (1712345600000 -inf LIMIT 0 50

  # Check timeline depth
  ZCARD home_timeline:bob

DELETE TWEET:

  # Soft delete in tweet store, then:
  ZREM home_timeline:bob 9876543210
  # Problem: must ZREM from ALL follower timelines if push model
  # Solution: async "delete propagation" job via Kafka tweet.deleted
  # OR: tombstone filter at read time (check deleted flag on hydrate)

REDIS CLUSTER SHARDING:

  Key home_timeline:bob → hash slot = CRC16("home_timeline:bob") mod 16384
  Each user's timeline on ONE shard — no cross-slot multi-key ops needed
  Hot celebrity cache: celebrity_recent:elon → ONE slot → HOT KEY RISK

  Hash tags for co-location (if needed):
    {user:bob}:home_timeline  and  {user:bob}:followees
    → same slot, enables MULTI/EXEC across both

MEMORY ESTIMATE PER USER TIMELINE:

  800 tweet IDs × 8 bytes (int64) + 8 bytes score + overhead ≈ 16KB/user
  50M DAU with hot timelines in Redis: 50M × 16KB = 800 GB
  → Not all users fit in Redis — use TTL + LRU eviction for cold users
  → Only ~20–30% of users active daily → 160–240 GB manageable on cluster

PIPELINING FOR FAN-OUT:

  # Batch ZADD for one tweet to many followers (pipeline, not MULTI)
  pipe = redis.pipeline()
  for follower_id in batch_of_1000_followers:
      pipe.zadd(f"home_timeline:{follower_id}", {tweet_id: score})
      pipe.zremrangebyrank(f"home_timeline:{follower_id}", 0, -801)
  pipe.execute()
  # Amortizes round-trip latency — critical at 6K tweets × 300 followers
```

### 3.11 Kafka — Async Fan-Out Pipeline

```
WHY KAFKA BETWEEN POST AND FAN-OUT:

  Post API must return in < 100ms — cannot synchronously fan-out to 500 followers
  Decouple: Post API → Kafka → Fan-out workers (async)

TOPIC DESIGN:

  tweet.created
    Key: author_id (keeps one author's tweets ordered in partition)
    Value: { tweet_id, author_id, created_at_ms, text_hash }
    Partitions: 256–1024 (parallel fan-out consumers)

  tweet.deleted
    Key: author_id
    Value: { tweet_id, author_id }

  timeline.backfill
    Key: follower_id
    Value: { follower_id, followee_id }  (triggered on new follow)

PRODUCER (Post API):

  1. Persist tweet to Cassandra/DynamoDB
  2. Produce to tweet.created (acks=all for durability)
  3. Return 201 to client with tweet_id
  Client sees tweet on OWN profile immediately (read own user_timeline)
  Followers see tweet within fan-out lag (typically 1–5 sec)

CONSUMER (Fan-out Worker Group):

  @kafka_listener(topics=["tweet.created"], group="fan-out-v2")
  def handle_tweet(event):
      author = get_user(event.author_id)
      if author.follower_count > CELEBRITY_THRESHOLD:
          zadd_user_timeline(event)
          zadd_celebrity_cache(event)
          return  # NO fan-out

      followers = get_followers_paginated(event.author_id)
      for batch in chunks(followers, 1000):
          pipeline_zadd_to_home_timelines(batch, event.tweet_id, event.score)

PARTITION STRATEGY:

  Key = author_id → all tweets from same author go to same partition
  Benefits: ordering per author (delete after create processed in order)
  Risk: hot partition if one author posts 1000×/sec (spam/abuse)

  Mitigation:
    → Rate limit posts per author at API gateway
    → Detect hot partition lag, route spam accounts to dead-letter queue

CONSUMER LAG — THE USER-VISIBLE METRIC:

  lag = high_watermark - consumer_offset (per partition)

  If lag = 60 seconds:
    → Tweets appear 60 seconds late in followers' feeds
    → Alert: fan_out_consumer_lag_seconds p99 > 10

  Scale: add consumer instances up to partition count
  256 partitions → max 256 parallel fan-out consumers

DEAD LETTER / RETRY:

  Failed fan-out (Redis timeout): retry 3× with backoff
  Still failing: produce to fan-out.dlq for manual replay
  Idempotency: ZADD is idempotent (same tweet_id + score = no duplicate)
```

### 3.12 Cache Layers

```
CACHE HIERARCHY (bottom = durable, top = fastest):

  Layer 0: Durable store (Cassandra/DynamoDB/S3)
    Source of truth for tweets, users, graph

  Layer 1: Redis Cluster (hot timelines + tweet bodies)
    home_timeline:{user_id} — precomputed feed
    tweet:{tweet_id} — serialized tweet JSON, TTL 1h
    engagement:{tweet_id} — like/retweet counts

  Layer 2: Application-local cache (in-process Caffeine/Guava)
    Per Timeline Service pod: LRU 10K tweet bodies
    Avoids Redis round-trip for viral tweets everyone hydrates

  Layer 3: CDN (CloudFront) — MEDIA ONLY
    https://pbs.twimg.com/media/ABC123.jpg
    → S3 origin, Cache-Control: public, max-age=31536000, immutable
    → Content-hash URLs — tweet deletion doesn't require CDN purge
    → See CDN Fundamentals: never cache authenticated feed JSON

READ PATH WITH CACHES:

  1. ZREVRANGE home_timeline:bob → [id1, id2, ... id50]
  2. For each id:
       check local cache → hit? use it
       else check Redis tweet:{id} → hit? use it, populate local
       else fetch from Cassandra batch → populate Redis + local
  3. Batch mget tweet:id1 tweet:id2 ... (Redis pipeline)
  4. Merge, rank, respond

CACHE INVALIDATION:

  Tweet deleted:
    DEL tweet:{id} from Redis
    Async ZREM from timelines OR tombstone at hydrate

  User blocked:
    Filter at read time (block list in Redis SET)
    No need to purge timelines — cheaper

  Follow/unfollow:
    Follow: backfill job writes last 800 tweets from followee
    Unfollow: lazy filter (remove followee from merge) OR async purge job

TIMELINE CACHE STAMPEDE:

  Cold user (evicted from Redis) opens app:
    Cache miss on home_timeline:bob
    → Rebuild from graph + user timelines (EXPENSIVE)
    → 1000 cold users simultaneously = thundering herd

  Fix:
    → Request coalescing: one rebuild per user, others wait
    → stale-if-error: serve last known good from backup
    → Probabilistic early refresh before TTL expiry
    → See CDN Fundamentals stale-while-revalidate pattern (same idea)
```

### 3.13 Capacity Estimates

```
ASSUMPTIONS (Twitter-scale):

  DAU:                    500M
  Daily tweets:           500M  (~6,000 tweets/sec avg, 25K peak)
  Timeline reads/day:     500B  (~5.8M reads/sec avg)
  Avg followers/user:     300 (for fan-out calc)
  Avg followees/user:     800
  Celebrity threshold:    50,000 followers
  Timeline cache depth:   800 tweet IDs
  Avg tweet body:         500 bytes (JSON)
  % users posting daily:  10%

TRAFFIC:

  Write (tweets):           6,000/sec
  Fan-out writes (push):    6,000 × 300 avg followers = 1.8M ZADD/sec
                            (excluding celebrities — ~95% of tweets)
                            Effective: ~1.7M Redis writes/sec
  Timeline reads:           5.8M/sec
  Tweet hydrations/read:    50 tweets × 5.8M = 290M tweet lookups/sec
                            (mitigated by caching — 90%+ hit rate target)

STORAGE:

  Tweets/day:               500M × 500 bytes = 250 GB/day raw
  Annual tweet storage:     ~90 TB (before replication)
  With RF=3 Cassandra:      ~270 TB

  Redis timeline memory:
    Active users in cache:  100M (20% of DAU)
    Per user:               16 KB
    Total:                  1.6 TB (+ 30% overhead) ≈ 2.1 TB
    ElastiCache cluster:    r6g.2xlarge × 20 shards ≈ handles 2.5TB

KAFKA:

  tweet.created events:     6,000/sec × 200 bytes = 1.2 MB/sec ingress
  Partitions:               512
  Fan-out consumers:        512 (one per partition max)
  Each consumer:            ~12 tweets/sec × 300 followers = 3,600 ZADD/sec
                            (pipeline batches — achievable on modern CPU)

BANDWIDTH:

  Feed API response:        50 tweets × 1KB JSON = 50 KB/response
  5.8M reads/sec × 50 KB  = 290 GB/sec egress (dominant cost!)
  Mitigation: compression (gzip/brotli) → 5× reduction
  CloudFront for API: NO (personalized). ALB + regional edge caching of
  static tweet media via CDN.

SERVERS (rough):

  Timeline Service:         5.8M RPS / 5K RPS per pod = 1,160 pods
  Fan-out workers:          512 Kafka consumers (CPU-bound on Redis pipeline)
  Post API:                 6K WPS / 2K per pod = 3 pods (+ HA)
  Graph Service:            100 pods (follower list lookups)

  AWS mapping in Section 3.14
```

### 3.14 AWS Architecture

```
REGION: us-east-1 (primary) + eu-west-1, ap-northeast-1 (read replicas)

┌─────────────────────────────────────────────────────────────────────────┐
│                              AWS ARCHITECTURE                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  EDGE:                                                                   │
│    Route 53 (latency routing) → CloudFront (media only) → S3           │
│    API: Route 53 → Global Accelerator → Regional ALB                   │
│                                                                          │
│  INGRESS:                                                                │
│    AWS WAF (rate limit, bot control)                                     │
│    Application Load Balancer (TLS termination, path routing)             │
│      /v2/tweets      → Post Service (ECS Fargate)                        │
│      /v2/timeline/*  → Timeline Service (ECS Fargate, auto-scaling)      │
│      /v2/graph/*     → Graph Service                                     │
│                                                                          │
│  COMPUTE:                                                                │
│    ECS Fargate / EKS for stateless services                              │
│    Auto Scaling: Timeline Service on CPU + custom metric feed_p99        │
│    Fan-out Workers: ECS on EC2 (network-optimized, pinned to AZ)         │
│                                                                          │
│  CACHING:                                                                │
│    ElastiCache Redis Cluster Mode Enabled                                │
│      20 shards × 3 replicas = 60 nodes                                   │
│      r6g.2xlarge (52GB RAM each) — timeline ZSETs + tweet cache          │
│    Application: Caffeine local cache on Timeline pods                    │
│                                                                          │
│  MESSAGING:                                                              │
│    Amazon MSK (Managed Kafka)                                            │
│      3 brokers × m5.2xlarge (prod), 512 partitions on tweet.created      │
│      retention: 7 days (replay for fan-out recovery)                     │
│                                                                          │
│  DURABLE STORAGE:                                                        │
│    Amazon Keyspaces (Cassandra-compatible) OR DynamoDB                   │
│      tweets table: PK=tweet_id                                           │
│      user_tweets: PK=user_id, SK=created_at                              │
│    RDS PostgreSQL (Aurora): follow graph, user profiles                  │
│      Read replicas for follower list queries                             │
│    S3: media objects, Kafka archive, analytics export                   │
│                                                                          │
│  SEARCH / ANALYTICS (out of feed hot path):                              │
│    OpenSearch for tweet search                                           │
│    Kinesis → S3 → Athena for ranking feature pipelines                   │
│                                                                          │
│  OBSERVABILITY:                                                          │
│    CloudWatch metrics + alarms                                           │
│    X-Ray tracing on Timeline Service                                   │
│    Prometheus/Grafana on EKS (fan-out lag, Redis memory)                 │
│    PagerDuty via SNS                                                     │
│                                                                          │
│  MULTI-REGION:                                                           │
│    Global timeline reads: route to nearest region's Redis replica        │
│    Writes: primary region only → replicate via Kafka mirroring           │
│    Celebrity cache: replicated to all regions (read-local)               │
└─────────────────────────────────────────────────────────────────────────┘

IAM / NETWORK:

  VPC private subnets for Redis, MSK, Keyspaces
  Timeline Service in private subnet, NAT for external calls
  Security groups: Timeline → Redis:6379, MSK:9092 only

COST DRIVERS (monthly, illustrative):

  ElastiCache 2TB RAM:        ~$25K–40K
  MSK 3× m5.2xlarge:           ~$1.5K
  ECS Timeline 1200 tasks:     ~$80K (depends on task size)
  Keyspaces/DynamoDB storage:  ~$20K+ at 270TB replicated
  Data transfer out:           DOMINANT — feed egress at scale
  CloudFront (media):          Offloads S3 egress, pays for itself
```

---

## Concrete Examples

### 4.1 End-to-End Write Flow

```
SCENARIO: @alice (2,400 followers, below threshold) posts "Hello world"

STEP 1 — CLIENT → POST API
━━━━━━━━━━━━━━━━━━━━━━━━━━

  POST /v2/tweets HTTP/2
  Authorization: Bearer <oauth_token>
  Content-Type: application/json

  { "text": "Hello world" }

  Post Service:
    1. Validate auth, rate limit (300 tweets/3hr per user)
    2. Generate tweet_id = snowflake.next() → 18446744073709551616
    3. created_at_ms = 1712345678900
    4. INSERT INTO tweets (Keyspaces):
         INSERT INTO tweets_by_id (tweet_id, author_id, text, created_at)
         VALUES (18446744073709551616, alice_id, 'Hello world', ...)
    5. ZADD user_timeline:alice (sync, fast — author's own view)
    6. PRODUCE Kafka tweet.created:
         key=alice_id
         value={"tweet_id":18446744073709551616,"author_id":alice_id,
                "created_at_ms":1712345678900}
    7. RETURN 201 { "tweet_id": "18446744073709551616", ... }

  Latency budget: 45ms p99 (no fan-out in request path)

STEP 2 — KAFKA → FAN-OUT WORKER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Consumer fan-out-v2-42 reads partition keyed to alice_id

  Load follower list:
    SELECT follower_id FROM follows WHERE followee_id = alice_id
    → 2,400 IDs (cached in Graph Service Redis: followers:alice_id)

  Pipeline to Redis (24 batches × 100):
    for batch in 24:
      pipe.zadd(f"home_timeline:{fid}", {18446744073709551616: 1712345678900})
      pipe.zremrangebyrank(f"home_timeline:{fid}", 0, -801)
    pipe.execute()

  Duration: ~80ms for 2,400 followers
  @bob's home_timeline now contains the new tweet

STEP 3 — CLIENT READ (follower @bob)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  GET /v2/timeline/home?count=50 HTTP/2

  Timeline Service:
    ids = ZREVRANGE home_timeline:bob 0 49
    → includes 18446744073709551616

    # Hybrid merge (bob follows 2 celebrities)
    celeb_ids = pull_celebrity_tweets(bob.followed_celebrities, limit=100)
    merged = merge_sort_by_score(ids, celeb_ids)[:50]

    tweets = hydrate_batch(merged)  # Redis mget + Cassandra fallback
    ranked = ranking_service.score(bob, tweets)  # optional
    RETURN 200 { "tweets": [...], "cursor": "..." }

  Latency: 85ms p99 (Redis 2ms + hydrate 40ms + rank 20ms + overhead)
```

### 4.2 Celebrity Write Flow

```
SCENARIO: @mega_star (52M followers) posts during product launch

  Post API: same as above — 1 Cassandra write, 1 Kafka produce
  Fan-out worker:
    author.follower_count = 52_000_000 > THRESHOLD (50_000)
    → SKIP follower fan-out
    → ZADD user_timeline:mega_star 1712345678900 tweet_id
    → ZADD celebrity_recent:mega_star 1712345678900 tweet_id
    → ZREMRANGEBYRANK celebrity_recent:mega_star 0 -101
    → DONE in 3 Redis commands (~1ms)

  52M followers NOT updated at write time.

  When @bob (follows mega_star) loads feed:
    candidates = ZREVRANGE home_timeline:bob 0 799
    celeb = ZREVRANGE celebrity_recent:mega_star 0 99
    merged = merge(candidates, celeb)
    → mega_star's tweet appears in feed within read latency (no fan-out lag)
```

### 4.3 Redis Schema Reference

```
# ─── HOME TIMELINE (per user, push model) ───
# Type: Sorted Set
# Key:  home_timeline:{user_id}
# Score: created_at_ms (double)
# Member: tweet_id (string representation of int64)

ZADD home_timeline:10042 1712345678900 9876543210001
ZADD home_timeline:10042 1712345678000 9876543209000
ZREVRANGE home_timeline:10042 0 49 WITHSCORES

ZCARD home_timeline:10042
# (integer) 847

# Trim to 800 max (remove oldest = lowest rank)
ZREMRANGEBYRANK home_timeline:10042 0 -801

# ─── USER TIMELINE (author's own tweets) ───
ZADD user_timeline:7 1712345678900 9876543210001

# ─── CELEBRITY CACHE (shared across all readers) ───
# HOT KEY — see Failure Modes
ZREVRANGE celebrity_recent:999 0 19 WITHSCORES

# ─── TWEET BODY CACHE ───
SET tweet:9876543210001 '{"id":"...","text":"Hello","author_id":7}' EX 3600

# ─── FOLLOWEE SET (for hybrid pull list) ───
SADD followees:10042 999 1001 1002
SMEMBERS followees:10042
```

### 4.4 Kafka Message Schemas

```json
// Topic: tweet.created — Partition key: author_id
{
  "event_id": "evt_8f3a2b1c",
  "tweet_id": "18446744073709551616",
  "author_id": "7",
  "created_at_ms": 1712345678900,
  "type": "original",
  "retweet_of": null,
  "media_ids": [],
  "follower_count_at_post": 2400
}

// Topic: tweet.deleted
{
  "tweet_id": "18446744073709551616",
  "author_id": "7",
  "deleted_at_ms": 1712345700000
}

// Topic: graph.follow.created (triggers backfill)
{
  "follower_id": "10042",
  "followee_id": "7",
  "created_at_ms": 1712345800000
}
```

### 4.5 Fan-Out Worker (Pseudocode)

```python
CELEBRITY_THRESHOLD = 50_000
TIMELINE_MAX_LEN = 800

def handle_tweet_created(event):
    author = user_service.get(event.author_id)
    score = event.created_at_ms
    tweet_id = event.tweet_id

    redis.zadd(f"user_timeline:{author.id}", {tweet_id: score})
    redis.zremrangebyrank(f"user_timeline:{author.id}", 0, -(TIMELINE_MAX_LEN + 1))

    if author.follower_count > CELEBRITY_THRESHOLD:
        redis.zadd(f"celebrity_recent:{author.id}", {tweet_id: score})
        redis.zremrangebyrank(f"celebrity_recent:{author.id}", 0, -101)
        return

    cursor = None
    while True:
        followers, cursor = graph_service.get_followers_page(
            author.id, limit=1000, cursor=cursor
        )
        if not followers:
            break
        pipe = redis.pipeline(transaction=False)
        for fid in followers:
            key = f"home_timeline:{fid}"
            pipe.zadd(key, {tweet_id: score})
            pipe.zremrangebyrank(key, 0, -(TIMELINE_MAX_LEN + 1))
        pipe.execute()
```

### 4.6 Timeline Service Read Path (Pseudocode)

```python
def get_home_timeline(user_id, cursor=None, limit=50):
    if cursor:
        candidates = redis.zrevrangebyscore(
            f"home_timeline:{user_id}", max=f"({cursor}",
            min="-inf", start=0, num=limit * 2
        )
    else:
        candidates = redis.zrevrange(
            f"home_timeline:{user_id}", 0, limit * 2 - 1, withscores=True
        )

    celeb_followees = redis.smembers(f"followees:{user_id}")
    celeb_tweets = []
    for celeb_id in celeb_followees:
        recent = redis.zrevrange(
            f"celebrity_recent:{celeb_id}", 0, 99, withscores=True
        )
        celeb_tweets.extend(recent)

    merged = merge_sorted(candidates, celeb_tweets)[:limit]
    tweets = hydrate_tweets([t[0] for t in merged], user_id)

    if feature_flags.is_enabled("ranked_feed", user_id):
        tweets = ranking_service.rank(user_id, tweets)
    return {"tweets": tweets, "cursor": merged[-1][1] if merged else None}
```

### 4.7 Follow Backfill and Pagination

```
NEW FOLLOW: backfill worker ZADDs last 800 tweets from followee into follower timeline.
UNFOLLOW: lazy filter via unfollowed_set — nightly compaction async.
CURSOR: ZREVRANGEBYSCORE with exclusive max=cursor_score — no offset pagination.
```

### 4.8 Media + CDN Integration

```
Tweet media served via CloudFront + S3 — NOT through Timeline Service.
Cache-Control: public, max-age=31536000, immutable on content-hash URLs.
See CDN Fundamentals — never cache authenticated feed JSON at edge.
```

---

## Production Patterns

### 5.1 How Real Systems Evolved

```
TWITTER (2010–2013 engineering posts):

  2010: Pure pull — MySQL at read time. Broke at scale.
  2012: Hybrid fan-out with Redis timelines (Manhattan)
  2013+: Gizzard sharding, dedicated Timeline Service
  Later: Algorithmic ranking on chronological candidates

  Pattern: "Fanout on write for most users, fanout on read for celebrities."

FACEBOOK / INSTAGRAM / LINKEDIN:

  All converged on hybrid push + pull for celebrities
  All added ranking layer after chronological MVP worked
  All use async workers (Kafka/Celery) — never sync fan-out in post API
```

### 5.2 Active-User-Only Fan-Out

```
60% of users inactive 30+ days → skip fan-out to them.
On login: trigger timeline.rebuild (once, async via Kafka).
Saves ~40% of fan-out Redis writes continuously.
Tradeoff: first login after hiatus is slower (acceptable).
```

### 5.3 Idempotency

```
Kafka at-least-once delivery → ZADD is idempotent (safe retry).
Delete/create ordering: same author_id partition key guarantees order.
Engagement counters need idempotency keys per event.
```

### 5.4 Multi-Region and Degradation

```
Writes: single primary region (us-east-1) → Kafka → fan-out → Redis primary.
Reads: regional Redis replicas (50–200ms replication lag acceptable for feed).
Degradation ladder:
  L1: disable ranking → chronological
  L2: skip celebrity merge
  L3: reduce page size 50 → 20
  L4: stale cache only
  L5: fail whale
Each level = feature flag with automated trigger on SLO breach.
```

### 5.5 Production Metrics Dashboard

```
Timeline Service: feed.home.p99_ms, feed.hydrate.p99_ms, feed.rank.p99_ms
Fan-out: fan_out.consumer_lag_seconds (CRITICAL), fan_out.celebrity_skip.count
Redis: memory.used_pct, cpu.max_shard, evicted_keys_per_sec
Kafka: MaxOffsetLag per partition (not just aggregate)
Alerts: P1 lag > 60s, P1 feed p99 > 1000ms, P2 Redis memory > 85%
```

---

## Failure Modes

### Failure 1: Hot Key on Celebrity Cache

```
SCENARIO:
  @world_cup posts during final. 80M followers, hybrid model.
  ONE key: celebrity_recent:world_cup
  500K+ reads/sec on single Redis shard (single-threaded)
  ALL keys on that shard slow — collateral damage

DETECT:
  redis.cpu{shard=42} = 99%
  feed.celebrity_merge.p99_ms spike at event start

FIX:
  1. App micro-cache (Caffeine, TTL 2s) — collapse QPS per pod
  2. Key splitting: celebrity_recent:X:0..3 — 4× QPS reduction
  3. Read from ElastiCache replica nodes round-robin
  4. Dedicated Redis cluster for celebrity keys
  5. Pre-event playbook: temporary push to active users
```

### Failure 2: Fan-Out Consumer Lag Storm

```
SCENARIO:
  Viral event: 40K tweets/sec for 3 minutes (normal 6K)
  Kafka lag: 2s → 5 minutes. Users: "friends don't see my tweet"
  Worker OOM → partition rebalance → cascade

DETECT:
  kafka.consumer.lag rising monotonically
  Post API OK (async problem — users blame feed, not post)

FIX:
  Scale consumers to partition count (512)
  Rate limit trending topic posts
  Temporarily raise celebrity threshold (50K → 10K)
  Auto-scale on lag metric (long-term)
```

### Failure 3: Redis Memory Pressure

```
SCENARIO:
  Memory 96% → volatile-lru evicts home_timeline keys
  Hit ratio 94% → 60% → Keyspaces 4× load → hydrate timeouts → 503

DETECT:
  redis.memory.used_pct > 90%, evicted_keys spike
  feed.hydrate.cassandra_fallback_rate spike

FIX:
  Add ElastiCache shards (online resharding)
  Trim depth 800 → 400
  Separate clusters: ZSET timelines vs STRING tweet bodies
  Alert at 75%, 85% — act before eviction
```

### Failure 4: Timeline Rebuild Thundering Herd

```
SCENARIO:
  Redis shard AZ failure → 5M users cache miss simultaneously
  5M rebuilds × 800 followees = graph service collapse in 90 seconds

DETECT:
  feed.timeline.cache_miss_rate 5% → 80%
  graph_service RPS vertical spike

FIX:
  Redis multi-AZ auto-failover (~30s)
  Circuit breaker: max 100 concurrent rebuilds globally
  Rebuild via rate-limited Kafka queue (10K/sec max)
  Serve empty feed + retry banner — NOT unbounded rebuild
```

### Failure 5: Delete Propagation Lag

```
SCENARIO:
  Tweet fan-out to 50K timelines. Purge takes 45s.
  Illegal content requires < 5s removal.

FIX:
  Soft delete flag checked at HYDRATE time (immediate invisibility)
  Bloom filter of deleted IDs (24h window) on all Timeline pods
  Async ZREM for storage cleanup
```

### Failure 6: Kafka Partition Hot Spot

```
SCENARIO:
  Compromised API key: 10K tweets/sec from one author_id → one partition

DETECT:
  Per-partition lag dashboard (partition 247 >> others)

FIX:
  Rate limit 300 tweets/3hr per user at API Gateway
  Quarantine topic for spam (no fan-out)
```

### Failure 7: Ranking Cascading Failure

```
SCENARIO:
  Feature store slow → ranking blocks → Timeline thread pool exhausted
  Feed 504 despite healthy Redis timelines

FIX:
  50ms ranking timeout → chronological fallback
  Bulkhead thread pools (ranking vs core feed)
  rank_feed=false feature flag (Level 1 degradation)
```

### Failure 8: Stale Follower List Cache

```
SCENARIO:
  Viral account gains 50K followers/hour. Cached list stale.
  50K followers miss tweets in their timeline.

FIX:
  Invalidate followers:{author} on graph.follow.created
  Fan-out compares follower_count_at_post vs cache, refreshes if mismatch
  Reconciliation job for accounts > 10K followers
```

---

## SRE Diagnostic Toolkit
### 7.1 First 5 Minutes Checklist

```
□ Global or regional? (Route 53 per-region error rates)
□ Timeline Service or downstream? (compare feed p99 vs redis p99 vs hydrate p99)
□ Redis healthy? (ElastiCache CPU, memory, evictions, CLUSTER INFO)
□ Fan-out lag? (kafka-consumer-groups --describe --group fan-out-v2)
□ Recent deploy? (ECS rollout last 30 min → rollback candidate)
```

### 7.2 Redis Commands

```bash
redis-cli -c -h $HOST CLUSTER INFO
redis-cli -c ZCARD home_timeline:10042
redis-cli -c ZREVRANGE home_timeline:10042 0 4 WITHSCORES
redis-cli -c MEMORY USAGE home_timeline:10042
redis-cli -c SLOWLOG GET 20
redis-cli -c --latency -h $HOST
```

### 7.3 Kafka Commands

```bash
kafka-consumer-groups.sh --bootstrap-server $BOOTSTRAP \
  --group fan-out-v2 --describe

aws cloudwatch get-metric-statistics \
  --namespace AWS/Kafka --metric-name MaxOffsetLag \
  --dimensions Name="Consumer Group",Value="fan-out-v2" \
  --period 60 --statistics Maximum
```

### 7.4 Metrics Thresholds

```
┌────────────────────────────┬──────────┬──────────┐
│ feed.home.p99_ms           │ > 300    │ > 1000   │
│ fan_out.consumer_lag_sec   │ > 10     │ > 60     │
│ redis.memory.used_pct      │ > 85%    │ > 95%    │
│ feed.hydrate.miss_rate     │ > 15%    │ > 40%    │
└────────────────────────────┴──────────┴──────────┘
```

### 7.5 Trace Patterns

```
Healthy (120ms): zrevrange 2ms → celebrity 4ms → hydrate 45ms → rank 25ms
Hot celebrity: celebrity_merge 850ms → check redis shard CPU
Fan-out lag: tweet missing from zrevrange → check kafka partition lag
Ranking block: ranking.score 5000ms → rank_feed=false immediately
```

---

## Decision Framework
### 8.1 Push vs Pull vs Hybrid

```
┌─────────────────────────┬─────────────────┬─────────────────┬─────────────────┐
│ Criterion               │ Push (write)    │ Pull (read)     │ Hybrid          │
├─────────────────────────┼─────────────────┼─────────────────┼─────────────────┤
│ Read latency            │ Excellent (O(1))│ Poor (O(follow))│ Excellent       │
│ Write cost per tweet    │ O(followers)    │ O(1)            │ O(min(foll,T))  │
│ Celebrity handling      │ Breaks          │ Natural         │ Threshold split │
│ Inactive user waste     │ High            │ None            │ Medium (filter) │
│ Follow/unfollow cost    │ Backfill/purge  │ Cheap           │ Backfill normal │
│ Implementation          │ Kafka + Redis   │ Graph + DB      │ Both paths      │
│ Consistency lag         │ Fan-out lag     │ None            │ Fan-out lag     │
│                         │ (1–5 sec)       │                 │ for normal only │
├─────────────────────────┼─────────────────┼─────────────────┼─────────────────┤
│ USE WHEN                │ Read-heavy,     │ MVP, small      │ Production at   │
│                         │ low follower    │ graphs, celeb   │ scale (default) │
│                         │ counts          │ accounts        │                 │
└─────────────────────────┴─────────────────┴─────────────────┴─────────────────┘

DECISION TREE:

  START: Building a home timeline feed

  Q1: Is this MVP / < 10K users?
    YES → Pull model (simplest). Revisit at scale.
    NO  → Continue

  Q2: Read:write ratio > 100:1?
    YES → Precomputation (push or hybrid) required
    NO  → Pull may still work (LinkedIn early model)

  Q3: Any user with > 10K followers?
    YES → Hybrid mandatory. Set CELEBRITY_THRESHOLD.
    NO  → Pure push acceptable (for now — plan hybrid anyway)

  Q4: Post API latency SLO < 100ms?
    YES → Async fan-out via Kafka (never sync push)
    NO  → You can sync push small graphs (still not recommended)

  Q5: Need ranked feed?
    YES → Chronological candidates + online ranking layer
          (do NOT fan-out by rank score — scores change)
    NO  → ZSET score = timestamp. Ship faster.
```

### 8.2 Redis vs Cassandra vs DynamoDB for Timelines

```
┌──────────────────┬────────────────────────────────────────────────────────┐
│ Store            │ Verdict for home timeline                               │
├──────────────────┼────────────────────────────────────────────────────────┤
│ Redis ZSET       │ YES — hot path. Sub-ms reads, natural time ordering,   │
│                  │ trim, pagination. Limited by RAM — cache not archive.   │
├──────────────────┼────────────────────────────────────────────────────────┤
│ Cassandra /      │ YES — durable tweet storage + user_timeline archive.    │
│ Keyspaces        │ NOT for every feed read — too slow (ms vs µs).          │
├──────────────────┼────────────────────────────────────────────────────────┤
│ DynamoDB         │ YES — alternative to Cassandra.                        │
│                  │ PK=user_id, SK=timestamp. GSIs expensive for fan-out.   │
├──────────────────┼────────────────────────────────────────────────────────┤
│ PostgreSQL       │ NO for hot timeline at 500M DAU.                       │
│                  │ OK for follow graph (Aurora + read replicas).           │
├──────────────────┼────────────────────────────────────────────────────────┤
│ Elasticsearch    │ NO for timeline ordering.                               │
│                  │ YES for tweet search (separate concern).                │
└──────────────────┴────────────────────────────────────────────────────────┘
```

### 8.3 Chronological vs Ranked

```
SHIP CHRONOLOGICAL FIRST IF:
  → MVP / early product
  → User base expects real-time (breaking news, finance)
  → Ranking team/model not ready
  → Regulatory transparency requirements

ADD RANKING WHEN:
  → Engagement metrics plateau on chronological
  → Feature store infrastructure exists
  → You can degrade to chronological (ranking is NEVER hard dependency)
  → A/B framework ready to measure engagement lift vs latency cost

RANKING ARCHITECTURE RULE:
  Fan-out stores chronologically.
  Ranking re-orders at read time.
  NEVER re-fan-out on score change (likes don't trigger 300 Redis writes).
```

### 8.4 Kafka vs SQS vs Direct Fan-Out

```
┌─────────────┬─────────────────────────────────────────────────────────────┐
│ Option      │ When to use                                                  │
├─────────────┼─────────────────────────────────────────────────────────────┤
│ Kafka (MSK) │ High throughput (6K+ events/sec), ordering per key,       │
│             │ replay for recovery, multiple consumers (fan-out + search +  │
│             │ analytics from same tweet.created stream). PRODUCTION CHOICE.│
├─────────────┼─────────────────────────────────────────────────────────────┤
│ SQS         │ Lower throughput, simpler ops, no ordering guarantee.       │
│             │ OK for backfill jobs, delete propagation — not main fan-out. │
├─────────────┼─────────────────────────────────────────────────────────────┤
│ Sync push   │ NEVER at scale. Post API blocks on follower count.           │
│ in Post API │ Acceptable only: demo apps, < 100 followers guaranteed.      │
└─────────────┴─────────────────────────────────────────────────────────────┘
```

### 8.5 Cache Layer Decisions

```
WHAT TO CACHE WHERE:

  ┌─────────────────────────┬──────────────┬─────────────────────────────┐
  │ Data                    │ Cache        │ Why                         │
  ├─────────────────────────┼──────────────┼─────────────────────────────┤
  │ home_timeline ZSET      │ Redis        │ Core read path, ms latency  │
  │ tweet JSON body         │ Redis + local│ Hydrate bottleneck          │
  │ celebrity_recent ZSET   │ Redis + local│ Hot key — micro-cache req  │
  │ follow graph edges      │ Redis + app  │ Fan-out reads followers     │
  │ ranking features        │ Redis/Dynamo │ Precomputed affinities      │
  │ tweet media (images)    │ CloudFront   │ CDN Fundamentals — static   │
  │ feed API JSON response  │ DO NOT CACHE │ Per-user, personalized      │
  └─────────────────────────┴──────────────┴─────────────────────────────┘
```

---

## 9. Capacity Estimates (Expanded)

### 9.1 Assumptions Table

```
┌─────────────────────────────────────┬──────────────────────────────────────┐
│ Parameter                           │ Value                                │
├─────────────────────────────────────┼──────────────────────────────────────┤
│ DAU                                 │ 500M                                 │
│ MAU                                 │ 800M                                 │
│ Daily tweets                        │ 500M                                 │
│ Average tweets/sec                  │ 5,787                                │
│ Peak tweets/sec (3× avg)            │ 17,000–25,000                        │
│ Timeline reads/day                  │ 500B (1000 reads/posting-user/day)   │
│ Average reads/sec                   │ 5.78M                                │
│ Peak reads/sec                      │ 15M (events, mornings)               │
│ Avg followers (for fan-out)         │ 300                                  │
│ Avg followees (for pull merge)      │ 800                                  │
│ Avg celebrities followed            │ 15                                   │
│ Celebrity threshold                 │ 50,000 followers                     │
│ % tweets from celebrities           │ 0.1% of tweets, 30% of impressions   │
│ Timeline ZSET depth                 │ 800 tweet IDs                        │
│ Tweet JSON size                     │ 500 bytes avg                        │
│ Feed page size                      │ 50 tweets                            │
│ Feed API response size              │ 50 KB (with metadata, uncompressed)  │
│ Active users with cached timeline   │ 20% of DAU = 100M                    │
└─────────────────────────────────────┴──────────────────────────────────────┘
```

### 9.2 Write Path Math

```
TWEET WRITES:

  500M tweets/day ÷ 86,400 sec = 5,787 tweets/sec average
  Peak: 25,000 tweets/sec

DURABLE STORAGE (Keyspaces):

  500M tweets × 500 bytes = 250 GB/day
  × 365 = 91 TB/year raw
  RF=3 replication = 273 TB/year
  + indexes (user_timeline table) ≈ 350 TB/year total

FAN-OUT WRITES (Redis ZADD):

  Non-celebrity tweets: 99.9% × 5,787 = 5,781 tweets/sec
  Avg followers: 300 (excluding celebrity followers from avg)
  Effective fan-out: 5,781 × 300 = 1.73M ZADD/sec average

  Each ZADD paired with ZREMRANGEBYRANK = 3.46M Redis write cmds/sec

  Peak: 25,000 × 300 = 7.5M ZADD/sec (before active-user filter)
  With active-user filter (40% skip): 4.5M ZADD/sec peak

CELEBRITY WRITES:

  0.1% × 5,787 = 6 tweets/sec from celebrities
  Each: 3 Redis cmds (user_timeline + celebrity_recent + trim)
  = 18 Redis cmds/sec (negligible vs normal fan-out)

KAFKA THROUGHPUT:

  5,787 events/sec × 250 bytes/event = 1.4 MB/sec ingress
  Well within MSK m5.2xlarge capacity (100+ MB/sec per broker)
  512 partitions → ~11 events/sec/partition average (very light)
  Peak 25K/sec → ~49 events/sec/partition (still light)
  Bottleneck is CONSUMER processing (Redis pipeline), not Kafka ingress
```

### 9.3 Read Path Math

```
TIMELINE READS:

  500B reads/day = 5.78M reads/sec average
  Peak: 15M reads/sec

REDIS READS PER FEED LOAD:

  ZREVRANGE home_timeline: 1 cmd
  SMEMBERS followees: 1 cmd (cached)
  ZREVRANGE celebrity_recent × 15 celebs: 15 cmds
  MGET tweet:{id} × 50: 50 cmds (pipelined = 1 round trip)
  Total: ~18 Redis round trips pipelined to ~3-4 round trips
  Target: < 5ms Redis time per feed load

HYDRATE MISS RATE:

  Target cache hit: 92% for tweet bodies
  15M peak reads × 50 tweets × 8% miss = 60M Keyspaces reads/sec peak
  → MUST keep hit rate high or Keyspaces disintegrates
  → Local cache (Caffeine) + Redis double layer → 97%+ effective hit rate
  → 15M × 50 × 3% = 22.5M Keyspaces reads/sec (still hard — need bigger cache)

EGRESS BANDWIDTH:

  5.78M reads/sec × 50 KB = 289 GB/sec uncompressed
  With gzip (5×): 58 GB/sec
  With HTTP/2 + smaller payloads (30 KB effective): 173 GB/sec raw
  → DOMINANT COST at this scale
  → Cannot CDN-cache feed JSON (personalized)
  → Optimize payload: field filtering, lazy-load media URLs only
```

### 9.4 Redis Memory Sizing

```
HOME TIMELINE ZSET:

  100M active cached users × 800 IDs × ~20 bytes overhead = 1.6 TB
  + Redis internal overhead (30%) = 2.1 TB

TWEET BODY CACHE:

  10M hottest tweets in cache × 500 bytes = 5 GB
  (Long tail — most tweets read once then cold)

CELEBRITY CACHE:

  10K celebrities × 100 tweets × 20 bytes = 20 MB (tiny)
  But EACH key gets massive read QPS — not memory issue, CPU issue

GRAPH CACHE:

  followers:{user_id} — top 100K accounts by follower count
  100K × 50KB avg follower list = 5 GB

TOTAL ESTIMATE: ~2.2 TB working set
PROVISION: 2.5 TB (15% headroom) on ElastiCache cluster mode
  20 shards × r6g.2xlarge (52 GB usable each after overhead)
  3 replicas for HA → 60 nodes total
```

### 9.5 Compute Sizing

```
TIMELINE SERVICE:

  Target: 5K RPS per pod (p99 < 200ms, 2 vCPU, 4GB)
  Average: 5.78M / 5K = 1,156 pods
  Peak: 15M / 5K = 3,000 pods
  Auto-scale on RPS + p99 latency

FAN-OUT WORKERS:

  512 partitions = 512 max consumers
  Each consumer: ~11 tweets/sec avg × 300 followers = 3,300 ZADD/sec
  Pipeline 1000 followers per batch: ~3 pipeline execs/sec/tweet
  CPU-bound on Redis network I/O
  512 × c5.2xlarge (8 vCPU) — one per partition at peak

POST API:

  25K WPS peak / 5K per pod = 5 pods (+ HA margin = 20 pods)

GRAPH SERVICE:

  Fan-out follower lookups: 5,787 tweets × 1 paginated scan avg
  Feed followee lookups: lower
  Estimate: 100–200 pods

MONTHLY COMPUTE (illustrative AWS):
  1500 Timeline tasks (avg) × $0.04/hr × 730 hr = $44K
  512 Fan-out EC2 × $0.15/hr × 730 = $56K
  Total compute ~$120–150K/month (excluding data transfer)
```

### 9.6 Cost Sensitivity Analysis

```
TOP 3 COST DRIVERS:

  1. Data transfer out (feed API egress): 50–60% of infra bill at scale
     Mitigation: smaller payloads, compression, regional serving

  2. ElastiCache (2.5 TB cluster): 15–20%
     Mitigation: trim depth, evict cold users, separate tweet body tier

  3. Keyspaces/DynamoDB storage + reads: 15–25%
     Mitigation: hydrate cache hit rate > 97%

  CHEAP relative to above:
     MSK ($1–3K/month), Post API compute, Graph Service

  CLOUDFRONT (media):
     Pays for itself — S3 egress avoided, user experience improved
     See CDN Fundamentals cost model
```

---

## Incident Scenario
### Scenario: Global Music Awards — Feed Meltdown

```
SETUP:
━━━━━━
You operate a Twitter-scale social platform. Tonight is the Global Music
Awards (GMA) — 400M expected concurrent viewers worldwide.

Architecture (as designed in this module):
  → Timeline Service on EKS (us-east-1, eu-west-1, ap-northeast-1)
  → ElastiCache Redis Cluster: 20 shards, 3 replicas, 2.1 TB used (81% memory)
  → MSK: tweet.created, 512 partitions, fan-out-v2 consumer group (480 active)
  → Keyspaces: tweets + user_timelines, RF=3
  → Aurora PostgreSQL: follow graph
  → CloudFront + S3: media
  → Celebrity threshold: 50,000 followers
  → Ranking Service + Feature Store Redis (separate cluster, 64 GB)

KEY ACCOUNTS:
  @GMA_Official — 95M followers (celebrity, pull path)
  @StarArtist — 42M followers (celebrity)
  @HostLive — 8M followers (below threshold — PUSH fan-out)
  Normal users: 300 avg followers

TRAFFIC BASELINE (pre-event):
  → 4,200 tweets/sec
  → 4.1M feed reads/sec
  → fan-out consumer lag p99: 1.8 sec
  → feed.home p99: 145ms
  → Redis memory: 81%, max shard CPU: 52%

THE INCIDENT (multi-system cascade):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

19:45 — GMA starts. Viewership spikes. Tweet rate: 4.2K → 11K/sec in 90 sec.
        Mostly reactions to performances from normal users (push fan-out).

19:46 — Fan-out consumer lag rises: 1.8s → 8s → 22s.
        480 consumers processing 11K tweets × 300 followers = 3.3M ZADD/sec.
        32 consumer pods CPU-saturated. Kafka partition lag uneven.

19:47 — @HostLive (8M followers, PUSH path) posts "WELCOME TO GMA!!!"
        Single tweet triggers 8M fan-out writes.
        Fan-out worker assigned to HostLive's partition falls behind:
        that partition lag → 4 minutes within 60 seconds.
        8M followers don't see host's tweet (ironic for live event).

19:48 — @GMA_Official posts winner announcement. 95M followers.
        Hybrid: celebrity path — ZADD celebrity_recent:GMA_Official.
        HOT KEY: celebrity_recent:GMA_Official on shard 7.
        Shard 7 CPU: 52% → 89% → 99% in 30 seconds.
        ALL users with home_timeline on shard 7 see p99 spike:
        feed.home p99 (shard-7 users): 145ms → 2,300ms.
        5% of DAU affected by shard collision (not just GMA followers).

19:49 — Timeline Service pods add 2-second local cache for celebrity_recent:GMA.
        Shard 7 CPU drops to 71%. Partial relief.
        feed.home p99 global: 380ms. Error rate: 0.3%.

19:50 — Ranking Service feature store Redis (64 GB cluster) hit by offline
        job accidentally left running (Spark feature refresh during event).
        Feature store CPU: 95%. Ranking p99: 25ms → 800ms.
        Timeline Service thread pool exhaustion (ranking is sync call).
        feed.home 504 rate: 0.3% → 4.7%.
        On-call hasn't disabled rank_feed flag yet.

19:51 — Mobile clients retry failed feed loads (exponential backoff NOT
        implemented in older app version — 3.2.x, 28% of users).
        Effective read load: 4.1M → 6.8M reads/sec.
        Timeline Service auto-scale lag: 1,100 → 1,400 pods (300 pending).
        Hydrate path miss rate rises (Redis CPU contention): 8% → 19%.
        Keyspaces read capacity autoscaling triggers — 30 sec delay.

19:52 — Keyspaces throttling on tweets_by_id table: 2.1% hydrate failures.
        Users see partial feeds (25 tweets instead of 50).
        Support Twitter trending: #GMAFeedDown

19:53 — Engineer runs "SCALE UP REDIS" — adds 4 shards via online resharding.
        Resharding triggers slot migration — temporary latency spike.
        Redis p99 during migration: 5ms → 45ms for 3 minutes.
        Fan-out workers see pipeline timeouts — produce to fan-out.dlq.

19:54 — DLQ depth: 0 → 840,000 events in 90 seconds.
        Effective fan-out lag for non-celebrity tweets: 6+ minutes.
        Users report: "my tweets aren't showing up for friends."

19:55 — @StarArtist (42M followers) live-tweets wardrobe malfunction.
        Celebrity path OK for storage, but 42M users merge celebrity_recent
        in feed load — second hot key on shard 12.
        Combined with GMA key micro-cache expiring (TTL 2s, 1,400 pods
        with uncoordinated cache) — celebrity merge p99: 450ms.

19:57 — Aurora read replica (graph follower lookups) lag hits 12 seconds.
        Fan-out workers read stale follower lists — new followers of @HostLive
        (followed during broadcast) NOT in cached list — miss host tweets.
        Different symptom, same incident.

20:00 — Incident commander declares SEV-1.
        Status page updated. Executive visibility.

YOUR TASK AS ON-CALL SRE:
  Diagnose root causes, prioritize mitigations, stabilize the system,
  and prevent recurrence. You have full runbook access but NO hand-holding.
```

---

## 11. Expert Analysis (Full Worked Response)

### 11.1 T+0 to T+5: Triage and Stabilization (19:45–19:50)

```
PRIORITY ORDER (what kills users fastest):

  P0 — Stop 504 errors (Ranking blocking Timeline)
  P1 — Hot key shard 7 (2.3s p99 for 5% of users)
  P2 — Fan-out lag (tweets delayed minutes — bad but not 504)
  P3 — Aurora replica lag (subset of followers)
  P4 — Keyspaces throttling (partial feeds)
  P5 — DLQ replay (after stabilization)

ACTION 1 (IMMEDIATE — 30 seconds):
  Disable ranked feed globally.
    feature_flags.set("rank_feed", false)  # all regions
  Expected: Timeline thread pool frees, 504 rate 4.7% → < 0.1%
  Serves chronological feed — acceptable for live event
  Rationale: ranking is optional degradation Level 1 — USE IT

ACTION 2 (IMMEDIATE — 60 seconds):
  Extend celebrity micro-cache TTL 2s → 10s on Timeline Service.
    Deploy config change (no code deploy — ConfigMap hot reload)
  Expected: shard 7 CPU 99% → 55%, celebrity_merge p99 drop
  Tradeoff: 10s staleness on GMA tweets — acceptable for announcements

ACTION 3 (2 minutes):
  Temporarily raise celebrity threshold 50K → 500K.
    @HostLive (8M) now treated as celebrity — skip push fan-out
  Prevents future mega-push during event
  NOTE: does NOT fix HostLive tweet already in lag queue

ACTION 4 (3 minutes):
  Scale fan-out consumers to 512 (match partition count).
    Currently 480 — 32 partitions had no consumer during peak
  Expected: lag growth rate slows

DO NOT YET:
  ✗ Add Redis shards (19:53 mistake — resharding during incident adds latency)
  ✗ Purge Kafka and replay (DLQ replay during active storm makes it worse)
  ✗ Scale Timeline further before fixing 504 root cause (more load on broken ranking)
```

### 11.2 T+5 to T+15: Root Cause Isolation (19:50–20:00)

```
ROOT CAUSE MAP:

  ┌────────────────────────┬─────────────────────┬─────────────────────────┐
  │ Symptom                │ Root cause          │ Evidence                │
  ├────────────────────────┼─────────────────────┼─────────────────────────┤
  │ 504 on feed load       │ Ranking sync block  │ rank p99 800ms, redis   │
  │                        │ + feature store CPU │ p99 normal during 504   │
  ├────────────────────────┼─────────────────────┼─────────────────────────┤
  │ 2.3s p99 shard-7 users │ Hot key celebrity_  │ shard 7 CPU 99%, key    │
  │                        │ recent:GMA_Official │ = celebrity_recent:GMA  │
  ├────────────────────────┼─────────────────────┼─────────────────────────┤
  │ 6 min fan-out lag      │ Write amplification │ 11K tweets × 300 +     │
  │                        │ + under-provisioned │ HostLive 8M push + 480  │
  │                        │ consumers           │ not 512 consumers       │
  ├────────────────────────┼─────────────────────┼─────────────────────────┤
  │ DLQ 840K events        │ Redis resharding    │ pipeline timeouts 19:53 │
  │                        │ during incident     │ correlate with resharding│
  ├────────────────────────┼─────────────────────┼─────────────────────────┤
  │ Partial feeds (25/50)  │ Keyspaces throttle  │ hydrate miss 19% + RCU  │
  │                        │ + hydrate miss rise │ autoscale delay         │
  ├────────────────────────┼─────────────────────┼─────────────────────────┤
  │ New followers miss     │ Aurora replica lag  │ repl lag 12s on graph   │
  │ HostLive tweets        │ 12 sec on graph     │ read replica            │
  └────────────────────────┴─────────────────────┴─────────────────────────┘

AMPLIFIERS (made it worse):

  1. Client retry storm (app 3.2.x) — 65% read load increase
  2. Spark job on feature store during event — preventable scheduling error
  3. Redis resharding mid-incident — operational mistake
  4. @HostLive below celebrity threshold — 8M push on live TV moment

VICTims vs TRIGGERS:

  TRIGGER: GMA event traffic spike (expected, planned for incompletely)
  AMPLIFIER: Spark job, client retries, resharding, HostLive push
  VICTIM: Users on shard 7, users on app 3.2.x, new followers of HostLive
```

### 11.3 T+15 to T+30: Recovery Actions (20:00–20:15)

```
STEP 1 — Fan-out lag recovery:
  ✓ rank_feed=false (done)
  ✓ 512 consumers active (done)
  Rate limit global posts: 100 tweets/sec/user max (API Gateway rule)
  Pause non-essential Kafka consumers (analytics, search indexer)
    → Free broker bandwidth for fan-out priority

STEP 2 — Hot key permanent fix (during event):
  Split celebrity_recent:GMA_Official into 8 salted keys:
    celebrity_recent:GMA_Official:0 through :7
  Fan-out writes to ALL 8 keys (same data, replicated)
  Timeline reads random shard, merges — QPS / 8 per key
  Deploy via fan-out worker config (15 min rollout)

STEP 3 — HostLive tweet catch-up:
  Manually produce synthetic tweet.created replay for HostLive welcome
    tweet to fan-out.dlq-replay topic with PRIORITY consumer
  OR: accept celebrity conversion — future tweets pull-only
  Communicate: "Some timelines may be 5–10 min behind during peak"

STEP 4 — Keyspaces throttling:
  Double read capacity units temporarily (AWS console — 2 min)
  Increase tweet body local cache 10K → 50K entries (ConfigMap)
  Target hydrate miss < 5%

STEP 5 — Aurora graph lag:
  Route fan-out follower lookups to PRIMARY (not replica) during event
    Feature flag: graph_read_primary=true
  Tradeoff: primary load increases — acceptable for 2 hours vs stale fan-out

STEP 6 — DLQ replay (ONLY after lag stable 10 min):
  Dedicated replay consumer at 5K events/sec (rate limited)
  Idempotent ZADD — safe replay
  Monitor Redis write rate during replay — don't re-trigger storm

STEP 7 — Client retry storm:
  CDN/API Gateway: return Retry-After: 5 on 503/504
  Push notification to app 3.2.x users: "Update app for better experience"
  Long-term: client backoff — track separately
```

### 11.4 T+30 to T+60: Verification and Communication

```
SUCCESS CRITERIA (declare incident resolved when ALL true for 15 min):

  □ feed.home p99 < 250ms all regions
  □ feed.home 5xx rate < 0.05%
  □ fan_out.consumer_lag p99 < 15 sec
  □ redis.max_shard_cpu < 75%
  □ hydrate.cassandra_fallback_rate < 5%
  □ DLQ replay complete or rate-limited backlog < 1 hour

STATUS PAGE TIMELINE (external comms):

  20:05 — "Some users experiencing delayed timelines during GMA."
  20:15 — "Feed loading issues identified. Fix deployed. Monitoring."
  20:35 — "Timelines recovering. Delays may persist up to 10 min."
  21:00 — "All systems nominal. Post-incident review scheduled."

INTERNAL POST-MORTEM STRUCTURE:

  1. Timeline of events (minute-by-minute — section 10 above)
  2. Root causes (ranking dependency, hot key, threshold config)
  3. What went well (rank_feed flag existed, micro-cache partial save)
  4. What went poorly (Spark during event, resharding mid-incident)
  5. Action items with owners and dates
```

### 11.5 Long-Term Fixes (Prevent Recurrence)

```
┌────┬──────────────────────────────────────┬──────────┬─────────────────┐
│ #  │ Action                               │ Priority │ Owner           │
├────┼──────────────────────────────────────┼──────────┼─────────────────┤
│ 1  │ Ranking NEVER sync without timeout   │ P0       │ Timeline team   │
│    │ (50ms max, bulkhead thread pool)     │          │                 │
├────┼──────────────────────────────────────┼──────────┼─────────────────┤
│ 2  │ Auto-disable rank_feed on rank p99   │ P0       │ SRE             │
│    │ > 200ms for 60 sec                   │          │                 │
├────┼──────────────────────────────────────┼──────────┼─────────────────┤
│ 3  │ Celebrity key salting by default     │ P0       │ Fan-out team    │
│    │ for accounts > 10M followers         │          │                 │
├────┼──────────────────────────────────────┼──────────┼─────────────────┤
│ 4  │ Event playbook: pre-raise threshold  │ P1       │ SRE             │
│    │ 24hr before known events             │          │                 │
├────┼──────────────────────────────────────┼──────────┼─────────────────┤
│ 5  │ Fan-out consumers ALWAYS = partition │ P1       │ Infra           │
│    │ count (512), auto-scaled on lag      │          │                 │
├────┼──────────────────────────────────────┼──────────┼─────────────────┤
│ 6  │ Ban Spark jobs on feature store      │ P1       │ ML platform     │
│    │ during SEV-prevention windows        │          │                 │
├────┼──────────────────────────────────────┼──────────┼─────────────────┤
│ 7  │ Redis resharding: change window only │ P1       │ SRE             │
│    │ never during SEV-1 or live events    │          │                 │
├────┼──────────────────────────────────────┼──────────┼─────────────────┤
│ 8  │ Client retry with exponential backoff│ P2       │ Mobile team     │
│    │ mandatory app 3.3+                   │          │                 │
├────┼──────────────────────────────────────┼──────────┼─────────────────┤
│ 9  │ Dedicated Redis cluster for celebrity│ P2       │ Infra           │
│    │ keys (isolation from home_timeline)  │          │                 │
├────┼──────────────────────────────────────┼──────────┼─────────────────┤
│ 10 │ Graph fan-out reads from primary     │ P2       │ Graph team      │
│    │ during events (flag exists now)      │          │                 │
└────┴──────────────────────────────────────┴──────────┴─────────────────┘
```

### 11.6 Interview-Style Architecture Summary

```
IF ASKED "DESIGN TWITTER FEED" IN 45 MINUTES:

  Minute 0–5:   Requirements, scale numbers (500M DAU, 6K tweets/sec)
  Minute 5–10:  High-level diagram (Post API, Kafka, Fan-out, Redis, Timeline)
  Minute 10–20: Fan-out on write vs read — explain hybrid + celebrity threshold
  Minute 20–25: Redis ZSET schema, pagination, trim depth
  Minute 25–30: Kafka async fan-out, consumer lag as key metric
  Minute 30–35: Cache layers (Redis timelines, local hydrate, CDN media only)
  Minute 35–40: Failure modes — hot key, lag storm, ranking dependency
  Minute 40–45: Capacity estimate + one AWS service mapping

DIFFERENTIATORS (principal-level):

  → Hybrid fan-out with explicit threshold math
  → Hot key on celebrity cache (not just "use cache")
  → Ranking as optional read-path layer, not fan-out dependency
  → Delete via hydrate-time filter + async purge
  → Event playbook for known traffic spikes
  → "Never resharding Redis during an incident" (war story)
```

---

## Key Takeaways
```
1. HYBRID FAN-OUT IS THE PRODUCTION ANSWER — Push for normal users
   (fast reads), pull for celebrities (bounded write amplification).
   Pure push or pure pull both fail at Twitter scale.

2. REDIS SORTED SETS ARE THE TIMELINE HOT PATH — ZADD on fan-out,
   ZREVRANGE on read, ZREMRANGEBYRANK to trim. Score = timestamp
   for chronological; ranking happens AFTER candidate fetch.

3. KAFKA DECOUPLES POST FROM FAN-OUT — Post API returns in < 100ms;
   fan-out lag is the user-visible delivery metric. Monitor per-partition
   lag, scale consumers to partition count.

4. THE CELEBRITY PROBLEM IS A HOT KEY PROBLEM — celebrity_recent:{id}
   concentrates read QPS on one Redis shard. Salting, micro-cache,
   and dedicated clusters are required — not optional optimizations.

5. CACHE LAYERS ARE STRICTLY SEPARATED — CDN for media (CloudFront),
   Redis for timelines and tweet bodies, local cache for viral hydrates.
   NEVER CDN-cache personalized feed JSON (see CDN Fundamentals).

6. CAPACITY IS READ-DOMINATED — 1000:1 read:write ratio drives Redis
   and Timeline Service sizing. Fan-out write amplification (1.7M ZADD/sec)
   drives Kafka consumer and Redis write capacity. Egress bandwidth dominates
   cost at scale.

7. DEGRADATION MUST BE AUTOMATED — rank_feed=false, skip celebrity merge,
   reduce page size — each level pre-built as feature flags with SLO triggers.
   Ranking, celebrity merge, and ranking features are NEVER hard dependencies.

8. FAILURE MODES CASCADE — Hot key → shard CPU → unrelated users hurt.
   Ranking timeout → thread pool → 504 despite healthy Redis. Client retries
   → 65% read amplification. Diagnose by comparing phase latencies in traces.

9. INCIDENT RESPONSE PRIORITY — Fix user-visible 504s first (disable ranking),
   then hot keys (micro-cache/salt), then fan-out lag (scale consumers),
   then data plane throttling (Keyspaces RCU). Never resharding mid-incident.

10. AWS MAPPING — ALB + EKS Timeline Service, ElastiCache Redis Cluster,
    MSK for fan-out, Keyspaces for durable tweets, Aurora for graph,
    CloudFront for media. Multi-region read replicas with single write primary.
```

---

## Targeted Reading
```
PRIMARY SOURCES (specific — not "read DDIA"):

  Twitter engineering blog:
    → "Timelines at Scale" (2010) — original fan-out discussion
    → "The Infrastructure Behind Twitter's Scale" — Redis, Manhattan
    Search: site:blog.twitter.com engineer timeline fanout

  DDIA (Designing Data-Intensive Applications):
    → Chapter 1: Reliability, Scalability (fan-out write amplification)
    → Chapter 5: Replication (async fan-out as eventual consistency)
    → Chapter 11: Stream Processing (Kafka consumer groups, lag)
    Pages: 1–30 (scale definitions), 151–162 (leader/follower lag analogy),
           466–481 (stream processing concepts)

  Redis documentation:
    → Sorted Sets: redis.io/docs/data-types/sorted-sets
    → ZREVRANGEBYSCORE pagination pattern
    → Cluster specification: hash slots, CROSSSLOT errors
    → MEMORY USAGE, LATENCY DOCTOR commands

  Kafka (Confluent docs):
    → Consumer groups and partition assignment
    → MaxOffsetLag monitoring
    → Idempotent producers (exactly-once semantics discussion)
    → MSK best practices: AWS docs on msk best practices

  AWS specifics:
    → ElastiCache Redis Cluster Mode: scaling, online resharding risks
    → Amazon Keyspaces capacity modes (on-demand vs provisioned)
    → CloudFront: cache authenticated content NEVER — link to CDN Fundamentals

  Papers:
    → "Scaling Memcache at Facebook" (NSDI 2013) — cache hierarchy patterns
    → "Kafka: a Distributed Messaging System for Log Processing" (LinkedIn)

  Related modules in this curriculum:
    → CDN Fundamentals — media caching, why feed JSON is not CDN-cacheable
    → Message Queues and Kafka — consumer lag, partitioning, DLQ
    → Database Scaling Patterns — when Redis vs Cassandra vs Aurora
    → Sharding — hot key patterns (celebrity problem parallels shard hot spots)
    → Monitoring and Observability — golden signals, trace phase analysis

  Mock interview prep (Week 15):
    → Mock Interview 01: Social Feed — practice 45-min delivery
    → Principal SRE System Design Checklist — feed-specific gates
```

---

## Appendix A: API Contract Reference

```
POST /v2/tweets
  Request:  { "text": string, "media_ids": [string], "reply_to": string? }
  Response: 201 { "tweet_id", "created_at", "author" }
  Errors:   429 rate limit, 401 auth, 400 validation

GET /v2/timeline/home
  Query:    count (default 50, max 100), cursor (optional)
  Response: 200 { "tweets": [...], "next_cursor", "has_more" }
  Headers:  Cache-Control: private, no-store

DELETE /v2/tweets/{tweet_id}
  Response: 204
  Async:    tweet.deleted → purge workers

POST /v2/graph/follow/{user_id}
  Triggers: graph.follow.created → backfill worker

GET /v2/timeline/user/{user_id}
  Profile timeline — user_timeline ZSET, no hybrid merge needed
```

---

## Appendix B: Snowflake ID Layout

```
64-bit tweet ID:

  ┌────────────────────────────────────────────────────────────────┐
  │ 41 bits: timestamp ms since epoch  │ 5 bits DC │ 5 bits worker │ 13 bits seq │
  └────────────────────────────────────────────────────────────────┘

  Properties:
    → Sortable by time (roughly — use explicit created_at_ms as ZSET score)
    → 4096 IDs/ms per worker (13 bit sequence)
    → 32 datacenters × 32 workers = 1024 ID generators without coordination

  Clock skew handling:
    → If timestamp < last_timestamp: wait or use last_timestamp
    → Never generate duplicate (sequence overflow → wait next ms)
```

---

## Appendix C: Fan-Out Latency Budget

```
END-TO-END: post click → visible in follower's feed

  Post API persist:           30 ms
  Kafka produce (acks=all):   15 ms
  Kafka consume latency:       5 ms (p99 under normal load)
  Fan-out 300 followers:      80 ms (pipelined ZADD)
  Follower next feed poll:     0–30 sec (human) or immediate if app open
  Feed read ZREVRANGE:           2 ms
  ─────────────────────────────────
  System latency (p99):        ~130 ms (excluding client poll interval)

  Under lag (incident):
  Kafka lag 5 min → user-visible delay 5 min regardless of read path speed

  SLI: fan_out_propagation_delay_seconds
    = time(tweet_id first visible in sample follower timeline)
      - time(Post API 201 returned)
  Target p99: < 5 seconds
```

---

## Appendix D: Comparison with Other Feed Designs

```
┌─────────────────┬──────────────────┬──────────────────┬──────────────────┐
│ Aspect          │ Twitter Home     │ Instagram Feed   │ Reddit Home      │
├─────────────────┼──────────────────┼──────────────────┼──────────────────┤
│ Fan-out model   │ Hybrid push/pull │ Push + ranking   │ Pull (subreddits)│
│ Graph shape     │ Asymmetric follow│ Symmetric follow │ Subscribe        │
│ Ranking         │ Heavy ML         │ Heavy ML         │ Hot score + time │
│ Celebrity       │ Pull at read     │ Similar hybrid   │ N/A (communities)│
│ Real-time need  │ High             │ Medium           │ Medium           │
│ Post frequency  │ High             │ Medium           │ Medium           │
└─────────────────┴──────────────────┴──────────────────┴──────────────────┘

WhatsApp / Chat (Week 9 sibling module):
  → Inbox model, not fan-out timeline
  → Per-conversation ordering, not global merge
  → Different CAP tradeoffs (delivery guarantees > feed freshness)
```

---

## Appendix E: Glossary

```
FAN-OUT (WRITE):     Push tweet to all follower timelines at post time
FAN-OUT (READ):      Pull tweets from followees at feed load time
HYBRID FAN-OUT:      Push for normal users, pull for celebrities
CELEBRITY THRESHOLD: Follower count above which push is skipped
HOME TIMELINE:       Materialized feed of tweets from followed accounts
USER TIMELINE:       All tweets authored by one user (profile page)
HYDRATE:             Fetch full tweet JSON from ID list
HOT KEY:             Single Redis key receiving disproportionate QPS
CONSUMER LAG:        Kafka messages produced but not yet consumed
ZSET:                Redis sorted set — member + score, range queries
SALTING:             Split one logical key into multiple Redis keys
BACKFILL:            Populate timeline when user follows someone new
TOMBSTONE:           Soft delete marker checked at read/hydrate time
DEGRADATION LADDER:  Ordered fallback modes when components fail
```

---

## Appendix F: Interview Rapid-Fire Q&A

```
Q: Why not use a graph database for the follow graph AND timeline?
A: Graph DBs excel at traversals (followers of X). Timelines need sorted
   time-ordered retrieval at massive QPS — Redis ZSET beats graph DB for
   that access pattern. Use Aurora/graph for edges, Redis for materialized
   timelines. Separation of concerns.

Q: How do you handle a retweet in fan-out?
A: Retweet creates a NEW tweet_id pointing to original. Fan-out the retweet
   ID (not the original again). Original already in timeline from author's
   own post unless author is muted. Retweet metadata hydrated at read time.

Q: What happens if Kafka loses a tweet.created message?
A: With acks=all and RF=3, loss is extremely rare. Detection: author sees
   tweet on profile (user_timeline written sync) but followers don't.
   Reconciliation: compare user_timeline vs fan-out completion markers.
   Prevention: idempotent replay from durable store on consumer crash.

Q: Can you use DynamoDB Streams instead of Kafka for fan-out?
A: Possible for smaller scale. DynamoDB Streams has lower throughput ceiling,
   no long retention for replay, coupling to DB write path. Kafka preferred
   at 6K+ tweets/sec because multiple consumers (fan-out, search, analytics)
   need the same event stream independently.

Q: How do you A/B test ranked vs chronological feeds?
A: Feature flag per user cohort. Same Redis candidates, different final sort.
   Metrics: session time, likes/session, p99 latency per cohort. Never A/B
   the fan-out layer — only the ranking layer.

Q: What's the difference between home timeline and "For You" algorithmic feed?
A: Home = accounts you follow (this module). For You = recommendation engine
   pulling from global corpus based on interests (separate candidate source).
   Production X merges both candidate pools before ranking. Harder problem.

Q: How do you shard the follow graph?
A: Shard by follower_id for "who does Alice follow?" (feed merge list).
   Separate index or table sharded by followee_id for "who follows Alice?"
   (fan-out). Same edge stored once, two access paths — classic DDIA ch5 pattern.

Q: Why ZSET score as timestamp instead of tweet_id?
A: tweet_id from Snowflake is roughly time-ordered but not exact score.
   Explicit created_at_ms avoids clock skew issues in ID generator.
   Ranking scores change — never use mutable score in fan-out ZSET.

Q: How long do you retain home_timeline in Redis?
A: 800 tweets depth, not time-based. At 800 × avg followee rate, covers
   ~2–7 days for active users. Older tweets: pull from Keyspaces on deep
   scroll (rare — most users never scroll past page 3).

Q: What SLO do you set for feed freshness?
A: fan_out_propagation_delay p99 < 5 sec (normal users).
   Celebrity tweets: < 500ms (pull path — no fan-out lag).
   Separate SLIs — mixing them hides fan-out problems.
```

---

## Appendix G: Redis Cluster Operations Runbook

```
ONLINE RESHARDING (planned maintenance ONLY — never during incidents):

  1. Add shards: aws elasticache increase-replica-count / modify
  2. Reshard: redis-cli --cluster reshard $HOST:6379
  3. Monitor: CLUSTER NODES, slot migration progress
  4. Duration: ~minutes per GB moved — plan change window
  5. During migration: expect 2-5× latency spike on affected slots

FAILOVER (automatic):

  ElastiCache Multi-AZ: primary failure → replica promoted ~30 sec
  Application: use cluster-aware client (redis-py cluster, jedis cluster)
  Retry logic: exponential backoff on MOVED/ASK redirects

MEMORY EMERGENCY:

  1. Identify largest keys: redis-cli --bigkeys (sample per shard)
  2. Trim depth: ZREMRANGEBYRANK home_timeline:* 0 -401 (800→400)
  3. Evict cold users: DEL home_timeline where last_access > 7d
  4. Add shards (planned — not emergency if incident active)

HOT KEY MITIGATION CHECKLIST:

  □ Application micro-cache deployed (Caffeine, TTL 2-10s)
  □ Key salting for followers > 10M
  □ Read from replica nodes (ElastiCache reader endpoint)
  □ Dedicated cluster for celebrity_recent:* pattern
  □ Pre-event playbook executed 24hr before known spikes
```

---

## Appendix H: Kafka Fan-Out Consumer Configuration

```
PRODUCTION CONSUMER CONFIG (MSK):

  group.id=fan-out-v2
  enable.auto.commit=false          # commit after successful Redis pipeline
  max.poll.records=50               # tweets per poll batch
  fetch.min.bytes=65536             # batch fetch for throughput
  session.timeout.ms=45000
  max.poll.interval.ms=300000       # 5 min — large celebrity backfill excepted

  # Parallelism: one consumer instance per partition maximum
  # 512 partitions → 512 consumer tasks in ECS service

PRODUCER CONFIG (Post API):

  acks=all                          # durability before 201 response
  retries=3
  enable.idempotence=true           # no duplicate tweet.created on retry
  compression.type=lz4

MONITORING:

  CloudWatch: MaxOffsetLag, BytesInPerSec, UnderReplicatedPartitions
  Alert: any partition lag > 10000 for 2 min → page
  Dashboard: per-partition lag heatmap (not aggregate — hides hot partitions)

REPLAY PROCEDURE (fan-out.dlq):

  1. Confirm Redis write capacity headroom (< 70% max shard CPU)
  2. Confirm consumer lag on main topic < 30 sec
  3. Start replay consumer at 5000 events/sec (rate limited)
  4. Monitor ZADD rate and Redis CPU during replay
  5. Idempotent — safe to replay same event multiple times
  6. Stop replay if Redis CPU > 85% — resume after scale-up
```

---

## Appendix I: Timeline Merge Algorithm (Detailed)

```
MERGE TWO SORTED LISTS (chronological candidates + celebrity pulls):

  Input:
    push_list:  [(tweet_id, score), ...]  from home_timeline ZREVRANGE
    pull_lists: [[(tweet_id, score), ...], ...]  from celebrity ZSETs

  Algorithm:
    merged = []
    pointers = [0] * (1 + len(pull_lists))
    lists = [push_list] + pull_lists

    while len(merged) < limit:
      best_idx = argmax(lists[i][pointers[i]].score for i where pointer valid)
      if no valid pointer: break
      candidate = lists[best_idx][pointers[best_idx]]
      if candidate.tweet_id not in seen:  # dedupe retweets/quotes
        merged.append(candidate)
        seen.add(candidate.tweet_id)
      pointers[best_idx] += 1

  Complexity: O(limit × num_lists) — with 16 lists and limit 50 = 800 comparisons
  Target: < 1ms in application memory

DEDUPLICATION RULES:

  Same tweet_id from push and pull → include once (push wins — already ranked)
  Retweet of tweet already in list → include retweet wrapper (different ID)
  Deleted tweet_id in timeline → filter at hydrate (tombstone check)
  Blocked author → filter at hydrate (block set check)
  Muted author → filter at hydrate OR ranking penalty (product decision)
```

---

## Appendix J: Security and Abuse Considerations

```
RATE LIMITS (API Gateway + application):

  Post tweet:     300 per 3 hours per user (Twitter actual limit)
  Feed load:      1000 per minute per user (prevent scraping)
  Follow:         400 per day per user (prevent graph spam)

ABUSE VECTORS ON FAN-OUT:

  1. Spam account gains followers → expensive fan-out target
     Mitigation: new account post rate limits, captcha, follower quality score

  2. Follow-unfollow churn to trigger backfill storms
     Mitigation: rate limit follow, debounce backfill (1 backfill per pair per hour)

  3. Mega-thread bombing (1000 replies/sec)
     Mitigation: reply rate limits, separate fan-out topic with lower priority

  4. Graph manipulation (bot followers)
     Mitigation: fan-out to "active verified" followers only for suspicious accounts

PRIVACY:

  Protected accounts: fan-out ONLY to approved followers
    followers list filtered at fan-out worker — not at read time
  Block: fan-out worker excludes blocked relationships on both directions
  GDPR delete: user delete → async purge all home_timelines containing their tweets
    + delete user_timeline + celebrity_recent if applicable
```

---

> **Retention test:** Week 9 rapid-fire + compound scenario (social platform
> meltdown) will live in `Retention-Tests/Week-09.md` when written — this
> module is topic-only per curriculum standards.

---
