# Cloud-Native Networking: Envoy Proxy, Service Mesh, eBPF & Overlay Networks

## Learning Objectives

```
╔══════════════════════════════════════════════════════════════════════════╗
║ AFTER THIS TOPIC, YOU WILL BE ABLE TO:                                   ║
╟──────────────────────────────────────────────────────────────────────────╢
║                                                                          ║
║ 1. Explain Envoy Proxy's internal threading model (thread-per-core event ║
║    loop) and how xDS dynamically drives configuration without reloads.   ║
║                                                                          ║
║ 2. Quantify the latency and CPU overhead of Service Mesh mTLS, and       ║
║    design mitigations (AES-NI, TLS session resumption, connection pools).║
║                                                                          ║
║ 3. Contrast traditional Linux IP stack routing with eBPF/Cilium socket   ║
║    bypassing (`sockmap`, XDP) to eliminate kernel context switches.      ║
║                                                                          ║
║ 4. Diagnose MTU misconfigurations and packet fragmentation caused by     ║
║    VXLAN/Geneve overlay network encapsulation headers.                   ║
║                                                                          ║
║ 5. Troubleshoot Cloud VPC CNI limits: ENI attachment limits, IP address  ║
║    exhaustion, and pod provisioning stalls.                              ║
╚══════════════════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔════════════════════════════════════════════════════════════════════════════════╗
║ MENTAL MODEL #1: "Service mesh proxies (Envoy) add negligible latency"         ║
╟────────────────────────────────────────────────────────────────────────────────╢
║ WRONG. Each sidecar hop introduces context switching, memory copying across    ║
║ Unix domain sockets or loopback, and L7 HTTP parsing. A pod-to-pod mesh call   ║
║ traverses TWO Envoy proxies (client sidecar + server sidecar), adding          ║
║ 1.5ms to 4ms of p99 tail latency and significant CPU overhead.                 ║
╠════════════════════════════════════════════════════════════════════════════════╣
║ MENTAL MODEL #2: "Hardware security acceleration makes mTLS free"              ║
╟────────────────────────────────────────────────────────────────────────────────╢
║ WRONG. AES-NI accelerates symmetric bulk encryption, but TLS 1.3 handshakes    ║
║ still pay an asymmetric crypto tax (ECDHE key exchange) per connection.        ║
║ High-churn microservice architectures without connection reuse saturate CPU    ║
║ on handshake crypto alone.                                                     ║
╠════════════════════════════════════════════════════════════════════════════════╣
║ MENTAL MODEL #3: "eBPF replaces Envoy completely"                              ║
╟────────────────────────────────────────────────────────────────────────────────╢
║ WRONG. eBPF operates at L3/L4 (IP/TCP) inside the Linux kernel. It cannot      ║
║ perform L7 routing (HTTP header matching, gRPC retry policies, OAuth JWT       ║
║ validation) efficiently without proxying to an L7 userspace engine. eBPF       ║
║ accelerates network transport; Envoy handles L7 application logic.             ║
╠════════════════════════════════════════════════════════════════════════════════╣
║ MENTAL MODEL #4: "Standard 1500-byte MTU works fine in Kubernetes overlays"    ║
╟────────────────────────────────────────────────────────────────────────────────╢
║ WRONG. VXLAN adds a 50-byte outer encapsulation header (Outer IP + UDP +       ║
║ VXLAN). Setting pod MTU to 1500 on an underlying 1500 MTU fabric forces IP     ║
║ fragmentation or silent packet dropping (DF bit set), destroying TCP throughput║
║ with massive retransmission storms.                                            ║
╚════════════════════════════════════════════════════════════════════════════════╝
```

---

## Core Teaching

### Foundation

> Staff / Principal stretch sections are marked below. Mastery gate: Staff required; Principal optional.

### 1. Envoy Proxy Architecture & xDS Control Plane

Modern cloud-native platforms rely on **Envoy** as the universal data plane proxy. Understanding its threading and configuration model is essential for diagnosing service mesh performance.

#### The Thread-per-Core Event Loop Model

Envoy uses a single-process, multi-threaded architecture based on an asynchronous event loop (`libevent`):

