# Migration and Cutover

Northstar Commerce now has enough moving parts that the
hard problems are not only algorithmic. Checkout,
inventory, seller analytics, auth, rate limits, feature
flags, CloudFront, MSK, Debezium CDC, PostgreSQL, Redis,
mobile clients, and support tools all preserve different
invariants. Operations hardening is the practice of making
changes, tests, defenses, and clients safe when those
invariants meet real traffic.

This Week 08c module sits between the mechanism weeks and
the large design weeks. It assumes the learner remembers
DNS, HTTP, caches, replication, queues, outbox, feature
flags, observability, SLOs, rate limits, auth, cost, and
tenancy. The goal is to force those pieces into rollout
and incident decisions instead of isolated flash cards.

A migration is not a deploy. A deploy changes code; a
migration changes which states are legal, which readers
understand them, which writers produce them, and which
rollback path still exists. Cutover is the moment
authority moves, but the safe work happens before that
moment: expand, observe, backfill, verify, route, and only
then contract.

Northstar uses this topic whenever checkout schema
changes, seller routing maps move tenants, analytics
projections are rebuilt, payment ledger writes are
redirected, or CDC ownership moves from one consumer
pipeline to another. The same mechanics apply whether the
change is a PostgreSQL column split, a Kafka topic
repartition, a CloudFront DNS move, or a mobile API
version transition.

## Learning objectives

### Foundation

> Staff is the mastery gate; Principal stretch is optional depth.


1. Model migrations as state machines with allowed writer
   and reader versions, not as one-time scripts.
2. Use expand/contract sequencing for schema, API, cache,
   topic, and storage changes.
3. Design dual-write paths with idempotency, ownership,
   reconciliation, and a plan to stop writing twice.
4. Use shadow reads and parity checks without putting
   experimental output on the user path too early.
5. Plan data backfills with chunking, throttling,
   checkpointing, verification, and rollback boundaries.
6. Cut over with feature flags, routing maps, percentage
   gates, tenant/cell gates, and explicit stop conditions.
7. Explain DNS, TTL, connection pool, JVM, mobile, and CDN
   caches that make cutover slower than the control plane
   says.
8. Move CDC readers safely by reasoning about source LSNs,
   offsets, snapshots, lag, and duplicate delivery.
9. Define rollback criteria before cutover so incident
   command does not invent safety rules under pressure.
10. Communicate migration state across product, support,
    security, finance, and SRE with evidence instead of
    hope.

## Wrong mental models

| Wrong model | Correction | Why it hurts |
| --- | --- | --- |
| The migration is done when the script finishes | It is done when all readers, writers, data, caches, and rollback contracts are in the new steady state. | A completed backfill can still leave old writers corrupting new columns. |
| Dual-write means safer by default | Dual-write creates a second source of disagreement unless ownership and reconciliation are clear. | Divergent writes become harder to debug than the original migration. |
| Rollback is redeploying old code | Rollback must also restore routing, data authority, cache keys, offsets, and user-visible semantics. | Old code may not understand data produced after cutover. |
| DNS TTL controls all clients | Many clients, pools, resolvers, mobile apps, and JVMs cache beyond authoritative TTL. | Traffic continues to old endpoints while dashboards say cutover succeeded. |
| Backfill can run as fast as spare CPU allows | Backfill consumes locks, IO, WAL, cache, queue, replicas, and human attention. | A harmless script fills WAL or starves checkout. |
| Shadow reads prove safety if counts match | Counts are necessary but insufficient; compare semantics, slices, latency, and decision impact. | Wrong prices can match row counts. |
| Feature flags are just booleans | Flags are runtime control planes with targeting, TTL, cache, audit, and kill-switch behavior. | A stale mobile or edge flag can keep the bad path alive. |
| CDC cutover is changing a consumer group | CDC cutover includes snapshot boundary, LSN ownership, offset fences, and duplicate handling. | The new projection misses rows or replays side effects. |
| Contract can happen immediately after cutover | Contract waits until old clients, old jobs, old caches, and rollback windows are gone. | A long-lived worker reads a dropped column. |
| The safest cutover is global and quick | Small cells, tenants, and reversible routing reduce blast radius while preserving observability. | A global move removes comparison and rollback room. |

## Core mechanism

### 1. Migration state machines

A safe migration names every state the system can be in:
old only, expanded but unused, dual-written, shadow-read,
cut over for a slice, cut over globally, and contracted.
Each state has allowed reader versions, writer versions,
data repair actions, and rollback edges. If a state cannot
be named, it cannot be monitored.

- State must be explicit in dashboards and runbooks.
- Every transition has a precondition and an abort
  condition.
- Rollback edges disappear over time; mark when they
  close.
- Never let a background job create a state the API cannot
  read.
- Audit records should show who moved the migration state.

| Lens | Question to ask | Northstar example |
| --- | --- | --- |
| Invariant | What must stay true while migration state machines changes? | Checkout money effects, tenant isolation, or seller trust. |
| Authority | Which system is source of truth while migration state machines is active? | Name the Northstar owner for Migration state machines: API, data platform, mobile, edge, fraud, or payments. |
| Time | Which time window controls migration state machines risk? | Use the relevant TTL, retry budget, lag, offset, stale age, or rollout window for Migration state machines. |
| Blast radius | Which slice sees migration state machines first? | Compare cell, tenant tier, region, route, app version, and dependency for Migration state machines. |
| Rollback | What rollback edge remains open for migration state machines, and when does it close? | Name the old path, old data shape, old client, old control-plane value, or evidence store tied to Migration state machines. |

### 2. Expand/contract schema changes

Expand/contract adds new structures while old code still
works, teaches writers to populate both views, teaches
readers to prefer the new view only after parity, and
removes old structures last. It is a compatibility
protocol between versions, not a naming style.

- Expand with nullable or default-safe fields first.
- Avoid table rewrites on hot paths during peak.
- Write old and new until read parity is proven.
- Contract only after old binaries and jobs are gone.
- Migration tests must include rollback from each state.

| Lens | Question to ask | Northstar example |
| --- | --- | --- |
| Invariant | What must stay true while expand/contract schema changes changes? | Checkout money effects, tenant isolation, or seller trust. |
| Authority | Which system is source of truth while expand/contract schema changes is active? | Name the Northstar owner for Expand/contract schema changes: API, data platform, mobile, edge, fraud, or payments. |
| Time | Which time window controls expand/contract schema changes risk? | Use the relevant TTL, retry budget, lag, offset, stale age, or rollout window for Expand/contract schema changes. |
| Blast radius | Which slice sees expand/contract schema changes first? | Compare cell, tenant tier, region, route, app version, and dependency for Expand/contract schema changes. |
| Rollback | What rollback edge remains open for expand/contract schema changes, and when does it close? | Name the old path, old data shape, old client, old control-plane value, or evidence store tied to Expand/contract schema changes. |

### 3. Dual-write ownership

Dual-write is useful when two stores must stay warm during
a move, but one side must remain authoritative until
cutover. The secondary write should be idempotent and
reconcilable. If both sides can independently accept
business decisions, the migration has split-brain risk.

- Use stable operation IDs across both writes.
- Persist write intent before external side effects.
- Emit reconciliation events for mismatches.
- Track dual-write latency separately from user latency.
- Have a plan to stop dual-writing and clean drift.

