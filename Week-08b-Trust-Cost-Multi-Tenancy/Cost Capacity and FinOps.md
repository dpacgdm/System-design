# Cost Capacity and FinOps

Cost is a production signal. At Northstar Commerce, a
checkout incident can be caused by a database queue, a
Kafka lag spike, a CDN cache miss, or a runaway
cross-region egress bill that forces emergency
throttling. Capacity is the engineering side of the same
coin: how much work a system can absorb at a target
latency and failure rate. FinOps is the operating model
that connects unit economics, forecasts, reservations,
rightsizing, architecture choices, and accountability.

## Learning objectives

1. Compute unit economics for requests, orders, sellers,
   tenants, messages, GB transferred, and GB-month
   stored.
2. Identify hidden cost drivers: egress, idle resources,
   observability cardinality, over-replication, cross-AZ
   transfer, NAT gateways, and control-plane churn.
3. Translate p50, p95, p99 load and seasonality into
   capacity plans with headroom, error budget, and
   failover assumptions.
4. Choose right-sizing, autoscaling, reserved capacity,
   savings plans, spot, serverless, or redesign based on
   workload shape.
5. Explain the cost of consistency: synchronous
   replication, quorum reads/writes, multi-region
   writes, CDC fanout, and exactly-once business
   effects.
6. Create cost-aware SLO and capacity worksheets that
   preserve reliability while making tradeoffs explicit.
7. Build telemetry packs for cost incidents: cost
   anomaly, utilization, request rate, queue depth,
   egress, reservation coverage, and per-tenant spend.
8. Reject bad fixes that lower today's bill by creating
   tomorrow's outage, compliance failure, or
   customer-visible throttling.
9. Use AWS examples accurately: EC2, EKS, RDS, DynamoDB,
   MSK, OpenSearch, S3, CloudFront, NAT Gateway, Savings
   Plans, and Cost Explorer.
10. Communicate with finance, product, incident command,
    and service owners using unit metrics instead of
    vague statements about expensive infrastructure.

## Wrong mental models

| Wrong model | Correction | Why it hurts |
| --- | --- | --- |
| Cost optimization means cutting resources | Optimization means matching capacity shape to work and risk. | Teams remove headroom and pay through incidents. |
| CPU average tells us rightsizing | Average hides p99 saturation, burst shape, throttling, memory, and IO. | A pod at 35% average can fail during auctions. |
| Reserved is always cheaper | Commitments are cheap only for predictable stable baselines. | A migration strands three years of unused capacity. |
| Serverless means no capacity planning | Limits move to concurrency, cold start, downstreams, and per-request cost. | Lambda scales into RDS until connections collapse. |
| Egress is a networking detail | Egress is a data-locality and margin constraint. | Cross-region reads silently erase campaign profit. |
| Storage is cheap | Hot indexed storage, WAL, snapshots, replicas, and logs are not cheap. | Debug indexes and traces live forever. |
| Autoscaling fixes capacity | Autoscaling reacts late and can overload dependencies. | App scale turns DB queue into DB outage. |
| FinOps is finance job | Engineers choose replication, data movement, retention, and cardinality. | No one owns cost until invoice shock. |
| Cost dashboards are enough | Dashboards lag unless tied to deploys, tenants, and unit metrics. | A bad release burns a week of budget. |
| Idle reserved capacity is free | Prepaid idle capacity has opportunity cost. | Zombie clusters survive because bill is hidden. |

## Core mechanism

### Foundation

### Unit economics

Unit economics turns a cloud bill into engineering
levers. The unit must match the business and the system.
For checkout, cost per successful order is more useful
than cost per pod. For seller analytics, cost per seller
report and cost per GB scanned matter. For Kafka, cost
per million durable events plus retained GB-month
exposes throughput and storage. Precision matters less
than stable, decision-grade allocation that catches
directional mistakes.

```text
unit_cost_per_order =
  (checkout_api_compute
 + checkout_db_compute_and_storage
 + kafka_checkout_events
 + payment_platform_share
 + auth_session_cache_share
 + observability_allocated_to_checkout
 + cross_az_and_cross_region_transfer
 - reusable_shared_platform_credit)
 / successful_orders
```

| Unit | Numerator | Denominator | Decision |
| --- | --- | --- | --- |
| Cost per checkout order | API, DB, cache, Kafka, auth, observability, transfer. | Successful non-refunded orders. | Is a sale profitable after infra cost? |
| Cost per seller report | Analytics compute, query scans, OpenSearch, storage. | Reports delivered within SLO. | Precompute, cache, charge, or defer? |
| Cost per million events | MSK brokers, EBS, replication, consumers. | Accepted durable events. | Batch, compress, split topics, tune retention. |
| Cost per active tenant | Shared allocation plus tenant-specific resources. | Active tenants by tier. | Isolation and pricing decisions. |
| Cost per GB served | CloudFront, origin, compression CPU, egress. | GB delivered to users. | Cache TTL and image format decisions. |

### The cost equation engineers change

Most cloud cost is rate times duration times replication
plus waste. Rate is requests, queries, events, or GB
transferred. Duration is how long resources run, data
remains hot, or queries scan. Replication is copies
across nodes, AZs, regions, indexes, and logs. Waste is
idle headroom without a named risk, overprovisioned
limits, zombie resources, bad cache hit ratios, and
repeated work. A useful cost review names which term
changed.

```text
total_cost ~= work_rate * cost_per_unit * replication_factor * retention_duration
             + idle_capacity_cost
             + reliability_headroom
             + observability_and_security_overhead

capacity_needed ~= peak_work_rate * service_time / target_utilization
                  + failover_headroom
                  + rollout_headroom
                  + forecast_error_buffer
```

