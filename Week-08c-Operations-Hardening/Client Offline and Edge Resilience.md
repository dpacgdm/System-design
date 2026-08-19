# Client Offline and Edge Resilience

Northstar Commerce now has enough moving parts that the
hard problems are not only algorithmic. Checkout,
inventory, seller analytics, auth, rate limits, feature
flags, CloudFront, MSK, Debezium CDC, PostgreSQL, Redis,
mobile clients, and support tools all preserve different
invariants. Operations hardening is the practice of making
changes, tests, defenses, and clients safe when those
invariants meet real traffic.

This Week 08c module sits between the mechanism weeks and
the large design weeks. It assumes the learner remembers
DNS, HTTP, caches, replication, queues, outbox, feature
flags, observability, SLOs, rate limits, auth, cost, and
tenancy. The goal is to force those pieces into rollout
and incident decisions instead of isolated flash cards.

Clients are distributed systems. Mobile apps go offline,
retry across radio changes, keep stale feature flags,
cache API responses, migrate QUIC connections, reconnect
WebSockets, and sync writes long after the server-side
deploy finished. Edge caches and clients can protect the
origin, but they can also preserve bad state after the
backend is fixed.

Northstar cares because buyers bid during flaky subway
rides, sellers scan inventory from warehouses, and mobile
checkout must never turn a retry into a duplicate payment.
Client resilience is not making every operation work
offline. It is classifying which operations can queue,
which must revalidate, which can be stale, and which must
fail closed.

## Learning objectives

### Foundation

> Staff is the mastery gate; Principal stretch is optional depth.


1. Classify client operations into read-only cacheable,
   offline queueable, requires revalidation, and online-
   only safety-critical paths.
2. Design mobile offline queues with durable local
   records, operation IDs, dependency ordering, retry
   budgets, and user-visible state.
3. Use idempotent sync protocols that survive retries, app
   restarts, duplicate delivery, and server partial
   success.
4. Choose conflict-resolution UX for carts, inventory
   edits, seller drafts, profile settings, and money-
   moving actions.
5. Diagnose flaky-network failures across DNS, TCP, TLS,
   HTTP/2, HTTP/3/QUIC, connection migration, and captive
   portals.
6. Apply stale-while-revalidate on clients and edges while
   preserving authorization, tenant, price, and freshness
   invariants.
7. Plan mobile feature-flag, config, and cache TTLs so
   rollback works when clients are offline.
8. Control reconnect storms for WebSockets, push
   notifications, and background sync using jitter,
   admission, and server backpressure.
9. Instrument client-side golden signals without leaking
   secrets or exploding telemetry volume.
10. Tie client resilience to Northstar checkout, live
    auctions, seller analytics, auth sessions, rate
    limits, and abuse controls.

## Wrong mental models

| Wrong model | Correction | Why it hurts |
| --- | --- | --- |
| Offline mode means everything works offline | Only operations with safe local intent and later reconciliation should queue. | Offline checkout can create duplicate or invalid payment effects. |
| Retry fixes flaky networks | Retry without idempotency, budgets, and jitter creates duplicates and storms. | One subway tunnel becomes payment fanout. |
| Last write wins is good enough | Many conflicts need domain-aware merge or user choice. | A seller inventory decrement is overwritten by a stale edit. |
| Client cache is harmless because server is source of truth | Client cache shapes user decisions and can preserve stale auth, price, or flags. | Users buy at a price the server will reject. |
| QUIC removes network problems | QUIC helps connection migration but cannot fix captive portals, server state, or bad retry logic. | Teams ignore app-level idempotency. |
| Edge stale-while-revalidate is only a CDN concern | Mobile and service-worker caches also serve stale state and need validation rules. | Private data or stale risk decisions leak. |
| Conflict resolution belongs only on the server | The user experience must expose unresolved conflicts and safe choices. | Silent merges destroy user trust. |
| Push means instant invalidation | Push can be delayed, dropped, denied, or throttled. | Clients keep stale catalog or flag state. |
| Mobile telemetry can be sampled like backend telemetry | Client telemetry is bursty, delayed, privacy-sensitive, and version-fragmented. | The incident lacks old-app evidence. |
| Rollback ends when backend flag flips | Offline clients and edge caches may keep old code/config for hours or days. | The bad path survives long after rollback. |

## Core mechanism

### 1. Operation classification

The first design move is deciding what a client may do
without a fresh server decision. Browsing cached product
descriptions is different from authorizing payment. A
seller draft can queue; a live auction bid may queue only
with strict expiration or not at all.

- Name the invariant before enabling offline.
- Separate local drafts from committed server state.
- Require fresh server validation for money, inventory,
  and auth.
- Expose queued/pending state to the user.
- Expire intents that become unsafe with time.

| Lens | Question to ask | Northstar example |
| --- | --- | --- |
| Invariant | What must stay true while operation classification changes? | Checkout money effects, tenant isolation, or seller trust. |
| Authority | Which system is source of truth while operation classification is active? | Name the Northstar owner for Operation classification: API, data platform, mobile, edge, fraud, or payments. |
| Time | Which time window controls operation classification risk? | Use the relevant TTL, retry budget, lag, offset, stale age, or rollout window for Operation classification. |
| Blast radius | Which slice sees operation classification first? | Compare cell, tenant tier, region, route, app version, and dependency for Operation classification. |
| Rollback | What rollback edge remains open for operation classification, and when does it close? | Name the old path, old data shape, old client, old control-plane value, or evidence store tied to Operation classification. |

### 2. Offline queue design

An offline queue stores user intent durably with operation
ID, tenant, auth/session snapshot, dependencies, created
time, expiry, and retry policy. It is not a hidden pile of
HTTP requests. The sync engine must understand ordering
and cancellation.

- Persist before acknowledging local pending state.
- Use stable client_operation_id across app restarts.
- Record dependency graph between operations.
- Let users cancel pending non-critical work.
- Encrypt sensitive local queue content.

| Lens | Question to ask | Northstar example |
| --- | --- | --- |
| Invariant | What must stay true while offline queue design changes? | Checkout money effects, tenant isolation, or seller trust. |
| Authority | Which system is source of truth while offline queue design is active? | Name the Northstar owner for Offline queue design: API, data platform, mobile, edge, fraud, or payments. |
| Time | Which time window controls offline queue design risk? | Use the relevant TTL, retry budget, lag, offset, stale age, or rollout window for Offline queue design. |
| Blast radius | Which slice sees offline queue design first? | Compare cell, tenant tier, region, route, app version, and dependency for Offline queue design. |
| Rollback | What rollback edge remains open for offline queue design, and when does it close? | Name the old path, old data shape, old client, old control-plane value, or evidence store tied to Offline queue design. |

### 3. Idempotent sync

Idempotency lets clients retry without creating duplicate
server effects. The server stores operation IDs and
returns the same result for duplicate attempts.
Idempotency scope must include tenant, actor, operation
kind, and enough payload hash to reject accidental key
reuse.

- Client generates stable IDs for user intents.
- Server records first result atomically with effect.
- Duplicate with same payload returns prior result.
- Duplicate with different payload is a conflict.
- TTL matches maximum retry/offline window.

