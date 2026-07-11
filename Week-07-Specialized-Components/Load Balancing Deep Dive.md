# Week 7, Topic 1: Load Balancing Deep Dive

## Learning Objectives

```
╔════════════════════════════════════════════════════════════════╗
║   AFTER THIS TOPIC, YOU WILL BE ABLE TO:                       ║
╟────────────────────────────────────────────────────────────────╢
║                                                                ║
║   1. Explain what a load balancer does at L4 vs L7,            ║
║      including connection vs request distribution,             ║
║      TLS termination, and why the layer choice matters         ║
║                                                                ║
║   2. Design an AWS load-balancing stack for a real             ║
║      service: Route 53 → Global Accelerator → ALB/NLB →        ║
║      target groups, with correct health checks and             ║
║      connection draining                                       ║
║                                                                ║
║   3. Diagnose production LB incidents: unhealthy               ║
║      targets, asymmetric routing, gRPC L4 black holes,         ║
║      WebSocket stickiness failures, and cross-zone             ║
║      imbalance                                                 ║
║                                                                ║
║   4. Choose ALB vs NLB vs GWLB vs client-side balancing        ║
║      for HTTP/2, gRPC, WebSockets, and stateful services       ║
║                                                                ║
║   5. Connect load-balancing algorithms to consistent           ║
║      hashing (Week 3) and explain when sticky sessions         ║
║      are a liability vs a requirement (Week 1 WebSockets)      ║
║                                                                ║
║   6. Write Terraform and AWS CLI configurations for            ║
║      target groups, health checks, stickiness, and             ║
║      connection draining with production-safe defaults         ║
╚════════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔══════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Load balancer = infinite capacity"               ║
╟──────────────────────────────────────────────────────────────────────╢
║   WRONG. A load balancer is a DISTRIBUTOR, not a multiplier.         ║
║   It cannot create backend capacity. If backends are saturated,      ║
║   the LB forwards requests to saturated servers anyway.              ║
║   LB itself has connection limits, bandwidth caps, and               ║
║   per-target connection ceilings.                                    ║
╠══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "Round-robin always gives even distribution"      ║
╟──────────────────────────────────────────────────────────────────────╢
║   WRONG. Round-robin distributes REQUESTS or CONNECTIONS, not        ║
║   load. One heavy request can saturate a target while others         ║
║   are idle. Long-lived connections (WebSockets, gRPC HTTP/2)         ║
║   pin all traffic to one target. Request cost is never uniform.      ║
╠══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "NLB is always faster than ALB"                   ║
╟──────────────────────────────────────────────────────────────────────╢
║   WRONG. NLB is lower latency at L4 (no HTTP parsing), but           ║
║   ALB provides L7 features you may need: path routing,               ║
║   host-based routing, HTTP/2 termination, WebSocket upgrade,         ║
║   WAF integration, OIDC auth. Choosing NLB for HTTP APIs             ║
║   without understanding gRPC/WebSocket implications causes           ║
║   the L4 black hole (Week 1 tie-in).                                 ║
╠══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "Health check green = target is healthy"          ║
╟──────────────────────────────────────────────────────────────────────╢
║   WRONG. Health checks probe a single endpoint on an interval.       ║
║   A target can pass /health while: database pool exhausted,          ║
║   GC paused, thread pool full, or only 1 of 8 dependencies           ║
║   is down. Health checks measure LIVENESS, not full READINESS.       ║
╠══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Sticky sessions fix stateful apps"               ║
╟──────────────────────────────────────────────────────────────────────╢
║   WRONG. Sticky sessions are a CRUTCH that creates hot spots,        ║
║   complicates deploys, and breaks when targets drain.                ║
║   Prefer externalized state (Redis, DB). Use stickiness only         ║
║   when protocol requires it (WebSockets) or migration cost           ║
║   is prohibitive — and then design for uneven distribution.          ║
╠══════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #6: "Route 53 and the LB do the same job"             ║
╟──────────────────────────────────────────────────────────────────────╢
║   WRONG. Route 53 is DNS — it resolves names to IPs with             ║
║   latency-based or weighted routing. It has NO visibility into       ║
║   backend health at request time (unless using alias + healthy       ║
║   target evaluation). ALB/NLB actively health-checks targets         ║
║   and stops sending traffic to failures. They operate at             ║
║   different layers and timescales.                                   ║
╚══════════════════════════════════════════════════════════════════════╝
```

---

## Core Teaching

### What Is Load Balancing?

```
THE FUNDAMENTAL PROBLEM:

  You have ONE hostname: api.example.com
  You have MANY servers that can answer.

  Without a load balancer:
    → Clients must know all server IPs (impossible at scale)
    → One server dies → clients still try it → errors
    → One server gets all traffic → overload
    → Deploy requires DNS TTL gymnastics

  With a load balancer:
    → Clients connect to ONE stable endpoint (VIP/DNS name)
    → LB distributes traffic across healthy backends
    → Unhealthy backends removed automatically
    → Deploy: drain connections, replace target, repeat

THE LOAD BALANCER'S JOB (four responsibilities):

  1. DISCOVERY — clients find one address, LB knows many backends
  2. DISTRIBUTION — spread traffic by algorithm (RR, LC, CH, etc.)
  3. HEALTH — stop sending to failed/slow targets
  4. TERMINATION — optionally handle TLS, HTTP/2, WebSocket upgrade

TWO LAYERS MATTER:

  L4 (Transport): distributes TCP/UDP connections by IP:port
    → Fast, protocol-agnostic
    → Cannot route by URL path or Host header
    → One TCP connection = one backend (the black hole problem)

  L7 (Application): understands HTTP, gRPC-over-HTTP/2, WebSockets
    → Can route /api → service A, /admin → service B
    → Can distribute individual HTTP/2 streams on one connection
    → Higher latency (parses headers), more features
```

### The Request Path — End to End

```
TYPICAL AWS PRODUCTION STACK:

  User (Mumbai)
      │
      │ DNS query: api.example.com
      ▼
  ┌──────────────────────────────────────────────────────────┐
  │ Route 53                                                 │
  │   Latency-based routing OR weighted OR failover          │
  │   Returns: ALB DNS name (alias) or Global Accelerator IP │
  └──────────────────────────┬───────────────────────────────┘
                             │
                             ▼
  ┌──────────────────────────────────────────────────────────┐
  │ AWS Global Accelerator (optional)                        │
  │   Anycast static IPs → routes to nearest AWS edge        │
  │   Then to regional ALB/NLB/EC2                           │
  │   Use when: global users, static IP allowlisting,        │
  │   fast regional failover                                 │
  └──────────────────────────┬───────────────────────────────┘
                             │
                             ▼
  ┌──────────────────────────────────────────────────────────┐
  │ Application Load Balancer (ALB) or Network Load Balancer │
  │   Terminates TLS, HTTP/2, routes by path/host            │
  │   Target group: ECS tasks / EC2 / Lambda / IP targets    │
  └──────────────────────────┬───────────────────────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
         ┌─────────┐   ┌─────────┐   ┌─────────┐
         │ Task 1  │   │ Task 2  │   │ Task 3  │
         │ :8080   │   │ :8080   │   │ :8080   │
         └─────────┘   └─────────┘   └─────────┘

LATENCY BUDGET (illustrative):

  Route 53 resolution:        5–50 ms (cached: 0 ms)
  Global Accelerator edge:    0–30 ms (if used)
  ALB processing:             1–5 ms
  Backend processing:         10–500 ms
  ─────────────────────────────────────
  LB overhead is usually SMALL vs backend — until it isn't
  (connection exhaustion, TLS handshake storms, cross-AZ charges)
```

### Load Balancing Algorithms

