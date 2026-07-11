# Design Uber
> **Week 10 — Media and Mobility System Designs**
> **Prerequisites:** Geospatial systems (Week 8), Message Queues & Kafka (Week 6), Caching Patterns (Week 2), Consistent Hashing (Week 3)
> **Cross-links:** Week 8 geospatial indexing (Geohash, S2, H3) powers driver location queries; surge pricing ties to event-driven architecture.

---

## Learning Objectives
```
╔════════════════════════════════════════════════════════════╗
║ AFTER THIS MODULE, YOU WILL BE ABLE TO:                    ║
╟────────────────────────────────────────────────────────────╢
║                                                            ║
║ 1. Design a ride-hailing dispatch system: request intake,  ║
║ driver                                                     ║
║    matching, trip state machine, and payment settlement    ║
║                                                            ║
║ 2. Apply geospatial indexing (Geohash, S2 cells, H3) to su ║
║ b-second                                                   ║
║    nearest-driver queries at millions of concurrent locati ║
║ ons                                                        ║
║                                                            ║
║ 3. Explain surge pricing mechanics: supply/demand zones, m ║
║ ultiplier                                                  ║
║    calculation, fairness, and anti-gaming controls         ║
║                                                            ║
║ 4. Design ETA prediction: map services, traffic models, ML ║
║  refinement,                                               ║
║    and how ETA feeds back into matching decisions          ║
║                                                            ║
║ 5. Size AWS infrastructure for peak Friday night: location ║
║  write                                                     ║
║    throughput, matching QPS, WebSocket fan-out, DynamoDB R ║
║ CU/WCU                                                     ║
║                                                            ║
║ 6. Diagnose incidents: ghost drivers, surge stuck at 3x, m ║
║ atching                                                    ║
║    loops, GPS drift, payment double-charge, regional outag ║
║ e                                                          ║
╚════════════════════════════════════════════════════════════╝
```
---

## Section 2: Wrong Mental Models (Destroy These First)

```
╔════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Match to the closest driver by distance"       ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Road network distance ≠ haversine. A driver 500m away     ║
║   across a river may be 15 min by road. ETA to pickup must use     ║
║   routing graph, not Euclidean distance. Week 8 geospatial gets    ║
║   you candidates; routing gets you the correct match.              ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "SELECT ORDER BY distance in PostgreSQL"        ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Full table scan or naive B-tree cannot do k-NN at         ║
║   millions of moving points. Use Geohash prefixes, S2 cell         ║
║   covering, or H3 hex grids with inverted index per cell.          ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "Surge pricing = multiply fare by 2"            ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Surge is ZONE-based, time-varying, smoothed, and capped.  ║
║   It must balance supply (driver incentive) vs demand (rider       ║
║   churn). Sticky surge, phantom surge, and upfront pricing         ║
║   change the UX entirely.                                          ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "Every GPS ping writes to the database"         ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. 4M drivers × 1 update/4 sec = 1M writes/sec. Location     ║
║   flows through Redis/DynamoDB with TTL; matching reads snapshot.  ║
║   Historical trail goes to Kafka → cold storage for analytics.     ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "One dispatch algorithm for all cities"         ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Manhattan grid ≠ suburban sprawl ≠ Mumbai congestion.     ║
║   Matching weights (ETA vs distance vs driver fairness) are        ║
║   per-market tuned. Airport queues, pool rides, and scheduled      ║
║   rides are separate modes.                                        ║
╚════════════════════════════════════════════════════════════════════╝
```
---

## Core Teaching

### Functional Requirements

```
P0:
  → Rider requests ride (pickup, dropoff, ride type)
  → System matches driver and assigns trip
  → Real-time ETA for pickup and trip duration
  → Live trip tracking (driver location on map)
  → Surge pricing displayed BEFORE rider confirms
  → Payment on trip completion

P1:
  → Pool/shared rides, scheduled rides, multi-stop
  → Driver heat maps, incentive zones
  → Ratings, support, fraud detection
```

```
                    UBER — LOGICAL ARCHITECTURE
                    ═══════════════════════════

  ┌──────────────┐              ┌──────────────┐
  │ Rider App    │              │ Driver App   │
  │ (iOS/Android)│              │ (location    │
  └──────┬───────┘              │  streaming)  │
         │                        └──────┬───────┘
         │    WebSocket / gRPC             │
         └────────────┬────────────────────┘
                      │
             ┌────────▼────────┐
             │  API Gateway    │
             │  + ALB          │
             └────────┬────────┘
                      │
    ┌─────────────────┼─────────────────┐
    │                 │                 │
┌───▼───┐      ┌──────▼──────┐   ┌──────▼──────┐
│ Trip  │      │ Dispatch /  │   │ Location    │
│Service│      │ Matching    │   │ Service     │
└───┬───┘      └──────┬──────┘   └──────┬──────┘
    │                 │                 │
    │          ┌──────▼──────┐   ┌──────▼──────┐
    │          │ Pricing /   │   │ Redis Geo / │
    │          │ Surge       │   │ H3 Index    │
    │          └──────┬──────┘   └──────┬──────┘
    │                 │                 │
┌───▼─────────────────▼─────────────────▼───┐
│ DynamoDB (trips) │ Aurora (users) │ Kafka   │
└───────────────────────────────────────────┘
                      │
             ┌────────▼────────┐
             │ Maps / Routing  │  (Google Maps API / OSRM / AWS Location)
             └─────────────────┘
```

### Geospatial Indexing — Week 8 Tie-In

```
WEEK 8 RECAP → APPLIED TO UBER
════════════════════════════════

PROBLEM: Find 10 nearest AVAILABLE drivers to rider at (37.7749, -122.4194)
  Naive: O(n) over 4 million drivers — impossible at request time

SOLUTION 1: GEOHASH (Week 8)
  Encode (lat, lng) → base32 string, e.g. "9q8yyk"
  Precision 6 ≈ 1.2km × 0.6km cell
  Index: Redis GEOADD drivers:sf  -122.4194 37.7749 driver_123
  Query: GEORADIUS drivers:sf  -122.4194 37.7749 3 km ASC COUNT 20
  Expand: if < 5 drivers, query parent geohash prefix (broader cell)

SOLUTION 2: S2 CELLS (Google — used at scale)
  Hilbert curve on sphere → 64-bit cell ID
  Level 14 cell ≈ 1 km²
  Inverted index: cell_id → [driver_ids]
  Covering: query region → union of S2 cells → union driver sets

SOLUTION 3: H3 (Uber's open-source hex grid)
  Resolution 9 hex ≈ 0.1 km² (urban matching)
  H3 hexes tile cleanly — uniform neighbor distance
  k-ring expansion: center hex + 1 ring = 7 hexes for wider search
  Storage: DynamoDB PK=h3_index SK=driver_id GSI=status+timestamp

LOCATION UPDATE PATH (write-optimized):
  Driver app → Location Gateway (WebSocket) → Kafka topic
  → Location Processor (Flink):
      → Update Redis GEO / H3 index (latest position, TTL 30s)
      → Emit to analytics sink (S3 parquet, not matching path)
  Stale driver rule: no update in 30s → mark OFFLINE, remove from index
```

