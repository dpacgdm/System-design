# Week 11, Topic 2: Design Online Judge and Cloud Runtime Platform

---

## Learning Objectives
```
╔════════════════════════════════════════════════════════════════════════════╗
║   AFTER THIS MODULE, YOU WILL BE ABLE TO:                                  ║
╟────────────────────────────────────────────────────────────────────────────╢
║                                                                            ║
║   1. Formulate latency, throughput, and security requirements for executing║
║      100,000+ untrusted multi-language user submissions daily              ║
║                                                                            ║
║   2. Architect a scalable asynchronous evaluation pipeline decoupling      ║
║      HTTP submission ingestion from sandboxed worker node execution        ║
║                                                                            ║
║   3. Master Linux kernel sandboxing primitives: namespaces, cgroups v2     ║
║      (memory.max, cpu.max, pids.max), seccomp-bpf, and chroot/pivot_root   ║
║                                                                            ║
║   4. Evaluate multi-tenant isolation tradeoffs: standard Docker vs gVisor  ║
║      (user-space kernel) vs AWS Firecracker (KVM-based microVMs)           ║
║                                                                            ║
║   5. Defend against malicious code attacks: fork bombs, infinite loops,    ║
║      network exfiltration, memory exhaustion, and host filesystem escapes  ║
╚════════════════════════════════════════════════════════════════════════════╝
```

---

## Section 2: Wrong Mental Models (Destroy These First)

```
╔══════════════════════════════════════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Execute user code directly in worker using exec()"                               ║
╟──────────────────────────────────────────────────────────────────────────────────────────────────────╢
║   WRONG. Running untrusted code in a host process gives attackers full root                          ║
║   access to host files, environment variables, network sockets, and credentials.                     ║
║   Any shell command can wipe the disk or pivot deeper into internal VPCs.                            ║
╠══════════════════════════════════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "Standard Docker containers provide bulletproof sandboxing"                       ║
╟──────────────────────────────────────────────────────────────────────────────────────────────────────╢
║   WRONG. Docker shares the host Linux kernel. A single kernel privilege-escalation                   ║
║   vulnerability (Dirty COW, namespace breakout) allows an attacker to compromise                     ║
║   the entire physical host. Untrusted multi-tenant code requires hypervisor or microkernel isolation.║
╠══════════════════════════════════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "Spin up a fresh cold microVM on demand for each submission"                      ║
╟──────────────────────────────────────────────────────────────────────────────────────────────────────╢
║   WRONG. Cold VM boot time (2-5 seconds) crushes interactive grading latency where                   ║
║   a 50ms user program expects sub-second verdicts. Production judges maintain pre-warmed             ║
║   idle sandbox pools and utilize snapshot-restore mechanisms (< 10ms).                               ║
╠══════════════════════════════════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "Kill runaway execution using sleep and kill -9 process timeouts"                 ║
╟──────────────────────────────────────────────────────────────────────────────────────────────────────╢
║   WRONG. A fork bomb spawns 50,000 child processes in milliseconds before a                          ║
║   SIGKILL can target the root PID, starving host OS thread tables. Strict                            ║
║   kernel cgroup limits (pids.max) are mandatory to reject process creation.                          ║
╠══════════════════════════════════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Pass large test case payloads directly inside the task queue"                    ║
╟──────────────────────────────────────────────────────────────────────────────────────────────────────╢
║   WRONG. Putting 50MB test cases in Kafka/RabbitMQ saturates queue brokers and                       ║
║   causes severe consumer lag. Worker nodes fetch and cache test cases locally on                     ║
║   NVMe SSDs, reading test data directly into memory pipes for the sandbox.                           ║
╚══════════════════════════════════════════════════════════════════════════════════════════════════════╝
```

---

## Section 3: Requirements & Sizing Calculations

### 1. Functional Requirements

