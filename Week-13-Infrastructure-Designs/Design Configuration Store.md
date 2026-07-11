# Design Configuration Store
> Week 13 — Infrastructure System Design | etcd / Consul / ZooKeeper
> **Watch semantics + Raft (Week 4)** — design a strongly-consistent metadata and configuration service for interviews.

---

## Learning Objectives
```
╔═════════════════════════════════════════════════════════════════════════════╗
║ AFTER THIS MODULE, YOU WILL BE ABLE TO:                                     ║
╟─────────────────────────────────────────────────────────────────────────────╢
║ 1. Design a configuration store for K8s, service discovery, feature flags   ║
║ 2. Explain watch semantics: long poll, gRPC stream, ZAB notifications       ║
║ 3. Map requirements to CP (Raft) vs AP (gossip) — config is CP              ║
║ 4. Walk Raft leader election + log replication for config writes (Week 4)   ║
║ 5. Design key namespace, versioning, and lease-based locks                  ║
║ 6. Compare etcd vs Consul vs ZooKeeper with decision matrix                 ║
║ 7. Handle watch storms, large value rejection, and etcd overload            ║
║ 8. Answer 'design service discovery' and 'design distributed lock'          ║
╚═════════════════════════════════════════════════════════════════════════════╝
```
---

## Wrong Mental Models (Destroy These First)
```
╔═════════════════════════════════════════════════════════════════════════════════════════╗
║ Config store = Redis                                                                    ║
╟─────────────────────────────────────────────────────────────────────────────────────────╢
║ WRONG. Redis is AP/cache. Config needs linearizable reads for coordination decisions.   ║
╚═════════════════════════════════════════════════════════════════════════════════════════╝



╔═════════════════════════════════════════════════════════════════════════════════════╗
║ ZooKeeper is legacy — skip it                                                       ║
╟─────────────────────────────────────────────────────────────────────────────────────╢
║ WRONG. ZK still underpins older Kafka, Hadoop. Interviewers expect ZAB awareness.   ║
╚═════════════════════════════════════════════════════════════════════════════════════╝



╔══════════════════════════════════════════════════════════════════════╗
║ Watch = polling every second                                         ║
╟──────────────────────────────────────────────────────────────────────╢
║ WRONG. Efficient watches push changes; naive poll melts the store.   ║
╚══════════════════════════════════════════════════════════════════════╝



╔═════════════════════════════════════════════════════════════════════════╗
║ Strong consistency is slow always                                       ║
╟─────────────────────────────────────────────────────────────────────────╢
║ WRONG. Config data is small, low QPS — Raft p99 < 10ms is achievable.   ║
╚═════════════════════════════════════════════════════════════════════════╝



╔══════════════════════════════════════════════════════════════════════════════════╗
║ etcd only for Kubernetes                                                         ║
╟──────────────────────────────────────────────────────────────────────────────────╢
║ WRONG. Locks, leader election, feature flags, service mesh config — all valid.   ║
╚══════════════════════════════════════════════════════════════════════════════════╝
```
---

## Core Teaching

### Foundation

> Staff / Principal stretch sections are marked below. Mastery gate: Staff required; Principal optional.

```
THE SYSTEM DESIGN INTERVIEW OPENING (45 MINUTES TOTAL)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Minutes 0-5:   CLARIFY requirements (functional + non-functional)
  Minutes 5-10:  ESTIMATE scale (QPS, storage, bandwidth)
  Minutes 10-15: HIGH-LEVEL design (boxes and arrows — get buy-in)
  Minutes 15-35: DEEP DIVE (2-3 areas interviewer picks)
  Minutes 35-42: BOTTLENECKS, failure modes, tradeoffs
  Minutes 42-45: SUMMARY and extensions

  RULE: Never jump to micro-optimizations before the interviewer
  agrees on the high-level shape. A beautiful consistent-hashing
  explanation that solves the wrong problem scores zero.
```

### 3.1 — Canonical Prompts

```
  "Design a configuration management system for 10K microservices"
  "Design service discovery for a datacenter"
  "Design a distributed lock service"
  "Design etcd" / "How does Kubernetes store cluster state?"

CLARIFY:
  □ Data size (config files vs small keys — etcd limit 1.5 MB default)
  □ Read/write QPS (usually low thousands, not millions)
  □ Consistency (must be linearizable for locks and leader election)
  □ Watch requirements (how many watchers per key?)
  □ Multi-datacenter or single?
  □ Ephemeral nodes (service registration TTL)?
```

### 3.2 — Why CP / Raft (Week 4 Connection)

```
CONFIGURATION STORE REQUIREMENTS → CP SYSTEM:

  Leader election for database primary:
    → Two nodes must NOT both think they're leader (split-brain)
    → Requires consensus — Raft (Week 4)

  Service discovery:
    → Stale registry → traffic to dead instances
    → Linearizable read OR carefully documented staleness bound

  Feature flag rollout:
    → Inconsistent flag across instances → split behavior
    → Strong consistency preferred for control plane

  PACELC: P+C during partition ( sacrifice A)
    → Minority partition cannot accept writes (no quorum)
    → Correct for config — better unavailable than wrong

  RAFT SUMMARY (interview 2-minute version):
    → Leader elected per term (Week 4 Consensus Raft.md)
    → Client writes go to leader, appended to replicated log
    → Committed when majority ack → applied to state machine
    → Reads from leader (or lease-read from follower with risk)
```

### 3.3 — High-Level Architecture

```
                    CLIENTS (apps, kube-apiserver)
                           │
                           ▼
              ┌────────────────────────────┐
              │      Load Balancer         │
              │   (optional — smart client │
              │    often talks to leader)  │
              └─────────────┬──────────────┘
                            │
         ┌──────────────────┼──────────────────┐
         ▼                  ▼                  ▼
    ┌─────────┐       ┌─────────┐       ┌─────────┐
    │ etcd-1  │◄─────►│ etcd-2  │◄─────►│ etcd-3  │
    │ (leader)│ Raft  │(follower)│ Raft  │(follower)│
    └────┬────┘       └────┬────┘       └────┬────┘
         │                 │                 │
         └─────────────────┴─────────────────┘
                           │
                    BoltDB / bbolt
                    (embedded KV on disk)

  State machine: hierarchical key-value
    /services/payment/instances/10.0.1.5:8080 = {"healthy":true}
    /config/feature/dark_mode = "enabled"
    /locks/db-migration = lease_id (ephemeral)
```
### 3.4 — Data Model & Key Namespace

```
Hierarchical keys (like filesystem):
  /env/prod/service/payment/v1/replicas/192.168.1.10

Operations:
  PUT(key, value) — linearizable write via Raft
  GET(key) — linearizable or serializable (etcd)
  DELETE(key)
  GET prefix /services/payment/ → range query
  WATCH(key | prefix) — stream of change events

Version:
  Each key has mod_revision (global cluster revision)
  CAS: Compare-And-Swap on mod_revision — optimistic locking
### 3.5 — Watch Semantics (Critical Interview Topic)

```
WATCH = push-based change notification

  etcd watch flow:
    1. Client issues WatchRequest(key or prefix, start_revision)
    2. gRPC bidi stream opened
    3. On PUT/DELETE affecting watched key → event on stream
    4. Events include: type, key, value, mod_revision
    5. Client updates local cache, reacts (reload config, reroute)

  start_revision:
    → 0 or current: only future events
    → N: replay from revision N (catch-up after disconnect)

  WATCH STORM problem:
    10K clients watch same prefix → 1 config change → 10K notifications
    Mitigation:
      → App-side debounce (wait 500ms coalesce)
      → Watch proxies (Consul agent local cache)
      → Avoid watching root prefix /

  ZooKeeper watch:
    → ONE-TIME trigger — must re-register after each event
    → Miss events if slow to re-watch (classic footgun)
    etcd/Consul: persistent stream (better)

  Consul blocking queries:
    → HTTP long poll: ?index=123&wait=30s
    → Returns when index changes or timeout
    → Agent serves from local cache — reduces server load
### 3.6 — Ephemeral Keys & Leases

```
SERVICE DISCOVERY PATTERN:

  Register: PUT /services/payment/instance/host:port
            with TTL lease (heartbeat every lease/3)

  Lease expires without refresh → key auto-deleted
  Watchers receive DELETE event → remove from load balancer

  DISTRIBUTED LOCK:
    CREATE /locks/job-X with lease
    If key exists with live lease → lock held
    Fencing token = lease revision (Week 4 fencing tokens)

  Kubernetes uses leases API for leader election components
### 3.7 — etcd vs Consul vs ZooKeeper

```
┌────────────┬─────────────┬─────────────┬─────────────┐
│            │ etcd        │ Consul      │ ZooKeeper   │
├────────────┼─────────────┼─────────────┼─────────────┤
│ Consensus  │ Raft        │ Raft        │ ZAB (Paxos) │
│ API        │ gRPC v3     │ HTTP+DNS    │ Custom ZK   │
│ Watch      │ gRPC stream │ blocking Q  │ one-shot    │
│ Multi-DC   │ limited     │ WAN gossip  │ observers   │
│ Health     │ minimal     │ built-in    │ ephemeral   │
│ K8s        │ native      │ optional    │ no          │
└────────────┴─────────────┴─────────────┴─────────────┘

Interview pick:
  K8s control plane → etcd
  Service mesh + DNS → Consul
  Legacy Hadoop/Kafka → know ZooKeeper
### 3.8 — Read Scales vs Write Scales

```
Config store QPS typically:
  Writes: hundreds/sec (cluster events, deploys)
  Reads: thousands/sec (watches + gets)
  Reads from followers (etcd quorum read, Consul stale OK)
  Writes ALWAYS through leader

  BoltDB: single writer — leader applies sequentially
  Not your bottleneck at config scale (<10K W/s)
### 3.9 — Kubernetes Integration

```
kube-apiserver → etcd:
  All cluster state: pods, services, secrets, configmaps
  Optimistic concurrency: resourceVersion = etcd mod_revision
  Watch opens for kubectl get -w, controllers (ReplicaSet)

  Design interview extension:
    "How does kubectl rolling update work?"
    → Deployment controller watches ReplicaSet, updates etcd,
      kubelet watches pod spec, pulls new image

---

## Concrete Examples
### Service Discovery
```
Payment service registers with Consul agent; NGINX/consul-template watches; dead instances removed in 1 TTL cycle.
```
### Feature Flags
```
Key /flags/checkout_v2 = {enabled: true, pct: 5}; apps watch prefix /flags/; debounce reload 1s.
```
### Database Leader Election
```
Patroni uses etcd DCS; key /service/postgres/leader holds master identity with session TTL.
```
### Distributed Lock for Cron
```
Only one scheduler runs nightly batch; etcd lock with 30s lease, heartbeat renew.
```
### Config Push vs Pull
```
Pull: app watches etcd; Push: GitOps commits to etcd via CI — audit trail in revision history.
```

---

### Staff

## Production Patterns
#### Always 3 or 5 etcd nodes (odd quorum)
```
Implementation: Always 3 or 5 etcd nodes (odd quorum)
```
#### Dedicated etcd cluster — never colocate with app workloads
```
Implementation: Dedicated etcd cluster — never colocate with app workloads
```
#### Defragmentation schedule (etcdctl defrag)
```
Implementation: Defragmentation schedule (etcdctl defrag)
```
#### Automated snapshot to S3 every 30 min
```
Implementation: Automated snapshot to S3 every 30 min
```
#### Rate limit expensive range queries
```
Implementation: Rate limit expensive range queries
```
#### Separate RBAC for read-only watchers
```
Implementation: Separate RBAC for read-only watchers
```
#### TLS everywhere (peer + client)
```
Implementation: TLS everywhere (peer + client)
```
#### Monitor db size, leader changes, proposal failures
```
Implementation: Monitor db size, leader changes, proposal failures
```

---

## Failure Modes
### etcd overload from watches
```
Too many watchers on hot prefix; add proxies, narrow watch scope
```
### Split brain (misconfigured)
```
Even number of nodes or partition without quorum — minority stops writes
```
### Large value rejection
```
Config > 1.5 MB — store in object storage, etcd holds pointer only
```
### Defrag during peak
```
Brief unavailability; schedule off-peak; snapshot first
```
### Leader election storm
```
Network flap; tune election timeout; fix asymmetric routing
```
### Zombie lock holder
```
Lease TTL too long; always use fencing tokens on protected resources
```
### Revision compaction lag
```
Long watch with old start_revision fails; client must compact catch-up
```

---

## SRE Diagnostic Toolkit
```
etcdctl endpoint health --cluster
etcdctl endpoint status -w table  → DB size, leader, RAFT index
etcdctl check perf → baseline write/read latency

Metrics:
  etcd_server_leader_changes_seen_total (flapping?)
  etcd_disk_wal_fsync_duration_seconds (disk slow?)
  etcd_network_peer_round_trip_time_seconds

Consul:
  consul members, consul operator raft list-peers
  DEBUG blocking query latency on servers

ZooKeeper:
  echo stat | nc localhost 2181  → latency, connections
  mntr command → zk_outstanding_requests
```

