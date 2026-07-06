# Mock Interview 05 — Design Uber (Ride-Sharing Platform)

> **Week 15 — Mock Interviews** | 45-minute timed session  
> **Prerequisites:** Week 8 (Geospatial Systems), Week 10 (Design Uber), Week 6 (Kafka), Week 2 (Caching)  
> **Level target:** L5–L6 (Senior / Staff)  
> **Interviewer persona:** Engineering Manager, Mobility Platform team

---

## Learning Objectives

```
╔════════════════════════════════════════════════════════════════════╗
║   AFTER THIS MOCK INTERVIEW, YOU WILL BE ABLE TO:                  ║
╟────────────────────────────────────────────────────────────────────╢
║                                                                    ║
║   1. Run a complete 45-minute interview for "design Uber" —        ║
║      real-time rider-driver matching at 1M concurrent rides        ║
║      globally with correct scope and capacity math                 ║
║                                                                    ║
║   2. Deep-dive on geospatial indexing: compare geohash, S2,        ║
║      and H3; design a two-phase candidate retrieval pipeline       ║
║      that scales to millions of moving driver locations            ║
║                                                                    ║
║   3. Explain dispatch algorithm mechanics: batch offers,           ║
║      scoring function, trip state machine, and double-match        ║
║      prevention                                                    ║
║                                                                    ║
║   4. Design surge pricing: zone definition, supply/demand          ║
║      ratio, smoothing, upfront pricing, and anti-gaming            ║
║                                                                    ║
║   5. Design ETA prediction layers and how ETA feeds matching       ║
║      decisions (not straight-line distance)                        ║
║                                                                    ║
║   6. Diagnose mobility failure modes: ghost drivers, double        ║
║      matching, location staleness, and payment-at-trip-end         ║
║      with detection and mitigation                                 ║
╚════════════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔══════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Match to nearest driver by straight-line         ║
║   distance"                                                          ║
╟──────────────────────────────────────────────────────────────────────╢
║   WRONG. Road network distance ≠ haversine. A driver 500m away       ║
║   across a river may be 15 min by road. Geospatial index gets        ║
║   candidates; routing engine gets ETA for dispatch scoring.          ║
║   Week 8 and Week 10 are explicit on the two-phase query.            ║
╠══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "SELECT * FROM drivers ORDER BY distance"         ║
╟──────────────────────────────────────────────────────────────────────╢
║   WRONG. O(n) over millions of moving points is impossible at        ║
║   match time. Use geohash prefix, S2 cell covering, or H3 k-ring     ║
║   with inverted index per cell — then refine with routing ETA.       ║
╠══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "Every GPS ping writes to PostgreSQL"             ║
╟──────────────────────────────────────────────────────────────────────╢
║   WRONG. 4M drivers × 1 update/4 sec ≈ 1M location writes/sec.       ║
║   Hot path: WebSocket → Kafka → in-memory geo index (Redis/H3).      ║
║   Historical trail to cold storage for analytics only.               ║
╠══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "Surge = multiply fare by 2"                      ║
╟──────────────────────────────────────────────────────────────────────╢
║   WRONG. Surge is zone-based (H3 cells), time-varying, smoothed,     ║
║   capped, and shown upfront before rider confirms. Must balance      ║
║   driver incentive vs rider churn. Sticky surge changes UX.          ║
╠══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Dispatch one driver at a time"                   ║
╟──────────────────────────────────────────────────────────────────────╢
║   WRONG at scale. Batch dispatch — offer to top N drivers            ║
║   simultaneously; first accept wins. Serial dispatch is slow and     ║
║   unfair. Must prevent double-matching with atomic trip assignment.  ║
╚══════════════════════════════════════════════════════════════════════╝
```

---

## Problem Statement (Give This to the Candidate)

```
PROMPT (read verbatim at minute 0):

  "Design a ride-sharing platform like Uber. Riders request rides,
   the system matches them with nearby drivers in real time, tracks
   the trip, and handles payment at the end.

   Scale:
     • 1 million concurrent active rides globally at peak
     • 20 million rides completed per day
     • 4 million drivers online at peak (location updating)
     • Operates in 50+ countries (multi-region)

   Core flows:
     • Rider requests ride → matched with driver → live tracking → payment
     • Surge pricing when demand exceeds supply
     • ETA shown before rider confirms and during trip

   Non-functional:
     • p99 match latency (request → driver assigned): < 15 seconds
     • p99 location freshness on map: < 5 seconds
     • 99.95% availability for match + trip tracking
     • Payment must not double-charge on retries

   Out of scope unless candidate asks:
     • Pool/shared rides, scheduled rides, freight
     • Driver onboarding / KYC
     • Full fraud ML pipeline

   You have 45 minutes. I'll redirect for depth on specific areas."
```

---

## 45-Minute Timed Schedule

