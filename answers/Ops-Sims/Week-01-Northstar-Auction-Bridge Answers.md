# Answer Key - Week 01 Northstar Auction Bridge

> Open only after attempting the Ops Sim.

## Q1 - Layer map

- EU old ALB traffic: DNS/client/recursive cache staleness.
- Mobile page slowness: HTTP request amplification plus HTTP/3 fallback on affected networks.
- GraphQL 200 with errors: API/application monitoring gap.
- Bid update freezes: WebSocket idle timeout mismatch and reconnect storm.
- Checkout settlement failures: TCP ephemeral port exhaustion from per-bid DB connects.
- SQL p99 normal: red herring for checkout; DB execution is not primary bottleneck.

## Q2 - Strongest evidence

1. h3 success 14% with high attempt rate: QUIC fallback penalty.
2. XHR count 168/page with HTTP/1.1 target path: user-perceived latency from fan-out.
3. WebSocket sawtooth every 60s plus timeout config 60s and heartbeat 75s: idle timeout disconnects.
4. Reconnect attempts 420k/min: synchronized retry storm.
5. TIME_WAIT 44k > 28,232 ephemeral range: local port exhaustion.
6. `cannot assign requested address`: local source port exhaustion.

Red herring: gateway/SQL handler p95 is low. Individual operations are fast; composition and connection management are failing.

## Q3 - First 15-minute sequence

1. Declare P1 and assign separate leads for edge/WebSocket/checkout.
2. Preserve source-of-truth bid ordering; do not alter bid write semantics.
3. Restore WebSocket timeout alignment: raise edge idle timeout or lower heartbeat below timeout; enable jittered reconnect where possible.
4. Re-enable/bypass to bundled mobile auction endpoint; hide optional seller widgets if needed.
5. Segment/strip long `Alt-Svc` for affected EU carriers rather than disabling all edge optimizations globally.
6. Stop checkout settlement connection churn: flip `use_shared_pool=true` / disable `connect_per_bid`.
7. Drain/restart settlement pods in batches only after churn is stopped.
8. For stale DNS clients, keep old ALB safe/read-only or redirect mutating paths; do not rely on record deletion.

## Q4 - Bad fixes

- Scaling every backend 5x does not fix DNS cache, h3 fallback, WebSocket timeout mismatch, or per-bid connect churn.
- Purging/deleting old ALB DNS records does not affect clients with cached answers.
- Disabling all reconnects strands legitimate mobile users; use jitter/backoff/resume.
- Raising Postgres `max_connections` ignores local port exhaustion and can destabilize the DB.

## Q5 - Capacity math

```text
56 items x 3 calls/item = 168 mobile data calls/page

250,000 reconnects x 24 channels = 6,000,000 subscriptions

28,232 ephemeral ports / 60s TIME_WAIT ~= 470 new connects/sec/pod unsafe threshold
```

Each number maps to a different blast radius: ALB/app worker pools, Redis/auth subscription load, and local TCP port exhaustion.

## Q6 - Durable guardrails

- BFF/bundle endpoints and request-count budgets for mobile pages.
- RUM by protocol/ASN and controlled `Alt-Svc` max-age.
- WebSocket heartbeat < path idle timeout, full-jitter reconnect, resume cursors.
- CDN/DNS failover game days sampling recursive and app-process caches.
- Shared DB pools enforced in hot paths; no transient clients per request.
- GraphQL operation error metrics independent of HTTP status.

## Q7 - Org / runbook

By T+10: incident commander, auction operations, edge/DNS owner, WebSocket owner, checkout owner, DB owner, support, legal/comms liaison.

Pre-authorized degradations: hide optional seller widgets, show live-update delay banner, serve stale non-authoritative bid display with clear state, disable affected checkout settlement worker path, keep old ALB read-only for mutating checkout. Not pre-authorized: changing bid order, accepting checkout without idempotent payment/inventory checks, or closing auction based on stale clients.

## Principal model response

### Incident thesis

Week 01 is about transport and application composition. The
auction bridge incident is not solved by scaling a single
backend because the symptoms live at different layers:

- DNS and client caches keep old ALB traffic alive;
- HTTP request fanout and HTTP/3 fallback create mobile page
  latency;
- GraphQL returns HTTP 200 while operations fail, hiding
  application errors from status-code dashboards;
- WebSocket heartbeat and idle timeout mismatch creates a
  reconnect storm;
