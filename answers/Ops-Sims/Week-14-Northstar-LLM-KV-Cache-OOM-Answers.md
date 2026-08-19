# Ops-Sim Answer Key: Week 14 — Northstar LLM Serving KV Cache OOM

## 1. Root Cause Analysis (5-Whys)
1. **Why did GPU pods OOM?** GPU VRAM allocation exceeded physical 80GB VRAM capacity on A100 SXM4 cards.
2. **Why VRAM exceeded?** KV Cache block allocation grew dynamically without hard max context bounds during 32k context prompt bursts.
3. **Why context bursts?** Marketing batch job submitted 10,000 PDF processing prompts with 30,000 tokens each.
4. **Why no admission control?** vLLM engine flag `--max-model-len` was unconfigured, defaulting to theoretical model maximum.
5. **Why no isolation?** Batch PDF processing shared the same GPU node pool as real-time user chat requests.

## 2. Immediate Containment Commands
```bash
# Emergency rollback of batch queue
kubectl scale deployment/batch-pdf-processor --replicas=0 -n ai-platform

# Apply vLLM KV Cache GPU memory fraction ceiling
kubectl set env deployment/llm-serving-vllm GPU_MEMORY_UTILIZATION=0.90 MAX_MODEL_LEN=8192 -n ai-platform
```
