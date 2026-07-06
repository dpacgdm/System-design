# Design LLM Serving Platform

---

## Learning Objectives

╔══════════════════════════════════════════════════════════════╗
║ AFTER THIS MODULE, YOU WILL BE ABLE TO:                      ║
╠══════════════════════════════════════════════════════════════╣
║ 1. Design a multi-tenant LLM inference platform with         ║
║ continuous batching, KV cache management, and routing.       ║
║ 2. Explain vLLM-style PagedAttention and why it beats        ║
║ static batching for variable-length sequences.               ║
║ 3. Size GPU clusters on AWS (p4d, p5) for target QPS         ║
║ and token latency SLAs.                                      ║
║ 4. Diagnose GPU serving incidents: OOM, preemption storms,   ║
║ prefix cache poisoning, and bad model routing.               ║
║ 5. Choose deployment patterns: dedicated vs shared GPU,      ║
║ tensor parallel vs pipeline parallel vs multi-model.         ║
╚══════════════════════════════════════════════════════════════╝
---

## Wrong Mental Models (Destroy These First)

╔══════════════════════════════════════════════════════════════╗
║ MENTAL MODEL #1: "One request = one GPU forward pass"        ║
╠══════════════════════════════════════════════════════════════╣
║ WRONG. Continuous batching merges many sequences per forward ║
║ pass.                                                        ║
╚══════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════╗
║ MENTAL MODEL #2: "KV cache is optional optimization"         ║
╠══════════════════════════════════════════════════════════════╣
║ WRONG. Without KV cache, decode is O(n^2) recompute —        ║
║ unusable at scale.                                           ║
╚══════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════╗
║ MENTAL MODEL #3: "Bigger batch always faster"                ║
╠══════════════════════════════════════════════════════════════╣
║ WRONG. Batch grows until memory bound; latency SLA breaks    ║
║ first.                                                       ║
╚══════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════╗
║ MENTAL MODEL #4: "Model routing is just round-robin"         ║
╠══════════════════════════════════════════════════════════════╣
║ WRONG. Prompt length, adapter LoRA, and SLA tier drive       ║
║ routing.                                                     ║
╚══════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════╗
║ MENTAL MODEL #5: "LLM serving = wrap model in Flask"         ║
╠══════════════════════════════════════════════════════════════╣
║ WRONG. Production needs scheduler, memory pool, preemption,  ║
║ observability.                                               ║
╚══════════════════════════════════════════════════════════════╝


---

## Core Teaching

### 3.1 Inference Phases: Prefill vs Decode

```
TWO PHASES (every autoregressive LLM request):

  PREFILL (compute-bound):
    Process entire prompt tokens in parallel (one forward pass).
    Build KV cache entries for each layer.
    Time ~ proportional to prompt_length * model_width.

  DECODE (memory-bandwidth-bound):
    Generate one token at a time.
    Read entire KV cache from HBM each step.
    Time ~ proportional to batch_size * cache_size.

THROUGHPUT vs LATENCY:

  High batch → great throughput (tokens/sec/GPU)
  High batch → bad tail latency (wait in queue behind long prompts)

PRODUCTION SCHEDULER GOAL:
  Maximize GPU utilization WITHOUT violating:
    - TTFT p99 (time to first token) < 800ms
    - ITL p99 (inter-token latency) < 50ms
    - Max queue wait < 2s for premium tier
```

### 3.2 KV Cache — Mechanism

```
WHAT KV CACHE STORES:

  For each layer l, each token position t:
    Key tensor K[l,t], Value tensor V[l,t]

  During decode step for new token:
    Attention reads ALL prior K,V — not recomputed from scratch.

MEMORY FORMULA (approximate):

  kv_bytes = 2 * num_layers * num_kv_heads * head_dim * seq_len * bytes_per_param

  Example LLaMA-70B, FP16, seq_len=8192:
    layers=80, kv_heads=8, head_dim=128
    kv = 2 * 80 * 8 * 128 * 8192 * 2 ≈ 2.1 GB per sequence

  Batch of 32 concurrent 8K contexts ≈ 67 GB KV alone
  → A100 80GB fits model weights + small batch OR large batch on smaller model

PAGEDATTENTION (vLLM):

  Store KV in non-contiguous physical blocks (like OS virtual memory).
  Logical sequence → list of block IDs.
  Blocks shared across requests with common prefix (prompt caching).

  Benefits:
    - Reduce fragmentation (no pad-to-max_seq_len waste)
    - Copy-on-write fork for speculative decoding branches
    - Prefix cache hit → skip prefill for shared system prompts

AWS DEPLOYMENT:
  EKS node: p4d.24xlarge (8x A100 40GB) or p5.48xlarge (8x H100 80GB)
  NVMe instance store for fast checkpoint load (not EBS for weight load)

### 3.3 Continuous Batching

```
STATIC BATCHING (BAD):

  Wait until 8 requests arrive → batch → run → all finish together.
  Short request waits for long generation → GPU idle gaps.

CONTINUOUS BATCHING (vLLM/TGI):

  Iteration scheduler:
    Each decode step, evict finished sequences, admit new ones.
    GPU always runs full micro-batch until memory full.

ITERATION SCHEDULER LOOP:

  while True:
    finished = [r for r in running if r.done]
    free_blocks = deallocate_kv(finished)
    while free_blocks >= needed(new_request) and queue not empty:
        admit new_request (maybe preempt low priority)
    batch = build_batch(running)
    forward(batch)  # one token per sequence
    append tokens; update KV block tables

PREEMPTION (when memory pressure):

  Swap KV blocks to CPU RAM (slow) OR
  Recompute from scratch on resume (trade memory for compute)

CHUNKED PREFILL:

  Long prompt doesn't monopolize GPU for entire prefill.
  Interleave prefill chunks with decode steps → fairer ITL.

### 3.4 Model Routing and Multi-Model Serving

```
MODEL ROUTING AND MULTI-MODEL SERVING — DEEP DIVE 1:

  Production consideration 1 for Model Routing and Multi-Model Serving:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
MODEL ROUTING AND MULTI-MODEL SERVING — DEEP DIVE 2:

  Production consideration 2 for Model Routing and Multi-Model Serving:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
MODEL ROUTING AND MULTI-MODEL SERVING — DEEP DIVE 3:

  Production consideration 3 for Model Routing and Multi-Model Serving:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
MODEL ROUTING AND MULTI-MODEL SERVING — DEEP DIVE 4:

  Production consideration 4 for Model Routing and Multi-Model Serving:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
MODEL ROUTING AND MULTI-MODEL SERVING — DEEP DIVE 5:

  Production consideration 5 for Model Routing and Multi-Model Serving:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
MODEL ROUTING AND MULTI-MODEL SERVING — DEEP DIVE 6:

  Production consideration 6 for Model Routing and Multi-Model Serving:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
MODEL ROUTING AND MULTI-MODEL SERVING — DEEP DIVE 7:

  Production consideration 7 for Model Routing and Multi-Model Serving:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
MODEL ROUTING AND MULTI-MODEL SERVING — DEEP DIVE 8:

  Production consideration 8 for Model Routing and Multi-Model Serving:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```

### 3.5 Tensor Parallelism and Pipeline Parallelism

```
TENSOR PARALLELISM AND PIPELINE PARALLELISM — DEEP DIVE 1:

  Production consideration 1 for Tensor Parallelism and Pipeline Parallelism:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
TENSOR PARALLELISM AND PIPELINE PARALLELISM — DEEP DIVE 2:

  Production consideration 2 for Tensor Parallelism and Pipeline Parallelism:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
TENSOR PARALLELISM AND PIPELINE PARALLELISM — DEEP DIVE 3:

  Production consideration 3 for Tensor Parallelism and Pipeline Parallelism:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
TENSOR PARALLELISM AND PIPELINE PARALLELISM — DEEP DIVE 4:

  Production consideration 4 for Tensor Parallelism and Pipeline Parallelism:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
TENSOR PARALLELISM AND PIPELINE PARALLELISM — DEEP DIVE 5:

  Production consideration 5 for Tensor Parallelism and Pipeline Parallelism:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
TENSOR PARALLELISM AND PIPELINE PARALLELISM — DEEP DIVE 6:

  Production consideration 6 for Tensor Parallelism and Pipeline Parallelism:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
TENSOR PARALLELISM AND PIPELINE PARALLELISM — DEEP DIVE 7:

  Production consideration 7 for Tensor Parallelism and Pipeline Parallelism:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
TENSOR PARALLELISM AND PIPELINE PARALLELISM — DEEP DIVE 8:

  Production consideration 8 for Tensor Parallelism and Pipeline Parallelism:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```

### 3.6 Speculative Decoding

```
SPECULATIVE DECODING — DEEP DIVE 1:

  Production consideration 1 for Speculative Decoding:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
SPECULATIVE DECODING — DEEP DIVE 2:

  Production consideration 2 for Speculative Decoding:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
SPECULATIVE DECODING — DEEP DIVE 3:

  Production consideration 3 for Speculative Decoding:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
SPECULATIVE DECODING — DEEP DIVE 4:

  Production consideration 4 for Speculative Decoding:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
SPECULATIVE DECODING — DEEP DIVE 5:

  Production consideration 5 for Speculative Decoding:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
SPECULATIVE DECODING — DEEP DIVE 6:

  Production consideration 6 for Speculative Decoding:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
SPECULATIVE DECODING — DEEP DIVE 7:

  Production consideration 7 for Speculative Decoding:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
SPECULATIVE DECODING — DEEP DIVE 8:

  Production consideration 8 for Speculative Decoding:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```

### 3.7 Quantization (AWQ/GPTQ/FP8)