A microservice that adds one 2 KB synchronous cross-AZ
call per checkout event creates transfer charges,
latency, retries, trace spans, logs, and downstream
capacity. A histogram label that adds tenant_id can
create millions of time series. A database index that
halves read CPU but doubles write amplification can be
brilliant for reads and expensive for write-heavy
auctions. The point is to make the cost shape visible
before it is embedded in architecture.

### Egress and data locality

Egress is a bill for crossing boundaries. In AWS,
transfer may be charged between regions, out to the
internet, through NAT gateways, through load balancers,
and across availability zones depending on service and
path. Architects often think about latency locality but
forget billing locality. A design that reads product
images from us-east-1 for Asia pays latency and
transfer. A design that sends every eu-west-1 event to
us-east-1 for enrichment pays the same mistake at
analytics scale.

| Pattern | Surprise | Mitigation |
| --- | --- | --- |
| Cross-AZ chatty services | Many small calls and replies cross AZ repeatedly. | Locality-aware routing with failure testing. |
| NAT to AWS APIs | Private subnets reach S3/STS through NAT. | Gateway/interface endpoints when economics work. |
| CloudFront origin miss | Wrong cache key pulls large objects repeatedly. | Cache-Control, variant keys, origin shield. |
| Cross-region analytics | DR copy becomes query source from another region. | Run compute near data or replicate curated compressed sets. |
| Kafka mirroring | Every topic and retention copied everywhere. | Classify topics by RPO/RTO and compress. |
| Observability export | Logs/traces leave region at high volume. | Sample, filter, aggregate, avoid high-cardinality payloads. |

### Idle resources and rightsizing

Idle capacity is not automatically waste. Some idle
capacity is reliability headroom, deployment headroom,
failover capacity, cache warmup, or predictable seasonal
buffer. Waste is idle capacity without a named risk.
Rightsizing asks what peak the resource covers, what
warmup time replacement capacity requires, what
dependency saturates if this tier scales, what SLO is at
risk, and what rollback exists if the change is wrong.

| Signal | Interpretation | Caution |
| --- | --- | --- |
| CPU p95 <20%, p99 <35% | Possible compute overprovisioning. | Check throttling, GC, burst windows, single-thread limits. |
| Memory stable at 30% request | Possible request reduction. | Check heap spikes, page cache, native memory. |
| RDS CPU low but latency high | Not compute-bound. | May be locks, IO, buffer cache, query plans. |
| Kafka disk high | Storage or retention pressure. | Reducing brokers can violate replication headroom. |
| EKS requested high, used low | Requests or binpacking may be poor. | Changing requests changes HPA and scheduling. |
| OpenSearch heap high, CPU low | Shard/query problem. | Bigger nodes may hide shard-design debt. |

Rightsizing should be canaried like code. Change one
service class, node group, tenant tier, or workload
class first. Watch p50, p95, p99 latency, saturation,
throttling, queue depth, error rate, and unit cost. If
the SLO risk cannot be explained in one paragraph, the
change is not ready for production.

### Reserved, on-demand, spot, serverless

Purchasing models transfer risk. On-demand buys
flexibility. Reserved capacity and Savings Plans
exchange commitment for discount. Spot exchanges
interruption risk for discount. Serverless exchanges
capacity management for per-use pricing and provider
limits. The correct choice depends on utilization
predictability, workload interruptibility, architecture
stability, and the actual bottleneck.

| Model | Best fit | Bad fit | Control |
| --- | --- | --- | --- |
| On-demand | New, spiky, unknown, migration, incident headroom. | Stable 24x7 baseline at scale. | Tag ownership and expire experiments. |
| Savings Plan | Predictable aggregate compute. | Exact instance chargeback needs. | Track coverage and utilization separately. |
| Reserved DB | Stable RDS/OpenSearch/MSK baseline. | Near-term engine or region migration. | Model replicas and failover before commit. |
| Spot | Batch, CI, image jobs, backfills with checkpoints. | Stateful brokers or latency-critical checkout. | Handle interruption and diversify pools. |
| Serverless | Bursty event-driven low idle workloads. | High steady throughput or connection-heavy DB paths. | Set concurrency caps, DLQs, and idempotency. |

### Cost of consistency and replication

Reliability choices have cost. Synchronous replication
buys durability or read-your-writes at the price of
latency, network, and write amplification. Quorum
systems pay for extra copies and coordination.
Multi-region active-active pays for conflict handling,
replicated writes, and extra observability. Exactly-once
business effects require idempotency keys, transactional
outbox, dedupe tables, and replay tooling. These costs
are often correct; attach them to the invariant they
protect.

| Choice | Cost paid | Invariant bought | Question |
| --- | --- | --- | --- |
| Multi-AZ RDS | Standby compute/storage, replication latency. | AZ failure survival. | Is p99 write latency still inside SLO? |
| Kafka RF=3/minISR=2 | 3x storage, bandwidth, ack latency. | Durable event after one broker loss. | Which topics truly need this? |
| Global NoSQL table | Replicated write units and conflict handling. | Regional availability. | Can data tolerate LWW conflicts? |
| OpenSearch replicas | Extra heap, disk, indexing CPU. | Search availability and read throughput. | Are replicas for failure or query load? |
| CDC analytics | WAL retention, connectors, brokers, writes. | Fresh decoupled reporting. | What lag SLO justifies cost? |
| Cross-region strong consistency | WAN latency and coordination. | Single-copy semantics. | Is invariant worth distance on every write? |

