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
