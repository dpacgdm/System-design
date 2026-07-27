# Week-15c — SRE LLD (thick)

First-class **low-level design** for SRE interview loops — not optional toy OOD.

## Modules (do in order)

| # | Module | Timebox | Sealed answers |
|---|--------|--------:|----------------|
| 1 | [LLD Rate Limiter](./LLD%20Rate%20Limiter.md) | 45 + 20 micro | [answers](../answers/Week-15c-SRE-LLD/LLD%20Rate%20Limiter.answers.md) |
| 2 | [LLD Expiring / LRU Cache](./LLD%20Expiring%20LRU%20Cache.md) | 45 + 20 micro | [answers](../answers/Week-15c-SRE-LLD/LLD%20Expiring%20LRU%20Cache.answers.md) |
| 3 | [LLD Worker Pool](./LLD%20Worker%20Pool.md) | 45 + 20 micro | [answers](../answers/Week-15c-SRE-LLD/LLD%20Worker%20Pool.answers.md) |

## How to study

1. Read the module once (no keys).
2. Whiteboard under the timebox; run the 20-min micro-drill.
3. Self-score with the sealed key + grading bar.
4. Retention: [Week-15c.md](../Retention-Tests/Week-15c.md)

## Gate (Timed Interview OS)

Calibration requires **rate limiter + (cache OR worker pool)** Staff pass under timed conditions.

## Prerequisites

- Timed Interview OS
- Week-07 rate limiting (HLD algorithms) helpful before module 1
- Week-03/ caching concepts before module 2
- Week-08b backpressure before module 3
