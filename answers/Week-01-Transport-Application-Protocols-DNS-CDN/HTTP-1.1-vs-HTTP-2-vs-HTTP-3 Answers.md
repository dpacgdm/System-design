# Answer Key — HTTP-1.1-vs-HTTP-2-vs-HTTP-3

> Open only after attempting the learner file questions.

## Expert Analysis

---

## Ops Sim: Northstar Mobile Checkout Protocol Regression

### Q1 - Layer & root cause

This is primarily request fan-out plus protocol fallback, not slow backend work.

- Fan-out: the mobile screen changed from bundled reads to 42 items x 3 calls = 126 XHRs.
- HTTP/1.1 target group: ALB speaks HTTP/1.1 to `checkout-api`, so backend concurrency is bounded by connection pools and per-origin browser limits.
- HTTP/3 failure: carrier/corporate paths attempt QUIC, time out, then fall back to TCP/TLS.

Backend handler p95 of 22ms proves individual calls are fast; the page is slow because there are too many calls and slow connection setup/fallback.

### Q2 - Evidence

Confirming signals:
1. Mobile XHR count changed from 9 to 126 per checkout page.
2. RUM degradation is network-sensitive: LTE p95 8.1s vs broadband 2.3s.
3. HTTP/3 attempt rate is high but success is only 11%, with client logs showing QUIC timeout fallback.

Misleading green metric: ALB target response time. It measures each target request, not the user's full page composed of 126 requests.

### Q3 - First 15 minutes

1. Keep the fraud banner, but flip `bundle_endpoint_enabled=true` and `per_item_endpoints=false` for checkout data.
2. Reduce or strip `Alt-Svc` max-age for affected mobile carrier ASNs, or disable HTTP/3 only on the checkout behavior while leaving static assets untouched.
3. Verify RUM LCP, XHR count, h3 success rate, ALB RequestCountPerTarget, and checkout abandonment.
4. Avoid full release rollback unless the targeted flags fail.

### Q4 - Bad fixes

Scaling `checkout-api` is incomplete because each request is already fast. It may absorb some amplified traffic but does not reduce 126 client round trips or QUIC fallback delay.

Disabling HTTP/3 globally is overbroad because successful consumer networks and static asset paths may benefit from QUIC. Prefer behavior/segment-specific mitigation or lowering `Alt-Svc` max-age.

### Q5 - Capacity / blast radius

Request amplification:

```text
42 cart items x 3 endpoints = 126 data calls/page
Previous page ~= 9 calls
Amplification = 14x
```

If auction traffic doubles, the amplified backend call volume is roughly 28x the old baseline. ALB target keep-alive pools, app worker queues, and downstream inventory/promo services can saturate even while per-call latency stays low.

### Q6 - Durable fix

Contract:
- Browser/mobile screens call bounded bundle/BFF endpoints.
- Internal fan-out uses HTTP/2/gRPC with server-side parallelism and budgets.
- CI/performance gates assert max client calls per screen and RUM budget by network type.
- Edge policies require explicit canary by protocol/ASN before long `Alt-Svc` max-age.

Acceptance criteria: checkout mobile LCP p95 < 2s on LTE, data calls/page < 15, HTTP/3 fallback penalty visible in RUM, and ALB RequestCountPerTarget within 2x pre-release baseline.

## Question 1: Root Cause — Request Amplification + Protocol Downgrade

**Root cause:** Microservice endpoint split multiplied browser-visible requests 40× while
ALB terminated HTTP/2 from clients but spoke HTTP/1.1 to backends — serializing fan-out.

```
REQUEST MATH (listing page, 50 products):

  BEFORE deploy: 1 aggregated response (or 1 + image CDN hits)
  AFTER deploy:  50 products × 4 endpoints = 200 API calls per page view

PROTOCOL PATH:

  Browser ──HTTP/2──► CloudFront ──HTTP/2──► ALB ──HTTP/1.1──► 12 backends
                              multiplexed              6 conn/host max
                                                       serial queue

WHY BACKEND p50=15ms BUT PAGE=4.2s:
  Per-request latency is fine. User-perceived time = batches × RTT.
  200 requests / 6 parallel = ~34 sequential batches
  Desktop RTT ~20ms → ~680ms minimum (observed ~1.1s with TLS/overhead — before deploy)
  Same pattern post-deploy with 200 requests → multi-second loads

DEPLOYMENT CORRELATION:
  git diff shows endpoint split 2h before symptom onset — causal, not coincident.
  CloudFront hit rate 94% unchanged → not a CDN/cache problem.
  Backend CPU 30% → not compute saturation.
```