| Lens | Question to ask | Northstar example |
| --- | --- | --- |
| Invariant | What must stay true while idempotent sync changes? | Checkout money effects, tenant isolation, or seller trust. |
| Authority | Which system is source of truth while idempotent sync is active? | Name the Northstar owner for Idempotent sync: API, data platform, mobile, edge, fraud, or payments. |
| Time | Which time window controls idempotent sync risk? | Use the relevant TTL, retry budget, lag, offset, stale age, or rollout window for Idempotent sync. |
| Blast radius | Which slice sees idempotent sync first? | Compare cell, tenant tier, region, route, app version, and dependency for Idempotent sync. |
| Rollback | What rollback edge remains open for idempotent sync, and when does it close? | Name the old path, old data shape, old client, old control-plane value, or evidence store tied to Idempotent sync. |

### 4. Conflict UX

Conflict resolution is a product decision backed by data
semantics. Carts can merge quantities with checkout
revalidation. Seller inventory edits may require field-
level compare and user choice. Profile text can often use
last-writer with version warning. Payment cannot be
merged.

- Show server version and local intent when needed.
- Avoid silent destructive overwrites.
- Use domain-specific merges only when safe.
- Keep audit trail for seller/admin conflicts.
- Teach support what pending and conflicted mean.

| Lens | Question to ask | Northstar example |
| --- | --- | --- |
| Invariant | What must stay true while conflict ux changes? | Checkout money effects, tenant isolation, or seller trust. |
| Authority | Which system is source of truth while conflict ux is active? | Name the Northstar owner for Conflict UX: API, data platform, mobile, edge, fraud, or payments. |
| Time | Which time window controls conflict ux risk? | Use the relevant TTL, retry budget, lag, offset, stale age, or rollout window for Conflict UX. |
| Blast radius | Which slice sees conflict ux first? | Compare cell, tenant tier, region, route, app version, and dependency for Conflict UX. |
| Rollback | What rollback edge remains open for conflict ux, and when does it close? | Name the old path, old data shape, old client, old control-plane value, or evidence store tied to Conflict UX. |

### 5. Flaky network mechanics

Mobile networks create DNS failures, TCP resets, TLS
handshakes, NAT rebinding, radio sleep, captive portals,
and path changes. HTTP/3 over QUIC can migrate connections
across network changes, a callback to Week 1 transport,
but application state still needs replay-safe semantics.

- Use timeouts appropriate to radio behavior.
- Reuse connections but recover from path migration.
- Detect captive portal and auth redirects.
- Apply exponential backoff with jitter.
- Do not retry unsafe methods without idempotency.

| Lens | Question to ask | Northstar example |
| --- | --- | --- |
| Invariant | What must stay true while flaky network mechanics changes? | Checkout money effects, tenant isolation, or seller trust. |
| Authority | Which system is source of truth while flaky network mechanics is active? | Name the Northstar owner for Flaky network mechanics: API, data platform, mobile, edge, fraud, or payments. |
| Time | Which time window controls flaky network mechanics risk? | Use the relevant TTL, retry budget, lag, offset, stale age, or rollout window for Flaky network mechanics. |
| Blast radius | Which slice sees flaky network mechanics first? | Compare cell, tenant tier, region, route, app version, and dependency for Flaky network mechanics. |
| Rollback | What rollback edge remains open for flaky network mechanics, and when does it close? | Name the old path, old data shape, old client, old control-plane value, or evidence store tied to Flaky network mechanics. |

### 6. Client stale-while-revalidate

Stale-while-revalidate can make apps feel fast: show
cached data, fetch fresh data in background, then update.
It is safe for catalog descriptions with freshness labels;
risky for price, inventory, auth, fraud, and tenant-
specific data unless validators and max staleness are
strict.

- Tag cache entries by user, tenant, currency, and auth
  class.
- Attach freshness age to UI decisions.
- Block checkout on stale price/inventory.
- Use ETag or version validators.
- Purge or version caches after security changes.

| Lens | Question to ask | Northstar example |
| --- | --- | --- |
| Invariant | What must stay true while client stale-while-revalidate changes? | Checkout money effects, tenant isolation, or seller trust. |
| Authority | Which system is source of truth while client stale-while-revalidate is active? | Name the Northstar owner for Client stale-while-revalidate: API, data platform, mobile, edge, fraud, or payments. |
| Time | Which time window controls client stale-while-revalidate risk? | Use the relevant TTL, retry budget, lag, offset, stale age, or rollout window for Client stale-while-revalidate. |
| Blast radius | Which slice sees client stale-while-revalidate first? | Compare cell, tenant tier, region, route, app version, and dependency for Client stale-while-revalidate. |
| Rollback | What rollback edge remains open for client stale-while-revalidate, and when does it close? | Name the old path, old data shape, old client, old control-plane value, or evidence store tied to Client stale-while-revalidate. |

### 7. Edge resilience

CloudFront and service workers can absorb origin issues.
They must not cache personalized data as public, preserve
stale errors too long, or ignore auth/tenant variants.
Edge fallback should know what may be stale and what must
fail closed.

- Default private/no-store for authenticated responses.
- Allow stale public catalog within named max age.
- Do not stale risk or authorization decisions.
- Use origin shield and request coalescing.
- Measure stale-served ratio by route.

| Lens | Question to ask | Northstar example |
| --- | --- | --- |
| Invariant | What must stay true while edge resilience changes? | Checkout money effects, tenant isolation, or seller trust. |
| Authority | Which system is source of truth while edge resilience is active? | Name the Northstar owner for Edge resilience: API, data platform, mobile, edge, fraud, or payments. |
| Time | Which time window controls edge resilience risk? | Use the relevant TTL, retry budget, lag, offset, stale age, or rollout window for Edge resilience. |
| Blast radius | Which slice sees edge resilience first? | Compare cell, tenant tier, region, route, app version, and dependency for Edge resilience. |
| Rollback | What rollback edge remains open for edge resilience, and when does it close? | Name the old path, old data shape, old client, old control-plane value, or evidence store tied to Edge resilience. |

### 8. Reconnect storms

When a gateway deploy or network outage drops clients,
synchronized reconnects can become the real incident.
Clients need backoff with jitter, server-advertised retry-
after, token refresh staggering, and admission control.
Servers need connection draining and capacity-aware
accepts.

- Persist random client jitter seed.
- Honor retry-after and push backpressure.
- Avoid fixed 1s reconnect loops.
- Separate auth refresh from socket reconnect.
- Watch reconnect attempts per active client.

| Lens | Question to ask | Northstar example |
| --- | --- | --- |
| Invariant | What must stay true while reconnect storms changes? | Checkout money effects, tenant isolation, or seller trust. |
| Authority | Which system is source of truth while reconnect storms is active? | Name the Northstar owner for Reconnect storms: API, data platform, mobile, edge, fraud, or payments. |
| Time | Which time window controls reconnect storms risk? | Use the relevant TTL, retry budget, lag, offset, stale age, or rollout window for Reconnect storms. |
| Blast radius | Which slice sees reconnect storms first? | Compare cell, tenant tier, region, route, app version, and dependency for Reconnect storms. |
| Rollback | What rollback edge remains open for reconnect storms, and when does it close? | Name the old path, old data shape, old client, old control-plane value, or evidence store tied to Reconnect storms. |

