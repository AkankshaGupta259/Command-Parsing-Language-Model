# CS3081 Cloud Computing — Mini Project

Knowledge distillation and deployment of a lightweight command-parsing language
model on a local Kubernetes cloud. A teacher model (Phi-3.5 via Ollama) labels a set of natural-language commands; a 70M student (Pythia-70M) is fine-tuned on those labels, containerised as a FastAPI service, and deployed on a k3d cluster with object storage, autoscaling, a CI/CD pipeline, and a performance/cost analysis.

**GitHub repository:** https://github.com/AkankshaGupta259/Command-Parsing-Language-Model

The full write-up is in [`report/report.pdf`](report/report.pdf); AI-tool usage is
disclosed in [`AI_USE.md`](AI_USE.md).

## Repository layout

| Path | Contents |
|---|---|
| `worker/` | Teacher-labelling worker + cleaning (`clean.py`), Dockerfile |
| `training/` | Student fine-tuning (`train.py`), prediction (`predict.py`), `config.yaml`, loss CSVs |
| `service/` | FastAPI inference service + Dockerfile (Task 3) |
| `k8s/` | Kubernetes manifests: `app/` (Deployment, Service, Ingress, HPA), `storage/`, `pipeline/` |
| `network/` | Subnet plan (`subnets.md`) and NACL (`nacl.json`) |
| `scripts/` | `deploy.py` (`make up`), secret + storage bootstrap, model publish |
| `tests/` | pytest unit tests |
| `tools/` | Provided `score.py`, `nacl_sim.py`, `locustfile.py` |
| `.github/workflows/` | CI pipeline (`ci.yml`) |
| `results/` | Evaluation outputs, Locust results, and command-output evidence |
| `report/` | Project report (PDF) |

Model weights are published as **GitHub Release assets**
(`pythia70m-v1.tar.gz`); only the SHA-256 checksums (`models/v*/model.sha256`) are tracked. `make up` downloads the model from the Release into object storage.

## Prerequisites

Docker, [k3d](https://k3d.io), `kubectl`, Python 3.12, and `make` on `PATH`.

```bash
pip install -r requirements-deploy.txt
```

## Build and deploy

Builds the image and deploys the whole system (cluster, object storage, model,
service) from a fresh clone:

```bash
make up
```

Then the service answers through the Ingress:

```bash
curl -s -X POST http://localhost:8080/parse -H "Content-Type: application/json" -d '{"text":"what is the weather in london"}'
```

## Test

```bash
make lint      # ruff
```

```bash
make test      # pytest unit tests
```

```bash
# load test (the standard marking command)
locust -f tools/locustfile.py --headless --users 4 --spawn-rate 4 --run-time 2m --host http://localhost:8080 --csv results/loadtest
```

## Reproduce the model (optional)

```bash
make train                 # train student v1 (first 1500 records)
make train VERSION=v2      # second version
make eval                  # score teacher / base / student on validation.jsonl
make publish VERSION=v1    # upload to object storage + checksum + Release asset
```

## Shut down

Deletes the cluster and everything in it:

```bash
make down
```

---

Commands data from SLURP (Bastianelli et al., EMNLP 2020), CC BY 4.0 —
https://github.com/pswietojanski/slurp
