# Multi-Tenancy Isolation and Noisy Neighbor

Northstar Commerce is multi-tenant because sellers share
the marketplace platform while expecting their data,
performance, billing, and operational fate to be
isolated. Multi-tenancy is not just a database schema
choice. It is an isolation contract across identity,
data, compute, cache, queue, search, observability,
billing, support tooling, deployment, and incident
response.

## Learning objectives

1. Compare shared, pooled, partitioned, cell-based, and
   siloed tenancy models with tradeoffs in cost,
   isolation, operability, and blast radius.
2. Enforce tenant isolation at identity, API, service,
   database, cache, queue, search, object storage,
   analytics, and support-tool layers.
3. Diagnose noisy-neighbor failures in Redis,
   PostgreSQL, Kafka, OpenSearch, worker pools, and rate
   limiters using telemetry.
4. Design tenant fair-share rate limits that combine
   global protection, tier entitlements, burst
   tolerance, endpoint weights, and abuse response.
5. Choose data isolation patterns: tenant_id predicates,
   row-level security, schema per tenant, database per
   tenant, account per tenant, and encryption-key
   separation.
6. Model blast radius for tenant feature flags,
   migrations, backfills, index rebuilds, cache keys,
   and support actions.
7. Build dashboards that show per-tenant saturation
   without exploding metric cardinality or leaking
   sensitive tenant identities.
8. Reject bad fixes such as globally raising limits,
   flushing shared caches, disabling tenant predicates,
   or moving a hot tenant without capacity math.
9. Use Northstar examples to reason about marketplace
   sellers, enterprise tiers, live auctions, seller
   analytics, and shared checkout infrastructure.
10. Write runbooks that preserve fairness: protect
    shared control planes, isolate the offender,
    communicate with affected tenants, and avoid
    cross-tenant data exposure.

## Wrong mental models

| Wrong model | Correction | Why it hurts |
| --- | --- | --- |
| tenant_id column equals isolation | A predicate is one guardrail; every query, cache key, job, export, and policy must preserve it. | One missing WHERE clause leaks data. |
| Enterprise tenants must always be siloed | Siloing improves blast radius but increases cost and fleet surface. | Hundreds of snowflake stacks cannot be patched. |
| Shared means shared fate is inevitable | Shared systems can enforce quotas, partitions, workload groups, and backpressure. | Noisy tenants harm everyone by default. |
| Rate limits are only abuse defense | Limits are capacity allocation and fairness controls. | Legitimate tenant imports starve checkout. |
| Per-tenant metrics need tenant_id everywhere | Raw tenant labels can destroy cardinality and leak business facts. | Observability cost and confidentiality risk spike. |
| Cache isolation is easy | Caches need tenant-aware keys, memory quotas, TTLs, and stampede controls. | One tenant evicts sessions or sees another tenant response. |
| Kafka partitions isolate tenants | Partitions isolate ordering, not broker IO, consumer CPU, or retention. | One hot tenant saturates a broker. |
| Moving a tenant fixes noisy neighbor | Migration changes load placement and risk. | The destination shard fails and scope doubles. |
| Support tools are trusted | Support tools are high-risk multi-tenant clients. | A support query exports the wrong tenant. |
| Blast radius is only data size | Blast radius includes revenue, legal exposure, credits, toil, and trust. | A small regulated tenant can be highest severity. |

## Core mechanism

### Foundation

### Tenancy model spectrum

The tenancy spectrum runs from fully shared to fully
siloed. Shared means many tenants use the same
application, database, cache, queue, and search cluster
with logical separation. Pooled or partitioned means
tenants share a service but are assigned to shards,
schemas, queues, or node pools. Siloed means a tenant
has dedicated infrastructure. Cell-based means groups of
tenants live in repeatable stacks so blast radius is
bounded without one stack per tenant. Mature systems mix
these patterns by tier, workload, and data sensitivity.

| Model | Isolation | Cost | Operational shape | Good fit |
| --- | --- | --- | --- | --- |
| Shared table with tenant_id | Lowest by default; relies on predicates and policy. | Lowest. | Simple provisioning; hard noisy-neighbor prevention. | Small homogeneous tenants. |
| Schema per tenant | Moderate namespace separation. | Low to moderate. | Migration fanout and drift. | Hundreds to low thousands of B2B tenants. |
| Database per tenant | High data/performance isolation. | Moderate to high. | Backups, migrations, connections. | Enterprise tenants. |
| Cluster/account per tenant | Very high boundary. | High. | Fleet patching and observability dominate. | Regulated or very large tenants. |
| Cell-based pooled | High within cell boundary. | Moderate. | Routing, capacity, and migration tooling. | Large platforms needing blast-radius caps. |

Northstar may use shared checkout tables for normal
sellers, dedicated OpenSearch indexes for enterprise
analytics, separate KMS keys for regulated sellers, and
cell-based Kafka topics for high-volume auction sellers.
The contract should name which property each layer
provides: data visibility, performance, failure blast
radius, deployment independence, compliance boundary, or
billing attribution.

