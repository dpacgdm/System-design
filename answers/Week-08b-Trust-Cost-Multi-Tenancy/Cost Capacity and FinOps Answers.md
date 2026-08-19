# Cost Capacity and FinOps Answers

Open only after attempting the learner file Ops Sim.

## The Sale Is Profitable Until the Cloud Bill Arrives

### Q1 - Mechanism

The primary cost driver is data movement and raw
analytics shape. The new feature runs in eu-west-1 while
reading raw us-east-1 events every 15 seconds, mirrors
broad Kafka topics without compression, and emits 100%
traces. Kafka lag and OpenSearch latency are capacity
consequences of the same bad data path, not the source
of the spend.

### Q2 - Evidence

- Cross-region bytes rise from 1.1 TB/h to 9.8 TB/h and
  NAT bytes from 140 GB/h to 3.2 TB/h.
- Deploy diff changes source from curated eu-west-1
  table to raw us-east-1 checkout.events.
- Cost allocation shows data transfer, NAT, and
  observability ingest dwarf compute-hour increases.
- Red herring: checkout-api p99 rose modestly but
  checkout is not the spend driver.

### Q3 - First 15 minutes

1. Declare cost/capacity incident with finance and
   product in channel because unit economics crossed
   break-even.
2. Disable or restrict live_margin_by_region for
   standard tenants; keep enterprise path only if
   required by contract.
3. Switch source back to curated regional data or run
   the job near raw data until curated eu-west-1 catches
   up.
4. Restore trace sampling to normal or tail-based
   incident policy with expiry.
5. Enable compression and narrow mirrored topics if
   safe; pause clickstream.raw replication if not
   needed.
6. Do not reduce checkout capacity and do not 4x
   OpenSearch until source data movement is corrected.

### Q4 - Bad fixes

- Scaling OpenSearch may reduce indexing latency but
  leaves cross-region raw scans, NAT transfer,
  uncompressed Kafka mirror, and trace ingest intact.
- Reducing checkout capacity lowers successful orders
  and risks retries, support load, and lost revenue;
  unit cost can worsen.
- Turning off all analytics may breach enterprise
  contracts; tier-aware degradation is safer.

### Q5 - Unit math

Cost is above break-even by $0.236 - $0.19 = $0.046 per
order. At 310,000 orders per minute, that is $14,260 per
minute or $855,600 per hour above break-even.

### Q6 - Durable fix

- Run analytics where data lives or replicate curated
  compressed aggregates, not raw event firehoses.
- Every analytics feature declares source dataset,
  refresh interval, scan bytes, tenant tier, and max
  cost per report.
- Set quotas for Kafka mirror topics, OpenSearch bulk
  ingest, dashboard concurrency, and NAT/VPC endpoint
  paths.
- Sampling defaults need incident override expiry and
  cost anomaly by feature/deploy tag.
- Acceptance: cost per order below $0.19 during load
  test, dashboard p95 in contract, cross-region bytes
  within budget, rollback flag tested.

### Q7 - Org

By T+10 include incident command, seller analytics
owner, checkout owner, finance, product lead, enterprise
support/customer success, and networking/platform if NAT
or endpoints are involved. Finance owns break-even
facts; product owns degradation tradeoffs; engineering
owns safe mitigations; support owns customer
communication.

## Expanded Ops Sim Worked Analysis

### 1. Signal inventory

- Read unit cost beside success volume: dollars per successful order, not just hourly spend.
- Break down cost by compute, DB, Kafka, OpenSearch, S3 scan bytes, cross-AZ, cross-region, NAT, third-party API, and observability.
- Tag cost by deploy, feature flag, tenant tier, region, and data source.
- A cost anomaly without feature/deploy dimensions becomes a finance mystery instead of an incident.

### 2. Timeline reconstruction

- Mark the analytics deploy, source dataset switch, trace sampling change, Kafka mirror config, and first unit-cost breach.
- Separate checkout traffic growth from data movement growth.
- Correlate dashboard lag with index/consumer backlog but do not assume the slow sink is the spend root.
- Use derivative metrics: bytes/hour and dollars/hour above break-even.

### 3. Root cause statement

- The likely root cause is a data-locality and observability mistake: raw us-east-1 events are repeatedly scanned or mirrored into eu-west-1 at high frequency.
- NAT and cross-region bytes dominate because the feature moved data instead of moving compute or using curated regional aggregates.
- OpenSearch or Kafka lag may be symptoms of ingestion shape, not the first cost driver.
- Checkout being healthy means cutting checkout capacity is not a root-cause fix.

### 4. Unit economics math

- Cost per successful order = allocated cost for the checkout/sale domain divided by successful orders.
- If cost rises from $0.19 break-even to $0.236 at 310k orders/min, burn is $0.046 * 310k = $14,260/min.
- Hourly burn is $855,600/hour; this is urgent even if customer-facing latency is only moderately degraded.
- Always report both margin delta and absolute dollars/hour so product and finance can decide degradation.

### 5. First 15 minutes

- Declare cost/capacity incident with finance, product, analytics, and platform present.
- Disable or tier-limit live analytics for standard tenants; protect enterprise obligations explicitly.
- Switch back to curated regional data or run the job near the raw data.
- Restore trace sampling to tail/error or incident profile with automatic expiry.

### 6. What not to do