```
ALGORITHM CATALOG:

┌────────────────────┬──────────────────────────────────────────────────┐
│ Algorithm          │ Behavior                                         │
├────────────────────┼──────────────────────────────────────────────────┤
│ Round Robin (RR)   │ Rotate through healthy targets in order          │
│ Weighted RR        │ Targets with higher weight get more slots        │
│ Least Connections  │ Send to target with fewest active conns          │
│ Least Outstanding  │ ALB: fewest in-flight requests (L7)              │
│ Random             │ Pick random healthy target                       │
│ IP Hash            │ hash(client_ip) → fixed target (sticky-ish)      │
│ Consistent Hash    │ hash(key) on ring → minimal remap on change      │
│ Maglev             │ Google variant; fast lookup, even spread         │
└────────────────────┴──────────────────────────────────────────────────┘

ROUND ROBIN — THE DEFAULT (AND ITS TRAP):

  Targets: [A, B, C, D]
  Request 1 → A
  Request 2 → B
  Request 3 → C
  Request 4 → D
  Request 5 → A
  ...

  Works when: stateless HTTP, short requests, uniform cost

  Fails when:
    → Request 1 is a 2GB file download (A saturated for 60s)
    → Requests 2–100 are 1KB API calls (B, C, D idle)
    → gRPC client opens ONE HTTP/2 connection → ALL streams to A

LEAST CONNECTIONS — BETTER FOR LONG-LIVED WORK:

  Track active TCP connections per target.
  New connection → target with minimum count.

  ALB (L7) uses "least outstanding requests" for HTTP routing —
  counts in-flight HTTP requests, not just TCP connections.

  Still imperfect: 10 idle WebSocket conns weigh same as
  10 active API requests unless you use request-based metrics.

CONSISTENT HASHING — WEEK 3 CONNECTION:

  From Week 3 Consistent Hashing: place backends on a hash ring.
  hash(session_id) or hash(client_ip) → walk clockwise to backend.

  WHY USE IT AT THE LB LAYER?

    Cache servers behind LB: same user → same cache node
    Stateful shard routing: user:12345 → always shard owner
    Minimal disruption: add/remove node → only K/N keys move

  AWS IMPLEMENTATION:

    ALB sticky sessions (lb_cookie or app_cookie) ≈ session affinity
    NLB: no built-in consistent hash — use Maglev in Envoy/Nginx
    Route 53 weighted/latency: DNS-level, coarse-grained

  THE RING (conceptual):

                        0 / 2^32
                          │
                    ╭─────┴─────╮
                 ╱                 ╲
               ╱    Target-A        ╲
             ╱       @ 0.15           ╲
            │                           │
   ─────────┤    LB CONSISTENT HASH     ├─────────
   ring     │         RING              │
             ╲       Target-C @ 0.68   ╱
               ╲    Target-B @ 0.42   ╱
                 ╲                 ╱
                    ╰─────┬─────╯
                          │
                    Target-D @ 0.91

  key="user:8842" → hash → 0.55 → clockwise → Target-C

  Target-C dies:
    Only keys in (Target-B, Target-C] remap to Target-D
    ~25% of keys move (with 4 nodes), NOT 75% like hash-mod-N

  VIRTUAL NODES (vnodes):
    Each physical target gets 100–200 positions on ring
    → evens distribution when few physical nodes
    → same math as Week 3 Cassandra/DynamoDB vnode discussion
```

### AWS Load Balancer Types — Deep Dive

#### Application Load Balancer (ALB)

```
ALB = Layer 7 HTTP/HTTPS load balancer

LISTENER EXAMPLE:

  Client ──HTTPS:443──► ALB Listener
                           │
                           ├── Rule: Host=api.example.com AND Path=/v1/*
                           │         → Target Group: api-v1-tg
                           │
                           ├── Rule: Host=api.example.com AND Path=/v2/*
                           │         → Target Group: api-v2-tg
                           │
                           ├── Rule: Path=/health
                           │         → Fixed response 200 OK
                           │
                           └── Default → Target Group: api-default-tg

KEY CAPABILITIES:

  ✓ HTTP/1.1, HTTP/2 termination (client ↔ ALB can be HTTP/2)
  ✓ WebSocket upgrade (Connection: Upgrade)
  ✓ gRPC over HTTP/2 (with correct target group settings)
  ✓ Host-based, path-based, header-based, query-string routing
  ✓ TLS termination (ACM certificates)
  ✓ OIDC authentication at edge
  ✓ AWS WAF integration
  ✓ Lambda targets, ECS, EC2, IP, ALB (chaining)

HTTP/2 TERMINATION — WHAT ACTUALLY HAPPENS:

  WITHOUT termination (NLB pass-through):
    Client ══HTTP/2══ Backend
    One TCP connection end-to-end
    NLB sees opaque bytes

  WITH ALB termination:
    Client ══HTTP/2══ ALB ══HTTP/1.1 or HTTP/2══ Backend

    Client benefits:
      → Multiplexed streams to ALB
      → TLS handled at edge (ACM cert rotation)
      → ALB can distribute streams across backends

    Backend may see:
      → HTTP/1.1 (default for many target types) — one conn per request
      → OR HTTP/2 to backend if target group protocol is HTTPS + HTTP/2

  CONFIGURATION (target group):

    protocol          = HTTPS
    protocol_version  = HTTP2   # backend speaks HTTP/2

  OR for gRPC:

    protocol          = HTTPS
    protocol_version  = GRPC

  IMPORTANT: ALB terminates client TLS. Backend TLS is separate
  (re-encrypt with ACM on targets, or HTTP to targets in VPC).

WEBSOCKET SUPPORT (WEEK 1 TIE-IN):

  From Week 1 WebSockets: upgrade handshake is HTTP/1.1:

    GET /chat HTTP/1.1
    Upgrade: websocket
    Connection: Upgrade

  ALB recognizes Upgrade header → switches to TCP tunnel mode
  for THAT connection. Subsequent frames are opaque to ALB.

  IMPLICATIONS:
    → Connection is STICKY to one target for its lifetime
    → ALB idle timeout applies (default 60s — increase for WS)
    → Deploy: must drain connections or clients disconnect
    → Cannot round-robin WebSocket messages across targets

  ALB SETTINGS FOR WEBSOCKETS:

    idle_timeout = 3600          # 1 hour (max 4000s)
    stickiness     = optional    # upgrade already pins connection
    health_check   = HTTP /health on separate short-lived path

TARGET GROUP (ALB):

  ┌──────────────────────────────────────────────────────────────┐
  │ Target Group: api-prod-tg                                    │
  ├──────────────────────────────────────────────────────────────┤
  │ Target type:     ip (ECS awsvpc) or instance or lambda       │
  │ Protocol:        HTTP or HTTPS                               │
  │ Port:            8080                                        │
  │ VPC:             vpc-0abc123                                 │
  │ Deregistration:  300 seconds (connection draining)           │
  │ Stickiness:      lb_cookie, duration 86400s (if enabled)     │
  │ Health check:    HTTP GET /health, interval 15s,             │
  │                  healthy_threshold 2, unhealthy 3            │
  └──────────────────────────────────────────────────────────────┘
```

#### Network Load Balancer (NLB)

```
NLB = Layer 4 TCP/UDP/TLS load balancer

  Client ──TCP:443──► NLB ──TCP:443──► Target (same port or different)

CHARACTERISTICS:

  ✓ Ultra-low latency (~100μs added)
  ✓ Millions of connections per minute
  ✓ Static IP per AZ (or Elastic IP)
  ✓ Preserves source IP (or uses proxy protocol v2)
  ✓ TLS passthrough OR TLS termination at NLB
  ✓ UDP support (gaming, DNS, VoIP)
  ✓ Cross-zone load balancing (configurable)

  ✗ No path-based routing
  ✗ No HTTP header inspection
  ✗ No WebSocket-aware routing (just TCP flow)
  ✗ No HTTP/2 stream-level distribution

NLB FLOW:

  New TCP SYN arrives at NLB
       │
       ▼
  Algorithm: flow hash (5-tuple) OR round robin (configurable)
       │
       ▼
  Selected target receives ALL packets for that connection

THE gRPC L4 BLACK HOLE (WEEK 1 TIE-IN):

  From Week 1 REST vs GraphQL vs gRPC:

    gRPC uses long-lived HTTP/2 connections.
    Traditional L4 load balancers distribute TCP connections,
    not individual requests.
    If client opens ONE connection to NLB, ALL gRPC calls
    go to the SAME backend server.

  DIAGRAM:

    gRPC Client                    NLB                    Backends
        │                           │                   A   B   C
        │════ 1 TCP conn ══════════►│──────────────────►A
        │    (HTTP/2 multiplex)     │                   │   │   │
        │    1000 RPCs on           │    B and C idle   │   │   │
        │    1 connection           │                   │   │   │
        │                           │                   │   │   │

  SYMPTOMS:
    → 3 targets, but CPU: A=95%, B=10%, C=10%
    → Autoscaling adds targets D, E — no relief on A
    → p99 latency spikes on A, others report healthy

  FIXES (pick one or combine):

    1. ALB with gRPC target group (HTTP/2 stream distribution)
    2. Client-side load balancing (gRPC pick_first / round_robin
       with multiple backend addresses from service discovery)
    3. Envoy/Nginx sidecar with Maglev/consistent hash per RPC
    4. Force connection churn: max_connection_age on server
       (gRPC keepalive + GOAWAY after N minutes)
    5. NLB + many short-lived connections (defeats HTTP/2 benefit)

CROSS-ZONE LOAD BALANCING (NLB):

  Setting: load_balancing.cross_zone.enabled

  DISABLED (default for NLB):
    Client in AZ-a → NLB node in AZ-a → targets in AZ-a only
    Pro: no cross-AZ data transfer charges for LB→target traffic
    Con: uneven if target counts differ per AZ

  ENABLED:
    Client in AZ-a → NLB node in AZ-a → may route to target in AZ-b
    Pro: even distribution across all healthy targets
    Con: cross-AZ data transfer charges ($0.01/GB per direction)

  DECISION:
    Even target distribution per AZ → often leave disabled + equal targets/AZ
    Uneven targets or burst in one AZ → enable cross-zone
```