```
                       ┌──────────────────────────────────────┐
                       │           Main Thread                │
                       │  - Handles xDS gRPC control plane    │
                       │  - Admin API & metrics aggregation   │
                       └──────────────────┬───────────────────┘
                                          │ Post config updates
         ┌────────────────────────────────┼────────────────────────────────┐
         ▼                                ▼                                ▼
┌──────────────────┐             ┌──────────────────┐             ┌──────────────────┐
│ Worker Thread 1  │             │ Worker Thread 2  │             │ Worker Thread N  │
│ (epoll event loop│             │ (epoll event loop│             │ (epoll event loop│
│  bound to CPU 0) │             │  bound to CPU 1) │             │  bound to CPU N) │
└────────┬─────────┘             └────────┬─────────┘             └────────┬─────────┘
         │                                │                                │
  Non-blocking I/O               Non-blocking I/O               Non-blocking I/O
         │                                │                                │
  Accepted Sockets                Accepted Sockets                Accepted Sockets
```

**Key Operational Characteristics:**
* **No Cross-Thread Locks on Data Path:** Each worker thread runs an independent `epoll()` loop handling a non-overlapping subset of TCP client connections. Connections are assigned to worker threads by `SO_REUSEPORT` kernel socket balance or main-thread listener socket distribution.
* **Non-Blocking I/O:** Buffers are managed via watermark memory chunks (`evbuffer`-style). If a downstream client is slow, memory buffers hit high-watermarks, triggering backpressure up to the upstream cluster socket without blocking the event loop.

#### Dynamic Configuration via xDS APIs

Instead of static configuration files requiring process restarts, Envoy fetches infrastructure topology dynamically via gRPC stream APIs (**xDS**):

```
┌──────────────────────────────┐                ┌──────────────────────────────┐
│  Control Plane (Istio /      │   gRPC Stream  │         Envoy Proxy          │
│  Linkerd / Custom Control)   ├───────────────►│          Data Plane          │
└──────────────────────────────┘                └──────────────────────────────┘
  1. LDS (Listener Discovery)  ───────────────► Configures IP:Port sockets & TLS
  2. RDS (Route Discovery)     ───────────────► Configures HTTP path -> Cluster maps
  3. CDS (Cluster Discovery)   ───────────────► Configures upstream backend pools
  4. EDS (Endpoint Discovery)  ───────────────► Configures IP:Port of backend pods
```

**SRE Warning — xDS Propagation Lag:** When an application pod restarts, Endpoint Discovery Service (EDS) must propagate the IP removal. If client Envoy proxies receive traffic before EDS updates, they route requests to dead pod IPs resulting in `503 Service Unavailable / NR (No Route)` spikes.

---

### 2. Service Mesh Latency Overhead & mTLS Tax

Adding a Service Mesh (Istio, Linkerd) injects two sidecar proxy hops into every internal RPC request:

```
[ Pod A: App ] ──(Unix Socket/Loopback)──► [ Pod A: Envoy ] 
                                                   │
                                            mTLS over TCP (Internet/VPC)
                                                   │
[ Pod B: App ] ◄──(Unix Socket/Loopback)─── [ Pod B: Envoy ]
```

#### Breakdown of Service Mesh Latency Penalty

| Overhead Stage | Source of Delay | Latency Cost (p50) | Latency Cost (p99) |
| :--- | :--- | :--- | :--- |
| **Userspace / Kernel Hop** | TCP loopback / iptables redirection (`PREROUTING` / `OUTPUT` hooks) | 0.1ms | 0.5ms |
| **L7 Parsing & Filter Chain** | HTTP/2 or gRPC header framing, route matching, telemetry | 0.3ms | 1.2ms |
| **mTLS Handshake & Encryption** | Asymmetric ECDHE key exchange (if new conn) + AES-256-GCM framing | 0.5ms (warm) / 4ms (cold) | 2.5ms (warm) / 15ms (cold) |
| **Total Added Mesh Latency** | Cumulative across BOTH client and server sidecars | **~1.8ms** | **~5.5ms** |

#### Mitigating the mTLS Cryptographic Tax

1. **Symmetric Crypto Hardware Acceleration (AES-NI):** Ensure host CPU flags expose `aes` and `pclmulqdq`. Modern CPUs process AES-GCM at <1 cycle per byte.
2. **Session Resumption & TLS 1.3:** TLS 1.3 reduces the handshake to **1 RTT** (or 0-RTT via PSK). Ensure Envoy downstream/upstream TLS contexts enable session ticketing (`tls_session_ticket_keys`).
3. **HTTP/2 & gRPC Connection Multiplexing:** Keep upstream connections alive infinitely (`max_connection_duration: 0s`) to amortize the asymmetric handshake cost over millions of requests.

