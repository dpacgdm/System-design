# Answer Key - Transfer Foundations Northstar

> Open only after attempting the transfer drill.

## Q1 - Inventory

Expected problems:

1. **CDN privacy/cache correctness:** personalized GraphQL cached with `public, s-maxage=90`; Authorization not in key. Evidence: 86% hit ratio and cross-account complaints.
2. **gRPC L4 black hole:** `pick_first` and one channel per BFF behind NLB pin traffic to two pods. Evidence: two hot pods, four idle.
3. **DNS ndots expansion:** external hostname with fewer than 5 dots generates search-domain NXDOMAINs. Evidence: 510K CoreDNS qps, 68% NXDOMAIN.
4. **Replica freshness violation:** discount eligibility reads use async replicas and ignore commit LSN. Evidence: r2 lag 38s and duplicate discount complaints.
5. **Cassandra hot partition:** partition key begins with campaign ID; one campaign receives 19K writes/sec. Evidence: three hot replicas and low cluster median.
6. **Unsafe token movement:** streaming/compactions add load to already hot Cassandra replicas.
7. **etcd write storm:** rollout writes 650 x 6 = 3,900 objects into saturated etcd. Evidence: proposals pending and leader changes.

## Q2 - Causal graph

Public GraphQL cache leaks/stales member status -> users retry checkout and trigger extra eligibility calls. gRPC imbalance makes eligibility slow -> BFF retries -> more fraud calls and DNS lookups. DNS expansion makes fraud slower -> eligibility slower -> more retries. Replica-lag eligibility allows duplicate-discount decisions. Cassandra hot partition makes reservation uncertain; token movement amplifies IO. etcd saturation should not be converted into data-plane outage by draining healthy serving pods.

## Q3 - First 15 minutes

1. Declare P1 with privacy and correctness owners.
2. Restore `private, no-store` for personalized GraphQL; invalidate affected objects.
3. Stop duplicate-discount risk: require primary/required-LSN reads for eligibility and remove lagged replica from decision reads.
4. Switch gRPC to round_robin/xDS or Envoy; cap retries.
5. Fix fraud DNS with trailing dot or `ndots:1`; enable NodeLocal DNSCache.
6. Stop Cassandra token movement; degrade counters; keep final reservation on source-of-truth.
7. Freeze rollout controllers; do not drain NotReady nodes while data plane serves.

## Q4 - Consistency contract

After a write, reads that influence discount eligibility must go to primary or a replica whose replay LSN is >= the commit LSN returned by the write. If no replica qualifies within a small budget, route to primary or fail closed. Generic profile display can use async replicas with explicit staleness labels, but authorization/eligibility cannot.

## Q5 - CDN/security response

Immediate action: remove shared caching for personalized member summary and purge/invalidate affected entries after fixing the header. Potential leak: membership status, personalized eligibility, and account-associated summary fields. Prevention: CI/cache-policy tests that fail if identity-bearing fields are served with public/shared cache headers or a cache key lacking identity dimensions; prefer separate public and private endpoints.

## Q6 - DNS math

With four search suffixes plus absolute query, each lookup is about five DNS queries. At 16,000 calls/sec, that is about 80,000 DNS qps, with roughly 64,000 NXDOMAIN qps. Retried eligibility calls multiply both numbers. Mitigations: trailing dot, `ndots:1`, bounded DNS cache, and NodeLocal DNSCache.

## Q7 - Cassandra hot partition

Token movement moves ownership of token ranges; it does not split one logical partition's write load across more replica sets. Add bucket/shard to the partition key, e.g. `((campaign_id, shard_id), card_id, event_time)`, pre-bucket large campaigns, and aggregate availability asynchronously.

## Q8 - gRPC balancing

Replace `pick_first` with gRPC `round_robin`/xDS or an L7 Envoy/Istio layer that understands HTTP/2/gRPC streams. Success: pod CPU/p99 and request counts become even, hot-pod p99 falls, connection stream distribution covers all pods, and retry rate drops.

## Q9 - etcd/control plane

NotReady can be a control-plane symptom while existing pods continue serving. Draining forces rescheduling and more API writes, making etcd worse and potentially causing data-plane outage. Freeze rollouts/controllers, pause drains/evictions where safe, protect existing capacity, and reduce API write rate.

## Q10 - Bad fixes

- Purge with bad header: refills bad cache; change header first.
- All-primary reads forever: protects correctness but can starve writes; use required-LSN routing and pool isolation.
- 500 channels: connection storm; use bounded proper balancing.
- Scale CoreDNS only: treats symptom; fix ndots/query pattern.
- Faster token movement: worsens IO and does not split partition.
- Drain NotReady: converts control-plane issue into data-plane outage.
- Trust Redis summary: derived stale data; final checkout needs Cassandra/source-of-truth reservation.

## Q11 - T+60 runbook

Can degrade live counters, search freshness, and non-critical member summary display. Must preserve one-discount enforcement and gift-card reservation source of truth. Continuing launch requires IC, business owner, risk/security, and checkout/inventory owners to agree that correctness invariants are protected.

## Q12 - Prevention

Separate public/private GraphQL fields, cache-header tests, gRPC LB policy tests, DNS config standards for external names, required-LSN read routing for eligibility, Cassandra launch bucketing, retry budgets, rollout write-rate limits, etcd fsync/proposal alerts, and explicit approval gates for data-plane drains.



## Verification checklist by subsystem

