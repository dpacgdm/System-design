# Design Photo Sharing Platform (Instagram / Flickr)

## Learning Objectives
```
╔════════════════════════════════════════════════════════════════╗
║   AFTER THIS MODULE, YOU WILL BE ABLE TO:                      ║
╟────────────────────────────────────────────────────────────────╢
║                                                                ║
║   1. Design a hyperscale photo sharing and media discovery     ║
║      platform serving 500M+ DAU and 100M daily media uploads   ║
║                                                                ║
║   2. Master direct-to-S3 client media uploads using            ║
║      pre-signed URLs to bypass API gateway buffer exhaustion   ║
║                                                                ║
║   3. Architect asynchronous media processing pipelines:        ║
║      WebP/AVIF compression, multi-size thumbnail generation,   ║
║      EXIF metadata stripping, and Blurhash placeholder creation║
║                                                                ║
║   4. Implement global CDN edge caching architectures with      ║
║      origin shields, content addressing, and immutable headers ║
║                                                                ║
║   5. Partition photo metadata across sharded PostgreSQL/Vitess ║
║      and design efficient user media grid queries              ║
║                                                                ║
║   6. Diagnose P0 production incidents: media worker queue      ║
║      meltdown, CDN origin shield bypass, and photo corruption  ║
╚════════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Upload 15MB high-resolution camera images      ║
║   directly through the API Gateway web servers"                    ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Proxying 15MB file uploads through API gateways ties up   ║
║   web server worker threads, bloats heap buffers, and exhausts     ║
║   TCP connection pools. Production apps request a Pre-signed URL   ║
║   from the API and stream raw bytes directly from device to S3.    ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "Generate image thumbnails synchronously inside ║
║   the user upload HTTP handler"                                    ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Resizing and transcoding a 15MB image to multiple sizes   ║
║   takes 800ms to 2,500ms of intense CPU time. Synchronous resizing ║
║   creates massive client latency and kills API throughput.         ║
║   Resizing must be handled asynchronously via Kafka & worker pods. ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "Store images on local web server disks or as   ║
║   database byte BLOBs"                                             ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Local disks make stateless autoscaling impossible and     ║
║   risk catastrophic data loss on pod restart. Database BLOBs ruin  ║
║   buffer cache efficiency. Image bytes belong strictly on cloud    ║
║   Object Storage (S3 / GCS) behind high-bandwidth CDNs.            ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "Purge CDN image caches whenever a user updates ║
║   their photo caption or tags"                                     ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Media files are content-addressed and immutable (e.g.     ║
║   `https://cdn.photos.com/p/a1b2c3d4_1080.webp`). Only post        ║
║   metadata in the database changes on caption edit. Image URLs     ║
║   never change, allowing 1-year immutable CDN edge caching.        ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "The mobile app should wait for full resolution ║
║   images to load before rendering the grid"                        ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Waiting for 500KB images causes blank, stuttering feeds   ║
║   on cellular networks. Production apps store a 30-character       ║
║   Blurhash string in the metadata DB, rendering instant pastel     ║
║   placeholders in < 5ms before media bytes arrive over the network.║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #6: "Preserve all original EXIF camera metadata on  ║
║   public image files"                                              ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. EXIF tags contain sensitive user privacy data: exact GPS  ║
║   latitude/longitude, phone serial numbers, and home addresses.    ║
║   Production media pipelines strictly strip EXIF metadata before   ║
║   publishing thumbnails to public CDN distributions.               ║
╚════════════════════════════════════════════════════════════════════╝
```

---

## Core Teaching

### 1. Requirements & Quantitative Capacity Sizing

#### Functional Requirements
1. **Photo Upload**: Users upload high-resolution photos (up to 20MB) with captions and tags.
2. **Media Optimization**: Automatically generate multiple thumbnail resolutions:
   - Thumbnail: 150 × 150 (WebP)
   - Medium Grid: 640 × 640 (WebP)
   - Full Screen: 1080 × 1350 (WebP / AVIF)
   - Low-res placeholder: Blurhash string
3. **User Profile Grid**: Fast browsing of a user's recent 30 photos with sub-50ms latency.
4. **Follow & Feed Integration**: When a user posts a photo, update followers' home timelines.

#### Non-Functional Requirements & SLAs
- **Durability**: 99.999999999% (11 9's durability for user photos).
- **Availability**: 99.99% for viewing; 99.9% for uploads.
- **Latency**: First-image load < 100ms via Edge CDN; upload processing completed < 3 seconds.

#### Quantitative Hardware & Sizing Estimations

```
SCALE ESTIMATION:
  - Daily Active Users (DAU) : 500 Million users
  - Daily Photo Uploads      : 100 Million photos / day
  - Daily Photo Views        : 10 Billion views / day (100:1 view-to-upload ratio)
  
  - Ingress Storage Sizing:
    → Average raw image size uploaded: ~2 MB
    → Daily raw ingest = 100M × 2 MB = 200 Terabytes / day
    → Transcoded Storage per photo:
        150x150 WebP   : ~10 KB
        640x640 WebP   : ~60 KB
        1080x1350 WebP : ~200 KB
        Total optimized: ~270 KB per photo
    → Daily optimized storage = 100M × 270 KB ≈ 27 TB / day
    → Annual storage footprint = 27 TB × 365 ≈ 9.85 Petabytes / year

  - Bandwidth Calculations:
    → Peak Upload Ingress (2x peak):
      (100M × 2 MB × 8 bits) / 86,400s ≈ 18.5 Gbps sustained ingress (37 Gbps peak)
    → Egress Bandwidth (Photo Views):
      10 Billion views / day × 150 KB (average viewed size) × 8 bits / 86,400s
      ≈ 138.8 Gbps sustained egress (277 Gbps peak)
    → CDN Cache Hit Ratio target: 95%
    → Origin Shield Egress = 277 Gbps × 0.05 ≈ 13.85 Gbps (Protects origin S3 bucket!)