### Capacity worksheet

### Staff

Little's Law links demand to concurrency: in-flight work
equals arrival rate times service time. If checkout-api
handles 45k events per second at peak and each request
holds 80 ms of service time, average in-flight work is
3600 requests before retries and tail latency. At 60%
target utilization, capacity needs roughly 6000
concurrent request-equivalents plus failover, rollout,
and forecast buffers.

```text
checkout-api worksheet
1. steady RPS: 18,000
2. peak sale RPS: 45,000
3. average service time at peak: 80 ms
4. in-flight work: 45,000 * 0.080 = 3,600
5. target utilization: 60%
6. capacity before failover: 3,600 / 0.60 = 6,000
7. tolerate loss of 1 of 3 AZs: 6,000 / (2/3) = 9,000
8. deployment headroom: +10%
9. forecast error buffer: +15%
10. planned capacity: 9,000 * 1.10 * 1.15 = 11,385 equivalents
```

A mature capacity plan names the scarce resource for
each path: API CPU, DB connections, cache ops, Kafka
producer throughput, ALB LCUs, NAT bandwidth, KMS
requests, IdP validation, and external PSP limits.
Scaling one layer without dependency budgets often
converts a local queue into a platform incident.

## Production anatomy

### Telemetry pack

| Signal | Dimensions | Lead/lag | Use |
| --- | --- | --- | --- |
| cost_anomaly_usd_estimated | service, account, owner, region | Lagging daily but early | Detect spend slope before invoice. |
| unit_cost_per_order | domain, region, channel | Lagging business | Connect cost to successful output. |
| request_cost_estimate | route, service, tenant_tier | Near real time | Find expensive routes and tenants. |
| cpu_utilization/throttling | service, node_group | Leading saturation | Rightsizing and latency risk. |
| memory_working_set/oom | service, pod_class | Leading saturation | Memory safety. |
| db_connections_active/max | cluster, pool, user | Leading limit | Protect DB from app scale. |
| queue_depth/oldest_age | queue, topic, consumer | Leading backlog | Capacity and downstream health. |
| cross_az/cross_region_bytes | source, destination | Leading cost | Data locality and chatty calls. |
| nat_gateway_bytes | vpc, az | Leading bill/failure | Missing endpoints and NAT bottlenecks. |
| reservation_coverage/utilization | service, family | Financial control | Separate undercommit from unused commit. |
| observability_ingest_bytes | team, signal_type | Leading cost | Prevent log/trace runaway. |
| tenant_resource_share | tenant_tier, resource | Leading fairness | Tie noisy neighbor to spend. |

### Tags and allocation

Tags are the join key between architecture and invoice.
A useful model includes service, domain, owner,
environment, cost center, lifecycle, data class, and
tenant tier where safe. Untagged cost is operational
debt. Platforms should block persistent resources
without ownership tags, publish untagged-cost reports,
and let teams correct tags quickly.

| Tag | Example | Purpose |
| --- | --- | --- |
| service | checkout-api | Operational owner. |
| domain | checkout | Product unit economics. |
| environment | prod | Separate prod and dev spend. |
| owner | team-checkout | Anomaly routing. |
| lifecycle | expires-2026-07-30 | Cleanup experiments. |
| data_class | pii-low | Retention and compliance cost. |
| tenant_tier | enterprise | Allocation without raw tenant labels. |

## Failure catalog

### Cross-region egress runaway

Trigger: Analytics job reads us-east-1 raw data from
eu-west-1. Amplifier: No transfer budget by dimension.
Blast radius: Large bill and saturated inter-region
links. First safe move: Stop or throttle job; rerun near
data or curated set.

### Autoscale into DB limit

Trigger: HPA doubles pods during sale. Amplifier: No
connection budget per pod. Blast radius: Checkout p99
rises despite more pods. First safe move: Cap app scale
and reserve DB pool.

### Reservation stranded

Trigger: Service migrates instance family after RI
purchase. Amplifier: Commitment invisible to service.
Blast radius: Discount use drops and on-demand rises.
First safe move: Map commitments or revisit migration
economics.

### Log cardinality explosion

Trigger: request_id/user_id label added. Amplifier: No
CI cardinality guard. Blast radius: Observability bill
and query latency spike. First safe move: Drop labels,
sample, use logs for drilldown.

### NAT surprise

Trigger: Private subnets call S3 through NAT. Amplifier:
No VPC endpoints and large batch. Blast radius: NAT bill
and port pressure. First safe move: Add endpoint or
route batch differently.

### Idle load-test cluster

Trigger: Temporary cluster left after test. Amplifier:
No expiration tag. Blast radius: Persistent monthly
waste. First safe move: Capture artifacts and delete;
add TTL janitor.

### Underprovision after cut

Trigger: Nodes reduced from average CPU. Amplifier:
Auction burst ignored. Blast radius: Retries amplify
latency. First safe move: Rollback and re-size on
p99/failover.

### Spot interruption storm

Trigger: Backfill only on one spot pool. Amplifier: No
checkpointing/diversification. Blast radius: Reports
delayed repeatedly. First safe move: Restore baseline
and diversify pools.

### Cold start concurrency wall

Trigger: Serverless fraud check scales suddenly.
Amplifier: RDS connections and concurrency limits. Blast
radius: Payment auth delayed. First safe move: Cap
concurrency and queue safely.

### Replication creep

Trigger: Every topic mirrored everywhere. Amplifier:
Retention copied unchanged. Blast radius: MSK and
transfer grow without value. First safe move: Classify
topics by RPO/RTO.