### 9. Mobile flags and rollback

Mobile clients cache config because they must work under
poor networks. That cache makes rollback hard. Critical
flags need short TTL, safe defaults, server override on
API response, minimum app version gates, and kill switches
that work despite stale local state.

- Missing context fails safe.
- Include config version in telemetry.
- Bundle emergency deny/disable paths in app.
- Avoid long TTL for money or auth behavior.
- Plan sunset for old app versions.

| Lens | Question to ask | Northstar example |
| --- | --- | --- |
| Invariant | What must stay true while mobile flags and rollback changes? | Checkout money effects, tenant isolation, or seller trust. |
| Authority | Which system is source of truth while mobile flags and rollback is active? | Name the Northstar owner for Mobile flags and rollback: API, data platform, mobile, edge, fraud, or payments. |
| Time | Which time window controls mobile flags and rollback risk? | Use the relevant TTL, retry budget, lag, offset, stale age, or rollout window for Mobile flags and rollback. |
| Blast radius | Which slice sees mobile flags and rollback first? | Compare cell, tenant tier, region, route, app version, and dependency for Mobile flags and rollback. |
| Rollback | What rollback edge remains open for mobile flags and rollback, and when does it close? | Name the old path, old data shape, old client, old control-plane value, or evidence store tied to Mobile flags and rollback. |

### 10. Client telemetry

Client telemetry arrives late, batched, sampled, and
fragmented by app version, OS, network, and region. It
must be designed before incidents. Useful signals include
queue depth, pending age, retry attempts, conflict rate,
stale cache age, network transition, and local error
reason.

- Bound cardinality and avoid raw identifiers.
- Keep old app versions visible during incidents.
- Correlate client operation ID with server trace.
- Upload telemetry only with privacy controls.
- Distinguish local fail, network fail, server reject, and
  conflict.

| Lens | Question to ask | Northstar example |
| --- | --- | --- |
| Invariant | What must stay true while client telemetry changes? | Checkout money effects, tenant isolation, or seller trust. |
| Authority | Which system is source of truth while client telemetry is active? | Name the Northstar owner for Client telemetry: API, data platform, mobile, edge, fraud, or payments. |
| Time | Which time window controls client telemetry risk? | Use the relevant TTL, retry budget, lag, offset, stale age, or rollout window for this mechanism. |
| Blast radius | Which slice sees client telemetry first? | Compare cell, tenant tier, region, route, app version, and dependency before trusting fleet averages. |
| Rollback | What rollback edge remains open for client telemetry, and when does it close? | Name the old path, old data shape, old client, old control-plane value, or evidence store tied to Client telemetry. |

## Production anatomy

Production anatomy is the concrete evidence a staff
engineer expects on the bridge: metrics with dimensions,
logs with reason codes, config that shows the dangerous
default, and runbook decisions tied to thresholds. A
design that cannot say what it will measure is not ready
for Northstar traffic.

### Telemetry pack

| Signal | Useful dimensions | Why it matters |
| --- | --- | --- |
| offline_queue_depth | app_version, operation_class | Pending local work pressure. |
| offline_queue_oldest_age_seconds | operation_class | Risk of stale intents. |
| sync_duplicate_operation_total | operation_class, result | Idempotency behavior. |
| sync_conflict_total | entity_type, resolution | Conflict UX and data drift. |
| client_retry_attempts | route, network_type | Retry storm evidence. |
| client_network_transition_total | from, to, protocol | Wi-Fi/cellular/QUIC migration signal. |
| quic_connection_migration_success_ratio | app_version, region | Transport resilience callback to W1. |
| stale_cache_served_ratio | route, max_age_bucket | SWR safety. |
| stale_checkout_block_total | reason | Freshness guard for money/inventory. |
| websocket_reconnect_attempts | app_version, gateway_cell | Reconnect storm signal. |
| push_invalidation_delay_seconds | platform, region | Invalidation is not instant. |
| mobile_flag_version | flag, app_version | Rollback observability. |
| client_auth_refresh_failure_total | reason, app_version | Session/JWKS/client clock issues. |
| local_storage_crypto_error_total | platform | Offline queue security signal. |
| client_telemetry_upload_lag_seconds | app_version | Know evidence freshness. |

### Config pack

#### Offline operation policy

```text
operation: seller_inventory_adjustment
queueable_offline: true
requires_fresh_auth_on_sync: true
client_operation_id: required
idempotency_scope: tenant_id + actor_id + operation_kind + client_operation_id
expires_after: 24h
conflict_policy: compare_version_then_user_choice
local_storage: encrypted
user_visible_state: pending_sync
```

#### Dangerous mobile retry

```text
operation: checkout_payment_submit
queueable_offline: true
retry:
  max_attempts: unlimited
  interval_seconds: 1
idempotency_key: generated_per_http_attempt
stale_price_allowed_minutes: 60
user_message: order placed
```

#### Client SWR policy

```text
route: GET /catalog/product
serve_stale_while_revalidate: true
max_stale_seconds: 300
cache_key: tenant_id + viewer_class + product_id + currency + price_list_version
block_checkout_if:
  price_age_seconds: "> 30"
  inventory_age_seconds: "> 10"
  auth_state: stale
revalidate_with: ETag
```

### Runbook anatomy

- Declare the protected invariant before naming the fix;
  this prevents fast actions that make the system less
  safe.
- Slice the symptom by cell, tenant tier, region, client
  version, route, and dependency before trusting a global
  graph.
- Identify the current authority for reads, writes, risk
  decisions, and customer communications.
- Name the pre-authorized mitigations and the actions that
  require security, finance, product, or executive
  approval.
- Write down the bad fixes the bridge is likely to propose
  so they can be rejected quickly and calmly.
- Keep a decision log with metric values before and after
  each mitigation; rollback without evidence is guessing.
- Assign one owner for customer/support language and one
  owner for evidence preservation.
- Set a timer to revisit temporary rules, flags,
  throttles, or queues so the incident fix does not become
  permanent architecture.

### Production review questions

1. What is the smallest blast radius that still gives
   meaningful evidence?
2. Which metric would change first if the suspected
   mechanism is true?
3. Which metric would stay green and mislead executives?
4. What scarce resource is consumed by the mitigation
   itself?
5. Which clients, jobs, or partners may continue old
   behavior after rollback?
6. What data must be preserved before cleanup or
   mitigation destroys it?
7. Which tenant or customer slice has a stricter contract
   than the fleet?
8. How will support distinguish pending, failed, rejected,
   and repaired customer states?
9. What is the maximum safe duration for any temporary
   degradation?
10. Who owns the follow-up test that prevents recurrence?

### Staff

## Failure catalog

