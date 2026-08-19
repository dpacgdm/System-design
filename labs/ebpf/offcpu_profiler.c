// SPDX-License-Identifier: GPL-2.0 OR BSD-3-Clause
/* eBPF CO-RE Off-CPU Profiler Lab */

#include <vmlinux.h>
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_tracing.h>
#include <bpf/bpf_core_read.h>

#define MAX_ENTRIES 10240
#define MAX_STACK_DEPTH 127

struct stack_key_t {
    u32 pid;
    u32 tgid;
    char comm[16];
    s32 user_stack_id;
    s32 kernel_stack_id;
};

struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __uint(max_entries, MAX_ENTRIES);
    __type(key, u32);
    __type(value, u64);
} start_time SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __uint(max_entries, MAX_ENTRIES);
    __type(key, struct stack_key_t);
    __type(value, u64);
} offcpu_counts SEC(".maps");

SEC("tp/sched/sched_switch")
int BPF_PROG(sched_switch, bool preempt, struct task_struct *prev, struct task_struct *next) {
    u64 ts = bpf_ktime_get_ns();
    u32 prev_pid = BPF_CORE_READ(prev, pid);
    u32 next_pid = BPF_CORE_READ(next, pid);

    // Record Off-CPU start time for prev task
    if (prev_pid != 0) {
        bpf_map_update_elem(&start_time, &prev_pid, &ts, BPF_ANY);
    }

    // Process next task resuming execution
    u64 *start_ts = bpf_map_lookup_elem(&start_time, &next_pid);
    if (start_ts) {
        u64 delta = ts - *start_ts;
        bpf_map_delete_elem(&start_time, &next_pid);

        // Record latency if > 50 microseconds
        if (delta > 50000) {
            struct stack_key_t key = {};
            key.pid = next_pid;
            key.tgid = BPF_CORE_READ(next, tgid);
            bpf_get_current_comm(&key.comm, sizeof(key.comm));

            u64 *val = bpf_map_lookup_elem(&offcpu_counts, &key);
            if (val) {
                *val += delta;
            } else {
                bpf_map_update_elem(&offcpu_counts, &key, &delta, BPF_NOEXIST);
            }
        }
    }

    return 0;
}

char LICENSE[] SEC("license") = "GPL";
