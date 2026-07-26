# Answer Key - Design Trending Hashtags

> Open only after attempting the learner file questions.

A strong answer treats trending hashtags as derived, approximate, abuse-sensitive state built from durable post events.
It protects policy and safety overrides more strongly than ordinary rank freshness.

## Principal Model Answer - What Excellent Looks Like

1. Separates post/chat durability from hashtag extraction and derived rank state.
2. Uses event-time windows, watermarks, corrections, and publish snapshots with versions.
3. Uses approximate counting for long-tail tags and candidate top-K structures for heavy hitters.
4. Plans for hot partitions with salted two-stage aggregation rather than only adding partitions.
5. Ranks with velocity, unique authors, geo/language context, hysteresis, and abuse penalties.
6. Defines geo and global merge carefully enough not to lose tags spread across regions.
7. Treats abuse and moderation as ranking gates with audit, not downstream cleanup.
8. Serves cached snapshots and enforces emergency override versions on read or publish.
9. Calculates mention QPS, Kafka bytes/sec, hot partition skew, sketch memory, and merge cost.
10. Sequences incident response by preserving safety and user trust before perfect analytics repair.
11. Scopes kill switches by tag, geo, language, model version, worker pool, or cache key.
12. Names what remains working when trends degrade: feed posting, chat, checkout, bidding, and previous safe trends.

## Ops Sim Model Answer - Astroturfed Hashtag During Northstar Live Auction

### Root cause chain

1. The primary symptom is manipulated trend ranking plus hot stream partitions, not wallet API or checkout failure.
2. The hashtag is keyed by normalized_tag, so the attack concentrates traffic on partition 11 and related hot keys.
3. New-account author ratio of 82 percent versus 7 percent comparator is strong astroturf evidence.
4. Unique authors are low relative to raw mentions: 41k authors for 1.8M mentions indicates repetition and coordination.
5. Duplicate text cluster of 720k posts with 0.94 similarity confirms coordinated content.
6. Abuse model suppress rate fell from 6.5 percent to 0.4 percent after model/threshold rollout; canary missed semantic safety.
7. Trend cache TTL of 300 seconds keeps a bad rank visible even after processors or humans react.
8. Wallet auth failures and checkout/bid health are red herrings for ranking root cause, but they matter for comms because users are alarmed.

### First 15 minutes

1. Open P1 with trends as primary, Trust and Safety plus security/support/comms as required stakeholders.
2. Apply scoped demotion, hide, or annotation for #NorthstarWalletHack based on T&S policy, not a global trends shutdown.
3. Shorten or invalidate the specific trend cache key and ensure override version is checked before serving.
4. Roll back or lower-risk configure the abuse model threshold from 0.98 if T&S approves and canary evidence supports it.
5. Enable hot-tag salting or route the tag to a dedicated hot-key aggregation path if available.
6. Reduce publish cadence or merge depth only if needed to protect processors, while preserving emergency override propagation.
7. Protect feed/chat/checkout by stopping any trend backfills or expensive analytics sharing live resources.
8. Preserve raw events, duplicate cluster evidence, and rank snapshots for audit and post-incident review.
9. Do not hide all trends unless manipulation is widespread and scoped controls cannot protect users.
10. Do not add Kafka partitions alone and expect relief while the key remains normalized_tag.

### Capacity and skew calculation

- Global hashtag event QPS is 410k.
- The top tag has 1.8M mentions over 5 minutes, or 6k mentions/sec average for that tag in the observed 5-minute window.
- The partition bytes metric says partition 11 receives 220 MB/sec, far above uniform partition average, implying other traffic or larger enriched events also concentrate there.
- Uniform QPS over 96 partitions would be about 4.3k mentions/sec per partition.
- Any one partition lagging 480 seconds while median is 12 seconds indicates key skew, not global broker shortage alone.
- If a future hot tag reaches 100k/sec and safe per-subkey target is 5k/sec, salting factor should be at least 20 plus headroom.
- Cache TTL of 300 seconds means an unsafe rank can remain visible for five minutes unless emergency override bypasses TTL.
- Top-K merge p99 of 340 ms indicates merge/rank publish is overloaded; emergency hide should not depend on waiting for normal publish.

