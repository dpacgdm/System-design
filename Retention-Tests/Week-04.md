# Week 4 Retention Test

## Rules

- Answer from memory before opening the answer key.
- Keep rapid-fire answers concise: 2-4 sentences unless math is required.
- For the compound scenario, show the causal chain, not only isolated facts.
- Name the layer, invariant, and bad fix for each incident response.

---

## Part 1: Rapid-Fire (Q1-Q20)

**Q1 - TCP: `EADDRNOTAVAIL` with short-lived HTTP connections**
A service opens 50,000 short-lived outbound HTTP/1.1 connections per minute to one destination. It starts returning `connect() EADDRNOTAVAIL`; CPU and memory are normal, and many sockets are in `TIME_WAIT`. Explain the mechanism, name the kernel setting involved in reusing `TIME_WAIT` sockets, and give one kernel-level and one application-level fix.

**Q2 - gRPC + L4 load balancer: imbalanced backend load**
Six backend pods sit behind an L4 load balancer. A small number of clients use gRPC and two pods receive almost all traffic while the others are idle. Explain the mechanism and give the correct balancing fix.

**Q3 - DNS: Java app slow external resolution with `ClusterFirst`**
A Java service in Kubernetes resolves `api.payment.com` slowly while CoreDNS shows many NXDOMAIN responses. Pods use the default `ClusterFirst` DNS policy. Explain the exact resolver behavior and two safe fixes.

**Q4 - CDN: cache-control header interpretation**
Interpret `Cache-Control: s-maxage=86400, max-age=3600, stale-while-revalidate=60, stale-if-error=300`. Which cache uses each directive, and what happens when the origin is slow or down?

**Q5 - PostgreSQL Read Committed: three anomalies**
Read Committed prevents dirty reads but not stronger anomalies. Name three anomalies Serializable prevents and give a real-world example of each.

**Q6 - Composite index: `(customer_id, order_date, status)`**
For this B-tree index, decide which queries are efficient and why:
A. `WHERE customer_id = 42 AND order_date > '2024-01-01'`
B. `WHERE order_date > '2024-01-01' AND status = 'pending'`
C. `WHERE customer_id = 42 AND status = 'pending'`

**Q7 - Cassandra: CL=QUORUM write + CL=ONE read**
With RF=3, W=QUORUM, and R=ONE, is strong consistency guaranteed? Show the quorum math and name the anomaly.

**Q8 - Cache stampede prevention**
Name three cache stampede prevention strategies. For each, state the mechanism and whether application code must change.

**Q9 - PACELC classification**
Classify these systems and explain the tradeoff:
A. PostgreSQL synchronous replication to all standbys
B. Cassandra with CL=ONE
C. DynamoDB strongly consistent reads

**Q10 - Consistency violation: old -> new -> old**
A user refreshes a profile photo and sees old -> new -> old across three page loads. Which consistency property is violated? What property is violated if they only see old -> new after their own write?

**Q11 - Consistent hashing: key movement math**
Compare key movement when growing from 100 to 105 nodes under `hash(key) mod N` versus consistent hashing with 200 vnodes per node. Show approximate movement percentages.

**Q12 - PostgreSQL `synchronous_commit` levels**
List the five levels from weakest to strongest. What exactly has happened at `remote_write`, and what failure can still lose data?

**Q13 - CDC vs cache-aside for Redis consistency**
Why can CDC from the database WAL be safer than cache-aside invalidation for correctness-sensitive cache updates? Include an example of a harmful stale read.

**Q14 - Leader-follower failover: four failure modes**
Name four failure modes during leader-follower failover and one prevention or repair mechanism for each.

**Q15 - DynamoDB GSI update semantics**
Are GSI updates synchronous or asynchronous? What consistency anomaly can a GSI reader see, and how can a hot GSI affect base-table writes?

**Q16 - Elasticsearch: adding shards to an existing index**
Can you add primary shards to an existing index? Explain why, then describe the migration strategy and one ILM rollover condition that prevents recurrence.

**Q17 - Raft election restriction: can node D win?**
In a 5-node cluster, committed entry X exists on A, B, C. A crashes. D does not have X and starts an election. Can D win? Prove your answer using the election restriction and majority overlap.

**Q18 - etcd: leader crashes before replicating**
A leader accepts a write but crashes before replicating it to a majority. What can the client observe, and why is the write not committed under Raft?

**Q19 - Sharding: hot tenant and resharding risk**
A single tenant creates a hot shard while average cluster utilization is low. Name two mitigation patterns and one resharding hazard.

**Q20 - Replication/CDC safety-critical reads**
When is an async replica acceptable, and when must a read route to primary or a bounded-staleness/synchronous source? Give one financial or safety-critical example.

---

## Part 2: Compound Scenario

```
Incident: Cross-region trading cascade

At 09:29:55, a firewall change blocks CockroachDB ports between
us-east-1 and eu-west-1. CockroachDB ranges still have quorum through
us-west-2, but leaseholder transfers begin away from eu-west-1.

Within one minute:
- 8,000 ranges initiate leaseholder transfers.
- Commit latency rises from 4 ms to 340 ms, including on ranges that did
  not directly need eu-west-1.
- Debezium CDC lag grows; market-data Kafka topics become stale.
- Automated brokers retry aggressively; API traffic doubles.
- PgBouncer queues margin-check queries.
- The eu-west-1 PostgreSQL async replica lags 45 seconds.
- A EU broker margin check reads $2.4M available from the stale replica
  when true available margin is $600K.
- A $2.1M unauthorized margin trade is accepted.
- Separately, Consul flapping increases etcd writes and Redis has a hot
  AAPL order-book key.
```

**Q1 - Root cause chain (10 pts)**
Map the cascade link by link. Which link is direct root cause, which are consequences, and which single architectural link would have prevented the financial loss?

**Q2 - Unauthorized trade data path (10 pts)**
Trace how the real balance became a stale margin-check read. Where should the protection exist? Should EU brokers read from the eu-west-1 replica at all for margin checks?

**Q3 - Immediate mitigation plan at 09:32 (10 pts)**
Give the priority order for the next 10-30 minutes. Include actions for financial exposure, firewall rollback, retry amplification, CockroachDB leaseholder storm, PostgreSQL pressure, etcd, and Redis. Name what each action fixes and does not fix.

**Q4 - Verification and rollback safety (10 pts)**
For each mitigation, state the evidence you would check before and after execution. Include commands or queries where useful.

**Q5 - Long-term prevention (10 pts)**
Design durable fixes for staleness-bounded financial reads, retry budgets, CockroachDB placement/rebalancing safety, CDC lag alerts, PgBouncer isolation, and runbook ownership.

---

> **Answer key (do not open until you attempt the retention test):**
> [`../answers/Retention-Tests/Week-04 Answers.md`](../answers/Retention-Tests/Week-04%20Answers.md)
