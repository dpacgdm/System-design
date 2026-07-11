# Week 8, Topic 2 — Geospatial Systems

---

## Learning Objectives
```
After this topic, you will be able to:

1. Explain WHY geospatial systems need spatial indexing — and why
   "SELECT * WHERE distance(lat, lng) < X" collapses at scale

2. Compare geohashing, quad trees, S2, and H3 by cell shape,
   neighbor semantics, boundary behavior, and operational fit
   (ride-hailing vs warehouse vs analytics)

3. Design an Uber-style supply/demand matching pipeline:
   location ingestion → spatial index → candidate retrieval →
   ranking → dispatch → geofence enforcement

4. Write production-grade PostGIS queries (GiST indexes, ST_DWithin,
   geography vs geometry) and DynamoDB geo query patterns
   (geohash prefix + GSI, hot-cell mitigation)

5. Implement geofencing correctly: point-in-polygon, enter/exit
   events, debouncing GPS jitter, and timezone-aware rules

6. Map AWS Location Service components (Place Index, Route Calculator,
   Geofence Collections, Tracker) to a real mobility architecture

7. Diagnose geospatial production failures: hot geohash cells,
   stale driver positions, boundary mismatches, GPS spoofing,
   and dispatch fairness regressions

8. Choose the right spatial stack for a given workload using a
   decision framework — not "we use H3 because Uber uses H3"
```

---

## Wrong Mental Models (Destroy These First)

```
╔════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Lat/lng is enough — just compute distance"     ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Haversine on every row is O(n) per query. At 500K         ║
║   active drivers, one rider request scanning all drivers =         ║
║   500K trig operations. You need a SPATIAL INDEX that reduces      ║
║   candidates to dozens before distance math runs.                  ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "Geohash neighbors are always adjacent"         ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Geohash is a Z-order curve on a rectangle. Two cells      ║
║   that share a border may NOT be geohash neighbors. Near a         ║
║   cell boundary, you MUST query the cell AND all 8 neighbors       ║
║   (or use a library that handles it). Missing neighbors =          ║
║   "no drivers nearby" when drivers are 20 meters away.             ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "H3 and geohash are interchangeable"            ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. H3 uses hexagons (uniform-ish neighbor distance,          ║
║   6 neighbors). Geohash uses rectangles (4/8 neighbors,            ║
║   anisotropic distortion). S2 uses spherical cells on the          ║
║   actual globe. Pick based on query shape, aggregation needs,      ║
║   and whether you need hierarchical rollups.                       ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "PostGIS ST_Distance on geometry is fine"       ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG for global apps. geometry uses a flat plane; degrees       ║
║   ≠ meters at different latitudes. Use geography type (meters      ║
║   on spheroid) for radius queries, or project to a local CRS       ║
║   for city-scale precision. Mixing types silently gives wrong      ║
║   ETAs and wrong geofence triggers.                                ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Real-time matching = nearest driver"           ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Production dispatch optimizes a MULTI-OBJECTIVE           ║
║   function: ETA, acceptance probability, fairness, vehicle         ║
║   type, destination direction, surge zone, cancellation risk.      ║
║   Nearest straight-line distance is a pre-filter, not the          ║
║   dispatch decision.                                               ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #6: "GPS coordinates from phones are truth"         ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Urban canyon multipath, tunnel dropouts, battery-saving   ║
║   throttling, and spoofing apps produce 50–200m jitter routinely.  ║
║   Geofences need hysteresis; matching needs staleness cutoffs;     ║
║   fraud needs velocity/acceleration sanity checks.                 ║
╚════════════════════════════════════════════════════════════════════╝
```

---

## Core Teaching

### 3.1 — The Fundamental Problem: Location at Scale

```
THE QUESTION EVERY MOBILITY SYSTEM MUST ANSWER:

  "Given a point P (rider pickup), find all entities E (drivers)
   within radius R that satisfy constraints C, ranked by score S,
   in < 100ms at peak load."

WORKLOAD SHAPE (Uber-scale order of magnitude):

  Active drivers updating location:     1–5 million
  Location updates per second:          500K–2M
  Match requests per second:              10K–50K
  Acceptable p99 match latency:           50–150ms
  Staleness budget for driver position:   5–15 seconds

WHY BRUTE FORCE FAILS:

  Rider at (37.7749, -122.4194) requests a ride.
  Naive approach:

    SELECT driver_id,
           haversine(driver_lat, driver_lng, 37.7749, -122.4194) AS dist
    FROM drivers
    WHERE status = 'available'
    ORDER BY dist
    LIMIT 10;

  At 2M rows (all drivers, not just available):
    → Full table scan OR index on (lat,lng) that still can't
      express "within radius" efficiently without PostGIS
    → Even with partial index on status='available' (200K rows):
      200K haversine calculations × 30K match req/s = impossible

THE FIX: TWO-PHASE QUERY

  Phase 1 — SPATIAL INDEX (cheap):
    Reduce 200K candidates → ~20–100 using cell lookup

  Phase 2 — REFINEMENT (expensive but small):
    Compute road-network ETA or haversine on the short list
    Apply business rules (vehicle type, rating, fairness)

  ┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
  │ 2M drivers  │ ──► │ Spatial index    │ ──► │ ~50 cand.   │
  │ (all locs)  │     │ (geohash/H3/S2)  │     │ in radius   │
  └─────────────┘     └──────────────────┘     └──────┬──────┘
                                                      │
                                                      ▼
                                               ┌─────────────┐
                                               │ Rank by ETA │
                                               │ + dispatch  │
                                               └─────────────┘
```

### 3.2 — Coordinate Systems (You Must Know These)

```
WGS84 (EPSG:4326):
  What GPS returns. Latitude [-90, 90], Longitude [-180, 180].
  Units: DEGREES. Not meters.
  This is what your mobile SDK gives you.

Web Mercator (EPSG:3857):
  What Google Maps tiles use. Distorts area near poles.
  Good for visualization, BAD for distance math globally.

LOCAL PROJECTED CRS (e.g., UTM zones, state plane):
  Flat plane in METERS for a city/region.
  Excellent precision for municipal geofences and local ETAs.
  Must reproject when crossing zone boundaries.

PostGIS types:
  GEOMETRY  → flat plane, degrees or projected meters
  GEOGRAPHY → spheroid, distances in meters

  Rule of thumb:
    Global radius search     → GEOGRAPHY + ST_DWithin
    City-scale polygons      → GEOMETRY with local SRID
    Cross-continental routes → GEOGRAPHY or routing engine

THE LAT/LNG TRAP:

  1 degree latitude  ≈ 111 km (everywhere)
  1 degree longitude ≈ 111 km × cos(latitude)

  At San Francisco (37.7°N):
    1° lng ≈ 88 km

  A "0.01 degree" box is NOT a square in meters.
  Spatial indexes that treat lat/lng as Cartesian x,y
  without projection introduce systematic error.
```

### 3.3 — Geohashing

```
GEOHASH: Encode (lat, lng) as a base32 string.
Invented by Gustavo Niemeyer (2008). Used by Redis GEO,
DynamoDB geo libraries, early Uber prototypes.

MECHANISM:
  1. Bisect latitude range [-90, 90] and longitude [-180, 180]
     alternately (one bit lat, one bit lng, ...).
  2. Accumulate bits into an integer.
  3. Encode in base32: "9q8yyk" (precision grows with length).

PRECISION BY LENGTH:

  ┌────────┬────────────────────┬─────────────────────┐
  │ Length │ Cell width × height│ Typical use         │
  ├────────┼────────────────────┼─────────────────────┤
  │ 5      │ ~4.9km × 4.9km     │ City district       │
  │ 6      │ ~1.2km × 0.6km     │ Neighborhood        │
  │ 7      │ ~153m × 153m       │ Block-level match   │
  │ 8      │ ~38m × 19m         │ Fine pre-filter     │
  │ 9      │ ~4.8m × 4.8m       │ Usually overkill    │
  └────────┴────────────────────┴─────────────────────┘

  Note: cells are RECTANGULAR, not square at most latitudes.

EXAMPLE:

  San Francisco City Hall: 37.7793, -122.4193
  Geohash precision 7: "9q8yyk8"

PREFIX QUERY (how DynamoDB/Redis use it):

  To find points near SF City Hall:
    center_hash = geohash(37.7793, -122.4193, precision=7)
    neighbors   = geohash_neighbors(center_hash)  // 8 cells
    search_keys = [center_hash] + neighbors

  Query: WHERE geohash STARTS WITH any of those 9 prefixes
  (or BETWEEN range for sorted indexes)

THE BOUNDARY PROBLEM (critical):

  Driver at (37.7800, -122.4193) — 80m north of rider
  Rider cell: 9q8yyk8
  Driver cell: 9q8yykb  ← NOT a prefix neighbor in some layouts

  If you only query rider's cell, you MISS the driver.

  ALWAYS: query cell + 8 neighbors for geohash.
  Libraries: geohash2 (Python), ngeohash, Redis GEOHASH commands.

Z-ORDER CURVE VISUALIZATION (conceptual):

  Earth surface flattened to a square, space-filling curve
  visits cells in an order where nearby cells on the curve
  are often nearby geographically — but NOT always.

  ┌───┬───┬───┬───┐
  │ 0 │ 1 │ 4 │ 5 │    Numbers = visit order on curve
  ├───┼───┼───┼───┤    Cells 1 and 2 are adjacent on map
  │ 2 │ 3 │ 6 │ 7 │    but far apart on the curve
  └───┴───┴───┴───┘

STORAGE PATTERN:

  drivers table:
    driver_id    (PK)
    geohash_7    (GSI partition key or sort key prefix)
    lat, lng
    updated_at
    status

  On location update:
    h = geohash(lat, lng, 7)
    PUT driver_id, geohash_7=h, lat, lng, updated_at=now()
```

### 3.4 — Quad Trees

```
QUAD TREE: Recursively subdivide 2D space into four quadrants
until each leaf holds ≤ N points (or max depth reached).

STRUCTURE:

                    [Root: entire region]
                    /        |        \
                   /         |         \
           [NW quadrant] [NE] [SW] [SE]
              /  \                          
           [...] [...]  (subdivide when > N points)

QUERY: "Find points within radius R of P"
  1. Start at root.
  2. If node bbox intersects search circle → descend.
  3. At leaf, test each point.
  4. Prune branches that don't intersect.

PROS:
  → Adaptive density: downtown gets deep splits, rural stays shallow
  → Simple to implement in memory
  → Good for static or slow-changing point sets

CONS:
  → Rebalancing on updates is expensive at scale
  → Not trivially distributed (unlike fixed grid / geohash)
  → Variable depth → unpredictable query latency
  → Hard to persist efficiently in DynamoDB/SQL without rebuilding

WHERE YOU SEE IT:
  In-memory game engines, early mapping APIs, single-node
  collision detection. MongoDB's geospatial index uses
  quadtree-like structures internally (2dsphere).

DISTRIBUTED ALTERNATIVE:
  Fixed-depth quadtree / geohash IS essentially a quadtree
  with uniform depth — that's why geohash won for distributed
  systems: every cell at precision N is the same "depth."
```