### Over-indexed OLTP

Trigger: Product fields indexed in primary DB.
Amplifier: Write amplification during sale. Blast
radius: Checkout/inventory writes slow. First safe move:
Drop noncritical indexes or move path.

### Trace override forgotten

Trigger: 100% sampling left on. Amplifier: High RPS
spans. Blast radius: Vendor bill and collector CPU
spike. First safe move: Restore sampling and set expiry.

### Latency hidden as savings

Trigger: CPU downsize increases GC and retries.
Amplifier: Retry storm raises work. Blast radius: Lower
node bill but higher unit cost. First safe move:
Rollback and measure successful-unit cost.

### Data lifecycle gap

Trigger: Raw events never transitioned. Amplifier: No
retention policy. Blast radius: Storage and scan cost
compound. First safe move: Classify and lifecycle cold
data.

### Cache miss storm cost

Trigger: TTL reduced globally. Amplifier: Origin
capacity ignored. Blast radius: Origin overload plus
egress bill. First safe move: Targeted invalidation or
stale-while-revalidate.

## Decision framework

### Cost reliability ladder

1. Remove true waste first: zombies, untagged
   experiments, duplicate logs, unused volumes, and idle
   test clusters.
2. Improve efficiency without reducing safety:
   compression, cache hit ratio, query plans, batching,
   right indexes, Graviton after tests, and VPC
   endpoints.
3. Buy the workload correctly: Savings Plans,
   reservations, spot for interruptible work, and
   serverless where idle dominates.
4. Change architecture when the cost shape is wrong:
   move compute to data, precompute reads, partition
   noisy tenants, reduce replication, or change
   consistency.
5. Only then reduce reliability headroom, with explicit
   SLO, error budget, failover, and rollback approval.

### Reserved versus on-demand worksheet

```text
Inputs:
  baseline_vcpu_hours_per_month = p10 hourly usage * hours
  variable_vcpu_hours_per_month = total - baseline
  expected_architecture_lifetime_months = 18
  commitment_term_months = 12 or 36
  migration_probability = probability of changing family/service/region
Decision:
  commit only to the lower of stable baseline and architecture confidence.
  keep incident, failover, and burst capacity flexible unless burst is predictable.
  track coverage separately from utilization.
```

### Capacity review questions

1. What is the business unit and current cost per
   successful unit?
2. Which resource is the p99 peak bottleneck: CPU,
   memory, IO, network, connection count, queue depth,
   or managed-service quota?
3. What headroom is required for AZ failure, region
   failover, deploy surge, retry surge, and forecast
   error?
4. Which dependencies receive more load if this tier
   scales out?
5. What is the warmup time for capacity, caches,
   partitions, and replicas?
6. What is the cost of one hour overcapacity versus one
   hour undercapacity?
7. Which optimization can be canaried, and what signal
   triggers rollback?
8. Which commitment becomes wrong if product plans
   change?

## Key takeaways

- Cost is not the opposite of reliability; it reveals
  waste, demand shape, and architectural fit.
- Unit economics beat aggregate bills because they
  connect engineering choices to business output.
- Egress, replication, logs, indexes, and idle
  commitments are common hidden multipliers.
- Rightsizing from averages is unsafe; use peak, tail
  latency, saturation, and failover assumptions.
- Reserved capacity is for stable baselines, not a
  substitute for capacity engineering.
- Consistency and replication buy invariants with
  latency, transfer, storage, and operational cost.
- A good FinOps runbook rejects cuts that move cost into
  retries, incidents, support load, or lost revenue.

## Targeted reading

- AWS Well-Architected Framework: Cost Optimization
  Pillar.
- AWS Cost Management User Guide: Cost Explorer, anomaly
  detection, budgets, and reservation reports.
- AWS data transfer pricing, NAT Gateway pricing, VPC
  endpoints, CloudFront caching, and inter-region
  transfer documentation.
- Kubernetes resource requests/limits, HPA, VPA, cluster
  autoscaler, and CPU throttling behavior.
- FinOps Foundation materials on allocation, unit
  economics, commitment management, and engineering
  accountability.
- Kafka documentation on replication factor,
  min.insync.replicas, retention, compression,
  partitions, and tiered storage.
- Database vendor documentation on storage, IOPS, read
  replicas, backup retention, and cross-region
  replication pricing.

## Principal-depth field guide: cost and capacity controls

### Principal stretch

Use these cards as design-review prompts and
incident-response heuristics. Each card names the
mechanism, the production signal, the failure it
prevents, and the strict decision rule. They are
intentionally concrete so that a staff or principal
engineer can turn them into runbook checks, CI policy,
or dashboard requirements.

### Unit numerator ownership

Mechanism: Every unit metric has a named owner for each
cost component, including shared platform allocation.

Production signal: untagged cost, allocation freshness,
shared cost percentage by domain.

Failure prevented: Teams argue about numbers instead of
changing the cost driver.

Decision rule: Use stable allocation rules and improve
them quarterly, not during incidents.

### Successful-unit denominator

Mechanism: The denominator counts successful business
outcomes, not attempts, retries, or failed requests.

Production signal: successful_orders, retry rate,
refunded order adjustment.

Failure prevented: A retry storm makes request cost look
efficient while order cost explodes.

Decision rule: Use business-success denominators for
product decisions.

### Egress boundary inventory

Mechanism: Architectures list every boundary crossed by
hot data: AZ, region, internet, NAT, vendor, and
analytics export.

