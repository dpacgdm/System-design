# Design Google Flights

> Week 12, Topic 3 - System Design. Flight search fan-out, partner APIs,
> fare cache freshness, itinerary graph generation, ranking, calendar search,
> rate limits, and quoted-vs-booked fare consistency.
> Cross-links: Week 12 Web Crawler, Week 12 Google Search, Week 11 payments,
> and `templates/DESIGN_MODULE_GATES.md`.

---

## Learning Objectives

### Foundation

After this module, you will be able to:

1. Explain why flight search is a freshness problem, not only a ranking problem.
2. Separate schedule data, fare data, availability data, and booking authority.
3. Design a fan-out search across airline, GDS, aggregator, and cache sources.
4. Build a fare cache with explicit staleness and confidence metadata.
5. Model itineraries as graph paths with constraints.
6. Explain calendar search without calling every partner for every date.
7. Rank flights by price, duration, stops, reliability, and user preferences.
8. Respect partner rate limits and contractual display rules.
9. Preserve quote-vs-book consistency with revalidation before handoff.
10. Diagnose stale price, missing route, and partner brownout incidents.

### Staff

After the Staff tier, you will be able to:

1. Size QPS and fan-out for popular origin/destination/date searches.
2. Choose cache keys that avoid user-specific leakage and stale fare surprises.
3. Bound API calls with per-partner budgets and adaptive degradation.
4. Design an itinerary graph that handles multi-city, open-jaw, and connection rules.
5. Separate precomputed calendar grids from live shopping.
6. Explain why "lowest price seen" is not a guaranteed bookable fare.
7. Build consistency states for quoted, revalidated, reserved, ticketed, and failed.
8. Handle partner-specific failure modes without global search outage.
9. Define abuse controls for scraping, fare harvesting, and partner quota abuse.
10. Create dashboards that show freshness, accuracy, and conversion, not only latency.

### Principal stretch

After the stretch tier, you will be able to:

1. Design multi-region flight search with partner-local egress and quota isolation.
2. Decide when to hide stale cheap fares versus show them with revalidation risk.
3. Negotiate product tradeoffs between price accuracy, breadth, latency, and cost.
4. Design a rate-limit marketplace where scarce partner calls are spent deliberately.
5. Explain legal and contractual constraints around fare display and booking handoff.
6. Evaluate ML ranking under fairness, revenue, and user-trust constraints.
7. Plan backfills when an airline changes fare families or baggage rules.
8. Build incident runbooks for "cheap fare shown, booking fails".
9. Prevent one tenant or partner from consuming all live-shopping capacity.
10. Design verification that detects systematic fare underquoting.

---

## Wrong Mental Models

### Foundation

```text
MENTAL MODEL #1: "Flights are just rows in a database."
Wrong. Schedules, fares, seat availability, fare rules, ancillaries, and booking
state come from different sources and change at different rates.

MENTAL MODEL #2: "Search result price is the booking price."
Wrong. Search results are quotes or cached observations until revalidated.
Airlines can change fare buckets between display and booking.

MENTAL MODEL #3: "Fan out to every airline on every query."
Wrong. Partner APIs have quotas, latency, costs, and contracts. Use cache,
precomputation, selective live shopping, and adaptive budgets.

MENTAL MODEL #4: "Calendar search is 30 normal searches."
Wrong. Calendar search must be precomputed, sampled, and confidence-labeled.
Calling every partner for every date pair explodes cost and rate limits.

MENTAL MODEL #5: "The cheapest itinerary is the best result."
Wrong. Users weigh duration, stops, time of day, airline, baggage, reliability,
emissions, airport changes, self-transfer risk, and booking confidence.

MENTAL MODEL #6: "Stale cache is only a UX issue."
Wrong. Stale cheap fares can create regulatory complaints, support load,
partner penalties, and conversion collapse.
```

### Staff

```text
MENTAL MODEL #7: "One global cache key per route/date is enough."
Wrong. Fare varies by cabin, passenger mix, point of sale, currency, refundable
flag, loyalty context, fare family, and sometimes device/channel contract.

MENTAL MODEL #8: "Partner timeout means no flights exist."
Wrong. It means one source failed. Search must label coverage and degrade using
cache or other partners while preserving truth about freshness.

MENTAL MODEL #9: "Availability count in cache is safe to trust."
Wrong. Seat counts are volatile and often bucketed. Availability must be
rechecked before quote lock, booking handoff, or ticketing.

MENTAL MODEL #10: "Graph shortest path solves itineraries."
Incomplete. The graph has constraints: minimum connection time, airport
terminal changes, married segments, fare combinability, visa risk, bags,
overnight layovers, and self-transfer policies.

MENTAL MODEL #11: "Ranking can hide backend inconsistency."
Wrong. Ranking can demote low-confidence fares, but it cannot make a stale
fare bookable. Accuracy telemetry must feed product decisions.

MENTAL MODEL #12: "Rate limits are only 429 counters."
Wrong. Partners enforce daily quotas, look-to-book ratio, cache-display rules,
IP allowlists, credentials, commercial penalties, and emergency cutoffs.
```

### Principal stretch

```text
MENTAL MODEL #13: "More freshness always wins."
Wrong. Live shopping every query can bankrupt the product or get partner access
revoked. Freshness is allocated to high-intent and high-risk surfaces.

MENTAL MODEL #14: "Google Flights is the merchant of record by default."
Wrong. Many flows hand off to airlines or OTAs. Some flows may be assisted
booking. Authority, liability, refunds, and payment handling differ.

MENTAL MODEL #15: "A price mismatch is just partner fault."
Wrong. The platform chose cache TTLs, ranking confidence, display copy,
revalidation timing, and retry behavior. User trust is shared responsibility.
```

---

## Requirements & Constraints

### Foundation - product scope

Functional requirements:

1. Search one-way, round-trip, and multi-city itineraries.
2. Filter by origin, destination, date, cabin, passengers, stops, airlines, bags, times, and price.
3. Show price, duration, stops, airline, fare family, baggage hints, emissions, and booking source.
4. Support flexible date and calendar price exploration.
5. Support nearby airports and region searches.
6. Support price tracking alerts.
7. Support deep links or handoff to airline/OTA booking pages.
8. Revalidate selected itinerary before booking handoff.
9. Display freshness/confidence when data is stale or approximate.
10. Respect partner display, caching, ranking, and attribution rules.
11. Provide admin/ops tools for partner health, route coverage, and cache controls.
12. Prevent scraping and automated fare harvesting.