### 3.5 — S2 Geometry (Google)

```
S2: Hierarchical decomposition of the SPHERE into cells.
Developed at Google. Used in Google Maps, Pokemon GO, Foursquare.

KEY PROPERTIES:
  → Cells are on a sphere, not a flat projection
  → Hilbert curve ordering → good spatial locality
  → 6 levels of hierarchy, 30 levels of depth
  → Cell IDs are 64-bit integers → fast comparison, no strings
  → Mostly quadrilateral cells (with some special handling)

CELL ID:

  64-bit token encodes:
    face (which cube face)
    position on Hilbert curve
    level (resolution)

  Example level-15 cell covers ~0.5–1 km depending on latitude.

OPERATIONS:
  S2CellId.from_lat_lng(lat, lng).parent(level)
  cell.get_neighbors()          // 4 edge neighbors at same level
  cell.get_all_neighbors(level) // includes diagonal neighbors
  S2Cap.from_axis_angle(center, radius) for region cover

REGION COVER (powerful for geofences):

  Given a polygon geofence, S2RegionCoverer finds the
  MINIMUM set of S2 cells that cover the polygon.

  ┌───────────────────────────────────┐
  │    Geofence polygon (airport)     │
  │ ┌───┬───┬───┐                     │
  │ │ S2│ S2│   │  Cover uses mixed   │
  │ ├───┼───┤   │  cell levels: big   │
  │ │ S2│ S2│ S2│  cells in interior, │
  │ └───┴───┴───┘  small on boundary  │
  └───────────────────────────────────┘

WHEN TO USE S2:
  → Global apps needing spherical correctness
  → Polygon coverage with hierarchical refinement
  → Systems already on Google's stack (s2geometry library)
  → Integer cell IDs in columnar stores (BigQuery, ClickHouse)

LIBRARIES:
  C++: google/s2geometry
  Go:  github.com/golang/geo/s2
  Java: com.google.geometry.s2
```

### 3.6 — H3 (Uber)

```
H3: Hexagonal hierarchical geospatial index.
Open-sourced by Uber (2018). THE standard for ride-hailing
and many mobility analytics pipelines.

WHY HEXAGONS:

  ┌───┐     Squares: 8 neighbors, distance to corner
  │   │     ≠ distance to edge → anisotropic error
  └───┘

       ⬡       Hexagons: 6 neighbors, roughly equal
      ⬡ ⬡      distance to all neighbors → better
       ⬡       approximation of a circle

  Only regular polygons that tile with themselves: triangles,
  squares, hexagons. Hexagons have the best edge-to-area ratio.

RESOLUTION TABLE (selected):

  ┌────────────┬──────────────┬─────────────────────────┐
  │ Resolution │ Avg hex edge │ Typical use             │
  ├────────────┼──────────────┼─────────────────────────┤
  │ 7          │ ~1.22 km     │ City-level aggregation  │
  │ 8          │ ~461 m       │ Neighborhood demand     │
  │ 9          │ ~174 m       │ Match pre-filter        │
  │ 10         │ ~66 m        │ Fine supply indexing    │
  │ 11         │ ~25 m        │ Pickup zone analysis    │
  └────────────┴──────────────┴─────────────────────────┘

  16 resolutions total (0 = ~1100 km edge, 15 = ~0.5 m).

H3 INDEX FORMAT:

  64-bit integer: 0x8928308280fffff (example)
  Or string: "8928308280fffff"

OPERATIONS:

  h3 = geo_to_h3(lat, lng, res=9)
  neighbors = k_ring(h3, k=1)  // center + 6 neighbors (k=1)
  parent = h3_to_parent(h3, res=8)  // roll up for aggregation
  polyfill = polygon_to_h3(polygon, res=9)  // geofence → cells

K-RING SEARCH (replaces geohash neighbor hack):

  For radius R, choose resolution where edge ≈ R/2,
  then k_ring(center, k=1) or k=2 to cover circle.

  ┌─────────────────────────────────────┐
  │         k=2 ring (19 hexes)         │
  │            ⬡ ⬡ ⬡                    │
  │          ⬡ ⬡ ⬡ ⬡ ⬡                  │
  │            ⬡ ● ⬡   ● = rider        │
  │          ⬡ ⬡ ⬡ ⬡ ⬡                  │
  │            ⬡ ⬡ ⬡                    │
  └─────────────────────────────────────┘

PENTAGON DISTORTION:
  H3 grid has 12 pentagons (icosahedron vertices) where
  one neighbor is missing. Libraries handle this; you must
  NOT assume exactly 6 neighbors globally. Rare in practice
  for city-scale ops but matters for global correctness tests.

UBER'S USE:
  → Supply heatmaps aggregated by H3 res-7/8
  → Surge pricing zones = H3 cell sets
  → Driver indexing at res-9/10
  → Analytics: trip origin/destination rolled to parent cells
```

### 3.7 — Comparing Spatial Index Schemes

```
╔═════════════════════════════════════════════════════════════════════════════╗
║ SCHEME   │ CELL SHAPE   │ NEIGHBORS │ SPHERE │ DISTRIBUTED  │ AGGREGATION   ║
╠═════════════════════════════════════════════════════════════════════════════╣
║ Geohash  │ Rectangle    │ 8 (buggy  │ Flat   │ Excellent    │ Prefix rollup ║
║          │              │  edges)   │        │ (string key) │ (approximate) ║
╠═════════════════════════════════════════════════════════════════════════════╣
║ Quadtree │ Rectangle    │ Variable  │ Flat   │ Hard         │ Tree walk     ║
║          │ (adaptive)   │           │        │              │               ║
╠═════════════════════════════════════════════════════════════════════════════╣
║ S2       │ Quad on      │ 4–8       │ Yes    │ Good (int64) │ Parent level  ║
║          │ sphere       │           │        │              │               ║
╠═════════════════════════════════════════════════════════════════════════════╣
║ H3       │ Hexagon      │ 6 (±pent) │ Yes    │ Good (int64) │ Parent res    ║
║          │              │           │        │              │ (clean)       ║
╠═════════════════════════════════════════════════════════════════════════════╣
║ PostGIS  │ User-defined │ R-tree    │ Both   │ Single-node  │ SQL GROUP BY  ║
║ GiST     │ (any geom)   │ based     │ types  │ or read rep  │ + geom        ║
╚═════════════════════════════════════════════════════════════════════════════╝

INTERVIEW SOUND BITE:
  "Geohash for simple DynamoDB/Redis prefix queries.
   H3 for mobility aggregation and hex-based pricing zones.
   S2 for global polygon coverage on the sphere.
   PostGIS when complex polygons and joins live in Postgres.
   Often you use TWO: H3 in the stream pipeline, PostGIS
   for airport geofence polygons in the ops database."
```

### 3.8 — PostGIS Deep Dive

```
PostGIS = PostgreSQL extension for geospatial types and queries.

ENABLE:
  CREATE EXTENSION postgis;

TYPES:
  POINT, LINESTRING, POLYGON, MULTIPOLYGON, GEOMETRY, GEOGRAPHY

INDEX:
  CREATE INDEX idx_drivers_loc ON drivers USING GIST (location);

  GiST (Generalized Search Tree) — the workhorse for
  "find geometries that intersect / are within distance."

CRITICAL QUERY PATTERN — radius search:

  -- CORRECT: geography, meters
  SELECT driver_id, ST_Distance(location, pickup) AS dist_m
  FROM drivers
  WHERE status = 'available'
    AND ST_DWithin(
          location::geography,
          ST_SetSRID(ST_MakePoint(-122.4193, 37.7749), 4326)::geography,
          3000  -- meters
        )
    AND updated_at > NOW() - INTERVAL '15 seconds'
  ORDER BY dist_m
  LIMIT 20;

  ST_DWithin uses the index when geography column is indexed.
  ST_Distance in ORDER BY is computed only for filtered rows.

GEOMETRY vs GEOGRAPHY:

  -- WRONG for global radius (treats degrees as flat units):
  ST_DWithin(geom, point, 0.027)  -- "0.027 degrees ≈ 3km" — lies at 60°N

  -- RIGHT:
  ST_DWithin(geom::geography, point::geography, 3000)

POINT-IN-POLYGON (geofence):

  SELECT airport_code
  FROM airport_geofences
  WHERE ST_Contains(
    boundary,
    ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)
  );

  Index: GIST on boundary. ST_Contains uses index for bounding-box prefilter.

GEOFENCE WITH BUFFER (GPS jitter tolerance):

  ST_DWithin(point::geography, boundary::geography, 50)
  -- 50m buffer outside polygon edge

COMPLEX EXAMPLE — drivers inside surge polygon:

  SELECT d.driver_id
  FROM drivers d
  JOIN surge_zones s ON ST_Contains(s.polygon, d.location)
  WHERE s.zone_id = 'surge_downtown_001'
    AND d.status = 'available';

PERFORMANCE NOTES:
  → Always SRID 4326 for WGS84 lat/lng points
  → CAST to geography for meter-based ops
  → VACUUM ANALYZE after bulk loads
  → EXPLAIN ANALYZE must show "Index Scan using idx_... GiST"
  → If Seq Scan → index not used → check type mismatch

RDS/AURORA:
  PostGIS available on RDS PostgreSQL. Enable via parameter group.
  Read replicas for geo read scaling; writes stay on primary.
```

### 3.9 — DynamoDB Geo Queries

```
DynamoDB has NO native geo index. Pattern: geohash (or H3) as
access pattern key + GSI.

TABLE DESIGN:

  Table: DriverLocations
  PK: driver_id (String)
  Attributes: lat, lng, geohash_7, status, vehicle_type, updated_at

  GSI: GeohashIndex
    PK: geohash_7 (String)
    SK: driver_id (String)  -- or updated_at for staleness sort

QUERY FLOW:

  1. rider at (37.7749, -122.4194)
  2. hash = geohash(37.7749, -122.4194, precision=7)
  3. neighbors = geohash_neighbors(hash)  // 8 strings
  4. For each of 9 cells (parallel Query):
       Query GeohashIndex WHERE geohash_7 = :cell
         AND status = 'available'  (FilterExpression — post-index)
  5. Merge results, filter by haversine / staleness
  6. Rank, dispatch

ITEM COLLECTION HOT PARTITION PROBLEM:

  Downtown SF geohash "9q8yyk" at 7pm:
    3,000 available drivers in ONE partition key.

  DynamoDB partition limit: 3,000 RCU + 1,000 WCU per partition
  (soft, can burst). Sustained hot key → throttling.

MITIGATIONS:

  A) INCREASE PRECISION (shorter geohash → more partitions):
     geohash_8 or geohash_9 splits downtown into many cells.
     Tradeoff: more parallel queries (9 × more at each precision step).

  B) GEOHASH + SALT:
     PK: geohash_7#shard_0 .. geohash_7#shard_3
     Random shard on write. Query all 4 shards per cell.
     4× read cost, 4× partition spread.

  C) H3 WITH FINER RESOLUTION:
     res-10 cells are ~66m → natural sharding in dense areas.

  D) DAX / ELASTICACHE FRONTING:
     Hot cells served from cache; DynamoDB for durability.

  E) DUAL-WRITE TO MEMORY INDEX:
     Kafka location stream → Flink → Redis GEO / custom H3 index
     DynamoDB = source of truth for driver profile, not live index

EXAMPLE AWS SDK QUERY (conceptual):

  # Query one geohash cell
  response = dynamodb.query(
      TableName='DriverLocations',
      IndexName='GeohashIndex',
      KeyConditionExpression='geohash_7 = :gh',
      FilterExpression='#st = :avail AND updated_at > :cutoff',
      ExpressionAttributeNames={'#st': 'status'},
      ExpressionAttributeValues={
          ':gh': {'S': '9q8yyk'},
          ':avail': {'S': 'available'},
          ':cutoff': {'N': str(int(time.time()) - 15)}
      }
  )

AMAZON LOCATION SERVICE + DYNAMODB:
  Often paired: Location Service for geocoding/routing/geofences,
  DynamoDB for entity state, ElastiCache for hot spatial index.

DEPRECATED LIBRARY NOTE:
  Amazon DynamoDB Geo library (Java, S2-based) was an early helper.
  Modern stacks prefer custom H3/geohash GSI or Amazon Location
  Service Trackers for managed geofence + position history.
```