```

---

### 2. High-Level Design (HLD) Box-and-Arrow Architecture

```
                                 [ Mobile App / Browser ]
                                             │
                        1. POST /upload-intent│ 3. Stream Raw Image
                           (Request URL)     │    directly via PUT
                                             ▼
                               ┌───────────────────────────┐
                               │   API Gateway & Auth      │
                               │   (Envoy Proxy)           │
                               └─────────────┬─────────────┘
                                             │
               ┌─────────────────────────────┴─────────────────────────────┐
               │ 2. Issue Pre-signed S3 URL                                │ 4. Direct Upload
               ▼                                                           ▼
┌─────────────────────────────┐                             ┌─────────────────────────────┐
│    Photo Metadata Svc       │                             │    S3 Ingestion Bucket      │
│  (Sharded PostgreSQL)       │                             │   (raw-uploads-temp)        │
└─────────────────────────────┘                             └──────────────┬──────────────┘
                                                                           │
                                                              5. S3 Object │ Created Event
                                                                 (Event)   │
                                                                           ▼
                                                            ┌─────────────────────────────┐
                                                            │     Kafka Media Queue       │
                                                            │   (Topic: photo_processing) │
                                                            └──────────────┬──────────────┘
                                                                           │
                                                                           │ 6. Consume Event
                                                                           ▼
                                                            ┌─────────────────────────────┐
                                                            │   Media Processing Fleet    │
                                                            │  - Strip EXIF GPS Data      │
                                                            │  - Generate WebP Resizes    │
                                                            │  - Compute Blurhash String  │
                                                            └──────────────┬──────────────┘
                                                                           │
                     ┌─────────────────────────────────────────────────────┴─────────────────────────┐
                     │ 7. Write Thumbnails                                                           │ 8. Update Record
                     ▼                                                                               ▼
      ┌─────────────────────────────┐                                                 ┌─────────────────────────────┐
      │     S3 Production Bucket    │                                                 │    Photo Metadata DB        │
      │  (photos-public-prod)       │                                                 │  (Status = 'READY')         │
      └──────────────┬──────────────┘                                                 └─────────────────────────────┘
                     │
                     │ Origin Fetch
                     ▼
      ┌─────────────────────────────┐
      │     Origin Shield & CDN     │ ◄──────────────── User View Requests (GET /cdn/photo.webp)
      │    (Cloudflare / Fastly)    │
      └─────────────────────────────┘
