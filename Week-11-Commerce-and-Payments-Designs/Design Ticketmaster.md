# Design Ticketmaster

> Week 11, Topic 3 - System Design. Ticket inventory, assigned-seat maps,
> waiting rooms, flash-sale holds, payment capture, fairness, and bot defense.
> Cross-links: Week 11 Payment System, Week 11 E-Commerce Platform,
> Week-08c abuse hardening (`Retention-Tests/Week-08c.md`), and
> `Ops-Sims/Week-04-Northstar-Flash-Sale-Cascade.md`.

---

## Learning Objectives

### Foundation

After this module, you will be able to:

1. Explain why ticketing inventory is not a simple counter.
2. Model an assigned seat as a finite-state object.
3. Separate seat-map browsing from authoritative seat holding.
4. Design TTL holds that release inventory safely.
5. Prevent oversell with conditional writes or serial event partitions.
6. Use a waiting room to shape demand before it hits hot event shards.
7. Explain authorization vs capture for card payments.
8. Tie bot controls to fairness without blocking legitimate fans.
9. State which data is authoritative and which data is only a projection.
10. Diagnose stale seat maps without violating the no-oversell invariant.

### Staff

After the Staff tier, you will be able to:

1. Size event-sharded inventory for a high-demand onsale.
2. Defend partition keys for holds, orders, and seat-map updates.
3. Bound payment-provider retries with idempotency keys.
4. Design a purchase flow where every state transition is replay-safe.
5. Choose between virtual queue, lottery, dynamic throttling, and open sale.
6. Design runbooks for "payments slow but holds expiring".
7. Distinguish organic flash crowd from credential stuffing or bot farms.
8. Explain how fairness controls interact with revenue and trust.
9. Keep search, CDN, and seat-map read models fast while stale.
10. Define blast radius by event, venue, region, partner, and payment rail.

### Principal stretch

After the stretch tier, you will be able to:

1. Design multi-region active/passive ticketing without double-selling seats.
2. Decide when to sacrifice latency, fairness, or conversion.
3. Create an abuse program that survives adversarial bot adaptation.
4. Explain incentives around scalping, transfer, resale, and fees.
5. Review a design for legal, payments, SRE, product, and venue constraints.
6. Precompute and rehearse onsale capacity using event heat scores.
7. Create a migration plan from legacy ticketing systems to event shards.
8. Set executive-facing incident thresholds for celebrity onsales.
9. Prevent support tooling from violating tenant or venue boundaries.
10. Design observability that proves "no oversell" under partial outages.

---

## Wrong Mental Models

### Foundation

```
MENTAL MODEL #1: "A ticket is like a shopping-cart SKU."
Wrong. A ticket can be an exact seat, a general-admission entitlement,
a wheelchair-accessible seat, a promoter hold, a companion seat, or resale.
Inventory is a graph of constraints, not one integer.

MENTAL MODEL #2: "If the seat map shows a seat, the user can buy it."
Wrong. Seat maps are read models. They are allowed to be stale. The hold
service is authoritative and must revalidate every requested seat.

MENTAL MODEL #3: "Put Redis in front and the flash sale is solved."
Wrong. Caching helps browse and rendering. It does not serialize ownership.
The oversell invariant lives in the hold store or per-event command log.

MENTAL MODEL #4: "Payment success means the ticket is sold."
Wrong. Authorization reserves funds; capture moves money later. The system
must coordinate inventory commit, order creation, capture, and repair.

MENTAL MODEL #5: "Waiting rooms are only UX."
Wrong. Waiting rooms are load-shedding, fairness, fraud, and capacity-control
systems. They decide who can consume scarce hold attempts per unit time.

MENTAL MODEL #6: "Bots are just high QPS."
Wrong. Bots distribute IPs, age accounts, replay sessions, use real cards,
and solve CAPTCHAs. Week-08c abuse lessons apply: limit by account, device,
payment instrument, velocity, risk, and event, not only by IP.
```

### Staff

```
MENTAL MODEL #7: "Consistent hashing by seat_id spreads load."
Incomplete. The event is the operational unit. A stadium onsale is hot as a
whole. Spread seats enough for throughput, but keep adjacent selection cheap.

MENTAL MODEL #8: "TTL cleanup is immediate."
Wrong. DynamoDB TTL, Redis expiry notifications, and scheduled jobs are not
exact. The hold expiry timestamp is authoritative; cleanup removes garbage.

MENTAL MODEL #9: "Disable holds if payment is slow."
Dangerous. That creates either oversell or double booking. Slow payment rails
require longer targeted holds, degraded capture, queue throttling, or pause.

MENTAL MODEL #10: "Fairness means first request wins."
Incomplete. First request wins rewards lowest latency, bot proximity, and
scripted retries. Fairness may require randomized queue order and cohorts.

MENTAL MODEL #11: "Seat-map polling is harmless."
Wrong. A million users refreshing SVG tiles can drown the event cell that
holds need. Seat maps require CDN, projection, and cache boundaries.

MENTAL MODEL #12: "The PSP can be the source of truth."
Wrong. The order/ledger system records business truth. PSP callbacks are
external evidence that must be reconciled idempotently.
```

### Principal stretch

```
MENTAL MODEL #13: "Active/active is required for availability."
Usually wrong for assigned seats. Two regions independently committing the
same seat buys an integrity incident. Prefer event home region and fencing.

MENTAL MODEL #14: "More anti-bot friction is always better."
Wrong. Friction can block accessible users, mobile users, privacy-conscious
users, and high-latency regions. False-positive budgets matter.

MENTAL MODEL #15: "Resale is outside the core design."
Wrong. Transfer and resale alter ownership, fraud risk, refunds, chargebacks,
and ticket validity at the venue gate.
```

---

## Requirements & Constraints

### Foundation - product scope

Functional requirements:

1. Browse events by artist, venue, city, date, and category.
2. View event detail page with ticket types, price ranges, and sale timing.
3. Render an interactive seat map for reserved-seat venues.
4. Support general admission inventory where seats are not assigned.
5. Support primary sale, presale, verified-fan sale, promoter allocation, and resale.
6. Place a short-lived hold on selected seats or GA quantity.
7. Keep held inventory unavailable to other buyers.
8. Expire holds automatically when users abandon checkout.
9. Let users pay with card, wallet, gift balance, or stored payment method.
10. Authorize payment before final commit when possible.
11. Capture payment exactly once after inventory commit is durable.
12. Create an order with ticket entitlement, barcode/token metadata, and receipt.
13. Support refund, void, transfer, resale listing, and venue scan validation.
14. Provide support/admin tools scoped by venue, promoter, event, and role.
15. Provide public APIs or partner feeds where contracts require them.

