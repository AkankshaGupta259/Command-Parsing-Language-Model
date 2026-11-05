"""Generate validation predictions for a causal LM (Task 2, step 6).

Runs the student (models/v1) or the untrained base model (EleutherAI/pythia-70m)
over data/validation.jsonl with the same prompt the student was trained on, and
writes one line per command in the format tools/score.py expects:

    {"id": "V001", "prediction": "<the raw text the model produced>"}

Decoding is greedy (deterministic), so re-running gives the same predictions.

Usage:
  python training/predict.py --model models/v1       --out results/student_predictions.jsonl
  python training/predict.py --model EleutherAI/pythia-70m --out results/base_predictions.jsonl
"""
import argparse
import json
import pathlib

import torch
import yaml
from transformers import AutoModelForCausalLM, AutoTokenizer, set_seed

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="model dir or HF id")
    ap.add_argument("--out", required=True, help="output predictions.jsonl")
    ap.add_argument("--data", default="data/validation.jsonl")
    ap.add_argument("--max-new-tokens", type=int, default=64)
    args = ap.parse_args()

    with open(ROOT / "training" / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    set_seed(int(cfg["seed"]))

    model_path = args.model
    if (ROOT / args.model).exists():
        model_path = str(ROOT / args.model)

    tok = AutoTokenizer.from_pretrained(model_path)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(model_path)
    model.config.pad_token_id = tok.pad_token_id
    model.eval()

    rows = []
    with open(ROOT / args.data, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as out:
        for r in rows:
            prompt = f"Command: {r['text']}\nJSON: "
            ids = tok(prompt, return_tensors="pt")
            with torch.no_grad():
                gen = model.generate(
                    **ids,
                    max_new_tokens=args.max_new_tokens,
                    do_sample=False,
                    num_beams=1,
                    pad_token_id=tok.pad_token_id,
                    eos_token_id=tok.eos_token_id,
                )
            text = tok.decode(gen[0][ids["input_ids"].shape[1]:],
                              skip_special_tokens=True)
            # The target is a single JSON line; keep only the first line.
            prediction = text.split("\n", 1)[0].strip()
            out.write(json.dumps({"id": r["id"], "prediction": prediction},
                                 ensure_ascii=False) + "\n")

    print(f"[predict] {len(rows)} predictions -> {out_path}")


if __name__ == "__main__":
    main()