Non-functional requirements:

1. Search p95 under 700 ms for cache-first normal queries.
2. Search p95 under 2.5 sec when selective live shopping is needed.
3. Calendar grid p95 under 500 ms from precomputed summaries.
4. Quote revalidation p95 under partner-specific budget, usually 3-8 sec.
5. Price accuracy target measured as quote-to-revalidate match rate.
6. Coverage target measured by route/date/source completeness.
7. Partner quota burn must stay inside contractual budgets.
8. One partner outage must not break global search.
9. User-specific data must not leak across cache keys.
10. Ranking changes must not hide systematic fare errors.
11. Search must degrade explicitly when freshness is lower.
12. Booking handoff must not imply guaranteed price unless a guarantee exists.

### Design Gates - authn/z trust boundary

1. Public anonymous users can search generic fares.
2. Signed-in users can save preferences and price alerts.
3. Partner API calls use service credentials and signed requests.
4. Admins use role-bound tools for route, partner, and cache operations.
5. The first trust boundary is CDN/API Gateway.
6. User identity is optional for search but required for alerts and personalization.
7. Partner credentials cross the strongest trust boundary and must never reach clients.
8. Authorization for partner calls is enforced by Partner Gateway.
9. Authorization for cache purge and fare override is enforced by Admin Service.
10. Authorization for user alerts is enforced by Alert Service.
11. Workload identity or mTLS is required between search, cache, and partner gateway.
12. Fail closed for partner credential access.
13. Fail closed for admin cache mutation.
14. Fail open with generic unauthenticated search if personalization policy is unavailable.
15. Every live-shopping call carries service identity, partner_id, route, and quota budget id.

### Design Gates - abuse and misuse

1. Scrapers harvest fare grids at high volume.
2. Competitors probe route/date prices repeatedly.
3. Bots trigger expensive live partner shopping.
4. Malicious clients vary passengers/currency to bypass cache.
5. Alert abuse creates notification and partner-load amplification.
6. Partners can accidentally send malformed or stale data.
7. Internal users can misuse fare override/admin tools.
8. Controls are per-IP, per-account, per-device, per-route, per-partner, per-API-key, and global.
9. Live-shopping endpoints use higher token cost than cache reads.
10. Calendar search has route/date budget caps.
11. Price alert creation is quota-limited per user and route.
12. Partner API errors are quarantined by partner and route before global suppression.
13. Evidence for scraping includes low dwell time, complete grid traversal, no clickouts, and high cache-busting diversity.
14. Evidence for organic travel planning includes repeated but narrow route exploration and clickout/book intent.
15. Bad fix: block all unauthenticated search during bot spike.
16. Bad fix: spend live partner quota for every suspicious query.
17. Bad fix: hide cheap fares only because they are operationally inconvenient.

### Design Gates - multi-tenant isolation

1. Tenants include airlines, OTAs, GDS partners, advertisers, and internal products.
2. Partner Gateway isolates credentials, quotas, and circuit breakers by partner_id.
3. Cache entries carry source attribution and contract metadata.
4. Ranking can be personalized but must not violate partner display rules.
5. One partner can be disabled without removing all route coverage.
6. One route/date can be quarantined without purging global cache.
7. Alert workload is isolated from interactive search.
8. Calendar batch jobs are isolated from live revalidation.
9. Admin tools require partner/route scope.
10. Logs and exports include partner_id, source_id, route, and query class.
11. Per-partner quota pages before shared egress or credentials are exhausted.
12. One large tenant cannot consume all live-shopping worker slots.
13. Contract-specific fare fields are not shown to unauthorized surfaces.
14. Test/sandbox partner feeds cannot poison production ranking.
15. User cache keys exclude user_id unless the data is truly personalized and protected.

### Design Gates - unit cost at target scale

Primary business unit: search query and live partner shopping call.

Target scale:

1. 100 million monthly active users.
2. 10 million searches/day.
3. 2,000 average search QPS.
4. 20,000 peak search QPS during travel events.
5. 70% cache-only search responses.
6. 25% cache plus selective live shopping.
7. 5% high-intent full revalidation.
8. Average candidate itineraries per query: 500 before ranking.
9. Calendar query covers up to 31 departure dates and 31 return dates.
10. Popular route cache refresh every 5-15 minutes.
11. Long-tail route cache refresh every hours or on demand.
12. Partner p95 latency ranges from 300 ms to 8 sec.
13. Partner daily quota can be route-specific and low.
14. Price alert batch processes tens of millions of subscriptions.
15. Search result freshness metadata retained for accuracy analysis.

Dominant cost lines:

1. Partner API fees and quota scarcity.
2. Compute for fan-out aggregation and graph search.
3. Cache storage for route/date/cabin/passenger grids.
4. Egress through partner-specific network paths.
5. Observability cardinality by route/date/partner/source.
6. Alert batch compute and notification delivery.
7. ML ranking features and training.
8. Support costs from price mismatch complaints.
9. Legal/compliance review for fare display.
10. Idle headroom for holiday peaks.

Cost guardrails:

1. Page if live-shopping calls per search exceed budget.
2. Page if partner quota burn exceeds projected day curve.
3. Page if price mismatch support tickets cross threshold.
4. Page if calendar refresh backlog misses freshness SLO.
5. Page if route/date cache miss storm exceeds origin budget.

### Design Gates - failure blast radius

Smallest failing units:

1. Partner API credential.
2. Partner route/date/cabin feed.
3. Fare cache key or route partition.
4. Itinerary graph shard.
5. Calendar batch partition.
6. Alert worker pool.
7. Ranking model version.
8. Region-specific partner egress cell.

Shared dependencies:

1. Identity for saved alerts.
2. Partner Gateway.
3. Fare cache.
4. Schedule store.
5. Ranking feature store.
6. Observability backend.
7. Global config service.
8. CDN/API Gateway.

Degrade first:

