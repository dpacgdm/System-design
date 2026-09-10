# Week 13, Topic 3: Design Distributed Blob Storage S3

---

## Learning Objectives
```
╔═════════════════════════════════════════════════════════════════════════╗
║   AFTER THIS MODULE, YOU WILL BE ABLE TO:                               ║
╟─────────────────────────────────────────────────────────────────────────╢
║                                                                         ║
║   1. Formulate functional and capacity requirements for a global-scale  ║
║      object store supporting 100PB+ data and 11 nines of durability     ║
║                                                                         ║
║   2. Design an HLD blueprint cleanly decoupling the low-latency Metadata║
║      Plane from the high-throughput Chunk Server Data Plane             ║
║                                                                         ║
║   3. Master Reed-Solomon Erasure Coding (K+M) vs 3-way replication to   ║
║      slash cloud infrastructure storage costs by up to 66%              ║
║                                                                         ║
║   4. Architect zero-copy multipart upload coordination and proactive    ║
║      background bit-rot scrubbing                                       ║
║                                                                         ║
║   5. Defend consistency models (read-after-write) and failure recoveries║
║      under disk, rack, and availability zone outages in interviews      ║
╚═════════════════════════════════════════════════════════════════════════╝
```

---

## Section 2: Wrong Mental Models (Destroy These First)

```
╔═══════════════════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Store files directly in PostgreSQL/MySQL as BLOBs"            ║
╟───────────────────────────────────────────────────────────────────────────────────╢
║   WRONG. Storing binary payloads in relational tables causes severe buffer        ║
║   pool pollution, massive WAL bloat, and crashes connection pools during          ║
║   large streaming transfers. Relational DBs store metadata; blobs go to disks.    ║
╠═══════════════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "Use 3-way replication for all petabytes of storage"           ║
╟───────────────────────────────────────────────────────────────────────────────────╢
║   WRONG. 3-way replication imposes a 200% storage overhead (300PB paid for        ║
║   100PB data). Production object stores use Reed-Solomon Erasure Coding (e.g. 8+4)║
║   achieving superior durability with only 50% storage overhead.                   ║
╠═══════════════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "Application servers buffer full 10GB uploads in RAM"          ║
╟───────────────────────────────────────────────────────────────────────────────────╢
║   WRONG. App servers would instantly run out of memory. Production systems        ║
║   stream chunks directly from the client to chunk storage nodes via presigned     ║
║   URLs and multipart upload sessions.                                             ║
╠═══════════════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "A POSIX file system (e.g. NFS) scales to trillions of files"  ║
╟───────────────────────────────────────────────────────────────────────────────────╢
║   WRONG. POSIX hierarchical directory locks, inodes, and file metadata operations ║
║   create extreme bottleneck serialization. Object stores use a flat key-value     ║
║   namespace backed by partitioned LSM-trees or distributed NoSQL.                 ║
╠═══════════════════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Disks never silently corrupt written data"                    ║
╟───────────────────────────────────────────────────────────────────────────────────╢
║   WRONG. Bit-rot occurs regularly due to cosmic rays, magnetic degradation,       ║
║   and firmware bugs. Systems must store cryptographic checksums (CRC32C) and      ║
║   run periodic background scrubbers to detect and heal corrupt blocks.            ║
╚═══════════════════════════════════════════════════════════════════════════════════╝
```

---

## Section 3: Requirements & Sizing Calculations

### 1. Functional Requirements

```
FUNCTIONAL REQUIREMENTS (Interview Scope):
  P0 — Core Requirements:
    → PutObject: Upload objects up to 5 TB with high throughput and durable persistence.
    → GetObject: Retrieve objects by bucket and key with low latency (< 100ms first byte).
    → DeleteObject: Remove objects or mark tombstone for soft delete / versioning.
    → Multipart Upload: Chunk uploads for files > 100 MB with resumable retry of parts.
    → Durability: 99.999999999% (11 nines) durability for stored objects.

  P1 — Desirable Features:
    → Presigned URLs: Allow clients to upload/download directly without passing through app servers.
    → Object Versioning: Maintain historical revisions of overwritten keys.
```