```
╔══════════════════════════════════════════════════════════════════════╗
║   MINUTE  0–5  │ Requirements clarification                          ║
║   MINUTE  5–12 │ Capacity estimation (rides, locations, QPS)         ║
║   MINUTE 12–18 │ API & data model (trip state machine)               ║
║   MINUTE 18–28 │ High-level architecture                             ║
║   MINUTE 28–40 │ Deep dive (geospatial, dispatch, surge, ETA)        ║
║   MINUTE 40–45 │ Failure modes, wrap-up, candidate questions         ║
╠══════════════════════════════════════════════════════════════════════╣
║   INTERVIEWER CHECKPOINTS:                                           ║
║   • Minute 5:  candidate distinguishes match latency vs ETA          ║
║   • Minute 12: location write QPS computed (~1M/sec)                 ║
║   • Minute 28: architecture shows location path separate from        ║
║                trip/match path                                       ║
║   • Minute 40: ghost drivers + double matching addressed             ║
╠══════════════════════════════════════════════════════════════════════╣
║   IF BEHIND AT MINUTE 20: skip payment detail; draw match flow.      ║
║   IF AHEAD AT MINUTE 35: inject airport geofence constraint.         ║
╚══════════════════════════════════════════════════════════════════════╝
```

---

## Interviewer Script

### Minute 0–5: Opening & Requirements

```
INTERVIEWER (minute 0):
  "Design Uber — ride matching at scale, 1M concurrent rides globally.
   You have 45 minutes. Start with clarifying questions."

  [Wait. Take notes. Do not lead.]

GOOD CANDIDATE QUESTIONS (score 3–4):
  → "Match latency target — how fast must driver be assigned?"
  → "Location update frequency from driver app?"
  → "Surge pricing — shown before or after match?"
  → "Payment timing — end of trip? Pre-auth?"
  → "Vehicle types — UberX, XL, separate pools?"
  → "Cross-region — one global system or per-market?"
  → "Read vs write ratio on location updates?"
  → "Acceptable staleness for driver position in matching?"

INTERVIEWER PROBES (if silent after 2 min):
  "What's the difference between matching a driver and computing ETA?"
  "Can a driver be matched to two riders simultaneously?"

INTERVIEWER (minute 5 — transition):
  "Scope: UberX only, payment at trip end with pre-auth hold,
   surge shown upfront, 15-second match p99, driver location
   stale after 15 seconds excluded from matching. Good?"
```

### Minute 5–12: Capacity Estimation

```
INTERVIEWER (minute 5):
  "Size the system. Location writes, match QPS, storage."

  [Let candidate compute. Nudge if stuck 60+ seconds.]

EXPECTED ANCHORS:
  → 20M rides/day ≈ 230 rides/sec avg; peak 3× ≈ 700/sec
  → 1M concurrent rides (given — use for state storage)
  → 4M drivers / 4 sec update ≈ 1M location writes/sec
  → Match requests track ride creation ≈ 700/sec peak

INTERVIEWER PROBE (minute 10):
  "1M location writes/sec — can you write every ping to Postgres?"
```

### Minute 12–18: API & Data Model

```
INTERVIEWER (minute 12):
  "Core APIs and trip state machine."

  [Expect: request ride, accept, start, complete, cancel;
   trip statuses; idempotency keys.]

INTERVIEWER PROBE:
  "How do you prevent the same driver being assigned twice
   in a 500ms window?"
```

### Minute 18–28: Architecture

```
INTERVIEWER (minute 18):
  "Draw the architecture. Separate location ingestion from matching."

  [Expect: rider/driver apps → gateway → trip service, dispatch,
   location service, pricing, Redis/H3 geo index, Kafka, DynamoDB.]

INTERVIEWER PROBES:
  "Where does surge multiplier get computed?"
  "How does rider see driver moving on the map in real time?"
```

### Minute 28–40: Deep Dive

```
INTERVIEWER (minute 28 — pick path):

  PATH A — Geospatial Indexing:
    "Compare geohash vs H3 for driver indexing. Which do you pick
     and why? How do you handle a cell boundary?"

  PATH B — Dispatch Algorithm:
    "Walk through matching from ride request to driver assigned.
     Batch or serial? What's the scoring function?"

  PATH C — Surge Pricing:
    "Friday night downtown — demand 3× supply. How is multiplier
     calculated, smoothed, and displayed?"

  PATH D — ETA:
    "Rider sees '4 min away.' How is that computed? What if traffic
     changes mid-trip?"

INTERVIEWER (minute 32 — constraint):
  "Airport has a virtual queue — drivers must be in geofence to receive
   airport requests. How does that change matching?"

INTERVIEWER (minute 37):
  "Trip ends. Payment fails on first attempt. Walk me through retry
   without double-charging."
```

### Minute 40–45: Failure Modes & Close