1. Personalization degrades before generic search.
2. Calendar precision degrades before selected itinerary revalidation.
3. Long-tail live shopping degrades before popular route search.
4. Low-confidence sources are hidden before high-confidence direct airline fares.
5. Price alerts defer before interactive quote validation.

Fail closed:

1. Partner credentials unavailable.
2. Admin fare override unavailable.
3. Booking guarantee unavailable.
4. User-specific loyalty fare cache uncertain.
5. Quote revalidation cannot confirm final price.

Runbook actions that widen blast radius:

1. Purging all fare cache for one partner route defect.
2. Disabling all partner calls instead of one partner_id.
3. Raising live-shopping concurrency without quota math.
4. Rolling back ranking without checking display contracts.
5. Reusing personalized fare cache for anonymous results.

---

## Architecture Overview

### Foundation - logical services

```text
Users
  |
  v
CDN / API Gateway / Abuse Edge
  |
  v
Search Frontend
  |
  +--> Query Normalizer
  +--> Itinerary Graph Service
  +--> Fare Cache Service
  +--> Partner Gateway
  +--> Calendar Price Service
  +--> Ranking Service
  +--> Quote Revalidation Service
  +--> Price Alert Service
  +--> Admin / Partner Ops
```

Core stores:

1. Airport and region metadata store.
2. Airline schedule store.
3. Minimum connection time and airport transfer rules.
4. Fare observation cache.
5. Availability and fare rule cache.
6. Itinerary candidate store for popular routes.
7. Calendar summary store.
8. Partner quota and health store.
9. User preference and alert store.
10. Quote/revalidation audit log.

### Staff - data freshness classes

Freshness classes:

1. STATIC: airports, terminals, time zones, aircraft type mapping.
2. SLOW: published schedules, minimum connection times, route maps.
3. MEDIUM: fare families, baggage rules, branded fare metadata.
4. FAST: prices, booking class availability, seat inventory.
5. LIVE: selected itinerary quote, taxes, fees, and booking handoff.

Why classes matter:

1. Static data can be CDN and memory cached.
2. Slow data can be batch refreshed.
3. Medium data needs versioned cache invalidation.
4. Fast data needs route/date confidence and TTL.
5. Live data is expensive and reserved for high-intent flows.

### Principal stretch - cells and egress

Flight search cells:

1. Region cell handles user latency and cache reads.
2. Partner egress cell handles credentialed API calls from approved IP ranges.
3. Quota cell tracks daily/hourly budget by partner and route.
4. Calendar batch cell refreshes low-priority grids.
5. Alert cell consumes stale-tolerant workloads.
6. Revalidation cell handles high-intent quote checks.
7. Ranking cell serves model versions and feature snapshots.

Cell isolation rules:

1. Alert jobs cannot starve live revalidation.
2. Calendar refresh cannot exhaust partner daily quota.
3. Partner A brownout does not consume Partner B worker pool.
4. One route/date cache storm does not evict global popular routes.
5. A bad ranking model can be rolled back without cache purge.

---

## Critical Paths

### Path 1 - query normalization

Foundation sequence:

1. User enters origin, destination, dates, passenger count, and cabin.
2. Search Frontend validates date range and passenger constraints.
3. Query Normalizer expands city codes to airports when needed.
4. Nearby airport expansion applies user-configured radius.
5. Time zones are normalized to local departure and arrival dates.
6. Passenger mix is canonicalized: adults, children, infants, seniors if supported.
7. Cabin is mapped to partner-specific cabin codes.
8. Currency and point of sale are inferred from locale and user settings.
9. Filters are split into hard constraints and ranking preferences.
10. Cache key is built from normalized, privacy-safe dimensions.
11. Abuse score is computed for query cost and scraping pattern.
12. Query plan chooses cache-only, cache-plus-live, or revalidation path.

Important normalized dimensions:

1. origin airport set.
2. destination airport set.
3. departure date.
4. return date or one-way marker.
5. passenger mix.
6. cabin.
7. point of sale.
8. currency.
9. nonstop/connection constraints.
10. baggage or refundable filters if they alter fare availability.
11. partner contract display context.
12. personalization key only when data is genuinely personalized.

Do not put in a public cache key:

1. user_id.
2. email.
3. raw session token.
4. loyalty account identifiers.
5. precise location when city-level is enough.
6. experiment ids that do not affect fare data.
7. random anti-cache query params.

### Path 2 - search fan-out plan

Foundation sequence:

1. Query Planner receives normalized request.
2. Planner checks route/date popularity.
3. Planner reads partner health and quota state.
4. Planner reads fare cache confidence.
5. Planner chooses candidate sources.
6. Cache Service returns recent fare observations and itinerary candidates.
7. Partner Gateway sends selective live-shopping calls when needed.
8. Aggregator merges cache and live responses.
9. Itinerary Graph Service fills missing connections from schedule graph.
10. Ranking Service scores candidates.
11. Response includes price, source, freshness, and revalidation risk.
12. Low-confidence or contractually invalid results are hidden or labeled.

Fan-out source types:

1. Direct airline APIs.
2. Global Distribution Systems.
3. OTA or aggregator feeds.
4. Cached fare observations from prior searches.
5. Batch-ingested fare files.
6. Schedule-only sources for candidate generation.
7. Historical price models for calendar hints.
8. User alert refresh observations.

Staff planning rules:

1. Do not fan out to every partner by default.
2. Spend live calls on high-intent, low-confidence, or high-value queries.
3. Prefer direct airline source when contract and latency allow.
4. Use cache for popular route/date candidates.
5. Use GDS/aggregator when direct airline is down or missing coverage.
6. Bound each partner call by deadline and quota token.
7. Return partial results with explicit coverage metadata.
8. Do not let one slow partner hold the entire response.
9. Feed live observations back into fare cache.
10. Sample some cache-hit queries for freshness measurement.

Fan-out deadline budget:

1. Frontend total budget cache-first: 700 ms p95.
2. Query normalize: 15 ms.
3. Cache reads: 50-120 ms.
4. Itinerary candidate generation: 50-150 ms.
5. Partner live calls: 300-2,000 ms depending path.
6. Aggregation and dedupe: 50 ms.
7. Ranking: 50-100 ms.
8. Response rendering: 30 ms.
9. Slow partner deadline: cut at per-source budget.
10. Revalidation path can be slower because user selected a fare.