- checkout settlement creates one DB connection per bid and
  exhausts ephemeral ports.

The invariant is bid and settlement correctness. Display
freshness can degrade; bid ordering, payment settlement, and
idempotency cannot.

### T+0 to T+15 sequence

1. Declare P1 and split owners: incident command, edge/DNS,
   mobile/BFF, WebSocket/realtime, checkout settlement, DB,
   support/comms.
2. Preserve bid source-of-truth writes; do not change bid
   ordering or auction close semantics while transport is
   unstable.
3. Align WebSocket heartbeat and idle timeout immediately:
   heartbeat must be comfortably below the shortest path idle
   timeout, and reconnects need full jitter.
4. Enable resume cursors so reconnects do not resubscribe all
   channels from scratch.
5. Re-enable bundled mobile endpoint or temporarily remove
   optional seller widgets to lower request count per page.
6. Scope HTTP/3/Alt-Svc mitigation to affected EU carriers or
   ASNs instead of disabling all edge optimization globally.
7. Flip checkout settlement away from per-bid DB connects to a
   shared pool; only then drain/restart pods in batches.
8. Keep old ALB safe for stale clients: read-only or redirect
   mutating paths, with metrics on old endpoint traffic.

### Telemetry interpretation

DNS:

- Stale clients hitting old ALB after cutover are expected in
  real systems because recursive resolvers, JVM/mobile caches,
  and connection pools outlive DNS record changes.
- Deleting old records does not recall cached answers.

HTTP:

- `56 items x 3 calls/item = 168` calls per mobile page means
  performance depends on composition, not only backend p95.
- HTTP/1.1 or fallback paths multiply connection overhead and
  head-of-line pain compared with a bundled endpoint.

HTTP/3:

- Low h3 success with high attempts means Alt-Svc is causing
  clients to attempt a bad path repeatedly. Strip or shorten
  Alt-Svc for affected networks.

GraphQL:

- HTTP 200 with operation errors means infrastructure
  dashboards can be green while user operations fail. Track
  GraphQL error objects by operation.

WebSocket:

- Idle timeout 60s and heartbeat 75s guarantees the path can
  close the connection before the heartbeat proves liveness.
- 250k reconnects across 24 channels means 6M subscription
  operations, which can saturate Redis/auth/subscription
  services.

TCP/DB:

- Ephemeral range about 28,232 ports with 60s TIME_WAIT yields
  roughly 470 new connections/sec/pod as an unsafe ceiling.
- `cannot assign requested address` is local source-port
  exhaustion, not a Postgres query slowness diagnosis.

### Bad-fix physics

- Scaling all services 5x preserves DNS staleness, WebSocket
  timeout mismatch, and per-bid connect churn.
- Deleting old ALB records ignores cached DNS and can strand
  clients.
- Disabling reconnects stops legitimate bidders from
  recovering; use jitter and resume.
- Raising Postgres `max_connections` does not increase local
  ephemeral ports and can destabilize DB memory.
- Accepting settlement without idempotency risks duplicate
  payments when clients retry after transport errors.
- Closing the auction based on stale client display state
  violates bid fairness.

### Blast-radius checks

Compute at least one of:

- mobile page fanout: 168 data calls per page times active
  page loads gives BFF/origin pressure;
- reconnect fanout: reconnecting clients times channels gives
  subscription pressure;
- ephemeral ports: available local ports divided by TIME_WAIT
  window gives maximum safe new connection rate;
- old endpoint traffic: stale ALB request rate by method tells
  which mutating paths need safe handling.

### Repair and reconciliation

Use authoritative bid log and settlement idempotency keys.
Display caches and WebSocket delivery logs can locate symptoms
but cannot decide winners or charges. If a bid or settlement
status is ambiguous, mark it pending and reconcile from the
bid ledger/payment provider instead of replaying UI events.

### Durable acceptance gates

- Mobile pages have request-count budgets and BFF/bundled
  endpoints for high-fanout views.
- RUM slices by protocol, carrier/ASN, region, app version,
  and fallback reason.
- Alt-Svc changes have scoped rollout, max-age control, and
  rollback.
- WebSocket heartbeat, idle timeout, jitter, and resume cursor
  are tested together.
- Settlement hot paths use bounded shared pools and
  idempotency keys.
- GraphQL dashboards alert on operation errors even when HTTP
  status is 200.
- DNS failover game-days measure recursive cache and
  app-process cache behavior, not just authoritative TTL.
