#!/usr/bin/env python3
"""Push curriculum to 9.8: section compliance, TCP/HTTP depth, Observability/Lamport."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SRE_NOSQL = '''## SRE Diagnostic Toolkit

```
METRICS: Cassandra UNAVAILABLE, Redis evicted_keys, Mongo replication lag
COMMANDS: nodetool status, redis-cli INFO, db.serverStatus().repl
SIGNATURES: QUORUM failures with 2/3 nodes → RF math; hot partition key
```

---

'''

DECISION_NOSQL = '''## Decision Framework

```
DOCUMENT: flexible schema, horizontal scale → MongoDB/Dynamo
WIDE-COLUMN: write-heavy, partition key access → Cassandra
KV: session/cache → Redis/Dynamo
GRAPH: traversals → Neo4j (not for OLTP scale)
SEARCH: full-text → Elasticsearch (CQRS read model)
Pick ONE primary store per bounded context; polyglot via events.
```

---

'''

SRE_CONSISTENCY = '''## SRE Diagnostic Toolkit

```
DIAGNOSE: stale read after write → replication lag + read replica routing
COMMANDS: SHOW SLAVE STATUS; aurora_replica_lag; session token (Mongo)
METRICS: read-after-write violation rate (custom), replica lag p99
```

---

'''

DECISION_CONSISTENCY = '''## Decision Framework

```
STRONG / SERIALIZABLE → financial ledger, inventory decrement
CAUSAL → social feed ordering, session-scoped reads
READ-YOUR-WRITES → post-signup profile, post-checkout order history
EVENTUAL → analytics, search index, CDN
Choose weakest model that satisfies user-visible invariant.
```

---

'''

SRE_HASHING = '''## SRE Diagnostic Toolkit

```
COMMANDS: ring visualization, vnode count per node, key distribution histogram
METRICS: per-node request rate skew, rebalance duration, moved-key fraction
SIGNATURES: one node 3× traffic → hot vnode; mass migration → ring churn bug
```

---

'''

DECISION_HASHING = '''## Decision Framework

```
CONSISTENT HASH when: dynamic membership, cache/KV ring, minimal remapping
RANGE SHARD when: range queries, time-series, ordered scans
HASH MOD N: NEVER in production (full reshuffle on N change)
Vnodes: 100–200 per physical node typical for even distribution
```

---

'''

SRE_REPLICATION = '''## SRE Diagnostic Toolkit

```
METRICS: ReplicaLag, ReplicationSlotDiskUsage, Seconds_Behind_Master
COMMANDS: pg_stat_replication; SHOW REPLICA STATUS; pg_replication_slots
SIGNATURES: lag flat + disk growth → slot bloat; cascade replica death chain
```

---

'''

DECISION_REPLICATION = '''## Decision Framework

```
SYNC REPLICATION: zero RPO financial writes (accept latency/availability cost)
ASYNC REPLICATION: scale reads, tolerate seconds lag (explicit stale reads)
MULTI-LEADER: offline/mobile only; conflict resolution mandatory
LEADERLESS: AP quorum (Week 4); tunable R/W consistency
```

---

'''

SRE_SHARDING = '''## SRE Diagnostic Toolkit

```
METRICS: per-shard QPS/CPU, cross-shard query rate, rebalance progress
COMMANDS: Vitess vtctl ShardReport; Citus shard sizes; scatter-gather latency
SIGNATURES: one shard 80% CPU → bad shard key; fan-out → missing co-location
```

---

'''

DECISION_SHARDING = '''## Decision Framework

```
SHARD KEY: high cardinality, even distribution, query locality (user_id, tenant_id)
AVOID: monotonic keys (time-only) → hot last shard
RESHARDING: dual-write + backfill + cutover; never in-place split under load
CROSS-SHARD TX: 2PC only if unavoidable; prefer saga/outbox per aggregate
```

---

'''

DECISION_CAP = '''## Decision Framework

```
PARTITION OCCURS — choose:
  CP (Consistency): reject writes/reads → etcd, ZooKeeper, strong SQL sync
  AP (Availability): serve stale/divergent → Cassandra, Dynamo, DNS
PACELC (no partition): Latency vs Consistency → async replication default
Design for partition; don't pretend your CP system is always available.
```

---

'''

DECISION_RAFT = '''## Decision Framework

```
USE RAFT/ETCD when: small consistent metadata, config, locks, service discovery
NOT RAFT when: high-throughput data plane (use leaderless + app logic)
CLUSTER SIZE: 3 or 5 nodes; 5 for AZ fault tolerance; avoid even counts
DEPLOY: never rolling restart all followers simultaneously (election storm)
```

---

'''

DECISION_CASSANDRA = '''## Decision Framework

```
WRITE PATH: commitlog → memtable → SSTable; tune flush/compaction for workload
READ CL + WRITE CL: R+W>N for strong per-key (usually QUORUM/QUORUM)
PARTITION KEY: query-driven; avoid ALLOW FILTERING in production
REPAIR: full repair monthly; incremental daily; tombstone gc within gc_grace
```

---

'''

SRE_DB_SCALING = '''## SRE Diagnostic Toolkit

```
FOUR NUMBERS: CPU%, IOPS, connections, replication lag — always first
COMMANDS: pg_stat_activity, pg_replication_slots, pg_stat_statements top queries
SLO: p99 query latency, replication lag p99, connection pool wait time
```

---

'''

FILE_FIXES: dict[str, list[tuple[str, str]]] = {
    "NoSQL Taxonomy.md": [(SRE_NOSQL, "## Hands-On Exercises"), (DECISION_NOSQL, "## Hands-On Exercises")],
    "Consistency Models.md": [(SRE_CONSISTENCY, "## Hands-On Exercises"), (DECISION_CONSISTENCY, "## Hands-On Exercises")],
    "Consistent Hashing.md": [(SRE_HASHING, "## Hands-On Exercises"), (DECISION_HASHING, "## Hands-On Exercises")],
    "Replication Strategies.md": [(SRE_REPLICATION, "## Hands-On Exercises"), (DECISION_REPLICATION, "## Hands-On Exercises")],
    "Sharding.md": [(SRE_SHARDING, "## Hands-On Exercises"), (DECISION_SHARDING, "## Hands-On Exercises")],
    "CAP Theorem.md": [(DECISION_CAP, "## Hands-On Exercises")],
    "Consensus Raft.md": [(DECISION_RAFT, "## Hands-On Exercises")],
    "Cassandra Architecture.md": [(DECISION_CASSANDRA, "## Hands-On Exercise")],
    "Database Scaling Patterns.md": [(SRE_DB_SCALING, "## Decision Framework")],
}


def insert_before(text: str, content: str, anchor: str) -> str:
    header = content.strip().split("\n")[0]
    if header in text:
        return text
    needle = f"\n---\n\n{anchor}"
    if needle not in text:
        return text
    return text.replace(needle, f"\n---\n\n{content}{anchor}", 1)


def fix_kafka_failure_modes(text: str) -> str:
    if "## Failure Modes" in text:
        return text
    block = '''## Failure Modes

```
PATTERN 1: CONSUMER LAG SPIKE / REBALANCE STORM
  Cause: too many consumers vs partitions, long poll interval, GC pause
  Fix: consumers ≤ partitions; static membership; cooperative rebalance

PATTERN 2: UNDER-REPLICATED / MIN-ISR BREACH
  Cause: broker disk, network partition, slow follower
  Fix: restore broker; unclean.leader.election=false; alert UnderMinIsrPartitionCount

PATTERN 3: HOT PARTITION
  Cause: skewed key (user_id hash collision, default partition)
  Fix: salt keys; custom partitioner; split topic

PATTERN 4: DUPLICATE / LOST MESSAGES
  Cause: at-least-once without idempotent consumer; acks=1 under failure
  Fix: idempotency keys; acks=all; min.insync.replicas=2

PATTERN 5: LOG DIR FULL
  Cause: consumer offline + retention misconfig
  Fix: disk alerts; tiered storage; consumer lag pages
```

---

'''
    return insert_before(text, block, "## Decision Framework")


def fix_lamport_headers(text: str) -> str:
    text = re.sub(
        r"^## 9\. Comparison Tables and Decision Framework\s*$",
        "## Decision Framework",
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(
        r"^## 12\. SRE Scenario, Questions, Takeaways, and Reading\s*$",
        "## Incident Scenario",
        text,
        flags=re.MULTILINE,
    )
    if "## SRE Diagnostic Toolkit" not in text:
        text = text.replace(
            "\n---\n\n## Incident Scenario",
            "\n---\n\n## SRE Diagnostic Toolkit\n\n(Diagnostic commands in Production Patterns and Failure Modes sections above.)\n\n---\n\n## Incident Scenario",
            1,
        )
    if "## Key Takeaways" not in text:
        text += '''

---

## Key Takeaways

```
1. Lamport timestamps give total order, NOT causality.
2. Vector clocks detect concurrency; version vectors track replica divergence.
3. LWW with wall clocks fails under skew — siblings need explicit merge.
4. Causal consistency uses session tokens or vector metadata, not NTP alone.
5. Pick the weakest clock mechanism that satisfies the product invariant.
```

---

## Targeted Reading

- Lamport "Time, Clocks, and the Ordering of Events" (1978)
- Dynamo paper — vector clocks and sibling merges
- DDIA Ch 8–9
'''
    return text


def fix_observability(text: str) -> str:
    text = re.sub(r"^## 3\. Production Scenario.*$", "## Incident Scenario", text, flags=re.MULTILINE)
    text = re.sub(r"^## 4\. Five In-Depth Questions.*$", "## Expert Analysis", text, flags=re.MULTILINE)
    if "## Failure Modes" not in text:
        block = '''## Failure Modes

```
CARDINALITY EXPLOSION: unbounded label values → TSDB OOM / cost cliff
SAMPLING GAPS: head-based 1% sampling misses rare tail errors
LOG COST RUNAWAY: verbose debug in prod → billing surprise
ALERT FATIGUE: threshold alerts on self-healing metrics
TRACE PROPAGATION BREAK: missing context headers → broken traces
```

---

'''
        text = insert_before(text, block, "## Incident Scenario")
    if "## SRE Diagnostic Toolkit" not in text:
        block = '''## SRE Diagnostic Toolkit

```
METRICS: RED (rate, errors, duration); USE for nodes
LOGS: CloudWatch Logs Insights, Loki LogQL with label selectors
TRACES: X-Ray/OpenTelemetry — verify trace_id propagation
COMMANDS:
  histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))
CARDINALITY: count unique label values before shipping user_id tag
```

---

'''
        text = insert_before(text, block, "## Incident Scenario")
    if "## Decision Framework" not in text:
        block = '''## Decision Framework

```
METRICS → aggregated SLO dashboards
LOGS → "why this request failed" (structured, sampled)
TRACES → cross-service latency chain (tail sampling)
VENDOR: AWS → CloudWatch+X-Ray; K8s → Prom/Grafana/Loki/Tempo
SLO alerting: see SLOs SLIs Error Budgets and Alerting.md
```

---

'''
        text = insert_before(text, block, "## Incident Scenario")
    if "## Key Takeaways" not in text:
        text += '''

---

## Key Takeaways

```
1. Observability = arbitrary questions on high-cardinality data.
2. Cardinality is a design constraint — compute before new labels.
3. Page on symptom burn rates, not CPU thresholds.
4. Structured logs + trace context propagation are baselines.
5. Tail-based trace sampling captures incidents affordably.
```

---

## Targeted Reading

- Google SRE Book Ch 6
- USE/RED methods (Gregg, Wilkie)
- SLOs SLIs Error Budgets and Alerting.md (Week 8)
'''
    return text


def reorder_standard_sections(text: str, incident_marker: str) -> str:
    m = re.search(
        r"(---\n\n## Production Failure Patterns\n.*?)(---\n\n## Key Takeaways)",
        text,
        re.DOTALL,
    )
    if not m or incident_marker not in text:
        return text
    block = m.group(1).rstrip() + "\n"
    without = text[: m.start()] + text[m.end(1) :]
    if block.strip() in without.split(incident_marker)[0]:
        return without
    return without.replace(f"\n---\n\n{incident_marker}", f"\n---\n\n{block}---\n\n{incident_marker}", 1)


def fix_http_structure(text: str) -> str:
    text = text.replace("# 🔥 SRE TROUBLESHOOTING SCENARIO — HTTP", "## Incident Scenario")
    text = text.replace("# Incident Response & Analysis", "## Expert Analysis")
    return reorder_standard_sections(text, "## Incident Scenario")


def expand_http_expert_analysis(text: str) -> str:
    replacements = [
        (
            "## Question 2: Why Mobile Users Are More Affected\n\nHigher RTT amplifies serial HTTP/1.1 chains. Mobile connection pools churn more.\nOptional HTTP/3 QUIC timeout on restrictive networks is a secondary amplifier.",
            """## Question 2: Why Mobile Users Are More Affected

