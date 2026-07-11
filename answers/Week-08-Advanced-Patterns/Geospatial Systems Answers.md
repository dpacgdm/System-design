# Answer Key - Geospatial Systems

> Open only after attempting the learner file questions.

## Ops Sim: Northstar Courier Geofence Projection Drift

> Open only after attempting the learner-side drill.

### Executive diagnosis

A dispatch migration treats meters as degrees and lowers S2 precision. Couriers across a river match into the wrong store geofence; stale-location fallback hides it.

A principal response separates the trigger from the amplifier and states the invariant before proposing capacity or repair. The answer should not say only "scale it" or "roll it back"; it must explain why this system failed this way.

### Evidence map

- `courier_eta_error_seconds{p95}: 90 -> 980`
- `wrong_side_of_river_match_total: +3400`
- `geofence_contains_disagreement_rate: 0.02% -> 11%`
- `dispatch_accept_timeout_rate: 0.4% -> 13%`
- `location_age_seconds{matched_courier,p99}: 181`
- `postgis_st_dwithin_seqscan_total: +820k`
- Config clue: `distance.units: degrees`
- Config clue: `postgis.srid: 4326`
- Red herring: a fleet average or generic health check that does not include the damaged slice.

### First 15 minutes: sequencing

1. Declare severity, name the invariant, and assign an incident commander.
2. Freeze deploys, config flips, schema changes, broad failovers, and bulk replay touching this path.
3. Stop the active amplifier before adding capacity: retry storms, unsafe repair, global fallback, bad routing, or telemetry blow-up.
4. Roll back or override the specific dangerous config while preserving source-of-truth writes.
5. Shed noncritical surfaces: dashboards, notifications, search, decorative metadata, analytics, or advisory enrichment as appropriate.
6. Verify with the sliced SLI and scarce-resource metric; do not declare recovery from a global average.
7. Start an affected-record ledger before any replay or customer-visible repair.

### Bad fixes

- `increase dispatch radius globally`: increases wrong matches when the unit/projection is already incorrect.
- `ignore geofence on timeout`: removes the physical constraint that protects dispatch feasibility.
- `trust stale courier locations`: matches people based on positions too old to satisfy ETA guarantees.
- `repair from customer complaints only`: under-counts silent bad assignments and misses orders without tickets.

### Capacity and blast radius

A principal answer gives at least one bound. Compute the affected slice, backlog or queue depth, derivative, safe downstream throughput, and time-to-exhaustion or time-to-drain. If those values are unknown, the safe move is to throttle and measure before scale/failover/replay.

Examples of the expected math:
- current backlog / safe drain rate = minimum repair duration
- free disk or pool headroom / growth rate = time-to-exhaustion
- affected tenants, SKUs, auctions, regions, orders, or carts from source-of-truth keys
- downstream provider/API/database quota that caps replay concurrency

### Repair and reconciliation

Source of truth: authoritative courier GPS pings, order pickup geofence, and dispatch decision logs.

Build the affected set from authoritative records in the incident window, not from cache, search, dashboards, or customer anecdotes alone. Repair must use stable idempotency or operation keys, be throttled to downstream headroom, and write an audit trail. Derived projections can be rebuilt after the invariant is safe.

### Durable fixes

- SRID/unit contract tests
- S2 precision review per city density
- max location-age enforcement
- geofence canaries for river/coast boundaries

Acceptance criteria:
- The exact bad config from the drill is blocked or requires senior review.
- A staging drill reproduces the old failure and verifies safe rollback/replay.
- The dashboard contains the sliced SLI and the scarce-resource metric together.
- The alert fires before customer impact or before the scarce resource reaches exhaustion.

### Org and runbook

By T+10 include incident command, the owning service team, the relevant platform/data owner, product/business owner, and support. Add payments, security, finance, warehouse, seller-ops, or customer-success when money, trust, physical fulfillment, or enterprise promises are involved.

Pre-authorized: rollback bad config, pause unsafe repair, shed noncritical work, throttle retry/replay, quarantine unhealthy replicas/consumers/pods, and communicate degraded mode. Escalate: destructive state changes, durability downgrades, broad failover, consistency weakening, manual ledger/customer remediation outside policy, or accepting derived data as truth.

### Principal-depth checklist

- Root mechanism, trigger, and amplifier are distinct.
- Evidence uses real metric/config names from the drill.
- First action protects the invariant, not the prettiest graph.
- Bad fixes are rejected with concrete failure modes.
- Capacity math precedes scale/failover/replay.
- Repair has source of truth, idempotency, throttle, and audit.
- Durable fixes include alerts, tests, config guardrails, and ownership.