| Failure | Trigger | Amplifier | Blast radius |
| --- | --- | --- | --- |
| Duplicate payment | Offline queue retries unsafe checkout | New idempotency key each attempt | PSP duplicate risk |
| Stale price | Client serves cached sale price | Checkout trusts client price | Revenue/customer dispute |
| Inventory overwrite | Last-write wins seller edit | Offline stale version syncs later | Stock corruption |
| Reconnect storm | Gateway deploy drops sockets | Fixed retry loop | Auth and gateway overload |
| Flag rollback miss | Mobile caches bad flag 24h | Backend rollback incomplete | Bad path persists |
| Auth stale allow | Client uses expired token offline | Server fallback too permissive | Unauthorized action |
| SWR private leak | Service worker shares tenant response | Cache key missing tenant | Cross-tenant exposure |
| Edge stale error | CDN caches 500 with long TTL | Origin recovers but edge serves failure | False outage |
| Captive portal confusion | HTML login page parsed as API success | Client stores bad state | Sync failures |
| QUIC optimism | Connection migrates but app request timed out | Client replays unsafe method | Duplicate effect |
| Push invalidation lost | Device denies notifications | Cache never purged | Stale catalog |
| Telemetry blind spot | Old app version not tagged | Incident only affects legacy app | Root cause delayed |
| Queue privacy leak | Sensitive payload stored plaintext | Lost device exposes data | Security incident |
| Conflict hidden | Server auto-merges destructive change | User cannot repair | Support escalation |
| Retry budget absent | Radio flaps all morning | Client drains battery and backend | User churn and overload |

Failure catalogs are not lists of scary nouns. Each row
should teach the incident shape: the trigger starts the
problem, the amplifier turns it into a distributed
failure, and the blast radius says who or what is harmed.
During a design review, pick the three rows most likely
for the proposed change and prove the telemetry and
rollback exist.

### Failure drill prompts

- For Duplicate payment, what single metric would page
  before the customer-visible psp duplicate risk?
- What mitigation reduces new idempotency key each attempt
  without hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Stale price, what single metric would page before
  the customer-visible revenue/customer dispute?
- What mitigation reduces checkout trusts client price
  without hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Inventory overwrite, what single metric would page
  before the customer-visible stock corruption?
- What mitigation reduces offline stale version syncs
  later without hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Reconnect storm, what single metric would page
  before the customer-visible auth and gateway overload?
- What mitigation reduces fixed retry loop without hiding
  the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Flag rollback miss, what single metric would page
  before the customer-visible bad path persists?
- What mitigation reduces backend rollback incomplete
  without hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Auth stale allow, what single metric would page
  before the customer-visible unauthorized action?
- What mitigation reduces server fallback too permissive
  without hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For SWR private leak, what single metric would page
  before the customer-visible cross-tenant exposure?
- What mitigation reduces cache key missing tenant without
  hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Edge stale error, what single metric would page
  before the customer-visible false outage?
- What mitigation reduces origin recovers but edge serves
  failure without hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Captive portal confusion, what single metric would
  page before the customer-visible sync failures?
- What mitigation reduces client stores bad state without
  hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For QUIC optimism, what single metric would page before
  the customer-visible duplicate effect?
- What mitigation reduces client replays unsafe method
  without hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Push invalidation lost, what single metric would
  page before the customer-visible stale catalog?
- What mitigation reduces cache never purged without
  hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Telemetry blind spot, what single metric would page
  before the customer-visible root cause delayed?
- What mitigation reduces incident only affects legacy app
  without hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Queue privacy leak, what single metric would page
  before the customer-visible security incident?
- What mitigation reduces lost device exposes data without
  hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Conflict hidden, what single metric would page
  before the customer-visible support escalation?
- What mitigation reduces user cannot repair without
  hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Retry budget absent, what single metric would page
  before the customer-visible user churn and overload?
- What mitigation reduces client drains battery and
  backend without hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

## Decision framework

Good operational decisions are conditional. They do not
say always use one pattern or never use another. They name
the invariant, workload shape, rollback cost, evidence
quality, and human ownership. Use this table as a forcing
function before launch and during incidents.

| Option | Use when | Caution |
| --- | --- | --- |
| Public catalog read | SWR allowed with freshness label | Must revalidate before checkout |
| Personalized price | Short client cache with tenant/auth key | Block money decision if stale |
| Cart edit | Queueable with idempotent operation and merge rules | Checkout revalidates inventory/price |
| Payment submit | Online-only or durable idempotent pending state | Never generate new key per retry |
| Seller draft | Offline queueable | Conflict UX on sync |
| Inventory decrement | Queue only if business accepts conflict review | Needs version and server arbitration |
| Live auction bid | Usually online with server timestamp/sequence | Offline bid must expire quickly if allowed |
| Auth refresh | Retry with backoff and safe logout/reauth path | Do not fail open |
| Feature flag | Cache with short TTL for critical paths | Safe default and server override |
| Push invalidation | Helpful optimization | Not source of truth |

### Decision checklist

1. State the business invariant in one sentence. If the
   invariant is vague, stop and clarify.
2. Name the source of truth and the derived views. Never
   repair the source from an unverified projection.
3. Choose the rollout unit: request, tenant, seller tier,
   region, cell, app version, or control-plane version.
4. Define the abort condition before starting. Include
   correctness, latency, saturation, cost, security, and
   support signals.
5. Estimate cross-system capacity impact. A safe local fix
   can overload Kafka, Redis, Postgres, PSP, or support.
6. List data that becomes hard or impossible to recover
   after the next step.
7. Choose communication timing and audience based on
   affected slice, not global severity language.
8. Decide what can be automated and what must require
   human approval.
9. Set expiration for emergency mitigations and create a
   follow-up owner before leaving the bridge.
10. Write the acceptance test that would have caught the
    issue before launch.

### Northstar field practice cards

Use these cards as mini design-review prompts before the
Ops Sim. They are not answer keys; they force you to name
mechanism, evidence, invariant, and rollback before the
timed drill.

#### Card 01 - Offline cart edit

- **Setup:** Buyer adds items offline and syncs later.
- **Mechanism to name:** Queueable intent with checkout
                         revalidation.
- **Evidence to request:** Client operation ID, item
                           versions, price age, inventory
                           age, sync status.
- **Safe first move:** Sync cart as pending and revalidate
                       price/inventory before checkout.
- **Bad fix to reject:** Show order confirmed when local
                         queue accepts.
- **Durable gate:** Cart offline test covers stale price
                    and inventory conflict.

#### Card 02 - Payment retry

- **Setup:** Payment submit retries after radio switch
             with new key.
- **Mechanism to name:** Idempotent sync for money
                         effects.
- **Evidence to request:** Operation ID source, retry
                           count, PSP attempts, ledger
                           dedupe, network transition.
- **Safe first move:** Disable offline payment submit and
                       require stable operation ID.
- **Bad fix to reject:** Trust ledger duplicate count and
                         ignore PSP attempts.
- **Durable gate:** Duplicate external attempts must be
                    zero in replay.

#### Card 03 - QUIC migration

- **Setup:** Wi-Fi to cellular changes during checkout.
- **Mechanism to name:** Transport migration versus app-
                         level business retry.
- **Evidence to request:** QUIC migration success, app
                           timeout, request ID, server
                           commit status.
