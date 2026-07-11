# Answer Key - Week-10

> Open only after attempting `Retention-Tests/Week-10.md`.

---

## Part 1: Rapid-Fire Model Answers

**Q1:** Presigned multipart uploads keep huge video bytes off app servers, reduce bandwidth and memory pressure, and let S3 handle retries/parallel parts. The API stays a control plane for auth, metadata, and upload session state.

**Q2:** The source video must be durably accepted before slow transcode work begins. The user-visible state should be "uploaded/processing" with source preserved, progress/status, and no promise that all renditions are ready.

**Q3:** A manifest lists available renditions and segment URLs; segments are the actual media chunks. Manifests need short TTLs so new renditions/live edges appear; immutable versioned segments should have long TTLs.

**Q4:** S3/origin becomes the bottleneck because more segment requests miss the edge and hit origin. For video, a hit-ratio collapse multiplies origin requests and egress while users immediately see buffering, so it is usually P1.

**Q5:** A radius crosses geohash/H3 boundaries. Querying only one cell misses nearby drivers in adjacent cells; the fix is query neighbor cells/covering cells and exact-distance filter.

**Q6:** Serial closest-driver dispatch waits for one driver to decline or time out before trying the next. Batch dispatch offers to several qualified drivers and accepts the first response, reducing matching loops and rider wait.

**Q7:** A hot video would lock and update one row thousands of times per second. Kafka/Flink aggregate events asynchronously, dedupe viewers, and write compacted counts without putting the watch path on the database write lock.

**Q8:** Cache video metadata in app/local cache and Redis, prewarm viral entries, and use versioned invalidation on metadata update. The watch page should use cache-aside with short TTL or explicit bust for title/status changes.

**Q9:** Keep source upload durable, then throttle transcode starts by creator, account tier, and queue priority. Apply upload quotas, transcode budgets, and priority queues; do not delete source video just because transcode is delayed.

**Q10:** CDN segment hit ratio, origin 5xx/first-byte latency, player rebuffer ratio, ABR downshift rate, segment retry rate, and Origin Shield hit ratio are leading indicators.

**Q11:** Origin Shield is a regional mid-tier cache that collapses misses from many edge POPs into fewer origin requests. It protects S3/custom origin during viral traffic and improves cache fill efficiency.

**Q12:** HTTP/2 multiplexes many streams over one TCP connection. Packet loss blocks delivery of later bytes for all streams on that connection, so unrelated manifest/API streams can be delayed together.

**Q13:** Dispatch can often tolerate slightly stale locations to preserve availability and then correct with driver accept/decline. Payment state is money correctness; stale captures/refunds can double-charge or lose funds.

**Q14:** Use signed URLs/cookies that authorize path/time/customer while keeping the object path cacheable across authorized viewers where possible. Avoid embedding user-specific random tokens in the cache key unless necessary.

**Q15:** `3M * 600 / 3600 = 500,000` segment requests/sec. That is CDN scale; origin must see only a small miss fraction.

---

## Part 2: Compound Scenario - Expert Analysis

### Playback Root Cause Cascade

The CDN deploy changed `.m4s` segment TTL from 86400 to 60 and disabled Origin Shield for `/hls/*`. Segments are immutable and should be cached for a long time. Short TTL plus no shield caused many edge POPs to revalidate/refetch the same hot segments, dropping segment hit ratio from 94% to 61% and shield hit ratio from 88% to 41%. S3 then saw an 11x prefix request spike, `SlowDown` 503s, and p99 first-byte latency of 2.9s. Players retried fixed 250ms loops, increasing request pressure and buffering.

### Why Manifest TTL Matters

The manifest TTL stayed short and roughly healthy, which means the deploy did not break player discovery of renditions. The bad change targeted media segments, the high-volume objects that must be long-lived at edge. If manifests were stale, users might be stuck on old rendition lists; here the issue is segment fetch pressure.

### T+0 Decision