```
QUANTIZATION (AWQ/GPTQ/FP8) — DEEP DIVE 1:

  Production consideration 1 for Quantization (AWQ/GPTQ/FP8):
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
QUANTIZATION (AWQ/GPTQ/FP8) — DEEP DIVE 2:

  Production consideration 2 for Quantization (AWQ/GPTQ/FP8):
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
QUANTIZATION (AWQ/GPTQ/FP8) — DEEP DIVE 3:

  Production consideration 3 for Quantization (AWQ/GPTQ/FP8):
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
QUANTIZATION (AWQ/GPTQ/FP8) — DEEP DIVE 4:

  Production consideration 4 for Quantization (AWQ/GPTQ/FP8):
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
QUANTIZATION (AWQ/GPTQ/FP8) — DEEP DIVE 5:

  Production consideration 5 for Quantization (AWQ/GPTQ/FP8):
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
QUANTIZATION (AWQ/GPTQ/FP8) — DEEP DIVE 6:

  Production consideration 6 for Quantization (AWQ/GPTQ/FP8):
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
QUANTIZATION (AWQ/GPTQ/FP8) — DEEP DIVE 7:

  Production consideration 7 for Quantization (AWQ/GPTQ/FP8):
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
QUANTIZATION (AWQ/GPTQ/FP8) — DEEP DIVE 8:

  Production consideration 8 for Quantization (AWQ/GPTQ/FP8):
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```

### 3.8 LoRA and Multi-Adapter Batching

```
LORA AND MULTI-ADAPTER BATCHING — DEEP DIVE 1:

  Production consideration 1 for LoRA and Multi-Adapter Batching:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
LORA AND MULTI-ADAPTER BATCHING — DEEP DIVE 2:

  Production consideration 2 for LoRA and Multi-Adapter Batching:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
LORA AND MULTI-ADAPTER BATCHING — DEEP DIVE 3:

  Production consideration 3 for LoRA and Multi-Adapter Batching:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
LORA AND MULTI-ADAPTER BATCHING — DEEP DIVE 4:

  Production consideration 4 for LoRA and Multi-Adapter Batching:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
LORA AND MULTI-ADAPTER BATCHING — DEEP DIVE 5:

  Production consideration 5 for LoRA and Multi-Adapter Batching:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
LORA AND MULTI-ADAPTER BATCHING — DEEP DIVE 6:

  Production consideration 6 for LoRA and Multi-Adapter Batching:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
LORA AND MULTI-ADAPTER BATCHING — DEEP DIVE 7:

  Production consideration 7 for LoRA and Multi-Adapter Batching:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
LORA AND MULTI-ADAPTER BATCHING — DEEP DIVE 8:

  Production consideration 8 for LoRA and Multi-Adapter Batching:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```

### 3.9 Autoscaling GPU Workers on EKS

```
AUTOSCALING GPU WORKERS ON EKS — DEEP DIVE 1:

  Production consideration 1 for Autoscaling GPU Workers on EKS:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
AUTOSCALING GPU WORKERS ON EKS — DEEP DIVE 2:

  Production consideration 2 for Autoscaling GPU Workers on EKS:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
AUTOSCALING GPU WORKERS ON EKS — DEEP DIVE 3:

  Production consideration 3 for Autoscaling GPU Workers on EKS:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
AUTOSCALING GPU WORKERS ON EKS — DEEP DIVE 4:

  Production consideration 4 for Autoscaling GPU Workers on EKS:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
AUTOSCALING GPU WORKERS ON EKS — DEEP DIVE 5:

  Production consideration 5 for Autoscaling GPU Workers on EKS:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
AUTOSCALING GPU WORKERS ON EKS — DEEP DIVE 6:

  Production consideration 6 for Autoscaling GPU Workers on EKS:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
AUTOSCALING GPU WORKERS ON EKS — DEEP DIVE 7:

  Production consideration 7 for Autoscaling GPU Workers on EKS:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
AUTOSCALING GPU WORKERS ON EKS — DEEP DIVE 8:

  Production consideration 8 for Autoscaling GPU Workers on EKS:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```

### 3.10 Request Queuing and Priority Tiers

```
REQUEST QUEUING AND PRIORITY TIERS — DEEP DIVE 1:

  Production consideration 1 for Request Queuing and Priority Tiers:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
REQUEST QUEUING AND PRIORITY TIERS — DEEP DIVE 2:

  Production consideration 2 for Request Queuing and Priority Tiers:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
REQUEST QUEUING AND PRIORITY TIERS — DEEP DIVE 3:

  Production consideration 3 for Request Queuing and Priority Tiers:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
REQUEST QUEUING AND PRIORITY TIERS — DEEP DIVE 4:

  Production consideration 4 for Request Queuing and Priority Tiers:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
REQUEST QUEUING AND PRIORITY TIERS — DEEP DIVE 5:

  Production consideration 5 for Request Queuing and Priority Tiers:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
REQUEST QUEUING AND PRIORITY TIERS — DEEP DIVE 6:

  Production consideration 6 for Request Queuing and Priority Tiers:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
REQUEST QUEUING AND PRIORITY TIERS — DEEP DIVE 7:

  Production consideration 7 for Request Queuing and Priority Tiers:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
REQUEST QUEUING AND PRIORITY TIERS — DEEP DIVE 8:

  Production consideration 8 for Request Queuing and Priority Tiers:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```

### 3.11 Observability: Tokens/sec, MFU, KV Utilization

```
OBSERVABILITY: TOKENS/SEC, MFU, KV UTILIZATION — DEEP DIVE 1:

  Production consideration 1 for Observability: Tokens/sec, MFU, KV Utilization:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
OBSERVABILITY: TOKENS/SEC, MFU, KV UTILIZATION — DEEP DIVE 2:

  Production consideration 2 for Observability: Tokens/sec, MFU, KV Utilization:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
OBSERVABILITY: TOKENS/SEC, MFU, KV UTILIZATION — DEEP DIVE 3:

  Production consideration 3 for Observability: Tokens/sec, MFU, KV Utilization:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
OBSERVABILITY: TOKENS/SEC, MFU, KV UTILIZATION — DEEP DIVE 4:

  Production consideration 4 for Observability: Tokens/sec, MFU, KV Utilization:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
OBSERVABILITY: TOKENS/SEC, MFU, KV UTILIZATION — DEEP DIVE 5:

  Production consideration 5 for Observability: Tokens/sec, MFU, KV Utilization:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
OBSERVABILITY: TOKENS/SEC, MFU, KV UTILIZATION — DEEP DIVE 6:

  Production consideration 6 for Observability: Tokens/sec, MFU, KV Utilization:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
OBSERVABILITY: TOKENS/SEC, MFU, KV UTILIZATION — DEEP DIVE 7:

  Production consideration 7 for Observability: Tokens/sec, MFU, KV Utilization:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
OBSERVABILITY: TOKENS/SEC, MFU, KV UTILIZATION — DEEP DIVE 8:

  Production consideration 8 for Observability: Tokens/sec, MFU, KV Utilization:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```

### 3.12 Cold Start and Model Weight Loading

```
COLD START AND MODEL WEIGHT LOADING — DEEP DIVE 1:

  Production consideration 1 for Cold Start and Model Weight Loading:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
COLD START AND MODEL WEIGHT LOADING — DEEP DIVE 2:

  Production consideration 2 for Cold Start and Model Weight Loading:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
COLD START AND MODEL WEIGHT LOADING — DEEP DIVE 3:

  Production consideration 3 for Cold Start and Model Weight Loading:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
COLD START AND MODEL WEIGHT LOADING — DEEP DIVE 4:

  Production consideration 4 for Cold Start and Model Weight Loading:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
COLD START AND MODEL WEIGHT LOADING — DEEP DIVE 5:

  Production consideration 5 for Cold Start and Model Weight Loading:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
COLD START AND MODEL WEIGHT LOADING — DEEP DIVE 6:

  Production consideration 6 for Cold Start and Model Weight Loading:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
COLD START AND MODEL WEIGHT LOADING — DEEP DIVE 7:

  Production consideration 7 for Cold Start and Model Weight Loading:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
COLD START AND MODEL WEIGHT LOADING — DEEP DIVE 8:

  Production consideration 8 for Cold Start and Model Weight Loading:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```

### 3.13 Safety Filters and Output Moderation

```
SAFETY FILTERS AND OUTPUT MODERATION — DEEP DIVE 1:

  Production consideration 1 for Safety Filters and Output Moderation:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
SAFETY FILTERS AND OUTPUT MODERATION — DEEP DIVE 2:

  Production consideration 2 for Safety Filters and Output Moderation:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
SAFETY FILTERS AND OUTPUT MODERATION — DEEP DIVE 3:

  Production consideration 3 for Safety Filters and Output Moderation:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
SAFETY FILTERS AND OUTPUT MODERATION — DEEP DIVE 4:

  Production consideration 4 for Safety Filters and Output Moderation:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
SAFETY FILTERS AND OUTPUT MODERATION — DEEP DIVE 5:

  Production consideration 5 for Safety Filters and Output Moderation:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
SAFETY FILTERS AND OUTPUT MODERATION — DEEP DIVE 6:

  Production consideration 6 for Safety Filters and Output Moderation:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
SAFETY FILTERS AND OUTPUT MODERATION — DEEP DIVE 7:

  Production consideration 7 for Safety Filters and Output Moderation:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```
```
SAFETY FILTERS AND OUTPUT MODERATION — DEEP DIVE 8:

  Production consideration 8 for Safety Filters and Output Moderation:
    - AWS instance family selection (p4d vs p5 vs inf2 for cost)
    - vLLM flag: --max-num-seqs, --gpu-memory-utilization 0.92
    - SageMaker endpoint vs self-managed EKS (ops tradeoff)

  Scenario: Premium tenant SLA 500ms TTFT, free tier 5s acceptable.
  Router sends premium to dedicated H100 pool; free tier to shared pool
  with preemption allowed.

  Metric: model_router_mismatch_total (wrong pool assignment)
  Alert: kv_cache_usage > 0.95 for 2 min → scale out GPU nodes

  Interview line: "We measure MFU (Model FLOPs Utilization) — target
  55-65% on decode-heavy workloads; prefill-heavy chatbots lower."
```

