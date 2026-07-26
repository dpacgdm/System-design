# Answer Key - Service Discovery

> Open only after attempting `Week-07-Specialized-Components/Service Discovery.md`.

## Ops Sim Model Answer

### 1. Trigger, amplifiers, symptoms, impact

- Trigger: registry leader election and fsync stall pauses watch delivery.
- Amplifier: client library falls back to fixed 10-second full catalog polling with zero jitter.
- Amplifier: unlimited remote-zone spillover drains healthy zones after az-b inventory readiness flaps.
- Amplifier: aggressive outlier ejection and stale connections keep routing unstable after the trigger clears.
- Symptom: checkout 5xx, p99 latency, requests to draining endpoints, cross-zone bytes, and endpoint cache age rise.
- Customer impact: checkout becomes slow/unreliable; inventory freshness and reservation safety are at risk.

### 2. First safe mitigation

Push an emergency discovery-client config that restores jittered watch behavior or increases fallback poll interval with full jitter, while extending bounded last-known-good cache for safe paths.
Rate-limit full catalog polls at the registry and prefer delta watches/snapshots from a read cache.
Restarting clients is unsafe because it synchronizes reconnects, drops warm caches, and can multiply registry load.

### 3. Stale cache by path

- Checkout write: use stale endpoints only within a short window if endpoint identity/version/cell are known safe and inventory/payment invariants are preserved. Otherwise shed or route to known healthy cell.
- Catalog read: last-known-good is acceptable for longer because stale product reads are safer than routing collapse.
- Metrics ingest: buffer locally and use stale route or degraded ingest; do not let telemetry lookups compete with checkout discovery.

### 4. Suspicious config

- `fallbackPollInterval: 10s`: creates high steady-state load during watch failures.
- `pollJitter: 0s`: synchronizes all clients.
- `remoteZoneSpilloverLimit: unlimited`: turns one zone problem into all-zone overload.
- `consecutive5xx: 2`: ejects endpoints on a tiny sample during retries/brownout.
- `drainTimeout: 20s`: may be too short when p99 is seconds and streams exist.

### 5. Capacity math

28,000 clients / 10 seconds = 2,800 polls/second.
2,800 * 450 KB = 1,260,000 KB/s, about 1.26 GB/s or roughly 10 Gbps before protocol overhead and retries.
This alone can saturate registry nodes or network links, explaining registry p99 and CPU collapse.

### 6. Cross-zone cap

Cap az-b remote spillover by spare capacity in az-a/az-c, not by demand.
For example, allow remote spillover only up to 20% of each remote zone's measured headroom and shed optional work first.
Expose same-zone ratio, rejected requests, and inventory reservation failures so the cap does not hide real user impact.

### 7. Inventory health semantics

Readiness should include local critical dependency capacity such as DB pool availability, worker queue saturation, valid service cert, and ability to perform inventory reservation checks.
It should exclude slow optional dependencies and full synthetic transactions that can amplify outages.
Brownout should disable optional enrichment before removing all endpoints.

### 8. Registry trigger evidence

Registry API p99, leader changes, watch reconnects, full catalog polls, and cache age all move before or with checkout errors.
If inventory alone were root cause, registry QPS and full catalog responses would not rise by two orders of magnitude.

### 9. Bad fixes

- Global DNS failover: service-to-service traffic bypasses public ALB/DNS and may shift load into an unprepared region.
- Full cache flush: forces every client to hit the registry at once and loses last-known-good state.
- Outlier threshold of 1: ejects healthy endpoints on transient errors, reducing capacity.
- Doubling checkout replicas: increases discovery clients and backend pressure without fixing registry amplification.

### 10. Rollback/emergency config

Rollback the client library or push config: restore jittered watches, poll interval 60-120s with full jitter, cap full catalog fetches, keep stale cache max age explicit, and reduce registry lookup concurrency.

### 11. Draining connections

Stop new requests to draining endpoints, reduce connection pool max lifetime, send GOAWAY for HTTP/2/gRPC, close idle connections, and wait for active requests until the drain timeout or explicit stream migration completes.

### 12. Incident comms

Tell service owners not to restart fleets or flush endpoint caches, freeze deploys that change discovery metadata, and report client library versions and zone-specific impact.

### 13. Prevention

- Game day registry watch outage with 30k clients.
- Load test full catalog poll limits.
- Enforce jitter in client library tests.
- Per-service and per-client registry quotas.
- Zone spillover budgets and brownout policy.
- Alerts on endpoint cache age, watch reconnects, and requests to draining endpoints.

### 14. Ownership

Platform owns registry SLO, client library defaults, quotas, watch protocol, and emergency config.
Service teams own readiness semantics, safe stale-cache policy by operation, deployment drain behavior, and dependency capacity signals.

### 15. Smallest boundary

Restore one high-value path such as checkout -> inventory in az-a/az-c with bounded same-zone routing and stale cache while keeping az-b spillover capped.

## Rubric

A passing answer must: separate registry trigger from backend symptoms, compute registry poll load, reject cache flush/restart herds, scope stale-cache behavior by path, and name zone-aware spillover caps.

## Principal Deep Dive - Ops Sim Review

### Telemetry interpretation sequence

1. Start with user impact, not with the registry graph.
2. Confirm checkout 5xx and p99 by zone, route, and dependency.
3. Overlay registry leader changes, fsync latency, watch lag, and client reconnects.
4. Compare endpoint cache age distribution across client versions.
5. Separate same-zone failures from remote-zone spillover failures.
6. Check whether endpoint removals happened before, during, or after checkout errors.
7. Inspect requests to terminating, not-ready, and recently-drained endpoints.
8. Compare full catalog response bytes with normal delta-watch traffic.
9. Verify inventory readiness flaps against DB pool and queue metrics.
10. Read client logs for fallback mode, backoff, jitter, and poll interval.
11. Check connection pool lifetime and HTTP/2 subchannel reuse.
12. Build a minute-by-minute timeline before assigning root cause.