- **Safe first move:** Let QUIC reduce reconnect cost but
                       keep idempotency and timeout
                       budget.
- **Bad fix to reject:** Assume QUIC means retries are
                         safe.
- **Durable gate:** Network transition test with slow
                    success and stable operation ID.

#### Card 04 - Seller inventory conflict

- **Setup:** Warehouse app changes stock offline while web
             admin edits same SKU.
- **Mechanism to name:** Domain conflict UX and version
                         checks.
- **Evidence to request:** Client version, server version,
                           field diff, actor, conflict
                           resolution.
- **Safe first move:** Show conflict with choices or route
                       to review for dangerous decrements.
- **Bad fix to reject:** Last-write wins silently.
- **Durable gate:** Inventory sync contract defines merge
                    and conflict classes.

#### Card 05 - SWR stale price

- **Setup:** Client displays stale sale price then submits
             checkout.
- **Mechanism to name:** Display freshness versus decision
                         freshness.
- **Evidence to request:** Price age, ETag, cache key,
                           checkout stale block, user
                           message.
- **Safe first move:** Block checkout until fresh
                       price/inventory validation.
- **Bad fix to reject:** Let client price win because user
                         saw it.
- **Durable gate:** Checkout API rejects stale decision
                    inputs.

#### Card 06 - Service-worker leak

- **Setup:** Service worker serves cached tenant response
             to another account.
- **Mechanism to name:** Client cache partition by auth
                         and tenant.
- **Evidence to request:** Cache key, account switch
                           event, tenant ID, response
                           headers.
- **Safe first move:** Purge private cache on auth switch
                       and partition by viewer.
- **Bad fix to reject:** Tell users to clear browser
                         cache.
- **Durable gate:** Cache tests cover logout/login and
                    tenant switch.

#### Card 07 - Reconnect storm

- **Setup:** Gateway deploy drops sockets and clients
             reconnect every second.
- **Mechanism to name:** Backoff, jitter, admission, and
                         server retry-after.
- **Evidence to request:** Reconnect attempts per client,
                           auth refresh QPS, gateway
                           accept rate.
- **Safe first move:** Enable jittered backoff and staged
                       gateway admission.
- **Bad fix to reject:** Scale auth service only.
- **Durable gate:** Client reconnect contract honors
                    retry-after.

#### Card 08 - Flag stale rollback

- **Setup:** Bad offline flag remains true on old app for
             a day.
- **Mechanism to name:** Mobile config TTL and server
                         override.
- **Evidence to request:** Flag version, TTL age, app
                           version, server reject reason.
- **Safe first move:** Server-side deny risky operation
                       and shorten/override flag.
- **Bad fix to reject:** Wait for clients to fetch config
                         eventually.
- **Durable gate:** Critical flags have safe default false
                    and short TTL.

#### Card 09 - Push invalidation loss

- **Setup:** Some devices miss price invalidation push.
- **Mechanism to name:** Push as optimization, not
                         authority.
- **Evidence to request:** Push delivery delay, cache max
                           age, revalidation request,
                           stale served count.
- **Safe first move:** Use max-age/validators so missed
                       push still expires.
- **Bad fix to reject:** Depend on push to clear all bad
                         state.
- **Durable gate:** Cache policy test with dropped push.

#### Card 10 - Telemetry lag

- **Setup:** Mobile evidence arrives hours after incident.
- **Mechanism to name:** Delayed client telemetry and
                         version slicing.
- **Evidence to request:** Upload lag, app version, OS,
                           route, local error reason.
- **Safe first move:** Use server-side correlation IDs and
                       preserve delayed uploads.
- **Bad fix to reject:** Declare no client issue because
                         backend dashboards are green.
- **Durable gate:** Client telemetry SLO by app version
                    and network class.

#### Card 11 - Local queue privacy

- **Setup:** Offline queue stores address and token
             plaintext.
- **Mechanism to name:** Local data protection for queued
                         intents.
- **Evidence to request:** Storage encryption status,
                           token presence, device loss
                           policy.
- **Safe first move:** Encrypt payloads and avoid storing
                       bearer secrets.
- **Bad fix to reject:** Log the queue payload to debug
                         sync.
- **Durable gate:** Offline queue security review blocks
                    sensitive plaintext.

#### Card 12 - Captive portal

- **Setup:** API call receives hotel login HTML and parser
             treats it as success.
- **Mechanism to name:** Network classification and
                         response validation.
- **Evidence to request:** Content-Type, status, TLS/cert,
                           parser error, captive portal
                           detection.
- **Safe first move:** Reject invalid API response and
                       show network-auth state.
- **Bad fix to reject:** Cache the HTML as product
                         response.
- **Durable gate:** Client tests include captive portal
                    and proxy responses.

### Principal stretch

## Ops Sim

### Northstar Mobile Offline Queue Duplicates Checkout

**Time box:** 75 minutes  
**Severity:** P1  
**Service / domain:** Mobile offline sync, idempotency, QUIC/flaky networks, SWR  
**Northstar system:** shared commerce platform

#### Rules

1. Answer from memory of this module and earlier Northstar
   weeks; do not open the key mid-drill.
2. Write decisions in order from T+0 to T+60, including
   what you intentionally do not do.
3. Name evidence for every claim: metric, log line, trace
   field, config key, or customer slice.
4. Include at least one capacity or blast-radius
   calculation before proposing a repair.
5. Do not put worked answers in this learner file; open
   the answer key only after attempting.

#### Scenario stem

```text
WHAT USERS SEE:
  Some mobile buyers on trains see 'order pending' and later receive
  two payment authorization notifications. Sellers see inventory holds
  that appear, disappear, and reappear.

WHAT ON-CALL SEES:
  The new mobile offline queue launched to 20% of Android users. Backend
  checkout success is globally green, but duplicate payment attempts and
  inventory hold conflicts are concentrated on app version 2026.07.11.

BUSINESS CONSTRAINT:
  Product wants offline carts for conversion. Finance requires no
  duplicate PSP effects. Support needs a customer-safe explanation that
  does not promise orders succeeded before server confirmation.
```

#### Telemetry pack

```text
METRICS:
  offline_queue_depth_p95{app=2026.07.11}: 0 -> 18
  offline_queue_oldest_age_seconds_p99: 4200
  sync_duplicate_operation_total{operation=checkout_submit}: 812
  duplicate_psp_authorize_attempt_total: 143
  duplicate_business_effect_total{ledger}: 0
  client_retry_attempts_p99{network=cellular}: 19
  quic_connection_migration_success_ratio: 91%
  stale_cache_served_ratio{route=catalog/product}: 37%
  stale_checkout_block_total: 0
  websocket_reconnect_attempts{app=2026.07.11}: 9x baseline
  mobile_flag_version{offline_checkout_enabled}: stale on 62% of affected clients

LOG LINES:
  mobile-sync: generated idempotency key per HTTP retry
  checkout-api: accepted client price_age_seconds=1800
  pay-ledger: duplicate PSP key rejected, ledger op already pending
  inventory: hold conflict, client_version=418, server_version=421

TRACE NOTES:
  Wi-Fi to cellular transition occurs during payment submit
  QUIC connection migrates, app timeout fires, sync worker retries as new operation
  user-visible local state says order placed before server confirmation
```

