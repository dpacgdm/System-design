# Transfer Drill: Foundations Northstar - The Checkout Mirage

**Time box:** 60 minutes
**Concept range:** Weeks 1-4
**Novel failure:** A cross-layer checkout inconsistency caused by cache-key drift, DNS resolver amplification, replica freshness gaps, and a control-plane lease storm. This is not the Week 1 auction, Week 4 flash sale, or any module incident with nouns changed.

## Rules

1. Work from memory.
2. Answer in T+ order.
3. Name root cause, amplifier, symptom, and bad fix separately.
4. Use the telemetry numbers; do not say "scale it" without math.
5. Keep answers sealed until finished.

---

## 1. Scenario stem

```text
Northstar runs a premium membership launch.
Members can buy one discounted annual plan and one limited gift card.
The checkout path must guarantee:
  - one membership per user
  - no gift-card oversell
  - no approval based on stale fraud or balance state

Traffic:
  580,000 users waiting at launch
  74,000 checkout attempts/min at peak
  19,000 gift-card reservations/sec for the first 8 minutes

Architecture:
  Browser/mobile -> CloudFront -> BFF
  BFF exposes REST checkout and GraphQL membership summary
  BFF -> gRPC -> Eligibility service (6 pods behind internal NLB)
  Eligibility -> PostgreSQL primary + two async replicas
  Eligibility -> Redis reservation summary
  Eligibility -> fraud.member-risk-api.com
  Inventory reservation -> Cassandra RF=3
  Control plane -> etcd for feature-flag rollout controllers
```

---

## 2. Telemetry pack

```text
EDGE / HTTP:
  /graphql/memberSummary cache hit ratio: 4% -> 86%
  response header after deploy:
    Cache-Control: public, s-maxage=90, stale-while-revalidate=180
  cache key:
    host + path + normalized query
  Authorization forwarded to origin: true
  Authorization in cache key: false
  complaints:
    "I see member status for another account"
    "Checkout says I used my discount but page says I did not"

TRANSPORT / gRPC:
  Eligibility pods:
    e-1 CPU=95%, p99=2.1s
    e-2 CPU=91%, p99=1.8s
    e-3 CPU=12%, p99=35ms
    e-4 CPU=11%, p99=34ms
    e-5 CPU=10%, p99=37ms
    e-6 CPU=12%, p99=36ms
  gRPC client:
    load_balancing_policy: pick_first
    max_channels_per_bff: 1
    internal LB: L4 NLB

DNS:
  CoreDNS qps: 120,000 -> 510,000
  NXDOMAIN ratio: 68%
  pod resolv.conf: ndots:5
  external hostname: fraud.member-risk-api.com
  fraud call rate: 16,000/sec before retries

POSTGRES / CONSISTENCY:
  primary write TPS: 2,200 -> 7,800
  replica lag:
    r1=2.4s
    r2=38s
  membership summary reads routed to replicas: 72%
  write response includes commit_lsn but BFF ignores it
  duplicate discount complaints: 1,180 in 10 minutes

CASSANDRA / SHARDING:
  partition key: ((campaign_id), card_id, event_time)
  hot campaign_id: annual-2026
  hot partition writes: 19,000/sec
  hot replica CPUs: [98, 96, 95]
  cluster median CPU: 39
  token move started: true
  streaming: 180MB/sec

ETCD / CONTROL PLANE:
  feature-flag rollout writes: 650 nodes x 6 objects/node
  proposals_pending: 80 -> 18,500
  leader changes: +8 in 5 min
  WAL fsync p99: 8ms -> 240ms
  existing checkout pods serving capacity: 64% utilized
```

---

## 3. Config pack

