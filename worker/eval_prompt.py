"""Run the teacher prompt over a set of commands and write predictions for score.py.

This is the prompt-development / teacher-evaluation harness. It is NOT the sharded
labelling worker (that is label.py) - it runs locally against the host Ollama so we
can measure how good the prompt is before committing to labelling all 3,000 commands.

Usage
  python worker/eval_prompt.py INPUT.jsonl OUTPUT.jsonl [--limit N]

INPUT   JSON Lines with at least {"id": ..., "text": ...} per line
        (both data/commands_pool.jsonl and data/validation.jsonl match this).
OUTPUT  JSON Lines with {"id": ..., "prediction": "<raw teacher reply>"} per line,
        exactly the format tools/score.py expects.

Then score it:
  python tools/score.py OUTPUT.jsonl data/validation.jsonl
"""
import argparse
import json
import sys
import time

from teacher_client import OLLAMA_HOST, TEACHER_MODEL, health, label, load_prompt


def read_jsonl(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--limit", type=int, default=None, help="only process the first N commands")
    a = ap.parse_args()

    if not health():
        sys.exit(
            f"Ollama at {OLLAMA_HOST} is not reachable or model '{TEACHER_MODEL}' is not pulled.")

    template = load_prompt()
    rows = read_jsonl(a.input)
    if a.limit:
        rows = rows[: a.limit]

    t0 = time.time()
    with open(a.output, "w", encoding="utf-8") as out:
        for i, r in enumerate(rows, 1):
            reply = label(r["text"], template=template)
            out.write(json.dumps({"id": r["id"], "prediction": reply}) + "\n")
            out.flush()
            if i % 10 == 0 or i == len(rows):
                rate = i / (time.time() - t0)
                print(f"  {i}/{len(rows)}  ({rate:.2f} cmd/s)", file=sys.stderr)

    dt = time.time() - t0
    print(f"wrote {len(rows)} predictions to {a.output} in {dt:.1f}s", file=sys.stderr)
    print(f"now score:  python tools/score.py {a.output} data/validation.jsonl", file=sys.stderr)


if __name__ == "__main__":
    main()
