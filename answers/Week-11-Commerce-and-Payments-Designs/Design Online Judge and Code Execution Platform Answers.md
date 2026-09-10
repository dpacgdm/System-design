# Design Online Judge & Code Execution Platform — Worked Answers

## Answer 1: Network Namespace Isolation Rationale

1. **VPC & Metadata Service Protection**:
   In cloud environments (AWS/GCP), instances can access the link-local metadata service at `http://169.254.169.254`. An untrusted submission with network access could query IAM role security credentials and assume full AWS account control.
2. **Network Exfiltration Defense**:
   Malicious actors could submit code to scan internal cluster ports (Redis, Postgres), exfiltrate private database data, or use judge worker CPU/bandwidth to participate in distributed denial-of-service (DDoS) botnets.
3. **Loopback Only Enforcement**:
   Running `ip netns add sandbox_isolated` without binding any physical or virtual Ethernet (`veth`) interface guarantees at the kernel routing layer that zero packets leave the process.

---

## Answer 2: Ephemeral State Reset in Warm Sandbox Pools

1. **The State Contamination Risk**:
   If User A leaves a file `/tmp/secret.txt` or spawns a detached background thread, User B executing in the same VM could read User A's source code or exploit the background process.
2. **Copy-on-Write (CoW) Root Filesystems**:
   Warm Firecracker microVMs are pre-booted from a clean, read-only base rootfs image (`base_root.ext4`).
   Each execution mounts an ephemeral `tmpfs` overlay or device-mapper snapshot for `/tmp` and `/run`.
3. **Instant Post-Execution Teardown**:
   Because Firecracker microVMs terminate in < 5ms, production platforms **never reuse** a microVM across different users. When execution finishes, the microVM is destroyed, and the warm pool manager immediately boots a fresh microVM in 15ms in the background to replenish the warm pool.

---

## Answer 3: Distinguishing SIGSEGV vs. Linux OOM-Killer

1. **Linux Exit Status Codes**:
   When a process terminates due to a signal, its exit status reflects `128 + signal_number`:
   - `SIGSEGV` (Segmentation Fault) is signal 11 $\rightarrow$ Exit status `139`.
   - `SIGKILL` (Forced Kill) is signal 9 $\rightarrow$ Exit status `137`.
2. **cgroups v2 OOM Event Inspection**:
   When a program exceeds its memory limit (e.g. 256MB), the Linux kernel `cgroup` OOM killer sends a `SIGKILL` (Exit 137). However, an external timeout script could also send a `SIGKILL`.
   To definitively identify an OOM condition:
   - Inspect `/sys/fs/cgroup/<sandbox>/memory.events`.
   - The kernel increments the `oom_kill` counter:
     ```bash
     cat /sys/fs/cgroup/sandbox_01/memory.events
     # oom 1
     # oom_kill 1
     ```
   If `oom_kill > 0`, the judge flags the verdict as **MLE (Memory Limit Exceeded)**; otherwise, exit 139 is flagged as **RE (Runtime Error / SIGSEGV)**.