```
FUNCTIONAL REQUIREMENTS (Interview Scope):
  P0 — Core Requirements:
    → Multi-Language Execution: Support Python 3, C++20, Java 17, Go, Rust.
    → Hidden Test Case Evaluation: Feed stdin to user code and validate stdout against expected answers.
    → Strict Resource Caps: Enforce deterministic Time Limit (TLE, e.g. 1.0s) and Memory Limit (MLE, e.g. 256MB).
    → Accurate Verdict Reporting: AC (Accepted), WA (Wrong Answer), TLE, MLE, CE (Compile Error), RE (Runtime Error).
    → Asynchronous Status Updates: Client submits code and receives real-time progress via WebSocket or SSE.

  P1 — Desirable Features:
    → Interactive Problem Support: Bidirectional streaming between user process and judge evaluator.
    → Contest Bursts: Gracefully handle massive concurrent submission spikes during coding contest deadlines.
```

### 2. Capacity Sizing (Back-of-the-Envelope)

| Factor | Metric | Baseline / Average | Peak Load (5x Contest Surge) | Daily Volume |
| :--- | :--- | :--- | :--- | :--- |
| **1. Submissions** | Submission Rate | ~20 submissions/sec | ~100 submissions/sec | ~1.7M submissions / day |
| **2. Active Sandboxes** | Concurrency (2s avg run) | 40 concurrent sandboxes | 200 concurrent sandboxes | Peak execution capacity |
| **3. Compute Capacity** | Sandboxed Execution Nodes| 5 hosts (16 vCPU, 64GB) | 20 hosts (Auto-scaled pool) | Scale-out worker fleet |
| **4. Test Case Bandwidth**| Test data I/O per problem| ~2 MB avg (50MB max) | 200 MB/s aggregate read | 99% hit rate on NVMe cache |
| **5. Result Latency** | End-to-end Verdict P95 | < 1.5 seconds | < 3.0 seconds | Instant student feedback |

---

## Section 4: High-Level Design (HLD) Box-and-Arrow

```
                     ONLINE JUDGE & CODE EXECUTION PLATFORM — HLD
                     ════════════════════════════════════════════

   ┌────────────────────┐
   │ Student / User IDE │
   └─────────┬──────────┘
             │ (1) POST /api/v1/submissions {problem_id, language, code}
             ▼
   ┌─────────────────────────────────┐
   │ API Gateway & Rate Limiter      │ ──► Rejects spam, checks auth & active contest quotas
   └─────────┬───────────────────────┘
             │
             ▼
   ┌─────────────────────────────────┐      ┌─────────────────────────────────┐
   │ Submission Ingestion Service    │ ───► │ Primary PostgreSQL Database     │
   │ - Validates payload syntax      │      │ - Stores submission record:     │
   │ - Assigns submission_id         │      │   {id, status: PENDING, code}   │
   │ - Publishes task to Queue       │      └─────────────────────────────────┘
   └─────────┬───────────────────────┘
             │
             │ (2) Publish execution event
             ▼
   ┌─────────────────────────────────┐
   │ Distributed Task Queue          │ (Partitioned by language or problem tier)
   │ (RabbitMQ / Kafka / Redis List) │
   └─────────┬───────────────────────┘
             │
             │ (3) Long-poll consumer pull
             ▼
   ┌─────────────────────────────────┐      ┌─────────────────────────────────┐
   │ Worker Dispatcher / Scheduler   │ ───► │ S3 Problem Test Case Store      │
   │ - Tracks idle sandbox pool      │      │ - test_cases/{prob_id}/in_{i}   │
   │ - Dispatches task to worker host│      │ - test_cases/{prob_id}/out_{i}  │
   └─────────┬───────────────────────┘      └──────────────┬──────────────────┘
             │                                             │ (Cached locally)
             ▼                                             ▼
   ┌──────────────────────────────────────────────────────────────────────────┐
   │ Sandboxed Execution Worker Host (Bare Metal / KVM)                       │
   │                                                                          │
   │  ┌────────────────────────┐  ┌────────────────────────────────────────┐  │
   │  │ Warm Sandbox Pool Mgr  │  │ Local Problem Cache (Fast NVMe RAMFS)  │  │
   │  │ (Pre-warmed instances) │  │ - Inputs / Expected outputs in memory  │  │
   │  └───────────┬────────────┘  └───────────────────┬────────────────────┘  │
   │              │                                   │                       │
   │              ▼                                   ▼                       │
   │  ┌────────────────────────────────────────────────────────────────────┐  │
   │  │ Sandboxed Container / MicroVM (gVisor / Firecracker)               │  │
   │  │  - Isolated Namespaces (pid, net, mnt, ipc, uts)                   │  │
   │  │  - Cgroups v2: memory.max=256M, cpu.max=100000, pids.max=32        │  │
   │  │  - Seccomp-BPF Filter: Whitelist read, write, exit (blocks socket) │  │
   │  │  - Read-only Root FS + Ephemeral tmpfs (16MB max)                  │  │
   │  │  - stdin < input.txt  ──►  [User Binary]  ──►  stdout > output.txt │  │
   │  └───────────────────────────────────┬────────────────────────────────┘  │
   │                                      │                                   │
   │                                      ▼                                   │
   │  ┌────────────────────────────────────────────────────────────────────┐  │
   │  │ Output Evaluator & Diff Engine                                     │  │
   │  │ - Compares stdout vs expected answer (tokens, floats, whitespace)  │  │
   │  │ - Evaluates: AC, WA, TLE, MLE, RE                                  │  │
   │  └───────────────────────────────────┬────────────────────────────────┘  │
   └──────────────────────────────────────┼───────────────────────────────────┘
                                          │
                                          │ (4) Publish result verdict
                                          ▼
   ┌─────────────────────────────────┐      ┌─────────────────────────────────┐
   │ Real-time Notification Service  │ ───► │ Client IDE (Live Verdict Stream)│
   │ (WebSocket / SSE via Redis)     │      │ Status: "Accepted (42ms, 18MB)" │
   └─────────────────────────────────┘      └─────────────────────────────────┘
```