### Data isolation

Data isolation starts with identity and ends at storage.
The authenticated principal must carry a tenant claim or
be mapped to tenant memberships. The API authorizes the
action against the resource tenant. The service passes
tenant context explicitly. Queries bind tenant_id as a
parameter. The database can enforce row-level security
as a final guardrail. Exports, analytics, caches, and
search indexes must preserve the same boundary.

```sql
ALTER TABLE seller_orders ENABLE ROW LEVEL SECURITY;
CREATE POLICY seller_orders_tenant_isolation ON seller_orders
USING (tenant_id = current_setting('app.tenant_id')::uuid)
WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
BEGIN;
SELECT set_config('app.tenant_id', $1, true);
SELECT * FROM seller_orders WHERE order_id = $2;
COMMIT;
```

Row-level security is a guardrail, not an excuse to omit
tenant predicates. Connection pools must reset session
variables, admin jobs must use safe roles, query plans
must be tested with tenant predicates, and debugging
must not switch to superuser roles that bypass policies.
Defense in depth means API policy, service code,
database policy, tests, and audit logs agree.

| Layer | Control | Failure to test |
| --- | --- | --- |
| Identity | Tenant memberships and support impersonation approval. | User from Seller A retains Seller B role. |
| API | Object authorization checks resource tenant and action. | Endpoint fetches by order_id without tenant binding. |
| Service | Tenant context object required by repository calls. | Background retry drops tenant context. |
| Database | Tenant predicate, RLS, schema/database isolation. | Pool leaks previous tenant setting. |
| Cache | Tenant in key, quota, safe invalidation. | product:123 key shared across tenants. |
| Search | Filtered alias or index per tenant. | Global query misses tenant filter. |
| Object storage | Tenant prefix, bucket policy, signed URL scope. | Export writes to shared public prefix. |
| Analytics | Row filters and data contracts. | BI join crosses tenants. |

### Noisy neighbor mechanisms

A noisy neighbor is a tenant whose legitimate or abusive
workload consumes a shared scarce resource enough to
degrade other tenants. Scarce resources include Redis
memory, Redis single-thread CPU, DB locks, DB
connections, IOPS, Kafka partitions, broker network,
consumer CPU, OpenSearch heap, worker concurrency,
rate-limiter storage, KMS quotas, and support-team
attention. Diagnosis starts by naming the scarce
resource and proving which tenant consumes it.

#### Redis

Redis failures come from hot keys, large values,
high-cardinality keys, eviction pressure, and blocking
commands. Controls include tenant-aware prefixes, memory
accounting, command allowlists, TTL contracts, hot-key
sharding, request coalescing, and separate session
versus analytics clusters.

#### PostgreSQL

PostgreSQL failures show up as locks, connection
exhaustion, buffer-cache churn, temp file spills,
autovacuum lag, and slow queries. Controls include
statement timeouts, workload groups, PgBouncer pools,
read replicas for exports, partial indexes,
partitioning, and query governors.

#### Kafka

Kafka partitions isolate ordering, not broker IO or
consumer CPU. A hot tenant partition can saturate a
broker. Controls include safer partition keys,
tenant-specific topics for heavy tiers,
producer/consumer quotas, compression, retention
classes, and backpressure.

#### OpenSearch and analytics

Search and analytics amplify tenancy mistakes because
queries are expressive and data volume varies. Controls
include index-per-large-tenant, filtered aliases, query
cost limits, async reports, pre-aggregations, time-range
caps, fielddata controls, and dashboard concurrency.

### Fair-share rate limits

### Staff

Fair-share limits protect shared resources while
respecting product tiers. They need global safety,
tenant entitlement, user or token sublimits, and
endpoint-specific cost weighting. A refund creation is
not equivalent to a product read. A seller import job
should not consume the same pool as buyer checkout.
Limits should return retry-after metadata and degrade
optional work before critical paths.

```text
effective_limit(tenant, endpoint) = min(
  platform_global_remaining(endpoint_class),
  tenant_tier_limit(tenant.tier, endpoint_class),
  tenant_dynamic_share(resource_pressure),
  abuse_or_risk_limit(tenant, credential, ip)
)

cost weights:
  GET /products/{id}: 1 token
  POST /orders/refund: 20 tokens
  POST /seller/import: 100 tokens plus async queue quota
  GET /analytics/live-margin?range=24h: 250 tokens
```

| Pattern | Good for | Weakness | Tenant note |
| --- | --- | --- | --- |
| Token bucket | Bursts with average rate. | Synchronized bursts. | Use per-tenant plus global bucket. |
| Leaky bucket | Smoothing output. | Less burst flexibility. | Good for strict downstreams. |
| Concurrency limit | Protect DB/search/worker pools. | Needs timeout and queue policy. | Set per tenant and endpoint class. |
| Weighted fair queue | Shared workers with tiers. | More scheduler complexity. | Prevents starvation. |
| Adaptive limit | Rapid resource pressure changes. | Can oscillate. | Base on saturation, not just errors. |

