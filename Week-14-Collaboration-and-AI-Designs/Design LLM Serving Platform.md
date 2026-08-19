# Design LLM Serving Platform

> Week 14, Topic 2 — System Design. Production-grade multi-tenant Large Language Model (LLM) inference platform: continuous batching, vLLM PagedAttention KV cache management, speculative decoding, multi-GPU parallelism (Tensor vs Pipeline), multi-LoRA routing, and semantic caching.

---

## Learning Objectives

```
╔═══════════════════════════════════════════════════════════════════════════╗
║ AFTER THIS MODULE, YOU WILL BE ABLE TO:                                   ║
╟───────────────────────────────────────────────────────────────────────────╢
║                                                                           ║
║ 1. Calculate GPU memory footprint for model weights and KV cache using    ║
║    exact parameter precision, sequence length, and batch size math.       ║
║                                                                           ║
║ 2. Apply the Roofline Model to diagnose Prefill (Compute-Bound) vs        ║
║    Decode (Memory-Bandwidth Bound) inference bottlenecks.                 ║
║                                                                           ║
║ 3. Design vLLM-style PagedAttention virtual memory page tables to         ║
║    eliminate internal/external fragmentation and enable prefix caching.   ║
║                                                                           ║
║ 4. Quantify Tensor Parallelism (TP over NVLink) vs Pipeline Parallelism   ║
║    (PP over InfiniBand) communication latency bounds.                     ║
║                                                                           ║
║ 5. Implement Speculative Decoding with draft-model verification math and  ║
║    Semantic Vector Caching to reduce p99 inter-token latency (ITL).       ║
╚═══════════════════════════════════════════════════════════════════════════╝
```

---

## Wrong Mental Models (Destroy These First)

```
╔═════════════════════════════════════════════════════════════════════════════════╗
║ MENTAL MODEL #1: "LLM inference is pure GPU compute-bound"                      ║
╟─────────────────────────────────────────────────────────────────────────────────╢
║ WRONG. Only the Prefill phase (prompt processing) is compute-bound. The         ║
║ Decode phase (token generation) is strictly memory-bandwidth bound. Each        ║
║ generated token requires loading gigabytes of KV cache and weights from HBM     ║
║ to GPU SRAM, operating at a low Arithmetic Intensity (FLOPs per byte).          ║
╠═════════════════════════════════════════════════════════════════════════════════╣
║ MENTAL MODEL #2: "Static batching yields maximum GPU throughput"                ║
╟─────────────────────────────────────────────────────────────────────────────────╢
║ WRONG. Requests have variable prompt and generation lengths. Static batching    ║
║ forces the GPU to pad shorter requests with zero-tokens until the longest       ║
║ request completes, wasting over 50% of GPU compute and memory bandwidth.        ║
╠═════════════════════════════════════════════════════════════════════════════════╣
║ MENTAL MODEL #3: "KV Cache memory fragmentation is negligible"                  ║
╟─────────────────────────────────────────────────────────────────────────────────╢
║ WRONG. Naive contiguous allocation pre-allocates memory for maximum sequence    ║
║ length (e.g., 8192 tokens). Actual allocations waste 60-80% of GPU HBM in       ║
║ virtual fragmentation, triggering premature out-of-memory (OOM) evictions.      ║
╠═════════════════════════════════════════════════════════════════════════════════╣
║ MENTAL MODEL #4: "Tensor Parallelism scales infinitely across nodes"            ║
╟─────────────────────────────────────────────────────────────────────────────────╢
║ WRONG. Tensor Parallelism requires 2x All-Reduce collective communication       ║
║ per Transformer layer. Over NVLink (900 GB/s intra-node), it is fast; over      ║
║ PCIe or cross-node network, latency explodes, making TP across nodes non-viable.║
╚═════════════════════════════════════════════════════════════════════════════════╝
```

---

## Core Teaching

### Foundation

> Staff / Principal stretch sections are marked below. Mastery gate: Staff required; Principal optional.

### Step 1: Clarify Requirements & Scope

```
FUNCTIONAL REQUIREMENTS:
  F1. Serve multiple open-weight LLMs (e.g., LLaMA-3-70B, Mistral-7B) via OpenAI-compatible REST/gRPC APIs.
  F2. Support streaming responses (Server-Sent Events / gRPC streams) for real-time token delivery.
  F3. Support dynamic LoRA adapter loading for multi-tenant fine-tuned models.
  F4. Provide Prefix Caching for shared system prompts and multi-turn chat context.
  F5. Implement Semantic Caching to bypass GPU computation for near-identical queries.

NON-FUNCTIONAL REQUIREMENTS:
  NFR1. Time to First Token (TTFT): p99 < 500ms for prompts up to 4K tokens.
  NFR2. Inter-Token Latency (ITL): p99 < 30ms per token (minimum 33 tokens/sec generation).
  NFR3. High Availability: 99.9% uptime for inference endpoint cluster.
  NFR4. Multi-Tenant Isolation: Strict memory and quota boundaries between tenants.
```