### End-to-End Execution Flow

```
STEP 1: SUBMISSION INGESTION
  1. Client sends POST /submissions with source code.
  2. Ingestion Service writes record with status "QUEUED" in PostgreSQL.
  3. Emits message to Task Queue: `{submission_id, problem_id, language, code_s3_url}`.
  4. Client immediately receives 202 Accepted with submission_id and establishes SSE connection.

STEP 2: DISPATCH & SANDBOX ACQUISITION
  1. Worker daemon pulls job from queue.
  2. Claims a pre-warmed idle sandbox from its local warm pool (takes < 5ms).
  3. Verifies test cases for problem_id exist on local NVMe disk; fetches from S3 if absent.

STEP 3: COMPILATION & EXECUTION
  1. Compiled languages (C++, Rust): Runs compilation inside a build sandbox with 10s CPU limit.
     If compilation fails, immediately marks status "COMPILE_ERROR" and returns compiler stderr.
  2. Worker mounts compiled binary and input data into execution sandbox.
  3. Spawns process under cgroups v2 resource limits and restrictive seccomp filter.
  4. Pipes input to stdin and captures stdout and stderr up to a 16MB buffer cap.

STEP 4: VERDICT EVALUATION & CLEANUP
  1. Evaluator diffs generated output against ground truth.
  2. Records peak memory consumption and user CPU cycles from cgroup counters.
  3. Destroys or recycles the sandbox environment back to fresh pristine state.
  4. Updates PostgreSQL with final metrics and pushes verdict to client via SSE.
```

---

## Section 5: Core Technical Deep Dives (Interview Focus)

### Deep Dive 1: The Isolation Spectrum — Docker vs gVisor vs Firecracker