### Dispatch and Driver Matching

```
TRIP STATE MACHINE:

  REQUESTED → MATCHING → DRIVER_ASSIGNED → DRIVER_ARRIVING →
  IN_PROGRESS → COMPLETED → PAYMENT_SETTLED
                    ↓ (timeout)
                 NO_DRIVERS / CANCELLED

MATCHING ALGORITHM (simplified production flow):

  1. Rider submits request → Trip Service creates trip_id, status=MATCHING
  2. Dispatch Service receives MatchTrip command:
     a. Get surge multiplier for pickup H3 cell
     b. Geospatial query: 20 candidate drivers within 3 km road-network
     c. Filter: status=AVAILABLE, vehicle type matches, not on blocklist
     d. Score each candidate:
        score = w1×(-ETA_pickup) + w2×driver_rating + w3×fairness_bonus
     e. Batch offer to top 3 drivers simultaneously (batch dispatch)
     f. First ACCEPT wins; others get CANCEL_OFFER
     g. If no accept in 15 sec → expand radius, increase offer batch
     h. After 3 waves → NO_DRIVERS, suggest retry or schedule

BATCH vs SERIAL DISPATCH:
  Serial: offer to closest → wait 15s → next (slow, unfair to #2)
  Batch: offer to top 3 → first accept wins (Uber production pattern)
  Pool: different algorithm — detour minimization, not just pickup ETA
```

### Surge Pricing

```
SURGE MECHANICS:

  Zone: H3 resolution 7 hex (~5 km²) or custom geofence
  Metrics per zone (rolling 5-min window):
    demand = ride_requests_count
    supply = available_drivers_count
    ratio = demand / max(supply, 1)

  Multiplier curve (illustrative):
    ratio < 1.2  → 1.0x (no surge)
    ratio 1.2-1.5 → 1.2x
    ratio 1.5-2.0 → 1.5x
    ratio 2.0-3.0 → 2.0x
    ratio > 3.0   → min(3.0, 1 + 0.5×log2(ratio))  [cap at 3x]

  SMOOTHING: EMA on multiplier — no jump 1.0 → 3.0 in one tick
  UPFRONT PRICING: fare quoted at request time locked for rider
  DRIVER PAYOUT: surge share per market (e.g., 75% of surge to driver)

ANTI-GAMING:
  Drivers colluding to go offline to spike surge → detect coordinated
  offline clusters; cap surge duration; manual review queue
```

### ETA Prediction

```
ETA COMPONENTS:

  pickup_ETA = time(driver → pickup via road network)
  trip_ETA   = time(pickup → dropoff via road network)

  LAYER 1: Routing engine (OSRM / Google Directions / AWS Location Service)
    → Returns base duration from static graph + live traffic overlay

  LAYER 2: ML correction model
    Features: time_of_day, day_of_week, weather, event flags, historical
              error for this route segment, driver speed profile
    Output: multiplier on base duration (0.8 - 1.5×)

  LAYER 3: Uncertainty band
    Display: '4 min' with p50; internal p90 for matching timeout

  FEEDBACK LOOP:
    Actual trip duration logged → training data for ML layer
    Bad ETA → rider cancels → worsens matching → metric: ETA_error_p90
```

#### AWS Architecture — Regional Deployment

```
MULTI-REGION ACTIVE-ACTIVE (simplified)

  us-west-2 (primary SF market):
    EKS cluster: trip, dispatch, location, pricing services
    ElastiCache Redis Cluster: driver locations (GEORADIUS)
    DynamoDB: trips table (PK=trip_id), GSI rider_id+created_at
    MSK: location-updates, trip-events topics
    AWS Location Service: route calculator + geofence collections

  Data partitioning:
    Trips sharded by geohash prefix of pickup location
    Location index: one Redis cluster per major metro (avoid cross-region latency)
    Global users table: Aurora Global Database

  Peak capacity (SF Friday 11 PM):
    50,000 active drivers, 200,000 concurrent riders
    Location updates: 50K / 4 sec = 12,500 writes/sec
    Match requests: 5,000/min = 83/sec (burst 500/sec)
    WebSocket connections: 250K (drivers + riders on active trips)
```

#### Capacity Math — Location Writes

```
LOCATION UPDATE THROUGHPUT

  Drivers online globally: 4,000,000
  Update frequency: every 4 seconds (GPS + battery tradeoff)
  Writes/sec: 4M / 4 = 1,000,000 writes/sec (global peak)

  Per city (NYC): ~80,000 drivers → 20,000 writes/sec

  Redis GEOADD: ~100K ops/sec per shard → need 200 shards NYC alone
  OR partition by geohash prefix → 10 Redis clusters × 20 shards

  DynamoDB alternative:
    PK: h3_cell  SK: driver_id  attribute: lat, lng, heading, ts
    WCU: 20,000/sec → on-demand or 25K provisioned with auto-scaling

  Kafka ingestion:
    Topic: location-updates, 256 partitions, 3x replication
    Partition by driver_id hash → ordered updates per driver
```

#### Payment and Trip Completion

```
PAYMENT FLOW (at COMPLETED):

  1. Trip Service computes final fare:
     base + distance×rate + time×rate + surge×eligible + tolls + tip
  2. Payment Service charges rider (Stripe / Adyen pre-auth at trip start)
  3. Capture actual amount; release pre-auth hold delta
  4. Driver payout queued (weekly batch or instant cash-out fee)
  5. Trip event → Kafka → analytics, tax, compliance

  IDEMPOTENCY: payment_id = trip_id — duplicate COMPLETED events safe
  Saga: if capture fails → retry → manual review queue → rider invoice
```


---

## Section 4: Concrete Examples — AWS Configurations

### Example: Redis GEO Driver Index

```python
import redis

r = redis.RedisCluster(host="driver-geo.sf.cache.amazonaws.com", decode_responses=True)

def update_driver_location(driver_id: str, lat: float, lng: float, status: str):
    pipe = r.pipeline()
    pipe.geoadd("drivers:available:sf", (lng, lat, driver_id))
    pipe.hset(f"driver:meta:{driver_id}", mapping={
        "lat": lat, "lng": lng, "status": status, "updated_at": int(time.time())
    })
    pipe.expire(f"driver:meta:{driver_id}", 30)
    pipe.execute()

def find_candidates(lat: float, lng: float, radius_km: float = 3, count: int = 20):
    return r.georadius(
        "drivers:available:sf", lng, lat, radius_km, unit="km",
        withdist=True, sort="ASC", count=count
    )
```