```
INTERVIEWER (minute 40):
  "Three things that break in production for this system."

INTERVIEWER (minute 43):
  "30-second summary. V1 vs v2 scope."

INTERVIEWER (minute 45):
  "Questions for me?"
```

---

## Candidate Expectations

### Requirements Phase (Score 3+)

```
FUNCTIONAL (ranked):
  P0: Request ride, match driver, track trip live, complete + pay
  P0: Surge pricing visible before confirm
  P0: ETA for pickup and trip duration
  P1: Cancel ride (rider/driver)
  P1: Rating after trip
  P2: Pool, scheduled rides

NON-FUNCTIONAL:
  → 1M concurrent rides (state in memory + durable store)
  → p99 match < 15 sec
  → Location freshness < 5 sec on map
  → 99.95% availability match + tracking
  → Idempotent payment (no double charge)

DESIGN DRIVER:
  "Location write throughput (1M/sec) and sub-second geo queries
   are the constraints — matching cannot scan all drivers."
```

### Capacity Phase (Score 3+)

```
RIDES:
  20M rides/day ÷ 86,400 ≈ 231 rides/sec average
  Peak factor 3× ≈ 700 ride requests/sec
  1M concurrent × ~2 KB trip state ≈ 2 GB hot trip state
    (plus indexes, replicas → Redis/DynamoDB sharded)

LOCATION WRITES:
  4M drivers ÷ 4 sec interval = 1M updates/sec peak
  ~50 bytes/update on wire × 1M = 50 MB/s ingress
  NOT every write hits durable DB — geo index is source of truth
    for matching; Kafka → processor → Redis/H3

MATCHING QPS:
  ~700/sec peak (matches ride creation rate)
  Each match: geo query + 20 ETAs + scoring ≈ 50ms budget

STORAGE (trips, 5-year retention for disputes):
  20M/day × 5 KB/trip × 365 × 5 ≈ 18 TB (DynamoDB/S3 archive)

GEO INDEX MEMORY:
  4M drivers × 100 bytes (id + cell + metadata) ≈ 400 MB
  Fits Redis cluster per region — sharded by geohash prefix
```

### Architecture Phase (Score 3+)

```
MINIMUM VIABLE DIAGRAM:

  Rider App ──┐
              ├──► API Gateway / ALB
  Driver App ─┘         │
         │              ├──► Trip Service ──► DynamoDB (trips)
         │              ├──► Dispatch Service
         │              ├──► Pricing / Surge Service
         │              └──► Location Gateway (WebSocket)
         │                        │
         │                        ▼
         │                   Kafka: location-updates
         │                        │
         │                        ▼
         │              Location Processor (Flink)
         │                        │
         │              ┌─────────┴─────────┐
         │              ▼                   ▼
         │         Redis GEO /          Analytics → S3
         │         H3 Index
         │              │
         └──────────────┼──► Dispatch reads candidates
                        │
              Maps / Routing API (ETA)
                        │
              Payment Service (Stripe) ← trip complete
```

---

## Capacity Estimation — Worked Solution

```
STEP 1: RIDE THROUGHPUT
━━━━━━━━━━━━━━━━━━━━━━━

  Daily rides:           20,000,000
  Average QPS:           20M / 86400 ≈ 231/sec
  Peak (3×):             ~700/sec
  Concurrent (given):    1,000,000 active trips

  Trip state size:       ~2 KB (ids, coords, status, fare estimate)
  Hot state memory:      1M × 2 KB = 2 GB (one region's share
                         if globally sharded — ~200K concurrent
                         per major region)

STEP 2: LOCATION INGEST
━━━━━━━━━━━━━━━━━━━━━━━

  Online drivers:        4,000,000 peak (global)
  Update interval:       4 seconds (typical Uber driver app)
  Write QPS:             4M / 4 = 1,000,000 updates/sec

  Per update payload:    ~50–80 bytes (driver_id, lat, lng, ts, heading)
  Bandwidth:             1M × 60 B ≈ 60 MB/s ingress (location only)

  CRITICAL INSIGHT:
    Cannot persist 1M writes/sec to Postgres.
    Path: WebSocket gateway → Kafka (partition by driver_id)
    → stream processor → in-memory geo index (Redis/H3)
    → optional downsampled trail to S3 for analytics

STEP 3: MATCHING LOAD
━━━━━━━━━━━━━━━━━━━━━

  Match requests/sec:    ~700 peak (one per new ride)
  Per match:
    Geo lookup:          1–9 cell queries (H3 k-ring)
    Candidates:          ~50 drivers after filter
    ETA calls:           10–20 (batch to routing service)
    Target latency:      p99 < 200ms for geo+ETA phase

  Routing service QPS: 700 × 15 ETAs ≈ 10,500 QPS peak
    → Cache ETAs by (driver_cell, pickup_cell) for 30 sec
    → Reduces to ~2,000 unique QPS with cache

STEP 4: WEBSOCKET FAN-OUT (LIVE TRACKING)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1M concurrent rides × 1 rider watching driver
  Location update every 4 sec to rider: 250K pushes/sec
  Use regional pub/sub (Redis Pub/Sub, or dedicated push gateway)
  Connection sharding: 250K/sec per region, not global

STEP 5: PAYMENT
━━━━━━━━━━━━━━━

  Completed rides/sec:   ~700 peak (same as creation)
  Pre-auth at match:     hold estimated fare × 1.2
  Capture at complete:   idempotent capture by trip_id
  Storage:               payment_intent_id indexed by trip_id
```

