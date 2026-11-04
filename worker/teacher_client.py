"""Call the Phi-3.5 teacher through Ollama, deterministically.

Shared by the prompt-eval harness (eval_prompt.py) and the sharded labelling
worker (label.py). The handout fixes temperature=0 and seed=42 for every student.

Configuration (environment variables, with defaults):
  OLLAMA_HOST    base URL of the Ollama server   (default http://localhost:11434)
                 inside the k3d cluster this is   http://host.k3d.internal:11434
  TEACHER_MODEL  Ollama model tag                 (default phi3.5)
  PROMPT_PATH    path to the prompt template      (default prompts/teacher_prompt.txt)
  NUM_PREDICT    max tokens to generate           (default 128)
  REQUEST_TIMEOUT seconds per request             (default 120)
"""
import os
import time

import requests

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
TEACHER_MODEL = os.environ.get("TEACHER_MODEL", "phi3.5")
PROMPT_PATH = os.environ.get("PROMPT_PATH", "prompts/teacher_prompt.txt")
NUM_PREDICT = int(os.environ.get("NUM_PREDICT", "128"))
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "120"))

# These two are fixed by the handout and must not change between students.
TEMPERATURE = 0
SEED = 42

_PLACEHOLDER = "{command}"


def load_prompt(path=PROMPT_PATH):
    with open(path, encoding="utf-8") as f:
        template = f.read()
    if _PLACEHOLDER not in template:
        raise ValueError(f"prompt template {path} is missing the {_PLACEHOLDER} placeholder")
    return template


def build_prompt(template, command):
    return template.replace(_PLACEHOLDER, command)


def label(command, template=None, retries=3):
    """Return the teacher's raw reply (a string) for one command.

    The reply is returned verbatim, exactly as generated, per the handout
    ("Store the teacher's replies exactly as generated"). Parsing/cleaning
    happens later in clean.py.
    """
    if template is None:
        template = load_prompt()
    payload = {
        "model": TEACHER_MODEL,
        "prompt": build_prompt(template, command),
        "stream": False,
        "options": {
            "temperature": TEMPERATURE,
            "seed": SEED,
            "num_predict": NUM_PREDICT,
            # Stop as soon as the single-line JSON object ends, so the model
            # cannot append prose ("Note: ...") that would invalidate the JSON.
            # This truncates generation; it does not edit the stored reply.
            "stop": ["\n\n", "\nNote", "\nCommand:", "\nExplanation"],
        },
    }
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(
                f"{OLLAMA_HOST}/api/generate", json=payload, timeout=REQUEST_TIMEOUT
            )
            resp.raise_for_status()
            return resp.json()["response"].strip()
        except Exception as e:  # noqa: BLE001 - surface any transport/HTTP error
            last_err = e
            if attempt < retries:
                time.sleep(2 * attempt)
    raise RuntimeError(f"teacher request failed after {retries} attempts: {last_err}")


def health():
    """Return True if the Ollama server answers and has the teacher model."""
    try:
        r = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=10)
        r.raise_for_status()
        tags = [m["name"] for m in r.json().get("models", [])]
        return any(t.split(":")[0] == TEACHER_MODEL.split(":")[0] for t in tags)
    except Exception:  # noqa: BLE001
        return False


if __name__ == "__main__":
    # Smoke test: label one example command and print the raw reply.
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "set an alarm for seven am tomorrow"
    print(f"OLLAMA_HOST = {OLLAMA_HOST}")
    print(f"model present = {health()}")
    print(f"command: {cmd}")
    print(f"reply  : {label(cmd)}")