The principal move is to avoid treating every symptom as a separate outage.
A discovery incident often presents as backend errors, zone imbalance, and noisy readiness at the same time.
The useful question is which signal plausibly caused the others.
Here, registry watch delivery stalls first, clients enter synchronized full polling, cache age rises, and routing degrades.
Inventory readiness flaps are important, but they do not explain registry QPS or response-byte explosion.

### Sequencing the response

1. Freeze discovery-affecting deploys and config pushes.
2. Announce no restarts, no cache flushes, and no manual DNS churn.
3. Rate-limit full catalog fetches at the registry.
4. Push emergency client config for full jitter and longer fallback polling.
5. Extend bounded last-known-good routing for safe read and degraded paths.
6. Cap remote-zone spillover by measured spare capacity.
7. Restore critical same-zone checkout-to-inventory paths first.
8. Brown out optional enrichment that consumes inventory or discovery capacity.
9. Shorten connection pool lifetime only enough to exit draining endpoints.
10. Preserve audit and trace data for later root cause analysis.

This order reduces amplification before trying to perfect endpoint freshness.
Fresh-but-unservable discovery data is worse than bounded stale data when the registry is overloaded.
The goal is to make the control plane boring again, then repair individual backend health problems.

### Bad fixes and why they fail

- Lowering DNS TTL to one second increases resolver pressure and does not move existing connections.
- Restarting checkout aligns reconnects, destroys warm caches, and increases registry demand.
- Flushing every endpoint cache turns a watch outage into a thundering herd.
- Global DNS failover shifts traffic at the wrong layer and may bypass service mesh policy.
- Disabling readiness entirely routes traffic to instances that cannot reserve inventory.
- Making liveness deeper kills pods for dependency brownouts and creates crash loops.
- Setting outlier ejection to one error shrinks capacity during a retry storm.
- Raising registry node count without client throttles may only move the bottleneck to network and storage.
- Allowing unlimited cross-zone spillover protects local SLO graphs while draining remote zones.
- Doubling checkout replicas doubles discovery clients and can worsen every shared dependency.

Each bad fix shares a pattern: it optimizes a local metric while increasing correlated work.
A principal answer names the hidden coupling and rejects the fix even if it sounds operationally familiar.

### Capacity and control-plane budgets

Discovery capacity must be budgeted as a shared control plane.
Normal watch traffic should be small delta updates.
Fallback full catalog polling is an emergency mode and needs explicit quotas.
Budget by client fleet, service, zone, and response size.
Alert on bytes/sec and serialized endpoint count, not only request/sec.

For the given incident, 28,000 clients polling every 10 seconds produce 2,800 polls/sec.
At 450 KB each, that is about 1.26 GB/sec before TLS, headers, retries, and compression variance.
If a retry layer doubles requests, the registry can see more than 20 Gbps of effective pressure.
If each client also opens new connections, CPU moves from serialization to TLS and accept queues.
This is why jitter and admission control are correctness features, not polish.

Useful capacity limits:

- per-client token bucket for full catalog reads;
- per-service quota so one fleet cannot starve others;
- registry-side stale snapshot cache for emergency full reads;
- maximum serialized endpoint metadata size per service;
- backpressure that tells clients to extend last-known-good rather than retry immediately;
- separate SLOs for watch delivery, snapshot reads, and write quorum.

### Readiness, liveness, and brownout

Readiness answers "should this endpoint receive new traffic now?"
Liveness answers "should the process be restarted?"
Mixing them creates outages.
Inventory DB pool exhaustion should usually remove readiness or reduce weight.
An optional personalization dependency should brown out, not remove checkout entirely.
A slow synthetic that calls every downstream can become a denial-of-service probe.

Good readiness includes local critical capacity:

- can accept a request;
- has valid identity and current config;
- can reach mandatory local dependency pools;
- has worker and queue headroom for the operation class;
- can safely reject when invariants cannot be met.

Good readiness excludes:

- optional recommendations;
- full end-to-end synthetic purchases;
- remote-zone health that does not reflect this instance;
- checks that allocate scarce locks, reservations, or DB transactions.

### Durable fixes

1. Make jitter mandatory in the client library and test it statistically.
2. Ship a remote kill switch for fallback polling interval and registry concurrency.
3. Add a registry read-through snapshot tier for emergency full catalogs.
4. Enforce service and client quotas on discovery reads.
5. Require zone spillover budgets tied to live headroom.
6. Separate readiness, liveness, startup, and brownout contracts in service templates.
7. Add drain conformance tests for HTTP/1.1, HTTP/2, gRPC, and long streams.
8. Record endpoint version, service identity, zone, and drain state in routing logs.
9. Add dashboards for cache age, watch lag, full-poll mode, and requests to draining endpoints.
10. Run a game day with registry watch outage, compaction errors, and partial-zone capacity loss.

### Organization and ownership

Platform owns the registry, watch protocol, quotas, emergency client config, and library defaults.
Service teams own meaningful readiness, safe stale-route policy, dependency brownout, and drain behavior.
SRE owns incident playbooks, game days, burn alerts, and cross-zone capacity policy.
Security owns the service identity invariants that decide when stale endpoints become unsafe.
Product and support own user-facing messaging when degraded checkout or stale catalog reads are visible.

The post-incident action item should not be "service discovery was down."
It should list which contracts were missing: fallback traffic budget, readiness semantics, spillover caps, and drain conformance.
