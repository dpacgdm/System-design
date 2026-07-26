# Answer Key - Design Google Flights

> Open only after attempting the learner file questions.

---

## Expert Analysis - Ops Sim Worked Response

### Q1 - Root cause and layer split

Displayed-vs-revalidated mismatch:

1. The mismatch belongs to fare cache freshness plus quote revalidation.
2. Search displayed stale SkyHub observations as if they were competitive current fares.
3. Revalidation proved current price was $412, not displayed $198.
4. This is not only a partner outage; our TTL, ranking, calendar, and quota policy amplified it.

Ranking amplifier:

1. `ranking_top1_source_share{partner="SkyHub"} = 68%`.
2. `ranker_price_weight = 0.52`.
3. `ranker_confidence_weight = 0.04`.
4. SkyHub stale low fares were cheap enough to dominate top result.
5. Confidence was too weak to demote 9-hour-old fares on a volatile holiday route.

Quota-wasting workload:

1. Calendar refresh is wasting quota: log line says partner 429 workload=calendar_refresh.
2. Alert refresh consumes 900 SkyHub calls/min.
3. Live shopping consumes 1,200/min.
4. Actual revalidation calls are 1,900/min, already above reserve.
5. Low-intent workloads are competing with high-intent revalidation.

Abusive traffic:

1. `suspected_scraper_grid_queries_per_minute = 240,000`.
2. `bot_score_high_share_route_grid = 46%`.
3. Log shows `date_pairs=961`, `dwell_ms=90`, `clickouts=0`.
4. That is complete calendar traversal without travel intent.
5. It should not trigger live shopping.

Causal chain:

1. SkyHub feed lags 7.4 hours.
2. Cache TTL allows SkyHub fares for 720 minutes.
3. Calendar max age also allows 720 minutes.
4. Ranking overweights price and underweights confidence.
5. Planner allows up to 8 live partners and 5.8 calls/search actual.
6. Scraper grid traffic increases cache misses and planner work.
7. Calendar and alert refresh burn partner quota.
8. SkyHub 429s increase revalidation timeout.
9. Users see stale $198, then $412 or unavailable on revalidation.

---

### Q2 - Evidence

SkyHub stale evidence:

1. `partner_feed_lag_hours{partner="SkyHub"} = 7.4`.
2. `fare_cache_age_p95_minutes{source="SkyHub", route="NYC-LAX"} = 546`.
3. `mismatch_rate{source="SkyHub", route="NYC-LAX"} = 39%`.
4. `calendar_cell_cache_age_p95_hours route=NYC-LAX = 9.1`.
5. Log shows SkyHub top result cache age `08:55:14`.
6. Calendar cell observed previous day at 22:35.

AirDirect should remain:

1. `fare_cache_age_p95_minutes{source="AirDirect", route="NYC-LAX"} = 18`.
2. `mismatch_rate{source="AirDirect", route="NYC-LAX"} = 4%`.
3. Product constraint says direct airline sources still validate.
4. Hiding all low fares would remove valid coverage.

Wrong config:

1. `skyhub_cache_ttl_minutes: 720`.
2. `calendar_max_cell_age_minutes: 720`.
3. `ranker_price_weight: 0.52`.
4. `ranker_confidence_weight: 0.04`.
5. `live_partners_per_search_max: 8`.
6. `revalidation_quota_reserve_percent: 20`.
7. `calendar_refresh_priority: high`.
8. `alert_refresh_priority: high`.
9. `scraper_live_shopping_action: allow_cache_miss`.

Calendar stale log:

1. `07:46:02 calendar cell source=SkyHub price=198 observed_at=22:35 previous_day`.
2. This directly proves the green $198 calendar cells are old.

Scraper signal:

1. Complete grid traversal: `date_pairs=961`.
2. Dwell time: `dwell_ms=90`.
3. Clickouts: `0`.
4. High route-grid bot score.
5. Organic users explore narrower date sets and produce clickout/revalidation intent.

---

### Q3 - T+0 to T+5 mitigation

Before touching global cache:

1. Confirm mismatch is source/route scoped.
2. Preserve revalidation quota.
3. Open SkyHub NYC-LAX route/source incident.
4. Freeze live fan-out increases.
5. Confirm direct airline sources still validate.