---

## Decision Framework
```
Use etcd when: Kubernetes, need gRPC watches, strong consistency
Use Consul when: service discovery + health checks + DNS interface
Use ZooKeeper when: maintaining legacy stack only
Use NOT config store when: high QPS KV → Dynamo; cache → Redis

Watch pattern:
  Few keys, many clients → local agent cache (Consul) or watch proxy
  Many keys, few clients → direct etcd watch OK
```

---

## Incident Scenario
```
P1: Kubernetes API timeouts — etcd cluster degraded

  3-node etcd on m5.large, DB size 7.8 GB (quota 8 GB)
  14:00 Deploy adds 500 ConfigMaps (large JSON blobs)
  14:15 DB size 8.1 GB — etcd rejects writes
  14:18 kube-apiserver 503, new pods fail scheduling
  14:22 Discovery: no compaction/defrag for 90 days
  14:25 50 controllers each watching / — watch fan-out 50K events/sec

Questions:
  1. Root cause chain?
  2. Immediate recovery steps?
  3. Why did watches make it worse?
  4. Architecture changes?
```

---



---

> **Answer key (do not open until you attempt the Ops Sim / questions):**
> [`../answers/Week-13-Infrastructure-Designs/Design Configuration Store Answers.md`](../answers/Week-13-Infrastructure-Designs/Design Configuration Store Answers.md)

## Key Takeaways
```
╔═════════════════════════════════════════════════════════════════════════╗
║ REMEMBER:                                                               ║
╟─────────────────────────────────────────────────────────────────────────╢
║ 1. Config/coordination → CP + Raft (Week 4), not AP Dynamo.             ║
║ 2. Watches: etcd persistent stream vs ZK one-shot vs Consul blocking.   ║
║ 3. Leases + ephemeral keys = service discovery and locks.               ║
║ 4. Keep values small; etcd is for metadata not blobs.                   ║
║ 5. Interview: draw 3-node Raft before API details.                      ║
╚═════════════════════════════════════════════════════════════════════════╝
```
---

## Targeted Reading
```
REQUIRED:
  1. etcd Raft paper + etcd.io docs (Watch API, Learner nodes)
  2. Week 4: Consensus Raft.md (this repo)
  3. Google Chubby paper (predecessor inspiration)
  4. Consul architecture docs (gossip + Raft separation)

OPTIONAL:
  5. ZooKeeper Programmer's Guide (watches section)
  6. Kubernetes etcd best practices (official ops guide)
```

---

## Appendix: Extended Practice and Production Deep Dive

## A. Hands-On Exercises

These exercises run on local Docker clusters. Each exercise builds interview muscle memory for watch semantics, leases, and production failure modes.

### A.1 — Local Lab Setup

```
PREREQUISITES:
  Docker Desktop or Podman
  etcd v3.5+ image: quay.io/coreos/etcd:v3.5.12
  Consul 1.16+ image: hashicorp/consul:1.16
  ZooKeeper 3.8 image: zookeeper:3.8

NETWORK TOPOLOGY (single machine):

  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
  │  etcd-1     │◄───►│  etcd-2     │◄───►│  etcd-3     │
  │ :2379/:2380 │     │ :2479/:2480 │     │ :2579/:2580 │
  └──────┬──────┘     └──────┬──────┘     └──────┬──────┘
         │                   │                   │
         └───────────────────┴───────────────────┘
                             │
                    ┌────────┴────────┐
                    │  Your laptop    │
                    │  etcdctl client │
                    └─────────────────┘

START 3-NODE ETCD CLUSTER:

  docker network create etcd-net

  for i in 1 2 3; do
    PORT=$((2378 + i))
    PEER=$((2380 + i - 1))
    docker run -d --name etcd-$i --network etcd-net \
      -p ${PORT}:2379 -p ${PEER}:2380 \
      quay.io/coreos/etcd:v3.5.12 \
      /usr/local/bin/etcd \
        --name etcd-$i \
        --data-dir /etcd-data \
        --listen-client-urls http://0.0.0.0:2379 \
        --advertise-client-urls http://etcd-$i:2379 \
        --listen-peer-urls http://0.0.0.0:2380 \
        --initial-advertise-peer-urls http://etcd-$i:2380 \
        --initial-cluster etcd-1=http://etcd-1:2380,etcd-2=http://etcd-2:2380,etcd-3=http://etcd-3:2380 \
        --initial-cluster-state new \
        --initial-cluster-token etcd-cluster-1
  done

VERIFY:
  export ETCDCTL_API=3
  export ETCDCTL_ENDPOINTS=http://localhost:2379,http://localhost:2479,http://localhost:2579
  etcdctl endpoint health --cluster
  etcdctl endpoint status -w table
```

### A.2 — Exercise 1: etcdctl Watch with Revision Catch-Up

**Goal:** Observe persistent gRPC watch streams, `mod_revision`, and catch-up after disconnect.

```
TERMINAL 1 — Start watch from revision 0 (future events only):

  etcdctl watch /config/app --prefix

TERMINAL 2 — Write keys and observe revision increments:

  etcdctl put /config/app/feature_flags '{"dark_mode":true}'
  # revision increments globally (e.g., mod_revision=15)

  etcdctl put /config/app/rate_limit "1000"
  # mod_revision=16

  etcdctl del /config/app/rate_limit
  # mod_revision=17, DELETE event on watch stream

TERMINAL 1 OUTPUT (expected):
  PUT
  /config/app/feature_flags
  {"dark_mode":true}
  PUT
  /config/app/rate_limit
  1000
  DELETE
  /config/app/rate_limit

REVISION CATCH-UP EXERCISE:

  1. Record current revision:
     REV=$(etcdctl get /config/app/feature_flags --print-value-only -w json \
       | jq '.kvs[0].mod_revision')
     echo "Current mod_revision: $REV"

  2. Kill Terminal 1 watch (Ctrl-C)

  3. Make 5 more writes in Terminal 2:
     for i in 1 2 3 4 5; do
       etcdctl put /config/app/counter "$i"
     done

  4. Restart watch FROM OLD REVISION (replay missed events):
     etcdctl watch /config/app --prefix --rev=$REV

  5. Observe: you receive ALL events from revision $REV+1 through current
     This is how Kubernetes informers recover after apiserver reconnect

CATCH-UP FAILURE MODE (compact boundary):

  # Compact history older than revision 100:
  etcdctl compact 100

  # Try watch from revision 50:
  etcdctl watch /config/app --prefix --rev=50
  # ERROR: mvcc: required revision has been compacted

  FIX: Client must LIST current state + watch from "now":
    etcdctl get /config/app --prefix
    etcdctl watch /config/app --prefix   # no --rev, future only

INTERVIEW TALKING POINT:
  "Disconnected clients use start_revision for replay. If revision is
   compacted, full resync via range query is mandatory. Production
   clients (client-go reflector) handle this automatically."
```

### A.3 — Exercise 2: Compare-And-Swap (Optimistic Locking)

```
SETUP:
  etcdctl put /config/deploy/version "v1.2.3"

CAS SUCCESS PATH:

  # Read mod_revision:
  etcdctl get /config/deploy/version -w json | jq '.kvs[0].mod_revision'
  # Assume output: 42

  # CAS: only write if mod_revision still 42:
  etcdctl txn --compare mod="/config/deploy/version"=42 \
    --then put /config/deploy/version "v1.2.4" \
    --else get /config/deploy/version

  # SUCCESS: version updated to v1.2.4

CAS FAILURE PATH (concurrent writer):

  # Terminal A reads mod_revision=55
  # Terminal B writes first, mod_revision becomes 56
  # Terminal A attempts CAS with rev=55:
  etcdctl txn --compare mod="/config/deploy/version"=55 \
    --then put /config/deploy/version "v1.2.5" \
    --else get /config/deploy/version

  # FAILURE branch executes: returns current value v1.2.4
  # Terminal A must re-read and retry

INTERVIEW CONNECTION:
  CAS on mod_revision is the foundation of Kubernetes resourceVersion
  optimistic concurrency. Apiserver rejects PATCH if resourceVersion stale.
```

### A.4 — Exercise 3: Lease-Based Ephemeral Keys (Service Discovery)

```
CREATE LEASE (TTL 10 seconds):

  LEASE_ID=$(etcdctl lease grant 10 -w json | jq '.ID')
  echo "Lease ID: $LEASE_ID"

REGISTER EPHEMERAL SERVICE INSTANCE:

  etcdctl put /services/payment/instances/10.0.1.5:8080 \
    '{"healthy":true,"weight":100}' --lease=$LEASE_ID

VERIFY KEY EXISTS:
  etcdctl get /services/payment/instances --prefix

SIMULATE HEARTBEAT (keepalive):
  # In production, app calls LeaseKeepAlive every TTL/3
  etcdctl lease keep-alive $LEASE_ID &
  KEEPALIVE_PID=$!

STOP HEARTBEAT — SIMULATE CRASH:
  kill $KEEPALIVE_PID
  sleep 12   # wait for TTL expiry

VERIFY AUTO-DELETION:
  etcdctl get /services/payment/instances/10.0.1.5:8080
  # Key not found — lease expired, key deleted automatically

WATCH LEASE EVENTS:
  # Terminal 1:
  etcdctl watch /services/payment/instances --prefix

  # Terminal 2: create lease, put key, let expire
  # Terminal 1 sees DELETE event when lease TTL expires

PRODUCTION PARALLEL:
  Consul: session TTL + check TTL on service registration
  ZooKeeper: ephemeral sequential znodes under /services
  Kubernetes: Lease objects bound to Pod lifecycle
```

### A.5 — Exercise 4: Distributed Lock with Fencing Token

```
LOCK ACQUISITION PATTERN (etcd concurrency recipe):

  # Step 1: Create lease for lock holder
  LOCK_LEASE=$(etcdctl lease grant 15 -w json | jq '.ID')

  # Step 2: Acquire lock (create key if not exists)
  etcdctl lock /locks/db-migration --ttl=15
  # Blocks until lock acquired, returns lock key path

  # Alternative manual implementation:
  etcdctl txn \
    --compare create="/locks/db-migration"=0 \
    --then put /locks/db-migration "holder-$(hostname)" --lease=$LOCK_LEASE \
    --else get /locks/db-migration

FENCING TOKEN (store revision as token):

  # When lock acquired, record mod_revision as fencing token:
  TOKEN=$(etcdctl get /locks/db-migration -w json | jq '.kvs[0].mod_revision')
  echo "Fencing token: $TOKEN"

  # Protected resource (simulated DB) rejects writes with token < highest_seen
  # If old holder wakes up after crash, its token is stale

RELEASE LOCK:
  etcdctl del /locks/db-migration
  # Or revoke lease: etcdctl lease revoke $LOCK_LEASE

LOCK CONTENTION DEMO:

  # Terminal 1: acquire lock (blocks)
  etcdctl lock /locks/db-migration --ttl=30

  # Terminal 2: attempt lock (waits)
  etcdctl lock /locks/db-migration --ttl=30

  # Terminal 1: Ctrl-C or revoke lease
  # Terminal 2: immediately acquires lock

INTERVIEW GOTCHA:
  "Lock without fencing token is NOT safe. Crashed holder can resume
   writes after TTL if GC pause exceeded lease duration. Always pass
   monotonic fencing token to storage layer (Chubby paper, §2.5)."
```

### A.6 — Exercise 5: Consul KV and Blocking Queries

```
START CONSUL DEV AGENT:

  consul agent -dev -client=0.0.0.0

WRITE CONFIG:
  consul kv put config/app/feature_flags '{"canary":5}'
  consul kv put config/app/timeout_ms 3000

READ WITH BLOCKING QUERY (long poll):

  # First read — note X-Consul-Index header (or -detailed):
  curl -s "http://localhost:8500/v1/kv/config/app/feature_flags?raw"
  INDEX=$(curl -s "http://localhost:8500/v1/kv/config/app/feature_flags" \
    | jq '.[0].ModifyIndex')
  echo "Current index: $INDEX"

  # Blocking wait (returns when index changes OR 30s timeout):
  curl -s "http://localhost:8500/v1/kv/config/app/feature_flags?index=$INDEX&wait=30s"

  # In another terminal, update key:
  consul kv put config/app/feature_flags '{"canary":10}'

  # Blocking query returns immediately with new value

CONSUL AGENT LOCAL CACHE:

  ┌──────────┐    blocking query    ┌──────────────┐
  │ App on   │ ──────────────────► │ Consul Agent │
  │ host A   │ ◄────────────────── │ (local cache)│
  └──────────┘    cached response └──────┬───────┘
                                          │ fan-in
                                          ▼
                                   ┌──────────────┐
                                   │ Consul Server│
                                   │ (Raft leader)│
                                   └──────────────┘

  # 1000 apps on same host → 1 blocking query to server (via agent)
  # vs etcd: 1000 gRPC watch streams to server directly

CONSUL SESSION LOCK:

  consul lock -shell='echo acquired; sleep 10; echo done' \
    config/locks/deploy

  # Uses session + KV lock prefix under .lock path
```

