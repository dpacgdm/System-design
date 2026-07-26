# Design Trending Hashtags
> **Week 09 - Feed and Chat System Designs**
> **Interview themes:** Meta social trends, Twitter/X trending topics, Kafka stream aggregation, abuse-resistant ranking, geographically consistent top-K.
> **Northstar continuity:** Northstar Commerce has a social feed, live auction chat, seller updates, and support/discovery surfaces that can expose trending topics.
> **Answer key:** [`../answers/Week-09-Feed-and-Chat-Designs/Design Trending Hashtags Answers.md`](../answers/Week-09-Feed-and-Chat-Designs/Design%20Trending%20Hashtags%20Answers.md)

This module designs the system that identifies, ranks, and serves trending hashtags across global, regional, language, and interest surfaces.
The important interview move is to separate post durability from derived trend state and to treat abuse as part of the ranking problem, not an afterthought.
The learner file ends at questions; full worked answers live under `answers/`.

## Learning Objectives

### Foundation

- Describe the write path from post creation through hashtag extraction, Kafka ingestion, stream counting, top-K merge, cache publish, and read serving.
- Explain sliding windows, tumbling windows, hopping windows, and why trend detection needs velocity rather than only total count.
- Use count-min sketch, heavy-hitter summaries, and bounded top-K heaps to avoid exact counters for every tag in every region.
- Identify why normalized hashtag keys create hot partitions during breaking events.
- Distinguish raw mention counts, unique author counts, weighted counts, and abuse-adjusted rank scores.
- Explain why trend ranks are eventually consistent and how much inconsistency a product surface can tolerate.
- Serve trends from cache while preserving moderation and emergency override semantics.
- Calculate stream event volume and state size from posts/sec, hashtags/post, geos, and windows.

### Staff

- Design Kafka partitioning and repartitioning so one hashtag does not stall the entire trend pipeline.
- Build geo and language trends from local windows while preserving a coherent global list.
- Detect astroturfing using entropy, account age, text duplication, graph structure, velocity shape, and external signals.
- Create a consistency contract for rank changes: publish cadence, cache TTL, hysteresis, and monotonic safety during incidents.
- Sequence mitigation for hot partitions, stream lag, bad abuse model rollout, stale trend cache, and moderation backlog.
- Protect feed and chat systems from trend backfills and analytics replays.
- Define rate limits and kill switches per tag, geo, language, user cluster, model version, worker pool, and tenant.
- Calculate unit cost per hashtag mention and top-K publish at peak traffic.

### Principal stretch

- Defend the product tradeoff between surfacing real social movements quickly and slowing coordinated manipulation.
- Design auditability so Trust and Safety can explain why a tag was promoted, demoted, hidden, or restored.
- Plan multi-region failover without double-counting mentions or publishing contradictory global ranks.
- Constrain ML abuse models so a bad threshold cannot silently suppress legitimate civic, safety, or support trends.
- Separate advertiser/promoted trends from organic trends while avoiding tenant leakage and user trust damage.

## Wrong Mental Models

### Mental model 1: Trending means highest count

- Why it fails: Highest lifetime or 24-hour count favors old large tags; trends need velocity, acceleration, uniqueness, and recency.
- Interview correction: define the invariant, the time window, the estimator, the merge step, and the abuse gate.
- Production smell: a design that can rank a tag but cannot explain why the tag is safe to show is incomplete.

### Mental model 2: Just increment a counter per hashtag

- Why it fails: A single counter per hot tag becomes a hot key and loses time-window behavior.
- Interview correction: define the invariant, the time window, the estimator, the merge step, and the abuse gate.
- Production smell: a design that can rank a tag but cannot explain why the tag is safe to show is incomplete.

### Mental model 3: Kafka solves real time

- Why it fails: Kafka preserves durable ordered logs per partition; stream lag and hot keys still make ranks stale.
- Interview correction: define the invariant, the time window, the estimator, the merge step, and the abuse gate.
- Production smell: a design that can rank a tag but cannot explain why the tag is safe to show is incomplete.

### Mental model 4: Count-min sketch gives exact top-K

- Why it fails: A sketch estimates counts with error; top-K requires a candidate structure and merge strategy.
- Interview correction: define the invariant, the time window, the estimator, the merge step, and the abuse gate.
- Production smell: a design that can rank a tag but cannot explain why the tag is safe to show is incomplete.

### Mental model 5: Global trend can be computed from regional top-10 lists

- Why it fails: A tag ranked 11th in many regions may be globally dominant; merge needs enough candidates and counts.
- Interview correction: define the invariant, the time window, the estimator, the merge step, and the abuse gate.
- Production smell: a design that can rank a tag but cannot explain why the tag is safe to show is incomplete.

### Mental model 6: Abuse is only Trust and Safety's problem

- Why it fails: The ranking system must include abuse features before publishing; downstream moderation alone is too late.
- Interview correction: define the invariant, the time window, the estimator, the merge step, and the abuse gate.
- Production smell: a design that can rank a tag but cannot explain why the tag is safe to show is incomplete.

### Mental model 7: Geo trends are just IP geolocation

- Why it fails: Geo assignment involves user locale, event location, privacy rules, VPN/proxy risk, and travel behavior.
- Interview correction: define the invariant, the time window, the estimator, the merge step, and the abuse gate.
- Production smell: a design that can rank a tag but cannot explain why the tag is safe to show is incomplete.

### Mental model 8: Rank consistency means every user sees the same rank at the same millisecond

- Why it fails: Production consistency is a contract: publish cadence, cache version, hysteresis, and bounded staleness.
- Interview correction: define the invariant, the time window, the estimator, the merge step, and the abuse gate.
- Production smell: a design that can rank a tag but cannot explain why the tag is safe to show is incomplete.

### Mental model 9: Deleting abusive posts automatically fixes trends

- Why it fails: Derived windows and caches must be corrected or expire; audit must preserve why a tag was demoted.
- Interview correction: define the invariant, the time window, the estimator, the merge step, and the abuse gate.
- Production smell: a design that can rank a tag but cannot explain why the tag is safe to show is incomplete.

### Mental model 10: Adding partitions fixes hot hashtag incidents

- Why it fails: If keying remains `normalized_tag`, the hot tag still lands on one partition unless salting or two-stage aggregation changes.
- Interview correction: define the invariant, the time window, the estimator, the merge step, and the abuse gate.
- Production smell: a design that can rank a tag but cannot explain why the tag is safe to show is incomplete.

## Requirements and Constraints

### Product scope

- Extract hashtags from posts, comments, live auction chat, seller updates, and support/community surfaces.
- Rank trends globally, by region, by language, and optionally by interest cluster.
- Serve trend lists to feed, search, discovery, and live auction companion panels with p99 read latency under 80 ms.
- Update published trend ranks every 30 seconds for hot surfaces and every 2 to 5 minutes for low-traffic surfaces.
- Suppress, demote, annotate, or review trends that are abusive, unsafe, illegal, or manipulative.
- Provide audit trails for rank inputs, moderation decisions, model versions, and emergency overrides.
- Support backfill and replay after parser, abuse model, or stream processor bugs without corrupting current serving.
- Protect Northstar checkout, bid websocket, feed posting, and chat delivery from trend pipeline overload.

### Functional requirements

| ID | Requirement | Notes |
| --- | --- | --- |
| F1 | Extract normalized hashtags from accepted posts | Post durability is owned by feed/chat, not trends. |
| F2 | Count mentions in rolling windows | Support 1m, 5m, 15m, 1h, and 24h windows. |
| F3 | Estimate top-K by geo/language/global | Bound memory and CPU with sketches and candidate heaps. |
| F4 | Apply abuse and safety adjustments before publish | Risk gates are part of ranking. |
| F5 | Serve cached ranked lists | Readers do not hit stream processors. |
| F6 | Expose moderation override | Hide, demote, annotate, region-scope, or restore. |
| F7 | Audit rank decisions | Store rank version, model version, inputs, and decisions. |
| F8 | Replay corrected windows | Backfills are isolated from live traffic. |

### Non-functional requirements

