# Design Ad Platform
> **Week 10 - Media and Mobility System Designs**
> **Interview themes:** Meta ads delivery, Netflix-style real-time ranking/logging, marketplace monetization, abuse-resistant attribution.
> **Northstar continuity:** Northstar Commerce runs marketplace search, feed, wallet, live auctions, and seller analytics across `us-east-1`, `eu-west-1`, and `ap-northeast-1`.
> **Answer key:** [`../answers/Week-10-Media-and-Mobility-Designs/Design Ad Platform Answers.md`](../answers/Week-10-Media-and-Mobility-Designs/Design%20Ad%20Platform%20Answers.md)

This module designs the ad serving platform behind sponsored listings, feed ads, and event promotions.
The interview target is not a banner endpoint; it is a marketplace where money, policy, ranking, and low-latency serving collide.
The learner file ends at questions; full model answers live under `answers/`.

## Learning Objectives

### Foundation

- Describe an ad request from page render through candidate retrieval, targeting, ranking, auction, logging, and reporting.
- Explain why an impression is not just an HTTP response and why click or conversion attribution is an asynchronous ledger-like workflow.
- Use frequency capping without putting a single hot counter on every active user or campaign.
- Size the low-latency serving path separately from the analytics and billing path.
- Name the source of truth for campaigns, budgets, creatives, user consent, and billable events.
- Distinguish first-price and second-price auction intuition without getting trapped in auction theory details.
- Explain why pacing is control theory applied to spend, not a cron job that checks budget once per hour.
- Draw the data plane and control plane as separate blast-radius domains.

### Staff

- Budget a 120 ms p99 ad decision while calling no unbounded dependency on the request path.
- Model hot keys from celebrity products, sale-day campaigns, and large advertisers, then isolate them without global cache flushes.
- Use Kafka/Flink-style streams to reconcile delivery logs, attribution, billing, and seller reporting under duplicate events.
- Build tenant isolation for advertisers so one tenant's burst, report export, or bad creative cannot degrade all auctions.
- Define rate limits across users, advertisers, campaigns, creatives, targeting keys, API keys, regions, and global pools.
- Identify which failures overcharge advertisers, underdeliver campaigns, leak targeting data, or violate privacy policy.
- Create a mitigation order for overpacing, underpacing, logging lag, auction latency, and attribution backlog.
- Calculate dominant unit costs per thousand ad requests and per thousand billable impressions.

### Principal stretch

- Defend the fairness and business tradeoffs between advertiser ROI, marketplace user trust, seller diversity, and platform revenue.
- Design privacy-safe measurement when mobile identifiers, cookies, and cross-device joins are unavailable or restricted.
- Constrain model and targeting teams so a new feature cannot silently change auction economics or protected-class exposure.
- Run multi-region failover without double spending a budget or replaying billable events twice.
- Evaluate blast radius when ads share infrastructure with feed, search, checkout, and seller analytics during Northstar peak auctions.

## Wrong Mental Models

### Mental model 1: The ad server only chooses the highest bid

- Why it fails: Highest bid can lose because eligibility, policy, user experience, quality score, pacing, frequency cap, and auction rules all happen before or during ranking.
- Interview correction: state the invariant, then draw the mechanism that enforces it on the request path or reconciliation path.
- Production smell: a design that optimizes revenue but cannot explain user trust, advertiser fairness, or billable-event correctness is incomplete.

### Mental model 2: Frequency cap is a simple Redis INCR

- Why it fails: A cap is keyed by user, campaign, creative, device, consent state, and time window; naive counters create hot keys and privacy problems.
- Interview correction: state the invariant, then draw the mechanism that enforces it on the request path or reconciliation path.
- Production smell: a design that optimizes revenue but cannot explain user trust, advertiser fairness, or billable-event correctness is incomplete.

### Mental model 3: Pacing means stop when the budget is empty

- Why it fails: Good pacing spends smoothly toward a target curve; bad pacing drains the campaign at 09:00 and underdelivers the rest of the day.
- Interview correction: state the invariant, then draw the mechanism that enforces it on the request path or reconciliation path.
- Production smell: a design that optimizes revenue but cannot explain user trust, advertiser fairness, or billable-event correctness is incomplete.

### Mental model 4: Attribution can be exact

- Why it fails: Attribution is probabilistic or rule-based under delayed conversions, multiple touchpoints, privacy limits, and duplicate client events.
- Interview correction: state the invariant, then draw the mechanism that enforces it on the request path or reconciliation path.
- Production smell: a design that optimizes revenue but cannot explain user trust, advertiser fairness, or billable-event correctness is incomplete.

### Mental model 5: Kafka logs are billing truth

- Why it fails: Raw logs are evidence; billing truth is a reconciled, deduped ledger with idempotency, audit, and correction workflows.
- Interview correction: state the invariant, then draw the mechanism that enforces it on the request path or reconciliation path.
- Production smell: a design that optimizes revenue but cannot explain user trust, advertiser fairness, or billable-event correctness is incomplete.

### Mental model 6: Second-price auctions make advertisers safe automatically

- Why it fails: Second-price intuition reduces bid shading but still needs reserve prices, quality scores, fraud controls, and budget enforcement.
- Interview correction: state the invariant, then draw the mechanism that enforces it on the request path or reconciliation path.
- Production smell: a design that optimizes revenue but cannot explain user trust, advertiser fairness, or billable-event correctness is incomplete.

### Mental model 7: Targeting is just matching user attributes

- Why it fails: Targeting uses consent, policy, freshness, inferred segments, negative targeting, lookalikes, inventory constraints, and legal restrictions.
- Interview correction: state the invariant, then draw the mechanism that enforces it on the request path or reconciliation path.
- Production smell: a design that optimizes revenue but cannot explain user trust, advertiser fairness, or billable-event correctness is incomplete.

### Mental model 8: Multi-tenant ads just means advertiser_id in a table

- Why it fails: Tenant isolation includes API quotas, report exports, creative review, cache keys, stream partitions, budget ledgers, and support tooling.
- Interview correction: state the invariant, then draw the mechanism that enforces it on the request path or reconciliation path.
- Production smell: a design that optimizes revenue but cannot explain user trust, advertiser fairness, or billable-event correctness is incomplete.

## Requirements and Constraints

### Product scope

- Serve sponsored product ads on search results, product detail pages, home feed slots, and live auction companion panels.
- Support advertiser campaign creation, creative upload, targeting, budgets, bids, pacing, reporting, and billing exports.
- Choose up to N ads per request within 120 ms p99 server-side budget for the ad decision.
- Enforce user consent, privacy restrictions, seller safety policy, and marketplace content policy before ranking.
- Log impression, viewability, click, conversion, auction, and delivery-decision events with replayable identifiers.
- Attribute conversions to ad touchpoints using deterministic rules first and privacy-safe aggregation where deterministic joins are unavailable.
- Provide near-real-time delivery metrics within 5 minutes and finalized billing within 24 hours.
- Allow Northstar support to disable one advertiser, campaign, creative, placement, or targeting rule without a global deploy.

### Functional requirements

| ID | Requirement | Notes |
| --- | --- | --- |
| F1 | Ad request returns zero or more eligible ads | Zero ads is valid when policy or budgets eliminate candidates. |
| F2 | Campaign control plane manages status, budget, bids, targeting, creatives | Writes are strongly authorized and auditable. |
| F3 | Serving path enforces targeting, pacing, caps, and auction | No unbounded DB joins on request path. |
| F4 | Impression/click/conversion logs are durable | At-least-once ingestion plus idempotent reconciliation. |
| F5 | Reporting separates real-time estimates from billing truth | Dashboards can be approximate; invoices cannot. |
| F6 | Abuse controls detect click fraud and astroturf campaigns | Controls feed both serving and billing review. |
| F7 | Multi-tenant API and reporting | Advertisers cannot see or exhaust another advertiser. |
| F8 | Regional privacy behavior | EU consent and data residency change available targeting and joins. |

### Non-functional requirements

| Area | Target | Why it matters |
| --- | --- | --- |
| Serving latency | p99 <= 120 ms for ad decision | Feed/search/page rendering cannot wait on ads. |
| Availability | 99.99% for serving, 99.9% for advertiser UI | Serving is user-facing; UI can degrade to read-only. |
| Freshness | Campaign updates visible to serving within 60 seconds | Advertisers expect pauses and budget changes to work quickly. |
| Logging durability | No acknowledged billable event is lost | Revenue and advertiser trust depend on auditability. |
| Attribution lag | Initial within 15 minutes, final within 24 hours | Fast enough for pacing; final enough for billing. |
| Consistency | Budget cannot overspend beyond bounded guardrail | A small controlled overspend may be acceptable; unbounded overspend is not. |
| Cost | Unit cost tracked per thousand requests and per tenant | Auction CPU and stream volume can erase margin. |
| Abuse | Throttle coordinated clicks, fake conversions, scraping | Authenticated actors can still be malicious. |

### Constraints and assumptions

