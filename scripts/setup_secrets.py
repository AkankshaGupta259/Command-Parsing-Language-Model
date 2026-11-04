"""Generate S3 credentials and create the Kubernetes Secrets — no secrets in git.

What it does (idempotent):
  1. Loads S3 keys from .secrets/s3.env, or generates random ones on first run
     and saves them there (.secrets/ is git-ignored).
  2. Builds the SeaweedFS S3 identity config (s3config.json) and stores it as the
     Secret `seaweedfs-s3-config` in namespace `data` (mounted by the SeaweedFS pod).
  3. Stores the client credentials as the Secret `s3-credentials` in namespaces
     data, pipeline and app (consumed by the bootstrap, the workers and the service).

Run:  python scripts/setup_secrets.py
Requires: kubectl on PATH pointing at the k3d cluster.
"""
import json
import os
import pathlib
import secrets
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SECRETS_DIR = ROOT / ".secrets"
ENV_FILE = SECRETS_DIR / "s3.env"

# In-cluster S3 endpoint (DNS of the seaweedfs Service in namespace data).
IN_CLUSTER_ENDPOINT = "http://seaweedfs.data.svc.cluster.local:8333"
NAMESPACES = ["data", "pipeline", "app"]


def load_or_create_keys():
    if ENV_FILE.exists():
        kv = {}
        for line in ENV_FILE.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                kv[k.strip()] = v.strip()
        if "AWS_ACCESS_KEY_ID" in kv and "AWS_SECRET_ACCESS_KEY" in kv:
            print(f"reusing keys from {ENV_FILE}")
            return kv["AWS_ACCESS_KEY_ID"], kv["AWS_SECRET_ACCESS_KEY"]
    SECRETS_DIR.mkdir(exist_ok=True)
    access = "cs3081" + secrets.token_hex(6)
    secret = secrets.token_hex(20)
    ENV_FILE.write_text(
        f"# Generated S3 credentials for SeaweedFS. DO NOT COMMIT.\n"
        f"AWS_ACCESS_KEY_ID={access}\nAWS_SECRET_ACCESS_KEY={secret}\n"
        f"S3_ENDPOINT_HOST=http://localhost:8333\n"
    )
    print(f"generated new keys -> {ENV_FILE}")
    return access, secret


def kubectl(*args, stdin=None):
    r = subprocess.run(["kubectl", *args], input=stdin, text=True, capture_output=True)
    if r.returncode != 0:
        sys.exit(f"kubectl {' '.join(args)} failed:\n{r.stderr}")
    return r.stdout


def recreate_secret_from_literals(name, ns, literals):
    kubectl("delete", "secret", name, "-n", ns, "--ignore-not-found")
    args = ["create", "secret", "generic", name, "-n", ns]
    for k, v in literals.items():
        args += [f"--from-literal={k}={v}"]
    kubectl(*args)
    print(f"  secret/{name} -> namespace {ns}")


def recreate_secret_from_file(name, ns, filekey, content):
    tmp = SECRETS_DIR / filekey
    tmp.write_text(content)
    try:
        kubectl("delete", "secret", name, "-n", ns, "--ignore-not-found")
        kubectl("create", "secret", "generic", name, "-n", ns, f"--from-file={filekey}={tmp}")
        print(f"  secret/{name} -> namespace {ns}")
    finally:
        tmp.unlink(missing_ok=True)


def main():
    access, secret = load_or_create_keys()

    s3config = {
        "identities": [
            {
                "name": "cs3081",
                "credentials": [{"accessKey": access, "secretKey": secret}],
                "actions": ["Admin", "Read", "Write", "List", "Tagging"],
            }
        ]
    }
    print("creating Secrets:")
    recreate_secret_from_file(
        "seaweedfs-s3-config", "data", "s3config.json", json.dumps(s3config, indent=2)
    )
    creds = {
        "AWS_ACCESS_KEY_ID": access,
        "AWS_SECRET_ACCESS_KEY": secret,
        "S3_ENDPOINT": IN_CLUSTER_ENDPOINT,
    }
    for ns in NAMESPACES:
        recreate_secret_from_literals("s3-credentials", ns, creds)
    print("done.")


if __name__ == "__main__":
    main()
