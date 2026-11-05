# Task 3 — Container evidence

Image built from a fresh checkout with one command:

```
docker build -f service/Dockerfile -t cs3081-service:latest .
```

## Image size (limit: 2 GB)

```
$ docker images cs3081-service:latest --format "{{.Repository}}:{{.Tag}}  {{.Size}}"
cs3081-service:latest  1.6GB
```

The image contains **no model weights** (CPU-only torch; the model is downloaded
from object storage at start-up). 1.6 GB < 2 GB.

## Running under 1 CPU and 1 GiB

```
docker run -d --name cs3081-svc --cpus=1 --memory=1g -p 8000:8000 \
  -e MODEL_URI=s3://models/v1 -e MODEL_VERSION=v1 \
  -e S3_ENDPOINT=http://host.docker.internal:8333 \
  -e MAX_NEW_TOKENS=64 \
  -e AWS_ACCESS_KEY_ID=*** -e AWS_SECRET_ACCESS_KEY=*** \
  cs3081-service:latest
```

The service downloaded the model from `s3://models/v1` at start-up, then 50
requests (the first 50 commands of `validation.jsonl`) were sent one after
another:

```
readyz -> 200 after model load
healthz: 200
50 requests: status codes {200: 50}        # all succeeded
latency: min 2.59s  median 2.90s  max 5.30s  (single CPU core)
PEAK MEMORY: 424.2MiB / 1GiB   (~424 MiB of the 1024 MiB limit)
OOMKilled: false
```

Peak memory **424 MiB** is well under the 1 GiB limit and there was no
out-of-memory kill.

## Endpoints and headers

```
GET  /healthz            -> 200
GET  /readyz             -> 503 before the model loads, 200 after
POST /parse {"text":...} -> 200 + four-key JSON only, e.g.
     {"intent":"weather_query","date":null,"time":null,"place":"london"}
     response headers:  X-Model-Version: v1   X-Served-By: 8e1e54f5bab3
```

`X-Served-By` is the container hostname (the Pod name when deployed on
Kubernetes).

## Validation / FAULT_INJECT

With `FAULT_INJECT=1` the model output is replaced with `not json` before the
schema check, so `/parse` must return 500. Verified in-container:

```
FAULT_INJECT=1  ->  POST /parse  ->  500  {"error":"invalid_model_output"}
```

The service never returns broken JSON with HTTP 200.