---

## API & Data Model

### Core APIs

```
POST /v1/rides
  Request:
  {
    "rider_id": "r_123",
    "pickup": { "lat": 37.7749, "lng": -122.4194 },
    "dropoff": { "lat": 37.7849, "lng": -122.4094 },
    "vehicle_type": "UBERX",
    "payment_method_id": "pm_456",
    "idempotency_key": "uuid-789"
  }
  Response:
  {
    "trip_id": "t_abc",
    "status": "MATCHING",
    "surge_multiplier": 1.5,
    "estimated_fare": { "min": 12.50, "max": 15.00, "currency": "USD" },
    "pickup_eta_sec": null   // populated when matched
  }

GET /v1/rides/{trip_id}
  → status, driver info, live location, fare

POST /v1/rides/{trip_id}/cancel
  → cancellation fee rules

POST /v1/drivers/{driver_id}/location
  (WebSocket preferred — HTTP fallback for debugging)
  {
    "lat": 37.7750, "lng": -122.4190,
    "heading": 90, "speed_mps": 8.5,
    "timestamp": 1712345678900
  }

POST /v1/drivers/{driver_id}/offers/{offer_id}/accept
  → atomic accept; 409 if already assigned

POST /v1/rides/{trip_id}/complete
  → triggers fare calculation + payment capture
```

### Trip State Machine

```
STATES:

  REQUESTED    → rider submitted; validating payment method
  MATCHING   → dispatch searching / offering drivers
  DRIVER_ASSIGNED → driver accepted; en route to pickup
  DRIVER_ARRIVING   → driver within 500m (geofence trigger)
  IN_PROGRESS       → rider picked up; en route to dropoff
  COMPLETED         → arrived; payment processing
  PAYMENT_SETTLED   → terminal success
  CANCELLED         → terminal (rider/driver/system)
  NO_DRIVERS        → terminal (match timeout)

TRANSITIONS (simplified):

  REQUESTED → MATCHING          : payment pre-auth OK
  MATCHING → DRIVER_ASSIGNED    : driver accept (atomic)
  MATCHING → NO_DRIVERS         : timeout 3 waves (~45 sec)
  DRIVER_ASSIGNED → DRIVER_ARRIVING : GPS geofence
  DRIVER_ARRIVING → IN_PROGRESS : driver starts trip
  IN_PROGRESS → COMPLETED       : driver ends trip
  COMPLETED → PAYMENT_SETTLED   : capture success
  * → CANCELLED                 : cancel rules per state

CONCURRENCY RULE:
  Driver status: AVAILABLE | OFFER_PENDING | ON_TRIP | OFFLINE
  Accept transitions AVAILABLE → ON_TRIP atomically (compare-and-set)
```

### Data Stores

```
DynamoDB — Trips:
  PK: trip_id
  Attributes: rider_id, driver_id, status, pickup, dropoff,
              surge_multiplier, fare, version (optimistic lock)
  GSI: rider_id + created_at
  GSI: driver_id + status (active trip lookup)

Redis — Driver Location Index:
  Option A: GEOADD drivers:{region} lng lat driver_id
            GEORADIUS for candidates
  Option B: H3 cell → SET of driver_ids
            Key: h3:{cell_id} → {driver_id: last_seen_ts}

Redis — Driver State:
  driver:{id} → { status, vehicle_type, current_trip_id, rating }

DynamoDB — Surge Zones:
  PK: h3_cell_id (res-7)
  surge_multiplier, demand_count, supply_count, updated_at

Aurora/Postgres — Users, payment methods (low QPS)

Kafka Topics:
  location-updates (key=driver_id, 1M/sec)
  trip-events (created, matched, completed)
  surge-events (zone recalculation)
```

---

## High-Level Architecture

