# Formal Verification & DST — Socratic Check Answer Key

## Question 1: System Deadlock Missing in TLA+ Model Checking

**Answer:**
The missing invariant is a **Liveness Invariant** (e.g., $\Diamond \text{LeaderElected}$ or $\Box \Diamond \text{State = Operational}$).

The engineer only specified a **Safety Invariant** ($\Box \text{SingleLeader}$). A safety invariant checks that the system never enters a "bad state" (such as having two leaders simultaneously). However, a system that halts completely or deadlocks satisfies safety perfectly — because in a deadlocked state, no bad state transitions occur!

To catch deadlocks, the engineer must specify **Liveness / Fairness properties** (e.g., Weak Fairness $WF_v(\text{Action})$ or Strong Fairness $SF_v(\text{Action})$) and instruct the TLC Model Checker to check temporal formulas ensuring the system *eventually* progresses to a valid operational state.

---

## Question 2: Non-Deterministic Leaks in Simulation Runs Across Laptops

**Answer:**
The root cause is an **Unhandled Source of Non-Determinism** inside the codebase or runtime engine.

Common leaks include:
1. **Unseeded Global Random Generators:** Calling `rand.Float64()` or system entropy (`/dev/urandom`) directly instead of passing the simulation engine's seeded PRNG.
2. **Real-World System Time Leak:** Calling native system time APIs (`time.Now()` in Go, `std::chrono::system_clock::now()` in C++) instead of using the simulation's virtual clock context.
3. **OS-Level Thread Scheduling / Map Iteration Non-Determinism:** In Go, iterating over native Go maps (`for k, v := range my_map`) randomized key ordering by language spec design. If protocol logic processes messages in map iteration order, execution paths diverge across runs regardless of RNG seeds.

**Mitigation:**
Enforce strict linter rules and abstraction wrappers forbidding direct calls to system time, native concurrency primitives, and unseeded randomness. Map data structures must be replaced with ordered maps or sorted key slices during iteration.


---
