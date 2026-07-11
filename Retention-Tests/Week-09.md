# WEEK 9 RETENTION TEST

Covers **Weeks 1-9** with emphasis on WhatsApp, Twitter feed, and social-platform meltdown operations.

---

## Rules

```text
RULES OF ENGAGEMENT

1. Answer from memory. Do not open teaching modules, answer keys, or prior notes.
2. Rapid-fire answers should be 2-4 sentences each.
3. The compound Ops Sim should be answered like you are the incident lead.
4. If you do not remember, write "I do not remember" and move on.
5. Open the answer key only after completing your attempt.
```

---

## Part 1: Rapid-Fire Concept Recall (14 Questions)

Answer all 14. The mix is intentional: current week, mid-prior weeks, and older foundations.

**Q1 (Current - WhatsApp fan-out):** Why does a chat system usually use write fan-out for small groups but switch to read fan-out or hybrid behavior for very large groups?

**Q2 (Current - WhatsApp ordering):** A mobile client sends the same message twice after a timeout. Which identifiers and deduplication checks keep the recipient from seeing duplicates while preserving per-chat order?

**Q3 (Current - Twitter feed):** Explain the celebrity problem in a home timeline design. Why is "just push every tweet to every follower timeline" not viable for a 50M-follower account?

**Q4 (Current - feed storage):** Why are Redis sorted sets a good fit for cached home timelines, and what operational risk appears when one shared celebrity cache key becomes globally hot?

**Q5 (Mid - Kafka):** A fan-out worker group has high lag on one partition only. What does that suggest about the partition key, and what should you inspect before adding consumers?

**Q6 (Mid - outbox/CDC):** Message ingress writes to Cassandra successfully but fails before producing to Kafka. What pattern prevents accepted messages from disappearing from fan-out?

**Q7 (Mid - rate limits):** A celebrity live chat gets spammed by 20k clients. Name two rate limits you would apply and where they should sit in the request path.

**Q8 (Mid - feature flags):** You want to enable read-fanout mode for groups over 256 members. What rollout guardrails prevent a flag mistake from taking down Cassandra or Redis?

**Q9 (Old - TCP/WebSocket):** 800k WebSocket clients reconnect after a gateway deployment. What reconnect algorithm prevents a thundering herd?

**Q10 (Old - CDN):** Which parts of a social app are safe to cache at a CDN, and why should authenticated home timeline JSON not be cached there?

**Q11 (Old - caching):** Timeline service uses Redis plus local in-process cache for tweet bodies. What is the stale-read risk after a tweet delete, and how can read-time tombstone filtering help?

**Q12 (Old - CAP/replication):** Presence is stored in Redis with TTL and can be stale during a network partition. Why is that usually acceptable, while message history needs stronger durability?

**Q13 (Old - auth/tenancy):** A seller-analytics tenant triggers a feed fan-out storm in a shared Redis cluster. What tenancy isolation signal would have caught this before customer feeds slowed?

**Q14 (Old - cost):** What is the main cost trade-off between write fan-out and read fan-out for inactive users?

---

## Part 2: Compound Ops Sim - Northstar Social Meltdown

Use the shared company context in `/workspace/Ops-Sims/fictional-company/NORTHSTAR.md`.

```text
INCIDENT REPORT

Severity: P1
Company: Northstar Commerce
Systems involved:
  - feed-fanout: Redis timelines + Kafka fan-out workers
  - chat-gateway: WebSocket gateways for live auctions and seller chats
  - cass-msg: Cassandra message and inbox tables
  - redis-social: connection registry, home timelines, celebrity caches
  - api-edge: CloudFront + ALB for mobile/web APIs

Business event:
  A celebrity seller with 42M followers announces a live auction.
  Users can follow the seller feed, join a live chat, and receive auction
  notifications. Bid WebSocket delivery SLO is still <500ms p99.

Timeline:
  18:00 - Celebrity posts auction announcement.
  18:02 - Product enables `fanout.write_all_followers=true` for "auction boost".
  18:05 - feed-fanout lag starts climbing.
  18:08 - chat messages in the celebrity room arrive out of order.
  18:12 - Redis CPU reaches 96%; timeline reads p99 > 2s.
  18:17 - WebSocket gateways restart after memory pressure.
  18:20 - Users complain that bid notifications are missing or delayed.
```

