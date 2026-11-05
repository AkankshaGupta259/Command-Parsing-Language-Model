"""Fine-tune EleutherAI/pythia-70m on the teacher-generated labels (Task 2).

Sequence-level knowledge distillation: the student is trained directly on the
teacher's JSON replies. For each command we build one example

    Command: <the command>
    JSON: <the teacher's JSON reply>

and train the causal LM to produce the JSON given the command. Loss is computed
only on the JSON part (the prompt tokens are masked with -100), so the model
learns to *continue* a command into its label rather than to echo the command.

Everything that affects the result is read from training/config.yaml:
  seed, learning_rate, batch_size, epochs, max_seq_length, library_versions.

Usage (normally invoked through the Makefile):
  python training/train.py                 # v1, first 1500 records
  python training/train.py --subset 50     # smoke test, first 50 records
  python training/train.py --version v2    # second version (extra epochs)

Outputs:
  models/<version>/            trained model + tokenizer (git-ignored)
  training/loss.csv            epoch,loss for v1  (loss_v2.csv for v2)
"""
import argparse
import csv
import json
import pathlib
import time

import torch
import yaml
from torch.utils.data import Dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    Trainer,
    TrainerCallback,
    TrainingArguments,
    set_seed,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "training" / "config.yaml"


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def read_records(train_file, n):
    """Return the first n records of the cleaned training set (id order)."""
    path = ROOT / train_file
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
            if len(rows) >= n:
                break
    return rows


def target_json(rec):
    """The teacher's reply in canonical four-key form (the training target)."""
    return json.dumps(
        {"intent": rec["intent"], "date": rec["date"],
         "time": rec["time"], "place": rec["place"]},
        ensure_ascii=False,
    )


class CommandJSONDataset(Dataset):
    """Tokenised examples with the prompt masked out of the loss."""

    def __init__(self, records, tokenizer, max_len):
        self.examples = []
        eos = tokenizer.eos_token
        for rec in records:
            prompt = f"Command: {rec['text']}\nJSON: "
            target = target_json(rec) + eos
            p_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
            t_ids = tokenizer(target, add_special_tokens=False)["input_ids"]
            input_ids = (p_ids + t_ids)[:max_len]
            labels = ([-100] * len(p_ids) + t_ids)[:max_len]
            self.examples.append({"input_ids": input_ids, "labels": labels})

    def __len__(self):
        return len(self.examples)

    def __getitem__(self, i):
        return self.examples[i]


class Collator:
    """Pad input_ids with the pad id and labels with -100 to the batch max."""

    def __init__(self, pad_id):
        self.pad_id = pad_id

    def __call__(self, batch):
        maxlen = max(len(b["input_ids"]) for b in batch)
        input_ids, attn, labels = [], [], []
        for b in batch:
            n = len(b["input_ids"])
            pad = maxlen - n
            input_ids.append(b["input_ids"] + [self.pad_id] * pad)
            attn.append([1] * n + [0] * pad)
            labels.append(b["labels"] + [-100] * pad)
        return {
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "attention_mask": torch.tensor(attn, dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
        }


class EpochLossLogger(TrainerCallback):
    """Append (epoch, loss) to the loss CSV as soon as each epoch logs.

    Writing per epoch (rather than at the end) means a crash leaves the
    completed epochs' losses on disk.
    """

    def __init__(self, csv_path):
        self.csv_path = csv_path
        with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(["epoch", "loss"])

    def on_log(self, args, state, control, logs=None, **kwargs):
        logs = logs or {}
        if "loss" in logs:  # training-loss log line (not eval)
            with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow([round(logs.get("epoch", 0), 4),
                                        round(logs["loss"], 6)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", choices=["v1", "v2"], default="v1")
    ap.add_argument("--subset", type=int, default=None,
                    help="train on the first N records only (smoke test)")
    args = ap.parse_args()

    cfg = load_config()
    seed = int(cfg["seed"])
    set_seed(seed)                       # seed is fixed via the config, in code
    torch.use_deterministic_algorithms(False)

    epochs = int(cfg["v2"]["epochs"]) if args.version == "v2" else int(cfg["epochs"])
    is_subset = args.subset is not None
    n_records = args.subset if is_subset else int(cfg["max_train_records"])
    run_tag = f"{args.version}_subset{args.subset}" if is_subset else args.version
    if is_subset:
        # smoke test: throwaway model dir + tagged loss file, never touches models/v1
        out_dir = ROOT / "models" / f"_smoke_{run_tag}"
        loss_path = ROOT / "training" / f"loss_{run_tag}.csv"
    else:
        out_dir = ROOT / "models" / args.version
        loss_path = ROOT / "training" / ("loss.csv" if args.version == "v1" else "loss_v2.csv")

    print(f"[train] version={args.version} epochs={epochs} "
          f"records={n_records} seed={seed} model={cfg['model_name']}")

    tok = AutoTokenizer.from_pretrained(cfg["model_name"])
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(cfg["model_name"])
    model.config.pad_token_id = tok.pad_token_id

    records = read_records(cfg["train_file"], n_records)
    print(f"[train] loaded {len(records)} examples from {cfg['train_file']}")
    dataset = CommandJSONDataset(records, tok, int(cfg["max_seq_length"]))

    targs = TrainingArguments(
        output_dir=str(ROOT / "models" / f"_logs_{run_tag}"),
        num_train_epochs=epochs,
        per_device_train_batch_size=int(cfg["batch_size"]),
        learning_rate=float(cfg["learning_rate"]),
        weight_decay=float(cfg.get("weight_decay", 0.0)),
        warmup_steps=int(cfg.get("warmup_steps", 0)),
        logging_strategy="epoch",
        save_strategy="no",   # run is short (~13 min); re-run on crash. loss.csv is per-epoch.
        seed=seed,
        data_seed=seed,
        use_cpu=True,
        dataloader_num_workers=0,
        report_to=[],
        disable_tqdm=False,
    )

    trainer = Trainer(
        model=model,
        args=targs,
        train_dataset=dataset,
        data_collator=Collator(tok.pad_token_id),
        callbacks=[EpochLossLogger(loss_path)],
    )

    t0 = time.time()
    trainer.train()
    secs = time.time() - t0

    out_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out_dir)
    tok.save_pretrained(out_dir)

    per_epoch = secs / epochs if epochs else secs
    rate = (len(records) * epochs) / secs if secs else 0
    print(f"\n[train] DONE in {secs:.0f}s  "
          f"({per_epoch:.0f}s/epoch, {rate:.1f} examples/s)")
    print(f"[train] model+tokenizer -> {out_dir}")
    print(f"[train] loss -> {loss_path}")


if __name__ == "__main__":
    main()
