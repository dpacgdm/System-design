# Week 7, Topic 6: Service Discovery

Service discovery is the control loop that turns a stable service name into a changing set of safe endpoints.
It sits between DNS, load balancing, orchestration, health checking, and client retry behavior.
A strong design treats discovery as a production dependency with failure modes, not as a directory lookup.

---

## 1. Learning Objectives

After this module, you will be able to:

1. Explain client-side discovery, server-side discovery, DNS discovery, and registry-backed discovery without blurring their timing or failure domains.
2. Compare Consul, etcd, Eureka, Kubernetes Service discovery, and service-mesh/xDS patterns by ownership, health semantics, and outage behavior.
3. Design health checks that distinguish liveness, readiness, dependency health, brownout, and zone-local capacity.
4. Diagnose zone imbalance, stale endpoint caches, negative DNS caching, and registry outage thundering herds using concrete telemetry.
5. Choose cache TTLs, watch streams, jitter, backoff, and fail-open/fail-closed policies that preserve availability without routing into dead endpoints.
6. Explain how discovery interacts with Week 7 load balancing, Week 6 retries/backpressure, Week 1 DNS, Week 8 observability, and 08b service identity.
7. Run an incident bridge for a discovery control-plane outage and reject mitigations that widen blast radius.

---

## 2. Wrong Mental Models

### Mental model 1: Discovery is just DNS

Wrong because: DNS is one discovery mechanism. It has resolver caches, TTLs, negative caching, and limited health semantics. A registry watch can update in seconds while DNS clients may hold old answers for minutes or hours.

### Mental model 2: Health check green means safe to receive traffic

Wrong because: A green liveness probe may only prove the process responds. It does not prove DB pool availability, tenant quota health, dependency freshness, or zone-local spare capacity.

### Mental model 3: Client-side discovery is always faster

Wrong because: It removes a central hop but pushes registry watches, endpoint cache behavior, load-balancing policy, and retry storms into every client library.

### Mental model 4: Server-side discovery hides all complexity

Wrong because: It centralizes routing but the proxy or load balancer becomes the place where stale endpoints, overload, TLS identity, and draining policy must be solved.

### Mental model 5: Short TTLs are always safer

Wrong because: Short TTLs can turn a registry or DNS outage into synchronized refresh traffic. TTL is a control-loop parameter, not just a freshness knob.

### Mental model 6: If the registry is down, keep retrying it

Wrong because: Synchronized retry from thousands of clients can take a weak registry and make it unavailable to everyone. Backoff, jitter, stale cache, and admission control are required.

### Mental model 7: Zone-aware routing is only a cost optimization

Wrong because: Zone preference protects latency, cross-zone data transfer, and failure isolation. Wrong zone policy can drain one AZ and overload another during partial failure.

### Mental model 8: etcd and Consul are interchangeable

Wrong because: Both can store service state, but consistency, watch behavior, session leases, operational ownership, ACLs, and intended use differ. Tool names do not replace invariants.

---

## 3. Core Mechanism

### Foundation

> Staff and Principal stretch material is marked in-line. Staff mastery is required before using Principal answers.

### 3.1 The Discovery Contract

Discovery is a contract between a caller and a fleet:

```text
service name + constraints -> endpoint set + metadata + freshness bound
```

The caller usually knows a logical name such as `checkout-api`.
The discovery layer returns concrete targets such as IP:port pairs, hostnames, or proxy routes.
The returned record is only useful when it carries enough metadata to make safe routing decisions.

Common metadata:

- service version or deployment ring
- zone, region, cell, or shard
- weight or priority
- health state and last update time
- protocol and port
- service identity or SPIFFE ID when tied to mTLS
- tenant or workload class when discovery is partitioned by blast radius

A production caller should always be able to answer three questions:

1. How fresh is my endpoint set?
2. Who decided these endpoints are healthy?
3. What do I do if the discovery source is unavailable?

### 3.2 DNS-Based Discovery

DNS discovery maps a name to one or more addresses using A, AAAA, SRV, or CNAME records.
It is attractive because every runtime already has a resolver path.
It is dangerous when engineers forget that DNS is cached at many layers.

```text
client -> libc/JVM/Go resolver -> node cache -> VPC resolver -> authoritative DNS
```

DNS strengths:

- universal interface
- simple regional failover with weighted or latency records
- good for coarse service endpoints such as load balancer names
- avoids forcing every client to link a registry SDK

DNS weaknesses:

- stale positive cache after endpoint removal
- stale negative cache after endpoint creation
- resolver-specific TTL behavior
- weak per-request health awareness
- poor fit for thousands of rapidly changing pod IPs unless paired with stable service VIPs

Week 1 connection: Java `networkaddress.cache.ttl`, local DNS caches, and HTTP connection pools can hold an endpoint long after DNS changed.
Do not promise ten-second failover if clients cache DNS for an hour or keep TCP connections open indefinitely.

### 3.3 Registry-Based Discovery

A registry stores live service instances and metadata.
Instances register, renew leases, and deregister on shutdown.
Callers, proxies, or controllers read the registry and update routing tables.

Typical pattern:

```text
instance starts
  -> obtains identity and config
  -> registers service, endpoint, metadata, lease TTL
  -> health checker marks it ready
  -> callers receive endpoint via watch/poll/DNS bridge
  -> instance drains and deregisters before termination
```

Registry examples:

- Consul: service catalog, health checks, sessions, KV, DNS interface, ACLs, multi-datacenter patterns.
- etcd: strongly consistent key-value store used heavily by Kubernetes; best treated as coordination storage, not a dumping ground for arbitrary high-churn traffic.
- Eureka: AP-leaning registry pattern from Netflix; clients cache registry and tolerate registry unavailability for service-to-service calls.
- Kubernetes: Services, Endpoints/EndpointSlices, CoreDNS, kube-proxy/ipvs/eBPF, and increasingly xDS via mesh control planes.
- xDS/service mesh: control plane pushes listeners, clusters, routes, endpoints, and certificates to sidecars or gateways.

### 3.4 Client-Side Discovery