### Path 3 - fare cache read/write

Foundation sequence:

1. Fare observation enters from live search, batch feed, or alert refresh.
2. Observation is normalized to canonical itinerary and fare dimensions.
3. Cache stores observed_price, currency, cabin, passenger mix, fare family, source, observed_at, and confidence.
4. Cache TTL depends on route popularity, travel date proximity, partner volatility, and source type.
5. Search reads cache by normalized route/date/cabin/passenger key.
6. Candidate cache entries are filtered by freshness and constraints.
7. Stale entries can remain for trend/calendar display with lower confidence.
8. Revalidation updates or invalidates selected entry.
9. Accuracy metrics compare displayed quote to revalidated price.
10. System learns partner/route volatility from mismatch history.

Cache key example:

```text
fare:v3:
  origin_set=SFO|OAK|SJC
  dest_set=JFK|EWR|LGA
  depart=2026-11-24
  return=2026-12-01
  pax=ADT1
  cabin=ECONOMY
  pos=US
  currency=USD
  filters=checked_bag_optional
```

Do include:

1. point of sale when it affects fares.
2. currency when partner returns currency-specific prices.
3. passenger mix.
4. cabin.
5. fare family when user filters by it.
6. refundable or bag constraints when availability differs.
7. source contract metadata.
8. observed_at and expires_at.
9. confidence and mismatch history.
10. partner attribution.

Do not include:

1. user_id for generic fares.
2. raw device fingerprint.
3. arbitrary sort order.
4. UI experiment if it does not alter fare.
5. scroll position.
6. anti-CSRF token.
7. incomplete airport expansion.

TTL strategy:

1. Popular routes get proactive refresh.
2. Near-term travel dates get shorter TTL.
3. Routes with high mismatch rate get shorter TTL.
4. Airline direct results can have different TTL from OTA cached feeds.
5. Calendar low-price cells can retain stale hints longer with label.
6. Selected itinerary must be revalidated regardless of cache TTL.
7. Fare cache can serve "from $X" but not guaranteed final price.
8. Cache invalidation from partner feed updates should be route/date scoped.
9. Cache purge should not remove schedule data.
10. Negative cache entries must expire quickly.

### Path 4 - itinerary graph generation

Foundation graph model:

1. Node can be airport-time state.
2. Edge can be flight segment with airline, flight number, departure, arrival, cabin, and operating carrier.
3. Edge can be ground transfer between airports if allowed.
4. Path can be one-way itinerary.
5. Round trip is pair of outbound and inbound paths with fare combinability.
6. Multi-city is ordered sequence of path constraints.
7. Edge weights include duration, price estimate, reliability, and penalties.
8. Constraints prune invalid paths before ranking.

Hard constraints:

1. origin/destination airport sets.
2. travel dates.
3. maximum stops.
4. cabin availability.
5. minimum connection time.
6. maximum connection time if configured.
7. airport transfer viability.
8. visa or overnight self-transfer warning when known.
9. carrier or alliance inclusion/exclusion.
10. fare combinability and married segment rules when source provides them.

Soft ranking features:

1. price.
2. total duration.
3. number of stops.
4. departure time convenience.
5. arrival time convenience.
6. airline preference.
7. airport preference.
8. delay/cancellation reliability.
9. baggage/ancillary clarity.
10. emissions estimate.
11. booking confidence.
12. source trust.

Candidate generation rules:

1. Generate schedules first, prices second when price coverage is sparse.
2. For popular routes, precompute top schedule skeletons.
3. For long-tail routes, use bounded graph search at query time.
4. Prune paths that violate minimum connection time.
5. Prune self-transfers unless user opts in or clearly labeled.
6. Keep enough diversity: cheapest, fastest, best, fewest stops, morning, evening.
7. Do not create impossible interline combinations just because graph connects.
8. Keep partner source attached to each priced path.
9. Deduplicate codeshares and operating/marketing carrier variants.
10. Preserve fare-rule source for revalidation.

### Path 5 - calendar search

Foundation sequence:

1. User asks for flexible dates.
2. Calendar Service loads precomputed low-price cells.
3. Cells are keyed by origin set, destination set, trip length, cabin, pax, point of sale, and currency.
4. Cells include observed_low_price, observed_at, confidence, and source coverage.
5. UI shows calendar heat map with freshness label.
6. User clicks a date pair.
7. Selected date pair triggers normal search and possibly live shopping.
8. Calendar observation is updated if selected search finds new price.
9. Alerts and background jobs refresh popular cells.
10. Calendar never guarantees final bookable fare.

Why precompute:

1. 31 departure dates * 31 return dates = 961 date pairs.
2. A full partner fan-out per cell would explode quota.
3. Calendar users browse more than they book.
4. Low-price hints can tolerate lower precision if labeled.
5. Popular routes benefit from batch refresh and alert observations.

Calendar refresh prioritization:

1. route popularity.
2. search volume.
3. alert count.
4. travel date proximity.
5. price volatility.
6. partner quota availability.
7. recent mismatch rate.
8. holiday or event demand.
9. stale cell age.
10. business priority.

Calendar pitfalls:

1. Showing stale low price without label.
2. Mixing one-way and round-trip fare logic.
3. Ignoring minimum stay requirements.
4. Ignoring point-of-sale differences.
5. Letting calendar batch consume live revalidation quota.
6. Treating historical model output as observed fare.
7. Purging all calendar cells for one partner defect.
8. Not recording source coverage for each cell.

### Path 6 - ranking and presentation

Foundation sequence:

1. Aggregator deduplicates equivalent itineraries.
2. Hard filters remove invalid candidates.
3. Ranking Service computes feature vector.
4. Candidate receives score for default "best" ranking.
5. Separate sort orders support cheapest, fastest, earliest, latest, and emissions.
6. Low-confidence fares are demoted or labeled.
7. Sponsored/partner placements follow display rules.
8. UI shows price, duration, stops, times, airline, and booking source.
9. UI explains when price changed or needs revalidation.
10. Clickout/revalidation events feed accuracy metrics.