#### Gateway Load Balancer (GWLB)

```
GWLB = Layer 3 Gateway + Layer 4 flow distribution for APPLIANCES

  NOT for your application servers.
  FOR: firewalls, IDS/IPS, deep packet inspection, NAT appliances.

ARCHITECTURE:

  ┌──────────┐     ┌─────────┐     ┌──────────────┐     ┌──────────┐
  │  App VPC │────►│   GWLBe │────►│     GWLB     │────►│ Firewall │
  │  subnets │     │ (endpoint)│    │  (distributes)│     │ appliance│
  └──────────┘     └─────────┘     └──────────────┘     └──────────┘
                         │                                      │
                         └──────── RETURN PATH (GENEVE tunnel) ──┘

  Traffic flow:
    1. Route table sends traffic to Gateway Load Balancer Endpoint
    2. GWLB distributes flows to registered appliance targets
    3. Appliance inspects/forwards via GENEVE encapsulation
    4. Return traffic symmetric through same appliance (flow stickiness)

USE CASES:
  → Centralized inspection for east-west VPC traffic
  → Third-party NGFW (Palo Alto, Fortinet) on EC2
  → Replacing inline NAT instances with scalable pattern

DIFFERENCE FROM ALB/NLB:
  → Operates at GENEVE tunnel level
  → Flow stickiness mandatory (stateful inspection)
  → Consumer/producer VPC model (AWS Marketplace appliances)
```

#### Route 53 — DNS Load Balancing

```
Route 53 is NOT a load balancer — it is DNS routing.

POLICIES:

┌─────────────────────┬──────────────────────────────────────────────┐
│ Policy              │ Use case                                     │
├─────────────────────┼──────────────────────────────────────────────┤
│ Simple              │ One record → one target                      │
│ Weighted            │ A=70%, B=30% traffic split (coarse)          │
│ Latency-based       │ Return lowest-latency healthy record         │
│ Failover            │ Primary + secondary (health check required)  │
│ Geolocation         │ Route by user country/continent              │
│ Geoproximity        │ Route by geographic proximity + bias         │
│ Multi-value         │ Return multiple healthy IPs (client picks)   │
└─────────────────────┴──────────────────────────────────────────────┘

ALIAS RECORDS TO ALB:

  api.example.com  ALIAS  →  dualstack.api-prod-123.us-east-1.elb.amazonaws.com

  Benefits:
    → No charge for alias queries to AWS resources
    → Automatic evaluation of ALB health (failover policies)
    → Tracks ALB IP changes (ALB IPs are not stable)

HEALTH CHECKS (Route 53):

  HTTP/HTTPS/TCP check to endpoint (can be ALB, EC2, CloudWatch alarm)

  Failure: DNS stops returning that record (for failover/latency policies)

  LIMITATIONS:
    → DNS TTL caching: clients may use stale IP for TTL duration
    → No per-request health — only DNS resolution time
    → Cannot drain connections gracefully

ROUTE 53 vs ALB — WHEN BOTH:

  Route 53: global routing, multi-region failover, latency
  ALB: per-region request distribution, path routing, health at request time

  Pattern:
    Route 53 latency routing → ALB in us-east-1 AND ALB in eu-west-1
    User in Tokyo → ap-northeast-1 ALB (if deployed) or nearest region
```

#### AWS Global Accelerator

```
Global Accelerator = Anycast static IP + AWS global network

  Two static IPs (IPv4) announced from AWS edge locations worldwide.
  Traffic enters nearest edge → rides AWS backbone → regional endpoint.

ENDPOINT GROUPS:

  ┌──────────────────────────────────────────────────────────────┐
  │ Accelerator: 2 static IPs                                    │
  │   Listener: TCP 443, TCP 80                                  │
  │   Endpoint group: us-east-1 (weight 100, traffic dial 100%)  │
  │     Endpoints: ALB api-prod-use1, EC2 i-abc (optional)       │
  │   Endpoint group: eu-west-1 (weight 50, traffic dial 0%)     │
  │     Endpoints: ALB api-prod-euw1                             │
  │   Client affinity: SOURCE_IP (optional)                      │
  └──────────────────────────────────────────────────────────────┘

VS CLOUDFRONT:
  CloudFront: HTTP/S content caching at edge
  Global Accelerator: TCP/UDP proxy, no caching, any protocol

VS ROUTE 53 LATENCY:
  Global Accelerator: traffic enters AWS network at edge (lower jitter)
  Route 53: DNS returns regional IP, client connects directly

USE WHEN:
  → Need static IPs for allowlisting
  → Global users need consistent low latency to ONE entry point
  → Fast regional failover (traffic dial 0→100 in seconds)
  → Non-HTTP protocols (gaming UDP, IoT MQTT over TLS)

CLIENT AFFINITY:
  SOURCE_IP: same client IP → same endpoint (sticky at GA layer)
  NONE: distribute per flow
```

### Target Groups — The Contract Between LB and Backends

```
TARGET GROUP = pool of backends + health check + routing settings

TARGET TYPES:

┌──────────────┬──────────────────────────────────────────────────────┐
│ Type         │ Registration                                         │
├──────────────┼──────────────────────────────────────────────────────┤
│ instance     │ EC2 instance ID + port (nodeport or host port)       │
│ ip           │ Private IP + port (ECS awsvpc, on-prem via DX)       │
│ lambda       │ Lambda ARN (ALB only, request/response transform)    │
│ alb          │ Another ALB (multi-tier)                             │
│ appliance    │ GWLB firewall instances                              │
└──────────────┴──────────────────────────────────────────────────────┘

REGISTRATION FLOW (ECS example):

  1. ECS service launches task in awsvpc mode
  2. Task gets ENI with IP 10.0.1.45
  3. ECS controller registers 10.0.1.45:8080 with target group
  4. Target state: initial → healthy (after health check pass)
  5. ALB sends traffic to 10.0.1.45:8080

DEREGISTRATION (deploy or scale-in):

  1. ECS stops sending new tasks to draining task
  2. Target deregistered: state → draining
  3. Connection draining timer starts (default 300s)
  4. Existing connections complete; no new connections
  5. Timer expires → target removed
  6. Task terminated

HEALTH CHECK ANATOMY:

  ┌──────────────────────────────────────────────────────────────┐
  │ Protocol:        HTTP / HTTPS / TCP / TLS / gRPC             │
  │ Path:            /health (HTTP/HTTPS/gRPC)                   │
  │ Port:            traffic-port OR override (e.g., 8081 admin) │
  │ Interval:        5s (fast) to 300s (slow)                    │
  │ Timeout:         must be < interval                          │
  │ Healthy threshold:   consecutive successes to mark healthy   │
  │ Unhealthy threshold: consecutive failures to mark unhealthy  │
  │ Matcher:         HTTP 200-299 (customize)                    │
  │ Success codes:   gRPC: 0-99 (status codes)                   │
  └──────────────────────────────────────────────────────────────┘

  TIMELINE (defaults: interval 30s, unhealthy threshold 3):

    Target crashes at T=0
    Health check fails at T=0, T=30, T=60
    Marked unhealthy at T=60 (3 failures)
    ALB stops new connections at T=60
    In-flight requests may still fail until draining completes

  AGGRESSIVE (production API):

    interval=5, unhealthy_threshold=2, timeout=2
    → Unhealthy in ~10 seconds
    → Risk: brief GC pause marks target unhealthy (flapping)

  READINESS VS LIVENESS:

    /health/live  → process up (for kubelet/ALB liveness)
    /health/ready → can serve traffic (DB connected, cache warm)

    Point ALB health check at /health/ready with dependencies.
    If only /health/live → zombie targets accept traffic.
```

