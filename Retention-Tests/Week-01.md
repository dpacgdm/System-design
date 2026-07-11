# WEEK 1 RETENTION TEST

## Rules

```text
RULES OF ENGAGEMENT

1. Answer from MEMORY. Do not re-read the teaching modules.
2. Rapid-fire answers: 2-4 sentences each.
3. Diagnostic cards: name the layer, mechanism, evidence, and safest first move.
4. Compound scenario: full depth expected; show sequencing and blast radius.
5. It is OK to write "I don't remember." Guessing hides the gap.
6. Do not open the answer key until you have attempted every section.
```

---

## Part 1: Foundation Rapid-Fire Concept Recall (Q1-Q18)

Answer ALL 18 in one response. Keep each answer concise.

**Q1 (TCP - TIME_WAIT):** What is the purpose of `TIME_WAIT`, why does it last for 2xMSL, and what SRE problem does it cause when one service opens many short-lived outbound connections to one destination?

**Q2 (TCP - ephemeral ports):** A pod reports `connect: cannot assign requested address` while CPU and memory are normal. `ss -tan state time-wait | wc -l` is huge. What resource is exhausted, why is the destination tuple relevant, and what is one application-level fix?

**Q3 (TCP vs UDP - DNS):** Standard DNS queries usually use UDP. Explain why, and name the exact condition that causes a resolver to retry with TCP.

**Q4 (UDP - reliability):** A telemetry pipeline switches from TCP to UDP and p99 latency improves, but dashboards have small gaps during packet loss. What guarantee did the team give up, and what application-level feature would be required if gaps are unacceptable?

**Q5 (HTTP/1.1):** Why did browsers open multiple HTTP/1.1 connections per origin, and how did that workaround interact with TCP slow start and head-of-line blocking?

**Q6 (HTTP/2):** HTTP/2 solved HTTP-layer head-of-line blocking with multiplexed streams. Explain why a single lost TCP packet can still stall unrelated HTTP/2 streams.

**Q7 (HTTP/3 / QUIC):** What is QUIC's connection ID, and what user-visible problem does it solve that TCP cannot solve without reconnecting?

**Q8 (HTTP/3 fallback):** Users on one corporate network see first page load latency of 8-12s after HTTP/3 was enabled, then subsequent loads are fine. What likely network policy is involved and why is the symptom front-loaded?

**Q9 (REST):** A REST endpoint changed from `GET /orders/{id}` to `POST /orders/search` for cacheable lookups. What CDN/browser caching behavior did the team likely lose, and what should they verify before keeping the change?

**Q10 (GraphQL):** Your HTTP status-code dashboard shows 0.0% errors while users see broken product pages. What GraphQL behavior can explain this, and what metric should be added?

**Q11 (GraphQL):** A product page launches one GraphQL query that expands into 130 downstream resolver calls. Name the failure mode and one guardrail that should exist before production.

**Q12 (gRPC):** Two of six gRPC backends are hot while four are idle behind an L4 load balancer. Explain the mechanism and the balancing layer that actually fixes it.

**Q13 (gRPC deadlines):** A client sets a 30s deadline but the request path has a 2s user-facing SLO. Why is this dangerous, and how should deadlines propagate through downstream calls?

**Q14 (WebSockets):** 200,000 clients reconnect after a server restart. Name the retry algorithm with both required components and why one component alone is insufficient.

**Q15 (WebSockets idle timeout):** WebSocket connections drop every 60 seconds while servers are healthy. What timeout pattern does this suggest, and what frame-level mechanism usually prevents it?

**Q16 (DNS TTL):** You plan to move `api.example.com` from IP A to IP B. Current TTL is 86400. What preparation must happen before cutover, how far ahead, and why does lowering TTL at cutover not help enough?

**Q17 (DNS Java caching):** A Java service keeps using an old RDS IP after failover while Go and Python services recover in 60 seconds. What JVM behavior is likely responsible and which property controls it?

**Q18 (CDN cache directives):** Interpret `Cache-Control: public, s-maxage=60, stale-while-revalidate=300, stale-if-error=86400`. What happens at T=0, T=61, T=361, and when origin is down at T=500?

---

## Part 2: Staff Diagnostic Cards (Q19-Q26)

For each card, answer:

- Which layer/protocol is implicated?
- What is the most likely mechanism?
- Which evidence is decisive?
- What is the safest first mitigation?

### Card A - Port churn after a release

```text
Service: catalog-bff
Change: new HTTP client created per request instead of shared client
Traffic: 4,800 requests/sec steady
Destination: inventory.internal:443
Kernel: ip_local_port_range = 32768 60999
Observed:
  connect EADDRNOTAVAIL: 2,400/min
  TIME_WAIT sockets to inventory.internal: 51,800
  CPU: 38%, memory: 44%
  inventory p99 server handling time: 18ms
Tempting fix:
  double catalog-bff replicas immediately
```