### Example: DynamoDB Trips Table

```json
{
  "TableName": "trips-prod",
  "KeySchema": [
    { "AttributeName": "trip_id", "KeyType": "HASH" }
  ],
  "GlobalSecondaryIndexes": [{
    "IndexName": "rider-trips-index",
    "KeySchema": [
      { "AttributeName": "rider_id", "KeyType": "HASH" },
      { "AttributeName": "created_at", "KeyType": "RANGE" }
    ],
    "Projection": { "ProjectionType": "ALL" }
  }],
  "BillingMode": "PAY_PER_REQUEST",
  "StreamSpecification": { "StreamEnabled": true, "StreamViewType": "NEW_AND_OLD_IMAGES" }
}
```


---

## Production Patterns
```
PATTERN 1: Optimistic locking on trip status transitions — conditional writes in DynamoDB
```

```
PATTERN 2: Driver offer timeout via SQS delay queue — auto-expire unmatched offers
```

```
PATTERN 3: Circuit breaker on routing API — fallback to haversine × 1.3 if maps down
```

```
PATTERN 4: Surge preview cached 30 sec — avoid recalc on every app open
```

```
PATTERN 5: Location dedupe — ignore updates < 10m movement in < 2 sec (GPS jitter)
```

```
PATTERN 6: Idempotent trip creation — client request_id prevents double-book from retry
```

```
PATTERN 7: Geofence airport queue — FIFO matching for taxi rank zones
```

```
PATTERN 8: Dark mode matching — shadow test new algorithm on 1% without affecting trips
```


---

## Failure Modes
### Failure: Ghost Drivers in Index

```
SCENARIO: Driver offline but still in GEO index; match fails at accept
DETECT: Accept timeout rate > 20%
FIX: TTL on geo entries; heartbeat; remove on 3 missed pings
```

### Failure: Surge Stuck at 3x

```
SCENARIO: EMA smoothing bug after demand drop; riders abandon
DETECT: Surge > 2x for 60 min with low demand
FIX: Max surge duration; manual override API; decay factor audit
```

### Failure: Matching Loop

```
SCENARIO: Driver rejects → same driver re-offered due to score cache
DETECT: Same driver_id in 5 consecutive offers
FIX: Exclude rejected drivers for trip; cooldown set
```

### Failure: GPS Drift / Tunnel

```
SCENARIO: Driver location frozen; ETA stuck; rider sees car not moving
DETECT: Location age > 60s during IN_PROGRESS
FIX: Dead reckoning; last-known-good; prompt manual confirm
```

### Failure: Double Payment Capture

```
SCENARIO: Duplicate COMPLETED event from at-least-once Kafka
DETECT: Two charges same trip_id
FIX: Idempotent capture; payment_id uniqueness constraint
```

### Failure: Regional Redis Failover

```
SCENARIO: Primary Redis cluster down; empty driver index
DETECT: GEORADIUS returns 0 drivers city-wide
FIX: Multi-AZ; read replica promote; rebuild index from Kafka replay
```

### Failure: Routing API Outage

```
SCENARIO: Google Maps timeout; matching uses stale ETAs
DETECT: ETA error p90 > 300%
FIX: Circuit breaker; haversine fallback; pause pool rides
```

### Failure: Hot H3 Cell

```
SCENARIO: Stadium event — 10K requests in one hex
DETECT: DynamoDB throttling on h3_cell partition
FIX: Split hot cell; pre-position drivers; dynamic surge cap
```


---

## SRE Diagnostic Toolkit
```
KEY METRICS:

  match.success_rate                  threshold=< 85%           P1
  match.time_to_assign_p95            threshold=> 45 sec        P2
  location.update_lag_p99             threshold=> 10 sec        P2
  surge.zones_above_2x                threshold=> 50% of city   P2
  eta.error_p90_pct                   threshold=> 40%           P2
  websocket.disconnect_rate           threshold=> 5%/min        P1
  payment.capture_failure_rate        threshold=> 0.1%          P1
  redis.geo.index_size_delta          threshold=> 20% drop      P1

DEBUG COMMANDS:
  redis-cli GEORADIUS drivers:available:sf -122.4 37.77 5 km WITHDIST COUNT 5
  aws dynamodb get-item --table-name trips-prod --key '{"trip_id":{"S":"..."}}'
  kafka-console-consumer --topic trip-events --from-beginning --max-messages 10
```


---

## Decision Framework
```
╔════════════════════════════════════════════════════════════╗
║ GEOSPATIAL CHOICE (Week 8 applied)                         ║
╟────────────────────────────────────────────────────────────╢
║                                                            ║
║ Geohash + Redis GEO:                                       ║
║   → Fastest to ship; built into Redis; good for MVP / sing ║
║ le city                                                    ║
║   → Edge effects at cell boundaries — expand prefix search ║
║                                                            ║
║ S2 cells:                                                  ║
║   → Google-scale proven; excellent spherical geometry      ║
║   → Steeper learning curve; use if already on Google infra ║
║                                                            ║
║ H3:                                                        ║
║   → Uber open-source; uniform hex neighbors; best for surg ║
║ e zones                                                    ║
║   → Recommended for multi-city production matching + prici ║
║ ng                                                         ║
║                                                            ║
║ PostGIS:                                                   ║
║   → NOT for hot path at 1M writes/sec; use for analytics w ║
║ arehouse                                                   ║
╚════════════════════════════════════════════════════════════╝
```
---

## Incident Scenario
```
INCIDENT: New Year's Eve SF — P1
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  11:45 PM: match.success_rate drops 94% → 61%
  11:47 PM: Support flooded — 'No cars available' in SOMA
  11:48 PM: Dashboard shows 12,000 drivers ONLINE but matching finds 0
  11:50 PM: Deploy at 11:30 PM changed location TTL 30s → 300s
  11:52 PM: Surge stuck at 3.0x citywide despite demand drop
  11:55 PM: Redis CPU 98% on driver-geo cluster

Q1: Root cause chain?
Q2: First 10 minutes mitigation?
Q3: Why drivers ONLINE but 0 candidates?
Q4: Permanent fixes?
```


---



---

> **Answer key (do not open until you attempt the Ops Sim / questions):**
> [`../answers/Week-10-Media-and-Mobility-Designs/Design Uber Answers.md`](../answers/Week-10-Media-and-Mobility-Designs/Design Uber Answers.md)

## Key Takeaways
```
╔════════════════════════════════════════════════════════════╗
║ REMEMBER:                                                  ║
╟────────────────────────────────────────────────────────────╢
║                                                            ║
║ 1. Geospatial index (Week 8) finds candidates; routing fin ║
║ ds correct match.                                          ║
║ 2. Location writes never go synchronously to matching — Re ║
║ dis/Kafka path.                                            ║
║ 3. Surge is zone-smoothed supply/demand — not a simple far ║
║ e multiplier.                                              ║
║ 4. Batch dispatch with timeout beats serial closest-driver ║
║  offers.                                                   ║
║ 5. ETA error drives cancel rate — treat ETA as matching in ║
║ put, not display-only.                                     ║
╚════════════════════════════════════════════════════════════╝
```
---