- Northstar baseline: 12M DAU, 45k checkout-event TPS peak, 800k concurrent users during major live auctions.
- Ads are served in three regions, with `us-east-1` primary for campaign management and regional serving cells for latency.
- The platform starts with sponsored products and marketplace seller ads; offsite ad network exchange is out of scope for V1.
- User profile, catalog, inventory, feed, search, wallet, and risk systems already exist and emit Kafka events.
- Consent service is authoritative; if consent is absent, use contextual targeting only or return no personalized ad.
- Checkout correctness must never depend on ad systems; ads may observe conversions but cannot block orders.
- Advertisers are tenants, but sellers may also be advertisers; tenant and seller identities must not be conflated.
- The system must survive Black Friday and live auction traffic where hot products dominate ad inventory.
- Design for at-least-once event delivery and duplicate client logs; every money-impacting event needs an idempotency key.
- Serve stale read models for a short window, but never serve a paused creative or blocked advertiser after policy revocation reaches the serving cell.

### Out of scope for this module

- Self-serve creative editor details beyond upload, validation, review, and status.
- Full ML feature engineering for lookalike audiences; this module treats features as inputs with freshness and policy constraints.
- Legal definitions of every privacy regime; the design handles consent and data minimization as hard requirements.
- External real-time bidding exchanges; the auction here is first-party marketplace advertising.
- Payment collection from advertisers beyond exporting reconciled charges to Northstar wallet and ledger systems.

## Critical Paths

### Architecture map

```text
Client page render
  -> Northstar API gateway
  -> Placement service decides ad slots
  -> Ad serving cell
     -> request context builder: user, page, catalog, consent, geo, device
     -> candidate retrieval: campaign index, catalog index, targeting inverted index
     -> policy filter: creative status, seller safety, restricted categories, consent
     -> pacing and budget guard: spend curve, daily budget, tenant quota
     -> frequency cap service: user/campaign/creative/window counters
     -> ranker: predicted CTR/CVR/value and marketplace quality
     -> auction: choose winners, price impressions or clicks
     -> response: ad markup, tracking tokens, auction metadata hash
  -> durable event collector
     -> Kafka impression/click/conversion topics
     -> Flink reconciliation: dedupe, attribution, billing ledger, reporting marts
Advertiser UI
  -> campaign API -> campaign DB -> changelog -> serving read models per region
```

### Request path: ad decision in 120 ms

1. Gateway authenticates the user session or anonymous device token and attaches request_id, region, and consent state.
2. Placement service names the inventory: search_top_1, search_middle_2, feed_card_5, product_detail_sponsor, or live_auction_panel.
3. Context builder fetches bounded data from local caches: coarse user segment, recent viewed categories, page item, geo, device, and seller safety labels.
4. If consent is missing or profile cache is stale beyond policy TTL, drop personalized fields and continue with contextual targeting.
5. Candidate retrieval reads precomputed indexes keyed by placement, category, keyword, geo, language, and advertiser tier.
6. The retrieval layer returns hundreds of candidate campaign_creative pairs, not millions of raw campaigns.
7. Policy filter removes paused campaigns, rejected creatives, out-of-stock products, restricted categories, blocked sellers, and conflicts with page content.
8. Budget guard checks a regional spend shadow plus a central budget lease; it rejects candidates that cannot safely spend.
9. Pacing guard compares actual spend to expected spend on a curve and applies a probability gate or bid multiplier.
10. Frequency cap checks user-campaign and user-creative windows using sharded counters or compact sketches.
11. Ranker scores candidates with bid, predicted click-through rate, predicted conversion rate, margin, quality, freshness, and user fatigue.
12. Auction chooses winners per slot and computes clearing price according to first-price or second-price product rules.
13. Response includes creative payload, click/impression tokens, experiment IDs, price metadata hash, and debugging fields for sampled internal traffic.
14. The server emits a delivery-decision event even when no ad was served, so underdelivery can be diagnosed.
15. The client separately fires viewability and click events; server-side response is not automatically billable.
16. All external calls have fixed deadlines; timeout of ranking or feature service falls back to cached simple scoring or no-ad depending on policy.

### Control path: campaign creation and update

- Advertiser authenticates with tenant-scoped identity and chooses campaign objective, placement, budget, bid, schedule, targeting, and creatives.
- Campaign API validates tenant permissions, budget ownership, seller-product ownership, and policy restrictions before accepting writes.
- Creative service stores assets in object storage, computes hashes, scans for malware, checks dimensions, and sends to review queue.
- Campaign DB is the source of truth for campaign state; it stores status transitions with actor, reason, and policy version.
- Every write emits a campaign_changed event with version, tenant_id, campaign_id, and changed fields.
- Regional materializers consume the changelog and build serving indexes optimized for low-latency reads.
- Serving cells reject stale index versions for high-risk status changes such as pause, policy block, or budget exhaustion.
- Read-your-write in the advertiser UI is from the primary DB; serving propagation is measured separately as a freshness SLI.
- Bulk updates use rate-limited jobs and write fences so a tenant cannot invalidate every cache key in one second.
- Support tools use the same APIs as advertisers with stricter audit, not direct database edits.

### Logging, attribution, and billing path

- Delivery-decision events are server generated and include candidates considered, filters applied, winner, price metadata hash, and budget lease ID.
- Impression events are client or edge generated only after the creative is rendered or viewability threshold is met, depending on product definition.
- Click events include signed click tokens so attackers cannot mint arbitrary campaign_id charges.
- Conversion events come from checkout, not the ad client, and carry order_id, user/device linkage where permitted, product_id, seller_id, and timestamp.
- Collectors accept events at high availability and attach ingestion time, source, schema version, and request_id.
- Kafka topics are partitioned by event family and a stable key: impression_id for dedupe, campaign_id for budget, or user_id for attribution windows.
- Stream processors dedupe by idempotency key and watermark by event time to handle mobile delays.
- Attribution joins eligible clicks/impressions to conversions using configured windows, last-touch or multi-touch rules, and consent constraints.
- Billing ledger writes immutable charge records with adjustment records for reversals, not destructive updates.
- Reporting marts are derived; if a report is wrong, replay from the ledger or corrected event stream rather than patching dashboards by hand.
- Fraud review can mark events non-billable while preserving raw evidence for audit.
- Budget spend uses fast approximate counters for serving and reconciled ledger totals for final billing.

### Consistency boundaries

- Strong consistency: campaign ownership, advertiser role, creative policy status, budget ledger, support/admin action, billing ledger.
- Bounded staleness: serving campaign indexes, pacing counters, spend shadows, frequency cap counters, user segments.
- Eventual consistency: advertiser reporting, attribution aggregates, model features, lookalike audiences, seller analytics.
- Fail closed: blocked advertiser, rejected creative, consent missing for personalized targeting, budget fence unavailable for money-impacting campaigns.
- Serve stale: read-only advertiser dashboard, non-critical delivery estimates, contextual candidate index for low-risk placements.
- Drop optional: ranking features, expensive conversion prediction, experimental creatives, long-tail candidate sources.
- Never do: let an ad response charge money without a durable event path, or let a paused campaign keep serving because a cache is convenient.

### Auction and ranking mechanisms

- **Eligibility before scoring:** A candidate that violates targeting, consent, budget, or policy must not enter the auction no matter how high the bid is.
- **Bid types:** CPM bids optimize for impressions, CPC for clicks, CPA for conversions; serving converts them into expected value using predicted rates.
- **Quality score:** A lower bid with high relevance can beat a high bid that creates poor user experience or low conversion probability.
- **First-price intuition:** Winner pays its own bid after multipliers; simple and transparent, but advertisers may shade bids.
- **Second-price intuition:** Winner pays enough to beat the next eligible competitor, adjusted by quality; easier bidding story but more complicated explanation.
- **Reserve price:** The platform can require minimum value so low-quality inventory is not sold below operational or trust cost.
- **Pacing multiplier:** A campaign ahead of schedule lowers delivery probability or effective bid; a campaign behind schedule may raise it within safeguards.
- **Frequency fatigue:** Score should decay when a user has recently seen or ignored the same advertiser, campaign, or creative.
- **Diversity constraint:** Do not fill adjacent slots with the same advertiser, category, or seller unless product policy explicitly permits it.
- **Exploration:** Reserve small traffic for new creatives or campaigns, but cap spend and isolate from billing surprises.
- **Model fallback:** If ML ranking times out, use bid times coarse quality and policy filters; if pricing metadata is missing, return no ad rather than unsafe price.
- **Explainability:** Store sampled feature values and reasons so advertisers and incident responders can understand delivery changes.

### Frequency capping mechanisms