### Telemetry Pack

```text
feed-fanout Kafka:
  topic=tweet.created partitions=384 RF=3
  lag_sum{group="feed-fanout"}: 8k -> 14.7M in 12 min
  lag_by_partition:
    p071: 8.9M
    p122: 1.1M
    all others: <40k
  producer acks=1
  key for announcement events: author_id

Redis social:
  redis_cpu{cluster="redis-social"}: 96%
  evicted_keys_total: +1.8M in 10 min
  top keys by ops/sec:
    celebrity_recent:seller_77: 410k ops/sec
    home_timeline:* pipeline writes: 1.9M ops/sec
    conn_registry:*: timeout rate 6%

Cassandra cass-msg:
  write_p99_ms: 42 -> 780
  pending_compactions: 3 -> 61
  tombstones/read on inbox_by_user: p95 11,800
  coordinator_timeouts: 0.2% -> 7.1%

WebSocket gateways:
  connected_clients: 820k
  reconnects/min: 9k -> 260k
  gateway RSS: 70% -> OOM on 11 pods
  app ping interval: 55s
  NLB idle timeout: 60s

Customer signals:
  bid_notification_delivery_p99: 420ms -> 5.8s
  home_timeline_p99: 95ms -> 2.4s
  duplicate_chat_message_rate: 0.03% -> 2.8%
```

### Config Pack

```text
feature flags:
  fanout.write_all_followers=true
  fanout.celebrity_threshold_followers=1000000
  feed.rank_at_read=true
  chat.receipt_aggregation=false

fan-out worker:
  consumer.instances=512
  max.poll.records=1000
  redis.pipeline.batch_size=100
  retry.backoff.ms=100
  dedup.ttl.seconds=3600

Cassandra:
  inbox_by_user compaction=STCS
  gc_grace_seconds=864000
  write consistency=LOCAL_QUORUM

WebSocket:
  reconnect: fixed 1s retry for legacy Android client
  server heartbeat: disabled for idle rooms
```

### Decision Points

Answer each decision point with your action, evidence, and rollback/verification signal.

**T+0:** You join the bridge. What are the first three facts you confirm, and what is the first mitigation you order?

**T+5:** Product wants to keep the celebrity boost flag enabled because the auction is high revenue. What do you do and why?

**T+15:** Lag is still growing on partition p071 after doubling fan-out workers. What do you inspect, and what do you stop doing?

**T+60:** The platform is stable but timelines are stale for some users. What recovery sequence rebuilds correctness without causing a second incident?

### Scenario Questions

1. Identify the primary root cause and at least four contributing factors. Tie each to telemetry.
2. Explain why scaling consumers alone is a bad fix in this incident.
3. Separate the feed problem from the WebSocket/chat problem. Which symptoms share a cause, and which are independent amplifiers?
4. Design the safe mitigation plan for the first 15 minutes.
5. **Bad-fix gallery:** For each proposal, explain the failure mode: (a) flush all Redis keys, (b) lower Cassandra consistency to ONE globally, (c) increase Kafka partitions immediately, (d) disable all WebSockets, (e) purge CloudFront.
6. **Capacity question:** Estimate the write amplification of pushing one seller announcement to 42M followers. If each Redis ZADD+trim pipeline operation averages 300 bytes on the wire plus 80 bytes stored per timeline entry, what are the network and memory implications?
7. **Org/runbook question:** What runbook, ownership, and pre-launch review changes prevent this class of social meltdown?

---

## Self-Score Error-Type Table

Do not fill this in until after you compare with the answer key.

| Error type | Count | Notes to review |
|------------|-------|-----------------|
| Fan-out strategy error | | |
| Kafka partition/lag error | | |
| Redis/cache hot-key error | | |
| Cassandra/tombstone/scaling error | | |
| WebSocket/reconnect error | | |
| Incident sequencing error | | |
| Capacity math error | | |
| Org/runbook gap | | |

---

> **Answer key (do not open until you attempt the test):**  
> [`../answers/Retention-Tests/Week-09 Answers.md`](../answers/Retention-Tests/Week-09%20Answers.md)