Non-functional requirements:

1. Oversell target is zero for assigned seats.
2. GA oversell target is zero beyond configured safety buffer.
3. Hold p99 under 250 ms for warm event shards during onsale.
4. Seat-map read p99 under 300 ms with CDN/projection help.
5. Waiting-room admission p99 under 100 ms excluding intentional wait time.
6. Payment authorization p99 is external; local timeout budget is explicit.
7. Checkout completion availability target is higher than browse availability.
8. Event isolation must prevent one onsale from harming unrelated events.
9. Bot controls must handle flash traffic without assuming all spikes are abuse.
10. Auditability must explain every state transition for disputed seats.
11. Accessibility must preserve ADA seat rules and companion-seat policy.
12. Privacy must protect buyer identity, payment tokens, and device signals.
13. Cost guardrails must page before queue or CDN spend runs away.
14. Operations must support scheduled celebrity onsales with war-room staffing.
15. Venue gate scanning must remain available when purchase APIs degrade.

### Design Gates - authn/z trust boundary

1. Authenticated actors include users, guests, admins, venue scanners, partners, and services.
2. Guest users may browse and join waiting rooms; high-risk onsales may require login.
3. The first trust boundary is crossed at CDN/WAF/API gateway.
4. Session cookies or OAuth tokens identify users at the BFF.
5. Service-to-service calls use workload identity or mTLS.
6. Admins use step-up auth and role-bound support consoles.
7. Venue scanners use device certificates plus event-scoped tokens.
8. Partners use scoped API keys, signed webhooks, and per-partner quotas.
9. Authorization for seat holds is enforced by Hold Service, not by the UI.
10. Authorization for event configuration is enforced by Event Admin Service.
11. Authorization for transfer/resale is enforced by Ownership Service.
12. Payment token scope is enforced by Payment Orchestrator.
13. Policy store outage fails closed for admin mutation and payment capture.
14. Policy store outage can allow public browse with cached safe policy.
15. Every hold command carries user_id, session_id, device_id, event_id, and risk decision id.

### Design Gates - abuse and misuse

1. Organic fans overload event detail pages and seat maps.
2. Bots overload login, queue join, seat-map scrape, hold, and payment.
3. Scalpers create aged accounts to bypass simple signup limits.
4. Credential-stuffing attacks target stored payment and transfer flows.
5. Card testers target low-value events and gift balances.
6. Resale bots poll transfer/listing APIs for underpriced seats.
7. Insider misuse targets admin allocation and manual release tools.
8. Partner misuse can scrape inventory through privileged feeds.
9. Controls are layered by IP, ASN, device, account, payment instrument, household, event, and cohort.
10. Rate limits use token cost: hold attempt costs more than browse.
11. Verified-fan cohorts can reserve queue lanes.
12. CAPTCHA is used after risk signals, not as the only gate.
13. Queue tokens are signed, single-use, event-scoped, and short-lived.
14. Replay of queue or hold requests is rejected by nonce/idempotency key.
15. Evidence for abuse includes impossible click cadence, low think time, high failure velocity, account graph clusters, and solve-farm patterns.
16. Evidence for organic flash traffic includes marketing calendar, social trend, normal account age mix, and lower automation features.
17. Week-08c abuse hardening applies: do not rely on IP-only limits.
18. Bad anti-bot fix: block all VPNs during onsale without false-positive budget.
19. Bad anti-bot fix: share device fingerprints with support tools without privacy controls.
20. Bad anti-bot fix: add global CAPTCHA after the event shard is already melting.

### Design Gates - multi-tenant isolation

1. Tenants are venues, promoters, artists, partners, and internal business units.
2. Event is the primary blast-radius cell.
3. Venue is the secondary administrative boundary.
4. Promoter contracts may require allocation privacy.
5. Partner feeds are quota-isolated by partner_id and event_id.
6. Shared tables include tenant/event identifiers in every key and log.
7. Dedicated event shards are allocated for high-heat onsales.
8. Support exports require venue/promoter authorization filters.
9. Scanner devices can only validate tickets for assigned event windows.
10. Payment merchant accounts may differ by region or promoter.
11. Fraud decisions are event-scoped but can use cross-event account signals.
12. One event can be paused without pausing all events.
13. One partner feed can be throttled without harming direct purchase.
14. One venue scanner fleet can be revoked without invalidating buyer ownership.
15. Admin actions are audited with actor, tenant, event, and reason.

### Design Gates - unit cost at target scale

Primary business unit: successful order and peak hold attempt.

Target scale for capacity exercises:

1. 20 million monthly active users.
2. 2 million daily active users.
3. 100,000 concurrent users for a normal large onsale.
4. 5 million waiting-room users for a celebrity onsale.
5. 250,000 admission tokens per minute during queue ramp.
6. 25,000 seat-map reads per second for one hot event.
7. 8,000 hold attempts per second for one hot event.
8. 2,000 successful orders per second during first minute.
9. 4 seats average per order for group purchase.
10. 15 minute default checkout hold.
11. 3 minute emergency hold for scarce events with slow queues.
12. 30 second stale seat-map projection SLO.
13. 5 second hold-state stream SLO for hot sections.
14. 30 day audit retention for hot operational logs; longer financial retention elsewhere.
15. Assigned seat target is exact; a percentage oversell SLO is not acceptable.

Dominant cost lines:

1. CDN egress for maps and event pages.
2. Waiting-room state and signed token verification.
3. Event-shard write capacity for holds.
4. Payment-provider fees and auth retries.
5. Bot-detection compute and third-party signals.
6. Observability cardinality from event/section/seat labels.
7. Idle headroom reserved for scheduled onsales.
8. Support and chargeback operations after incidents.
9. Scanner offline sync and venue edge devices.
10. Fraud review queues for high-risk purchases.

Cost guardrails:

1. Page if seat-map origin request rate exceeds planned CDN miss budget.
2. Page if hold attempts per admitted user exceed risk-adjusted forecast.
3. Page if bot scoring cost per admitted user exceeds fee margin.
4. Page if PSP auth retries exceed provider-rate budget.
5. Page if observability ingest for one event exceeds event cell budget.

### Design Gates - failure blast radius

Smallest failing units:

1. Seat key for a single assigned seat.
2. Section shard for groups of seats.
3. GA bucket for a ticket type.
4. Event cell for all inventory writes of one event.
5. Waiting-room cohort for one event.
6. Payment rail by provider, region, and merchant account.
7. Partner feed by partner_id and event_id.
8. Venue scanner cell by venue and event day.

Shared dependencies:

1. Identity provider.
2. WAF and bot scoring.
3. CDN configuration.
4. Payment provider.
5. Fraud model.
6. Observability backend.
7. Global config service.
8. Support console.

