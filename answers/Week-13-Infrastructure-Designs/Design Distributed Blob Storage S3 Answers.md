# Design Distributed Blob / Object Storage (AWS S3 / GCS) — Worked Answers

## Answer 1: Fixed Chunk Size (64MB) Architecture Rationale

1. **Metadata Scale Reduction**:
   If every file were arbitrary in size, a 50GB file would require tracking thousands of variable-length extents, or a 1KB file would waste disk sector allocation. 64MB balances metadata entry count with chunk transfer efficiency.
2. **Predictable Rebalancing & Striping**:
   Fixed chunk sizes make storage node disk capacity allocation trivial ($N$ slots of 64MB). Distributing 64MB chunks across storage nodes guarantees uniform disk utilization without fragmentation.
3. **Optimized Erasure Coding**:
   Reed-Solomon encoding works over uniform block matrices. Splitting into 64MB chunks allows parallel SIMD hardware acceleration (AVX-512) over 8MB shards.

---

## Answer 2: Incomplete Multipart Upload Lifecycle & Garbage Collection

1. **Orphaned Chunk Leakage**:
   When a client disconnects midway through a 50GB upload, uploaded parts (e.g. 30GB of chunks) occupy physical disk space on Chunk Nodes. Because `CompleteMultipartUpload` was never called, no user-visible object exists.
2. **Bucket Lifecycle Policy Abort Trigger**:
   Production systems enforce an automated lifecycle rule: `AbortIncompleteMultipartUpload` (typically after 7 days).
3. **Two-Phase Garbage Collection**:
   - The metadata service scans the `multipart_uploads` table for `created_at < NOW() - 7 days`.
   - Sends tombstone deletion commands to the Chunk Placement Master, freeing physical chunk slices.

---

## Answer 3: Low-Impact Background Bit-Rot Scrubbing

1. **Storage Node Local Scrubbing**:
   Scrubbing runs locally on each Chunk Node rather than over the network. The node computes the CRC32C / BLAKE3 hash of stored chunk blocks.
2. **cgroups I/O Weight Throttling**:
   Scrubbing processes run under Linux `cgroups v2` with `io.weight = 10` (minimum priority) or using `ionice -c 3` (idle priority), yielding disk head movements to live customer reads.
3. **Time-Windowed Pacing**:
   Each drive scrubs a fraction of its blocks per hour (e.g. 1 / 720th of capacity per hour) so that the entire drive is scrubbed once every 30 days without exceeding 2% disk I/O utilization.
4. **Correction Escalation**:
   If a local CRC mismatch is detected, the Chunk Node alerts the Placement Master, which schedules a background Cauchy Reed-Solomon reconstruction from healthy peer shards.