### A.7 — Exercise 6: ZooKeeper One-Shot Watch Footgun

```
START ZK (docker):
  docker run -d --name zk -p 2181:2181 zookeeper:3.8

USING zkCli.sh:

  # Create node:
  create /config/app "v1"

  # Set one-shot watch:
  get -w /config/app

  # In another session, update:
  set /config/app "v2"
  # First session receives Watcher.Event.NodeDataChanged

  # CRITICAL: watch is ONE-TIME — must re-register:
  get /config/app
  # No watch active! Changes between events can be MISSED

  # In second session:
  set /config/app "v3"
  set /config/app "v4"

  # First session (only did get, not get -w):
  get /config/app
  # Sees v4 — MISSED v2→v3 transition notification

SAFE ZK PATTERN (Curator Framework):
  1. Read data + register watch atomically
  2. On event: re-read + re-register before processing
  3. Or use TreeCache/PathChildrenCache (maintains local cache)

INTERVIEW CONTRAST:
  etcd: persistent bidi gRPC stream, events until disconnect
  Consul: blocking query loop, index-based
  ZK: one-shot, client must re-arm every event
```

---

## B. Watch Semantics Deep Dive

Understanding watch implementations separates senior candidates from junior ones. Each system makes different tradeoffs between latency, correctness, and server load.

### B.1 — Why Watches Exist

```
WITHOUT WATCHES (naive polling):

  while true:
    config = GET("/config/app")
    if config != last_config:
      reload()
    sleep(1)

  Problems:
    → 10,000 clients × 1 QPS = 10,000 reads/sec on config store
    → Config changes once per hour — 99.97% of reads are wasted
    → Leader etcd node handles all linearizable reads
    → During incident: polling INCREASES load on failing system

WITH WATCHES (push notification):

  watch("/config/app")
  on_event(event):
    reload(event.value)

  Benefits:
    → Zero load when config is stable
    → Sub-millisecond notification on change
    → Server tracks subscriptions, pushes only on mutation

  Risks:
    → Watch storm: one change → N notifications
    → Memory per watch connection (etcd: ~KB per watcher)
    → Reconnection catch-up can generate read amplification
```

### B.2 — etcd gRPC Watch: Protocol and Lifecycle

```
ETCD WATCH ARCHITECTURE:

  Client                           etcd Leader
    │                                  │
    │──── WatchCreateRequest ─────────►│
    │     key=/config/app              │
    │     range_end=/config/app\x00    │  (prefix watch)
    │     start_revision=100           │
    │     progress_notify=true         │
    │                                  │
    │◄─── WatchCreatedResponse ────────│  (stream established)
    │                                  │
    │◄─── WatchResponse (PUT) ────────│  revision=101
    │◄─── WatchResponse (DELETE) ─────│  revision=102
    │◄─── WatchResponse (progress) ────│  revision=105 (no events, heartbeat)
    │                                  │
    │     ... TCP disconnect ...       │
    │                                  │
    │──── WatchCreateRequest ─────────►│  (new stream)
    │     start_revision=103           │  (replay from last seen+1)
    │◄─── WatchResponse (DELETE) ─────│  revision=104 (missed event)
    │◄─── WatchResponse (PUT) ────────│  revision=105
    │                                  │

KEY FIELDS IN WatchCreateRequest:
  key:           start of range (byte string)
  range_end:     end of range (prefix trick: key + 1)
  start_revision: 0 = current; N = replay from N
  filters:       PUT only, DELETE only, or both
  progress_notify: periodic heartbeat with current revision

REVISION SEMANTICS:
  Every mutation increments the GLOBAL cluster revision (monotonic)
  mod_revision on a key = revision of its last modification
  create_revision = revision when key was first created
  watch events carry header.revision = current store revision at event time
```

**ASCII Sequence: etcd Watch Happy Path**

```
  App              etcdctl           etcd Leader         etcd Follower
   │                  │                   │                   │
   │  watch /config   │                   │                   │
   │─────────────────►│                   │                   │
   │                  │──WatchCreate─────►│                   │
   │                  │◄─WatchCreated─────│                   │
   │                  │                   │                   │
   │                  │                   │◄──AppendEntries───│
   │                  │                   │   (Raft replicate)│
   │                  │                   │                   │
   │  put /config v2  │                   │                   │
   │─────────────────►│──Txn/Put─────────►│                   │
   │                  │                   │──apply to mvcc────│
   │                  │                   │──notify watchers──│
   │                  │◄─WatchResponse────│                   │
   │◄─event PUT v2────│                   │                   │
   │  reload config   │                   │                   │
   │                  │                   │                   │
```

**ASCII Sequence: etcd Watch Disconnect and Catch-Up**

```
  App                    etcd Leader
   │                          │
   │◄─── event rev=500 ───────│
   │◄─── event rev=501 ───────│
   │                          │
   │  *** network partition   │
   │      (30 seconds)        │
   │                          │  rev=502 PUT (missed)
   │                          │  rev=503 PUT (missed)
   │                          │  rev=504 DELETE (missed)
   │                          │
   │  *** reconnect           │
   │                          │
   │──WatchCreate rev=502────►│
   │◄─── event rev=502 ───────│  (replay)
   │◄─── event rev=503 ───────│
   │◄─── event rev=504 ───────│
   │◄─── progress rev=504 ────│  (caught up)
   │                          │
   │  IF rev=502 compacted:   │
   │──WatchCreate rev=502────►│
   │◄─── ERROR compacted ─────│
   │──Get /config --prefix───►│  (full resync)
   │◄─── current state ───────│
   │──WatchCreate rev=0──────►│  (watch future)
   │                          │
```

### B.3 — ZooKeeper One-Shot Watches

```
ZOOKEEPER WATCH MODEL:

  Watches are ONE-TIME triggers, set at read time:
    getData(path, watcher)    → watch data changes
    getChildren(path, watcher) → watch child list changes
    exists(path, watcher)     → watch creation/deletion

  After event fires, watch is REMOVED.
  Client MUST re-register before processing event to avoid gaps.

THE CLASSIC RACE:

  Thread A                          Thread B
    │                                  │
    │ getData("/config") → "v1"        │
    │ (watch registered)               │
    │                                  │ setData("/config", "v2")
    │                                  │ setData("/config", "v3")
    │◄── event: data changed ──────────│
    │                                  │
    │ process event...                 │
    │ getData("/config") → "v3"        │
    │                                  │
    │ MISSED: notification of v1→v2    │
    │ (acceptable if only care about   │
    │  latest value, NOT event log)    │

  For event sourcing / audit: UNACCEPTABLE
  For "reload latest config": acceptable IF you always read after event

ZAB (ZooKeeper Atomic Broadcast):
  Leader serializes all writes
  Followers apply in order (similar to Raft log apply)
  Watch notifications sent AFTER local apply on each node
  Client connected to follower may see watch slightly after leader
```

**ASCII Sequence: ZK One-Shot Watch**

```
  Client              ZK Follower           ZK Leader
    │                      │                     │
    │──getData -w /cfg────►│                     │
    │◄─data=v1, watch set──│                     │
    │                      │                     │
    │                      │                     │◄──setData /cfg v2
    │                      │◄──ZAB replicate─────│
    │                      │──apply v2───────────│
    │◄──WatcherEvent───────│  (watch FIRED)      │
    │  (watch now GONE)    │                     │
    │                      │                     │
    │  [gap window]        │                     │◄──setData /cfg v3
    │                      │◄──ZAB replicate─────│
    │                      │  (NO watch active)  │
    │                      │                     │
    │──getData /cfg────────►│                     │
    │◄─data=v3─────────────│  (missed v2→v3 evt) │
    │──getData -w /cfg─────►│  (re-arm watch)    │
    │◄─data=v3, watch set─│                     │
```

### B.4 — Consul Blocking Queries

```
CONSUL BLOCKING QUERY SEMANTICS:

  HTTP GET /v1/kv/key?index=N&wait=30s

  Server behavior:
    1. Read current Raft index (ModifyIndex for key)
    2. If index > N: return immediately with data + new index
    3. If index == N: BLOCK up to 30 seconds
    4. On mutation OR timeout: return (possibly unchanged)
    5. Client loops: new request with updated index

  This is LONG POLLING, not a persistent stream.
  Each wait cycle = one HTTP request/response.

INDEX vs ETCD REVISION:
  Consul ModifyIndex: per-key monotonic counter
  Raft index: global log position (similar to etcd revision)
  Blocking query uses per-key ModifyIndex, not global Raft index

AGENT CACHING (critical for scale):

  ┌─────────────────────────────────────────────────────────┐
  │ WITHOUT AGENT:                                          │
  │   500 apps ──blocking query──► Consul Server (500 conns)│
  │                                                         │
  │ WITH AGENT:                                             │
  │   500 apps ──blocking query──► Local Agent (1 conn up)  │
  │   Agent maintains cache, single blocking query to server│
  └─────────────────────────────────────────────────────────┘

STALENESS BOUND:
  Agent cache may lag server by ~10-50ms (anti-entropy sync)
  For service discovery: acceptable (health check TTL is seconds)
  For leader election: use server directly or sessions
```

**ASCII Sequence: Consul Blocking Query Loop**

```
  App              Consul Agent          Consul Server (leader)
   │                    │                        │
   │ GET ?index=100     │                        │
   │ &wait=30s          │                        │
   │───────────────────►│                        │
   │                    │ GET ?index=100         │
   │                    │ &wait=30s              │
   │                    │───────────────────────►│
   │                    │                        │ (blocks...)
   │                    │                        │
   │                    │                        │◄── KV PUT (index→105)
   │                    │◄─── 200, index=105 ────│
   │◄── 200, index=105 ─│                        │
   │ reload config      │                        │
   │                    │                        │
   │ GET ?index=105     │                        │
   │ &wait=30s          │                        │
   │───────────────────►│                        │
   │                    │───────────────────────►│
   │                    │                        │ (blocks 30s...)
   │                    │◄─── 200, index=105 ────│  (timeout, no change)
   │◄── 200, index=105 ─│                        │
   │ (loop continues)   │                        │
```

### B.5 — Watch Semantics Comparison Matrix

```
╔══════════════════╦════════════════╦═══════════════════╦══════════════════╗
║ Property         ║ etcd           ║ ZooKeeper         ║ Consul           ║
╠══════════════════╬════════════════╬═══════════════════╬══════════════════╣
║ Transport        ║ gRPC bidi      ║ TCP binary proto  ║ HTTP long poll   ║
║ Persistence      ║ until disconnect║ ONE-SHOT         ║ per request      ║
║ Replay           ║ start_revision ║ none (re-read)    ║ index parameter  ║
║ Prefix watch     ║ native range   ║ getChildren       ║ ?recurse         ║
║ Event ordering   ║ global revision║ per-znode order   ║ per-key index    ║
║ Server memory    ║ ~2KB/watcher   ║ ~1KB/watcher      ║ minimal (stateless)║
║ Catch-up         ║ revision replay║ full re-read      ║ index compare    ║
║ Compaction risk  ║ YES (mvcc)     ║ NO (watch fires   ║ NO               ║
║                  ║                ║  on deletion only)║                  ║
║ Best for         ║ K8s, precise   ║ Kafka, legacy     ║ DNS discovery,   ║
║                  ║ event ordering ║ Hadoop            ║ health checks    ║
╚══════════════════╩════════════════╩═══════════════════╩══════════════════╝
```

### B.6 — Watch Storm Mechanics

```
WATCH STORM ANATOMY:

  Scenario: 50 Kubernetes controllers, each watching "/" prefix

  1 Pod created:
    → apiserver writes to etcd: /registry/pods/default/my-pod
    → etcd fires watch event to ALL watchers matching prefix
    → 50 apiservers × N watchers each = thousands of events
    → Each event includes full Pod JSON (5-50 KB)

  1000 Pods/minute during scale-up:
    → 1000 × 50 watchers × 10KB = 500 MB/sec event traffic
    → etcd network egress saturates
    → apiserver watch cache falls behind
    → controllers see stale state, retry LIST (more load)

MITIGATION LAYERS:

  Layer 1 — Client scope:
    Watch /registry/pods/default/ not /
    Use label selectors (field indexes in etcd)

  Layer 2 — Apiserver watch cache:
    Apiserver maintains in-memory cache per resource type
    Serves watches from cache, not direct etcd for most resources

  Layer 3 — etcd quota and compaction:
    Auto-compaction prevents unbounded revision history
    Defrag reclaims disk space (does not reduce watch load)

  Layer 4 — Rate limiting:
    --max-requests-inflight on apiserver
    etcd --max-txn-ops, client rate limits

  Layer 5 — Architecture:
    Separate etcd cluster for events vs main (advanced)
    etcd watch proxy (experimental, not production default)
```

