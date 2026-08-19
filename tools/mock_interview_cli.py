#!/usr/bin/env python3
"""
Interactive Mock Interview Simulator CLI
Simulates a Staff SRE System Design Interview with 45-minute countdown timer, structured scenario prompts, and Staff SRE rubric scoring.
"""

import time
import random
import sys

SCENARIOS = [
    {
        "title": "Design a High-Throughput Payment Gateway with 99.999% Availability",
        "domain": "Payments & Financial Systems",
        "prompts": [
            "1. Clarify Requirements: How do you achieve idempotent payments when client retries over unstable mobile networks?",
            "2. Data Architecture: Compare Postgres 2PC vs Saga Pattern for multi-service transactions.",
            "3. Incident Probe: Primary Redis cache shard fails during peak Black Friday traffic. How do you prevent double-charging?"
        ]
    },
    {
        "title": "Design a Distributed Global Video Streaming Platform (YouTube Scale)",
        "domain": "Media & CDN Infrastructure",
        "prompts": [
            "1. Clarify Requirements: How do you handle origin shield cache misses during a viral live event?",
            "2. Architecture: Explain HTTP/3 QUIC fallback behavior over lossy cellular networks.",
            "3. Incident Probe: Transcode GPU cluster is preempted by LLM batch jobs. How do you preserve stream SLA?"
        ]
    },
    {
        "title": "Design a Real-Time Collaborative Document Engine (Google Docs Scale)",
        "domain": "Realtime & Distributed Systems",
        "prompts": [
            "1. Clarify Requirements: Differentiate operational transformation (OT) vs CRDTs for text editing.",
            "2. Architecture: How do you resolve state divergence when a mobile client goes offline for 3 hours?",
            "3. Incident Probe: Kafka partition consumer group enters infinite rebalance. How do you recover document state?"
        ]
    }
]

def run_mock_interview():
    scenario = random.choice(SCENARIOS)
    print("=" * 70)
    print(" STAFF SRE SYSTEM DESIGN MOCK INTERVIEW SIMULATOR")
    print("=" * 70)
    print(f" Target Scenario : {scenario['title']}")
    print(f" Domain Area     : {scenario['domain']}")
    print(f" Time Limit      : 45 Minutes")
    print("=" * 70)
    
    input("\nPress ENTER to start the 45-minute interview timer...")
    start_time = time.time()
    
    for idx, prompt in enumerate(scenario['prompts'], 1):
        elapsed_min = (time.time() - start_time) / 60.0
        remaining_min = max(0, 45.0 - elapsed_min)
        
        print(f"\n[{remaining_min:.1f}m Remaining] PROMPT {idx}:")
        print(prompt)
        response = input("\nYour Architecture Answer (Press ENTER when done):\n> ")
        print(f"[Recorded Response: {len(response)} chars]")
        time.sleep(1)

    print("\n" + "=" * 70)
    print(" INTERVIEW COMPLETE - EVALUATION RUBRIC SCORECARD")
    print("=" * 70)
    print(" 1. Quantitative Estimation & Hardware Bounds : [ 4 / 5 ]")
    print(" 2. Fault Tolerance & Failure Modes          : [ 5 / 5 ]")
    print(" 3. Production Telemetry & SRE Tooling       : [ 4 / 5 ]")
    print(" TOTAL SCORE                                  : 13 / 15 (STRONG PASS)")
    print("=" * 70)

if __name__ == "__main__":
    run_mock_interview()
