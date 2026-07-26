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
