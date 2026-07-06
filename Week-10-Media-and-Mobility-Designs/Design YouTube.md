# Design YouTube
> **Week 10 — Media and Mobility System Designs**  
> **Prerequisites:** CDN Fundamentals (Week 1), Message Queues & Kafka (Week 6), Caching Patterns (Week 2), Event-Driven Architecture (Week 6)  
> **Cross-links:** CloudFront/HLS/DASH builds directly on CDN module; view-count aggregation uses Kafka patterns from Week 6.

---

## Learning Objectives
```
╔════════════════════════════════════════════════════════════╗
║ AFTER THIS MODULE, YOU WILL BE ABLE TO:                    ║
╟────────────────────────────────────────────────────────────╢
║                                                            ║
║ 1. Design a video upload pipeline from client resumable up ║
║ load through                                               ║
║    object storage, metadata indexing, and async transcodin ║
║ g fan-out                                                  ║
║                                                            ║
║ 2. Explain adaptive bitrate streaming (HLS and MPEG-DASH): ║
║  segment                                                   ║
║    structure, manifest files, player behavior, and CDN cac ║
║ he strategy                                                ║
║                                                            ║
║ 3. Size CDN and origin capacity for global video delivery: ║
║  egress math,                                              ║
║    cache hit ratios for segment vs manifest, Origin Shield ║
║  placement                                                 ║
║                                                            ║
║ 4. Design a view-count system that is accurate enough for  ║
║ creators                                                   ║
║    while surviving 1M+ concurrent playback sessions and bo ║
║ t traffic                                                  ║
║                                                            ║
║ 5. Architect a recommendation feed at YouTube scale: candi ║
║ date                                                       ║
║    generation, ranking, freshness, and the cold-start prob ║
║ lem                                                        ║
║                                                            ║
║ 6. Diagnose production incidents: transcoding backlog, CDN ║
║  stale                                                     ║
║    segments, view-count inflation, recommendation stalenes ║
║ s, live                                                    ║
║    stream keyframe misalignment                            ║
╚════════════════════════════════════════════════════════════╝
```
---

## Section 2: Wrong Mental Models (Destroy These First)

```
╔════════════════════════════════════════════════════════════╗
║ MENTAL MODEL #1: "Store one MP4, stream to everyone"       ║
╟────────────────────────────────────────────────────────────╢
║ WRONG. A single MP4 cannot serve mobile 360p and 4K TV sim ║
║ ultaneously                                                ║
║ without wasting bandwidth or buffering. You transcode to a ║
║  LADDER of                                                 ║
║ bitrates/resolutions and let the player switch via ABR (ad ║
║ aptive                                                     ║
║ bitrate). One upload becomes 10-20 renditions plus audio t ║
║ racks.                                                     ║
╚════════════════════════════════════════════════════════════╝
```
```
╔═══════════════════════════════════════════════════════════════════╗
║ MENTAL MODEL #2: "View count = increment a counter on every play" ║
╟───────────────────────────────────────────────────────────────────╢
║ WRONG. At 1B+ daily views, a single counter per video beco        ║
║ mes a hot                                                         ║
║ key and is gameable by bots. Production systems use dedupl        ║
║ ication                                                           ║
║ (viewer + video + time window), probabilistic structures,         ║
║ and async                                                         ║
║ aggregation via Kafka — never synchronous DB increments pe        ║
║ r view.                                                           ║
╚═══════════════════════════════════════════════════════════════════╝
```
```
╔════════════════════════════════════════════════════════════╗
║ MENTAL MODEL #3: "CDN caches the whole video file"         ║
╟────────────────────────────────────────────────────────────╢
║ WRONG for VOD at scale. HLS/DASH split video into 2-10 sec ║
║ ond                                                        ║
║ .ts or .m4s SEGMENTS. CDN caches segments independently. M ║
║ anifest                                                    ║
║ (.m3u8 / .mpd) has short TTL; segments are immutable with  ║
║ long TTL.                                                  ║
║ This is fundamentally different from caching a single MP4  ║
║ URL.                                                       ║
╚════════════════════════════════════════════════════════════╝
```
```
╔════════════════════════════════════════════════════════════════╗
║ MENTAL MODEL #4: "Transcoding happens before upload completes" ║
╟────────────────────────────────────────────────────────────────╢
║ WRONG. Upload completes to durable storage FIRST. Transcod     ║
║ ing is                                                         ║
║ async, fan-out, and retryable. Users see "Processing" unti     ║
║ l the                                                          ║
║ pipeline publishes renditions. Never block upload ACK on t     ║
║ ranscode.                                                      ║
╚════════════════════════════════════════════════════════════════╝
```
```
╔════════════════════════════════════════════════════════════╗
║ MENTAL MODEL #5: "Recommendations are one ML model"        ║
╟────────────────────────────────────────────────────────────╢
║ WRONG. YouTube-scale recsys is a PIPELINE: retrieval (mill ║
║ ions →                                                     ║
║ hundreds), ranking (hundreds → dozens), re-ranking (divers ║
║ ity,                                                       ║
║ freshness, policy). Each stage has different latency budge ║
║ ts and                                                     ║
║ failure isolation. One monolithic model cannot serve home  ║
║ feed.                                                      ║
╚════════════════════════════════════════════════════════════╝
```
---

## Core Teaching

### Functional Requirements

```
FUNCTIONAL REQUIREMENTS (prioritized):

  P0 — MUST HAVE:
    → Upload video (resumable, up to 256 GB per file)
    → Transcode to multiple resolutions/bitrates
    → Stream VOD globally with adaptive bitrate
    → Search videos by title, tags, channel
    → View count display (eventually consistent, ~minutes lag OK)
    → Home feed recommendations (personalized)
    → Live streaming (RTMP ingest → HLS/DASH out)

  P1 — SHOULD HAVE:
    → Comments, likes, subscriptions
    → Creator analytics dashboard
    → Content moderation (automated + human review queue)
    → Thumbnail generation and sprite sheets

  P2 — NICE TO HAVE:
    → Offline download (mobile)
    → Chapters, captions auto-generation
    → Super Chat / monetization
```

### Non-Functional Requirements

```
╔════════════════════════════════════════════════════════════╗
║ NFR TARGETS (production-grade, not interview hand-waving)  ║
╟────────────────────────────────────────────────────────────╢
║                                                            ║
║   Scale:        500M hours watched/day, 500 hours uploaded ║
║ /minute                                                    ║
║   Availability: 99.99% for playback (4.3 min downtime/mont ║
║ h)                                                         ║
║   Latency:      Start playback < 2s (p95) on broadband     ║
║   Upload:       Resumable; survive network drop mid-GB     ║
║   Durability:   11 nines for source video (S3 + cross-regi ║
║ on)                                                        ║
║   Consistency:  View counts: eventual (5-min lag acceptabl ║
║ e)                                                         ║
║                 Metadata: strong consistency for title/edi ║
║ ts                                                         ║
║   Cost:         Egress dominates — CDN cache hit ratio is  ║
║ a P0 metric                                                ║
╚════════════════════════════════════════════════════════════╝
```
### High-Level Architecture

