# Answer Key - Design Web Crawler

> Open only after attempting the learner file questions.

## Expert Analysis — Full Worked Response


```
Q1: ROOT CAUSE ANALYSIS
━━━━━━━━━━━━━━━━━━━━━━━

Primary: Concurrency increase 1→8 violated de-facto politeness budget.
Retailer WAF correlates burst requests from same ASN/subnet as DDoS signature.
robots.txt still allows crawling — this is rate/abuse detection, not robots.

Contributing factors:
  → Global flag change without per-host canary
  → No hard cap in application code (config-only limit)
  → Token bucket measured rate but not concurrent connection fingerprint
  → IP rotation attempted during active block — burned fresh IPs

Evidence chain:
  403 body contains WAF vendor marker
  concurrency metric pegged at 8 exactly when deploy landed
  rate token bucket shows adequate spacing — rules out simple rate limit

Q2: IMMEDIATE FIX (ORDERED — MINUTES MATTER)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  T+0 min:  FEATURE FLAG rollback max_concurrent 8→1 globally
            (Do NOT gradual rollout — partner already hot)

  T+2 min:  PAUSE frontier dequeue for retailer.com
            (URLs stay queued; zero new TCP connections to origin)

  T+5 min:  STOP IP rotation — rotating while blocked burns pool
            Document current blocked CIDR for partner abuse desk

  T+10 min: CONTACT partner via abuse@ / TAM with:
            - User-Agent string
            - Approximate fetch timeline
            - Acknowledgment of concurrency misconfiguration
            - Request whitelist restoration timeline

  T+15 min: After partner ack OR 403 rate <1% for 5 min on test fetch:
            Resume at 1 concurrent, 1 req/2s with jitter
            Monitor 403 rate per minute

  T+30 min: Gradual index recovery — prioritize product URLs from sitemap
            (high business value, known-good paths)

Q3: PREVENTION (SYSTEMIC FIXES)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  CODE ENFORCEMENT:
    const MAX_CONCURRENT_PER_HOST = 2  // not configurable above 2
    Deploy pipeline rejects config >2

  CANARY PROTOCOL:
    Politeness changes roll to 3 low-risk hosts for 24h
    Auto-rollback if any host 403_rate >2%

  ALERTS:
    fetch_403_rate{host} > 5% for 2 min → auto throttle host to 1 concurrent
    fetch_rps{host} > 2× 7-day baseline → page

  TESTING:
    Robots + rate policy simulator in CI
    Replay production traffic against staging with new politeness params

  RUNBOOK:
    "403 spike" → pause host → rollback → contact → slow resume
    Never rotate IPs during active block

Q4: INDEX RECOVERY WITHOUT RE-BLOCK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Phase 1 (hours 1-6): Sitemap-only crawl at 1 req/3s
    ~50K product URLs from sitemap index
    Skip follow-links until 403 rate stable 24h

  Phase 2 (day 2-7): BFS depth=1 from product pages only
    max 500K URLs; daily quota 100K fetches

  Phase 3 (week 2+): Full revisit schedule restored
    Partner confirmed whitelist restored

  Parallel: Serve stale index with "prices may be outdated" banner
    Better stale than empty for revenue URLs

POSTMORTEM ACTION ITEMS:
  □ Hard cap in code (owner: crawl-platform)
  □ Canary framework for politeness (owner: SRE)
  □ Partner notification automation (owner: partnerships)
  □ WAF response body logging (owner: fetcher)
  □ Incident added to Week 12 retention test
```


---

---

## Design Gates (mandatory) - Model Responses

These responses are intentionally gate-shaped rather than a second full design.
Use them to verify the design explicitly covers trust, abuse, tenancy, cost,
and blast radius.

### Gate 1 - Authn/z trust boundary

- State every principal: external user, internal service, admin/support actor,
  background worker, tenant, and third-party partner where applicable.
- Put the first trust boundary at the public edge or private service ingress,
  then name the enforcement point that owns object/action authorization.
- Accept only scoped identity artifacts with issuer, audience, expiry, and
  key/certificate validation. Service-to-service calls should use workload
  identity or mTLS, not ambient network trust.
- Fail closed for money, privacy, admin, and write paths. Degrade or serve
  cached public content only where policy explicitly allows it.

### Gate 2 - Abuse and misuse

- Identify the highest-amplification actor in `Design Web Crawler`: the one that can turn
  one request into many writes, fetches, fan-outs, model calls, or downstream
  retries.
- Use layered quotas: user/API key, tenant/tier, entity key, endpoint/job
  class, region/cell, and global safety cap.
- Distinguish organic flash traffic from abuse with per-key skew, user-agent
  or principal entropy, retry rate, error mix, and historical baselines.
- Bound retries with budgets, jitter, circuit breakers, and idempotency keys.

### Gate 3 - Multi-tenant isolation

- Name the tenancy model for every stateful plane: relational data, cache,
  queue/topic, object storage, search index, model/vector store, metrics, logs,
  and support exports.
- Tenant context must be explicit in APIs, async messages, cache keys, search
  filters, audit logs, and support tooling. Missing tenant context fails closed.
- Reserve or quota shared scarce resources: DB connections, Kafka partitions
  and bytes, cache memory/ops, worker concurrency, indexing bandwidth, and
  third-party API calls.
- Prove isolation with cross-tenant cache/search/export tests, route-map tests,
  and incident kill switches for one tenant or cell.

### Gate 4 - Unit cost at target scale

- Define one business unit and compute order-of-magnitude cost at target scale
  and at peak multiplier. Include idle headroom and replication, not only
  request CPU.
- Dominant line items usually include storage retention, egress/cross-AZ or
  cross-region transfer, observability ingest, model/API calls, NAT, cache
  memory, and replay/rebuild capacity.
- Page on cost per successful business unit and slope by feature/deploy/tenant,
  not only monthly spend after the fact.
- Preferred degradation cuts optional analytics, freshness, ranking depth,
  export concurrency, or non-critical replicas before correctness-critical
  writes and reads.

### Gate 5 - Failure blast radius

- Declare the intended blast-radius boundary: partition, shard, tenant, topic,
  cell, region, queue, worker pool, cache namespace, or model version.
- Separate critical and non-critical paths so analytics, exports, replay,
  recommendation/ranking, or support tooling cannot starve checkout, payment,
  auth, or core serving.
- Document runbook hazards: global cache flush, raising max connections,
  disabling auth, removing rate limits, replaying without throttle, or widening
  a feature flag globally.
- Game day the highest-risk boundary and verify alerts fire before customer or
  tenant-wide impact.