- Use multiple caps: per creative, per campaign, per advertiser, per category, and per sensitive placement.
- Key counters by normalized user_id when authenticated and by privacy-safe device/browser bucket when anonymous and allowed.
- Shard hot cap keys by user hash or use local approximate counters plus periodic reconciliation to avoid single Redis hot keys.
- Use sliding windows for user experience caps and tumbling windows for coarse budget controls where exact boundary behavior is less important.
- Keep cap state region-local for latency, but reconcile for cross-region users with a bounded overexposure budget.
- Do not store raw personal attributes in cap keys; use opaque identifiers and enforce retention.
- Let the ad server treat cap service timeout as candidate rejection for high-risk campaigns or as conservative stale state for low-risk campaigns.
- Emit cap_hit and cap_bypass metrics by placement, campaign, region, and reason.
- Avoid exact per-user-per-campaign cardinality in metrics; aggregate with bounded labels and sample debug traces.
- Repair workflow: if cap state is corrupted, disable affected campaigns or placement until counters are rebuilt from impression logs.

### Pacing mechanisms

- Represent each campaign's target spend curve as expected cumulative spend by time of day, region, placement, and inventory forecast.
- Use budget leases so each serving cell can spend a bounded amount without synchronously calling the central ledger on every request.
- Refresh leases frequently and shrink them when lag, fraud signals, or spend variance grows.
- Calculate actual spend from durable billable events and a fast spend shadow; never rely only on response counts.
- For a campaign behind target, increase selection probability only if eligible inventory and user experience constraints remain healthy.
- For a campaign ahead of target, lower delivery probability, reduce bid multiplier, or pause low-value placements first.
- Use per-tenant and per-campaign burst limits so one large advertiser cannot consume all high-quality inventory at midnight.
- Feed forecast errors back into pacing; a flash sale can invalidate yesterday's traffic curve.
- Protect small advertisers from being starved by large tenants through fair-share or tiered inventory reservations.
- Expose overpacing and underpacing as separate alerts; both are incidents with different mitigations.

## Data Model and Capacity Math

### Core records

| Record | Primary key | Notes |
| --- | --- | --- |
| advertiser | advertiser_id | Tenant root, billing account, risk tier, support owner. |
| campaign | campaign_id | Objective, status, budget, bid, schedule, tenant_id, version. |
| ad_group | ad_group_id | Targeting set, placement constraints, bid overrides. |
| creative | creative_id | Asset refs, product refs, review state, policy labels. |
| targeting_rule | rule_id | Positive and negative criteria with policy version. |
| budget_ledger | campaign_id + ledger_seq | Immutable charges, credits, leases, and adjustments. |
| delivery_decision | request_id + slot_id | Candidates, winner, filters, price metadata hash. |
| impression | impression_id | Viewability, user/device bucket, campaign, creative, placement. |
| click | click_id | Signed token, impression_id, campaign, timestamp, fraud signals. |
| conversion | order_id + attribution_rule | Order-side source of truth and attributed touchpoint. |

### Serving read models

| Index/cache | Key | Invalidation |
| --- | --- | --- |
| placement_campaign_index | placement + category + region | campaign_changed, creative_reviewed, forecast_refresh |
| keyword_candidate_index | keyword_norm + locale | campaign targeting updates and query taxonomy updates |
| campaign_budget_shadow | campaign_id + region | budget lease refresh and ledger reconciliation |
| frequency_cap_state | user_bucket + campaign/creative + window | TTL expiration and impression replay repair |
| creative_payload_cache | creative_id + version | creative status change or asset publish |
| advertiser_quota | advertiser_id + api/use | quota config change and rolling-window expiry |
| policy_blocklist | seller/category/creative | risk engine and manual moderation |
| feature_snapshot | user/item/context + version | feature store TTL and model version rollout |

### Baseline traffic assumptions

- 12M DAU at Northstar.
- Average 60 ad opportunities per active user per day across search, feed, product pages, and live auctions.
- Daily ad opportunities = 12M * 60 = 720M.
- Average ad request rate = 720M / 86,400 = about 8.3k requests/sec.
- Peak multiplier during auctions and sale events = 10x average, so design for about 83k ad requests/sec.
- Each request has 2.2 slots on average, so peak candidate decisions are about 183k slot decisions/sec.
- Candidate retrieval returns 400 candidates per request before filters, so peak candidate scoring is about 33M candidates/sec if every candidate is scored deeply.
- Therefore use staged retrieval: cheap filters reduce 400 to 80, then ranker scores 80, then auction evaluates final 10 to 20.
- If each final rank score costs 50 microseconds CPU, 83k * 80 * 50 us = 332 CPU-seconds/sec, before overhead.
- At 50 percent headroom and replica overhead, budget about 700 to 900 vCPU for peak ranking across regions unless model inference is optimized.
- Logging volume: delivery decisions plus impressions plus clicks plus conversions; assume 1 KB decision, 0.5 KB impression, 0.5 KB click.
- At 83k requests/sec and 2.2 slots, impression candidate logs can exceed 180k events/sec; sampling debug fields matters.
- Click-through at 1 percent adds about 1.8k click events/sec at peak; conversion events are lower but more important to billing and attribution.
- A 1 percent duplicate impression rate at 720M/day is 7.2M duplicate events; dedupe is a billing requirement, not an optimization.

### Capacity worksheet

1. Ad decision QPS = DAU * opportunities_per_day * peak_multiplier / 86,400.
2. Slot decision QPS = ad_decision_QPS * average_slots_per_request.
3. Candidate scan rate = ad_decision_QPS * candidates_after_retrieval.
4. Deep score rate = ad_decision_QPS * candidates_after_filtering.
5. Auction operations = slot_decision_QPS * final_candidates_per_slot.
6. Frequency cap operations = deep_score_rate * cap_checks_per_candidate unless caps are batched or prefiltered.
7. Budget guard operations = candidate_count_after_policy, not every raw campaign in the tenant.
8. Kafka ingress bytes/sec = sum(event_rate_i * avg_event_size_i * replication_factor overhead).
9. Stream processor state = active_keys * windows_per_key * bytes_per_counter plus checkpoint overhead.
10. Budget lease size must be small enough that region failure cannot overspend beyond the advertiser contract.
11. If a campaign has daily budget $100,000 and max tolerated overspend 1 percent, all active regional leases combined must be <= $1,000 beyond reconciled spend.
12. If `us-east-1` has 60 percent traffic, `eu-west-1` 25 percent, and `ap-northeast-1` 15 percent, leases should follow forecast but retain global cap.
13. If a hot campaign receives 20 percent of peak opportunities, its budget and cap keys can see 16k requests/sec before sharding.
14. If frequency cap service p99 is 15 ms and ad budget is 120 ms, cap checks must be parallel, local, and batched; sequential per-candidate calls are impossible.
15. If reporting needs 5-minute freshness, stream lag alert should page before lag exceeds 2 minutes, leaving time to shed debug payloads or add consumers.

### Hot key patterns and mitigations

- **Hot campaign budget:** Shard spend counters by region and time bucket; use budget leases and reconcile to ledger.
- **Hot creative payload:** Cache by creative_id/version at the serving cell and CDN image edge; prewarm event campaigns.
- **Hot frequency cap user:** High-activity users can create many cap writes; coalesce per request and batch updates.
- **Hot advertiser API:** Bulk campaign edits must use job queues with tenant concurrency limits, not synchronous fan-out to all indexes.
- **Hot product category:** Search sale category can overload candidate index; partition by category plus region plus campaign hash.
- **Hot placement:** Home feed top slot can dominate traffic; split placement index by region and experiment cell.
- **Hot attribution key:** Large campaigns can create campaign_id partitions; include time bucket or impression_id for raw events, then aggregate.
- **Hot report export:** Exports read from reporting replicas or object snapshots with tenant byte budgets.
- **Hot fraud rule:** A global blocklist update can invalidate many caches; use versioned policy pushed gradually with critical overrides.
- **Hot support query:** Support tools need query guards and tenant filters so incident debugging does not compete with serving.

### Rate-limit dimensions

- Per user/device: ad refreshes, click events, conversion pings, and suspicious repeat actions.
- Per IP/ASN: unauthenticated scraping, fake impressions, click farms, and request bursts.
- Per advertiser: campaign mutations, creative uploads, report exports, spend changes, and API key calls.
- Per campaign: delivery decision rate, budget lease burn rate, frequency-cap bypass rate, and auction participation.
- Per creative: render errors, click anomaly rate, policy review retries, and asset fetches.
- Per placement: top-slot QPS, no-fill rate, timeout rate, and fallback usage.
- Per region/cell: total auction CPU, Kafka producer bytes, cap service calls, and spend lease allocation.
- Global: emergency spend ceiling, event collector ingress, attribution backlog, and billing ledger write rate.
- Per support/admin actor: disable/enable actions, exports, and break-glass reads.
- Per model version: inference QPS and timeout budget, so an experimental ranker cannot consume the fleet.

## Failure and Abuse Catalog

### Catalog