**Q19:** Diagnose the failure and calculate whether the default ephemeral port range is plausibly exceeded.

**Q20:** Explain why doubling replicas might reduce symptoms but does not fix the mechanism. Name the better application-level fix.

### Card B - Cacheable user data at the edge

```text
Endpoint: GET /api/account/summary
Before:
  Cache-Control: private, no-store
After:
  Cache-Control: public, s-maxage=120
CDN cache key:
  host + path + query
  Cookie, Authorization, and X-User-ID are not in the key
Telemetry:
  CDN hit ratio: 0% -> 91%
  origin RPS: 18,000 -> 1,700
  support tickets: "I see another seller's balance"
  Age header on bad responses: 37-104 seconds
Tempting fix:
  add Vary: Cookie globally
```

**Q21:** Identify the security/correctness failure and the cache-key mistake.

**Q22:** Reject or accept `Vary: Cookie` as the main fix. Give the immediate mitigation and the durable prevention.

### Card C - DNS search-path explosion

```text
Cluster: EKS
Pod dnsPolicy: ClusterFirst
/etc/resolv.conf:
  search checkout.svc.cluster.local svc.cluster.local cluster.local ec2.internal
  options ndots:5 attempts:2 timeout:1
External hostname: fraud.partner-api.com
Call rate: 11,500/sec during launch
CoreDNS:
  qps: 145,000 -> 520,000
  NXDOMAIN ratio: 71%
  coredns_cpu: 96%
Tempting fix:
  scale all application pods because "DNS is slow"
```

**Q23:** Show the query expansion behavior and explain why NXDOMAIN dominates.

**Q24:** Give two safe mitigations and one metric that proves the fix worked.

### Card D - API protocol mismatch

```text
Mobile app flow: product page load
REST calls before release: 7 calls, 180 KB total
GraphQL after release: 1 call, 2.8 MB response
Resolver fanout:
  ProductResolver -> 1 DB call
  SellerResolver -> 1 REST call
  ReviewResolver -> 80 REST calls
  RecommendationResolver -> 30 gRPC calls
HTTP status: 200 for 99.98% responses
GraphQL response body contains errors on 14% responses
```

**Q25:** What monitoring blind spot exists, and what dashboard should be added?

**Q26:** What guardrails should stop this query shape from becoming a production incident?

---

## Part 3: Compound SRE Scenario - Northstar Live Drop Edge Meltdown

This scenario requires TCP, HTTP, DNS, CDN, WebSockets, GraphQL, gRPC, and API design simultaneously.