### Connection Draining (Deregistration Delay)

```
CONNECTION DRAINING = graceful removal of a target

WITHOUT DRAINING:

  Deploy: kill task → all active requests get TCP RST
  Users see: 502 Bad Gateway, checkout failures, WebSocket drops

WITH DRAINING (deregistration_delay = 300s):

  T=0:   Target marked draining, ALB stops NEW connections
  T=0–300: Existing connections complete normally
  T=300: Target removed from pool

SETTINGS:

  ALB target group attribute:
    deregistration_delay.timeout_seconds = 30–3600 (default 300)

  ECS:
    Service deploymentConfiguration:
      minimumHealthyPercent = 100
      maximumPercent = 200
    → Starts new task before killing old (rolling deploy)

  Kubernetes:
    preStop hook: sleep 15 (allow endpoint removal to propagate)
    terminationGracePeriodSeconds: 60

WEBSOCKET DRAINING:

  Draining stops NEW connections, not existing WS frames.
  Existing WebSocket stays on draining target until:
    → Client disconnects
    → Server closes
    → Idle timeout
    → Draining period ends (then RST)

  PRODUCTION PATTERN:
    1. Mark target draining
    2. Server sends WS close frame to clients (app-level)
    3. Clients reconnect → land on healthy targets
    4. Wait for connection count → 0 or timeout
    5. Kill task

  From Week 1: implement client-side exponential backoff reconnect
  to avoid thundering herd on deploy.
```

### Sticky Sessions (Session Affinity)

```
STICKY SESSION = same client → same target for duration

ALB MECHANISMS:

  1. Load balancer cookie (AWSALB / AWSALBAPP)
     ALB inserts cookie on first response
     Subsequent requests with cookie → same target

  2. Application cookie
     App sets cookie (e.g., JSESSIONID)
     ALB reads it and pins to target

  3. Duration: 1 second to 7 days (604800s)

CONFIGURATION:

  stickiness.enabled = true
  stickiness.type = lb_cookie | app_cookie
  stickiness.lb_cookie.duration_seconds = 86400
  stickiness.app_cookie.cookie_name = SESSION

WHEN REQUIRED:
  → In-memory session state (legacy apps)
  → WebSocket (connection inherently sticky)
  → Server-side SSE buffer (long-poll affinity)

WHEN HARMFUL:
  → Even distribution needed
  → Targets heterogeneous (sticky → hot spot on popular users)
  → Deploy: sticky users hit draining target repeatedly

HOT SPOT EXAMPLE:

  10 targets, 10,000 users
  Without stickiness: ~1000 users/target
  With stickiness + power law: 1 influencer user on Target-A
    → Target-A serves 5000 fans' sticky sessions
    → Target-B–J serve 500 each

MITIGATION:
  → Externalize sessions (ElastiCache Redis)
  → Consistent hash on user_id with many vnodes (Week 3)
  → Disable stickiness when state is shared
```

### TLS Termination and Certificate Management

```
TLS TERMINATION OPTIONS:

┌────────────────────┬─────────────────────────────────────────────┐
│ Pattern            │ Flow                                        │
├────────────────────┼─────────────────────────────────────────────┤
│ ALB terminate      │ Client TLS → ALB → HTTP to target (VPC)     │
│ ALB re-encrypt     │ Client TLS → ALB → HTTPS to target          │
│ NLB passthrough    │ Client TLS → NLB → Target (SNI preserved)   │
│ NLB terminate      │ Client TLS → NLB (cert on NLB) → TCP to tgt │
│ End-to-end TLS     │ TLS at every hop (service mesh mTLS)        │
└────────────────────┴─────────────────────────────────────────────┘

ACM INTEGRATION:

  Certificate on ALB listener :443
  Auto-renewal, no manual rotation
  SNI: multiple certs per listener (host-based)

CIPHER CONSIDERATIONS:

  ALB security policy: ELBSecurityPolicy-TLS13-1-2-2021-06
  HTTP/2 requires TLS 1.2+ with ALPN negotiation

PERFORMANCE:

  TLS handshake: 1–2 RTT (TLS 1.3: 1 RTT)
  At 10K new connections/sec → CPU on LB matters
  Mitigation: session resumption, TLS 1.3, connection reuse (HTTP/2)
```

### HTTP/2 and gRPC at the Load Balancer

```
HTTP/2 TERMINATION AT ALB — DETAILED FLOW:

  1. Client opens TLS connection to ALB
  2. ALPN negotiates h2
  3. Client sends HTTP/2 SETTINGS, opens streams
  4. ALB terminates HTTP/2 from client
  5. ALB opens separate connection(s) to backend per routing decision
  6. Each client stream may map to backend request

  BENEFIT: Stream-level distribution across targets
  (solves gRPC black hole for server-side LB)

gRPC TARGET GROUP:

  protocol_version = GRPC
  health check: GRPC health checking protocol (/grpc.health.v1.Health/Check)
  OR HTTP health path if using grpc-health-probe

  Common misconfiguration:
    protocol_version = HTTP2 (not GRPC)
    → Health check passes HTTP but gRPC calls fail with PROTOCOL_ERROR

ENVOY gRPC LOAD BALANCING (alternative):

  Client → Envoy sidecar → multiple upstream gRPC servers
  Policies: ROUND_ROBIN, LEAST_REQUEST, RING_HASH (consistent hash)

  ring_hash on metadata.user_id → Week 3 consistent hashing in mesh
```

### WebSockets and Load Balancers (Week 1 Tie-In)

```
From Week 1 WebSockets: full-duplex persistent connection.

LOAD BALANCER BEHAVIOR BY TYPE:

┌───────────┬────────────────────────────────────────────────────────┐
│ LB        │ WebSocket behavior                                     │
├───────────┼────────────────────────────────────────────────────────┤
│ ALB       │ Native upgrade support; tune idle_timeout              │
│ NLB       │ TCP pass-through; no HTTP awareness; works if upgrade  │
│           │ completes end-to-end                                   │
│ CloudFront│ Supports WebSocket (no caching on upgrade)             │
│ NGINX     │ proxy_read_timeout, proxy_http_version 1.1, Upgrade    │
└───────────┴────────────────────────────────────────────────────────┘

ALB WEBSOCKET SETTINGS:

  idle_timeout: 3600 (default 60 kills idle WS)
  stickiness: not required post-upgrade (connection pinned)

FAILURE MODES (Week 1):
  → LB idle timeout < app heartbeat interval → silent disconnect
  → Deploy without drain → mass reconnect storm
  → NLB + multiple WS servers without shared pub/sub → missed messages

ARCHITECTURE FOR SCALE:

  Client ──WS──► ALB ──► WS Gateway (sticky conn)
                              │
                              ├── Redis Pub/Sub or Kafka
                              │
                         WS Gateway peers sync messages

  Connection lands on one gateway; cross-gateway messaging via bus.
  Do NOT assume broadcast works across WS servers without backplane.
```

### Capacity Planning and Limits

```
ALB LIMITS (check current AWS docs — illustrative):

  Targets per ALB:           1000
  Rules per ALB:             100 (soft limit, increase via quota)
  New connections/sec:       scales automatically
  LCU (Load Balancer Capacity Units): billing dimension

NLB LIMITS:

  Extremely high connection rates
  Static IP per AZ
  TLS termination consumes NLU

LCU CALCULATION (ALB) — simplified:

  1 LCU = min of:
    → 25 new connections/sec
    → 3000 active connections/min
    → 1 GB processed/hour
    → 1000 rule evaluations/sec

  Cost driver: HTTPS (more GB), many short connections, complex rules

CONNECTION MATH:

  100K concurrent WebSocket users
  ALB active connections: 100K
  If avg 1 KB/sec per WS: 100 MB/sec = 360 GB/hour → ~360 LCUs from GB dim

BACKEND CAPACITY:

  LB distributes — backends must handle sum of traffic
  10 targets × 1000 conn each = 10K max if each target limited
  Size targets for CPU/memory at expected conn count
```

---

## Concrete Examples

### Example 1: Public REST API — ALB + ECS + Route 53

```
ARCHITECTURE:

  api.example.com
       │
       ▼
  Route 53 (latency-based, health check on ALB)
       │
       ▼
  ALB (public, 3 AZs)
    Listener :443 HTTPS (ACM cert)
    Rule: default → tg-api-prod
       │
       ▼
  ECS Fargate service (10 tasks, awsvpc)
    Task IP targets in tg-api-prod
```