Degrade first:

1. Seat-map fidelity degrades before hold writes.
2. Real-time price/availability banners degrade before checkout.
3. Resale listing creation degrades before primary sale.
4. Partner feeds degrade before direct purchase.
5. Non-critical recommendations degrade before event pages.
6. Global search degrades before event-specific checkout.

Fail closed:

1. Hold commit when state is ambiguous.
2. Payment capture when inventory commit is not durable.
3. Transfer when ownership proof is unavailable.
4. Admin release when authorization policy is unavailable.
5. Scanner revocation override when device identity is invalid.

Runbook actions that widen blast radius:

1. Disabling queue globally instead of for one event.
2. Raising hold-service concurrency without checking partition hot keys.
3. Turning off bot scoring for all onsales.
4. Extending all holds globally during one PSP incident.
5. Replaying payment captures without idempotency keys.
6. Flushing CDN for all seat maps during one stale projection.
7. Switching event writes to another region before sealing old writes.

---

## Architecture Overview

### Foundation - logical services

```
Fans
  |
  v
CDN + WAF + Bot Edge
  |
  v
BFF / API Gateway
  |
  +--> Event Catalog Service
  +--> Seat Map Service
  +--> Waiting Room Service
  +--> Hold Service
  +--> Checkout Orchestrator
  +--> Payment Orchestrator
  +--> Order / Ticket Ownership Service
  +--> Transfer / Resale Service
  +--> Venue Scanner Service
  +--> Admin / Allocation Service
```

Core data stores:

1. Event catalog store: events, venues, performers, sale windows.
2. Inventory command store: authoritative seat and GA state.
3. Seat-map projection store: read-optimized map tiles and summaries.
4. Hold store: active holds with expires_at and state.
5. Order store: durable order and line items.
6. Payment ledger: internal payment attempts and PSP references.
7. Ownership store: ticket entitlement and transfer history.
8. Queue store: waiting-room cohort, randomization, admission leases.
9. Risk store: account/device/payment/event risk decisions.
10. Audit log: append-only admin and state transition evidence.

### Staff - event cell decomposition

Each high-heat event receives an event cell.

The event cell contains:

1. A route table entry for event_id.
2. Dedicated hold workers.
3. Dedicated inventory partitions.
4. Dedicated seat-map projection workers.
5. Dedicated queue admission controller.
6. Dedicated dashboards and SLO burn alerts.
7. Reserved PSP concurrency budget if contract allows.
8. Dedicated support runbook page.
9. Event-specific bot policy.
10. Event-specific kill switches.

Why event cells work:

1. Fan demand is correlated by event.
2. Seat contention is bounded inside one event.
3. Queue admission can be tuned per event heat score.
4. A bad onsale does not exhaust global checkout workers.
5. War-room ownership maps to one operational unit.
6. Per-event cost and fairness can be measured.
7. Event cells make failure blast radius explicit.

Principal stretch region strategy:

1. Event has a home write region.
2. Queue tokens route admitted users to the home region.
3. Seat-map projections replicate outward.
4. Orders replicate for read/support after commit.
5. Venue scanner packages are pre-distributed before doors open.
6. Failover requires fencing the old region.
7. Failover publishes a new event write epoch.
8. Hold commands from old epoch are rejected.
9. Payment captures wait for inventory commit evidence.
10. Recovery reconciles ambiguous auths before capture.

---

## Critical Paths

### Path 1 - event creation and inventory import

Foundation sequence:

1. Promoter creates event shell.
2. Venue template defines sections, rows, seats, entrances, and accessibility metadata.
3. Pricing team defines price levels and ticket types.
4. Allocation service marks promoter holds, artist holds, VIP packages, and public sale pool.
5. Admin publishes sale windows: presale, verified fan, general onsale.
6. Inventory import validates seat uniqueness within event.
7. Inventory command store receives seats in AVAILABLE or BLOCKED state.
8. Seat-map projection builder creates static geometry tiles.
9. Availability projection marks sellable seats by section and price level.
10. Event cell capacity plan is generated from heat score.
11. Waiting-room policy is attached to the sale window.
12. Bot policy is attached to the event.
13. Admin sign-off freezes seat geometry before public sale.
14. Audit log records every allocation and policy change.
15. Synthetic hold-and-release test runs before sale opens.

Staff checks:

1. Seat identifiers are deterministic and scoped by event_id.
2. Imported seats cannot overlap between public sale and promoter hold.
3. Accessible seats cannot be converted without policy approval.
4. Price-level changes carry version numbers.
5. Seat-map projection references inventory_version.
6. Sale-window config has a rollback plan.
7. Queue policy has a maximum admission rate.
8. Event cell has reserved write capacity.
9. PSP merchant account is configured.
10. Scanner package generation is scheduled.

Principal review:

1. Legacy venue feeds may resend full inventory; import must be idempotent.
2. Promoter allocations are tenant-sensitive; logs and exports need redaction.
3. Freeze windows prevent late admin changes from invalidating queue fairness.
4. Heat score uses waitlist, social demand, artist history, and bot telemetry.
5. Rehearsal includes support, fraud, venue, and payments, not only SRE.

### Path 2 - waiting-room join

Foundation sequence:

1. User lands on event page before sale.
2. CDN serves static event content and queue bootstrap JavaScript.
3. BFF requests a queue join challenge for event_id and sale_window_id.
4. Bot edge evaluates IP, device, account, session age, and browser signals.
5. User completes required friction if risk policy requires it.
6. Waiting Room Service assigns queue_entry_id.
7. Queue entry stores user/session/device/event/cohort/risk_decision_id.
8. Entry receives a randomized position or lottery bucket.
9. Queue token is signed and event-scoped.
10. Client polls or receives SSE/WebSocket updates from queue projection.
11. Queue admission controller releases tokens at configured rate.
12. Admission token contains event_id, cohort, expires_at, max_hold_attempts, and nonce.
13. Hold Service validates admission token before accepting hold commands.
14. Expired admission token requires rejoin or revalidation.
15. Queue state is audited for fairness review.

Why randomization matters:

1. It reduces advantage from millisecond request timing.
2. It reduces bot value from edge colocation.
3. It gives product a fairness story before demand is known.
4. It lets verified cohorts receive controlled priority.
5. It separates "joined before sale" from "hammered endpoint at sale start".

Admission rate math:

1. If hold capacity is 8,000 attempts/sec, do not admit 100,000 users/sec.
2. If each admitted user makes 4 hold attempts/min, 120,000 admitted users create 8,000 attempts/sec.
3. If payment p95 is 8 seconds, checkout workers must absorb admitted conversion.
4. If average group size is 4 seats, 2,000 orders/sec consumes 8,000 seats/sec.
5. If event has 70,000 public seats, a full sellout at 2,000 orders/sec takes about 35 seconds.
6. A queue ramp slower than sellout time is normal for scarce events.
7. Queue transparency should say "demand exceeds supply", not "everyone will get tickets".