---

## C. Raft Write Path Walkthrough (Week 4 Connection)

This section traces a single config write through etcd's Raft implementation at the message level. Read alongside `Week-04-Replication-Partitioning-Consensus/Consensus Raft.md`.

### C.1 — Cluster State Before Write

```
3-NODE ETCD CLUSTER (steady state):

  Node         Role       Term   Commit Index   Applied Index   Leader ID
  ────────────────────────────────────────────────────────────────────────
  etcd-1       Leader     7      10,452         10,452          1
  etcd-2       Follower   7      10,452         10,452          1
  etcd-3       Follower   7      10,452         10,452          1

  Leader lease: valid (heartbeat within election timeout)
  Client connections: 847 active watch streams, 23 write clients
```

### C.2 — Client Submits PUT Request

```
CLIENT → ETCD-1 (leader):

  gRPC: KV.PutRequest
    key:   /config/payment/timeout_ms
    value: 5000
    lease: 0 (persistent key)

ETCD-1 LEADER PROCESSING:

  1. Validate request (RBAC, key size, value size < 1.5MB)
  2. Propose to Raft: Entry{Term:7, Index:10453, Data: PutBlob}
  3. Append to local WAL (Write Ahead Log) on disk
  4. Entry now UNCOMMITTED in leader's log

  TIMING: WAL fsync typically 1-5ms on NVMe, 10-50ms on EBS
```

### C.3 — Raft Log Replication (Message Level)

```
STEP 1: Leader sends AppendEntries RPC to followers

  etcd-1 → etcd-2:
    AppendEntries RPC {
      Term:         7
      LeaderId:     1
      PrevLogIndex: 10452
      PrevLogTerm:  7
      Entries:      [{Term:7, Index:10453, Data:PutBlob}]
      LeaderCommit: 10452
    }

  etcd-1 → etcd-3:
    (same AppendEntries RPC)

STEP 2: Followers validate and append

  etcd-2:
    - Check Term: 7 >= my term (7) ✓
    - Check PrevLogIndex/Term: log[10452].term == 7 ✓
    - Append entry at index 10453
    - Write to follower WAL (fsync)
    - Reply: AppendEntries Response {Term:7, Success:true, MatchIndex:10453}

  etcd-3: (same, Success:true, MatchIndex:10453)

STEP 3: Leader receives majority ack

  Leader tracks: index 10453 replicated on 2/3 nodes (self + 1 follower minimum)
  Actually: self + etcd-2 + etcd-3 = 3/3 → majority achieved

STEP 4: Commit and apply

  Leader updates commitIndex = 10453
  Leader sends next heartbeat with LeaderCommit: 10453

  All nodes apply entry 10453 to state machine (mvcc store):
    PUT /config/payment/timeout_ms = 5000
    Global revision: 10,453 → 10,454 (revision increments on apply)

STEP 5: Notify watchers and respond to client

  Leader fires watch events to all matching watch streams
  Leader responds: PutResponse {Header:{Revision:10454}, PrevKv:...}
```

**ASCII Sequence: Full Raft Write Path**

```
  Client        etcd-1 (Leader)    etcd-2 (Follower)   etcd-3 (Follower)
    │                │                    │                    │
    │──Put──────────►│                    │                    │
    │                │──append WAL────────│                    │
    │                │  index=10453       │                    │
    │                │                    │                    │
    │                │──AppendEntries────►│                    │
    │                │  prev=10452,term=7 │                    │
    │                │  entry=10453       │                    │
    │                │                    │──append WAL────────│
    │                │◄──Success──────────│                    │
    │                │                    │                    │
    │                │──AppendEntries─────────────────────────►│
    │                │◄──Success────────────────────────────────│
    │                │                    │                    │
    │                │ commitIndex=10453  │                    │
    │                │──apply mvcc────────│                    │
    │                │──notify watchers───│                    │
    │◄──PutResponse──│                    │                    │
    │  revision=10454│                    │                    │
    │                │──heartbeat────────►│                    │
    │                │  commit=10453      │                    │
    │                │                    │──apply mvcc────────│
    │                │──heartbeat─────────────────────────────►│
    │                │                    │                    │──apply
```

### C.4 — Write During Leader Failure

```
TIMELINE: Leader dies after WAL append, before majority ack

  T+0ms:   Client sends Put to etcd-1 (leader)
  T+2ms:   etcd-1 appends to WAL (index 10453)
  T+3ms:   etcd-1 sends AppendEntries to etcd-2, etcd-3
  T+5ms:   etcd-1 CRASHES (power loss)
  T+5ms:   Only etcd-2 received AppendEntries (not etcd-3)

  UNCOMMITTED ENTRY STATE:
    etcd-1: has 10453 (dead, irrelevant)
    etcd-2: has 10453 (uncommitted, leaderCommit was 10452)
    etcd-3: does NOT have 10453

  ELECTION (T+5ms to T+200ms):
    etcd-2 and etcd-3 detect missed heartbeat
    Election timeout: random 150-300ms
    etcd-2 wins (higher log wins tie-break)
    New term: 8, new leader: etcd-2

  CLIENT RETRY:
    Client gets RPC error (connection refused)
    Client retries Put to etcd-2 (new leader)
    New entry at index 10453 (term 8) — OVERWRITES uncommitted term-7 entry
    This is safe: uncommitted entries from old term are discarded

  WEEK 4 SAFETY RULE:
    "Leader can only commit entries from its own term once it knows
     the entry is stored on a majority." (Raft paper, §5.4.2)
    Term-7 entry 10453 was never committed → correctly lost
```

### C.5 — Linearizable Read Path

```
STRONG READ (linearizable):

  Client → any node: RangeRequest{key:/config/payment/timeout_ms}

  IF follower receives read:
    Option A: Forward to leader (default in etcd)
    Option B: ReadIndex protocol (follower confirms with quorum)

  ReadIndex STEPS (follower serves read):
    1. Follower sends ReadIndex request to leader (or self if leader)
    2. Leader confirms it is still leader (heartbeat quorum)
    3. Leader returns current commit index
    4. Follower waits until appliedIndex >= commitIndex
    5. Follower reads from local mvcc store
    6. Return to client

  WHY: Prevents stale read from follower that hasn't applied latest commit

SERIALIZABLE READ (weaker, faster):

  etcd: serializable=true on RangeRequest
  Reads local state without quorum confirmation
  May return slightly stale data (bounded by replication lag, typically <10ms)
  Acceptable for service discovery, NOT for lock checks
```

### C.6 — Membership Change (Joint Consensus)

```
ADDING 4TH NODE (etcd-4) — DANGER ZONE:

  WRONG (unsafe):
    etcdctl member add etcd-4
    # Now 4 nodes, quorum = 3
    # If 2 nodes partition: each side has 2, NEITHER has quorum
    # Cluster UNAVAILABLE until manual intervention

  RIGHT (joint consensus, etcd handles automatically):
    1. Leader proposes ConfChange: add etcd-4
    2. Joint consensus phase: quorum requires majority of OLD and NEW
       Old: 3 nodes, need 2
       New: 4 nodes, need 3
       Combined: need BOTH → effectively need 3 of old 3 AND 3 of new 4
    3. Once committed, exit joint state
    4. Normal operation with 4 nodes, quorum = 3

  INTERVIEW TIP:
    "Never run even-numbered etcd clusters. 4 nodes tolerate same
     failures as 3 (1), but cost more and complicate quorum math."
```

---

## D. K8s etcd Overload Incident — Expert Analysis (Q1–Q4)

**Incident context (from Section 9):**

```
P1: Kubernetes API timeouts — etcd cluster degraded

  3-node etcd on m5.large, DB size 7.8 GB (quota 8 GB)
  14:00 Deploy adds 500 ConfigMaps (large JSON blobs)
  14:15 DB size 8.1 GB — etcd rejects writes
  14:18 kube-apiserver 503, new pods fail scheduling
  14:22 Discovery: no compaction/defrag for 90 days
  14:25 50 controllers each watching / — watch fan-out 50K events/sec
```

---

### D.1 — Question 1: Root Cause Chain (150+ lines)

```
EXPERT ANALYSIS: ROOT CAUSE CHAIN

The incident is NOT a single failure. It is a cascading chain where
each weakness amplified the next. Understanding the sequence is
critical for both incident response and interview answers.

═══════════════════════════════════════════════════════════════════════
LINK 1: OPERATIONAL DEBT — COMPACTION AND DEFRAG NEGLECTED
═══════════════════════════════════════════════════════════════════════

etcd uses MVCC (multi-version concurrency control). Every PUT, DELETE,
and lease expiration creates a new revision. Old revisions remain on
disk until compacted.

  Day 0:   Cluster provisioned, --auto-compaction-retention not set
  Day 30:  DB size 2.1 GB, no alerts configured
  Day 60:  DB size 5.4 GB, p99 write latency creeping up (WAL replay)
  Day 90:  DB size 7.8 GB, approaching 8 GB default quota

Without compaction:
  → Every historical version of every key remains in bbolt
  → Range queries scan more data (ConfigMap LIST gets slower)
  → Defrag cannot reclaim space until compact marks pages free
  → WAL replay on restart takes longer (more entries to replay)

ROOT CAUSE CONTRIBUTOR #1: Missing --auto-compaction-retention=1h
                          Missing defrag cron job
                          Missing db_size alert at 70% quota

═══════════════════════════════════════════════════════════════════════
LINK 2: LARGE CONFIGMAP DEPLOY — QUOTA EXCEEDED
═══════════════════════════════════════════════════════════════════════

14:00 Deploy pushes 500 ConfigMaps containing JSON configuration blobs.

  Average ConfigMap size: 800 KB (should be <100 KB)
  Total new data: 500 × 800 KB = 400 MB
  Each update creates NEW revision (old version retained until compact)

  DB size trajectory:
    14:00  7.8 GB (already near quota)
    14:05  8.0 GB (quota reached)
    14:15  8.1 GB (quota EXCEEDED)

When etcd DB exceeds --quota-backend-bytes (default 8 GB):
  → ALL writes rejected with "mvcc: database space exceeded"
  → Reads still work (for a while)
  → Lease keepalives fail (they are writes)
  → New Pod registrations fail
  → Controller status updates fail

ROOT CAUSE CONTRIBUTOR #2: ConfigMaps used as blob storage
                          No admission control on ConfigMap size
                          Deploy batch too large for remaining quota headroom

═══════════════════════════════════════════════════════════════════════
LINK 3: WRITE REJECTION → APISERVER CASCADE
═══════════════════════════════════════════════════════════════════════

kube-apiserver is a stateless front-end to etcd. Every Kubernetes
object is stored in etcd under /registry/...

  Apiserver write path:
    Admission → validation → encode → etcd PUT → respond

  When etcd rejects writes:
    → Pod CREATE fails (cannot persist to etcd)
    → Deployment status update fails
    → Lease renewals for running Pods fail
    → Node heartbeats fail (NodeLease objects)
    → Controllers cannot update status subresources

  Apiserver behavior under etcd stress:
    → Request queue grows (default 400 in-flight)
    → Timeouts increase (default 60s request timeout)
    → Watch connections drop (TCP backpressure)
    → Apiserver returns 503 Service Unavailable

14:18 Observation: "kube-apiserver 503, new pods fail scheduling"
  → Scheduler cannot bind Pods (write failure)
  → Existing Pods may appear healthy but control plane is frozen

ROOT CAUSE CONTRIBUTOR #3: No circuit breaker between apiserver load
                          and etcd capacity; single etcd cluster SPOF

═══════════════════════════════════════════════════════════════════════
LINK 4: WATCH FAN-OUT AMPLIFIES READ LOAD
═══════════════════════════════════════════════════════════════════════

14:25 Discovery: 50 controllers watching "/" prefix.

  Each controller (informer) does:
    1. LIST /registry/... (full state sync) — expensive at 7.8 GB
    2. WATCH /registry/... from resourceVersion — persistent stream

  During incident recovery attempts:
    → Controllers detect watch disconnect
    → Each does full LIST to resync (thundering herd)
    → 50 controllers × LIST all resources = massive read spike
    → etcd serves linearizable reads from bbolt (disk-bound)
    → Read latency spikes → more watch timeouts → more LIST retries

  Watch fan-out calculation:
    50 watchers × 1000 events/minute during churn = 50,000 events/min
    Each event: 5-50 KB serialized object
    Egress: 50K × 10KB / 60s ≈ 8.3 MB/sec sustained

ROOT CAUSE CONTRIBUTOR #4: Unscoped informer watches on "/"
                          No controller watch metrics/alerts
                          Recovery behavior (LIST storm) not rate-limited

═══════════════════════════════════════════════════════════════════════
LINK 5: HARDWARE UNDERSIZED FOR WORKLOAD
═══════════════════════════════════════════════════════════════════════

m5.large specifications:
  2 vCPUs, 8 GB RAM, EBS gp2 (up to 3500 IOPS baseline)

etcd requirements for production Kubernetes:
  → NVMe SSD strongly recommended (not EBS gp2)
  → 8+ vCPUs for large clusters
  → 32+ GB RAM (watch buffers, page cache)
  → Dedicated nodes (no workload colocation)

With 7.8 GB DB on EBS:
  → bbolt random read I/O for range scans
  → WAL fsync latency spikes under I/O contention
  → Raft heartbeat delays → false leader elections

ROOT CAUSE CONTRIBUTOR #5: 3-node m5.large insufficient for cluster size
                          No dedicated etcd nodes

═══════════════════════════════════════════════════════════════════════
COMPLETE CAUSAL CHAIN (diagram)
═══════════════════════════════════════════════════════════════════════

  [90 days no compact/defrag]
           │
           ▼
  [DB grows to 7.8 GB / 8 GB quota]
           │
           ▼
  [500 large ConfigMaps deployed]
           │
           ▼
  [Quota exceeded → ALL writes rejected]
           │
           ├──────────────────────────┐
           ▼                          ▼
  [Apiserver 503]            [Lease renewals fail]
           │                          │
           ▼                          ▼
  [Controllers retry LIST]   [Node/Pod health stale]
           │
           ▼
  [50 unscoped watches amplify read load]
           │
           ▼
  [etcd I/O saturated → reads also slow]
           │
           ▼
  [FULL CONTROL PLANE FAILURE]

═══════════════════════════════════════════════════════════════════════
INTERVIEW DELIVERY (2-minute version)
═══════════════════════════════════════════════════════════════════════

"Root cause is operational debt compounded by a triggering deploy.
 etcd hit its 8 GB quota because compaction wasn't running for 90 days
 and ConfigMaps stored large blobs. Write rejection froze the control
 plane. Recovery attempts made it worse: 50 controllers with unscoped
 watches on / caused LIST storms and 50K events/sec fan-out. Hardware
 was undersized — m5.large with EBS can't serve a 7.8 GB etcd under
 that load."
```

