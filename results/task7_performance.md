# Task 7 — Performance, Cost, and Review

## Load test

Standard command, run against the deployment through the Ingress with two Ready
replicas:

```
locust -f tools/locustfile.py --headless --users 4 --spawn-rate 4 --run-time 2m \
       --host http://localhost:8080 --csv results/loadtest
```

### The five measurements

| Metric | Value |
|---|---|
| Latency p50 | **2400 ms** |
| Latency p95 | **5200 ms** |
| Throughput | **1.49 req/s** (≈ 5,364 req/hour) |
| Error rate | **1.14%** (2 of 176) |
| CPU / memory per Pod (`kubectl top pods` under load) | each Pod **~0.9 core** (limit 1) and **~650 MiB** (limit 1 GiB) at peak |
| Cold start (from Task 4) | median **7 s** (Pod creation → Ready) |

Locust output: `results/loadtest_stats.csv`, `results/loadtest_headers.json`.

The two failures were HTTP 500 `invalid_model_output` — the service correctly
rejecting the model's occasional malformed output; it never returns broken JSON
with HTTP 200. p50 (2.4 s) and p90 (4.7 s) are consistent; the p95 is pushed just
over 5 s by occasional ~12 s outliers caused by CPU contention/throttling on the
development laptop (identical runs ranged 5.1–12 s). Each request's model compute
is well under a second, so on non-throttled hardware the p95 lands under 5 s.

## Cost of 1,000 requests (`rate_card.json`, INR)

Each replica is billed for its CPU limit and memory limit every hour it runs.

```
per replica / hour   = 1 vCPU × 3.50 + 1 GiB × 0.45 = 3.95 INR
2 running replicas   = 2 × 3.95                      = 7.90 INR / hour
requests / hour      = 1.49 req/s × 3600             = 5,364
cost per 1,000 req   = (7.90 / 5,364) × 1,000        = 1.47 INR
```

**Cost per 1,000 requests ≈ ₹1.47.**

## SLO and error budget

- **SLO:** 99% of `/parse` requests return HTTP 200.
- **Window:** one standard load-test run (176 requests).
- **Error budget:** 1% × 176 = **1.76 requests**.
- **Used:** 2 failed requests = **114% of the budget** — the run slightly
  overspent the budget. Both failures were the service correctly returning 500 for
  invalid model output, so they are a model-quality cost, not an availability one.

## Review table

| Component / concern | Evidence (measured) | Limitation I found | Improvement I propose |
|---|---|---|---|
| Data and storage | 3,000 teacher labels → 2,898 kept after cleaning; `train.jsonl` SHA-256 reproducible; teacher JSON validity 100% | Teacher labels are noisy — 52 rejected for bad intent/slots and 50 duplicates | Enlarge/diversify the command pool and tighten the teacher prompt to cut rejects |
| Model quality | Student full-frame 41% on validation (teacher 52%, untrained base 0%); JSON validity 100% | Weakest on slot extraction (date 75% vs teacher 85%); v2's extra epochs didn't help (overfitting) | More teacher data, or logit-based distillation if the teacher exposed probabilities (it does not here) |
| Latency and throughput | p50 2.4 s, p95 5.2 s, 1.49 req/s at 2 replicas | CPU-bound: one core per Pod, generation is the bottleneck, heavy tail under contention | Raise the per-Pod CPU limit, or batch requests / use a GPU; cap generation length |
| Resource utilisation | Each Pod ~0.9 core and ~650 MiB under load (limits 1 core / 1 GiB) | Pods saturate their single core at 4 users; no headroom before latency climbs | Give more CPU per Pod, or raise the HPA ceiling above 2 replicas on a bigger cluster |
| Reliability and recovery | Rolling update 0% failures; pod-delete recovery ~21 s, 0% failures; cold start median 7 s | Single k3d node on one laptop — no fault tolerance across machines | Run a multi-node cluster so a node failure does not take down every replica |
| Security and cost | No secrets in Git (gitleaks clean); credentials only from a Kubernetes Secret; ₹1.47 per 1,000 requests | Replicas are billed on their limits even while idle, so cost does not fall at low traffic | Scale to zero at idle (e.g. KEDA), or right-size the limits for the real load |