In client-side discovery, application clients ask the registry for endpoints and choose a target themselves.
Netflix Eureka plus Ribbon is the classic pattern.
Modern gRPC can use xDS or resolver plugins to do similar work.

Client-side responsibilities:

- maintain an endpoint cache
- watch or poll registry updates
- pick load-balancing algorithm
- apply zone preference and outlier ejection
- handle stale registry data
- coordinate retries with discovery refresh
- expose client-level discovery metrics

Client-side advantages:

- no per-request proxy hop
- rich caller-local policy such as tenant-aware routing
- can keep serving from last-known-good cache during registry outage
- useful for high-throughput internal RPC where every millisecond matters

Client-side risks:

- every language needs correct library behavior
- bugs roll out across many services
- stale cache plus aggressive retries can hammer dead instances
- endpoint selection is hard to audit centrally
- thundering herd if clients refresh registry on the same schedule

### 3.5 Server-Side Discovery

In server-side discovery, clients call a stable proxy, load balancer, gateway, or VIP.
The server-side component discovers backends and routes each connection or request.

Examples:

- Kubernetes ClusterIP Service with kube-proxy or eBPF dataplane
- Envoy sidecar or gateway receiving xDS endpoint updates
- AWS ALB/NLB target groups populated by controllers
- Consul Connect sidecar proxy
- service mesh waypoint or ambient proxy

Server-side advantages:

- clients use a simple stable address
- policy is centralized and easier to observe
- heterogeneous clients do not need registry SDKs
- per-request routing decisions are possible at L7

Server-side risks:

- proxy/load balancer becomes a scaling and failure point
- L4 connection pinning can hide bad distribution
- central control-plane outage can freeze many routes
- misconfigured health checks affect all callers

### 3.6 Health Checks Are Several Questions

Health is not one boolean.
Production discovery needs at least these states:

- Liveness: should the process be restarted?
- Readiness: should new traffic be sent to this instance?
- Dependency readiness: can the instance satisfy critical operations?
- Brownout: should optional features be disabled while core requests continue?
- Draining: should existing traffic finish while new traffic is withheld?
- Zone capacity: is this endpoint safe for local callers, remote callers, both, or neither?

Safe readiness checks are narrow enough to run often and broad enough to protect user-visible correctness.
They should not run a full checkout transaction against production dependencies every second.
They should not return green when the app has zero DB connections, no valid service certificate, or a full worker queue.

### 3.7 Zone-Aware Routing

Zone-aware discovery biases callers toward same-zone endpoints when safe.
This reduces latency and cross-zone cost, but more importantly preserves failure isolation.

A good policy looks like:

```text
if same-zone healthy capacity >= demand * headroom:
    route mostly same-zone
elif local zone is degraded but remote zones have spare capacity:
    spill over with admission limits
else:
    shed optional work before saturating every zone
```

Zone-aware routing fails when local clients stampede into a remote zone without checking spare capacity.
It also fails when health checks mark a whole zone bad because one shared dependency is slow, causing a healthy zone to absorb all traffic and then collapse.

### 3.8 Discovery Caches and TTLs

Every discovery system has caches even when engineers do not name them:

- DNS resolver cache
- application endpoint cache
- proxy cluster cache
- xDS snapshot cache
- load balancer target health cache
- connection pool that keeps using an endpoint after it was removed

Cache policy must state:

1. maximum staleness tolerated for traffic routing
2. behavior when refresh fails
3. jitter and backoff on refresh attempts
4. whether stale endpoints are used for reads, writes, or neither
5. how connections are drained when an endpoint disappears

The safest outage default for many internal RPCs is last-known-good for a bounded window, with endpoint-level outlier ejection and conservative retries.
The safest default for security-sensitive or money-moving dynamic policy may be fail closed if the discovery result includes authorization-critical metadata.

### 3.9 Thundering Herd on Registry Outage

A registry outage becomes a fleet outage when clients synchronize refresh, retry, and connection behavior.

Herd sequence:

```text
T+0 registry leader election stalls watches
T+1 clients miss watch heartbeat
T+2 clients all poll full catalog
T+3 registry CPU rises and queues requests
T+4 clients mark cache expired and reconnect to old endpoints
T+5 dead endpoints receive retry storms
T+8 service errors look like backend failure even though the trigger is discovery
```

Prevent it with:

- randomized refresh schedules
- exponential backoff with full jitter
- bounded stale cache
- delta watches instead of full catalog polls
- per-client and per-service registry rate limits
- emergency config to extend TTLs
- registry read replicas or fanout caches
- client circuit breaker around registry lookups

### Staff: 3.10 Pattern Comparison

| Pattern | Best fit | Main hazard | Operational complexity |
|---|---|---|---|
| DNS only | Coarse endpoints, public services, simple regional failover | stale caches, no per-request health, JVM cache surprises | low |
| DNS to load balancer | Most internet-facing APIs and many internal services | LB target health and connection draining still need design | medium |
| Consul catalog | Multi-runtime service discovery with health checks and DNS bridge | ACL/session/watch misconfig, catalog overload | medium-high |
| etcd direct | Coordination-heavy systems with strong consistency needs | using etcd as high-QPS discovery read path | high |
| Eureka-style client cache | AP-leaning internal RPC where registry outage should not stop calls | stale instances and client library drift | medium |
| Kubernetes Service | Pod churn behind stable virtual service | CoreDNS or EndpointSlice scale, kube-proxy delays | medium |
| xDS mesh | Central policy with sidecar/daemon data plane | control-plane push lag, config blast radius | high |

### Staff: 3.11 Discovery Telemetry

- Metric: `registry_request_rate by client, service, method, and response code`
  - Ask: does this separate trigger, amplifier, and symptom?
  - Page only when it predicts user-visible routing failure or control-plane collapse.
- Metric: `registry_watch_lag_seconds and dropped_watch_count`
  - Ask: does this separate trigger, amplifier, and symptom?
  - Page only when it predicts user-visible routing failure or control-plane collapse.