| Lens | Question to ask | Northstar example |
| --- | --- | --- |
| Invariant | What must stay true while dual-write ownership changes? | Checkout money effects, tenant isolation, or seller trust. |
| Authority | Which system is source of truth while dual-write ownership is active? | Name the Northstar owner for Dual-write ownership: API, data platform, mobile, edge, fraud, or payments. |
| Time | Which time window controls dual-write ownership risk? | Use the relevant TTL, retry budget, lag, offset, stale age, or rollout window for Dual-write ownership. |
| Blast radius | Which slice sees dual-write ownership first? | Compare cell, tenant tier, region, route, app version, and dependency for Dual-write ownership. |
| Rollback | What rollback edge remains open for dual-write ownership, and when does it close? | Name the old path, old data shape, old client, old control-plane value, or evidence store tied to Dual-write ownership. |

### 4. Shadow reads

A shadow read executes the candidate path beside the real
path and discards the candidate result except for
telemetry. It should never call non-idempotent side
effects, mutate caches as authority, or extend user
latency beyond a budget without an explicit experiment
flag.

- Compare row-level hashes and semantic fields.
- Slice by tenant, region, API version, and item class.
- Sample enough high-risk cases, not only happy path.
- Do not cache shadow output as user-visible truth.
- Alert on disagreement type, not only disagreement count.

| Lens | Question to ask | Northstar example |
| --- | --- | --- |
| Invariant | What must stay true while shadow reads changes? | Checkout money effects, tenant isolation, or seller trust. |
| Authority | Which system is source of truth while shadow reads is active? | Name the Northstar owner for Shadow reads: API, data platform, mobile, edge, fraud, or payments. |
| Time | Which time window controls shadow reads risk? | Use the relevant TTL, retry budget, lag, offset, stale age, or rollout window for Shadow reads. |
| Blast radius | Which slice sees shadow reads first? | Compare cell, tenant tier, region, route, app version, and dependency for Shadow reads. |
| Rollback | What rollback edge remains open for shadow reads, and when does it close? | Name the old path, old data shape, old client, old control-plane value, or evidence store tied to Shadow reads. |

### 5. Feature-flag cutover

Flags make cutover reversible only when evaluation is
fast, scoped, audited, and has a safe default. The flag
controls traffic to the new authority, not the existence
of the migration. A flag without compatibility work is a
panic switch painted green.

- Target by cell, tenant, tier, app version, and route.
- Cache flag values for bounded time with kill switch
  override.
- Require context; missing context fails to old safe path.
- Write flag changes to the incident timeline.
- Keep flag and code owners available during cutover.

| Lens | Question to ask | Northstar example |
| --- | --- | --- |
| Invariant | What must stay true while feature-flag cutover changes? | Checkout money effects, tenant isolation, or seller trust. |
| Authority | Which system is source of truth while feature-flag cutover is active? | Name the Northstar owner for Feature-flag cutover: API, data platform, mobile, edge, fraud, or payments. |
| Time | Which time window controls feature-flag cutover risk? | Use the relevant TTL, retry budget, lag, offset, stale age, or rollout window for Feature-flag cutover. |
| Blast radius | Which slice sees feature-flag cutover first? | Compare cell, tenant tier, region, route, app version, and dependency for Feature-flag cutover. |
| Rollback | What rollback edge remains open for feature-flag cutover, and when does it close? | Name the old path, old data shape, old client, old control-plane value, or evidence store tied to Feature-flag cutover. |

### 6. Backfill mechanics

Backfills are production workloads. They need chunk keys,
checkpoints, rate limits, retries, idempotency,
verification, and safe pauses. The backfill rate is chosen
from the smallest spare resource, not from the fastest
loop a developer can write.

- Chunk by stable primary key or time range.
- Record high-water marks and completed chunk hashes.
- Throttle on database IO, WAL, replica lag, and p99.
- Treat failed chunks as resumable work, not mystery gaps.
- Use read replicas only when staleness is acceptable.

| Lens | Question to ask | Northstar example |
| --- | --- | --- |
| Invariant | What must stay true while backfill mechanics changes? | Checkout money effects, tenant isolation, or seller trust. |
| Authority | Which system is source of truth while backfill mechanics is active? | Name the Northstar owner for Backfill mechanics: API, data platform, mobile, edge, fraud, or payments. |
| Time | Which time window controls backfill mechanics risk? | Use the relevant TTL, retry budget, lag, offset, stale age, or rollout window for Backfill mechanics. |
| Blast radius | Which slice sees backfill mechanics first? | Compare cell, tenant tier, region, route, app version, and dependency for Backfill mechanics. |
| Rollback | What rollback edge remains open for backfill mechanics, and when does it close? | Name the old path, old data shape, old client, old control-plane value, or evidence store tied to Backfill mechanics. |

### 7. DNS and traffic cutover

DNS is a hint with caching. Authoritative TTL, recursive
resolver TTL, client DNS cache, HTTP connection pools,
HTTP/2 sessions, TLS session tickets, JVM settings, mobile
offline behavior, and CDN origin shields can all keep
traffic on old routes.

- Lower TTL before the move, then wait real TTL windows.
- Drain connections and watch old endpoint request rate.
- Expect some clients to ignore TTL until restart.
- Use application routing when DNS precision is not
  enough.
- Keep old endpoint healthy until observed traffic decays.

| Lens | Question to ask | Northstar example |
| --- | --- | --- |
| Invariant | What must stay true while dns and traffic cutover changes? | Checkout money effects, tenant isolation, or seller trust. |
| Authority | Which system is source of truth while dns and traffic cutover is active? | Name the Northstar owner for DNS and traffic cutover: API, data platform, mobile, edge, fraud, or payments. |
| Time | Which time window controls dns and traffic cutover risk? | Use the relevant TTL, retry budget, lag, offset, stale age, or rollout window for DNS and traffic cutover. |
| Blast radius | Which slice sees dns and traffic cutover first? | Compare cell, tenant tier, region, route, app version, and dependency for DNS and traffic cutover. |
| Rollback | What rollback edge remains open for dns and traffic cutover, and when does it close? | Name the old path, old data shape, old client, old control-plane value, or evidence store tied to DNS and traffic cutover. |

### 8. CDC cutover

CDC pipelines have a snapshot boundary and a stream
boundary. A correct cutover says exactly which LSN or
offset separates old projection ownership from new
projection ownership. Duplicate delivery must be harmless;
missing delivery must be detectable.

- Capture source LSN at snapshot start and completion.
- Pause or fence old consumers before authority moves.
- Store projection version and source offset together.
- Compare lag in time, bytes, and business freshness.
- Do not drop old slots until recovery path is clear.

| Lens | Question to ask | Northstar example |
| --- | --- | --- |
| Invariant | What must stay true while cdc cutover changes? | Checkout money effects, tenant isolation, or seller trust. |
| Authority | Which system is source of truth while cdc cutover is active? | Name the Northstar owner for CDC cutover: API, data platform, mobile, edge, fraud, or payments. |
| Time | Which time window controls cdc cutover risk? | Use the relevant TTL, retry budget, lag, offset, stale age, or rollout window for CDC cutover. |
| Blast radius | Which slice sees cdc cutover first? | Compare cell, tenant tier, region, route, app version, and dependency for CDC cutover. |
| Rollback | What rollback edge remains open for cdc cutover, and when does it close? | Name the old path, old data shape, old client, old control-plane value, or evidence store tied to CDC cutover. |

### 9. Rollback criteria

Rollback is a business and correctness decision written
before the change. Good criteria include SLO burn by
slice, mismatch rate, error class, data drift, queue lag,
cost pressure, security invariant breach, and whether the
new data can be read by the old code.