```

#### Native Mermaid Architecture Schematic

```mermaid
flowchart TD
    subgraph ClientTier[Client Layer]
        App[Mobile / Web App]
    end

    subgraph APITier[API Gateway]
        Gateway[Envoy Ingress Gateway]
        MetaDB[(Photo Metadata DB)]
    end

    subgraph IngestionStorage[Raw Ingest Bucket]
        S3Raw[(S3: raw-uploads-temp)]
    end

    subgraph PipelineCluster[Async Processing Pipeline]
        Kafka[Kafka: photo_process_queue]
        Workers[Media Processing Worker Fleet]
    end

    subgraph PublicStorage[Production Assets]
        S3Prod[(S3: photos-public-prod)]
        CDN[CloudFront / Fastly Edge CDN]
    end

    App -->|1. Request Pre-signed URL| Gateway
    Gateway -->|2. Create Pending Record| MetaDB
    Gateway -->|3. Return Pre-signed PUT URL| App

    App -->|4. Direct Stream Upload (15MB)| S3Raw
    S3Raw -.->|5. S3:ObjectCreated Notification| Kafka
    Kafka --> Workers

    Workers -->|6. Strip EXIF + Generate WebP Resizes| Workers
    Workers -->|7. Store 150px, 640px, 1080px| S3Prod
    Workers -->|8. Update Status='READY' + Blurhash| MetaDB

    App -->|9. View Photo: GET /cdn/photo.webp| CDN
    CDN -->|Cache Miss| S3Prod
```

---

### 3. Deep Dive into Pre-signed Uploads & Blurhash

#### Subsystem A: Direct Pre-signed Upload Flow

```
STEP 1: Client sends POST /api/v1/photos/upload-intent
        Payload: { "file_size": 8388608, "content_type": "image/jpeg" }

STEP 2: Server generates cryptographically signed AWS S3 PUT URL:
        https://raw-bucket.s3.amazonaws.com/uploads/2026/09/user_42/photo_89a.jpg?
        X-Amz-Algorithm=AWS4-HMAC-SHA256&
        X-Amz-Credential=...&
        X-Amz-Date=20260910T120000Z&
        X-Amz-Expires=900&
        X-Amz-Signature=...

STEP 3: Client streams bytes directly to S3 via HTTP PUT.
        Zero bytes touch your API Gateway or microservice memory!
```

#### Subsystem B: Go Media Transcoding Worker with Blurhash

```go
package worker

import (
	"bytes"
	"context"
	"image"
	"image/jpeg"
	_ "image/png"

	"github.com/bbrks/go-blurhash"
	"github.com/disintegration/imaging"
)

type ProcessedMedia struct {
	Thumbnail150 []byte
	Grid640      []byte
	Full1080     []byte
	Blurhash     string
}