| Area | Target | Why it matters |
| --- | --- | --- |
| Ingest | Handle 250k posts/sec peak and 400k hashtag mentions/sec | Live events create bursty tag volume. |
| Freshness | Publish hot trend lists within 60 seconds | Trend value decays quickly. |
| Read latency | p99 <= 80 ms from trend cache | Feed and search surfaces cannot block on trends. |
| Availability | 99.99% read serving; stream pipeline can degrade | Stale trends are better than unavailable feed. |
| Accuracy | Top ranks stable within bounded error | Sketch error must not reorder obviously dominant tags. |
| Abuse | Detect coordinated manipulation before rank 1 publish | Astroturf can cause customer trust and safety incidents. |
| Cost | Track per mention, window update, and top-K publish | State and observability explode with geos/windows. |
| Privacy | No raw sensitive attributes in trend keys or exports | Trend analytics can leak small cohorts. |

### Constraints and assumptions

- Northstar already has feed posting and live auction chat; trend pipeline consumes accepted post events and does not decide post durability.
- A post can contain zero to five hashtags after parser limits; excessive tags are truncated or downweighted.
- Normalized tag includes Unicode normalization in real systems; this file keeps examples ASCII for readability.
- Events are at least once; duplicates and edits/deletes require idempotent corrections or negative events.
- User privacy rules may restrict geo granularity and profile-based trend personalization.
- Trust and Safety owns policy decisions; trend system owns enforcement hooks and auditable ranking inputs.
- Global ranks can tolerate 30 to 60 seconds staleness; emergency hides must propagate faster.
- Trend systems can serve stale or empty lists but must not surface tags marked hidden by policy.
- Advertiser/promoted trends are out of scope for ranking mechanics but are included in gates for tenant isolation.
- Exact counts for every hashtag in every geo/window are too expensive and unnecessary for top-K discovery.

## Critical Paths

### Architecture map

```text
Post/chat write path
  -> Feed or chat service accepts durable post
  -> Hashtag extractor normalizes tags and emits hashtag_mention events
  -> Kafka topic hashtag_mentions_raw
  -> Parser/enrichment: user risk, geo, language, author age, graph hints, duplicate text cluster
  -> Kafka topic hashtag_mentions_enriched
  -> Windowed stream processors
     -> local sketches and per-partition top-K candidates
     -> hot-tag salted aggregation
     -> geo/language/global merge
     -> abuse and safety rank adjustment
     -> rank publish event with version
  -> Trend cache and API
  -> Feed/search/live auction clients read cached trend lists
Moderation path
  -> Trust and Safety override service
  -> emergency hide/demote/annotate events
  -> cache invalidation and rank publisher fence
Replay path
  -> isolated backfill topics and state stores
  -> corrected rank snapshots for reports, not live publish until validated
```

### Write path: accepted post to hashtag event

1. Feed or chat service validates author, rate limits, content policy, and post durability before trends see the event.
2. Accepted post event includes post_id, author_id, event_time, text hash, language, coarse geo, source surface, and moderation state.
3. Hashtag extractor parses tags, normalizes case, strips punctuation, handles aliases, and enforces max tags per post.
4. Extractor emits one hashtag_mention event per normalized tag plus a post_tag_set event for delete/edit correction.
5. Duplicate event ids are deterministic: post_id plus normalized_tag plus operation version.
6. If a post is edited, old tags receive decrement/correction events and new tags receive increment events.
7. If a post is deleted or policy-hidden, derived trend state receives correction or suppression signals depending on product rules.
8. Events enter Kafka with enough context for stream processing but not raw private user attributes.
9. The raw topic is partitioned for ingest durability; a later repartition stage can use salted keys for hot tags.
10. Extractor failure should not block post creation unless product policy requires hashtags to be validated synchronously.
11. Parser metrics include extraction errors, tags per post, duplicate post event rate, and policy-hidden tag rate.
12. The serving trend system never becomes source of truth for posts or moderation state.

### Stream path: windows, sketches, and top-K

1. Enrichment adds coarse geo, language, account age bucket, follower graph hints, client type, risk score, and duplicate text cluster id.
2. A first-stage processor computes local window counts using hopping windows such as 1m slide over 5m and 5m slide over 1h.
3. Count-min sketch estimates mention counts for many tags without storing exact counters for every low-frequency tag.
4. A small exact map can track candidate heavy hitters from the sketch, SpaceSaving, or lossy counting output.
5. Each partition emits top-K candidates with estimated count, error bound, unique author estimate, weighted count, and abuse features.
6. The merge stage combines candidate lists from partitions and geos; K must be larger than the final list to avoid losing cross-region broad tags.
7. Ranking score uses growth rate, unique authors, geographic concentration, language, recency, previous rank, and abuse penalty.
8. Hysteresis prevents rank thrash: a new tag must beat current rank by margin or sustain velocity for N publish intervals.
9. Publish events include rank_version, window_end, model_version, input offsets, and override version.
10. Trend cache stores global/geo/language lists keyed by version and refuses to publish ranks older than current policy override version.
11. Backfill processors write corrected snapshots to separate namespaces until validated, then can repair reports or republish with an explicit correction marker.
12. Stream lag alerting is by partition, tag family, geo, and operator; median lag hides hot partitions.

### Read path: serving trends

- Client asks trend API for surface, region, language, user consent class, and optionally interest context.
- Trend API authenticates if needed and authorizes protected or internal surfaces.
- API reads a cached trend list by surface/geo/language/version; it does not call stream processors.
- Emergency hide/demote list is checked at read or cache-publish time so stale ranks do not bypass policy.
- Response includes tag, display label, rank, movement, optional context, and rank_version.
- For sensitive trends, response may include an annotation or link to authoritative support page rather than raw promotion.
- If cache is stale but policy version is current, serve stale within TTL and mark freshness header.
- If policy version is stale or override service is unavailable for a hidden tag, fail closed for that tag.
- If global cache is unavailable, return regional or previous snapshot rather than querying Kafka.
- Trend reads are CDN-cacheable only for public anonymous surfaces with no personalized or protected context.

### Consistency boundaries

- Strong consistency: author privacy, blocked/hidden tag policy, moderation overrides, support/admin actions.
- Bounded staleness: published rank list, moving averages, abuse scores, geo assignments, unique author estimates.
- Eventual consistency: analytics exports, historical trend charts, model feature stores, replayed corrections.
- Fail closed: hidden tag, protected author content, private/community-only posts, emergency safety blocks.
- Serve stale: previous safe trend list, previous rank movement, cached counts within TTL.
- Drop optional: personalized trends, explanatory snippets, ads/promoted modules, expensive graph features.
- Never do: publish a tag known to be hidden because stream lag or cache TTL made it convenient.

## Data Model and Capacity Math

### Core events and state

| Object | Key | Notes |
| --- | --- | --- |
| post_accepted | post_id | Source event from feed/chat; durable post truth. |
| hashtag_mention | post_id + normalized_tag + op_version | Increment event with author, geo, language, risk hints. |
| hashtag_correction | post_id + normalized_tag + correction_seq | Delete/edit/moderation correction. |
| window_count_state | window + shard + tag | Sketch or exact candidate state. |
| topk_candidate | window + geo + shard | Candidate list for merge stage. |
| trend_rank_snapshot | surface + geo + language + window_end + version | Published list and audit input offsets. |
| trend_override | tag + scope + version | Hide, demote, annotate, restore. |
| abuse_feature_state | tag + window | Entropy, duplication, account age, graph spread. |
| trend_cache | surface + geo + language + version | Serving cache with policy version. |
| audit_record | rank_version + tag | Inputs, model version, override version, and reason codes. |

### Baseline traffic assumptions

