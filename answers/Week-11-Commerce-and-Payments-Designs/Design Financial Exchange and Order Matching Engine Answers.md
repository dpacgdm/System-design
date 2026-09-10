# Answer Key - Week 11: Design Financial Exchange and Order Matching Engine

> Open only after attempting the learner file scenario questions.

## Principal Model Answer & Interview Evaluation Matrix

```
╔══════════════════════════════════════════════════════════════════════════╗
║ PRINCIPAL MODEL ANSWER SUMMARY — FINANCIAL MATCHING ENGINE               ║
╠══════════════════════════════════════════════════════════════════════════╣
║ 1. LOB topology: B-Tree for price points + Doubly Linked List for FIFO.  ║
║ 2. Single-writer core with LMAX Disruptor eliminates lock contention.    ║
║ 3. Deterministic sequencing + WAL guarantees zero-loss crash recovery.   ║
║ 4. Pre-allocated object pools eliminate stop-the-world GC latency spikes ║
║ 5. Decoupled market data publisher isolates matcher from client egress.  ║
╚══════════════════════════════════════════════════════════════════════════╝
```

---

## Detailed Model Solutions to Section 9 Practice Drills

### Q1: Mechanical Sympathy & The Single-Threaded Core
* **Amdahl's Law in Matching:** Order matching within a single instrument is inherently sequential—every order changes the state of the book and the available liquidity for the next order.
* **Cache Line Invalidation (MESI):** In a multi-threaded design, multiple CPU cores attempt to acquire the book lock. The CPU must broadcast cache-invalidation messages across the interconnect bus, causing memory stall cycles.
* **Core Pinning:** Pining the matcher thread to a dedicated physical CPU core (`pthread_setaffinity_np`) ensures the book data structures remain permanently resident in L1/L2 data cache ($< 1-4 	ext{ ns}$ access time).

### Q2: Price-Time Priority Formalization
* **Total Order Function:** An order $O_1$ has priority over $O_2$ ($O_1 \succ O_2$) if and only if:
  $$	ext{Price}(O_1) > 	ext{Price}(O_2) \quad (	ext{for Bids})$$
  $$	ext{Price}(O_1) < 	ext{Price}(O_2) \quad (	ext{for Asks})$$
  $$	ext{Price}(O_1) = 	ext{Price}(O_2) \implies 	ext{Timestamp}(O_1) < 	ext{Timestamp}(O_2)$$
* **Queue Placement:** Because orders at each price are stored in a Doubly Linked List, new arrivals are appended to the tail in $O(1)$, and matching consumes from the head in $O(1)$.

### Q3: Zero-GC Memory Management
* **Object Pooling Pattern:** Pre-allocate a static array of Order nodes at boot time:
  ```java
  class OrderPool {
      private final Order[] pool = new Order[1_000_000];
      private int freeIndex = 0;
      public Order borrow() { return pool[freeIndex++]; }
      public void release(Order o) { pool[--freeIndex] = o; }
  }
  ```
* **Primitive Types:** Store prices and quantities as 64-bit integers (fixed-point arithmetic, e.g. price $	imes 10^8$) rather than floating point or objects to eliminate memory allocations.

### Q4: Deterministic State Machine Recovery
* **Snapshot + Delta Replay:** The state machine recovery equation is:
  $$S_t = S_{	ext{snapshot}} + \sum_{k=	ext{seq}_{	ext{snap}}+1}^{t} 	ext{Apply}(E_k)$$
* **Zero Recovery Ambiguity:** Because the matching engine is strictly single-threaded and receives inputs through a serialized sequencer, replaying the same log of events will produce the exact same matches, trades, and order states down to the nanosecond.

### Q5: Asynchronous Egress & Conflation
* **Decoupling Pattern:** The matching thread only pushes output events to an egress ring buffer. It never touches socket file descriptors.
* **Market Data Conflator:** A dedicated ticker daemon aggregates individual trades into consolidated candles or 100ms L2 depth updates. If a client socket returns `EWOULDBLOCK`, the gateway skips intermediate deltas and only transmits the latest consolidated snapshot.
