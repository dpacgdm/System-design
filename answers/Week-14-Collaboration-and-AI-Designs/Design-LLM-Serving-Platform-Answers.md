# Design LLM Serving Platform — Socratic Check Answer Key

## Question 1: ITL Spike and FLOP Utilization Drop Under High Concurrency

**Answer:**
The bottleneck is **GPU HBM Memory Bandwidth Saturation during the Decode Phase combined with KV Cache Memory Pressure**.

1. **Why Memory Bandwidth Saturated:** During the Decode phase, every single token generation step requires loading the entire model weights and all active requests' KV caches from HBM into SRAM. At 128 concurrent requests, the memory footprint of active KV caches expands massively. HBM3 bandwidth (3.35 TB/s on H100) becomes 100% saturated fetching KV data for 128 sequences.
2. **Why Tensor Core FLOP Utilization Dropped to 12%:** Because the Decode phase generates 1 token per sequence per step, Arithmetic Intensity ($\text{FLOPs/Byte}$) is extremely low (~2). The Tensor Cores finish computing matrix multiplications in microseconds and spend 88% of their time idle waiting for memory transfers from HBM.

**Mitigation:**
1. Enable **Chunked Prefills** (`--max-num-batched-tokens`) to interleave compute-heavy prefill chunks with memory-heavy decode steps, boosting Tensor Core FLOP utilization.
2. Implement **FP8 / INT8 Quantization** for KV cache to cut KV memory transfer bytes per token in half.

---

## Question 2: Latency Explosion When Tensor Parallelism Is Deployed Across Network Nodes

**Answer:**
The design constraint violated is **Using Tensor Parallelism (TP) Over Low-Bandwidth / High-Latency Network Fabrics**.

Tensor Parallelism splits matrix multiplications within every single Transformer layer across GPUs. This requires **2x All-Reduce collective communication operations per layer**.
* For a 80-layer model, one single generated token requires **160 All-Reduce network round trips**.
* Over NVLink (900 GB/s intra-node interconnect), each All-Reduce takes $\approx 1.8 \mu\text{s}$ (total penalty $< 0.3\text{ms}$).
* Over a 25GbE top-of-rack network switch (3.125 GB/s bandwidth with network stack latency), each All-Reduce takes $\approx 150 \mu\text{s} - 500 \mu\text{s}$. Multiplying by 160 All-Reduce passes yields over **1.2 seconds of pure network latency penalty per single token**.

**Mitigation:**
Restrict **Tensor Parallelism (TP) strictly to GPUs within the same physical server board** connected by high-speed NVLink. For multi-node cluster scaling across separate physical servers, use **Pipeline Parallelism (PP)** or **Data Parallelism (DP)** over InfiniBand/RoCE.