Immediate mitigation sequence:

1. Quarantine SkyHub fares for NYC-LAX holiday date range.
2. Demote or suppress SkyHub stale results on affected route/date cells.
3. Keep AirDirect and other validating sources visible.
4. Add user label: "Price last seen; confirm current price" for medium-confidence cells.
5. Disable SkyHub calendar refresh for affected route while feed is stale.
6. Cut alert refresh calls to SkyHub.
7. Reserve quota for selected-itinerary revalidation.
8. Block scraper cache misses from live shopping.
9. Lower live partners per search from 8 toward budget.
10. Notify support and partner ops.

Protect revalidation quota:

1. Increase reserve above 20% during incident.
2. Stop calendar and alert workloads from consuming SkyHub quota.
3. Enforce per-workload token buckets.
4. Allow only selected itinerary revalidation and high-confidence direct sources.
5. Shed low-intent anonymous grid traffic.

Calendar and alert actions:

1. Mark SkyHub NYC-LAX calendar cells stale or hide them.
2. Do not globally purge all calendar cells.
3. Pause SkyHub alert refresh on affected route/date.
4. Continue alert refresh from validating sources if quota-safe.
5. On alert click, force normal search and revalidation.

User-facing degradation:

1. If SkyHub source is stale, demote or suppress exact $198 claim.
2. Use "prices may have changed" label for older observations.
3. If revalidation changes price, require explicit user acceptance.
4. If timeout occurs, say price could not be confirmed.
5. Do not call timeout "unavailable" unless partner confirms unavailable.

---

### Q4 - Capacity and quota math

Time to exhaustion:

1. Remaining quota = 120,000.
2. Burn = 3,100/min.
3. Time = 120,000 / 3,100 = 38.7 minutes.
4. The prompt's "40 minutes" is consistent.
5. This is before additional retries from 429s and timeouts.

Global live call rate:

1. Search QPS = 18,000.
2. Live calls/search = 5.8.
3. Attempted live calls/sec = 18,000 * 5.8 = 104,400.
4. This is enormous and will hit partner, worker, and egress ceilings.

Over budget:

1. Budget = 2.2 calls/search.
2. Actual = 5.8.
3. Ratio = 5.8 / 2.2 = 2.64x.
4. Excess = 3.6 calls/search over budget.
5. Current planner is 164% over budget relative to allowed level.

Cut first:

1. Scraper live shopping.
2. Calendar live refresh.
3. Alert refresh on affected partner/route.
4. Redundant live fan-out beyond top validating sources.
5. Low-intent anonymous cache-miss expansion.

Revalidation reserve:

1. Existing reserve is 20%.
2. During incident, reserve should rise materially, e.g. 50-70%, depending contract.
3. At 3,100/min burn, 50% reserve would protect 1,550/min for revalidation.
4. Current actual revalidation is 1,900/min, so reserve must either exceed 61% or revalidation demand must be shed by suppressing stale SkyHub results.
5. Best fix is both: reduce bad clicks and reserve remaining quota.

---

### Q5 - Bad fix gallery

Purging all fare cache:

1. Removes valid AirDirect and other source coverage.
2. Creates cache miss storm.
3. Forces more partner live calls during quota incident.
4. Slows all routes, not only NYC-LAX.
5. Destroys evidence needed for mismatch analysis.

Hiding all SkyHub globally:

1. Too broad if only NYC-LAX holiday route/date is stale.
2. Reduces coverage and may violate partner obligations.
3. Could hide valid fares on other routes.
4. Partner-specific route quarantine is safer.
5. Global disable remains option if feed lag is global and severe.

Increasing live_partners_per_search_max:

1. Current live calls/search already exceeds budget.
2. More fan-out burns quota faster.
3. It worsens 429 and latency.
4. It may starve revalidation.
5. It attacks coverage symptom without fixing stale ranking.

Ranking solely by price:

1. It promotes stale cheap observations.
2. It ignores booking confidence.
3. It increases mismatch at top rank.
4. It harms user trust and support load.
5. It can violate display quality commitments.

Treating timeout as unavailable:

1. Timeout means unknown, not no seats.
2. User may retry elsewhere and still book.
3. Partner may have accepted or rate-limited request.
4. Metrics become inaccurate.
5. UI should say "price could not be confirmed."