- Northstar social/feed/live auction traffic: 12M DAU and 800k concurrent users during major auctions.
- Assume 250k accepted posts or chat messages/sec at peak across feed, comments, and live auction chat.
- Assume 45 percent of posts contain at least one hashtag during events.
- Assume average 1.6 hashtags for posts that contain hashtags after parser truncation.
- Peak hashtag mention rate = 250k * 0.45 * 1.6 = 180k mentions/sec for ordinary event peak.
- Design headroom for coordinated events and spam at 400k mentions/sec.
- If event size averages 700 bytes after enrichment, 400k/sec is 280 MB/sec before Kafka replication and compression.
- With replication factor 3, raw broker write amplification is roughly 840 MB/sec before compression.
- If there are 96 partitions, uniform average is about 4.2k mentions/sec per partition, but a hot tag can push 100k/sec to one key.
- A five-minute window at 400k/sec contains 120M mention events.
- Exact per-tag-per-geo-per-window counters are plausible only for candidates; all long-tail tags need approximate or compact state.
- If one state entry costs 80 bytes and 50M active tag-window-geo entries exist, raw state is 4 GB before indexes/checkpoints, but cardinality can be far higher.
- Count-min sketch width for epsilon 0.001 is about 2,718 counters per row; depth for delta 0.001 is about 7 rows.
- With 8-byte counters, one sketch is about 152 KB per window shard; multiply by geos, languages, and windows.
- A top-K heap of 1,000 candidates per shard is cheap; correctness depends on candidate recall and merge depth, not heap memory.

### Capacity worksheet

1. Mention QPS = accepted_posts_per_sec * hashtag_post_ratio * average_hashtags_per_tagged_post.
2. Kafka bytes/sec = mention_QPS * average_event_bytes * replication_factor / compression_factor.
3. Uniform partition load = mention_QPS / partition_count; hot partition load can approach hot_tag_QPS if keyed by tag.
4. Window event count = mention_QPS * window_seconds.
5. Sketch memory = width * depth * counter_bytes * windows * geos * shards.
6. Top-K merge cost = candidate_count_per_partition * partition_count * publish_frequency.
7. Read QPS = active_clients * trend_refreshes_per_min / 60; serve from cache, never processors.
8. Cache object size = tags_per_list * metadata_per_tag; multiply by surfaces, geos, languages, and versions retained.
9. Replay cost = historical_events / replay_duration plus live traffic; replay must not starve live processors.
10. Abuse feature state = active_tags * feature_count * windows; cap or compact features for long-tail tags.
11. Hot tag salting factor should keep per-subkey QPS below processor and broker safe limits.
12. For 100k/sec hot tag and 5k/sec target per subkey, use at least 20 salts plus headroom.
13. Cache TTL must be shorter than acceptable abuse exposure; 300 seconds may be too long for high-volatility surfaces.
14. Hysteresis lowers rank churn but can preserve an abusive tag too long if abuse penalty arrives late.
15. Moderation queue capacity should be sized for suspicious clusters, not just individual tags.

### Sliding window mechanisms

- A tumbling window counts fixed intervals such as 12:00:00 to 12:04:59, but boundary effects can miss emerging trends.
- A sliding or hopping window updates more often, for example a 5-minute window every 30 seconds.
- Trend scoring usually compares current window to baseline windows such as previous hour or same time yesterday.
- Velocity is count delta over time; acceleration is velocity delta and helps detect sudden emergence.
- Very short windows are responsive but noisy; longer windows are stable but slow.
- Use multiple windows and combine features rather than one magic window.
- Event time should drive windows, but ingestion time is needed for lag monitoring and late-event handling.
- Watermarks define how long the processor waits for late events before finalizing a window.
- For live trends, late events can update historical analytics but should not constantly rewrite current ranks.
- Correction events from deletes or moderation should update live state if inside active windows and historical state if inside retention.
- Rank publisher should include window_end and watermark so readers know freshness.
- A common mistake is publishing every incremental update; publish cadence and hysteresis protect readers from thrash.
- Another mistake is using only raw mentions; coordinated spam can produce high raw counts with low unique author diversity.
- Staff answer: define exact windows, update cadence, allowed lateness, and correction semantics.
- Principal answer: explain how window choices affect abuse, civic events, support incidents, and product trust.

### Count-min sketch and top-K mechanisms

- Count-min sketch uses several hash rows and returns the minimum counter estimate across rows.
- It overestimates counts because collisions add noise; it does not underestimate if counters only increment.
- The error bound is useful for deciding whether two tags are too close to rank confidently.
- Sketch alone does not list top tags; pair it with candidate heavy-hitter tracking.
- SpaceSaving or lossy counting can maintain candidate heavy hitters with bounded memory.
- Exact counters can be kept for the candidate set after a tag crosses a threshold.
- Unique authors can use HyperLogLog or sampled sets; exact author sets are too large for every tag/window.
- Abuse features need their own compact structures: account age histograms, text cluster counts, geo entropy, and graph spread.
- Partition-local top-K must emit more candidates than final K so global merge does not lose broad tags.
- If final list is top 20, emitting top 200 or top 1000 per partition/geo is a product and cost tradeoff.
- Error bounds should be surfaced to ranker; tags within error margin can be ordered by stability or held back.
- A small exact deny/allow/override set is separate from approximate count state.
- Sketch state must be versioned because changing epsilon or hash seeds changes comparability.
- Backfills with a new sketch version should not merge blindly with live old-version state.
- A good interview answer can state what the sketch buys and what it cannot do.

### Hot partition mechanisms

- Keying Kafka by normalized_tag preserves per-tag order but sends a hot hashtag to one partition.
- Keying by post_id spreads load but requires a second aggregation stage to combine tag counts.
- A two-stage design can use salted keys such as tag#salt for hot tags, then merge salted partial counts.
- Hot tag detection can be reactive from partition lag or proactive from candidate velocity in the extractor.
- Dynamic salting must be deterministic within a window so counts are mergeable and replayable.
- Changing partition count alone does not move a hot key if all events for that tag still choose one partition.
- Repartitioning during peak can increase lag and state migration cost; use hot-key isolation first.
- The hot-key registry should expire entries after velocity drops to avoid permanent overcomplexity.
- Processor state for hot tags can live in dedicated pools so ordinary tags continue updating.
- Caches should publish partial degradation: stale global list but healthy regional lists, or hide one tag only.
- Metrics must show lag by partition and by hot tag; average lag is misleading.
- Runbook should include preauthorized salting for a tag family and rollback after the window closes.
- Backfills must replay with the same salting version used in the incident window or explicitly translate state.
- Hot partitions are common during real news; the design must not treat every hot key as abuse.
- Staff signal: candidate calculates per-hot-tag QPS and salting factor.

### Geo and language trend mechanisms

- Geo trends are not just current IP; combine declared region, coarse location, content language, and privacy policy.
- Users traveling or using VPNs can distort geo signals; use confidence scores and coarse aggregation.
- A tag may be local in one city, regional in a country, and irrelevant globally; each surface has separate scoring.
- Global trend merge must consider tags that are moderately high in many regions, not only regional rank 1 tags.
- Language normalization handles aliases, casing, spacing, transliteration, and banned spelling variants.
- A tag can have different meanings in different languages; moderation and annotations are scoped accordingly.
- Geo counts should respect privacy thresholds so tiny regions do not reveal group behavior.
- Regional cache publish should continue when global merge is degraded, if regional policy state is current.
- Global list can include region diversity constraints to avoid one country dominating every slot during a local event.
- Live auction trends may need event-specific region weighting because Northstar business impact is uneven.
- Consistency contract: a user in a region should not see a tag hidden for that region even if global cache still contains it.
- Failover to another region must not assign all unknown users to the failover region for trend geo purposes.
- Geo trend dashboards need rank, mentions, unique authors, abuse score, and confidence by region.
- Backfill of geo assignment after IP database update should repair analytics but avoid rewriting live history without annotation.
- Principal tradeoff: speed of surfacing local crises versus risk of manipulation in small geos.

### Abuse and astroturf mechanisms