---

### Staff

### 3. eBPF & Cilium Kernel Bypass

Traditional Linux networking relies on `iptables` and the netfilter kernel subsystem. In Kubernetes clusters with thousands of services, `iptables` rules scale $O(N)$ linearly: every incoming packet must evaluate thousands of sequential `iptables` evaluation chains.

#### The iptables Bottleneck vs eBPF Acceleration

```
TRADITIONAL LINUX IPSTACK (iptables / netfilter):
Packet -> NIC -> Driver -> SoftIRQ -> ip_rcv -> netfilter (PREROUTING) -> iptables linear evaluation -> Routing -> Socket Queue
[ High CPU overhead, linear O(N) lookup penalty, lock contention ]

eBPF (Cilium XDP / Socket Layer Enforcement):
Packet -> NIC -> XDP eBPF Program (Direct Driver Level) -> Hash Lookup O(1) -> Direct Socket Delivery / Redirect
[ Zero netfilter traversal, BPF map O(1) lookups, bypasses IP stack ]
```

#### eBPF `sockmap` Bypassing for Local Proxies

When Envoy sits as a sidecar inside the same pod as the application container, traffic between App and Envoy normally traverses the Linux TCP stack twice:

```
WITHOUT eBPF (Standard Loopback):
App -> L7 Socket -> TCP Stack -> Loopback Interface -> TCP Stack -> L7 Socket -> Envoy
[ 2x TCP stack traversal, checksum calculations, buffer allocation ]

WITH eBPF sockmap (Cilium Accelerator):
App -> L7 Socket ───────(eBPF BPF_MAP_TYPE_SOCKMAP Direct Memory Transfer)───────► Envoy
[ Completely bypasses TCP/IP stack code paths inside the kernel ]
```

**SRE Impact:** Cilium `sockmap` acceleration reduces sidecar latency overhead by **30-50%** and cuts proxy CPU utilization in half by avoiding netfilter evaluation and TCP checksum re-computations for intra-node/intra-pod traffic.

---

### Principal Stretch

### 4. Overlay Networks vs. Direct Routing & MTU Encapsulation Mechanics

Pod-to-pod communication across nodes requires either **Overlay Encapsulation** or **Direct VPC Routing**.

```
OVERLAY NETWORK (VXLAN / Geneve):
┌─────────────────────────────────────────────────────────────────────────┐
│ Outer IP (Node IP) │ Outer UDP (Port 4789) │ VXLAN Header │ Inner Packet│
│       20 Bytes     │        8 Bytes        │   8 Bytes    │ (Pod traffic│
└─────────────────────────────────────────────────────────────────────────┘
◄───────────────────── 50 Bytes Overhead ─────────────────────────►
```

#### MTU Misconfiguration & Path MTU Discovery (PMTUD) Failure