## Targeted Reading
```
  Uber H3 documentation: https://h3geo.org/
  DDIA Chapter 1 — reliability on location stream processing
  Week 8 Geospatial systems module (when complete) — Geohash, S2, H3
  AWS Location Service developer guide — route calculators
  'How Uber Computes ETAs at Scale' (Uber Engineering blog)
```


---

# Appendix A: Market-Specific Matching Parameters

### SF — Parameter Set 1

```
  Market: SF
  w_eta: 0.52
  w_rating: 0.21
  w_fairness: 0.11
  initial_radius_km: 3
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 9
  Notes: tuned from A/B experiment 2024-Q2
```

### SF — Parameter Set 2

```
  Market: SF
  w_eta: 0.54
  w_rating: 0.22
  w_fairness: 0.11
  initial_radius_km: 4
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 9
  Notes: tuned from A/B experiment 2024-Q3
```

### SF — Parameter Set 3

```
  Market: SF
  w_eta: 0.56
  w_rating: 0.23
  w_fairness: 0.12
  initial_radius_km: 5
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 9
  Notes: tuned from A/B experiment 2024-Q4
```

### SF — Parameter Set 4

```
  Market: SF
  w_eta: 0.58
  w_rating: 0.24
  w_fairness: 0.12
  initial_radius_km: 2
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 9
  Notes: tuned from A/B experiment 2024-Q1
```

### SF — Parameter Set 5

```
  Market: SF
  w_eta: 0.60
  w_rating: 0.25
  w_fairness: 0.12
  initial_radius_km: 3
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 9
  Notes: tuned from A/B experiment 2024-Q2
```

### SF — Parameter Set 6

```
  Market: SF
  w_eta: 0.62
  w_rating: 0.26
  w_fairness: 0.13
  initial_radius_km: 4
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 9
  Notes: tuned from A/B experiment 2024-Q3
```

### SF — Parameter Set 7

```
  Market: SF
  w_eta: 0.64
  w_rating: 0.27
  w_fairness: 0.14
  initial_radius_km: 5
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 9
  Notes: tuned from A/B experiment 2024-Q4
```

### SF — Parameter Set 8

```
  Market: SF
  w_eta: 0.66
  w_rating: 0.28
  w_fairness: 0.14
  initial_radius_km: 2
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 9
  Notes: tuned from A/B experiment 2024-Q1
```

### SF — Parameter Set 9

```
  Market: SF
  w_eta: 0.68
  w_rating: 0.29
  w_fairness: 0.15
  initial_radius_km: 3
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 9
  Notes: tuned from A/B experiment 2024-Q2
```

### SF — Parameter Set 10

```
  Market: SF
  w_eta: 0.70
  w_rating: 0.30
  w_fairness: 0.15
  initial_radius_km: 4
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 9
  Notes: tuned from A/B experiment 2024-Q3
```

### SF — Parameter Set 11

```
  Market: SF
  w_eta: 0.72
  w_rating: 0.31
  w_fairness: 0.15
  initial_radius_km: 5
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 9
  Notes: tuned from A/B experiment 2024-Q4
```

### SF — Parameter Set 12

```
  Market: SF
  w_eta: 0.74
  w_rating: 0.32
  w_fairness: 0.16
  initial_radius_km: 2
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 9
  Notes: tuned from A/B experiment 2024-Q1
```

### NYC — Parameter Set 1

```
  Market: NYC
  w_eta: 0.52
  w_rating: 0.21
  w_fairness: 0.11
  initial_radius_km: 3
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 9
  Notes: tuned from A/B experiment 2024-Q2
```

### NYC — Parameter Set 2

```
  Market: NYC
  w_eta: 0.54
  w_rating: 0.22
  w_fairness: 0.11
  initial_radius_km: 4
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 9
  Notes: tuned from A/B experiment 2024-Q3
```

### NYC — Parameter Set 3

```
  Market: NYC
  w_eta: 0.56
  w_rating: 0.23
  w_fairness: 0.12
  initial_radius_km: 5
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 9
  Notes: tuned from A/B experiment 2024-Q4
```

### NYC — Parameter Set 4

```
  Market: NYC
  w_eta: 0.58
  w_rating: 0.24
  w_fairness: 0.12
  initial_radius_km: 2
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 9
  Notes: tuned from A/B experiment 2024-Q1
```

### NYC — Parameter Set 5

```
  Market: NYC
  w_eta: 0.60
  w_rating: 0.25
  w_fairness: 0.12
  initial_radius_km: 3
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 9
  Notes: tuned from A/B experiment 2024-Q2
```

### NYC — Parameter Set 6

```
  Market: NYC
  w_eta: 0.62
  w_rating: 0.26
  w_fairness: 0.13
  initial_radius_km: 4
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 9
  Notes: tuned from A/B experiment 2024-Q3
```

### NYC — Parameter Set 7

```
  Market: NYC
  w_eta: 0.64
  w_rating: 0.27
  w_fairness: 0.14
  initial_radius_km: 5
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 9
  Notes: tuned from A/B experiment 2024-Q4
```

### NYC — Parameter Set 8

```
  Market: NYC
  w_eta: 0.66
  w_rating: 0.28
  w_fairness: 0.14
  initial_radius_km: 2
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 9
  Notes: tuned from A/B experiment 2024-Q1
```

### NYC — Parameter Set 9

```
  Market: NYC
  w_eta: 0.68
  w_rating: 0.29
  w_fairness: 0.15
  initial_radius_km: 3
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 9
  Notes: tuned from A/B experiment 2024-Q2
```

### NYC — Parameter Set 10

```
  Market: NYC
  w_eta: 0.70
  w_rating: 0.30
  w_fairness: 0.15
  initial_radius_km: 4
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 9
  Notes: tuned from A/B experiment 2024-Q3
```

### NYC — Parameter Set 11

```
  Market: NYC
  w_eta: 0.72
  w_rating: 0.31
  w_fairness: 0.15
  initial_radius_km: 5
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 9
  Notes: tuned from A/B experiment 2024-Q4
```

### NYC — Parameter Set 12

```
  Market: NYC
  w_eta: 0.74
  w_rating: 0.32
  w_fairness: 0.16
  initial_radius_km: 2
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 9
  Notes: tuned from A/B experiment 2024-Q1
```

### LA — Parameter Set 1

```
  Market: LA
  w_eta: 0.52
  w_rating: 0.21
  w_fairness: 0.11
  initial_radius_km: 3
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q2
```

### LA — Parameter Set 2