### 3.10 — Uber-Style Matching Architecture

```
END-TO-END DISPATCH PIPELINE:

  ┌──────────┐    ┌─────────────┐    ┌──────────────┐
  │ Mobile   │───►│ Ingestion   │───►│ Spatial Index│
  │ (GPS)    │    │ (Kafka)     │    │ (H3/Redis)   │
  └──────────┘    └─────────────┘    └──────┬───────┘
                                             │
  ┌──────────┐    ┌─────────────┐            │
  │ Rider    │───►│ Match       │◄───────────┘
  │ request  │    │ Service     │
  └──────────┘    └──────┬──────┘
                         │
                         ▼
                  ┌─────────────┐    ┌──────────────┐
                  │ Ranking     │───►│ Dispatch     │
                  │ (ETA, ML)   │    │ (push notify)│
                  └─────────────┘    └──────────────┘

LOCATION INGESTION:

  Driver app sends GPS every 4 seconds (moving) or 30 seconds (idle).
  Payload: {driver_id, lat, lng, heading, speed, accuracy_m, ts}

  Ingestion service:
    → Validate (speed < 200 km/h, accuracy < 100m, ts fresh)
    → Publish to Kafka topic: driver-locations
    → Partition by driver_id (ordering per driver)

STREAM PROCESSOR (Flink / Kinesis Analytics):

  For each event:
    h3_cell = h3.geo_to_h3(lat, lng, res=10)
    UPDATE redis: ZADD h3:{cell} driver_id timestamp
    UPDATE dynamodb: driver_id → lat, lng, h3, updated_at
    EMIT metric: location_update_lag_ms

SPATIAL INDEX IN REDIS (common pattern):

  Key: h3:8928308280fffff
  Type: Sorted set or hash
  Members: driver_id → last_seen_ts

  On match request:
    cells = k_ring(rider_h3, k=1)
    candidates = SUNION across cell keys
    filter: now - last_seen < 15s

MATCH SERVICE:

  Input: {rider_id, pickup_lat, pickup_lng, product_type}
  Steps:
    1. Geocode if needed (Address → lat/lng via Location Service)
    2. h3 = geo_to_h3(pickup, res=9)
    3. candidates = spatial_index.query(h3, k_ring=1, limit=100)
    4. Filter: status=available, vehicle matches, not in trip
    5. Score each candidate:
         score = w1*eta_road + w2*(1-accept_prob) + w3*fairness_penalty
    6. Batch dispatch: offer to top 3 sequentially or simultaneously
    7. First accept wins; others get cancel notification

ETA CALCULATION:

  Phase 1: haversine × road_factor (1.3–1.5) — microseconds
  Phase 2: routing API (AWS Location Routes, OSRM, Google) — 20–80ms
           Only for top 10 candidates after phase 1

  Production: cache road segments, use ML ETA model trained on
  historical trip times (Uber Michelangelo, etc.)

DISPATCH OFFER FLOW:

  Match service → Dispatch service → Push (APNs/FCM)
  Driver has 15 seconds to accept.
  Timeout → offer next driver (chain dispatch).
  Surge multiplier attached to offer payload.

FAIRNESS:
  Drivers idle > 20 min get score boost.
  Prevent same driver getting all airport runs via destination filter.
```

### 3.11 — Geofencing

```
GEOFENCE: Virtual boundary; trigger action on enter/exit.

USE CASES:
  → Airport pickup zones (must be in zone to get matched)
  → Warehouse yard entry notifications
  → Surge pricing boundaries
  → Marketing: "user entered mall → push coupon"
  → Compliance: disable ride-hail in jurisdiction polygon

IMPLEMENTATION OPTIONS:

  1. POSTGIS (batch / server-side):
     ST_Contains(polygon, point) on each location update

  2. AWS LOCATION SERVICE Geofence Collections:
     Managed polygons, enter/exit events to EventBridge

  3. H3 POLYFILL (precomputed):
     polygon_to_h3(airport_polygon, res=10) → set of cell IDs
     On driver update: if h3 in airport_cells → in_geofence=true
     Fast O(1) lookup, approximate boundary (hex edges)

  4. S2 REGION COVER: similar to H3 polyfill, spherical accuracy

ENTER/EXIT STATE MACHINE:

  States: OUTSIDE, INSIDE, UNCERTAIN (GPS jitter buffer)

  ┌──────────┐  point in polygon   ┌──────────┐
  │ OUTSIDE  │ ──────────────────► │ INSIDE   │
  └──────────┘                     └──────────┘
       ▲                                 │
       │         point outside           │
       └─────────────────────────────────┘

  HYSTERESIS (mandatory):
    Enter: must be inside for 2 consecutive updates (8 sec)
    Exit:  must be outside for 3 consecutive updates (12 sec)
    Prevents flapping at boundary from 30m GPS noise

DEBOUNCING GPS JITTER:

  Raw GPS at boundary:
    t=0:  inside
    t=4:  outside  ← would fire exit without hysteresis
    t=8:  inside   ← would fire re-enter
    t=12: outside

  With 2-update enter / 3-update exit: state stays INSIDE.

VELOCITY SANITY:
  If distance(last, current) / delta_t > 150 km/h → reject update
  Prevents teleport spoofing triggering false geofence events.

AWS LOCATION SERVICE GEOFENCE FLOW:

  1. Create GeofenceCollection
  2. PutGeofence(GeofenceId, Polygon)
  3. BatchUpdateDevicePosition(TrackerName, device_id, lat, lng)
  4. EvaluateGeofences → EventBridge:
       {eventType: "ENTER", geofenceId: "airport_sfo", deviceId: "d123"}
  5. Lambda → update driver eligibility flag in DynamoDB
```

### 3.12 — AWS Location Service

```
AWS Location Service — managed geospatial primitives.

COMPONENTS:

  ┌────────────────────┬────────────────────────────────────────────┐
  │ Place Index        │ Geocode / reverse geocode / search         │
  ├────────────────────┼────────────────────────────────────────────┤
  │ Route Calculator   │ Turn-by-turn routes, ETAs, matrices        │
  ├────────────────────┼────────────────────────────────────────────┤
  │ Tracker            │ Device position history + geofence eval    │
  ├────────────────────┼────────────────────────────────────────────┤
  │ Geofence Collection│ Polygons + enter/exit events               │
  ├────────────────────┼────────────────────────────────────────────┤
  │ Maps               │ Raster tiles (visualization)               │
  └────────────────────┴────────────────────────────────────────────┘

TYPICAL MOBILITY STACK ON AWS:

  Mobile app
    → API Gateway → Lambda (auth)
    → Amazon Location (Place Index: SearchPlaceIndexForText)
    → Match service on ECS/EKS
    → ElastiCache Redis (H3 spatial index)
    → DynamoDB (driver state, trips)
    → Kinesis (location stream)
    → Location Service Tracker + Geofences (airport zones)
    → EventBridge → Lambda (geofence enter → enable pickup queue)
    → SNS (push to driver)

PRICING AWARENESS (order of magnitude):
  Geocoding: per 1000 requests
  Routes: per 1000 calculated routes
  Tracker: per 1000 position updates + geofence eval
  At Uber scale, self-hosted OSRM + custom geocoder may win —
  but Location Service wins on time-to-market and ops burden.

EXAMPLE — Create geofence (CLI):

  aws location create-geofence-collection \
    --collection-name airport-pickup-zones \
    --pricing-plan RequestBasedUsage

  aws location put-geofence \
    --collection-name airport-pickup-zones \
    --geofence-id sfo-terminal-1 \
    --geometry '{
      "Polygon": [[
        [-122.389, 37.612], [-122.385, 37.612],
        [-122.385, 37.616], [-122.389, 37.616],
        [-122.389, 37.612]
      ]]
    }'

IAM: least privilege per API (geo:SearchPlaceIndex*, geo:CalculateRoute*,
     geo:BatchUpdateDevicePosition*, geo:BatchEvaluateGeofences*).
```

---

## Concrete Examples

### 4.1 — Ride-Hail: Match Request in San Francisco

```
SCENARIO:
  Rider opens app at 37.7849, -122.4094 (Union Square area).
  Product: UberX. Time: Friday 5:45 PM.

STEP 1 — Reverse geocode (optional, for display):
  aws location search-place-index-for-position \
    --index-name ProdPlaceIndex \
    --position -122.4094,37.7849 \
    --max-results 1

  Returns: "333 Post St, San Francisco, CA"

STEP 2 — H3 index rider pickup:
  import h3
  rider_h3 = h3.geo_to_h3(37.7849, -122.4094, 9)
  # → '892830828cbffff'

STEP 3 — Query spatial index (Redis):
  cells = h3.k_ring('892830828cbffff', 1)  # 7 hexes at res-9
  candidates = []
  for cell in cells:
      key = f"h3:{cell}"
      drivers = redis.zrangebyscore(key, min=now-15, max=now)
      candidates.extend(drivers)
  # → 847 raw candidates (many duplicates across cells)

STEP 4 — Dedupe + filter:
  unique = dedupe(candidates)
  available = [d for d in unique if ddb.get(d).status == 'available']
  fresh = [d for d in available if now - d.updated_at < 15]
  # → 312 drivers

STEP 5 — Coarse filter (haversine < 2 km):
  nearby = [d for d in fresh if haversine(d, rider) < 2000]
  # → 48 drivers

STEP 6 — Road ETA for top 15 (AWS Location):
  aws location calculate-route \
    --calculator-name ProdRouteCalc \
    --departure-position -122.4101,37.7812 \   # driver 1
    --destination-position -122.4094,37.7849 \  # rider
    --travel-mode Car \
    --departure-time 2026-07-06T17:45:00-07:00

  Returns DurationSeconds, DistanceMeters for each driver.
  Sort by ETA ascending.

STEP 7 — Apply business rules:
  Remove drivers heading away (dot product of velocity vs rider vector < 0)
  Boost driver idle 25+ minutes (+0.15 fairness score)
  Apply surge zone multiplier from H3 res-8 parent cell

STEP 8 — Dispatch:
  Offer to drivers ranked 1, 2, 3 sequentially.
  Driver 1 accepts in 4.2 seconds.
  Trip created in DynamoDB Trips table.
  Total match latency: 87ms p50, 134ms p99.
```

