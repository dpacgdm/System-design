# Northstar Commerce — Fictional Company (Ops Sim Continuity)

Use this shared world so incidents compound across weeks.

---

## Business

- **Product:** Global marketplace + wallet + live auctions + seller analytics  
- **Scale (steady):** 12M DAU, 45k checkout peak TPS (events), 800k concurrent on major auctions  
- **Regions:** `us-east-1` (primary), `eu-west-1`, `ap-northeast-1`  
- **Cloud:** AWS-centric (explicit bias)

---

## Core systems (map to curriculum)

| System | Tech | Week hooks |
|--------|------|------------|
| Edge | CloudFront + ALB/NLB | W1 CDN/DNS/TCP |
| API | HTTP/2 + gRPC internal | W1 protocols |
| Session | Redis Cluster | W2/W3 cache + hashing |
| Checkout OLTP | PostgreSQL 15 + PgBouncer | W2/W4/W5 |
| Inventory | Cassandra | W2/W5 |
| Search | OpenSearch | W7/W12 |
| Async | MSK (Kafka) + Debezium CDC | W4/W6/W13 |
| Feed / notifications | Redis timelines + workers | W9 |
| Payments | Ledger service + PSP | W11 |
| Feature flags | Internal flags + AppConfig | W7 |
| Control plane | EKS + etcd | W4 Raft |
| Auth | Cognito + internal session + mTLS mesh | W08b |
| Multi-tenant sellers | Shared DB + tenant_id | W08b |

---

## Standing SLOs (reference)

| Service | SLI | SLO |
|---------|-----|-----|
| Checkout API | availability | 99.95% |
| Checkout API | p99 latency | 300ms |
| Bid WebSocket | delivery lag | <500ms p99 |
| Search freshness | CDC→index lag | <60s p99 |
| Payment capture | exactly-once business effect | 99.99% (dupes detectable) |

---

## Recurring failure themes (teach deliberately)

1. Cross-system capacity miss (fix A dumps load on B)  
2. Sync replication / quorum vs availability under sale spikes  
3. Cache poisoning / personalized content at CDN  
4. CDC slot WAL growth  
5. gRPC L4 black hole  
6. Celebrity / hot-key fan-out  
7. Flag rollout without parity gates  
8. Tenant noisy-neighbor on shared Redis/DB  

When writing a new Ops Sim, reuse names (`checkout-api`, `inv-cas`, `pay-ledger`, `feed-fanout`) so learners build a mental model of one platform.