func ProcessRawImage(rawBytes []byte) (*ProcessedMedia, error) {
	// 1. Decode Image (Automatically strips EXIF orientation)
	src, err := imaging.Decode(bytes.NewReader(rawBytes), imaging.AutoOrientation(true))
	if err != nil {
		return nil, err
	}

	// 2. Generate Blurhash Placeholder (32-character string for instant UI render)
	blurhashStr, err := blurhash.Encode(4, 3, src)
	if err != nil {
		blurhashStr = "LEHLh[WB2yk8pyoJadR*.7kCMdnj" // safe fallback
	}

	// 3. Parallel Thumbnail Generation
	thumb150 := imaging.Fill(src, 150, 150, imaging.Center, imaging.Lanczos)
	grid640 := imaging.Resize(src, 640, 0, imaging.Lanczos)
	full1080 := imaging.Resize(src, 1080, 0, imaging.Lanczos)

	// 4. Encode to Optimized JPEG/WebP
	var b150, b640, b1080 bytes.Buffer
	_ = jpeg.Encode(&b150, thumb150, &jpeg.Options{Quality: 80})
	_ = jpeg.Encode(&b640, grid640, &jpeg.Options{Quality: 85})
	_ = jpeg.Encode(&b1080, full1080, &jpeg.Options{Quality: 90})

	return &ProcessedMedia{
		Thumbnail150: b150.Bytes(),
		Grid640:      b640.Bytes(),
		Full1080:     b1080.Bytes(),
		Blurhash:     blurhashStr,
	}, nil
}
```

---

### 4. Storage Schemas & Database Models

#### PostgreSQL Photo Metadata Schema (`schema.sql`)

```sql
CREATE TABLE photos (
    photo_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    caption TEXT,
    blurhash VARCHAR(36) NOT NULL, -- Compact 32-36 char UI placeholder string
    width INT NOT NULL,
    height INT NOT NULL,
    media_url_150 VARCHAR(512),
    media_url_640 VARCHAR(512),
    media_url_1080 VARCHAR(512),
    status VARCHAR(32) NOT NULL DEFAULT 'UPLOADING',
    -- UPLOADING, PROCESSING, READY, FAILED, DELETED
    like_count BIGINT NOT NULL DEFAULT 0,
    comment_count BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- User Grid Index: Enables instant loading of user's most recent 30 photos
CREATE INDEX idx_photos_user_grid ON photos (user_id, created_at DESC)
WHERE status = 'READY';
```

---

## SRE Diagnostic Toolkit

### 1. Prometheus Telemetry & Alerts

```promql
# Alert: Transcoding Queue Processing Delay (Queue delay > 15s)
histogram_quantile(0.99, sum(rate(media_transcode_queue_delay_seconds_bucket[5m])) by (le)) > 15.0

# Alert: CDN Origin Shield Cache Miss Spike (Hit ratio < 90%)
sum(rate(cdn_cache_hits_total[5m])) / 
(sum(rate(cdn_cache_hits_total[5m])) + sum(rate(cdn_cache_misses_total[5m]))) < 0.90

# Alert: S3 Upload Abort Spike (> 5% client uploads failing)
sum(rate(s3_upload_failures_total[5m])) / sum(rate(s3_upload_attempts_total[5m])) > 0.05
```

### 2. CDN Cache-Control Header Tuning

```http
# Media headers returned by Origin Shield to Edge CDN PoPs
HTTP/1.1 200 OK
Content-Type: image/webp
Cache-Control: public, max-age=31536000, immutable
ETag: "98bf4a12e823"
Access-Control-Allow-Origin: *
```

---

## Decision Framework

| Requirement / Component | Recommended Architecture | Rejected Alternative | Engineering Rationale |
| :--- | :--- | :--- | :--- |
| **Media Ingest Path** | `Direct-to-S3 via Pre-Signed PUT URLs` | `Upload through API Gateway Web Pods` | Proxying 15MB files through Envoy/Nginx exhausts connection pools and saturates container RAM. |
| **Image Formatting** | `WebP / AVIF with Responsive Sizes` | `Original Raw JPEG Only` | WebP reduces payload sizes by 35% compared to JPEG, saving Petabytes of monthly CDN egress bandwidth. |
| **Feed Loading UX** | `Blurhash Strings in Metadata DB` | `Loading Spinners / Blank Rectangles` | Blurhash renders instant pastel placeholders in < 5ms before media loads, eliminating perceived network latency. |
| **CDN Architecture** | `Origin Shield + Regional Edge Caches` | `Direct S3 Hits on Cache Miss` | Origin Shield coalesces thousands of concurrent edge cache misses into a single request, protecting S3. |

---

## Failure Modes

### Failure Mode 1: Media Processing Queue Saturation During Global Event
- **Failure Trigger**: Millions of users simultaneously upload celebration photos at midnight on New Year's Eve. Media worker queue length spikes to 10M messages.
- **Cascading Impact**: Processing latency exceeds 45 minutes; users post duplicate photos assuming uploads failed; worker CPU hits 100%.
- **SRE Containment**:
  1. Implement **Tiered Priority Transcoding**: Generate the small 640px grid thumbnail first and mark status `READY` in 400ms so the post appears in feeds immediately; defer heavy 1080px archival encoding to a low-priority background queue.
  2. Autoscaling: Scale worker pod count dynamically using KEDA (Kubernetes Event-driven Autoscaling) based on Kafka queue depth.

### Failure Mode 2: EXIF GPS Data Leakage Vulnerability
- **Failure Trigger**: A developer refactors image transcoding logic to stream raw buffers directly without passing through the metadata-stripping filter.
- **Cascading Impact**: Public users download full resolution images containing precise GPS coordinates of user private residences, creating a severe privacy and regulatory breach.
- **SRE Containment**:
  1. Enforce **Automated Image Sanitation Unit Tests**: Pipeline checks must fail build if any EXIF tag (`0x8825 GPSInfo`) is detected in output byte buffers.
  2. Implement **Origin-Level Gateway Verification**: An Envoy lua filter inspects outgoing image headers and blocks any image carrying EXIF markers.

---

## 🛑 SOCRATIC CHECK

### Question 1:
Why should the client request a Pre-signed URL using HTTP `POST` instead of an HTTP `GET` request?

### Question 2:
How does a CDN Origin Shield prevent S3 from being overwhelmed during a "thundering herd" event when a celebrity with 100M followers posts a photo?

### Question 3:
If an image is uploaded and later deleted by the user, how do you handle CDN cache purging without incurring massive CDN invalidation API costs?