Terraform (abbreviated, production-shaped):

```hcl
resource "aws_lb" "api" {
  name               = "api-prod"
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = var.public_subnet_ids

  idle_timeout = 60

  access_logs {
    bucket  = aws_s3_bucket.alb_logs.bucket
    prefix  = "api-prod"
    enabled = true
  }
}

resource "aws_lb_target_group" "api" {
  name        = "api-prod-tg"
  port        = 8080
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  deregistration_delay = 120

  health_check {
    enabled             = true
    path                = "/health/ready"
    protocol            = "HTTP"
    port                = "traffic-port"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 10
    timeout             = 5
    matcher             = "200"
  }

  stickiness {
    type            = "lb_cookie"
    cookie_duration = 86400
    enabled         = false
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.api.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate.api.arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

resource "aws_route53_record" "api" {
  zone_id = var.zone_id
  name    = "api.example.com"
  type    = "A"

  alias {
    name                   = aws_lb.api.dns_name
    zone_id                = aws_lb.api.zone_id
    evaluate_target_health = true
  }
}
```

CLI — verify target health:

```bash
aws elbv2 describe-target-health \
  --target-group-arn arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/api-prod-tg/abc123 \
  --query 'TargetHealthDescriptions[*].[Target.Id,TargetHealth.State,TargetHealth.Reason]' \
  --output table
```

### Example 2: Internal gRPC Microservices — ALB vs NLB Decision

```
SERVICE: order-service (gRPC, 5 replicas, internal only)

OPTION A — NLB (WRONG for single long-lived client):

  order-client ──1 HTTP/2 conn──► NLB ──► order-pod-1 (100% load)

OPTION B — ALB with gRPC target group (CORRECT for centralized LB):
```

```hcl
resource "aws_lb_target_group" "order_grpc" {
  name             = "order-grpc-tg"
  port             = 50051
  protocol         = "HTTPS"
  protocol_version = "GRPC"
  vpc_id           = var.vpc_id
  target_type      = "ip"

  health_check {
    enabled             = true
    protocol            = "HTTP"
    path                = "/grpc.health.v1.Health/Check"
    matcher             = "0-99"
    interval            = 10
    healthy_threshold   = 2
    unhealthy_threshold = 2
  }
}
```

```
OPTION C — Client-side (no LB, Cloud Map):

  order-client resolves order-service.local → 5 pod IPs
  gRPC channel with round_robin load balancing policy
  Each RPC may use different subchannel
```

```json
{
  "loadBalancingConfig": [{"round_robin": {}}],
  "healthCheckConfig": {
    "serviceName": "order-service"
  }
}
```

```
Production at scale: Option C inside mesh (Istio/Linkerd) OR Option B at VPC edge.
```

### Example 3: WebSocket Chat — ALB + Sticky + Redis Backplane

```
ARCHITECTURE:

  wss://chat.example.com
       │
       ▼
  ALB (idle_timeout=3600)
       │
       ▼
  chat-gateway tasks (ECS)
       │
       ├── ElastiCache Redis (pub/sub channels per room)
       └── DynamoDB (room metadata)

ALB LISTENER RULE:

  Path /ws/* → tg-chat-ws
  Path /api/* → tg-chat-api

TARGET GROUP (WebSocket):

  stickiness: disabled (connection pinning automatic post-upgrade)
  deregistration_delay: 300
  health_check: GET /health (not WebSocket — separate liveness)

DEPLOY SEQUENCE:

  1. New task starts, registers, passes health check
  2. Old task deregistered (draining)
  3. Old task sends WS Close(1001 Going Away) to all clients
  4. Clients reconnect per Week 1 backoff → ALB → new tasks

NLB ALTERNATIVE:

  NLB TCP :443 → NGINX → upstream WS
  NLB preserves source IP; use proxy_protocol if needed for rate limits
```

### Example 4: Multi-Region with Global Accelerator

```
GLOBAL API ENTRY:

  Static IPs: 198.51.100.10, 198.51.100.11 (Global Accelerator)
       │
       ├── Endpoint group us-east-1 (traffic dial 100%)
       │     └── ALB api-use1
       │
       └── Endpoint group eu-west-1 (traffic dial 0% — standby)

FAILOVER (region outage):

  aws globalaccelerator update-endpoint-group \
    --endpoint-group-arn arn:aws:globalaccelerator::123:endpoint-group/abc \
    --traffic-dial-percentage 0.0   # us-east-1

  aws globalaccelerator update-endpoint-group \
    --endpoint-group-arn arn:aws:globalaccelerator::123:endpoint-group/def \
    --traffic-dial-percentage 100.0  # eu-west-1

Failover time: seconds (vs DNS TTL minutes)

CLIENT AFFINITY:

  source_ip enabled → same user stays in region after initial connect
  Disable for stateless APIs to allow natural redistribution
```

### Example 5: GWLB Inline Firewall

```
INSPECTION VPC PATTERN:

  App subnet route table:
    0.0.0.0/0 → Internet Gateway (north-south)
    10.0.0.0/8 → GWLBe (east-west inspection)

  GWLB target group: firewall appliance instances
  Health check: TCP 80 on management port

  Flow stickiness: required — return path through same appliance

Not interchangeable with ALB — different layer, different purpose.
```

### Example 6: Consistent Hashing for Cache Tier (Week 3)

```
PROBLEM: 4 Memcached nodes behind NLB, cache-mod-N on client

  Add 5th node → 80% keys invalid (Week 3 math)

SOLUTION: Envoy RING_HASH on cache_key header

  hash_policy:
    ring_hash: {}
    headers:
      - header_name: x-cache-key

  Each key maps to consistent backend
  Add node 5 → ~20% keys move (not 80%)

AWS ALB cannot do ring hash natively.
Options:
  → ALB + sticky on hash(cookie) — coarse
  → NLB + Envoy sidecar per client
  → ElastiCache Cluster Mode (AWS handles sharding)
```

---

## Production Patterns

### Pattern 1: Blue/Green at the Target Group Level

```
TWO TARGET GROUPS:

  tg-blue  (current production)
  tg-green (new version)

ALB LISTENER RULE:

  Weighted forward:
    tg-blue:  100%
    tg-green: 0%

DEPLOY:

  1. Deploy green tasks, register in tg-green
  2. Validate green health checks pass
  3. Shift weights: blue 90 / green 10 (canary)
  4. Monitor error rate, latency
  5. Shift to blue 0 / green 100
  6. Drain blue

CLI weight shift:

```bash
aws elbv2 modify-listener \
  --listener-arn $LISTENER_ARN \
  --default-actions Type=forward,ForwardConfig='{
    "TargetGroups":[
      {"TargetGroupArn":"'$TG_BLUE'","Weight":0},
      {"TargetGroupArn":"'$TG_GREEN'","Weight":100}
    ]
  }'
```

Rollback: reverse weights in seconds. No DNS change.
```

### Pattern 2: Path-Based Microservice Routing (ALB as Edge Router)

```
SINGLE HOST api.example.com:

  /users/*     → tg-user-service
  /orders/*    → tg-order-service
  /payments/*  → tg-payment-service (stricter WAF rule)
  /internal/*  → fixed-response 403

BENEFITS:
  → One TLS cert, one WAF attachment
  → Per-service target group health independence
  → Payment service can have slower health check without affecting users

LISTENER RULE PRIORITY:
  Lower number = evaluated first
  Reserve priority 1–10 for security deny rules
```

### Pattern 3: NLB for Static IP + ALB for HTTP (Layer Cake)

```
Internet → NLB (static EIPs, TLS passthrough) → ALB (internal) → targets

WHY:
  → Partners allowlist NLB EIPs
  → ALB provides path routing behind stable entry

```hcl
resource "aws_lb" "nlb" {
  name               = "api-nlb"
  load_balancer_type = "network"
  subnet_mapping {
    subnet_id     = var.public_subnet_a
    allocation_id = aws_eip.nlb_a.id
  }
  subnet_mapping {
    subnet_id     = var.public_subnet_b
    allocation_id = aws_eip.nlb_b.id
  }
}

resource "aws_lb_target_group" "alb_as_target" {
  name        = "nlb-to-alb"
  port        = 443
  protocol    = "TCP"
  vpc_id      = var.vpc_id
  target_type = "alb"
  target_id   = aws_lb.internal_alb.arn
}
```
```

### Pattern 4: Graceful Deploy Checklist (ECS + ALB)

