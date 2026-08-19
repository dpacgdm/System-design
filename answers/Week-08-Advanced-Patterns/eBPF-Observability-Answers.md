# eBPF Observability — Socratic Check Answer Key

## Question 1: Low CPU Utilization with High p99 Latency

**Answer:**
No, JSON decoding does **NOT** explain the 3.5-second p99 latency.
* Because CPU utilization is only 4%, On-CPU activity (including JSON decoding) represents a minuscule fraction of real wall-clock time (e.g., 40ms of CPU time over a 1000ms window). Standard `pprof` only samples when CPU cores are executing instructions, so it correctly reports that *of the tiny CPU time consumed*, JSON decoding is 90%. But it is blind to the remaining 3.46 seconds of wall-clock time!
* **How eBPF Off-CPU Profiling Reveals the Culprit:** An eBPF Off-CPU profiler hooks into Linux `finish_task_switch` kernel tracepoints. It measures the total time threads spend in non-running states (`TASK_UNINTERRUPTIBLE` or `TASK_INTERRUPTIBLE`). An Off-CPU Flame Graph will show wide towers corresponding to the 3.46s block—typically pointing directly to `sys_futex` (mutex contention waiting for a DB connection), `ext4_file_write_iter` (synchronous disk flushing), or network socket read blocks.

---

## Question 2: Inaccuracy of User-Space Signals (`SIGPROF`) vs. eBPF Kernel Hooks

**Answer:**
User-space signal-based profiling (`SIGPROF`) is fundamentally limited and unsafe for Off-CPU analysis for three core reasons:

1. **Signal Delivery Bias (On-CPU Only):** Operating system signals (`SIGPROF`) can only be delivered to a thread when it is running on a CPU core or returning from a system call. If a thread is sleeping or blocked on a kernel futex (`TASK_UNINTERRUPTIBLE`), the kernel defers signal delivery until the thread wakes up. As a result, user-space profilers miss the entire duration of the blocked state.
2. **Signal Overhead and Degradation:** Generating user-space signals at high frequency (e.g., thousands of times per second across 100 threads) forces expensive kernel-to-user-space context switches and signal handler executions, causing 5%–15% CPU overhead and altering system behavior (observer effect).
3. **eBPF Kernel Advantage:** eBPF code executes *inside* the kernel scheduler context in nanoseconds. When `finish_task_switch` occurs, eBPF calculates the timestamp delta directly inside BPF maps without waking up user-space processes or issuing OS signals. It achieves zero-copy, 100% accurate Off-CPU measurement at < 0.5% CPU overhead.


---