```
                         UBER — PRODUCTION ARCHITECTURE
                         ══════════════════════════════

  ┌──────────────┐                    ┌──────────────┐
  │  Rider App   │                    │  Driver App  │
  │  (map, fare) │                    │  (GPS stream)│
  └──────┬───────┘                    └──────┬───────┘
         │  HTTPS / WebSocket                 │ WebSocket (persistent)
         └──────────────┬─────────────────────┘
                        ▼
              ┌─────────────────┐
              │  API Gateway    │
              │  + L7 LB        │
              │  (rate limit)   │
              └────────┬────────┘
                       │
     ┌─────────────────┼─────────────────┬──────────────────┐
     ▼                 ▼                 ▼                  ▼
┌─────────┐    ┌──────────────┐  ┌────────────┐   ┌─────────────┐
│ Trip    │    │ Dispatch /   │  │ Pricing /  │   │ Location    │
│ Service │    │ Matching     │  │ Surge      │   │ Gateway     │
└────┬────┘    └──────┬───────┘  └─────┬──────┘   └──────┬──────┘
     │                │                │                  │
     │                │                │                  ▼
     │                │                │           Kafka: location-updates
     │                │                │                  │
     │                ▼                │                  ▼
     │         ┌──────────────┐        │         Location Processor
     │         │ H3 / Redis   │◄───────┼─────────────────┘
     │         │ Geo Index    │        │
     │         └──────┬───────┘        │
     │                │                │
     ▼                ▼                ▼
┌─────────────────────────────────────────────┐
│ DynamoDB (trips) │ Redis (state) │ Aurora    │
└─────────────────────────────────────────────┘
     │                                    │
     ▼                                    ▼
┌─────────────┐                  ┌─────────────────┐
│ Payment Svc │                  │ Maps / Routing  │
│ (Stripe)    │                  │ (ETA engine)    │
└─────────────┘                  └─────────────────┘

MATCH FLOW (numbered):
  1. Rider POST /rides → Trip Service creates trip (MATCHING)
  2. Pricing Service returns surge + fare estimate (H3 pickup cell)
  3. Dispatch receives MatchTrip(trip_id, pickup, vehicle_type)
  4. Geo index: H3 k-ring(res-9) → 50 candidate driver_ids
  5. Filter: status=AVAILABLE, not stale (<15s), vehicle match
  6. Routing: batch ETA pickup for top 20 candidates
  7. Score: w1×(-ETA) + w2×rating + w3×fairness
  8. Batch offer to top 3 drivers via push notification
  9. First accept: atomic CAS driver AVAILABLE→ON_TRIP, trip→ASSIGNED
  10. No accept in 15s → expand k-ring, repeat (max 3 waves)

LOCATION FLOW:
  1. Driver app streams GPS every 4s on WebSocket
  2. Location Gateway validates, publishes to Kafka
  3. Processor updates H3 index + Redis driver state
  4. Pub/sub pushes to rider's WebSocket if on active trip
  5. Stale rule: no update 15s → remove from index, status OFFLINE
```

---

## Deep Dive — Interviewer Reference

### 1. Geospatial Indexing (Geohash / S2 / H3)

```
TWO-PHASE QUERY (Week 8):

  Phase 1 — SPATIAL INDEX (cheap):
    Reduce 4M drivers → ~20–100 candidates via cell lookup

  Phase 2 — REFINEMENT (expensive, small set):
    Road-network ETA, business rules, scoring

GEOHASH:
  base32(lat,lng) → prefix string, e.g. "9q8yyk"
  Precision 7 ≈ 150m × 150m cell
  Query: cell + 8 neighbors (boundary bug — neighbors not always adjacent)
  Redis: GEORADIUS or prefix SCAN
  DynamoDB: GSI on geohash prefix (hot partition risk downtown)

S2 (Google):
  Hilbert curve on sphere → 64-bit cell ID
  Level 14 ≈ 1 km²
  Good for global polygon coverage
  Used at scale in Google Maps infrastructure

H3 (Uber open source):
  Hexagonal grid, resolution 9 ≈ 0.1 km² urban
  6 uniform neighbors (+ pentagon edge cases)
  k_ring(center, 1) = 7 cells; k=2 = 19 cells
  Clean aggregation for surge heatmaps (parent cell rollup)
  Uber uses H3 for supply/demand zones and driver indexing

INTERVIEW RECOMMENDATION (score 4):
  "H3 for driver index and surge zones — hex uniformity and k-ring
   expansion. Geohash for simple Redis GEORADIUS if team knows it.
   PostGIS for airport polygon geofences in ops DB.
   Two indexes is normal."

HOT CELL MITIGATION (Week 8):
  Downtown SF: 3,000 drivers in one H3 cell
  → Finer resolution (res-10), or shard cell key with suffix
  → DynamoDB: geohash_7#shard_0..3

STALENESS FILTER:
  updated_at > now() - 15 seconds
  Exclude drivers with no ping — prevents ghost drivers
```

### 2. Dispatch Algorithm