---

### Step 2: Capacity Estimation & Roofline Saturation Math

#### 1. Model Weight Memory Calculation

For a model with $P$ parameters:

$$\text{Weight Bytes} = P \times \text{Bytes Per Parameter}$$

* **FP16 / BF16 (16-bit):** 2 Bytes / parameter.
* **INT8 (8-bit Quantized):** 1 Byte / parameter.
* **INT4 / FP4 (4-bit Quantized):** 0.5 Bytes / parameter.

$$\text{LLaMA-3-70B (FP16)} = 70 \times 10^9 \times 2 \text{ Bytes} = 140 \text{ GB}$$

*Fits across 2x NVIDIA H100 80GB GPUs (160 GB total HBM).*

#### 2. KV Cache Memory Footprint Math

For each Transformer layer $l$, Key ($K$) and Value ($V$) tensors must be cached for all sequence tokens:

$$\text{KV Cache Bytes Per Token} = 2 \times \text{Layers} \times \text{KV Heads} \times \text{Head Dim} \times \text{Bytes Per Element}$$

**LLaMA-3-70B Specifications:**
* Layers = `80`
* KV Heads (Grouped-Query Attention) = `8`
* Head Dimension = `128`
* Precision (FP16) = `2 Bytes`

$$\text{KV Bytes / Token} = 2 \times 80 \times 8 \times 128 \times 2 = 327,680 \text{ Bytes} \approx 327.68 \text{ KB / Token}$$

For a batch of $B = 64$ requests at sequence length $S = 4096$ tokens:

$$\text{Total KV Memory} = 64 \times 4096 \times 327.68 \text{ KB} \approx 85.9 \text{ GB}$$

#### 3. Roofline Model: Prefill vs. Decode Saturation

$$\text{Arithmetic Intensity} = \frac{\text{Total Floating Point Operations (FLOPs)}}{\text{Total Memory Bytes Transferred (HBM to SRAM)}}$$

```
ROOFLINE MODEL FOR GPU INFERENCE:

Attainable Performance (TFLOPS)
   ▲
   │                              Compute Bound Ceiling (FP16 Tensor Cores)
989│                             ┌───────────────────────────────────────
   │                            /  H100 SXM (989 TFLOPS FP16)
   │                           /
   │                          / ◄── Prefill Phase (Batch 1, Prompt 4K: AI ~150)
   │                         /
   │                        /  Memory Bandwidth Bound Slanted Line
   │                       /   (H100 HBM3 Bandwidth = 3.35 TB/s)
   │                      /
   │                     / ◄── Decode Phase (Batch 1: AI ~2 -> Highly Bottlenecked!)
   └────────────────────┴─────────────────────────────────────────────────►
                        0            156 (Ridge Point)               Arithmetic Intensity (FLOPs/Byte)
```

* **Prefill Phase (Compute-Bound):** Processes $N$ prompt tokens in parallel. High Arithmetic Intensity. Fully saturates Tensor Cores.
* **Decode Phase (Memory-Bandwidth Bound):** Generates 1 token per step. Arithmetic Intensity $\approx 2 \text{ FLOPs/Byte}$. The GPU spends 95% of its time waiting for memory transfers from HBM to SRAM.

---

### Step 3: High-Level Architecture

```
                                ┌───────────────────────────┐
                                │   Client API Gateway      │
                                └─────────────┬─────────────┘
                                              │ HTTP/gRPC SSE
                                              ▼
                                ┌───────────────────────────┐
                                │   Semantic Cache Tier     │ (Redis Vector DB)
                                └─────────────┬─────────────┘
                                              │ Cache Miss
                                              ▼
                                ┌───────────────────────────┐
                                │   Router & Load Balancer  │ (LoRA & SLA Routing)
                                └─────────────┬─────────────┘
                                              │
                ┌─────────────────────────────┴─────────────────────────────┐
                ▼                                                           ▼
┌───────────────────────────────┐                           ┌───────────────────────────────┐
│   vLLM Engine Node 1          │                           │   vLLM Engine Node 2          │
│ ┌───────────────────────────┐ │                           │ ┌───────────────────────────┐ │
│ │ Continuous Scheduler      │ │                           │ │ Continuous Scheduler      │ │
│ └─────────────┬─────────────┘ │                           │ └─────────────┬─────────────┘ │
│               ▼               │                           │               ▼               │
│ ┌───────────────────────────┐ │                           │ ┌───────────────────────────┐ │
│ │ PagedAttention Page Table │ │                           │ │ PagedAttention Page Table │ │
│ └─────────────┬─────────────┘ │                           │ └─────────────┬─────────────┘ │
│               ▼               │                           │               ▼               │
│ ┌───────────────────────────┐ │                           │ ┌───────────────────────────┐ │
│ │ Tensor Parallel Execution │ │                           │ │ Tensor Parallel Execution │ │
│ │ (GPU 0 ──NVLink──► GPU 1) │ │                           │ │ (GPU 2 ──NVLink──► GPU 3) │ │
│ └───────────────────────────┘ │                           │ └───────────────────────────┘ │
└───────────────────────────────┘                           └───────────────────────────────┘
```