### Blast radius and migration

Blast radius is the set of tenants, systems, data,
revenue, legal obligations, and operators affected by a
fault or mitigation. Moving a hot seller to a new shard
helps only if the destination has CPU, memory, IOPS,
cache, Kafka partition, and support capacity. Moving
data also risks dual writes, lag, stale cache, and
tenant routing errors. A tenant move is a distributed
systems change, not a ticket label.

```text
Tenant move checklist:
  source shard pressure: CPU 88%, p99 900ms, lock waits high
  destination spare: CPU p95 42%, buffer cache 120 GB, IOPS p95 38%
  tenant data size: 2.4 TB orders, 180 GB search index, 60 GB cache hot set
  write cutover: freeze optional writes, dual-write idempotently, verify counts
  read routing: versioned tenant map cached for <=60s
  rollback: source remains authoritative until verification passes
  blast radius: destination tenants receive additional 12% CPU and 9% IO load
```

## Production anatomy

### Telemetry without cardinality collapse

Per-tenant visibility is necessary, but raw tenant_id
labels on every metric are dangerous. Use tier, cell,
shard, tenant hash buckets, top-N heavy hitters,
exemplars, logs, and periodic allocation tables. For
high-risk operations, audit logs should include
tenant_id. For high-volume metrics, aggregate by tier or
shard and maintain a separate heavy-hitter stream.

| Signal | Safe dimensions | High-cardinality handling | Use |
| --- | --- | --- | --- |
| tenant_request_rate | tier, route_class, cell | Top-N side stream by tenant hash. | Find noisy tenants. |
| tenant_error_rate | tier, service, reason | Audit logs include tenant_id. | Detect tenant-specific breakage. |
| redis_ops_evictions | cluster, key_class, tier | Sample hot keys with hash. | Separate session and analytics pressure. |
| db_query_seconds | role, fingerprint, shard, tier | Slow log stores tenant_id under access control. | Find bad query shape. |
| kafka_produce_bytes | topic, broker, tier | Quota logs by tenant. | Detect hot producers and partition skew. |
| rate_limit_decisions | tier, endpoint_class, decision | Top limited tenants in logs. | Prove fairness. |
| support_export_events | support_role, tenant, result | Audit only, not metric label. | Forensics for access risk. |

### Config examples

```yaml
tenant_controls:
  rate_limits:
    standard: {checkout_write_rps: 50, analytics_concurrency: 2, import_jobs_active: 1}
    enterprise: {checkout_write_rps: 500, analytics_concurrency: 8, import_jobs_active: 3}
  redis:
    key_prefix_required: true
    forbidden_commands: [KEYS, FLUSHALL, FLUSHDB, CONFIG]
    max_value_bytes: 1048576
  postgres:
    statement_timeout_ms: {interactive: 1500, export: 300000}
    app_role_bypasses_rls: false
  kafka:
    producer_byte_rate_quota_mb_s: {standard: 2, enterprise: 25}
```

## Failure catalog

### Missing tenant predicate

Trigger: New endpoint queries by order_id only.
Amplifier: Order ID treated as authorization boundary.
Blast radius: Cross-tenant data exposure. First safe
move: Disable endpoint or add guard; audit logs.

### RLS bypass role

Trigger: App uses owner role that bypasses row security.
Amplifier: Tests use same privileged role. Blast radius:
All shared-table tenants at risk. First safe move:
Switch to non-bypass role and audit.

### Redis cache bleed

Trigger: Key lacks tenant prefix. Amplifier: Same
product IDs across sellers. Blast radius: Wrong
price/content served. First safe move: Invalidate key
class and fix key builder.

### Redis eviction neighbor

Trigger: Tenant writes large analytics results.
Amplifier: Sessions share cluster. Blast radius: Login
failures for many tenants. First safe move: Throttle
analytics and separate cache class.

### Postgres long export

Trigger: Seller export holds snapshot for hours.
Amplifier: Autovacuum blocked, bloat rises. Blast
radius: Shared shard latency. First safe move: Cancel or
move export to replica.

### DB connection hoarding

Trigger: Tenant import opens many workers. Amplifier: No
per-tenant pool. Blast radius: Other tenants cannot get
connections. First safe move: Cap tenant concurrency and
reserve pool.

### Kafka hot partition

Trigger: Partition key tenant_id for huge seller.
Amplifier: One broker leads hot partition. Blast radius:
Shared topic lag and retention pressure. First safe
move: Throttle, split key, or dedicated topic.

### OpenSearch unbounded query

Trigger: Dashboard defaults to all time. Amplifier:
Shared index and expensive aggregations. Blast radius:
Thread pool rejects many tenants. First safe move: Limit
range and async report.

### Support export wrong tenant