```
BATCH DISPATCH (production pattern):

  Serial (bad):
    Offer closest → wait 15s → next
    Slow; unfair to driver #2 who was 30s away

  Batch (Uber):
    Score top 20 → offer to top 3 simultaneously
    First accept wins → cancel other offers
    15s timeout → next wave with expanded radius

SCORING FUNCTION (multi-objective):

  score = w1 × (-ETA_pickup_sec)
        + w2 × driver_rating
        + w3 × fairness_bonus
        + w4 × destination_direction_match  (optional)

  NOT straight-line distance — ETA from routing engine

  Weights tuned per market (Manhattan ≠ suburban)

DOUBLE-MATCH PREVENTION:

  Problem: two rides accept same driver in 500ms window

  Solution — atomic conditional update:
    UPDATE driver SET status='ON_TRIP', trip_id=:tid
    WHERE driver_id=:did AND status='AVAILABLE'
    → if affected_rows=0, reject accept

  DynamoDB: ConditionExpression status = :available
  Redis: SETNX driver:{id}:lock with TTL

  Trip side: version field optimistic locking

MATCH TIMEOUT:
  Wave 1: k-ring 1, batch 3, wait 15s
  Wave 2: k-ring 2, batch 5, wait 15s
  Wave 3: k-ring 3, batch 5, wait 15s
  → NO_DRIVERS; suggest retry or schedule

AIRPORT GEofence (constraint injection):
  Separate queue: drivers in airport polygon get airport requests
  FIFO or priority queue within geofence — not geo radius match
```

### 3. Surge Pricing

```
ZONE DEFINITION:
  H3 resolution 7 (~5 km²) or custom polygon
  Metrics per zone, rolling 5-minute window:
    demand = ride_requests (not yet matched)
    supply = available_drivers in cell

  ratio = demand / max(supply, 1)

MULTIPLIER CURVE (illustrative):
  ratio < 1.2   → 1.0×
  ratio 1.2–1.5 → 1.2×
  ratio 1.5–2.0 → 1.5×
  ratio 2.0–3.0 → 2.0×
  ratio > 3.0   → min(3.0, formula)  [cap]

SMOOTHING:
  EMA on multiplier — prevent 1.0 → 3.0 jump in one tick
  "Sticky surge" — rider sees locked multiplier from request time

UPFRONT PRICING:
  Fare estimate shown BEFORE rider confirms
  Locked for rider; driver payout per market rules (e.g., 75% surge)

COMPUTATION PATH:
  Location + trip events → Flink windowed aggregation
  → update DynamoDB surge table every 30–60 sec
  → Pricing Service reads cell multiplier at request time

ANTI-GAMING:
  Coordinated driver offline to spike surge → detect cluster
  Phantom surge (multiplier without wait time) → UX trust issue
  Cap duration and magnitude; manual review queue
```

### 4. ETA Prediction

```
ETA = pickup_ETA + trip_ETA (shown separately to rider)

LAYER 1 — ROUTING ENGINE:
  OSRM / Google Directions / AWS Location Service
  Road network graph + live traffic overlay
  Returns base duration seconds

LAYER 2 — ML CORRECTION:
  Features: hour, day, weather, events, historical error
  Multiplier 0.8–1.5× on base duration
  Trained on actual vs predicted trip times

LAYER 3 — UNCERTAINTY:
  Display p50 to user ("4 min")
  Internal p90 for match timeout decisions

CACHING:
  (driver_h3_cell, pickup_h3_cell) → ETA cached 30 sec
  Reduces routing QPS 5–10× at match peak

FEEDBACK LOOP:
  Log actual trip duration → retrain ML layer
  Metric: ETA_error_p90 — bad ETA → rider cancel → worse match rate

MATCHING USES ETA, NOT DISTANCE:
  Candidate sort by ETA_pickup, not haversine
  Week 8 + Week 10 tie-in — geospatial is pre-filter only
```

---

## Failure Modes

### 1. Ghost Drivers

```
FAILURE:       Stale driver locations shown as available on map
SYMPTOM:       Rider sees nearby car; request times out; no match
DETECTION:     Match success rate drop; stale_location_rejects metric;
               driver updated_at > 15s in index
BLAST RADIUS:  User trust; wasted match attempts
MITIGATION:    Hard staleness cutoff (15s); remove from geo index;
               show "last seen X sec ago" in debug mode only
PREVENTION:    Heartbeat on WebSocket; background OFFLINE on disconnect;
               client-side location accuracy filters
```

### 2. Double Matching

```
FAILURE:       Same driver assigned to two rides
SYMPTOM:       Two riders see same driver; one gets cancelled;
               support tickets; safety incident
DETECTION:     driver_id with two active trips; accept race alerts
BLAST RADIUS:  Two riders; driver; brand damage
MITIGATION:    Conditional atomic update on accept; driver lock TTL;
               reconciliation job cancels duplicate trip
PREVENTION:    DynamoDB ConditionExpression; single active trip invariant;
               load test accept race with concurrent requests
```

### 3. Location Staleness