---

### D.2 — Question 2: Immediate Recovery Steps (150+ lines)

```
EXPERT ANALYSIS: IMMEDIATE RECOVERY STEPS

P1 incident response prioritizes: (1) stop the bleeding, (2) restore
writes, (3) verify control plane, (4) avoid data loss. Order matters.

═══════════════════════════════════════════════════════════════════════
PHASE 0: INCIDENT COMMAND (T+0 to T+5 min)
═══════════════════════════════════════════════════════════════════════

  □ Page on-call SRE + platform team
  □ Freeze non-essential deploys (CI/CD pipeline gate)
  □ Open war room bridge
  □ Assign roles: incident commander, etcd operator, k8s operator, comms

  DO NOT:
    ✗ Restart etcd cluster blindly (risk split-brain if quorum confused)
    ✗ Raise quota before defrag (quota increase on full DB = no effect)
    ✗ Delete random objects hoping to free space (may delete critical state)

═══════════════════════════════════════════════════════════════════════
PHASE 1: STOP AMPLIFYING LOAD (T+5 to T+15 min)
═══════════════════════════════════════════════════════════════════════

STEP 1.1: Identify rogue watchers

  # On each apiserver, check etcd metrics:
  etcd_debugging_mvcc_keys_total
  etcd_debugging_mvcc_watch_stream_total

  # Find controllers with broad watches:
  kubectl get pods -n kube-system -o wide
  kubectl logs -n kube-system <controller-manager> --tail=100

  # Check for custom operators watching all resources:
  # Prometheus query:
  #   sum(apiserver_longrunning_requests) by (verb, resource)

STEP 1.2: Stop rogue controllers (if identified)

  # Scale down non-critical operators:
  kubectl scale deployment custom-operator -n operators --replicas=0

  # DO NOT scale down:
  #   - kube-controller-manager
  #   - kube-scheduler
  #   - coredns (unless DNS not needed for recovery)

STEP 1.3: Halt the triggering deploy

  # Rollback ConfigMap deploy:
  kubectl rollout undo deployment/config-loader -n production

  # Delete the 500 oversized ConfigMaps (if safe — verify with app team):
  kubectl delete configmap -l deploy-id=2024-07-06-bad-deploy -n production

═══════════════════════════════════════════════════════════════════════
PHASE 2: ETCD EMERGENCY SURGERY (T+15 to T+45 min)
═══════════════════════════════════════════════════════════════════════

STEP 2.1: Snapshot BEFORE any destructive operation

  # On etcd leader (check with etcdctl endpoint status):
  ETCDCTL_API=3 etcdctl \
    --endpoints=https://etcd-1:2379 \
    --cacert=/etc/kubernetes/pki/etcd/ca.crt \
    --cert=/etc/kubernetes/pki/etcd/server.crt \
    --key=/etc/kubernetes/pki/etcd/server.key \
    snapshot save /backup/etcd-emergency-$(date +%s).db

  # Verify snapshot:
  ETCDCTL_API=3 etcdctl snapshot status /backup/etcd-emergency-*.db -w table

  CRITICAL: Never compact/defrag without snapshot. Defrag is irreversible
  space reclamation; if etcd crashes mid-defrag without snapshot, data loss.

STEP 2.2: Compact old revisions

  # Check current revision and DB size:
  etcdctl endpoint status -w table
  # Example output:
  #   ENDPOINT    ID    VERSION  DB SIZE  IS LEADER  RAFT TERM  RAFT INDEX
  #   etcd-1:2379  xxx  3.5.12   8.1 GB   true       7          2847291

  # Compact all revisions older than 1 hour:
  # (retain enough history for watches to catch up)
  REV=$(etcdctl endpoint status -w json | jq '.[0].Status.header.revision')
  COMPACT_REV=$((REV - 10000))  # retain last 10K revisions
  etcdctl compact $COMPACT_REV

  # Compact runs on leader, replicates via Raft
  # Does NOT immediately free disk space

STEP 2.3: Defrag to reclaim disk space

  # Defrag EACH member (maintenance operation, brief unavailability per node):
  for endpoint in etcd-1:2379 etcd-2:2379 etcd-3:2379; do
    echo "Defragging $endpoint..."
    etcdctl --endpoints=https://$endpoint defrag
  done

  # Defrag on follower first, leader last (minimize leader disruption)
  # Expected: DB size drops from 8.1 GB to ~2-3 GB (depends on live data)

STEP 2.4: Verify writes restored

  etcdctl put /health/check "ok"
  etcdctl get /health/check
  # If successful, writes are restored

STEP 2.5: ONLY NOW — raise quota if needed

  # If defrag insufficient and live data still near quota:
  # Edit etcd manifest: --quota-backend-bytes=17179869184  (16 GB)
  # Restart etcd members ONE AT A TIME (maintain quorum)
  # NEVER raise quota as first action — masks the problem

═══════════════════════════════════════════════════════════════════════
PHASE 3: RESTORE CONTROL PLANE (T+45 to T+90 min)
═══════════════════════════════════════════════════════════════════════

STEP 3.1: Verify apiserver health

  kubectl get --raw /healthz
  kubectl get --raw /readyz
  kubectl get nodes
  # Nodes may show NotReady if lease renewals failed during outage

STEP 3.2: Restart apiservers (if stuck)

  # Apiserver is stateless — safe to restart:
  systemctl restart kube-apiserver
  # Or delete apiserver pods if running as static pods

STEP 3.3: Verify scheduler and controller-manager

  kubectl get pods -n kube-system | grep -E 'scheduler|controller'
  # Check logs for successful etcd reconnection

STEP 3.4: Gradual workload restoration

  # Re-enable operators one at a time:
  kubectl scale deployment custom-operator -n operators --replicas=1
  # Monitor etcd metrics for 10 minutes before scaling further

═══════════════════════════════════════════════════════════════════════
PHASE 4: VERIFY AND MONITOR (T+90 min onward)
═══════════════════════════════════════════════════════════════════════

  □ etcd_db_total_use_bytes < 70% quota
  □ etcd_server_is_leader stable (no flapping)
  □ etcd_disk_wal_fsync_duration_seconds p99 < 10ms
  □ apiserver_request_duration_seconds p99 < 1s
  □ No pods stuck in Pending (scheduler writing)
  □ Node leases renewing (Node objects updating)

═══════════════════════════════════════════════════════════════════════
RECOVERY DECISION TREE
═══════════════════════════════════════════════════════════════════════

  Writes failing?
    │
    ├─ YES → DB over quota?
    │         ├─ YES → snapshot → compact → defrag → verify
    │         └─ NO  → check leader election, disk I/O, network
    │
    └─ NO → Reads slow?
              ├─ YES → stop rogue watches → reduce LIST load
              └─ NO  → control plane healthy, monitor

═══════════════════════════════════════════════════════════════════════
INTERVIEW DELIVERY (2-minute version)
═══════════════════════════════════════════════════════════════════════

"Immediate recovery: freeze deploys, stop rogue controllers watching /,
 snapshot etcd, compact old revisions, defrag all members to reclaim
 space below quota, verify writes, then restart apiservers. Only raise
 quota after defrag if live data still too large. Never defrag without
 snapshot. Bring operators back gradually while watching etcd metrics."
```

---

### D.3 — Question 3: Why Did Watches Make It Worse? (150+ lines)

