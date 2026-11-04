# Labelling worker image (Task 1). Build from the repo root:
#   docker build -f worker/Dockerfile -t cs3081-worker:latest .
#   k3d image import cs3081-worker:latest -c cs3081
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Worker code (label.py, teacher_client.py, s3_util.py) and the frozen prompt.
COPY worker/*.py /app/
COPY prompts/teacher_prompt.txt /app/prompts/teacher_prompt.txt

ENTRYPOINT ["python", "label.py"]
