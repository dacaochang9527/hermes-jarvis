#!/usr/bin/env bash
set -euo pipefail
cd /Users/fenomenoronaldo/Documents/ai-project/a-share-stock-assistant
exec .venv/bin/python scripts/tulong/runtime/preopen_guard_check.py "$@"