- Astroturfing tries to make coordinated behavior look organic by using many accounts and repeated text.
- Raw mention growth is necessary for a trend but not sufficient for legitimacy.
- Unique authors, account age distribution, device diversity, IP/ASN entropy, graph spread, and text diversity are core features.
- Organic trends usually have broader reply trees, quote/comment variation, and mixed phrasing.
- Coordinated campaigns often show synchronized bursts, near-duplicate text, new-account concentration, and external referral spikes.
- Abuse model output should be a penalty, review trigger, hide decision, or annotation, depending on confidence and policy.
- High-confidence harmful tags can be hidden or demoted; medium-confidence tags may be held from global rank pending review.
- False positives are serious: suppressing legitimate safety reports can damage trust.
- Use model version and threshold as audited config with canary metrics beyond CPU and p99.
- Canaries should include known organic events, known coordinated campaigns, and multilingual edge cases.
- Threshold changes should be scoped by region or surface when possible.
- Manual overrides need reason, scope, expiry, owner, and appeal/review path.
- Abuse features should not expose raw identities to rank readers or advertiser tenants.
- A trend can be demoted while the underlying posts remain visible, or posts can be removed while tag audit remains.
- Principal answer: manipulation defense is part of ranking, not a downstream cleanup job.

### Rank consistency mechanisms

- Ranks are published snapshots with version numbers, not per-request live computations.
- Each snapshot includes input offsets, window end, model version, override version, and cache expiry.
- Readers can tolerate seeing version N while another region sees N+1 if TTL and surface contract allow it.
- Emergency hides are stronger than ordinary rank publish and should invalidate or overlay stale cache entries.
- Hysteresis prevents tags from bouncing in and out because counts are close or sketch error overlaps.
- A rank should not move dramatically on every publish unless score change exceeds a configured margin.
- Stability must not protect known abusive tags; safety overrides bypass hysteresis.
- Cache TTL should be short for volatile surfaces and longer for low-risk informational modules.
- Cache stampede is prevented with single-flight refresh and stale-while-revalidate for safe snapshots.
- Rank publisher must reject stale stream outputs that are older than the current override version.
- Clients should not locally cache hidden tags beyond emergency TTL.
- A/B experiments need separate rank versions so one experiment cannot poison global cache.
- Observability should compare rank versions by region and detect divergence beyond contract.
- After replay correction, publish a correction snapshot for analytics; live UI may not need to rewrite old rank history.
- Staff signal: candidate defines consistency in terms of product contract, not impossible instant global agreement.

### Operational dashboards and runbooks

- Ingest dashboard: accepted post rate, hashtag mention rate, extraction errors, duplicate events, tags per post.
- Kafka dashboard: bytes in/out, producer error, partition lag, hot key estimates, broker disk/network saturation.
- Processor dashboard: window update latency, checkpoint duration, state size, backpressure, watermark delay.
- Sketch dashboard: candidate recall canaries, error bounds, top-K merge latency, collision indicators.
- Rank dashboard: publish cadence, rank volatility, cache freshness, stale snapshot age, divergence by region.
- Abuse dashboard: suppress/demote/hide rates, model version, threshold, duplicate clusters, new-account ratios.
- Moderation dashboard: queue depth, override latency, hidden tags by scope, expired overrides, appeal workload.
- Read dashboard: API p99, cache hit ratio, stale served rate, per-surface error rate, emergency overlay usage.
- Cost dashboard: cost per million mentions, state-store bytes, checkpoint bytes, replay throughput, observability cardinality.
- Runbook first step: classify as stream capacity, abuse manipulation, policy emergency, cache serving, or reporting/backfill.
- Runbook for hot partition: isolate hot tag with salting or dedicated pool, reduce publish cadence if safe, and protect ordinary tags.
- Runbook for abuse: demote or hide scoped tag, lower threshold only with Trust and Safety approval, preserve evidence.
- Runbook for stale cache: shorten TTL or invalidate scoped cache; do not flush all feed caches.
- Runbook for replay: use isolated backfill topic and publish corrected analytics only after validation.
- Runbook for model rollback: roll back threshold/model version and compare known organic and known abusive fixtures.

### Northstar integration points

- Feed and chat own post durability; trends own derived visibility and rank.
- Live auctions create predictable bursts; trend pipeline should pre-scale and pre-register event tags.
- Wallet and checkout health signals are useful red herrings during security-themed astroturfing.
- Risk engine provides user/device/account risk hints but trend ranker must handle risk-service timeout safely.
- Support pages can be linked from annotated sensitive trends to reduce panic while preserving legitimate discussion.
- Seller analytics may consume trend reports but must not see user-level evidence or other tenants' private signals.
- Ads/promoted modules must be visually and architecturally separated from organic trends.
- Northstar recurring hot-key theme appears as hot hashtag partition, not celebrity timeline key.
- Northstar replay theme appears when corrected parser or abuse model backfills threaten live stream processors.
- Northstar noisy-neighbor theme appears when one event tag or promoted campaign exhausts shared top-K merge resources.
- Incident command should protect checkout and bid WebSocket SLOs before trend freshness.
- Trend suppression during a wallet rumor needs Trust and Safety, security, support, and comms coordination.
- If a real wallet incident occurs, trends should route users to authoritative updates rather than hide all discussion by default.
- A regional event should not become global solely because one language or region has denser chat traffic.
- The safest default during uncertainty is demotion or annotation plus review, not silent promotion.

### Interview worksheet prompts

1. Draw the post-to-trend pipeline and mark source of truth versus derived state.
2. Choose keys for raw Kafka ingest, enriched repartition, hot-tag salting, and top-K merge.
3. Compute mention QPS from posts/sec, tag ratio, and hashtags per post.
4. Compute hot partition skew if one tag is 25 percent of mentions and key is normalized_tag.
5. Pick sliding windows and explain freshness versus noise tradeoff.
6. Explain what count-min sketch estimates and why it cannot emit top-K alone.
7. Explain how unique author estimates change rank score under spam.
8. Explain how to merge regional candidates into a global list without losing broad tags.
9. Explain how cache TTL interacts with emergency hide latency.
10. Explain how rank hysteresis prevents thrash but can hurt abuse response.
11. Explain how to replay corrected parser output without corrupting live ranks.
12. Explain why adding Kafka partitions does not fix normalized_tag hot keys.
13. Explain why hiding all trends can be a bad first action.
14. Explain why raw mentions can be a red herring during astroturfing.
15. Name metrics that separate organic breaking news from coordinated manipulation.
16. Name a safe degradation when top-K merge is overloaded.
17. Name a safe degradation when abuse model times out.
18. Name a safe degradation when trend cache is stale but policy state is current.
19. Name an unsafe action during a moderation emergency.
20. Define one game day for hot partition plus model threshold regression.
21. Define one tenant isolation test for promoted trends or seller analytics.
22. Define one privacy threshold for geo trends.
23. Define one audit record needed to explain a demoted tag.
24. Define one replay budget for historical correction.
25. Define one blast-radius boundary for a bad tag, region, model version, or worker pool.

## Production Readiness Appendix for Trending Hashtags

This appendix adds the operational and algorithmic depth expected in Meta-style feed and trends interviews.

### API contracts and invariants

- `hashtag_mention` is derived from an accepted post; if the post is not durable or visible, it should not create a normal public trend count.
- `hashtag_correction` carries post_id, old tag, new tag or delete reason, operation version, and moderation state.
- `trend_snapshot` is a published immutable rank version for a surface, region, language, and window end.
- `trend_override` is a control-plane event with tag, scope, action, reason, owner, expiry, and policy version.
- `GET /trends` reads only rank snapshots and override overlays; it does not read Kafka or stream state.
- The client cannot request hidden tags by bypassing the trend list; search suggestions and feed modules must share override state.
- A moderator can hide a tag in one region while leaving another region annotated or unaffected.
- A backfill job can write corrected analytics snapshots but cannot publish live ranks without validation and explicit promotion.
- Invariant: private or protected posts do not contribute to public trend counts.
- Invariant: a hidden tag does not appear in public trend APIs after override version reaches cache/API.
- Invariant: stream lag cannot block post creation or chat delivery.
- Invariant: rank score records enough reason codes and versions for audit.
- Invariant: approximate counters can affect rank confidence but cannot bypass safety policy.
- Invariant: deletes, edits, and moderation actions have correction paths for active windows and audit paths for historical windows.
- Invariant: promoted trends, if present, are labeled and isolated from organic trend ranking.
- Invariant: replay is rate-limited and isolated from live rank publishing.
- Invariant: cache TTL can preserve safe staleness but cannot preserve a known hidden tag.
- Invariant: low-confidence geo assignment should not create precise small-cohort trends.
- Invariant: raw identities are not exposed in trend API, seller analytics, or advertiser reports.
- Invariant: an abuse model deploy cannot become global policy without threshold, fixture, and override review.