Trigger: Tool accepts tenant_id without membership.
Amplifier: Broad break-glass role. Blast radius:
Regulatory incident. First safe move: Disable path and
preserve evidence.

### Global feature flag

Trigger: Beta flag enabled by default. Amplifier: Config
cache ignores tenant override. Blast radius: All sellers
see experimental path. First safe move: Kill flag and
fix context.

### Tenant migration split

Trigger: Route map cached inconsistently. Amplifier:
Reads and writes see different shard. Blast radius: Lost
writes or stale reads. First safe move: Freeze writes
and pin route.

### Metric cardinality explosion

Trigger: tenant_id added to HTTP metric. Amplifier: Many
tenants create series. Blast radius: Observability
degrades. First safe move: Drop label and use top-N
logs.

### Shared DLQ leak

Trigger: All tenant failed events in one support view.
Amplifier: Payload contains PII. Blast radius: Support
sees unrelated tenants. First safe move: Partition and
restrict DLQ viewer.

### Noisy KMS usage

Trigger: Tenant bulk decrypts objects. Amplifier: Shared
regional quota. Blast radius: Other tenants fail
decrypt. First safe move: Throttle job and cache data
keys safely.

### Global cache flush

Trigger: Responder flushes Redis for one tenant.
Amplifier: Sessions share cluster. Blast radius: All
tenants re-login; origin storm. First safe move: Target
prefix invalidation.

## Decision framework

### Isolation decision matrix

| Requirement | Shared with guardrails | Partitioned/cell | Siloed |
| --- | --- | --- | --- |
| Small tenant, low variance | Usually right. | Only if cells already exist. | Usually wasteful. |
| Large bursty auction tenant | Risky without quotas. | Often right: shard/topic/cache partition. | Right if tenant pays for dedicated SLO. |
| Strict residency/regulation | Only with proven controls. | Possible by regional cell. | Often right for account/key boundary. |
| Custom schema/extensions | Risky. | Possible per schema/cell. | Often right if customization is deep. |
| High support/export risk | Possible with strong tooling. | Better with tenant pipelines. | Right for regulated enterprise. |
| Cost-sensitive long tail | Right. | May be too much overhead. | Wrong unless required. |

### Fairness incident sequence

1. Protect shared control plane and critical paths
   first: checkout, auth, session, payment, tenant
   routing, and policy stores.
2. Identify the scarce resource and top consumers with
   evidence, not tenant reputation.
3. Apply the narrowest safe limiter: tenant, endpoint
   class, job class, partition, query shape, or cache
   namespace.
4. Degrade optional and batch work before interactive or
   contractual work.
5. Communicate to affected support/customer success with
   exact limit and customer-visible behavior.
6. Avoid global destructive actions such as cache
   flushes, disabling RLS, or raising all limits unless
   incident command accepts blast radius.
7. After stability, decide whether the tenant needs
   pricing, partitioning, dedicated infrastructure, or
   product changes.

### Design review checklist

1. Where is tenant context created, verified,
   propagated, and cleared?
2. Which APIs enforce object authorization close to the
   resource?
3. Can a test fail if a query omits tenant_id or RLS
   context?
4. Are cache keys, lock keys, idempotency keys, and
   rate-limit keys tenant-scoped?
5. What is the per-tenant budget for DB connections,
   Redis memory, Kafka bytes, search concurrency, and
   worker slots?
6. What is the largest tenant, and what happens when it
   doubles overnight?
7. How do we observe top tenants without adding
   tenant_id to every metric?
8. Which operations bypass tenant isolation, and how are
   they approved and audited?
9. What is the migration and rollback plan for moving a
   tenant between cells or shards?
10. What is the legal and communication path for
    suspected cross-tenant data exposure?

## Key takeaways

- Multi-tenancy is an isolation contract across every
  layer, not a schema trick.
- Shared infrastructure can be safe only when data
  isolation, fairness, and blast-radius controls are
  deliberate.
- Noisy-neighbor diagnosis starts by naming the scarce
  resource and proving tenant contribution.
- Rate limits are capacity allocation mechanisms; they
  should be tier-aware, endpoint-weighted, and
  resource-pressure aware.
- Tenant_id metrics everywhere are a cardinality and
  confidentiality trap.
- Siloing buys isolation at operational and cost
  expense; cell-based designs often provide a better
  middle ground.
- Bad mitigations often harm innocent tenants or create
  data exposure; narrow fixes beat global actions.

## Targeted reading

- AWS SaaS Lens for tenant isolation, deployment models,
  onboarding, and noisy-neighbor controls.
- PostgreSQL row-level security, roles, security barrier
  views, statement timeout, and connection pooling
  caveats.
- Redis command complexity, eviction policies, ACLs,
  latency monitoring, and cluster sharding.
- Apache Kafka quotas, partitioning, replication,
  consumer lag, retention, compression, and multi-tenant
  clusters.