#### Config pack

```yaml
# dangerous settings included
mobile_offline_queue:
  checkout_submit:
    queueable_offline: true
    idempotency_key: generated_per_attempt
    max_retry_attempts: unlimited
    retry_interval_seconds: 1
    user_visible_success_on_enqueue: true

client_swr:
  product_price_max_stale_seconds: 3600
  block_checkout_on_stale_price: false

flag_cache:
  offline_checkout_enabled_ttl_seconds: 86400
  safe_default: true
```

#### Timeline and decision points

| Time | Event | Your move |
| --- | --- | --- |
| T+0 | Incident or gate failure declared; first dashboards are noisy. | Name invariant, commander, owner, and first slice query. |
| T+5 | A tempting fast fix appears in chat. | Decide whether to reject, defer, or scope it. |
| T+15 | Telemetry narrows the mechanism and blast radius. | Apply the smallest safe mitigation and record evidence. |
| T+30 | Support/product ask what customers are affected. | Communicate slice, status, and uncertainty. |
| T+60 | System is stable enough for durable repair planning. | Write acceptance tests and follow-up owners. |

#### Questions

1. Which operations should have been offline queueable,
   revalidated, or online-only?
2. Which signals prove the duplicate is client
   idempotency/retry behavior rather than ledger double-
   commit?
3. How does QUIC connection migration help, and what app-
   level problem remains?
4. Write the first 15-minute mitigation that stops new
   risk without corrupting pending orders.
5. What should the server do with stale price and
   inventory versions during sync?
6. What conflict UX should buyers and sellers see?
7. What mobile flag and cache TTL design would make
   rollback reliable?
8. Name durable telemetry and tests before relaunch.

#### Self-score after opening the key

| Error type | Did it happen? | Note |
| --- | --- | --- |
| Knowledge gap |  |  |
| Wrong layer |  |  |
| Sequencing error |  |  |
| Capacity or blast-radius miss |  |  |
| Security/tenancy invariant miss |  |  |
| Org/comms miss |  |  |
| Careless slip |  |  |

**Pass bar:** correct mechanism, safe sequencing, explicit rejection of at least one bad fix, one numeric capacity or blast-radius check, and a durable prevention plan grounded in source of truth.

**Answer key:** [answers/Week-08c-Operations-Hardening/Client Offline and Edge Resilience Answers.md](../answers/Week-08c-Operations-Hardening/Client%20Offline%20and%20Edge%20Resilience%20Answers.md)

## Key takeaways

- Clients and edges are part of the distributed system.
- Offline queueing stores user intent, not arbitrary HTTP
  requests.
- Idempotency keys must survive retries, restarts, and
  network migration.
- Some data can be stale for display but not for
  decisions.
- Conflict resolution is both a data rule and a user
  experience.
- QUIC helps transport migration but not business
  idempotency.
- Rollback must account for mobile flag TTLs, caches, and
  old app versions.

## Targeted reading

- IETF RFC 9114 and QUIC RFC 9000 sections on HTTP/3 and
  connection migration.
- HTTP caching RFC 9111 sections on validators and stale-
  while-revalidate behavior.
- Apple and Android background execution/networking
  guidance for offline sync constraints.
- Stripe API idempotency documentation for retry-safe
  money operations.
- Martin Kleppmann, Designing Data-Intensive Applications,
  chapters on replication, conflict, and offline clients.
- Service Worker caching guidance from MDN for cache
  partitioning and update behavior.
- Google SRE material on overload, client backoff, and
  cascading failures.
- Northstar Week 01 transport, Week 07 rate limits, Week
  08 CRDTs, and Week 08b auth modules.

---

## Staff & Principal Stretch: Advanced Client & Edge Resilience Protocols

### 1. Mathematical Formalism of Offline Idempotency Key Generation

To guarantee that offline client operation retries never execute duplicate money-moving or state-mutating actions, idempotency keys must be derived deterministically from the client intent:

$$\text{IdempotencyKey} = \text{HMAC-SHA256}\left(K_{\text{client}}, \text{TenantID} \parallel \text{ActorID} \parallel \text{OpType} \parallel \text{ClientSeqNum}\right)$$

```
CLIENT INTENT REPLAY ARBITRATION:

  Client Device (Offline Queue)                      Backend Gateway / Idempotency Store
        │                                                           │
        │── HTTP POST /orders (Key: key_981a) ────────────────────► │
        │   [Network Connection Drops mid-flight]                  │ (Processes order, stores key_981a)
        │                                                           │
        │── HTTP POST /orders (Key: key_981a) [RETRY ON RECONNECT] ─►│
        │                                                           │ (Detects duplicate key_981a)
        │◄── HTTP 200 OK (Returns cached previous order response) ──│
```

### 2. QUIC Connection Migration vs Application-Layer Re-auth

HTTP/3 over QUIC uses **Connection IDs (CIDs)** independent of the client IP/port. When a mobile client transitions from Wi-Fi ($192.168.1.50$) to Cellular ($172.56.12.99$):

- **Transport Layer (QUIC):** Path validation occurs via `PATH_CHALLENGE` / `PATH_RESPONSE` frames without breaking the active 4-way handshake.
- **Application Layer (Security):** If the network transition crosses security domains, the TLS exporter key must re-validate the client session token to prevent hijacked connection migration.

```
QUIC CONNECTION MIGRATION PIPELINE:

  Mobile Device (Wi-Fi: 192.168.1.50) ──────► Envoy Edge Gateway (CID: 0x8a9bf2)
         │ [Switches to 5G Cellular]
  Mobile Device (Cellular: 172.56.12.99) ────► Envoy Edge Gateway (CID: 0x8a9bf2)
         │
         ├── Transport: Validates PATH_CHALLENGE (0ms handshake drop)
         └── App Layer: Re-evaluates Token TTL & Geofence Policy
```

### 3. Delta-CRDT Synchronization Protocol for Edge State

Instead of transferring complete document/cart state arrays across cellular links, **Delta-State CRDTs ($\delta$-CRDTs)** transmit only incremental state mutations ($\delta$) generated since the last acknowledged vector clock $V_{\text{ack}}$:

$$\Delta_{\text{sync}} = S_{\text{local}} \setminus S_{\text{remote}}(V_{\text{ack}})$$

$$\text{Bandwidth Savings} = 1 - \frac{|\Delta_{\text{sync}}|}{Space(S_{\text{full}})} \ge 95\%$$

---

## Appendix A: Extended Principal SRE Field Guide for Client Offline & Edge Resilience

### A.1 — Offline Local Database Schemas (SQLite / IndexedDB)

When clients operate offline, local persistent storage (IndexedDB in web browsers, SQLite in mobile apps) acts as the transient source of truth for pending intents.