---

### Step 4: PagedAttention & KV Cache Page Allocation

Traditional memory allocation assigns contiguous HBM space per request. **PagedAttention** (vLLM) models KV cache memory like Virtual Memory in operating systems:

```
PAGEDATTENTION VIRTUAL MEMORY MAPPING:

Logical KV Cache (Request A):   [ Block 0 ] ──► [ Block 1 ] ──► [ Block 2 ]
                                     │               │               │
                                     ▼               ▼               ▼
Physical HBM Memory Blocks:     [ Block 4 ]     [ Block 87 ]    [ Block 12 ]
(Non-Contiguous 16-Token Pages)

PROMPT PREFIX SHARING (Shared System Prompt):
Request 1 (System Prompt A):   [ Block 0 (Physical 4) ] ──► [ Block 1 (Physical 87) ]
Request 2 (System Prompt A):   [ Block 0 (Physical 4) ] ──► [ Block 1 (Physical 87) ]
                               (Ref Count = 2, ZERO duplicate KV memory overhead!)
```

#### Page Table Mechanics & Block Allocation

1. Memory is partitioned into fixed-size physical blocks (e.g., `Block Size = 16 tokens`).
2. When a new request arrives, its prompt is mapped into logical blocks.
3. The scheduler checks the **Prefix Hash Map**: if a physical block matching the prompt prefix exists, it increments the reference count and maps the block directly (**Prefix Cache Hit $\rightarrow$ 0 prefill compute cost**).
4. For generation steps, new blocks are allocated on-demand. When a request finishes, its reference count decrements, returning physical blocks to the free pool.

---

### Staff

### Step 5: Speculative Decoding Mechanics

To bypass the memory-bandwidth bottleneck during the Decode phase, **Speculative Decoding** pairs a small, fast Draft Model ($M_{\text{draft}}$) with a large Target Model ($M_{\text{target}}$).

```
SPECULATIVE DECODING PIPELINE:

Step 1: Draft Model ($M_{draft}$) generates $K=4$ candidate tokens sequentially (Fast, Low Latency).
        Tokens: [ "The", "capital", "of", "France" ]

Step 2: Target Model ($M_{target}$) runs ONE single parallel forward pass over all $K=4$ tokens.

Step 3: Modified Rejection Sampling accepts or rejects candidate tokens.
```

#### Modified Rejection Sampling Math

For candidate token $x_i$ at position $i$:

$$\text{Acceptance Probability } P_{\text{accept}}(x_i) = \min\left(1, \frac{P_{\text{target}}(x_i)}{P_{\text{draft}}(x_i)}\right)$$

1. Sample $r \sim U(0, 1)$.
2. If $r \le P_{\text{accept}}(x_i)$, **Accept Token** $x_i$.
3. If $r > P_{\text{accept}}(x_i)$, **Reject Token**, discard all subsequent draft tokens $x_{i+1 \dots K}$, and sample replacement token from adjusted distribution:

$$P_{\text{adjusted}}(x) = \max\left(0, P_{\text{target}}(x) - P_{\text{draft}}(x)\right)$$

**Performance Impact:** Achieves **2x to 3x speedup** in inter-token latency (ITL) without any loss in output quality or mathematical distribution accuracy.

---

### Principal Stretch

### Step 6: Multi-GPU Parallelism Communication Bounds

When models exceed single-GPU memory, workload must be split using **Tensor Parallelism (TP)** or **Pipeline Parallelism (PP)**.

```
TENSOR PARALLELISM (Intra-Node via NVLink):
Matrix Multiply split across GPUs within a single layer.
Requires 2x All-Reduce collectives per Transformer Layer.

┌──────────────┐                  ┌──────────────┐
│    GPU 0     │◄─── NVLink ────►│    GPU 1     │
│ (Matrix W1)  │  (900 GB/s Link) │ (Matrix W2)  │
└──────────────┘                  └──────────────┘

PIPELINE PARALLELISM (Inter-Node via InfiniBand):
Layers split sequentially across nodes. (Layers 1-40 on Node 0, Layers 41-80 on Node 1).
Requires Point-to-Point (P2P) activation tensor passing between nodes.
```