```text
INCIDENT REPORT

Severity: P1
Company: Northstar Commerce
Event: Limited sneaker drop with live bidding for numbered pairs
Start time: 20:00 UTC
Active users: 920,000 browsers + 180,000 mobile clients
Revenue sensitivity: every minute of checkout confusion burns customer trust
Integrity sensitivity: displayed price and winning bidder must not be stale

ARCHITECTURE

  Browser/mobile
    -> Route 53
    -> CloudFront
       - static app shell
       - GraphQL product cards
       - REST checkout eligibility
       - HTTP/3 enabled two weeks ago

  Real-time updates
    Browser/mobile -> NLB -> 14 WebSocket gateway pods
    WebSocket gateway -> Redis Pub/Sub -> Drop event processor

  Purchase path
    BFF pods -> gRPC -> Allocation service (8 pods behind internal NLB)
    Allocation service -> PostgreSQL primary + 2 async replicas
    Allocation service -> fraud.partner-api.com

  Kubernetes
    EKS us-east-1
    CoreDNS handles service discovery
    NodeLocal DNSCache is deployed only in the payments namespace

  APIs
    GraphQL productCard includes:
      sku
      displayPrice
      inventoryRemaining
      bidderAlias
      timeRemaining
      personalizedEligibility

CHANGE WINDOW

  19:42 - CDN behavior changed for /graphql:
         from: Cache-Control: private, no-store
         to:   Cache-Control: public, s-maxage=45, stale-while-revalidate=120

  19:45 - BFF GraphQL query was expanded to include personalizedEligibility.

  19:50 - Allocation gRPC client pool was changed:
         max_channels_per_client: 1
         resolver: dns:///allocation.internal
         load_balancing_policy: pick_first

  19:55 - WebSocket ping interval was changed:
         from: 25s
         to:   disabled_when_event_stream_active=true

  19:58 - Fraud client was changed:
         hostname: fraud.partner-api.com
         dns_cache_ttl: 0

TIMELINE

T+0 / 20:00
  Drop begins.
  Users enter waiting room and product pages.
  CloudFront request rate rises to 310,000 req/sec.
  Allocation gRPC calls rise from 1,800/sec to 15,500/sec.

T+3 / 20:03
  Support reports:
    "My page says I am eligible but checkout says blocked."
    "Inventory says 317 left but live feed says sold out."
    "I see someone else's bidder alias in a product card."

T+5 / 20:05
  Product GraphQL telemetry:
    CDN hit ratio for /graphql: 0% -> 88%
    Age header on stale product cards: 12-44 seconds
    GraphQL HTTP 5xx: 0.02%
    GraphQL body errors: 11%
    origin RPS: 140,000 -> 18,000
    cache key: host + path + normalized query
    Authorization header forwarded to origin but not in cache key

T+7 / 20:07
  Allocation service telemetry:
    pod-1 CPU 97%, p99 2.4s
    pod-2 CPU 93%, p99 2.0s
    pod-3 CPU 11%, p99 40ms
    pod-4 CPU 10%, p99 41ms
    pod-5 CPU 9%, p99 39ms
    pod-6 CPU 10%, p99 40ms
    pod-7 CPU 11%, p99 42ms
    pod-8 CPU 10%, p99 40ms
    client connection count: 2 long-lived HTTP/2 connections carry 81% of RPCs

T+9 / 20:09
  WebSocket telemetry:
    connected clients: 1.1M
    reconnects: 58,000/min
    disconnect reason: tcp close from downstream
    regularity: drops cluster around 60s idle windows per SKU room
    gateway CPU: 52%, memory: 61%
    NLB TCP idle timeout: 350s
    corporate proxy idle timeout observed in RUM: 60s

T+12 / 20:12
  DNS telemetry:
    CoreDNS qps: 160,000 -> 690,000
    CoreDNS CPU: 97%
    NXDOMAIN: 74%
    top queried names include:
      fraud.partner-api.com.checkout.svc.cluster.local
      fraud.partner-api.com.svc.cluster.local
      fraud.partner-api.com.cluster.local
      fraud.partner-api.com.ec2.internal
      fraud.partner-api.com
    BFF DNS lookup p99: 4ms -> 280ms

T+15 / 20:15
  EU office and several enterprise customers report first page load of 9-13s.
  RUM shows:
    QUIC success global: 79%
    QUIC success affected networks: 4%
    HTTP/2 fallback success: 99.6%
    first navigation only: slow
    repeat navigation: normal

T+22 / 20:22
  Incident commander asks for immediate priorities.
  Legal flags possible privacy leak from product cards.
  Business asks whether to keep drop open.

CAPACITY NOTES

  Default ephemeral port range on BFF nodes: 32768-60999.
  BFF pods make one fraud call per allocation attempt.
  Fraud hostname has three dots, fewer than ndots:5.
  CloudFront invalidation propagation is 60-300 seconds.
  Current product-card TTL is 45 seconds plus stale-while-revalidate 120 seconds.
  Each stale eligible card can cause a failed allocation attempt.

BAD FIXES PROPOSED ON THE BRIDGE

  1. "Purge the entire CDN and keep the new public cache header."
  2. "Disable all WebSockets; polling every second is simpler."
  3. "Set gRPC max channels to 1000 immediately on every BFF pod."
  4. "Scale CoreDNS to 200 replicas and ignore ndots for now."
  5. "Disable HTTP/3 globally forever because one network blocks UDP."
  6. "Cache GraphQL by Authorization header to preserve hit ratio."
```

### Compound questions

**Q27 - Problem inventory:** Identify at least SIX distinct problems. For each, name the layer/protocol, root cause, and the telemetry that proves it.

**Q28 - Causal graph:** Draw the root cause -> amplifier -> symptom graph. Include at least three links where one failure makes another worse.

**Q29 - Priority order:** Rank the first five mitigations. Consider security/privacy, auction/drop integrity, user impact, reversibility, and blast radius.

**Q30 - Immediate commands/config:** Give concrete first actions for CDN/GraphQL caching, gRPC balancing, WebSocket heartbeats, DNS search expansion, and HTTP/3 fallback.

**Q31 - Bad fix rejection:** For each proposed bad fix, state why it is unsafe or incomplete and what to do instead.

**Q32 - Capacity math:** Estimate the DNS query amplification from fraud lookups at 15,500/sec. Explain how retries from stale eligibility cards change the number.

**Q33 - Verification plan:** List the before/after metrics that prove each mitigation worked. Include cache, DNS, gRPC, WebSocket, and RUM signals.

**Q34 - Org/runbook:** Who must be in the incident room by T+15, what customer/legal comms are needed, and which actions require senior approval?