- Rollback on correctness breach faster than latency
  breach.
- Prefer cell rollback before global rollback.
- Do not rollback into a schema the current data violates.
- Freeze contract steps when any rollback uncertainty
  appears.
- Keep customer communications tied to affected slices.

| Lens | Question to ask | Northstar example |
| --- | --- | --- |
| Invariant | What must stay true while rollback criteria changes? | Checkout money effects, tenant isolation, or seller trust. |
| Authority | Which system is source of truth while rollback criteria is active? | Name the Northstar owner for Rollback criteria: API, data platform, mobile, edge, fraud, or payments. |
| Time | Which time window controls rollback criteria risk? | Use the relevant TTL, retry budget, lag, offset, stale age, or rollout window for Rollback criteria. |
| Blast radius | Which slice sees rollback criteria first? | Compare cell, tenant tier, region, route, app version, and dependency for Rollback criteria. |
| Rollback | What rollback edge remains open for rollback criteria, and when does it close? | Name the old path, old data shape, old client, old control-plane value, or evidence store tied to Rollback criteria. |

### 10. Contract and cleanup

Contract removes compatibility scaffolding only when
evidence proves it is unused. The dangerous part of
cleanup is that it destroys rollback, old readers, old
cache keys, and forensic comparison. Contract deserves a
review even when the cutover was quiet.

- Search for old column, endpoint, topic, and flag usage.
- Inspect slow logs, job queues, mobile versions, and
  partners.
- Expire old caches after no old writers exist.
- Archive reconciliation evidence before deleting tables.
- Set a final alarm for unexpected old-path calls.

| Lens | Question to ask | Northstar example |
| --- | --- | --- |
| Invariant | What must stay true while contract and cleanup changes? | Checkout money effects, tenant isolation, or seller trust. |
| Authority | Which system is source of truth while contract and cleanup is active? | Name the Northstar owner for Contract and cleanup: API, data platform, mobile, edge, fraud, or payments. |
| Time | Which time window controls contract and cleanup risk? | Use the relevant TTL, retry budget, lag, offset, stale age, or rollout window for this mechanism. |
| Blast radius | Which slice sees contract and cleanup first? | Compare cell, tenant tier, region, route, app version, and dependency before trusting fleet averages. |
| Rollback | What rollback edge remains open for contract and cleanup, and when does it close? | Name the old path, old data shape, old client, old control-plane value, or evidence store tied to Contract and cleanup. |

## Production anatomy

Production anatomy is the concrete evidence a staff
engineer expects on the bridge: metrics with dimensions,
logs with reason codes, config that shows the dangerous
default, and runbook decisions tied to thresholds. A
design that cannot say what it will measure is not ready
for Northstar traffic.

### Telemetry pack

| Signal | Useful dimensions | Why it matters |
| --- | --- | --- |
| migration_state | cell, tenant_tier, route | Shows where the state machine actually is. |
| dual_write_mismatch_total | entity_type, field, writer_version | Separates count drift from semantic drift. |
| shadow_read_disagreement_ratio | route, tenant_tier, region | Cutover gate for candidate reads. |
| backfill_rows_per_second | job, shard | Backfill pace and stall detection. |
| backfill_lag_seconds | job, source_table | Age of unprocessed data. |
| postgres_wal_bytes_retained | cluster, slot | Detects CDC/backfill pressure before disk fills. |
| replica_replay_lag_seconds | replica, region | Prevents read-model verification from lying. |
| old_endpoint_request_rate | endpoint, client_class | Proves DNS and connection drain progress. |
| flag_eval_missing_context_total | flag, service | Finds unsafe global fallback. |
| rollback_edge_open | migration, state | Makes rollback availability visible. |
| cache_key_version_hit_ratio | key_class, version | Shows stale cache population after route change. |
| cdc_projection_offset | consumer, topic | Fences old and new projection authority. |
| tenant_cutover_error_rate | tenant_tier, cell | Prevents fleet averages from hiding paid slices. |
| contract_old_path_calls_total | binary, job | Blocks cleanup until old calls stop. |
| support_ticket_rate | migration, tenant_tier | Human signal that telemetry may miss. |

### Config pack

#### Safe flag shape

```text
flag: checkout.new_order_shape
owner: checkout-platform
safe_default: old_path
targeting:
  cells: [cell-a]
  tenant_tiers: [internal, beta]
  app_min_version: 2026.07.10
cache_ttl_seconds: 30
kill_switch: checkout.force_old_order_shape
requires_context: [tenant_id, cell, app_version, route]
audit: required
```

#### Dangerous flag shape

```text
flag: checkout.new_order_shape
safe_default: true
cache_ttl_seconds: 1800
requires_context: []
comment: enable globally once backfill is probably done
```

#### Backfill guardrails

```text
job: order_shape_backfill
chunk_key: order_id
chunk_size: 5000
max_rows_per_second: 25000
pause_when:
  checkout_p99_ms: "> 260"
  replica_lag_seconds: "> 10"
  wal_free_gb: "< 200"
  dual_write_mismatch_ratio: "> 0.001"
checkpoint_store: migration_control.order_shape_chunks
idempotency_key: migration_name + chunk_start + chunk_end
```

### Runbook anatomy

- Declare the protected invariant before naming the fix;
  this prevents fast actions that make the system less
  safe.
- Slice the symptom by cell, tenant tier, region, client
  version, route, and dependency before trusting a global
  graph.
- Identify the current authority for reads, writes, risk
  decisions, and customer communications.
- Name the pre-authorized mitigations and the actions that
  require security, finance, product, or executive
  approval.
- Write down the bad fixes the bridge is likely to propose
  so they can be rejected quickly and calmly.
- Keep a decision log with metric values before and after
  each mitigation; rollback without evidence is guessing.
- Assign one owner for customer/support language and one
  owner for evidence preservation.
- Set a timer to revisit temporary rules, flags,
  throttles, or queues so the incident fix does not become
  permanent architecture.

### Production review questions

1. What is the smallest blast radius that still gives
   meaningful evidence?
2. Which metric would change first if the suspected
   mechanism is true?
3. Which metric would stay green and mislead executives?
4. What scarce resource is consumed by the mitigation
   itself?
5. Which clients, jobs, or partners may continue old
   behavior after rollback?
6. What data must be preserved before cleanup or
   mitigation destroys it?
7. Which tenant or customer slice has a stricter contract
   than the fleet?
8. How will support distinguish pending, failed, rejected,
   and repaired customer states?
9. What is the maximum safe duration for any temporary
   degradation?
10. Who owns the follow-up test that prevents recurrence?

### Staff

## Failure catalog

| Failure | Trigger | Amplifier | Blast radius |
| --- | --- | --- | --- |
| Old writer survives | A cron job still writes old column only | New readers see null or stale value | Inventory decisions fail for one route |
| Dual-write drift | Secondary write times out but primary commits | Retry lacks stable operation key | New store misses paid orders |
| Shadow side effect | Candidate read warms shared cache | Wrong result becomes visible later | Cross-tenant price exposure |
| Backfill stampede | Job ignores replica lag | WAL and IO saturate | Checkout p99 burns budget |
| DNS optimism | TTL lowered after cutover begins | Clients keep old address | Two endpoints receive writes |
| CDC gap | Snapshot LSN not recorded | Stream starts too late | Search projection misses rows |
| CDC duplicate side effect | New consumer replays old offsets | External email/refund not idempotent | Duplicate customer actions |
| Unsafe contract | Column dropped while mobile old version remains | Old clients fail parsing | Mobile checkout outage |
| Flag missing context | Tenant flag evaluates globally | All tenants hit beta path | Enterprise SLO breach |
| Rollback data incompatibility | New code writes enum old code rejects | Rollback increases 500s | Incident gets trapped |
| Cache version leak | Old cache key reused for new semantics | Readers mix shapes | Wrong totals in cart |
| Tenant move without capacity | Whale seller moved to warm shard | Destination cache/IO saturates | Blast radius doubles |
| Support tool bypass | Admin export reads old and new tables separately | Counts disagree under dual write | False customer comms |
| Partner client lag | Partner still posts old API shape | Contract step rejects payloads | Fulfillment backlog |
| Contract evidence deleted | Reconciliation table dropped early | Cannot prove affected orders | Longer incident and credits |