- Metric: `endpoint_cache_age_seconds by caller and service`
  - Ask: does this separate trigger, amplifier, and symptom?
  - Page only when it predicts user-visible routing failure or control-plane collapse.
- Metric: `endpoint_set_size and endpoint_set_churn_rate`
  - Ask: does this separate trigger, amplifier, and symptom?
  - Page only when it predicts user-visible routing failure or control-plane collapse.
- Metric: `ready_endpoint_count by zone, version, cell, and tenant class`
  - Ask: does this separate trigger, amplifier, and symptom?
  - Page only when it predicts user-visible routing failure or control-plane collapse.
- Metric: `connections_to_draining_endpoint`
  - Ask: does this separate trigger, amplifier, and symptom?
  - Page only when it predicts user-visible routing failure or control-plane collapse.
- Metric: `requests_to_unhealthy_endpoint_total`
  - Ask: does this separate trigger, amplifier, and symptom?
  - Page only when it predicts user-visible routing failure or control-plane collapse.
- Metric: `same_zone_route_ratio and cross_zone_spillover_qps`
  - Ask: does this separate trigger, amplifier, and symptom?
  - Page only when it predicts user-visible routing failure or control-plane collapse.
- Metric: `dns_resolution_latency and negative_cache_hit_count`
  - Ask: does this separate trigger, amplifier, and symptom?
  - Page only when it predicts user-visible routing failure or control-plane collapse.
- Metric: `resolver answer TTL observed by client runtime`
  - Ask: does this separate trigger, amplifier, and symptom?
  - Page only when it predicts user-visible routing failure or control-plane collapse.
- Metric: `registry leader changes and consensus apply latency`
  - Ask: does this separate trigger, amplifier, and symptom?
  - Page only when it predicts user-visible routing failure or control-plane collapse.
- Metric: `xds_push_success, xds_reject, and config version skew`
  - Ask: does this separate trigger, amplifier, and symptom?
  - Page only when it predicts user-visible routing failure or control-plane collapse.
- Metric: `outlier_ejections by reason and endpoint`
  - Ask: does this separate trigger, amplifier, and symptom?
  - Page only when it predicts user-visible routing failure or control-plane collapse.
- Metric: `retry_after_discovery_failure_total`
  - Ask: does this separate trigger, amplifier, and symptom?
  - Page only when it predicts user-visible routing failure or control-plane collapse.
- Metric: `client_library_version distribution`
  - Ask: does this separate trigger, amplifier, and symptom?
  - Page only when it predicts user-visible routing failure or control-plane collapse.

### Principal stretch: 3.12 Registry as a Tier-0 Dependency

- A registry can become Tier 0 when every deploy, scale-up, failover, and service call depends on it.
- Tier-0 treatment means capacity headroom, regional blast-radius boundaries, restore drills, schema governance, and change freezes during incidents.
- Do not let every team write arbitrary high-churn keys into the same consensus store used for endpoint membership.
- Separate control-plane writes from read fanout. Use caches, snapshots, and watch compaction deliberately.
- If registry metadata affects auth or tenant routing, a stale cache can become a security bug, not only an availability bug.
- Design for degraded operation before the outage: last-known-good is a product decision, not an on-call improvisation.

---

## 4. Production Anatomy

### 4.1 Kubernetes Example

```text
Pod readiness -> EndpointSlice -> kube-proxy/eBPF -> ClusterIP routing
CoreDNS -> service DNS name -> ClusterIP or headless pod records
Ingress/Gateway -> controller -> cloud LB target group or Envoy route
```

What you inspect during incident response:

- `kubectl get endpointslices -l kubernetes.io/service-name=checkout`
- ready versus not-ready endpoint counts
- CoreDNS error rate and cache metrics
- kube-proxy or CNI dataplane sync duration
- pod readiness transition timestamps
- connection counts to terminating pods
- service mesh config version accepted by sidecars

### 4.2 Consul/Eureka Example

```text
service instance -> agent -> registry servers -> watch/DNS/API -> client cache -> load balancer policy
```

What you inspect:

- lease/session renewal failures
- catalog index or revision seen by clients
- watch reconnect count and full catalog fetch rate
- check output age, not only check status
- ACL deny counts and token expiry
- client cache age distribution
- zone/region metadata completeness

### 4.3 Deployment and Draining Sequence

A safe deploy changes discovery state before it kills capacity:

1. new instance starts and passes local boot checks
2. readiness remains false until dependencies and warm caches are ready
3. registry adds endpoint with low weight or canary metadata
4. clients/proxies observe new endpoint and send limited traffic
5. old endpoint is marked draining
6. new requests stop, existing requests finish within drain timeout
7. endpoint deregisters or lease expires
8. process exits only after connection count reaches safe floor

Draining must be longer than common request duration and shorter than deploy safety window.
If long-lived WebSockets or streams exist, design a separate migration path.

### 4.4 Diagnostic Command Cards

#### Card: DNS stale answer

- Inspect: dig +trace service.example.com; compare resolver TTL and authoritative TTL
- Symptom: client keeps old IP after failover
- First safe action: reduce change rate, preserve last-known-good endpoint sets, and stop synchronized retries.
- Bad action to reject: global cache flush or fleet restart before cache and registry load are understood.

#### Card: JVM DNS cache

- Inspect: check `networkaddress.cache.ttl` and process uptime
- Symptom: Java ignores low DNS TTL
- First safe action: reduce change rate, preserve last-known-good endpoint sets, and stop synchronized retries.
- Bad action to reject: global cache flush or fleet restart before cache and registry load are understood.

#### Card: EndpointSlice lag

- Inspect: compare pod readiness time to EndpointSlice update time
- Symptom: Kubernetes service routes to old pods
- First safe action: reduce change rate, preserve last-known-good endpoint sets, and stop synchronized retries.
- Bad action to reject: global cache flush or fleet restart before cache and registry load are understood.

#### Card: xDS skew

- Inspect: compare route/cluster/endpoint version across proxies
- Symptom: some callers see old targets
- First safe action: reduce change rate, preserve last-known-good endpoint sets, and stop synchronized retries.
- Bad action to reject: global cache flush or fleet restart before cache and registry load are understood.

