# Week-08b Retention Test

Questions only. Attempt without opening answers. This spaced mix
references Weeks 1-8 plus Week-08b trust, cost, and multi-tenancy. Show
math where numbers are provided and name the layer for every incident
question.

## Part 1: Rapid-fire mechanism checks

1. Week 1 DNS/CDN: A CloudFront distribution serves another user's
   personalized cart for 90 seconds after deploy. Which cache key or
   header mistake is most likely, and what evidence would prove it?
2. Week 1 TCP/HTTP: An HTTP/2 service has one slow stream causing many
   requests from the same client to appear slow. What is the mechanism,
   and how is it different from HTTP/1.1 connection limits?
3. Week 2 storage: An LSM database shows high write latency after
   compaction falls behind. Name two leading metrics and one bad fix.
4. Week 3 distributed systems: A service times out and retries a
   non-idempotent payment capture. Which guarantee is missing, and what
   key should exist?
5. Week 4 replication: A leader accepts writes during a network
   partition and later loses leadership. Which consistency property is
   at risk?
6. Week 5 database internals: A PostgreSQL query is slow only for one
   large tenant. What plan/cache/index issue could explain this?
7. Week 6 Kafka/outbox: Consumer lag grows while producer rate is
   normal. Name three possible bottlenecks at different layers.
8. Week 7 feature flags: A tenant-scoped flag accidentally enables
   globally. What config or evaluation-context test should have caught
   it?
9. Week 8 observability: Why is tenant_id on every HTTP latency metric
   dangerous, and what alternate telemetry pattern preserves visibility?
10. Week 08b Auth: A valid JWT is rejected by one service but accepted
    by another. Name four validation/config differences to compare.
11. Week 08b Cost: Define cost per successful order and name three costs
    that teams often forget.
12. Week 08b Multi-tenancy: Why does tenant_id in a table not by itself
    prevent cross-tenant leakage?

## Part 2: Scenario questions

1. A new Cognito signing kid appears at 10:00. At 10:03, checkout 401s
   spike, JWKS 429s spike, and session Redis is normal. What is the
   likely layer, first mitigation, and one fix you must reject?
2. Northstar adds a seller analytics route that scans raw us-east-1 S3
   from eu-west-1 every 30 seconds. Cross-region bytes rise 6x, seller
   dashboards lag, checkout is healthy. What is the root cost driver and
   the first safe degradation?
3. Seller_9000 runs an import that opens 500 DB connections. Checkout
   for unrelated sellers on the same shard times out. What limiter
   should have existed, and why is raising max_connections risky?
4. A Redis key product:123 stores tenant-specific price data. Two
   sellers both have product 123. What bug class is this, how do you
   mitigate immediately, and what test prevents recurrence?
5. Kafka topic checkout.events uses tenant_id as the partition key. One
   celebrity seller drives 70% of bytes and one broker hits 95% network.
   What is wrong with the partitioning/fairness design?
6. Finance says campaign cost per order is $0.24, break-even is $0.18,
   and volume is 120,000 successful orders/min. How many dollars per
   hour above break-even is the campaign burning?
7. A mTLS mesh rollout causes gRPC UNAVAILABLE only from checkout-api to
   pay-ledger. What certificate/trust-bundle signals do you inspect
   before scaling pods?
8. A Secrets Manager DB password rotation promotes AWSCURRENT, but new
   PgBouncer connections fail while old pooled connections work. Which
   rotation step was insufficient?
9. A support tool exports orders by order_id without tenant context.
   Logs show one request from support during an incident. What evidence
   must be preserved and who joins the channel?
10. A feature flag lowers CDN TTL to 0 for all product pages during a
    sale to fix freshness. Origin traffic and egress explode. Which
    prior-week and Week-08b concepts are involved?

## Part 3: Decision drills

1. Choose server-side session or bearer access token for browser
   checkout. State the replay, revocation, and XSS tradeoffs.
2. Choose shared table, schema per tenant, database per tenant, or
   cell-based tenancy for 50,000 small sellers plus 40 enterprise
   sellers with bursty auctions. Give a mixed answer.
3. Choose on-demand, Savings Plan, reserved DB, spot, or serverless for
   a stable 24x7 checkout API, nightly interruptible image jobs, and a
   new unknown analytics feature.
4. Design a fair-share limiter for seller analytics that protects
   checkout, supports enterprise contracts, and avoids tenant_id
   cardinality explosion in metrics.
5. A team wants to cut 30% of EKS nodes because average CPU is 22%. List
   the minimum evidence required before approving.
6. A JWT has iss correct, exp valid, signature valid, but aud is
   seller-admin while the request is checkout-api. What is the exact
   failure and why is accepting it dangerous?
7. A tenant migration plan moves 2 TB of seller data to a new shard.
   List the routing, dual-write, rollback, and blast-radius checks.
8. A cost anomaly is driven by observability ingest after trace sampling
   was set to 100% during an incident. What control prevents recurrence
   without removing incident debug power?

## Part 4: Mini Ops Sim question

You are incident commander for Northstar at T+0. Auth 401s, Kafka lag,
Redis evictions, and cost anomaly all fire within 20 minutes of a
flash-sale deploy. Write a five-step triage order that separates
independent failures from shared causes. For each step, name one metric
and one bad fix you would explicitly reject.