### 2. Capacity Sizing (Back-of-the-Envelope)

| Factor | Metric | Baseline / Average | Peak Load (3x Burst) | 1-Year Requirement |
| :--- | :--- | :--- | :--- | :--- |
| **1. Total Storage** | Usable Data Footprint | 100 Petabytes (PB) | 150 PB | ~150 PB raw with RS (8+4)|
| **2. Object Count** | Total Objects Stored | 10 Billion objects | 15 Billion | — |
| **3. Write Throughput**| PutObject Requests | ~5,000 req/sec | ~15,000 req/sec | ~432M uploads / day |
| **4. Read Throughput** | GetObject Requests | ~25,000 req/sec | ~75,000 req/sec | ~2.1B downloads / day |
| **5. Network Egress** | Read Bandwidth (1MB avg)| ~25 GB/sec Egress | ~75 GB/sec Egress | Requires 100GbE spines |

---

## Section 4: High-Level Design (HLD) Box-and-Arrow

```
                        DISTRIBUTED BLOB STORAGE — HLD BLUEPRINT
                        ════════════════════════════════════════

  ┌──────────────────┐           ┌──────────────────┐
  │ Client Web / App │           │ Enterprise S3 SDK│
  └────────┬─────────┘           └────────┬─────────┘
           │                              │
           └──────────────┬───────────────┘
                          │ HTTPS (PUT /bucket/video.mp4)
                          ▼
             ┌─────────────────────────┐
             │ API Gateway & Edge Auth │ ──► Validates IAM credentials & presigned signatures
             └────────────┬────────────┘
                          │
          ┌───────────────┴────────────────────────────────┐
          │ (1) Query Metadata & Placement                 │ (2) Stream Chunks Direct
          ▼                                                ▼
  ┌─────────────────────────────────┐              ┌─────────────────────────────────┐
  │ Metadata Service Plane          │              │ Data Plane: Chunk Gateway Fleet │
  │ - Distributed Key-Value Store   │              │ - Splits objects into 64MB chunks│
  │   (Spanner / Cassandra / RocksDB│              │ - Computes Reed-Solomon parity  │
  │ - Stores `{bucket, key}` ->     │              └──────────────┬──────────────────┘
  │   `[chunk_1, chunk_2 ...]`      │                             │
  └──────────────┬──────────────────┘                             │ (3) Scatter write chunks
                 │                                                ▼
                 │ (Coordinates placement)         ┌─────────────────────────────────┐
                 ▼                                 │ Chunk Storage Nodes (Fleet)     │
  ┌─────────────────────────────────┐              │ [Rack 1]  [Rack 2]  [Rack 3]    │
  │ Placement Master Cluster        │              │ Node A    Node B    Node C      │
  │ (Raft Consensus Coordinator)    │              │ (Local NVMe/HDD append-only fs) │
  │ - Tracks disk health & capacity │              └──────────────┬──────────────────┘
  │ - Schedules rebalancing & scrub │                             │
  └─────────────────────────────────┘                             ▼
                                                   ┌─────────────────────────────────┐
                                                   │ Background Scrubber & Healer    │
                                                   │ - Validates CRC32C checksums    │
                                                   │ - Rebuilds lost blocks from RS  │
                                                   └─────────────────────────────────┘
```

### End-to-End Data Flow

```
STEP 1: PUT OBJECT (Small Objects < 64MB)
  1. Client sends PUT /bucket/key with payload to Chunk Gateway.
  2. Gateway splits payload into K data chunks + M parity chunks (e.g. 8+4 Reed-Solomon).
  3. Gateway asks Placement Master for 12 healthy chunk nodes across distinct fault domains/racks.
  4. Gateway writes the 12 chunks in parallel to the selected Chunk Servers.
  5. Once a quorum (K=8) confirms durable write, Gateway registers chunk pointers in Metadata DB.
  6. Returns 200 OK with ETag (MD5/CRC32C).

STEP 2: GET OBJECT
  1. Client sends GET /bucket/key.
  2. API Gateway queries Metadata Service for chunk IDs and chunk server locations.
  3. Gateway contacts any K healthy chunk servers (e.g., 8 out of 12).
  4. Gateway reassembles raw bytes and streams them directly to client (first byte < 80ms).
```

