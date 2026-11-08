"""Inference service for the command parser (Task 3).

A FastAPI app on port 8000 with three endpoints:
  POST /parse    {"text": "..."} -> 200 + the four-key JSON (and nothing else),
                 with headers X-Model-Version and X-Served-By. If the model's
                 output fails schema validation it returns 500
                 {"error": "invalid_model_output"} - never broken JSON with 200.
  GET  /healthz  200 while the process is alive.
  GET  /readyz   503 until the model has loaded, 200 afterwards.

All configuration comes from environment variables:
  MODEL_URI        s3://<bucket>/<prefix> to the model in object storage
                   (a local directory path is also accepted, for development).
  MODEL_VERSION    returned in the X-Model-Version header.
  S3_ENDPOINT      object-storage endpoint.
  MAX_NEW_TOKENS   generation cap per request.
  FAULT_INJECT     when "1", the model output is replaced with "not json"
                   before validation (to exercise the 500 path).
Credentials (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY) come from a Kubernetes
Secret, injected as env vars. The model weights are downloaded at start-up and
are never baked into the image.
"""
import json
import os
import pathlib
import tempfile
import threading
import time

import boto3
import torch
from botocore.client import Config
from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from transformers import AutoModelForCausalLM, AutoTokenizer

# --- configuration (all from the environment) ---
MODEL_URI = os.environ.get("MODEL_URI", "s3://models/v1")
MODEL_VERSION = os.environ.get("MODEL_VERSION", "v1")
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "http://localhost:8333")
MAX_NEW_TOKENS = int(os.environ.get("MAX_NEW_TOKENS", "64"))
FAULT_INJECT = os.environ.get("FAULT_INJECT", "0") == "1"
POD_NAME = os.environ.get("POD_NAME") or os.environ.get("HOSTNAME", "unknown")


def _resolve_schema():
    if os.environ.get("SCHEMA_PATH"):
        return pathlib.Path(os.environ["SCHEMA_PATH"])
    here = pathlib.Path(__file__).resolve().parent
    for cand in (pathlib.Path("/app/schema.json"),
                 here / "schema.json",
                 here.parent / "data" / "schema.json"):
        if cand.exists():
            return cand
    raise FileNotFoundError("schema.json not found (set SCHEMA_PATH)")


SCHEMA = json.loads(_resolve_schema().read_text(encoding="utf-8"))
KEYS = SCHEMA["keys"]                 # ordered: intent, date, time, place
KEYSET = set(KEYS)
INTENTS = set(SCHEMA["intents"])
SLOTS = ("date", "time", "place")

# --- runtime state, filled by the background loader ---
STATE = {"ready": False, "model": None, "tok": None, "error": None}

app = FastAPI(title="command-parser", version=MODEL_VERSION)


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def _download_model(dest: pathlib.Path):
    """Download the model + tokenizer files from object storage into dest."""
    assert MODEL_URI.startswith("s3://")
    bucket, _, prefix = MODEL_URI[len("s3://"):].partition("/")
    prefix = prefix.rstrip("/") + "/"
    c = _s3_client()
    resp = c.list_objects_v2(Bucket=bucket, Prefix=prefix)
    objs = resp.get("Contents", [])
    if not objs:
        raise RuntimeError(f"no objects under {MODEL_URI}")
    for o in objs:
        name = o["Key"].rsplit("/", 1)[-1]
        if not name or name.endswith(".tar.gz") or name.endswith(".sha256"):
            continue  # skip the release archive and checksum; keep model+tokenizer
        c.download_file(bucket, o["Key"], str(dest / name))


def _load_model():
    """Background worker: fetch + load the model (with retries), then flip ready.

    Retries transient failures (e.g. object storage not reachable yet right after
    the cluster starts) so a Pod recovers on its own instead of staying unready.
    """
    for attempt in range(1, 6):
        t0 = time.time()
        try:
            if MODEL_URI.startswith("s3://"):
                print(f"[startup] downloading model {MODEL_VERSION} from object storage "
                      f"{MODEL_URI} (endpoint {S3_ENDPOINT})", flush=True)
                src = pathlib.Path(tempfile.mkdtemp(prefix="model_"))
                _download_model(src)
                print(f"[startup] download complete in {time.time() - t0:.1f}s; loading model",
                      flush=True)
            else:
                src = pathlib.Path(MODEL_URI)   # local directory (development)
                print(f"[startup] loading model from local path {MODEL_URI}", flush=True)
            tok = AutoTokenizer.from_pretrained(src)
            if tok.pad_token is None:
                tok.pad_token = tok.eos_token
            model = AutoModelForCausalLM.from_pretrained(src)
            model.config.pad_token_id = tok.pad_token_id
            model.eval()
            STATE["tok"], STATE["model"] = tok, model
            STATE["ready"] = True
            print(f"[startup] model {MODEL_VERSION} ready in {time.time() - t0:.1f}s", flush=True)
            return
        except Exception as exc:  # noqa: BLE001 - retry transient storage/network errors
            STATE["error"] = repr(exc)
            print(f"[startup] load attempt {attempt} failed: {exc!r}", flush=True)
            time.sleep(5)
    print("[startup] model load gave up after retries", flush=True)


@app.on_event("startup")
def _startup():
    threading.Thread(target=_load_model, daemon=True).start()


def _validate(obj) -> bool:
    """Check one model output against schema.json."""
    if not isinstance(obj, dict) or set(obj.keys()) != KEYSET:
        return False
    if obj.get("intent") not in INTENTS:
        return False
    for slot in SLOTS:
        v = obj.get(slot)
        if v is not None and not isinstance(v, str):
            return False
    return True


def _generate(text: str) -> str:
    tok, model = STATE["tok"], STATE["model"]
    prompt = f"Command: {text}\nJSON: "
    ids = tok(prompt, return_tensors="pt")
    with torch.no_grad():
        gen = model.generate(
            **ids, max_new_tokens=MAX_NEW_TOKENS, do_sample=False, num_beams=1,
            pad_token_id=tok.pad_token_id, eos_token_id=tok.eos_token_id,
        )
    text_out = tok.decode(gen[0][ids["input_ids"].shape[1]:], skip_special_tokens=True)
    return text_out.split("\n", 1)[0].strip()


class ParseIn(BaseModel):
    text: str


@app.get("/healthz")
def healthz():
    return Response(status_code=200)


@app.get("/readyz")
def readyz():
    return Response(status_code=200 if STATE["ready"] else 503)


@app.post("/parse")
def parse(body: ParseIn):
    headers = {"X-Model-Version": MODEL_VERSION, "X-Served-By": POD_NAME}
    if not STATE["ready"]:
        return JSONResponse({"error": "model_not_ready"}, status_code=503, headers=headers)

    raw = _generate(body.text)
    if FAULT_INJECT:
        raw = "not json"

    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        obj = None
    if obj is None or not _validate(obj):
        return JSONResponse({"error": "invalid_model_output"}, status_code=500, headers=headers)

    result = {k: obj[k] for k in KEYS}   # exactly the four keys, in schema order
    return JSONResponse(result, status_code=200, headers=headers)
