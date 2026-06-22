#!/usr/bin/env bash
set -euo pipefail
cd /Users/fenomenoronaldo/.hermes/skills/finance/futures-trading-assistant
exec python3 pvc2609_preopen_guard.py --session day