### Parser and normalization edge cases

- Hashtag extraction must define whether underscores, digits, emoji, case, punctuation, accents, and full-width characters are distinct.
- Normalization maps visually similar forms where product policy chooses to merge them, but audit stores raw display examples.
- A tag alias table can merge campaign spellings, but alias updates are versioned because historical ranks need explanation.
- Parser limits tags per post so spam cannot create hundreds of mentions from one message.
- Parser should not count tags hidden inside URLs or markup unless product rules explicitly permit it.
- A post edit must decrement old tags and increment new tags with the same operation version to prevent double counting.
- A repost/quote/share has explicit weighting; otherwise bots can amplify with cheap reshares.
- Live chat messages may have lower weight than feed posts because they are shorter and more bursty.
- Seller or brand official accounts can be weighted differently only with policy approval and abuse safeguards.
- Parser deploys need fixture tests for multilingual tags, banned variants, aliases, and edit/delete paths.
- Malformed or extremely long tags are dropped with metrics, not allowed to poison stream processors.
- Parser output carries parser_version so stream windows can diagnose sudden count shifts.
- A parser rollback may require correction events for active windows and analytics repair for historical charts.
- Foundation signal: learner can explain why parsing is not just regex and INCR.
- Staff signal: learner can repair a bad parser deploy without rewriting posts by hand.

### Delete, edit, and moderation correction semantics

- A deleted public post should stop contributing to active trend windows if product policy counts only visible content.
- Historical charts may retain aggregate counts with policy labels, depending on audit and legal requirements.
- A moderation hide can either remove counts, demote rank, or hide display; the action type must be explicit.
- A correction event is not a negative raw post; it is a derived-state repair with reason and operation version.
- Corrections must be idempotent because delete and moderation systems retry under load.
- If a correction arrives after the live window expires, it updates analytics snapshots or audit but not necessarily live UI.
- If a tag is hidden, cache/API overlay enforces display policy before waiting for all window counts to drain.
- If a post changes visibility from private to public, trend contribution should follow product policy and event time semantics.
- If a protected community post leaks into raw stream, policy filter must prevent public rank contribution and alert.
- Backfill can recompute counts from accepted post logs and correction logs, but live snapshots require validation before publish.
- Correction dashboards show events by reason: edit, delete, author privacy, policy hide, spam cluster, or parser repair.
- A high correction rate after deploy is a canary failure even if rank API p99 is green.
- Trend rank audit stores pre-correction and post-correction score where major rank changes occur.
- Support communications need to know whether a tag was hidden due to policy or corrected due to data bug.
- Principal signal: learner preserves evidence while repairing user-visible harm.

### Rank scoring formula worksheet

- Start with normalized_count for the current short window.
- Compute baseline_count from a longer historical window and comparable daypart.
- Growth_rate can be `(current + smoothing) / (baseline + smoothing)` to avoid division by zero explosions.
- Unique_author_factor rewards broad participation and dampens repeated posts from few accounts.
- Text_diversity_factor rewards organic phrasing and penalizes near-duplicate clusters.
- Geo_entropy can reward broad global spread for global ranks or local concentration for local ranks, depending on surface.
- Account_trust_factor uses coarse age/risk buckets, not raw private profiles in the rank output.
- Abuse_penalty is applied before publish and can hold a tag for review.
- Hysteresis_margin means a challenger must beat incumbent by a threshold to reduce rank thrash.
- Freshness_decay prevents old tags from staying high after velocity falls.
- Safety_override can set rank to hidden/demoted/annotated regardless of score.
- Confidence score reflects sketch error, feature freshness, and abuse uncertainty.
- A tag within sketch error margin may be delayed or ordered by previous rank to avoid false precision.
- The rank formula is versioned and sampled inputs are stored for audit.
- Interview signal: learner can explain each factor's failure mode and not just write a score equation.

### Cache and serving consistency details

- Trend cache objects are small and should be replicated close to API servers.
- Key includes surface, geo, language, consent/personalization class, rank_version, and override_version.
- Read API can serve stale-while-revalidate only when override_version is current.
- Emergency override can be implemented as an overlay deny/demote list checked after cache read.
- Cache invalidation is scoped by tag and surface where possible; global flush is last resort.
- Clients receive rank_version so screenshots and support tickets can identify stale behavior.
- Public global trends can be CDN cached briefly; personalized or protected trends should not be CDN cached broadly.
- Feed modules should degrade to no trends or previous safe trends rather than blocking feed load.
- Search suggestions and trend lists must use shared safety overlay or a hidden tag leaks through another surface.
- Cache stampede is controlled with single-flight refresh and jittered expiry.
- A rank publisher writes new snapshot before flipping the pointer so readers never observe half-written lists.
- If a new snapshot is lower quality or missing many geos, publisher can hold previous safe snapshot and alert.
- Stale cache metric is measured by snapshot age and override version mismatch, not just hit ratio.
- Acceptance test: hide a tag and verify every trend API/surface omits it within emergency SLO.
- Staff signal: learner differentiates safe stale rank from unsafe stale policy.

### Stream processing failure controls

- Stream processors use checkpointing so restart resumes without uncontrolled duplication.
- State store compaction is scheduled away from known live events when possible.
- Backpressure signals can reduce publish cadence or candidate depth while keeping corrections and overrides flowing.
- Poison events are isolated by parser version and source surface rather than blocking entire partitions.
- A hot tag can be moved to a dedicated operator pool if ordinary salting is insufficient.
- Operator autoscaling must consider state migration cost; blindly adding workers can worsen checkpoint duration.
- Lag alerts are keyed by max partition lag and top hot keys, not average consumer lag.
- Checkpoint duration alerts catch state-store pain before rank freshness fails.
- Watermark delay alerts catch late-event disorder that can make ranks jump backward.
- A replay job cannot share the live consumer group or live output topic without explicit incident approval.
- Backfill output goes to validation snapshots and only then to reporting or corrected UI history.
- Stream configuration changes need canaries with synthetic hot tags and duplicate/correction fixtures.
- During an incident, preserve raw ingest first; exact analytics can wait.
- During an incident, protect feed/chat posting from trend processor retries and broker saturation.
- Principal signal: learner understands autoscaling stateful streaming is not the same as scaling stateless HTTP.

### Moderation and Trust and Safety workflow

- Trend on-call can recommend demotion/hide, but policy owner authorizes sensitive suppression except preapproved emergency classes.
- Emergency classes include malware, doxxing, targeted harassment, and active financial scam tags as defined by policy.
- Each override has action, scope, reason, owner, approval, expiry, and appeal/review field.
- Demotion lowers rank but can leave discussion discoverable; hide removes public trend display; annotation adds context.
- Annotation can route users to Northstar status or security pages when suppressing discussion would be harmful.
- Review queues group by tag cluster and duplicate text, not individual posts only.
- A model false positive should be reversible with audit and measured by restored rank impact.
- Human review tools need sampled evidence and aggregate features, not raw private data by default.
- Policy decisions are replicated to caches with stronger priority than ordinary rank snapshots.
- Moderator tools have rate limits and break-glass controls because a compromised moderator account can manipulate trends.
- Public comms should distinguish platform security truth from trend manipulation where appropriate.
- Suppression metrics are monitored for regional/language bias and sudden threshold effects.
- A tag can be unsafe globally but legitimate in one local context; scope matters.
- The postmortem records whether automation, human policy, or infrastructure failed.
- Principal signal: learner treats moderation as a socio-technical control plane, not a Boolean filter.

### Privacy, reporting, and analytics