```
┌─────────────────┬──────────────────────┬──────────────────────┬──────────────────────┐
│ Attribute       │ Standard Docker      │ Google gVisor        │ AWS Firecracker      │
├─────────────────┼──────────────────────┼──────────────────────┼──────────────────────┤
│ Virtualization  │ OS-level namespaces  │ User-space Kernel    │ Hardware-assisted    │
│ Architecture    │ & cgroups (shared)   │ (Sentry intercepts)  │ MicroVM (Linux KVM)  │
├─────────────────┼──────────────────────┼──────────────────────┼──────────────────────┤
│ Startup Latency │ ~300ms - 800ms       │ ~50ms - 100ms        │ ~5ms - 15ms          │
│                 │                      │ (Warm: < 5ms)        │ (Snapshot: < 5ms)    │
├─────────────────┼──────────────────────┼──────────────────────┼──────────────────────┤
│ Security Blast  │ HIGH RISK: Host      │ LOW RISK: Intercepts │ ZERO SHARED KERNEL:  │
│ Radius          │ kernel shared; zero- │ 300+ syscalls in Go; │ True hypervisor VM;  │
│                 │ day escape risk      │ can't touch host OS  │ guest kernel isolated│
├─────────────────┼──────────────────────┼──────────────────────┼──────────────────────┤
│ Syscall Overhead│ Near zero (native)   │ Medium (Go syscall   │ Low (direct KVM vCPU │
│                 │                      │ emulation overhead)  │ hardware execution)  │
├─────────────────┼──────────────────────┼──────────────────────┼──────────────────────┤
│ Best Fit In     │ Internal trusted     │ High-throughput web  │ Untrusted production │
│ Production      │ enterprise services  │ tasks, Python/NodeJS │ grading, C++/Rust    │
└─────────────────┴──────────────────────┴──────────────────────┴──────────────────────┘

SENIOR INTERVIEW RECOMMENDATION:
  "For high-volume online judges executing untrusted arbitrary user code:
   Deploy AWS Firecracker MicroVMs or gVisor (runsc). Avoid bare Docker containers.
   Firecracker boots a minimal Linux guest kernel in under 10 milliseconds, providing
   hardware-enforced virtualization security boundaries without the memory bloat of traditional VMs."
```

### Deep Dive 2: Linux Kernel Sandboxing Primitives in Action

```
HOW THE JUDGE ENFORCES LIMITS AT THE LINUX KERNEL LAYER:

1. RESOURCE QUOTAS VIA CGROUPS V2:
   /sys/fs/cgroup/judge_job_{id}/
     ├── memory.max = 268435456     # Hard cap: Exactly 256 MB RAM
     ├── memory.swap.max = 0        # Zero swap space permitted (instant OOM if exceeded)
     ├── cpu.max = 100000 100000    # Max 1.0 CPU core (100ms per 100ms window)
     └── pids.max = 32              # Maximum 32 concurrent processes/threads

2. SYSTEM CALL RESTRICTION VIA SECCOMP-BPF:
   Seccomp compiles a Berkeley Packet Filter program attached to the process via:
   prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &prog)
   
   → WHITELISTED SYSCALLS: read, write, fstat, mmap, mprotect, munmap, brk, exit_group.
   → BLOCKED (KILL_PROCESS):
     - socket, connect, bind, accept, listen  (Completely prevents network access)
     - clone, fork (if exceeding thread cap)  (Mitigates fork bombs)
     - reboot, ptrace, chown, setuid          (Prevents privilege escalation)

3. FILESYSTEM ISOLATION VIA PIVOT_ROOT & TMPFS:
   - Root filesystem mounted as READ-ONLY.
   - User scratch directory mounted as memory-backed tmpfs capped at 16MB.
   - Any attempt to write outside /tmp fails with Read-only file system error.
```

### Deep Dive 3: Pre-Warmed Pool Management & Snapshot Recycling

```
THE COLD START LATENCY BOTTLENECK:
  Booting a runtime environment from scratch takes 500ms - 2000ms.
  If an online judge does this for every submission, response latency degrades unacceptably.

THE PRE-WARMED POOL ARCHITECTURE:
  1. Worker maintains a localized pool of 10-20 "ready-to-execute" sandboxes per node.
  2. A daemon continuously monitors pool watermarks:
     - High Watermark: 20 warm sandboxes
     - Low Watermark: 5 warm sandboxes
  3. When a submission arrives:
     - Worker pops a pre-warmed sandbox instantly (< 2ms).
     - Injects user binary into ephemeral tmpfs mount.
     - Executes tests, extracts metrics, and drains outputs.
  4. Sandbox Disposal vs Recycling:
     - Never reuse a contaminated sandbox environment!
     - The used sandbox is terminated in background.
     - Firecracker restores a fresh microVM instance from a clean memory snapshot in 5ms.
```

### Deep Dive 4: Accurate TLE (Time Limit Exceeded) vs Host Load Skew

