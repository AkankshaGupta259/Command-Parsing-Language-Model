# Task 4 — Kubernetes deployment, scaling, and reliability (evidence)

Deploy with `kubectl apply -f k8s/app/` (namespace `app`). Image imported with
`k3d image import cs3081-service:latest -c cs3081`.

## Deployment, Service, Ingress

```
$ kubectl get deploy,svc,ingress,hpa -n app
deployment/parser   2 replicas, image cs3081-service:latest
service/parser      ClusterIP, port 80 -> targetPort 8000
ingress/parser      traefik, path / -> parser:80
hpa/parser          min 1, max 2, target 70% CPU
```

`/parse` answers through the Ingress (k3d maps host 8080 -> Traefik 80):

```
GET  http://localhost:8080/healthz  -> 200
GET  http://localhost:8080/readyz   -> 200
POST http://localhost:8080/parse {"text":"what is the weather in london"}
  -> 200 {"intent":"weather_query","date":null,"time":null,"place":"london"}
     X-Model-Version: v1   X-Served-By: parser-...-c58qv  (Pod name)
```

- **Requests/limits:** requests `cpu 100m, memory 512Mi`; limits `cpu 1, memory 1Gi`.
- **Probes:** liveness `GET /healthz`, readiness `GET /readyz`.
- **No endpoints while loading:** immediately after `apply`, the Service endpoints
  are `<none>` until the readiness probe passes (model downloaded + loaded); only
  then do Pods receive traffic.

## HPA scaling (1 -> 2 -> 1)

Captured during the standard 4-user load (CPU request 100m so load crosses 70%):

```
00:57:51  replicas=1  cpu=3%     at rest
00:58:53  replicas=2  cpu=999%   under load  -> scaled UP 1->2
01:01:18  replicas=1  cpu=3%     load ended  -> scaled DOWN 2->1
```

(Full file: `results/task4_hpa_timeline.txt`.)

## Load balancing (standard load test, 2 replicas)

`locust -f tools/locustfile.py --headless --users 4 --spawn-rate 4 --run-time 2m
--host http://localhost:8080 --csv results/loadtest`

```
147 requests, 0 failures (0.00%)
per replica:  parser-...-8q7gs = 87 (59%),  parser-...-xx7gn = 61 (41%)   # both >= 30%
per model version: v1 = 148
latency: median 3.5s, p95 6.1s     throughput 1.24 req/s
```

(Files: `results/loadtest_stats.csv`, `results/loadtest_headers.json`.)

## Rolling update v1 -> v2 and rollback

Under load, `kubectl set env deployment/parser MODEL_VERSION=v2 MODEL_URI=s3://models/v2`,
then `kubectl rollout undo`. A `preStop` drain (sleep 8) + `maxUnavailable: 0`
keep the service up during Pod replacement.

```
BEFORE:   X-Model-Version: v1
AFTER set env v2:   X-Model-Version: v2
AFTER rollout undo: X-Model-Version: v1   (6/6 requests)
load during the update: 233 requests, 0 failures (0.00%)   # limit 0.5%
version split while updating: v1 = 202, v2 = 31
```

(Files: `results/rollout_stats.csv`, `results/rollout_headers.json`.)

## Recovery (delete a Pod under load)

```
delete pod parser-...-lqttt           01:10:37
restored to 2 ready replicas          01:10:58   (~21s; new pod parser-...-kdbkd)
load during recovery: 147 requests, 0 failures (0.00%)   # limit 2%
```

The surviving replica served throughout; the Deployment recreated the deleted Pod.

## Cold start (delete all Pods, 3 runs)

```
run 1: creation->Ready = 7s
run 2: creation->Ready = 7s
run 3: creation->Ready = 7s
MEDIAN = 7s
```

Each new Pod logs the download from object storage (no weights in the image):

```
[startup] downloading model v1 from object storage s3://models/v1 (endpoint http://seaweedfs.data.svc.cluster.local:8333)
[startup] download complete in 1.8s; loading model
[startup] model v1 ready in 2.7s
```

(The 7s creation->Ready includes the 5s readiness-probe initial delay; the model
itself downloads + loads in ~2.7s from in-cluster object storage.)

## Limitation of the local cluster

The cluster is a single k3d node on one laptop. The HPA can only scale between 1
and 2 replicas, and every replica shares the same physical host, so this setup
demonstrates horizontal scaling and self-healing but **not fault tolerance across
machines** - if the node (laptop) fails, every replica fails with it.