### 4.2 — PostGIS: Airport Pickup Geofence

```sql
-- Schema
CREATE TABLE airport_zones (
  zone_id     TEXT PRIMARY KEY,
  airport_code TEXT NOT NULL,
  boundary    GEOGRAPHY(POLYGON, 4326) NOT NULL,
  min_dwell_sec INT DEFAULT 30
);

CREATE INDEX idx_airport_zones_boundary
  ON airport_zones USING GIST (boundary);

-- Insert SFO Terminal 1 approximate polygon
INSERT INTO airport_zones (zone_id, airport_code, boundary)
VALUES (
  'sfo_t1_pickup',
  'SFO',
  ST_GeogFromText('POLYGON((
    -122.3890 37.6120,
    -122.3850 37.6120,
    -122.3850 37.6160,
    -122.3890 37.6160,
    -122.3890 37.6120
  ))')
);

-- Check if driver is in pickup zone (called on location update)
SELECT zone_id, airport_code
FROM airport_zones
WHERE ST_Covers(
  boundary,
  ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography
);
-- $1 = lng, $2 = lat

-- Find all available drivers currently inside any airport zone
SELECT d.driver_id, az.airport_code
FROM drivers d
JOIN airport_zones az
  ON ST_Covers(az.boundary, d.location::geography)
WHERE d.status = 'available'
  AND d.updated_at > NOW() - INTERVAL '15 seconds';

-- EXPLAIN ANALYZE should show:
-- Index Scan using idx_airport_zones_boundary on airport_zones
-- Index Scan using idx_drivers_loc on drivers
```

### 4.3 — DynamoDB: Geohash GSI with Anti-Hot-Partition Sharding

```
TABLE DEFINITION (CloudFormation excerpt):

  DriverLocations:
    Type: AWS::DynamoDB::Table
    Properties:
      TableName: prod-driver-locations
      BillingMode: PAY_PER_REQUEST
      AttributeDefinitions:
        - AttributeName: driver_id
          AttributeType: S
        - AttributeName: geohash_shard
          AttributeType: S
      KeySchema:
        - AttributeName: driver_id
          KeyType: HASH
      GlobalSecondaryIndexes:
        - IndexName: GeohashShardIndex
          KeySchema:
            - AttributeName: geohash_shard
              KeyType: HASH
            - AttributeName: driver_id
              KeyType: RANGE
          Projection:
            ProjectionType: ALL

WRITE PATH:

  def update_driver_location(driver_id, lat, lng):
      gh7 = geohash.encode(lat, lng, precision=7)
      shard = random.randint(0, 3)
      geohash_shard = f"{gh7}#{shard}"

      dynamodb.put_item(
          TableName='prod-driver-locations',
          Item={
              'driver_id': driver_id,
              'geohash_shard': geohash_shard,
              'geohash_7': gh7,
              'lat': Decimal(str(lat)),
              'lng': Decimal(str(lng)),
              'status': 'available',
              'updated_at': int(time.time())
          }
      )

READ PATH (match query):

  def query_cell(gh7):
      results = []
      for shard in range(4):
          key = f"{gh7}#{shard}"
          resp = dynamodb.query(
              IndexName='GeohashShardIndex',
              KeyConditionExpression='geohash_shard = :k',
              FilterExpression='#s = :avail AND updated_at > :cutoff',
              ExpressionAttributeNames={'#s': 'status'},
              ExpressionAttributeValues={
                  ':k': key,
                  ':avail': 'available',
                  ':cutoff': int(time.time()) - 15
              }
          )
          results.extend(resp['Items'])
      return results

  center = geohash.encode(37.7749, -122.4194, 7)
  cells = [center] + geohash.neighbors(center)
  all_drivers = []
  for cell in cells:
      all_drivers.extend(query_cell(cell))
```

### 4.4 — H3 Surge Pricing Zone

```python
import h3

# Define downtown surge polygon (GeoJSON coordinates)
surge_polygon = {
    "type": "Polygon",
    "coordinates": [[
        [-122.42, 37.77], [-122.40, 37.77],
        [-122.40, 37.79], [-122.42, 37.79],
        [-122.42, 37.77]
    ]]
}

# Polyfill at resolution 8 (~461m hex edge)
surge_cells = h3.polyfill_geojson(surge_polygon, res=8)
# → set of ~45 H3 indices

SURGE_MULTIPLIER = 1.8

def get_surge_multiplier(pickup_lat, pickup_lng):
    cell = h3.geo_to_h3(pickup_lat, pickup_lng, 8)
    if cell in surge_cells:
        return SURGE_MULTIPLIER
    return 1.0

# Stored in Redis for fast lookup:
# SET surge:8928308280fffff 1.8
# On pricing request: GET surge:{h3_parent_8}
```

### 4.5 — AWS Location Service: End-to-End Tracker + Geofence

```python
import boto3

location = boto3.client('location')

# Register device position (called every 4 sec from driver app backend)
location.batch_update_device_position(
    TrackerName='prod-drivers',
    Updates=[{
        'DeviceId': 'driver-88421',
        'SampleTime': datetime.utcnow(),
        'Position': [-122.4101, 37.7812]  # [lng, lat]
    }]
)

# AWS evaluates against all geofences in linked collections
# EventBridge receives:
# {
#   "detail-type": "Location Geofence Event",
#   "detail": {
#     "EventType": "ENTER",
#     "GeofenceId": "sfo_t1_pickup",
#     "DeviceId": "driver-88421",
#     "SampleTime": "2026-07-06T17:45:00Z"
#   }
# }

# Lambda handler
def geofence_handler(event, context):
    detail = event['detail']
    if detail['EventType'] == 'ENTER':
        dynamodb.update_item(
            TableName='prod-drivers',
            Key={'driver_id': detail['DeviceId']},
            UpdateExpression='SET airport_eligible = :t, geofence_id = :g',
            ExpressionAttributeValues={
                ':t': True,
                ':g': detail['GeofenceId']
            }
        )
```

### 4.6 — Redis GEO (Alternative Index)

```
Redis GEO uses geohash internally (52-bit precision).

  GEOADD drivers:live -122.4193 37.7793 driver-1001
  GEOADD drivers:live -122.4180 37.7800 driver-1002

  GEORADIUS drivers:live -122.4193 37.7793 2 km WITHDIST COUNT 20 ASC

  Returns drivers within 2 km sorted by distance.

LIMITATIONS AT SCALE:
  → Single key "drivers:live" = single Redis shard hot spot
  → Split by city: drivers:sf, drivers:nyc
  → Or split by H3 cell keys (preferred at Uber scale)
  → GEORADIUS is O(N+log(M)) — fine for city shard, not global

WHEN REDIS GEO IS ENOUGH:
  Single-city MVP, < 50K active drivers, one Redis cluster.
```

---

## Production Patterns

### 5.1 — Location Update Pipeline

```
MOBILE → INGESTION → STREAM → INDEX → ANALYTICS

┌─────────┐   HTTPS    ┌──────────┐   Kafka    ┌─────────┐
│ Driver  │ ─────────► │ Ingest   │ ─────────► │ Topic:  │
│ App     │  batch 5s  │ (ALB+    │            │ driver- │
└─────────┘            │  Go svc) │            │ loc     │
                       └──────────┘            └────┬────┘
                                                    │
                    ┌───────────────────────────────┼────────────────┐
                    ▼                               ▼                ▼
             ┌────────────┐                  ┌────────────┐    ┌────────────┐
             │ Flink job  │                  │ S3 archive │    │ Kinesis    │
             │ → Redis    │                  │ (compliance│    │ Firehose   │
             │ → DynamoDB │                  │  7yr)      │    │ → Redshift │
             └────────────┘                  └────────────┘    └────────────┘

INGESTION VALIDATION RULES:
  → Reject if accuracy_m > 100 (unless last known good fallback)
  → Reject if timestamp skew > 30s from server time
  → Reject if implied speed > 180 km/h from last point
  → Coalesce: if 3 updates in 1 second, keep latest only

BACKPRESSURE:
  If Kafka lag > 60s → increase Flink parallelism
  If Redis write p99 > 10ms → shard by H3 prefix across clusters
```

### 5.2 — Dual-Index Pattern (Memory + Durable)

```
PROBLEM: DynamoDB query latency 5–15ms × 36 cell queries = too slow.

SOLUTION: ElastiCache as hot path, DynamoDB as recovery source.

  Write path:
    Kafka → Flink → Redis (primary index) + DynamoDB (async)

  Read path (match):
    Query Redis only.
    If Redis miss (failover): rebuild cell from DynamoDB scan (degraded mode)

  Redis structure:
    HASH  h3:{cell_id}  →  {driver_id: json_metadata}
    ZSET  h3:{cell_id}:ts  →  {driver_id: unix_ts}  (for staleness eviction)

  Eviction cron (every 10s):
    For each cell key, ZREMRANGEBYSCORE ts_key 0 (now - 30)

RECOVERY AFTER REDIS FAILURE:
  Replay last 30s of Kafka topic → rebuild index.
  MTTR target: < 60 seconds.
  During rebuild: widen match radius or show "limited availability."
```

### 5.3 — Stale Location Handling

```
DRIVER STATUS STATE MACHINE:

  AVAILABLE ──(accept trip)──► EN_ROUTE ──(pickup)──► ON_TRIP ──(dropoff)──► AVAILABLE
       │                           │
       │(no update 60s)            │(no update 120s)
       ▼                           ▼
  UNAVAILABLE                  ALERT_OPS

STALENESS THRESHOLDS (typical):

  ┌──────────────────┬─────────────┬──────────────────────────────┐
  │ Context          │ Max age     │ Action                       │
  ├──────────────────┼─────────────┼──────────────────────────────┤
  │ Match candidate  │ 15 sec      │ Exclude from query           │
  │ Map display      │ 30 sec      │ Show grayed icon             │
  │ Geofence eval    │ 10 sec      │ Skip evaluation              │
  │ Billing start    │ 5 sec       │ Require fresh fix            │
  └──────────────────┴─────────────┴──────────────────────────────┘

GHOST DRIVER PREVENTION:
  Driver kills app without going offline → last location persists.
  Fix: heartbeat timeout marks UNAVAILABLE even if status says AVAILABLE.
  Fix: require periodic foreground GPS when status=AVAILABLE.
```

### 5.4 — Supply/Demand Balancing with H3 Heatmaps

```
AGGREGATION PIPELINE:

  Kafka trip-requests → Flink window (1 min) →
    key by h3_to_parent(request_h3, res=7) →
    COUNT → Redis HASH demand:{cell}:{minute}

  Kafka driver-locations → Flink →
    key by h3_to_parent(driver_h3, res=7) →
    COUNT DISTINCT driver_id → supply:{cell}:{minute}

  Ratio = demand / supply → surge trigger if ratio > 2.0 for 5 min

DASHBOARD (Grafana):
  Geo map layer: H3 cells colored by supply/demand ratio.
  Alert: ratio > 3.0 in any res-7 cell for 10 min → ops review.
```