| Failure | Trigger | Primary symptom | Blast radius |
| --- | --- | --- | --- |
| Overpacing | Forecast too low or budget lease too large | Campaign spends day budget early | Advertiser refunds and inventory starvation |
| Underpacing | Candidate index stale or ranker suppresses tenant | Campaign misses spend target | Revenue loss and support escalations |
| Double billing | Duplicate impression/click event without idempotency | Ledger records repeated charges | Advertiser trust incident |
| Paused creative still serves | Serving cache ignores status version | Policy-blocked ad appears | User trust and legal exposure |
| Hot budget key | Sale campaign receives concentrated traffic | Redis or stream partition p99 rises | All auctions in cell slow |
| Click fraud | Botnet clicks ads with valid tokens | CTR spikes but conversion flat | Advertisers charged for junk |
| Fake conversions | Compromised integration sends order-like events | CPA campaigns overpay | Ledger and risk incident |
| Targeting leakage | Report/export includes audience segment too granular | Tenant infers user attributes | Privacy breach |
| Attribution backlog | Flink lag after schema rollout | Reports stale and pacing uses old spend | Over/under delivery |
| Creative asset outage | Object store/CDN issue | Blank ad slots or render errors | UX degradation |
| Ranking feature outage | Feature store timeout | Auction latency breaches | No-fill or low-quality ads |
| Advertiser noisy neighbor | Bulk edit invalidates shared indexes | Serving index rebuild thrashes | Multi-tenant outage |
| Consent service outage | Cannot verify personalized targeting | Personalized ads fail closed | Revenue drop but privacy preserved |
| Regional failover | Cell loses budget lease state | Potential double spend | Bounded by lease and ledger reconciliation |

### Abuse-specific design notes

- Click fraud is not solved by one bot score; combine device entropy, timing, conversion quality, IP reputation, user history, and advertiser complaints.
- Astroturf advertiser campaigns can use many small tenants to dominate a category; enforce beneficial-owner or risk-cluster limits where available.
- Scrapers may request ad slots to learn bids or targeting; response tokens should not expose raw bid or sensitive audience reason.
- Competitors can click each other's ads; billing must support invalid traffic adjustment without deleting raw evidence.
- A malicious seller can target a competitor product detail page if policy allows broad category targeting; placement rules need conflict controls.
- A compromised advertiser API key can upload many creatives or drain budget; tenant API keys need scopes, rotation, anomaly alerts, and spend caps.
- Client replay of impression tokens must be deduped by signed token and event window.
- Conversion stuffing is mitigated by taking conversion truth from checkout and requiring valid ad touchpoint eligibility.
- Report inference attacks are reduced with thresholding, aggregation, delayed reporting, and privacy review for small audiences.
- Incident responders need kill switches by advertiser, campaign, creative, placement, model version, candidate source, and region.

### Failure-mode reasoning drills

- If auction latency rises but no-fill stays flat, suspect slow optional scoring or feature store, not budget exhaustion.
- If spend accelerates while impressions are flat, suspect duplicate click/conversion billing or price calculation, not serving volume.
- If one advertiser reports underdelivery and global inventory is healthy, inspect pacing curve, policy status, targeting reach, and tenant quota before scaling servers.
- If all advertisers underdeliver in one region, inspect serving index freshness, budget lease allocation, and regional Kafka materializer lag.
- If conversion attribution drops while checkout is healthy, inspect join keys, consent changes, delayed mobile events, and attribution processor watermark.
- If campaign pause takes minutes to apply, inspect campaign_changed lag and serving index version rejection, not the advertiser UI.
- If Redis CPU is high on cap state, inspect hot users or campaigns and batching behavior before increasing cap strictness.
- If support exports time out, do not scale serving; move exports to object snapshots and tenant queues.
- If fraud controls block a flash-sale campaign, compare identity diversity and conversion quality before disabling risk globally.
- If budgets overspend during failover, quantify outstanding leases before replaying events or opening new leases.

## Production Readiness Appendix for Ad Platform

This appendix is intentionally operational: these are the checks that usually separate Staff-level designs from diagrams that only work on a whiteboard.

### API contracts and invariants

- `POST /ads/request` accepts placement, page context, request_id, user/session context, consent summary, and client capability; it returns zero or more ads plus signed tracking tokens.
- The client never submits advertiser_id or campaign_id as trusted input for serving; those appear only after server-side candidate selection.
- `POST /campaigns` and `PATCH /campaigns/{id}` require advertiser tenant role, budget authority, and policy-compatible targeting rules.
- `POST /creatives` writes assets to quarantine state before review; serving indexes only publish approved creative versions.
- `POST /events/impression` accepts signed impression token and viewability fields; collector validates signature before enqueueing.
- `POST /events/click` uses a redirect or signed token path so arbitrary clients cannot mint clicks for any campaign.
- `POST /events/conversion` is accepted only from checkout or trusted server integrations, not from untrusted ad clients.
- `GET /advertisers/{id}/reports` reads from reporting snapshots or marts, never from live serving stores.
- Every public API includes tenant_id from auth context, not from request body as authority.
- Every money-impacting write includes idempotency key, actor, tenant, request_id, and schema version.
- Every support/admin action requires reason, scope, expiry, and audit record before execution.
- Invariant: a blocked or paused campaign is not eligible once the status version reaches a serving cell.
- Invariant: no billable event enters the ledger without a valid token or trusted conversion source.
- Invariant: campaign budget exposure is bounded by outstanding leases plus reconciled spend.
- Invariant: user consent controls which targeting features can be read, logged, and joined.
- Invariant: an advertiser can see its own reports and aggregate marketplace diagnostics, never another advertiser's raw data.
- Invariant: checkout success path does not depend on ad response, ad collector, attribution, or reporting.
- Invariant: raw events are append-only evidence; corrections are additional records with reasons.
- Invariant: ranker/model timeouts degrade ad quality or fill, not policy, consent, or budget checks.
- Invariant: emergency controls are scoped and expiring unless incident command explicitly extends them.

### Schema evolution and replay controls

- Schema registry compatibility is required for delivery, impression, click, conversion, and ledger event topics.
- New fields can be optional first, then required after all producers and consumers observe them.
- Event consumers must ignore unknown fields but reject unknown billing-critical enum values.
- A schema rollback must not reinterpret old price metadata under a new auction rule.
- Replay jobs specify source topic, sink, tenant, campaign, event type, time range, and max write rate.
- Replay output carries replay_id so dashboards can separate live processing from repair processing.
- Billing replay is dry-run compared with ledger before any adjustment records are written.
- Attribution replay can repair reports without changing invoices unless finance approves adjustment scope.
- A replay cannot write to campaign control-plane tables; it repairs derived event outputs only.
- DLQ triage groups poison events by schema version, producer, tenant, and first bad field.
- A poison creative or campaign update is quarantined; ordinary events continue processing.
- Backfills run in lanes with tenant and byte budgets so one tenant cannot starve current traffic.
- Checkpoint restore drills prove stream processors do not double-charge on restart.
- Acceptance test: replay same click batch twice and ledger contains one charge plus zero duplicates.
- Acceptance test: replay late conversions and reports update while invoice finalization remains protected.

### Privacy, compliance, and data minimization

- Personalized targeting reads only features permitted by consent, region, age policy, and product policy.
- Contextual ads remain available when personalization is not allowed, but contextual logs still avoid unnecessary identifiers.
- Audience reports enforce minimum cohort size so advertisers cannot infer a single user's behavior.
- Raw user identifiers in event logs are tokenized or bucketed according to retention and purpose limits.
- Data deletion requests propagate to attribution eligibility, feature stores, user-level exports, and future targeting.
- Deletion does not erase immutable billing evidence where legal retention requires it; access is restricted and purpose-scoped.
- Support views redact sensitive targeting reasons and show coarse categories or policy reason codes.
- Cross-device joins require explicit legal basis and are disabled by region when unavailable.
- Creative review data and advertiser billing data have different retention and access controls.
- A privacy config rollout has canaries for personalized_eligible_rate and contextual_fallback_rate by region.
- A privacy outage favors no-ad/contextual fallback and creates revenue incident, not privacy bypass.
- Incident review includes whether debug sampling or emergency exports exposed more data than needed.
- The ranking model should not encode protected-class proxies without review and monitoring.
- Advertiser APIs should never return raw user-level conversion paths for small cohorts.
- Principal answer: privacy constraints shape architecture, not just legal copy at the end.

### Model rollout and experiment safety

- Ranking models are versioned with feature schema, training data window, objective, and offline/online guardrails.
- A model can improve revenue while harming user trust through repetition or low-quality sellers; guardrails must include UX metrics.
- Experiments are scoped by region, placement, tenant tier, and traffic percentage with automatic rollback criteria.
- Model features have TTLs; stale features are marked and can trigger fallback rather than silent bad scoring.
- Feature store timeout has a deadline smaller than the ad request budget and a deterministic fallback.
- A new model cannot change auction pricing semantics without audit and finance review.
- Model logs are sampled with privacy controls and include enough reason codes for incident debugging.
- Calibration dashboards compare predicted CTR/CVR to realized outcomes by placement and tenant class.
- A model that increases fill but decreases conversion quality can create advertiser churn and fraud exposure.
- Feature backfills run separately from serving and do not evict current serving features.
- Shadow mode evaluates candidate rank without affecting auction to measure latency, cost, and economic changes.
- Canaries include cold-start campaigns, large tenants, small tenants, sensitive categories, and event traffic.
- Rollback restores previous model and feature schema compatibility; it does not require rebuilding all campaign indexes.
- Kill switch disables one model version while preserving simple bid-quality fallback.
- Principal answer: model governance is an economic and trust boundary, not only an ML platform concern.

