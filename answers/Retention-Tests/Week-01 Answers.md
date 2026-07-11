# Answer Key - Week-01

> Open only after attempting the learner file questions.

---

# Part 1: Foundation Rapid-Fire

## Q1 - TCP TIME_WAIT

`TIME_WAIT` keeps the closing side's connection tuple reserved long enough for delayed packets from the old connection to expire and for the final ACK to be retransmitted if needed. It lasts 2xMSL so packets cannot be confused with a later connection that reuses the same tuple. At scale, short-lived outbound connections accumulate in `TIME_WAIT` and can exhaust ephemeral ports.

## Q2 - Ephemeral ports

The exhausted resource is the client's ephemeral source-port space for the same destination IP:port tuple. The tuple matters because TCP uniqueness is source IP, source port, destination IP, destination port; thousands of short connections to one destination reuse the same destination tuple and burn through source ports. The best application fix is connection reuse/pooling, not just kernel tuning.

## Q3 - DNS UDP/TCP

DNS uses UDP for ordinary small request/response lookups because it avoids connection setup overhead. It retries over TCP when the UDP response is truncated, signaled by the TC bit, commonly with large DNSSEC or record-set responses.

## Q4 - UDP reliability

The team gave up ordered, reliable byte-stream delivery and congestion-managed retransmission. If gaps are unacceptable, the application must add sequence numbers, acknowledgments/retry or forward-error correction, and missing-sample detection.

## Q5 - HTTP/1.1 parallel connections

Browsers opened multiple connections to parallelize requests because HTTP/1.1 could not safely multiplex independent responses over one connection in the general case. The workaround reduced application head-of-line blocking but paid extra TCP slow-start and connection-state overhead; packet loss on one connection hurt only that connection.

## Q6 - HTTP/2 TCP HOL

HTTP/2 multiplexes streams over one TCP connection. TCP delivers bytes in order, so if one packet is lost, later bytes for all streams behind that missing sequence number are withheld until retransmission completes.

## Q7 - QUIC connection ID

QUIC identifies a connection by a connection ID rather than only the TCP 4-tuple. When a phone switches WiFi to cellular and its IP/port changes, QUIC can continue the logical connection instead of forcing a full reconnect.

## Q8 - HTTP/3 fallback

The likely policy is UDP/443 blocked or degraded by the corporate firewall. Browsers try QUIC first, wait for timeout/failure, then fall back to HTTP/2 over TCP; once the network is learned as QUIC-hostile, repeat navigations skip or shorten the attempt.

## Q9 - REST cacheability

The team likely lost default cache-friendly semantics of GET, including CDN/browser willingness to cache safe idempotent responses. They should verify whether the operation is actually safe, whether POST caching is explicitly configured if desired, and whether the cache key includes all correctness dimensions.

## Q10 - GraphQL 200 errors

GraphQL often returns HTTP 200 with application errors in the JSON `errors` field and partial `data`. Add body-level error rate, resolver error rate, nullability violations, and per-field latency/fanout metrics.

## Q11 - GraphQL fanout

This is resolver fanout / N+1 amplification hidden behind one API call. Guardrails include query complexity/depth limits, persisted query allowlists, resolver batching, per-request downstream call budgets, and field-level tracing.

## Q12 - gRPC and L4 imbalance

gRPC uses long-lived HTTP/2 connections. An L4 load balancer balances connections, not streams, so a few connections can pin most RPCs to a few pods. Fix with client-side gRPC round-robin/xDS or an L7 proxy like Envoy that balances HTTP/2/gRPC requests.

## Q13 - Deadlines

A 30s downstream deadline violates a 2s user-facing SLO and lets abandoned work consume capacity. Each hop should receive a propagated deadline derived from the remaining upstream budget, with time reserved for retries and response assembly.

## Q14 - WebSocket reconnect storm

Use exponential backoff with jitter. Backoff alone still synchronizes clients at powers of two; jitter spreads each retry wave so the replacement server is not hit by a coordinated thundering herd.

## Q15 - WebSocket idle timeout

Regular 60s drops suggest an intermediate idle timeout, often proxy/firewall/NAT. Application ping/pong heartbeats shorter than the idle timeout keep the connection active and detect dead peers.

## Q16 - DNS TTL migration