### 5.5 — Geofence-Restricted Matching

```
AIRPORT PICKUP RULE:
  Driver must be INSIDE airport geofence AND status=AVAILABLE
  to receive airport trip offers.

  Two indexes:
    1. H3 spatial index (general matching)
    2. SET geofence:sfo_t1 → {driver_ids inside zone}

  On geofence ENTER event → SADD geofence:sfo_t1 driver_id
  On geofence EXIT event  → SREM geofence:sfo_t1 driver_id

  Airport trip request:
    candidates = SINTER(general_h3_query, geofence:sfo_t1)
    If empty → "No drivers in pickup zone. Move to Terminal 1."
```

### 5.6 — Multi-Region Location Data

```
CHALLENGE: Driver near region boundary; rider in different AWS region.

PATTERN:
  → Partition spatial index by metro/city (not AWS region)
  → Metro "sf_bay" spans single Redis cluster + DynamoDB table
  → Cross-metro trips: hand off to destination metro index at trip start
  → GDPR: EU driver locations stay in eu-west-1; never replicate to us-east-1

ROUTE CALCULATION:
  AWS Location Route Calculator is regional but routes are global.
  Store map data provider keys per region for data residency compliance.
```

---

## Failure Modes

### Failure 1: Hot Geohash / H3 Cell (DynamoDB Throttling)

```
SCENARIO:
  New Year's Eve downtown. 8,000 drivers in H3 cell 8928308280fffff.
  40,000 match requests/minute query that cell.
  DynamoDB GeohashIndex partition for that key saturates.
  ProvisionedThroughputExceededException spikes.
  Match latency p99 → 4 seconds. Riders see spinner.

SYMPTOMS:
  → CloudWatch: UserErrors on DynamoDB table
  → ThrottledRequests metric > 0
  → Match service logs: "Retrying DDB query, attempt 3/5"
  → Geographic: only one neighborhood affected

ROOT CAUSE:
  Spatial index partition key = geohash/H3 cell.
  High supply density + high demand = hot partition.

FIX (immediate):
  → Failover match reads to Redis index (if dual-index deployed)
  → Increase DDB on-demand burst (automatic, but has limits)
  → Raise geohash precision from 7 → 8 for queries in affected metro

FIX (long-term):
  → geohash#shard pattern (4–8 shards per cell)
  → H3 res-10 instead of res-7 for indexing
  → Never use DynamoDB alone for hot spatial reads — cache mandatory
```

### Failure 2: Geohash Boundary Miss (No Drivers Found)

```
SCENARIO:
  Rider at cell edge. 12 drivers 50m away in neighboring cell.
  Match service queries ONLY rider's geohash, not neighbors.
  Result: "No drivers available" despite drivers on map.

SYMPTOMS:
  → Support tickets: "App shows cars but won't match me"
  → Logs: candidate_count=0, h3_query_cells=1 (should be 7+)
  → Reproduces at specific intersections (cell boundaries)

ROOT CAUSE:
  Missing k_ring(1) or geohash_neighbors() in query logic.
  Common bug in new engineer's first geo PR.

FIX:
  → Always query center + neighbors
  → Integration test: place rider and driver 1m apart across boundary
  → Code review checklist item: "neighbor cells included?"
```

### Failure 3: Stale Driver Positions (Ghost Supply)

```
SCENARIO:
  Driver closed app without toggling offline 20 minutes ago.
  Last location still in Redis index.
  Rider matched to driver 3 km away (actually at home).
  Driver never responds → 15s timeout → chain to next → bad UX.

SYMPTOMS:
  → High dispatch timeout rate
  → Accept rate drops
  → Driver app shows "available" in admin but no heartbeat

ROOT CAUSE:
  Status=AVAILABLE without freshness check on location timestamp.
  Or: Redis eviction job stopped (cron failure).

FIX:
  → Match query: updated_at > now - 15s (mandatory filter)
  → Background job: mark drivers UNAVAILABLE if no update 60s
  → Alert on Redis eviction cron last-success timestamp
```

### Failure 4: GPS Spoofing / Teleportation

```
SCENARIO:
  Fraudulent driver uses GPS spoof app to appear at airport
  (high trip value) while physically 30 km away.
  Accepts airport pickup, never arrives. Rider waits 10 min.

SYMPTOMS:
  → Airport queue complaints
  → Driver track shows impossible jumps (SOMA → SFO in 30 sec)
  → Cancellation rate spike for airport trips

DETECTION:
  → Velocity check: distance(last, current) / Δt > threshold
  → Mock location API flags (Android isMockLocation)
  → Compare GPS to cell tower / WiFi fingerprint (mobile SDK)
  → Historical pattern: driver never physically near airport before

FIX:
  → Reject location updates failing sanity checks
  → Require geofence dwell time 60s before airport eligibility
  → Manual review queue for flagged drivers
```

### Failure 5: PostGIS Geography/Geometry Type Mismatch

```
SCENARIO:
  Migration adds geometry column; app writes lat/lng as geometry.
  Geofence query uses geography cast inconsistently.
  ST_DWithin returns wrong drivers — includes drivers 5 km away
  in latitude but query intended 500m radius.

SYMPTOMS:
  → ETAs wildly wrong for "nearby" drivers
  → EXPLAIN shows Seq Scan (no index use)
  → Bug only manifests above 45° latitude

ROOT CAUSE:
  geometry ST_DWithin with degree units treated as meters.
  Or: SRID 0 (undefined) silently assumed.

FIX:
  → Standardize on geography(POINT, 4326) for all location columns
  → CHECK constraint: ST_SRID(location) = 4326
  → CI test: ST_DWithin 500m query at lat 0, 37, 64 must return same count
```

### Failure 6: Geofence Flapping (Enter/Exit Storm)

```
SCENARIO:
  Driver idles at geofence boundary (airport pickup line).
  GPS oscillates ±40m. 12 ENTER/EXIT events in 2 minutes.
  Each event triggers Lambda → DynamoDB write → push notification.
  Driver gets "You entered the zone" / "You left" spam.
  DynamoDB WCU spike on driver table.

SYMPTOMS:
  → EventBridge rule invocations 10× normal
  → Driver complaints about notification spam
  → geofence_state_changed metric oscillates

FIX:
  → Hysteresis: 2 consecutive inside readings to ENTER
  → 3 consecutive outside to EXIT
  → Debounce in Lambda: ignore opposite event within 30s
  → Use 50m interior buffer polygon (shrink geofence for enter,
    expand for exit — "donut" logic)
```

### Failure 7: Routing API Latency Cascade

```
SCENARIO:
  Match service calls AWS Location CalculateRoute for 50 candidates
  sequentially instead of batch/matrix.
  50 × 80ms = 4 seconds per match request.
  Match pool exhausted. Queue depth grows. p99 match time 12s.

SYMPTOMS:
  → Location Service API latency metric elevated
  → Match service thread pool 100% busy
  → Correlation: deploy changed "refine all candidates" logic

FIX:
  → Haversine pre-filter to top 10 BEFORE routing API
  → Use CalculateRouteMatrix (batch up to 350 origins × 1 dest)
  → Cache route segments: (h3_origin, h3_dest) → ETA minutes
  → Circuit breaker: if routing API p99 > 200ms, fall back to haversine×1.4
```

### Failure 8: Clock Skew in Location Timestamps

```
SCENARIO:
  Driver phone clock 90 seconds ahead (user manually set).
  Location updates appear "from the future."
  Staleness filter (updated_at > now - 15) fails — updates rejected.
  Driver invisible in match index despite active app.

SYMPTOMS:
  → Single-driver reports "not getting trips"
  → Logs: "rejected future timestamp"
  → Server time vs client time delta > 60s

FIX:
  → Use server_received_at for staleness, not client ts
  → Store client_ts for debugging only
  → NTP enforcement message in driver app if skew detected
```

### Failure 9: H3 Pentagonal Distortion Edge Case

```
SCENARIO:
  Test suite assumes exactly 6 neighbors for k_ring(1) = 7 cells.
  Driver near icosahedron pentagon vertex has 5 neighbors.
  Test passes in SF, fails in production for Arctic ops.

SYMPTOMS:
  → Missing candidates in extreme latitudes (rare for ride-hail)
  → Unit test failure when CI adds global coordinate cases

FIX:
  → Use h3.k_ring() return length, never hardcode 7
  → Document pentagon cells in runbook
  → For global products: integration tests at pentagon coordinates
```

### Failure 10: Surge Polygon Drift (Wrong Pricing)

```
SCENARIO:
  Marketing updates surge polygon in admin UI.
  H3 polyfill cache not invalidated.
  Riders inside new surge zone charged 1.0× instead of 1.8×.
  Revenue loss + driver complaints about low fares in busy area.

SYMPTOMS:
  → Pricing support tickets from specific block
  → Redis surge keys don't match admin polygon version
  → surge_config_version mismatch in logs

FIX:
  → Version surge configs: surge:v{version}:{h3_cell}
  → On polygon update: publish Kafka event → Flink rebuilds polyfill
  → Atomic swap: SET surge:current_version 42; rebuild all cells
  → Alert if demand/supply ratio high but surge=1.0 (sanity check)
```

---

## SRE Diagnostic Toolkit
### 7.1 — Metrics to Instrument

```
MATCH SERVICE:
  match_request_total              (counter, labels: city, product)
  match_candidate_count            (histogram) — should be 20-200, not 0 or 5000
  match_latency_seconds            (histogram, p50/p99 SLO: 100ms/200ms)
  match_empty_result_total         (counter) — spike = index bug or supply outage
  dispatch_offer_sent_total        (counter)
  dispatch_accept_rate             (gauge) — drop = stale drivers or bad ranking
  dispatch_timeout_total           (counter)

LOCATION INGESTION:
  location_update_received_total   (counter)
  location_update_rejected_total   (counter, labels: reason)
      reasons: accuracy, velocity, future_ts, stale
  location_ingest_lag_seconds      (histogram) — Kafka consumer lag proxy
  active_drivers_gauge             (gauge, by city)

SPATIAL INDEX (Redis):
  h3_index_size                    (gauge, by cell) — detect hot cells
  redis_georadius_latency_ms       (histogram)
  index_rebuild_duration_seconds   (gauge) — failover metric

DYNAMODB:
  ConsumedReadCapacityUnits        (by GSI, by key if possible)
  ThrottledRequests                (MUST be zero in steady state)
  SuccessfulRequestLatency         (p99 by operation)

GEOFENCE:
  geofence_event_total             (counter, labels: type=ENTER|EXIT, zone)
  geofence_flap_rate               (gauge) — events per driver per hour
  geofence_eval_latency_ms         (histogram)

ROUTING:
  route_api_latency_ms             (histogram)
  route_api_error_total            (counter)
  eta_discrepancy_meters           (histogram) — predicted vs actual at pickup
```

### 7.2 — Log Patterns to Search