Bad waiting-room designs:

1. Queue token not bound to event_id.
2. Queue token reusable for unlimited hold attempts.
3. Queue admission independent of hold-service health.
4. Queue position stored only in browser local storage.
5. Queue poll endpoint bypasses CDN and melts origin.
6. Queue order based only on request arrival timestamp.
7. CAPTCHA checked after admission instead of before scarce resource access.
8. No way to pause admission while preserving already-held seats.

### Path 3 - seat-map browse

Foundation sequence:

1. User opens event detail page.
2. CDN serves event shell, static venue geometry, and price legend.
3. Client requests availability summary by section.
4. Seat Map Service reads projection store, not inventory command store.
5. Projection returns section counts, price ranges, and freshness timestamp.
6. Client zooms into a section.
7. Seat Map Service returns tile or vector layer with seat states.
8. Seat states are coarse: available, held/sold/unavailable, accessible, companion, resale.
9. Projection may lag hold stream by configured SLO.
10. UI warns when availability is changing quickly.
11. User selects seats locally.
12. Client submits exact seat_ids to Hold Service.
13. Hold Service revalidates against authoritative inventory.
14. Projection gets updated by hold/sold events asynchronously.
15. Seat map never grants ownership.

Read-model design:

1. Static geometry is immutable and CDN cached for a year using versioned URL.
2. Availability summary has short TTL, often 1-5 seconds during onsale.
3. Availability tile cache can be section-scoped.
4. Hot sections can be pushed through WebSocket/SSE to reduce polling.
5. Projection store can be Redis, DynamoDB, Cassandra, or document cache.
6. Projection key includes event_id and section_id.
7. Projection value includes inventory_version or stream_offset.
8. UI must show stale timestamp for internal tools.
9. Public UI can show "limited availability" instead of exact counts near sellout.
10. Seat-level availability may be hidden from unauthenticated users on high-risk events.

Seat-map scale levers:

1. CDN static geometry.
2. Cache section summaries.
3. Collapse rapid hold events into delta batches.
4. Push only visible viewport changes.
5. Rate-limit zoomed seat-level views.
6. Use approximate counts during high churn.
7. Reserve inventory writes for hold service, not map reads.
8. Separate projection workers from hold workers.
9. Drop low-priority projection updates before delaying hold commits.
10. Pre-render common venue tiles before sale.

Staleness rules:

1. A seat shown available can be rejected at hold time.
2. A seat shown unavailable can become available after hold expiry.
3. A sold seat should never become available without explicit admin reversal.
4. Projection must converge from the authoritative stream.
5. Projection loss can be rebuilt from inventory snapshot plus event log.
6. Stale map is a UX defect; oversell is an integrity defect.
7. The system chooses integrity over map freshness.

### Path 4 - assigned-seat hold

Foundation sequence:

1. Client sends hold request with event_id, seat_ids, admission_token, idempotency_key.
2. API validates authentication/session and admission token.
3. Risk service confirms the decision is still valid.
4. Hold router maps event_id and section/row to inventory shard.
5. Hold Service loads requested seat states.
6. Hold Service checks all seats are AVAILABLE and in the sale pool.
7. Hold Service checks adjacency, accessibility, orphan-seat policy, and max quantity.
8. Hold Service performs atomic conditional transition to HELD.
9. Hold record is created with hold_id, user_id, seats, expires_at, and state HELD.
10. Hold expiry is usually 2-15 minutes depending on event heat.
11. Seat-held event is emitted to projection stream.
12. Response returns hold_id, expires_at, checkout deadline, and payment options.
13. Client displays countdown.
14. Duplicate hold request with same idempotency_key returns same hold_id.
15. Duplicate hold request with different key for same user may be limited.

Atomicity options:

1. Single partition transaction for seats in one section shard.
2. Per-event command log with deterministic serial processor.
3. Relational row locks scoped to event shard.
4. DynamoDB TransactWrite for small adjacent seat sets.
5. Redis Lua can be a fast gate only if backed by durable commit discipline.
6. Kafka partition can serialize commands but response latency and durability must be designed.
7. Actor model per event section is simple but needs failover state replay.

Assigned-seat invariant:

1. AVAILABLE can transition to HELD.
2. HELD can transition to SOLD if matching hold_id is valid.
3. HELD can transition to AVAILABLE after expires_at if not committed.
4. HELD can transition to RELEASED by user cancel or saga compensation.
5. SOLD cannot transition to AVAILABLE except admin refund/void workflow.
6. RELEASED is an audit state; availability may be represented separately.
7. Every transition has actor, reason, command_id, and previous_version.
8. Two successful holds for same seat_id and overlapping time are forbidden.

Conditional write example:

```text
PK = EVENT#E123#SECTION#A
SK = SEAT#A-10-14
Condition: state = AVAILABLE AND version = expected_version
Update: state = HELD, hold_id = H789, expires_at = now + ttl, version += 1
```

Multi-seat challenge:

1. Group purchase requires all requested seats or none.
2. Adjacent seats may share one section shard.
3. Cross-section purchases can require multiple shards.
4. Two-phase locking across shards risks deadlock during flash sale.
5. Prefer routing groups to one section shard when possible.
6. If cross-shard is required, order locks by shard_id.
7. Keep cross-shard hold size small.
8. Use compensation to release partial holds if transaction fails.
9. Reject complex seat combinations before hot path when possible.
10. Preserve user trust by showing "these seats are gone" quickly.

Oversell prevention rules:

1. UI optimism never bypasses conditional hold.
2. Payment authorization never bypasses conditional hold.
3. Admin manual sale never bypasses conditional hold or command log.
4. Queue admission never guarantees seat availability.
5. Projection lag never creates inventory.
6. Retries use idempotency keys.
7. Timeout status is UNKNOWN until read-after-write or command result confirms.
8. Unknown hold status does not permit a second conflicting hold.
9. Hold expiry compares server time to expires_at.
10. TTL deletion is not the authority for expiry.

### Path 5 - general-admission hold

Foundation sequence:

1. GA ticket type has capacity and safety buffer.
2. Sellable = capacity - sold - held - blocked - safety_buffer.
3. Hold request asks for quantity, not seat_ids.
4. Hold Service checks max tickets per user and sale cohort.
5. Conditional update increments held if sellable >= requested quantity.
6. Hold record stores ticket_type_id and quantity.
7. Expiry decrements held if hold was not committed.
8. Commit moves held to sold.
9. Refund/void moves sold to refunded and may or may not return capacity.
10. Scanner validates entitlement count at the gate.