```
  Market: LA
  w_eta: 0.54
  w_rating: 0.22
  w_fairness: 0.11
  initial_radius_km: 4
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q3
```

### LA — Parameter Set 3

```
  Market: LA
  w_eta: 0.56
  w_rating: 0.23
  w_fairness: 0.12
  initial_radius_km: 5
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q4
```

### LA — Parameter Set 4

```
  Market: LA
  w_eta: 0.58
  w_rating: 0.24
  w_fairness: 0.12
  initial_radius_km: 2
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q1
```

### LA — Parameter Set 5

```
  Market: LA
  w_eta: 0.60
  w_rating: 0.25
  w_fairness: 0.12
  initial_radius_km: 3
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q2
```

### LA — Parameter Set 6

```
  Market: LA
  w_eta: 0.62
  w_rating: 0.26
  w_fairness: 0.13
  initial_radius_km: 4
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q3
```

### LA — Parameter Set 7

```
  Market: LA
  w_eta: 0.64
  w_rating: 0.27
  w_fairness: 0.14
  initial_radius_km: 5
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q4
```

### LA — Parameter Set 8

```
  Market: LA
  w_eta: 0.66
  w_rating: 0.28
  w_fairness: 0.14
  initial_radius_km: 2
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q1
```

### LA — Parameter Set 9

```
  Market: LA
  w_eta: 0.68
  w_rating: 0.29
  w_fairness: 0.15
  initial_radius_km: 3
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q2
```

### LA — Parameter Set 10

```
  Market: LA
  w_eta: 0.70
  w_rating: 0.30
  w_fairness: 0.15
  initial_radius_km: 4
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q3
```

### LA — Parameter Set 11

```
  Market: LA
  w_eta: 0.72
  w_rating: 0.31
  w_fairness: 0.15
  initial_radius_km: 5
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q4
```

### LA — Parameter Set 12

```
  Market: LA
  w_eta: 0.74
  w_rating: 0.32
  w_fairness: 0.16
  initial_radius_km: 2
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q1
```

### Chicago — Parameter Set 1

```
  Market: Chicago
  w_eta: 0.52
  w_rating: 0.21
  w_fairness: 0.11
  initial_radius_km: 3
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q2
```

### Chicago — Parameter Set 2

```
  Market: Chicago
  w_eta: 0.54
  w_rating: 0.22
  w_fairness: 0.11
  initial_radius_km: 4
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q3
```

### Chicago — Parameter Set 3

```
  Market: Chicago
  w_eta: 0.56
  w_rating: 0.23
  w_fairness: 0.12
  initial_radius_km: 5
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q4
```

### Chicago — Parameter Set 4

```
  Market: Chicago
  w_eta: 0.58
  w_rating: 0.24
  w_fairness: 0.12
  initial_radius_km: 2
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q1
```

### Chicago — Parameter Set 5

```
  Market: Chicago
  w_eta: 0.60
  w_rating: 0.25
  w_fairness: 0.12
  initial_radius_km: 3
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q2
```

### Chicago — Parameter Set 6

```
  Market: Chicago
  w_eta: 0.62
  w_rating: 0.26
  w_fairness: 0.13
  initial_radius_km: 4
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q3
```

### Chicago — Parameter Set 7

```
  Market: Chicago
  w_eta: 0.64
  w_rating: 0.27
  w_fairness: 0.14
  initial_radius_km: 5
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q4
```

### Chicago — Parameter Set 8

```
  Market: Chicago
  w_eta: 0.66
  w_rating: 0.28
  w_fairness: 0.14
  initial_radius_km: 2
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q1
```

### Chicago — Parameter Set 9

```
  Market: Chicago
  w_eta: 0.68
  w_rating: 0.29
  w_fairness: 0.15
  initial_radius_km: 3
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q2
```

### Chicago — Parameter Set 10

```
  Market: Chicago
  w_eta: 0.70
  w_rating: 0.30
  w_fairness: 0.15
  initial_radius_km: 4
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q3
```

### Chicago — Parameter Set 11

```
  Market: Chicago
  w_eta: 0.72
  w_rating: 0.31
  w_fairness: 0.15
  initial_radius_km: 5
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q4
```

### Chicago — Parameter Set 12

```
  Market: Chicago
  w_eta: 0.74
  w_rating: 0.32
  w_fairness: 0.16
  initial_radius_km: 2
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q1
```

### London — Parameter Set 1

```
  Market: London
  w_eta: 0.52
  w_rating: 0.21
  w_fairness: 0.11
  initial_radius_km: 3
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q2
```

### London — Parameter Set 2

```
  Market: London
  w_eta: 0.54
  w_rating: 0.22
  w_fairness: 0.11
  initial_radius_km: 4
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q3
```

### London — Parameter Set 3

```
  Market: London
  w_eta: 0.56
  w_rating: 0.23
  w_fairness: 0.12
  initial_radius_km: 5
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q4
```

### London — Parameter Set 4

```
  Market: London
  w_eta: 0.58
  w_rating: 0.24
  w_fairness: 0.12
  initial_radius_km: 2
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q1
```

### London — Parameter Set 5

```
  Market: London
  w_eta: 0.60
  w_rating: 0.25
  w_fairness: 0.12
  initial_radius_km: 3
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q2
```

### London — Parameter Set 6

```
  Market: London
  w_eta: 0.62
  w_rating: 0.26
  w_fairness: 0.13
  initial_radius_km: 4
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q3
```

### London — Parameter Set 7

```
  Market: London
  w_eta: 0.64
  w_rating: 0.27
  w_fairness: 0.14
  initial_radius_km: 5
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q4
```

### London — Parameter Set 8

```
  Market: London
  w_eta: 0.66
  w_rating: 0.28
  w_fairness: 0.14
  initial_radius_km: 2
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q1
```

### London — Parameter Set 9

```
  Market: London
  w_eta: 0.68
  w_rating: 0.29
  w_fairness: 0.15
  initial_radius_km: 3
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q2
```

### London — Parameter Set 10

```
  Market: London
  w_eta: 0.70
  w_rating: 0.30
  w_fairness: 0.15
  initial_radius_km: 4
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q3
```

### London — Parameter Set 11

```
  Market: London
  w_eta: 0.72
  w_rating: 0.31
  w_fairness: 0.15
  initial_radius_km: 5
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q4
```

### London — Parameter Set 12

```
  Market: London
  w_eta: 0.74
  w_rating: 0.32
  w_fairness: 0.16
  initial_radius_km: 2
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q1
```

### Mumbai — Parameter Set 1

```
  Market: Mumbai
  w_eta: 0.52
  w_rating: 0.21
  w_fairness: 0.11
  initial_radius_km: 3
  max_surge: 3.0
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q2
```

### Mumbai — Parameter Set 2

```
  Market: Mumbai
  w_eta: 0.54
  w_rating: 0.22
  w_fairness: 0.11
  initial_radius_km: 4
  max_surge: 3.0
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q3
```