```
╔═════════════════════════════════════════════════════════════════╗
║  SIGNAL                 │ VALUE            │ WHAT IT TELLS YOU  ║
╠═════════════════════════════════════════════════════════════════╣
║  Backend p50 latency    │ 15ms             │ Each request fast —║
║                         │                  │ NOT a slow DB      ║
╠═════════════════════════════════════════════════════════════════╣
║  Page load time         │ 4.2s (was 1.1s)  │ Fan-out count, not ║
║                         │                  │ per-request speed  ║
╠═════════════════════════════════════════════════════════════════╣
║  Deployment timing      │ 2h ago, split    │ Causal — request   ║
║                         │ endpoints        │ count multiplied   ║
╚═════════════════════════════════════════════════════════════════╝

```
50 products × 4 endpoints = 200 backend requests per page load
ALB → backend HTTP/1.1: requests serialize on limited keep-alive pool
```

---

## Question 2: Why Mobile Users Are More Affected

```
Mobile RTT ~120ms (LTE) vs desktop ~20ms. With 200 serial HTTP/1.1 backend
requests and ~6 parallel connections per host:
  batches ≈ 34 × 120ms ≈ 4.1s minimum (matches observed 4.2s page load)

Radio state transitions and app background/foreground churn connection pools.
QUIC fallback adds timeout if UDP/443 blocked on corporate WiFi.
Backend p50 15ms is irrelevant — user time = f(RTT, request count, parallelism).
```

---

## Question 3: Immediate Mitigation

```
MINUTE 0-2: Revert deployment OR deploy BFF /api/product/{id}/bundle
MINUTE 2-5: ALB logs — verify requests/page drops from ~200 to <10
MINUTE 5-10: Enable HTTP/2 to backends if keeping split (ALPN h2 on targets)
WATCH: RUM LCP 4.2s → ~1.1s; TargetResponseTime stays ~15ms
```

---

## Question 4: Long-Term Fix

```
1. BFF per client — server-side parallel fan-out (GraphQL + DataLoader)
2. HTTP/2 end-to-end ALB → backend with sufficient concurrent streams
3. Edge aggregation for cacheable public catalog (CloudFront Functions)
NEVER: N microservice endpoints directly to browser over HTTP/1.1
CI: load test asserts requests/page < 15; alarm RequestCountPerTarget > 3× baseline
```

---

## Incident Scenario (Extended): QUIC Fallback Storm

```
INCIDENT REPORT #2
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Severity: P2 → P1 (EU enterprise segment)
Service: SaaS dashboard (global, CloudFront + ALB)
Time: 09:00 CET Monday (enterprise login peak)

ARCHITECTURE:
  CloudFront: HTTP/3 enabled, Alt-Svc: h3=":443"; ma=86400
  Origin: ALB → 24 EC2 instances (HTTP/2)
  Users: 40% mobile, 35% desktop, 25% enterprise (Zscaler proxy)

SYMPTOMS (EU enterprise only):
  - Page load p99: 8.2s (US: 1.1s, EU mobile: 1.3s)
  - CloudFront metrics: HTTP/3 attempt rate 100%, success rate 12%
  - TCP fallback succeeds but after 3-5s QUIC timeout per connection
  - No origin errors; TTFB from origin normal when request arrives

ROOT CAUSE:
  Corporate firewalls block UDP/443. Browser honors Alt-Svc, tries QUIC first,
  waits for QUIC timeout, then falls back to TCP. ma=86400 keeps retrying
  QUIC on every navigation for 24 hours.

QUESTIONS:
  Q1: Why US users unaffected?
  Q2: Immediate mitigation without disabling HTTP/3 globally?
  Q3: Long-term architecture for enterprise + consumer on same domain?
  Q4: How do you detect this in RUM before ticket volume spikes?
```

### Expert Analysis — QUIC Fallback

**Q1:** US consumer networks rarely block UDP/443. EU enterprise Zscaler/proxy
users hit firewall policy. Geographic + client-segment correlation is the tell.

**Q2:**
```bash
# Reduce Alt-Svc max-age during incident (origin response header)
Cache-Control: private
Alt-Svc: h3=":443"; ma=300

# CloudFront: create behavior for enterprise ASN list → HTTP/2 only
# Or Lambda@Edge: strip Alt-Svc for User-Agent matching corporate patterns

# Fastest: CloudFront disable HTTP/3 on affected distribution behavior
# (AWS Console → Behaviors → HTTP/3 → disable — propagates ~5 min)
```

**Q3:** Split hostnames: `app.example.com` (HTTP/3 for consumer) and
`enterprise.example.com` (HTTP/2 only, IP allowlist). Or client hints /
CDN geolocation policy. Never assume QUIC works because lab tests pass.

**Q4:** RUM metrics by ASN and protocol version:
```javascript
// Log: navigation.protocol, connection.rtt, geo.asn, time_to_first_byte
// Alert: HTTP/3 success rate < 50% for any ASN for 15 min
// CloudFront real-time logs: sslProtocol, cs(Client) ASN if enriched
```

---