```
FAILURE:       GPS jitter, tunnel dropout, battery throttling
SYMPTOM:       Driver icon jumps; geofence triggers wrong;
               match to driver who is actually 2 km away
DETECTION:     ETA error spike; cancel-after-assign rate;
               GPS accuracy field in telemetry
BLAST RADIUS:  Match quality; rider cancels; driver wasted drive
MITIGATION:    Kalman filter on client; ignore accuracy > 50m;
               re-verify ETA before final offer wave
PREVENTION:    Hysteresis on geofence enter/exit; velocity sanity
               checks (impossible 200 km/h jump → discard)
```

### 4. Payment at Trip End

```
FAILURE:       Network retry causes double capture; or lost payment
SYMPTOM:       Rider charged twice; or free ride with completed status
DETECTION:     duplicate payment_intent for trip_id; reconciliation
BLAST RADIUS:  Financial loss; regulatory; user trust
MITIGATION:    Idempotent capture: POST /capture with Idempotency-Key
               = trip_id; Stripe idempotency keys
PREVENTION:    Pre-auth at match (hold); capture once at COMPLETED;
               state machine: COMPLETED → PAYMENT_SETTLED only once;
               nightly reconciliation job trip vs payment ledger

FAILED CAPTURE FLOW:
  COMPLETED → payment fails → PAYMENT_PENDING
  Retry with exponential backoff (idempotent)
  After N failures → debt collection flow; driver still paid
    from platform float (separate saga)
```

---

## Rubric Scoring — Problem-Specific Criteria

```
DIMENSION 1 — REQUIREMENTS (Uber-specific):
  ✓ Separates match latency from ETA accuracy
  ✓ Asks location update frequency and staleness budget
  ✓ Surge shown before confirm
  ✗ Designs only happy path without cancel/payment

DIMENSION 2 — CAPACITY:
  ✓ Computes ~1M location writes/sec
  ✓ Does NOT put every GPS ping in Postgres
  ✓ Estimates match QPS from rides/day
  ✗ Ignores WebSocket fan-out for live tracking

DIMENSION 3 — API & DATA MODEL:
  ✓ Trip state machine with atomic accept
  ✓ Idempotency on ride request and payment
  ✗ Missing driver status (AVAILABLE/ON_TRIP)

DIMENSION 4 — ARCHITECTURE:
  ✓ Separate location ingestion path (Kafka → geo index)
  ✓ Dispatch reads geo index; routing for ETA
  ✗ Monolith scanning DB for nearest driver

DIMENSION 5 — DEEP DIVE:
  ✓ Two-phase geo query (index + ETA refinement)
  ✓ H3 or geohash with boundary/neighbor handling
  ✓ Batch dispatch with double-match prevention
  ✗ Nearest driver by straight-line distance

DIMENSION 6 — TRADE-OFFS:
  ✓ H3 vs geohash vs S2 with use case
  ✓ Batch vs serial dispatch
  ✓ Pre-auth vs post-trip payment only

DIMENSION 7 — FAILURE MODES:
  ✓ Ghost drivers + double matching + payment idempotency
  ✓ Staleness cutoff with specific seconds

DIMENSION 8 — COMMUNICATION:
  ✓ Walks match flow end-to-end in 60 seconds
  ✓ Time management; v1/v2 scope at end

SCORING WORKSHEET:

  Dimension                          │ Score (1-4) │ Notes
  ───────────────────────────────────┼─────────────┼──────
  1. Requirements & Scope            │             │
  2. Capacity Estimation             │             │
  3. API & Data Model                │             │
  4. High-Level Architecture         │             │
  5. Deep Dive                       │             │
  6. Trade-offs & Alternatives       │             │
  7. Failure Modes & Reliability     │             │
  8. Communication & Structure       │             │
  ───────────────────────────────────┼─────────────┼──────
  TOTAL                              │    /32      │
```

---

## Expert Answer — Full 45-Minute Narrative

