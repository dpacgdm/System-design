# Answer Key - Week 14: Design Real-Time Collaborative Canvas and Comments

> Open only after attempting the learner file scenario questions.

## Principal Model Answer & Interview Evaluation Matrix

```
╔══════════════════════════════════════════════════════════════════════════╗
║ PRINCIPAL MODEL ANSWER SUMMARY — COLLABORATIVE CANVAS & COMMENTS         ║
╠══════════════════════════════════════════════════════════════════════════╣
║ 1. Flat object map + property-level LWW-Set CRDT ensures convergence.    ║
║ 2. Ephemeral 30Hz binary WebSocket cursor streaming with client LERP.    ║
║ 3. Selective local undo generates forward inverse deltas on user ops.    ║
║ 4. Spatial comments anchor via relative normalized offsets (rel_x, y).   ║
║ 5. Mention fan-out via Transactional Outbox and Kafka notification bus.  ║
╚══════════════════════════════════════════════════════════════════════════╝
```

---

## Detailed Model Solutions to Section 9 Practice Drills

### Q1: CRDT vs Operational Transformation for 2D Canvases
* **Independent Property Commutativity:** In a 2D scene graph, objects have distinct attributes ($x, y, w, h, 	ext{fill}$). By treating each property as a Last-Write-Wins Register (LWW-Register) parameterized by a Lamport timestamp and Client UUID, concurrent edits commute:
  $$	ext{Merge}(	ext{Op}_A, 	ext{Op}_B) = 	ext{Merge}(	ext{Op}_B, 	ext{Op}_A)$$
* **Failure of 1D Text OT:** OT relies on transform functions $T(	ext{op}_1, 	ext{op}_2)$ designed to adjust character indices in a linear string. Canvas mutations represent topological tree edits and geometric transforms, where OT transformation matrices expand exponentially in complexity.

### Q2: High-Frequency Cursor Presence Optimization
* **Bandwidth Arithmetic:** Uncompressed JSON cursors at 60 fps for 50 users generate:
  $$50 	imes 60 	imes 250 	ext{ bytes} pprox 750 	ext{ KB/s per client} \quad (6 	ext{ Mbps saturating mobile connections})$$
* **Binary Serialization & Throttling:** Packing into a 32-byte binary struct and throttling to 30 fps slashes bandwidth to:
  $$50 	imes 30 	imes 32 	ext{ bytes} pprox 48 	ext{ KB/s per client} \quad (93.6\% 	ext{ reduction})$$
* **Client-Side LERP:** The client renders at native monitor refresh rates (60Hz / 120Hz) by interpolating between the two most recently received position vectors over $\Delta t$.

### Q3: Selective Collaborative Undo Mechanics
* **Operation Inversion Formalism:** Let operation $O_1 = 	ext{Set}(x: 10 	o 50)$ by User A. The selective inverse is $O_1^{-1} = 	ext{Set}(x: 50 	o 10)$.
* **Forward Delta Application:** $O_1^{-1}$ is not applied via a retroactive time-travel rollback; instead, it is appended to the event log as a new forward operation with timestamp $T_{	ext{now}}$.
* **Peer Conflict Resolution:** If User B altered property $x$ after User A with timestamp $T_B > T_{O_1}$, the system checks whether User A's undo intent overrides $T_B$. In standard practice, User A's undo generates a new delta with $T_{	ext{now}} > T_B$, legitimately restoring User A's requested position while preserving all of User B's unrelated property edits (e.g. fill color).

### Q4: Object-Relative Spatial Comment Anchoring
* **Normalized Coordinate Mapping:**
  $$X_{	ext{screen}} = X_{	ext{object}} + (	ext{rel\_x} 	imes W_{	ext{object}})$$
  $$Y_{	ext{screen}} = Y_{	ext{object}} + (	ext{rel\_y} 	imes H_{	ext{object}})$$
* **Rotation Matrix Transformation:** When an object undergoes affine rotation by angle $	heta$ around center $(X_c, Y_c)$:
  $$egin{bmatrix} X' \ Y' \end{bmatrix} = egin{bmatrix} \cos	heta & -\sin	heta \ \sin	heta & \cos	heta \end{bmatrix} egin{bmatrix} X_{	ext{screen}} - X_c \ Y_{	ext{screen}} - Y_c \end{bmatrix} + egin{bmatrix} X_c \ Y_c \end{bmatrix}$$
  The comment icon tracks the rotated anchor point with pixel perfection.

### Q5: Asynchronous Notification Fan-Out & Rate Limiting
* **Transactional Outbox Guarantee:** Storing the comment and its outbox event within the same database transaction guarantees at-least-once delivery to Kafka even if the application server crashes immediately after DB commit.
* **Notification Aggregation & Digesting:** If User A mentions Sarah 10 times across 3 minutes in a single canvas review session, the notification worker aggregates these into a single consolidated digest ("User A mentioned you in 10 comments on Canvas X") to prevent notification spam.