- OpenSearch documentation on filtered aliases,
  index-per-tenant tradeoffs, shard sizing, thread
  pools, and query circuit breakers.
- OWASP API Security Top 10: broken object level
  authorization and unrestricted resource consumption.
- Kubernetes resource quotas, priority classes, limit
  ranges, network policies, and namespace isolation
  limitations.

## Principal-depth field guide: tenant isolation controls

### Principal stretch

Use these cards as design-review prompts and
incident-response heuristics. Each card names the
mechanism, the production signal, the failure it
prevents, and the strict decision rule. They are
intentionally concrete so that a staff or principal
engineer can turn them into runbook checks, CI policy,
or dashboard requirements.

### Tenant context creation

Mechanism: Tenant context is derived from authenticated
membership, not caller-supplied free text.

Production signal: authz logs with tenant source,
missing tenant context rejects.

Failure prevented: A caller chooses another tenant ID in
a request body.

Decision rule: Tenant context is server-derived and
immutable through the request.

### Object authorization

Mechanism: Every resource action checks tenant ownership
and action permission close to the resource.

Production signal: resource_owner_mismatch, authz deny
reason, route coverage.

Failure prevented: A valid user acts on another tenant
object by guessing ID.

Decision rule: Scopes never replace object-level tenant
checks.

### RLS pool hygiene

Mechanism: Connection pools reset tenant variables and
use roles that do not bypass RLS.

Production signal: pool reset failures,
app_role_bypasses_rls, RLS test results.

Failure prevented: One tenant setting leaks to the next
transaction.

Decision rule: RLS is only valid with pool reset and
non-bypass roles.

### Cache key builder

Mechanism: Tenant-specific data keys require tenant
component by type-safe builder.

Production signal: cache key lint, cross-tenant cache
tests, prefix coverage.

Failure prevented: product:123 serves the wrong seller's
price.

Decision rule: Raw string cache keys are banned for
tenant data.

### Cache quota

Mechanism: Shared caches enforce per-tenant memory/value
size/TTL limits by key class.

Production signal: evictions by key class, tenant memory
sample, hot keys.

Failure prevented: Analytics cache evicts sessions for
all tenants.

Decision rule: Session and analytics classes have
separate quotas or clusters.

### Hot key sharding

Mechanism: Auction leaderboards and celebrity objects
spread load without breaking correctness.

Production signal: top key ops, single-thread CPU,
request coalescing hits.

Failure prevented: One tenant hot key monopolizes Redis
CPU.

Decision rule: Hot keys above threshold are sharded or
moved to dedicated path.

### DB pool reservation

Mechanism: Interactive checkout has reserved connections
separate from imports and exports.

Production signal: pool usage by role, checkout reserved
remaining, wait time.

Failure prevented: Tenant import consumes every DB
connection.

Decision rule: Batch pools cannot starve interactive
pools.

### Statement timeout class

Mechanism: Interactive, export, support, and migration
queries have different timeouts and queues.

Production signal: timeout by class, temp spill, lock
wait by query class.

Failure prevented: One export holds snapshot and blocks
vacuum or IO.

Decision rule: Long work runs on replica/async path with
explicit budget.

### Tenant-aware partitioning

Mechanism: Kafka keys balance ordering needs against hot
tenant risk.

Production signal: bytes by partition and tenant hash,
leader network, lag.

Failure prevented: tenant_id key puts all celebrity
seller traffic on one partition.

Decision rule: Partition keys are load-tested with
largest tenant distribution.

### Producer quotas

Mechanism: Kafka producers have tenant and topic
byte-rate quotas matching tier and broker capacity.

Production signal: quota decisions, broker network,
producer throttle time.

Failure prevented: A premium tenant saturates shared
broker network.

Decision rule: Premium means higher quota, not unlimited
quota.

### Consumer fairness

Mechanism: Workers use fair queues or per-tenant
concurrency for shared async processing.

Production signal: queue age by tenant tier, worker
allocation, starvation count.

Failure prevented: One tenant backlog consumes every
worker.

Decision rule: Worker schedulers reserve capacity for
other tenants.

### Search filter alias

Mechanism: Shared search indexes enforce tenant filters
through aliases or query builders.

Production signal: queries missing tenant filter, alias
coverage, denied searches.

Failure prevented: Dashboard query returns another
tenant's documents.

Decision rule: Raw index access is restricted; aliases
are mandatory.

### Index-per-large-tenant

Mechanism: Very large tenants get indexes or shards when
shared index cost/risk exceeds threshold.

Production signal: shard heap, tenant query CPU,
rejected searches.

Failure prevented: Long-tail design collapses under
enterprise tenant volume.

Decision rule: Isolation threshold is based on query and
index pressure, not sales pressure.

### Object storage prefixes

Mechanism: Exports and signed URLs are scoped by tenant
prefix and policy.

Production signal: signed URL tenant, bucket access
denies, public prefix scan.