- Do not reduce checkout capacity first; retries and failed orders can worsen unit cost and revenue.
- Do not 4x OpenSearch before stopping the source firehose.
- Do not turn off all analytics if enterprise contracts require it; degrade by tier and freshness.
- Do not rely on monthly cost reports; this incident burns money by the hour.

### 7. Data movement analysis

- Cross-region S3 reads charge for transfer and add latency; repeated raw scans multiply both.
- NAT gateway bytes often appear when private workloads reach public endpoints instead of VPC endpoints or regional services.
- Kafka mirror without compression and filtering can replicate low-value clickstream bytes at peak sale rates.
- Trace payloads can be larger than the business events they describe.

### 8. Capacity analysis

- Capacity is not only CPU. It includes indexer bulk queue, Kafka broker network, NAT throughput, S3 request rate, consumer lag, and dashboard concurrency.
- Backlog age matters more than queue length when refresh SLO is user-facing.
- Headroom must be reserved for checkout even while analytics is degraded.
- Use workload classes: checkout, enterprise analytics, standard analytics, offline backfill, and observability.

### 9. Safe degradations

- Lower analytics freshness from 15 seconds to 5 minutes for standard tenants.
- Serve cached aggregates with staleness labels rather than raw live scans.
- Sample traces by error/tail and keep 100% only for a scoped tenant/cell with expiry.
- Pause low-value mirrored topics and preserve payment/order topics.

### 10. Cost guardrails

- Every feature declares max scan bytes, max cross-region bytes, expected unit cost, and rollback flag.
- Alerts page on cost per successful order and hourly burn above break-even.
- Sampling overrides require owner, reason, target scope, and expiry.
- Dashboards show top cost deltas by deploy and feature, not only service.

### 11. Telemetry queries

- Group CUR or cost telemetry by resource tag: feature=seller-live-margin, deploy=v18, tenant_tier, region.
- Compare `nat_gateway_bytes`, `s3_bytes_scanned`, `kafka_mirror_bytes`, `trace_ingest_bytes`, and `opensearch_bulk_bytes`.
- Join success-order counts with cost windows to calculate real unit cost.
- Track retry rate because retries can increase compute cost while successful order count falls.

### 12. Organizational ownership

- Finance owns break-even and escalation threshold.
- Product owns degradation policy and tenant contractual tradeoffs.
- Analytics owns data source and refresh interval.
- Platform owns quotas, NAT/VPC endpoints, observability controls, and cost dashboards.

### 13. Durable design

- Move compute to data or replicate curated aggregates; avoid raw cross-region loops.
- Use regional materialized datasets for dashboards.
- Add feature launch gates for unit cost at target scale and peak multiplier.
- Reserve checkout capacity and make analytics consume leftover or separately purchased capacity.

### 14. Acceptance criteria

- Load test proves cost/order remains below break-even at sale peak.
- Trace override expires automatically and alerts before ingest doubles.
- Cross-region and NAT bytes stay within budget after analytics deploy.
- Degradation flag lowers analytics cost within five minutes without reducing checkout success.

## Additional Ops Sim Drills

### Runbook drill: raw scan multiplier

- Give a dashboard query a 15-second refresh and 500 tenants.
- Expected calculation: scan_bytes * refreshes_per_hour * tenants * regions.
- Fail condition: design review reports only one query cost.
- Guardrail: max bytes/hour per feature and precomputed aggregates.

### Runbook drill: NAT surprise

- Route analytics traffic through NAT instead of VPC endpoint or regional private path.
- Telemetry: nat_gateway_bytes, destination service, route table version, and deploy tag.
- Mitigation: switch endpoint/path after verifying security groups and DNS.
- Fail condition: scaling consumers increases NAT burn.

### Runbook drill: trace override

- Set 100% sampling for one incident scope with an expiry and owner.
- Expected behavior: automatic reversion and alert on ingest slope.
- Fail condition: global 100% sampling persists after incident close.
- Metric: trace_ingest_bytes by service, tenant tier, and override id.

### Runbook drill: retry cost

- Inject downstream 500s and observe client retries.
- Expected behavior: retry budgets cap extra calls and preserve idempotency.
- Cost model includes failed attempts, not just successful orders.
- Fail condition: retries triple compute while successful order count drops.

### Procurement versus engineering

- Reserved capacity lowers rate for stable workloads but cannot fix bad query shape.
- Spot is appropriate only for checkpointed interruptible jobs, not checkout critical path.
- Serverless helps unknown shape but needs concurrency and spend caps.
- FinOps decisions need latency and reliability context, not only discount percentage.

### Feature launch checklist

- Declare business unit and target scale.
- Estimate steady-state and peak cost per unit.
- List dominant line items and owners.
- Define kill switch, tier degradation, and cost alert before launch.

### Incident communication

- Finance states break-even and dollars/hour risk.
- Product states acceptable freshness and tenant contractual minimums.
- Engineering states safe levers and blast radius.
- Customer success handles enterprise messaging when analytics is degraded.

### Post-incident artifacts

- Add cost dashboard panels for unit cost, raw scan bytes, NAT bytes, trace ingest, and retry amplification.
- Backfill tags on resources created by the feature.
- Write a prevention item for data-locality review.
- Run a sale-load test with cost assertions, not only latency assertions.

### Final acceptance note

- The feature is safe to re-enable only when product, finance, and engineering can point to the same unit-cost graph and the rollback flag has been tested under load.


---
