# Ops-Sim: Week 14 — Northstar LLM Serving KV Cache OOM Meltdown

## Incident Telemetry Brief
At **14:02 UTC**, the LLM inference fleet serving `omni_copilot_v2` experienced catastrophic OOM pod crashes across 80% of GPU worker nodes, resulting in 504 Gateway Timeouts for all AI features.

```
INCIDENT METRICS SIGNAL:
  - GPU VRAM Utilization  : 99.8% (Target < 85%)
  - vLLM PagedAttention   : 0 Block Table Entries Free
  - Request Latency (p99)  : 48.5 seconds (Baseline 1.2s)
  - Pod Restart Rate      : 42 restarts / min
```

## SRE Diagnostic Checklist & Triage Objectives
1. Inspect GPU memory allocation flags in vLLM container specs.
2. Identify why prompt context length scaling caused unbudgeted KV Cache memory allocation.
3. Formulate an emergency admission control rate limiter script to shed long-context prompts.