### 3.14 GPU Cluster Pattern 1

```
PATTERN 1: EKS GPU node group topology

  Node pool 1: p5.48xlarge × 14 nodes
  Each node: 8 H100, tensor parallel size 8 for 70B model
  Or: 2 models × TP4 per node with MIG-like manual split (advanced)

  Cluster autoscaler custom metric:
    pending_requests / gpu_capacity > 0.7 → add node
    kv_cache_free_blocks / total_blocks < 0.1 → add node

  NCCL over EFA (Elastic Fabric Adapter) for TP communication.
  Without EFA: TP all-reduce becomes bottleneck at 70B+ scale.

  Failure: GPU Xid 79 error → cordon node, drain, terminate instance.
  AWS replaces p5 instance; reload weights from S3 (~3-7 min).

CAPACITY EXAMPLE 1:
  70B FP16 model ~140GB → needs 2× A100 80GB with TP2 minimum.
  Decode throughput ~ 1640 tokens/sec/GPU at batch 16.
  1000 concurrent chat users × 30 tok/gen ÷ throughput = required GPUs.
```

### 3.15 GPU Cluster Pattern 2

```
PATTERN 2: EKS GPU node group topology

  Node pool 2: p5.48xlarge × 15 nodes
  Each node: 8 H100, tensor parallel size 8 for 70B model
  Or: 2 models × TP4 per node with MIG-like manual split (advanced)

  Cluster autoscaler custom metric:
    pending_requests / gpu_capacity > 0.7 → add node
    kv_cache_free_blocks / total_blocks < 0.1 → add node

  NCCL over EFA (Elastic Fabric Adapter) for TP communication.
  Without EFA: TP all-reduce becomes bottleneck at 70B+ scale.

  Failure: GPU Xid 79 error → cordon node, drain, terminate instance.
  AWS replaces p5 instance; reload weights from S3 (~3-7 min).

CAPACITY EXAMPLE 2:
  70B FP16 model ~140GB → needs 2× A100 80GB with TP2 minimum.
  Decode throughput ~ 1650 tokens/sec/GPU at batch 16.
  1000 concurrent chat users × 30 tok/gen ÷ throughput = required GPUs.
```

### 3.16 GPU Cluster Pattern 3

```
PATTERN 3: EKS GPU node group topology

  Node pool 3: p5.48xlarge × 16 nodes
  Each node: 8 H100, tensor parallel size 8 for 70B model
  Or: 2 models × TP4 per node with MIG-like manual split (advanced)

  Cluster autoscaler custom metric:
    pending_requests / gpu_capacity > 0.7 → add node
    kv_cache_free_blocks / total_blocks < 0.1 → add node

  NCCL over EFA (Elastic Fabric Adapter) for TP communication.
  Without EFA: TP all-reduce becomes bottleneck at 70B+ scale.

  Failure: GPU Xid 79 error → cordon node, drain, terminate instance.
  AWS replaces p5 instance; reload weights from S3 (~3-7 min).

CAPACITY EXAMPLE 3:
  70B FP16 model ~140GB → needs 2× A100 80GB with TP2 minimum.
  Decode throughput ~ 1660 tokens/sec/GPU at batch 16.
  1000 concurrent chat users × 30 tok/gen ÷ throughput = required GPUs.
```

### 3.17 GPU Cluster Pattern 4

```
PATTERN 4: EKS GPU node group topology

  Node pool 4: p5.48xlarge × 17 nodes
  Each node: 8 H100, tensor parallel size 8 for 70B model
  Or: 2 models × TP4 per node with MIG-like manual split (advanced)

  Cluster autoscaler custom metric:
    pending_requests / gpu_capacity > 0.7 → add node
    kv_cache_free_blocks / total_blocks < 0.1 → add node

  NCCL over EFA (Elastic Fabric Adapter) for TP communication.
  Without EFA: TP all-reduce becomes bottleneck at 70B+ scale.

  Failure: GPU Xid 79 error → cordon node, drain, terminate instance.
  AWS replaces p5 instance; reload weights from S3 (~3-7 min).

CAPACITY EXAMPLE 4:
  70B FP16 model ~140GB → needs 2× A100 80GB with TP2 minimum.
  Decode throughput ~ 1670 tokens/sec/GPU at batch 16.
  1000 concurrent chat users × 30 tok/gen ÷ throughput = required GPUs.
```

### 3.18 GPU Cluster Pattern 5

```
PATTERN 5: EKS GPU node group topology

  Node pool 5: p5.48xlarge × 18 nodes
  Each node: 8 H100, tensor parallel size 8 for 70B model
  Or: 2 models × TP4 per node with MIG-like manual split (advanced)

  Cluster autoscaler custom metric:
    pending_requests / gpu_capacity > 0.7 → add node
    kv_cache_free_blocks / total_blocks < 0.1 → add node

  NCCL over EFA (Elastic Fabric Adapter) for TP communication.
  Without EFA: TP all-reduce becomes bottleneck at 70B+ scale.

  Failure: GPU Xid 79 error → cordon node, drain, terminate instance.
  AWS replaces p5 instance; reload weights from S3 (~3-7 min).

CAPACITY EXAMPLE 5:
  70B FP16 model ~140GB → needs 2× A100 80GB with TP2 minimum.
  Decode throughput ~ 1680 tokens/sec/GPU at batch 16.
  1000 concurrent chat users × 30 tok/gen ÷ throughput = required GPUs.
```

### 3.19 GPU Cluster Pattern 6

```
PATTERN 6: EKS GPU node group topology

  Node pool 6: p5.48xlarge × 19 nodes
  Each node: 8 H100, tensor parallel size 8 for 70B model
  Or: 2 models × TP4 per node with MIG-like manual split (advanced)

  Cluster autoscaler custom metric:
    pending_requests / gpu_capacity > 0.7 → add node
    kv_cache_free_blocks / total_blocks < 0.1 → add node

  NCCL over EFA (Elastic Fabric Adapter) for TP communication.
  Without EFA: TP all-reduce becomes bottleneck at 70B+ scale.

  Failure: GPU Xid 79 error → cordon node, drain, terminate instance.
  AWS replaces p5 instance; reload weights from S3 (~3-7 min).

CAPACITY EXAMPLE 6:
  70B FP16 model ~140GB → needs 2× A100 80GB with TP2 minimum.
  Decode throughput ~ 1690 tokens/sec/GPU at batch 16.
  1000 concurrent chat users × 30 tok/gen ÷ throughput = required GPUs.
```

### 3.20 GPU Cluster Pattern 7

```
PATTERN 7: EKS GPU node group topology

  Node pool 7: p5.48xlarge × 20 nodes
  Each node: 8 H100, tensor parallel size 8 for 70B model
  Or: 2 models × TP4 per node with MIG-like manual split (advanced)

  Cluster autoscaler custom metric:
    pending_requests / gpu_capacity > 0.7 → add node
    kv_cache_free_blocks / total_blocks < 0.1 → add node

  NCCL over EFA (Elastic Fabric Adapter) for TP communication.
  Without EFA: TP all-reduce becomes bottleneck at 70B+ scale.

  Failure: GPU Xid 79 error → cordon node, drain, terminate instance.
  AWS replaces p5 instance; reload weights from S3 (~3-7 min).

CAPACITY EXAMPLE 7:
  70B FP16 model ~140GB → needs 2× A100 80GB with TP2 minimum.
  Decode throughput ~ 1700 tokens/sec/GPU at batch 16.
  1000 concurrent chat users × 30 tok/gen ÷ throughput = required GPUs.
```

### 3.21 GPU Cluster Pattern 8

```
PATTERN 8: EKS GPU node group topology

  Node pool 8: p5.48xlarge × 21 nodes
  Each node: 8 H100, tensor parallel size 8 for 70B model
  Or: 2 models × TP4 per node with MIG-like manual split (advanced)

  Cluster autoscaler custom metric:
    pending_requests / gpu_capacity > 0.7 → add node
    kv_cache_free_blocks / total_blocks < 0.1 → add node

  NCCL over EFA (Elastic Fabric Adapter) for TP communication.
  Without EFA: TP all-reduce becomes bottleneck at 70B+ scale.

  Failure: GPU Xid 79 error → cordon node, drain, terminate instance.
  AWS replaces p5 instance; reload weights from S3 (~3-7 min).

CAPACITY EXAMPLE 8:
  70B FP16 model ~140GB → needs 2× A100 80GB with TP2 minimum.
  Decode throughput ~ 1710 tokens/sec/GPU at batch 16.
  1000 concurrent chat users × 30 tok/gen ÷ throughput = required GPUs.
```

### 3.22 GPU Cluster Pattern 9

```
PATTERN 9: EKS GPU node group topology

  Node pool 9: p5.48xlarge × 22 nodes
  Each node: 8 H100, tensor parallel size 8 for 70B model
  Or: 2 models × TP4 per node with MIG-like manual split (advanced)

  Cluster autoscaler custom metric:
    pending_requests / gpu_capacity > 0.7 → add node
    kv_cache_free_blocks / total_blocks < 0.1 → add node

  NCCL over EFA (Elastic Fabric Adapter) for TP communication.
  Without EFA: TP all-reduce becomes bottleneck at 70B+ scale.

  Failure: GPU Xid 79 error → cordon node, drain, terminate instance.
  AWS replaces p5 instance; reload weights from S3 (~3-7 min).

CAPACITY EXAMPLE 9:
  70B FP16 model ~140GB → needs 2× A100 80GB with TP2 minimum.
  Decode throughput ~ 1720 tokens/sec/GPU at batch 16.
  1000 concurrent chat users × 30 tok/gen ÷ throughput = required GPUs.
```