---

## Section 5: Core Technical Deep Dives (Interview Focus)

### Deep Dive 1: 3-Way Replication vs Reed-Solomon Erasure Coding (K+M)

```
╔═══════════════════════════════════════════════════════════════════════════════════════════╗
║ STRATEGY             │ STORAGE OVERHEAD │ FAULT TOLERANCE          │ NETWORK & CPU COST   ║
╠═══════════════════════════════════════════════════════════════════════════════════════════╣
║ 3-Way Replication    │ 200% Overhead    │ Can lose ANY 2 nodes;    │ Zero CPU encoding;   ║
║ (3 identical copies) │ (100PB -> 300PB) │ 3rd failure causes loss  │ high network write   ║
╠═══════════════════════════════════════════════════════════════════════════════════════════╣
║ Reed-Solomon (8 + 4) │ 50% Overhead     │ Can lose ANY 4 nodes/    │ Requires Galois field║
║ (8 Data + 4 Parity)  │ (100PB -> 150PB) │ racks simultaneously!    │ CPU matrix math      ║
╠═══════════════════════════════════════════════════════════════════════════════════════════╣
║ Reed-Solomon (12 + 4)│ 33% Overhead     │ Can lose ANY 4 nodes/    │ Slightly higher      ║
║ (12 Data + 4 Parity) │ (100PB -> 133PB) │ racks simultaneously!    │ rebuild network cost ║
╚═══════════════════════════════════════════════════════════════════════════════════════════╝

RECOMMENDED SENIOR INTERVIEW TALKING POINTS:
  "For hot metadata or small files (< 1MB), use 3-way replication for lowest read latency.
   For all bulk blob data (> 95% of storage volume), use Reed-Solomon Erasure Coding (8+4).
   It slashes infrastructure storage costs from 300PB down to 150PB while providing vastly
   higher durability (survives 4 simultaneous rack failures vs only 2 in replication)."
```

### Deep Dive 2: Multipart Upload Coordination (Zero-Byte Copying)

```
HOW MULTIPART UPLOAD WORKS FOR 50GB FILES:

  1. Initiate Multipart Upload:
     Client calls POST /bucket/large-file.iso?uploads
     → Server creates unique `upload_id` and records state in metadata table.

  2. Parallel Part Upload:
     Client splits file into 500 parts of 100MB each.
     Client uploads parts in parallel using worker threads:
     PUT /bucket/large-file.iso?partNumber=1&uploadId=xyz
     PUT /bucket/large-file.iso?partNumber=2&uploadId=xyz
     → Each part is stored as independent chunks on chunk servers.
     → Failed parts are retried independently without restarting the entire 50GB file.

  3. Complete Multipart Upload:
     Client sends manifest: `{parts: [{part: 1, etag: "a"}, {part: 2, etag: "b"} ...]}`.
     → Metadata service atomically binds all part chunk pointers to the final key `large-file.iso`.
     → ZERO data copying or byte-reassembly occurs on disk! It is a pure metadata pointer swap.
```

### Deep Dive 3: Silent Data Corruption & Bit-Rot Scrubbing

```
THE BIT-ROT PROBLEM:
  Magnetic media and flash memory experience silent bit-flips without throwing OS I/O errors.
  If an unread chunk bit-flips, when a user requests it 2 years later, the data is corrupted.

THE BACKGROUND HEALING PROTOCOL:
  1. Checksum Verification: Every 64MB chunk is stored with a trailing CRC32C block checksum.
  2. Continuous Background Scrubber:
     - Worker daemon continuously cycles through all storage drives, reading chunks and
       verifying on-disk bytes against recorded CRC32C.
  3. Automatic Healing:
     - If chunk #3 fails CRC verification, it is flagged as corrupted.
     - Scrubber pulls remaining K=8 healthy chunks from other racks.
     - Reconstructs chunk #3 in memory using Reed-Solomon parity decoding.
     - Writes new healthy chunk to a fresh drive and updates metadata pointers.
```