Immediately roll back `/hls/*.m4s` TTL to long-lived immutable caching and re-enable Origin Shield. If rollback propagation is slow, add emergency cache policy for the viral replay path and consider stale-if-error for immutable segments. The first metric that must move is segment hit ratio/Origin Shield hit ratio; origin 503s should follow.

### T+5 Decision

While warming, shed or reroute noncritical origin pressure: reduce player retry aggressiveness via config if possible, disable autoplay/previews, route hot replay to secondary CDN if object paths are compatible, and temporarily cap lower-priority replay resolutions. Do not shed live bid/checkout traffic. Protect origin by prioritizing hot immutable segment cache fill and by avoiding CDN purge.

### T+15 Decision

Playback root cause is CDN/origin. Transcode queue is harmful to creators but not causal for already-published replay playback unless renditions are missing. View-count lag is correlated with viral traffic and Kafka/Flink overload; it affects displayed counts, not segment delivery. Priority remains playback/origin first, then count reconciliation and transcode queue triage.

### T+60 Recovery

- Confirm hit ratio, origin 503s, and rebuffer ratio are back in SLO.
- Backfill view counts from Kafka retained events or raw logs; recompute unique views with the normal dedupe window.
- Mark displayed counts as delayed if needed; do not invent counts.
- Reprioritize transcode queue: premium/live/replay first, long-tail later.
- For courier dispatch, lower stale-location max age, expand H3 neighbor search, split hot cells, and switch batch dispatch size from 1 to 3 where supply permits.

### View-Count Drop Explanation

The observed count dropped because `view-events` lag rose to 1,900 seconds and dedupe drop rate spiked. The watch path still emitted events; they are delayed or being over-deduped due to late/out-of-order processing windows. The correct claim is "displayed counts are stale/underreported," not "views were lost," until retention/log audit proves loss.

### Bad-Fix Gallery

| Bad fix | Failure mode |
|---------|--------------|
| Purge all CDN objects | Forces a global cold-cache stampede into S3 and worsens origin 503s |
| Scale app servers | The bottleneck is CDN/origin for media segments, not watch API CPU |
| Raise player retries to 20 | Multiplies origin load and synchronized retry pressure |
| Prioritize every transcode job | Priority queues stop working; concurrency is still capped at 500 |
| Set driver location max age to 30 min | Reduces dispatch misses but sends riders to ghost/stale drivers |

### Capacity Answer

Segment load: `3,000,000 viewers * 600 segments/hour / 3600 = 500,000 segment requests/sec`.

At 94% hit ratio, origin sees 6% misses: `500,000 * 0.06 = 30,000 origin req/sec`.

At 61% hit ratio, origin sees 39% misses: `500,000 * 0.39 = 195,000 origin req/sec`.

Extra origin load is about `165,000 req/sec`, a 6.5x increase over the healthy-origin load. That explains S3 `SlowDown`, first-byte latency, and buffering.

### Org/Runbook Controls

- CDN config deploys require canary distribution and automated diff lint: long TTL for immutable segments, short TTL for manifests.
- Origin Shield cannot be disabled for video paths without video SRE approval.
- Dashboards must show hit ratio by path pattern, shield hit ratio, origin 5xx, and rebuffer ratio.
- Transcode queues need per-creator budgets, priority classes, and cost alerts.
- Dispatch needs hot-cell detection, neighbor-cell query validation, stale-location max-age alarms, and batch dispatch defaults.

---

## Scoring Guide - 85% Gate

| Area | Points |
|------|--------|
| Rapid-fire correctness | 30 |
| CDN/root-cause chain | 20 |
| Timed decisions and prioritization | 15 |
| View-count/transcode separation | 10 |
| Bad-fix analysis | 10 |
| Capacity math | 10 |
| Org/runbook controls | 5 |

Pass gate: **85%+**. A critical failure is blaming transcode or app servers as the primary playback root cause while ignoring segment TTL and Origin Shield.