Failure catalogs are not lists of scary nouns. Each row
should teach the incident shape: the trigger starts the
problem, the amplifier turns it into a distributed
failure, and the blast radius says who or what is harmed.
During a design review, pick the three rows most likely
for the proposed change and prove the telemetry and
rollback exist.

### Failure drill prompts

- For Old writer survives, what single metric would page
  before the customer-visible inventory decisions fail for
  one route?
- What mitigation reduces new readers see null or stale
  value without hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Dual-write drift, what single metric would page
  before the customer-visible new store misses paid
  orders?
- What mitigation reduces retry lacks stable operation key
  without hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Shadow side effect, what single metric would page
  before the customer-visible cross-tenant price exposure?
- What mitigation reduces wrong result becomes visible
  later without hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Backfill stampede, what single metric would page
  before the customer-visible checkout p99 burns budget?
- What mitigation reduces wal and io saturate without
  hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For DNS optimism, what single metric would page before
  the customer-visible two endpoints receive writes?
- What mitigation reduces clients keep old address without
  hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For CDC gap, what single metric would page before the
  customer-visible search projection misses rows?
- What mitigation reduces stream starts too late without
  hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For CDC duplicate side effect, what single metric would
  page before the customer-visible duplicate customer
  actions?
- What mitigation reduces external email/refund not
  idempotent without hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Unsafe contract, what single metric would page
  before the customer-visible mobile checkout outage?
- What mitigation reduces old clients fail parsing without
  hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Flag missing context, what single metric would page
  before the customer-visible enterprise slo breach?
- What mitigation reduces all tenants hit beta path
  without hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Rollback data incompatibility, what single metric
  would page before the customer-visible incident gets
  trapped?
- What mitigation reduces rollback increases 500s without
  hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Cache version leak, what single metric would page
  before the customer-visible wrong totals in cart?
- What mitigation reduces readers mix shapes without
  hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Tenant move without capacity, what single metric
  would page before the customer-visible blast radius
  doubles?
- What mitigation reduces destination cache/io saturates
  without hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Support tool bypass, what single metric would page
  before the customer-visible false customer comms?
- What mitigation reduces counts disagree under dual write
  without hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Partner client lag, what single metric would page
  before the customer-visible fulfillment backlog?
- What mitigation reduces contract step rejects payloads
  without hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

- For Contract evidence deleted, what single metric would
  page before the customer-visible longer incident and
  credits?
- What mitigation reduces cannot prove affected orders
  without hiding the root cause?
- Which customer or tenant slice is most likely to see
  this before the fleet average moves?

## Decision framework

Good operational decisions are conditional. They do not
say always use one pattern or never use another. They name
the invariant, workload shape, rollback cost, evidence
quality, and human ownership. Use this table as a forcing
function before launch and during incidents.

| Option | Use when | Caution |
| --- | --- | --- |
| Expand/contract | Changing data shape while multiple versions run | Requires compatibility discipline and delayed cleanup |
| Blue/green | Stateless serving path with clear traffic switch | Weak for long-lived data authority |
| Canary by cell | Need blast-radius control and slice telemetry | Requires routing and comparable cells |
| Dual-write | Need new store warmed while old remains source | Creates drift unless reconciled |
| Read shadow | Need confidence before serving candidate result | Only proves sampled paths and chosen assertions |
| Bulk backfill | Historical data must be converted | Consumes scarce resources and creates lag |
| CDC replay | Need ordered catch-up from source of truth | Offset mistakes cause duplicates or gaps |
| DNS cutover | Need simple endpoint move for broad clients | Caches and long connections limit precision |
| Application routing map | Need tenant/cell precision | Routing map itself becomes critical state |
| Freeze window | Correctness risk exceeds feature velocity | Expensive and must be short |

### Decision checklist

1. State the business invariant in one sentence. If the
   invariant is vague, stop and clarify.
2. Name the source of truth and the derived views. Never
   repair the source from an unverified projection.
3. Choose the rollout unit: request, tenant, seller tier,
   region, cell, app version, or control-plane version.
4. Define the abort condition before starting. Include
   correctness, latency, saturation, cost, security, and
   support signals.
5. Estimate cross-system capacity impact. A safe local fix
   can overload Kafka, Redis, Postgres, PSP, or support.
6. List data that becomes hard or impossible to recover
   after the next step.
7. Choose communication timing and audience based on
   affected slice, not global severity language.
8. Decide what can be automated and what must require
   human approval.
9. Set expiration for emergency mitigations and create a
   follow-up owner before leaving the bridge.
10. Write the acceptance test that would have caught the
    issue before launch.

### Northstar field practice cards

Use these cards as mini design-review prompts before the
Ops Sim. They are not answer keys; they force you to name
mechanism, evidence, invariant, and rollback before the
timed drill.

#### Card 01 - Column split on orders

- **Setup:** Checkout splits order_items JSON into
             line_item rows while old workers still write
             JSON.
- **Mechanism to name:** Expand/contract compatibility and
                         writer-version skew.
- **Evidence to request:** Writer version by route, null
                           new rows, dual-write mismatch
                           by field, old job write rate.
- **Safe first move:** Freeze contract, force missing-
                       context flag to old path, and keep
                       both representations.
- **Bad fix to reject:** Drop the JSON column because the
                         new table has most rows.
- **Durable gate:** No old-path writes for a full rollback
                    window plus parity by semantic hash.

#### Card 02 - Tenant route map move

- **Setup:** A whale seller moves to a new shard but
             cached routing maps differ across API pods.
- **Mechanism to name:** Authority of routing map and
                         cache TTL during tenant
                         migration.
- **Evidence to request:** Route-map version in traces,
                           source/destination write rates,
                           cache age, tenant p99.
- **Safe first move:** Pin tenant to one source of truth
                       and drain stale route-map caches by
                       cell.
- **Bad fix to reject:** Move more tenants to balance the
                         graph before proving destination
                         headroom.
- **Durable gate:** Route-map propagation SLO and stale-
                    version alarm before next move.

#### Card 03 - Dual-write to ledger replica

- **Setup:** Payment ledger events are copied to a new
             store for analytics and secondary write
             latency rises.
- **Mechanism to name:** Dual-write authority and
                         idempotent secondary writes.
- **Evidence to request:** Operation ID reuse, primary
                           commit success, secondary
                           timeout, reconciliation queue
                           age.
- **Safe first move:** Keep primary authoritative and make
                       secondary retry idempotently from
                       durable intent.
- **Bad fix to reject:** Let analytics query whichever
                         store responds first.
- **Durable gate:** Reconciliation mismatch threshold and
                    replay from source ledger events.

#### Card 04 - Backfill during sale

- **Setup:** Backfill runs faster after a quiet hour, then
             flash-sale traffic starts.