- **CDN:** personalized endpoint returns `private, no-store`; shared cache hit ratio for that endpoint goes to zero; invalidation completes; no new cross-account tickets.
- **Postgres:** decision reads include required LSN; lagged replica r2 is removed from eligibility; primary pool waiters fall after selective routing replaces all-primary routing.
- **gRPC:** request count, stream count, CPU, and p99 distribute across all six pods; retry rate and deadline exceeded errors fall.
- **DNS:** top NXDOMAIN names disappear; CoreDNS qps and CPU fall; fraud lookup p99 returns to baseline.
- **Cassandra:** streaming stops; compactions drain; hot partition p99 improves or traffic is rate-limited; reservation truth remains source-of-truth.
- **etcd:** proposal backlog and leader changes fall; no new mass drains; existing checkout capacity remains stable.

## Runbook ownership

Incident command owns sequencing. Edge owner owns cache rollback and privacy evidence. Checkout owner owns eligibility consistency. Platform owner owns DNS/etcd safety. Inventory owner owns Cassandra degradation. Security/legal owns customer impact review. Business owner approves launch continuation after invariants are protected.

## Principal model response

### Incident thesis

This is not one outage with one root cause. It is a coupled
foundations failure where unsafe cache policy, connection
stickiness, DNS expansion, stale eligibility reads, Cassandra
partition design, and control-plane pressure all amplify each
other. A principal answer keeps three truths separate:

- privacy/correctness is already violated by personalized
  GraphQL caching;
- checkout correctness is at risk because discount eligibility
  and gift-card reservation reads are not authoritative;
- control-plane stress must not be converted into a data-plane
  outage by draining working capacity.

### Layer-by-layer evidence

Edge/cache:

- `Cache-Control: public, s-maxage=90` on personalized
  GraphQL is the privacy bug.
- Authorization missing from the cache key explains
  cross-account complaints.
- High cache hit ratio is bad here; it means the wrong object
  can be served efficiently.

Transport/LB:

- gRPC `pick_first` plus one long-lived channel per BFF means
  the NLB can scale pods without redistributing streams.
- Two hot pods and four idle pods prove connection-level
  imbalance, not aggregate CPU shortage.

DNS:

- External names with fewer than five dots trigger Kubernetes
  search suffix expansion.
- At 16k lookups/sec and roughly five queries per lookup, the
  resolver path sees about 80k qps, mostly NXDOMAIN.

Storage/consistency:

- Discount eligibility after a write cannot read any async
  replica; it needs primary or required-LSN replica routing.
- Cassandra hot partition is logical. More nodes do not split
  one campaign key already receiving 19k writes/sec.

Control plane:

- etcd leader churn and proposals pending mean rollout churn
  is itself a scarce resource.
- Draining NotReady nodes during etcd pain increases writes and
  can evict healthy data-plane pods.

### T+0 to T+15 sequence

1. Declare a P1 with privacy and checkout correctness
   invariants.
2. Freeze rollouts, autoscaling churn, node drains, Cassandra
   token movement, and broad cache purges until headers are
   fixed.
3. Change personalized GraphQL to `private, no-store` and only
   then purge/invalidate affected objects.
4. Route eligibility decision reads to primary or
   required-LSN replicas; remove lagged `r2` from decision
   reads.
5. Degrade noncritical member summary display if needed; do
   not degrade discount uniqueness or reservation truth.
6. Switch gRPC clients to round_robin/xDS/Envoy and cap
   retries to stop retry-fueled fanout.
7. Fix DNS with trailing dot or `ndots:1`; enable NodeLocal
   DNSCache where appropriate.
8. Stop Cassandra token movement and reduce counter/detail
   reads while keeping final reservation authoritative.
9. Freeze rollout controllers and protect existing serving
   pods from eviction.

### Required calculations

DNS: four search suffixes plus the absolute query creates
about five queries per lookup. At 16,000 external fraud calls
per second, resolver load is `16,000 * 5 = 80,000 qps`; if 68%
are NXDOMAIN, about 54,400 qps are pure failure work before
retries.

gRPC: if two pods carry nearly all traffic while six exist,
effective serving capacity is about one third of expected.
Adding pods behind `pick_first` can leave new pods idle until
clients reconnect.

Cassandra: 19k writes/sec into one partition stay on one
replica set. Adding nodes helps future token distribution but
not the current hot logical key. The fix is bucketing by
campaign and shard, not blind token movement.

Replica freshness: a 38s lag on eligibility reads means any
"one discount per buyer/order" decision can be made from a
state older than the write it is supposed to observe.

### Bad-fix physics

- Purging the CDN before fixing headers refills the bad shared
  cache.
- All-primary reads forever can protect correctness but can
  starve the write pool; use required-LSN routing and capacity
  isolation.
- Opening hundreds of gRPC channels creates a connection
  storm; use an L7-aware policy.
- Scaling CoreDNS treats the symptom while ndots still
  multiplies every lookup.
- Token movement during peak spends the same disk/network IO
  Cassandra needs for reads and compaction.
- Draining NotReady nodes turns a control-plane incident into
  a serving incident.
- Trusting Redis or GraphQL summary for final checkout uses a
  derived view as source of truth.

### Durable acceptance gates

- CI fails personalized GraphQL fields with public cache
  headers or missing identity dimensions.
- Required-LSN read routing is tested with a 60s lagged
  replica and proves eligibility does not use it.
- gRPC clients have a load-balancing policy conformance test.
- Kubernetes DNS config standards cover external names,
  ndots, and local cache.
- Cassandra launch review requires hot-key analysis,
  bucketing, TTL/compaction choice, and peak-write rehearsal.
- Rollout systems have API write-rate budgets and etcd health
  gates.
- Incident dashboards show cache privacy, DNS NXDOMAIN,
  stream distribution, replica freshness, hot partitions, and
  etcd health together.