```
EXPERT ANALYSIS: WATCH AMPLIFICATION DURING INCIDENT

Watches are efficient in steady state. During incidents, they become
an accelerant. This is one of the most underappreciated dynamics in
Kubernetes operations.

═══════════════════════════════════════════════════════════════════════
MECHANISM 1: WATCH DISCONNECT → LIST THUNDERING HERD
═══════════════════════════════════════════════════════════════════════

Normal steady state:
  Controller informer maintains ONE watch stream to apiserver
  Apiserver serves watch from its in-memory cache (not etcd per event)
  Events flow at rate of actual changes (~10-100/minute typical)

During etcd overload:
  1. etcd read latency exceeds watch heartbeat timeout
  2. Apiserver watch connection to etcd drops
  3. Apiserver watch cache becomes stale
  4. Apiserver closes downstream client watch streams
  5. ALL 50 controllers detect disconnect simultaneously
  6. Each controller executes resync():
     a. LIST all resources of watched type (full state)
     b. Re-establish WATCH from returned resourceVersion

  LIST cost per controller:
    50,000 Pods × 5 KB each = 250 MB read from etcd (via apiserver)
    50 controllers × 250 MB = 12.5 GB read burst

  This is a THUNDERING HERD on etcd reads:
    → bbolt must traverse B+ tree for each LIST
    → 7.8 GB database = deep tree, slow scans
    → EBS gp2 throttles IOPS → latency compounds
    → More timeouts → more disconnects → more LISTs

═══════════════════════════════════════════════════════════════════════
MECHANISM 2: UNSCOPED WATCH PREFIX "/"
═══════════════════════════════════════════════════════════════════════

Kubernetes controllers using client-go informers:

  CORRECT (scoped):
    informer.NewFilteredSharedIndexInformer(
      listerWatcher,
      &v1.Pod{},
      resyncPeriod,
      cache.Indexers{},
      func(opts *metav1.ListOptions) {
        opts.FieldSelector = "spec.nodeName=" + nodeName
      },
    )

  INCORRECT (unscoped):
    informer.NewSharedIndexInformer(
      listerWatcher,  // watches ALL pods cluster-wide
      &v1.Pod{},
      resyncPeriod,
      cache.Indexers{},
    )

  50 controllers watching "/" equivalent:
    → ANY etcd change triggers notification to ALL 50
    → ConfigMap change in namespace A notifies payment controller
    → Secret rotation notifies ingress controller
    → Irrelevant events consume network, CPU, deserialization

  Event fan-out math:
    1 ConfigMap CREATE:
      → etcd watch event to 3 apiservers
      → each apiserver notifies N downstream watchers
      → 50 controllers × 3 apiservers = 150 notifications
      → Each deserializes 800 KB ConfigMap payload

═══════════════════════════════════════════════════════════════════════
MECHANISM 3: EVENT PAYLOAD SIZE DURING CHURN
═══════════════════════════════════════════════════════════════════════

Watch events carry FULL OBJECT PAYLOAD (not deltas by default):

  Pod CREATE event:
    {
      "type": "ADDED",
      "object": { ... entire Pod spec + status ... }  // 5-50 KB
    }

  During recovery (many status updates):
    → Kubelet updates Pod status every 10s
    → 5000 Pods × 6 updates/min = 30,000 MODIFY events/min
    → 50 watchers × 30,000 = 1.5M events/min
    → At 10 KB/event = 15 GB/min egress (unsustainable)

  Delta encoding (Kubernetes 1.27+):
    APIServerWatchCache feature gate enables delta watches
    Reduces payload for MODIFY events (only changed fields)
    NOT enabled by default in all clusters

═══════════════════════════════════════════════════════════════════════
MECHANISM 4: ETCD WATCH MEMORY PRESSURE
═══════════════════════════════════════════════════════════════════════

Each etcd watch stream consumes server memory:

  Per-watch overhead: ~1-4 KB (sync buffer, metadata)
  50,000 active watch streams: 50-200 MB
  Plus: event backlog if consumer is slow

  When etcd is under I/O pressure:
    → Slow consumers accumulate event backlog
    → Backlog memory grows unbounded (until timeout)
    → OOM risk on 8 GB m5.large (shared with page cache, bbolt mmap)
    → etcd may kill slow watch streams → triggers more LIST storms

  etcd metric to watch:
    etcd_debugging_mvcc_slow_watcher_total
    → watchers falling behind by >1000 revisions

═══════════════════════════════════════════════════════════════════════
MECHANISM 5: APISERVER WATCH CACHE INVALIDATION
═══════════════════════════════════════════════════════════════════════

Apiserver architecture:

  ┌────────────┐     watch      ┌─────────────┐     watch     ┌──────┐
  │ Controller │◄──────────────│  Apiserver  │◄─────────────│ etcd │
  │ (50x)      │               │ watch cache │               │      │
  └────────────┘               └─────────────┘               └──────┘

  Apiserver watch cache:
    → Caches decoded objects in memory per resource type
    → Serves watches from cache (avoids per-event etcd read)
    → Re-lists from etcd on resync period (default 30 min for informers)

  When etcd writes fail:
    → Cache cannot refresh
    → Cache becomes increasingly stale
    → Controllers make decisions on stale data
    → Incorrect scaling, failed health checks, routing errors

  When etcd reads slow:
    → Cache resync LIST takes longer
    → During resync, watch events may be missed
    → Apiserver forces full relist → more etcd load

═══════════════════════════════════════════════════════════════════════
COMPOUNDING TIMELINE
═══════════════════════════════════════════════════════════════════════

  14:15  etcd write rejection begins
  14:16  apiserver watch to etcd starts failing
  14:17  first wave of controller watch disconnects
  14:17  50 controllers initiate LIST (12.5 GB read burst)
  14:18  etcd read I/O saturated, apiservers return 503
  14:19  second wave of disconnects (from 503 responses)
  14:20  50K events/sec fan-out from status update churn
  14:22  investigation begins (incident detected)
  14:25  rogue "/" watchers identified (but damage done)

  KEY INSIGHT: Watches turned a write failure into a read catastrophe.
  Without watch amplification, etcd might have remained readable while
  operators fixed the quota issue. Instead, both read AND write paths
  collapsed simultaneously.

═══════════════════════════════════════════════════════════════════════
INTERVIEW DELIVERY (2-minute version)
═══════════════════════════════════════════════════════════════════════

"Watches made it worse through three mechanisms. First, disconnect
 thundering herd: 50 controllers all LIST full state simultaneously
 when watches dropped, creating a 12 GB read burst on an already
 struggling etcd. Second, unscoped watches on / meant every ConfigMap
 change fanned out to every controller, 50K events/sec. Third, event
 payloads are full objects not deltas, so 800 KB ConfigMaps multiplied
 across watchers saturated network. The write failure became a read
 catastrophe."
```

---

### D.4 — Question 4: Architecture Changes (150+ lines)

```
EXPERT ANALYSIS: LONG-TERM ARCHITECTURE CHANGES

Immediate recovery restores service. Architecture changes prevent
recurrence. Each change maps to a specific failure mode from the chain.

═══════════════════════════════════════════════════════════════════════
CHANGE 1: ETCD OPERATIONS AUTOMATION
═══════════════════════════════════════════════════════════════════════

IMPLEMENT:

  # etcd static pod manifest flags:
  --auto-compaction-mode=periodic
  --auto-compaction-retention=1h
  --quota-backend-bytes=8589934592   # 8 GB, alert at 70%

  # Defrag cron (weekly, off-peak):
  0 3 * * 0 /opt/etcd-maintenance.sh

  # /opt/etcd-maintenance.sh:
  #!/bin/bash
  ETCDCTL_API=3 etcdctl snapshot save /backup/etcd-$(date +%F).db
  ETCDCTL_API=3 etcdctl compact $(($(etcdctl endpoint status -w json \
    | jq '.[0].Status.header.revision') - 1000))
  for ep in $ENDPOINTS; do
    ETCDCTL_API=3 etcdctl --endpoints=$ep defrag
  done
  ETCDCTL_API=3 etcdctl alarm disarm  # clear NOSPACE if set

ALERTS (Prometheus):

  - alert: EtcdDatabaseHigh
    expr: etcd_mvcc_db_total_use_in_bytes / etcd_server_quota_backend_bytes > 0.7
    for: 5m
    labels: { severity: warning }

  - alert: EtcdDatabaseCritical
    expr: etcd_mvcc_db_total_use_in_bytes / etcd_server_quota_backend_bytes > 0.85
    for: 1m
    labels: { severity: critical }

  - alert: EtcdCompactionFailure
    expr: increase(etcd_debugging_mvcc_db_compaction_keys_total[1h]) == 0
    for: 2h
    labels: { severity: warning }

PREVENTS: Root cause links 1 and 2 (unbounded growth, quota surprise)

═══════════════════════════════════════════════════════════════════════
CHANGE 2: CONFIGMAP ADMISSION CONTROL
═══════════════════════════════════════════════════════════════════════

IMPLEMENT: Validating Admission Webhook

  apiVersion: admissionregistration.k8s.io/v1
  kind: ValidatingWebhookConfiguration
  metadata:
    name: configmap-size-limit
  webhooks:
    - name: configmap-size.k8s.io
      rules:
        - apiGroups: [""]
          apiVersions: ["v1"]
          operations: ["CREATE", "UPDATE"]
          resources: ["configmaps"]
      clientConfig:
        service:
          name: configmap-validator
          namespace: kube-system
      admissionReviewVersions: ["v1"]

  # Webhook logic:
  #   reject if total ConfigMap size > 1 MB
  #   reject if data keys > 100
  #   suggest ExternalSecret or S3 for large payloads

ALTERNATIVE: OPA Gatekeeper policy

  package kubernetes.configmap
  violation[{"msg": msg}] {
    input.review.object.kind == "ConfigMap"
    size := object.size(input.review.object.data)
    size > 1048576  # 1 MB
    msg := sprintf("ConfigMap exceeds 1MB limit: %d bytes", [size])
  }

DATA ARCHITECTURE:

  ┌───────────────────────────────────────────────────────────────┐
  │  SMALL config (<100 KB)  → ConfigMap in etcd (appropriate)    │
  │  MEDIUM config (100KB-1MB) → ConfigMap + compression          │
  │  LARGE config (>1 MB)    → S3/GCS + ConfigMap holds URI only  │
  │  SECRETS                 → External Secrets Operator + Vault  │
  └───────────────────────────────────────────────────────────────┘

PREVENTS: Root cause link 2 (blob storage in etcd)

═══════════════════════════════════════════════════════════════════════
CHANGE 3: ETCD CLUSTER RIGHT-SIZING
═══════════════════════════════════════════════════════════════════════

RECOMMENDED PRODUCTION TOPOLOGY:

  ┌─────────────────────────────────────────────────────────────┐
  │  5-node etcd cluster (tolerate 2 failures, not 1)           │
  │  Dedicated nodes: m5.2xlarge or r5.xlarge                   │
  │  Storage: NVMe instance store (i3.large) or io2 EBS 10K IOPS│
  │  Network: same AZ for quorum latency, spread for AZ failure │
  │  NO workload pods on etcd nodes (taints + tolerations)      │
  └─────────────────────────────────────────────────────────────┘

  Node count decision:
    3 nodes: tolerate 1 failure (minimum production)
    5 nodes: tolerate 2 failures (recommended >500 nodes)
    7 nodes: tolerate 3 failures (very large clusters only)
    4 or 6: NEVER (no additional tolerance vs n-1)

HARDWARE BENCHMARK (etcd check perf):

  etcdctl check perf
  # PASS criteria for production:
  #   PUT/txn 10K seq:  < 50ms p99
  #   RANGE 10K seq:    < 50ms p99
  #   WAL fsync:        < 10ms p99

PREVENTS: Root cause link 5 (undersized hardware)

═══════════════════════════════════════════════════════════════════════
CHANGE 4: CONTROLLER WATCH GOVERNANCE
═══════════════════════════════════════════════════════════════════════

IMPLEMENT:

  1. Audit all in-cluster operators for watch scope:
     # List all watches on etcd (via etcd metrics):
     etcd_debugging_mvcc_watch_stream_total

  2. Enforce scoped informers in operator SDK:
     // WRONG: watches all namespaces
     mgr.GetCache().GetInformer(&corev1.ConfigMap{})

     // RIGHT: watches own namespace only
     mgr.GetCache().GetInformerForKind(
       schema.GroupVersionKind{Group: "", Version: "v1", Kind: "ConfigMap"},
       cache.ByObject{
         Namespaces: map[string]cache.Config{
           operatorNamespace: {},
         },
       },
     )

  3. Rate-limit resync on watch reconnect:
     client-go supports custom resync period
     Add jitter: resyncPeriod + random(0, 30s) to desync controllers

  4. Apiserver request limits:
     --max-requests-inflight=800
     --max-mutating-requests-inflight=400
     --watch-cache-sizes=pods:10000,configmaps:5000

  5. Enable APIServerWatchCache feature gate (delta encoding)

PREVENTS: Root cause link 4 (watch fan-out, LIST storms)

═══════════════════════════════════════════════════════════════════════
CHANGE 5: ETCD MONITORING DASHBOARD
═══════════════════════════════════════════════════════════════════════

GRAFANA DASHBOARD PANELS:

  ┌───────────────────────────────────────────────────────────────┐
  │  Panel 1: DB Size vs Quota (gauge, alert at 70%)              │
  │  Panel 2: Leader Changes (rate, alert on flapping)            │
  │  Panel 3: WAL Fsync Duration (heatmap)                        │
  │  Panel 4: Active Watch Streams (count)                        │
  │  Panel 5: Slow Watchers (count, alert > 10)                   │
  │  Panel 6: Proposal Failed Rate (alert > 0)                    │
  │  Panel 7: gRPC Receive/Send Bytes (detect fan-out)            │
  │  Panel 8: Apiserver Request Duration by Verb (LIST vs WATCH)  │
  └───────────────────────────────────────────────────────────────┘

PREVENTS: Late detection (90 days without noticing growth)

═══════════════════════════════════════════════════════════════════════
CHANGE 6: DISASTER RECOVERY RUNBOOK
═══════════════════════════════════════════════════════════════════════

  Document and test quarterly:

  1. Snapshot restore to fresh cluster (RTO target: 30 min)
  2. Member replacement (remove dead node, add new)
  3. Full cluster rebuild from snapshot
  4. Apiserver failover (multi-master setup)
  5. Control plane bootstrap without workload disruption

  Runbook stored in: docs/runbooks/etcd-recovery.md
  Tested in: staging cluster monthly, production quarterly

═══════════════════════════════════════════════════════════════════════
ARCHITECTURE SUMMARY DIAGRAM
═══════════════════════════════════════════════════════════════════════

  BEFORE (fragile):
  ┌──────────┐  broad watches  ┌───────────┐  7.8GB  ┌─────────────┐
  │ 50 ctrlrs│────────────────►│ apiserver │────────►│ etcd (3 node│
  │ watch /  │                 │ (single)  │         │ m5.large)   │
  └──────────┘                 └───────────┘         └─────────────┘
                                 no admission          no compact
                                 control               90 days

  AFTER (resilient):
  ┌──────────┐  scoped watches ┌───────────┐         ┌─────────────┐
  │ operators│────────────────►│ apiserver │────────►│ etcd (5 node│
  │ (scoped) │  + delta watch  │ (HA x3)   │         │ r5.xlarge)  │
  └──────────┘                 └─────┬─────┘         │ NVMe + auto │
                                     │               │ compact/defrag│
                              ┌──────▼──────┐        └─────────────┘
                              │ admission   │              │
                              │ webhook     │         ┌──────▼──────┐
                              │ (size limit)│         │ Prometheus  │
                              └─────────────┘         │ + alerts    │
                                                      └─────────────┘

═══════════════════════════════════════════════════════════════════════
INTERVIEW DELIVERY (2-minute version)
═══════════════════════════════════════════════════════════════════════

"Long-term: automate compaction hourly and defrag weekly with alerts
 at 70% quota. Admission webhook rejects ConfigMaps over 1 MB — large
 config goes to S3. Right-size to 5 dedicated NVMe nodes. Audit operator
 watches to enforce scoped informers, enable delta encoding. Build Grafana
 dashboard for DB size, slow watchers, and proposal failures. Quarterly
 DR drill for snapshot restore."
```