```
Mobile RTT ~120ms (LTE) vs desktop ~20ms. With 200 serial HTTP/1.1 backend
requests and ~6 parallel connections per host:
  batches ≈ 34 × 120ms ≈ 4.1s minimum (matches observed 4.2s page load)

Radio state transitions and app background/foreground churn connection pools.
QUIC fallback adds timeout if UDP/443 blocked on corporate WiFi.
Backend p50 15ms is irrelevant — user time = f(RTT, request count, parallelism).
```""",
        ),
        (
            "## Question 3: Immediate Mitigation\n\nRoll back endpoint split, or add BFF aggregation endpoint. Verify requests/page\ndrops from ~200 to ~5.",
            """## Question 3: Immediate Mitigation

```
MINUTE 0-2: Revert deployment OR deploy BFF /api/product/{id}/bundle
MINUTE 2-5: ALB logs — verify requests/page drops from ~200 to <10
MINUTE 5-10: Enable HTTP/2 to backends if keeping split (ALPN h2 on targets)
WATCH: RUM LCP 4.2s → ~1.1s; TargetResponseTime stays ~15ms
```""",
        ),
        (
            "## Question 4: Long-Term Fix\n\nBFF aggregation, HTTP/2 end-to-end through ALB, GraphQL, or edge aggregation.\nNever expose microservice fan-out to browsers across an HTTP/1.1 hop.",
            """## Question 4: Long-Term Fix

