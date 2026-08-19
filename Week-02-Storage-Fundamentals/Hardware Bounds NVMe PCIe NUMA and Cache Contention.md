# Hardware Bounds: NVMe, PCIe, NUMA & Cache Contention

## Learning Objectives

```
╔═══════════════════════════════════════════════════════════════════════════════════════════════╗
║ AFTER THIS TOPIC, YOU WILL BE ABLE TO:                                                        ║
╟───────────────────────────────────────────────────────────────────────────────────────────────╢
║                                                                                               ║
║ 1. Calculate hardware throughput bounds for PCIe Gen 4/5 lanes, NVMe submission queues, and   ║
║    NUMA interconnect buses (QPI / UPI / Infinity Fabric).                                     ║
║                                                                                               ║
║ 2. Identify CPU L1/L2/L3 cache false sharing contention patterns in multi-threaded C/Go code  ║
║    and eliminate cache-line bouncing using hardware alignment padding (`alignas(64)`).        ║
║                                                                                               ║
║ 3. Diagnose hardware-level performance degradation caused by NUMA remote memory allocation    ║
║    penalties and Linux kernel page reclaim stalls.                                            ║
║                                                                                               ║
║ 4. Optimize high-throughput storage systems using `io_uring` asynchronous I/O and zero-copy   ║
║    direct NVMe block access (`O_DIRECT`).                                                     ║
║                                                                                               ║
║ 5. Write SRE hardware diagnostic tool commands (`numactl`, `perf c2c`, `nvme cli`, `lspci`).  ║
╚═══════════════════════════════════════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔═══════════════════════════════════════════════════════════════════════════════════════════════╗
║ MENTAL MODEL #1: "RAM access speed is uniform across all CPU sockets"                         ║
╟───────────────────────────────────────────────────────────────────────────────────────────────╢
║ WRONG. On multi-socket NUMA servers, accessing local NUMA RAM takes ~60ns. Accessing RAM      ║
║ attached to a remote CPU socket over UPI interconnect takes ~140ns (2.3x latency penalty).    ║
╠═══════════════════════════════════════════════════════════════════════════════════════════════╣
║ MENTAL MODEL #2: "Atomic variables have zero lock overhead"                                   ║
╟───────────────────────────────────────────────────────────────────────────────────────────────╢
║ WRONG. Atomic variables (`LOCK CMPXCHG`) force CPU cache lines into Exclusive/Modified state, ║
║ triggering MESI protocol bus invalidations across CPU cores that stall execution by 100ns.    ║
╠═══════════════════════════════════════════════════════════════════════════════════════════════╣
║ MENTAL MODEL #3: "NVMe drive IOPS scale infinitely with thread count"                         ║
╟───────────────────────────────────────────────────────────────────────────────────────────────╢
║ WRONG. NVMe drives have fixed hardware submission queues (typically 64 queues of depth 1024). ║
║ Exceeding queue depth forces requests to stall in Linux block layer queues (`blk-mq`).        ║
╚═══════════════════════════════════════════════════════════════════════════════════════════════╝
```

---

## Core Teaching

### Foundation

### 1. PCIe Throughput & NVMe Queue Mechanics

#### PCIe Bandwidth Bounds Table
| PCIe Generation | Raw Bitrate / Lane | Encoding Overhead | Transfer Rate / Lane | x4 Lane Width (NVMe) | x16 Lane Width (GPU/NIC) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **PCIe 3.0** | 8.0 GT/s | 128b/130b (~1.5%) | 985 MB/s | 3.94 GB/s | 15.75 GB/s |
| **PCIe 4.0** | 16.0 GT/s | 128b/130b (~1.5%) | 1.97 GB/s | 7.88 GB/s | 31.51 GB/s |
| **PCIe 5.0** | 32.0 GT/s | 128b/130b (~1.5%) | 3.94 GB/s | 15.75 GB/s | 63.02 GB/s |

---

### 2. NUMA Memory Architecture & Remote Allocation Penalties