#### Card: Consul watch drop

- Inspect: inspect blocking query index and watch reconnects
- Symptom: clients full-poll catalog
- First safe action: reduce change rate, preserve last-known-good endpoint sets, and stop synchronized retries.
- Bad action to reject: global cache flush or fleet restart before cache and registry load are understood.

#### Card: Eureka stale cache

- Inspect: compare registry timestamp to client cache timestamp
- Symptom: client routes to terminated instance
- First safe action: reduce change rate, preserve last-known-good endpoint sets, and stop synchronized retries.
- Bad action to reject: global cache flush or fleet restart before cache and registry load are understood.

#### Card: Zone imbalance

- Inspect: same-zone ratio and ready endpoints per zone
- Symptom: one AZ hot while fleet average green
- First safe action: reduce change rate, preserve last-known-good endpoint sets, and stop synchronized retries.
- Bad action to reject: global cache flush or fleet restart before cache and registry load are understood.

#### Card: Draining leak

- Inspect: connections to endpoints marked draining
- Symptom: deploy causes 5xx spike
- First safe action: reduce change rate, preserve last-known-good endpoint sets, and stop synchronized retries.
- Bad action to reject: global cache flush or fleet restart before cache and registry load are understood.

#### Card: Health false green

- Inspect: readiness green while dependency pool exhausted
- Symptom: LB sends traffic into brownout
- First safe action: reduce change rate, preserve last-known-good endpoint sets, and stop synchronized retries.
- Bad action to reject: global cache flush or fleet restart before cache and registry load are understood.

#### Card: Registry overload

- Inspect: registry qps, p99, leader changes, queue depth
- Symptom: discovery failure appears as backend failure
- First safe action: reduce change rate, preserve last-known-good endpoint sets, and stop synchronized retries.
- Bad action to reject: global cache flush or fleet restart before cache and registry load are understood.

---

## 5. Failure Catalog

### Failure 1: Stale positive DNS cache

- Trigger: endpoint removed.
- Amplifier: client/runtime cache ignores intended TTL.
- Blast radius: traffic continues to dead target.
- Evidence: compare endpoint-set age, ready endpoint count, discovery error rate, and user-visible error slices.
- Safer mitigation: scope the fix by service, zone, version, or client library; preserve known-good routes while reducing load.

### Failure 2: Negative DNS cache

- Trigger: new service name created.
- Amplifier: NXDOMAIN cached.
- Blast radius: new deployment appears unavailable.
- Evidence: compare endpoint-set age, ready endpoint count, discovery error rate, and user-visible error slices.
- Safer mitigation: scope the fix by service, zone, version, or client library; preserve known-good routes while reducing load.

### Failure 3: Registry leader churn

- Trigger: disk or network hiccup.
- Amplifier: watch streams reset.
- Blast radius: clients poll full catalog.
- Evidence: compare endpoint-set age, ready endpoint count, discovery error rate, and user-visible error slices.
- Safer mitigation: scope the fix by service, zone, version, or client library; preserve known-good routes while reducing load.

### Failure 4: Lease renewal pause

- Trigger: GC or node CPU steal.
- Amplifier: healthy instances expire.
- Blast radius: capacity vanishes from routing.
- Evidence: compare endpoint-set age, ready endpoint count, discovery error rate, and user-visible error slices.
- Safer mitigation: scope the fix by service, zone, version, or client library; preserve known-good routes while reducing load.

### Failure 5: False readiness

- Trigger: health endpoint too shallow.
- Amplifier: dependency pool saturated.
- Blast radius: 5xx from green targets.
- Evidence: compare endpoint-set age, ready endpoint count, discovery error rate, and user-visible error slices.
- Safer mitigation: scope the fix by service, zone, version, or client library; preserve known-good routes while reducing load.

### Failure 6: Over-deep health

- Trigger: check calls every dependency.
- Amplifier: dependency slowness cascades into readiness flaps.
- Blast radius: entire fleet removed.
- Evidence: compare endpoint-set age, ready endpoint count, discovery error rate, and user-visible error slices.
- Safer mitigation: scope the fix by service, zone, version, or client library; preserve known-good routes while reducing load.

### Failure 7: Missing zone metadata

- Trigger: deployment omits labels.
- Amplifier: policy treats endpoints as remote/global.
- Blast radius: cross-zone overload.
- Evidence: compare endpoint-set age, ready endpoint count, discovery error rate, and user-visible error slices.
- Safer mitigation: scope the fix by service, zone, version, or client library; preserve known-good routes while reducing load.

### Failure 8: Client cache too short

- Trigger: low TTL.
- Amplifier: registry outage.
- Blast radius: refresh storm.
- Evidence: compare endpoint-set age, ready endpoint count, discovery error rate, and user-visible error slices.
- Safer mitigation: scope the fix by service, zone, version, or client library; preserve known-good routes while reducing load.

### Failure 9: Client cache too long

- Trigger: high TTL.
- Amplifier: bad deploy.
- Blast radius: clients pin broken version.
- Evidence: compare endpoint-set age, ready endpoint count, discovery error rate, and user-visible error slices.
- Safer mitigation: scope the fix by service, zone, version, or client library; preserve known-good routes while reducing load.

### Failure 10: Full catalog polling

- Trigger: watch compaction or proxy restart.
- Amplifier: all clients recover at once.
- Blast radius: registry CPU collapse.
- Evidence: compare endpoint-set age, ready endpoint count, discovery error rate, and user-visible error slices.
- Safer mitigation: scope the fix by service, zone, version, or client library; preserve known-good routes while reducing load.

### Failure 11: Endpoint churn

- Trigger: autoscaler oscillation.
- Amplifier: routing tables never settle.
- Blast radius: connection resets.
- Evidence: compare endpoint-set age, ready endpoint count, discovery error rate, and user-visible error slices.
- Safer mitigation: scope the fix by service, zone, version, or client library; preserve known-good routes while reducing load.

### Failure 12: Draining too short