### Multi-region serving and failover

- Campaign management may be primary-region strong, while serving read models are regional for latency.
- Regional cells hold bounded budget leases and local cap state, then reconcile with central ledger and global windows.
- A region failover cannot simply duplicate traffic into another region without accounting for existing leases and cap exposure.
- Serving cells advertise index freshness and policy version so routers can avoid stale or unsafe cells.
- If one region loses materializer lag for bid changes, it can serve stale bids within bounds; if it loses policy blocks, it must fail closed for affected campaigns.
- Cross-region Kafka replication is useful for replay but should not be required for each request.
- Attribution can process in regional lanes and merge to global reports after privacy and ledger constraints.
- Clock skew affects event-time windows and budget lease expiry; services use monotonic sequence fences where money matters.
- Regional emergency kill switches are safer than global switches when only one serving cell is unhealthy.
- Global advertiser UI should show propagation lag per region for pause, budget, and creative status.
- Disaster recovery restores tenant boundaries and ledger state before restoring optional analytics freshness.
- Game day: lose `eu-west-1` materializer while live auctions run and prove other regions keep serving safe ads.
- Game day: fail over traffic after leases issued and prove overspend stays below contract threshold.
- Game day: replay replicated impressions and prove dedupe prevents double billing.
- Principal answer: multi-region ads are about bounded financial exposure as much as availability.

### Testing strategy and launch gates

- Unit tests cover auction price calculations, quality adjustments, reserve prices, tie-breaking, and budget rejection.
- Property tests generate random campaigns and verify policy-blocked candidates never win.
- Contract tests verify campaign_changed events build serving indexes with exact version semantics.
- Load tests include hot campaign, hot placement, hot cap key, feature store timeout, and collector burst.
- Replay tests verify duplicate impression/click/conversion events do not create duplicate ledger charges.
- Privacy tests verify no personalized targeting when consent is missing or expired.
- Tenant isolation tests verify report exports and support tools cannot cross advertiser boundaries.
- Chaos tests slow cap service and prove high-risk campaigns fail conservative, not allow unlimited repeats.
- Chaos tests slow materializer and prove campaign pause/block still has stricter propagation or cell rejection.
- Game-day drill includes Northstar live auction traffic, seller support escalations, and finance spend hold.
- Canary dashboards must include revenue, user trust, advertiser delivery, latency, and billing duplicate metrics.
- Launch gate rejects any new placement without no-ad fallback and scoped kill switch.
- Launch gate rejects any new event schema without replay and idempotency tests.
- Launch gate rejects any new model without fallback and cost budget.
- Launch gate rejects any new advertiser API without tenant quota and audit.

### Staff and Principal review checklist

- Foundation: Can you explain why no-ad is safer than unsafe ad?
- Foundation: Can you identify source of truth for campaigns, creatives, budget, and ledger?
- Foundation: Can you compute peak request QPS from DAU and opportunities?
- Foundation: Can you explain why impression logging is not billing truth by itself?
- Foundation: Can you name the request-path deadline budget?
- Staff: Can you bound budget overspend during regional failover?
- Staff: Can you design cap state without one hot Redis key per campaign?
- Staff: Can you stop one advertiser bulk edit from delaying everyone else?
- Staff: Can you explain attribution with late and duplicate events?
- Staff: Can you sequence overpacing mitigation without breaking checkout?
- Staff: Can you reject a global cache flush during a cap hot-key incident?
- Staff: Can you name metrics for overpacing, underpacing, duplicate billing, and privacy fallback?
- Principal: Can you defend auction economics under model rollout and advertiser fairness constraints?
- Principal: Can you preserve privacy and measurement when deterministic IDs are unavailable?
- Principal: Can you communicate financial exposure with uncertainty during an incident?
- Principal: Can you scope emergency controls so unaffected tenants keep serving?
- Principal: Can you design game days that combine hot keys, model timeout, and budget leases?
- Principal: Can you prove support tools cannot become a tenant data exfiltration path?
- Principal: Can you explain which business metrics you are willing to sacrifice to protect trust?
- Principal: Can you identify the organizational owner for policy, pricing, ledger, and model changes?

## Ad Platform Scenario Bank

Use these scenarios to pressure-test the design without opening the answer key.

### Scenario A - Stale pause during creator controversy

- A celebrity seller is suspended by Trust and Safety while its campaign is still active in feed ads.
- The advertiser UI shows paused, but one serving cell keeps showing the creative for two minutes.
- Inspect status version propagation, policy override path, serving index freshness, and cache key version.
- Do not rely on lowering bid or draining budget because policy status is the controlling invariant.
- The smallest blast radius is seller/campaign/creative in one cell, then placement if status index is shared.
- Acceptance criterion: blocked seller creative cannot win once policy version reaches the serving cell.

### Scenario B - Report export noisy neighbor

- An agency starts 400 report exports for quarterly billing reconciliation.
- Advertiser UI slows and the reporting database CPU hits 95 percent, but serving p99 remains healthy.
- Throttle the tenant's export jobs and move large exports to object snapshots.
- Do not scale serving or touch auction code because the blast radius is reporting plane.
- The design should enforce tenant byte budgets and export concurrency before this happens.
- Acceptance criterion: one advertiser can delay its reports without affecting another advertiser's dashboard or serving.

### Scenario C - Feature store stale after catalog migration

- Catalog migration changes product categories and the ranker receives stale category features for 18 minutes.
- Ad fill remains high, but conversion rate drops and seller complaints rise.
- Compare feature version, catalog version, candidate index version, and conversion-quality guardrails.
- Do not call it healthy because revenue or fill is high; advertiser ROI and user quality are degraded.
- A safe fallback is simple contextual category from page context with lower deep-rank confidence.
- Acceptance criterion: feature version skew triggers fallback and pages before conversion quality collapses.

### Scenario D - Collector accepts unsigned clicks

- A mobile client bug omits click token on 3 percent of clicks, and a collector deploy accepts missing tokens as anonymous clicks.
- Billing duplicate rate is low, but invalid charge risk is high because source authenticity is absent.
- Stop accepting unsigned money-impacting clicks and hold billing for the affected window.
- Do not infer validity from normal-looking CTR because attackers can mimic normal timing.
- Durable fix is schema validation, signed token requirement, and collector canary for malformed events.
- Acceptance criterion: unsigned clicks can be logged for diagnostics but never billed.

### Scenario E - Small advertiser starvation

- A large marketplace seller wins nearly every luxury-accessory ad slot during a sale.
- Revenue rises but smaller advertisers underdeliver and users report repetitive ads.
- Inspect diversity constraints, fair-share retrieval, frequency caps, pacing curves, and tenant budgets.
- Do not solve only by increasing ad load because user trust and inventory fairness are part of the product.
- A design answer can defend reserved exploration or fair-share candidates with explicit business tradeoffs.
- Acceptance criterion: large tenant growth cannot drive cap_hit_rate to near zero or starve protected advertiser classes silently.

### Scenario F - Region-local consent outage

- Consent cache in eu-west-1 returns unknown for 60 percent of users after a deploy.
- Personalized eligible rate drops, contextual fallback rises, and revenue falls in that region.
- The safe behavior is contextual or no-ad, not cached personalized targeting beyond policy TTL.
- Mitigation is rollback or bypass the bad consent cache while preserving fail-closed semantics.
- Notify privacy/legal only if policy was violated; notify business owners because revenue is impacted even when privacy is preserved.
- Acceptance criterion: no personalized ad is served with unknown consent, and contextual capacity absorbs the load.

### Scenario G - Attribution watermark misconfigured

- Watermark allowed lateness changes from 24 hours to 10 minutes for conversion joins.
- Real-time reports look fast, but final conversions fall for mobile users with delayed events.
- Pause finalization for affected windows and replay conversions with correct watermark.
- Do not change serving bids immediately based on broken attribution because pacing/model feedback would amplify the bug.
- Durable fix is config review, canary with delayed mobile events, and report confidence labels.
- Acceptance criterion: delayed conversion fixture appears in final report and ledger according to attribution policy.

## Detailed Mechanism Walkthroughs

These notes are the difference between a plausible whiteboard answer and a production answer.
Each mechanism should be tied to an invariant, a metric, and a failure mode.

### Candidate retrieval details