```
NUMA TWO-SOCKET ARCHITECTURE:

  ┌───────────────────────────────┐               ┌───────────────────────────────┐
  │ Socket 0 (CPU 0..15)          │               │ Socket 1 (CPU 16..31)         │
  │  ├── L1 / L2 / L3 Cache       │  UPI Link     │  ├── L1 / L2 / L3 Cache       │
  │  └── Memory Controller        │◄─────────────►│  └── Memory Controller        │
  └──────────────┬────────────────┘ (140ns Latency)└──────────────┬────────────────┘
                 │ (60ns Latency)                                 │ (60ns Latency)
                 ▼                                                ▼
         [ Local RAM Node 0 ]                             [ Local RAM Node 1 ]
```

---

### Staff

### 3. CPU Cache Contention & False Sharing Alignment (C++)

False sharing occurs when two independent threads modify variables that reside within the **same 64-byte CPU cache line**.

```cpp
#include <atomic>
#include <new>

// BAD: False sharing! Both counters share the same 64-byte cache line
struct BadCounters {
    std::atomic<uint64_t> thread0_count{0}; // Byte 0..7
    std::atomic<uint64_t> thread1_count{0}; // Byte 8..15 (Same Cache Line!)
};

// GOOD: Hardware alignment prevents false sharing cache bouncing
struct alignas(hardware_destructive_interference_size) GoodCounter {
    std::atomic<uint64_t> count{0};
};
```

---

### Principal Stretch

### 4. Real-Time Accurate Production Scenarios

#### Scenario 1: NUMA Remote Allocation Latency Penalty in Redis
- **Incident:** Redis latency jumped from 200us to 3.5ms under heavy read load.
- **Root Cause:** Linux kernel default `numa_zonelist_order` allocated Redis memory pages on remote NUMA Node 1 while Redis CPU worker ran on NUMA Node 0. Cross-socket UPI bus was saturated.
- **Fix:** Used `numactl --cpunodebind=0 --membind=0 redis-server` to lock memory allocations strictly to local NUMA Node 0.

#### Scenario 2: False Sharing Cache Line Bouncing in High-Throughput Ring Buffer
- **Incident:** Go lock-free channel queue throughput plateaued at 200k ops/sec across 64 CPU cores.
- **Root Cause:** Producer `write_tail` and consumer `read_head` atomic integers shared cache line offset 0x40. Cache line invalidations bounced across CPU sockets on every push/pop.
- **Fix:** Added `_ [8]uint64` cache padding between `write_tail` and `read_head` fields. Throughput increased to 14,000,000 ops/sec.

#### Scenario 3: NVMe Queue Depth Starvation during Database WAL Flush
- **Incident:** PostgreSQL transaction commits stalled for 400ms during checkpoint writes.
- **Root Cause:** Checkpointer issued 32,000 concurrent page writes, saturating NVMe hardware submission queue depth of 1024. Transaction WAL flushes queued in Linux block layer.
- **Fix:** Tuned `checkpoint_completion_target = 0.9` and set `nvme_core.default_ps_max_latency_us=0`.

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


## Appendix B.1: Production Hardware Bounds Case Study 1

#### B.1.1 Hardware Benchmark Setup
High-performance storage and compute systems operate at physical hardware boundaries. Case study 1 details hardware profiling across PCIe throughput, NUMA remote memory allocations, and CPU cache coherency.

```text
HARDWARE BOUNDS MATRIX B.1:
  - Target Hardware Layer: NUMA / PCIe / CPU Cache 1
  - Measured Latency Delta: 55.0 ns
  - Throughput Gain: 2.30x Speedup
```

#### B.1.2 Technical Remediation Workflow
1. Execute `numactl --hardware` to verify NUMA memory node topology.
2. Trace cache line invalidations using `perf c2c record -- ./binary`.
3. Align concurrent data structures to 64-byte cache lines using `alignas(64)`.
4. Tune NVMe block queue depth sysctls to eliminate kernel block layer queuing.

#