- Trigger: deploy kills pod.
- Amplifier: long requests still active.
- Blast radius: partial writes and retries.
- Evidence: compare endpoint-set age, ready endpoint count, discovery error rate, and user-visible error slices.
- Safer mitigation: scope the fix by service, zone, version, or client library; preserve known-good routes while reducing load.

### Failure 13: Connection pool stickiness

- Trigger: endpoint removed from registry.
- Amplifier: pool keeps sockets.
- Blast radius: traffic bypasses discovery update.
- Evidence: compare endpoint-set age, ready endpoint count, discovery error rate, and user-visible error slices.
- Safer mitigation: scope the fix by service, zone, version, or client library; preserve known-good routes while reducing load.

### Failure 14: Outlier ejection too aggressive

- Trigger: one slow sample.
- Amplifier: endpoint removed globally.
- Blast radius: capacity loss and retry amplification.
- Evidence: compare endpoint-set age, ready endpoint count, discovery error rate, and user-visible error slices.
- Safer mitigation: scope the fix by service, zone, version, or client library; preserve known-good routes while reducing load.

### Failure 15: Auth metadata stale

- Trigger: service identity rotated.
- Amplifier: clients use old registry metadata.
- Blast radius: mTLS or authorization failures.
- Evidence: compare endpoint-set age, ready endpoint count, discovery error rate, and user-visible error slices.
- Safer mitigation: scope the fix by service, zone, version, or client library; preserve known-good routes while reducing load.

### Failure 16: Control-plane config blast

- Trigger: bad xDS route.
- Amplifier: global push.
- Blast radius: all sidecars reject config.
- Evidence: compare endpoint-set age, ready endpoint count, discovery error rate, and user-visible error slices.
- Safer mitigation: scope the fix by service, zone, version, or client library; preserve known-good routes while reducing load.

### Failure 17: CoreDNS saturation

- Trigger: short TTL service names.
- Amplifier: node-local cache missing.
- Blast radius: pods see DNS timeouts.
- Evidence: compare endpoint-set age, ready endpoint count, discovery error rate, and user-visible error slices.
- Safer mitigation: scope the fix by service, zone, version, or client library; preserve known-good routes while reducing load.

### Failure 18: Hot service name

- Trigger: one dependency called by every service.
- Amplifier: lookup rate exceeds cache fanout.
- Blast radius: registry becomes bottleneck.
- Evidence: compare endpoint-set age, ready endpoint count, discovery error rate, and user-visible error slices.
- Safer mitigation: scope the fix by service, zone, version, or client library; preserve known-good routes while reducing load.

### Failure 19: Clock skew in leases

- Trigger: node clock jumps.
- Amplifier: lease TTL logic breaks.
- Blast radius: healthy endpoint expires early or late.
- Evidence: compare endpoint-set age, ready endpoint count, discovery error rate, and user-visible error slices.
- Safer mitigation: scope the fix by service, zone, version, or client library; preserve known-good routes while reducing load.

### Failure 20: ACL/token expiry

- Trigger: registry token rotation.
- Amplifier: clients denied refresh.
- Blast radius: stale cache hides security/config failure.
- Evidence: compare endpoint-set age, ready endpoint count, discovery error rate, and user-visible error slices.
- Safer mitigation: scope the fix by service, zone, version, or client library; preserve known-good routes while reducing load.

---

## 6. Decision Framework

### 6.1 Client-Side vs Server-Side Discovery

Choose client-side discovery when:

- callers are trusted internal services with a maintained common client library
- low latency and rich local policy matter
- last-known-good cache during registry outage is an explicit requirement
- client language/runtime count is small enough to govern

Choose server-side discovery when:

- clients are diverse, untrusted, or hard to update
- central policy, auth, observability, or L7 routing matters
- you need to hide backend churn from callers
- operational teams can own proxy/load balancer capacity as a first-class service

Choose DNS-only discovery when:

- endpoint churn is low
- health requirements are coarse
- stale answers are acceptable within a bounded TTL
- clients are known to honor TTL and connection-drain behavior is handled elsewhere

### 6.2 Registry Tool Selection

Use Consul when you need service catalog, DNS bridge, health checks, ACLs, and heterogeneous runtimes.
Use etcd as a strongly consistent coordination substrate, especially when Kubernetes already owns service membership through it.
Use Eureka-style behavior when service-to-service calls should continue from cache while the registry is unavailable.
Use Kubernetes Service discovery when workloads are already on Kubernetes and pod churn should be hidden behind Services or EndpointSlices.
Use xDS when you need centralized L7 routing, outlier detection, traffic splitting, and policy pushed to proxies.

### 6.3 Cache Policy Matrix

| Path | Freshness need | Safe stale behavior | Bad stale behavior |
|---|---|---|---|
| Checkout write | seconds | stale endpoints only if endpoint identity and version are safe | route to old leader or wrong tenant cell |
| Product read | tens of seconds | last-known-good endpoint with retries bounded | global 5xx from empty cache |
| Metrics ingest | minutes | local buffering and stale route | dropping critical incident telemetry |
| Auth policy route | immediate to seconds | fail closed for unknown policy | fail open to wrong service identity |
| Batch enrichment | minutes | pause queue and drain later | saturate registry with retries |

### 6.4 First Five Incident Questions

1. Did endpoints disappear, become stale, or become unreachable?
2. Is the registry unhealthy, the client cache unhealthy, or the backend unhealthy?
3. Is traffic failing globally or by zone, version, tenant, or client library?
4. Are clients refreshing/retrying in a synchronized way?
5. What invariant is safer: use stale endpoints briefly, shed traffic, or fail closed?

### 6.5 Review Prompts

#### Prompt 1

A service has 4 zones or cells, endpoint churn every 11 seconds, and client caches with TTL 10 seconds.
- Name the discovery mechanism you would use and why.
- State the health signal that must remove endpoints from rotation.
- State the cache behavior during registry outage.
- State the metric that tells you whether your decision is safe.
- Reject one mitigation that would create a thundering herd.

#### Prompt 2