GA hot-key mitigation:

1. Split a ticket type into N inventory buckets.
2. Preallocate capacity across buckets.
3. Route user to bucket by hash(user_id or queue_entry_id).
4. Hold within one bucket using conditional update.
5. Keep a small coordinator for bucket top-up if allowed.
6. Avoid summing all buckets per request.
7. Display approximate remaining inventory.
8. Rebalance only before sale or with careful epoching.
9. Bucket safety buffers absorb eventual release lag.
10. Oversell prevention still requires per-bucket strict caps.

Bucket math:

1. 40,000 GA tickets.
2. 1,000 safety buffer for late reconciliation and venue holds.
3. 39,000 sellable public capacity.
4. 64 buckets gives about 609 sellable tickets per bucket.
5. 8,000 hold attempts/sec gives 125 attempts/sec per bucket if uniform.
6. If bot traffic skews to 4 buckets, those buckets see 2,000 attempts/sec each.
7. Risk routing should not let attackers choose bucket.
8. Queue_entry_id hashing is harder to game than client-chosen parameters.

### Path 6 - checkout and payment

Foundation sequence:

1. User enters checkout with hold_id.
2. Checkout validates hold ownership and unexpired expires_at.
3. Price service returns price snapshot, fees, taxes, and currency.
4. User accepts final price.
5. Payment Orchestrator creates payment_attempt with idempotency key.
6. PSP authorization reserves funds.
7. Authorization success is recorded with PSP auth id.
8. Checkout Orchestrator commits inventory from HELD to SOLD.
9. Order Service creates order and line items.
10. Ownership Service creates ticket entitlements.
11. Payment Orchestrator captures authorized funds.
12. Receipt and tickets are delivered.
13. Projection marks seats sold.
14. Scanner package eventually receives sold entitlement.
15. Reconciliation job compares orders, inventory, ownership, and PSP ledger.

Why authorize before commit:

1. It avoids selling seats to users who cannot pay.
2. It reduces refund noise.
3. It still requires hold TTL long enough for PSP latency.
4. It creates ambiguous states when auth succeeds and commit times out.
5. Ambiguity is repaired by idempotent state machine.

Why capture after commit:

1. Capturing before inventory commit can charge for unavailable seats.
2. Capturing exactly once requires internal payment_attempt state.
3. Capture can be retried after transient PSP errors.
4. Capture should not be retried if order was voided.
5. Capture failure after sold state requires fulfillment hold and escalation.

Checkout timeouts:

1. If PSP authorize times out, status is UNKNOWN.
2. Query PSP by idempotency key or merchant reference.
3. Do not submit a second unrelated auth while hold is active.
4. If hold expires before auth resolves, void auth if it later appears.
5. If inventory commit times out, read hold/order state before capture.
6. If capture times out, reconcile before retrying.
7. User messaging distinguishes "processing" from "failed".
8. Support tools show state evidence, not guesses.

### Path 7 - hold expiry and release

Foundation sequence:

1. Hold record includes expires_at from trusted server clock.
2. Checkout displays deadline from expires_at.
3. Hold Service rejects commit if now > expires_at unless grace policy applies.
4. Expiry scanner reads holds past expires_at.
5. Scanner conditionally releases HELD seats where hold_id still matches.
6. Release event updates seat-map projection.
7. TTL deletes or archives expired hold records later.
8. Metrics count expired, released, commit-after-expiry rejected, and cleanup lag.
9. Reaper is idempotent.
10. Reaper never releases SOLD seats.

TTL pitfalls:

1. TTL execution is delayed.
2. TTL deletion can remove audit evidence if misconfigured.
3. Expiry event delivery can be at-least-once.
4. Clock skew can expire holds too early if client time is trusted.
5. Long holds reduce churn but hoard inventory.
6. Short holds increase payment failure and accessibility pressure.
7. Global hold extension during PSP incident can starve waiting-room fairness.
8. Extending only affected payment cohorts is safer than global extension.
9. Release storm can spike projection writes.
10. Expiry backlog can make maps stale but must not oversell.

Grace policy:

1. A small server-side grace can protect users at payment submit boundary.
2. Grace must be event-scoped and explicit.
3. Grace cannot be visible as a promise to all users.
4. Grace consumes inventory and reduces queue throughput.
5. Grace is disabled when oversell risk is ambiguous.
6. Grace decisions are audited.
7. Payment submit timestamp must be server-received, not client-reported.

---

## Data Model & Capacity Math

### Foundation - entities

Event:

1. event_id.
2. venue_id.
3. performer_ids.
4. timezone.
5. sale_windows.
6. status.
7. heat_score.
8. home_region.
9. tenant/promoter ids.
10. config_version.

Seat:

1. event_id.
2. section_id.
3. row_id.
4. seat_number.
5. seat_id canonical string.
6. price_level_id.
7. accessibility_flags.
8. current_state.
9. hold_id nullable.
10. order_id nullable.
11. owner_ticket_id nullable.
12. version.
13. updated_at.

GA inventory bucket:

1. event_id.
2. ticket_type_id.
3. bucket_id.
4. capacity.
5. held_count.
6. sold_count.
7. blocked_count.
8. safety_buffer.
9. version.
10. epoch.

Hold:

1. hold_id.
2. event_id.
3. user_id.
4. session_id.
5. queue_entry_id.
6. risk_decision_id.
7. seat_ids or ticket_type quantities.
8. state.
9. expires_at.
10. idempotency_key.
11. price_snapshot_version.
12. created_at.
13. committed_at nullable.

Order:

1. order_id.
2. user_id.
3. event_id.
4. hold_id.
5. order_state.
6. total_amount.
7. currency.
8. payment_attempt_id.
9. line_items.
10. created_at.
11. captured_at nullable.
12. fulfillment_state.

PaymentAttempt:

1. payment_attempt_id.
2. order_id nullable until order exists.
3. hold_id.
4. user_id.
5. amount.
6. currency.
7. psp.
8. idempotency_key.
9. auth_id.
10. capture_id.
11. state.
12. retry_count.
13. last_psp_status.

QueueEntry:

1. queue_entry_id.
2. event_id.
3. sale_window_id.
4. user_id nullable for guests.
5. session_id.
6. device_id.
7. cohort.
8. random_bucket.
9. risk_score.
10. state.
11. admitted_at.
12. admission_token_id.

### Staff - partitioning keys

Recommended keys:

1. Event catalog by event_id and city/date secondary indexes.
2. Seat command key by event_id + section_shard_id.
3. Seat row key by seat_id inside section shard.
4. GA bucket key by event_id + ticket_type_id + bucket_id.
5. Hold key by hold_id, with GSI by user_id/event_id.
6. Order key by order_id, with GSI by user_id and event_id.
7. Payment key by payment_attempt_id and PSP merchant reference.
8. Queue key by event_id + sale_window_id + random_bucket.
9. Projection key by event_id + section_id + tile_id.
10. Audit log key by event_id + time bucket.

Avoid:

1. Global auto-increment order ids as the hot write key.
2. seat_id without event_id if seat labels repeat across venues.
3. user_id as primary inventory key; events are hotter than users.
4. one Redis key for total remaining inventory on celebrity onsale.
5. queue position stored in a single sorted set for all events.
6. payment attempts keyed only by PSP reference before PSP responds.
7. support exports keyed only by order_id without tenant context.

### Staff - hold throughput worksheet

Assumptions:

1. Hot event has 70,000 public assigned seats.
2. Waiting room has 5,000,000 entrants.
3. 1,000,000 entrants are admitted over the sale.
4. 20% admitted users attempt holds.
5. Each attempting user makes 3 hold attempts on average.
6. Peak hold attempt rate is 8,000/sec.
7. Average requested seats per hold is 3.
8. Successful orders peak at 2,000/sec for first minute.
9. Section shard can process 500 conditional writes/sec with headroom.
10. Seat-map projection consumes hold events at 50,000 seat updates/sec.

Calculations:

1. Hold attempts total = 1,000,000 * 20% * 3 = 600,000.
2. Peak seat conditional writes = 8,000 attempts/sec * 3 seats = 24,000 seat writes/sec.
3. Needed section shards = 24,000 / 500 = 48 shards before headroom.
4. With 2x headroom, plan 96 active section shards.
5. If one famous floor section receives 40% attempts, that section sees 9,600 seat writes/sec.
6. Floor section needs internal row shards or queue steering.
7. 70,000 seats / 2,000 orders/sec / 3 seats/order = about 11.7 seconds to sell if every order succeeds.
8. Real sellout time is longer because attempts fail, users choose seats, and payments take time.
9. Queue admission must target hold capacity, not available seat count only.
10. If payment auth p95 is 8 sec, 2,000 order/sec requires roughly 16,000 concurrent auths.
11. PSP concurrency must be negotiated before onsale.
12. If hold TTL is 10 min and 20,000 holds are active with 3 seats each, 60,000 seats are locked.
13. That can appear as near sellout before actual sale.
14. Shorter TTL increases churn; longer TTL increases hoarding.
15. Admission controller should respond to active_hold_count and sold_count.

### Staff - seat-map capacity worksheet

Assumptions:

1. 5,000,000 users wait.
2. 1,000,000 users open event page within 10 minutes.
3. Average page loads per user during waiting period = 3.
4. Seat-map zoom users = 20%.
5. Each zoom user requests 20 tiles.
6. CDN hit ratio for static geometry = 99%.
7. CDN hit ratio for availability summary during hot sale = 80%.
8. Origin p99 target = 300 ms.

Calculations:

1. Event page loads = 3,000,000 over 600 sec = 5,000/sec average.
2. Static geometry origin rate at 99% hit = 50/sec.
3. Availability summary origin rate at 80% hit = 1,000/sec average.
4. Zoom tile requests = 1,000,000 * 20% * 20 = 4,000,000.
5. Over 600 sec, zoom tile average = 6,667/sec.
6. At 90% tile cache hit, origin tile reads = 667/sec.
7. Projection store should handle burst multiples, not average only.
8. If cache key includes random query params, hit ratio can collapse to near zero.
9. A zero-hit tile storm can exceed 6,000 origin reads/sec for one event.
10. Protect origin with cache-key normalization and per-event throttles.

## Failure & Abuse Catalog

### Foundation - inventory failures

1. Oversell from non-atomic check-then-update.
2. Oversell from read-model availability used as authority.
3. Oversell from retrying timed-out commit with new command id.
4. Seat stuck HELD because expiry reaper failed.
5. Seat released incorrectly because TTL delete triggered without state check.
6. Hold committed after expiry due to client clock.
7. Group purchase partially held across shards.
8. Admin release races with checkout commit.
9. Price-level version mismatch after late price update.
10. Accessible seat sold without companion rule enforcement.

Mitigations:

1. Conditional writes or serial command processor.
2. Server time for expiry.
3. Idempotency key for hold and checkout.
4. Reaper condition checks hold_id and state.
5. Admin operations go through same command path.
6. Versioned pricing and user acceptance.
7. Orphan-seat and accessibility validators inside hold service.
8. Audit stream for all transitions.

### Staff - waiting room failures

1. Queue admits too many users after hold p99 rises.
2. Queue token replay opens unlimited hold attempts.
3. Queue position lost after cache node restart.
4. Queue poll endpoint becomes origin DDoS.
5. Risk vendor timeout blocks all legitimate users.
6. Friction challenge creates accessibility incident.
7. Randomization bug favors one browser or region.
8. Countdown UI promises tickets that are not available.
9. Sale pause drops admitted users without preserving order.
10. Bot actors farm queue entries weeks before sale.

Mitigations:

1. Admission rate tied to hold p99, active holds, sold count, PSP health.
2. Signed event-scoped admission tokens.
3. Durable queue entries with projection cache.
4. CDN/SSE for status; rate-limited polling.
5. Risk fail mode based on event policy: fail-closed for hold, degrade for browse.
6. Accessible alternative challenge.
7. Fairness audit on queue assignment.
8. UX copy separates admission from guaranteed purchase.
9. Pause and resume semantics.
10. Account age, verified fan, and device graph controls.

### Staff - payment failures

1. PSP auth succeeds but local timeout returns failure.
2. PSP auth succeeds and hold expires before commit.
3. Inventory commit succeeds but capture fails.
4. Capture succeeds but receipt generation fails.
5. Duplicate capture from retry without idempotency.
6. Chargeback after transfer or resale.
7. Fraud review holds fulfillment too long.
8. Payment provider rate limit during onsale.
9. Wallet callback arrives after user cancels.
10. Multi-currency rounding mismatch.

Mitigations:

1. Merchant reference idempotency.
2. Query PSP before retry.
3. Internal payment_attempt state machine.
4. Capture after durable inventory/order commit.
5. Reconciliation worker.
6. Void auth when inventory is unavailable.
7. Transfer delay for high-risk payments.
8. Provider concurrency pre-allocation.
9. Explicit callback state validation.
10. One pricing authority for final amount.

### Staff - abuse catalog