Production signal: cross_az_bytes, cross_region_bytes,
nat bytes, vendor ingest bytes.

Failure prevented: A feature is approved on compute cost
while transfer dominates margin.

Decision rule: No high-volume feature ships without
data-locality review.

### NAT endpoint economics

Mechanism: Private subnet access to AWS services uses
endpoint math instead of accidental NAT routing.

Production signal: nat bytes by destination, VPC
endpoint utilization, route table drift.

Failure prevented: Batch jobs pay NAT processing for S3,
STS, or DynamoDB traffic.

Decision rule: Endpoint choice is reviewed when NAT
bytes change slope.

### Cache hit economics

Mechanism: Cache hit ratio is translated into origin
cost, latency, and egress, not only backend CPU.

Production signal: hit ratio by route, origin bytes,
miss penalty, stale serve count.

Failure prevented: A TTL change fixes freshness and
creates an origin cost incident.

Decision rule: Cache policy changes include origin
capacity and cost simulation.

### Observability budget

Mechanism: Logs, metrics, and traces have per-team
ingest budgets and emergency override expiry.

Production signal: ingest GB/hour, series count,
sampling override age.

Failure prevented: Debug sampling left on becomes the
largest cost line.

Decision rule: Incident observability overrides expire
automatically.

### Metric cardinality guard

Mechanism: CI estimates new time-series count before
accepting labels.

Production signal: series created by metric, top label
cardinality, rejected builds.

Failure prevented: A tenant/user/request label melts
monitoring and budget.

Decision rule: High-cardinality dimensions go to
logs/exemplars unless explicitly approved.

### Reservation coverage split

Mechanism: Coverage and utilization are reported
separately so undercommit and unused commit are not
confused.

Production signal: coverage percent, utilization
percent, on-demand baseline.

Failure prevented: A team buys commitment for burst or
leaves stable baseline on-demand.

Decision rule: Commit only to stable baseline and track
unused commitments.

### Architecture half-life

Mechanism: Commitment terms respect how long the
architecture and instance family will remain stable.

Production signal: migration roadmap, family mix,
commitment expiry.

Failure prevented: A Graviton or serverless migration
strands three-year reservations.

Decision rule: Financial commitment length cannot exceed
architecture confidence.

### Spot checkpoint contract

Mechanism: Spot workloads prove checkpoint, idempotency,
and interruption handling before scale.

Production signal: interruption recovery time, duplicate
work, checkpoint age.

Failure prevented: Cheap compute restarts work forever
and misses deadlines.

Decision rule: Spot is for interruptible work with
measured recovery.

### Serverless downstream cap

Mechanism: Serverless concurrency is capped against
downstream connection and quota budgets.

Production signal: lambda concurrency, DB connections,
throttles, queue age.

Failure prevented: Serverless scales faster than RDS,
KMS, or a partner API.

Decision rule: Concurrency limits protect downstreams
before provider scaling does.

### Right-size canary

Mechanism: Capacity reductions roll out as canaries with
SLO, saturation, and rollback gates.

Production signal: p99 latency, throttling, queue depth,
OOM, unit cost.

Failure prevented: Average utilization cuts remove tail
headroom.

Decision rule: A resource cut is a production change
with rollback.

### Failover headroom math

Mechanism: Capacity plans model loss of AZ/region and
degraded cache warmup, not just steady peak.

Production signal: per-AZ utilization, failover
simulation, warm cache hit ratio.

Failure prevented: A zone loss doubles load onto tiers
sized for normal average.

Decision rule: Headroom has a named failure mode and a
tested failover shape.

### Retry cost accounting

Mechanism: Retries are counted as extra work and can
raise unit cost even when success rate recovers.

Production signal: retry_attempts, retry_after
compliance, downstream saturation.

Failure prevented: A cheap timeout policy multiplies
compute and transfer cost.

Decision rule: Retry budgets are part of capacity and
cost planning.

### Consistency cost label

Mechanism: Strong consistency and replication choices
state the invariant they buy.

Production signal: write latency, replica bytes, quorum
failures, storage multiplier.

Failure prevented: Teams pay 3x or WAN latency without
knowing the protected invariant.

Decision rule: If no invariant is named, revisit
consistency level.

### CDC lag tradeoff

Mechanism: Freshness SLOs are priced in WAL retention,
broker throughput, consumers, and downstream writes.

Production signal: cdc_lag, WAL bytes retained,
connector CPU, topic bytes.

Failure prevented: Near-real-time dashboards silently
tax OLTP and Kafka.

Decision rule: Freshness tighter than business need
requires product approval.

### Index write amplification

Mechanism: Every new index reports read benefit and
write/storage cost under peak write load.

Production signal: index size, write latency, buffer
churn, query frequency.

Failure prevented: Read optimization breaks checkout
writes during sale.

Decision rule: Indexes on hot OLTP paths need peak-write
acceptance tests.

### OpenSearch shard economy

Mechanism: Shard count, replica count, and tenant index
choices are capacity decisions, not defaults.

Production signal: heap per shard, segment count,
rejected searches, indexing p99.

Failure prevented: Index-per-tenant creates too many
shards or shared index leaks filters.

Decision rule: Shard design follows tenant size
distribution and query isolation needs.

### Data lifecycle tiering

Mechanism: Data retention states hot, warm, cold, legal
hold, and delete behavior by data class.

Production signal: age by storage tier, restore tests,
lifecycle failures.

Failure prevented: Raw events stay hot forever because
nobody owns deletion.

Decision rule: Retention is a product/compliance
decision encoded in lifecycle policy.

