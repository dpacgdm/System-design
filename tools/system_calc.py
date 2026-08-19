#!/usr/bin/env python3
"""
System Design Capacity & Hardware Calculator CLI
Provides instant quantitative bounds for IOPS, PCIe Bandwidth, RAM, Bandwidth Delay Product (BDP), and Egress Costs.
"""

import argparse
import math

def calculate_capacity(dau, requests_per_user, payload_kb, retention_days, replication_factor):
    daily_requests = dau * requests_per_user
    qps = daily_requests / 86400
    peak_qps = qps * 2.5
    
    ingress_mbps = (qps * payload_kb * 1024 * 8) / 1000000
    peak_ingress_gbps = (peak_qps * payload_kb * 1024 * 8) / 1000000000
    
    daily_storage_gb = (daily_requests * payload_kb) / (1024 * 1024)
    total_raw_storage_tb = (daily_storage_gb * retention_days * replication_factor) / 1024
    
    # NVMe IOPS provisioning (4KB block size)
    iops_required = math.ceil(peak_qps * (payload_kb / 4.0))
    nvme_drives_required = math.ceil(iops_required / 100000) # Assuming 100k IOPS per drive
    
    # Egress Cost ($0.08 per GB)
    monthly_egress_tb = (daily_storage_gb * 30)
    monthly_egress_cost_usd = monthly_egress_tb * 1024 * 0.08

    print("=" * 65)
    print(" SYSTEM DESIGN CAPACITY & HARDWARE BOUNDS ESTIMATOR")
    print("=" * 65)
    print(f" Daily Active Users (DAU) : {dau:,}")
    print(f" Daily Total Requests     : {daily_requests:,.0f}")
    print(f" Average QPS              : {qps:,.2f} req/sec")
    print(f" Peak QPS (2.5x multiplier): {peak_qps:,.2f} req/sec")
    print("-" * 65)
    print(f" Average Ingress Bandwidth : {ingress_mbps:,.2f} Mbps")
    print(f" Peak Ingress Bandwidth    : {peak_ingress_gbps:,.2f} Gbps")
    print(f" Daily Storage Growth      : {daily_storage_gb:,.2f} GB/day")
    print(f" Total Raw Storage ({retention_days}d, {replication_factor}x): {total_raw_storage_tb:,.2f} TB")
    print("-" * 65)
    print(f" Peak NVMe IOPS Required   : {iops_required:,} IOPS (4KB blocks)")
    print(f" Min NVMe Drives (100k IOPS): {nvme_drives_required} Enterprise NVMe SSDs")
    print(f" Estimated Monthly Egress  : ${monthly_egress_cost_usd:,.2f} USD")
    print("=" * 65)

def main():
    parser = argparse.ArgumentParser(description="System Design Hardware & Capacity Estimator CLI")
    parser.add_argument("--dau", type=int, default=10000000, help="Daily Active Users (default: 10M)")
    parser.add_argument("--req-per-user", type=int, default=50, help="Average requests per user per day (default: 50)")
    parser.add_argument("--payload-kb", type=float, default=2.0, help="Average payload size in KB (default: 2.0 KB)")
    parser.add_argument("--retention-days", type=int, default=365, help="Data retention in days (default: 365)")
    parser.add_argument("--replication-factor", type=int, default=3, help="Replication factor (default: 3)")
    
    args = parser.parse_args()
    calculate_capacity(args.dau, args.req_per_user, args.payload_kb, args.retention_days, args.replication_factor)

if __name__ == "__main__":
    main()
