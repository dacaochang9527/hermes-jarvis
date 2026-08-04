#!/usr/bin/env bash
set -euo pipefail
exec /Users/fenomenoronaldo/.hermes/hermes-agent/venv/bin/python \
  /Users/fenomenoronaldo/.hermes/skills/finance/pvc2701-review-forecast/pvc2701_review_publish.py \
  --target afternoon