### Backfill budget

Mechanism: Backfills declare throughput caps, stop
conditions, and business priority versus live traffic.

Production signal: backfill RPS, queue age, live p99,
cost per hour.

Failure prevented: A correctness job starves checkout or
burns transfer during sale.

Decision rule: Backfills are schedulable tenants with
quotas.

### Budget alert lead time

Mechanism: Alerts fire on spend slope early enough to
change behavior, not month-end totals.

Production signal: daily forecast, hourly anomaly, cost
per unit slope.

Failure prevented: Finance sees the problem after the
campaign is over.

Decision rule: Cost alerts need operational lead time
and an owner.

### Per-tenant cost share

Mechanism: Heavy tenants are visible through allocation
tables without exploding metric labels.

Production signal: tenant resource share, top-N cost
report, tier margin.

Failure prevented: A tenant consumes 30% of Redis while
paying for 2% revenue.

Decision rule: Pricing/isolation decisions use tenant
cost share evidence.

### Idle risk label

Mechanism: Idle capacity is tagged with the risk it
protects or an expiry date.

Production signal: idle resources by risk tag, untagged
idle, expiry violations.

Failure prevented: All idle resources look like waste or
all waste hides as safety.

Decision rule: No risk label means the resource is
cleanup candidate.

### Load-test cleanup

Mechanism: Load-test environments have expiration,
owner, and artifact checklist.

Production signal: expires tag, orphan spend, test
artifact status.

Failure prevented: A temporary cluster becomes permanent
monthly spend.

Decision rule: Performance tests finish by deleting or
renewing explicitly.

### Managed quota budget

Mechanism: Capacity plans include ALB LCUs, KMS TPS, NAT
ports, ENIs, Kafka partitions, and vendor quotas.

Production signal: quota utilization, throttle count,
limit increase age.

Failure prevented: Compute scales but a managed quota
throttles the path.

Decision rule: Scaling plans list non-compute quotas.

### Forecast error buffer

Mechanism: Plans include explicit forecast uncertainty
instead of optimistic product numbers.

Production signal: forecast vs actual, buffer burn, sale
calendar changes.

Failure prevented: A campaign exceeds plan and every
autoscaler chases tail latency.

Decision rule: Buffers are sized from historical
forecast error.

### Degradation economics

Mechanism: Runbooks state which features degrade first
based on revenue, contracts, and cost per unit.

Production signal: feature cost, tenant tier, SLO
credits, margin impact.

Failure prevented: Teams turn off the wrong feature or
violate enterprise contracts.

Decision rule: Degrade optional standard-tier analytics
before checkout.

### Finance incident role

Mechanism: Finance provides break-even, margin, and burn
rate but does not choose unsafe mitigations.

Production signal: incident role assignment, break-even
value, burn per hour.

Failure prevented: Engineers lack business threshold or
finance demands unsafe cuts.

Decision rule: Incident command combines financial facts
with technical safety.

### Chargeback feedback

Mechanism: Teams see cost close to deploy time and
ownership, not only monthly reports.

Production signal: cost by deploy, owner, service, tag
freshness.

Failure prevented: A release doubles cost and no
engineer notices.

Decision rule: Cost feedback belongs in the engineering
loop.

### Compression default

Mechanism: High-volume event and replication paths
specify compression and payload budget.

Production signal: bytes per event, compression ratio,
CPU cost.

Failure prevented: Uncompressed mirrors multiply broker
and egress cost.

Decision rule: Compression is default unless latency/CPU
evidence rejects it.

### Queue age as capacity

Mechanism: Backlog age is treated as user impact for
async systems, not just queue depth.

Production signal: oldest message age, consumer lag, SLA
miss count.

Failure prevented: A huge queue looks acceptable because
depth lacks time context.

Decision rule: Capacity alerts include age and business
deadline.

### Cost-aware SLO

Mechanism: SLOs state the cost envelope for meeting
reliability, especially during campaigns.

Production signal: SLO burn, cost per good event,
campaign budget.

Failure prevented: Reliability is met by infinite
scaling at negative margin.

Decision rule: Reliability targets and cost envelopes
are reviewed together.

### Rollback cost estimate

Mechanism: Rollback plans include cost impact and data
movement, not only code safety.

Production signal: rollback transfer bytes, duplicate
processing, cache warmup.

Failure prevented: Rollback doubles data transfer or
recomputes large indexes.

Decision rule: Every rollback for data features has cost
and capacity notes.

### Shared platform credit

Mechanism: Shared systems allocate reusable baseline
without hiding marginal feature cost.

Production signal: platform allocation percent, marginal
feature delta.

Failure prevented: A feature appears cheap by dumping
load on shared infra.

Decision rule: Marginal cost is shown next to allocated
cost.

### RDS storage IO coupling

Mechanism: DB cost and capacity consider storage, IOPS,
memory, and query shape together.

Production signal: read/write IOPS, buffer hit ratio,
temp spills, storage autoscale.

Failure prevented: Compute rightsizing ignores IO
bottleneck.

Decision rule: DB sizing decisions name the limiting
resource.

### Savings versus risk review

Mechanism: Every cost reduction identifies risk removed,
unchanged, or added.

Production signal: risk register, rollback condition,
SLO impact.

Failure prevented: Savings are approved while
reliability debt increases silently.

Decision rule: Cost changes need risk classification
like architecture changes.

## Additional principal reviewer checks: FinOps operating model

### Cost anomaly ownership

Every anomaly routes to a service owner who can change
code or configuration. If ownership routes only to
finance, the alert is informational rather than
operational. The review asks whether the owner has
rollback authority, feature-flag authority, and the
dashboard context to identify the marginal driver.