Lower TTL well before cutover, at least one full old TTL in advance (often 24h for 86400, plus safety margin). If you lower TTL at cutover, resolvers that cached the old record still honor the old 86400-second TTL.

## Q17 - JVM DNS cache

The JVM can cache DNS answers indefinitely or longer than DNS TTL depending on security settings. Set `networkaddress.cache.ttl` (or `-Dsun.net.inetaddr.ttl`) to a bounded value such as 30-60 seconds.

## Q18 - CDN directives

At T=0 the CDN misses, fetches origin, and stores a shared-cache response. At T=61 the object is stale under `s-maxage=60`, so it can be served immediately while the CDN revalidates asynchronously during the 300s stale-while-revalidate window. At T=361 the SWR window is over, so the cache must synchronously revalidate before serving. If origin is down at T=500, `stale-if-error=86400` lets the CDN serve stale rather than fail, as long as it still has an object within that error window.

---

# Part 2: Staff Diagnostic Cards

## Q19 - Port churn diagnosis and math

The failure is ephemeral port exhaustion from short-lived TCP connections. Default range 32768-60999 has 28,232 ports. With 4,800 requests/sec and ~60s `TIME_WAIT`, steady-state closed sockets can be roughly 288,000 for one destination tuple, far above the range. The `EADDRNOTAVAIL` plus huge `TIME_WAIT` count proves client-side port exhaustion.

## Q20 - Why doubling replicas is incomplete

Doubling replicas may distribute client source IPs and temporarily reduce per-pod churn, but each pod still creates one connection per request and can exhaust its range under load. The durable application fix is a shared HTTP client with keep-alive/connection pooling and sane max-idle/max-open settings; kernel port-range/tcp_tw_reuse tuning is secondary.

## Q21 - Cacheable user data failure

The failure is personalized account data cached in a shared CDN cache. The cache key ignores Cookie, Authorization, and X-User-ID while the response varies by identity, so one user's account summary can be served to another user. The 91% hit ratio and `Age` headers on wrong-user responses prove edge reuse.

## Q22 - Vary Cookie rejection

`Vary: Cookie` is not the main fix; it can explode the key space and still leaves a risky design for sensitive data. Immediate mitigation: restore `private, no-store` or bypass CDN caching and invalidate affected objects. Durable prevention: classify endpoints by sensitivity, enforce cache-header tests, keep identity-bearing responses private, and review cache keys for every shared-cache behavior.

## Q23 - DNS expansion

With `ndots:5`, `fraud.partner-api.com` has fewer dots than the threshold, so the resolver tries search-domain variants first: `fraud.partner-api.com.checkout.svc.cluster.local`, then `svc.cluster.local`, then `cluster.local`, then `ec2.internal`, and only then the absolute name. Most attempts return NXDOMAIN, which explains the high NXDOMAIN ratio and CoreDNS CPU.

## Q24 - DNS mitigations

Safe mitigations: use a trailing dot for external FQDNs (`fraud.partner-api.com.`), set pod `dnsConfig` `ndots:1` for workloads with external dependencies, cache DNS in-process with bounded TTL, or deploy NodeLocal DNSCache for the namespace. Proof: CoreDNS qps and NXDOMAIN ratio drop, DNS lookup p99 returns near baseline, and fraud-call latency improves without scaling unrelated app pods.

## Q25 - GraphQL monitoring blind spot

HTTP status monitoring misses GraphQL application errors because the transport succeeds with 200. Add body-level `errors` rate, partial-data/null field rate, resolver latency/failure by field, response size, and downstream call count per operation name.

## Q26 - Query guardrails

Use persisted query allowlists for mobile flows, complexity/depth limits, resolver batching/DataLoader, per-request fanout budgets, response-size budgets, and field-level tracing. The release should fail CI/canary if one page query expands into unbounded downstream calls or returns a multi-megabyte response.

---

# Part 3: Compound Scenario

## Q27 - Problem inventory