A service has 5 zones or cells, endpoint churn every 12 seconds, and client caches with TTL 15 seconds.
- Name the discovery mechanism you would use and why.
- State the health signal that must remove endpoints from rotation.
- State the cache behavior during registry outage.
- State the metric that tells you whether your decision is safe.
- Reject one mitigation that would create a thundering herd.

#### Prompt 3

A service has 6 zones or cells, endpoint churn every 13 seconds, and client caches with TTL 20 seconds.
- Name the discovery mechanism you would use and why.
- State the health signal that must remove endpoints from rotation.
- State the cache behavior during registry outage.
- State the metric that tells you whether your decision is safe.
- Reject one mitigation that would create a thundering herd.

#### Prompt 4

A service has 7 zones or cells, endpoint churn every 14 seconds, and client caches with TTL 25 seconds.
- Name the discovery mechanism you would use and why.
- State the health signal that must remove endpoints from rotation.
- State the cache behavior during registry outage.
- State the metric that tells you whether your decision is safe.
- Reject one mitigation that would create a thundering herd.

#### Prompt 5

A service has 3 zones or cells, endpoint churn every 15 seconds, and client caches with TTL 30 seconds.
- Name the discovery mechanism you would use and why.
- State the health signal that must remove endpoints from rotation.
- State the cache behavior during registry outage.
- State the metric that tells you whether your decision is safe.
- Reject one mitigation that would create a thundering herd.

#### Prompt 6

A service has 4 zones or cells, endpoint churn every 16 seconds, and client caches with TTL 35 seconds.
- Name the discovery mechanism you would use and why.
- State the health signal that must remove endpoints from rotation.
- State the cache behavior during registry outage.
- State the metric that tells you whether your decision is safe.
- Reject one mitigation that would create a thundering herd.

#### Prompt 7

A service has 5 zones or cells, endpoint churn every 17 seconds, and client caches with TTL 5 seconds.
- Name the discovery mechanism you would use and why.
- State the health signal that must remove endpoints from rotation.
- State the cache behavior during registry outage.
- State the metric that tells you whether your decision is safe.
- Reject one mitigation that would create a thundering herd.

#### Prompt 8

A service has 6 zones or cells, endpoint churn every 18 seconds, and client caches with TTL 10 seconds.
- Name the discovery mechanism you would use and why.
- State the health signal that must remove endpoints from rotation.
- State the cache behavior during registry outage.
- State the metric that tells you whether your decision is safe.
- Reject one mitigation that would create a thundering herd.

#### Prompt 9

A service has 7 zones or cells, endpoint churn every 19 seconds, and client caches with TTL 15 seconds.
- Name the discovery mechanism you would use and why.
- State the health signal that must remove endpoints from rotation.
- State the cache behavior during registry outage.
- State the metric that tells you whether your decision is safe.
- Reject one mitigation that would create a thundering herd.

#### Prompt 10

A service has 3 zones or cells, endpoint churn every 20 seconds, and client caches with TTL 20 seconds.
- Name the discovery mechanism you would use and why.
- State the health signal that must remove endpoints from rotation.
- State the cache behavior during registry outage.
- State the metric that tells you whether your decision is safe.
- Reject one mitigation that would create a thundering herd.

#### Prompt 11

A service has 4 zones or cells, endpoint churn every 21 seconds, and client caches with TTL 25 seconds.
- Name the discovery mechanism you would use and why.
- State the health signal that must remove endpoints from rotation.
- State the cache behavior during registry outage.
- State the metric that tells you whether your decision is safe.
- Reject one mitigation that would create a thundering herd.

#### Prompt 12

A service has 5 zones or cells, endpoint churn every 22 seconds, and client caches with TTL 30 seconds.
- Name the discovery mechanism you would use and why.
- State the health signal that must remove endpoints from rotation.
- State the cache behavior during registry outage.
- State the metric that tells you whether your decision is safe.
- Reject one mitigation that would create a thundering herd.

#### Prompt 13

A service has 6 zones or cells, endpoint churn every 23 seconds, and client caches with TTL 35 seconds.
- Name the discovery mechanism you would use and why.
- State the health signal that must remove endpoints from rotation.
- State the cache behavior during registry outage.
- State the metric that tells you whether your decision is safe.
- Reject one mitigation that would create a thundering herd.

#### Prompt 14

A service has 7 zones or cells, endpoint churn every 24 seconds, and client caches with TTL 5 seconds.
- Name the discovery mechanism you would use and why.
- State the health signal that must remove endpoints from rotation.
- State the cache behavior during registry outage.
- State the metric that tells you whether your decision is safe.
- Reject one mitigation that would create a thundering herd.

#### Prompt 15

A service has 3 zones or cells, endpoint churn every 25 seconds, and client caches with TTL 10 seconds.
- Name the discovery mechanism you would use and why.
- State the health signal that must remove endpoints from rotation.
- State the cache behavior during registry outage.
- State the metric that tells you whether your decision is safe.
- Reject one mitigation that would create a thundering herd.

#### Prompt 16

A service has 4 zones or cells, endpoint churn every 26 seconds, and client caches with TTL 15 seconds.
- Name the discovery mechanism you would use and why.
- State the health signal that must remove endpoints from rotation.
- State the cache behavior during registry outage.
- State the metric that tells you whether your decision is safe.
- Reject one mitigation that would create a thundering herd.

#### Prompt 17

A service has 5 zones or cells, endpoint churn every 27 seconds, and client caches with TTL 20 seconds.
- Name the discovery mechanism you would use and why.
- State the health signal that must remove endpoints from rotation.
- State the cache behavior during registry outage.
- State the metric that tells you whether your decision is safe.
- Reject one mitigation that would create a thundering herd.

#### Prompt 18

A service has 6 zones or cells, endpoint churn every 28 seconds, and client caches with TTL 25 seconds.
- Name the discovery mechanism you would use and why.
- State the health signal that must remove endpoints from rotation.
- State the cache behavior during registry outage.
- State the metric that tells you whether your decision is safe.
- Reject one mitigation that would create a thundering herd.

