#!/usr/bin/env python3
"""Fix gold-standard structural issues across curriculum modules."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HEADER_NORMALIZATIONS = [
    (r"^## Step \d+: Learning Objectives\s*$", "## Learning Objectives"),
    (r"^## \d+\. Learning Objectives\s*$", "## Learning Objectives"),
    (r"^## Section \d+: Learning Objectives\s*$", "## Learning Objectives"),
    (r"^## \d+\. Wrong Mental Models.*$", "## Wrong Mental Models (Destroy These First)"),
    (r"^## Section \d+: Wrong Mental Models\s*$", "## Wrong Mental Models (Destroy These First)"),
    (r"^## \d+\. Core Teaching.*$", "## Core Teaching"),
    (r"^## Section \d+: Core Teaching.*$", "## Core Teaching"),
    (r"^## \d+\. Concrete Examples.*$", "## Concrete Examples"),
    (r"^## Section \d+: Concrete Examples\s*$", "## Concrete Examples"),
    (r"^## \d+\. Production Patterns.*$", "## Production Patterns"),
    (r"^## Section \d+: Production Patterns\s*$", "## Production Patterns"),
    (r"^## \d+\. Failure Modes.*$", "## Failure Modes"),
    (r"^## Section \d+: Failure Modes\s*$", "## Failure Modes"),
    (r"^^## \d+\. SRE Diagnostic Toolkit\s*$", "## SRE Diagnostic Toolkit"),
    (r"^## \d+\. SRE Diagnostic Toolkit\s*$", "## SRE Diagnostic Toolkit"),
    (r"^## Section \d+: SRE Diagnostic Toolkit\s*$", "## SRE Diagnostic Toolkit"),
    (r"^## \d+\. Decision Framework\s*$", "## Decision Framework"),
    (r"^## Section \d+: Decision Framework\s*$", "## Decision Framework"),
    (r"^## \d+\. Incident Scenario\s*$", "## Incident Scenario"),
    (r"^## Section \d+: Incident Scenario\s*$", "## Incident Scenario"),
    (r"^## \d+\. Expert Analysis\s*$", "## Expert Analysis"),
    (r"^## Section \d+: Expert Analysis\s*$", "## Expert Analysis"),
    (r"^## \d+\. Key Takeaways\s*$", "## Key Takeaways"),
    (r"^## Section \d+: Key Takeaways\s*$", "## Key Takeaways"),
    (r"^## \d+\. Targeted Reading\s*$", "## Targeted Reading"),
    (r"^## Section \d+: Targeted Reading\s*$", "## Targeted Reading"),
    (r"^## Step 3: Production Patterns & Failure Modes\s*$", "## Production Patterns"),
    (r"^## 3\. Production Patterns & Failure Modes\s*$", "## Production Patterns"),
    (r"^## Step 5: SRE Scenario\s*$", "## Incident Scenario"),
    (r"^## 5\. SRE Scenario\s*$", "## Incident Scenario"),
    (r"^## Step 4: Hands-On Exercises\s*$", "## Hands-On Exercises"),
    (r"^## 4\. Hands-On Exercise\s*$", "## Hands-On Exercises"),
    (r"^## Step 6: Targeted Reading\s*$", "## Targeted Reading"),
    (r"^## 6\. Targeted Reading\s*$", "## Targeted Reading"),
    (r"^## Step 7: Key Takeaways\s*$", "## Key Takeaways"),
    (r"^## 7\. Key Takeaways\s*$", "## Key Takeaways"),
    (r"^## Step 2: Core Teaching\s*$", "## Core Teaching"),
    (r"^## 2\. Core Teaching\s*$", "## Core Teaching"),
    (r"^## Part 11: Operational Health — What to Watch\s*$", "## SRE Diagnostic Toolkit"),
    (r"^## Part 12: SRE Scenario — .+$", "## Incident Scenario"),
    (r"^## Part 12 \(continued\): SRE Scenario — .+$", "## Incident Scenario (Extended)"),
    (r"^## Part 12 \(extended\): SRE Scenario — .+$", "## Incident Scenario (Extended)"),
    (r"^## Part 13: The Four In-Depth Questions\s*$", "## Expert Analysis"),
    (r"^## Part 13: The Five In-Depth Questions\s*$", "## Expert Analysis"),
    (r"^## Part 13 \(continued\): .+$", "## Expert Analysis (Extended)"),
    (r"^## Part 11: Failure Modes — .+$", "## Failure Modes"),
    (r"^## Part 12: Decision Framework.*$", "## Decision Framework"),
    (r"^## Part 18: The Decision Framework.*$", "## Decision Framework"),
    (r"^## Part 14: CDC Failure Modes.*$", "## Failure Modes"),
    (r"^## Production Patterns & Failure Modes\s*$", "## Failure Modes"),
    (r"^## SRE Scenario: .+$", "## Incident Scenario"),
    (r"^## 2\. Why This Topic Exists.*$", "## Core Teaching"),
]

# Observability numbered sections
OBSERVABILITY_MAP = {
    r"^## 1\. Learning Objectives\s*$": "## Learning Objectives",
    r"^## 2\. Core Teaching\s*$": "## Core Teaching",
}


def normalize_headers(text: str) -> str:
    for pat, repl in HEADER_NORMALIZATIONS:
        text = re.sub(pat, repl, text, flags=re.MULTILINE)
    for pat, repl in OBSERVABILITY_MAP.items():
        text = re.sub(pat, repl, text, flags=re.MULTILINE)
    return text


def remove_google_docs_artifacts(text: str) -> str:
    # Remove duplicate diagnostic playbook comment blocks
    pattern = (
        r"(?:^# Diagnostic playbook step \d+: correlate WS disconnect reason codes\n"
        r"# ALB access log field: connection_logs\.reason \(if enabled\)\n"
        r"# Common: \"client reset\", \"target reset\", \"idle timeout\"\n"
        r"# Fix idle timeout: aws elbv2 modify-load-balancer-attributes \\\n"
        r"#   --load-balancer-arn \$ARN --attributes Key=idle_timeout\.timeout_seconds,Value=3600\n\n?)+"
    )
    return re.sub(pattern, "", text, flags=re.MULTILINE)


def remove_kafka_meta(text: str) -> str:
    # AI process artifact embedded mid-file
    artifact = re.compile(
        r"\nRead week-4-topic-3-consensus-raft\.md.*?Let me redo the Kafka module's scenario \+ questions at that bar\.\n\n---\n\n"
        r"# Week 6, Topic 1 — REVISED Parts 12-14\n\n",
        re.DOTALL,
    )
    return artifact.sub("\n\n## Incident Scenario — The Tuesday Afternoon Black Hole\n\n", text)


def fix_config_store_appendix(text: str) -> str:
    text = re.sub(
        r"# Appendix: Design Configuration Store — Extended Practice & Production Deep Dive\n\n"
        r"> \*\*Append to:\*\* `Design Configuration Store\.md` \(Week 13\)\n"
        r"> \*\*Prerequisites:\*\* Week 4 `Consensus Raft\.md`, Week 3 consistency models\n"
        r"> \*\*Systems covered:\*\* etcd v3\.5\+, Consul 1\.16\+, ZooKeeper 3\.8\+\n\n---\n\n",
        "## Appendix: Extended Practice and Production Deep Dive\n\n",
        text,
    )
    return text


def fix_observability_title(text: str) -> str:
    text = re.sub(
        r"^# Week 8, Topic 1 — Observability: Metrics, Logs, Traces, SLOs",
        "# Observability: Metrics, Logs, and Traces",
        text,
        count=1,
    )
    # Add Wrong Mental Models placeholder section after LO if missing
    if "## Wrong Mental Models" not in text and "## 2. Core Teaching" in text:
        text = text.replace(
            "## 2. Core Teaching",
            "## Wrong Mental Models (Destroy These First)\n\n"
            "```\n"
            "See also: SLOs SLIs Error Budgets and Alerting.md for SLO-specific misconceptions.\n"
            "This module covers the three pillars (metrics, logs, traces) and cardinality traps.\n"
            "```\n\n---\n\n## Core Teaching",
            1,
        )
    return text


def add_kafka_front_matter(text: str) -> str:
    if "## Learning Objectives" in text or "## Part 0:" not in text:
        return text
    insert = '''## Learning Objectives

```
After this module, you will be able to:
  1. Choose queue vs log semantics for a workload and justify the tradeoff
  2. Explain Kafka partitions, consumer groups, ISR, and rebalance protocol
  3. Design idempotent producers, transactional outbox, and idempotent consumers
  4. Diagnose consumer lag, rebalance storms, and under-replicated partitions
  5. Compare Kafka vs SQS vs RabbitMQ for AWS-centric architectures
```

---

## Wrong Mental Models (Destroy These First)

```
MENTAL MODEL #1: "Kafka is a message queue"
  WRONG. Kafka is an append-only distributed log with replay. Queues delete
  messages on ack; logs retain by policy. Design consumers accordingly.

MENTAL MODEL #2: "More partitions always means more throughput"
  WRONG. Each partition is ordered and single-leader. Too many partitions
  increases rebalance cost, file handles, and end-to-end latency variance.

MENTAL MODEL #3: "Exactly-once Kafka means my app is exactly-once"
  WRONG. Kafka EOS covers producer+broker+consumer protocol boundaries.
  Your side effects (DB writes, API calls) still need idempotency keys.

MENTAL MODEL #4: "Consumer lag is always a consumer problem"
  WRONG. Lag rises from slow processing, skewed keys, broker disk IO,
  under-replicated partitions, or rebalance storms — diagnose before scaling.

MENTAL MODEL #5: "Delete the message after processing"
  WRONG. In a log, you commit offsets; retention is time/size policy.
  Treating Kafka like SQS causes replay bugs and wrong capacity planning.
```

---

'''
    return text.replace("## Part 0: Why This Module Exists", insert + "## Part 0: Why This Module Exists", 1)


def add_missing_tcp_http_sections(text: str, topic: str) -> str:
    if "## SRE Diagnostic Toolkit" in text:
        return text
    if "## Key Takeaways" not in text:
        return text

    if topic == "tcp":
        block = '''
---

## Production Failure Patterns

```
PATTERN 1: TIME_WAIT EXHAUSTION (high-churn microservices)
  Symptom: connect() failures, "Cannot assign requested address", rising error rate
  Cause:   Short-lived TCP connections without reuse; default ip_local_port_range
  Fix:     Connection pooling, keep-alive, SO_REUSEADDR, tune net.ipv4.tcp_tw_reuse

PATTERN 2: SYN FLOOD / BACKLOG OVERFLOW
  Symptom: intermittent connection timeouts under load spikes
  Cause:   listen backlog too small, slow accept loop, SYN cookies not enabled
  Fix:     Increase somaxconn, optimize accept path, enable SYN cookies, scale out

PATTERN 3: SILENT PACKET LOSS ON UDP
  Symptom: "works in dev, garbled in prod" for VoIP/gaming/custom protocols
  Cause:   No app-level sequencing; middleboxes drop large UDP datagrams
  Fix:     App-level ACK/retransmit, MTU discovery, or move to QUIC/TCP

PATTERN 4: NAGLE + DELAYED ACK INTERACTION
  Symptom: 200ms stalls on tiny request/response pairs
  Cause:   TCP_NODELAY off + delayed ACK waiting for piggyback data
  Fix:     TCP_NODELAY on latency-sensitive paths; batch writes where safe

PATTERN 5: EPHEMERAL PORT EXHAUSTION ON NAT/LB
  Symptom: outbound connections fail from app servers despite low CPU
  Cause:   Each destination:port tuple consumes ephemeral port until TIME_WAIT clears
  Fix:     Connection pooling to backends, ip_local_port_range expansion, L4 SNAT
```

---

## SRE Diagnostic Toolkit

```
METRICS (Prometheus / CloudWatch):
  node_netstat_Tcp_CurrEstab          — active TCP connections
  node_netstat_Tcp_ActiveOpens        — new connections/sec (churn indicator)
  node_sockstat_TCP_tw                — sockets in TIME_WAIT
  node_netstat_TcpExt_ListenOverflows — accept queue drops (critical)

COMMANDS:
  ss -s                               — socket summary (TIME_WAIT count)
  ss -tan state time-wait | wc -l     — TIME_WAIT connections
  cat /proc/sys/net/ipv4/ip_local_port_range
  netstat -s | grep -i "listen\|overflow\|retransmit"
  ss -i dst <backend-ip>:443          — per-connection TCP info (cwnd, rtt)

LOG PATTERNS:
  "connection refused" + rising ActiveOpens → backlog or target down
  "cannot assign requested address"         → ephemeral port / TIME_WAIT exhaustion
  "broken pipe" after deploy                → drained connections hitting closed sockets

AWS-SPECIFIC:
  NLB/ALB TargetConnectionErrorCount      — backend connect failures
  NLB ActiveFlowCount / ProcessedBytes    — correlate with app connection pools
  Enhanced networking (ENA) metrics       — packet drops at hypervisor
```

---

## Decision Framework

```
TCP vs UDP — QUICK CHOOSER:

  Need reliable ordered byte stream?           → TCP (default for APIs, DB, HTTP)
  Can tolerate loss, need message boundaries?  → UDP (+ app reliability if needed)
  Need low latency + encryption + multiplex?   → QUIC (HTTP/3) over UDP
  Real-time media with late-frame discard?     → UDP (RTP/WebRTC) or QUIC streams

CONNECTION MANAGEMENT:
  High RPS to same backend                   → persistent connection pool (HTTP/2, gRPC)
  Millions of short RPCs                     → watch TIME_WAIT; pool or tune sysctl
  NAT traversal / mobile                     → QUIC or TCP keepalive + app heartbeats

TUNING:
  Interactive small messages                 → consider TCP_NODELAY
  Bulk transfer                              → leave Nagle on; increase buffer sizes
  Long-idle connections through LBs          → app-level heartbeats < LB idle timeout
```

---
'''
    elif topic == "http":
        block = '''
---

## Production Failure Patterns

```
PATTERN 1: HTTP/2 MULTIPLEXING KILLED AT DOWNGRADE
  Symptom: p99 spikes after adding microservices; requests/page explodes
  Cause:   HTTP/2 front → HTTP/1.1 backend hop serializes streams
  Fix:     End-to-end HTTP/2, BFF aggregation, or gRPC between services

PATTERN 2: TCP HOL BLOCKING UNDER LOSS (HTTP/2)
  Symptom: single slow/lost packet stalls all multiplexed streams
  Cause:   HTTP/2 runs over single TCP connection per origin
  Fix:     HTTP/3/QUIC, multiple connections (limited), or reduce per-connection load

PATTERN 3: 0-RTT REPLAY ATTACK SURFACE
  Symptom: duplicate mutations after reconnect (rare but catastrophic)
  Cause:   TLS 1.3 early data accepted on non-idempotent endpoints
  Fix:     Disable 0-RTT for mutating routes; anti-replay tokens at app layer

PATTERN 4: QUIC BLOCKED BY CORPORATE FIREWALL
  Symptom: EU enterprise users on HTTP/3 timeout; TCP fallback slow
  Cause:   UDP/443 blocked; Alt-Svc advertises QUIC that never connects
  Fix:     Adaptive protocol selection, shorter QUIC timeout, TCP fallback hints

PATTERN 5: ALT-SVC STICKY BAD STATE
  Symptom: subset of users stuck on broken HTTP/3 path for hours
  Cause:   Alt-Svc max-age too long after QUIC regression
  Fix:     Reduce max-age during incidents; purge via Cache-Control on HTML
```

---

## SRE Diagnostic Toolkit

```
METRICS:
  http_requests_total{protocol="h2|h3|http/1.1"}  — protocol mix shift
  http_request_duration_seconds (by handler)       — p50/p99 per route
  ALB TargetResponseTime + HTTPCode_Target_5XX
  CloudFront OriginLatency vs TimeToFirstByte

COMMANDS:
  curl -sI --http2 https://origin/health | grep -i "HTTP/2\\|HTTP/3"
  curl -w "dns:%{time_namelookup} connect:%{time_connect} tls:%{time_appconnect}\\n" -o /dev/null -s URL
  h2load -n10000 -c100 -m100 URL                    — HTTP/2 load test
  openssl s_client -connect host:443 -alpn h2,http/1.1

LOG PATTERNS:
  "PRI * HTTP/2.0" parse errors                     — bad client or downgrade bug
  Spike in 499 (client closed)                      — timeout before response
  HTTP/1.1 200 with high body latency on fan-out    — missing aggregation

BROWSER / RUM:
  Compare TTFB by protocol version and geography
  Navigation Timing: connectEnd - connectStart (TCP/TLS cost)
```

---

## Decision Framework

```
WHICH HTTP VERSION?

  Browser → CDN → static/API                     → HTTP/2 minimum; HTTP/3 if CDN supports
  Mobile global users, lossy networks              → HTTP/3 (QUIC) with TCP fallback
  Legacy corporate proxy environment             → HTTP/1.1 or HTTP/2 only; test QUIC
  Service-to-service inside VPC                  → HTTP/2 or gRPC over h2; not HTTP/3 required

MICROSERVICE EXPOSURE:
  Never expose N microservice calls to browser     → BFF/GraphQL/edge aggregate
  HTTP/2 end-to-end through ALB                  → enable ALPN on targets

0-RTT POLICY:
  Idempotent GET/HEAD only                         → 0-RTT allowed
  POST/PUT/PATCH/DELETE                            → disable early data
```

---
'''
    else:
        return text

    return text.replace("\n---\n\n## Key Takeaways", block + "\n## Key Takeaways", 1)


def add_rest_sections(text: str) -> str:
    if "## Decision Framework" in text or "## Key Takeaways" not in text:
        return text
    block = '''
---

## Production Failure Patterns

```
PATTERN 1: GraphQL N+1 / RESOLVER STORM
  Symptom: p99 explodes on nested queries; DB connection pool exhausted
  Fix:     DataLoader batching, query depth/complexity limits, persisted queries

PATTERN 2: gRPC LOAD BALANCER BLACK HOLE
  Symptom: one pod at 100% CPU, others idle; sticky broken connections
  Cause:   L4 LB unaware of gRPC long-lived HTTP/2 connections
  Fix:     L7 gRPC-aware LB (Envoy/Istio), client-side round_robin, max connection age

PATTERN 3: REST OVER-FETCH + CHATTY MOBILE
  Symptom: high egress, slow screens, battery drain
  Fix:     Field selection, BFF per client, or GraphQL for aggregate views

PATTERN 4: PROTOBUF SCHEMA BREAKING CHANGE
  Symptom: deserialization errors after deploy skew between services
  Fix:     Field numbering rules, backward-compatible adds, feature flags for rollout

PATTERN 5: GraphQL INTROSPECTION + DEPTH ATTACK
  Symptom: CPU spike from malicious deep queries
  Fix:     Disable introspection in prod, complexity scoring, rate limits
```

---

## Decision Framework

```
REST vs GraphQL vs gRPC:

  Public third-party API, cacheable resources     → REST + OpenAPI
  Mobile/web with varied screens, aggregation     → GraphQL (+ DataLoader)
  Internal service-to-service, high RPS           → gRPC (+ protobuf)
  Browser-facing real-time                       → REST/GraphQL + WebSocket; not raw gRPC

RULE: Match protocol to client + coupling, not team preference.
  gRPC   = performance + strong contracts + generated stubs
  GraphQL = flexible reads + single endpoint + server complexity
  REST   = simplicity + HTTP caching + universal tooling
```

---
'''
    return text.replace("\n---\n\n## Key Takeaways", block + "\n## Key Takeaways", 1)


def add_dns_websocket_decision(text: str, kind: str) -> str:
    if "## Decision Framework" in text:
        return text
    if kind == "dns":
        block = '''
---

## Decision Framework

```
DNS RECORD TYPE CHOOSER:

  Stable IP, health-checked failover           → A/AAAA + Route 53 failover routing
  Load-balanced endpoints change frequently    → CNAME/ALIAS (never CNAME at apex without ALIAS)
  Service discovery inside K8s                 → CoreDNS ClusterIP; external via Ingress/LB
  Geo/latency routing                          → Route 53 latency or geolocation policies
  Certificate validation                       → CNAME for ACM DNS validation

TTL POLICY:
  Infrastructure you control + fast failover   → TTL 60s or lower
  Stable CDN/origin                            → TTL 300–3600s
  Never change TTL during incident without plan  → low TTL + cache = resolver stampede
```

---
'''
        anchor = "## Production Failure Patterns"
    else:  # websockets
        block = '''
---

## Decision Framework

```
WebSocket vs ALTERNATIVES:

  Server push, bidirectional, low latency chat  → WebSocket (or HTTP/2 SSE for one-way)
  Fire-and-forget events to browser             → SSE (simpler, HTTP/2 friendly)
  Request/response only                           → HTTP/2/3 polling or long-poll (last resort)
  Mobile background unreliable                  → push notifications + REST sync on foreground

LB / PROXY:
  ALB supports WebSocket                        → ensure idle timeout > heartbeat interval
  CloudFront                                    → WebSocket only on specific behaviors
  API Gateway                                   → $connect route + Lambda or HTTP integration
```

---
'''
        anchor = "## Production Failure Patterns"

    if anchor in text:
        return text.replace(f"\n---\n\n{anchor}", block + f"\n---\n\n{anchor}", 1)
    return text


def reorder_tcp_sections(text: str) -> str:
    """Move Failure/SRE/Decision before Incident Scenario (gold-standard order)."""
    if "## Incident Scenario: The Mystery Latency Spike" not in text:
        return text
    if text.find("## Production Failure Patterns") > text.find("## Incident Scenario:"):
        return text  # already ordered
    m_start = re.search(r"^## Production Failure Patterns\s*$", text, re.MULTILINE)
    m_end = re.search(r"^## Key Takeaways\s*$", text, re.MULTILINE)
    m_incident = re.search(r"^## Incident Scenario:", text, re.MULTILINE)
    if not (m_start and m_end and m_incident):
        return text
    block = text[m_start.start():m_end.start()]
    without = text[:m_start.start()] + text[m_end.start():]
    insert_at = without.find("## Incident Scenario:")
    return without[:insert_at] + block + "\n" + without[insert_at:]


def add_lamport_wrong_models(text: str) -> str:
    if "## Wrong Mental Models" in text:
        return text
    block = '''
## Wrong Mental Models (Destroy These First)

```
MENTAL MODEL #1: "Lamport timestamp A < B means A happened-before B"
  WRONG. Lamport gives TOTAL ORDER with false positives. Only vector clocks
  (or explicit causality tracking) detect true happens-before vs concurrent.

MENTAL MODEL #2: "Vector clocks are always better"
  WRONG. O(N) metadata per write. Use when you need concurrent detection
  (Dynamo siblings, CRDT merge). Lamport + tiebreaker suffices for many logs.

MENTAL MODEL #3: "Version vectors and vector clocks are the same"
  WRONG. Version vectors track replica state for anti-entropy; vector clocks
  track per-event causality. Conflating them is a common interview fail.

MENTAL MODEL #4: "NTP sync fixes distributed ordering"
  WRONG. Clock skew breaks last-write-wins. Causal systems use logical clocks,
  not wall time, for ordering guarantees that matter.

MENTAL MODEL #5: "Causal consistency is free if you use Kafka"
  WRONG. Kafka gives per-partition order only. Cross-partition causality
  requires metadata propagation and consumer-side buffering.
```

---

'''
    return re.sub(
        r"(## Learning Objectives\n```\n[\s\S]*?\n```\n\n---\n\n)",
        r"\1" + block,
        text,
        count=1,
    )


def add_observability_wrong_models(text: str) -> str:
    if "## Wrong Mental Models" in text:
        return text
    block = '''
## Wrong Mental Models (Destroy These First)

```
MENTAL MODEL #1: "More dashboards = better observability"
  WRONG. Dashboards answer known questions. Observability means arbitrary
  ad-hoc queries on high-cardinality data when the unknown breaks.

MENTAL MODEL #2: "Log everything — storage is cheap"
  WRONG. Unbounded logs explode cost and drown signal. Structured logs with
  sampling and retention tiers; metrics for aggregates, logs for context.

MENTAL MODEL #3: "Trace every request in production"
  WRONG. 100% tracing kills performance and backends. Head-based or tail-based
  sampling with consistent context propagation on errors and high latency.

MENTAL MODEL #4: "Alert on every threshold breach"
  WRONG. Symptom alerts without SLO/error-budget context cause fatigue.
  Page on user-visible SLO burn; ticket on resource saturation trends.

MENTAL MODEL #5: "Metrics cardinality doesn't matter at our scale"
  WRONG. One unbounded label (user_id, URL path) can take down Prometheus/
  CloudWatch. Calculate cardinality before shipping new labels.
```

---

'''
    return re.sub(
        r"(## Learning Objectives\n\n```\n[\s\S]*?\n```\n\n---\n\n)",
        r"\1" + block,
        text,
        count=1,
    )


LEGACY_SRE_DECISION = {
    "SQL Deep Dive.md": (
        "## SRE Diagnostic Toolkit",
        '''```
POSTGRES PRODUCTION DIAGNOSTICS:

  pg_stat_activity / pg_stat_statements     — who is running what, query cost
  EXPLAIN (ANALYZE, BUFFERS)                — plan vs reality under load
  pg_locks + pg_blocking_pids               — lock chains and deadlocks
  pg_stat_replication + replay_lag            — replica freshness
  pg_replication_slots + pg_wal_lsn_diff    — slot bloat (CDC risk)

CLOUDWATCH/RDS:
  DatabaseConnections, CPUUtilization, ReadIOPS/WriteIOPS, ReplicaLag
  FreeableMemory, DiskQueueDepth

INCIDENT SIGNATURES:
  Connections at max + low CPU               → pool missing or connection leak
  Rising replication lag + stable CPU        → large transaction or slot consumer stall
  Seq scan on large table + latency spike    → missing index or stale statistics
```''',
        "## Decision Framework",
        '''```
ISOLATION LEVEL:
  READ COMMITTED (default)     → most OLTP; explicit locks for hot rows
  REPEATABLE READ            → reporting snapshots; watch serialization failures
  SERIALIZABLE               → financial invariants; expect retries

INDEX TYPE:
  Equality + range on column → B-tree (default)
  JSONB containment          → GIN
  Full-text                  → GIN/GiST tsvector (or external search engine)

SQL vs NoSQL vs CACHE:
  ACID + joins + moderate scale → Postgres (+ read replicas, pooling)
  Massive write partition key   → Cassandra/Dynamo (Week 5)
  Hot read path                 → Redis cache-aside (Week 2 Caching)
```''',
    ),
    "Caching Patterns.md": (
        "## SRE Diagnostic Toolkit",
        '''```
REDIS / ELASTICACHE:
  INFO stats / INFO memory / INFO replication
  redis-cli --latency-history
  redis-cli --bigkeys (careful in prod — use replica)
  evicted_keys, keyspace_hits/misses → hit ratio

MEMCACHED:
  stats items / stats slabs — slab class imbalance

CLOUDWATCH:
  CacheHitRate, CurrConnections, Evictions, ReplicationLag

SIGNATURES:
  Hit ratio drop + latency up                 → hot key, TTL storm, or bypass
  Evictions spike + memory flat               → maxmemory-policy wrong
  Replica lag on Redis primary                → large writes or slow commands
```''',
        "## Decision Framework",
        '''```
CACHE PATTERN:
  Read-heavy, tolerate staleness    → cache-aside + TTL
  Write-heavy counters              → write-through or Redis INCR
  Invalidation complexity           → versioned keys > purge-by-pattern

STORE:
  Sub-ms, simple KV, session        → Redis
  Multi-tenant RAM pooling          → Memcached
  Durability required               → NOT pure cache — use DB + cache-aside
```''',
    ),
}


def inject_legacy_sections(text: str, filename: str) -> str:
    if filename not in LEGACY_SRE_DECISION:
        return text
    sre_title, sre_body, dec_title, dec_body = LEGACY_SRE_DECISION[filename]
    if sre_title in text:
        return text
    anchor = "## Hands-On Exercises"
    if anchor not in text:
        anchor = "## Incident Scenario"
    if anchor not in text:
        return text
    block = f"\n---\n\n{sre_title}\n\n{sre_body}\n\n---\n\n{dec_title}\n\n{dec_body}\n\n---\n\n"
    return text.replace(f"\n---\n\n{anchor}", block + anchor, 1)


def add_kafka_decision(text: str) -> str:
    if "## Decision Framework" in text:
        return text
    block = '''
---

## Decision Framework

```
QUEUE vs LOG:
  Task queue, delete-on-ack, single consumer group     → SQS / RabbitMQ
  Event log, replay, multiple independent consumers    → Kafka / Kinesis

PARTITION COUNT:
  Target: enough for peak consumer throughput; not so many that rebalance hurts
  Rule of thumb: start with max(12, expected_peak_MBps / single_consumer_MBps)

DELIVERY SEMANTICS:
  At-most-once     → fire-and-forget (metrics only)
  At-least-once    → default; idempotent consumers required
  Exactly-once     → transactional producer + idempotent consumer + EOS boundaries

AWS CHOOSER:
  Managed, minimal ops, moderate volume              → SQS + SNS
  High throughput, replay, stream processing           → MSK (Kafka)
  Firehose analytics pipeline                          → Kinesis Data Firehose
```

---
'''
    if "## SRE Diagnostic Toolkit" in text:
        return text.replace("\n---\n\n## SRE Diagnostic Toolkit", block + "## SRE Diagnostic Toolkit", 1)
    return text


def reorder_tcp_sections(text: str) -> str:
    """Move Failure/SRE/Decision before Incident Scenario (gold-standard order)."""
    marker = "## Incident Scenario: The Mystery Latency Spike"
    if marker not in text or "## Production Failure Patterns" not in text:
        return text
    # Extract the three standard sections block
    m = re.search(
        r"(---\n\n## Production Failure Patterns\n.*?)(---\n\n## Key Takeaways)",
        text,
        re.DOTALL,
    )
    if not m:
        return text
    block = m.group(1).rstrip() + "\n"
    without = text[: m.start()] + text[m.end(1) :]
    return without.replace(f"\n---\n\n{marker}", f"\n---\n\n{block}---\n\n{marker}", 1)


def add_lamport_wrong_models(text: str) -> str:
    if "## Wrong Mental Models" in text:
        return text
    block = '''
## Wrong Mental Models (Destroy These First)

```
MENTAL MODEL #1: "Lamport timestamp A < B means A happened-before B"
  WRONG. Lamport gives TOTAL ORDER with false causality — concurrent events
  can get arbitrary order. Use vector clocks to detect concurrency.

MENTAL MODEL #2: "Vector clocks and version vectors are the same"
  WRONG. Version vectors track replicas (anti-entropy); vector clocks track
  per-process causality. Mixing them breaks merge semantics in CRDTs/Dynamo.

MENTAL MODEL #3: "Wall clock + NTP fixes ordering"
  WRONG. Skew and leap seconds make wall clocks unsafe for correctness.
  Logical clocks track causality; physical clocks are for human UX only.

MENTAL MODEL #4: "Causal consistency requires vector clocks everywhere"
  WRONG. Session tokens (MongoDB), hybrid logical clocks, and partition-
  scoped vectors trade metadata cost for the guarantee you actually need.

MENTAL MODEL #5: "Last-write-wins with timestamps resolves all conflicts"
  WRONG. Clock skew picks the wrong winner; siblings proliferate under
  concurrent writes. LWW is a product decision, not a correctness proof.
```

---

'''
    # Insert after Learning Objectives block (before next section)
    m = re.search(r"## Learning Objectives\n```.*?```\n\n---\n\n", text, re.DOTALL)
    if m:
        return text[: m.end()] + block + text[m.end() :]
    return text


def add_observability_wrong_models(text: str) -> str:
    if "## Wrong Mental Models" in text:
        return text
    block = '''
## Wrong Mental Models (Destroy These First)

```
MENTAL MODEL #1: "More dashboards = better observability"
  WRONG. Dashboards answer known questions. Observability means arbitrary
  ad-hoc queries on high-cardinality data when the unknown breaks.

MENTAL MODEL #2: "Log everything — storage is cheap"
  WRONG. Unbounded logs explode cost and drown signal. Structured logs
  with sampling and retention tiers beat verbose println debugging.

MENTAL MODEL #3: "Metrics cardinality doesn't matter at our scale"
  WRONG. user_id or request_id labels destroy Prometheus/CloudWatch.
  Cardinality is a design constraint, not an ops afterthought.

MENTAL MODEL #4: "100% trace sampling in production"
  WRONG. Full tracing at high RPS melts collectors and storage. Tail-based
  sampling + error-biased sampling captures incidents without bankrupting you.

MENTAL MODEL #5: "Alert on every threshold breach"
  WRONG. Symptom-based multi-window burn rates (see SLOs module) beat
  static CPU thresholds that page at 3 AM for self-healing blips.
```

---

'''
    m = re.search(r"## Learning Objectives\n\n```.*?```\n\n---\n\n", text, re.DOTALL)
    if m:
        return text[: m.end()] + block + text[m.end() :]
    return text


LEGACY_SRE_BLOCKS = {
    "SQL Deep Dive.md": '''## SRE Diagnostic Toolkit

```
KEY METRICS (RDS/Aurora):
  DatabaseConnections, CPUUtilization, FreeableMemory, ReadIOPS/WriteIOPS
  ReplicaLag (Aurora), Deadlocks, BufferCacheHitRatio

COMMANDS:
  EXPLAIN (ANALYZE, BUFFERS) SELECT ...
  SELECT * FROM pg_stat_activity WHERE state != 'idle';
  SELECT * FROM pg_locks WHERE NOT granted;
  SHOW max_connections; SELECT count(*) FROM pg_stat_activity;

INCIDENT SIGNATURES:
  Connections at max + low CPU     → pool missing or connection leak
  ReplicaLag spike + write spike   → async replica cannot keep up
  seq_scan >> idx_scan on hot table → missing or unused index
```

---

''',
    "Caching Patterns.md": '''## SRE Diagnostic Toolkit

```
KEY METRICS:
  cache_hit_ratio, evicted_keys, used_memory, connected_clients (Redis)
  memcached curr_items, cmd_get/cmd_set, evictions

COMMANDS:
  redis-cli INFO stats | egrep 'keyspace|hit|miss|evict'
  redis-cli --latency-history -i 1
  memcached-tool <host>:11211 stats | grep hit

INCIDENT SIGNATURES:
  Hit ratio cliff after deploy        → cache key schema change
  Evictions + latency spike           → memory pressure / hot key
  Thundering herd on expiry           → missing jitter / stale-while-revalidate
```

---

''',
    "CAP Theorem.md": '''## SRE Diagnostic Toolkit

```
DIAGNOSTIC QUESTIONS (partition drill):
  1. Which invariant broke first — availability or consistency?
  2. Did clients see stale reads, errors, or split-brain writes?
  3. Was the partition real (network) or slow node (GC pause)?

METRICS:
  Error rate by AZ, quorum ack latency, leader election count
  Cassandra UNAVAILABLE rate, etcd proposal failures

COMMANDS:
  kubectl get pods -o wide --field-selector spec.nodeName=...
  nodetool status / etcdctl endpoint health
```

---

''',
    "Consensus Raft.md": '''## SRE Diagnostic Toolkit

```
METRICS:
  etcd_server_has_leader, etcd_disk_wal_fsync_duration_seconds
  raft_term, proposal_failed_total

COMMANDS:
  etcdctl endpoint status -w table
  etcdctl member list
  etcdctl check perf

INCIDENT SIGNATURES:
  Frequent leader elections + disk latency → fsync/storage bottleneck
  proposal failures + quorum loss         → partition or slow follower
```

---

''',
    "Database Scaling Patterns.md": '''## SRE Diagnostic Toolkit

```
FOUR NUMBERS (always check first):
  CPU%, IOPS, connection count, replication lag

COMMANDS:
  SELECT count(*) FROM pg_stat_activity;
  SELECT * FROM pg_replication_slots;
  EXPLAIN (ANALYZE) on top pg_stat_statements query

SCALING RUNG (see Decision Framework):
  Tune → pool → replicas → vertical → partition → shard → CQRS
```

---

''',
}

LEGACY_DECISION_BLOCKS = {
    "SQL Deep Dive.md": '''## Decision Framework

```
ISOLATION LEVEL:
  Read-heavy, tolerate anomalies     → READ COMMITTED (default Postgres)
  Financial/reporting consistency    → REPEATABLE READ or SERIALIZABLE
  High-contention OLTP               → explicit row locks + READ COMMITTED

SQL vs NoSQL:
  ACID + joins + ad-hoc queries      → Postgres/Aurora
  Massive write scale + partition key → Cassandra/Dynamo (Week 5)
```

---

''',
    "Caching Patterns.md": '''## Decision Framework

```
CACHE STRATEGY:
  Read-heavy, stale OK briefly         → cache-aside + TTL jitter
  Write-heavy, must not serve stale    → write-through or shorter TTL + purge
  Thundering herd risk                 → probabilistic early expiry / singleflight

STORE:
  Sub-ms session/rate-limit            → Redis (single-digit ms)
  Simple KV blob cache                 → Memcached (lower overhead)
  Query result cache                   → application layer + Redis
```

---

''',
}


def insert_before_hands_on(text: str, inserts: str) -> str:
    if "## SRE Diagnostic Toolkit" in text:
        return text
    anchor = "## Hands-On Exercises"
    if anchor not in text:
        anchor = "## Hands-On Exercise"
    if anchor not in text:
        return text
    return text.replace(f"\n---\n\n{anchor}", f"\n---\n\n{inserts}{anchor}", 1)


def add_kafka_decision(text: str) -> str:
    if "## Decision Framework" in text:
        return text
    block = '''
---

## Decision Framework

```
QUEUE vs LOG:
  Task queue, delete-on-ack, single consumer group    → SQS / RabbitMQ
  Event log, replay, multiple consumer groups         → Kafka / Kinesis

PARTITION COUNT:
  Target ~10–50 MB/s per partition write throughput
  Consumer parallelism ≤ partition count
  Key skew → hot partition before adding partitions

DELIVERY SEMANTICS:
  At-most-once     → fire-and-forget producer, no retries
  At-least-once    → idempotent consumer required (default honest choice)
  Exactly-once     → transactional producer + idempotent consumer + EOS protocol
```

---
'''
    if "## SRE Diagnostic Toolkit" in text:
        return text.replace("\n---\n\n## SRE Diagnostic Toolkit", block + "\n---\n\n## SRE Diagnostic Toolkit", 1)
    return text


def process_file(path: Path) -> bool:
    original = path.read_text(encoding="utf-8", errors="replace")
    text = original

    text = normalize_headers(text)

    if "Design Google Docs" in path.name:
        text = remove_google_docs_artifacts(text)

    if "Message Queues and Kafka" in path.name:
        text = remove_kafka_meta(text)
        text = add_kafka_front_matter(text)
        # Rename duplicate Part 12/13 to avoid collision
        count = 0
        def rename_part(m):
            nonlocal count
            count += 1
            if count <= 2:
                return m.group(0)
            num = m.group(1)
            title = m.group(2)
            suffix = " (continued)" if count == 3 else " (extended)"
            return f"## Part {num}{suffix}: {title}"
        text = re.sub(r"^## Part (\d+): (.+)$", rename_part, text, flags=re.MULTILINE)

    if "Design Configuration Store" in path.name:
        text = fix_config_store_appendix(text)

    if path.name == "Observability.md":
        text = fix_observability_title(text)

    if path.name == "TCP vs UDP.md":
        text = add_missing_tcp_http_sections(text, "tcp")
        # reorder_tcp_sections disabled — breaks file structure when sections absent

    if path.name == "HTTP-1.1-vs-HTTP-2-vs-HTTP-3.md":
        text = add_missing_tcp_http_sections(text, "http")

    if path.name == "REST vs GraphQL vs gRPC.md":
        text = add_rest_sections(text)

    if path.name == "DNS Resolution.md":
        text = add_dns_websocket_decision(text, "dns")

    if path.name == "WebSockets.md":
        text = add_dns_websocket_decision(text, "websockets")

    if path.name == "Lamport Clocks Vector Clocks and Causality.md":
        text = add_lamport_wrong_models(text)

    if path.name == "Observability.md":
        text = add_observability_wrong_models(text)

    if path.name in LEGACY_SRE_BLOCKS:
        text = insert_before_hands_on(text, LEGACY_SRE_BLOCKS[path.name])

    if path.name in LEGACY_DECISION_BLOCKS:
        if "## Decision Framework" not in text:
            anchor = "## Hands-On Exercises"
            if anchor not in text:
                anchor = "## Hands-On Exercise"
            if anchor in text and LEGACY_DECISION_BLOCKS[path.name] not in text:
                text = text.replace(
                    f"\n---\n\n{anchor}",
                    f"\n---\n\n{LEGACY_DECISION_BLOCKS[path.name]}{anchor}",
                    1,
                )

    if "Message Queues and Kafka" in path.name:
        text = add_kafka_decision(text)

    if path.name == "Cassandra Architecture.md":
        if "## SRE Diagnostic Toolkit" not in text:
            block = '''## SRE Diagnostic Toolkit

```
COMMANDS:
  nodetool status / nodetool tpstats
  nodetool tablestats keyspace.table
  nodetool compactionstats
  cassandra-stress write n=1000000 -rate threads=50

METRICS:
  org.apache.cassandra.metrics.compaction pending tasks
  ReadLatency/WriteLatency p99, SSTable count per table
  Disk usage per node, repair session progress
```

---

'''
            text = insert_before_hands_on(text, block)

    if text != original:
        path.write_text(text, encoding="utf-8", newline="\n")
        return True
    return False


def main():
    changed = []
    for p in sorted(ROOT.rglob("*.md")):
        if "00-Curriculum" in str(p) or p.name == "README.md":
            continue
        if process_file(p):
            changed.append(str(p.relative_to(ROOT)))
    print(f"Fixed {len(changed)} files:")
    for c in changed:
        print(f"  {c}")


if __name__ == "__main__":
    main()