1. Credential stuffing to reuse stored cards.
2. Queue farming with many aged accounts.
3. Residential proxy hold storms.
4. Seat-map scraping to infer release patterns.
5. Low-and-slow card testing.
6. Gift-card balance draining.
7. Transfer phishing.
8. Support social engineering for manual release.
9. Partner API scraping.
10. Scanner device theft.
11. Replay of barcode screenshots.
12. Account graph collusion to bypass purchase caps.
13. CAPTCHA solve farms.
14. Bot scripts that simulate human pacing.
15. Refund abuse after transfer.

Controls:

1. Account velocity limits by event.
2. Device graph cluster limits.
3. Payment instrument limits.
4. Household or billing-address limits where legally allowed.
5. Event-scoped purchase caps.
6. Risk-based challenge before queue admission.
7. Token binding and nonce replay defense.
8. Transfer velocity limits.
9. Admin dual control.
10. Partner quotas and signed requests.
11. Scanner device revocation.
12. Barcode rotation.
13. Post-sale resale analysis.
14. False-positive review process.
15. Privacy review for signals.

### Principal stretch - compound incidents

Compound incident A:

1. Bot traffic enters queue at normal per-IP rates.
2. Hold p99 climbs from 180 ms to 1.8 sec.
3. PSP auth p95 climbs to 12 sec.
4. Active holds consume 80% of seats.
5. Seat map shows stale availability.
6. Fans complain "seats disappear at payment".
7. Bad fix: disable hold TTL to give users more time.
8. Safer fix: pause admission, preserve active holds, extend only payment-submitted holds, throttle high-risk cohorts.

Compound incident B:

1. Admin late price change increments price_version.
2. Seat-map projection lags.
3. Checkout shows old fees for some users.
4. PSP auth uses old amount.
5. Order service rejects commit due to price mismatch.
6. Holds expire and fans lose seats.
7. Bad fix: force commit at old amount without approval.
8. Safer fix: pause sale, honor legally required displayed prices if policy says so, reconcile affected holds.

Compound incident C:

1. Home region loses database primary.
2. Queue still admits users through CDN.
3. Backup region has stale inventory replica.
4. Payments are still authorizing.
5. Bad fix: open writes in backup without fencing old region.
6. Safer fix: pause admission, seal old epoch, fail over event route, reject old tokens, reconcile unknown auths.

---

## Decision Frameworks

### Staff - fairness vs bot controls

Prefer invisible controls when:

1. Signals are high-confidence.
2. False positive cost is low.
3. Attack is known and automated.
4. Control can be audited.
5. Privacy review approves use.

Prefer explicit friction when:

1. Risk is moderate and recoverable.
2. User can reasonably prove humanness or account ownership.
3. Accessibility alternative exists.
4. Friction happens before scarce hold attempt.
5. Product accepts conversion cost.

Prefer hard block when:

1. Evidence shows confirmed abuse.
2. Token replay or signature failure occurs.
3. Payment fraud is active.
4. Admin role is invalid.
5. Device or partner credential is revoked.

Do not:

1. Conflate VPN use with bot use.
2. Punish all users from a region for one proxy network without review.
3. Store raw fingerprint data longer than necessary.
4. Make bot score the only reason a user loses held seats without appeal path.
5. Introduce friction after payment submission unless fraud risk is extreme.

### Principal stretch - when to pause a sale

Pause admission when:

1. Hold p99 burns SLO and queue can absorb waiting.
2. Payment p95 exceeds hold TTL budget.
3. Bot confidence is rising but not yet isolated.
4. Seat-map projection lag creates user confusion but holds are safe.
5. Active holds approach inventory capacity.

Pause hold creation when:

1. Oversell risk is ambiguous.
2. Inventory command store loses quorum.
3. Admin mutation corrupted event allocation.
4. Region failover requires fencing.
5. Conditional write errors are inconsistent with load.

Pause payment submission when:

1. PSP idempotency is unavailable.
2. Auth success cannot be reconciled.
3. Currency/price mismatch is widespread.
4. Capture queue is replaying without dedupe.
5. Fraud attack targets payment endpoint.

Cancel or postpone sale when:

1. No-oversell evidence cannot be reconstructed.
2. Legal/fairness commitments were violated.
3. Queue randomization was biased in material way.
4. Payment charges occurred without ticket entitlement.
5. Executive incident team accepts customer remediation cost.

---

## Ops Sim / Interview Drill

**Time box:** 45 minutes

**Severity:** P0 for hot event checkout integrity

**Service / domain:** Ticketing, holds, waiting room, payments, abuse

**Northstar system:** Week-04 Flash-Sale Cascade, Week-08 Slow-Burn Checkout

### Rules

1. Answer from memory of the teaching section.
2. Do not open `answers/` until finished.
3. Write decisions in order: T+0, T+5, T+15, T+60.
4. Name evidence for every claim.
5. Preserve the no-oversell invariant above conversion.
6. Separate symptoms, amplifiers, and root cause.
7. Reject at least two bad fixes explicitly.

### 1. Scenario stem

```text
WHAT USERS SEE:
  10:00:00 general onsale opens for EVENT#E-TITAN-STADIUM.
  5.2M users are in the waiting room.
  Some admitted users hold four floor seats, submit payment, then see:
    "We could not complete your order. Your seats may still be held."
  Other users see seats flicker from available to unavailable to available.
  Social media says bots are getting all floor seats.

WHAT ON-CALL SEES:
  hold_api_p99_ms{event="E-TITAN-STADIUM"} = 180 -> 2100 in 4 minutes
  hold_conditional_conflict_rate = 34%
  hold_unknown_status_rate = 6.8%
  active_held_seats = 61,000 of 70,000 public seats
  sold_seats = 9,400
  queue_admission_rate = 180,000 users/min
  psp_auth_p95_ms = 11,800
  psp_auth_timeout_rate = 9.1%
  bot_risk_high_share_of_hold_attempts = 41%
  seat_map_projection_lag_seconds = 52
  support tickets: "charged but no tickets" = 620 in 10 minutes

BUSINESS CONSTRAINT:
  Artist contract requires max 4 tickets/account and no bot bypass.
  Finance requires no capture unless order + inventory commit are durable.
  Promoter wants sale to continue if no oversell risk exists.
```

### 2. Telemetry pack