#### Prompt 19

A service has 7 zones or cells, endpoint churn every 29 seconds, and client caches with TTL 30 seconds.
- Name the discovery mechanism you would use and why.
- State the health signal that must remove endpoints from rotation.
- State the cache behavior during registry outage.
- State the metric that tells you whether your decision is safe.
- Reject one mitigation that would create a thundering herd.

#### Prompt 20

A service has 3 zones or cells, endpoint churn every 30 seconds, and client caches with TTL 35 seconds.
- Name the discovery mechanism you would use and why.
- State the health signal that must remove endpoints from rotation.
- State the cache behavior during registry outage.
- State the metric that tells you whether your decision is safe.
- Reject one mitigation that would create a thundering herd.

#### Prompt 21

A service has 4 zones or cells, endpoint churn every 31 seconds, and client caches with TTL 5 seconds.
- Name the discovery mechanism you would use and why.
- State the health signal that must remove endpoints from rotation.
- State the cache behavior during registry outage.
- State the metric that tells you whether your decision is safe.
- Reject one mitigation that would create a thundering herd.

#### Prompt 22

A service has 5 zones or cells, endpoint churn every 32 seconds, and client caches with TTL 10 seconds.
- Name the discovery mechanism you would use and why.
- State the health signal that must remove endpoints from rotation.
- State the cache behavior during registry outage.
- State the metric that tells you whether your decision is safe.
- Reject one mitigation that would create a thundering herd.

#### Prompt 23

A service has 6 zones or cells, endpoint churn every 33 seconds, and client caches with TTL 15 seconds.
- Name the discovery mechanism you would use and why.
- State the health signal that must remove endpoints from rotation.
- State the cache behavior during registry outage.
- State the metric that tells you whether your decision is safe.
- Reject one mitigation that would create a thundering herd.

#### Prompt 24

A service has 7 zones or cells, endpoint churn every 34 seconds, and client caches with TTL 20 seconds.
- Name the discovery mechanism you would use and why.
- State the health signal that must remove endpoints from rotation.
- State the cache behavior during registry outage.
- State the metric that tells you whether your decision is safe.
- Reject one mitigation that would create a thundering herd.

#### Prompt 25

A service has 3 zones or cells, endpoint churn every 35 seconds, and client caches with TTL 25 seconds.
- Name the discovery mechanism you would use and why.
- State the health signal that must remove endpoints from rotation.
- State the cache behavior during registry outage.
- State the metric that tells you whether your decision is safe.
- Reject one mitigation that would create a thundering herd.

#### Prompt 26

A service has 4 zones or cells, endpoint churn every 36 seconds, and client caches with TTL 30 seconds.
- Name the discovery mechanism you would use and why.
- State the health signal that must remove endpoints from rotation.
- State the cache behavior during registry outage.
- State the metric that tells you whether your decision is safe.
- Reject one mitigation that would create a thundering herd.

#### Prompt 27

A service has 5 zones or cells, endpoint churn every 37 seconds, and client caches with TTL 35 seconds.
- Name the discovery mechanism you would use and why.
- State the health signal that must remove endpoints from rotation.
- State the cache behavior during registry outage.
- State the metric that tells you whether your decision is safe.
- Reject one mitigation that would create a thundering herd.

#### Prompt 28

A service has 6 zones or cells, endpoint churn every 38 seconds, and client caches with TTL 5 seconds.
- Name the discovery mechanism you would use and why.
- State the health signal that must remove endpoints from rotation.
- State the cache behavior during registry outage.
- State the metric that tells you whether your decision is safe.
- Reject one mitigation that would create a thundering herd.

#### Prompt 29

A service has 7 zones or cells, endpoint churn every 39 seconds, and client caches with TTL 10 seconds.
- Name the discovery mechanism you would use and why.
- State the health signal that must remove endpoints from rotation.
- State the cache behavior during registry outage.
- State the metric that tells you whether your decision is safe.
- Reject one mitigation that would create a thundering herd.

#### Prompt 30

A service has 3 zones or cells, endpoint churn every 40 seconds, and client caches with TTL 15 seconds.
- Name the discovery mechanism you would use and why.
- State the health signal that must remove endpoints from rotation.
- State the cache behavior during registry outage.
- State the metric that tells you whether your decision is safe.
- Reject one mitigation that would create a thundering herd.

---

## 7. Ops Sim: Registry Outage and Zone Herd

Questions only. Do not open the answer key until you finish.

### Scenario

Northstar Commerce runs checkout, catalog, inventory, and recommendation services across three zones in `us-east-1`.
Internal gRPC clients use client-side discovery through a Consul-like registry.
Public traffic enters through an ALB, but service-to-service calls bypass the ALB.
A recent client library release changed registry refresh from jittered 60-second watches to a fixed 10-second poll after watch errors.

### Telemetry pack

```text
checkout 5xx:                    0.3% -> 8.7% in 12 minutes
checkout p99:                    220 ms -> 3.9 s
registry API p99:                35 ms -> 4.8 s
registry CPU:                    42% -> 96%
registry leader changes:         0 -> 7 in 20 minutes
full catalog polls:              1.5k/min -> 280k/min
watch reconnects:                200/min -> 90k/min
client endpoint cache age p95:   45 s -> 11 min
ready inventory endpoints:       az-a 42, az-b 4, az-c 39
same-zone route ratio az-b:      86% -> 18%
cross-zone bytes:                3 TB/day -> projected 19 TB/day
requests to draining endpoints:  0 -> 14k/min
```

### Config pack

```yaml
serviceDiscovery:
  mode: client_side
  registry: consul-like
  watchHeartbeatTimeout: 15s
  fallbackPollInterval: 10s     # suspect
  pollJitter: 0s                # suspect
  endpointCacheTtl: 60s
  staleCacheMaxAge: 15m
  failWhenCacheExpired: false
  zoneAwareRouting: true
  remoteZoneSpilloverLimit: unlimited  # suspect
  outlierEjection:
    consecutive5xx: 2           # suspect during partial outage
    baseEjectionTime: 30s
deploy:
  drainTimeout: 20s             # suspect for p99 3.9s and streams
  deregisterBeforeSigterm: true
```

