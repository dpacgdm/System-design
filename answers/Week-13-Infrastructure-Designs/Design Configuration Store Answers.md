# Answer Key — Design Configuration Store

> Open only after attempting the learner file questions.

## Expert Analysis
### Question 1-4 Worked Answers

```
ROOT CAUSE:
  DB quota exceeded → write rejection → apiserver failures
  Compaction disabled/missed → unbounded revision history
  Large ConfigMaps accelerated growth
  Broad watches amplified read load during recovery attempts

IMMEDIATE:
  1. Stop rogue controller watching / (identify via metrics)
  2. etcdctl compact + defrag on leader (after snapshot)
  3. Delete unnecessary ConfigMaps / move blobs to S3
  4. Temporarily raise quota ONLY after defrag (not before)

WATCH AMPLIFICATION:
  Each apiserver LIST/WATCH on / sends events for ALL changes
  During churn, event rate exceeds network capacity

LONG-TERM:
  Auto-compaction (--auto-compaction-retention=1h)
  Defrag cron, db size alerts at 70%
  Admission webhook reject ConfigMap > 1MB
  Controller informers must use scoped watches
  Dedicated etcd cluster with NVMe, 5 nodes for prod
```

---