### Principal model response

The root mechanism is spatial contract drift. A dispatch
migration uses degrees where meters were expected, lowers S2
precision, and permits stale-location fallback. Couriers are
matched across physical barriers such as rivers because the
geometry and freshness constraints are wrong.

First 15 minutes:

1. Declare P1 for dispatch feasibility and courier/customer
   trust.
2. Assign incident command, dispatch owner, geospatial data
   owner, mobile/location owner, PostGIS/search owner,
   support/ops, and city operations.
3. Freeze geofence migration, S2 precision changes, and global
   radius increases.
4. Revert or override the units/SRID contract on matching
   paths.
5. Disable stale-location fallback for assignment decisions
   beyond the accepted max age.
6. Degrade noncritical ETA/personalization while preserving
   pickup feasibility.
7. Build affected ledger from dispatch decisions, courier GPS,
   store geofence, order id, city, and timestamp.
8. Communicate affected cities/zones, not global courier
   outage, unless evidence widens.

Telemetry interpretation:

- `wrong_side_of_river_match_total: +3400` is physical
  impossibility evidence.
- `geofence_contains_disagreement_rate: 11%` shows two
  geospatial implementations disagree.
- `distance.units: degrees` with SRID 4326 explains the
  meters/degrees bug.
- `location_age_seconds p99: 181` proves stale fallback is
  participating.
- `ST_DWithin` seq scans show query/index path may also be
  degraded, but correctness comes first.

Capacity/blast radius:

- Count affected dispatches by city, geofence version, courier
  location age, and wrong-side barrier classification.
- If 3,400 wrong-side matches occurred over 20 minutes, the
  system is producing about 170 bad matches/minute until
  mitigated.
- Increasing radius globally widens the candidate set and can
  increase wrong-side matches rather than fix supply.

Bad fixes:

- Increasing dispatch radius globally makes an incorrect
  distance model more permissive.
- Ignoring geofence on timeout removes the physical feasibility
  guard.
- Trusting stale courier locations violates ETA and pickup
  constraints.
- Repairing only from customer complaints misses silent bad
  assignments and orders cancelled without tickets.

Repair:

- Source of truth is authoritative courier GPS pings, store
  pickup geofence, and dispatch decision log.
- Recompute affected assignments with the fixed SRID/units and
  location freshness rules.
- Classify orders as delivered, reassigned, cancelled,
  customer delayed, or needs support credit.
- Do not use derived ETA cache as authority for repair.

Durable architecture:

- Distance APIs carry units and SRID in type or contract tests.
- S2 precision is reviewed by city density and physical
  barriers.
- Max location age is enforced for assignment, with stale state
  producing re-ping or no-match.
- Boundary canaries include rivers, bridges, airports, coasts,
  and dense downtown polygons.
- Dashboards show geofence disagreement, wrong-side matches,
  location age, seq scans, assignment timeouts, and ETA error.

Question-by-question grading notes:

- Q1 should name unit/projection/freshness drift, not courier
  supply.
- Q2 should cite wrong-side matches, contains disagreement,
  SRID/unit config, and location age.
- Q3 should freeze radius/precision changes before scaling.
- Q4 should reject stale-location and geofence bypass.
- Q5 should compute affected match rate or city blast radius.
- Q6 should define GPS/geofence/dispatch logs as source of
  truth.
- Q7 should name dispatch, geo, mobile, support, and city ops
  owners.

Recovery is complete when:

- wrong-side match canaries are zero;
- geofence disagreement returns to baseline;
- location age is inside decision budget;
- affected orders are classified and customer communication is
  scoped;
- migration tests fail on meters/degrees and SRID mismatch;
- game-day covers one city rollback without global radius
  changes.

Minimum learner bar:

- If the answer increases radius before fixing units and SRID,
  it fails.
- If it accepts stale locations for assignment, it violates the
  dispatch invariant.
- If it cannot name the authoritative GPS/geofence/dispatch
  logs, it cannot repair safely.
- If it reports only global ETA, it misses physical boundary
  blast radius.

Interview-caliber close:

- State the coordinate system, unit, index precision, and
  max-location-age contract before proposing capacity.
- Verify at least one known-hard boundary canary, such as a
  river, bridge, airport, or coast polygon.
- Keep assignment decisions stricter than display ETA
  enrichment; display can degrade first.
- A passable answer always ties geography to physical
  feasibility, not only query latency.

---

