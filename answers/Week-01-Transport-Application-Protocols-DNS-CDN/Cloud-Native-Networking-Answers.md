# Cloud-Native Networking — Socratic Check Answer Key

## Question 1: 503 Service Unavailable (NR) Errors During Deployment Rollouts

**Answer:**
The root cause is **xDS Endpoint Discovery Service (EDS) propagation lag** relative to Kubernetes pod lifecycle execution.
When a deployment rollout begins, Kubernetes marks old pods as `Terminating` and revokes their IPs from the Kubernetes Endpoints object. However, the Control Plane (e.g., Istio Pilot) must:
1. Detect the Endpoint state change via Kubernetes API watch.
2. Build updated xDS EDS configuration snapshots.
3. Push gRPC updates to all worker node Envoy sidecar proxies across the cluster.

During this window (which takes hundreds of milliseconds to several seconds depending on cluster size), client Envoy proxies still hold the dead pod IP in their active upstream cluster load balancing pool. Requests routed to these IPs fail at TCP connect or L7 processing, generating `503 NR (No Route)` errors.

**Mitigation:**
1. Implement a `preStop` container lifecycle hook in application deployment manifests (`sleep 10-15`) to keep the container receiving traffic while xDS updates propagate across the cluster data plane.
2. Configure Envoy active health checks alongside passive outlier detection (`consecutive_5xx`).

---

## Question 2: High CPU in `crypto/elliptic` and 15ms Latency Spikes Post-mTLS Enablement

**Answer:**
The root cause is **Asymmetric TLS Handshake Saturation driven by TCP Connection Churn**.
While bulk symmetric encryption (AES-256-GCM) is accelerated by CPU hardware instructions (AES-NI), establishing a *new* TLS connection requires asymmetric Elliptic Curve Diffie-Hellman Ephemeral (ECDHE) key exchange. ECDHE operations require intensive math in `crypto/elliptic` and cannot be accelerated by AES-NI.

If downstream applications open short-lived, non-persistent TCP connections for every single request (creating and tearing down sockets at high RPS), the Envoy sidecars are forced to compute full TLS asymmetric handshakes continuously.

**Mitigation:**
1. Enforce persistent connection pooling (HTTP/2 multiplexing or gRPC long-lived streams) at the application tier.
2. Enable TLS 1.3 with Session Resumption / Tickets in Envoy downstream TLS settings (`tls_session_ticket_keys`) to allow 0-RTT/1-RTT warm reconnects without re-executing full asymmetric ECDHE key generation.