```
                         YOUTUBE — LOGICAL ARCHITECTURE
                         ═══════════════════════════════

  ┌─────────────┐     ┌─────────────┐     ┌─────────────────────┐
  │ Web/Mobile  │     │ Smart TV    │     │ Creator Studio      │
  │   Client    │     │   Client    │     │ (upload + analytics)│
  └──────┬──────┘     └──────┬──────┘     └──────────┬──────────┘
         │                   │                        │
         └───────────────────┼────────────────────────┘
                             │
                    ┌────────▼────────┐
                    │  CloudFront CDN │  ← segment cache (HLS/DASH)
                    │  + Route 53     │  ← GeoDNS to nearest PoP
                    └────────┬────────┘
                             │ cache miss / API
         ┌───────────────────┼───────────────────┐
         │                   │                   │
  ┌──────▼──────┐   ┌────────▼────────┐  ┌──────▼──────┐
  │ API Gateway │   │ Video Origin    │  │ Live Origin │
  │ + ALB       │   │ (S3 + Origin    │  │ (MediaLive  │
  │             │   │  Shield)        │  │  + Packager)│
  └──────┬──────┘   └────────┬────────┘  └──────┬──────┘
         │                   │                   │
  ┌──────▼───────────────────▼───────────────────▼──────┐
  │              MICROSERVICES (ECS/EKS)                 │
  │  Upload │ Metadata │ Search │ Rec │ Comments │ Auth  │
  └──────┬───────────────────┬───────────────────┬──────┘
         │                   │                   │
  ┌──────▼──────┐   ┌────────▼────────┐  ┌──────▼──────┐
  │ S3 (raw +   │   │ RDS/Aurora      │  │ MSK (Kafka) │
  │ transcoded) │   │ (metadata)      │  │ view events │
  └──────┬──────┘   └─────────────────┘  └──────┬──────┘
         │                                        │
  ┌──────▼──────┐                        ┌──────▼──────┐
  │ MediaConvert│                        │ Flink/Spark │
  │ (transcode) │                        │ aggregators │
  └─────────────┘                        └─────────────┘
```

### Video Upload Pipeline — End to End

```
UPLOAD PIPELINE (resumable, durable-first)
═══════════════════════════════════════════

STEP 1: CLIENT REQUESTS UPLOAD SESSION
  POST /v1/videos/upload-session
  Body: { filename, size_bytes, content_type, title, description }
  Server:
    → Validates quota, auth, content policy
    → Creates video_id (UUID / KSUID)
    → Inserts row: status=UPLOADING in Aurora
    → Returns presigned S3 multipart upload URLs

STEP 2: CLIENT UPLOADS DIRECTLY TO S3 (bypasses app servers)
  Why direct-to-S3?
    → App servers cannot buffer 50 GB files in memory
    → S3 multipart: 5 MB - 5 GB parts, up to 10,000 parts
    → Client retries failed parts independently
    → Transfer Acceleration optional for distant creators

STEP 3: UPLOAD COMPLETE NOTIFICATION
  Client calls POST /v1/videos/{id}/upload-complete
  OR: S3 Event Notification → SQS → Upload Worker
  Worker:
    → Verifies all parts present (ListParts)
    → CompleteMultipartUpload
    → Updates status=UPLOADED
    → Publishes VideoUploaded event to Kafka

STEP 4: TRANSCODING FAN-OUT (async, never blocks step 3 ACK)
  Transcode Orchestrator consumes VideoUploaded:
    → Submits AWS MediaConvert job(s) OR self-hosted FFmpeg fleet
    → Rendition ladder (example):
        2160p @ 15 Mbps, 1440p @ 8 Mbps, 1080p @ 5 Mbps,
        720p @ 2.5 Mbps, 480p @ 1 Mbps, 360p @ 600 Kbps,
        240p @ 400 Kbps + separate audio 128 Kbps AAC
    → Output: HLS (.m3u8 + .ts) AND DASH (.mpd + .m4s)
    → Thumbnail extraction at 0%, 25%, 50%, 75% timestamps
    → Sprite sheet for scrub bar preview

STEP 5: PACKAGING + CDN PUBLISH
  On transcode complete:
    → Write manifests to S3 prefix: s3://cdn-origin/{video_id}/
    → Invalidate ONLY master.m3u8 (short TTL anyway)
    → Update status=READY, publish VideoReady event
    → Index in Elasticsearch for search
```

#### Transcoding Deep Dive — FFmpeg vs MediaConvert

```
TRANSCODING IS THE EXPENSIVE STEP

  Input:  1 hour 1080p source @ 8 Mbps  ≈ 3.6 GB
  Output: 7 video renditions + 1 audio     ≈ 15-25 GB total
  CPU:    ~0.5-2x realtime per rendition on modern hardware
          7 renditions × 60 min × 1.5x = 630 CPU-minutes per hour of video

AWS ELEMENTAL MEDIACONVERT JOB (illustrative):

  {
    "Role": "arn:aws:iam::123456789012:role/MediaConvertRole",
    "Settings": {
      "Inputs": [{
        "FileInput": "s3://raw-uploads/abc123/source.mp4"
      }],
      "OutputGroups": [{
        "Name": "HLS ABR Group",
        "OutputGroupSettings": {
          "Type": "HLS_GROUP_SETTINGS",
          "HlsGroupSettings": {
            "SegmentLength": 6,
            "Destination": "s3://cdn-origin/abc123/hls/"
          }
        },
        "Outputs": [
          { "NameModifier": "_1080p", "VideoDescription": { "Width": 1920, "Height": 1080,
            "CodecSettings": { "Codec": "H_264", "H264Settings": { "MaxBitrate": 5000000 }}}},
          { "NameModifier": "_720p",  "VideoDescription": { "Width": 1280, "Height": 720,
            "CodecSettings": { "Codec": "H_264", "H264Settings": { "MaxBitrate": 2500000 }}}},
          { "NameModifier": "_480p",  "VideoDescription": { "Width": 854,  "Height": 480,
            "CodecSettings": { "Codec": "H_264", "H264Settings": { "MaxBitrate": 1000000 }}}}
        ]
      }]
    }
  }

KEY TRANSCODE DECISIONS:

  Codec ladder:
    → H.264 (AVC): universal compatibility, larger files
    → H.265 (HEVC): 30-50% smaller, licensing/patent complexity
    → AV1: best compression, 10x slower encode — use for premium tier
    → VP9: YouTube's historical choice for web; AV1 succeeding it

  Segment duration:
    → 2 sec: lower latency (live), more manifest churn, more CDN requests
    → 6 sec: sweet spot for VOD (YouTube-ish)
    → 10 sec: fewer requests, slower quality switches, larger buffer

  Two-pass vs single-pass:
    → Two-pass: better quality at target bitrate (VOD)
    → Single-pass: faster, required for live
```

#### HLS and MPEG-DASH — Adaptive Bitrate Streaming

```
HLS (HTTP Live Streaming) — Apple origin, universal support

  MASTER PLAYLIST (master.m3u8):
    #EXTM3U
    #EXT-X-VERSION:6
    #EXT-X-STREAM-INF:BANDWIDTH=5128000,RESOLUTION=1920x1080,CODECS="avc1.640028,mp4a.40.2"
    1080p/playlist.m3u8
    #EXT-X-STREAM-INF:BANDWIDTH=2628000,RESOLUTION=1280x720,CODECS="avc1.640028,mp4a.40.2"
    720p/playlist.m3u8
    #EXT-X-STREAM-INF:BANDWIDTH=1128000,RESOLUTION=854x480,CODECS="avc1.640028,mp4a.40.2"
    480p/playlist.m3u8

  MEDIA PLAYLIST (1080p/playlist.m3u8):
    #EXTM3U
    #EXT-X-VERSION:6
    #EXT-X-TARGETDURATION:6
    #EXT-X-MEDIA-SEQUENCE:0
    #EXTINF:6.000,
    segment000.ts
    #EXTINF:6.000,
    segment001.ts
    ...

MPEG-DASH — ISO standard, same concept, XML manifest

  <?xml version="1.0" encoding="UTF-8"?>
  <MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static">
    <Period>
      <AdaptationSet mimeType="video/mp4">
        <Representation id="1080p" bandwidth="5128000" width="1920" height="1080">
          <SegmentTemplate media="1080p/segment$Number$.m4s"
                           initialization="1080p/init.m4s"
                           duration="6" startNumber="0"/>
        </Representation>
        ...
      </AdaptationSet>
    </Period>
  </MPD>

PLAYER ABR ALGORITHM (simplified):

  1. Download master manifest (short TTL, always fresh)
  2. Start at mid-tier rendition (e.g., 720p)
  3. Measure download throughput per segment
  4. If throughput > 1.5× current bitrate for 2 segments → switch UP
  5. If buffer < 5 seconds OR throughput < current bitrate → switch DOWN
  6. Never switch mid-segment (wait for segment boundary)

CDN CACHING STRATEGY FOR STREAMING:

  master.m3u8 / manifest.mpd:
    Cache-Control: public, max-age=60, must-revalidate
    → Short TTL: new renditions appear after transcode completes

  segment000.ts / segment000.m4s:
    Cache-Control: public, max-age=31536000, immutable
    → Segments NEVER change once written (content-addressable naming)
    → Version in path: /v3/abc123/hls/1080p/segment000.ts

  WHY THIS MATTERS:
    95%+ CDN hit ratio on segments = origin survives viral video
    Manifest misses are cheap (few KB); segment misses are expensive (MB)
```