### Forecast reconciliation

After major events, forecast and actual demand are
reconciled by traffic source, tenant tier, region, and
feature. The goal is not blame; the goal is to size the
next buffer from measured forecast error rather than
optimism.

### Unit-cost regression gate

A release that increases cost per successful unit beyond
an agreed threshold should have the same seriousness as
a latency regression. The gate can be advisory for
experiments, but production rollouts need a named
approver when unit cost moves materially.

### Fail-open cost controls

Cost controls must define whether they fail open or
closed. A budget alert should not automatically kill
checkout, but an analytics job can fail closed when it
exceeds its scan-byte budget. The difference is a
product and reliability decision.

### Vendor and SaaS pass-through

Cloud bills are not the only infrastructure cost.
Payment provider fixed fees, observability SaaS, fraud
APIs, email/SMS, and search vendors may be marginal per
request or per event. Unit economics include these when
the engineering path controls volume.

### Carbon and region tradeoff

Some organizations track carbon intensity or region
sustainability. Treat it as another constraint beside
latency, residency, availability, and price. A greener
region that adds cross-region transfer or breaks
residency may still be the wrong placement.

### Cost of rollback delay

When a release causes runaway spend, the rollback
decision has a dollar-per-minute value. Incident command
should know the burn rate so product can decide whether
preserving a feature for enterprise tenants is worth the
spend while a safer fix is built.

### Capacity debt register

When a team accepts lower headroom for cost reasons,
record the capacity debt with owner, expiry, and
trigger. Otherwise temporary risk becomes invisible
permanent fragility.

## Ops Sim: The Sale Is Profitable Until the Cloud Bill Arrives

**Time box:** 45 minutes   **Severity:** P2 escalating
to P1 if throttling begins   **Service / domain:**
Checkout, analytics, Kafka, egress, capacity planning
**Northstar system:** flash sale and seller analytics

### Rules

1. Answer from memory; do not re-read the module
   mid-drill.
2. Write decisions T+0 through T+60.
3. Name evidence for every claim.
4. Reject at least one bad fix.
5. Do not open answers until finished.

### 1. Scenario stem

```text
WHAT USERS SEE:
  Checkout is mostly healthy, but seller dashboards lag by 25 minutes.
  Finance flags projected daily cloud spend at 4.7x forecast.
  Product wants the flash sale to run six more hours.

WHAT ON-CALL SEES:
  No single service is down.
  Kafka and OpenSearch are hot, NAT Gateway bytes spiked, and cross-region transfer rose sharply.
  A seller analytics feature shipped four hours ago.

BUSINESS CONSTRAINT:
  If infra cost per order exceeds $0.19, the campaign loses money.
  Pausing all analytics violates enterprise contracts but is acceptable for standard sellers.
```

### 2. Telemetry pack

```text
METRICS:
  successful_orders_per_min: 310k
  estimated_cost_per_order: $0.071 -> $0.236
  cross_region_bytes{src="us-east-1",dst="eu-west-1"}: 1.1 TB/h -> 9.8 TB/h
  nat_gateway_bytes{vpc="analytics-prod"}: 140 GB/h -> 3.2 TB/h
  msk_broker_network_out: 42% -> 91% of tested safe throughput
  kafka_consumer_lag{group="seller-analytics-live"}: 2.4M -> 61M
  opensearch_indexing_latency_p99: 180ms -> 2.8s
  checkout_api_p99: 210ms -> 248ms
  observability_ingest_gb_per_hour{team="seller-analytics"}: 0.8 -> 11.6

LOG LINES:
  seller-analytics feature=live_margin_by_region query_mode=raw_events region=eu-west-1 src_bucket=us-east-1
  analytics-worker exporting trace sample_rate=1.0 route=/seller/live-margin
  kafka MirrorMaker topic=checkout.events lag=59000000 compression=none
  nat-gw flow dst=s3.us-east-1.amazonaws.com bytes=714332221 endpoint=missing
  finance-alert campaign=summer-auction projected_cost_per_order=0.236 threshold=0.19

TRACES / COST:
  seller dashboard: API 22ms -> analytics query 12.4s -> OpenSearch refresh 2.1s -> timeout
  Cost allocation last hour: DataTransfer $18,900; NAT $14,700; Observability $4,300; OpenSearch $1,150; MSK $780
  Deploy diff: source changed from curated eu-west-1 table to raw us-east-1 checkout.events
```

### 3. Config pack

```yaml
analytics_live_margin:
  enabled: true
  tenants: [enterprise, standard]
  source: s3://northstar-us-east-1-raw/checkout/events/
  run_region: eu-west-1
  refresh_interval_seconds: 15
  trace_sample_rate: 1.0
  kafka_mirror:
    topics: ["checkout.events", "inventory.events", "clickstream.raw"]
    compression_type: none
    replicate_all_partitions: true

candidate_bad_fix:
  scale_opensearch_data_nodes_from_24_to_96: true
  leave_data_source_unchanged: true
```

### 4. Timeline and decision points

| Time | Event | Your move |
| --- | --- | --- |
| T+0 | Finance anomaly and seller lag arrive together. |  |
| T+5 | Cost per order exceeds break-even. |  |
| T+15 | Product asks whether checkout capacity should be reduced. |  |
| T+60 | Enterprise seller SLO clock is at risk. |  |

### 5. Questions

1. Which mechanism is the primary cost driver, and which
   symptom is a capacity consequence rather than root
   cause?