```
PRE-DEPLOY:
  □ New image scanned, task definition revision bumped
  □ deregistration_delay ≥ p99 request duration
  □ Health check path checks dependencies (/health/ready)
  □ autoscaling policy won't fight deploy (pause scale-in)

DEPLOY:
  □ minimumHealthyPercent=100, maximumPercent=200
  □ Wait for new tasks healthy in target group
  □ Old tasks enter draining automatically

POST-DEPLOY:
  □ Monitor HTTPCode_Target_5XX_Count
  □ Monitor TargetResponseTime p99
  □ Check draining connection count → zero
  □ WebSocket: verify reconnect rate normalizes < 5 min
```

### Pattern 5: Cross-Zone and AZ Symmetry

```
RULE: Equal target count per AZ when cross-zone DISABLED

  AZ-a: 5 tasks
  AZ-b: 5 tasks
  AZ-c: 5 tasks

  NLB in AZ-a distributes only to AZ-a targets (5)
  NLB in AZ-b distributes only to AZ-b targets (5)

IF AZ-a has 10 tasks, AZ-b has 2:
  Users resolving to AZ-a LB node → 10 targets
  Users in AZ-b → 2 targets → hot spot

FIX: Rebalance tasks OR enable cross-zone on NLB/ALB

ALB cross-zone: always enabled (cannot disable)
NLB cross-zone: configurable (default off)
```

### Pattern 6: Observability Hooks

```
ENABLE:

  ALB access logs → S3
  Connection logs (NLB) → S3
  CloudWatch metrics: ActiveConnectionCount, RejectedConnectionCount
  TargetConnectionErrorCount, HTTPCode_ELB_5XX, HTTPCode_Target_5XX

STRUCTURED LOG FIELDS (from ALB access log):

  request: client:port, target:port, request_processing_time,
           target_processing_time, response_processing_time,
           elb_status_code, target_status_code, received_bytes, sent_bytes

DASHBOARD PANELS:
  → Healthy host count per target group
  → Unhealthy host count (alert > 0 for 2 min)
  → Target response time p50/p99
  → Request count per target (detect imbalance)
```

### Pattern 7: Security Groups as Load Balancer Contract

```
ALB SECURITY GROUP:

  Ingress: 443 from 0.0.0.0/0 (or CloudFront prefix list)
  Egress: 8080 to ECS task security group

ECS TASK SECURITY GROUP:

  Ingress: 8080 ONLY from ALB security group (not 0.0.0.0/0)
  Egress: 443 to RDS, Redis, internet via NAT

ANTI-PATTERN:
  Task SG allows 0.0.0.0/0:8080 "for debugging"
  → Bypasses LB WAF, TLS, routing
```

---

## Failure Modes

### Failure 1: gRPC L4 Black Hole (NLB + Long-Lived HTTP/2)

```
SCENARIO:
  Microservice mesh migrated to gRPC over NLB for "performance."
  8 backends, 2000 RPS expected evenly (~250 each).
  Reality: Backend-1 at 1900 RPS, others at <50.

ROOT CAUSE:
  Go gRPC client default: one TCP connection per target address.
  NLB DNS → single IP → one connection → all RPCs on one pod.

SYMPTOMS:
  → CPU skew on one pod
  → HPA scales based on average CPU — doesn't help
  → OOMKill on hot pod while cluster "has capacity"

DETECTION:
  → Per-target request count metric (not just cluster aggregate)
  → grpc_server_handled_total by pod — 10x skew

FIX:
  → Migrate to ALB gRPC target group OR client-side round_robin
  → Set max_connection_age=300s on server to force rebalance (band-aid)
```

### Failure 2: Health Check Flapping During GC or Deploy

```
SCENARIO:
  Health check: interval 5s, timeout 2s, unhealthy_threshold 2
  JVM full GC pause: 3 seconds every 2 minutes
  Target alternates healthy/unhealthy every few minutes

EFFECT:
  → ALB removes target mid-traffic
  → Connections reset, 502 spikes
  → Target re-added, repeat

DETECTION:
  → CloudWatch TargetHealth state change events
  → Correlate with JVM GC logs

FIX:
  → Increase unhealthy_threshold to 3–5
  → Use /health/live with short timeout for LB
  → Separate heavy readiness from liveness
  → Tune GC (G1/ZGC) to sub-second pauses
```

### Failure 3: WebSocket Mass Disconnect on Deploy

```
SCENARIO:
  Chat app, 50K concurrent WebSocket connections
  Deploy: rolling update with deregistration_delay=30s
  ALB idle_timeout=60s (not the issue — active chat)

  Old tasks killed at 30s with 2000+ active WS each
  50K clients reconnect within 10 seconds
  Login API + WS handshake overload → cascade

ROOT CAUSE:
  → deregistration_delay too short for WS
  → No server-initiated graceful close
  → No client jitter on reconnect (Week 1 thundering herd)

FIX:
  → deregistration_delay=300+
  → preStop: broadcast Going Away, wait 60s
  → Client reconnect: exponential backoff + random jitter
  → Scale WS gateways temporarily during deploy
```

### Failure 4: Sticky Session Hot Spot

```
SCENARIO:
  E-commerce with ALB stickiness (lb_cookie, 24h)
  Flash sale: 40% traffic from 2% of users (bots + influencers)
  Those users sticky to 3 of 20 targets
  3 targets at 100% CPU, 17 targets at 20%

DETECTION:
  → Request count per target — top 3 at 10x median
  → Sticky cookie present on 98% of requests

FIX:
  → Disable stickiness; sessions in Redis
  → OR shorten cookie duration during events
  → OR scale the hot targets (imperfect)
  → Rate limit at WAF before traffic hits sticky layer
```

### Failure 5: Cross-Zone Billing Surprise

```
SCENARIO:
  NLB cross-zone enabled for "fairness"
  500 GB/day ALB→target traffic across AZs
  Data transfer charge: $0.01/GB × 500 GB × 2 directions = $10/day
  "Small" but $300/month unexplained

  At 50 TB/month cross-AZ: $1000+/month

DETECTION:
  → Cost Explorer: EC2-Other / Data Transfer
  → VPC Flow Logs: cross-AZ bytes to target subnets

FIX:
  → Disable cross-zone; balance targets per AZ
  → Keep workloads AZ-local where possible
```

### Failure 6: Target Group Wrong VPC or Subnet

```
SCENARIO:
  New ECS service in vpc-prod-2
  Target group still in vpc-prod-1
  Tasks register but health checks timeout (no route)

SYMPTOMS:
  → All targets unhealthy
  → Health check failures: Target.Timeout

DETECTION:
  aws elbv2 describe-target-health → all unhealthy, reason Target.FailedHealthChecks

FIX:
  → Target group VPC must match task ENI VPC
  → ALB subnets must route to target subnets (NACL, SG, route tables)
```

### Failure 7: TLS Mismatch ALB → Backend

```
SCENARIO:
  ALB listener HTTPS, target group HTTP port 8080
  App team enables TLS on app port 8080
  ALB sends plain HTTP to TLS-expecting backend → garbage → 502

OR:
  Target group HTTPS but backend is HTTP → SSL handshake error

DETECTION:
  → HTTPCode_ELB_502_Count spike
  → Target connection errors in access logs

FIX:
  → Align target group protocol with backend
  → If re-encrypt: install cert on targets, use HTTPS target group
```

### Failure 8: Connection Exhaustion on NLB/ALB

```
SCENARIO:
  Viral event, 2M new connections/minute
  RejectedConnectionCount spikes
  Clients see connection timeout

ROOT CAUSE:
  → LB scale limit hit (rare on NLB, possible during extreme burst)
  → Backend accept queue full → LB marks targets unhealthy
  → SYN flood (security event)

FIX:
  → Pre-warm: request AWS LCU/pre-scaling for known events
  → Connection pooling on clients (HTTP/2 reuse)
  → SYN cookies, Shield Advanced
  → Scale backends faster than LB (usually LB scales first)
```

### Failure 9: Route 53 Failover Stale DNS

```
SCENARIO:
  Primary region ALB fails
  Route 53 failover to secondary
  TTL=300 seconds on non-alias record
  40% of users still hit dead primary for 5 minutes

FIX:
  → Use alias records to ALB (TTL managed by AWS)
  → Combine with Global Accelerator for fast failover
  → Application-level retry with multiple endpoints
```

### Failure 10: WAF + ALB Body Inspection Latency