### 3.23 GPU Cluster Pattern 10

```
PATTERN 10: EKS GPU node group topology

  Node pool 10: p5.48xlarge × 23 nodes
  Each node: 8 H100, tensor parallel size 8 for 70B model
  Or: 2 models × TP4 per node with MIG-like manual split (advanced)

  Cluster autoscaler custom metric:
    pending_requests / gpu_capacity > 0.7 → add node
    kv_cache_free_blocks / total_blocks < 0.1 → add node

  NCCL over EFA (Elastic Fabric Adapter) for TP communication.
  Without EFA: TP all-reduce becomes bottleneck at 70B+ scale.

  Failure: GPU Xid 79 error → cordon node, drain, terminate instance.
  AWS replaces p5 instance; reload weights from S3 (~3-7 min).

CAPACITY EXAMPLE 10:
  70B FP16 model ~140GB → needs 2× A100 80GB with TP2 minimum.
  Decode throughput ~ 1730 tokens/sec/GPU at batch 16.
  1000 concurrent chat users × 30 tok/gen ÷ throughput = required GPUs.
```

### 3.24 GPU Cluster Pattern 11

```
PATTERN 11: EKS GPU node group topology

  Node pool 11: p5.48xlarge × 24 nodes
  Each node: 8 H100, tensor parallel size 8 for 70B model
  Or: 2 models × TP4 per node with MIG-like manual split (advanced)

  Cluster autoscaler custom metric:
    pending_requests / gpu_capacity > 0.7 → add node
    kv_cache_free_blocks / total_blocks < 0.1 → add node

  NCCL over EFA (Elastic Fabric Adapter) for TP communication.
  Without EFA: TP all-reduce becomes bottleneck at 70B+ scale.

  Failure: GPU Xid 79 error → cordon node, drain, terminate instance.
  AWS replaces p5 instance; reload weights from S3 (~3-7 min).

CAPACITY EXAMPLE 11:
  70B FP16 model ~140GB → needs 2× A100 80GB with TP2 minimum.
  Decode throughput ~ 1740 tokens/sec/GPU at batch 16.
  1000 concurrent chat users × 30 tok/gen ÷ throughput = required GPUs.
```

### 3.25 GPU Cluster Pattern 12

```
PATTERN 12: EKS GPU node group topology

  Node pool 12: p5.48xlarge × 25 nodes
  Each node: 8 H100, tensor parallel size 8 for 70B model
  Or: 2 models × TP4 per node with MIG-like manual split (advanced)

  Cluster autoscaler custom metric:
    pending_requests / gpu_capacity > 0.7 → add node
    kv_cache_free_blocks / total_blocks < 0.1 → add node

  NCCL over EFA (Elastic Fabric Adapter) for TP communication.
  Without EFA: TP all-reduce becomes bottleneck at 70B+ scale.

  Failure: GPU Xid 79 error → cordon node, drain, terminate instance.
  AWS replaces p5 instance; reload weights from S3 (~3-7 min).

CAPACITY EXAMPLE 12:
  70B FP16 model ~140GB → needs 2× A100 80GB with TP2 minimum.
  Decode throughput ~ 1750 tokens/sec/GPU at batch 16.
  1000 concurrent chat users × 30 tok/gen ÷ throughput = required GPUs.
```

### 3.26 GPU Cluster Pattern 13

```
PATTERN 13: EKS GPU node group topology

  Node pool 13: p5.48xlarge × 26 nodes
  Each node: 8 H100, tensor parallel size 8 for 70B model
  Or: 2 models × TP4 per node with MIG-like manual split (advanced)

  Cluster autoscaler custom metric:
    pending_requests / gpu_capacity > 0.7 → add node
    kv_cache_free_blocks / total_blocks < 0.1 → add node

  NCCL over EFA (Elastic Fabric Adapter) for TP communication.
  Without EFA: TP all-reduce becomes bottleneck at 70B+ scale.

  Failure: GPU Xid 79 error → cordon node, drain, terminate instance.
  AWS replaces p5 instance; reload weights from S3 (~3-7 min).

CAPACITY EXAMPLE 13:
  70B FP16 model ~140GB → needs 2× A100 80GB with TP2 minimum.
  Decode throughput ~ 1760 tokens/sec/GPU at batch 16.
  1000 concurrent chat users × 30 tok/gen ÷ throughput = required GPUs.
```

### 3.27 GPU Cluster Pattern 14

```
PATTERN 14: EKS GPU node group topology

  Node pool 14: p5.48xlarge × 27 nodes
  Each node: 8 H100, tensor parallel size 8 for 70B model
  Or: 2 models × TP4 per node with MIG-like manual split (advanced)

  Cluster autoscaler custom metric:
    pending_requests / gpu_capacity > 0.7 → add node
    kv_cache_free_blocks / total_blocks < 0.1 → add node

  NCCL over EFA (Elastic Fabric Adapter) for TP communication.
  Without EFA: TP all-reduce becomes bottleneck at 70B+ scale.

  Failure: GPU Xid 79 error → cordon node, drain, terminate instance.
  AWS replaces p5 instance; reload weights from S3 (~3-7 min).

CAPACITY EXAMPLE 14:
  70B FP16 model ~140GB → needs 2× A100 80GB with TP2 minimum.
  Decode throughput ~ 1770 tokens/sec/GPU at batch 16.
  1000 concurrent chat users × 30 tok/gen ÷ throughput = required GPUs.
```

### 3.28 GPU Cluster Pattern 15

```
PATTERN 15: EKS GPU node group topology

  Node pool 15: p5.48xlarge × 28 nodes
  Each node: 8 H100, tensor parallel size 8 for 70B model
  Or: 2 models × TP4 per node with MIG-like manual split (advanced)

  Cluster autoscaler custom metric:
    pending_requests / gpu_capacity > 0.7 → add node
    kv_cache_free_blocks / total_blocks < 0.1 → add node

  NCCL over EFA (Elastic Fabric Adapter) for TP communication.
  Without EFA: TP all-reduce becomes bottleneck at 70B+ scale.

  Failure: GPU Xid 79 error → cordon node, drain, terminate instance.
  AWS replaces p5 instance; reload weights from S3 (~3-7 min).

CAPACITY EXAMPLE 15:
  70B FP16 model ~140GB → needs 2× A100 80GB with TP2 minimum.
  Decode throughput ~ 1780 tokens/sec/GPU at batch 16.
  1000 concurrent chat users × 30 tok/gen ÷ throughput = required GPUs.
```

### 3.29 GPU Cluster Pattern 16

```
PATTERN 16: EKS GPU node group topology

  Node pool 16: p5.48xlarge × 29 nodes
  Each node: 8 H100, tensor parallel size 8 for 70B model
  Or: 2 models × TP4 per node with MIG-like manual split (advanced)

  Cluster autoscaler custom metric:
    pending_requests / gpu_capacity > 0.7 → add node
    kv_cache_free_blocks / total_blocks < 0.1 → add node

  NCCL over EFA (Elastic Fabric Adapter) for TP communication.
  Without EFA: TP all-reduce becomes bottleneck at 70B+ scale.

  Failure: GPU Xid 79 error → cordon node, drain, terminate instance.
  AWS replaces p5 instance; reload weights from S3 (~3-7 min).

CAPACITY EXAMPLE 16:
  70B FP16 model ~140GB → needs 2× A100 80GB with TP2 minimum.
  Decode throughput ~ 1790 tokens/sec/GPU at batch 16.
  1000 concurrent chat users × 30 tok/gen ÷ throughput = required GPUs.
```

### 3.30 GPU Cluster Pattern 17

```
PATTERN 17: EKS GPU node group topology

  Node pool 17: p5.48xlarge × 30 nodes
  Each node: 8 H100, tensor parallel size 8 for 70B model
  Or: 2 models × TP4 per node with MIG-like manual split (advanced)

  Cluster autoscaler custom metric:
    pending_requests / gpu_capacity > 0.7 → add node
    kv_cache_free_blocks / total_blocks < 0.1 → add node

  NCCL over EFA (Elastic Fabric Adapter) for TP communication.
  Without EFA: TP all-reduce becomes bottleneck at 70B+ scale.

  Failure: GPU Xid 79 error → cordon node, drain, terminate instance.
  AWS replaces p5 instance; reload weights from S3 (~3-7 min).

CAPACITY EXAMPLE 17:
  70B FP16 model ~140GB → needs 2× A100 80GB with TP2 minimum.
  Decode throughput ~ 1800 tokens/sec/GPU at batch 16.
  1000 concurrent chat users × 30 tok/gen ÷ throughput = required GPUs.
```

### 3.31 GPU Cluster Pattern 18

```
PATTERN 18: EKS GPU node group topology

  Node pool 18: p5.48xlarge × 31 nodes
  Each node: 8 H100, tensor parallel size 8 for 70B model
  Or: 2 models × TP4 per node with MIG-like manual split (advanced)

  Cluster autoscaler custom metric:
    pending_requests / gpu_capacity > 0.7 → add node
    kv_cache_free_blocks / total_blocks < 0.1 → add node

  NCCL over EFA (Elastic Fabric Adapter) for TP communication.
  Without EFA: TP all-reduce becomes bottleneck at 70B+ scale.

  Failure: GPU Xid 79 error → cordon node, drain, terminate instance.
  AWS replaces p5 instance; reload weights from S3 (~3-7 min).

CAPACITY EXAMPLE 18:
  70B FP16 model ~140GB → needs 2× A100 80GB with TP2 minimum.
  Decode throughput ~ 1810 tokens/sec/GPU at batch 16.
  1000 concurrent chat users × 30 tok/gen ÷ throughput = required GPUs.
```