```
1. BFF per client — server-side parallel fan-out (GraphQL + DataLoader)
2. HTTP/2 end-to-end ALB → backend with sufficient concurrent streams
3. Edge aggregation for cacheable public catalog (CloudFront Functions)
NEVER: N microservice endpoints directly to browser over HTTP/1.1
CI: load test asserts requests/page < 15; alarm RequestCountPerTarget > 3× baseline
```""",
        ),
    ]
    for old, new in replacements:
        if old in text:
            text = text.replace(old, new)
    return text


def expand_tcp_incident(text: str) -> str:
    marker = "## Question 1: Root Cause Analysis"
    if marker not in text or "MINUTE-BY-MINUTE REASONING" in text:
        return text
    expansion = """
```
MINUTE-BY-MINUTE REASONING:

T+0: TIME_WAIT ~2,000 — within noise. ActiveOpens rising slowly.
T+5: TIME_WAIT ~12,000. estab 847 despite pool max=100 → pool bypass.
T+10: Port consumption exceeds TIME_WAIT release (~28K ephemeral range).
T+15: ALERT. connect() EADDRNOTAVAIL → "connection timeout" to Postgres.

EVIDENCE: ss timewait 38,102 + estab 847 + DB 497/500 = per-request TCP churn.
```
"""
    return text.replace(marker + "\n\n", marker + expansion + "\n", 1)


def process_file(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    original = text
    name = path.name

    for block, anchor in FILE_FIXES.get(name, []):
        text = insert_before(text, block, anchor)

    if name == "Message Queues and Kafka.md":
        text = fix_kafka_failure_modes(text)
    elif name == "Lamport Clocks Vector Clocks and Causality.md":
        text = fix_lamport_headers(text)
    elif name == "Observability.md":
        text = fix_observability(text)
    elif name == "TCP vs UDP.md":
        text = reorder_standard_sections(text, "## Incident Scenario: The Mystery Latency Spike")
        text = expand_tcp_incident(text)
    elif name == "HTTP-1.1-vs-HTTP-2-vs-HTTP-3.md":
        text = fix_http_structure(text)
        text = expand_http_expert_analysis(text)

    if text != original:
        path.write_text(text, encoding="utf-8", newline="\n")
        return True
    return False


def main():
    weeks = [
        "Week-01-Transport-Application-Protocols-DNS-CDN",
        "Week-02-Storage-Fundamentals",
        "Week-03-Distributed-Systems-Theory",
        "Week-04-Replication-Partitioning-Consensus",
        "Week-05-Database-Internals",
        "Week-06-Architecture-Patterns",
        "Week-08-Advanced-Patterns",
    ]
    changed = []
    for week in weeks:
        for p in sorted((ROOT / week).glob("*.md")):
            if "Worked Answers" in p.name:
                continue
            if process_file(p):
                changed.append(str(p.relative_to(ROOT)))
    print(f"Updated {len(changed)} files:")
    for c in changed:
        print(f"  {c}")


if __name__ == "__main__":
    main()
