"""`make up` orchestrator (Task 6): build and deploy the whole system from a
fresh clone.

Steps:
  1. create the k3d cluster from cluster/k3d.yaml
  2. create namespaces and the Kubernetes Secrets (scripts/setup_secrets.py)
  3. deploy SeaweedFS object storage and wait for it
  4. download the trained model from the GitHub Release and upload it to the
     `models` bucket (the weights are never in Git or the image)
  5. build the service image and import it into the cluster
  6. deploy the app (Deployment, Service, Ingress, HPA) and wait until Ready

`make down` simply deletes the cluster, which removes everything.

Run via the Makefile:  make up   (teardown: make down)
Requires on PATH: k3d, kubectl, docker, git. Python deps: boto3, requests, pyyaml
(install with `pip install -r requirements-deploy.txt`).
"""
import io
import pathlib
import subprocess
import sys
import tarfile
import time

import boto3
import requests
from botocore.client import Config

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLUSTER = "cs3081"
NAMESPACES = ["data", "pipeline", "app"]
MODELS_BUCKET = "models"
MODEL_VERSIONS = ["v1"]          # v1 is the released model the service runs on


def run(cmd, check=True, capture=False, **kw):
    print(f"  $ {' '.join(cmd)}", flush=True)
    r = subprocess.run(cmd, text=True, capture_output=capture, **kw)
    if check and r.returncode != 0:
        if capture:
            sys.stderr.write(r.stdout or "")
            sys.stderr.write(r.stderr or "")
        sys.exit(f"command failed ({r.returncode}): {' '.join(cmd)}")
    return r


def step(n, msg):
    print(f"\n=== [{n}] {msg} ===", flush=True)


def cluster_exists():
    r = subprocess.run(["k3d", "cluster", "list", CLUSTER], text=True, capture_output=True)
    return r.returncode == 0 and CLUSTER in r.stdout


def release_base():
    """Derive the GitHub Release download base URL from the git remote."""
    url = subprocess.check_output(["git", "remote", "get-url", "origin"], text=True).strip()
    if url.endswith(".git"):
        url = url[:-4]
    if url.startswith("git@github.com:"):
        path = url.split("git@github.com:", 1)[1]
    else:
        path = url.split("github.com/", 1)[1]
    return f"https://github.com/{path}/releases/download"


def load_s3_env():
    env = {}
    for line in (ROOT / ".secrets" / "s3.env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def s3_client(env):
    return boto3.client(
        "s3", endpoint_url="http://localhost:8333",
        aws_access_key_id=env["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=env["AWS_SECRET_ACCESS_KEY"],
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def wait_port_forward(c, tries=30):
    for _ in range(tries):
        try:
            c.list_buckets()
            return True
        except Exception:
            time.sleep(1)
    return False


def fetch_model(c, version):
    url = f"{release_base()}/{version}/pythia70m-{version}.tar.gz"
    print(f"  downloading {url}", flush=True)
    resp = requests.get(url, timeout=300)
    resp.raise_for_status()
    with tarfile.open(fileobj=io.BytesIO(resp.content)) as tar:
        n = 0
        for m in tar.getmembers():
            if not m.isfile():
                continue
            body = tar.extractfile(m).read()
            c.put_object(Bucket=MODELS_BUCKET, Key=m.name, Body=body)  # key e.g. v1/config.json
            n += 1
        print(f"  uploaded {n} files to {MODELS_BUCKET}/{version}/", flush=True)


def fix_kubeconfig():
    """Point kubectl at the API server on loopback.

    k3d writes the kubeconfig with host.docker.internal, which on some hosts
    resolves to a LAN address that is not reachable; the API server is always
    published on the host's loopback, so 127.0.0.1:<port> is the reliable target.
    """
    try:
        out = subprocess.check_output(
            ["docker", "port", f"k3d-{CLUSTER}-serverlb", "6443/tcp"], text=True)
        port = out.strip().splitlines()[0].rsplit(":", 1)[1]
        subprocess.run(["kubectl", "config", "set-cluster", f"k3d-{CLUSTER}",
                        f"--server=https://127.0.0.1:{port}"], capture_output=True, text=True)
        print(f"  kubectl -> https://127.0.0.1:{port}")
    except Exception as exc:  # noqa: BLE001
        print(f"  (could not adjust kubeconfig: {exc})")


def up():
    # 1. cluster
    step(1, "k3d cluster")
    if cluster_exists():
        print("  cluster already exists; reusing")
    else:
        run(["k3d", "cluster", "create", "--config", str(ROOT / "cluster" / "k3d.yaml")])
    fix_kubeconfig()

    # 2. namespaces + secrets
    step(2, "namespaces and secrets")
    for ns in NAMESPACES:
        subprocess.run(["kubectl", "create", "namespace", ns], capture_output=True, text=True)
    run([sys.executable, str(ROOT / "scripts" / "setup_secrets.py")])

    # 3. object storage
    step(3, "deploy SeaweedFS and wait")
    run(["kubectl", "apply", "-f", str(ROOT / "k8s" / "storage" / "seaweedfs.yaml")])
    run(["kubectl", "wait", "-n", "data", "--for=condition=ready", "pod",
         "-l", "app=seaweedfs", "--timeout=180s"])

    # 4. model from the GitHub Release -> object storage (via a port-forward)
    step(4, "download model from GitHub Release -> object storage")
    pf = subprocess.Popen(["kubectl", "port-forward", "-n", "data",
                           "svc/seaweedfs", "8333:8333"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        env = load_s3_env()
        c = s3_client(env)
        if not wait_port_forward(c):
            sys.exit("port-forward to SeaweedFS never became ready")
        if MODELS_BUCKET not in {b["Name"] for b in c.list_buckets().get("Buckets", [])}:
            c.create_bucket(Bucket=MODELS_BUCKET)
        for v in MODEL_VERSIONS:
            fetch_model(c, v)
    finally:
        pf.terminate()

    # 5. build + import the service image
    step(5, "build and import the service image")
    run(["docker", "build", "-f", str(ROOT / "service" / "Dockerfile"),
         "-t", "cs3081-service:latest", str(ROOT)])
    run(["k3d", "image", "import", "cs3081-service:latest", "-c", CLUSTER])

    # 6. deploy the app
    step(6, "deploy the service and wait until Ready")
    run(["kubectl", "apply", "-f", str(ROOT / "k8s" / "app")])
    run(["kubectl", "rollout", "status", "deployment/parser", "-n", "app", "--timeout=200s"])

    print("\nSystem is up. Try it:")
    print('  curl -s -X POST http://localhost:8080/parse '
          '-H "Content-Type: application/json" -d \'{"text":"what is the weather in london"}\'')


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "up"
    if action == "up":
        up()
    else:
        sys.exit(f"unknown action {action!r} (use: up)")