1. **Personalized GraphQL cached at CDN (CDN/HTTP/security):** `/graphql` changed to `public, s-maxage=45` while product cards include personalized eligibility and bidder aliases. Evidence: 88% CDN hit ratio, `Age` 12-44s, wrong-user complaints, Authorization not in cache key.
2. **GraphQL body errors hidden by HTTP 200 (API monitoring):** HTTP 5xx is 0.02% but body errors are 11%. Evidence: mismatch between status and body error telemetry.
3. **gRPC L4/pick_first black hole (gRPC/HTTP2/LB):** one channel and `pick_first` behind NLB concentrates streams. Evidence: two hot pods, six idle pods, 2 long-lived connections carrying 81% of RPCs.
4. **WebSocket idle timeout due to missing heartbeats (WebSocket/TCP/proxy):** ping disabled when event stream is active; some rooms idle. Evidence: regular 60s drops, servers healthy, corporate proxy idle timeout 60s.
5. **Kubernetes DNS ndots expansion (DNS):** external fraud hostname with fewer than 5 dots triggers search-path queries. Evidence: 690K CoreDNS qps, 74% NXDOMAIN, top queries show appended cluster domains.
6. **HTTP/3/QUIC blocked on affected networks (HTTP/3/UDP):** first navigation slow where QUIC success is 4%, then fallback works. Evidence: affected network RUM and HTTP/2 fallback success.
7. **Stale eligibility amplifies allocation load (cross-layer):** cached eligibility cards drive users into failed allocation attempts, increasing gRPC and fraud calls.

## Q28 - Causal graph

- Public CDN caching of personalized GraphQL -> stale/wrong eligibility -> more failed checkout/allocation attempts -> more gRPC calls and more fraud DNS lookups.
- gRPC pick_first/L4 imbalance -> hot allocation pods -> higher latency/timeouts -> retries -> even more fraud lookups and CoreDNS load.
- DNS ndots expansion -> CoreDNS latency -> slower fraud checks -> allocation latency -> more client retries and worse checkout user experience.
- WebSocket drops -> reconnect load and stale live state perceptions -> more page refreshes/API calls.
- HTTP/3 failure affects first navigation and increases perceived outage but is not the integrity root cause.

## Q29 - Priority order

1. Stop the privacy/integrity leak: bypass/disable shared caching for personalized GraphQL and invalidate affected entries.
2. Stop allocation overload by fixing gRPC balancing or reducing traffic to hot pods; this protects checkout source of truth.
3. Reduce DNS amplification with trailing dot/ndots/NodeLocal caching because it is amplifying every fraud check.
4. Restore WebSocket ping/pong to reduce reconnect storm and live-state confusion.
5. Tune HTTP/3 fallback for affected networks or temporarily disable HTTP/3 for hostile networks; lower priority because TCP fallback succeeds.

## Q30 - Immediate actions

- CDN/GraphQL: restore `Cache-Control: private, no-store` for personalized GraphQL, create a separate public cacheable product summary without identity fields, and invalidate `/graphql*` objects.
- gRPC: switch from `pick_first` to `round_robin`/xDS or route through Envoy; increase channels conservatively and watch backend distribution.
- WebSockets: re-enable ping/pong at 20-25s for all rooms, including rooms with no event stream.
- DNS: use `fraud.partner-api.com.` or set `ndots:1` for allocation pods; deploy/enable NodeLocal DNSCache where absent.
- HTTP/3: keep HTTP/2 fallback healthy, consider disabling HTTP/3 only for affected enterprise networks or via staged rollback while working with network owners.

## Q31 - Bad fixes

1. Purging CDN while keeping public cache header only repeats the leak after refill; change headers/keying first.
2. Disabling WebSockets and polling every second creates massive HTTP load and worse freshness; fix heartbeats/backoff.
3. Setting 1000 gRPC channels everywhere can overload backends and connection state; use proper LB with bounded pools.
4. Scaling CoreDNS to 200 replicas treats symptom and adds control-plane/load cost; fix query amplification and cache locally.
5. Disabling HTTP/3 forever is disproportionate; fallback/network targeting is enough unless global QUIC health is bad.
6. Caching GraphQL by Authorization may create huge key cardinality and still caches sensitive data at shared edge; split public/private responses.

## Q32 - Capacity math

At 15,500 fraud lookups/sec and `ndots:5` with four search suffix failures plus one absolute success, the fraud client can generate roughly 77,500 DNS queries/sec, about 62,000 of them NXDOMAIN. If stale eligibility causes retries or failed allocations, a 2x retry factor doubles that to 155,000 DNS queries/sec just for fraud lookups, before baseline cluster DNS traffic.

## Q33 - Verification plan