### 3.32 GPU Cluster Pattern 19

```
PATTERN 19: EKS GPU node group topology

  Node pool 19: p5.48xlarge × 32 nodes
  Each node: 8 H100, tensor parallel size 8 for 70B model
  Or: 2 models × TP4 per node with MIG-like manual split (advanced)

  Cluster autoscaler custom metric:
    pending_requests / gpu_capacity > 0.7 → add node
    kv_cache_free_blocks / total_blocks < 0.1 → add node

  NCCL over EFA (Elastic Fabric Adapter) for TP communication.
  Without EFA: TP all-reduce becomes bottleneck at 70B+ scale.

  Failure: GPU Xid 79 error → cordon node, drain, terminate instance.
  AWS replaces p5 instance; reload weights from S3 (~3-7 min).

CAPACITY EXAMPLE 19:
  70B FP16 model ~140GB → needs 2× A100 80GB with TP2 minimum.
  Decode throughput ~ 1820 tokens/sec/GPU at batch 16.
  1000 concurrent chat users × 30 tok/gen ÷ throughput = required GPUs.
```

### 3.33 GPU Cluster Pattern 20

```
PATTERN 20: EKS GPU node group topology

  Node pool 20: p5.48xlarge × 33 nodes
  Each node: 8 H100, tensor parallel size 8 for 70B model
  Or: 2 models × TP4 per node with MIG-like manual split (advanced)

  Cluster autoscaler custom metric:
    pending_requests / gpu_capacity > 0.7 → add node
    kv_cache_free_blocks / total_blocks < 0.1 → add node

  NCCL over EFA (Elastic Fabric Adapter) for TP communication.
  Without EFA: TP all-reduce becomes bottleneck at 70B+ scale.

  Failure: GPU Xid 79 error → cordon node, drain, terminate instance.
  AWS replaces p5 instance; reload weights from S3 (~3-7 min).

CAPACITY EXAMPLE 20:
  70B FP16 model ~140GB → needs 2× A100 80GB with TP2 minimum.
  Decode throughput ~ 1830 tokens/sec/GPU at batch 16.
  1000 concurrent chat users × 30 tok/gen ÷ throughput = required GPUs.
```

### 3.34 GPU Cluster Pattern 21

```
PATTERN 21: EKS GPU node group topology

  Node pool 21: p5.48xlarge × 34 nodes
  Each node: 8 H100, tensor parallel size 8 for 70B model
  Or: 2 models × TP4 per node with MIG-like manual split (advanced)

  Cluster autoscaler custom metric:
    pending_requests / gpu_capacity > 0.7 → add node
    kv_cache_free_blocks / total_blocks < 0.1 → add node

  NCCL over EFA (Elastic Fabric Adapter) for TP communication.
  Without EFA: TP all-reduce becomes bottleneck at 70B+ scale.

  Failure: GPU Xid 79 error → cordon node, drain, terminate instance.
  AWS replaces p5 instance; reload weights from S3 (~3-7 min).

CAPACITY EXAMPLE 21:
  70B FP16 model ~140GB → needs 2× A100 80GB with TP2 minimum.
  Decode throughput ~ 1840 tokens/sec/GPU at batch 16.
  1000 concurrent chat users × 30 tok/gen ÷ throughput = required GPUs.
```

### 3.35 GPU Cluster Pattern 22

```
PATTERN 22: EKS GPU node group topology

  Node pool 22: p5.48xlarge × 35 nodes
  Each node: 8 H100, tensor parallel size 8 for 70B model
  Or: 2 models × TP4 per node with MIG-like manual split (advanced)

  Cluster autoscaler custom metric:
    pending_requests / gpu_capacity > 0.7 → add node
    kv_cache_free_blocks / total_blocks < 0.1 → add node

  NCCL over EFA (Elastic Fabric Adapter) for TP communication.
  Without EFA: TP all-reduce becomes bottleneck at 70B+ scale.

  Failure: GPU Xid 79 error → cordon node, drain, terminate instance.
  AWS replaces p5 instance; reload weights from S3 (~3-7 min).

CAPACITY EXAMPLE 22:
  70B FP16 model ~140GB → needs 2× A100 80GB with TP2 minimum.
  Decode throughput ~ 1850 tokens/sec/GPU at batch 16.
  1000 concurrent chat users × 30 tok/gen ÷ throughput = required GPUs.
```

### 3.36 GPU Cluster Pattern 23

```
PATTERN 23: EKS GPU node group topology

  Node pool 23: p5.48xlarge × 36 nodes
  Each node: 8 H100, tensor parallel size 8 for 70B model
  Or: 2 models × TP4 per node with MIG-like manual split (advanced)

  Cluster autoscaler custom metric:
    pending_requests / gpu_capacity > 0.7 → add node
    kv_cache_free_blocks / total_blocks < 0.1 → add node

  NCCL over EFA (Elastic Fabric Adapter) for TP communication.
  Without EFA: TP all-reduce becomes bottleneck at 70B+ scale.

  Failure: GPU Xid 79 error → cordon node, drain, terminate instance.
  AWS replaces p5 instance; reload weights from S3 (~3-7 min).

CAPACITY EXAMPLE 23:
  70B FP16 model ~140GB → needs 2× A100 80GB with TP2 minimum.
  Decode throughput ~ 1860 tokens/sec/GPU at batch 16.
  1000 concurrent chat users × 30 tok/gen ÷ throughput = required GPUs.
```

### 3.37 GPU Cluster Pattern 24

```
PATTERN 24: EKS GPU node group topology

  Node pool 24: p5.48xlarge × 37 nodes
  Each node: 8 H100, tensor parallel size 8 for 70B model
  Or: 2 models × TP4 per node with MIG-like manual split (advanced)

  Cluster autoscaler custom metric:
    pending_requests / gpu_capacity > 0.7 → add node
    kv_cache_free_blocks / total_blocks < 0.1 → add node

  NCCL over EFA (Elastic Fabric Adapter) for TP communication.
  Without EFA: TP all-reduce becomes bottleneck at 70B+ scale.

  Failure: GPU Xid 79 error → cordon node, drain, terminate instance.
  AWS replaces p5 instance; reload weights from S3 (~3-7 min).

CAPACITY EXAMPLE 24:
  70B FP16 model ~140GB → needs 2× A100 80GB with TP2 minimum.
  Decode throughput ~ 1870 tokens/sec/GPU at batch 16.
  1000 concurrent chat users × 30 tok/gen ÷ throughput = required GPUs.
```

### 3.38 GPU Cluster Pattern 25

```
PATTERN 25: EKS GPU node group topology

  Node pool 25: p5.48xlarge × 38 nodes
  Each node: 8 H100, tensor parallel size 8 for 70B model
  Or: 2 models × TP4 per node with MIG-like manual split (advanced)

  Cluster autoscaler custom metric:
    pending_requests / gpu_capacity > 0.7 → add node
    kv_cache_free_blocks / total_blocks < 0.1 → add node

  NCCL over EFA (Elastic Fabric Adapter) for TP communication.
  Without EFA: TP all-reduce becomes bottleneck at 70B+ scale.

  Failure: GPU Xid 79 error → cordon node, drain, terminate instance.
  AWS replaces p5 instance; reload weights from S3 (~3-7 min).

CAPACITY EXAMPLE 25:
  70B FP16 model ~140GB → needs 2× A100 80GB with TP2 minimum.
  Decode throughput ~ 1880 tokens/sec/GPU at batch 16.
  1000 concurrent chat users × 30 tok/gen ÷ throughput = required GPUs.
```

### 3.39 GPU Cluster Pattern 26

```
PATTERN 26: EKS GPU node group topology

  Node pool 26: p5.48xlarge × 39 nodes
  Each node: 8 H100, tensor parallel size 8 for 70B model
  Or: 2 models × TP4 per node with MIG-like manual split (advanced)

  Cluster autoscaler custom metric:
    pending_requests / gpu_capacity > 0.7 → add node
    kv_cache_free_blocks / total_blocks < 0.1 → add node

  NCCL over EFA (Elastic Fabric Adapter) for TP communication.
  Without EFA: TP all-reduce becomes bottleneck at 70B+ scale.

  Failure: GPU Xid 79 error → cordon node, drain, terminate instance.
  AWS replaces p5 instance; reload weights from S3 (~3-7 min).

CAPACITY EXAMPLE 26:
  70B FP16 model ~140GB → needs 2× A100 80GB with TP2 minimum.
  Decode throughput ~ 1890 tokens/sec/GPU at batch 16.
  1000 concurrent chat users × 30 tok/gen ÷ throughput = required GPUs.
```

### 3.40 GPU Cluster Pattern 27

```
PATTERN 27: EKS GPU node group topology

  Node pool 27: p5.48xlarge × 40 nodes
  Each node: 8 H100, tensor parallel size 8 for 70B model
  Or: 2 models × TP4 per node with MIG-like manual split (advanced)

  Cluster autoscaler custom metric:
    pending_requests / gpu_capacity > 0.7 → add node
    kv_cache_free_blocks / total_blocks < 0.1 → add node

  NCCL over EFA (Elastic Fabric Adapter) for TP communication.
  Without EFA: TP all-reduce becomes bottleneck at 70B+ scale.

  Failure: GPU Xid 79 error → cordon node, drain, terminate instance.
  AWS replaces p5 instance; reload weights from S3 (~3-7 min).

CAPACITY EXAMPLE 27:
  70B FP16 model ~140GB → needs 2× A100 80GB with TP2 minimum.
  Decode throughput ~ 1900 tokens/sec/GPU at batch 16.
  1000 concurrent chat users × 30 tok/gen ÷ throughput = required GPUs.
```

### 3.41 GPU Cluster Pattern 28