### Mumbai — Parameter Set 3

```
  Market: Mumbai
  w_eta: 0.56
  w_rating: 0.23
  w_fairness: 0.12
  initial_radius_km: 5
  max_surge: 3.0
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q4
```

### Mumbai — Parameter Set 4

```
  Market: Mumbai
  w_eta: 0.58
  w_rating: 0.24
  w_fairness: 0.12
  initial_radius_km: 2
  max_surge: 3.0
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q1
```

### Mumbai — Parameter Set 5

```
  Market: Mumbai
  w_eta: 0.60
  w_rating: 0.25
  w_fairness: 0.12
  initial_radius_km: 3
  max_surge: 3.0
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q2
```

### Mumbai — Parameter Set 6

```
  Market: Mumbai
  w_eta: 0.62
  w_rating: 0.26
  w_fairness: 0.13
  initial_radius_km: 4
  max_surge: 3.0
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q3
```

### Mumbai — Parameter Set 7

```
  Market: Mumbai
  w_eta: 0.64
  w_rating: 0.27
  w_fairness: 0.14
  initial_radius_km: 5
  max_surge: 3.0
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q4
```

### Mumbai — Parameter Set 8

```
  Market: Mumbai
  w_eta: 0.66
  w_rating: 0.28
  w_fairness: 0.14
  initial_radius_km: 2
  max_surge: 3.0
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q1
```

### Mumbai — Parameter Set 9

```
  Market: Mumbai
  w_eta: 0.68
  w_rating: 0.29
  w_fairness: 0.15
  initial_radius_km: 3
  max_surge: 3.0
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q2
```

### Mumbai — Parameter Set 10

```
  Market: Mumbai
  w_eta: 0.70
  w_rating: 0.30
  w_fairness: 0.15
  initial_radius_km: 4
  max_surge: 3.0
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q3
```

### Mumbai — Parameter Set 11

```
  Market: Mumbai
  w_eta: 0.72
  w_rating: 0.31
  w_fairness: 0.15
  initial_radius_km: 5
  max_surge: 3.0
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q4
```

### Mumbai — Parameter Set 12

```
  Market: Mumbai
  w_eta: 0.74
  w_rating: 0.32
  w_fairness: 0.16
  initial_radius_km: 2
  max_surge: 3.0
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q1
```

### São Paulo — Parameter Set 1

```
  Market: São Paulo
  w_eta: 0.52
  w_rating: 0.21
  w_fairness: 0.11
  initial_radius_km: 3
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q2
```

### São Paulo — Parameter Set 2

```
  Market: São Paulo
  w_eta: 0.54
  w_rating: 0.22
  w_fairness: 0.11
  initial_radius_km: 4
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q3
```

### São Paulo — Parameter Set 3

```
  Market: São Paulo
  w_eta: 0.56
  w_rating: 0.23
  w_fairness: 0.12
  initial_radius_km: 5
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q4
```

### São Paulo — Parameter Set 4

```
  Market: São Paulo
  w_eta: 0.58
  w_rating: 0.24
  w_fairness: 0.12
  initial_radius_km: 2
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q1
```

### São Paulo — Parameter Set 5

```
  Market: São Paulo
  w_eta: 0.60
  w_rating: 0.25
  w_fairness: 0.12
  initial_radius_km: 3
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q2
```

### São Paulo — Parameter Set 6

```
  Market: São Paulo
  w_eta: 0.62
  w_rating: 0.26
  w_fairness: 0.13
  initial_radius_km: 4
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q3
```

### São Paulo — Parameter Set 7

```
  Market: São Paulo
  w_eta: 0.64
  w_rating: 0.27
  w_fairness: 0.14
  initial_radius_km: 5
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q4
```

### São Paulo — Parameter Set 8

```
  Market: São Paulo
  w_eta: 0.66
  w_rating: 0.28
  w_fairness: 0.14
  initial_radius_km: 2
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q1
```

### São Paulo — Parameter Set 9

```
  Market: São Paulo
  w_eta: 0.68
  w_rating: 0.29
  w_fairness: 0.15
  initial_radius_km: 3
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q2
```

### São Paulo — Parameter Set 10

```
  Market: São Paulo
  w_eta: 0.70
  w_rating: 0.30
  w_fairness: 0.15
  initial_radius_km: 4
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q3
```

### São Paulo — Parameter Set 11

```
  Market: São Paulo
  w_eta: 0.72
  w_rating: 0.31
  w_fairness: 0.15
  initial_radius_km: 5
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q4
```

### São Paulo — Parameter Set 12

```
  Market: São Paulo
  w_eta: 0.74
  w_rating: 0.32
  w_fairness: 0.16
  initial_radius_km: 2
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q1
```

### Tokyo — Parameter Set 1

```
  Market: Tokyo
  w_eta: 0.52
  w_rating: 0.21
  w_fairness: 0.11
  initial_radius_km: 3
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q2
```

### Tokyo — Parameter Set 2

```
  Market: Tokyo
  w_eta: 0.54
  w_rating: 0.22
  w_fairness: 0.11
  initial_radius_km: 4
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q3
```

### Tokyo — Parameter Set 3

```
  Market: Tokyo
  w_eta: 0.56
  w_rating: 0.23
  w_fairness: 0.12
  initial_radius_km: 5
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q4
```

### Tokyo — Parameter Set 4

```
  Market: Tokyo
  w_eta: 0.58
  w_rating: 0.24
  w_fairness: 0.12
  initial_radius_km: 2
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q1
```

### Tokyo — Parameter Set 5

```
  Market: Tokyo
  w_eta: 0.60
  w_rating: 0.25
  w_fairness: 0.12
  initial_radius_km: 3
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q2
```

### Tokyo — Parameter Set 6

```
  Market: Tokyo
  w_eta: 0.62
  w_rating: 0.26
  w_fairness: 0.13
  initial_radius_km: 4
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q3
```

### Tokyo — Parameter Set 7

```
  Market: Tokyo
  w_eta: 0.64
  w_rating: 0.27
  w_fairness: 0.14
  initial_radius_km: 5
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q4
```

### Tokyo — Parameter Set 8

```
  Market: Tokyo
  w_eta: 0.66
  w_rating: 0.28
  w_fairness: 0.14
  initial_radius_km: 2
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q1
```

### Tokyo — Parameter Set 9

```
  Market: Tokyo
  w_eta: 0.68
  w_rating: 0.29
  w_fairness: 0.15
  initial_radius_km: 3
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q2
```

### Tokyo — Parameter Set 10

```
  Market: Tokyo
  w_eta: 0.70
  w_rating: 0.30
  w_fairness: 0.15
  initial_radius_km: 4
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q3
```

### Tokyo — Parameter Set 11