### Bad fixes to reject

- Hide all trends: removes a major discovery surface and can suppress legitimate support or safety information.
- Add Kafka partitions only: normalized_tag still maps the hot tag to one key unless salting/repartitioning changes.
- Globally lower abuse threshold without review: risks false positives against real events and protected speech.
- Replay the whole stream during peak: can worsen lag and rewrite ranks before live path is stable.
- Delete raw astroturf evidence: destroys audit and abuse investigation data.
- Trust CPU/p99 canary only: abuse model can be operationally healthy and semantically wrong.

### Durable prevention

- Change keying to two-stage aggregation: distribute raw mentions by post_id or salted tag, then merge by tag/window.
- Add hot-tag registry with deterministic salting, expiry, replay compatibility, and runbook ownership.
- Use rank score that includes unique authors, new-account ratio, duplicate text clusters, graph spread, and abuse penalty.
- Audit and canary abuse model changes with semantic fixtures, not only CPU and p99.
- Set shorter TTL or emergency overlay for high-volatility trends; hidden tags must bypass ordinary stale cache.
- Publish rank snapshots with input offsets, model version, threshold, override version, and confidence.
- Use isolated backfill worker pools and state namespaces for parser/model corrections.
- Acceptance tests: hot tag does not stall ordinary tags; emergency hide propagates under TTL; astroturf fixture is demoted; organic crisis fixture is not silently hidden.

## Design Gates - Principal-Depth Model Responses

### Gate 1 - Authn/z trust boundary

1. Principals include posters, readers, moderators, support/admin users, feed/chat services, extractors, stream processors, rank publishers, cache services, and analytics consumers.
2. Untrusted writes enter at feed/chat APIs; trends consume only accepted post events and signed moderation/control events.
3. Feed/chat authorizes post creation; Trust and Safety authorizes hide/demote/annotate; trend publisher authorizes rank publish; cache/API enforces override version.
4. Identity artifacts include user session, service mTLS identity, job identity, moderation/admin token, and signed control-plane event.
5. Protected/private posts, hidden tags, and moderation overrides fail closed when policy state is unavailable.
6. Public trend reads can serve previous safe snapshots if policy version is current.
7. Admin/support actions require scoped reason, expiry, and immutable audit.
8. Stream workers carry job identity and source offsets for replay audit.
9. Trend cache never overrides author privacy or tag hide policy.
10. A good answer draws auth and policy before sketches and Kafka partitions.

### Gate 2 - Abuse and misuse

1. Highest amplification actors are bot/new-account clusters, coordinated duplicate-text campaigns, hot tags, and replay/backfill jobs.
2. Abusable surfaces include post creation, chat messages, hashtag parser edge cases, rank publish, moderation override misuse, and analytics export.
3. Quota dimensions include user, device, IP/ASN, tag, text cluster, geo, language, source surface, partition, model version, and replay job.
4. Organic trends show high unique author diversity, graph spread, varied text, and plausible geo/language distribution.
5. Astroturf shows new-account concentration, synchronized bursts, duplicate text, low graph diversity, and suspicious referral/client patterns.
6. Retries and replays need deterministic ids and output rate limits to avoid count inflation.
7. Abuse controls must preserve evidence and support appeal/review paths.
8. Controls include demotion, hide, annotation, review hold, source throttling, and cluster suppression.
9. A weak answer says 'use ML'; a strong answer names features, thresholds, false positives, and audit.
10. Safety actions should be scoped by tag/geo/language when possible.

### Gate 3 - Multi-tenant isolation