```
PATTERN 28: EKS GPU node group topology

  Node pool 28: p5.48xlarge × 41 nodes
  Each node: 8 H100, tensor parallel size 8 for 70B model
  Or: 2 models × TP4 per node with MIG-like manual split (advanced)

  Cluster autoscaler custom metric:
    pending_requests / gpu_capacity > 0.7 → add node
    kv_cache_free_blocks / total_blocks < 0.1 → add node

  NCCL over EFA (Elastic Fabric Adapter) for TP communication.
  Without EFA: TP all-reduce becomes bottleneck at 70B+ scale.

  Failure: GPU Xid 79 error → cordon node, drain, terminate instance.
  AWS replaces p5 instance; reload weights from S3 (~3-7 min).

CAPACITY EXAMPLE 28:
  70B FP16 model ~140GB → needs 2× A100 80GB with TP2 minimum.
  Decode throughput ~ 1910 tokens/sec/GPU at batch 16.
  1000 concurrent chat users × 30 tok/gen ÷ throughput = required GPUs.
```

### 3.42 GPU Cluster Pattern 29

```
PATTERN 29: EKS GPU node group topology

  Node pool 29: p5.48xlarge × 42 nodes
  Each node: 8 H100, tensor parallel size 8 for 70B model
  Or: 2 models × TP4 per node with MIG-like manual split (advanced)

  Cluster autoscaler custom metric:
    pending_requests / gpu_capacity > 0.7 → add node
    kv_cache_free_blocks / total_blocks < 0.1 → add node

  NCCL over EFA (Elastic Fabric Adapter) for TP communication.
  Without EFA: TP all-reduce becomes bottleneck at 70B+ scale.

  Failure: GPU Xid 79 error → cordon node, drain, terminate instance.
  AWS replaces p5 instance; reload weights from S3 (~3-7 min).

CAPACITY EXAMPLE 29:
  70B FP16 model ~140GB → needs 2× A100 80GB with TP2 minimum.
  Decode throughput ~ 1920 tokens/sec/GPU at batch 16.
  1000 concurrent chat users × 30 tok/gen ÷ throughput = required GPUs.
```

### 3.43 GPU Cluster Pattern 30

```
PATTERN 30: EKS GPU node group topology

  Node pool 30: p5.48xlarge × 43 nodes
  Each node: 8 H100, tensor parallel size 8 for 70B model
  Or: 2 models × TP4 per node with MIG-like manual split (advanced)

  Cluster autoscaler custom metric:
    pending_requests / gpu_capacity > 0.7 → add node
    kv_cache_free_blocks / total_blocks < 0.1 → add node

  NCCL over EFA (Elastic Fabric Adapter) for TP communication.
  Without EFA: TP all-reduce becomes bottleneck at 70B+ scale.

  Failure: GPU Xid 79 error → cordon node, drain, terminate instance.
  AWS replaces p5 instance; reload weights from S3 (~3-7 min).

CAPACITY EXAMPLE 30:
  70B FP16 model ~140GB → needs 2× A100 80GB with TP2 minimum.
  Decode throughput ~ 1930 tokens/sec/GPU at batch 16.
  1000 concurrent chat users × 30 tok/gen ÷ throughput = required GPUs.
```

### 3.44 GPU Cluster Pattern 31

```
PATTERN 31: EKS GPU node group topology

  Node pool 31: p5.48xlarge × 44 nodes
  Each node: 8 H100, tensor parallel size 8 for 70B model
  Or: 2 models × TP4 per node with MIG-like manual split (advanced)

  Cluster autoscaler custom metric:
    pending_requests / gpu_capacity > 0.7 → add node
    kv_cache_free_blocks / total_blocks < 0.1 → add node

  NCCL over EFA (Elastic Fabric Adapter) for TP communication.
  Without EFA: TP all-reduce becomes bottleneck at 70B+ scale.

  Failure: GPU Xid 79 error → cordon node, drain, terminate instance.
  AWS replaces p5 instance; reload weights from S3 (~3-7 min).

CAPACITY EXAMPLE 31:
  70B FP16 model ~140GB → needs 2× A100 80GB with TP2 minimum.
  Decode throughput ~ 1940 tokens/sec/GPU at batch 16.
  1000 concurrent chat users × 30 tok/gen ÷ throughput = required GPUs.
```

---

## Concrete Examples

### Example: vLLM on EKS

```
vLLM on EKS — configuration layer 1:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 100 concurrent users):
    TTFT p50: 200 ms
    TTFT p99: 800 ms
    Throughput: 5000 tokens/sec/cluster

  Cost: $40000/month GPU + $2000/month egress
```
```
vLLM on EKS — configuration layer 2:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 150 concurrent users):
    TTFT p50: 205 ms
    TTFT p99: 820 ms
    Throughput: 5100 tokens/sec/cluster

  Cost: $40500/month GPU + $2000/month egress
```
```
vLLM on EKS — configuration layer 3:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 200 concurrent users):
    TTFT p50: 210 ms
    TTFT p99: 840 ms
    Throughput: 5200 tokens/sec/cluster

  Cost: $41000/month GPU + $2000/month egress
```
```
vLLM on EKS — configuration layer 4:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 250 concurrent users):
    TTFT p50: 215 ms
    TTFT p99: 860 ms
    Throughput: 5300 tokens/sec/cluster

  Cost: $41500/month GPU + $2000/month egress
```
```
vLLM on EKS — configuration layer 5:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 300 concurrent users):
    TTFT p50: 220 ms
    TTFT p99: 880 ms
    Throughput: 5400 tokens/sec/cluster

  Cost: $42000/month GPU + $2000/month egress
```
```
vLLM on EKS — configuration layer 6:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 350 concurrent users):
    TTFT p50: 225 ms
    TTFT p99: 900 ms
    Throughput: 5500 tokens/sec/cluster

  Cost: $42500/month GPU + $2000/month egress
```
```
vLLM on EKS — configuration layer 7:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 400 concurrent users):
    TTFT p50: 230 ms
    TTFT p99: 920 ms
    Throughput: 5600 tokens/sec/cluster

  Cost: $43000/month GPU + $2000/month egress
```
```
vLLM on EKS — configuration layer 8:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 450 concurrent users):
    TTFT p50: 235 ms
    TTFT p99: 940 ms
    Throughput: 5700 tokens/sec/cluster

  Cost: $43500/month GPU + $2000/month egress
```
```
vLLM on EKS — configuration layer 9:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 500 concurrent users):
    TTFT p50: 240 ms
    TTFT p99: 960 ms
    Throughput: 5800 tokens/sec/cluster

  Cost: $44000/month GPU + $2000/month egress
```
```
vLLM on EKS — configuration layer 10:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 550 concurrent users):
    TTFT p50: 245 ms
    TTFT p99: 980 ms
    Throughput: 5900 tokens/sec/cluster

  Cost: $44500/month GPU + $2000/month egress
```
### Example: TGI on SageMaker

```
TGI on SageMaker — configuration layer 1:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 100 concurrent users):
    TTFT p50: 200 ms
    TTFT p99: 800 ms
    Throughput: 5000 tokens/sec/cluster

  Cost: $40000/month GPU + $2000/month egress
```
```
TGI on SageMaker — configuration layer 2:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 150 concurrent users):
    TTFT p50: 205 ms
    TTFT p99: 820 ms
    Throughput: 5100 tokens/sec/cluster

  Cost: $40500/month GPU + $2000/month egress
```
```
TGI on SageMaker — configuration layer 3:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 200 concurrent users):
    TTFT p50: 210 ms
    TTFT p99: 840 ms
    Throughput: 5200 tokens/sec/cluster

  Cost: $41000/month GPU + $2000/month egress
```
```
TGI on SageMaker — configuration layer 4:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 250 concurrent users):
    TTFT p50: 215 ms
    TTFT p99: 860 ms
    Throughput: 5300 tokens/sec/cluster

  Cost: $41500/month GPU + $2000/month egress
```
```
TGI on SageMaker — configuration layer 5:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 300 concurrent users):
    TTFT p50: 220 ms
    TTFT p99: 880 ms
    Throughput: 5400 tokens/sec/cluster

  Cost: $42000/month GPU + $2000/month egress
```
```
TGI on SageMaker — configuration layer 6:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 350 concurrent users):
    TTFT p50: 225 ms
    TTFT p99: 900 ms
    Throughput: 5500 tokens/sec/cluster

  Cost: $42500/month GPU + $2000/month egress
```
```
TGI on SageMaker — configuration layer 7:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 400 concurrent users):
    TTFT p50: 230 ms
    TTFT p99: 920 ms
    Throughput: 5600 tokens/sec/cluster

  Cost: $43000/month GPU + $2000/month egress
```
```
TGI on SageMaker — configuration layer 8:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 450 concurrent users):
    TTFT p50: 235 ms
    TTFT p99: 940 ms
    Throughput: 5700 tokens/sec/cluster

  Cost: $43500/month GPU + $2000/month egress
```
```
TGI on SageMaker — configuration layer 9:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 500 concurrent users):
    TTFT p50: 240 ms
    TTFT p99: 960 ms
    Throughput: 5800 tokens/sec/cluster

  Cost: $44000/month GPU + $2000/month egress
```
```
TGI on SageMaker — configuration layer 10:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 550 concurrent users):
    TTFT p50: 245 ms
    TTFT p99: 980 ms
    Throughput: 5900 tokens/sec/cluster

  Cost: $44500/month GPU + $2000/month egress
```
### Example: OpenAI-style router