- **Mechanism to name:** Backfill as production workload
                         competing for WAL, IO, locks, and
                         cache.
- **Evidence to request:** WAL retained bytes, IO queue,
                           replica lag, lock waits,
                           checkout p99 by cell.
- **Safe first move:** Throttle or pause backfill on the
                       smallest spare resource.
- **Bad fix to reject:** Double workers because average
                         CPU is low.
- **Durable gate:** Backfill controller tied to WAL, lag,
                    p99, and error-budget burn.

#### Card 05 - Shadow read disagreement

- **Setup:** Shadow read count matches but totals differ
             for coupon orders.
- **Mechanism to name:** Semantic parity versus row-count
                         parity.
- **Evidence to request:** Field-level diffs, coupon route
                           slice, money totals,
                           rounding/version fields.
- **Safe first move:** Block cutover for coupon route and
                       preserve source-of-truth old
                       decision.
- **Bad fix to reject:** Ignore because disagreement ratio
                         is below one percent globally.
- **Durable gate:** Parity suite includes money,
                    discounts, currency, and tenant
                    slices.

#### Card 06 - DNS endpoint move

- **Setup:** Traffic remains on old checkout origin after
             Route 53 points to new one.
- **Mechanism to name:** TTL, resolver, client cache, and
                         connection-drain reality.
- **Evidence to request:** Old origin request rate, client
                           class, connection age, DNS TTL
                           observed by probes.
- **Safe first move:** Keep old origin healthy and drain
                       while routing writes safely.
- **Bad fix to reject:** Terminate old origin to force
                         clients to reconnect.
- **Durable gate:** Pre-cutover TTL lowering and old-
                    endpoint decay threshold.

#### Card 07 - CDC projection handoff

- **Setup:** New analytics projection starts after
             snapshot and misses late writes.
- **Mechanism to name:** Snapshot end LSN and stream
                         offset fence.
- **Evidence to request:** Snapshot start/end LSN,
                           consumer offset, source row
                           count, duplicate/gap audit.
- **Safe first move:** Restart projection from a known LSN
                       and make writes idempotent.
- **Bad fix to reject:** Patch missing rows from analytics
                         cache by hand.
- **Durable gate:** Projection stores source LSN with
                    every derived row.

#### Card 08 - Contract cleanup

- **Setup:** An old partner still posts legacy payloads
             after old endpoint removal.
- **Mechanism to name:** Contract timing across partners
                         and old clients.
- **Evidence to request:** Old endpoint request rate by
                           partner, error reason,
                           app/client version.
- **Safe first move:** Restore compatibility shim or
                       scoped route while preserving
                       audit.
- **Bad fix to reject:** Tell partner to retry until it
                         works.
- **Durable gate:** No legacy traffic for agreed window
                    plus partner sign-off.

#### Card 09 - Cache version drift

- **Setup:** New order shape reuses old cache key and old
             mobile parses cached value.
- **Mechanism to name:** Cache semantic versioning during
                         migration.
- **Evidence to request:** Cache key version hit ratio,
                           parser errors, app version,
                           payload shape.
- **Safe first move:** Version cache keys and expire old
                       unsafe values by route.
- **Bad fix to reject:** Flush all Redis globally during
                         checkout peak.
- **Durable gate:** Compatibility test with old app and
                    new cache payload.

#### Card 10 - Rollback edge closes

- **Setup:** New code writes enum the old binary cannot
             parse.
- **Mechanism to name:** Rollback compatibility and
                         irreversible data state.
- **Evidence to request:** Enum distribution, old parser
                           errors in replay, writer
                           version timeline.
- **Safe first move:** Stop new enum writes and deploy
                       compatibility reader before
                       rollback.
- **Bad fix to reject:** Rollback all pods immediately
                         because new deploy caused it.
- **Durable gate:** Rollback rehearsal with data produced
                    by every migration state.

#### Card 11 - Support export during drift

- **Setup:** Support exports affected orders from derived
             analytics table.
- **Mechanism to name:** Source of truth versus projection
                         during incident communication.
- **Evidence to request:** Source order rows, projection
                           lag, reconciliation status,
                           tenant context.
- **Safe first move:** Generate customer list from
                       authoritative order table plus
                       explicit lag notes.
- **Bad fix to reject:** Repair source from analytics
                         because it has fewer nulls.
- **Durable gate:** Support tooling labels projection
                    freshness and source authority.

#### Card 12 - Contract review

- **Setup:** Team wants to remove the dual-write
             reconciliation job after a quiet day.
- **Mechanism to name:** Contract cleanup evidence and
                         rollback window.
- **Evidence to request:** Old writer calls, mismatch
                           trend, late mobile versions,
                           partner traffic, job backlog.
- **Safe first move:** Keep reconciliation until old paths
                       and rollback window are closed.
- **Bad fix to reject:** Delete evidence tables to reduce
                         storage cost.
- **Durable gate:** Contract checklist signed by app,
                    data, support, and SRE owners.

### Principal stretch

## Ops Sim

### Northstar Checkout Order-Shape Cutover

**Time box:** 75 minutes  
**Severity:** P1  
**Service / domain:** Checkout OLTP, CDC, feature flags, DNS  
**Northstar system:** shared commerce platform

#### Rules

1. Answer from memory of this module and earlier Northstar
   weeks; do not open the key mid-drill.
2. Write decisions in order from T+0 to T+60, including
   what you intentionally do not do.
3. Name evidence for every claim: metric, log line, trace
   field, config key, or customer slice.
4. Include at least one capacity or blast-radius
   calculation before proposing a repair.
5. Do not put worked answers in this learner file; open
   the answer key only after attempting.

#### Scenario stem

```text
WHAT USERS SEE:
  Enterprise sellers in eu-west-1 report missing order line items
  in seller analytics 12 minutes after checkout succeeds. Buyer
  checkout success rate is globally 99.92%, but enterprise EU
  seller support tickets are rising.

WHAT ON-CALL SEES:
  The new normalized order_line_items table is live for 15% of EU
  tenants. The old JSON order_items column still exists. The
  analytics projection moved to the new table at T+18.

BUSINESS CONSTRAINT:
  Black Friday preview starts in four hours. Product wants the new
  order shape for promotion analytics, but payment correctness and
  enterprise seller reporting are higher priority.
```

#### Telemetry pack

```text
METRICS:
  checkout_success_rate_global: 99.92%
  checkout_success_rate_enterprise_eu: 98.1%
  shadow_read_disagreement_ratio{field=line_items}: 0.84%
  dual_write_mismatch_total{writer=v2026.07.11}: 1840/min
  backfill_rows_per_second: 31k -> 4k
  replica_replay_lag_seconds{eu_analytics}: 72
  wal_retained_gb{slot=debezium_orders_v2}: 640, +55GB/10min
  old_endpoint_request_rate{client=partner_fulfillment}: 9k/min
  flag_eval_missing_context_total{flag=checkout.new_order_shape}: 3.8k/min

LOG LINES:
  checkout-api: missing tenant context, defaulting checkout.new_order_shape=true
  order-writer: secondary insert timeout, primary json commit succeeded
  analytics-loader: projection offset 881244 < snapshot_end_lsn 881991
  partner-gw: POST /orders legacy payload accepted at old endpoint

TRACES / INSPECTION:
  order_id=o-91 has JSON item_count=4 and v2 line_item rows=3
  mismatch appears only when seller_promo_code is present
  old code cannot parse enum fulfillment_state='reserved_pending'
```

#### Config pack

