"""Sharded teacher-labelling worker (Task 1, steps 4-5).

Each worker handles one shard of the command pool, decided by two environment
variables:
  SHARD_INDEX   this worker's index, 0-based
  SHARD_COUNT   total number of workers

It takes every command whose line number (counting from 0) leaves remainder
SHARD_INDEX when divided by SHARD_COUNT, sends it to the Phi-3.5 teacher, and
writes one line per command to its own object:
  {"id": ..., "text": ..., "teacher_raw": "<the teacher's exact reply>"}
  -> datasets/teacher/shard-<SHARD_INDEX>.jsonl

The reply is stored exactly as generated (handout requirement). The run is
resumable: on restart it reloads the shard already written and skips finished ids,
and it re-uploads the whole shard every CHECKPOINT_EVERY commands.

Config (env): SHARD_INDEX, SHARD_COUNT, plus S3_ENDPOINT / AWS_* (s3_util) and
OLLAMA_HOST / TEACHER_MODEL / PROMPT_PATH (teacher_client).
"""
import json
import os
import sys
import time

from botocore.exceptions import ClientError

from s3_util import s3_client
from teacher_client import OLLAMA_HOST, TEACHER_MODEL, health, label, load_prompt

SHARD_INDEX = int(os.environ["SHARD_INDEX"])
SHARD_COUNT = int(os.environ["SHARD_COUNT"])
DATASETS_BUCKET = os.environ.get("DATASETS_BUCKET", "datasets")
COMMANDS_KEY = os.environ.get("COMMANDS_KEY", "commands_pool.jsonl")
SHARD_KEY = f"teacher/shard-{SHARD_INDEX}.jsonl"
CHECKPOINT_EVERY = int(os.environ.get("CHECKPOINT_EVERY", "50"))


def log(msg):
    print(f"[shard {SHARD_INDEX}/{SHARD_COUNT}] {msg}", flush=True)


def wait_for_teacher(max_wait=600):
    t0 = time.time()
    while time.time() - t0 < max_wait:
        if health():
            return
        log(f"waiting for teacher '{TEACHER_MODEL}' at {OLLAMA_HOST} ...")
        time.sleep(5)
    sys.exit(f"teacher not reachable at {OLLAMA_HOST} after {max_wait}s")


def load_existing(c):
    """Return {id: json_line_str} already written for this shard (resume support)."""
    done = {}
    try:
        body = c.get_object(Bucket=DATASETS_BUCKET, Key=SHARD_KEY)["Body"].read().decode("utf-8")
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404", "NoSuchBucket"):
            return done
        raise
    for line in body.splitlines():
        line = line.strip()
        if line:
            try:
                done[json.loads(line)["id"]] = line
            except Exception:  # noqa: BLE001
                pass
    return done


def upload_shard(c, results):
    body = "\n".join(results[i] for i in sorted(results)) + "\n"
    c.put_object(Bucket=DATASETS_BUCKET, Key=SHARD_KEY, Body=body.encode("utf-8"))


def main():
    if not (0 <= SHARD_INDEX < SHARD_COUNT):
        sys.exit(f"need 0 <= SHARD_INDEX < SHARD_COUNT (got {SHARD_INDEX}/{SHARD_COUNT})")

    c = s3_client()
    wait_for_teacher()
    template = load_prompt()

    raw = c.get_object(Bucket=DATASETS_BUCKET, Key=COMMANDS_KEY)["Body"].read().decode("utf-8")
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    mine = [json.loads(ln) for n, ln in enumerate(lines) if n % SHARD_COUNT == SHARD_INDEX]
    log(f"{len(lines)} commands total, {len(mine)} in this shard")

    results = load_existing(c)
    if results:
        log(f"resuming: {len(results)} already done, skipping those")

    t0 = time.time()
    processed = 0
    for cmd in mine:
        if cmd["id"] in results:
            continue
        reply = label(cmd["text"], template=template)
        results[cmd["id"]] = json.dumps(
            {"id": cmd["id"], "text": cmd["text"], "teacher_raw": reply}, ensure_ascii=False
        )
        processed += 1
        if processed % CHECKPOINT_EVERY == 0:
            upload_shard(c, results)
            rate = processed / (time.time() - t0)
            log(f"{len(results)}/{len(mine)} done ({rate:.2f} cmd/s), checkpoint saved")

    upload_shard(c, results)
    log(f"FINISHED: {len(results)}/{len(mine)} commands -> {DATASETS_BUCKET}/{SHARD_KEY} "
        f"in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