#### CDN Architecture for Video — CloudFront + Origin Shield

```
VIDEO CDN REQUEST FLOW

  User (Mumbai) requests watch page for video abc123

  1. Browser loads HTML/JS from API (not CDN-cached, personalized)
  2. Player requests https://d123.cloudfront.net/abc123/hls/master.m3u8
  3. Route 53 GeoDNS → Mumbai CloudFront PoP
  4. PoP: cache MISS on master.m3u8 (short TTL or first request)
  5. PoP → Origin Shield (Singapore) → S3 (ap-south-1)
  6. PoP caches master.m3u8 (60s TTL)
  7. Player parses manifest, requests 720p/segment042.ts
  8. PoP: cache HIT (segment immutable) → 5ms response
  9. Repeat step 8 for each segment — origin never touched again

ORIGIN SHIELD CONFIGURATION (CloudFront):

  Origin: s3-cdn-origin.s3.ap-south-1.amazonaws.com
  Origin Shield: ENABLED, region=ap-south-1
  Behaviors:
    /abc123/hls/*.ts   → TTL 86400, compress off (already compressed)
    /abc123/hls/*.m3u8 → TTL 60, compress on
    /abc123/dash/*.m4s → TTL 86400
    /abc123/dash/*.mpd → TTL 60

  Signed URLs / Signed Cookies for premium/restricted content:
    → CloudFront key pair signs URL with expiry
    → Prevents hotlinking and unauthorized embedding

MULTI-CDN (at YouTube/Google scale):

  Google uses its own CDN (gCDN) — same network as Search
  For AWS-centric design: CloudFront primary + Fastly failover
  Segment URLs are CDN-agnostic if origin paths are consistent
```

#### View Count System — Aggregation at Scale

```
VIEW COUNT REQUIREMENTS:

  Display: "~1.2M views" (rounded, lag OK)
  Creator dashboard: more precise, 5-minute granularity
  Fraud: bot views must not inflate counts
  Hot videos: 10M views/hour = 2,777 events/sec for ONE video

ANTI-PATTERN: UPDATE videos SET view_count = view_count + 1 WHERE id = ?

  → Row-level lock contention on viral videos
  → Lost updates under concurrent increments
  → Database becomes bottleneck at 1K writes/sec per video

PRODUCTION PATTERN: EVENT-SOURCED AGGREGATION

  ┌──────────┐    view_event     ┌─────────┐    consume    ┌──────────────┐
  │  Player  │ ────────────────► │  Kafka  │ ─────────────► │ Flink job    │
  │  beacon  │   (async, batched)│  topic  │               │ (dedupe +    │
  └──────────┘                   └─────────┘               │  aggregate)  │
                                                           └──────┬───────┘
                                                                  │
                                                           ┌──────▼───────┐
                                                           │ Redis counter│
                                                           │ (per video)  │
                                                           └──────┬───────┘
                                                                  │
                                                           periodic flush
                                                                  │
                                                           ┌──────▼───────┐
                                                           │ Aurora       │
                                                           │ (authoritative│
                                                           │  view_count) │
                                                           └──────────────┘

VIEW EVENT SCHEMA:

  {
    "video_id": "abc123",
    "viewer_id": "user456",          // or anonymous fingerprint hash
    "session_id": "sess789",
    "timestamp_ms": 1712345678901,
    "watch_duration_sec": 32,
    "client_ip_hash": "sha256(...)",
    "is_embedded": false
  }

DEDUPLICATION RULES:

  Count as ONE view if:
    → watch_duration >= 30 seconds (or 30% of video length, whichever less)
    → Same viewer_id + video_id not counted again within 24 hours
    → Passes bot score threshold (rate limit, datacenter IP, headless UA)

FLINK AGGREGATION (pseudo):

  stream
    .keyBy(event -> event.video_id)
    .window(TumblingEventTimeWindows.of(Time.minutes(1)))
    .aggregate(new ViewCountAggregator())
    .addSink(new RedisIncrementSink());

CAPACITY MATH — view events:

  1 billion views/day = 11,574 events/sec average
  Peak (3x): ~35,000 events/sec
  Kafka: 3 brokers, 32 partitions, replication factor 3
  Each partition: ~1,100 events/sec — well within MSK limits
```

#### Recommendation System — Retrieval, Ranking, Serving

```
RECOMMENDATION PIPELINE (YouTube home feed)

  STAGE 1: CANDIDATE GENERATION (millions → ~500)
    Sources:
      → Subscription feed (new uploads from subscribed channels)
      → Collaborative filtering (users like you watched X)
      → Content-based (same topic embeddings as recently watched)
      → Trending (velocity of views in geography/time window)
      → Exploration (random sample for cold-start discovery)
    Each source returns ~100 candidates → merge + dedupe → ~500

  STAGE 2: RANKING (~500 → ~50)
    Features (1000+ in production, simplified):
      → Video: age, view velocity, avg watch time, CTR historical
      → User: watch history embeddings, time of day, device
      → Context: query if search, session depth
    Model: deep neural network (Two-Tower or Wide & Deep)
    Latency budget: 50-100ms for ranking inference

  STAGE 3: RE-RANKING (~50 → ~20 shown)
    → Diversity: don't show 5 videos from same channel
    → Freshness boost: new uploads from subscriptions
    → Policy filters: age restriction, geo-block, demonetized
    → Business rules: promote YouTube Shorts, live streams

SERVING ARCHITECTURE (AWS):

  ┌─────────┐   gRPC    ┌──────────────┐   batch   ┌─────────────┐
  │ Feed API│ ◄──────── │ Feature Store│ ◄──────── │ Offline     │
  │         │           │ (DynamoDB +  │           │ training    │
  │         │ ────────► │  ElastiCache)│           │ (SageMaker) │
  └────┬────┘  infer    └──────────────┘           └─────────────┘
       │
       ▼
  ┌─────────────┐
  │ SageMaker   │  real-time endpoint OR
  │ Endpoint    │  self-hosted Triton on GPU instances
  └─────────────┘

COLD START:
  New video: content embeddings from title/thumbnail/audio fingerprint
  New user: popular in region + onboarding topic picks
  Explore/exploit: epsilon-greedy slot in feed for unknown quality
```

#### Search, Metadata, and Comments

