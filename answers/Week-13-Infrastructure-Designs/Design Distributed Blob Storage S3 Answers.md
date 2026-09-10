# Answer Key - Week 13: Design Distributed Blob Storage S3

> Open only after attempting the learner file scenario questions.

## Principal Model Answer & Interview Evaluation Matrix

```
╔══════════════════════════════════════════════════════════════════════════╗
║ PRINCIPAL MODEL ANSWER SUMMARY — DISTRIBUTED BLOB STORAGE S3             ║
╠══════════════════════════════════════════════════════════════════════════╣
║ 1. Decoupled metadata plane (Spanner/LSM) from chunk data plane.         ║
║ 2. Reed-Solomon Erasure Coding (8+4) cuts storage overhead by 66%.       ║
║ 3. Multipart uploads reassemble via zero-byte metadata pointer swaps.    ║
║ 4. Continuous CRC32C scrubbers proactively heal silent bit-rot.          ║
║ 5. Presigned direct uploads prevent application server memory exhaustion ║
╚══════════════════════════════════════════════════════════════════════════╝
```

---

## Detailed Model Solutions to Section 9 Practice Drills

### Q1: Why 64MB Chunk Sizes?
* **Failure Blast Radius:** Network errors or disk stalls affect only a 64MB slice rather than an entire multi-gigabyte object.
* **Storage Distribution:** Allows the Placement Master to pack storage efficiently across heterogeneous drives without creating massive skew.
* **Parallel Streaming:** Clients execute multi-threaded HTTP Range requests (`bytes=0-67108863`), streaming distinct chunks from distinct nodes concurrently.

### Q2: Reed-Solomon Mathematical Principles
* **Galois Field Matrix Multiplication:** Data vector $D = [d_1, \dots, d_K]$ is multiplied by generator matrix $G$ to produce codeword $C = [d_1, \dots, d_K, p_1, \dots, p_M]$.
* **Vandermonde Matrix Invertibility:** Any submatrix formed by taking $K$ surviving rows from $G$ is mathematically guaranteed to be invertible.
* **Reconstruction Cost:** Reading requires contacting any $K$ chunks; rebuilding a lost chunk requires reading $K$ chunks and computing matrix dot products.

### Q3: Multipart Upload Zero-Copy Internals
* **Parts as Independent Blobs:** Each part is assigned an independent chunk sequence during `UploadPart`.
* **Atomic Metadata Pointer Commit:** `CompleteMultipartUpload` creates a composite record in the metadata database mapping object key to ordered part chunk references. The physical storage nodes perform zero read/write operations during completion.

### Q4: Achieving 11 Nines of Durability
* **Durability Formula:** $P(	ext{loss}) = \sum_{i=M+1}^{K+M} inom{K+M}{i} p^i (1-p)^{K+M-i}$ where $p$ is probability of disk failure within the MTTR repair window.
* **MTTR Dominance:** Because rebuilds are parallelized across hundreds of nodes, a lost 8TB drive is reconstructed in $< 30 	ext{ minutes}$, keeping the concurrent failure window virtually non-existent.

### Q5: Presigned URL Security Mechanics
* **Signature String:** `StringToSign = HTTP-Verb + "
" + Expiry + "
" + CanonicalizedResource`.
* **Verification:** Gateway re-computes `HMAC-SHA256(SecretKey, StringToSign)` and verifies bitwise equality. If current timestamp $>$ Expiry, request is rejected with 403 Forbidden.