Failure prevented: Support export writes private data to
shared public prefix.

Decision rule: Tenant exports use generated scoped
prefixes and expiry.

### Support impersonation

Mechanism: Support access requires reason, approval,
tenant scope, and immutable audit.

Production signal: support_action audit, approval
coverage, break-glass use.

Failure prevented: Support tool becomes universal
cross-tenant client.

Decision rule: Support paths follow same object
authorization plus extra audit.

### DLQ segregation

Mechanism: Failed events with tenant data are
partitioned by tenant/security class in tooling.

Production signal: DLQ viewer access, payload class,
tenant filter coverage.

Failure prevented: Support sees another tenant payload
in shared DLQ.

Decision rule: DLQ access is least-privilege and
redacted by default.

### Feature flag context

Mechanism: Flag evaluation requires tenant, tier,
region, and environment context.

Production signal: flag evaluations missing tenant,
default path count.

Failure prevented: Tenant beta flag turns on globally.

Decision rule: Missing context fails closed for
tenant-scoped flags.

### Migration route map

Mechanism: Tenant shard/cell route maps are versioned,
cached briefly, and observed.

Production signal: route version skew, read/write shard
mismatch, cache TTL.

Failure prevented: Reads and writes split across source
and destination.

Decision rule: Tenant moves pin routes and keep source
authoritative until verified.

### Dual-write idempotency

Mechanism: During moves, dual writes are idempotent and
reconciled by counts and hashes.

Production signal: dual-write error, reconciliation
diff, duplicate key count.

Failure prevented: Migration creates lost or duplicate
writes.

Decision rule: Cutover requires verified reconciliation
and rollback path.

### Blast-radius estimate

Mechanism: Every tenant operation states affected
tenants and shared systems before execution.

Production signal: operation blast radius field,
cell/shard map, affected revenue.

Failure prevented: A fix for one tenant harms an
unrelated shard or cell.

Decision rule: No high-risk tenant action runs without
blast-radius estimate.

### Top-N heavy hitters

Mechanism: Observability captures top tenants through
controlled logs/reports, not universal metric labels.

Production signal: top-N resource report, metric series
count, tenant hash sample.

Failure prevented: tenant_id labels melt metrics or
reveal business facts.

Decision rule: High-volume metrics aggregate; forensic
logs carry tenant ID under access control.

### Tenant cost share

Mechanism: Noisy-neighbor reviews include
cost/revenue/tier context, not only technical usage.

Production signal: tenant resource share, gross margin
by tier, entitlement use.

Failure prevented: A tenant uses enterprise resources on
standard pricing.

Decision rule: Pricing and isolation decisions use
measured resource share.

### Adaptive fairness

Mechanism: Limits tighten on resource pressure and relax
when safe, with anti-oscillation guards.

Production signal: limit changes, saturation, 429 by
tier, retry-after compliance.

Failure prevented: Static limits are too high during
incidents and too low during normal bursts.

Decision rule: Adaptive limits use saturation windows
and minimum guarantees.

### Global safety bucket

Mechanism: Per-tenant buckets sit under a platform
global limit to protect shared systems.

Production signal: global bucket remaining, per-tenant
allow/deny, saturation.

Failure prevented: Every tenant individually complies
but aggregate load melts service.

Decision rule: Global and tenant budgets are both
required.

### Abuse versus load

Mechanism: Runbooks separate malicious abuse from
legitimate entitlement overuse.

Production signal: risk score, auth failures, workload
class, tenant comms.

Failure prevented: A good customer is treated as
attacker or attacker as customer.

Decision rule: Mitigation can be same throttle, but
communication and evidence differ.

### KMS quota isolation

Mechanism: Bulk tenant decrypt jobs have quotas and
data-key caching where safe.

Production signal: kms decrypt by caller/tenant class,
throttle count.

Failure prevented: One tenant export exhausts KMS for
all tenants.

Decision rule: Bulk decrypt work is scheduled and
quota-aware.

### Cell sizing

Mechanism: Cells are sized for tenant mix, failure
containment, and evacuation capacity.

Production signal: cell utilization, largest tenant
share, evacuation headroom.

Failure prevented: A cell cannot absorb failover or
isolate a whale tenant.

Decision rule: Cells have maximum tenant share and
evacuation tests.

### Silo escape hatch

Mechanism: Enterprise isolation has a documented path
from shared to dedicated resources.

Production signal: migration readiness, dedicated cost,
contract trigger.

Failure prevented: Teams invent emergency snowflake
isolation under pressure.

Decision rule: Siloing is a productized path, not a
one-off incident hack.

### Schema drift control

Mechanism: Schema-per-tenant designs track migration
state and block incompatible app versions.

Production signal: migration version by tenant, drift
count, failed migrations.

Failure prevented: Some tenants run old schema with new
code.

Decision rule: App deploy checks tenant migration
compatibility.

### Per-tenant backup restore

Mechanism: Restore tests prove one tenant can be
restored without exposing or overwriting another.

