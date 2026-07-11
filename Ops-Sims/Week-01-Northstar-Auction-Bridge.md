# Ops Sim: Week 01 - Northstar Auction Bridge

**Time box:** 45 minutes
**Severity:** P1
**Service / domain:** CloudFront, DNS, HTTP/2/gRPC, WebSockets, TCP
**Northstar system:** Edge, Bid WebSocket, API, Checkout

## Rules

1. Answer from memory of Week 1 modules.
2. Work in order: T+0 -> T+5 -> T+15 -> T+60.
3. Name evidence for every claim.
4. Do not open the answer key until finished.

---

## 1. Scenario stem

```text
WHAT USERS SEE:
  A live auction page loads slowly on mobile, bid updates freeze, and a subset
  of winners cannot complete checkout. Some users in EU still hit an old ALB
  after edge failover.

WHAT ON-CALL SEES:
  Bid writes are healthy. WebSocket delivery lag and mobile page LCP are bad.
  checkout-api connect timeouts rise only on pods handling auction settlement.

BUSINESS CONSTRAINT:
  The auction closes in 20 minutes. Accepted bid order must remain authoritative
  server-side. Checkout may degrade, but duplicate charges and stale winner
  displays are unacceptable.
```

---

## 2. Telemetry pack

```text
EDGE / DNS:
  CloudFront h3 attempt rate=39%, h3 success=14% on EU mobile carriers
  checkout.northstar.example: 8.8.8.8=old ALB, 1.1.1.1=new ALB
  authoritative TTL=300s; JVM cache ttl=-1 on checkout settlement workers

HTTP / API:
  mobile auction XHR count per page: 11 -> 168
  ALB target protocol to gateway: HTTP/1.1
  gateway handler p95: 26ms; RUM mobile LCP p95: 8.6s
  GraphQL AuctionPage HTTP 200 with errors path=["auction","seller"]

WEBSOCKET:
  concurrent_ws: 790k -> 530k -> 780k sawtooth every 60s
  ws_reconnect_attempts: 420k/min
  bid_delivery_lag_p99: 480ms -> 9.1s
  CloudFront origin_response_timeout_seconds changed 300 -> 60

TCP / CHECKOUT:
  checkout_api_db_connect_timeout_total: 0 -> 3,200/min
  TCP TIME_WAIT per settlement pod: 44k; ephemeral range=28,232 ports
  app log: connect: cannot assign requested address
  SQL execution p99 when connected: 19ms
```

---

## 3. Config pack

```yaml
cloudfront:
  http_version: http3
  origin_response_timeout_seconds: 60
mobileAuction:
  bundle_endpoint_enabled: false
  per_item_endpoints: true
  max_parallel_xhr: 6
ws_client:
  heartbeat_interval_seconds: 75
  reconnect_backoff: fixed
  reconnect_delay_ms: 1000
checkoutSettlement:
  use_shared_pool: false
  connect_per_bid: true
dns:
  java_networkaddress_cache_ttl: -1
```

---

## 4. Timeline & decision points

| Time | Event | Your move (write before reading further) |
|------|-------|------------------------------------------|
| T+0 | P1 page: auction UX degraded; bid write service healthy. | |
| T+5 | You identify 60s WebSocket reconnect waves and HTTP request fan-out. | |
| T+15 | Checkout settlement pods show port exhaustion; EU still has stale DNS clients. | |
| T+60 | Auction closes; bid order is intact, but checkout backlog remains. | |

---

## 5. Questions

**Q1 - Layer map:** For each symptom, identify the owning layer: DNS, CDN/HTTP, WebSocket, gRPC/API, or TCP.

**Q2 - Evidence:** Pick the 6 strongest signals and explain what each proves. Include one red herring.

**Q3 - Sequencing:** Write the first 15-minute mitigation plan. Preserve bid correctness and avoid creating a reconnect or DB connection storm.

**Q4 - Bad fix gallery:** Reject these fixes with reasons:
- scale every backend 5x
- purge DNS records for the old ALB
- disable all reconnects
- raise Postgres `max_connections`

**Q5 - Capacity / blast radius:** Estimate:
- mobile request amplification for 56 auction items at 3 calls/item
- reconnect subscription load for 250k clients x 24 channels
- unsafe new DB connect rate per pod with 28,232 ephemeral ports and 60s TIME_WAIT

**Q6 - Durable fix:** Name the Week 1 guardrails that should exist before the next auction.

**Q7 - Org / runbook:** Who is informed by T+10? Which degradations are pre-authorized?

---

## 6. Self-score

| Error type | Did it happen? | Note |
|------------|----------------|------|
| Wrong layer | | |
| Sequencing error | | |
| Capacity miss | | |
| Bad fix accepted | | |
| Org/runbook miss | | |

**Answer key:** [`../answers/Ops-Sims/Week-01-Northstar-Auction-Bridge Answers.md`](../answers/Ops-Sims/Week-01-Northstar-Auction-Bridge%20Answers.md)