Ranking features:

1. normalized price relative to route/date distribution.
2. total duration.
3. stop count.
4. layover quality.
5. departure/arrival time preference.
6. airport convenience.
7. airline/carrier preference.
8. baggage included or not.
9. refund/change policy.
10. reliability history.
11. source confidence.
12. freshness age.
13. predicted booking success.
14. emissions.
15. user explicit filters.

Ranking guardrails:

1. Do not rank unbookable stale fares at top without label.
2. Do not hide all direct-airline results because OTA margin is better.
3. Do not violate partner attribution or ordering contracts.
4. Do not use protected attributes for personalization.
5. Track price mismatch by rank position.
6. Track clickout failure by source.
7. Roll out ranking models with route/date slices.
8. Keep a deterministic fallback ranker.

### Path 7 - quote revalidation and booking handoff

Foundation sequence:

1. User selects itinerary.
2. Quote Revalidation Service receives canonical itinerary_id and selected fare source.
3. Service calls authoritative partner for current price, availability, fare rules, taxes, and fees.
4. Service compares current quote to displayed quote.
5. If match within policy, response marks quote_revalidated.
6. If price changed, UI shows new price and asks user to accept.
7. If unavailable, UI explains fare no longer available and suggests alternatives.
8. If partner timeout, UI says price could not be confirmed.
9. Booking handoff link or assisted booking token is generated only after policy passes.
10. Quote audit records displayed price, revalidated price, source, timestamps, and result.

Consistency states:

1. DISPLAYED_CACHE_OBSERVATION.
2. DISPLAYED_LIVE_OBSERVATION.
3. REVALIDATING.
4. REVALIDATED_MATCH.
5. REVALIDATED_PRICE_CHANGED.
6. REVALIDATED_UNAVAILABLE.
7. REVALIDATION_TIMEOUT.
8. HANDOFF_CREATED.
9. BOOKING_CONFIRMED_BY_PARTNER when callback exists.
10. BOOKING_UNKNOWN when handoff leaves platform.

Policy choices:

1. Allow small tax/fee deltas only if product/legal approves.
2. Require explicit user acceptance for material price increase.
3. Never guarantee price unless guarantee program backs it.
4. Hide sources with chronic revalidation failure.
5. Demote sources with high mismatch even if cheap.
6. Record mismatch even when user abandons.
7. Use partner-specific idempotency for assisted booking.
8. If platform is merchant of record, Week 11 payment rules apply.

## Data Model & Capacity Math

### Foundation - entities

Airport:

1. airport_code.
2. city_code.
3. country.
4. timezone.
5. latitude/longitude.
6. region group.
7. active flag.
8. terminal metadata version.

FlightSegment:

1. segment_id.
2. marketing_carrier.
3. operating_carrier.
4. flight_number.
5. origin_airport.
6. destination_airport.
7. departure_local_time.
8. arrival_local_time.
9. aircraft_type.
10. schedule_version.
11. days_of_operation.
12. validity_window.

Itinerary:

1. itinerary_id.
2. segment_ids ordered.
3. origin set.
4. destination set.
5. departure date.
6. return date nullable.
7. cabin.
8. passenger mix.
9. duration minutes.
10. stop count.
11. connection metadata.
12. source coverage.

FareObservation:

1. fare_observation_id.
2. itinerary_id.
3. source_id.
4. partner_id.
5. observed_price.
6. currency.
7. point_of_sale.
8. passenger mix.
9. cabin.
10. fare_family.
11. baggage summary.
12. availability_hint.
13. observed_at.
14. expires_at.
15. confidence.
16. fare_rules_hash.

QuoteAudit:

1. quote_audit_id.
2. user/session hash.
3. itinerary_id.
4. displayed_price.
5. displayed_source.
6. displayed_observed_at.
7. revalidated_price nullable.
8. revalidation_result.
9. partner_latency_ms.
10. mismatch_amount.
11. handoff_id nullable.
12. created_at.

PartnerQuota:

1. partner_id.
2. quota_window.
3. route_scope.
4. calls_allowed.
5. calls_used.
6. live_search_budget.
7. revalidation_budget.
8. alert_budget.
9. current_health.
10. circuit_state.

### Staff - partitioning and indexes

Recommended keys:

1. Fare cache partition by normalized route/date/cabin/passenger/pos.
2. Itinerary graph partition by origin region, destination region, and date bucket.
3. Schedule store partition by origin airport and departure date.
4. Calendar store partition by route, trip length, cabin, and month.
5. Partner quota key by partner_id and quota window.
6. Quote audit key by time bucket with route/partner indexes.
7. Alert subscription key by user_id and grouped cache key.
8. Partner health key by partner_id and route scope.

Avoid:

1. Global hot key for SFO-JFK holiday calendar.
2. Cache key missing point of sale.
3. Cache key including raw user_id for generic fares.
4. Partner quota tracked only in local process memory.
5. Ranking features that cannot be reproduced during audit.
6. Alert worker scanning all subscriptions per minute.
7. Itinerary id that changes when only price changes.

### Staff - search fan-out worksheet

Assumptions:

1. Peak search QPS is 20,000.
2. Cache-only share is 70%.
3. Cache-plus-live share is 25%.
4. Full revalidation share is 5%.
5. Cache-plus-live calls average 3 partners.
6. Revalidation calls average 1.2 partner calls due to retries/status checks.
7. Partner live call p95 is 1.5 sec for fast partners.
8. Aggregator worker can hold 200 concurrent outbound calls.

Calculations:

1. Cache-only QPS = 20,000 * 70% = 14,000.
2. Cache-plus-live QPS = 20,000 * 25% = 5,000.
3. Revalidation QPS = 20,000 * 5% = 1,000.
4. Live shopping partner calls/sec = 5,000 * 3 = 15,000.
5. Revalidation partner calls/sec = 1,000 * 1.2 = 1,200.
6. Total partner calls/sec = 16,200.
7. At 1.5 sec p95, live outbound concurrency is roughly 24,300.
8. Workers needed at 200 concurrency each = 122 before headroom.
9. With 2x headroom, plan about 250 outbound workers.
10. This math still fails if one partner has quota for only 100 QPS.