```yaml
member_summary:
  cache_control: "public, s-maxage=90, stale-while-revalidate=180"
  cache_key_headers: []
  includes_personalized_fields: true

eligibility_grpc:
  load_balancing_policy: pick_first
  max_channels_per_bff: 1
  lb_type: L4

pod_dns:
  ndots: 5
  fraud_hostname: fraud.member-risk-api.com
  use_trailing_dot: false

membership_reads:
  use_required_lsn: false
  allow_replica_for_discount_eligibility: true

cassandra:
  partition_key: "((campaign_id), card_id, event_time)"
  move_tokens_during_launch: true

control_plane:
  rollout_max_concurrent_nodes: 650
  emergency_drain_notready_nodes: true
```

---

## 4. T+ timeline

| Time | Event | Your written move |
|------|-------|-------------------|
| T+0 | Membership launch opens; checkout p99 crosses 2s. | |
| T+5 | Privacy complaints and duplicate-discount reports arrive. | |
| T+15 | DNS, Cassandra, and etcd are all saturated; someone proposes broad scaling and drains. | |
| T+60 | Launch can continue only if one-discount and reservation truth are protected. | |

---

## 5. Bad fixes on the bridge

1. Purge CDN but keep the public GraphQL cache header.
2. Route all member reads to primary forever.
3. Set gRPC channels to 500 per BFF pod immediately.
4. Scale CoreDNS only and leave `ndots:5` unchanged.
5. Move Cassandra tokens faster because cluster median CPU is low.
6. Drain all NotReady nodes because Kubernetes says they are unhealthy.
7. Trust Redis reservation summary for final checkout because Cassandra is slow.

---

## 6. Capacity and blast-radius worksheet

Fill in before answering:

```text
Default ephemeral port range if needed: 32768-60999 = ______ ports
DNS fraud lookup rate before retries:
  fraud calls/sec = 16,000
  ndots expansion queries per lookup = ______
  total fraud DNS qps = ______
  expected NXDOMAIN qps = ______

Control-plane write burst:
  nodes = 650
  objects per node = 6
  total objects = ______

Cassandra hot partition:
  hot writes/sec = 19,000
  replica set size = 3
  does adding nodes split one partition? ______
```

---

## 7. Questions

**Q1 - Inventory of problems:** Identify at least six distinct problems. For each, name layer, mechanism, decisive evidence, and blast radius.

**Q2 - Causal graph:** Show at least four causal links between problems. Which are root causes, which are amplifiers, and which are symptoms?

**Q3 - First 15 minutes:** Give the exact mitigation sequence. Include what to stop, what to roll back, what to degrade, and what not to touch.

**Q4 - Consistency contract:** How should membership discount eligibility be read after a write? Explain required LSN routing and when a replica is acceptable.

**Q5 - CDN/security response:** What is the immediate edge action, what data may have leaked, and what durable cache-policy test prevents recurrence?

**Q6 - DNS math:** Complete the DNS amplification math and name two safe mitigations.

**Q7 - Cassandra hot partition:** Why does token movement not fix the launch hot spot? What data model would distribute writes next time?

**Q8 - gRPC balancing:** What should replace `pick_first` behind an L4 NLB? What verification proves success?

**Q9 - etcd/control plane:** Why is draining NotReady nodes unsafe here? What should platform freeze or throttle first?

**Q10 - Bad fix rejection:** Reject each bad fix and provide the safer alternative.

**Q11 - T+60 runbook:** What can remain degraded, what must be source-of-truth, and who approves continuing the launch?

**Q12 - Postmortem prevention:** List durable prevention items across CDN, DNS, gRPC, Postgres consistency, Cassandra sharding, and rollout safety.

---

## 8. Self-score

| Error type | Did it happen? | Note |
|------------|----------------|------|
| Privacy cache leak missed | | |
| Required-LSN read missed | | |
| Hot partition confused with hot node | | |
| Control-plane/data-plane confusion | | |
| DNS math skipped | | |
| Unsafe bad fix accepted | | |

**Answer key:** [`../answers/Ops-Sims/Transfer-Foundations-Northstar Answers.md`](../answers/Ops-Sims/Transfer-Foundations-Northstar%20Answers.md)