```yaml
# one of these settings is dangerous
flag checkout.new_order_shape:
  safe_default: true
  cache_ttl_seconds: 900
  requires_context: []

backfill order_line_items:
  chunk_size: 50000
  pause_when_replica_lag_seconds: 120
  pause_when_wal_free_gb: 50

cdc projection orders_v2:
  snapshot_end_lsn: null
  start_stream_from: latest

rollback note:
  old reader rejects fulfillment_state=reserved_pending
```

#### Timeline and decision points

| Time | Event | Your move |
| --- | --- | --- |
| T+0 | Incident or gate failure declared; first dashboards are noisy. | Name invariant, commander, owner, and first slice query. |
| T+5 | A tempting fast fix appears in chat. | Decide whether to reject, defer, or scope it. |
| T+15 | Telemetry narrows the mechanism and blast radius. | Apply the smallest safe mitigation and record evidence. |
| T+30 | Support/product ask what customers are affected. | Communicate slice, status, and uncertainty. |
| T+60 | System is stable enough for durable repair planning. | Write acceptance tests and follow-up owners. |

#### Questions

1. Which layer owns the primary symptom: writer, backfill,
   CDC projection, DNS/client routing, or analytics
   reader? Name the mechanism.
2. Which five signals confirm the unsafe migration state?
   Which green global metric is a red herring?
3. Write the first 15-minute sequence. Which flag or
   routing changes happen first, and which contract step
   must be frozen?
4. Why is global rollback to old code dangerous in this
   case? What narrower rollback or freeze is safer?
5. Compute blast radius from the provided mismatch and
   request rates. What breaks if backfill concurrency is
   doubled now?
6. Define the CDC cutover repair: snapshot boundary,
   offset fence, duplicate handling, and projection
   verification.
7. What must the support and product update say by T+30,
   and which customers are included?
8. List three durable acceptance tests before attempting
   cutover again.

#### Self-score after opening the key

| Error type | Did it happen? | Note |
| --- | --- | --- |
| Knowledge gap |  |  |
| Wrong layer |  |  |
| Sequencing error |  |  |
| Capacity or blast-radius miss |  |  |
| Security/tenancy invariant miss |  |  |
| Org/comms miss |  |  |
| Careless slip |  |  |

**Pass bar:** correct mechanism, safe sequencing, explicit rejection of at least one bad fix, one numeric capacity or blast-radius check, and a durable prevention plan grounded in source of truth.

**Answer key:** [answers/Week-08c-Operations-Hardening/Migration and Cutover Answers.md](../answers/Week-08c-Operations-Hardening/Migration%20and%20Cutover%20Answers.md)

## Key takeaways

- A migration is a compatibility protocol with states, not
  a deploy script.
- Dual-write without authority and reconciliation creates
  split-brain data.
- Shadow reads must compare semantics and slices, not only
  row counts.
- Backfills spend WAL, IO, locks, cache, queue, and human
  attention.
- DNS, connection pools, and mobile clients outlive
  control-plane wishes.
- CDC cutover requires explicit snapshot and stream
  boundaries.
- Contract only after rollback, old readers, old caches,
  and old jobs are gone.

## Targeted reading

- Martin Kleppmann, Designing Data-Intensive Applications,
  chapters 4 and 11: schema evolution, logs, and stream
  processing.
- PostgreSQL documentation: ALTER TABLE locking behavior,
  logical replication slots, and monitoring replication
  lag.
- AWS Database Migration Service and Debezium
  documentation: snapshots, offsets, and restart behavior.
- AWS Route 53 and CloudFront documentation: DNS TTLs,
  origin routing, and cache invalidation semantics.
- LaunchDarkly or OpenFeature docs: targeting context,
  flag defaults, audit, and kill switches.
- Google SRE Workbook: canarying releases and safe rollout
  practices.
- Stripe engineering writing on idempotency keys and safe
  API evolution.
- Northstar Week 07 feature flags and Week 06 outbox/CDC
  modules before attempting this Ops Sim.

---

## Staff & Principal Stretch: Advanced Migration Protocols & CDC Boundary Math

### 1. The 5-Phase Expand-Contract Schema Evolution Matrix

To alter a live database schema (e.g., splitting a monolithic `orders` table into `orders` + `order_line_items`) with zero downtime, applications must progress strictly through the 5-phase expand-contract pattern:

```
EXPAND-CONTRACT STATE MACHINE:

  Phase 1: EXPAND SCHEMA      ──► Create new columns/tables (Nullable / Default values).
                                  Old code continues reading & writing Old Schema.

  Phase 2: DUAL-WRITE         ──► App writes to BOTH Old + New Schema in a single transaction.
                                  Reads still execute against Old Schema.
                                  Backfill job fills historical rows in New Schema.

  Phase 3: SHADOW READ        ──► App reads from Old Schema (authoritative), asynchronously reads
                                  from New Schema, and logs semantic field-level mismatches.

  Phase 4: READ CUTOVER       ──► App flips primary read path to New Schema.
                                  Dual-write continues so instant rollback remains possible.

  Phase 5: CONTRACT CLEANUP   ──► Stop dual-writes. Remove old columns/tables from database.
```

```
EXPAND-CONTRACT READ/WRITE AUTHORITY MATRIX:

  Phase              | App Write Path               | Primary Read Path | Rollback Safety
  ───────────────────┼──────────────────────────────┼───────────────────┼────────────────
  Phase 1 (Expand)   | Old Schema Only              | Old Schema        | Instant
  Phase 2 (Dual-W)   | Old Schema + New Schema      | Old Schema        | Instant
  Phase 3 (Shadow)   | Old Schema + New Schema      | Old Schema        | Instant
  Phase 4 (Read Cut) | Old Schema + New Schema      | New Schema        | Instant (Zero Data Loss)
  Phase 5 (Contract) | New Schema Only              | New Schema        | Irreversible (Old Schema Dropped)
```

### 2. Log Sequence Number (LSN) CDC Stream Fencing

Change Data Capture (CDC) engine transitions (e.g., Debezium / AWS DMS) require precise boundary alignment between the initial bulk snapshot and streaming replication logs to prevent missing or duplicated mutations:

1. **Snapshot Phase:** `SELECT * FROM table WITH (NOLOCK)` captures table state at PostgreSQL Log Sequence Number $\text{LSN}_{\text{start}}$. Record $\text{LSN}_{\text{snapshot\_end}}$ when snapshot completes.
2. **Stream Phase:** Consumer ignores streaming WAL events with $\text{LSN} < \text{LSN}_{\text{snapshot\_end}}$.
3. **Idempotency Merge:** Downstream consumer executes upserts (`INSERT ... ON CONFLICT DO UPDATE`) using source PK + WAL commit timestamp.

```
CDC LSN STREAM FENCING:

  PostgreSQL WAL Stream:  [ LSN: 100 ] ... [ LSN: 500 (Snapshot End) ] ... [ LSN: 800 (Live Stream) ]
                                                   │
                                                   ▼
  Consumer Action:                 DISCARD WAL < 500 ──► PROCESS WAL >= 500 (Upsert)
```

---

## Appendix A: Extended Principal SRE Field Guide for Migrations & Cutovers

### A.1 — Multi-Region Active-Active Traffic Cutover Sequence