### Timeline

- T+0: Consul leader election pauses watches for 18 seconds after an overloaded disk stalls fsync.
- T+5: clients switch from watch to fixed poll; registry full catalog polls jump by 180x.
- T+15: az-b inventory endpoints flap readiness because a local DB pool is exhausted; remote spillover is unlimited.
- T+60: checkout errors remain high even after registry leader is stable because clients keep stale endpoint caches and connections to draining pods.

### Questions

1. Split the incident into trigger, amplifiers, symptoms, and customer impact.
2. What is the first safe mitigation for registry load, and why is it safer than restarting clients?
3. Should checkout keep using stale endpoint caches? Answer by path: checkout write, catalog read, metrics ingest.
4. Which config values are most suspicious? For each, name the failure it amplifies.
5. Do capacity math: if 28,000 clients poll every 10 seconds and each full catalog response is 450 KB, what registry egress rate is created before retries?
6. How would you cap cross-zone spillover from az-b without hiding real customer pain?
7. Which health check semantics are wrong for inventory in az-b? What should readiness include and exclude?
8. What metric proves the registry is the trigger rather than inventory being the only root cause?
9. Which bad fix should you reject: global DNS failover, full cache flush, outlier ejection threshold of 1, or doubling checkout replicas? Explain each.
10. What is the rollback or emergency config change for the client library release?
11. What runbook step drains connections to endpoints already marked draining?
12. Which comms update should the incident commander send to service owners at T+15?
13. Which post-incident tests prevent this from recurring?
14. What should be owned by the platform team versus each service team?
15. What is the smallest blast-radius boundary you can restore first?

16. Additional drill: choose one service in the scenario and state the exact endpoint-cache policy, retry budget, and zone-spillover cap you would apply for the next hour.
17. Additional drill: choose one service in the scenario and state the exact endpoint-cache policy, retry budget, and zone-spillover cap you would apply for the next hour.
18. Additional drill: choose one service in the scenario and state the exact endpoint-cache policy, retry budget, and zone-spillover cap you would apply for the next hour.
19. Additional drill: choose one service in the scenario and state the exact endpoint-cache policy, retry budget, and zone-spillover cap you would apply for the next hour.
20. Additional drill: choose one service in the scenario and state the exact endpoint-cache policy, retry budget, and zone-spillover cap you would apply for the next hour.
21. Additional drill: choose one service in the scenario and state the exact endpoint-cache policy, retry budget, and zone-spillover cap you would apply for the next hour.
22. Additional drill: choose one service in the scenario and state the exact endpoint-cache policy, retry budget, and zone-spillover cap you would apply for the next hour.
23. Additional drill: choose one service in the scenario and state the exact endpoint-cache policy, retry budget, and zone-spillover cap you would apply for the next hour.
24. Additional drill: choose one service in the scenario and state the exact endpoint-cache policy, retry budget, and zone-spillover cap you would apply for the next hour.
25. Additional drill: choose one service in the scenario and state the exact endpoint-cache policy, retry budget, and zone-spillover cap you would apply for the next hour.
26. Additional drill: choose one service in the scenario and state the exact endpoint-cache policy, retry budget, and zone-spillover cap you would apply for the next hour.
27. Additional drill: choose one service in the scenario and state the exact endpoint-cache policy, retry budget, and zone-spillover cap you would apply for the next hour.
28. Additional drill: choose one service in the scenario and state the exact endpoint-cache policy, retry budget, and zone-spillover cap you would apply for the next hour.
29. Additional drill: choose one service in the scenario and state the exact endpoint-cache policy, retry budget, and zone-spillover cap you would apply for the next hour.
30. Additional drill: choose one service in the scenario and state the exact endpoint-cache policy, retry budget, and zone-spillover cap you would apply for the next hour.
31. Additional drill: choose one service in the scenario and state the exact endpoint-cache policy, retry budget, and zone-spillover cap you would apply for the next hour.
32. Additional drill: choose one service in the scenario and state the exact endpoint-cache policy, retry budget, and zone-spillover cap you would apply for the next hour.
33. Additional drill: choose one service in the scenario and state the exact endpoint-cache policy, retry budget, and zone-spillover cap you would apply for the next hour.
34. Additional drill: choose one service in the scenario and state the exact endpoint-cache policy, retry budget, and zone-spillover cap you would apply for the next hour.
35. Additional drill: choose one service in the scenario and state the exact endpoint-cache policy, retry budget, and zone-spillover cap you would apply for the next hour.

---

## 8. Key Takeaways

- Service discovery is a control loop, not a static lookup.
- DNS, registry, client cache, proxy cache, and connection pool all have separate freshness behavior.
- Health checks must distinguish liveness, readiness, brownout, draining, and dependency capacity.
- Zone-aware routing protects latency, cost, and blast radius only when spillover is bounded by spare capacity.
- Registry outages become fleet outages when clients synchronize refresh and retry behavior.
- Last-known-good cache is a deliberate safety policy with time bounds and path-specific invariants.
- The first mitigation is usually to stop amplification, not to restart every client or flush every cache.

---

## 9. Targeted Reading

- Kubernetes documentation: Services, DNS for Services and Pods, EndpointSlices, readiness and liveness probes.
- Consul documentation: service registration, health checks, blocking queries, prepared queries, ACLs, and Consul DNS.
- etcd documentation: watch API, compaction, leases, and operational limits.
- Netflix Eureka architecture notes: client cache, self-preservation, and AP-oriented registry behavior.
- Envoy xDS APIs: Listener, Route, Cluster, Endpoint discovery services and outlier detection.
- AWS docs: Route 53 health checks and DNS failover; ALB/NLB target health and deregistration delay.
- Week 1 DNS Resolution, Week 7 Load Balancing Deep Dive, Week 6 Circuit Breakers/Bulkheads/Timeouts/Retries, and Week 08b Authn/z and Multi-Tenancy modules.
