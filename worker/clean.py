"""Clean the teacher shard outputs into the training set (Task 1, step 6).

Reads every datasets/teacher/shard-*.jsonl, removes the bad records, and writes the
rest (in id order) to datasets/v1/train.jsonl plus its SHA-256 to
datasets/v1/train.sha256. Also saves local copies and a counts report.

Removal rules (each input record falls into exactly one bucket, checked in order):
  (a) invalid_json  reply is not parseable JSON
  (b) bad_keys      not an object, or keys != {intent, date, time, place}
  (c) bad_intent    intent is not one of the eight
  (d) bad_slot      a slot value is neither null nor text that appears in the command
  duplicates        same command text seen already (the smallest id is kept)
  kept              survives all of the above

Invariant: input == a + b + c + d + duplicates + kept.

Determinism: records are processed in id order and serialised with a fixed key
order, so the same shards always produce the same train.jsonl and the same checksum.
"""
import hashlib
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

# Host fallback: if S3 env is not already set (i.e. running outside the cluster),
# load credentials from .secrets/s3.env and default to the port-forwarded endpoint.
if "AWS_ACCESS_KEY_ID" not in os.environ:
    env_file = ROOT / ".secrets" / "s3.env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    os.environ.setdefault("S3_ENDPOINT", os.environ.get("S3_ENDPOINT_HOST", "http://localhost:8333"))

from s3_util import s3_client  # noqa: E402

DATASETS_BUCKET = os.environ.get("DATASETS_BUCKET", "datasets")
SHARD_PREFIX = "teacher/"
TRAIN_KEY = "v1/train.jsonl"
SHA_KEY = "v1/train.sha256"
INTENTS = {
    "alarm_set", "alarm_query", "calendar_set", "calendar_query",
    "calendar_remove", "weather_query", "datetime_query", "recommendation_events",
}
KEYS = {"intent", "date", "time", "place"}


def norm(v):
    return " ".join(str(v).strip().lower().split())


def read_shards(c):
    """Return a list of (id, text, teacher_raw) from every shard object, id-sorted."""
    records = []
    resp = c.list_objects_v2(Bucket=DATASETS_BUCKET, Prefix=SHARD_PREFIX)
    objs = [o["Key"] for o in resp.get("Contents", []) if o["Key"].endswith(".jsonl")]
    if not objs:
        sys.exit(f"no shard objects under {DATASETS_BUCKET}/{SHARD_PREFIX}")
    for key in sorted(objs):
        body = c.get_object(Bucket=DATASETS_BUCKET, Key=key)["Body"].read().decode("utf-8")
        for line in body.splitlines():
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            records.append((r["id"], r["text"], r.get("teacher_raw", "")))
    records.sort(key=lambda t: t[0])
    return records


def classify(text, raw):
    """Return (bucket, cleaned_obj_or_None) for one record, per rules (a)-(d)."""
    try:
        obj = json.loads(str(raw).strip())
    except (json.JSONDecodeError, TypeError):
        return "invalid_json", None
    if not isinstance(obj, dict) or set(obj.keys()) != KEYS:
        return "bad_keys", None
    if obj["intent"] not in INTENTS:
        return "bad_intent", None
    tnorm = norm(text)
    for slot in ("date", "time", "place"):
        v = obj[slot]
        if v is not None and norm(v) not in tnorm:
            return "bad_slot", None
    return "kept", obj


def main():
    c = s3_client()
    records = read_shards(c)

    counts = {"invalid_json": 0, "bad_keys": 0, "bad_intent": 0,
              "bad_slot": 0, "duplicates": 0, "kept": 0}
    seen_text = set()
    kept_lines = []
    for cid, text, raw in records:
        bucket, obj = classify(text, raw)
        if bucket != "kept":
            counts[bucket] += 1
            continue
        if norm(text) in seen_text:
            counts["duplicates"] += 1
            continue
        seen_text.add(norm(text))
        counts["kept"] += 1
        kept_lines.append(json.dumps(
            {"id": cid, "text": text, "intent": obj["intent"],
             "date": obj["date"], "time": obj["time"], "place": obj["place"]},
            ensure_ascii=False,
        ))

    train_bytes = ("\n".join(kept_lines) + "\n").encode("utf-8")
    digest = hashlib.sha256(train_bytes).hexdigest()
    sha_bytes = f"{digest}  train.jsonl\n".encode("utf-8")

    # Upload to object storage.
    c.put_object(Bucket=DATASETS_BUCKET, Key=TRAIN_KEY, Body=train_bytes)
    c.put_object(Bucket=DATASETS_BUCKET, Key=SHA_KEY, Body=sha_bytes)

    # Local copies (git-ignored) for training + evidence.
    (ROOT / "datasets" / "v1").mkdir(parents=True, exist_ok=True)
    (ROOT / "datasets" / "v1" / "train.jsonl").write_bytes(train_bytes)
    (ROOT / "datasets" / "v1" / "train.sha256").write_bytes(sha_bytes)
    (ROOT / "results").mkdir(exist_ok=True)

    total = len(records)
    report = {
        "input_records": total,
        "rejected_invalid_json": counts["invalid_json"],
        "rejected_bad_keys": counts["bad_keys"],
        "rejected_bad_intent": counts["bad_intent"],
        "rejected_bad_slot": counts["bad_slot"],
        "duplicates": counts["duplicates"],
        "kept": counts["kept"],
        "sha256": digest,
    }
    (ROOT / "results" / "clean_report.json").write_text(json.dumps(report, indent=2))

    check = (counts["invalid_json"] + counts["bad_keys"] + counts["bad_intent"]
             + counts["bad_slot"] + counts["duplicates"] + counts["kept"])
    print("\n  Counts")
    print(f"  input records ............... {total}")
    print(f"  (a) invalid JSON ............ {counts['invalid_json']}")
    print(f"  (b) wrong keys .............. {counts['bad_keys']}")
    print(f"  (c) bad intent .............. {counts['bad_intent']}")
    print(f"  (d) hallucinated slot ....... {counts['bad_slot']}")
    print(f"  duplicates .................. {counts['duplicates']}")
    print(f"  kept ........................ {counts['kept']}")
    print(f"  a+b+c+d+dup+kept ............ {check}  (== input: {check == total})")
    print(f"\n  SHA-256: {digest}")
    print(f"  wrote {DATASETS_BUCKET}/{TRAIN_KEY}, {DATASETS_BUCKET}/{SHA_KEY}, and local datasets/v1/")


if __name__ == "__main__":
    main()