Production signal: restore drill result, backup
encryption key, tenant scope.

Failure prevented: A restore for one tenant corrupts
shared data.

Decision rule: Tenant restore has tested isolation
semantics.

### Data residency cell

Mechanism: Tenant region/residency is enforced in
routing, storage, analytics, and support access.

Production signal: region route map, cross-region access
denies, data transfer.

Failure prevented: Analytics copies regulated tenant
data to wrong region.

Decision rule: Residency is a policy invariant checked
at every data movement.

### Runbook evidence preservation

Mechanism: Potential data exposure incidents preserve
logs before destructive mitigation.

Production signal: evidence bundle, retention hold,
redaction status.

Failure prevented: A cleanup action destroys proof
needed for legal review.

Decision rule: Stability work cannot erase exposure
evidence.

### Tenant communication

Mechanism: Customer success messages describe exact
degraded feature, limit, and ETA without leaking other
tenants.

Production signal: tenant comms log, approved status
page, support tags.

Failure prevented: A tenant learns another tenant caused
its outage.

Decision rule: Comms are tenant-safe and coordinated
through incident command.

### Limit increase review

Mechanism: Raising limits checks destination capacity,
shared dependencies, and fairness to other tenants.

Production signal: quota change audit, dependency
headroom, affected tenants.

Failure prevented: A premium tenant limit increase
starves everyone.

Decision rule: Higher tier raises budget within
capacity, never to unlimited.

### Shared fate registry

Mechanism: Services document which tenants share each
shard, topic, cache, and cell.

Production signal: tenant-to-resource map freshness,
unknown mappings.

Failure prevented: Incident team cannot identify
collateral tenants.

Decision rule: Resource maps are operational data, not
wiki trivia.

### Tenant delete safety

Mechanism: Deletion and offboarding are scoped, delayed,
auditable, and reversible within retention policy.

Production signal: delete job tenant, dry-run counts,
tombstone age.

Failure prevented: Wrong tenant deletion or shared
object deletion.

Decision rule: Destructive tenant jobs require dry-run
and approval.

### Idempotency tenant scope

Mechanism: Idempotency keys include tenant and operation
scope to avoid cross-tenant collisions.

Production signal: idempotency collision by tenant,
duplicate suppression logs.

Failure prevented: Tenant A suppresses Tenant B request
with same key.

Decision rule: Idempotency namespace includes tenant and
action.

### Rate-limit key scope

Mechanism: Limiter keys include tenant, credential,
endpoint class, and tier as appropriate.

Production signal: limit decision key sample, 429 by
class, missing key fields.

Failure prevented: One user's burst consumes whole
tenant or one tenant bypasses global cap.

Decision rule: Limiter keys are reviewed like cache
keys.

### Policy simulation

Mechanism: Authz policy changes run simulation against
production-shaped tenant/resource samples.

Production signal: would_allow/would_deny diff, sample
coverage.

Failure prevented: Policy deploy denies enterprise
tenant or allows cross-tenant read.

Decision rule: Policy changes require allow and deny
simulation.

### Noisy-neighbor postmortem

Mechanism: Postmortems record scarce resource, tenant
workload, missing guardrail, and pricing/isolation
follow-up.

Production signal: postmortem fields, action closure,
recurrence count.

Failure prevented: Teams fix the symptom and repeat with
another tenant.

Decision rule: Every noisy-neighbor incident updates
fairness controls.

## Additional principal reviewer checks: tenant operations

### Tenant entitlement ledger

Rate limits and isolation choices should trace to an
entitlement ledger: tier, contract, paid add-ons,
regulatory constraints, and approved exceptions.
Unlimited settings are rarely entitlements; they are
usually missing product decisions.

### Tenant-safe debugging

Debug endpoints and support tools must require tenant
context even when the caller is internal. A
production-only debug path is still an API surface; it
needs authorization, audit, expiry, and a kill switch.

### Fairness rollback

When a limiter change harms a tenant, rollback should
restore the previous tenant budget without disabling
global safety. Keeping global safety separate from
tenant entitlement lets responders fix a mistaken limit
while protecting shared capacity.

### Isolation test fixtures

Test data should include two tenants with colliding
resource IDs, cache keys, idempotency keys, and search
terms. Without collisions, tests prove only that the
happy path works, not that isolation works.

### Tenant move rehearsal

Practice moving a synthetic large tenant between shards
or cells before the emergency. Rehearsal proves routing
TTL, dual-write behavior, reconciliation, cache
invalidation, support visibility, and rollback while no
real tenant is at risk.

## Ops Sim: One Enterprise Seller Starves the Marketplace

**Time box:** 45 minutes   **Severity:** P1   **Service
/ domain:** Multi-tenant Redis/PostgreSQL/Kafka fairness
and data isolation   **Northstar system:** sellers,
checkout-api, seller analytics, feed-fanout

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
  Most buyers browse, but checkout confirmation stalls for some sellers.
  Seller dashboards time out for standard tenants.
  One enterprise seller running a celebrity auction asks for limits to be raised.