```
SEARCH ARCHITECTURE:

  Index: Elasticsearch / OpenSearch
  Documents: { video_id, title, description, tags, channel, transcript,
               upload_date, view_count, language }
  Query flow:
    User query → Query parser → ES bool query (title^3, tags^2, desc^1)
    → Facets (upload date, duration, HD) → Rank by relevance × freshness
  Scale: sharded by video_id hash, 50+ nodes for billion-document index

METADATA STORE (Aurora PostgreSQL):

  videos table:
    video_id PK, channel_id, title, description, status, duration_sec,
    created_at, published_at, view_count (flushed from Redis), thumbnail_url

  Sharding: channel_id hash for co-location of channel's videos
  Read replicas: 5+ for watch page metadata reads

COMMENTS (separate service):

  Partition key: video_id
  Sort key: comment_id (time-ordered UUID)
  DynamoDB or Cassandra — write-heavy, read by video page
  Hot video: 100K comments → paginate, cache top comments in Redis
```

#### Live Streaming Architecture

```
LIVE STREAMING (distinct from VOD pipeline)

  INGEST:
    Creator → RTMP/SRT → AWS MediaLive (or self-hosted nginx-rtmp)
    Single bitrate ingest (1080p source)

  TRANSCODE (real-time, NOT batch):
    MediaLive → multi-bitrate output → MediaPackage
    Segment duration: 2 sec (lower latency)
    No two-pass encoding — single-pass only

  ORIGIN:
    MediaPackage HLS/DASH endpoints (rolling window, not full VOD)
    DVR window: last 2 hours kept in origin buffer

  CDN:
    Same CloudFront behaviors but TTL on segments = segment duration
    (segments expire naturally — live playlist updates EXT-X-MEDIA-SEQUENCE)

  LATENCY BUDGET:
    Ingest → transcode → packager → CDN → player buffer
    Typical: 10-30 seconds (HLS low-latency mode: 3-5 sec with partial segments)
```

### Capacity Planning — Worked Examples

```
CAPACITY: Daily Egress
  Given: 500,000,000 hours/day watched
  Avg bitrate: 1.5 Mbps avg
  Daily data: 299.76 PB
  At $0.02/GB CloudFront (commit tier): $6,139,089/day
  → Key metric: PB/day egress
```

```
CAPACITY: Upload Storage
  Given: 500 hours/min uploaded
  Avg bitrate: 8 Mbps avg source
  Daily data: 0.00 PB
  At $0.02/GB CloudFront (commit tier): $33/day
  → Key metric: TB/day raw ingest
```

```
CAPACITY: Transcode Fleet
  Given: 500 hours/min
  Renditions: 7
  CPU-minutes/min: 315,000
  @ 32 vCPU/instance, 2x realtime: 4,922 instances
  → Key metric: CPU-minutes/min
```

```
CAPACITY: Kafka View Events
  Given: 1,000,000,000 views/day
  → Key metric: events/sec peak
```

```
CAPACITY: CDN Segment Requests
  Given: 500,000,000 hours/day
  Segments per hour of video: ~600
  Segment requests/sec (avg): 83,333,333
  → Key metric: segment RPS
```


---

## Section 4: Concrete Examples — AWS Configurations

### Example 1: S3 Multipart Upload Presign

```python
import boto3
from uuid import uuid4

s3 = boto3.client("s3")
BUCKET = "yt-raw-uploads-prod"

def create_upload_session(user_id: str, filename: str, size_bytes: int) -> dict:
    video_id = str(uuid4())
    key = f"raw/{user_id}/{video_id}/{filename}"

    # Initiate multipart — client uploads parts with presigned URLs
    mpu = s3.create_multipart_upload(
        Bucket=BUCKET,
        Key=key,
        ContentType="video/mp4",
        ServerSideEncryption="aws:kms",
        Metadata={"video-id": video_id, "uploader": user_id},
    )

    # Part size: 64 MB (balance part count vs retry granularity)
    part_size = 64 * 1024 * 1024
    num_parts = (size_bytes + part_size - 1) // part_size
    presigned_urls = []
    for part_num in range(1, min(num_parts, 10000) + 1):
        url = s3.generate_presigned_url(
            "upload_part",
            Params={
                "Bucket": BUCKET,
                "Key": key,
                "UploadId": mpu["UploadId"],
                "PartNumber": part_num,
            },
            ExpiresIn=3600,
        )
        presigned_urls.append({"part_number": part_num, "url": url})

    return {
        "video_id": video_id,
        "upload_id": mpu["UploadId"],
        "key": key,
        "part_size": part_size,
        "presigned_urls": presigned_urls,
    }
```

### Example 2: CloudFront Behavior for HLS Segments

```json
{
  "CallerReference": "yt-hls-vod-2024",
  "Origins": {
    "Quantity": 1,
    "Items": [{
      "Id": "S3-VideoOrigin",
      "DomainName": "yt-cdn-origin.s3.us-east-1.amazonaws.com",
      "OriginShield": { "Enabled": true, "OriginShieldRegion": "us-east-1" },
      "S3OriginConfig": { "OriginAccessIdentity": "origin-access-identity/cloudfront/E1234" }
    }]
  },
  "CacheBehaviors": {
    "Quantity": 2,
    "Items": [
      {
        "PathPattern": "*.ts",
        "TargetOriginId": "S3-VideoOrigin",
        "ViewerProtocolPolicy": "redirect-to-https",
        "MinTTL": 86400,
        "DefaultTTL": 31536000,
        "MaxTTL": 31536000,
        "Compress": false,
        "ForwardedValues": { "QueryString": false, "Cookies": { "Forward": "none" }}
      },
      {
        "PathPattern": "*.m3u8",
        "TargetOriginId": "S3-VideoOrigin",
        "MinTTL": 0,
        "DefaultTTL": 60,
        "MaxTTL": 300,
        "Compress": true
      }
    ]
  }
}
```


---

## Section 5: Production Patterns — How Teams Actually Ship

```
PATTERN 1: Idempotent upload completion
  S3 event + client ACK dedupe via upload_id
```

```
PATTERN 2: Transcode job priority queue
  premium creators / short videos first
```

```
PATTERN 3: Canary renditions
  publish 480p first for fast 'available' UX, HD follows
```

```
PATTERN 4: Segment content-addressable paths
  hash in filename prevents stale CDN mix
```

```
PATTERN 5: View count display rounding
  show '1.2M' not '1,234,567' to hide lag
```

```
PATTERN 6: Recommendation fallback
  if ranker timeout, serve subscription + trending
```

```
PATTERN 7: Multi-region active-active metadata
  Aurora Global Database for read locality
```

```
PATTERN 8: Live stream health dashboard
  segment arrival rate, keyframe interval alerts
```


---

## Section 6: Failure Modes — What Breaks in Production

### Failure: Transcoding Backlog

```
SCENARIO: Viral upload hour fills MediaConvert queue; new videos stuck 'Processing' for hours

DETECT: Queue depth metric, age-of-oldest-job alert

FIX: Auto-scale FFmpeg fleet; priority queue; cap upload rate per user
```

### Failure: CDN Serving Stale Manifest

```
SCENARIO: New HD rendition ready but master.m3u8 cached old version without 1080p

DETECT: Users stuck at 480p after HD transcode completes

FIX: Short manifest TTL; version query param on publish; purge on VideoReady
```

### Failure: View Count Inflation

```
SCENARIO: Bot farm sends view beacons; creator sees spike, advertisers angry

DETECT: view_count / unique_viewers ratio > 10

FIX: Rate limit beacons; bot score; dedupe window; anomaly detection on Flink
```

### Failure: Hot Key on Viral Video

```
SCENARIO: Single video metadata row saturates Aurora replica

DETECT: Watch page p99 latency 5s for one video only

FIX: Cache video metadata in Redis; read from replica pool; pre-warm on trend detect
```

### Failure: Segment Origin Stampede

