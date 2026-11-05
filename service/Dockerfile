# Inference service image (Task 3). Build from the repo root:
#   docker build -f service/Dockerfile -t cs3081-service:latest .
#   k3d image import cs3081-service:latest -c cs3081
#
# The model weights are NOT in the image - the service downloads them from
# object storage at start-up. torch is the CPU-only build (no CUDA), which keeps
# the image well under the 2 GB limit.
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    HF_HUB_OFFLINE=1 \
    PIP_NO_CACHE_DIR=1

# 1) CPU-only torch from the PyTorch CPU wheel index (no GPU libraries).
RUN pip install --no-cache-dir torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu

# 2) The rest of the pinned dependencies from PyPI (torch is already satisfied).
COPY service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3) Application code + the output schema (small, not model weights).
COPY service/app.py /app/app.py
COPY data/schema.json /app/schema.json

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
