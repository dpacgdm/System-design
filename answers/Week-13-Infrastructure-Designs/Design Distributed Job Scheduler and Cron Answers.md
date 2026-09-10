# Design Distributed Job Scheduler and Cron — Worked Answers

## Answer 1: Preventing Dual Master Dispatch via Atomic Redis Lua Scripts

1. **The Concurrency Race Condition**:
   If Master A and Master B both call `ZRANGEBYSCORE delay_queue 0 NOW`, both will receive the identical list of task IDs. If they then publish those tasks to the message broker, duplicate execution occurs.
   
2. **Atomic Pop via Server-Side Lua Script**:
   Redis executes Lua scripts single-threaded and atomically:
   ```lua
   local tasks = redis.call('ZRANGEBYSCORE', KEYS[1], 0, ARGV[1], 'LIMIT', 0, ARGV[2])
   if #tasks > 0 then
       redis.call('ZREM', KEYS[1], unpack(tasks))
   end
   return tasks
   ```
   Because Redis executes the read and remove as an uninterruptible atomic step, Master A gets the tasks and removes them in the same tick. When Master B executes, those tasks no longer exist in the ZSET.

---

## Answer 2: Append-Only Immutable Task Instances vs. Mutation

1. **Auditability & Compliance**:
   Mutating a cron job record (`UPDATE cron SET next_run = ...`) erases execution history, making it impossible to audit past execution times, latencies, failure rates, and retry counts.
2. **Separation of Definition vs. Execution**:
   - `task_definitions`: Defines the recurring rule (`0 0 * * *`) and payload.
   - `task_executions`: Records every discrete occurrence.
3. **Optimistic Locking**:
   Treating executions as immutable ledger entries prevents race conditions where a slow worker finishing run $N$ accidentally overwrites fields for run $N+1$.

---

## Answer 3: Datacenter Outage Recovery & Fencing Tokens

1. **Lease Expiration**:
   When the datacenter is partitioned, the tasks being processed there will fail to heartbeat to the central Redis/etcd cluster. After lease TTL expiration (e.g. 30 seconds), the scheduler marks the tasks as `ABANDONED` and re-dispatches them to healthy datacenters.
2. **Fencing Tokens**:
   To prevent partitioned workers from waking up later and writing stale results:
   - Each lease issuance increments a monotonic `fencing_token` in the database.
   - Downstream services (databases, payment processors) verify:
     ```sql
     UPDATE account_balances 
     SET balance = balance - 100, last_token = $fencing_token 
     WHERE account_id = $id AND last_token < $fencing_token;
     ```
   If the old worker attempts to commit with an outdated token, the update is rejected.