```text
METRICS:
  waiting_room_entries_total = 5,200,000
  admitted_users_total = 720,000
  admitted_users_active = 410,000
  queue_token_replay_reject_rate = 0.4%
  queue_token_reuse_success_rate = 2.7%
  hold_attempts_per_sec = 13,500
  hold_capacity_planned_per_sec = 8,000
  seats_per_hold_avg = 3.4
  conditional_write_throttles_per_sec{section="FLOOR"} = 4,200
  conditional_write_throttles_per_sec{section="UPPER"} = 120
  floor_section_attempt_share = 63%
  hold_reaper_lag_seconds = 310
  expired_holds_still_counted = 12,400
  commit_after_expiry_reject_rate = 3.1%
  payment_attempts_in_unknown = 8,900
  capture_without_order_count = 0
  duplicate_capture_rejected_by_idempotency = 212
  order_inventory_mismatch_count = 0
  seat_oversell_detected_count = 0

LOG LINES:
  10:02:13 queue-admit policy=event_hot admission_rate=180000/min reason=manual_override
  10:03:02 hold error event=E-TITAN-STADIUM section=FLOOR code=THROTTLED shard=FLOOR-07
  10:03:47 payment auth timeout psp=stripe merchant_ref=pa_778 status=UNKNOWN
  10:04:11 hold retry idempotency_key=missing user=U918 device=D441 seats=F7,F8,F9,F10
  10:04:38 queue token accepted token_id=Q55 previous_use=true event=E-TITAN-STADIUM
  10:05:02 reaper skipped hold=H332 reason=psp_unknown_grace expires_at=10:04:10
  10:06:45 bot risk cluster=R-77 accounts=28000 avg_think_ms=210 hold_success=18%
  10:07:19 support case payment_auth_seen=true order_id=null hold_state=HELD
```

### 3. Config pack

```text
event_id: E-TITAN-STADIUM
hold_ttl_seconds: 600
payment_submit_grace_seconds: 90
max_tickets_per_account: 4
queue_admission_rate_per_minute: 180000
queue_token_max_hold_attempts: 25
queue_token_reuse_policy: allow_within_ttl
hold_attempt_cost_tokens: 1
browse_cost_tokens: 1
floor_section_shards: 8
planned_floor_section_shards: 32
psp_auth_timeout_ms: 5000
psp_retry_policy: retry_timeout_immediately
bot_high_risk_action: challenge_after_hold_failure
```

### 4. Timeline & decision points

| Time | Event | Your move |
|------|-------|-----------|
| T+0 | Pager fires for hot event checkout errors. | Identify integrity status, stop unsafe amplification, and assign roles. |
| T+5 | Queue override and token reuse anomaly are confirmed. | Decide queue/hold/payment mitigation sequence. |
| T+15 | PSP says auth latency will remain high for 30 minutes. | Decide whether to extend holds, pause sale, or continue degraded. |
| T+60 | Event is mostly sold or paused; support has thousands of cases. | Define reconciliation and durable fixes. |

### 5. Questions

**Q1 - Root cause and layer split**

1. Which symptom is the primary integrity risk?
2. Which symptom is a capacity amplifier?
3. Which symptom is a fairness/abuse signal?
4. Which symptom is only a read-model UX problem?
5. What is the most likely causal chain from config to user-visible failure?

**Q2 - Evidence**

1. Which three metrics prove the queue is over-admitting?
2. Which two metrics prove no oversell has happened yet?
3. Which signal shows the floor section is the hot shard?
4. Which log line proves idempotency discipline is weak?
5. Which config values are wrong or dangerous?

**Q3 - T+0 to T+5 mitigation**

1. What do you do first to preserve no oversell?
2. Do you pause queue admission, hold creation, payment submission, or all three?
3. What role do you assign to payments?
4. What role do you assign to abuse/fraud?
5. What do you tell support by T+5?

**Q4 - T+15 mitigation**

1. PSP latency remains high; what hold policy do you change?
2. Which users, if any, receive hold extension?
3. How do you prevent bots from consuming the extension?
4. How do you message users with UNKNOWN auth?
5. What do you avoid doing even under promoter pressure?

**Q5 - Bad fix gallery**

1. Why is `hold_ttl_seconds: 3600` globally dangerous?
2. Why is disabling the waiting room dangerous?
3. Why is "capture all successful PSP auths now" dangerous?
4. Why is flushing every seat-map cache incomplete?
5. Why is raising floor shards during the incident non-trivial?

**Q6 - Capacity math**

1. At 13,500 hold attempts/sec and 3.4 seats/hold, how many seat conditional writes/sec are attempted?
2. If floor receives 63% of attempts and has 8 shards, what is attempted writes/sec per floor shard?
3. If planned capacity was 8,000 attempts/sec, how much is current demand over plan?
4. If 61,000 seats are held and 9,400 sold out of 70,000, what does the queue need to know?
5. How many active holds are likely expired or blocked by reaper lag?

**Q7 - Abuse and fairness**

1. How do you distinguish bot clusters from organic fans using given evidence?
2. Which controls should move before hold attempt?
3. Which limits should be event-scoped?
4. How do you avoid punishing legitimate high-latency users?
5. How do you audit fairness after the sale?

**Q8 - Durable design fixes**

1. Name five config changes before the next celebrity onsale.
2. Name three architecture changes to event cells or sharding.
3. Name three payment-orchestration changes.
4. Name three abuse-control changes tied to Week-08c lessons.
5. Name the acceptance criteria for declaring the design safe.

**Q9 - Org and runbook**

1. Who is incident commander by T+0?
2. Who owns payment reconciliation?
3. Who owns public status messaging?
4. What is pre-authorized for the on-call?
5. What requires executive or promoter approval?

### 6. Self-score after answer key

| Error type | Did it happen? | Note |
|------------|----------------|------|
| Treated seat map as authoritative | | |
| Captured payment before durable order | | |
| Ignored queue admission math | | |
| Missed bot vs organic distinction | | |
| Proposed global hold extension | | |
| Forgot support/comms | | |

**Pass:** correct integrity boundary, safe first 15 minutes, one capacity check, and rejection of bad fixes.

---

## Takeaways + Reading

### Key takeaways

1. Seat maps are projections; holds are authority.
2. Oversell prevention belongs in conditional inventory state transitions or serial command processing.
3. Waiting rooms must be tied to backend health and fairness policy.
4. TTL cleanup is not the source of truth; expires_at is.
5. Payment authorization, inventory commit, order creation, and capture need idempotent orchestration.
6. Bot defense is multidimensional and event-scoped; Week-08c IP-only limits are insufficient.
7. Event cells make blast radius, cost, capacity, and runbooks concrete.

### Targeted reading

1. `Week-11-Commerce-and-Payments-Designs/Design Payment System.md`
2. `Week-11-Commerce-and-Payments-Designs/Design E-Commerce Platform.md`
3. `Retention-Tests/Week-08c.md` for abuse and hardening prompts.
4. `Ops-Sims/Week-04-Northstar-Flash-Sale-Cascade.md`
5. `Ops-Sims/Week-08-Northstar-Slow-Burn-Checkout.md`
6. `templates/DESIGN_MODULE_GATES.md`
7. `templates/OPS_SIM_TEMPLATE.md`