- The retrieval service should never scan every active campaign for a request.
- The campaign materializer builds inverted indexes from targeting rules into placement-specific candidate lists.
- For search ads, the first key is normalized query or keyword intent, then locale, category, and region.
- For product detail ads, the first key is page product category, brand policy, seller conflict policy, and region.
- For feed ads, the first key is placement, coarse interest segment, language, device class, and region.
- Negative targeting is as important as positive targeting because brand safety and competitor policy remove candidates early.
- The retrieval response includes campaign_id, creative_id, bid class, targeting reason, index version, and cheap quality hints.
- Index entries store only serving-safe fields; the request path should not read private advertiser notes or billing metadata.
- Candidate lists are capped per key so a popular category cannot return unbounded candidates.
- Large advertisers are split across shards by campaign hash so one tenant cannot dominate one index partition.
- Small advertisers need fair-share sampling or they may never survive retrieval under dense category competition.
- Index freshness is measured by control-plane changelog offset and critical status update age, not by cache hit ratio.
- A campaign pause or policy block has stricter propagation than bid changes because serving a blocked ad is worse than stale pricing.
- The materializer should write new index versions atomically and keep the prior version for rollback until health checks pass.
- Serving cells reject mixed versions for one campaign when budget or policy fields disagree across indexes.
- A retrieval miss is logged with the request context so underdelivery can distinguish no inventory from retrieval lag.
- During overload, retrieval can drop long-tail candidate sources before dropping policy, budget, or consent checks.
- When index lag is regional, route only that region or placement to contextual fallback instead of disabling all ads.
- Canary campaigns with known eligibility should be present in every region and placement to detect silent retrieval failures.
- The interview signal is whether the candidate protects serving latency without making the index the source of truth.

### Targeting and consent details

- Targeting input starts with explicit campaign rules: include categories, keywords, regions, languages, devices, and seller/product constraints.
- The system then intersects those rules with user consent, privacy jurisdiction, age policy, and sensitive-category policy.
- A user profile segment is optional evidence, not authority to ignore consent state.
- If consent state is unknown, the platform can use contextual signals such as page category and search query if policy allows.
- Do not put raw sensitive attributes into Kafka headers, cache keys, or debug logs.
- Segment freshness has a TTL; stale segments should be dropped or marked stale in the feature vector.
- Negative targeting is evaluated before positive broad-match expansion so restricted matches are not reintroduced later.
- Lookalike audiences must carry model version and policy approval version.
- Advertiser-provided customer lists need hashing, consent proof, retention policy, and deletion propagation.
- Support tools should show why a user was eligible only through coarse reason codes, not private profile details.
- The ad response should not leak targeting reasons that let an attacker infer sensitive user attributes.
- Audience-size thresholds protect small cohorts from report inference and microtargeting abuse.
- Campaign reach estimates are approximate and should be labeled as such in the advertiser UI.
- Policy updates invalidate targeting indexes by version, but high-risk blocks can also push direct deny lists.
- The consistency question is not whether targeting is perfectly fresh; it is whether unsafe targeting fails closed.
- Metrics: personalized_eligible_rate, contextual_fallback_rate, consent_unknown_rate, policy_filter_rate, and small_audience_block_rate.
- Failure drill: consent service times out during EU peak; the correct behavior is contextual or no-ad, not cached personalized targeting forever.
- Capacity drill: if 70 percent of traffic becomes contextual, verify the contextual candidate index can absorb that sudden shift.
- Abuse drill: advertiser tries to target tiny audience with many slight rule variants; quota the rule explosion and report cardinality.
- Principal tradeoff: revenue loss from contextual fallback is acceptable compared with privacy or legal breach.

### Budget and pacing details

- The central budget ledger records authoritative spend and adjustments, but serving cannot synchronously check it per request.
- Budget leases give each region a bounded spend allowance for a short interval.
- A serving cell decrements local lease shadow after winning an auction or after billable event depending on product billing model.
- For CPM billing, impressions consume budget; for CPC billing, clicks consume budget; for CPA, conversions consume budget but serving still needs exposure estimates.
- Pacing compares spend-to-date against an expected curve and changes selection probability or effective bid.
- The expected curve should consider daypart, region, placement, seller inventory, and live-event forecast.
- A campaign behind schedule is not automatically boosted if it would hurt quality, violate caps, or crowd out reserved inventory.
- A campaign ahead of schedule can be slowed by reducing retrieval sampling, lowering effective bid, or temporarily pausing low-priority placements.
- Budget leases must shrink when event lag grows because the local shadow becomes less trustworthy.
- Every lease has owner region, expiry, amount, issued ledger sequence, and revocation state.
- Leases expire rather than remain open during network partitions.
- Overspend policy should be explicit: absolute dollar ceiling, percentage ceiling, or contractual guarantee by tenant tier.
- Do not share one giant lease across all campaigns in a tenant; that hides which campaign is responsible for spend.
- Pacing dashboards need expected spend, actual spend, lease outstanding, and event-lag-adjusted spend.
- A midnight reset storm is avoided by smoothing campaign start times or using randomized initial pacing windows.
- Replay of delayed billable events should debit ledger but not retroactively cause serving to overcorrect without bounded control logic.
- Refunds and invalid-traffic adjustments are ledger records, not deletions from historical spend.
- Incident action: freeze new leases before trying to perfect attribution if active spend is unsafe.
- Game-day action: kill one region after large leases issue and prove overspend remains bounded.
- Interview red flag: saying 'check budget in Redis' without source of truth, leases, and reconciliation.

### Auction pricing details

- The auction input is eligible candidates with bids, quality estimates, pacing modifiers, and placement constraints.
- First-price auction: winner pays its bid or effective bid; the platform may need bid guidance because advertisers shade bids.
- Second-price auction: winner pays enough to beat the next candidate after quality adjustments; simpler advertiser story, more opaque debugging.
- Quality adjustment means the apparent highest bid may lose to a lower bid with better predicted user value.
- Reserve price prevents selling scarce inventory below platform cost or trust threshold.
- Tie-breaking should be deterministic enough for audit but randomized enough to avoid permanent starvation.
- Pricing metadata must be logged with a hash or sealed details so disputes can be answered later without exposing competitor bids.
- The auction should never charge if the price calculation falls back to unknown state.
- Budget check happens before and after auction because winning price may differ from estimated price.
- If two slots are filled in one request, diversity and dedupe constraints apply across slots.
- A candidate can lose because of frequency cap, budget, pacing, quality, reserve, category conflict, or tenant fair-share.
- Advertiser UI should explain delivery with reason buckets, not raw competitor data.
- Model rollout can change auction economics, so model version is part of audit and cost dashboards.
- Auction latency is usually small compared with feature/ranking latency; do not optimize it first without evidence.
- A malformed bid should quarantine the campaign or ad group, not crash the serving cell.
- A bid update race uses campaign version; serving may use prior bid for bounded freshness except when status is pause/block.
- For CPC/CPA objectives, effective CPM is bid * predicted click/conversion rate times quality and margin factors.
- If predicted rates are unavailable, a conservative fallback prevents experimental models from creating free traffic.
- A billing dispute needs the winner, price rule, eligible competitor summary, and policy version for the event window.
- Principal tradeoff: maximizing auction revenue can harm marketplace trust if ad load, repetition, or low-quality sellers rise.

### Event schemas and idempotency

- Every event has event_id, request_id, tenant_id, campaign_id, creative_id, placement, region, source, schema_version, event_time, and ingest_time.
- Delivery-decision events are server-side and include candidates considered, filters applied, winner, and reason codes.
- Impression events include a signed impression token, render timestamp, viewability fields, and client integrity signals.
- Click events include signed click token, redirect path, client timestamp, and anti-replay nonce.
- Conversion events come from checkout or trusted server integrations and include order_id, product_id, seller_id, and permitted linkage keys.
- Idempotency key for impression is impression_token plus viewability threshold version.
- Idempotency key for click is click_token plus click sequence or nonce.
- Idempotency key for conversion attribution is order_id plus attribution_rule_version plus campaign/touchpoint key.
- Collectors validate signatures before enqueueing expensive downstream work.
- Collectors should accept events durably even if enrichment is down; enrichment is a downstream stage.
- Schema changes are forward/backward compatible and carry default behavior for old clients.
- Poison events go to DLQ with sample payload and reason, not silent drop.
- Stream processors checkpoint offsets with state snapshots to replay without double-charging.
- Watermarks handle delayed mobile events; finalization windows define when reports become invoiceable.
- Late events after finalization create adjustment records if policy allows.
- Raw event retention is longer for billing/audit than for low-value debug fields.
- Debug payload sampling increases during incidents only within cost and privacy limits.
- A replay job must specify tenant, campaign, event type, time range, and max output rate.
- Billing sink is idempotent; reporting sink can be rebuilt; raw log sink is append-only.
- Interview signal: candidate can say which path is allowed to be approximate and which path is not.

### Attribution details