- Trend analytics are aggregated by tag, window, geo, language, and surface with minimum cohort thresholds.
- Small geos or rare languages may be rolled up to larger buckets to avoid revealing group behavior.
- Seller analytics can show public aggregate trends but not user-level author lists or private support signals.
- Advertiser/promoted trend reporting must be separated and labeled to prevent organic trend inference.
- Data retention differs for raw post events, derived count state, audit snapshots, moderation evidence, and analytics reports.
- Right-to-delete workflows remove future use of user-level data while preserving legal aggregate/audit records as policy allows.
- Debug logs should sample tag text carefully because tags can include personal data or harassment content.
- Metrics should hash or bound high-cardinality tag labels and use drilldown stores for detailed investigation.
- Export jobs require purpose, tenant/context, byte budget, and audit.
- A report cannot include a trend audience if cohort is below privacy threshold even if the rank was public.
- Privacy review is needed before interest-personalized trends or cross-surface user profiling.
- Geo enrichment stores confidence and coarse bucket rather than precise location for trend ranking.
- Backfilled analytics after parser bug should mark versions so analysts do not mix incompatible counts.
- Support dashboards should show enough to explain user-facing ranks without exposing private identities.
- Principal signal: learner prevents trend analytics from becoming a covert surveillance product.

### Launch and game-day checklist

- Launch gate: extractor fixture coverage for parser edge cases, edit/delete corrections, and moderation states.
- Launch gate: synthetic hot hashtag proves salting or isolation keeps ordinary tags fresh.
- Launch gate: count-min sketch canary proves error bounds under known heavy hitters.
- Launch gate: top-K merge depth recalls tags spread across many partitions and regions.
- Launch gate: abuse model fixtures include organic event, astroturf cluster, false-positive regional crisis, and multilingual variants.
- Launch gate: emergency hide reaches all serving surfaces under the override SLO.
- Launch gate: trend cache serves stale safe snapshot when stream publish is late.
- Launch gate: replay cannot write to live output without validation approval.
- Game day: live auction creates organic tag at 100k/sec and no abuse suppression.
- Game day: bot cluster creates 1M duplicate posts and tag is demoted before rank 1 global.
- Game day: parser deploy splits aliases and backfill repairs analytics without blocking live publish.
- Game day: override service hides a tag while cache TTL is long and API still removes it.
- Game day: backfill floods state store and live worker bulkhead preserves publish cadence.
- Game day: model threshold suppresses legitimate support tag and rollback/restoration are audited.
- Game day: observability pipeline handles high-cardinality tag burst without taking down on-call dashboards.

### Principal tradeoff cards

- Speed versus safety: faster publish catches real events but gives astroturf less time to be detected.
- Accuracy versus cost: exact counters improve confidence for candidates but are impossible for every long-tail tag/window.
- Global coherence versus regional relevance: one global list is simple but can erase local context.
- Hysteresis versus responsiveness: stable ranks improve UX but can leave fast-emerging events hidden too long.
- Privacy versus personalization: interest trends may be useful but require more sensitive signals and controls.
- Transparency versus gaming: exposing rank reasons helps trust but can teach attackers how to manipulate features.
- Automation versus human review: models scale but humans handle ambiguous safety and public-interest cases.
- Cache freshness versus infrastructure cost: very low TTL increases load and rank jitter.
- Replay correctness versus live freshness: historical repair should not starve live trend discovery.
- Promoted revenue versus organic trust: paid trend modules must not blur labels or influence organic rank invisibly.
- Geo precision versus cohort privacy: small areas make trends more relevant and more identifying.
- Model strictness versus false positives: aggressive astroturf penalties can suppress legitimate grassroots events.
- Operator simplicity versus hot-key resilience: salting and two-stage aggregation add complexity but prevent single-key collapse.
- Audit retention versus data minimization: evidence is needed for safety but must have purpose and access limits.
- Principal signal: candidate names who owns the tradeoff, not only the technical knob.

### Staff and Principal review checklist

- Foundation: Can you explain why trending is derived state?
- Foundation: Can you calculate mention QPS from post QPS?
- Foundation: Can you distinguish raw count from velocity and unique authors?
- Foundation: Can you explain a sliding window and watermark?
- Foundation: Can you explain what count-min sketch does and does not do?
- Staff: Can you fix a hot normalized_tag partition without relying on partition count alone?
- Staff: Can you merge regional candidates without losing globally broad tags?
- Staff: Can you design emergency hide propagation despite cache TTL?
- Staff: Can you handle delete/edit/moderation corrections idempotently?
- Staff: Can you separate organic hot trend from astroturf with telemetry?
- Staff: Can you sequence mitigation for model regression plus stream lag?
- Staff: Can you protect live processors from replay and analytics jobs?
- Principal: Can you defend false-positive tradeoffs with Trust and Safety?
- Principal: Can you preserve audit evidence while repairing public harm?
- Principal: Can you design privacy thresholds for geo trends and reports?
- Principal: Can you keep promoted trends isolated from organic trust?
- Principal: Can you explain rank consistency as product contract, not instant agreement?
- Principal: Can you define game days that combine hot keys, abuse, stale cache, and backfill overload?
- Principal: Can you say what to communicate publicly during a security-themed astroturf campaign?
- Principal: Can you state which business surface degrades first to protect feed/chat/checkout?

## Trending Hashtags Scenario Bank

Use these scenarios to practice root-cause separation, mitigation order, and capacity math.

### Scenario A - Organic sports final

- A championship tag receives 150k mentions/sec for five minutes.
- Unique authors, old-account ratio, and text diversity are all high.
- Kafka partition 22 lags because the tag is keyed by normalized_tag.
- The right action is hot-tag isolation or salting, not abuse demotion.
- The right dashboard compares hot partition lag to overall rank publish health.
- The smallest blast radius is that tag's aggregation path, not global trends.
- Acceptance criterion: ordinary tags continue updating while the hot tag is isolated.

### Scenario B - Coordinated product smear

- A competitor pushes #NorthstarScam with thousands of new accounts and identical text.
- Raw mentions spike faster than #AuctionFinale but unique author count is low.
- The correct response is scoped demotion or review hold plus evidence preservation.
- The wrong response is deleting all posts without audit or hiding every negative Northstar tag.
- Capacity question: estimate duplicate cluster size and moderation queue load.
- Trust question: route users to status/support page if there is legitimate confusion.
- Acceptance criterion: ranker penalizes duplicate cluster before global rank 1 publish.

### Scenario C - Regional emergency false positive

- A real local safety tag appears mostly from new accounts after an outage in a region with low prior usage.
- The abuse model demotes it because account age distribution looks suspicious.
- The correct response is human review, regional restore or annotation, and threshold scope rollback.
- The wrong response is declaring all new-account-heavy tags abusive globally.
- Design implication: model fixtures need regional and language edge cases.
- Audit implication: store why the tag was demoted and who restored it.
- Acceptance criterion: false-positive restoration does not require cache flush or stream replay.

### Scenario D - Alias split after parser rollout

- #NorthstarLive, #northstar-live, and #Northstar_Live become separate normalized tags after deploy.
- Each variant ranks lower, so the real trend disappears from global list.
- The correct response is parser rollback or alias table fix plus correction backfill.
- The wrong response is pinning one display tag manually forever because historical analytics remain wrong.
- Capacity question: correction events may touch every active window and top-K candidate list.
- Consistency question: live UI can show corrected alias before historical chart is repaired if annotated.
- Acceptance criterion: alias fixtures catch variant splits before rollout.

### Scenario E - Trend cache leaks hidden tag

- Trust and Safety hides a doxxing tag globally with override version 48.
- Feed still serves snapshot version 103 with override version 47 from cache.
- The correct action is emergency overlay or scoped invalidation keyed by tag and surface.
- The wrong action is waiting for normal five-minute TTL when known unsafe content is visible.
- Design implication: cache entries need override version and read-time safety check.
- Blast radius: tag/surface cache key first, global cache only if overlay path is broken.
- Acceptance criterion: hidden tag disappears from feed, search suggestions, and live panel under emergency SLO.

### Scenario F - Top-K candidate depth too small