```
# Zero candidates despite visible supply
match_service AND candidate_count=0 AND h3_cells_queried=1
→ Missing neighbor cell query (Failure 2)

# Hot partition
dynamodb AND ProvisionedThroughputExceededException AND geohash
→ Hot cell (Failure 1)

# Stale ghost drivers
dispatch AND timeout AND driver_last_update_age_sec>60
→ Staleness filter broken (Failure 3)

# GPS fraud
location_ingest AND rejected AND reason=velocity_exceeded
→ Spoofing or highway driver (may be legitimate — check distribution)

# Geofence storm
geofence_handler AND device_id=X | stats count by event_type
→ Flapping (Failure 6) if ENTER/EXIT alternates > 5/min

# PostGIS slow query (RDS PostgreSQL log)
duration: 842.3 ms  statement: SELECT ... ST_DWithin
→ Missing GiST index or geometry/geography mismatch (Failure 5)
```

### 7.3 — Exact Commands

```bash
# ── Redis: inspect H3 cell contents ──
redis-cli -h prod-spatial.cache.amazonaws.com
> ZCARD h3:892830828cbfffff:ts
> ZRANGEBYSCORE h3:892830828cbfffff:ts (NOW-15) +inf WITHSCORES LIMIT 0 20

# ── Redis: compare adjacent cells (boundary debug) ──
> KEYS h3:892830828*
# Compare counts across neighbors

# ── H3 CLI (h3-py or h3 CLI tool) ──
python3 -c "
import h3
lat, lng = 37.7849, -122.4094
c = h3.geo_to_h3(lat, lng, 9)
print('center:', c)
print('ring1:', list(h3.k_ring(c, 1)))
"

# ── DynamoDB: query one geohash shard ──
aws dynamodb query \
  --table-name prod-driver-locations \
  --index-name GeohashShardIndex \
  --key-condition-expression "geohash_shard = :k" \
  --expression-attribute-values '{":k":{"S":"9q8yyk#0"}}' \
  --select COUNT

# ── DynamoDB: detect hot keys (CloudWatch Contributor Insights) ──
aws dynamodb describe-contributor-insights \
  --table-name prod-driver-locations

# ── PostGIS: verify index usage ──
psql $DATABASE_URL -c "
EXPLAIN (ANALYZE, BUFFERS)
SELECT driver_id FROM drivers
WHERE ST_DWithin(
  location::geography,
  ST_SetSRID(ST_MakePoint(-122.4193, 37.7749), 4326)::geography,
  3000
) AND status = 'available'
LIMIT 20;
"

# ── PostGIS: find drivers in geofence ──
psql $DATABASE_URL -c "
SELECT COUNT(*) FROM drivers d
JOIN airport_zones az ON ST_Covers(az.boundary, d.location::geography)
WHERE d.status = 'available';
"

# ── AWS Location: test route ETA ──
aws location calculate-route \
  --calculator-name ProdRouteCalc \
  --departure-position -122.4101,37.7812 \
  --destination-position -122.4094,37.7849 \
  --travel-mode Car \
  --include-leg-geometry false

# ── AWS Location: list geofences ──
aws location list-geofences \
  --collection-name airport-pickup-zones

# ── Kafka: location stream lag ──
kafka-consumer-groups.sh --bootstrap-server $BROKERS \
  --describe --group flink-spatial-indexer

# ── Curl: match API debug (internal) ──
curl -s "https://match.internal/debug?lat=37.7849&lng=-122.4094" \
  -H "Authorization: Bearer $TOKEN" | jq '.candidate_count, .h3_cells, .latency_ms'
```

### 7.4 — Dashboard Panels (Incident Commander View)

```
Panel 1: Match p99 latency (last 4h) + SLO line at 200ms
Panel 2: Empty match rate (% requests with 0 candidates)
Panel 3: DynamoDB throttles (GeohashIndex) — must be flat zero
Panel 4: Kafka consumer lag (location indexer)
Panel 5: Active drivers by city (detect supply drop)
Panel 6: Dispatch accept rate (leading indicator of stale index)
Panel 7: Map: H3 cell heat (supply count) — visual hot cell detection
Panel 8: Route API error rate + latency

ALERT BURN RATES:
  Page: match_p99 > 500ms for 5m AND empty_match_rate > 5%
  Page: dynamodb_throttles > 0 for 2m on GeohashIndex
  Ticket: dispatch_accept_rate < 0.6 for 15m
  Ticket: location_ingest_lag_p99 > 30s
```

### 7.5 — Synthetic Probes

```
CANARY MATCH (every 60s from 5 fixed coordinates per city):
  → Assert candidate_count > 5 during peak hours
  → Assert latency < 300ms
  → Alert if candidate_count = 0 for 3 consecutive probes
    at coordinate known to have supply (detects index corruption)

BOUNDARY CANARY:
  Place rider/driver pair 10m apart across H3 boundary.
  Assert both appear in mutual candidate sets.

GEOFENCE CANARY:
  Virtual device path scripted through airport polygon.
  Assert exactly 1 ENTER and 1 EXIT event (not 10).
```

---

## Decision Framework
### 8.1 — Spatial Index Selection

```
START: What is the primary query pattern?

┌─ "Find entities within radius R of point P"
│  └─ Need distributed scale (millions of updates/sec)?
│     ├─ YES → H3 or geohash in Redis/DynamoDB GSI
│     │        Prefer H3 for mobility (hex aggregation)
│     │        Prefer geohash if Redis GEO / simple prefix queries
│     └─ NO  → PostGIS ST_DWithin with GiST index
│              (single-region, < 100K points, complex joins)
│
├─ "Aggregate demand/supply per zone"
│  └─ Hexagonal fairness / uniform neighbors?
│     ├─ YES → H3 (resolution 7-8 for city, 9 for block)
│     └─ NO  → S2 or geohash prefix counts
│
├─ "Point in polygon (geofence)"
│  └─ Complex polygons, legal boundaries, airports?
│     ├─ YES → PostGIS ST_Contains OR AWS Location Geofences
│     └─ Simple circles → ST_DWithin geography or H3 k_ring
│
├─ "Cover polygon with cells for O(1) lookup"
│  └─ Spherical accuracy critical?
│     ├─ YES → S2 RegionCoverer or H3 polyfill
│     └─ NO  → geohash bounding box (approximate)
│
└─ "Road network ETA"
   └─ AWS Location Service / OSRM / Google Routes API
      Never haversine alone for rider-facing ETA at dispatch time
```

### 8.2 — Storage Backend Selection

```
╔════════════════════════════════════════════════════════════════════════════════╗
║ WORKLOAD              │ RECOMMENDED STACK                                      ║
╠════════════════════════════════════════════════════════════════════════════════╣
║ MVP ride-hail 1 city  │ Redis GEO + Postgres (trips) + PostGIS (geofences)     ║
║ Scale 100K drivers    │ Redis H3 index + DynamoDB state + Kafka pipeline       ║
║ Global multi-city     │ Per-metro Redis cluster + H3 + regional DynamoDB       ║
║ Analytics / pricing   │ H3 in Flink → Redshift/BigQuery (H3 column)            ║
║ Compliance geofences  │ PostGIS (audit trail) + Location Service (runtime)     ║
║ Warehouse logistics   │ PostGIS + local UTM projection + batch routing         ║
╚════════════════════════════════════════════════════════════════════════════════╝
```

### 8.3 — Precision / Resolution Selection

```
TARGET: Each index cell should contain 50–500 candidates at peak
         (enough for choice, not enough to hot-spot)

  active_drivers_in_metro / desired_candidates_per_cell = target_cell_area

  San Francisco peak: 12,000 available drivers
  Target: ~200 drivers per cell → 60 cells → ~200 drivers/cell

  H3 res-8: ~461m edge → ~60 cells cover metro core → ✓

  Rural Montana: 200 drivers across 400 km²
  H3 res-6: ~3.2 km edge → fewer cells, acceptable sparsity

RULE: Use PARENT resolution for aggregation (surge, heatmaps),
      CHILD resolution for matching (candidate retrieval).

  Match at res-9 or res-10.
  Surge at res-7 or res-8.
  Analytics rollup at res-6.
```

### 8.4 — Build vs Buy (AWS Location Service)

```
USE AWS LOCATION SERVICE WHEN:
  → Team < 10 engineers, need geocoding + routing + geofences quickly
  → Compliance requires managed data handling
  → Traffic < 100M route requests/month (cost-effective)
  → Geofence enter/exit to EventBridge is exactly what you need

SELF-HOST WHEN:
  → Match volume > 500K/min (routing cost dominates)
  → Custom map data (OSRM with OSM extracts per city)
  → Sub-10ms routing needed (precomputed segment matrices)
  → Heavy offline batch (historical ETA model training)

HYBRID (common at scale):
  → AWS Location for geocoding + geofences
  → Self-hosted OSRM for ETA in match hot path
  → H3/Redis for spatial index (always custom)
```

### 8.5 — Interview Decision Tree (60-Second Version)

```
1. Clarify scale: drivers, updates/sec, cities, latency SLO
2. Draw pipeline: ingest → index → match → dispatch
3. Pick spatial index: H3 for ride-hail, justify over geohash
4. Address hot cells: finer resolution + Redis + sharding
5. Staleness: 15s cutoff, heartbeat, server-side timestamp
6. Geofences: hysteresis + PostGIS or managed service
7. ETA: haversine pre-filter → routing API top-N
8. Failure: boundary neighbors, ghost drivers, DDB throttles
```

---

## 9. Incident Scenario — Uber-Style Dispatch Meltdown

