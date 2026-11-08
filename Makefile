# Entry points for the project.
#
#   make up                    # build + deploy the whole system from a fresh clone
#   make down                  # delete the cluster (removes everything)
#   make lint                  # ruff lint
#   make test                  # pytest unit tests
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

.PHONY: up down lint test train eval publish help

help:
	@echo "targets: up, down, lint, test, train [SUBSET=n] [VERSION=v1|v2], eval, publish VERSION=v1|v2"

up:
	$(PYTHON) scripts/deploy.py up

down:
	k3d cluster delete cs3081

lint:
	$(PYTHON) -m ruff check worker training service scripts tests

test:
	$(PYTHON) -m pytest

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
