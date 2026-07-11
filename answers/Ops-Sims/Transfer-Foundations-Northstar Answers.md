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