```
WHY WALL-CLOCK TIME MEASUREMENT FAILS:
  If an evaluator uses `time.Now()` before and after process execution:
  - If another background process spikes CPU on the worker host, the user's process gets
    scheduled out by the Linux OS CFS scheduler.
  - A program that only needs 300ms of CPU execution might sit in the CPU run queue for 1200ms!
  - Result: Unfair false-positive "Time Limit Exceeded" verdicts for students!

SENIOR INTERVIEW SOLUTION:
  Read CPU cycles directly from the kernel cgroup accounting statistics:
  cat /sys/fs/cgroup/judge_job_{id}/cpu.stat
    usage_usec 42180   # Precise CPU time consumed in user & kernel space
    user_usec  38110   # User-space execution duration
    system_usec 4070   # Kernel-space execution duration

  → TLE is triggered ONLY when `usage_usec > time_limit_usec`.
  → Host scheduling latency and CPU throttling NEVER penalize the student's submission.
```

---

## Section 6: API Design & Data Models

### 1. REST & SSE APIs

```http
POST /api/v1/submissions
Content-Type: application/json
Idempotency-Key: "7b4c-9821-4fca"

{
  "problem_id": "two-sum",
  "language": "cpp20",
  "source_code": "#include <iostream>\\nint main() { ... }"
}
Response: 202 Accepted
{
  "submission_id": "sub_88192a",
  "status": "QUEUED",
  "sse_url": "/api/v1/submissions/sub_88192a/stream"
}

GET /api/v1/submissions/sub_88192a/stream
Accept: text/event-stream

event: status
data: {"status": "RUNNING", "test_case": 3, "total_cases": 15}

event: verdict
data: {"status": "ACCEPTED", "cpu_time_ms": 42, "memory_bytes": 18450000, "passed": 15, "total": 15}
```

### 2. Database Schema (Relational PostgreSQL)

```sql
CREATE TABLE submissions (
    submission_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    problem_id VARCHAR(64) NOT NULL,
    language VARCHAR(16) NOT NULL,
    source_code_url VARCHAR(512) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'QUEUED', -- QUEUED, COMPILING, RUNNING, COMPLETED
    verdict VARCHAR(20),                          -- ACCEPTED, WRONG_ANSWER, TLE, MLE, CE, RE
    cpu_time_ms INT,
    memory_kb INT,
    compile_error_log TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_user_submissions ON submissions (user_id, created_at DESC);
CREATE INDEX idx_pending_submissions ON submissions (status) WHERE status IN ('QUEUED', 'RUNNING');

CREATE TABLE problem_test_cases (
    case_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    problem_id VARCHAR(64) NOT NULL,
    case_number INT NOT NULL,
    input_s3_url VARCHAR(512) NOT NULL,
    expected_output_s3_url VARCHAR(512) NOT NULL,
    is_hidden BOOLEAN NOT NULL DEFAULT TRUE,
    time_limit_ms INT NOT NULL DEFAULT 1000,
    memory_limit_kb INT NOT NULL DEFAULT 262144,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (problem_id, case_number)
);
```

---

## Section 7: Failure Modes & Self-Healing Resilience

```
╔══════════════════════════════════════════════════════════════════════════════════════════════╗
║ FAILURE SCENARIO         │ DETECTION                   │ MITIGATION & RECOVERY               ║
╠══════════════════════════════════════════════════════════════════════════════════════════════╣
║ Fork Bomb Attack         │ cgroup pids.max breached    │ Kernel rejects fork()/clone();      ║
║ (:(){ :|:& };:)          │ task creation fails instantly sandbox exits with Runtime Error    ║
╠══════════════════════════════════════════════════════════════════════════════════════════════╣
║ Runaway Infinite Loop    │ cgroup cpu.stat quota meter │ Worker sends SIGXCPU, then          ║
║ (100% CPU hogging)       │ exceeds user time limit (1s)│ SIGKILL; records Time Limit Exceeded║
╠══════════════════════════════════════════════════════════════════════════════════════════════╣
║ Memory Allocation Spike  │ cgroup memory.current       │ Kernel OOM killer terminates        ║
║ (Exceeds 256MB limit)    │ exceeds memory.max limit    │ process immediately; records MLE    ║
╠══════════════════════════════════════════════════════════════════════════════════════════════╣
║ Network Exfiltration     │ Kernel network namespace    │ Worker runs sandbox in empty net    ║
║ (Malicious socket call)  │ egress packet blocked       │ namespace (no loopback, no eth0)    ║
╠══════════════════════════════════════════════════════════════════════════════════════════════╣
║ Worker Node Dies Mid-Run │ RabbitMQ / SQS lease ack    │ Unacknowledged task re-enqueued;    ║
║ (Host hardware crash)    │ visibility timeout expires  │ dispatched to healthy peer worker   ║
╚══════════════════════════════════════════════════════════════════════════════════════════════╝
```

