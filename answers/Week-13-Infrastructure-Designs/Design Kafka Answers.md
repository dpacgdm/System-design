# Answer Key — Design Kafka

> Open only after attempting the learner file questions.

## Expert Analysis
### Question 1
```
Expert worked answer for incident Q1.
```
### Question 2
```
Expert worked answer for incident Q2.
```
### Question 3
```
Expert worked answer for incident Q3.
```
### Question 4
```
Expert worked answer for incident Q4.
```

### Full Expert Narrative

```
Q1 Rollback: Lag is BACKLOG not production rate. Consumers still
   process 500/sec; 45M / 500 = 25 hours to drain. Rollback stops
   NEW bugs but doesn't erase accumulated lag.

Q2 Root cause: max.poll.records=5000 → process loop exceeds
   max.poll.interval.ms (5 min default) → consumer kicked from group
   → rebalance storm → each rebalance pauses all 60 consumers
   → effective throughput collapses

Q3 Mitigation:
   1. Scale consumers to 120 (match partitions) on OLD version
   2. Increase max.poll.interval.ms temporarily (tactical)
   3. Pause non-critical producers if overload continues
   4. Fix code: batch DB writes before poll

Q4 Design:
   → Separate retry topic (don't block main partition)
   → Lag alert on derivative (dLag/dt) not absolute
   → Load test consumer with production message sizes pre-deploy
   → Circuit breaker on DB when pool exhausted
```

---