---

### Q6 - Durable design fixes

Cache TTL changes:

1. SkyHub route/source TTL should shrink when feed lag rises.
2. Calendar max cell age should be lower for volatile holiday routes.
3. TTL should depend on mismatch history and travel date proximity.
4. Feed-lag signal should invalidate or demote affected cells.
5. Negative and stale cache entries need separate policies.
6. Route/date quarantine should be supported without global purge.

Ranking changes:

1. Increase confidence/freshness weight.
2. Add guardrail: stale low-confidence fare cannot be rank #1 above validating source.
3. Track mismatch by rank position.
4. Use deterministic fallback if ranking model drives mismatch spike.
5. Add source trust and revalidation success as features.
6. Route/date slices in rollout gates.

Quota allocation:

1. Separate token buckets for revalidation, live search, calendar, and alerts.
2. Revalidation reserve increases during source incidents.
3. Calendar and alerts are preemptible.
4. Planner hard-caps live partners per search near budget.
5. Scraper and low-intent traffic cannot consume live-shopping quota.
6. Partner quota burn dashboard projects exhaustion time.

Abuse controls:

1. Detect grid traversal across all 961 date pairs.
2. Require intent signal before live shopping.
3. Increase token cost for calendar cache-miss exploration.
4. Rate-limit by IP, account, device, ASN, route, and date grid.
5. Keep cache-only responses for suspicious traffic.
6. Alert on high bot_score share by route grid.

Acceptance criteria:

1. NYC-LAX match rate recovers above target.
2. SkyHub mismatch rate falls or source remains quarantined.
3. Revalidation timeout rate returns to normal.
4. Live calls/search stays at or below budget.
5. Partner quota exhaustion projection clears.
6. Top-rank mismatch rate is within guardrail.
7. Calendar stale-cell rate is under SLO with labels.
8. Support ticket rate per 10k clickouts falls.

---

### Q7 - Org and comms

Partner communication owner:

1. Partner operations owns SkyHub communication.
2. They should share feed lag evidence, 429 rate, affected routes, and quota projection.
3. They should ask whether route feed or global feed is delayed.
4. They should confirm contractual obligations before suppression.

Product degradation owner:

1. Product lead owns user-visible copy and suppression policy.
2. Search lead owns ranking and cache behavior.
3. Legal/compliance reviews bait-and-switch wording if needed.
4. Support lead receives macros for price-change complaints.

Support message:

1. "Some NYC-LAX holiday fares from one source were stale."
2. "The price shown in search is not final until confirmed."
3. "If revalidation shows a higher price, user must accept the new price."
4. "If confirmation timed out, do not say unavailable; say not confirmed."
5. "Escalate screenshots with route/date/source to incident queue."

Actions requiring approval:

1. Globally disabling a contractual partner.
2. Public incident statement.
3. Price guarantee or compensation.
4. Hiding all low fares from a partner.
5. Changing sponsored or contractual display order.

Postmortem contents:

1. Timeline from feed lag to top-rank mismatch.
2. Cache TTL and calendar age policy gap.
3. Ranking confidence weakness.
4. Quota allocation failure.
5. Scraper live-shopping gap.
6. User/support impact.
7. Partner communication timeline.
8. Durable action owners and due dates.

---

## Scoring Guide

Foundation pass:

1. States cached fares are observations, not guaranteed prices.
2. Requires revalidation before booking handoff.
3. Quarantines source/route rather than global purge.
4. Performs quota math.
5. Rejects ranking solely by price.

Staff pass:

1. Separates SkyHub stale feed, ranking amplifier, quota starvation, and scraper traffic.
2. Preserves revalidation quota before low-intent workloads.
3. Keeps AirDirect results because evidence shows they validate.
4. Uses confidence/freshness in ranking and display.
5. Provides T+0/T+5/T+15/T+60 sequence.

Principal stretch pass:

1. Handles contract, product trust, support, and legal tradeoffs.
2. Defines route/source quarantine and quota marketplace.
3. Designs durable abuse controls for grid traversal.
4. Sets acceptance criteria tied to accuracy, quota, and support metrics.
5. Avoids hiding valid low fares for operational convenience.