2. Name the three strongest cost/capacity signals and
   one red herring.
3. Write the first 15 minutes of mitigation. Include
   what you protect, what you degrade, and what you do
   not scale yet.
4. Why is scaling OpenSearch data nodes by 4x incomplete
   or dangerous? Why is reducing checkout capacity the
   wrong first move?
5. Compute the unit-economics decision: at 310k
   successful orders per minute and cost per order of
   $0.236, how far above $0.19 break-even is the
   campaign per hour?
6. Design the durable fix: data locality, curated
   datasets, sampling, commitments, and capacity
   guardrails. Give acceptance criteria.
7. Who needs to be in the incident channel by T+10, and
   what decision rights does each party have?

### 6. Self-score after answer key

| Error type | Did it happen? | Note |
| --- | --- | --- |
| Knowledge gap |  |  |
| Misread / wrong layer |  |  |
| Sequencing error |  |  |
| Capacity or blast-radius miss |  |  |
| Org / runbook miss |  |  |
| Careless slip |  |  |

**Pass:** correct cost driver, safe sequencing, numeric
unit math, and durable acceptance criteria.

---

## Staff & Principal Stretch: Quantitative FinOps & Infrastructure Economics

### 1. Data Egress & Cross-AZ Transfer Cost Mathematical Framework

Data transfer costs in cloud environments (AWS / GCP / Azure) compound silently as systems scale horizontally:

$$\text{Monthly Transfer Cost} = \sum_{c \in \text{Cross-AZ}} B_c \cdot P_{\text{AZ}} + \sum_{r \in \text{Cross-Region}} B_r \cdot P_{\text{Region}} + \sum_{n \in \text{NAT}} B_n \cdot P_{\text{NAT}}$$

Where:
- $P_{\text{AZ}} = \$0.01\text{ / GB}$ (in + out combined across Availability Zones)
- $P_{\text{Region}} = \$0.02\text{ to }\$0.09\text{ / GB}$ (inter-region WAN transfer)
- $P_{\text{NAT}} = \$0.045\text{ / GB processed} + \$0.045\text{ / hour}$ (NAT Gateway)

```
AZ & NETWORK BOUNDARY TRANSFER COST COMPARISON MATRIX:

  Transfer Boundary                | Cost per TB  | Primary Architectural Mitigation
  ─────────────────────────────────┼──────────────┼────────────────────────────────────────────
  Intra-AZ Private IP              | $0.00        | Topology-aware service routing (K8s local AZ)
  Cross-AZ (Same Region)           | $20.00       | AZ affinity & local cache read replicas
  NAT Gateway Processing           | $45.00       | Gateway VPC Endpoints (S3 / DynamoDB)
  Cross-Region (Inter-WAN)         | $20 - $90.00 | CDC Delta Compression & Edge CloudFront Caching
  Internet Egress (Cloud to Public)| $90.00       | CloudFront CDN / Direct Connect Peering
```

### 2. Storage Tier IOPS & Throughput Cost Efficiency Matrix

```
AWS STORAGE TIER COST & IOPS EFFICIENCY COMPARISON (1 TB Volume Baseline):

  Storage Type   | Base Cost / Month | Included IOPS | Max IOPS | Provisioned IOPS Cost | Cost for 30,000 IOPS / Mo
  ───────────────┼───────────────────┼───────────────┼──────────┼───────────────────────┼───────────────────────────
  EBS gp3        | $80.00            | 3,000         | 16,000   | $0.005 / IOPS         | $145.00 (Max 16k IOPS limit)
  EBS io2        | $125.00           | 0             | 64,000   | $0.065 / IOPS         | $2,075.00
  Local NVMe SSD | $0.00 (Included)  | N/A           | >800,000 | $0.00 (Ephemeral)     | Included in EC2 `i3en/i4i`
```

**Key Takeaway for SREs:** Scaling from `gp3` to `io2` for high-throughput OLTP databases increases storage bill by up to **14x**. Where ephemeral data loss is tolerable (e.g., Kafka logs, Redis cache, Cassandra replicas), switch to **local NVMe SSD instance storage (`i4i`/`i3en` instances)** for $0 additional IOPS cost.

### 3. Kubernetes Pod Bin-Packing & Packing Density Mathematics

To maximize node compute efficiency without causing CPU throttling or OOM kills, compute request-to-limit ratios must follow strict bin-packing ratios:

$$\text{Node Allocation Efficiency} = \frac{\sum_{i=1}^{N} \text{CPU\_Request}_i}{\text{Capacity}_{\text{Node\_CPU}}} \approx 85\%$$

$$\text{Overcommit Ratio} = \frac{\sum \text{CPU\_Limit}}{\sum \text{CPU\_Request}} \le 2.5\times \quad (\text{For Stateless Microservices})$$

```python
# Bin-Packing Packing Density Simulation (First Fit Decreasing)
def calculate_packing_density(pod_cpu_requests: list[float], node_cpu_capacity: float = 16.0):
    # Sort pods descending for optimal packing
    sorted_pods = sorted(pod_cpu_requests, reverse=True)
    nodes = []

    for pod in sorted_pods:
        placed = False
        for node in nodes:
            if node['used'] + pod <= node_cpu_capacity:
                node['used'] += pod
                node['pods'].append(pod)
                placed = True
                break
        if not placed:
            nodes.append({'used': pod, 'pods': [pod]})
            
    total_used = sum(n['used'] for n in nodes)
    total_capacity = len(nodes) * node_cpu_capacity
    return len(nodes), (total_used / total_capacity) * 100
```