```sql
-- SQLite Schema for Local Offline Intent Queue
CREATE TABLE offline_intent_queue (
    intent_id TEXT PRIMARY KEY,       -- Client-generated UUIDv4
    operation_type TEXT NOT NULL,      -- 'ADD_TO_CART', 'UPDATE_PROFILE', 'SUBMIT_ORDER'
    payload JSON NOT NULL,            -- Serialized JSON payload
    created_at INTEGER NOT NULL,      -- Epoch millisecond timestamp
    attempt_count INTEGER DEFAULT 0,  -- Sync retry counter
    last_error TEXT,                  -- Last error string from server
    sync_status TEXT DEFAULT 'PENDING'-- 'PENDING', 'SYNCING', 'FAILED', 'SUCCESS'
);

CREATE INDEX idx_intent_status_created ON offline_intent_queue(sync_status, created_at);
```

### A.2 — Connection Draining Protocols during Edge Gateway Releases

```
ZERO-DOWNTIME GATEWAY CONNECTION DRAINING:

  1. Deploy New Gateway Instance (v2).
  2. Send SIGTERM to Old Gateway Instance (v1).
  3. Old Gateway Action:
     - Stop accepting NEW incoming TCP / TLS connections.
     - Send HTTP/2 GOAWAY frame (or WebSocket Close Frame 1001 Going Away) to active clients.
     - Keep active connection open for Grace Period (e.g., 60 seconds) to finish in-flight requests.
  4. Client Action:
     - Receives GOAWAY frame; opens new TCP / TLS connection to Gateway v2.
     - Existing in-flight requests on Gateway v1 complete cleanly.
  5. After 60 seconds: Hard terminate remaining idle connections on Gateway v1.
```

```
GATEWAY DRAINING METRIC SIGNALS:

  gateway_active_connections{version="v1"} ──► Drops monotonically to 0
  gateway_active_connections{version="v2"} ──► Ramps up to match fleet load
  in_flight_requests_drained_total        ──► Confirms clean termination
```

### A.3 — Client-Side Exponential Backoff with Equal Jitter

Standard exponential backoff without jitter causes synchronized "thundering herd" spikes when thousands of mobile clients reconnect after an outage:

$$t_{\text{sleep}} = \text{random\_between}\left(0, \min\left(\text{MaxSleep}, \text{Base} \times 2^{\text{attempt}}\right)\right)$$

```python
import random
import time

def backoff_with_jitter(attempt: int, base: float = 0.5, max_sleep: float = 30.0):
    temp = min(max_sleep, base * (2 ** attempt))
    sleep_duration = random.uniform(0, temp)  # Equal Jitter
    time.sleep(sleep_duration)
```

### A.4 — Progressive Web App (PWA) Service Worker Caching Architecture

```javascript
// Service Worker Cache-First with Network Fallback & Background Sync
const CACHE_NAME = 'catalog-v1';
const OFFLINE_URLS = ['/catalog', '/offline.html'];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => cache.addAll(OFFLINE_URLS))
    );
});

self.addEventListener('fetch', (event) => {
    if (event.request.mode === 'navigate') {
        event.respondWith(
            fetch(event.request).catch(() => caches.match('/offline.html'))
        );
    }
});
```

### A.5 — Mobile Offline Synchronization Protocol & State Machine

```
OFFLINE SYNCHRONIZATION STATE MACHINE:

  [ OFFLINE_PENDING ] ── Network Reconnect ──► [ SYNC_IN_PROGRESS ]
           │                                            │
           │                                 ┌──────────┴──────────┐
           │                                 ▼                     ▼
     Local Delete                      [ SYNC_SUCCESS ]    [ SYNC_CONFLICT ]
           │                                 │                     │
           ▼                                 ▼                     ▼
     [ REMOVED ]                     [ COMMITTED ]        [ USER_RESOLVE_REQUIRED ]
```

```
CONFLICT RESOLUTION STRATEGIES BY DATA CLASS:

  1. Financial / Money Mutations ──► Server Authority Always Wins; Notify User.
  2. Collaborative Documents      ──► Operational Transformation (OT) or CRDT Merge.
  3. User Preferences / Drafts   ──► Client Authority Wins (Last Write Wins via Hybrid Logical Clock).
```

### A.6 — Mobile Application Storage Encryption & Key Management

Offline queue items stored on mobile devices (iOS / Android) contain user intent payloads that may include sensitive information. Security guidelines mandate encryption at rest:

- **iOS:** Secure Enclave + Keychain API (`kSecAttrAccessibleAfterFirstUnlock`).
- **Android:** Android Keystore System + EncryptedSharedPreferences / SQLCipher.

### A.7 — SRE Incident Case Study: Resolving a Reconnect Storm During Gateway Rollouts

```
POST-MORTEM INCIDENT ANALYSIS: API GATEWAY RECONNECT STORM

  BACKGROUND:
  During a routine API Gateway canary deployment at 14:00 UTC, 2,000,000 active mobile WebSocket connections
  were terminated simultaneously.

  SYSTEM COLLAPSE MECHANISM:
  - Mobile client SDK was configured with fixed 1-second reconnect retries without jitter.
  - 2,000,000 clients re-connected at T+1s, creating a peak load of 2,000,000 QPS on the Auth Service.
  - Auth Service CPU reached 100%, causing health checks to fail and cascading to all remaining gateway instances.

  REMEDIATION ACTIONS:
  1. T+10m: Enforced connection rate limits at AWS ALB (max 10,000 new handshakes per second).
  2. T+22m: Deployed emergency mobile client config push enabling exponential backoff with full jitter.
  3. T+40m: Staggered gateway instance restarts across 10 distinct cell deployment windows.

  PREVENTION LESSONS:
  - Client SDKs MUST implement Full Jitter backoff algorithms before production release.
  - Gateway releases must use HTTP/2 GOAWAY frames with connection draining windows >= 120 seconds.
```

### A.8 — Edge Resilience & Service Worker Cache Partitioning Matrix

| Cache Tier | Storage Engine | Scope / Partitioning Key | Invalidation Trigger |
| :--- | :--- | :--- | :--- |
| Edge CDN | CloudFront / Fastly | URL Path + `Vary: Accept-Encoding` | Purge API / Cache-Control TTL |
| Browser Service Worker | CacheStorage API | Domain + User Auth Subnet | Versioned Service Worker Script Update |
| App Memory | IndexedDB / Memory Cache | Tenant ID + Session ID | User Logout / Session Expiry |

### A.9 — Client Synchronization Health Dashboard Metrics

```
CLIENT RESILIENCE TELEMETRY DASHBOARD:

  1. Offline Queue Backlog: `sum(offline_queue_depth) by (app_version, os)`
  2. Reconnect Storm QPS: `sum(rate(gateway_tcp_handshakes_total[1m])) by (cell)`
  3. SWR Freshness Violations: `sum(rate(stale_checkout_block_total[5m])) by (route)`
  4. Conflict Resolution Rate: `sum(rate(sync_conflict_total[5m])) by (resolution_type)`
```

### A.10 — Client Offline & Edge Resilience Telemetry Metric Dictionary