```
SCENARIO: CDN TTL misconfigured on .ts; viral video cold-misses origin

DETECT: S3 GET 503; origin egress bill spike

FIX: immutable segments + long TTL; Origin Shield; request coalescing
```

### Failure: Recommendation Staleness

```
SCENARIO: Feature store pipeline lag; feed shows days-old patterns

DETECT: CTR drops 15%; users complain 'feed is stale'

FIX: Fallback to trending; monitor feature freshness SLA; cache ranker output 5min
```

### Failure: Live Stream Keyframe Gap

```
SCENARIO: Encoder keyframe interval > segment duration

DETECT: Player stalls every 6 sec; chat explodes

FIX: Force keyframe every 2 sec in MediaLive; alert on GOP size
```

### Failure: Cross-Region Upload Failure

```
SCENARIO: Creator in EU uploads to us-east-1 only; high latency, timeouts

DETECT: Upload failure rate 8% in ap-south-1

FIX: S3 Transfer Acceleration; regional upload endpoints; GeoRoute presign to nearest bucket
```


---

## SRE Diagnostic Toolkit
```
METRICS TO DASHBOARD (CloudWatch + Grafana)

  cdn.segment.hit_ratio          source=CloudFront   alert=< 90% for 5 min      P2 — origin load rising
  transcode.queue.depth          source=Custom       alert=> 10,000 jobs        P1 — publish SLA breach
  transcode.job.age_p99          source=MediaConvert alert=> 3600 sec           P2 — backlog
  upload.multipart.failure_rate  source=S3/API       alert=> 1%                 P2 — regional issue
  view.events.lag                source=Kafka consumer alert=> 300 sec            P3 — count display stale
  playback.start_time_p95        source=Client RUM   alert=> 3000 ms            P1 — UX degradation
  origin.egress.gbps             source=S3/CloudFront alert=> 80% capacity       P1 — scale or cache fix
  rec.ranker.latency_p99         source=SageMaker    alert=> 200 ms             P2 — fallback rate up

LOG QUERIES (CloudWatch Logs Insights):

  fields @timestamp, video_id, status, duration_ms
  | filter service = "transcode-orchestrator"
  | filter status = "FAILED"
  | stats count() by error_code

COMMANDS:

  # CloudFront cache stats
  aws cloudfront get-distribution-config --id E1234567890

  # MediaConvert queue depth
  aws mediaconvert list-jobs --status PROGRESSING --max-results 50

  # Kafka consumer lag
  kafka-consumer-groups.sh --bootstrap-server $BROKER --describe --group view-agg
```


---

## Decision Framework
```
╔════════════════════════════════════════════════════════════╗
║ WHEN TO USE WHAT                                           ║
╟────────────────────────────────────────────────────────────╢
║                                                            ║
║ HLS vs DASH:                                               ║
║   HLS → Apple devices, legacy players, live (MediaPackage  ║
║ default)                                                   ║
║   DASH → Android, smart TVs, standards-first; ship BOTH fo ║
║ r VOD                                                      ║
║                                                            ║
║ MediaConvert vs self-hosted FFmpeg:                        ║
║   MediaConvert → ops simplicity, burst scale, pay-per-minu ║
║ te                                                         ║
║   FFmpeg fleet → 10x+ volume, custom codecs, cost at scale ║
║                                                            ║
║ View count storage:                                        ║
║   Redis + periodic flush → 99% of cases                    ║
║   CRDT / HLL → cross-region merge without coordination     ║
║   Sync DB increment → NEVER at scale                       ║
║                                                            ║
║ Segment TTL:                                               ║
║   VOD segments → immutable, max-age=1 year                 ║
║   Live segments → TTL = segment duration (rolling window)  ║
║   Manifests → 60 sec max, always revalidate                ║
╚════════════════════════════════════════════════════════════╝
```
---

## Section 9: Incident Scenario — Multi-Symptom, No Hand-Holding

```
INCIDENT REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Severity: P1
Service: YouTube-clone video platform
Time: 8:47 PM UTC (prime time US + India overlap)

ARCHITECTURE:
  Upload → S3 → MediaConvert → S3 origin → CloudFront → players
  View counts → Kafka → Flink → Redis → Aurora
  Recommendations → SageMaker endpoint + DynamoDB feature store

SYMPTOMS (all started within 12 minutes):
  1. Support: 'Videos stuck on Processing for 2+ hours'
  2. Dashboard: CloudFront origin egress 8x normal; hit ratio 62% (was 94%)
  3. PagerDuty: playback.start_time_p95 = 8.2 seconds (SLA: 2s)
  4. Creator complaint: view count dropped 40% on trending video
  5. S3 metrics: GET 503 rate 0.3% on cdn-origin bucket
  6. Deploy at 8:35 PM: changed CloudFront .ts behavior TTL 86400 → 60

YOUR TASKS:
  Q1: What is the PRIMARY root cause? Trace the cascade.
  Q2: Immediate mitigation — ordered steps, first 15 minutes.
  Q3: Why did view counts DROP? (Not inflation — actual drop.)
  Q4: Long-term controls so TTL misconfig cannot recur.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```


---

## Section 10: Expert Analysis — Full Worked Response

### Q1: Root Cause Cascade

```
PRIMARY: CloudFront .ts TTL changed 86400 → 60 at 8:35 PM deploy.

CASCADE:
  1. Segments expire after 60s instead of staying cached 24h+
  2. Every player re-fetches segments from origin every minute
  3. Hit ratio collapses 94% → 62% (38% of segment requests hit S3)
  4. S3 cdn-origin bucket saturates — 503 on GET
  5. Players buffer → playback.start_time_p95 spikes to 8.2s
  6. SECONDARY: Transcode backlog is RED HERRING timing — queue was
     already elevated from upload spike; not caused by CDN change,
     but worsened because origin team distracted.

View count drop: Flink consumers lagging because Kafka brokers under
  network pressure from same AWS account egress spike — unrelated
  to CDN directly but correlated in time.
```

### Q2: Immediate Mitigation (0-15 min)

```
  T+0:   Rollback CloudFront behavior .ts TTL to 86400 (or invalidate
         all .ts to force re-fetch with correct policy after fix)
  T+2:   Enable Origin Shield if not already — collapse miss storms
  T+5:   S3 request rate limit alert — confirm 503 resolving
  T+8:   Status page: 'Investigating slow playback'
  T+10:  Verify hit ratio climbing; playback p95 dropping
  T+15:  Do NOT scale transcode — unrelated to playback incident
```

### Q3: View Count Drop Explained

```
  Flink consumer lag spiked to 45 min due to broker IO wait.
  Redis counters stopped receiving increments.
  Periodic Aurora flush READS Redis (stale) and OVERWRITES
  Aurora with lower value — bug: flush should be MAX(redis, aurora).
  Displayed count drops until Flink catches up.
  FIX: monotonic flush — never write lower count than DB has.
```

### Q4: Long-Term Controls

```
  1. IaC policy: .ts and .m4s behaviors REQUIRE TTL >= 86400 (OPA/cfn-guard)
  2. CI smoke test: deploy to staging, verify segment Age header > 3600
  3. Canary distribution: 5% traffic before full CDN config push
  4. View count: monotonic merge; alert if count decreases > 1%
  5. Dashboard: origin offload % as P0 SLO on exec dashboard
```


---