### Staff - calendar explosion worksheet

Assumptions:

1. Calendar grid has 31 departure dates.
2. Round-trip grid has 31 return dates.
3. Date pairs = 961.
4. Three cabins are displayed.
5. Three passenger mixes are common.
6. Four origin airports in nearby expansion.
7. Three destination airports in nearby expansion.
8. Five partner sources would be queried live in naive design.

Naive calls:

1. Date/cabin/passenger combinations = 961 * 3 * 3 = 8,649.
2. Airport pair combinations = 4 * 3 = 12.
3. Source calls = 8,649 * 12 * 5 = 518,940.
4. One user's calendar could consume over half a million source calls.
5. Therefore calendar must use precomputed summaries and selective refresh.

### Principal stretch - price accuracy metrics

Core metrics:

1. displayed_to_revalidated_match_rate.
2. median_mismatch_amount.
3. p95_mismatch_amount.
4. mismatch_rate_by_partner.
5. mismatch_rate_by_route.
6. mismatch_rate_by_cache_age_bucket.
7. mismatch_rate_by_rank_position.
8. unavailable_on_revalidation_rate.
9. partner_timeout_on_revalidation_rate.
10. user_abandon_after_price_change_rate.
11. support_ticket_rate_per_10k_clickouts.
12. alert_price_staleness_rate.

Accuracy budget:

1. High-confidence direct airline result can be ranked normally.
2. Medium-confidence cached result can show with freshness label.
3. Low-confidence result can be demoted or require live refresh before display.
4. Chronic mismatch source can be quarantined by route/date.
5. Calendar cells can be stale if clearly not a final quote.
6. Booking guarantee requires stronger policy and financial backing.

---

## Failure & Abuse Catalog

### Foundation - freshness and accuracy failures

1. Cached fare shown after booking class sells out.
2. Calendar low price is stale and selected search cannot find it.
3. Partner feed omits taxes or fees.
4. Fare family changes but cache key still treats old rules as valid.
5. Point-of-sale mismatch shows a fare unavailable to the user.
6. Currency conversion cache is stale.
7. Codeshare dedupe collapses two distinct booking sources incorrectly.
8. Schedule change invalidates connection path.
9. Minimum connection time table is stale after terminal change.
10. Revalidation timeout is presented as unavailable instead of unknown.

Mitigations:

1. Always revalidate selected itinerary.
2. Store observed_at, source, confidence, and cache age.
3. Track mismatch by partner, route, and cache age.
4. Shorten TTL for volatile route/date/source.
5. Label calendar values as observed, not guaranteed.
6. Keep schedule and fare rule versions.
7. Quarantine bad source narrowly.
8. Degrade to alternative partners or cached coverage.

### Staff - partner failures

1. Airline API returns 500s for one route.
2. GDS latency jumps to 8 seconds.
3. OTA partner sends malformed baggage rules.
4. Partner rate limits because look-to-book ratio is too high.
5. Partner credential expires.
6. Partner feed is delayed by six hours.
7. Partner changes fare family codes without notice.
8. Partner blocks one egress IP range.
9. Partner returns prices without required attribution.
10. Partner contract forbids caching longer than configured TTL.

Mitigations:

1. Circuit breaker by partner and route.
2. Per-partner deadlines.
3. Schema validation and quarantine.
4. Quota token bucket by source and workload class.
5. Credential rotation alert.
6. Feed freshness dashboards.
7. Contract metadata in cache.
8. Egress cell health checks.
9. Display-rule validation.
10. Partner-specific incident owner.

### Staff - itinerary graph failures

1. Graph search creates illegal connection.
2. Self-transfer displayed without warning.
3. Married-segment fare broken into impossible cheaper legs.
4. Multi-city path explodes combinatorially.
5. Nearby airport expansion creates unacceptable ground transfer.
6. Daylight saving transition shifts local date.
7. Overnight layover violates user filter.
8. Codeshare duplicate dominates results.
9. Aircraft/terminal data stale after schedule change.
10. Path generator ignores fare source combinability.

Mitigations:

1. Hard constraint pruning before ranking.
2. Minimum connection time table by airport/terminal.
3. Fare combinability rules attached to source.
4. Candidate beam width limits.
5. Explicit self-transfer label and opt-in.
6. Time-zone aware date handling.
7. Diversity rules and dedupe.
8. Regression tests for major airports and weird calendars.

### Staff - ranking failures

1. Cheap stale fares rank first and fail on click.
2. Ranking model overweights OTA margin.
3. Direct airline result hidden despite better confidence.
4. Sponsored placement violates display contract.
5. Personalization makes audits unreproducible.
6. Ranking deployment changes route coverage.
7. Model demotes accessible or baggage-inclusive options unexpectedly.
8. Low-emissions badge computed from stale aircraft data.
9. Experiment causes price mismatch for one locale.
10. Fallback ranker lacks source-confidence feature.

Mitigations:

1. Include freshness and booking-confidence features.
2. Slice metrics by route/date/partner/locale.
3. Keep deterministic fallback.
4. Store model version and feature snapshot in result logs.
5. Contract validation before rendering.
6. Guardrail on mismatch rate by rank position.
7. Human review for major ranking objective changes.

### Staff - abuse catalog

1. Fare scraping through route/date grid traversal.
2. Cache-busting by random passenger/currency/filter combinations.
3. Live-shopping endpoint abused to burn partner quota.
4. Price alert spam creates batch amplification.
5. Competitor probes one route every minute.
6. Botnet simulates clickouts to improve look-to-book metrics.
7. Credential stuffing targets saved traveler profiles.
8. Partner API key leaked into client or logs.
9. Admin user purges competitor partner cache.
10. Fraudulent OTA partner injects impossible cheap fares.

Controls:

1. Token costs by query expense.
2. Per-route/date grid traversal limits.
3. Account/device/IP/ASN quotas.
4. Live-shopping budget requires intent signal.
5. Alert creation and refresh quotas.
6. Partner credential secret scanning and mTLS.
7. Admin dual control for fare override or purge.
8. Source trust scoring.
9. Bot evidence based on dwell, clickout, and diversity.
10. Abuse dashboards separated from organic travel spikes.