```
SCENARIO:
  WAF enabled with body inspection on large POST /upload
  Upload latency p99: 8s → 45s
  Timeouts at ALB (idle) and client

DETECTION:
  → WAF AllowedRequests vs latency correlation
  → request_processing_time high in ALB logs

FIX:
  → Exempt /upload from body inspection rule
  → Use S3 presigned URL bypass ALB for large payloads
  → Increase ALB idle timeout for upload paths
```

---

## SRE Diagnostic Toolkit

```
LOAD BALANCER DEBUGGING — QUICK REFERENCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Target health (most important first command)
aws elbv2 describe-target-health \
  --target-group-arn $TG_ARN \
  --output table

# Target group health check config
aws elbv2 describe-target-groups \
  --target-group-arns $TG_ARN \
  --query 'TargetGroups[0].HealthCheck'

# ALB listener rules
aws elbv2 describe-rules \
  --listener-arn $LISTENER_ARN \
  --query 'Rules[*].[Priority,Conditions,Actions]' \
  --output table

# Which targets receive traffic (metric)
aws cloudwatch get-metric-statistics \
  --namespace AWS/ApplicationELB \
  --metric-name RequestCountPerTarget \
  --dimensions Name=TargetGroup,Value=$TG_FULL_NAME \
               Name=LoadBalancer,Value=$ALB_FULL_NAME \
  --start-time $(date -u -d '15 min ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 60 \
  --statistics Sum

# Unhealthy host count (alert source)
aws cloudwatch get-metric-statistics \
  --namespace AWS/ApplicationELB \
  --metric-name UnHealthyHostCount \
  --dimensions Name=TargetGroup,Value=$TG_FULL_NAME \
               Name=LoadBalancer,Value=$ALB_FULL_NAME \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 60 \
  --statistics Maximum

# 502/503 breakdown (ELB-generated vs target)
aws cloudwatch get-metric-statistics \
  --namespace AWS/ApplicationELB \
  --metric-name HTTPCode_ELB_502_Count \
  --dimensions Name=LoadBalancer,Value=$ALB_FULL_NAME \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 60 \
  --statistics Sum

# Active connection count
aws cloudwatch get-metric-statistics \
  --namespace AWS/ApplicationELB \
  --metric-name ActiveConnectionCount \
  --dimensions Name=LoadBalancer,Value=$ALB_FULL_NAME \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 60 \
  --statistics Average,Maximum

# Test health check path from inside VPC (debug SG/routing)
aws ecs execute-command --cluster prod --task $TASK_ID \
  --container app --interactive --command \
  "curl -sv http://localhost:8080/health/ready"

# Hit ALB directly with verbose timing
curl -svo /dev/null -w '\nconnect:%{time_connect} ttfb:%{time_starttransfer}\n' \
  https://api.example.com/health

# Check stickiness cookie
curl -sv https://api.example.com/api/v1/session 2>&1 | grep -i set-cookie

# NLB: check cross-zone setting
aws elbv2 describe-load-balancer-attributes \
  --load-balancer-arn $NLB_ARN \
  --query 'Attributes[?Key==`load_balancing.cross_zone.enabled`]'

# Global Accelerator endpoint health
aws globalaccelerator describe-endpoint-group \
  --endpoint-group-arn $EGA_ARN

# Route 53 health check status
aws route53 get-health-check-status \
  --health-check-id $HC_ID

# Parse ALB access log (S3) — top 5xx targets
aws s3 cp s3://alb-logs/AWSLogs/.../elasticloadbalancing/.../ . --recursive
zcat *.log.gz | awk '$9 ~ /^5/ {print $4}' | sort | uniq -c | sort -rn | head


METRIC INTERPRETATION CHEAT SHEET:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  UnHealthyHostCount > 0 for 2+ min     → backends failing health check
  TargetConnectionErrorCount rising     → SG wrong, target down, port wrong
  HTTPCode_ELB_502_Count                → ALB can't reach target (no healthy target,
                                          target reset, protocol mismatch)
  HTTPCode_ELB_503_Count                → no healthy targets in TG
  HTTPCode_Target_5XX_Count             → app errors (backend reached)
  RejectedConnectionCount (NLB)         → capacity or SYN issue
  RequestCountPerTarget skew 10:1       → gRPC black hole or stickiness hot spot
  TargetResponseTime p99 spike          → backend slow OR one hot target
  ConsumedLCUs spike                    → more traffic, HTTPS GB, or new connections


LOG PATTERNS:
━━━━━━━━━━━━━

  ALB access log target_status_code = "-"
    → Target did not respond (timeout, connection refused)

  target_processing_time = -1
    → Request never completed to target

  elb_status_code = 460 (custom)
    → Client closed connection before idle timeout

  NLB connection log "client_reset"
    → Client disconnected abruptly


gRPC-SPECIFIC:
━━━━━━━━━━━━━━

  # grpcurl health check through ALB
  grpcurl -plaintext api.example.com:443 \
    grpc.health.v1.Health/Check

  # Per-pod RPC rate (Prometheus)
  sum(rate(grpc_server_handled_total[5m])) by (pod)

  # Detect single-connection dominance
  sum(grpc_server_started_total) by (pod) /
  sum(grpc_server_started_total) → if one pod > 40% with 4+ pods, investigate


WEBSOCKET-SPECIFIC:
━━━━━━━━━━━━━━━━━

  # Active WS connections per task (app metric)
  websocket_active_connections{task_id="..."}

  # ALB ActiveConnectionCount during deploy
  → Should stair-step, not cliff-drop then spike (reconnect storm)

  # Client-side reconnect rate
  → Alert if > 1000/sec during non-deploy window
```

---

## Decision Framework

```
WHICH AWS LOAD BALANCER?
━━━━━━━━━━━━━━━━━━━━━━━

  ┌────────────────────────────┬──────┬──────┬──────┬──────────────┐
  │ Requirement                │ ALB  │ NLB  │ GWLB │ GA + either  │
  ├────────────────────────────┼──────┼──────┼──────┼──────────────┤
  │ HTTP path routing          │ YES  │ NO   │ NO   │ GA→ALB       │
  │ WebSocket                  │ YES  │ YES* │ NO   │ GA→ALB       │
  │ gRPC L7 distribution       │ YES  │ NO   │ NO   │ GA→ALB       │
  │ gRPC TLS passthrough L4    │ NO   │ YES  │ NO   │ GA→NLB       │
  │ Static IP                  │ NO   │ YES  │ NO   │ GA (static)  │
  │ Ultra-low latency TCP      │ OK   │ BEST │ N/A  │ GA→NLB       │
  │ UDP                        │ NO   │ YES  │ NO   │ GA→NLB       │
  │ TLS termination + WAF      │ YES  │ LIM  │ NO   │ GA→ALB+WAF   │
  │ Lambda targets             │ YES  │ NO   │ NO   │ ALB only     │
  │ Firewall appliance         │ NO   │ NO   │ YES  │ GWLB only    │
  │ Preserve source IP         │ HDR  │ YES  │ N/A  │ NLB/GA       │
  └────────────────────────────┴──────┴──────┴──────┴──────────────┘
  * NLB: TCP pass-through; no HTTP-aware drain signaling

ALGORITHM / AFFINITY CHOICE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Stateless REST, uniform requests     → Round robin / least outstanding
  Long-lived TCP, can't change LB      → Least connections + more targets
  gRPC behind NLB                      → FIX THE ARCHITECTURE (ALB or client LB)
  Session in memory (legacy)           → Sticky cookie + externalize (migrate)
  WebSocket                            → Connection pinning + Redis backplane
  Cache sharding                       → Consistent hash (Week 3) / ElastiCache
  Global users, single entry           → Global Accelerator + regional ALB
  Multi-region active-active           → Route 53 latency + regional ALBs
  Partner IP allowlist                 → NLB EIPs or Global Accelerator static IPs

HEALTH CHECK DESIGN:
━━━━━━━━━━━━━━━━━━━

  Public API, fast failure detection:
    interval 10s, unhealthy 3, path /health/ready, matcher 200

  Slow-starting JVM:
    slow_start.duration_seconds = 60 on target group
    health check interval 15s, unhealthy 5

  gRPC:
    GRPC health protocol OR HTTP /health with protocol_version GRPC

DRAINING DURATION:
━━━━━━━━━━━━━━━━

  REST API p99 < 5s          → deregistration_delay 30–60s
  REST API p99 < 30s         → 120s
  WebSocket / SSE            → 300s + app-level close
  Batch jobs on same target  → 3600s or connection count gate

ROUTE 53 POLICY PICKER:
━━━━━━━━━━━━━━━━━━━━━━

  Single region                    → Simple alias to ALB
  Active-passive DR                → Failover (primary + secondary health checks)
  Lowest latency globally          → Latency-based routing
  Gradual migration                → Weighted (90/10 split)
  Compliance (data residency)      → Geolocation routing
```

