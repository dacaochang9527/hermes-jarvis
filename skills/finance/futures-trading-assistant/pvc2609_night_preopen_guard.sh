#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
exec python3 pvc2609_preopen_guard.py --session night
