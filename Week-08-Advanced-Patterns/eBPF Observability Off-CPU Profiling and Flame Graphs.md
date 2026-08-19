# eBPF Observability: Off-CPU Profiling, Flame Graphs & Continuous Profiling

## Learning Objectives

```
╔═══════════════════════════════════════════════════════════════════════════╗
║ AFTER THIS TOPIC, YOU WILL BE ABLE TO:                                    ║
╟───────────────────────────────────────────────────────────────────────────╢
║                                                                           ║
║ 1. Explain the mechanical difference between On-CPU sampling and          ║
║    Off-CPU latency profiling via eBPF kernel scheduler instrumentation.   ║
║                                                                           ║
║ 2. Read and interpret CPU & Off-CPU Flame Graphs to diagnose mutex        ║
║    contention, page fault stalls, and disk I/O bottlenecks.               ║
║                                                                           ║
║ 3. Compare continuous profiling tools (Parca, Pyroscope, Cilium Hubble)   ║
║    against runtime sampling (`pprof`, `async-profiler`) overhead.         ║
║                                                                           ║
║ 4. Write C-based eBPF BPF_PERF_OUTPUT maps to trace Linux kernel          ║
║    `finish_task_switch` events without overhead.                          ║
║                                                                           ║
║ 5. Diagnose production latency anomalies where CPU utilization is 5%      ║
║    but p99 response times explode to seconds.                             ║
╚═══════════════════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔══════════════════════════════════════════════════════════════════════════════╗
║ MENTAL MODEL #1: "Low CPU utilization means my service has no bottleneck"    ║
╟──────────────────────────────────────────────────────────────────────────────╢
║ WRONG. Threads spends most of their time waiting (Off-CPU) on lock           ║
║ contention, block I/O, network socket reads, or memory page fault stalls.    ║
║ A thread blocked in `TASK_UNINTERRUPTIBLE` state burns 0% CPU but introduces ║
║ massive user-facing latency.                                                 ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ MENTAL MODEL #2: "Standard pprof continuous sampling catches all slowdowns"  ║
╟──────────────────────────────────────────────────────────────────────────────╢
║ WRONG. Runtime profilers (like Go `pprof` or Java `jstack`) sample thread    ║
║ stack traces when threads are RUNNING on a CPU core. If a thread is blocked  ║
║ on a futex or disk read, standard sampling profilers omit it entirely.       ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ MENTAL MODEL #3: "eBPF continuous profiling degrades production latency"     ║
╟──────────────────────────────────────────────────────────────────────────────╢
║ WRONG. eBPF bytecode executes inside the Linux kernel in JIT-compiled C-like ║
║ instructions using zero-copy BPF ring buffers. Overhead is typically < 0.5%  ║
║ CPU, compared to 5–15% overhead for user-space signal-based profilers.       ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

---

## Core Teaching

### Foundation

> Staff / Principal stretch sections are marked below. Mastery gate: Staff required; Principal optional.

### 1. On-CPU vs. Off-CPU Profiling Mechanics

#### On-CPU Profiling
On-CPU profiling measures **where CPU cycles are spent**. The kernel fires a timer interrupt (e.g., 99 Hz) to sample the Instruction Pointer (IP) and call stack of currently executing threads.

$$\text{On-CPU Time} = \text{Samples in function } F \times \text{Sample Interval}$$

#### Off-CPU Profiling
Off-CPU profiling measures **time threads spend waiting while blocked**. The kernel hooks into the scheduler event (`finish_task_switch`) to measure the exact nanoseconds a thread remains in non-running states (`TASK_INTERRUPTIBLE` or `TASK_UNINTERRUPTIBLE`).

```
THREAD SCHEDULER STATE TRANSITION:

  [ RUNNING (On-CPU) ] ─────────── Block on Mutex / Disk / Socket ───────────► [ OFF-CPU (Waiting) ]
         ▲                                                                               │
         └──────────────── Context Switch Back (`finish_task_switch`) ───────────────────┘
                                   Duration = Off-CPU Latency (ns)
```

---

### 2. Interpreting Flame Graphs

Flame graphs visualize hierarchical call stacks:
- **X-axis:** Alphabetical sorting of function stack traces (width = total time/samples).
- **Y-axis:** Call stack depth (bottom = root entry point, top = leaf function).

```
OFF-CPU FLAME GRAPH EXAMPLE:

  ┌─────────────────────────────────────────────────────────┐
  │ sys_futex  [Width = 70% of total latency - LOCK STALL]  │
  ├─────────────────────────────────────────────────────────┤
  │ pthread_mutex_lock                                      │
  ├─────────────────────────────────────────────────────────┤
  │ DatabaseConnectionPool::GetConnection                   │
  ├─────────────────────────────────────────────────────────┤
  │ HandleHTTPRequest                                       │
  └─────────────────────────────────────────────────────────┘