```
  Market: Tokyo
  w_eta: 0.72
  w_rating: 0.31
  w_fairness: 0.15
  initial_radius_km: 5
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q4
```

### Tokyo — Parameter Set 12

```
  Market: Tokyo
  w_eta: 0.74
  w_rating: 0.32
  w_fairness: 0.16
  initial_radius_km: 2
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q1
```

### Berlin — Parameter Set 1

```
  Market: Berlin
  w_eta: 0.52
  w_rating: 0.21
  w_fairness: 0.11
  initial_radius_km: 3
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q2
```

### Berlin — Parameter Set 2

```
  Market: Berlin
  w_eta: 0.54
  w_rating: 0.22
  w_fairness: 0.11
  initial_radius_km: 4
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q3
```

### Berlin — Parameter Set 3

```
  Market: Berlin
  w_eta: 0.56
  w_rating: 0.23
  w_fairness: 0.12
  initial_radius_km: 5
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q4
```

### Berlin — Parameter Set 4

```
  Market: Berlin
  w_eta: 0.58
  w_rating: 0.24
  w_fairness: 0.12
  initial_radius_km: 2
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q1
```

### Berlin — Parameter Set 5

```
  Market: Berlin
  w_eta: 0.60
  w_rating: 0.25
  w_fairness: 0.12
  initial_radius_km: 3
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q2
```

### Berlin — Parameter Set 6

```
  Market: Berlin
  w_eta: 0.62
  w_rating: 0.26
  w_fairness: 0.13
  initial_radius_km: 4
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q3
```

### Berlin — Parameter Set 7

```
  Market: Berlin
  w_eta: 0.64
  w_rating: 0.27
  w_fairness: 0.14
  initial_radius_km: 5
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q4
```

### Berlin — Parameter Set 8

```
  Market: Berlin
  w_eta: 0.66
  w_rating: 0.28
  w_fairness: 0.14
  initial_radius_km: 2
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q1
```

### Berlin — Parameter Set 9

```
  Market: Berlin
  w_eta: 0.68
  w_rating: 0.29
  w_fairness: 0.15
  initial_radius_km: 3
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q2
```

### Berlin — Parameter Set 10

```
  Market: Berlin
  w_eta: 0.70
  w_rating: 0.30
  w_fairness: 0.15
  initial_radius_km: 4
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q3
```

### Berlin — Parameter Set 11

```
  Market: Berlin
  w_eta: 0.72
  w_rating: 0.31
  w_fairness: 0.15
  initial_radius_km: 5
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q4
```

### Berlin — Parameter Set 12

```
  Market: Berlin
  w_eta: 0.74
  w_rating: 0.32
  w_fairness: 0.16
  initial_radius_km: 2
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q1
```

### Sydney — Parameter Set 1

```
  Market: Sydney
  w_eta: 0.52
  w_rating: 0.21
  w_fairness: 0.11
  initial_radius_km: 3
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q2
```

### Sydney — Parameter Set 2

```
  Market: Sydney
  w_eta: 0.54
  w_rating: 0.22
  w_fairness: 0.11
  initial_radius_km: 4
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q3
```

### Sydney — Parameter Set 3

```
  Market: Sydney
  w_eta: 0.56
  w_rating: 0.23
  w_fairness: 0.12
  initial_radius_km: 5
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q4
```

### Sydney — Parameter Set 4

```
  Market: Sydney
  w_eta: 0.58
  w_rating: 0.24
  w_fairness: 0.12
  initial_radius_km: 2
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q1
```

### Sydney — Parameter Set 5

```
  Market: Sydney
  w_eta: 0.60
  w_rating: 0.25
  w_fairness: 0.12
  initial_radius_km: 3
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q2
```

### Sydney — Parameter Set 6

```
  Market: Sydney
  w_eta: 0.62
  w_rating: 0.26
  w_fairness: 0.13
  initial_radius_km: 4
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q3
```

### Sydney — Parameter Set 7

```
  Market: Sydney
  w_eta: 0.64
  w_rating: 0.27
  w_fairness: 0.14
  initial_radius_km: 5
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q4
```

### Sydney — Parameter Set 8

```
  Market: Sydney
  w_eta: 0.66
  w_rating: 0.28
  w_fairness: 0.14
  initial_radius_km: 2
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q1
```

### Sydney — Parameter Set 9

```
  Market: Sydney
  w_eta: 0.68
  w_rating: 0.29
  w_fairness: 0.15
  initial_radius_km: 3
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q2
```

### Sydney — Parameter Set 10

```
  Market: Sydney
  w_eta: 0.70
  w_rating: 0.30
  w_fairness: 0.15
  initial_radius_km: 4
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q3
```

### Sydney — Parameter Set 11

```
  Market: Sydney
  w_eta: 0.72
  w_rating: 0.31
  w_fairness: 0.15
  initial_radius_km: 5
  max_surge: 2.5
  batch_offer_size: 3
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q4
```

### Sydney — Parameter Set 12

```
  Market: Sydney
  w_eta: 0.74
  w_rating: 0.32
  w_fairness: 0.16
  initial_radius_km: 2
  max_surge: 2.5
  batch_offer_size: 5
  h3_resolution: 8
  Notes: tuned from A/B experiment 2024-Q1
```


---

# Appendix B: Trip Event Schema Reference

### Event: TripRequested

```json
{
  "event_type": "TripRequested",
  "trip_id": "uuid",
  "timestamp_ms": 0,
  "payload": { "..." : "see trip-service protos" }
}
```

### Event: MatchStarted

```json
{
  "event_type": "MatchStarted",
  "trip_id": "uuid",
  "timestamp_ms": 0,
  "payload": { "..." : "see trip-service protos" }
}
```

### Event: DriverOffered

```json
{
  "event_type": "DriverOffered",
  "trip_id": "uuid",
  "timestamp_ms": 0,
  "payload": { "..." : "see trip-service protos" }
}
```

### Event: DriverAccepted

```json
{
  "event_type": "DriverAccepted",
  "trip_id": "uuid",
  "timestamp_ms": 0,
  "payload": { "..." : "see trip-service protos" }
}
```

### Event: DriverRejected

```json
{
  "event_type": "DriverRejected",
  "trip_id": "uuid",
  "timestamp_ms": 0,
  "payload": { "..." : "see trip-service protos" }
}
```

### Event: DriverArrived

```json
{
  "event_type": "DriverArrived",
  "trip_id": "uuid",
  "timestamp_ms": 0,
  "payload": { "..." : "see trip-service protos" }
}
```

### Event: TripStarted

```json
{
  "event_type": "TripStarted",
  "trip_id": "uuid",
  "timestamp_ms": 0,
  "payload": { "..." : "see trip-service protos" }
}
```

### Event: TripCompleted

```json
{
  "event_type": "TripCompleted",
  "trip_id": "uuid",
  "timestamp_ms": 0,
  "payload": { "..." : "see trip-service protos" }
}
```