```
MULTI-REGION TRAFFIC CUTOVER STEPS (us-east-1 to us-west-2):

  Phase 1: Pre-warm Target Cluster
    - Verify us-west-2 database read replicas have 0ms replication lag.
    - Warm ElastiCache Redis caches in us-west-2 via synthetic query replay.

  Phase 2: Shift Read Traffic (Weighted Route 53 DNS)
    - Adjust Route 53 Weighted Resource Record (WRR): 80% us-east-1 / 20% us-west-2.
    - Monitor p99 latency, 5xx error rates, and cache hit ratios in us-west-2 for 30 minutes.
    - Ramp DNS weights: 50/50 ──► 0/100 (100% us-west-2 reads).

  Phase 3: Shift Write Authority (Database Primary Cutover)
    - Demote us-east-1 PostgreSQL primary to Read-Only mode (SET default_transaction_read_only = on).
    - Wait for WAL replication slot in us-west-2 to reach pg_current_wal_lsn().
    - Promote us-west-2 read replica to Primary (pg_promote()).
    - Update application database connection pools to point to us-west-2 endpoint.
```

### A.2 — PostgreSQL Zero-Downtime Column Renaming Pattern

Renaming a column directly (`ALTER TABLE orders RENAME COLUMN price TO unit_price;`) acquires an `ACCESS EXCLUSIVE` lock on the table, blocking all reads and writes until complete.

```sql
-- ZERO-DOWNTIME COLUMN RENAME PROTOCOL (PostgreSQL):

-- Step 1: Add new column (Nullable)
ALTER TABLE orders ADD COLUMN unit_price NUMERIC(10,2);

-- Step 2: Create Trigger to Dual-Write from old column to new column
CREATE OR REPLACE FUNCTION sync_orders_unit_price()
RETURNS TRIGGER AS $$
BEGIN
    NEW.unit_price = NEW.price;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_sync_unit_price
BEFORE INSERT OR UPDATE ON orders
FOR EACH ROW EXECUTE FUNCTION sync_orders_unit_price();

-- Step 3: Backfill historical rows in background batches
UPDATE orders SET unit_price = price WHERE unit_price IS NULL;

-- Step 4: Deploy code that reads & writes unit_price

-- Step 5: Drop Trigger and old column (Contract Phase)
DROP TRIGGER trg_sync_unit_price ON orders;
ALTER TABLE orders DROP COLUMN price;
```

### A.3 — Checklist for Safely Deprecating Legacy Microservice Endpoints

```
LEGACY ENDPOINT DEPRECATION CHECKLIST:

  [ ] Step 1: Add OpenTelemetry tracing & Prometheus metrics to measure endpoint call rate by caller identity.
  [ ] Step 2: Issue formal deprecation warning headers in HTTP responses (Sunset: Wed, 11 Nov 2026 00:00:00 GMT).
  [ ] Step 3: Execute scheduled brownouts (5-minute deliberate 503 HTTP responses during off-peak hours).
  [ ] Step 4: Validate that zero production callers hit the legacy endpoint for 14 consecutive days.
  [ ] Step 5: Remove API routing rule at API Gateway / Mesh Ingress and delete legacy code.
```

### A.5 — Zero-Downtime Multi-Tenant Data Shard Rebalancing Protocol

Moving a high-volume enterprise tenant from Shard A to Shard B without taking the tenant offline requires dual-writes and CDC logical replication:

```
TENANT SHARD REBALANCING PROTOCOL:

  1. Initial Snapshot: Copy tenant historical data from Shard A to Shard B via `pg_dump` / `COPY`.
  2. Start CDC Stream: Debezium streams CDC mutation logs for Tenant ID from Shard A to Shard B.
  3. Reconcile Replication Lag: Wait until Shard B CDC replication lag < 10 milliseconds.
  4. Write Lock Window (< 50ms):
     - Briefly acquire exclusive lock on Tenant Router Key in ElastiCache Redis.
     - Flush remaining CDC buffer to Shard B.
     - Update Tenant Router Key to point to Shard B.
     - Release Tenant Router Key lock.
  5. Cleanup: Deprecate old tenant records on Shard A after 30-day verification window.
```

### A.6 — Cutover Rollback Risk Assessment Matrix

| Cutover Stage | Rollback Complexity | Data Loss Risk | Recovery Action |
| :--- | :--- | :--- | :--- |
| Phase 1 (Expand Schema) | Low | Zero | Drop new columns/tables. |
| Phase 2 (Dual-Write) | Low | Zero | Stop writing to secondary store. |
| Phase 3 (Shadow Read) | Low | Zero | Disable shadow read feature flag. |
| Phase 4 (Read Cutover) | Medium | Zero | Flip primary read feature flag back to old store. |
| Phase 5 (Contract Cleanup) | Critical (Irreversible) | High | Restore from S3 database snapshot + WAL replay. |

### A.7 — SRE Incident Case Study: Recovering from Split-Brain Data Drift in Dual-Write Cutover

```
POST-MORTEM INCIDENT ANALYSIS: DUAL-WRITE DATA DRIFT IN ORDER DATABASE MIGRATION

  BACKGROUND:
  During Phase 2 (Dual-Write) of an order database migration, secondary store writes began timing out
  silently due to network throttling.

  DRIFT MECHANISM:
  - The application committed primary writes to Database A but swallowed exceptions on Database B writes.
  - Over 6 hours, 45,000 orders were committed in Database A but were missing or corrupted in Database B.
  - Shadow reads were disabled, so telemetry failed to detect the data divergence prior to Phase 4 (Read Cutover).

  REMEDIATION ACTIONS:
  1. T+05m: Instantly flipped Read Cutover feature flag back to Database A (Primary Source of Truth).
  2. T+25m: Deployed an outbox reconciliation worker to diff Database A and Database B via CDC WAL logs.
  3. T+04h: Re-played missing 45,000 mutations to Database B using idempotent primary-key upserts.

  PREVENTION LESSONS:
  - Dual-writes MUST be wrapped in transactional outbox patterns or CDC streams; never swallow secondary errors.
  - Shadow reads with automated field-level parity metrics are MANDATORY before flipping read authority.
```

### A.8 — Automated Rollback Criteria & Health Gate Matrix

```
AUTOMATED ROLLBACK DECISION MATRIX FOR CUTOVERS:

  Health Indicator         | Warning Threshold | Critical Rollback Abort Threshold
  ─────────────────────────┼───────────────────┼─────────────────────────────────
  HTTP 5xx Error Rate       | > 0.05%           | > 0.5% for 2 consecutive minutes
  Dual-Write Mismatch Rate | > 0.01%           | > 0.1% of write operations
  Replication Slot WAL Lag | > 10 GB           | > 50 GB (Risk of Disk Exhaustion)
  p99 Latency Degradation  | > 20% increase    | > 100% increase over baseline
```

### A.9 — Post-Cutover Decommissioning & Cleanup Playbook

```
SAFELY DECOMMISSIONING OLD DATABASE SCHEMAS (PHASE 5 CONTRACT):

  [ ] Audit Telemetry: Confirm zero queries target old columns/tables across all microservices for 30 days.
  [ ] Archive Snapshots: Take final long-term KMS-encrypted snapshot of old database tables and store in S3 Glacier.
  [ ] Revoke Credentials: Revoke database IAM read/write permissions for legacy table objects.
  [ ] Drop Database Objects: Execute `DROP TABLE` / `DROP COLUMN` in production during low-traffic maintenance window.
```

### A.10 — Migration & Cutover Telemetry Metric Dictionary

