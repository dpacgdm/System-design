# Answer Key - Week-09

> Open only after attempting `Retention-Tests/Week-09.md`.

---

## Part 1: Rapid-Fire Model Answers

**Q1:** Small chats can use write fan-out because N recipient inbox writes are cheap and reads stay fast. Large groups make N writes too expensive and can create hot Cassandra/Redis partitions, so they switch to read fan-out or hybrid mode where the message is stored once and merged at read time.

**Q2:** Use a client-generated message id plus a server message id, with dedup keyed by `(chat_id, client_msg_id)` at ingress and `(server_msg_id, recipient_id)` in fan-out. Per-chat order comes from a single ordered log/partition keyed by `chat_id` or a server sequence number assigned after acceptance.

**Q3:** The celebrity problem is write amplification from one author to tens of millions of follower timelines. A 50M-follower tweet becomes 50M Redis writes, trims, replication events, and cache churn for one human action, so the largest celebrity dictates total capacity.

**Q4:** Redis sorted sets support `ZADD`, time/rank score ordering, pagination with `ZREVRANGE`, and bounded trimming. A shared celebrity cache key amortizes writes but can become a hot key with hundreds of thousands of reads per second on one slot unless replicated, sharded, or locally cached.

**Q5:** One lagging partition suggests key skew: the hot author/chat maps to one Kafka partition. Inspect lag by partition, key distribution, worker logs, downstream Redis/Cassandra latency, and whether the consumer is blocked on a hot key before adding consumers.

**Q6:** Use a transactional outbox or CDC pattern. The accepted message and an outbox row are committed together, then Debezium or an outbox publisher reliably emits the Kafka fan-out event.

**Q7:** Apply per-user/per-device send limits at the gateway before expensive work, and per-room/per-chat aggregate limits before Kafka/Cassandra fan-out. For abuse, add author/message creation limits and recipient fan-out quotas.

**Q8:** Guardrails include canary by group tier, automatic rollback on fan-out lag/Cassandra p99/Redis CPU, per-group overrides, dry-run capacity estimates, and a kill switch owned by SRE. The flag should be bounded by member count and downstream headroom, not just product intent.

**Q9:** Exponential backoff with jitter. Fixed retries synchronize clients and create waves; jitter spreads reconnections across time.

**Q10:** Static assets, public media, avatars with versioned URLs, and public profile/media metadata can be CDN cached. Authenticated home timeline JSON is personalized by user, ranking, blocks, ads, and auth state, so CDN caching risks privacy leaks and stale personalized content.

**Q11:** A deleted tweet body may remain in Redis/local cache and still appear when timeline ids are hydrated. A tombstone or visibility check at read time filters deleted/blocked tweets even before async timeline cleanup finishes.

**Q12:** Presence is ephemeral and approximate; stale "online" state is annoying but recoverable. Message history is durable user data, so losing or reordering accepted messages violates the core product contract.

**Q13:** Per-tenant Redis ops/sec, memory, evictions, hot keys, and throttling counters would reveal a noisy tenant. A shared cluster needs tenant labels or shard isolation so one tenant's fan-out cannot silently consume feed capacity for all.

**Q14:** Write fan-out spends write/storage cost even for inactive users who may never open the app. Read fan-out saves those writes but shifts CPU/cache work to timeline reads and can make active-user reads slower.

---

## Part 2: Compound Scenario - Expert Analysis

### Executive Diagnosis

Primary root cause: product enabled `fanout.write_all_followers=true` for a 42M-follower seller, bypassing the celebrity/hybrid fan-out threshold. One announcement generated tens of millions of timeline writes, concentrated Kafka lag on the `author_id` partition, saturated Redis, and pushed Cassandra into compaction/read-amplification trouble.

The WebSocket outage is an amplifier and partial parallel failure: gateway OOMs and fixed 1s Android reconnects create a reconnect storm, while disabled heartbeat plus a 60s NLB idle timeout explains periodic disconnects for idle rooms. The feed hot path and chat gateway share Redis pressure through `conn_registry` timeouts, so they interact even though the first trigger is feed fan-out.

### Evidence Map

| Symptom | Interpretation |
|---------|----------------|
| `p071` lag 8.9M while others <40k | Hot Kafka key/partition, consistent with `author_id=seller_77` |
| `fanout.write_all_followers=true` | Celebrity bypass; direct trigger |
| Redis CPU 96%, 1.9M timeline writes/sec | Write fan-out saturating Redis |
| `celebrity_recent:seller_77` 410k ops/sec | Hot shared celebrity cache key on read path |
| Cassandra write p99 780ms, compactions 61 | Downstream database cannot absorb write/trim/tombstone pressure |
| WebSocket reconnects 260k/min | Reconnect storm after gateway OOMs and fixed retry |
| NLB idle 60s, ping 55s, heartbeat disabled | Fragile idle timeout margin; some rooms have no keepalive |
| Duplicate chat rate 2.8% | Retry/idempotency path under stress or fan-out dedup failures |

### T+0 Decision

Confirm:

1. The flag state and the affected author/follower count.
2. Kafka lag by partition/key and downstream Redis/Cassandra saturation.
3. Whether bid WebSocket delivery is impaired and whether reconnect rate is self-amplifying.

First mitigation: disable `fanout.write_all_followers` and force seller_77 into celebrity/read-fanout mode. Freeze nonessential social launches. Put a temporary per-author fan-out rate limit on seller_77 events while preserving bid traffic.

Verification: new announcement events no longer create large home-timeline write bursts; Redis ops/sec drops; lag derivative stops increasing; bid notification p99 starts recovering.

### T+5 Decision

Do not keep the flag enabled. Revenue from the auction is now threatened by platform integrity and bid notification SLO violations. Offer a product-safe alternative: pin the seller announcement in a read-time celebrity module, use a cached `celebrity_recent` path with controlled replication, or send batched notifications to active followers only. The kill switch stays off until downstream headroom is proven.

### T+15 Decision

Doubling consumers does not fix a single hot partition because only one consumer in a group can own `p071`. It may worsen Redis/Cassandra pressure for other partitions. Inspect hot keys, per-key fan-out counts, worker stack traces, Redis command latency, and Cassandra compaction. Stop blindly scaling consumers; throttle the hot author/key, pause low-priority fan-out, and isolate bid/chat traffic.

### T+60 Recovery

1. Keep celebrity write fan-out disabled.
2. Drain Kafka lag with bounded worker concurrency matched to Redis/Cassandra headroom.
3. Rebuild stale home timelines lazily for active users, prioritizing auction participants.
4. Use read-time merge against seller `user_timeline`/`celebrity_recent` for correctness while backfill catches up.
5. Run dedup reconciliation for duplicate chat messages.
6. Repair Cassandra compaction/tombstone debt during a controlled window, not peak.
7. Communicate known stale windows to support/product.

### Why Scaling Consumers Alone Is Bad

Kafka parallelism is capped by partitions and by hot-key distribution. A single hot partition cannot be processed by many consumers in the same group. Even where added consumers help, they convert Kafka lag into Redis/Cassandra write pressure; this incident already shows both are saturated. The correct response is reduce/reshape demand, then drain at a safe rate.

### Feed vs WebSocket/Chat

Feed root cause: celebrity write fan-out and hot Redis/Cassandra paths. WebSocket root causes: gateway OOM, fixed reconnect retry, missing heartbeat, tight NLB timeout. Shared amplifier: Redis `conn_registry` timeouts and overall resource contention delay fan-out and delivery. Independent amplifier: legacy Android fixed 1s retry causes synchronized reconnect storms even if feed is fixed.

### Bad-Fix Gallery

| Bad fix | Why it is dangerous |
|---------|---------------------|
| Flush all Redis keys | Destroys timelines, connection registry, hot caches; causes database/cache stampede |
| Lower Cassandra CL to ONE globally | Masks timeouts but risks stale/lost message visibility and inconsistent inboxes |
| Increase Kafka partitions immediately | Does not move existing lag safely; can break key ordering assumptions and requires producer routing changes |
| Disable all WebSockets | Breaks live bids and chat; creates massive reconnect/client failure behavior |
| Purge CloudFront | Feed JSON is not CDN-cached; purging static/media cache increases origin load without fixing fan-out |

### Capacity Answer

One announcement to 42M followers means roughly 42M timeline insert+trim operations.

Network: `42M * 300 bytes = 12.6 GB` of command payload before protocol overhead, replication, TLS, retries, and cross-AZ traffic. With replication and retries, effective network can be several times larger.

Memory: `42M * 80 bytes = 3.36 GB` for one timeline entry before Redis object overhead. Real Redis sorted-set overhead can be far higher than 80 bytes/member, so the effective memory impact may be tens of GB for one tweet, plus eviction churn. It is also concentrated over minutes, so ops/sec and hot shards matter more than daily average.

### Org/Runbook Changes

- Product flags that alter fan-out mode require SRE approval and automatic capacity simulation.
- Hard invariant: accounts above celebrity threshold cannot use full write fan-out without an emergency exception.
- Runbook: "Social hot author" with steps to identify hot partition/key, throttle author, switch to read-fanout, protect bid traffic, and drain lag.
- Dashboards: lag by key/partition, Redis top keys, Cassandra compaction, reconnect rate, bid delivery p99.
- Ownership: Feed team owns fan-out strategy; SRE owns kill switches and incident runbook; product owns launch checklist and blast-radius review.

---

## Scoring Guide - 85% Gate

Allocate 100 points:

| Area | Points |
|------|--------|
| Rapid-fire correctness | 28 |
| Root-cause and evidence mapping | 20 |
| Timed incident decisions | 16 |
| Bad-fix analysis | 10 |
| Capacity math | 10 |
| Recovery and correctness plan | 8 |
| Org/runbook prevention | 8 |

Pass gate: **85%+** with no critical miss on the primary root cause. A response below 70% should review Week 9 fan-out strategies, Kafka hot partitions, Redis hot keys, and WebSocket reconnect behavior before moving on.