1. Tenancy is contextual: user communities, geos, languages, advertisers/promoted trends, moderation queues, internal analytics consumers, and Northstar seller tenants.
2. Context propagates as region, language, source surface, visibility, policy scope, tenant, request_id, and rank_version.
3. Shared resources need fair share: Kafka partitions, stream workers, state store, top-K merge CPU, cache keys, moderation queue, analytics exports.
4. One tag or geo can be hidden, demoted, salted, moved to a dedicated worker pool, or removed from a surface without global outage.
5. Promoted trends must be labeled and separated from organic rank cache and audit.
6. Seller analytics receives aggregate trend reports only, not user-level evidence or other tenants' private context.
7. Support tools filter by policy scope and log all reads.
8. Backfills use isolated namespaces and byte budgets.
9. Isolation test: hidden tag cannot leak through global cache, regional cache, search suggestion, export, or support replay.
10. Missing context is a policy error, not default global visibility.

### Gate 4 - Unit cost at target scale

1. Business units are hashtag mention, window update, sketch update, top-K merge, rank publish, trend read, moderation item, and replayed event.
2. At 400k mentions/sec and 700 bytes/event, stream ingestion is hundreds of MB/sec before replication.
3. Dominant costs are Kafka broker IO, stream CPU, state store memory/checkpoints, cache read QPS, observability, and replay headroom.
4. Sketch memory is bounded by epsilon/depth but multiplied by windows, geos, languages, and shards.
5. Top-K cost depends on candidate depth per partition and publish frequency.
6. Observability can become expensive if raw tag labels are unbounded in metrics.
7. Track cost per million mentions, per rank publish, per replayed hour, per moderation item, and per trend read.
8. Graceful cost reductions: lower publish frequency, reduce candidate depth, disable personalization/snippets, sample debug logs, defer analytics backfill.
9. Do not reduce cost by weakening hide policy, privacy thresholds, or evidence retention.
10. A good answer can estimate mention QPS and explain why cache reads are cheap compared with stream state.

### Gate 5 - Failure blast radius

1. Smallest intended boundaries are tag, tag family, partition, salt group, geo, language, surface, model version, worker pool, cache key, and replay job.
2. Shared dependencies include Kafka, stream state store, top-K merger, trend cache, moderation override service, and observability pipeline.
3. Fail closed: hidden tags, private/protected posts, moderation overrides, admin actions, small-cohort privacy thresholds.
4. Serve stale: previous safe trend list, regional list if global merge lags, rank movement, historical charts.
5. Disable first: personalized trends, explanatory snippets, promoted modules, analytics backfill, deep graph features, one tag/surface.
6. Runbook hazards: global trend shutdown, global cache flush, unbounded replay, repartition during peak, and deleting evidence.
7. Bulkheads separate live stream processing from backfills, analytics, ads/promoted trends, and support exports.
8. Game day combines hot tag, abuse threshold regression, stale cache TTL, moderation backlog, and isolated replay.
9. Alerts should fire on partition lag, rank volatility, abuse suppress-rate shift, override latency, and cache policy version mismatch.
10. A good answer says what remains working: posting, chat, checkout, bidding, safe cached trends, and scoped moderation.

## Scenario Variants for Self-Review

### Variant A - Organic breaking news hot partition

1. Raw mentions and unique authors both spike with diverse text and old accounts.
2. Correct action is hot-key salting and capacity protection, not abuse suppression.
3. Durable fix is proactive hot-tag registry and dedicated worker pool.
4. Risk is stale ranks, not manipulation.

### Variant B - Parser normalization bug

1. A deploy splits #NorthstarSale into #northstarsale and #northstar-sale variants.
2. Correct action is rollback parser, stop live publish for affected tags, and replay correction in isolated namespace.
3. Do not merge variants by manual cache edit only; source events and audit need repair.
4. Acceptance test uses known hashtag aliases and edit/delete corrections.

### Variant C - False positive safety suppression

1. A legitimate regional emergency tag is hidden because new accounts are common in that region.
2. Correct action is T&S review, regional restore/annotation, and model threshold scope rollback.
3. Do not globally disable abuse model without checking known abusive fixtures.
4. Postmortem should add regional fixtures and false-positive dashboards.