---

## Part 4: Additional Rich Diagnostic Stems (Q35-Q44)

These are still questions only. Use them to test whether you can transfer Week 1 mechanisms to smaller, unfamiliar incidents.

### Card E - HTTP/2 origin regression after CDN optimization

```text
Change:
  CDN-to-browser supports HTTP/3 and HTTP/2.
  CDN-to-origin was changed from HTTP/2 keep-alive to HTTP/1.1 short connections
  because an origin team wanted easier packet captures.

Traffic:
  browser requests/sec: 210,000
  CDN origin miss ratio: 3.5%
  origin requests/sec after cache misses: 7,350

Origin telemetry:
  new TCP connections/sec from CDN: 6,900
  established connections average age: 1.2s
  TLS handshakes/sec: 6,700
  origin CPU: 48% -> 89%
  upstream connect time p95: 8ms -> 220ms
  response generation p95: unchanged at 35ms
  CDN x-edge-result-type: Miss and RefreshHit spike together

Network notes:
  packet loss on one ISP path: 1.5%
  HTTP/2 browser sessions on that path show p99 object latency 2.8s
  HTTP/1.1 fallback users are slower on median but fewer objects stall together

Tempting fixes:
  - disable HTTP/2 to browsers globally
  - double origin pods
  - raise CDN TTL on personalized API responses
```

**Q35:** Separate the origin regression from the browser-path packet-loss symptom. Which part is HTTP/1.1 short-connection churn, and which part is HTTP/2-over-TCP head-of-line blocking?

**Q36:** What metrics prove origin work itself is not the slow component? What first mitigation restores origin efficiency without changing user-facing protocol support?

**Q37:** Reject each tempting fix. Which one risks a correctness/security regression rather than just a performance regression?

### Card F - DNS migration with recursive resolver drag

```text
Planned migration:
  api.northstar.example moves from 203.0.113.10 to 198.51.100.25
  original TTL: 86400
  new TTL set to 30 at 10:00
  IP changed at 10:05

Observed at 11:00:
  63% of traffic reaches new IP
  37% still reaches old IP
  one mobile carrier resolver still serves old answer with TTL remaining 77,000s
  browser clients using DoH to public resolvers mostly moved within 60s

Old origin state:
  still serving reads
  write endpoint disabled
  returns 307 to new host for POST /checkout
  some mobile clients do not preserve Authorization header across cross-host redirect

Tempting fixes:
  - shut down old IP to force clients over
  - change DNS provider again
  - keep cross-host redirect for all methods
```

**Q38:** Explain exactly why the TTL lowering failed. What should have happened before the migration window?

**Q39:** What is the safest old-origin behavior for reads and writes while recursive caches drain? Discuss redirects, auth headers, and idempotency.

**Q40:** What telemetry tells you whether remaining old-IP traffic is cache drag, client pinning, or a routing/BGP issue?

### Card G - WebSocket retry storm meets ephemeral ports

```text
Realtime notifications:
  420,000 WebSocket clients connected through a regional edge
  deploy restarts 40% of gateway pods over 2 minutes
  client retry config:
    first retry: 1s
    multiplier: 2
    max: 30s
    jitter: disabled

Edge gateway telemetry:
  reconnect attempts at T+1s, T+2s, T+4s, T+8s form sharp spikes
  successful reconnects: 38,000/sec at peak
  failed connects: 21,000/sec at peak
  TIME_WAIT on gateway nodes: 44,000 per node
  ip_local_port_range: 32768 60999
  CPU: 54%, memory: 62%

Load balancer:
  healthy targets: enough for steady state
  SYN backlog drops: elevated during retry spikes
```

**Q41:** Which two retry components are missing or insufficient? Explain why exponential backoff without jitter still creates synchronized waves.

**Q42:** How can a WebSocket reconnect storm produce TCP symptoms such as `TIME_WAIT` and SYN backlog drops even when application CPU is healthy?

**Q43:** Give a client-side and a server-side mitigation that can be rolled out safely during the incident.

**Q44:** What post-incident test would prove the reconnect policy is safe before the next deploy?

---

## Self-score

| Error type | Did it happen? | Note |
|------------|----------------|------|
| Layer confusion | | |
| Cached personalized data missed | | |
| gRPC/L4 mechanism missed | | |
| DNS ndots math missed | | |
| Unsafe first mitigation | | |
| Capacity math skipped | | |
| Org/legal blast radius ignored | | |

---

> **Answer key (do not open until you attempt the Ops Sim / questions):**
> [`../answers/Retention-Tests/Week-01 Answers.md`](../answers/Retention-Tests/Week-01%20Answers.md)
