# Task 2 entry points. The teacher is not needed here (Task 1 produced the data).
#
#   make train                 # train v1 on the first 1500 records
#   make train SUBSET=50       # smoke test: train on the first 50 records only
#   make train VERSION=v2      # train the second version (extra epochs)
#   make eval                  # student + base predictions and score reports
#   make publish VERSION=v1    # upload model to object storage + checksum + release
#
# On Windows/PowerShell, point PYTHON at the venv interpreter:
#   make train PYTHON=.venv/Scripts/python.exe
# or activate the venv first (then plain `make train` works).

PYTHON  ?= python
VERSION ?= v1
SUBSET  ?=

SUBSET_ARG := $(if $(SUBSET),--subset $(SUBSET),)

.PHONY: train eval publish help

help:
	@echo "targets: train [SUBSET=n] [VERSION=v1|v2], eval, publish VERSION=v1|v2"

train:
	$(PYTHON) training/train.py --version $(VERSION) $(SUBSET_ARG)

eval:
	$(PYTHON) training/predict.py --model models/v1 --out results/student_predictions.jsonl
	$(PYTHON) tools/score.py results/student_predictions.jsonl data/validation.jsonl --out results/student_validation.json
	$(PYTHON) training/predict.py --model models/v2 --out results/student_v2_predictions.jsonl
	$(PYTHON) tools/score.py results/student_v2_predictions.jsonl data/validation.jsonl --out results/student_v2_validation.json
	$(PYTHON) training/predict.py --model EleutherAI/pythia-70m --out results/base_predictions.jsonl
	$(PYTHON) tools/score.py results/base_predictions.jsonl data/validation.jsonl --out results/base_validation.json

publish:
	$(PYTHON) scripts/publish_model.py --version $(VERSION)