### Event: PaymentCaptured

```json
{
  "event_type": "PaymentCaptured",
  "trip_id": "uuid",
  "timestamp_ms": 0,
  "payload": { "..." : "see trip-service protos" }
}
```

### Event: TripCancelled

```json
{
  "event_type": "TripCancelled",
  "trip_id": "uuid",
  "timestamp_ms": 0,
  "payload": { "..." : "see trip-service protos" }
}
```

### Event: SurgeApplied

```json
{
  "event_type": "SurgeApplied",
  "trip_id": "uuid",
  "timestamp_ms": 0,
  "payload": { "..." : "see trip-service protos" }
}
```

### Event: ETAUpdated

```json
{
  "event_type": "ETAUpdated",
  "trip_id": "uuid",
  "timestamp_ms": 0,
  "payload": { "..." : "see trip-service protos" }
}
```


---

# Appendix C: Surge Zone Calculation Walkthrough

```
WORKED EXAMPLE — SOMA district Friday 11 PM

  H3 cell: 8928308280fffff (resolution 9)
  Window: 5 minutes rolling
  ride_requests: 847
  available_drivers: 312
  ratio = 847 / 312 = 2.71
  raw_multiplier = 1 + 0.5 × log2(2.71) = 1 + 0.5 × 1.44 = 1.72
  previous_EMA = 1.4
  smoothed = 0.7 × 1.4 + 0.3 × 1.72 = 1.50x surge
  rider_quote = base_fare × 1.50 (locked at request time)
  driver_payout = base × 1.0 + surge_portion × 0.75
```


---

# Appendix D: ETA Error Budget

```
SLO: pickup ETA p90 error < 25% (|actual - predicted| / predicted)

  If ETA error > 25%:
    → Rider cancel rate increases ~8% per 10% error
    → Driver idle time increases (arrived early, rider not ready)
    → Matching weights should penalize uncertain ETAs

  Monitoring:
    eta_pickup_error_pct histogram by market, hour, weather
    Alert if p90 > 30% for 15 min in any top-10 city
```


---

# Appendix E: Week 8 Geospatial Deep-Dive — Geohash vs S2 vs H3

```
WEEK 8 CONCEPTS APPLIED TO DISPATCH (reference when Week 8 module ships)

GEOHASH:
  Properties: rectangular cells, base32 encoded, prefix = parent region
  Precision table:
    length 5 → ~4.9 km × 4.9 km
    length 6 → ~1.2 km × 0.6 km  ← urban driver search default
    length 7 → ~153 m × 153 m
  Edge problem: point near cell border may miss closer driver in neighbor
  Fix: query 8 adjacent prefixes OR use geohash + GEORADIUS (Redis handles)

S2 (Google):
  Properties: Hilbert curve on unit sphere, 30 levels, cell IDs are uint64
  Level 14 ≈ 1 km² — good for metro matching
  Advantages: no polar distortion, hierarchical covering of polygons
  Use case: airport geofence = union of S2 cells, not point radius

H3 (Uber):
  Properties: hexagonal grid, 16 resolutions, no neighbor ambiguity
  Resolution 9 hex edge ~174 m — dense urban
  kRing(1) = 7 hexes, kRing(2) = 19 hexes — systematic radius expansion
  Surge zones align naturally to H3 — one multiplier per hex

WORKED k-NN QUERY (H3, resolution 9, SF SOMA):

  Rider at lat/lng → h3_index = geoToH3(37.7749, -122.4194, 9)
  Step 1: lookup drivers in h3_index bucket (DynamoDB Query)
  Step 2: if count < 5, expand kRing(h3_index, 1) → 6 more hex lookups
  Step 3: merge driver sets, dedupe by driver_id
  Step 4: for each candidate, call routing API for road-network ETA
  Step 5: sort by ETA, take top 20 for scoring

  Latency budget: Steps 1-3 < 10ms (cached index)
                  Step 4 ~ 50ms (batch Directions API, 20 waypoints)
                  Step 5 < 1ms
                  Total matching prep < 70ms before offer send
```

---

> **Retention test moved:** Week 10 compound scenario will live in
> Retention-Tests/Week-10.md per curriculum standards.

---

## Design Gates (mandatory)

Answer these before calling the design complete. Keep responses concise in the
learner notes; compare against the answer key only after attempting the gates.

> Gate template: [`../templates/DESIGN_MODULE_GATES.md`](../templates/DESIGN_MODULE_GATES.md)
> Model responses: [`../answers/Week-10-Media-and-Mobility-Designs/Design Uber Answers.md`](../answers/Week-10-Media-and-Mobility-Designs/Design%20Uber%20Answers.md)

### Gate 1 - Authn/z trust boundary

1. Who is authenticated in this design: end user, admin, service, device, worker, tenant, or partner?
2. Where does the first untrusted request cross into your trusted control plane?
3. Which component makes the final authorization decision for each protected object or action?
4. What identity artifact is accepted: session cookie, bearer token, API key, mTLS SPIFFE ID, signed URL, or job identity?
5. What does the system do when the identity provider, policy store, or trust bundle is unavailable?

### Gate 2 - Abuse and misuse

6. Which actor can generate the largest write amplification or fan-out?
7. Which endpoint or background job can be abused while still authenticated?
8. What per-user, per-tenant, per-key, per-IP, per-region, and global quotas are required?
9. What telemetry distinguishes a legitimate flash crowd from abuse or scraping?
10. Which retry policy could amplify a partial outage into a full outage?

### Gate 3 - Multi-tenant isolation, if multi-tenant

11. What is the tenancy model for API, database, cache, queue/topic, search/index, and object storage?
12. Where is tenant context required, and how is it propagated through async jobs and support tools?
13. Which shared resource has reserved capacity or fair-share limits per tenant or tier?
14. How can one tenant be throttled, disabled, migrated, or isolated without affecting others?
15. What test proves a tenant cannot read another tenant's data through cache, search, export, or logs?

### Gate 4 - Unit cost at target scale

16. What is the business unit for cost: request, message, ride, order, document, query, minute, or tenant?
17. At the stated target scale and peak multiplier, what is the rough unit cost?
18. Which line items dominate: compute, storage, replication, egress, NAT, observability, ML inference, third-party APIs, or idle headroom?
19. What cost metric pages before margin, budget, or SLO error budget is breached?
20. What graceful degradation lowers cost without damaging the correctness-critical path?

### Gate 5 - Failure blast radius

21. What is the smallest unit that can fail independently: partition, shard, cell, topic, region, tenant, cache key, model, worker pool, or queue?
22. Which dependencies are shared between critical and non-critical paths?
23. What fails closed, what serves stale, and what can be disabled first?
24. Which runbook action could accidentally widen blast radius?
25. What game day proves the blast radius stays inside the intended boundary?