```
COMPLETE METRIC REGISTRY FOR CLIENT & EDGE RESILIENCE:

  1. client_offline_queue_size{app_version, operation_class}
     - Type: Gauge
     - Description: Number of pending local operations stored in IndexedDB / SQLite queues.

  2. client_sync_retry_attempts_total{operation_class, error_code}
     - Type: Counter
     - Description: Replay attempt counts for queued offline client actions.

  3. websocket_reconnect_storm_qps{cell, app_version}
     - Type: Gauge
     - Description: Rate of fresh socket reconnection handshakes per second following gateway releases.

  4. swr_stale_cache_served_total{route, staleness_age_bucket}
     - Type: Counter
     - Description: Volume of cached HTTP responses served under Stale-While-Revalidate header rules.

  5. quic_connection_migration_total{network_from, network_to, result}
     - Type: Counter
     - Description: Success rate of QUIC connection ID migrations during network interface switching.
```

### A.11 — Comprehensive Socratic Review & Production Verification Drill

```
SOCRATIC REVIEW DRILL — CLIENT OFFLINE & EDGE RESILIENCE:

  Question 1: Why is generating a new UUID idempotency key on every HTTP retry an anti-pattern for mobile clients?
  Answer 1: Generating a new key per HTTP retry defeats server-side deduplication. If the first attempt committed on
            the backend but the response was lost over a flaky cell link, the retry with a new key will execute a duplicate mutation.

  Question 2: How does Stale-While-Revalidate (SWR) improve perceived mobile performance without corrupting money state?
  Answer 2: SWR serves cached data instantly for UI rendering while fetching updates asynchronously. For money decisions
            (e.g., Checkout submit), the client and backend MUST enforce strict freshness checks that block stale inputs.

  Question 3: What protocol prevents WebSocket reconnect storms when thousands of mobile devices disconnect simultaneously?
  Answer 3: Clients MUST use Exponential Backoff with Equal Jitter, and edge gateways must send HTTP/2 GOAWAY frames with
            connection-draining windows to stagger client reconnection times.
```

### A.12 — Summary Architectural Invariants for Client & Edge Resilience

1. **Deterministic Idempotency Key Derivation:** Client offline retries MUST derive idempotency keys deterministically from user intent, not per HTTP request.
2. **Explicit Data Freshness Labels on UI:** Cached data displayed via SWR must convey staleness indicators, and financial operations must block on stale inputs.
3. **Partitioned Client Caches:** Browser and mobile caches MUST incorporate user identity and tenant scope into cache keys to prevent cross-tenant leakage.

### A.13 — Staff SRE Case Study: Edge CDN Stale-While-Revalidate Invalidation Bug

```
CASE STUDY: CROSS-TENANT EXPOSURE VIA IMPROPER CDN SWR CACHING

  BACKGROUND:
  An e-commerce platform experienced an incident where user account balances were exposed to adjacent users on shared browsers.

  ROOT CAUSE DIAGNOSIS:
  - The API endpoint `/api/v2/user/profile` was configured with header `Cache-Control: max-age=60, stale-while-revalidate=300`.
  - CloudFront CDN edge cached the response under key `/api/v2/user/profile` without including the `Authorization` header in the Cache Key.
  - When User B navigated to the profile page within 60 seconds of User A, CloudFront served User A's cached profile from the edge.

  REMEDIATION STEPS:
  1. Immediately issued global CDN invalidation for `/api/v2/user/profile*`.
  2. Updated API response headers to `Cache-Control: private, no-cache, no-store, must-revalidate`.
  3. Added CDN edge policy mandating `Vary: Authorization, X-Tenant-ID` for any cacheable user endpoints.

  PREVENTION LESSONS:
  - Personal data MUST default to `Cache-Control: private, no-store`.
  - Continuous automated security integration tests must verify CDN cache key components for all API routes.
```

### A.14 — Mobile Offline Queue Capacity & Garbage Collection Worksheet

```
OFFLINE QUEUE STORAGE CAPACITY CALCULATIONS:

  1. Storage Constraints:
     - Target Max Queued Operations per Client = 500 intents.
     - Average Payload Size per Intent = 2 KB.
     - Max Storage Footprint = 500 * 2 KB = 1 MB per client.

  2. Garbage Collection (GC) Policy:
     - Retain SUCCESS intents for 24 hours (for local UI history rendering), then purge.
     - Mark FAILED intents as `EXPIRED` if un-synced for > 72 hours and push to server dead-letter store.
     - Enforce SQLite `VACUUM` on app startup if database file size exceeds 10 MB.
```

### A.15 — Advanced Edge Request Coalescing & Collapse Architecture

```
ORIGIN SHIELD REQUEST COALESCING PIPELINE:

  10,000 Concurrent Requests for Item #1234
                     │
                     ▼
       [ CloudFront Origin Shield ]
                     │
       Coalesce to SINGLE Origin Fetch
                     │
                     ▼
           [ Origin API / DB ]
```

### A.16 — Mobile Network State Transition Matrix & App Resilience Policy

| Interface State | App Retry Strategy | Local Storage Strategy | UI Notification State |
| :--- | :--- | :--- | :--- |
| Wi-Fi (High Bandwidth) | Immediate Retry | Flush Offline Queue | Normal Online Indicator |
| Cellular (5G/LTE) | Jittered Backoff | Batch Sync Operations | Normal Online Indicator |
| Weak Signal / Flaky | Staggered Exponential Backoff | Queue All Intent Mutations | "Network Weak — Syncing in Background" |
| Completely Offline | Disable Network Retries | Append to SQLite Queue | "Offline Mode — Changes Saved Locally" |





















### A.17 — Client Offline Resilience & Edge Caching Operations Summary Table

| Resilience Component | Architectural Role | Core Failure Mode Prevented | Primary Verification SLA Metric |
| :--- | :--- | :--- | :--- |
| Local Intent Queue | SQLite / IndexedDB Storage | Data loss during network outages | 0 Lost Offline Mutations |
| Deterministic Idempotency | HMAC Key Derivation | Duplicate payment/order submissions | 0 Duplicate External Ledger Commits |
| Connection Draining | HTTP/2 GOAWAY Frames | Reconnect storm after gateway releases | `gateway_reconnect_qps` < threshold |
| Stale-While-Revalidate | Edge Cache Acceleration | Slow UI rendering over cellular links | Checkout freshness validation block = 100% |

### A.18 — Advanced Service Worker Cache Eviction & Quotas

```javascript
// Progressive Web App Storage Quota Management & Eviction Loop
async function checkAndCleanStorageQuota() {
    if (navigator.storage && navigator.storage.estimate) {
        const { quota, usage } = await navigator.storage.estimate();
        const percentUsed = (usage / quota) * 100;
        console.log(`IndexedDB Storage Usage: ${percentUsed.toFixed(2)}%`);
        
        if (percentUsed > 80) {
            // Evict oldest synced offline intent logs
            const db = await openDatabase();
            const tx = db.transaction('offline_intents', 'readwrite');
            const store = tx.objectStore('offline_intents');
            const index = store.index('sync_status');
            const range = IDBKeyRange.only('SUCCESS');
            
            index.openCursor(range).onsuccess = (event) => {
                const cursor = event.target.result;
                if (cursor) {
                    store.delete(cursor.primaryKey);
                    cursor.continue();
                }
            };
        }
    }
}
```




        
            




        
            




        
            