---

## Section 8: Interview Tradeoffs & Architecture Matrix

```
┌────────────────────────┬──────────────────────────┬───────────────────────────────┐
│ System Decision        │ Options Considered       │ Senior Interview Choice       │
├────────────────────────┼──────────────────────────┼───────────────────────────────┤
│ Execution Isolation    │ Docker vs gVisor vs      │ Firecracker / gVisor. Bare    │
│                        │ Firecracker MicroVMs     │ Docker is unsafe for untrusted│
├────────────────────────┼──────────────────────────┼───────────────────────────────┤
│ Grading Architecture   │ Synchronous HTTP vs      │ Asynchronous Queue + SSE/WS.  │
│                        │ Asynchronous Queue + SSE │ Prevents gateway worker stalls│
├────────────────────────┼──────────────────────────┼───────────────────────────────┤
│ Test Case Delivery     │ Injected into Task Queue │ Cached on Worker NVMe from S3.│
│                        │ vs Local NVMe Node Cache │ Keeps queue payloads < 10KB.  │
├────────────────────────┼──────────────────────────┼───────────────────────────────┤
│ TLE Enforcement        │ Wall-clock time.Now() vs │ cgroups v2 cpu.stat counters. │
│                        │ Kernel cpu.stat usage    │ Immune to noisy neighbor load.│
└────────────────────────┴──────────────────────────┴───────────────────────────────┘
```

---

## Section 9: Interview Scenario Practice (Test Yourself)

```
Q1: "How do you guarantee an untrusted C++ program cannot read files or steal DB passwords from the host?"
TALKING POINTS:
  → Read-only filesystem root with chroot/pivot_root into an isolated empty jail directory.
  → Network namespace with no route configured: any socket() or connect() call is dropped by the kernel.
  → Drop all Linux capabilities (CAP_SYS_ADMIN, CAP_NET_RAW) and enforce seccomp-bpf filter.
  → MicroVM hardware boundary: code executes inside a distinct guest kernel; host memory is unreachable.

Q2: "How do you stop a user from launching a fork bomb (:(){ :|:& };:) that crashes the grading server?"
TALKING POINTS:
  → Attach the execution process tree to a dedicated cgroups v2 hierarchy with `pids.max = 32`.
  → When the fork bomb attempts to create its 33rd process, the clone() system call returns EAGAIN.
  → The code crashes immediately with a clean Runtime Error, consuming zero host thread table slots.

Q3: "Why is measuring elapsed wall-clock time bad for Time Limit Exceeded (TLE) verdicts?"
TALKING POINTS:
  → Wall-clock time includes context switching, I/O wait, and queueing delays caused by other host jobs.
  → In multi-tenant environments, a noisy neighbor could cause a correct O(N) solution to falsely get TLE.
  → Systems must meter exact user + kernel CPU execution time via cgroups `cpu.stat.usage_usec`.

Q4: "How do you handle massive spikes during coding contests when 10,000 users submit simultaneously?"
TALKING POINTS:
  → Decouple ingestion from execution via message brokers (Kafka/RabbitMQ) with high queue depth.
  → Rate limit submissions per user (max 1 submission per 10 seconds per problem).
  → Auto-scale the worker tier based on queue backlog depth (Lag Metric), spinning up spot worker VMs.
  → Graceful degradation: Run only sample test cases first to return quick feedback; queue full suites.

Q5: "How does the platform prevent memory limit bypass via memory mapping (mmap)?"
TALKING POINTS:
  → cgroups v2 enforces `memory.max` across all memory types: anonymous RAM, RSS, and page cache buffers.
  → Disable swap completely (`memory.swap.max = 0`) to prevent the program from spilling onto disk.
  → As soon as `memory.current` exceeds `memory.max`, the Linux kernel OOM killer fires immediately.
```
