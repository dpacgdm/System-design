package main

import (
	"context"
	"fmt"
	"sync"
	"sync/atomic"
	"time"
)

type Node struct {
	ID        int
	IsLeader  bool
	Term      uint64
	ReadIndex uint64
}

type RaftCluster struct {
	Nodes []*Node
	mu    sync.RWMutex
}

func NewCluster(numNodes int) *RaftCluster {
	c := &RaftCluster{
		Nodes: make([]*Node, numNodes),
	}
	for i := 0; i < numNodes; i++ {
		c.Nodes[i] = &Node{
			ID:       i + 1,
			IsLeader: (i == 0), // Node 1 is Leader
			Term:     1,
		}
	}
	return c
}

// ExecuteReadIndex simulates Raft ReadIndex quorum heartbeat check
func (c *RaftCluster) ExecuteReadIndex(ctx context.Context, leaderID int) (uint64, error) {
	c.mu.RLock()
	leader := c.Nodes[leaderID-1]
	c.mu.RWMutex.RUnlock()

	if !leader.IsLeader {
		return 0, fmt.Errorf("Node %d is not the Leader", leaderID)
	}

	readIndex := atomic.LoadUint64(&leader.ReadIndex)
	quorum := len(c.Nodes)/2 + 1
	var ackCount int32 = 1 // Self count

	var wg sync.WaitGroup
	for _, node := range c.Nodes {
		if node.ID == leaderID {
			continue
		}
		wg.Add(1)
		go func(n *Node) {
			defer wg.Done()
			// Simulate RPC heartbeat ping
			time.Sleep(10 * time.Millisecond)
			atomic.AddInt32(&ackCount, 1)
		}(node)
	}

	wg.Wait()

	if atomic.LoadInt32(&ackCount) >= int32(quorum) {
		fmt.Printf("[Raft ReadIndex] Quorum Verified (%d/%d ACK). ReadIndex=%d Served Safely!\n",
			ackCount, len(c.Nodes), readIndex)
		return readIndex, nil
	}

	return 0, fmt.Errorf("ReadIndex Quorum Failed: Got %d/%d ACKs", ackCount, quorum)
}

func main() {
	cluster := NewCluster(5)
	ctx := context.Background()

	readIndex, err := cluster.ExecuteReadIndex(ctx, 1)
	if err != nil {
		fmt.Println("Error:", err)
	} else {
		fmt.Println("Successfully served linearizable read at index:", readIndex)
	}
}