```
COMPLETE METRIC REGISTRY FOR CUTOVER & MIGRATION PROTOCOLS:

  1. dual_write_mismatch_total{writer_version, table_name, field_name}
     - Type: Counter
     - Description: Field-level discrepancies detected during Phase 2 (Dual-Write) schema evolution.

  2. cdc_replication_lag_bytes{slot_name, consumer_group}
     - Type: Gauge
     - Description: Unread PostgreSQL WAL log bytes accumulated in replication slots.

  3. shadow_read_parity_mismatch_ratio{route, field}
     - Type: Gauge
     - Description: Percentage disagreement between authoritative reads and shadow target reads.

  4. backfill_progress_ratio{job_name, table_name}
     - Type: Gauge
     - Description: Percentage of total historical database rows backfilled into new schema.

  5. old_endpoint_traffic_qps{endpoint, client_identity}
     - Type: Gauge
     - Description: Remaining request rate targeting deprecated API routes prior to contract phase.
```

### A.11 — Comprehensive Socratic Review & Production Verification Drill

```
SOCRATIC REVIEW DRILL — MIGRATION & CUTOVER HARDENING:

  Question 1: Why must schema expansion (Phase 1) make all new columns nullable or provide default values?
  Answer 1: Existing application pods running older code versions do not know about the new columns and will omit them
            from INSERT statements. If the database enforces NOT NULL without defaults, old pods will fail with 500 errors.

  Question 2: What is the risk of dropping an unread PostgreSQL logical replication slot after a CDC migration?
  Answer 2: Dropping a replication slot releases the WAL retention lock. If the CDC engine needs to restart, missing WAL
            segments will require a full, expensive snapshot re-ingestion that can saturate database IOPS.

  Question 3: Why should DNS TTLs be lowered 48 hours BEFORE attempting a major region traffic cutover?
  Answer 3: Recursive DNS resolvers across ISPs cache IP records for the duration of the original TTL. Lowering TTL in advance
            ensures resolvers pick up the new IP address quickly when the DNS cutover record is changed.
```

### A.12 — Summary Architectural Invariants for Zero-Downtime Migrations

1. **5-Phase Expand-Contract Discipline:** Code and schema changes MUST progress strictly through Expand ──► Dual-Write ──► Shadow ──► Cutover ──► Contract.
2. **CDC Stream Fencing via LSN:** CDC consumers must fence snapshot boundaries using exact Log Sequence Numbers to avoid missed or duplicate WAL updates.
3. **Reversible Read Cutovers:** Read authority switches MUST remain reversible via feature flags until Phase 5 (Contract Cleanup) commences.

### A.13 — Staff SRE Case Study: Resolving PostgreSQL Replication Slot Disk Saturation

```
CASE STUDY: WAL DISK SATURATION DURING CDC CUTOVER

  BACKGROUND:
  During a zero-downtime migration of a 5 TB PostgreSQL database, the primary database disk reached 98% capacity,
  threatening an un-planned outage.

  ROOT CAUSE ANALYSIS:
  - A logical replication slot (`debezium_cdc_orders`) was created to stream CDC mutations to Kafka.
  - The CDC consumer worker crashed at T+2 hours due to an unhandled JSON parsing exception.
  - PostgreSQL held all WAL segments generated since T+2 hours to preserve logical replication sequence for the crashed slot.
  - WAL accumulation reached 450 GB over 8 hours, consuming all available disk space on the primary node.

  REMEDIATION STEPS:
  1. T+05m: Temporarily increased EBS Volume size from 1 TB to 2 TB (`aws ec2 modify-volume`).
  2. T+15m: Deployed hotfix to CDC worker parsing logic to skip malformed records and write to dead-letter queue.
  3. T+25m: CDC worker resumed reading, draining 450 GB WAL backlog within 45 minutes.

  PREVENTION LESSONS:
  - Setup Prometheus alerts for `pg_replication_slots_wal_bytes > 50 GB`.
  - Implement automated slot drop / alert triggers before WAL fills disk capacity.
```

### A.14 — Zero-Downtime Migration Checklist for Enterprise Platforms

```
ENTERPRISE MIGRATION CHECKLIST:

  [ ] Pre-Migration: Validate target environment CPU, RAM, and IOPS match or exceed source environment.
  [ ] Phase 1 (Expand): Deploy database migration scripts creating new tables/columns with default values.
  [ ] Phase 2 (Dual-Write): Enable transactional dual-writes; verify backfill job completion and zero error count.
  [ ] Phase 3 (Shadow Read): Enable shadow reads; verify field-level parity > 99.999% across 1,000,000 test queries.
  [ ] Phase 4 (Read Cutover): Switch primary read feature flag; observe system metrics for 48-hour stability window.
  [ ] Phase 5 (Contract Cleanup): Remove dual-write logic, drop old database columns, and archive migration artifacts.
```

### A.15 — Advanced Database Schema Migration Compatibility Matrix

```
DATABASE SCHEMA MIGRATION COMPATIBILITY RULES:

  1. Adding Columns ──────► MUST be NULLABLE or specify DEFAULT values (Phase 1 Expand).
  2. Deleting Columns ────► MUST stop reading/writing column in code >= 1 release cycle BEFORE dropping (Phase 5 Contract).
  3. Modifying Data Types ─► Add NEW column with target data type, dual-write, backfill, and cutover read path.
  4. Renaming Columns ────► Create NEW column, trigger-sync, backfill historical data, switch code, drop old column.
```

### A.16 — Zero-Downtime Migration Post-Mortem Template

```
POST-MORTEM RETROSPECTIVE TEMPLATE — ZERO-DOWNTIME MIGRATION:

  1. Migration Summary & Scope (Tables migrated, dataset volume, total duration).
  2. Telemetry Timeline (Phase 1 through Phase 5 start/end timestamps and operational milestones).
  3. Discrepancy & Parity Report (Field-level dual-write mismatch count, CDC replication lag stats).
  4. Incident / Escalation Log (Any unexpected alerts or emergency rollbacks executed).
  5. Action Items & Lessons Learned (Owner-assigned follow-up tasks for future cutovers).
```

























### A.17 — Zero-Downtime Migration & Cutover Operations Summary Table

| Migration Phase | Primary Operational Objective | Read Authority | Write Authority | Rollback Safety |
| :--- | :--- | :--- | :--- | :--- |
| Phase 1 (Expand) | Deploy schema additions (Nullable) | Old Schema | Old Schema | Instant (Drop New Column) |
| Phase 2 (Dual-Write) | Synchronize live mutations + Backfill | Old Schema | Old Schema + New Schema | Instant (Stop Dual-Write) |
| Phase 3 (Shadow Read) | Validate field-level semantic parity | Old Schema (Authoritative) | Old Schema + New Schema | Instant (Disable Shadow) |
| Phase 4 (Read Cutover) | Switch primary read path | New Schema | Old Schema + New Schema | Reversible via Feature Flag |
| Phase 5 (Contract) | Decommission old schema & code | New Schema | New Schema | Irreversible (Old Schema Dropped) |

### A.18 — Database Schema Migration Lock Timeout Best Practices

Executing `ALTER TABLE` statements in production without setting lock timeouts can lead to connection pool exhaustion:

```sql
-- RECOMMENDED POSTGRESQL MIGRATION SESSION SETTINGS:

-- 1. Set aggressive lock timeout to prevent blocking application queries for more than 2 seconds
SET lock_timeout = '2s';

-- 2. Set statement timeout to abort long-running migration queries
SET statement_timeout = '30s';

-- 3. Execute zero-downtime column addition
ALTER TABLE orders ADD COLUMN IF NOT EXISTS checkout_channel VARCHAR(32) DEFAULT 'WEB';
```


























---