### Deep Dive 4: Metadata Scalability & Prefix Sharding

```
PROBLEM:
  S3 provides strong read-after-write consistency.
  If billions of objects share the same bucket (e.g., `s3://bucket/2026/09/10/photo.jpg`):
  → Sequential timestamps cause all writes to hit the same partition/range key in the metadata DB!

SENIOR INTERVIEW SOLUTION:
  1. Distributed Partitioning via Consistent Hashing:
     Partition metadata store by `hash(bucket + key)` or partition prefixes.
  2. Bounded Prefix Limits:
     AWS S3 supports 3,500 PUT and 5,500 GET requests per second per prefix.
     If a single prefix gets hot, the metadata engine automatically splits the key range
     into sub-partitions transparently to maintain uniform throughput.
```

---

## Section 6: API Design & Data Models

### 1. REST APIs

```http
PUT /v1/{bucket}/{key}
Content-Type: application/octet-stream
x-amz-checksum-crc32c: 9a8f21bc
[Binary Payload]
Response: 200 OK { "ETag": ""9a8f21bc"", "version_id": "v1" }

GET /v1/{bucket}/{key}
Range: bytes=0-1048575  // Range request for first 1MB
Response: 206 Partial Content [Binary Bytes]

POST /v1/{bucket}/{key}?uploads
Response: 200 OK { "upload_id": "mp_9918ab" }

PUT /v1/{bucket}/{key}?partNumber=1&uploadId=mp_9918ab
Response: 200 OK { "ETag": ""part1_hash"" }

POST /v1/{bucket}/{key}?uploadId=mp_9918ab
Payload: { "parts": [{ "partNumber": 1, "ETag": ""part1_hash"" }] }
Response: 200 OK { "location": "https://s3.company.com/bucket/key" }
```

### 2. Database Schema (Metadata Key-Value Store)

```sql
CREATE TABLE object_metadata (
    bucket_name VARCHAR(64) NOT NULL,
    object_key VARCHAR(1024) NOT NULL,
    version_id VARCHAR(64) NOT NULL DEFAULT 'null',
    size_bytes BIGINT NOT NULL,
    checksum_crc32c VARCHAR(32) NOT NULL,
    storage_class VARCHAR(16) NOT NULL DEFAULT 'STANDARD',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (bucket_name, object_key, version_id)
);