```
OpenAI-style router — configuration layer 1:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 100 concurrent users):
    TTFT p50: 200 ms
    TTFT p99: 800 ms
    Throughput: 5000 tokens/sec/cluster

  Cost: $40000/month GPU + $2000/month egress
```
```
OpenAI-style router — configuration layer 2:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 150 concurrent users):
    TTFT p50: 205 ms
    TTFT p99: 820 ms
    Throughput: 5100 tokens/sec/cluster

  Cost: $40500/month GPU + $2000/month egress
```
```
OpenAI-style router — configuration layer 3:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 200 concurrent users):
    TTFT p50: 210 ms
    TTFT p99: 840 ms
    Throughput: 5200 tokens/sec/cluster

  Cost: $41000/month GPU + $2000/month egress
```
```
OpenAI-style router — configuration layer 4:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 250 concurrent users):
    TTFT p50: 215 ms
    TTFT p99: 860 ms
    Throughput: 5300 tokens/sec/cluster

  Cost: $41500/month GPU + $2000/month egress
```
```
OpenAI-style router — configuration layer 5:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 300 concurrent users):
    TTFT p50: 220 ms
    TTFT p99: 880 ms
    Throughput: 5400 tokens/sec/cluster

  Cost: $42000/month GPU + $2000/month egress
```
```
OpenAI-style router — configuration layer 6:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 350 concurrent users):
    TTFT p50: 225 ms
    TTFT p99: 900 ms
    Throughput: 5500 tokens/sec/cluster

  Cost: $42500/month GPU + $2000/month egress
```
```
OpenAI-style router — configuration layer 7:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 400 concurrent users):
    TTFT p50: 230 ms
    TTFT p99: 920 ms
    Throughput: 5600 tokens/sec/cluster

  Cost: $43000/month GPU + $2000/month egress
```
```
OpenAI-style router — configuration layer 8:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 450 concurrent users):
    TTFT p50: 235 ms
    TTFT p99: 940 ms
    Throughput: 5700 tokens/sec/cluster

  Cost: $43500/month GPU + $2000/month egress
```
```
OpenAI-style router — configuration layer 9:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 500 concurrent users):
    TTFT p50: 240 ms
    TTFT p99: 960 ms
    Throughput: 5800 tokens/sec/cluster

  Cost: $44000/month GPU + $2000/month egress
```
```
OpenAI-style router — configuration layer 10:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 550 concurrent users):
    TTFT p50: 245 ms
    TTFT p99: 980 ms
    Throughput: 5900 tokens/sec/cluster

  Cost: $44500/month GPU + $2000/month egress
```
### Example: Bedrock (managed)

```
Bedrock (managed) — configuration layer 1:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 100 concurrent users):
    TTFT p50: 200 ms
    TTFT p99: 800 ms
    Throughput: 5000 tokens/sec/cluster

  Cost: $40000/month GPU + $2000/month egress
```
```
Bedrock (managed) — configuration layer 2:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 150 concurrent users):
    TTFT p50: 205 ms
    TTFT p99: 820 ms
    Throughput: 5100 tokens/sec/cluster

  Cost: $40500/month GPU + $2000/month egress
```
```
Bedrock (managed) — configuration layer 3:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 200 concurrent users):
    TTFT p50: 210 ms
    TTFT p99: 840 ms
    Throughput: 5200 tokens/sec/cluster

  Cost: $41000/month GPU + $2000/month egress
```
```
Bedrock (managed) — configuration layer 4:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 250 concurrent users):
    TTFT p50: 215 ms
    TTFT p99: 860 ms
    Throughput: 5300 tokens/sec/cluster

  Cost: $41500/month GPU + $2000/month egress
```
```
Bedrock (managed) — configuration layer 5:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 300 concurrent users):
    TTFT p50: 220 ms
    TTFT p99: 880 ms
    Throughput: 5400 tokens/sec/cluster

  Cost: $42000/month GPU + $2000/month egress
```
```
Bedrock (managed) — configuration layer 6:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 350 concurrent users):
    TTFT p50: 225 ms
    TTFT p99: 900 ms
    Throughput: 5500 tokens/sec/cluster

  Cost: $42500/month GPU + $2000/month egress
```
```
Bedrock (managed) — configuration layer 7:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 400 concurrent users):
    TTFT p50: 230 ms
    TTFT p99: 920 ms
    Throughput: 5600 tokens/sec/cluster

  Cost: $43000/month GPU + $2000/month egress
```
```
Bedrock (managed) — configuration layer 8:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 450 concurrent users):
    TTFT p50: 235 ms
    TTFT p99: 940 ms
    Throughput: 5700 tokens/sec/cluster

  Cost: $43500/month GPU + $2000/month egress
```
```
Bedrock (managed) — configuration layer 9:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 500 concurrent users):
    TTFT p50: 240 ms
    TTFT p99: 960 ms
    Throughput: 5800 tokens/sec/cluster

  Cost: $44000/month GPU + $2000/month egress
```
```
Bedrock (managed) — configuration layer 10:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 550 concurrent users):
    TTFT p50: 245 ms
    TTFT p99: 980 ms
    Throughput: 5900 tokens/sec/cluster

  Cost: $44500/month GPU + $2000/month egress
```
### Example: Internal platform

```
Internal platform — configuration layer 1:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 100 concurrent users):
    TTFT p50: 200 ms
    TTFT p99: 800 ms
    Throughput: 5000 tokens/sec/cluster

  Cost: $40000/month GPU + $2000/month egress
```
```
Internal platform — configuration layer 2:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 150 concurrent users):
    TTFT p50: 205 ms
    TTFT p99: 820 ms
    Throughput: 5100 tokens/sec/cluster

  Cost: $40500/month GPU + $2000/month egress
```
```
Internal platform — configuration layer 3:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 200 concurrent users):
    TTFT p50: 210 ms
    TTFT p99: 840 ms
    Throughput: 5200 tokens/sec/cluster

  Cost: $41000/month GPU + $2000/month egress
```
```
Internal platform — configuration layer 4:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 250 concurrent users):
    TTFT p50: 215 ms
    TTFT p99: 860 ms
    Throughput: 5300 tokens/sec/cluster

  Cost: $41500/month GPU + $2000/month egress
```
```
Internal platform — configuration layer 5:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 300 concurrent users):
    TTFT p50: 220 ms
    TTFT p99: 880 ms
    Throughput: 5400 tokens/sec/cluster

  Cost: $42000/month GPU + $2000/month egress
```
```
Internal platform — configuration layer 6:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 350 concurrent users):
    TTFT p50: 225 ms
    TTFT p99: 900 ms
    Throughput: 5500 tokens/sec/cluster

  Cost: $42500/month GPU + $2000/month egress
```
```
Internal platform — configuration layer 7:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 400 concurrent users):
    TTFT p50: 230 ms
    TTFT p99: 920 ms
    Throughput: 5600 tokens/sec/cluster

  Cost: $43000/month GPU + $2000/month egress
```
```
Internal platform — configuration layer 8:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 450 concurrent users):
    TTFT p50: 235 ms
    TTFT p99: 940 ms
    Throughput: 5700 tokens/sec/cluster

  Cost: $43500/month GPU + $2000/month egress
```
```
Internal platform — configuration layer 9:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 500 concurrent users):
    TTFT p50: 240 ms
    TTFT p99: 960 ms
    Throughput: 5800 tokens/sec/cluster

  Cost: $44000/month GPU + $2000/month egress
```
```
Internal platform — configuration layer 10:

  Helm values / Terraform snippet concept:
    gpu_memory_utilization: 0.90
    max_model_len: 8192
    enable_prefix_caching: true
    aws_region: us-east-1
    s3_weights_uri: s3://models-bucket/llama-70b-fp16/

  Load test result (Locust, 550 concurrent users):
    TTFT p50: 245 ms
    TTFT p99: 980 ms
    Throughput: 5900 tokens/sec/cluster

  Cost: $44500/month GPU + $2000/month egress
```

---

## Production Patterns

### Pattern: Continuous batching with chunked prefill

```
Implementation notes for Continuous batching with chunked prefill...
```

  Rollout checklist item: verify Continuous batching with chunked prefill metrics in staging.
  Rollout checklist item: verify Continuous batching with chunked prefill metrics in staging.
  Rollout checklist item: verify Continuous batching with chunked prefill metrics in staging.
  Rollout checklist item: verify Continuous batching with chunked prefill metrics in staging.
### Pattern: Prefix caching for shared system prompts

```
Implementation notes for Prefix caching for shared system prompts...
```

  Rollout checklist item: verify Prefix caching for shared system prompts metrics in staging.
  Rollout checklist item: verify Prefix caching for shared system prompts metrics in staging.
  Rollout checklist item: verify Prefix caching for shared system prompts metrics in staging.
  Rollout checklist item: verify Prefix caching for shared system prompts metrics in staging.
### Pattern: Two-tier queue (premium vs best-effort)

```
Implementation notes for Two-tier queue (premium vs best-effort)...
```

  Rollout checklist item: verify Two-tier queue (premium vs best-effort) metrics in staging.
  Rollout checklist item: verify Two-tier queue (premium vs best-effort) metrics in staging.
  Rollout checklist item: verify Two-tier queue (premium vs best-effort) metrics in staging.
  Rollout checklist item: verify Two-tier queue (premium vs best-effort) metrics in staging.
### Pattern: Model warm pool (min replicas > 0)

```
Implementation notes for Model warm pool (min replicas > 0)...
```

  Rollout checklist item: verify Model warm pool (min replicas > 0) metrics in staging.
  Rollout checklist item: verify Model warm pool (min replicas > 0) metrics in staging.
  Rollout checklist item: verify Model warm pool (min replicas > 0) metrics in staging.
  Rollout checklist item: verify Model warm pool (min replicas > 0) metrics in staging.
### Pattern: Circuit breaker on upstream GPU OOM

