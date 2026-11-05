r"""Publish a trained model to object storage + build the release asset (Task 2).

For the given version it:
  1. uploads every file in models/<version>/ to the `models` bucket under
     <version>/ (the service downloads from here at start-up in Task 3/4);
  2. builds a reproducible archive  models/<version>/pythia70m-<version>.tar.gz
     (sorted members, fixed timestamps) to use as the GitHub Release asset;
  3. writes its SHA-256 to  models/<version>/model.sha256  (committed to Git);
  4. uploads the archive + checksum to the bucket too, and prints the
     `gh release` command to attach the asset.

Run from the host with the SeaweedFS port-forward open:
  kubectl port-forward -n data svc/seaweedfs 8333:8333
  .\.venv\Scripts\python.exe scripts\publish_model.py --version v1
"""
import argparse
import gzip
import hashlib
import io
import os
import pathlib
import sys
import tarfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

# Host fallback: load S3 creds from .secrets/s3.env and default to the
# port-forwarded endpoint when not already running inside the cluster.
if "AWS_ACCESS_KEY_ID" not in os.environ:
    env_file = ROOT / ".secrets" / "s3.env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    os.environ.setdefault("S3_ENDPOINT",
                          os.environ.get("S3_ENDPOINT_HOST", "http://localhost:8333"))

from s3_util import s3_client, ensure_bucket  # noqa: E402

MODELS_BUCKET = os.environ.get("MODELS_BUCKET", "models")


def model_files(model_dir):
    """All files in the model dir, sorted by relative path (deterministic)."""
    files = [p for p in model_dir.rglob("*") if p.is_file()]
    return sorted(files, key=lambda p: str(p.relative_to(model_dir)).replace("\\", "/"))


def build_archive(model_dir, files, arcprefix):
    """Reproducible .tar.gz bytes: sorted names, zeroed mtime/uid/gid."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        for p in files:
            rel = str(p.relative_to(model_dir)).replace("\\", "/")
            ti = tarfile.TarInfo(name=f"{arcprefix}/{rel}")
            data = p.read_bytes()
            ti.size = len(data)
            ti.mtime = 0
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = ""
            ti.mode = 0o644
            tar.addfile(ti, io.BytesIO(data))
    gz = io.BytesIO()
    with gzip.GzipFile(fileobj=gz, mode="wb", mtime=0) as g:
        g.write(raw.getvalue())
    return gz.getvalue()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", choices=["v1", "v2"], default="v1")
    args = ap.parse_args()

    model_dir = ROOT / "models" / args.version
    if not model_dir.exists():
        sys.exit(f"{model_dir} not found - train {args.version} first")

    files = model_files(model_dir)
    if not files:
        sys.exit(f"no files in {model_dir}")

    c = s3_client()
    ensure_bucket(c, MODELS_BUCKET)

    # 1. Upload each model/tokenizer file.
    print(f"[publish] uploading {len(files)} files to {MODELS_BUCKET}/{args.version}/")
    for p in files:
        rel = str(p.relative_to(model_dir)).replace("\\", "/")
        c.put_object(Bucket=MODELS_BUCKET, Key=f"{args.version}/{rel}",
                     Body=p.read_bytes())
        print(f"    {args.version}/{rel}  ({p.stat().st_size} bytes)")

    # 2-3. Build the release archive and its checksum.
    arc_name = f"pythia70m-{args.version}.tar.gz"
    arc_bytes = build_archive(model_dir, files, arcprefix=args.version)
    arc_path = model_dir / arc_name
    arc_path.write_bytes(arc_bytes)
    digest = hashlib.sha256(arc_bytes).hexdigest()
    sha_line = f"{digest}  {arc_name}\n"
    (model_dir / "model.sha256").write_text(sha_line, encoding="utf-8")

    # 4. Also keep the archive + checksum in object storage.
    c.put_object(Bucket=MODELS_BUCKET, Key=f"{args.version}/{arc_name}", Body=arc_bytes)
    c.put_object(Bucket=MODELS_BUCKET, Key=f"{args.version}/model.sha256",
                 Body=sha_line.encode("utf-8"))

    print(f"\n[publish] archive  -> {arc_path}  ({len(arc_bytes)} bytes)")
    print(f"[publish] checksum -> {model_dir / 'model.sha256'}")
    print(f"[publish] SHA-256  :  {digest}")
    print("\n[publish] attach the asset to a GitHub Release with:")
    print(f'    gh release create {args.version} "{arc_path}" '
          f'--title "pythia-70m student {args.version}" '
          f'--notes "SHA-256: {digest}"')
    print("  (or upload to an existing release:)")
    print(f'    gh release upload {args.version} "{arc_path}"')


if __name__ == "__main__":
    main()
