# Answer Key - Week 11: Design Online Judge and Cloud Runtime Platform

> Open only after attempting the learner file scenario questions.

## Principal Model Answer & Interview Evaluation Matrix

```
╔═══════════════════════════════════════════════════════════════════════════╗
║ PRINCIPAL MODEL ANSWER SUMMARY — ONLINE JUDGE & RUNTIME PLATFORM          ║
╠═══════════════════════════════════════════════════════════════════════════╣
║ 1. Multi-tenant isolation via Firecracker MicroVMs / gVisor (no Docker)   ║
║ 2. Kernel cgroups v2 quotas: memory.max, pids.max, and cpu.max limits.    ║
║ 3. Seccomp-BPF filters whitelist read/write and drop all socket/net calls.║
║ 4. Accurate TLE metering via cgroup cpu.stat (immune to noisy neighbors). ║
║ 5. Pre-warmed sandbox pooling with snapshot restore delivers < 10ms boot. ║
╚═══════════════════════════════════════════════════════════════════════════╝
```

---

## Detailed Model Solutions to Section 9 Practice Drills

### Q1: Preventing Host File System & Credential Theft
* **Hypervisor Boundary:** Deploying workloads within Firecracker microVMs ensures that even an exploit achieving full root inside the guest OS remains trapped in the guest. The host physical RAM, file descriptors, and credentials remain isolated behind KVM hardware virtualization.
* **Network Blackholing:** Create each sandbox inside a fresh, unconfigured Linux network namespace (`ip netns add sandbox_net`). Without a default gateway or bridge interface, network calls immediately return `ENETUNREACH`.
* **Seccomp Filters:** Whitelist only minimal required execution syscalls (`read`, `write`, `fstat`, `exit_group`). Explicitly block `socket`, `bind`, `connect`, and `sys_chroot`.

### Q2: Fork Bomb Defense Mechanics
* **Cgroups v2 `pids.max`:** By setting `pids.max = 32`, the Linux kernel maintains an atomic count of all threads and child processes inside the control group.
* **System Call Rejection:** When `clone()` or `fork()` is executed and the count equals 32, the kernel immediately terminates the syscall and returns `-EAGAIN`.
* **Host Thread Protection:** The host operating system's PID allocation pool (`/proc/sys/kernel/pid_max`) is never touched, preventing server lockups.

### Q3: TLE Metering: Wall-Clock vs CPU Time
* **The Noisy Neighbor Dilemma:** Wall-clock time measures elapsed real-world time ($\Delta t = t_{	ext{end}} - t_{	ext{start}}$), including time spent waiting for the OS scheduler while other threads run.
* **cgroup `cpu.stat` Solution:** The kernel tracks precise execution time via CPU performance counters:
  $$	ext{Total CPU Time} = 	ext{user\_usec} + 	ext{system\_usec}$$
* **Deterministic Verdict:** A submission only receives a `Time Limit Exceeded` verdict when actual CPU time exceeds the allocation (e.g. $> 1,000,000 \mu	ext{s}$), eliminating flakiness.

### Q4: Contest Traffic Spikes & Auto-Scaling
* **Queue Decoupling:** Ingestion API returns HTTP 202 Accepted within 15ms. The user receives a submission ticket and polls or listens to an SSE channel.
* **Metric-Based Scaling:** Worker auto-scaler monitors Queue Lag ($	ext{Messages in Queue} / 	ext{Worker Processing Rate}$). If latency exceeds 5s, workers auto-scale on spot instances.
* **Two-Tier Grading:** First grade against 3 public sample test cases for immediate UI feedback; queue full grading (50 hidden test cases) asynchronously.

### Q5: Memory Limit Precision via Cgroups v2
* **Comprehensive Tracking:** Unlike POSIX `setrlimit(RLIMIT_AS)` which only measures virtual address space, cgroups v2 tracks actual physical resident memory plus page caches.
* **Zero Swap Enforcement:** By enforcing `memory.swap.max = 0`, the process cannot write dirty pages to swap space to circumvent limits.
* **Immediate OOM Notification:** As soon as memory reaches `memory.max`, the cgroup invokes the OOM killer, killing the rogue process instantly and alerting the evaluator daemon.