- A tag is rank 12 in every large region and rank 1 nowhere.
- Regional publishers emit only top 10 candidates, so global merge never sees it.
- The correct diagnosis is candidate recall loss, not low global interest.
- The fix is deeper regional candidate emission, approximate global sketches, or a second broad-candidate path.
- Cost tradeoff: candidate depth raises merge CPU and network but improves global recall.
- Acceptance criterion: synthetic broad tag appears in global top-K canary.
- Principal question: how much regional diversity should global rank preserve?

### Scenario G - Observability cardinality incident

- A spam wave creates millions of unique random hashtags.
- Metrics pipeline falls over because raw tag text is used as a metric label.
- The correct response is label bounding/sampling and drilldown storage, not disabling trend safety metrics.
- The wrong response is to remove all tag-level observability during an abuse incident.
- Design implication: global metrics use bounded labels; detailed tag traces live in sampled logs or analytic stores.
- Cost question: observability can become the dominant cost under long-tail spam.
- Acceptance criterion: random-tag flood does not page metrics ingestion before trend pipeline pages.

### Scenario H - Replay rewrites live ranks

- A historical backfill uses the live output topic by mistake.
- Trend API starts showing yesterday's rank snapshots as current.
- The correct response is stop the replay, fence live publisher by window/version, and restore last safe snapshot.
- The wrong response is to clear all trend history because current cache is wrong.
- Design implication: live and backfill namespaces are separate with publish promotion gates.
- Audit implication: rank_version must include window_end and source namespace.
- Acceptance criterion: backfill cannot advance the live pointer without validation token.

### Scenario I - Promoted trend label bug

- A paid trend module loses its sponsored label on one client version.
- Organic rank pipeline is healthy, but user trust and advertiser policy are at risk.
- The correct response is disable promoted trend surface for that client/version or force label overlay.
- The wrong response is changing organic rank score because the bug is presentation/tenant labeling.
- Design implication: promoted and organic caches are separated, but clients also need contract tests.
- Tenant implication: advertiser reports must not infer organic rank data.
- Acceptance criterion: unlabeled paid trend cannot render in any client canary.

### Scenario J - Watermark delay hides late corrections

- Mobile offline clients send delete corrections 20 minutes late during an event.
- Live five-minute windows have expired but historical trend chart still counts removed posts.
- The correct response is repair analytics snapshot and mark correction version; live UI may not need rewrite.
- The wrong response is replaying all live rank snapshots during peak.
- Design implication: live windows and historical analytics have different correction policies.
- Privacy implication: deleted/protected posts should not remain exposed in drilldown evidence beyond policy.
- Acceptance criterion: late correction changes chart/audit without disrupting live trend serving.

### Final calibration questions

1. What exact window and publish cadence would you choose for a live auction surface, and why?
2. What is the maximum acceptable time for an emergency hidden tag to disappear from every user-facing surface?
3. How many salted subkeys do you need when one tag reaches 120k mentions/sec and one subkey can safely handle 6k/sec?
4. What rank confidence signal tells you a sketch error bound is too wide to claim tag A outranks tag B?
5. Which dashboard proves a model threshold change is suppressing legitimate regional trends?
6. Which audit record proves a tag was demoted by abuse model rather than hidden by human policy?
7. Which replay fence prevents yesterday's corrected snapshot from becoming today's live trend list?
8. Which privacy threshold prevents a tiny geo from exposing support or safety behavior?
9. Which kill switch protects feed and checkout when trend backfill overloads shared Kafka or state stores?
10. Which business owner approves restoring a controversial tag after the model generated a false positive?

## Failure and Abuse Catalog

### Catalog

| Failure | Trigger | Primary symptom | Blast radius |
| --- | --- | --- | --- |
| Hot hashtag partition | Kafka keyed by normalized tag | Lag on one partition and stale ranks | Affected tags and any shared merge stage |
| Sketch error reorder | Epsilon too high for close ranks | Wrong top tags or rank flapping | Surface/window using that sketch version |
| Astroturf promotion | Bot/new-account cluster | Manipulated tag reaches top list | User trust, support, safety |
| False positive suppression | Bad model threshold | Legitimate tag hidden | Civic/safety/support trust |
| Geo misassignment | IP database or VPN behavior | Local trend appears in wrong region | Region/language surface |
| Cache stale hidden tag | TTL too long or override not checked | Hidden tag remains visible | Surface/cache scope |
| Backfill overwhelms live | Replay shares workers/state | Fresh ranks lag | Global pipeline if no bulkhead |
| Moderation queue flood | Millions of suspicious posts | Review latency spikes | Safety response |
| Rank thrash | No hysteresis or publish margin | Users see unstable list | Trend UI and notifications |
| Candidate recall loss | Partition top-K too small | Broad tag missing globally | Global trend quality |
| Duplicate events | Producer retry without idempotency | Inflated counts | Tags in retry window |
| Delete correction lag | Policy/deletion events delayed | Removed content still influences trend | Affected tag/window |
| Promoted/organic leakage | Shared cache or labels | Ad looks organic | User trust and tenants |
| Observability cardinality blowup | Raw tag labels everywhere | Metrics cost and outage | Monitoring pipeline |

### Failure-mode reasoning drills

- If raw mentions spike but unique authors do not, suspect spam, duplicate text, or bot cluster before organic trend.
- If partition lag spikes only for one normalized tag, adding consumers without salting will not fully fix it.
- If global rank changes but regional ranks are stable, inspect merge depth, candidate recall, and global weighting.
- If hidden tag remains visible, inspect cache policy/override version before stream processor counts.
- If top-K merge p99 rises while Kafka lag is normal, inspect candidate list size, heap merge, and ranker features.
- If all tags show lower counts after parser deploy, inspect extraction/normalization and schema compatibility.
- If abuse suppress rate drops after model deploy, inspect threshold, model feature availability, and canary coverage.
- If legitimate support tags are hidden, inspect false-positive threshold and escalation path, not only bot metrics.
- If backfill runs during peak, inspect live/backfill worker isolation and state-store checkpoint pressure.
- If trend API p99 rises, inspect cache hit ratio and response assembly, not Kafka first.

## Takeaways and Reading

- Trending systems are derived-data systems: posts are source of truth, ranks are disposable but audited snapshots.
- Use velocity, uniqueness, recency, and abuse resistance; raw count alone is not a trend.
- Count-min sketches reduce memory but need candidate top-K structures and error-aware ranking.
- Normalized hashtag keys create hot partitions; salting and two-stage aggregation protect the stream.
- Geo trends require privacy thresholds, confidence, language context, and scoped policy overrides.
- Consistency is a product contract: publish cadence, cache TTL, hysteresis, override version, and safe stale serving.
- Astroturf defense belongs in the ranking path and must preserve audit evidence for review.

### Targeted reading

- Review Week 6 Kafka modules for partitioning, consumer lag, replay, and idempotency.
- Review Week 9 Twitter Feed for fan-out, hot keys, and celebrity/event load patterns.
- Review count-min sketch and heavy-hitter algorithms such as SpaceSaving or lossy counting.
- Review Trust and Safety incident playbooks for demotion, hide, annotation, and appeal workflows.
- Read Northstar Commerce notes in `Ops-Sims/fictional-company/NORTHSTAR.md` for shared systems and recurring failure themes.
## Design Gates (mandatory)

Answer these before calling the design complete. Keep the learner notes concise; compare against the answer key only after attempting the gates.
> Model responses: [`../answers/Week-09-Feed-and-Chat-Designs/Design Trending Hashtags Answers.md`](../answers/Week-09-Feed-and-Chat-Designs/Design%20Trending%20Hashtags%20Answers.md)

### Gate 1 - Authn/z trust boundary

1. Who is authenticated in this design: poster, reader, moderator, admin, service, worker, tenant, or partner?
2. Where does the first untrusted write enter the trusted control plane?
3. Which component makes the final authorization decision for counting, displaying, hiding, or moderating a hashtag?
4. What identity artifact is accepted: session cookie, bearer token, API key, mTLS identity, signed event, or job identity?
5. What fails closed when auth, policy, or trust bundle is unavailable?

