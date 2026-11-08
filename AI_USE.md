# AI Use

I used AI tools while building this project, as allowed by the assignment handout.
This document explains how I used them, what I did myself, and how I checked the
work before submitting it.

## The tools I used

- **Claude Code (an AI coding assistant).** I used it to help set up the repository
  and draft the Python code, Dockerfiles, Kubernetes manifests, subnet plan, NACL,
  and CI workflow. These drafts gave me a starting point. I read and ran the code,
  fixed errors, and changed parts that I wanted to handle differently.
- **Ollama running phi3.5.** I used this as the fixed teacher model required for
  Task 1. I ran it at temperature 0 and seed 42, as specified, to label the command
  pool. I then cleaned and checked the labels myself.

Any other AI assistance I used was for getting unstuck or checking an idea. I ran
and verified the work before including it in my submission.

## What I did myself

I ran, tested, and tuned the project myself, and every number in my report comes from runs on my own machine.

- **Task 1: labelling.** I ran the teacher over all 3,000 commands, checked that
  the sharding covers every id exactly once, and confirmed the cleaning counts add
  up (3000 = rejected + duplicates + kept) and that the `train.jsonl` checksum is
  reproducible.
- **Task 2: training.** I ran the fine-tuning on my CPU, watched the loss per
  epoch, and scored all three models (teacher, untrained base, and my student)
  myself. Training was very slow at first, so I investigated and traced the problem
  to a library version. I pinned a working version and ran the training again.
- **Task 3: service.** I tested the three endpoints, the response headers and
  `FAULT_INJECT` by hand, ran the 50-request test under the 1-CPU / 1-GiB limit,
  and confirmed the image stays under 2 GB.
- **Task 4: Kubernetes.** I applied the manifests and ran the scaling, rolling
  update and rollback, pod-delete recovery, and cold-start tests myself, tuning the
  resource requests and adding a drain hook until the failure rates met the targets.
- **Task 5: networking.** I recalculated the subnets by hand and checked the NACL
  with the provided `nacl_sim.py`, which passed all six sample packets.
- **Task 6: CI and tests.** I wrote and optimised each unit test myself, got the
  linting clean, and ran the whole pipeline, including the deliberately failing
  quality-gate run.

## How I checked what the AI gave me

- **I ran everything.** The scores, latency, memory, cold-start times, and cost in
  my report come from my own runs and the files in `results/`.
- **I used the provided checkers.** I checked model quality with `score.py`, the
  NACL with `nacl_sim.py`, and load performance with the Locust file. I used those
  results to judge whether the work met the requirements.
- **I read the code.** Building and running the project helped me catch mistakes
  in the AI output, including a version pin, a Kubernetes field name, and a
  networking assumption. I reviewed these issues and can explain every file in
  the repository.

## Limitations

A 70M student trained on about 1,500 noisy teacher labels still makes mistakes.
My reported scores reflect those limitations. The AI also gave some incorrect
details that sounded convincing, which I caught by running and checking the work
myself.
