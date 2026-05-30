#!/usr/bin/env bash
set -euo pipefail
cd /Users/fenomenoronaldo/.hermes/skills/finance/stock-strategy-assistant
exec .venv/bin/python scripts/tulong/runtime/watchdog.py "$@"