### Principal stretch - compound incidents

Compound incident A:

1. A partner feed is delayed.
2. Calendar cells show cheap stale fares.
3. Ranking promotes cheapest source.
4. Revalidation fails for 38% of clicks.
5. Users report bait-and-switch.
6. Bad fix: purge all fares globally.
7. Safer fix: quarantine partner/route/date cells, demote low-confidence fares, preserve other coverage.

Compound incident B:

1. Holiday travel spike raises cache misses.
2. Planner spends live calls on calendar browsing.
3. Partner quota exhausts by noon.
4. High-intent revalidation starts timing out.
5. Bad fix: raise partner concurrency after quota is exhausted.
6. Safer fix: reserve revalidation budget, degrade calendar, reduce live shopping for low intent.

Compound incident C:

1. Airport terminal change invalidates minimum connection time.
2. Graph still produces tight connections.
3. Users click cheap itineraries that airlines reject.
4. Bad fix: hide all connecting flights.
5. Safer fix: patch MCT table, quarantine affected airport/date ranges, rerun candidate generation.

---

## Decision Frameworks

### Foundation - cache vs live shopping

Use cache-only when:

1. Route/date is popular and recently refreshed.
2. User intent is exploratory.
3. Fare confidence is high enough for display.
4. Partner quota is constrained.
5. Calendar or price trend surface does not claim final quote.

Use cache plus selective live shopping when:

1. Cache confidence is mixed.
2. Query has high commercial intent.
3. A direct airline source is fast and quota-safe.
4. Route/date volatility is high.
5. Results need coverage fill from one or two partners.

Use full revalidation when:

1. User selects an itinerary.
2. UI is about to generate booking handoff.
3. Fare is low-confidence or high-value.
4. Price guarantee may apply.
5. Assisted booking or payment happens on platform.

Do not use live shopping when:

1. Abuse score is high and no intent signal exists.
2. Partner quota is reserved for revalidation.
3. Partner circuit is open.
4. Query dimensions are cache-busting noise.
5. Calendar browsing can use summaries.

### Staff - freshness vs price accuracy

Show stale price with label when:

1. Surface is exploratory.
2. Revalidation is one click away.
3. Mismatch risk is moderate and measured.
4. User sees observed_at or "prices may change".
5. No guarantee is implied.

Hide or demote stale price when:

1. Revalidation mismatch rate is high.
2. Price is materially lower than source distribution.
3. Partner feed is known delayed.
4. Result would rank first due only to stale cheapness.
5. Legal/product policy requires current price.

Force live refresh before display when:

1. User selected a specific booking action.
2. Fare is from volatile source.
3. Cache age exceeds route/source threshold.
4. Price guarantee or assisted booking applies.
5. Prior mismatch for same route/source is active.

### Staff - partner rate-limit allocation

Reserve quota for:

1. Quote revalidation.
2. High-intent selected itinerary refresh.
3. Popular route freshness sampling.
4. Paid or contractual partner obligations.
5. Incident verification.

Spend opportunistic quota on:

1. Calendar refresh.
2. Long-tail route exploration.
3. Alert refresh.
4. Ranking feature enrichment.
5. Model training samples.

Cut first:

1. Bot or scraper traffic.
2. Calendar live fan-out.
3. Low-intent anonymous grid browsing.
4. Redundant partner calls with low incremental coverage.
5. Stale alert refreshes.

### Principal stretch - booking authority

Deep-link handoff is appropriate when:

1. Partner is merchant of record.
2. Platform does not handle payment.
3. Price is revalidated but final booking happens off-platform.
4. Refund and ticketing support remain with partner.
5. UI copy makes authority clear.

Assisted booking is appropriate when:

1. Contract allows platform checkout.
2. Payment, order, refund, and ticketing workflows exist.
3. Partner supports idempotent booking APIs.
4. Fare can be reserved or ticketed reliably.
5. Week 11 payment and ledger controls are implemented.

Price guarantee is appropriate only when:

1. Revalidation is strong.
2. Guarantee budget exists.
3. Terms are clear.
4. Fraud controls are in place.
5. Support can remediate mismatches.

---

## Ops Sim / Interview Drill

**Time box:** 45 minutes

**Severity:** P1 trust and partner quota incident

**Service / domain:** Flight search, fare cache, partner APIs, ranking, quote revalidation

**Northstar system:** Week 12 Google Search freshness and query-serving incident

### Rules

1. Answer without opening `answers/`.
2. Write decisions in order: T+0, T+5, T+15, T+60.
3. Separate stale cache, partner outage, ranking amplifier, and abuse traffic.
4. Name evidence for every claim.
5. Include at least one quota or fan-out calculation.
6. Reject bad fixes explicitly.

### 1. Scenario stem

```text
WHAT USERS SEE:
  Holiday searches for NYC -> LAX show "$198 round trip" at rank #1.
  Clicking the result often changes price to "$412" or says unavailable.
  Calendar view still shows many green $198 cells.
  Social media accuses the product of bait-and-switch.

WHAT ON-CALL SEES:
  displayed_to_revalidated_match_rate route=NYC-LAX dropped 96% -> 61%.
  revalidation_price_increase_p95 = $238.
  partner_api_429_rate{partner="SkyHub"} = 31%.
  partner_feed_lag_hours{partner="SkyHub"} = 7.4.
  ranking_top1_source_share{partner="SkyHub"} = 68%.
  calendar_cell_cache_age_p95_hours route=NYC-LAX = 9.1.
  live_calls_per_search = 5.8, budget = 2.2.
  high_intent_revalidation_timeout_rate = 18%.
  suspected_scraper_grid_queries_per_minute = 240,000.

BUSINESS CONSTRAINT:
  Contract requires SkyHub attribution when shown.
  Product requires not hiding all low fares if direct airline sources still validate.
  Partner ops says SkyHub daily quota will be exhausted in 40 minutes at current burn.
```

### 2. Telemetry pack