WHAT ON-CALL SEES:
  Redis session latency rises, Kafka consumer lag grows, and PostgreSQL lock waits spike on shard 7.
  Error reports mention many tenants, but top resource consumers point to seller_4812.
  Security flags one log line showing an order lookup without tenant_id.

BUSINESS CONSTRAINT:
  seller_4812 has a premium SLO and major revenue impact.
  Cross-tenant data exposure, even for one order, is a legal P0.
```

### 2. Telemetry pack

```text
METRICS:
  checkout_api_p99{seller_shard="7"}: 240ms -> 1.9s
  redis_cmd_duration_p99{cluster="session"}: 1.8ms -> 46ms
  redis_evicted_keys{key_class="session"}: 0/min -> 18k/min
  redis_top_key_sample: seller_4812:auction:leaderboard 41% ops
  pg_lock_wait_seconds{shard="7",query="seller_export"}: 0 -> 880 cumulative seconds/min
  pg_connections{role="seller_import"}: 40 -> 640 of 700 max
  kafka_consumer_lag{topic="checkout.events",partition="113"}: 12k -> 19M
  kafka_produce_bytes_top_tenant{tenant_hash="h4812"}: 61% of topic bytes
  authz_denies{reason="tenant_mismatch"}: 0 -> 3/min

LOG LINES:
  seller-export tenant=seller_4812 shard=7 query=all_orders range=365d rows=190M
  redis warning command=HGETALL key=seller_4812:auction:leaderboard bytes=4982119
  checkout-api order_lookup order_id=ord_99012 tenant_context=null path=/internal/orders/debug
  kafka quota tenant=seller_4812 action=allow bytes_s=89MB configured_quota=unlimited
  support-tool export approved_by=none tenant=seller_4812 role=breakglass

TRACES / EXPLAIN / LAG:
  PostgreSQL shard 7: Seq Scan seller_orders, filter tenant_id='seller_4812', temp spill 840GB
  Kafka partition 113: leader broker-9 network out 96%, request queue p99 740ms
  Unrelated seller checkout trace: Redis 88ms -> DB lock wait 1500ms -> Kafka produce 620ms -> timeout
```

### 3. Config pack

```yaml
tenant_fairness:
  seller_4812:
    tier: enterprise
    checkout_write_rps: unlimited
    analytics_concurrency: unlimited
    kafka_producer_quota_mb_s: unlimited
    redis_memory_soft_limit_mb: unlimited
postgres:
  app_role_bypasses_rls: false
  statement_timeout_ms: {interactive: 1500, export: 0}
  pgbouncer_pool: {seller_import_max_connections: 650, checkout_reserved_connections: 25}
redis:
  shared_clusters: [session, auction_leaderboards, analytics_cache]
  forbidden_commands: [KEYS]
  max_value_bytes: 10485760
bad_fix_candidate:
  flush_redis_cluster: session
  raise_pg_max_connections_to: 2000
  disable_internal_order_debug_endpoint_authz: true
```

### 4. Timeline and decision points

| Time | Event | Your move |
| --- | --- | --- |
| T+0 | Marketplace p99 alert and enterprise escalation arrive. |  |
| T+5 | Top consumers identify seller_4812; tenant_mismatch denies appear. |  |
| T+15 | Product asks to raise seller_4812 limits. |  |
| T+60 | Legal asks whether null tenant_context means exposure. |  |

### 5. Questions

1. Which scarce resources are saturated, and which
   tenant or operation drives each one?
2. Separate performance noisy-neighbor symptoms from
   possible data-isolation symptoms. Which is P1 and
   which might be P0?
3. Write the first 15 minutes of mitigation in order.
   Include the narrow limiter and what you avoid doing
   globally.
4. Evaluate bad fixes: flushing Redis, raising
   PostgreSQL max_connections, disabling debug endpoint
   authorization, and simply moving seller_4812 to
   another shard.
5. Capacity math: if seller_4812 is 61% of
   checkout.events bytes and broker-9 is at 96% network,
   what happens if you raise its Kafka quota by 50%
   without repartitioning?
6. Design the durable tenant isolation/fairness fix
   across Redis, PostgreSQL, Kafka, support tooling, and
   metrics. Give acceptance criteria.
7. Who is informed by T+10, and what evidence must be
   preserved for possible cross-tenant exposure review?

### 6. Self-score after answer key

| Error type | Did it happen? | Note |
| --- | --- | --- |
| Knowledge gap |  |  |
| Misread / wrong layer |  |  |
| Sequencing error |  |  |
| Capacity or blast-radius miss |  |  |
| Org / runbook miss |  |  |
| Careless slip |  |  |

**Pass:** correct scarce resources, safe tenant-scoped
sequencing, data-exposure preservation, and durable
fairness controls.