If the underlying physical network MTU is `1500` bytes:
* Max Inner Pod Packet Payload = $1500 - 50 = 1450$ bytes.
* If pod interface MTU is misconfigured to `1500`:
  * Packets carrying 1500-byte payloads become **1550 bytes** post-VXLAN encapsulation.
  * Outer network interfaces drop packets if the `DF` (Don't Fragment) flag is set.
  * If `DF` is not set, the host kernel must split each packet into two fragments, causing massive CPU overhead and latency spikes.

```
DIAGNOSING VXLAN MTU DROPS:
# Test ping from pod with DF flag set:
ping -M do -s 1422 <target-pod-ip>  # 1422 payload + 28 IP/ICMP = 1450 MTU -> PASSES
ping -M do -s 1472 <target-pod-ip>  # 1472 payload + 28 IP/ICMP = 1500 MTU -> FAILS (Packet bigger than MTU)
```

#### Cloud VPC CNI Limits (AWS VPC CNI / Azure CNI)

Direct routing CNIs attach native Cloud Virtual Network Interfaces (ENIs) directly to instances:

$$\text{Max Pods Per Node} = (\text{Max ENIs Per Instance Type} \times (\text{IPs Per ENI} - 1)) + 1$$

**AWS EC2 Example (`m5.2xlarge`):**
* Max ENIs: `4`
* IPv4 Addresses per ENI: `15`
* Max Pods = $(4 \times (15 - 1)) + 1 = 57$ pods.

**SRE Failure Mode — IP Exhaustion & Warm Pool Exhaustion:**
When nodes scale up rapidly, the AWS CNI daemon (`aws-k8s-cni`) requests secondary IPs from AWS EC2 APIs. If the AWS EC2 API rate limits the cluster (`RequestLimitExceeded`), or the VPC subnet runs out of available IPs, newly scheduled pods freeze indefinitely in `ContainerCreating` status with `FailedCreatePodSandBox` events.

## Decision Framework

```
NETWORKING ARCHITECTURE QUICK CHOOSER:

  Need L7 HTTP routing, gRPC retries, JWT auth?     → Envoy Proxy Sidecar (Istio/Linkerd)
  Need zero-overhead packet filtering / firewall?    → eBPF / Cilium XDP
  Need max pod-to-pod mesh performance?             → eBPF sockmap acceleration + Envoy
  Overlay choice: Native Cloud Subnet Routing?       → AWS/Azure VPC CNI (Direct Routing)
  Overlay choice: Multi-cloud / heterogenous host?  → VXLAN / Geneve (Tune Pod MTU = Fabric MTU - 50)
```

---

## 🛑 SOCRATIC CHECK — STOP AND THINK

**Question 1:** Your Kubernetes cluster uses Istio with Envoy sidecars. A critical gRPC service reports intermittent `503 Service Unavailable` errors with `NR` (No Route) flags immediately following deployment rollouts. What specific control plane mechanism is lagging, and how do you resolve it?

**Question 2:** An SRE team enables mTLS mesh across a high-throughput microservices architecture. They notice pod CPU utilization jumps by 40%, but latency increases by 15ms per hop instead of the expected 1ms. `perf top` shows high CPU in `crypto/elliptic`. What is the root cause?

> **Socratic check answer key:**
> See [`../answers/Week-01-Transport-Application-Protocols-DNS-CDN/Cloud-Native-Networking-Answers.md`](../answers/Week-01-Transport-Application-Protocols-DNS-CDN/Cloud-Native-Networking-Answers.md).

---

## Production Failure Patterns

```
PATTERN 1: xDS STALE ENDPOINT ROUTING (503 NR SPIKES)
  Symptom:   HTTP 503 NR errors during pod autoscaling or deployment rollouts.
  Cause:     EDS updates lag behind Kubernetes endpoint deletion; Envoy routes to terminated IPs.
  Fix:       Configure `preStop` sleep hook (5-15s) in app container to drain traffic while xDS propagates.

PATTERN 2: VXLAN MTU BLACKHOLE
  Symptom:   TCP connections freeze on large API responses (TLS handshake stalls), small pings succeed.
  Cause:     Pod interface MTU set to 1500 on 1500 physical fabric; VXLAN 50-byte header exceeds MTU with DF bit set.
  Fix:       Set pod container interface MTU to 1450 (or 8950 on 9000 Jumbo Frame fabric).

PATTERN 3: AWS CNI ENI EXHAUSTION STALL
  Symptom:   Pods stuck in `ContainerCreating` with `FailedCreatePodSandBox` log messages.
  Cause:     Node subnet IP pool depleted or AWS EC2 API throttled `AssignPrivateIpAddresses`.
  Fix:       Use AWS CNI custom networking with secondary VPC subnets; tune `WARM_IP_TARGET` and `MIN_MINIMUM_IP_TARGET`.

PATTERN 4: MESH MTLS CRYPTOGRAPHIC HANDSHAKE STORM
  Symptom:   High CPU in sidecars; tail latency increases 10x under high connection churn.
  Cause:     Applications opening short-lived TCP connections instead of reusing HTTP/2 or gRPC persistent pools.
  Fix:       Enable HTTP/2 keepalive; configure connection pooling at client application level.
```

---

## SRE Diagnostic Toolkit

```bash
# Envoy Administrative CLI Commands (run from inside sidecar or container)
curl http://127.0.0.1:15000/stats | grep "cx_connect_fail\|ssl.handshake_failed"
curl http://127.0.0.1:15000/clusters | grep "health_flags"

# Inspecting Cilium eBPF Maps
cilium bpf tunnel list
cilium monitor --type drop

# PMTU & Packet Size Verification
tracepath <destination-pod-ip>
ip link show dev eth0 | grep mtu

# Prometheus Metrics to Monitor
envoy_cluster_upstream_cx_connect_timeout
envoy_cluster_membership_healthy
cilium_drop_count_total
```