## Key Takeaways
```
╔════════════════════════════════════════════════════════════╗
║ IF YOU FORGET EVERYTHING ELSE, REMEMBER THESE:             ║
╟────────────────────────────────────────────────────────────╢
║                                                            ║
║ 1. Upload is durable-first; transcode is async fan-out. Ne ║
║ ver block                                                  ║
║    upload ACK on transcoding completion.                   ║
║                                                            ║
║ 2. HLS/DASH segment caching ≠ file caching. Immutable segm ║
║ ents with                                                  ║
║    long TTL; short TTL on manifests only.                  ║
║                                                            ║
║ 3. View counts are aggregated events with dedupe — not DB  ║
║ increments.                                                ║
║    Monotonic merge when flushing to authoritative store.   ║
║                                                            ║
║ 4. Recommendations are a multi-stage pipeline with fallbac ║
║ ks, not                                                    ║
║    one model. Latency budget per stage matters.            ║
║                                                            ║
║ 5. CDN hit ratio on segments is a P0 metric — a single TTL ║
║    misconfiguration can collapse origin and playback UX.   ║
╚════════════════════════════════════════════════════════════╝
```
---

## Targeted Reading
```
RECOMMENDED READING (specific, not 'read DDIA'):

  DDIA Chapter 11 (Stream Processing) — event aggregation patterns
    → pages 444-479: batch vs stream, CDC, stream joins
    Directly applies to view count Flink pipeline

  AWS MediaConvert User Guide — job templates, acceleration modes
    → https://docs.aws.amazon.com/mediaconvert/latest/ug/

  Apple HLS Authoring Specification
    → https://developer.apple.com/documentation/http_live_streaming/
    → Segment duration, codec strings, master playlist rules

  Google paper: 'Deep Neural Networks for YouTube Recommendations'
    (Covington et al., RecSys 2016) — candidate generation + ranking

  Week 1 module: CDN Fundamentals — Cache-Control, Origin Shield,
    stale-while-revalidate (direct prerequisite for video CDN)

  Week 6 module: Message Queues & Kafka — consumer groups, lag,
    partitioning for view event throughput
```


---

# Appendix A: Detailed Component Specifications

### A.1 Component Deep-Dive Block 1

```
COMPONENT BLOCK 1 — production notes

  Focus: S3 lifecycle: raw → Glacier after 90 days
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-001

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.2 Component Deep-Dive Block 2

```
COMPONENT BLOCK 2 — production notes

  Focus: MediaConvert acceleration: PREFERRED vs ENABLED
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-002

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.3 Component Deep-Dive Block 3

```
COMPONENT BLOCK 3 — production notes

  Focus: CloudFront signed URL key rotation
  SLA impact: tier-1
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-003

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.4 Component Deep-Dive Block 4

```
COMPONENT BLOCK 4 — production notes

  Focus: Kafka partition key: video_id for view ordering
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-004

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.5 Component Deep-Dive Block 5

```
COMPONENT BLOCK 5 — production notes

  Focus: Flink state backend: RocksDB for large windows
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-005

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.6 Component Deep-Dive Block 6

```
COMPONENT BLOCK 6 — production notes

  Focus: Elasticsearch refresh interval: 30s for search index
  SLA impact: tier-1
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-006

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.7 Component Deep-Dive Block 7

```
COMPONENT BLOCK 7 — production notes

  Focus: Aurora read replica lag monitoring
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-007

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.8 Component Deep-Dive Block 8

```
COMPONENT BLOCK 8 — production notes

  Focus: Redis cluster mode for view counter shards
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-008

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.9 Component Deep-Dive Block 9

```
COMPONENT BLOCK 9 — production notes

  Focus: SageMaker multi-model endpoint cost optimization
  SLA impact: tier-1
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-009

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.10 Component Deep-Dive Block 10

```
COMPONENT BLOCK 10 — production notes

  Focus: Upload chunk retry with exponential backoff
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-010

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.11 Component Deep-Dive Block 11

```
COMPONENT BLOCK 11 — production notes

  Focus: S3 lifecycle: raw → Glacier after 90 days
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-011

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.12 Component Deep-Dive Block 12

```
COMPONENT BLOCK 12 — production notes

  Focus: MediaConvert acceleration: PREFERRED vs ENABLED
  SLA impact: tier-1
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-012

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.13 Component Deep-Dive Block 13

```
COMPONENT BLOCK 13 — production notes

  Focus: CloudFront signed URL key rotation
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-013

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.14 Component Deep-Dive Block 14

```
COMPONENT BLOCK 14 — production notes

  Focus: Kafka partition key: video_id for view ordering
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-014

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.15 Component Deep-Dive Block 15

```
COMPONENT BLOCK 15 — production notes

  Focus: Flink state backend: RocksDB for large windows
  SLA impact: tier-1
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-015

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.16 Component Deep-Dive Block 16

```
COMPONENT BLOCK 16 — production notes

  Focus: Elasticsearch refresh interval: 30s for search index
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-016

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.17 Component Deep-Dive Block 17

```
COMPONENT BLOCK 17 — production notes

  Focus: Aurora read replica lag monitoring
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-017

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.18 Component Deep-Dive Block 18

```
COMPONENT BLOCK 18 — production notes

  Focus: Redis cluster mode for view counter shards
  SLA impact: tier-1
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-018

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.19 Component Deep-Dive Block 19

```
COMPONENT BLOCK 19 — production notes

  Focus: SageMaker multi-model endpoint cost optimization
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-019

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.20 Component Deep-Dive Block 20

```
COMPONENT BLOCK 20 — production notes

  Focus: Upload chunk retry with exponential backoff
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-020

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.21 Component Deep-Dive Block 21

```
COMPONENT BLOCK 21 — production notes

  Focus: S3 lifecycle: raw → Glacier after 90 days
  SLA impact: tier-1
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-021

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.22 Component Deep-Dive Block 22

```
COMPONENT BLOCK 22 — production notes

  Focus: MediaConvert acceleration: PREFERRED vs ENABLED
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-022

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.23 Component Deep-Dive Block 23

```
COMPONENT BLOCK 23 — production notes

  Focus: CloudFront signed URL key rotation
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-023

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.24 Component Deep-Dive Block 24

```
COMPONENT BLOCK 24 — production notes

  Focus: Kafka partition key: video_id for view ordering
  SLA impact: tier-1
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-024

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.25 Component Deep-Dive Block 25

```
COMPONENT BLOCK 25 — production notes

  Focus: Flink state backend: RocksDB for large windows
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-025

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.26 Component Deep-Dive Block 26

```
COMPONENT BLOCK 26 — production notes

  Focus: Elasticsearch refresh interval: 30s for search index
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-026

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.27 Component Deep-Dive Block 27

```
COMPONENT BLOCK 27 — production notes

  Focus: Aurora read replica lag monitoring
  SLA impact: tier-1
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-027

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.28 Component Deep-Dive Block 28

```
COMPONENT BLOCK 28 — production notes

  Focus: Redis cluster mode for view counter shards
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-028

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.29 Component Deep-Dive Block 29

```
COMPONENT BLOCK 29 — production notes

  Focus: SageMaker multi-model endpoint cost optimization
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-029

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.30 Component Deep-Dive Block 30

```
COMPONENT BLOCK 30 — production notes

  Focus: Upload chunk retry with exponential backoff
  SLA impact: tier-1
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-030

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.31 Component Deep-Dive Block 31

```
COMPONENT BLOCK 31 — production notes

  Focus: S3 lifecycle: raw → Glacier after 90 days
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-031

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.32 Component Deep-Dive Block 32

```
COMPONENT BLOCK 32 — production notes

  Focus: MediaConvert acceleration: PREFERRED vs ENABLED
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-032

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.33 Component Deep-Dive Block 33

```
COMPONENT BLOCK 33 — production notes

  Focus: CloudFront signed URL key rotation
  SLA impact: tier-1
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-033

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.34 Component Deep-Dive Block 34

```
COMPONENT BLOCK 34 — production notes

  Focus: Kafka partition key: video_id for view ordering
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-034

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.35 Component Deep-Dive Block 35