#### Communication Latency Math

$$\text{All-Reduce Time} = 2 \times \left( \frac{N - 1}{N} \right) \times \frac{\text{Tensor Size (Bytes)}}{\text{Interconnect Bandwidth (Bytes/sec)}}$$

**Comparison:**
* **Intra-Node NVLink (900 GB/s):** All-Reduce for 4KB hidden state takes $\approx 1.8 \mu\text{s}$ (Negligible).
* **Inter-Node PCIe / 100GbE Network (12.5 GB/s):** All-Reduce takes $\approx 130 \mu\text{s}$ per layer $\times 80 \text{ layers} = 10.4 \text{ ms}$ penalty per token (**Unusable for TP**).

**SRE Rule:** Always use **Tensor Parallelism inside a single node** over NVLink, and **Pipeline Parallelism across distinct network nodes** over InfiniBand/RoCE.

---

### Step 7: Semantic Vector Caching Tier

For repetitive enterprise queries (e.g., customer support), querying the GPU is unnecessary if a semantically equivalent query was answered previously.

```
SEMANTIC CACHE ARCHITECTURE:

Incoming Query ──► Compute Embedding (e.g., BGE-Small) ──► Vector Index Search (HNSW)
                                                                 │
                                                   Cosine Distance Threshold (d)
                                                                 │
                                              ┌──────────────────┴──────────────────┐
                                              ▼                                     ▼
                                      d <= 0.08 (Cache HIT)                 d > 0.08 (Cache MISS)
                                              │                                     │
                                    Return Cached Response               Forward to vLLM GPU
                                    (Latency < 10ms!)                    Engine Pool
```

---

## 🛑 SOCRATIC CHECK — STOP AND THINK

**Question 1:** An inference cluster running LLaMA-3-70B FP16 on 2x H100 GPUs experiences an ITL (Inter-Token Latency) spike from 25ms to 180ms when concurrency increases from 16 to 128 requests. GPU utility metrics show Tensor Core FLOP utilization drops to 12%, but HBM memory bandwidth utilization hits 99%. What is the bottleneck, and why did FLOP utilization drop?

**Question 2:** An engineer configures Tensor Parallelism (TP=8) across 8 distinct single-GPU worker nodes connected via 25GbE top-of-rack network switches. The cluster latency explodes to 1.2 seconds per token. What design constraint of Tensor Parallelism was violated?

> **Socratic check answer key:**
> See [`../answers/Week-14-Collaboration-and-AI-Designs/Design-LLM-Serving-Platform-Answers.md`](../answers/Week-14-Collaboration-and-AI-Designs/Design-LLM-Serving-Platform-Answers.md).

---

## Production Failure Patterns

```
PATTERN 1: KV CACHE PREEMPTION STORM
  Symptom:   ITL latency degrades exponentially under high load; GPU logs show repeated `Evicting blocks / Recomputing prefill`.
  Cause:     Total active sequence contexts exceed available physical PagedAttention memory blocks; scheduler forced to swap KV blocks to CPU RAM or recompute.
  Fix:       Enforce max queue depth limits; enable Chunked Prefills (`--max-num-batched-tokens`); scale out GPU nodes.

PATTERN 2: PREFIX CACHE POISONING
  Symptom:   Incorrect or cross-tenant data returned in LLM streaming output.
  Cause:     System prompt hash collision or improper tenant boundary scoping in PagedAttention shared block tables.
  Fix:       Include `tenant_id` and strict cryptographic SHA-256 hashes in block prefix lookup keys.

PATTERN 3: NVLINK DEGRADATION FALLBACK TO PCIE
  Symptom:   One GPU node in a cluster exhibits 5x higher ITL latency than identical peer nodes.
  Cause:     NVLink interconnect hardware fault causing GPU driver to fallback to PCIe bus for Tensor Parallel All-Reduce collectives.
  Fix:       Monitor `nvidia-smi nvlink -s` error counters; auto-drain nodes experiencing NVLink link degradation.
```

---

## SRE Diagnostic Toolkit

```bash
# vLLM Engine Performance Metrics (Prometheus)
vllm:num_requests_waiting
vllm:gpu_cache_usage_factor       # Target < 0.90 to prevent preemption
vllm:avg_prompt_throughput_tok_s
vllm:avg_generation_throughput_tok_s

# GPU Hardware Monitoring Commands
nvidia-smi --query-gpu=utilization.gpu,utilization.memory,memory.free,memory.used --format=csv -l 1
nvidia-smi nvlink --status        # Verify NVLink status across GPUs

# Profiling Memory Bandwidth vs Compute Saturation
nsys profile -t cuda,nvtx vllm serve --model meta-llama/Meta-Llama-3-70B
```