- CDN: `CF/CloudFront-Cache-Status` for personalized GraphQL becomes BYPASS/MISS with `private, no-store`; wrong-user tickets stop; `Age` absent or zero for private responses.
- GraphQL: body error rate and null field rate fall; response size and resolver fanout return to baseline.
- gRPC: CPU and p99 spread evenly across all allocation pods; connection/stream distribution is balanced; retry rate drops.
- DNS: CoreDNS qps, CPU, NXDOMAIN ratio, and DNS lookup p99 fall; top query list no longer shows search-domain expansions for fraud.
- WebSocket: reconnects/min drop; close reason distribution normalizes; heartbeat metrics visible.
- RUM: affected networks show shorter first navigation or explicit HTTP/2 fallback without long QUIC timeout.

## Q34 - Org/runbook

By T+15 include incident command, edge/CDN owner, GraphQL/BFF owner, allocation/gRPC owner, DNS/platform owner, WebSocket owner, security/privacy, legal, support, and business lead. Customer comms should acknowledge product-card inconsistency/privacy investigation without overclaiming. Senior approval is required for keeping the drop open under known integrity risk, any durability/security bypass, broad protocol disablement, or customer-impacting data purge beyond scoped invalidation.


---

# Part 4: Additional Diagnostic Answers

## Q35 - HTTP/2 versus origin churn

The origin regression is CDN-to-origin HTTP/1.1 short-connection churn: new TCP/TLS handshakes nearly equal origin miss RPS, connection age is 1.2s, connect time rose, and response generation stayed flat. The browser-path symptom is HTTP/2 over TCP under packet loss: many multiplexed objects share one TCP congestion/retransmission fate, so unrelated streams stall behind a lost packet.

## Q36 - Origin efficiency proof and mitigation

Unchanged response generation p95 proves application work is not the primary slow component; connect time, TLS handshakes/sec, and new connections/sec identify connection setup overhead. Restore CDN-to-origin HTTP/2 or persistent HTTP/1.1 keep-alive with connection pooling, then verify handshake rate and connect p95 fall while origin generation remains stable.

## Q37 - Tempting fixes

Disabling HTTP/2 globally treats a path-specific packet-loss issue and worsens normal users. Doubling pods may hide CPU but keeps handshake waste. Raising CDN TTL on personalized API responses risks correctness/security leakage and stale identity-bearing data; never use cache TTL as an origin-protection hack for private responses.

## Q38 - TTL failure

The TTL was lowered only five minutes before the IP change. Recursive resolvers that cached the old answer before 10:00 can legally serve it for the old 86400-second TTL. TTL should have been lowered at least one old TTL before migration, then verified by observing resolver populations before cutover.

## Q39 - Old-origin behavior

Keep old origin serving safe reads and proxying or internally forwarding writes if correctness can be preserved. Avoid cross-host redirects for authenticated mutating requests unless clients are proven to preserve headers and idempotency keys. For unsafe writes, return a clear retryable maintenance response or proxy to the new origin with idempotency protection.

## Q40 - Telemetry split

Cache drag appears as resolver-specific old answers with decreasing TTLs. Client pinning appears as clients connecting to old IP without fresh DNS lookups or with long-lived app-level caches. Routing/BGP issues show traffic for the new IP taking wrong paths or failing independent of DNS answer distribution.

## Q41 - Retry policy

Backoff exists, but jitter is missing. Without jitter, every client retries at the same 1/2/4/8/16/30-second boundaries, creating synchronized spikes. A cap alone limits maximum delay but does not spread load.

## Q42 - TCP symptoms from reconnect storm

Each reconnect is a TCP handshake and eventual close. Spikes can overflow SYN backlogs and create many short-lived sockets that enter `TIME_WAIT`, exhausting ephemeral ports or conntrack entries even when application threads and CPU are healthy.

## Q43 - Safe mitigations

Client-side: ship or remotely configure full jitter with capped exponential backoff and a random initial delay. Server-side: slow rollout/restart batches, temporarily increase accept/SYN backlog where safe, shed reconnects with retry-after hints, and preserve existing connections during deploys.

## Q44 - Post-incident test

Run a game-day or load test where a large client cohort is disconnected at once. Verify reconnect attempts are smeared across the configured window, SYN backlog drops do not occur, `TIME_WAIT` remains under port-range runway, and steady-state connection recovery meets the product SLO.