- Attribution starts with eligible touchpoints, not every impression the user ever saw.
- Eligibility checks campaign status at touch time, consent state, lookback window, fraud disposition, and conversion product relationship.
- Last-click attribution is simpler but can underweight upper-funnel impressions.
- View-through attribution is easier to game and needs stricter fraud and viewability requirements.
- Multi-touch attribution is more complex and should not be introduced before event correctness is solid.
- Cross-device attribution depends on permitted identity joins and should degrade gracefully when unavailable.
- Checkout owns conversion truth; ad client pixels do not own purchase truth in Northstar.
- Attribution output feeds reporting, pacing models, and billing depending on product contract.
- Do not let near-real-time attribution estimates finalize invoices without reconciliation.
- Fraud review can set a touchpoint or conversion to non-billable while preserving analytics visibility if policy allows.
- A conversion can be attributed to one campaign for billing and multiple campaigns for modeled reporting only if labels are clear.
- Late conversions need watermark logic and finalization windows.
- Returns, cancellations, and chargebacks create negative adjustments rather than deleting original conversions.
- Data minimization removes raw identifiers once attribution windows close where policy requires.
- Metrics: attribution_join_rate, unmatched_conversion_rate, late_event_rate, invalid_traffic_adjustment_rate.
- Failure: checkout deploy changes order_id format; attribution drops while serving appears healthy.
- Mitigation: pause billing finalization for affected window, keep serving safe, and repair join parser with replay.
- Capacity: conversion volume is lower than impressions but joins touch historical windows, so state size can dominate.
- Principal question: how to measure ad value when privacy limits remove deterministic joins.
- Design direction: use aggregate measurement, experiments, modeled conversion lift, and conservative billing rules.

### Operational dashboards

- Serving dashboard starts with user-visible slot fill, p99 decision latency, timeout rate, and no-ad reason.
- Auction dashboard shows candidates retrieved, candidates filtered, deep-rank count, winners, clearing price distribution, and fallback rate.
- Policy dashboard shows block rates by reason, creative review backlog, consent fallback, and status propagation lag.
- Budget dashboard shows expected spend, actual spend, outstanding leases, lease expiry, overspend guard, and spend shadow freshness.
- Frequency dashboard shows cap hit rate, cap timeout rate, hot key families, shard CPU, and repeated-exposure samples.
- Event dashboard shows collector QPS, producer error, Kafka lag, DLQ rate, schema error rate, and duplicate rate.
- Attribution dashboard shows join rate, watermark delay, conversion lag, unmatched conversions, and finalization backlog.
- Billing dashboard shows ledger write errors, adjustment rate, invalid traffic holds, and invoice finalization age.
- Tenant dashboard shows top advertisers by QPS, spend, cache invalidations, API writes, report export bytes, and support actions.
- Cost dashboard shows vCPU per thousand requests, event bytes per impression, stream state bytes per campaign, and report export cost.
- Abuse dashboard shows click entropy, conversion quality, suspicious device clusters, and disputed spend.
- Runbook dashboard shows active kill switches and their scope, owner, reason, expiry, and rollback condition.
- Dashboards use bounded cardinality labels; detailed tenant/campaign views are drilldowns, not global metrics dimensions.
- Every page should include recent deploys, config versions, and model versions because ad incidents are often config-driven.
- Synthetic canaries should request known eligible and known ineligible ads to prove policy and retrieval both work.
- Golden signals should be split by region and placement; global averages hide EU product detail no-fill.
- If a dashboard cannot answer whether advertisers are overcharged, it is insufficient for ads on-call.
- If a dashboard cannot answer whether users are seeing repeated or unsafe ads, it is insufficient for marketplace trust.
- If a dashboard cannot answer whether checkout is unaffected, it is insufficient for Northstar incident command.
- The interview answer should name at least one metric that pages before customers or advertisers complain.

### Incident sequencing playbook

- First classify the incident as user trust, advertiser money, privacy/policy, latency/availability, or reporting freshness.
- If privacy, policy, or budget correctness is unsafe, fail closed for the affected scope before optimizing fill rate.
- If latency is high but correctness is safe, disable optional ranker features and reduce deep candidates before touching budget guards.
- If one campaign is hot, cap or pause that campaign before global ad disable.
- If one tenant bulk job causes lag, throttle that job and move materializer resources only within broker safety limits.
- If event collectors lag, protect durable ingestion first and sample non-billing debug fields second.
- If billing ledger errors, stop invoice finalization and create an incident-window hold.
- If fraud spikes, mark suspect events for review and lower delivery only where confidence is high enough.
- If consent service is unavailable, force contextual-only or no-ad by jurisdiction and placement.
- If serving index is stale, compare status update class: pause/block requires stricter action than bid update stale.
- Do not flush all caches unless the cache is proven to contain unsafe state and the blast radius of flush is understood.
- Do not reshard Redis or Kafka during peak without a rollback and owner for downstream lag.
- Do not replay backlog until the write path is stable and sinks are idempotent.
- Communicate advertiser-impact estimates with confidence intervals until reconciliation finishes.
- Use pre-approved templates for refunds, make-goods, and delayed reporting.
- Record every emergency config change with scope, owner, reason, expiry, and acceptance metric.
- After mitigation, reconcile raw events, dedupe output, ledger, reports, and advertiser-facing dashboards.
- After reconciliation, remove temporary kill switches and restore fair-share budgets gradually.
- Postmortem should add a gate, not just a graph; the failure must be caught before production next time.
- Principal evaluation: candidate sequences safety, money, latency, and cleanup instead of doing random scaling.

### Northstar integration points

- Search supplies query intent and product category but does not decide which advertiser can target a user.
- Feed supplies placement opportunities and organic ranking context; ads do not become organic feed source of truth.
- Checkout emits conversion events and order status; ads do not block or mutate checkout.
- Inventory service provides stock state; stale stock should suppress product ads when confidence is low.
- Seller analytics reads reconciled ad performance but should not read raw user-level event logs by default.
- Wallet and ledger systems receive finalized charges and adjustments, not raw impression logs.
- Risk engine labels suspicious users, devices, sellers, advertisers, and events; serving uses bounded risk hints.
- Cognito/session auth identifies shoppers; advertiser auth and seller auth require separate roles and scopes.
- MSK carries campaign changes, ad events, checkout conversions, and reconciliation outputs with topic-level ownership.
- Redis clusters used by sessions or feed must not share unbounded capacity with cap hot keys.
- OpenSearch can power report search and creative review queues, but billing truth remains ledger and event streams.
- Feature flags use AppConfig-like scoped rollout; emergency flags must include expiry and owner.
- Regional cells should degrade ads before they degrade bid WebSocket or checkout SLOs.
- Live auctions create predictable hot products; prewarm candidate indexes and creative payloads for event campaigns.
- Seller conflicts matter: a seller may not be allowed to advertise against its own page or competitor page depending on policy.
- Promoted listings must respect marketplace quality rules so ads cannot sell unsafe or unavailable inventory.
- Northstar support needs one console for campaign disable but separate controls for billing hold and report notices.
- Game days should reuse Northstar recurring themes: hot keys, noisy tenants, replay storms, and flag rollouts without gates.
- Ad incidents are often revenue-visible; finance should be part of P1 communications when spend integrity is at risk.
- The safest default is no ad, not bad ad, not privacy-unsafe ad, and not unbounded spend.

### Interview worksheet prompts

1. Draw the ad request sequence and mark every network call with a deadline.
2. Circle the first point where consent changes the request path.
3. Circle the first point where advertiser money is at risk.
4. Show which records are source of truth and which are serving read models.
5. Calculate peak ad requests for 12M DAU, 60 opportunities/day, and 10x peak.
6. Calculate CPU for scoring 80 candidates per request at 50 microseconds each.
7. Calculate event volume for impressions at 2.2 slots per request.
8. Calculate duplicate impact if 1 percent of impressions are replayed.
9. Calculate overspend if three regions each hold a $10k lease and ledger is partitioned.
10. Explain how to cap frequency without raw personal attributes in keys.
11. Explain how to stop one advertiser from invalidating all serving indexes.
12. Explain how to audit an auction result without exposing competitor bids.
13. Explain why second-price intuition still needs quality score and reserve price.
14. Explain why a report can be approximate while an invoice cannot.
15. Explain what happens when conversion events arrive after report finalization.
16. Explain how to repair a bad campaign pause propagation incident.
17. Explain how to separate flash crowd from click fraud.
18. Explain what to disable first when feature store p99 breaches the ad budget.
19. Explain why failing caps open is dangerous for both user trust and spend.
20. Explain how Northstar checkout remains insulated from ads backlog.
21. Name the first metric you page on for overpacing.
22. Name the first metric you page on for underdelivery.
23. Name the first metric you page on for billing integrity.
24. Name the first metric you page on for privacy-safe fallback.
25. Name the first metric you page on for advertiser noisy neighbor behavior.
26. Reject a global cache flush during a cap hot-key incident.
27. Reject a global ads disable when one campaign is overpacing.
28. Reject a replay of raw events before sinks are idempotent and serving is stable.
29. Reject manual DB edits that bypass campaign changelog and materializers.
30. Define a game day that proves campaign-level blast radius.

## Takeaways and Reading

- Ad platforms are low-latency decision systems connected to ledger-like reconciliation systems.
- Eligibility, policy, budget, pacing, and caps happen before revenue-maximizing ranking.
- A signed response is not a billable impression; billing needs durable, deduped, auditable events.
- Pacing and frequency caps are hot-key factories unless designed with shards, leases, windows, and fallbacks.
- Multi-tenant advertisers need capacity isolation, report isolation, API quotas, and support-tool isolation.
- Graceful degradation favors no-ad or contextual/simple ranking over privacy, billing, or policy shortcuts.
- Incident response must stop overspend and user repetition before replaying logs or optimizing models.

