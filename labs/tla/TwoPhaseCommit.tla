--------------------------- MODULE TwoPhaseCommit ---------------------------
EXTENDS Integers, Sequences, FiniteSets

CONSTANTS ResourceManagers

VARIABLES rmState, tmState, tmPrepared, msgs

vars == <<rmState, tmState, tmPrepared, msgs>>

Init ==
    /\ rmState = [rm \in ResourceManagers |-> "working"]
    /\ tmState = "init"
    /\ tmPrepared = {}
    /\ msgs = {}

RMPrepare(rm) ==
    /\ rmState[rm] = "working"
    /\ rmState' = [rmState EXCEPT ![rm] = "prepared"]
    /\ msgs' = msgs \cup {[type |-> "Prepared", rm |-> rm]}
    /\ UNCHANGED <<tmState, tmPrepared>>

TMCommit ==
    /\ tmState = "init"
    /\ tmPrepared = ResourceManagers
    /\ tmState' = "committed"
    /\ msgs' = msgs \cup {[type |-> "Commit"]}
    /\ UNCHANGED <<rmState, tmPrepared>>

ConsistencyInvariant ==
    \A rm1, rm2 \in ResourceManagers :
        ~(rmState[rm1] = "committed" /\ rmState[rm2] = "aborted")
=============================================================================