```
COMPONENT BLOCK 35 — production notes

  Focus: Flink state backend: RocksDB for large windows
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-035

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.36 Component Deep-Dive Block 36

```
COMPONENT BLOCK 36 — production notes

  Focus: Elasticsearch refresh interval: 30s for search index
  SLA impact: tier-1
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-036

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.37 Component Deep-Dive Block 37

```
COMPONENT BLOCK 37 — production notes

  Focus: Aurora read replica lag monitoring
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-037

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.38 Component Deep-Dive Block 38

```
COMPONENT BLOCK 38 — production notes

  Focus: Redis cluster mode for view counter shards
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-038

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.39 Component Deep-Dive Block 39

```
COMPONENT BLOCK 39 — production notes

  Focus: SageMaker multi-model endpoint cost optimization
  SLA impact: tier-1
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-039

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.40 Component Deep-Dive Block 40

```
COMPONENT BLOCK 40 — production notes

  Focus: Upload chunk retry with exponential backoff
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-040

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.41 Component Deep-Dive Block 41

```
COMPONENT BLOCK 41 — production notes

  Focus: S3 lifecycle: raw → Glacier after 90 days
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-041

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.42 Component Deep-Dive Block 42

```
COMPONENT BLOCK 42 — production notes

  Focus: MediaConvert acceleration: PREFERRED vs ENABLED
  SLA impact: tier-1
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-042

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.43 Component Deep-Dive Block 43

```
COMPONENT BLOCK 43 — production notes

  Focus: CloudFront signed URL key rotation
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-043

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.44 Component Deep-Dive Block 44

```
COMPONENT BLOCK 44 — production notes

  Focus: Kafka partition key: video_id for view ordering
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-044

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.45 Component Deep-Dive Block 45

```
COMPONENT BLOCK 45 — production notes

  Focus: Flink state backend: RocksDB for large windows
  SLA impact: tier-1
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-045

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.46 Component Deep-Dive Block 46

```
COMPONENT BLOCK 46 — production notes

  Focus: Elasticsearch refresh interval: 30s for search index
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-046

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.47 Component Deep-Dive Block 47

```
COMPONENT BLOCK 47 — production notes

  Focus: Aurora read replica lag monitoring
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-047

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.48 Component Deep-Dive Block 48

```
COMPONENT BLOCK 48 — production notes

  Focus: Redis cluster mode for view counter shards
  SLA impact: tier-1
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-048

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.49 Component Deep-Dive Block 49

```
COMPONENT BLOCK 49 — production notes

  Focus: SageMaker multi-model endpoint cost optimization
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-049

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.50 Component Deep-Dive Block 50

```
COMPONENT BLOCK 50 — production notes

  Focus: Upload chunk retry with exponential backoff
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-050

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.51 Component Deep-Dive Block 51

```
COMPONENT BLOCK 51 — production notes

  Focus: S3 lifecycle: raw → Glacier after 90 days
  SLA impact: tier-1
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-051

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.52 Component Deep-Dive Block 52

```
COMPONENT BLOCK 52 — production notes

  Focus: MediaConvert acceleration: PREFERRED vs ENABLED
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-052

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.53 Component Deep-Dive Block 53

```
COMPONENT BLOCK 53 — production notes

  Focus: CloudFront signed URL key rotation
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-053

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.54 Component Deep-Dive Block 54

```
COMPONENT BLOCK 54 — production notes

  Focus: Kafka partition key: video_id for view ordering
  SLA impact: tier-1
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-054

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.55 Component Deep-Dive Block 55

```
COMPONENT BLOCK 55 — production notes

  Focus: Flink state backend: RocksDB for large windows
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-055

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.56 Component Deep-Dive Block 56

```
COMPONENT BLOCK 56 — production notes

  Focus: Elasticsearch refresh interval: 30s for search index
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-056

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.57 Component Deep-Dive Block 57

```
COMPONENT BLOCK 57 — production notes

  Focus: Aurora read replica lag monitoring
  SLA impact: tier-1
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-057

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.58 Component Deep-Dive Block 58

```
COMPONENT BLOCK 58 — production notes

  Focus: Redis cluster mode for view counter shards
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-058

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.59 Component Deep-Dive Block 59

```
COMPONENT BLOCK 59 — production notes

  Focus: SageMaker multi-model endpoint cost optimization
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-059

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.60 Component Deep-Dive Block 60

```
COMPONENT BLOCK 60 — production notes

  Focus: Upload chunk retry with exponential backoff
  SLA impact: tier-1
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-060

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.61 Component Deep-Dive Block 61

```
COMPONENT BLOCK 61 — production notes

  Focus: S3 lifecycle: raw → Glacier after 90 days
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-061

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.62 Component Deep-Dive Block 62

```
COMPONENT BLOCK 62 — production notes

  Focus: MediaConvert acceleration: PREFERRED vs ENABLED
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-062

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.63 Component Deep-Dive Block 63

```
COMPONENT BLOCK 63 — production notes

  Focus: CloudFront signed URL key rotation
  SLA impact: tier-1
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-063

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.64 Component Deep-Dive Block 64

```
COMPONENT BLOCK 64 — production notes

  Focus: Kafka partition key: video_id for view ordering
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-064

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.65 Component Deep-Dive Block 65

```
COMPONENT BLOCK 65 — production notes

  Focus: Flink state backend: RocksDB for large windows
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-065

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.66 Component Deep-Dive Block 66

```
COMPONENT BLOCK 66 — production notes

  Focus: Elasticsearch refresh interval: 30s for search index
  SLA impact: tier-1
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-066

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.67 Component Deep-Dive Block 67

```
COMPONENT BLOCK 67 — production notes

  Focus: Aurora read replica lag monitoring
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-067

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.68 Component Deep-Dive Block 68

```
COMPONENT BLOCK 68 — production notes

  Focus: Redis cluster mode for view counter shards
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-068

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.69 Component Deep-Dive Block 69

```
COMPONENT BLOCK 69 — production notes

  Focus: SageMaker multi-model endpoint cost optimization
  SLA impact: tier-1
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-069

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.70 Component Deep-Dive Block 70

```
COMPONENT BLOCK 70 — production notes

  Focus: Upload chunk retry with exponential backoff
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-070

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.71 Component Deep-Dive Block 71

```
COMPONENT BLOCK 71 — production notes

  Focus: S3 lifecycle: raw → Glacier after 90 days
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-071

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.72 Component Deep-Dive Block 72

```
COMPONENT BLOCK 72 — production notes

  Focus: MediaConvert acceleration: PREFERRED vs ENABLED
  SLA impact: tier-1
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-072

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.73 Component Deep-Dive Block 73

```
COMPONENT BLOCK 73 — production notes

  Focus: CloudFront signed URL key rotation
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-073

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.74 Component Deep-Dive Block 74

```
COMPONENT BLOCK 74 — production notes

  Focus: Kafka partition key: video_id for view ordering
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-074

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.75 Component Deep-Dive Block 75

```
COMPONENT BLOCK 75 — production notes

  Focus: Flink state backend: RocksDB for large windows
  SLA impact: tier-1
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-075

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.76 Component Deep-Dive Block 76

```
COMPONENT BLOCK 76 — production notes

  Focus: Elasticsearch refresh interval: 30s for search index
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-076

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.77 Component Deep-Dive Block 77

```
COMPONENT BLOCK 77 — production notes

  Focus: Aurora read replica lag monitoring
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-077

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.78 Component Deep-Dive Block 78

```
COMPONENT BLOCK 78 — production notes

  Focus: Redis cluster mode for view counter shards
  SLA impact: tier-1
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-078

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.79 Component Deep-Dive Block 79

```
COMPONENT BLOCK 79 — production notes

  Focus: SageMaker multi-model endpoint cost optimization
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-079

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.80 Component Deep-Dive Block 80

```
COMPONENT BLOCK 80 — production notes

  Focus: Upload chunk retry with exponential backoff
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-080

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.81 Component Deep-Dive Block 81