### Targeted reading

- Review Week 6 Kafka material on at-least-once processing, idempotency, and replay before answering the attribution questions.
- Review Week 9 feed design for placement and ranking integration points.
- Review Week 11 payment/ledger modules before claiming billing correctness.
- Search for ad auction primers on first-price versus second-price intuition; focus on system implications, not pure theory.
- Read Northstar Commerce notes in `Ops-Sims/fictional-company/NORTHSTAR.md` for shared systems and recurring failure themes.
## Design Gates (mandatory)

Answer these before calling the design complete. Keep the learner notes concise; compare against the answer key only after attempting the gates.
> Model responses: [`../answers/Week-10-Media-and-Mobility-Designs/Design Ad Platform Answers.md`](../answers/Week-10-Media-and-Mobility-Designs/Design%20Ad%20Platform%20Answers.md)

### Gate 1 - Authn/z trust boundary

1. Who is authenticated in this design: end user, advertiser, admin, service, worker, device, or partner?
2. Where does the first untrusted request cross into the trusted control plane?
3. Which component makes the final authorization decision for each protected object or action?
4. What identity artifact is accepted: session cookie, bearer token, API key, mTLS identity, signed URL, or job identity?
5. What fails closed when the identity provider, policy store, or trust bundle is unavailable?

### Gate 2 - Abuse and misuse

6. Which actor can create the highest amplification while still looking like a legitimate user or tenant?
7. Which endpoint or background job can be abused after authentication succeeds?
8. What per-user, per-tenant, per-key, per-IP, per-region, and global quotas are required?
9. Which telemetry distinguishes organic demand from coordinated abuse?
10. Which retry policy can amplify a partial outage into a full outage?

### Gate 3 - Multi-tenant isolation

11. What is the tenancy model for API, database, cache, queue/topic, stream processor, index, and object storage?
12. Where is tenant context required, and how is it propagated through async jobs and support tools?
13. Which shared resource has reserved capacity or fair-share limits per tenant or tier?
14. How can one tenant be throttled, disabled, migrated, or isolated without affecting others?
15. What test proves a tenant cannot read another tenant's data through cache, search, export, report, or logs?

### Gate 4 - Unit cost at target scale

16. What is the business unit for cost: request, impression, click, conversion, auction, report row, or tenant?
17. At the stated target scale and peak multiplier, what is the rough unit cost driver?
18. Which line items dominate: compute, memory, storage, replication, egress, observability, ML inference, third-party APIs, or idle headroom?
19. What cost metric pages before margin, budget, or SLO error budget is breached?
20. What graceful degradation lowers cost without damaging the correctness-critical path?

### Gate 5 - Failure blast radius

21. What is the smallest unit that can fail independently: partition, shard, cell, topic, region, tenant, cache key, model, worker pool, or queue?
22. Which dependencies are shared between critical and non-critical paths?
23. What fails closed, what serves stale, and what can be disabled first?
24. Which runbook action could accidentally widen blast radius?
25. What game day proves the blast radius stays inside the intended boundary?

## Ops Sim: Northstar Sponsored Ads Overpacing

**Time box:** 35 minutes
**Severity:** P1
**Service / domain:** Ad serving, budget pacing, attribution, multi-tenant advertiser platform
**Northstar system (if any):** Northstar Commerce

### Rules

1. Answer from memory of the teaching section; do not re-read mid-drill.
2. Write decisions in order from T+0 through T+60.
3. Name evidence for every claim: metric, log line, config key, trace, or capacity check.
4. Do not open `answers/` until finished.

### 1. Scenario stem

```text
WHAT USERS SEE:
  Search and feed pages still load, but sponsored results repeat the same luxury handbag creative 6 to 9 times per session.
  Some users report clicking the ad and landing on an out-of-stock product page.
  Product detail pages in eu-west-1 show blank sponsored slots for 8 percent of requests.

WHAT ON-CALL SEES:
  `ads-serving-p99` page fired in `us-east-1` and `eu-west-1`.
  `campaign_overpacing_ratio` fired for advertiser tenant `adv-luma-market`.
  Seller support reports three smaller advertisers with sudden underdelivery in the same category.

BUSINESS CONSTRAINT:
  Northstar is in the first hour of a live auction event with 800k concurrent users.
  Checkout and bidding systems must not be slowed by ad mitigation.
```

### 2. Telemetry pack

```text
METRICS:
  ad_decision_qps: 78k global, 9.4x normal
  ads_serving_p99_ms: us-east-1=184, eu-west-1=212, ap-northeast-1=91
  no_fill_rate: global=2.1%, eu-west-1_product_detail=8.4%
  campaign adv-luma-market spend_rate: 6.8x target curve
  campaign adv-luma-market budget_lease_outstanding: $14,800, expected <= $2,000
  frequency_cap_hit_rate for adv-luma-market: 0.3%, normal category baseline 9.7%
  cap_service hot key: fc:user_bucket:*:campaign:camp-9842 p99=41ms, CPU shard-7=94%
  candidate_index_lag_seconds: us-east-1=18, eu-west-1=311
  impression_event_lag_seconds: p95=44, p99=420
  checkout conversion events healthy: p99 lag=12s
  ad_feature_store timeout_rate: 6.2% for category=luxury_accessories
  billing ledger writes normal: 2.1k/sec, error_rate=0.02%

LOG LINES:
  WARN pacing lease exceeded campaign_id=camp-9842 region=us-east-1 outstanding_usd=9300 target_remaining_usd=1800
  WARN cap lookup fallback mode=open campaign_id=camp-9842 reason=redis_timeout
  INFO creative render creative_id=cr-221 product_id=sku-99813 inventory_status=OUT_OF_STOCK cache_age=27m
  WARN materializer lag tenant=adv-luma-market region=eu-west-1 partition=17 lag=308s
  INFO fraud_score click_cluster=ip-asn-441 risk=medium entropy=user_high conversion_quality=normal
  ERROR feature_lookup deadline_exceeded model=ctr-v43 placement=search_top_1 timeout_ms=25

TRACES / LAG / EXPLAIN:
  Trace ad-request /search?q=handbag region=eu-west-1 request_id=req-991:
    context_builder 9ms, candidate_retrieval 18ms, policy_filter 11ms, cap_check 49ms, ranker 64ms, auction 6ms, emit_log 4ms
  Kafka topic ads.campaign_changed partition 17 consumer lag: 1.2M records
  Kafka topic ads.impression.raw lag: 14M records but producers healthy
  Redis shard cap-state-7 top command: MGET 83%, top key family campaign camp-9842
```

### 3. Config pack (one line is wrong or dangerous)

```yaml
ads_serving:
  cap_service_timeout_ms: 25
  cap_service_on_timeout: allow  # suspicious
  max_candidates_for_deep_rank: 120
  ranker_timeout_ms: 35
  model_fallback: bid_x_quality_v2
pacing:
  budget_lease_max_usd_per_campaign_region: 10000  # suspicious
  lease_refresh_seconds: 60
  overspend_guard_percent: 1.0
materializer:
  campaign_changed_partitions: 48
  tenant_bulk_update_concurrency: unlimited  # suspicious
kill_switches:
  disable_campaign: true
  disable_candidate_source_by_region: true
  force_contextual_only: true
```

### 4. Timeline and decision points

| Time | Event | Your move (write before reading further) |
|---|---|---|
| T+0 | Ad p99 and overpacing pages fire; auction event traffic is still climbing. | |
| T+5 | Finance says campaign `camp-9842` may overspend by $20k if current slope continues. | |
| T+15 | EU materializer lag grows; support asks whether to globally disable sponsored product ads. | |
| T+60 | Traffic normalizes, but raw impression lag remains high and advertisers ask for delivery reports. | |

### 5. Questions

**Q1 - Layer and root cause:** Which layer owns the primary user symptom? What is the likely mechanism?
**Q2 - Evidence:** Which 5 signals support your diagnosis, and which signal is a red herring?
**Q3 - Sequencing:** What do you do in the first 15 minutes? What do you explicitly not do yet?
**Q4 - Bad fix gallery:** Why is globally disabling ads risky? Why is increasing Redis nodes or Kafka consumers alone incomplete?
**Q5 - Capacity and blast radius:** Estimate overspend exposure from outstanding leases and name the smallest safe blast-radius boundary.
**Q6 - Durable fix:** Which config, architecture, and acceptance tests prevent this class of incident?
**Q7 - Org/runbook:** Who must be informed by T+10, and what actions are pre-authorized for the ad on-call?
**Q8 - Reconciliation:** After mitigation, how do you repair billing, reports, caps, and affected advertiser trust without deleting raw evidence?

### 6. Self-score after answer key

| Error type | Did it happen? | Note |
|---|---|---|
| Knowledge gap | | |
| Wrong layer | | |
| Sequencing error | | |
| Capacity miss | | |
| Blast-radius miss | | |
| Org or runbook miss | | |
| Careless slip | | |

**Pass:** correct layer, safe first mitigation, at least one capacity check, and a rejected bad fix.