```
Implementation notes for Circuit breaker on upstream GPU OOM...
```

  Rollout checklist item: verify Circuit breaker on upstream GPU OOM metrics in staging.
  Rollout checklist item: verify Circuit breaker on upstream GPU OOM metrics in staging.
  Rollout checklist item: verify Circuit breaker on upstream GPU OOM metrics in staging.
  Rollout checklist item: verify Circuit breaker on upstream GPU OOM metrics in staging.
### Pattern: Shadow traffic for new model versions

```
Implementation notes for Shadow traffic for new model versions...
```

  Rollout checklist item: verify Shadow traffic for new model versions metrics in staging.
  Rollout checklist item: verify Shadow traffic for new model versions metrics in staging.
  Rollout checklist item: verify Shadow traffic for new model versions metrics in staging.
  Rollout checklist item: verify Shadow traffic for new model versions metrics in staging.
### Pattern: Token-based billing meter at gateway

```
Implementation notes for Token-based billing meter at gateway...
```

  Rollout checklist item: verify Token-based billing meter at gateway metrics in staging.
  Rollout checklist item: verify Token-based billing meter at gateway metrics in staging.
  Rollout checklist item: verify Token-based billing meter at gateway metrics in staging.
  Rollout checklist item: verify Token-based billing meter at gateway metrics in staging.
### Pattern: Adaptive max batch based on KV pressure

```
Implementation notes for Adaptive max batch based on KV pressure...
```

  Rollout checklist item: verify Adaptive max batch based on KV pressure metrics in staging.
  Rollout checklist item: verify Adaptive max batch based on KV pressure metrics in staging.
  Rollout checklist item: verify Adaptive max batch based on KV pressure metrics in staging.
  Rollout checklist item: verify Adaptive max batch based on KV pressure metrics in staging.

---

## Failure Modes

### GPU OOM during prefill

```
Symptoms, detection, mitigation for GPU OOM during prefill.
```

### GPU OOM during prefill

```
Symptoms, detection, mitigation for GPU OOM during prefill.
```

### GPU OOM during prefill

```
Symptoms, detection, mitigation for GPU OOM during prefill.
```

### GPU OOM during prefill

```
Symptoms, detection, mitigation for GPU OOM during prefill.
```

### GPU OOM during prefill

```
Symptoms, detection, mitigation for GPU OOM during prefill.
```

### KV block leak

```
Symptoms, detection, mitigation for KV block leak.
```

### KV block leak

```
Symptoms, detection, mitigation for KV block leak.
```

### KV block leak

```
Symptoms, detection, mitigation for KV block leak.
```

### KV block leak

```
Symptoms, detection, mitigation for KV block leak.
```

### KV block leak

```
Symptoms, detection, mitigation for KV block leak.
```

### NCCL timeout on TP group

```
Symptoms, detection, mitigation for NCCL timeout on TP group.
```

### NCCL timeout on TP group

```
Symptoms, detection, mitigation for NCCL timeout on TP group.
```

### NCCL timeout on TP group

```
Symptoms, detection, mitigation for NCCL timeout on TP group.
```

### NCCL timeout on TP group

```
Symptoms, detection, mitigation for NCCL timeout on TP group.
```

### NCCL timeout on TP group

```
Symptoms, detection, mitigation for NCCL timeout on TP group.
```

### Bad LoRA adapter load

```
Symptoms, detection, mitigation for Bad LoRA adapter load.
```

### Bad LoRA adapter load

```
Symptoms, detection, mitigation for Bad LoRA adapter load.
```

### Bad LoRA adapter load

```
Symptoms, detection, mitigation for Bad LoRA adapter load.
```

### Bad LoRA adapter load

```
Symptoms, detection, mitigation for Bad LoRA adapter load.
```

### Bad LoRA adapter load

```
Symptoms, detection, mitigation for Bad LoRA adapter load.
```

### Prefix cache stale

```
Symptoms, detection, mitigation for Prefix cache stale.
```

### Prefix cache stale

```
Symptoms, detection, mitigation for Prefix cache stale.
```

### Prefix cache stale

```
Symptoms, detection, mitigation for Prefix cache stale.
```

### Prefix cache stale

```
Symptoms, detection, mitigation for Prefix cache stale.
```

### Prefix cache stale

```
Symptoms, detection, mitigation for Prefix cache stale.
```

### Scheduler starvation

```
Symptoms, detection, mitigation for Scheduler starvation.
```

### Scheduler starvation

```
Symptoms, detection, mitigation for Scheduler starvation.
```

### Scheduler starvation

```
Symptoms, detection, mitigation for Scheduler starvation.
```

### Scheduler starvation

```
Symptoms, detection, mitigation for Scheduler starvation.
```

### Scheduler starvation

```
Symptoms, detection, mitigation for Scheduler starvation.
```

### Weight download timeout on scale-out

```
Symptoms, detection, mitigation for Weight download timeout on scale-out.
```

### Weight download timeout on scale-out

```
Symptoms, detection, mitigation for Weight download timeout on scale-out.
```

### Weight download timeout on scale-out

```
Symptoms, detection, mitigation for Weight download timeout on scale-out.
```

### Weight download timeout on scale-out

```
Symptoms, detection, mitigation for Weight download timeout on scale-out.
```

### Weight download timeout on scale-out

```
Symptoms, detection, mitigation for Weight download timeout on scale-out.
```


---

## SRE Diagnostic Toolkit

```
# GPU memory snapshot on node
nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv

# vLLM metrics endpoint
curl -s localhost:8000/metrics | grep vllm_

# Key series:
#   vllm:gpu_cache_usage_perc
#   vllm:num_requests_running / waiting / swapped
#   vllm:avg_prompt_throughput_toks_per_s
#   vllm:avg_generation_throughput_toks_per_s

# EKS GPU node describe
kubectl describe node $NODE | grep -A5 "Allocatable\|nvidia.com/gpu"

# CloudWatch Container Insights GPU metrics
aws cloudwatch get-metric-statistics \
  --namespace ContainerInsights/Prometheus \
  --metric-name GPUUtilization \
  --dimensions Name=ClusterName,Value=llm-prod \
  --period 60 --statistics Average \
  --start-time ... --end-time ...

# Log query: OOM events
fields @timestamp, @message
| filter @message like /CUDA out of memory/
| stats count() by bin(5m)
```

# Runbook step 1: check pending queue depth vs GPU count
# Runbook step 2: check pending queue depth vs GPU count
# Runbook step 3: check pending queue depth vs GPU count
# Runbook step 4: check pending queue depth vs GPU count
# Runbook step 5: check pending queue depth vs GPU count
# Runbook step 6: check pending queue depth vs GPU count
# Runbook step 7: check pending queue depth vs GPU count
# Runbook step 8: check pending queue depth vs GPU count
# Runbook step 9: check pending queue depth vs GPU count
# Runbook step 10: check pending queue depth vs GPU count
# Runbook step 11: check pending queue depth vs GPU count
# Runbook step 12: check pending queue depth vs GPU count
# Runbook step 13: check pending queue depth vs GPU count
# Runbook step 14: check pending queue depth vs GPU count
# Runbook step 15: check pending queue depth vs GPU count
# Runbook step 16: check pending queue depth vs GPU count
# Runbook step 17: check pending queue depth vs GPU count
# Runbook step 18: check pending queue depth vs GPU count
# Runbook step 19: check pending queue depth vs GPU count
# Runbook step 20: check pending queue depth vs GPU count
# Runbook step 21: check pending queue depth vs GPU count
# Runbook step 22: check pending queue depth vs GPU count
# Runbook step 23: check pending queue depth vs GPU count
# Runbook step 24: check pending queue depth vs GPU count
# Runbook step 25: check pending queue depth vs GPU count

---

## Decision Framework


| Need | Choose |
|------|--------|
| Lowest ops burden | SageMaker / Bedrock |
| Max throughput/$ | Self-hosted vLLM on p4d/p5 |
| Multi-model 100+ | Router + shared pool + LoRA |
| Strict data residency | Dedicated VPC + no shared GPU |
| <100ms TTFT | Smaller model, dedicated GPU, short queue |

```
ROUTING FLOWCHART:

  Request arrives → classify (prompt len, tier, model id)
       → cache lookup (prefix hash)
       → if hit: decode-only path
       → else: route to pool with capacity
       → if none: queue or 429 based on tier
```

---

## Incident Scenario: LLM Platform Latency Spike

```
P1: TTFT p99 4s (SLA 800ms). GPU util 98%. Queue depth 2000.
Deploy: enabled prefix caching v3.1. Suspect cache bug or traffic mix shift.
Questions: diagnose, mitigate, prevent.
```

---

## Expert Analysis

### Q1

```
Worked answer for LLM incident Q1...
```

### Q2

```
Worked answer for LLM incident Q2...
```

### Q3

```
Worked answer for LLM incident Q3...
```

### Q4

```
Worked answer for LLM incident Q4...
```

### Q5

```
Worked answer for LLM incident Q5...
```


---

## Key Takeaways

╔══════════════════════════════════════════════════════════════╗
║ REMEMBER:                                                    ║
╠══════════════════════════════════════════════════════════════╣
║ 1. Prefill is compute-bound; decode is memory-bound —        ║
║ schedule both.                                               ║
║ 2. KV cache size dominates batch capacity — PagedAttention   ║
║ is table stakes.                                             ║
║ 3. Continuous batching + chunked prefill balance throughput  ║
║ and ITL.                                                     ║
║ 4. Route by SLA tier and prompt length, not round-robin.     ║
║ 5. Watch kv_cache_usage and queue depth — not just GPU util  ║
║ %.                                                           ║
╚══════════════════════════════════════════════════════════════╝
---

## Targeted Reading

```
vLLM paper (PagedAttention) — Sections 3-4
NVIDIA Triton Inference Server docs — dynamic batching
AWS: p5 instance networking with EFA
Kwon et al., "Efficient Memory Management for LLM Serving"
SageMaker large model inference container docs
```
```