### Variant D - Backfill overload

1. A historical replay shares live state store and checkpoint bandwidth.
2. Correct action is pause/reduce replay and protect live rank publish.
3. Durable fix is separate backfill namespaces, rate limits, and admission control.
4. Analytics correctness can lag; live safe ranks are higher priority.

### Variant E - Cache stale after override

1. T&S hides a tag but feed still shows it for three minutes.
2. Correct action is emergency overlay or scoped invalidation with policy version check.
3. Durable fix is cache entries carrying override version and hide bypassing ordinary TTL.
4. Do not flush all feed caches unless scoped invalidation is unavailable and risk justifies it.

## Minimum Whiteboard Capacity Answer

1. Peak mentions = posts/sec * tagged_post_ratio * hashtags_per_tagged_post.
2. With 250k posts/sec, 45 percent tagged, and 1.6 tags/tagged post, mentions are 180k/sec.
3. Design headroom uses 400k mentions/sec for coordinated events and spam.
4. At 700 bytes/event, 400k/sec is 280 MB/sec before replication.
5. With RF=3, broker write load is about 840 MB/sec before compression.
6. Uniform load across 96 partitions is about 4.2k mentions/sec per partition.
7. If one tag takes 25 percent of traffic, it creates 100k mentions/sec on one key when keyed by normalized_tag.
8. If target subkey load is 5k/sec, salted aggregation needs at least 20 salts plus headroom.
9. A five-minute window at 400k/sec contains 120M events.
10. Cache reads should serve trend lists in under 80 ms and never query Kafka or stream state.

## Evaluator Rubric and Red Flags

- Pass: separates source post events from derived trend state.
- Pass: defines windows, watermarks, sketches, top-K merge, and publish snapshots.
- Pass: calculates mention QPS, hot partition skew, and salting factor.
- Pass: treats abuse features and moderation overrides as ranking gates.
- Pass: scopes mitigation to tag/geo/model/cache before global shutdown.
- Pass: distinguishes stale safe ranks from unsafe hidden-tag cache.
- Red flag: highest raw count equals trend rank.
- Red flag: a single Redis counter per tag/window.
- Red flag: adding partitions without changing hot key distribution.
- Red flag: no duplicate, delete, edit, or moderation correction path.
- Red flag: global hide or global cache flush as the first move.
- Red flag: ML abuse answer without features, false positives, audit, or T&S ownership.

## Additional Verification Checklist

1. Verify extraction emits deterministic ids for increment and correction events.
2. Verify stream lag dashboard shows partition, tag, geo, and operator skew.
3. Verify hot-tag salting has deterministic merge and replay compatibility.
4. Verify sketch error bounds are visible to ranker and canaries.
5. Verify partition top-K depth is enough for global broad-tag recall.
6. Verify unique author estimates and duplicate text clusters feed rank score.
7. Verify abuse model rollout canary includes semantic fixtures, not only CPU and p99.
8. Verify override service can hide/demote/annotate by tag, geo, language, and surface.
9. Verify trend cache entries carry rank_version and override_version.
10. Verify hidden tags bypass ordinary cache TTL.
11. Verify trend API can serve previous safe snapshot if stream publish lags.
12. Verify raw tag labels are bounded or sampled in metrics to avoid cardinality blowup.
13. Verify replay jobs use isolated topics/state and output budgets.
14. Verify support/admin tools audit reason, owner, scope, and expiry.
15. Verify privacy thresholds prevent small-cohort geo trend leaks.
16. Verify promoted trends are labeled and isolated from organic rank cache.
17. Verify feed, chat, checkout, and bid WebSocket SLOs are protected from trend load.
18. Verify post-deletion and moderation corrections update active windows or safety overlays.
19. Verify rank divergence by region is measured against the product contract.
20. Verify game days cover organic hot tag, astroturf tag, model false positive, stale cache, and replay overload.
