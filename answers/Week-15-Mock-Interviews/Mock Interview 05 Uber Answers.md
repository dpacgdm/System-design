# Answer Key - Mock Interview 05 Uber

> Open only after attempting the learner file questions.

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