```
INCIDENT REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Severity: P1 (REVENUE / CUSTOMER IMPACT)
Service: Ride-hail platform "MetroMove" — SF Bay Area
Time: Saturday 11:47 PM (bar close surge)

ARCHITECTURE:
  Mobile apps → ALB → Match Service (Go, 48 pods)
  Location ingest → Kafka (24 brokers) → Flink → Redis Cluster (6 nodes)
  Driver state → DynamoDB (GeohashShardIndex GSI, 4 shards per cell)
  Geofences → AWS Location Service → EventBridge → Lambda
  Routing → AWS Location Route Calculator
  SLO: p99 match latency < 150ms, empty match rate < 2%

NORMAL BASELINE (Saturday 11 PM):
  Active drivers SF: ~8,200
  Match requests: ~180/sec
  Match p99: 95ms
  Empty match rate: 0.8%
  Dispatch accept rate: 78%
  DynamoDB throttles: 0

INCIDENT TIMELINE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

11:47 PM — PagerDuty P1: "MatchP99Critical — p99 890ms, SLO violated"
  On-call SRE opens Grafana.
  Match p99 spiked from 110ms → 890ms in 4 minutes.
  Empty match rate: 0.9% (normal).
  Error rate: 0.1% (normal).
  Customer complaints not yet visible.

11:49 PM — DispatchAcceptRateLow alert fires (62%, was 78%).
  Support Slack #incidents: "Can't get a ride in SOMA / Mission"
  NOT city-wide — geographically clustered.

11:51 PM — SRE checks match service logs:
  "ddb_throttle_retry" count up 400× in last 5 min.
  CloudWatch: DynamoDB ThrottledRequests on prod-driver-locations
  GeohashShardIndex → 1,247 throttles/min.

11:53 PM — Geographic overlay on dashboard:
  Hot cells concentrated in:
    H3 8928308280fffff (SOMA)
    H3 8928308281fffff (Mission)
    geohash prefix 9q8yyk (same area, precision 7)
  These cells: 2,100+ drivers, 340 match req/sec combined.

11:55 PM — Redis spatial index metrics NORMAL:
  redis_georadius p99: 2.1ms
  candidate_count from Redis path: 180-400 (healthy)
  BUT match service config flag USE_REDIS_INDEX=false since 11:30 PM
  (canary rollback gone wrong — see below)

11:58 PM — Engineering finds recent deploy:
  11:28 PM deploy match-service v2.14.3:
    "Optimize: query DynamoDB directly for fresher driver data"
    Feature flag redis_index_enabled rolled to 0% → 100% over 30 min
    Completed 11:58 PM — reads now bypass Redis entirely

12:02 AM — Incident commander declared.
  Status page: "Elevated wait times in San Francisco"
  340 match req/sec × 9 geohash cells × 4 shards = 12,240 DDB reads/sec
  Hot partition: geohash_shard = 9q8yyk#2 → sustained throttle

12:05 AM — Mitigation attempt 1:
  Scale match service 48 → 96 pods.
  RESULT: WORSE. More pods = more concurrent DDB queries on hot keys.
  Throttles increase. p99 → 1.4s.

12:08 AM — Mitigation attempt 2:
  Increase DynamoDB max concurrency / on-demand (already on-demand).
  RESULT: No effect. Hot partition hard limit hit.

12:10 AM — Data path investigation:
  Redis index HAS fresh data (Flink lag 0.8s).
  DynamoDB HAS fresh data but CANNOT SERVE READ RATE for hot cells.
  The v2.14.3 "optimization" removed the cache layer from read path.

12:14 AM — Secondary symptom appears:
  GeofenceFlapping alert — airport zone sfo_t1_pickup
  847 ENTER/EXIT events in 10 min (normal: 40)
  Separate issue? Or related?

12:18 AM — Driver reports in #driver-support:
  "App says I'm offline but I'm online"
  200+ reports. Coincides with match timeouts → drivers cycled
  to UNAVAILABLE by stale heartbeat logic conflicting with
  slow match responses (driver waiting for offer that never arrives).

SYMPTOMS SUMMARY AT 12:20 AM:
  ✓ Match p99: 1.4s (SLO 150ms)
  ✓ DynamoDB throttles: ~2,000/min on 3 partition keys
  ✓ Geographic: SOMA, Mission, Castro only
  ✓ Empty match rate: 1.2% (elevated but not catastrophic)
  ✓ Accept rate: 51%
  ✓ Redis index: healthy, unused
  ✓ Recent deploy: bypass Redis, DDB-only reads
  ✓ Geofence flapping: airport (secondary)
  ✗ Origin/server CPU: normal
  ✗ Kafka lag: normal
  ✗ GPS ingestion rate: normal

YOUR TASKS (answer in Section 10):
  Q1: Root cause chain — trace from deploy to user-visible "can't get a ride"
  Q2: Immediate mitigation — priority-ordered actions for next 15 minutes
  Q3: Why scaling match pods made it worse
  Q4: Is the geofence flapping related or independent?
  Q5: Long-term controls so this class of incident cannot recur
```

---

## 10. Expert Analysis — Full Worked Response

### Question 1: Root Cause Chain

```
THE COMPLETE CAUSAL CHAIN:

11:28 PM — Deploy match-service v2.14.3
  Change: redis_index_enabled feature flag ramp 0% → 100%
  Intent: "Fresher data" by reading DynamoDB GeohashShardIndex directly
  Effect: Every match request now issues 9 geohash cells × 4 shards = 36
          Query operations to DynamoDB instead of 7 Redis K-RING lookups

11:35 PM — Bar close surge begins (predictable Saturday pattern)
  Match requests SF core: 180/sec → 340/sec
  Supply concentrates downtown: 2,100 drivers in 3 H3 cells

11:42 PM — DynamoDB hot partition emerges
  Partition key geohash_shard = "9q8yyk#2" receives:
    340 req/sec × 36 queries = 12,240 read requests/sec
    (Not all hit same partition — but ~40% concentrate on 3 hot shards)
  Per-partition soft limit exceeded → ThrottledRequests

11:44 PM — Match service retry storm
  AWS SDK exponential backoff on throttled queries
  Each match request: 36 queries × up to 5 retries = 180 DDB ops
  Match latency: 95ms → 400ms → 890ms

11:47 PM — P1 alert fires (p99 SLO breach)

11:49 PM — Accept rate drops
  Slow match → slow dispatch offers → drivers accept other apps
  OR: offer timeout (15s) expires before match completes
  Chain dispatch queue backs up

11:51 PM — User-visible "can't get a ride"
  Not because zero drivers — because match pipeline too slow
  Some requests timeout at 2s client deadline → empty error
  Empty match rate only 1.2% because most requests SLOW, not empty

11:55 PM — Redis bypass confirmed
  Redis has correct data but is unused — the deploy removed it from path

12:05 PM — Scaling pods amplifies DDB load (see Q3)

12:14 PM — Geofence flapping (partially related — see Q4)

ROOT CAUSE (one sentence):
  Feature flag disabled Redis spatial index during peak surge, forcing
  all match reads through DynamoDB GSI hot partitions that cannot
  sustain bar-close query fan-out.

CONTRIBUTING FACTORS:
  → No canary on DDB throttle metric during flag ramp
  → Geohash precision 7 too coarse for SOMA density (too many drivers/shard)
  → No automatic fallback from DDB to Redis on throttle detection
  → Match service lacks circuit breaker on DDB path
```

### Question 2: Immediate Mitigation (Priority Order)

```
MINUTE 0–2: STOP THE BLEEDING

  Action 1: FLIP FEATURE FLAG (highest priority)
    redis_index_enabled = true (100% immediately)
    OR rollback match-service to v2.14.2

    Why first: Instantly removes 36 DDB queries per match.
    Redis p99 2ms → match p99 should recover in 2-3 minutes
    (cache warm already — Redis was being written all along).

    Command:
      aws appconfig start-deployment \
        --application-id $APP_ID \
        --environment-id prod \
        --configuration-profile-id match-service-flags \
        --configuration-version $VERSION_WITH_REDIS_TRUE

  Action 2: STATUS PAGE update
    "Investigating elevated wait times in San Francisco.
     Est. recovery 10 minutes."

MINUTE 2–5: VERIFY RECOVERY (do NOT scale pods yet)

  Watch:
    match_p99_latency → should drop below 200ms within 3 min
    dynamodb_throttled_requests → should go to zero
    dispatch_accept_rate → should climb toward 70%+

  If NOT recovering after 5 min:
    → Full rollback v2.14.2 via kubectl / ECS force deploy
    → Confirm Flink still writing Redis (check consumer lag)

MINUTE 5–10: ADDRESS DRIVER "OFFLINE" REPORTS

  Action 3: Pause auto-UNAVAILABLE cron (if safe)
    Drivers marked offline due to offer timeout during incident.
    Run batch job: set AVAILABLE for drivers with update < 30s
    AND manually confirmed online via heartbeat in last 2 min.

  Action 4: Clear dispatch queue backlog
    Cancel stale offers > 60s old in dispatch service queue.
    Prevents drivers receiving expired offers when system recovers.

MINUTE 10–15: GEofence flapping (if still firing)

  Action 5: Increase geofence hysteresis temporarily
    enter_required_readings: 2 → 4
    exit_required_readings: 3 → 5
    Reduces EventBridge/Lambda load during recovery traffic spike.

DO NOT DO (lessons from failed attempts):
  ✗ Scale match pods (adds DDB query concurrency — made it worse)
  ✗ Increase geohash precision mid-incident (requires reindex)
  ✗ Purge DynamoDB or Redis (destroys index)
  ✗ Disable surge pricing (doesn't fix match path)

SUCCESS CRITERIA (15 min):
  match p99 < 150ms for 5 consecutive minutes
  DDB throttles = 0
  accept rate > 75%
  PagerDuty resolved
```

### Question 3: Why Scaling Match Pods Made It Worse

```
MECHANISM:

  Each match request generates FIXED fan-out to DynamoDB:
    36 Query ops (9 cells × 4 shards)

  48 pods at 340 req/sec → ~7 req/sec per pod
  96 pods at 340 req/sec → ~3.5 req/sec per pod

  BUT: DDB throttling is per PARTITION KEY, not per client.

  More pods = more CONCURRENT in-flight queries to the SAME
  hot partition "9q8yyk#2".

  DynamoDB adaptive capacity can absorb bursts, but sustained
  concurrent reads to one partition → hard throttle regardless
  of how many clients.

  ANALOGY:
    One cashier (partition) serving one line (hot key).
    Opening more doors to the store (pods) doesn't help if
    everyone is in the SAME line.

  WHAT WOULD HELP:
    Fewer queries (Redis index) ✓
    More partitions (finer geohash / more shards) — long-term
    Request coalescing: one DDB query per cell per 100ms window,
    shared across pods (advanced pattern)

  LESSON:
    Scale horizontally only when the bottleneck is COMPUTE.
    Here bottleneck was DATA PARTITION throughput.
    Scaling compute into a data bottleneck = amplification.
```

### Question 4: Geofence Flapping — Related or Independent?

```
PARTIALLY RELATED — shared root cause, different mechanism.

INDEPENDENT COMPONENT:
  Geofence evaluation uses AWS Location Service Tracker,
  NOT the match service DDB path.
  Location Tracker → EvaluateGeofences → EventBridge

RELATED TRIGGER:
  During incident, driver apps showed "searching for ride" longer.
  Drivers idle at airport pickup queue (sfo_t1 geofence boundary).
  GPS naturally drifts ±30-50m when stationary (multipath).

  Normally: hysteresis (2 enter / 3 exit) handles this.

  AMPLIFYING FACTOR during incident:
  12:02 AM — ops ran manual script to "refresh driver status"
  during investigation. Script re-sent last-known positions for
  400 airport drivers to force index update.

  Script bug: replayed 60 seconds of historical positions
  in 5 seconds → Tracker received rapid position sequence
  crossing boundary back and forth → ENTER/EXIT storm.

EVIDENCE:
  Geofence flap started 12:14 AM (after script), not 11:47 AM
  Match latency spike started 11:47 AM
  
  → Primary incident: DDB hot partition (match path)
  → Secondary incident: geofence flap (ops script + boundary GPS)

FIX FOR SECONDARY:
  Roll back script. Increase hysteresis. Never bulk-replay
  historical positions to Tracker without deduplication.

CORRECT INCIDENT CLASSIFICATION:
  Primary: P1 match latency (revenue)
  Secondary: P3 geofence noise (ops annoyance, DDB write load)
```

### Question 5: Long-Term Controls