### Gate 2 - Abuse and misuse

6. Which actor can create the largest amplification while still looking like normal social activity?
7. Which endpoint, stream processor, or backfill can be abused after authentication succeeds?
8. What per-user, per-tag, per-geo, per-IP, per-device, per-tenant, per-partition, and global quotas are required?
9. Which telemetry distinguishes organic trend emergence from coordinated astroturfing?
10. Which retry or replay policy can amplify a partial outage into a global trend outage?

### Gate 3 - Multi-tenant isolation

11. What is the tenancy or isolation model for users, regions, languages, advertisers, moderation queues, stream topics, caches, and reports?
12. Where is tenant/context required, and how is it propagated through Kafka events, stream state, support tools, and exports?
13. Which shared resource has reserved capacity or fair-share limits per region, language, tag, or internal tenant?
14. How can one tag, geo, tenant, or campaign be throttled, hidden, migrated, or isolated without affecting others?
15. What test proves one tenant/context cannot read private trend signals through cache, search, export, or logs?

### Gate 4 - Unit cost at target scale

16. What is the business unit for cost: post, hashtag mention, stream event, window update, top-K merge, trend read, or report row?
17. At the stated target scale and peak multiplier, what is the rough unit cost driver?
18. Which line items dominate: Kafka, stream processing CPU, state store memory, cache, storage, observability, moderation, or replay headroom?
19. What cost metric pages before budget or SLO error budget is breached?
20. What graceful degradation lowers cost without corrupting rank correctness or safety policy?

### Gate 5 - Failure blast radius

21. What is the smallest unit that can fail independently: tag, partition, shard, window, geo, language, cell, topic, worker pool, cache key, or queue?
22. Which dependencies are shared between critical ranking and optional analytics or ads paths?
23. What fails closed, what serves stale, and what can be disabled first?
24. Which runbook action could accidentally widen blast radius?
25. What game day proves the blast radius stays inside the intended boundary?

## Ops Sim: Astroturfed Hashtag During Northstar Live Auction

**Time box:** 35 minutes
**Severity:** P1
**Service / domain:** Social trends, stream processing, abuse defense, cache serving
**Northstar system (if any):** Northstar Commerce feed, live auctions, abuse defense, MSK/Kafka

### Rules

1. Answer from memory of the teaching section; do not re-read mid-drill.
2. Write decisions in order from T+0 through T+60.
3. Name evidence for every claim: metric, log line, config key, trace, or capacity check.
4. Do not open `answers/` until finished.

### 1. Scenario stem

```text
WHAT USERS SEE:
  The hashtag #NorthstarWalletHack appears as the number 1 global trend and number 1 in three regions.
  Clicking it shows many near-identical posts from new accounts and a few legitimate support questions.
  The live auction page is healthy, but customer support volume spikes because users think wallets are compromised.

WHAT ON-CALL SEES:
  `trend_rank_volatility` fired globally.
  `kafka_consumer_lag_hashtag_counts` fired for partition 11 and partition 37.
  Abuse defense says a new risk model was deployed 20 minutes ago with canary green on CPU and p99.

BUSINESS CONSTRAINT:
  The live auction has 800k concurrent users; suppressing all trends removes a major discovery surface.
  Incorrectly hiding real security reports would be a trust and safety failure.
```

### 2. Telemetry pack

```text
METRICS:
  hashtag_events_qps: 410k global, 7.5x normal
  top tag #NorthstarWalletHack: raw_mentions_5m=1.8M, unique_authors_5m=41k, new_account_author_ratio=82%
  organic comparator #AuctionFinale: raw_mentions_5m=1.1M, unique_authors_5m=390k, new_account_author_ratio=7%
  tag_rank_volatility: global p95 rank_delta_per_min=37, baseline=4
  cms_error_bound_epsilon: configured=0.02, observed heavy-hitter error for partition 11=7.8%
  stream_lag_seconds: partition 11=480, partition 37=390, median_partition=12
  topk_merge_p99_ms: 340, baseline=44
  trend_cache_hit_ratio: 91%, baseline=96%
  moderation_queue_depth: 1.2M, baseline=80k
  abuse_model_suppress_rate: 0.4%, baseline=6.5%
  wallet-api auth failures: normal; checkout and bid websocket SLOs healthy

LOG LINES:
  WARN hot_partition topic=hashtag_mentions partition=11 key=#NorthstarWalletHack lag=480s bytes_in=220MBps
  WARN trend_publish tag=#NorthstarWalletHack geo=global rank=1 confidence=0.31 abuse_score=0.12 version=rank-v29
  INFO abuse_model model=astroturf-v8 threshold=0.98 suppress_rate=0.004 canary=green
  WARN duplicate_text_cluster cluster=cl-901 tag=#NorthstarWalletHack posts=720k accounts=29k similarity=0.94
  INFO cache_publish trend_set=global window=5m rank_version=rank-v29 cache_ttl=300s
  ERROR topk_merge timeout geo=global source_partition=11 elapsed_ms=750

TRACES / LAG / EXPLAIN:
  Kafka keying explain: hashtag_mentions key = normalized_tag
  Flink operator hashtag-counts checkpoint duration: 165s, baseline=18s
  State store top keys: #NorthstarWalletHack 39%, #AuctionFinale 14%, #WalletHack 6%
  Rank publish trace global: count_update 482ms, topk_merge 751ms, abuse_adjust 9ms, cache_write 18ms
```

### 3. Config pack (one line is wrong or dangerous)

```yaml
hashtag_stream:
  kafka_key: normalized_tag  # suspicious under hot-tag traffic
  partitions: 96
  max_event_lateness_seconds: 120
  checkpoint_interval_seconds: 30
sketches:
  count_min_epsilon: 0.02
  count_min_delta: 0.001
  topk_per_partition: 200
ranking:
  publish_interval_seconds: 30
  trend_cache_ttl_seconds: 300  # suspicious during attack volatility
  abuse_threshold: 0.98  # suspicious after model rollout
  min_unique_authors_5m: 5000
  rank_score: growth_rate * log(unique_authors) * geo_weight - abuse_penalty
moderation:
  emergency_hide_tag: true
  emergency_demote_tag: true
  regional_only_override: true
```

### 4. Timeline and decision points

| Time | Event | Your move (write before reading further) |
|---|---|---|
| T+0 | Trend volatility and hot-partition alerts fire; hashtag is rank 1 global. | |
| T+5 | Trust and Safety asks whether to hide the tag globally. | |
| T+15 | Stream lag grows, and cache still serves rank 1 because TTL is 300 seconds. | |
| T+60 | Attack slows, but legitimate support posts are mixed with astroturf content. | |

### 5. Questions

**Q1 - Layer and root cause:** Which layer owns the primary symptom? What is the mechanism?
**Q2 - Evidence:** Which 5 signals distinguish astroturf from organic trend growth, and which signal is a red herring?
**Q3 - Sequencing:** What do you do in the first 15 minutes? What do you explicitly not do yet?
**Q4 - Bad fix gallery:** Why is hiding all trends dangerous? Why is adding Kafka partitions alone incomplete?
**Q5 - Capacity and blast radius:** Estimate the hot partition skew and identify the smallest safe blast-radius boundary.
**Q6 - Durable fix:** Which keying, sketch, top-K, cache, abuse, and game-day changes prevent recurrence?
**Q7 - Org/runbook:** Who is informed by T+10, and what is pre-authorized for trend on-call versus Trust and Safety?
**Q8 - Reconciliation:** After mitigation, how do you backfill ranks, preserve audit evidence, and avoid suppressing legitimate wallet reports?

### 6. Self-score after answer key

| Error type | Did it happen? | Note |
|---|---|---|
| Knowledge gap | | |
| Wrong layer | | |
| Sequencing error | | |
| Capacity miss | | |
| Abuse miss | | |
| Org or runbook miss | | |
| Careless slip | | |

**Pass:** correct layer, safe abuse-aware sequencing, one hot-partition calculation, and a rejected bad fix.

