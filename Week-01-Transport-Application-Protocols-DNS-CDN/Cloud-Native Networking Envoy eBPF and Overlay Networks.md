# Cloud-Native Networking: Envoy, eBPF & Overlay Networks

## Learning Objectives

```
╔═══════════════════════════════════════════════════════════════════════════════════════════════╗
║ AFTER THIS TOPIC, YOU WILL BE ABLE TO:                                                        ║
╟───────────────────────────────────────────────────────────────────────────────────────────────╢
║                                                                                               ║
║ 1. Explain the mechanical difference between iptables packet interception and Cilium eBPF     ║
║    socket layer bypass (`sockmap` / `sockhash`).                                              ║
║                                                                                               ║
║ 2. Architecture Envoy xDS dynamic control plane pipelines (ADS, CDS, EDS, LDS, RDS) for       ║
║    zero-downtime service mesh configuration updates.                                          ║
║                                                                                               ║
║ 3. Calculate network packet overhead and MTU fragmentation math for VXLAN and Geneve          ║
║    encapsulated overlay networks.                                                             ║
║                                                                                               ║
║ 4. Diagnose production incidents such as eBPF conntrack table exhaustion, Envoy worker thread ║
║    lock contention, and MTU mismatch packet drops.                                            ║
║                                                                                               ║
║ 5. Implement production eBPF programs for socket-level load balancing and Envoy sidecar       ║
║    acceleration.                                                                              ║
╚═══════════════════════════════════════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔═══════════════════════════════════════════════════════════════════════════════════════════════╗
║ MENTAL MODEL #1: "Kube-proxy iptables rules scale linearly with pod count"                    ║
╟───────────────────────────────────────────────────────────────────────────────────────────────╢
║ WRONG. `iptables` uses sequential rule processing ($O(N)$ lookup). With 10,000 services,      ║
║ evaluating 50,000 iptables rules per packet burns 30% of system CPU and incurs 2ms latency.   ║
╠═══════════════════════════════════════════════════════════════════════════════════════════════╣
║ MENTAL MODEL #2: "Envoy sidecar proxy adds zero latency overhead"                             ║
╟───────────────────────────────────────────────────────────────────────────────────────────────╢
║ WRONG. Traversing user-space Envoy proxies requires two TCP socket traversals and 4 context   ║
║ switches per request. Without eBPF `sockmap` bypass, sidecars add 1.5ms - 3.0ms p99 latency.  ║
╠═══════════════════════════════════════════════════════════════════════════════════════════════╣
║ MENTAL MODEL #3: "Overlay network encapsulation has no MTU impact"                            ║
╟───────────────────────────────────────────────────────────────────────────────────────────────╢
║ WRONG. VXLAN adds a 50-byte header overhead (Outer Ethernet + IP + UDP + VXLAN). Setting      ║
║ pod interface MTU to 1500 instead of 1450 forces IP packet fragmentation, dropping gRPC.      ║
╚═══════════════════════════════════════════════════════════════════════════════════════════════╝
```

---

## Core Teaching

### Foundation

### 1. eBPF Socket Layer Bypass (`sockmap` / `sockhash`)

Standard service mesh sidecars route local pod traffic through the Linux TCP/IP stack twice:

```
STANDARD INTERCEPTION (iptables - 4 Context Switches + Full TCP Stack):
  Pod App Socket ──► TCP Stack ──► iptables PREROUTING ──► Loopback ──► Envoy Socket
                          │                                                 │
  Envoy Socket ◄── Loopback ◄── iptables POSTROUTING ◄── TCP Stack ◄────────┘

CILIUM eBPF BYPASS (sockmap - Direct Kernel Socket Buffer Transfer):
  Pod App Socket ──► [ eBPF BPF_MAP_TYPE_SOCKMAP ] ──► Envoy Socket (Zero TCP Overhead!)
```

#### eBPF `sockmap` Redirection C Code

```c
#include <vmlinux.h>
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_endian.h>

struct {
    __uint(type, BPF_MAP_TYPE_SOCKMAP);
    __uint(max_entries, 65535);
    __type(key, u32);
    __type(value, u64);
} sock_map SEC(".maps");

SEC("sk_skb/stream_verdict")
int bpf_stream_verdict(struct __sk_buff *skb) {
    u32 key = skb->remote_port;
    // Direct kernel-level socket redirection, bypassing host TCP stack
    return bpf_sk_redirect_map(skb, &sock_map, key, 0);
}

char LICENSE[] SEC("license") = "GPL";
```

---

### 2. Envoy xDS Dynamic Control Plane Architecture

Envoy uses the xDS gRPC API to dynamically update cluster configurations without restarting proxy processes:

```
ENVOY xDS CONTROL PLANE PIPELINE:

  xDS Control Plane (Istio / Kuma / Custom Go Control Plane)
       │ gRPC Stream (Aggregated Discovery Service - ADS)
       ▼
  ┌─────────────────────────────────────────────────────────┐
  │ Envoy Proxy                                             │
  │  ├── LDS (Listener Discovery Service)   : Port/IP Binds │
  │  ├── RDS (Route Discovery Service)      : HTTP Routes   │
  │  ├── CDS (Cluster Discovery Service)    : Upstream Pools│
  │  └── EDS (Endpoint Discovery Service)   : IP Addresses  │
  └─────────────────────────────────────────────────────────┘
```

---

### Staff

### 3. VXLAN & Geneve Packet Encapsulation Math

VXLAN encapsulates Layer 2 Ethernet frames inside Layer 4 UDP packets:

```
VXLAN PACKET HEADER OVERHEAD:

  [ Outer Ethernet (14B) ] [ Outer IP (20B) ] [ Outer UDP (8B) ] [ VXLAN Header (8B) ] [ Inner Frame ]
  └───────────────────────────────── 50 Bytes Overhead ──────────────────────────────┘
```

#### MTU Calculation Formula
For a physical network interface with standard MTU of 1500 bytes:

$$\text{Pod Interface MTU} = \text{Physical MTU} - \text{Encapsulation Overhead}$$

$$\text{Pod MTU (VXLAN)} = 1500 - 50 = 1450 \text{ bytes}$$

$$\text{Pod MTU (Geneve + Options)} = 1500 - 64 = 1436 \text{ bytes}$$

---

### Principal Stretch

### 4. Real-Time Accurate Production Scenarios

#### Scenario 1: Cilium eBPF Conntrack Table Exhaustion under SYN Flood
- **Incident:** Kubernetes API Server dropped 60% of incoming requests during load spike.
- **Root Cause:** Default eBPF conntrack map size (`bpf_ct_global7_max = 262144`) filled up during 100k QPS connection burst, causing eBPF kernel drops.
- **Fix:** Increased `bpf-ct-global-any-max` to 2,097,152 and tuned `bpf-ct-timeout-tcp-translated` to 60s.

#### Scenario 2: VXLAN MTU Mismatch Packet Fragmentation Dropping gRPC Traffic
- **Incident:** Microservice HTTP/1.1 calls succeeded, but gRPC streaming API calls hung indefinitely.
- **Root Cause:** Container network interface MTU was configured to 1500. Large gRPC payload packets exceeded 1500 bytes after VXLAN header addition; network firewalls dropped IP fragments with `DF` (Don't Fragment) bit set.
- **Fix:** Updated Cilium CNI MTU configuration to `1450` bytes across all worker nodes.

#### Scenario 3: Envoy Worker Thread Lock Contention under 100k HTTP/2 Streams
- **Incident:** Envoy sidecar CPU reached 100% while upstream service CPU was 10%.
- **Root Cause:** 100,000 HTTP/2 multiplexed streams shared a single Envoy upstream cluster lock.
- **Fix:** Enabled Envoy `use_remote_address` and sharded upstream cluster connection pools across CPU worker threads using `concurrency: auto`.

#

---

## Decision Framework

| Requirement / Scenario | Recommended Technology / Pattern | Key Trade-off / Bottleneck | Primary Telemetry Signal |
| :--- | :--- | :--- | :--- |
| Ultra-low latency microservice routing | eBPF Socket Layer Bypass (`sockmap`) | BPF map size bounds | Socket buffer drop count |
| Dynamic multi-cluster routing | Envoy xDS ADS Control Plane | xDS gRPC stream CPU overhead | CDS/EDS update latency |
| Pod network encapsulation | VXLAN / Geneve Overlay | 50-byte MTU header overhead | Interface packet drops |

---

## 🛑 SOCRATIC CHECK — STOP AND THINK

**Question 1:** Why does setting container interface MTU to 1500 bytes inside a VXLAN overlay network cause gRPC streaming calls to hang intermittently while short HTTP GET requests succeed?

**Question 2:** Why is iptables sequential packet evaluation ($O(N)$) fundamentally unsuited for large-scale Kubernetes clusters with 10,000+ services compared to Cilium eBPF socket maps?

> **Socratic check answer key:**
> See corresponding answer key in `answers/` directory.

---

## Production Failure Patterns

```
PATTERN 1: OVERLAY MTU MISMATCH FRAGMENTATION
  Symptom:   gRPC streaming calls hang or fail with connection timeouts; HTTP/1.1 calls succeed.
  Cause:     Container MTU set to 1500; VXLAN adds 50B header exceeding host 1500 MTU; IP fragments dropped with DF bit.
  Fix:       Set container interface MTU to 1450 bytes.

PATTERN 2: EBPF CONNTRACK MAP EXHAUSTION
  Symptom:   Kubernetes services reject incoming connections under load spikes.
  Cause:     High rate of short-lived TCP connections fills eBPF conntrack hash map.
  Fix:       Increase `bpf-ct-global-any-max` to 2,097,152 and tune TCP translation timeouts.
```

---

## SRE Diagnostic Toolkit

```bash
# 1. Trace kernel eBPF socket map lookup latency
bpftrace -e 'kprobe:bpf_sk_redirect_map { @[ustack] = count(); }'

# 2. Inspect Cilium eBPF conntrack map usage
cilium bpf ct list global

# 3. Check MTU configuration across pod interfaces
ip link show dev eth0
```


## Appendix B.1: Production Cloud-Native Network Case Study 1

#### B.1.1 Scenario Description
In high-density Kubernetes clusters, packet processing efficiency directly dictates microservice response times. Case study 1 documents network optimization across eBPF socket maps, Envoy proxy sidecars, and VXLAN overlays.

```text
NETWORK OPERATIONAL MATRIX B.1:
  - Target Component: Envoy / Cilium eBPF Subsystem 1
  - Interception Mechanism: BPF_MAP_TYPE_SOCKMAP Bypass
  - Latency Reduction: 1.60 ms p99
  - Packet Overhead: 50 Bytes VXLAN Header
```

#### B.1.2 Technical Remediation Workflow
1. Audit iptables packet traversal latency vs eBPF socket map lookup latency.
2. Deploy Cilium eBPF CNI with Host-Reachable Services enabled.
3. Configure Envoy xDS ADS control plane to stream incremental Endpoint updates.
4. Verify MTU configuration across pod interfaces and physical host NICs.

#