```
CONTROL 1: SPATIAL READ PATH ARCHITECTURE (mandatory)

  Redis (or Memcached) H3 index is PRIMARY for match reads.
  DynamoDB is source of truth for driver PROFILE, not hot spatial queries.
  Document in ADR: "DDB GeohashIndex is recovery-only, max 10 QPS per cell."

  Enforce in code:
    if redis_index_enabled || ddb_throttle_detected:
        candidates = redis.query(h3_ring)
    else:
        candidates = ddb.query(geohash_shards)  // degraded only

CONTROL 2: CANARY WITH PARTITION METRICS

  Feature flag ramps require:
    → DynamoDB ThrottledRequests = 0 for 15 min at each step
    → match_p99 < SLO at each step
    → Automatic rollback if throttle > 0 for 2 min

  Flag changes during peak hours (Fri/Sat 10 PM - 2 AM) FORBIDDEN
  without VP approval.

CONTROL 3: CIRCUIT BREAKER ON DDB SPATIAL PATH

  if ddb_throttle_rate > 10/min:
      open_circuit(60s)
      force_redis_path()
      page_oncall("DDB spatial circuit open")

CONTROL 4: FINER INDEX RESOLUTION IN DENSE CELLS

  Adaptive precision:
    if drivers_in_cell > 500: index at res-10 instead of res-9
    Automatic cell split in Flink job

  OR: dynamic shard count based on cell density (8 shards downtown, 2 rural)

CONTROL 5: QUERY COALESCING (advanced)

  Match service requests for same H3 cell within 50ms window
  coalesce into single Redis MGET or single DDB query.
  Result cached in-process for 50ms.
  Reduces duplicate fan-out when 340 req/sec hit same bar district.

CONTROL 6: INTEGRATION TESTS (CI blocking)

  test_boundary_neighbor_inclusion
  test_ddb_throttle_fallback_to_redis
  test_match_latency_under_synthetic_300rps
  test_geofence_hysteresis_at_boundary (no flap in 60 updates)

CONTROL 7: RUNBOOK — "Match Latency Spike"

  Step 1: Check redis_index_enabled flag
  Step 2: Check DDB throttles by GSI
  Step 3: Check H3 hot cell dashboard
  Step 4: DO NOT scale pods until data path confirmed
  Step 5: Flip flag / rollback before any other action

POSTMORTEM ACTION ITEMS:
  [ ] ADR-047: Spatial index read path architecture
  [ ] Circuit breaker PR in match-service
  [ ] Canary gate on DDB throttle metric
  [ ] Remove DDB-direct path from production code (Redis only)
  [ ] Ops script review: ban bulk Tracker replay without dedup
  [ ] Game day: simulate bar-close load monthly
```

### Additional Deep-Dive: Reconstructing One Failed Match Request

```
REQUEST at 11:52 PM:
  Rider: 37.7786, -122.4054 (SOMA, outside bar)
  POST /v1/match {pickup_lat, pickup_lng, product: "standard"}

MATCH SERVICE v2.14.3 (redis_index_enabled=false):

  T+0ms:   Receive request, validate JWT
  T+2ms:   h3 = geo_to_h3(37.7786, -122.4054, res=9)
           → 8928308280fffff
  T+3ms:   cells = k_ring(h3, 1) → 7 H3 cells
           Convert to geohash_7 for DDB GSI: 9q8yyk + 8 neighbors

  T+4ms:   Begin parallel DDB Query (36 total: 9 cells × 4 shards)
           Shard queries to partition "9q8yyk#2":
             Query 1: OK, 89 items, 12ms
             Query 2: OK, 102 items, 14ms
             Query 3: THROTTLED, retry 1 after 50ms
             Query 4: THROTTLED, retry 1 after 50ms
           ... cascading delays ...

  T+180ms: 28 of 36 queries complete, 8 still retrying
  T+340ms: All 36 complete (throttled queries succeeded on retry 3)
           Merge: 1,847 raw items (duplicates across cells)
  T+345ms: Dedupe → 412 unique drivers
  T+350ms: Filter status=available → 388
  T+352ms: Filter updated_at > now-15s → 241
  T+355ms: Haversine < 2km → 67 candidates

  T+360ms: Call Route Calculator for top 15 drivers
           Sequential API calls (bug — should be matrix):
           15 × 45ms = 675ms

  T+1035ms: Rank complete, dispatch offer to driver-4421
  T+1040ms: Return HTTP 200 to rider app

  Rider app client timeout: 1000ms
  → Rider saw timeout error at T+1000ms
  → Match actually succeeded at T+1040ms
  → Driver-4421 received offer rider never saw
  → Contributes to "ghost offer" and accept rate drop

THIS SINGLE REQUEST SHOWS THREE BUGS:
  1. DDB path instead of Redis (340ms vs ~15ms for index)
  2. No throttle circuit breaker (retries amplify latency)
  3. Sequential routing API (675ms) + client timeout mismatch
```

---

## Ops Sim: Northstar Courier Geofence Projection Drift

**Time box:** 50 minutes  
**Severity:** P1  
**Service / domain:** Geospatial indexing, courier dispatch, PostGIS/S2  
**Northstar system:** Northstar Commerce

### Rules of engagement

1. Answer from memory of the Geospatial Systems teaching section; do not re-read mid-drill.
2. Write decisions in order: T+0, T+5, T+15, T+30, T+60, and follow-up.
3. Tie every claim to a metric, log line, trace, query output, or config key from this packet.
4. Name the correctness invariant before proposing scale, failover, replay, or data repair.
5. Do not open the answer key until your response is written.

---

### Customer and on-call view

```text
WHAT USERS SEE:
  - Couriers across a river are assigned to unreachable pickups.
  - Source-of-truth records and derived projections disagree.
  - Support reports cluster in the named slice, not the full fleet.
  - A proposed generic mitigation would hide or worsen the invariant risk.

WHAT ON-CALL SEES:
  - Meters are interpreted as degrees after an SRID migration.
  - Fleet-average dashboards understate the incident.
  - The config fragment below changed recently or lacks a guardrail.
  - Repair must wait for a bounded affected set and idempotent operation key.

BUSINESS CONSTRAINT:
  Do not assign couriers that cannot physically reach pickup; dispatch can pause affected geofences.
```

### Why this fails physically

A dispatch migration treats meters as degrees and lowers S2 precision. Couriers across a river match into the wrong store geofence; stale-location fallback hides it.

Break it into these forces before answering:
- trigger: the release/config/data shape that started the failure
- amplifier: retry, cache, routing, projection, or observability behavior that widened it
- scarce resource: the metric that reaches a limit first
- invariant: what must remain conservative even while users see degraded experience
- repair boundary: the source of truth and operation id used after mitigation

### Recent change log

- The suspicious production lever is `distance.units: degrees`; tie it to the first bad minute before changing capacity.
- The dashboard that stayed calm does not expose `courier_eta_error_seconds{p95}` for the damaged slice.
- The runbook move closest to "increase dispatch radius globally" needs an explicit no-go decision on the bridge.
- The repair path is allowed only after the source-of-truth query and operation key are written down.

### Signals to use

```text
METRICS:
  - courier_eta_error_seconds{p95}: 90 -> 980
  - wrong_side_of_river_match_total: +3400
  - geofence_contains_disagreement_rate: 0.02% -> 11%
  - dispatch_accept_timeout_rate: 0.4% -> 13%
  - location_age_seconds{matched_courier,p99}: 181
  - postgis_st_dwithin_seqscan_total: +820k
  - s2_cell_level{service="dispatch"}: 12 -> 9
  - customer_cancellation_rate: 3.5% -> 14%

LOG LINES:
  - dispatch: ST_DWithin used units=degrees buffer=500
  - Northstar Courier Geofence Projection Drift: derived projection disagrees with source of truth
  - Northstar Courier Geofence Projection Drift: unsafe repair or fallback proposed on bridge
  - Northstar Courier Geofence Projection Drift: affected-slice metric exceeds fleet average
  - Northstar Courier Geofence Projection Drift: capacity check missing before replay/scale

TRACE / QUERY / INSPECTION NOTES:
  - Inspect SRID, S2 level, location age, and wrong-side-of-river matches.
  - Before/after config diff aligns with the first bad metric.
  - The affected set is bounded by time window plus business key.
  - One generic health check remains green and is a red herring.
```

### Config evidence

```yaml
distance.units: degrees
postgis.srid: 4326
buffer_meters_interpreted_as_degrees: true
s2.level: 9
fallback.ignore_geofence_on_timeout: true
```

### Decision clock

| Time | Event | Your move |
|------|-------|-----------|
| T+0 | Couriers are matched across a river. | Check units, SRID, and location age. |
| T+5 | Ops suggests increasing dispatch radius. | Reject wider wrong matches. |
| T+15 | Meters-as-degrees config is confirmed. | Rollback projection config. |
| T+30 | Affected geofences are paused. | Repair open assignments. |
| T+60 | ETA returns to normal. | Audit wrong-side matches. |
| T+24h | Maps review asks about canaries. | Add boundary geofence tests. |

### Allowed degradation

- Roll back or disable the specific dangerous config from the packet.
- Shed decorative, derived, notification, or analytics work before weakening source-of-truth correctness.
- Throttle retry/replay using the narrowest downstream capacity limit.
- Keep an affected-record ledger before customer-visible repair.
- Verify recovery with the sliced SLI plus the scarce-resource metric, not a fleet average.

### Reject these proposals

For each proposal, name the concrete failure mode it creates.

- increase dispatch radius globally
- ignore geofence on timeout
- trust stale courier locations
- repair from customer complaints only

### Questions to answer

**Q01.** What exact layer owns the failure and why is the most obvious graph a red herring?

**Q02.** Which config line is wrong, and what failure physics does it create?

**Q03.** Select three metrics and two log/inspection clues that prove your diagnosis.

**Q04.** What is the safe T+0 to T+5 announcement and freeze/rollback decision?

**Q05.** What do you stop first: trigger, amplifier, or repair job? Explain sequencing.

**Q06.** What invariant must remain true if every dashboard is stale?

**Q07.** Which bad fix is most tempting in this incident, and why does it make recovery worse?

**Q08.** What numeric capacity or blast-radius check is required before scale/failover/replay?

**Q09.** What is the source-of-truth query or ledger for the affected set?

**Q10.** Which derived systems may lag, and which external side effects require idempotency?

**Q11.** Write the durable config/architecture change and its acceptance test.

**Q12.** Who joins by T+10, and what is pre-authorized versus escalated?

### Self-review grid

| Error type | Count | Notes |
|------------|-------|-------|
| Wrong layer/root cause | | |
| Evidence gap | | |
| Unsafe first action | | |
| Capacity/blast-radius miss | | |
| Correctness invariant miss | | |
| Repair/replay mistake | | |
| Org/runbook gap | | |

**Pass bar:** correct mechanism, safe sequencing, explicit rejection of the bad fix, one numeric capacity check, and a repair plan grounded in source of truth.

**Answer key:** [answers/Week-08-Advanced-Patterns/Geospatial Systems Answers.md](../answers/Week-08-Advanced-Patterns/Geospatial%20Systems%20Answers.md)