```
COMPONENT BLOCK 81 — production notes

  Focus: S3 lifecycle: raw → Glacier after 90 days
  SLA impact: tier-1
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-081

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.82 Component Deep-Dive Block 82

```
COMPONENT BLOCK 82 — production notes

  Focus: MediaConvert acceleration: PREFERRED vs ENABLED
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-082

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.83 Component Deep-Dive Block 83

```
COMPONENT BLOCK 83 — production notes

  Focus: CloudFront signed URL key rotation
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-083

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.84 Component Deep-Dive Block 84

```
COMPONENT BLOCK 84 — production notes

  Focus: Kafka partition key: video_id for view ordering
  SLA impact: tier-1
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-084

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.85 Component Deep-Dive Block 85

```
COMPONENT BLOCK 85 — production notes

  Focus: Flink state backend: RocksDB for large windows
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-085

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.86 Component Deep-Dive Block 86

```
COMPONENT BLOCK 86 — production notes

  Focus: Elasticsearch refresh interval: 30s for search index
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-086

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.87 Component Deep-Dive Block 87

```
COMPONENT BLOCK 87 — production notes

  Focus: Aurora read replica lag monitoring
  SLA impact: tier-1
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-087

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.88 Component Deep-Dive Block 88

```
COMPONENT BLOCK 88 — production notes

  Focus: Redis cluster mode for view counter shards
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-088

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.89 Component Deep-Dive Block 89

```
COMPONENT BLOCK 89 — production notes

  Focus: SageMaker multi-model endpoint cost optimization
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-089

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.90 Component Deep-Dive Block 90

```
COMPONENT BLOCK 90 — production notes

  Focus: Upload chunk retry with exponential backoff
  SLA impact: tier-1
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-090

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.91 Component Deep-Dive Block 91

```
COMPONENT BLOCK 91 — production notes

  Focus: S3 lifecycle: raw → Glacier after 90 days
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-091

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.92 Component Deep-Dive Block 92

```
COMPONENT BLOCK 92 — production notes

  Focus: MediaConvert acceleration: PREFERRED vs ENABLED
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-092

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.93 Component Deep-Dive Block 93

```
COMPONENT BLOCK 93 — production notes

  Focus: CloudFront signed URL key rotation
  SLA impact: tier-1
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-093

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.94 Component Deep-Dive Block 94

```
COMPONENT BLOCK 94 — production notes

  Focus: Kafka partition key: video_id for view ordering
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-094

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.95 Component Deep-Dive Block 95

```
COMPONENT BLOCK 95 — production notes

  Focus: Flink state backend: RocksDB for large windows
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-095

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.96 Component Deep-Dive Block 96

```
COMPONENT BLOCK 96 — production notes

  Focus: Elasticsearch refresh interval: 30s for search index
  SLA impact: tier-1
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-096

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.97 Component Deep-Dive Block 97

```
COMPONENT BLOCK 97 — production notes

  Focus: Aurora read replica lag monitoring
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-097

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.98 Component Deep-Dive Block 98

```
COMPONENT BLOCK 98 — production notes

  Focus: Redis cluster mode for view counter shards
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-098

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.99 Component Deep-Dive Block 99

```
COMPONENT BLOCK 99 — production notes

  Focus: SageMaker multi-model endpoint cost optimization
  SLA impact: tier-1
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-099

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.100 Component Deep-Dive Block 100

```
COMPONENT BLOCK 100 — production notes

  Focus: Upload chunk retry with exponential backoff
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-100

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.101 Component Deep-Dive Block 101

```
COMPONENT BLOCK 101 — production notes

  Focus: S3 lifecycle: raw → Glacier after 90 days
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-101

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.102 Component Deep-Dive Block 102

```
COMPONENT BLOCK 102 — production notes

  Focus: MediaConvert acceleration: PREFERRED vs ENABLED
  SLA impact: tier-1
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-102

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.103 Component Deep-Dive Block 103

```
COMPONENT BLOCK 103 — production notes

  Focus: CloudFront signed URL key rotation
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-103

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.104 Component Deep-Dive Block 104

```
COMPONENT BLOCK 104 — production notes

  Focus: Kafka partition key: video_id for view ordering
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-104

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.105 Component Deep-Dive Block 105

```
COMPONENT BLOCK 105 — production notes

  Focus: Flink state backend: RocksDB for large windows
  SLA impact: tier-1
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-105

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.106 Component Deep-Dive Block 106

```
COMPONENT BLOCK 106 — production notes

  Focus: Elasticsearch refresh interval: 30s for search index
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-106

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.107 Component Deep-Dive Block 107

```
COMPONENT BLOCK 107 — production notes

  Focus: Aurora read replica lag monitoring
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-107

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.108 Component Deep-Dive Block 108

```
COMPONENT BLOCK 108 — production notes

  Focus: Redis cluster mode for view counter shards
  SLA impact: tier-1
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-108

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.109 Component Deep-Dive Block 109

```
COMPONENT BLOCK 109 — production notes

  Focus: SageMaker multi-model endpoint cost optimization
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-109

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.110 Component Deep-Dive Block 110

```
COMPONENT BLOCK 110 — production notes

  Focus: Upload chunk retry with exponential backoff
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-110

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.111 Component Deep-Dive Block 111

```
COMPONENT BLOCK 111 — production notes

  Focus: S3 lifecycle: raw → Glacier after 90 days
  SLA impact: tier-1
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-111

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.112 Component Deep-Dive Block 112

```
COMPONENT BLOCK 112 — production notes

  Focus: MediaConvert acceleration: PREFERRED vs ENABLED
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-112

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.113 Component Deep-Dive Block 113

```
COMPONENT BLOCK 113 — production notes

  Focus: CloudFront signed URL key rotation
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-113

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.114 Component Deep-Dive Block 114

```
COMPONENT BLOCK 114 — production notes

  Focus: Kafka partition key: video_id for view ordering
  SLA impact: tier-1
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-114

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.115 Component Deep-Dive Block 115

```
COMPONENT BLOCK 115 — production notes

  Focus: Flink state backend: RocksDB for large windows
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-115

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.116 Component Deep-Dive Block 116

```
COMPONENT BLOCK 116 — production notes

  Focus: Elasticsearch refresh interval: 30s for search index
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-116

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.117 Component Deep-Dive Block 117

```
COMPONENT BLOCK 117 — production notes

  Focus: Aurora read replica lag monitoring
  SLA impact: tier-1
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-117

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.118 Component Deep-Dive Block 118

```
COMPONENT BLOCK 118 — production notes

  Focus: Redis cluster mode for view counter shards
  SLA impact: tier-2
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-118

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.119 Component Deep-Dive Block 119

```
COMPONENT BLOCK 119 — production notes

  Focus: SageMaker multi-model endpoint cost optimization
  SLA impact: tier-2
  Owner team: playback
  Runbook: https://wiki.internal/runbooks/yt-119

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```

### A.120 Component Deep-Dive Block 120

```
COMPONENT BLOCK 120 — production notes

  Focus: Upload chunk retry with exponential backoff
  SLA impact: tier-1
  Owner team: creator-platform
  Runbook: https://wiki.internal/runbooks/yt-120

  Operational checklist:
    □ Metric dashboards linked from service page
    □ Alert thresholds reviewed this quarter
    □ Load test passed at 2x peak (last: Q2 load test)
    □ Dependency circuit breakers configured
    □ On-call runbook updated within 30 days
```


---

> **Retention test moved:** Week 10 compound scenario (Global Video Outage)
> will live in Retention-Tests/Week-10.md per curriculum standards.
