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
