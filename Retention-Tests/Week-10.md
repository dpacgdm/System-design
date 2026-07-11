# WEEK 10 RETENTION TEST

Covers **Weeks 1-10** with emphasis on YouTube, Uber, and global video outage operations.

---

## Rules

```text
RULES OF ENGAGEMENT

1. Answer from memory. Do not open answer keys or design modules.
2. Rapid-fire answers: 2-4 sentences each.
3. Compound Ops Sim: write as the incident lead with evidence and trade-offs.
4. Mark uncertainty honestly; do not bluff.
5. Open the answer key only after attempting all sections.
```

---

## Part 1: Rapid-Fire Concept Recall (15 Questions)

**Q1 (Current - YouTube upload):** Why should a video upload API issue presigned multipart S3 URLs instead of proxying large uploads through application servers?

**Q2 (Current - YouTube transcoding):** Why is transcoding asynchronous after durable upload acknowledgement? What user-visible state should exist before transcode finishes?

**Q3 (Current - HLS/DASH):** Explain the difference between a manifest and a media segment. Which should have a short TTL and which should have a long TTL?

**Q4 (Current - video CDN):** CloudFront segment hit ratio drops from 94% to 62%. What downstream system becomes the bottleneck, and why is this usually a P1 for video?

**Q5 (Current - Uber geospatial):** Why is querying only the rider's current geohash cell wrong for driver matching near cell boundaries?

**Q6 (Current - Uber dispatch):** Compare serial closest-driver dispatch with batch dispatch to the top three drivers. What failure mode does batch dispatch reduce?

**Q7 (Mid - Kafka):** View-count aggregation uses Kafka and Flink. Why should the watch page not synchronously increment a single SQL row per view?

**Q8 (Mid - caching):** A viral video's metadata row melts Aurora replicas. What cache layers and invalidation rules protect the database?

**Q9 (Mid - rate limits/cost):** A creator uploads 2,000 long videos in an hour. What limits protect transcode cost without losing already-uploaded source videos?

**Q10 (Mid - observability):** Name three leading indicators for video delivery before users report buffering.

**Q11 (Old - CDN):** What does Origin Shield do in a multi-POP CDN architecture?

**Q12 (Old - TCP/HTTP):** Why can HTTP/2 over one TCP connection amplify packet-loss head-of-line blocking for video manifest/API calls?

**Q13 (Old - CAP/replication):** For trip dispatch, why is stale driver location sometimes better than rejecting all matches during a brief partition, but stale payment state is not?

**Q14 (Old - auth/tenancy):** How should signed video URLs or cookies limit unauthorized sharing while preserving CDN cacheability?

**Q15 (Old - capacity):** If each viewer downloads 600 segments/hour and a live event has 3M concurrent viewers, what order of magnitude of CDN requests/sec must the system absorb?

---

## Part 2: Compound Ops Sim - Global Video Outage at Northstar

Northstar Commerce adds creator videos to seller pages and live auction replays.

```text
INCIDENT REPORT

Severity: P1
Systems:
  - video-watch-api
  - CloudFront distributions for HLS/DASH
  - S3 origin buckets: video-origin-use1, video-origin-aps1
  - transcode-orchestrator + MediaConvert
  - view-events Kafka + Flink aggregators
  - ride-style courier dispatch experiment using H3 cells for same-day pickup

Business event:
  Celebrity auction replay goes viral globally while a same-day courier
  pilot is running in NYC and London.

Timeline:
  20:30 - CDN config deploy.
  20:37 - Player buffering ratio crosses 18% in India and EU.
  20:41 - S3 origin GET 503s appear.
  20:44 - View counts on the viral replay drop by 35%.
  20:50 - Creator uploads stuck in "Processing".
  21:02 - Courier dispatch ETA p99 doubles in NYC.
```

### Telemetry Pack

```text
CloudFront:
  segment_hit_ratio: 94% -> 61%
  manifest_hit_ratio: 73% -> 76%
  origin_shield_hit_ratio: 88% -> 41%
  edge_5xx_rate: 0.03% -> 1.8%
  top path: /hls/replay_991/720p/seg*.m4s

S3 origin:
  GET 503 SlowDown: 0 -> 0.7%
  first_byte_latency_p99: 80ms -> 2.9s
  request_rate on prefix replay_991/720p/: 11x normal

Deploy diff:
  path pattern *.m4s TTL: 86400 -> 60
  path pattern master.m3u8 TTL: 15 unchanged
  Origin Shield region: Singapore -> disabled for /hls/*
  signed URL expiry: 6h unchanged

Transcode:
  queue_depth: 1,100 -> 19,400
  job_age_p99: 18 min -> 4.6 h
  MediaConvert account concurrency: 500/500
  source upload success: normal

Kafka/Flink view counts:
  view-events ingress: +4x
  consumer_lag_seconds: 25 -> 1,900
  unique_view_dedupe_drop_rate: 3% -> 31%
  redis view_count cache TTL: 5s

Courier dispatch:
  H3 cell nyc_res7_8a2a hot: 68k drivers/riders events/min
  Redis GEO CPU: 92%
  GPS update topic lag: 7 min
  dispatch uses last known location up to 10 min old
```

### Config Pack

```text
CloudFront:
  /hls/*.m3u8: minTTL=5 defaultTTL=15 maxTTL=60
  /hls/*.m4s: minTTL=0 defaultTTL=60 maxTTL=60
  stale-if-error: disabled
  origin shield: disabled on /hls/*

Player:
  ABR buffer target: 20s VOD, 6s live
  retry segment: 3 attempts, fixed 250ms

Transcode:
  priority: premium creators > auction replays > long-tail uploads
  no per-creator hourly transcode budget

Dispatch:
  geospatial index: Redis GEO plus H3 routing key
  stale location max age: 10 min
  batch dispatch size: 1
```

### Decision Points

**T+0:** What do you roll back or change immediately, and what metric must move first?

**T+5:** Origin 503s are still high. Which traffic do you shed or reroute while the CDN warms?

**T+15:** Transcode queue and view-count lag are also bad. Which is causal for playback, which is correlated, and how do you prioritize?

**T+60:** Playback is stable but counts and courier ETAs are wrong. What reconciliation and follow-up plan do you run?

### Scenario Questions

1. Identify the root-cause cascade for playback.
2. Explain why the manifest TTL remaining unchanged matters.
3. Explain the view-count drop without claiming views were actually lost.
4. **Bad-fix gallery:** Analyze (a) purge all CDN objects, (b) scale app servers, (c) raise player retries to 20, (d) prioritize every transcode job, (e) set driver location max age to 30 min.
5. **Capacity question:** Estimate segment request load for 3M concurrent viewers at 600 segments/hour and the extra origin load at 61% vs 94% hit ratio.
6. **Org/runbook question:** What controls belong around CDN config deploys, origin shielding, transcode budgets, and H3 hot-cell dispatch?

---

## Self-Score Error-Type Table

| Error type | Count | Notes to review |
|------------|-------|-----------------|
| HLS/DASH TTL misunderstanding | | |
| CDN/origin cascade miss | | |
| Kafka/view-count reasoning error | | |
| Transcode priority/cost error | | |
| Geospatial boundary/staleness error | | |
| Incident priority error | | |
| Capacity math error | | |
| Runbook/ownership gap | | |

---

> **Answer key (do not open until you attempt the test):**  
> [`../answers/Retention-Tests/Week-10 Answers.md`](../answers/Retention-Tests/Week-10%20Answers.md)