---

## E. Fifteen Unique Practice Problems

Each problem tests a distinct concept. Work through without looking at answers first.

### Problem 1: Quorum Arithmetic (3-Node Cluster)

```
Given: 3-node etcd cluster, 1 node fails permanently.

Questions:
  a) Can the cluster accept writes? (yes — 2/3 = majority)
  b) Can it tolerate another failure? (no — 1/3 is not majority)
  c) Should you add a 4th node now? (no — 4 nodes tolerate only 1,
     same as 3; add 5th for 2-failure tolerance)

Answer:
  Quorum = floor(N/2) + 1. With 2 alive of 3, quorum = 2. Writes OK.
  Adding 4th during incident risks joint-consensus complexity — replace
  dead node with new 3rd member first, then expand to 5 during maintenance.
```

### Problem 2: Quorum Arithmetic (5-Node, 2 Failures)

```
Given: 5-node etcd, 2 nodes in AZ-a lose network (not crashed).

Questions:
  a) Can remaining 3 nodes in AZ-b accept writes?
  b) What happens to nodes in AZ-a?
  c) When AZ-a recovers, is there a split-brain risk?

Answer:
  a) YES — 3/5 = majority. AZ-b partition becomes active cluster.
  b) AZ-a nodes stop accepting writes (minority partition).
  c) NO split-brain — Raft term numbers ensure stale leaders step down.
     AZ-a nodes rejoin as followers, replicate missing log entries.
```

### Problem 3: Watch Revision Catch-Up After Compaction

```
Given:
  - Client last received event at revision 50,000
  - Admin ran: etcdctl compact 48,000
  - Client reconnects with start_revision=50,001

What happens? What should the client do?

Answer:
  Watch succeeds — revision 50,001 > compact boundary 48,000.
  Client receives events from 50,001 onward.

  If client used start_revision=45,000:
    ERROR: mvcc: required revision has been compacted
    Client must: GET prefix (full state) + watch from revision=0 (now)
```

### Problem 4: Lock Expiry vs GC Pause

```
Given:
  - Lock lease TTL: 15 seconds
  - Holder JVM experiences 20-second GC pause
  - Backup holder acquires lock at T+16s

Can both holders write to the database? How do you prevent this?

Answer:
  YES, without fencing — both believe they hold the lock.
  GC pause exceeded TTL; backup acquired legitimately.
  Old holder wakes up, still thinks it owns lock.

  Prevention: fencing token (monotonic, stored with lock).
  Database rejects writes with token < highest_seen_token.
  Old holder's token is stale → write rejected.
```

### Problem 5: etcd vs Consul for Service Discovery

```
Requirements:
  - 10,000 microservices register health status
  - DNS-based discovery for legacy clients
  - Health check every 10 seconds
  - Multi-datacenter

Which system? Justify.

Answer:
  Consul. Native DNS interface (SRV records), integrated health
  checks (HTTP/TCP/script), local agent cache reduces server load,
  WAN gossip for cross-DC (with caveats). etcd lacks native health
  checks and DNS — you'd build a layer on top (like K8s does).
```

### Problem 6: Serializable vs Linearizable Read

```
Scenario: Follower etcd serves serializable read for lock check.

  T+0:  Leader commits lock DELETE (holder crashed)
  T+1:  Follower serves serializable read → still sees lock (stale)
  T+2:  Client thinks lock held, skips acquisition

What consistency level for lock checks? Why?

Answer:
  Linearizable reads required for lock checks.
  Serializable read may return pre-commit state on follower.
  Use quorum read or leader-forwarded read.
  Cost: +1-5ms latency. Worth it for correctness.
```

### Problem 7: ConfigMap Size Limit Design

```
Design admission control for ConfigMap size in a 50-team org.

Answer:
  Validating webhook: reject >1 MB, warn >256 KB.
  Policy-as-code (OPA): per-namespace quotas on total ConfigMap bytes.
  CI lint: kubeconform + custom rule in PR checks.
  Architecture doc: large config → S3 + ExternalName reference.
  Metrics: configmap_size_bytes histogram per namespace.
  Alert: namespace approaching 10% of etcd quota.
```

### Problem 8: ZooKeeper Session Timeout Tuning

```
ZK session timeout: 30 seconds.
Network blip: 25 seconds (all clients disconnected).

What happens to ephemeral nodes? What about watches?

Answer:
  Session NOT expired (25s < 30s). Ephemeral nodes remain.
  Watches are INVALIDATED on disconnect — must re-register.
  On reconnect within timeout: session restored, ephemerals kept.
  If blip was 35s: session expired, all ephemerals deleted,
  all locks released, all service registrations removed.
  Tune: too short = flapping; too long = slow failure detection.
```

### Problem 9: Raft Log Divergence

```
3-node cluster. Leader (term 5) appends entry index 100.
Leader crashes before replicating. New leader (term 6) elected.

What happens to index 100 term 5 entry?

Answer:
  Discarded. New leader's first action: find highest committed entry,
  overwrite uncommitted entries from prior terms with no-op or new entries.
  Client must retry — received no commit confirmation.
  This is Raft safety: only committed entries survive.
```

### Problem 10: Watch Storm Capacity Planning

```
Cluster: 5000 Pods, 200 controllers, avg Pod event 8 KB.
Pod churn: 100 creates + 100 deletes per minute during deploy.

Calculate sustained watch egress from etcd via apiservers.

Answer:
  Events/min: 200 changes × 200 controllers (if unscoped) = 40,000
  But apiserver watch cache deduplicates — each change = 1 etcd event,
  N apiserver fan-out to controllers.

  Realistic: 200 events/min × 200 controllers = 40,000 events/min
  Egress: 40,000 × 8 KB / 60 = 5.3 MB/sec

  With scoped watches (10 relevant controllers):
  200 × 10 × 8 KB / 60 = 267 KB/sec (20× reduction)
```

### Problem 11: Lease Grant vs Keep-Alive Timing

```
Lease TTL: 30 seconds. App calls keep-alive every 10 seconds.
App bug: keep-alive loop blocks for 45 seconds (deadlock).

Timeline of key deletion?

Answer:
  T+0:   lease granted, key created
  T+10:  keep-alive succeeds (TTL reset to 30s from now)
  T+20:  keep-alive succeeds (TTL reset)
  T+30:  keep-alive BLOCKED (deadlock begins)
  T+50:  no keep-alive for 30s → lease expires → key deleted
  T+45:  deadlock resolves, keep-alive attempt fails (lease gone)

  Production: use lease.keepalive_once() in dedicated thread,
  monitor keep-alive failures as CRITICAL alert.
```

### Problem 12: Joint Consensus Member Addition

```
4-node cluster (A, B, C, D). Add node E during peak traffic.

Describe the joint consensus phases and write availability.

Answer:
  Phase 1 (joint): quorum needs majority of {A,B,C,D} AND {A,B,C,D,E}
    Old majority: 3 of 4. New majority: 3 of 5. Combined: need both.
    Effectively need 3 old + 3 new = high bar, but always satisfiable
    if old cluster is healthy.
  Phase 2 (normal): 5-node cluster, quorum = 3.
  Write availability: maintained throughout if old cluster healthy.
  Risk: adding during incident when only 2 of 4 alive — DON'T add members.
```

### Problem 13: Consul Split-Brain in WAN Federation

```
Consul: 2 DCs federated. WAN partition between DCs.

Can each DC elect its own Raft leader? Impact on KV consistency?

Answer:
  YES — each DC has independent Raft cluster. WAN partition means:
    - Within-DC consistency: maintained (Raft quorum in each DC)
    - Cross-DC KV: stale reads possible (replication lag)
    - Cross-DC locks: DANGEROUS — use coordinated locking (single DC)
  For global config: use single authoritative DC or external store.
  Consul Connect mesh also partitions (intentional — avoid cross-DC deps).
```

### Problem 14: Defrag vs Compact Ordering

```
Operator runs defrag BEFORE compact on 8 GB etcd. Effective?

Answer:
  INEFFECTIVE for space reclamation. Defrag reclaims pages marked free
  by compaction. Without compact first, no pages are marked free.
  Defrag on uncompacted DB: marginal improvement (fragmentation only).
  Correct order: snapshot → compact → defrag → verify size.
```

### Problem 15: Kubernetes ResourceVersion in Optimistic Concurrency

```
User A reads Deployment at resourceVersion=10042.
User B patches Deployment (resourceVersion becomes 10043).
User A patches with resourceVersion=10042.

What happens? How does this relate to etcd CAS?

Answer:
  Apiserver rejects A's patch: 409 Conflict.
  "the object has been modified; please apply your changes to the
   latest version and try again"
  Internally: etcd txn compare mod_revision=10042 → fails (now 10043).
  This IS etcd CAS exposed through Kubernetes API.
  Client must retry: read latest, merge changes, patch again.
```

---

## F. Distributed Lock Service — Full Interview Script

Use this 15-minute script for "Design a distributed lock service" interviews.

### F.1 — Clarifying Questions (2 minutes)

```
SAY:
  "Before I design, let me clarify scope and constraints."

ASK:
  1. "What resources are we protecting? Database writes, cron jobs,
      file storage, or all of the above?"
  2. "How many lock contenders? Hundreds or millions?"
  3. "What's the maximum hold time? Seconds, minutes, hours?"
  4. "Can we tolerate brief dual-holder if holder crashes? Or must
      mutual exclusion be strict even across failures?"
  5. "Do we need reentrant locks (same client acquires twice)?"
  6. "Read-heavy or write-heavy? (Usually very write-sparse for locks)"

TYPICAL ANSWERS → DESIGN INPUT:
  - DB migration lock, 5 contenders, hold 30 min, strict exclusion
  - → etcd with lease, fencing token, linearizable reads
```

### F.2 — High-Level Design (3 minutes)

```
DRAW ON WHITEBOARD:

  ┌──────────┐   acquire/release   ┌─────────────────┐
  │  App     │────────────────────►│  Lock Service   │
  │  (N)     │◄────────────────────│  (etcd/Consul)  │
  └────┬─────┘   grant/deny + token └────────┬────────┘
       │                                      │
       │  write with fencing token            │ Raft replicated
       ▼                                      ▼
  ┌──────────┐                       ┌─────────────────┐
  │ Database │                       │ 3-5 node cluster│
  │          │                       │ (CP, quorum)    │
  └──────────┘                       └─────────────────┘

SAY:
  "Lock service is a CP system built on Raft consensus. Clients acquire
   locks via atomic create-if-not-exists with a lease TTL. The storage
   layer stores a monotonic fencing token. Protected resources reject
   operations with stale tokens."

KEY NAMESPACE:
  /locks/{resource_name} → {holder_id, fencing_token, acquired_at}
  Lease-bound: auto-deleted on holder crash (after TTL)
```

### F.3 — Acquire Flow (3 minutes)

```
SAY:
  "Acquire is a single atomic transaction."

ETCD IMPLEMENTATION:

  1. Create lease with TTL (e.g., 30 seconds)
  2. Start keep-alive goroutine (renew every TTL/3)
  3. Txn:
       IF create_revision("/locks/db-migration") == 0
       THEN put("/locks/db-migration", holder_id) with lease
       ELSE get("/locks/db-migration")
  4. IF success: fencing_token = mod_revision of the key
  5. Return {acquired: true, token: fencing_token, lease: lease_id}
  6. IF failure: another holder exists, return {acquired: false}

CONSUL IMPLEMENTATION:

  consul lock -ttl=30s locks/db-migration
  # Uses session + KV pair under .lock/ prefix
  # Session invalidated if health check fails

INTERVIEW EMPHASIS:
  "Create-if-not-exists is atomic because Raft serializes all writes.
   Two simultaneous acquires: one wins, one gets existing holder info.
   No race condition at the consensus layer."
```

### F.4 — Release and Fencing (3 minutes)