---

## Incident Scenario — Checkout API Degradation During Prime Day

```
INCIDENT REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Severity: P1 (REVENUE)
Service: ShopStream Checkout API
Time: 14:02 EST, Prime Day peak hour

ARCHITECTURE:
  Users → Route 53 (latency) → Global Accelerator (optional bypass in us-east)
       → ALB checkout-prod (public, 3 AZ)
       → Target groups:
            tg-checkout-api (ECS Fargate, 30 tasks)
            tg-checkout-ws (ECS, 12 tasks, WebSocket order status)
       → NLB order-grpc-nlb (internal) → order-service gRPC (8 pods)
       → Redis (sessions), RDS (orders)

  Deploy at 13:45: order-service v3.2.0 (gRPC keepalive change)
  Deploy at 13:50: checkout-api v5.8.1 (unrelated, HTTP)

SYMPTOMS (14:02):
  - PagerDuty P1: HTTPCode_Target_5XX_Count > 500/min on tg-checkout-api
  - PagerDuty P2: checkout p99 latency 4.2s (SLO: 800ms)
  - Slack #support: "Payment spinner forever", "Order status disconnected"
  - Grafana: ALB HealthyHostCount dropped 30 → 18 → 22 (flapping)
  - Grafana: order-service pod-7 CPU 98%, pod-1–6 CPU 15–25%
  - Grafana: NLB ActiveFlowCount evenly distributed but gRPC QPS skewed
  - Customers EU: worse than US (latency-based routing still hits us-east)

METRICS SNAPSHOT (14:05):
  ALB RequestCount: 18,400/min (normal for peak)
  ALB TargetResponseTime p99: 4,200ms (was 450ms at 13:40)
  ALB UnHealthyHostCount: 8 (of 30)
  ALB HTTPCode_ELB_502_Count: 120/min (new)
  NLB order-grpc-nlb: no unhealthy targets
  order_grpc_server_handled_total rate by pod:
    pod-7: 3,100/sec
    pod-1: 180/sec
    pod-2: 195/sec
    ... (others similar)

LOG EXCERPT — checkout-api task (14:03):
  ERROR grpc.order.CreateOrder deadline exceeded after 3.000s
  WARN  upstream connect error: connection timeout 10.0.4.88:50051
  (10.0.4.88 = order-pod-7)

LOG EXCERPT — order-pod-7 (14:03):
  WARN  grpc: Server.processUnaryRPC failed to write status:
        context deadline exceeded
  INFO  GC pause 2.8s
  METRIC active_grpc_streams: 4,812

ALB ACCESS LOG SAMPLE:
  14:02:41 ... elb_status_code=502 target_status_code=- target:8080 0.001s
  14:02:42 ... elb_status_code=200 target_status_code=200 target:8080 3.8s

HEALTH CHECK EVENTS (13:55–14:05):
  8 checkout-api tasks marked unhealthy 3x, re-added 2x
  Reason: Target.Timeout on GET /health/ready (timeout 5s)
  /health/ready checks: HTTP ok, Redis ok, order-service gRPC — TIMEOUT

WEBSOCKET COMPLAINTS:
  tg-checkout-ws: ActiveConnectionCount dropped 8,400 → 5,100 at 13:52
  (coincides with checkout-api deploy, NOT ws deploy)
  Reconnect rate: 2,200/sec at 13:53

DEPLOYMENT NOTES:
  order-service v3.2.0 changelog:
    "Increase grpc.keepalive_time_ms to 300000 (5 min) for stability"
  (Previously 30000 — 30 seconds)

INFRASTRUCTURE:
  order-grpc-nlb: cross_zone.enabled = false
  order-service HPA: target CPU 70%, max 8 pods (at max)
  ALB stickiness: enabled on tg-checkout-api (SESSION cookie, 1 hour)

YOUR ROLE: Principal engineer joining bridge at 14:08.
```

### Question 1: Causal Chain

Trace the full causal chain from the gRPC keepalive change and NLB architecture to checkout 5XX, health check flapping, and WebSocket disconnects. Which symptoms share a root cause vs are independent?

### Question 2: Immediate Mitigation (15 Minutes)

What exact changes stop customer impact in the next 15 minutes? Include AWS CLI commands, rollback targets, temporary config values, and what you explicitly will NOT do.

### Question 3: order-service Load Distribution Fix

Design the permanent fix for gRPC load distribution across order-service pods. Compare ALB gRPC target group vs client-side round_robin vs server max_connection_age. Which do you recommend for ShopStream and why?

### Question 4: Health Check and Deploy Hardening

The checkout-api tasks flapped unhealthy due to order-service timeouts propagating to /health/ready. How should health checks, circuit breakers, and deploy ordering change so a downstream gRPC incident does not pull healthy HTTP targets out of rotation?

### Question 5: WebSocket Reconnect Storm

Why did WebSocket connections drop during an unrelated checkout-api HTTP deploy? What ALB, ECS, and client-side changes prevent 2,200 reconnects/sec during future deploys?

---



---

> **Answer key (do not open until you attempt the Ops Sim / questions):**  
> [`../answers/Week-07-Specialized-Components/Load Balancing Deep Dive Answers.md`](../answers/Week-07-Specialized-Components/Load Balancing Deep Dive Answers.md)

## Key Takeaways

```
╔════════════════════════════════════════════════════════════════╗
║   IF YOU FORGET EVERYTHING ELSE, REMEMBER THESE:               ║
╟────────────────────────────────────────────────────────────────╢
║                                                                ║
║   1. L4 distributes connections; L7 distributes requests.      ║
║      gRPC and WebSockets on NLB create hot spots — the Week 1  ║
║      gRPC black hole is an architecture bug, not tuning.       ║
║                                                                ║
║   2. Health checks prove liveness of one endpoint, not system  ║
║      health. Never let slow dependencies on /health/ready      ║
║      empty your entire target group.                           ║
║                                                                ║
║   3. Connection draining is part of the deploy contract.       ║
║      deregistration_delay must exceed p99 request time and     ║
║      WebSocket close handshake needs app cooperation.          ║
║                                                                ║
║   4. Sticky sessions and consistent hashing (Week 3) solve     ║
║      affinity but create hot spots — prefer externalized       ║
║      state unless the protocol demands pinning.                ║
║                                                                ║
║   5. Route 53, Global Accelerator, and ALB/NLB operate at      ║
║      different layers. Production stacks combine them; none    ║
║      alone replaces backend capacity or correct target health. ║
╚════════════════════════════════════════════════════════════════╝
```

---

## Targeted Reading

```
REQUIRED:
  1. AWS ELB User Guide — "How Elastic Load Balancing works"
     https://docs.aws.amazon.com/elasticloadbalancing/latest/userguide/how-elastic-load-balancing-works.html
     → L4 vs L7, target groups, health checks, connection draining
     → 45 minute read; focus on ALB and NLB sections

  2. AWS Blog — "Application Load Balancer support for gRPC"
     https://aws.amazon.com/blogs/aws/new-application-load-balancer-support-for-grpc-protocol/
     → protocol_version GRPC, health checks, when to use ALB vs NLB for gRPC

  3. gRPC Load Balancing Guide
     https://grpc.io/blog/grpc-load-balancing/
     → Client-side vs proxy LB, why L4 fails, pick_first vs round_robin

OPTIONAL:
  4. AWS Global Accelerator Developer Guide — "How it works"
     https://docs.aws.amazon.com/global-accelerator/latest/dg/introduction-how-it-works.html
     → Static IPs, traffic dials, failover vs Route 53

  5. Google Maglev paper (consistent hashing at scale)
     https://research.google/pubs/pub44824/
     → Advanced; connects to Week 3 consistent hashing

CROSS-MODULE:
  Week 1 REST vs GraphQL vs gRPC — gRPC L4 black hole, HTTP/2 connections
  Week 1 WebSockets — proxy idle timeouts, reconnect storms, stickiness
  Week 3 Consistent Hashing — ring hash for cache and shard affinity
  Week 6 Circuit Breakers — fail-fast when downstream LB targets saturate
  Week 8 Observability — ALB metrics, RED method for per-target skew
```