```
MINUTE 0–5 — REQUIREMENTS

  "I'll scope UberX: request, match, track, pay at end.

   P0: Real-time matching, live driver on map, surge before confirm,
   ETA at request and during trip.

   NFR: 1M concurrent rides, p99 match < 15 sec, location freshness
   < 5 sec on map, 99.95% availability, idempotent payment.

   Design driver: 4M drivers updating location ≈ 1M writes/sec —
   we cannot scan all drivers at match time. Geospatial index +
   separate location pipeline.

   Stale driver cutoff: 15 seconds. Match uses road ETA, not distance."

MINUTE 5–12 — CAPACITY

  "20M rides/day ≈ 230/sec, peak ~700/sec.

   4M drivers / 4 sec = 1M location updates/sec — Kafka +
   in-memory H3 index, not Postgres per ping.

   1M concurrent trips × 2 KB ≈ 2 GB hot state per region shard.

   Match: 700/sec × 15 ETAs = ~10K routing QPS — cache by cell pair.

   Live tracking: 1M rides / 4 sec ≈ 250K WebSocket pushes/sec
   regionally sharded."

MINUTE 12–18 — API & DATA MODEL

  "POST /rides with idempotency key. State machine: MATCHING →
   DRIVER_ASSIGNED → IN_PROGRESS → COMPLETED → PAYMENT_SETTLED.

   Driver accept: conditional update status AVAILABLE → ON_TRIP.

   DynamoDB trips, Redis driver state + H3 index, Kafka location-updates."

MINUTE 18–28 — ARCHITECTURE

  [Draw architecture diagram]

  "Driver GPS → WebSocket gateway → Kafka → processor → H3 index.

   Match: geo k-ring → filter stale/vehicle → batch ETA → score →
   offer top 3 → atomic accept.

   Surge: Flink aggregates demand/supply per H3 res-7 cell.

   Payment: pre-auth at match, idempotent capture at complete
   with trip_id as idempotency key."

MINUTE 28–40 — DEEP DIVE

  "Geospatial: H3 res-9 for drivers, k-ring expansion on timeout.
   Hex neighbors uniform; handle pentagon edge cases in tests.
   Geohash alternative for Redis GEORADIUS — know the boundary bug.

   Dispatch: batch 3, 15 sec timeout, 3 waves. Score by ETA not
   distance. Double-match: DynamoDB condition on status.

   Surge: demand/supply ratio, EMA smoothed, cap 3×, upfront lock.

   ETA: routing engine + ML multiplier; cache 30 sec per cell pair.

   Airport: polygon geofence queue — FIFO within fence, not radius.

   Payment fail: retry idempotent; PAYMENT_PENDING state; driver
   paid from platform float via saga."

MINUTE 40–45 — FAILURE MODES & CLOSE

  "Ghost drivers: staleness cutoff, remove from index.
   Double matching: atomic accept CAS.
   Location staleness: accuracy filter, re-ETA before offer.
   Double payment: idempotency key = trip_id.

   V1: UberX, H3 index, batch dispatch, surge, Stripe pre-auth/capture.
   V2: Pool rides, scheduled, ML rank, multi-region active-active."
```

---

## Debrief Guide

```
FOR THE INTERVIEWER:

  1. Score all 8 dimensions with evidence quotes
  2. If Deep Dive < 3: assign Week 8 Geospatial Systems re-read
  3. If Capacity missed 1M writes/sec: flag as automatic below bar
     for mobility roles
  4. Strong signal: candidate mentioned batch dispatch + atomic accept
     without prompting on double-match

FOR THE CANDIDATE:

  □ Did I compute 1M location writes/sec?
  □ Did I separate location pipeline from match pipeline?
  □ Did I use ETA (routing) not haversine for dispatch scoring?
  □ Did I explain batch dispatch and double-match prevention?
  □ Did I cover payment idempotency at trip end?
  □ Did I name ghost drivers and staleness cutoff?

COMMON FAILURES:

  → Postgres for every GPS ping
  → SELECT ORDER BY distance
  → Serial one-driver-at-a-time dispatch
  → Surge as simple 2× multiplier with no zones
  → No trip state machine or atomic driver accept

REPEAT PRACTICE EXTENSIONS:

  → Design Uber Pool (detour minimization)
  → Multi-region: driver crosses market boundary mid-trip
  → Surge gaming incident: coordinated driver offline
  → Maps provider outage — fallback ETA strategy
```

---

## Key Takeaways

```
1. Location at scale (1M writes/sec) requires a streaming path to
   in-memory geo index — not durable DB on every ping.

2. Geospatial index is phase 1 (candidates); routing ETA is phase 2
   (dispatch decision). Never match on straight-line distance alone.

3. H3 hex grid is the Uber-standard for indexing and surge zones;
   know geohash boundary neighbors and when PostGIS fits (polygons).

4. Batch dispatch with atomic accept prevents slow serial matching
   and double-assignment races.

5. Surge is zone-based, smoothed, capped, and locked upfront —
   not a global multiplier.

6. Ghost drivers come from stale index entries — hard cutoff (15s)
   and WebSocket heartbeats are mandatory.

7. Payment at trip end: pre-auth at match, idempotent capture by
   trip_id — retries must not double-charge.
```

---

## Targeted Reading

```
REQUIRED (before retry):
  → Week 8: Geospatial Systems.md — geohash, H3, two-phase query
  → Week 10: Design Uber.md — dispatch, surge, ETA, AWS layout
  → Interview Rubric.md — 8 dimensions and timing

OPTIONAL:
  → Uber H3 blog posts and open-source H3 documentation
  → AWS Location Service (Place Index, Route Calculator)
  → Week 6: Kafka for location-updates pipeline
  → Week 6: Saga pattern for payment + driver payout float
```