```
RELEASE:
  1. Delete /locks/db-migration (or revoke lease)
  2. Stop keep-alive goroutine
  3. Protected resource operations MUST include fencing_token

FENCING TOKEN ENFORCEMENT (at database):

  CREATE TABLE writes (
    id SERIAL PRIMARY KEY,
    data TEXT,
    fencing_token BIGINT
  );

  -- Application logic:
  current_max = SELECT MAX(fencing_token) FROM writes;
  IF new_token < current_max:
    REJECT  -- stale writer from old lock holder
  ELSE:
    INSERT ...

WHY FENCING IS NON-NEGOTIABLE:

  Timeline without fencing:
    T+0:  Holder A acquires lock
    T+5:  A pauses (GC, network)
    T+35: Lock expires, Holder B acquires
    T+36: B writes to DB
    T+40: A resumes, writes to DB (STALE — no lock held)
    → Data corruption

  Timeline with fencing:
    T+36: B writes with token=105
    T+40: A writes with token=103 → REJECTED (103 < 105)
    → Safe
```

### F.5 — Failure Modes and Tradeoffs (4 minutes)

```
COVER:

  1. Holder crash:
     → Lease expires → lock auto-released
     → Detection time = TTL (tradeoff: short TTL = flapping risk)

  2. Clock skew:
     → etcd leases use server clock, not client
     → Client clock irrelevant (advantage over Redis Redlock)

  3. Network partition:
     → Minority partition cannot acquire (no quorum)
     → Lock holder in majority continues
     → Minority holders blocked (correct for CP)

  4. etcd unavailable:
     → No new acquires, existing holders keep lease via keep-alive
     → If etcd down > TTL: all leases expire, all locks released
     → Design: TTL long enough to survive brief outages

  5. Redlock controversy (Martin Kleppmann):
     → Redis Redlock lacks fencing, clock dependency
     → etcd/Consul/ZK with fencing tokens address the critique
     → Interview: acknowledge debate, explain your fencing approach

TRADEOFFS TABLE:

  ┌─────────────────┬──────────────┬──────────────────────────────┐
  │ Approach        │ Latency      │ Safety                       │
  ├─────────────────┼──────────────┼──────────────────────────────┤
  │ DB advisory lock│ ~1ms         │ Single DB SPOF               │
  │ Redis Redlock   │ ~2ms         │ Fencing gap, clock skew      │
  │ etcd lease+txn  │ ~10ms        │ Strong (with fencing token)  │
  │ ZK ephemeral    │ ~5ms         │ Strong (with fencing token)  │
  │ Consul session  │ ~15ms        │ Strong (with health checks)  │
  └─────────────────┴──────────────┴──────────────────────────────┘
```

---

## G. Mock Interview Snippets

Short exchanges for practice. Read interviewer line, respond aloud, then check model answer.

### G.1 — "Why not use Redis for config storage?"

```
INTERVIEWER: "Why not just store config in Redis? We already run it."

MODEL ANSWER:
  "Redis is optimized as an AP in-memory cache. For configuration and
   coordination, we need CP semantics: linearizable writes so all nodes
   see the same config simultaneously, and consensus-backed leader election.
   Redis Cluster loses writes during network partitions (last-writer-wins).
   For a feature flag or database primary election, that inconsistency
   causes split-brain behavior. etcd gives us Raft-backed linearizability
   at the cost of ~10ms write latency — acceptable for config QPS.
   Redis remains great for session cache and rate limiting."
```

### G.2 — "How does Kubernetes use etcd?"

```
INTERVIEWER: "Walk me through how Kubernetes stores a Pod creation."

MODEL ANSWER:
  "kubectl sends Pod spec to kube-apiserver. Apiserver validates,
   runs admission controllers, then encodes the Pod as JSON and writes
   to etcd at /registry/pods/{namespace}/{name} via gRPC Put. etcd
   leader appends to Raft log, replicates to followers, commits on
   majority, applies to mvcc store. Apiserver receives confirmation
   with resourceVersion (etcd mod_revision). Scheduler watches Pod
   CREATE events via apiserver watch cache, assigns node, patches Pod
   status — another etcd write. Kubelet watches its node's Pods, pulls
   container images, starts containers."
```

### G.3 — "What happens when etcd loses quorum?"

```
INTERVIEWER: "Two of three etcd nodes die. What happens to the cluster?"

MODEL ANSWER:
  "The remaining node is a minority — cannot achieve quorum (need 2 of 3).
   It stops accepting writes immediately. Reads may work briefly on the
   survivor but Kubernetes apiservers will fail writes and eventually
   reads. The control plane is effectively frozen: no new Pods, no
   status updates, no ConfigMap changes. Running workloads continue
   on nodes — data plane is independent. Recovery: restore from snapshot
   to a new 3-node cluster, or replace dead members if data intact.
   Prevention: 5-node cluster tolerates 2 failures."
```

### G.4 — "Design service discovery with health checks"

```
INTERVIEWER: "Design service discovery for 5000 microservices with
health checks and DNS interface."

MODEL ANSWER:
  "I'd use Consul. Each service host runs a Consul agent. On startup,
   service registers via agent API with HTTP health check every 10s.
   Agent forwards health status to Consul servers via Raft. DNS
   interface: dig @consul-agent payment.service.consul returns SRV
   records for healthy instances only. For HTTP clients, use agent
   local caching — blocking queries against local agent, not server.
   Cross-AZ: replicate within DC via Raft, federate across DCs for
   discovery (accept eventual consistency cross-DC). Namespace via
   Consul datacenters or ACL-separated key prefixes."
```

### G.5 — "Explain watch vs poll for config reload"

```
INTERVIEWER: "Your app needs to reload config when it changes.
Watch or poll every 5 seconds?"

MODEL ANSWER:
  "Watch, with local cache. Polling 10,000 instances every 5 seconds
   is 2,000 QPS on the config store for changes that happen once per
   hour. Watch gives zero load in steady state and instant notification
   on change. Implementation: on startup, GET current config + start watch
   from that revision. On event, update local cache and reload. Handle
   disconnect: replay from last_revision, fall back to full GET if
   compacted. Add debounce: coalesce rapid changes within 500ms window
   to avoid reload storms during bulk updates."
```

### G.6 — "Compare etcd watches to Kafka consumers"

```
INTERVIEWER: "etcd watches feel like Kafka consumer groups. Compare them."

MODEL ANSWER:
  "Similar notification pattern, different guarantees. Kafka: ordered
   log per partition, consumers track offset, replay from any offset,
   retention policy (7 days). etcd: ordered global revision, watches
   are push streams not pull, compaction deletes history (no replay past
   compact boundary), no consumer groups — each watcher gets all events.
   Kafka is for event sourcing and stream processing at high throughput.
   etcd watches are for cache invalidation and coordination at low
   throughput with strong consistency. Don't use etcd as a message queue."
```

### G.7 — "How would you migrate from ZooKeeper to etcd?"

```
INTERVIEWER: "We're on ZooKeeper for service discovery. Migrate to etcd?"

MODEL ANSWER:
  "Phased migration with dual-write period. Phase 1: deploy etcd alongside
   ZK, no consumers yet. Phase 2: bridge service writes registrations to
   both ZK and etcd (dual-write). Phase 3: migrate consumers to etcd
   watches one service at a time — validate health check parity. Phase 4:
   read traffic 100% on etcd, ZK becomes fallback. Phase 5: decommission
   ZK. Key differences to handle: ZK one-shot watches → etcd persistent
   streams (simpler), ZK ephemeral sequential → etcd lease keys, ZK ACLs
   → etcd RBAC. Test lease TTL behavior differences — ZK session timeout
   vs etcd lease TTL semantics differ during network blips."
```

### G.8 — "What's an etcd learner node?"

```
INTERVIEWER: "When would you add an etcd learner?"

MODEL ANSWER:
  "Learner nodes receive Raft replication but don't vote in elections
   or count toward quorum. Use case: add a new member without disrupting
   quorum — learner catches up on log first, then promote to voting member
   once replication lag is near zero. Prevents the classic mistake of
   adding a slow node that drags down cluster performance. Also useful
   for read replicas in geo-distributed setups (etcd 3.4+). Promotion:
   etcdctl member promote <member_id>. Learner cannot become leader."
```

---

## H. Quick Reference Card

```
╔═══════════════════════════════════════════════════════════════════════╗
║ ETCDCTL ESSENTIALS                                                    ║
╠═══════════════════════════════════════════════════════════════════════╣
║ etcdctl put key val              │ Write                              ║
║ etcdctl get key --prefix         │ Range read                         ║
║ etcdctl watch key --prefix       │ Persistent watch                   ║
║ etcdctl watch key --rev=N        │ Catch-up from revision N           ║
║ etcdctl txn --compare ...        │ Atomic compare-and-swap            ║
║ etcdctl lease grant 30           │ Create 30s lease                   ║
║ etcdctl lease keep-alive ID      │ Renew lease                        ║
║ etcdctl lock /locks/name         │ Distributed lock                   ║
║ etcdctl compact REV              │ Drop history before REV            ║
║ etcdctl defrag                   │ Reclaim disk space                 ║
║ etcdctl snapshot save file.db    │ Backup                             ║
║ etcdctl endpoint status -w table │ DB size, leader, index             ║
╠═══════════════════════════════════════════════════════════════════════╣
║ CONSUL ESSENTIALS                                                     ║
╠═══════════════════════════════════════════════════════════════════════╣
║ consul kv put key val            │ Write                              ║
║ consul kv get key                │ Read                               ║
║ curl ...?index=N&wait=30s        │ Blocking query                     ║
║ consul lock locks/name cmd       │ Distributed lock                   ║
║ consul members                   │ Cluster membership                 ║
║ consul operator raft list-peers  │ Raft state                         ║
╠═══════════════════════════════════════════════════════════════════════╣
║ INTERVIEW CHECKLIST                                                   ║
╠═══════════════════════════════════════════════════════════════════════╣
║ □ Draw 3-node Raft before API details                                 ║
║ □ State CP / PACELC: config is PC/EC                                  ║
║ □ Watch semantics: etcd stream vs ZK one-shot vs Consul poll          ║
║ □ Leases for ephemeral keys and locks                                 ║
║ □ Fencing tokens for lock safety                                      ║
║ □ Keep values small (<1 MB), compaction + defrag ops                  ║
║ □ Quorum math: 3 tolerate 1, 5 tolerate 2, never even                 ║
║ □ K8s integration: apiserver → etcd, resourceVersion = mod_revision   ║
╚═══════════════════════════════════════════════════════════════════════╝
```

---

*End of appendix. Approximately 1,450 lines of unique technical content for Week 13 Configuration Store interviews.*

---

### Principal stretch

## Design Gates (mandatory)

Answer these before calling the design complete. Keep responses concise in the
learner notes; compare against the answer key only after attempting the gates.

> Gate template: [`../templates/DESIGN_MODULE_GATES.md`](../templates/DESIGN_MODULE_GATES.md)
> Model responses: [`../answers/Week-13-Infrastructure-Designs/Design Configuration Store Answers.md`](../answers/Week-13-Infrastructure-Designs/Design%20Configuration%20Store%20Answers.md)

### Gate 1 - Authn/z trust boundary

1. Who is authenticated in this design: end user, admin, service, device, worker, tenant, or partner?
2. Where does the first untrusted request cross into your trusted control plane?
3. Which component makes the final authorization decision for each protected object or action?
4. What identity artifact is accepted: session cookie, bearer token, API key, mTLS SPIFFE ID, signed URL, or job identity?
5. What does the system do when the identity provider, policy store, or trust bundle is unavailable?

### Gate 2 - Abuse and misuse

6. Which actor can generate the largest write amplification or fan-out?
7. Which endpoint or background job can be abused while still authenticated?
8. What per-user, per-tenant, per-key, per-IP, per-region, and global quotas are required?
9. What telemetry distinguishes a legitimate flash crowd from abuse or scraping?
10. Which retry policy could amplify a partial outage into a full outage?

### Gate 3 - Multi-tenant isolation, if multi-tenant

11. What is the tenancy model for API, database, cache, queue/topic, search/index, and object storage?
12. Where is tenant context required, and how is it propagated through async jobs and support tools?
13. Which shared resource has reserved capacity or fair-share limits per tenant or tier?
14. How can one tenant be throttled, disabled, migrated, or isolated without affecting others?
15. What test proves a tenant cannot read another tenant's data through cache, search, export, or logs?

### Gate 4 - Unit cost at target scale

16. What is the business unit for cost: request, message, ride, order, document, query, minute, or tenant?
17. At the stated target scale and peak multiplier, what is the rough unit cost?
18. Which line items dominate: compute, storage, replication, egress, NAT, observability, ML inference, third-party APIs, or idle headroom?
19. What cost metric pages before margin, budget, or SLO error budget is breached?
20. What graceful degradation lowers cost without damaging the correctness-critical path?

### Gate 5 - Failure blast radius

21. What is the smallest unit that can fail independently: partition, shard, cell, topic, region, tenant, cache key, model, worker pool, or queue?
22. Which dependencies are shared between critical and non-critical paths?
23. What fails closed, what serves stale, and what can be disabled first?
24. Which runbook action could accidentally widen blast radius?
25. What game day proves the blast radius stays inside the intended boundary?