```

---

### Staff

### 3. Continuous Profiling Architecture (Parca / Pyroscope / eBPF)

```
CONTINUOUS PROFILING ARCHITECTURE:

  ┌─────────────────────────────────────────────────────────┐
  │ Kubernetes Worker Node                                  │
  │  ┌───────────────────────────────────────────────────┐  │
  │  │ eBPF Agent (Parca Agent / Pyroscope eBPF)         │  │
  │  │  - Attaches kprobe: finish_task_switch            │  │
  │  │  - Collects stack traces into BPF perf map        │  │
  │  └────────────────────────┬──────────────────────────┘  │
  └───────────────────────────┼─────────────────────────────┘
                              │ Push Stack Traces (gRPC / OTLP)
                              ▼
  ┌─────────────────────────────────────────────────────────┐
  │ Continuous Profiling Storage Engine (Parca / Pyroscope) │
  │  - Columnar storage (Parquet / TSDB)                    │
  │  - Symbolication engine (DWARF / Go symbol tables)      │
  │  - Query Engine (Diff flame graphs across deployments)  │
  └─────────────────────────────────────────────────────────┘
```

---

### Principal Stretch

### 4. Writing an eBPF Off-CPU Kernel Tracer in C

```c
#include <uapi/linux/ptrace.h>
#include <linux/sched.h>

struct key_t {
    u32 pid;
    u64 kernel_ip;
};

BPF_HASH(start, u32, u64);
BPF_HISTOGRAM(dist);

// Hooked into kernel scheduler: finish_task_switch
int trace_offcpu(struct pt_regs *ctx, struct task_struct *prev) {
    u32 pid = prev->pid;
    u64 ts = bpf_ktime_get_ns();

    // Store timestamp when thread goes off-CPU
    start.update(&pid, &ts);
    return 0;
}

int trace_oncpu(struct pt_regs *ctx) {
    u32 pid = bpf_get_current_pid_tgid();
    u64 *tsp, delta;

    tsp = start.lookup(&pid);
    if (tsp != 0) {
        delta = bpf_ktime_get_ns() - *tsp;
        start.delete(&pid);

        // Store off-cpu duration delta into log2 histogram
        dist.increment(bpf_log2l(delta / 1000)); // in microseconds
    }
    return 0;
}
```

---

## Decision Framework

```
PROFILING METHODOLOGY CHOOSER:

  CPU usage is 95-100%, services slow?          → On-CPU Profiling (eBPF / pprof)
  CPU usage is < 10%, p99 latency exploding?    → Off-CPU Profiling (eBPF scheduler hooks)
  Profiling production Kubernetes clusters?      → Continuous eBPF Profiler (Parca / Pyroscope)
  Profiling JVM GC pauses / lock allocation?     → async-profiler + eBPF hybrid
```

---

## 🛑 SOCRATIC CHECK — STOP AND THINK

**Question 1:** A microservice handling payment transactions shows 4% CPU utilization, but p99 HTTP latency is 3.5 seconds. Standard Go `pprof` shows `net/http` spending 90% of On-CPU time in JSON decoding. Does JSON decoding explain the 3.5s latency? How does eBPF Off-CPU profiling reveal the true culprit?

**Question 2:** Why is profiling Off-CPU latency with user-space signals (`SIGPROF`) inherently unsafe and inaccurate compared to eBPF `finish_task_switch` kernel tracepoints?

> **Socratic check answer key:**
> See [`../answers/Week-08-Advanced-Patterns/eBPF-Observability-Answers.md`](../answers/Week-08-Advanced-Patterns/eBPF-Observability-Answers.md).

---

## Production Failure Patterns

```
PATTERN 1: MUTEX CONTENTION THUNDERING HERD
  Symptom:   High p99 latency with low CPU usage after adding database connection pool.
  Cause:     Threads blocking in `TASK_UNINTERRUPTIBLE` waiting on connection pool lock.
  Fix:       Off-CPU flame graph isolates `mutex_lock` call site; refactor to lock-free ring buffer or bucketed pools.

PATTERN 2: MAJOR PAGE FAULT DISK STALLS
  Symptom:   Latency spikes whenever memory usage approaches node limit.
  Cause:     Linux page reclaimer (kswapd) swapping anonymous memory to disk; threads block in `do_anonymous_page`.
  Fix:       Off-CPU profile identifies page fault wait states; disable swap / set `vm.swappiness=0`.
```

---

## SRE Diagnostic Toolkit

```bash
# Measure Off-CPU time using bcc-tools offcputime
offcputime-bpfcc -df -p $(pgrep my_service) 30 > offcpu.stacks

# Render Off-CPU Flame Graph
flamegraph.pl --color=io offcpu.stacks > offcpu_flamegraph.svg
```