```text
METRICS:
  search_qps = 18,000
  route_qps{route="NYC-LAX"} = 2,400
  cache_hit_rate{route="NYC-LAX"} = 54%
  fare_cache_age_p95_minutes{source="SkyHub", route="NYC-LAX"} = 546
  fare_cache_age_p95_minutes{source="AirDirect", route="NYC-LAX"} = 18
  mismatch_rate{source="SkyHub", route="NYC-LAX"} = 39%
  mismatch_rate{source="AirDirect", route="NYC-LAX"} = 4%
  calendar_refresh_lag_minutes{route="NYC-LAX"} = 420
  partner_quota_remaining{partner="SkyHub"} = 120,000
  partner_quota_burn_per_minute{partner="SkyHub"} = 3,100
  revalidation_budget_reserved_per_minute{partner="SkyHub"} = 800
  actual_revalidation_calls_per_minute{partner="SkyHub"} = 1,900
  live_shopping_calls_per_minute{partner="SkyHub"} = 1,200
  alert_refresh_calls_per_minute{partner="SkyHub"} = 900
  bot_score_high_share_route_grid = 46%

LOG LINES:
  07:42:11 ranking result top1 source=SkyHub price=198 confidence=MEDIUM cache_age=08:55:14
  07:42:17 quote revalidate source=SkyHub displayed=198 current=412 result=PRICE_CHANGED
  07:43:01 partner 429 source=SkyHub route=NYC-LAX workload=calendar_refresh
  07:44:23 planner live_fanout partners=7 reason=cache_miss route=NYC-LAX
  07:45:36 abuse pattern route_grid ip_asn=AS64512 date_pairs=961 dwell_ms=90 clickouts=0
  07:46:02 calendar cell source=SkyHub price=198 observed_at=22:35 previous_day

CONFIG PACK:
  skyhub_cache_ttl_minutes: 720
  calendar_max_cell_age_minutes: 720
  ranker_price_weight: 0.52
  ranker_confidence_weight: 0.04
  live_partners_per_search_max: 8
  live_calls_per_search_budget: 2.2
  revalidation_quota_reserve_percent: 20
  calendar_refresh_priority: high
  alert_refresh_priority: high
  scraper_live_shopping_action: allow_cache_miss
```

### 3. Timeline & decision points

| Time | Event | Your move |
|------|-------|-----------|
| T+0 | Trust alert fires for NYC-LAX price mismatch. | Identify source, preserve revalidation quota, stop misleading top results. |
| T+5 | SkyHub feed lag and scraper grid traffic are confirmed. | Decide quarantine, ranking, calendar, and quota actions. |
| T+15 | SkyHub says feed recovery is 2 hours away. | Decide product degradation and partner communications. |
| T+60 | Quota burn is stable but users saw bad fares for an hour. | Define reconciliation, metrics, and durable fixes. |

### 4. Questions

**Q1 - Root cause and layer split**

1. Which layer owns the displayed-vs-revalidated mismatch?
2. Which component amplified the stale fare into top result?
3. Which workload is wasting partner quota?
4. Which traffic looks abusive?
5. What is the likely causal chain?

**Q2 - Evidence**

1. Which metrics prove SkyHub is stale?
2. Which metrics prove AirDirect should not be globally hidden?
3. Which config values are wrong?
4. Which log line proves calendar cells are stale?
5. Which signal distinguishes scraper traffic from organic browsing?

**Q3 - T+0 to T+5 mitigation**

1. What do you do before touching the global cache?
2. Do you purge all fares, quarantine SkyHub NYC-LAX, change ranking, or all?
3. How do you protect revalidation quota?
4. What do you do with calendar and alert refresh?
5. What user-facing label or suppression do you apply?

**Q4 - Capacity and quota math**

1. At 120,000 remaining SkyHub calls and 3,100/min burn, how long until exhaustion?
2. If search QPS is 18,000 and live_calls_per_search is 5.8, how many live calls/sec are attempted globally?
3. If the budget is 2.2 calls/search, how far over budget is the current planner?
4. Which workloads should be cut first?
5. How much quota should be reserved for high-intent revalidation?

**Q5 - Bad fix gallery**

1. Why is purging all fare cache dangerous?
2. Why is hiding all SkyHub results globally too broad?
3. Why is increasing `live_partners_per_search_max` dangerous?
4. Why is ranking solely by price dangerous?
5. Why is treating revalidation timeout as "unavailable" misleading?

**Q6 - Durable design fixes**

1. What cache TTL policy changes are needed?
2. What ranking feature/guardrail changes are needed?
3. What quota allocation changes are needed?
4. What abuse controls are needed?
5. What acceptance criteria prove price accuracy improved?

**Q7 - Org and comms**

1. Who owns partner communication?
2. Who owns product degradation copy?
3. What do you tell support?
4. Which actions require legal/product approval?
5. What goes into the postmortem?

### 5. Self-score after answer key

| Error type | Did it happen? | Note |
|------------|----------------|------|
| Treated cached price as guaranteed | | |
| Spent more partner quota before reserving revalidation | | |
| Purged globally instead of route/source quarantine | | |
| Ignored ranking amplifier | | |
| Missed scraper grid traffic | | |
| Forgot user/support communication | | |

**Pass:** correct layer split, safe quota sequencing, source-scoped mitigation, capacity math, and rejection of bad fixes.

---

## Takeaways + Reading

### Key takeaways

1. Flight search is built on observations, confidence, and revalidation.
2. Fare cache must carry source, age, point of sale, passenger mix, and confidence.
3. Itinerary generation is graph search plus hard travel and fare constraints.
4. Calendar search is a precomputed summary surface, not hundreds of live searches.
5. Ranking must include freshness and booking confidence, not only price.
6. Partner quota is a scarce resource that must be allocated by workload intent.
7. Quote-vs-book consistency is preserved by revalidating before handoff and being honest when price changes.

### Targeted reading

1. `Week-12-Search-and-Crawling-Designs/Design Google Search.md`
2. `Week-12-Search-and-Crawling-Designs/Design Web Crawler.md`
3. `Week-11-Commerce-and-Payments-Designs/Design Payment System.md`
4. `templates/DESIGN_MODULE_GATES.md`
5. `templates/OPS_SIM_TEMPLATE.md`
6. `Ops-Sims/Week-06-Northstar-CDC-Slot-Meltdown.md`
7. `Ops-Sims/Week-08-Northstar-Slow-Burn-Checkout.md`