CREATE TABLE object_chunks (
    chunk_id UUID PRIMARY KEY,
    bucket_name VARCHAR(64) NOT NULL,
    object_key VARCHAR(1024) NOT NULL,
    chunk_index INT NOT NULL,
    erasure_coding_m INT NOT NULL,  -- e.g. 4 parity chunks
    erasure_coding_k INT NOT NULL,  -- e.g. 8 data chunks
    chunk_size_bytes INT NOT NULL,
    chunk_servers_assigned JSONB NOT NULL -- ["rack1_node4", "rack2_node8" ...]
);
CREATE INDEX idx_chunks ON object_chunks (bucket_name, object_key);
```

---

## Section 7: Failure Modes & Self-Healing Resilience

```
╔═══════════════════════════════════════════════════════════════════════════════════════════╗
║ FAILURE SCENARIO         │ DETECTION                   │ MITIGATION & RECOVERY            ║
╠═══════════════════════════════════════════════════════════════════════════════════════════╣
║ Chunk Server Drive Dies  │ Heartbeat timeout (>15s)    │ Placement master schedules       ║
║ (Permanent Loss)         │ or repeated IO errors       │ reconstruction from parity blocks║
╠═══════════════════════════════════════════════════════════════════════════════════════════╣
║ Silent Bit-Rot On Disk   │ CRC32C checksum mismatch    │ Background scrubber detects bad  ║
║ (Corrupted Block)        │ during background scrub     │ chunk; rebuilds from RS parity.  ║
╠═══════════════════════════════════════════════════════════════════════════════════════════╣
║ Chunk Master Leader      │ Raft lease expires          │ Remaining coordinators elect new ║
║ Crashes                  │ missed keepalive > 3s       │ leader; load chunk map in memory ║
╠═══════════════════════════════════════════════════════════════════════════════════════════╣
║ Orphaned Multipart Parts │ Incomplete uploads older    │ Scheduled lifecycle policy drops ║
║ Never Completed          │ than 7 days                 │ unreferenced partial parts.      ║
╚═══════════════════════════════════════════════════════════════════════════════════════════╝
```

---

## Section 8: Interview Tradeoffs & Architecture Matrix

```
┌────────────────────────┬──────────────────────────┬───────────────────────────────┐
│ System Layer           │ Candidate Choices        │ Interview Recommendation      │
├────────────────────────┼──────────────────────────┼───────────────────────────────┤
│ Data Durability Engine │ 3-Way Replication vs     │ Erasure Coding (8+4) for bulk │
│                        │ Erasure Coding (8+4)     │ storage (50% overhead vs 200%)│
├────────────────────────┼──────────────────────────┼───────────────────────────────┤
│ Metadata Storage       │ Relational SQL vs        │ Distributed KV / LSM-tree for │
│                        │ Partitioned Key-Value    │ flat key scale & sub-ms reads.│
├────────────────────────┼──────────────────────────┼───────────────────────────────┤
│ Upload Architecture    │ App Proxy Upload vs      │ Direct-to-Storage presigned   │
│                        │ Presigned Direct Upload  │ upload avoids app OOM stalls. │
├────────────────────────┼──────────────────────────┼───────────────────────────────┤
│ Consistency Model      │ Eventual vs Strong       │ Strong read-after-write for   │
│                        │ Read-After-Write         │ PUTs/DELETEs (matches S3 2020)│
└────────────────────────┴──────────────────────────┴───────────────────────────────┘
```

---

## Section 9: Interview Scenario Practice (Test Yourself)

```
Q1: "Why does S3 split large files into 64MB chunks instead of storing a 5GB file as one file?"
TALKING POINTS:
  → Failure isolation: If a 5GB file transfer fails at 99%, the entire transfer is lost.
    With chunks, only the failed 64MB part is retried.
  → Parallelism: Chunks can be read and written in parallel across 100 independent storage nodes,
    saturating full network card bandwidth.
  → Storage packing: Small fixed chunk sizes prevent file system fragmentation on chunk drives.

Q2: "Explain Reed-Solomon Erasure Coding (8+4) in plain English to an interviewer."
TALKING POINTS:
  → Data is divided into 8 data blocks, and mathematical polynomials generate 4 parity blocks.
  → The 12 blocks are distributed across 12 distinct server racks.
  → ANY 8 of the 12 blocks can reconstruct the entire original file.
  → The system can survive losing ANY 4 storage nodes or racks simultaneously with only 50% overhead.

Q3: "How does Multipart Upload avoid copying gigabytes of data when completing an upload?"
TALKING POINTS:
  → Zero-copy pointer reassembly: When parts are uploaded, they are already written as durable chunks.
  → The `CompleteMultipartUpload` API simply writes a new metadata record referencing the list of
    already-written chunk IDs. Zero disk I/O occurs during completion.

Q4: "How do you achieve 11 nines (99.999999999%) of data durability in production?"
TALKING POINTS:
  → Geographic and rack failure domain separation (spreading RS blocks across multiple AZs/racks).
  → Proactive continuous background bit-rot scrubbing with CRC32C validation.
  → Mean Time to Repair (MTTR): Automatic re-replication starts within 15 seconds of drive failure,
    rebuilding missing blocks before a second failure can occur.

Q5: "How do you support presigned URLs securely without passing credentials to the client?"
TALKING POINTS:
  → HMAC-SHA256 signature generated by server using IAM secret key.
  → Query string embeds expiration timestamp, HTTP method, bucket, and cryptographic signature.
  → Storage gateway validates HMAC signature on request; rejects if expired or tampered with.
```
