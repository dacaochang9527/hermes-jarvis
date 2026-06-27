#!/usr/bin/env bash
# Gateway/plugin entry for /cursor-model — parse args and run switch or submit.
set -euo pipefail

usage() {
  cat >&2 <<'USAGE'
Usage: dispatch_cursor_model.sh [--window WORKSPACE] MODEL [prompt...]

Examples:
  dispatch_cursor_model.sh gpt-5.5
  dispatch_cursor_model.sh --window startell gpt
  dispatch_cursor_model.sh --window .hermes "Composer 2.5 Fast" Write upgrade plan
USAGE
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WINDOW_QUERY=""
ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    -W|--window|-w|--workspace)
      shift
      if [[ $# -eq 0 || -z "${1:-}" ]]; then
        echo "error: --window/--workspace requires a non-empty value" >&2
        usage
        exit 2
      fi
      WINDOW_QUERY="$1"
      ;;
    --window=*)
      WINDOW_QUERY="${1#*=}"
      if [[ -z "$WINDOW_QUERY" ]]; then
        echo "error: --window requires a non-empty value" >&2
        usage
        exit 2
      fi
      ;;
    --workspace=*)
      WINDOW_QUERY="${1#*=}"
      if [[ -z "$WINDOW_QUERY" ]]; then
        echo "error: --workspace requires a non-empty value" >&2
        usage
        exit 2
      fi
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      ARGS+=("$@")
      break
      ;;
    -*)
      echo "error: unknown option: $1" >&2
      usage
      exit 2
      ;;
    *)
      ARGS+=("$1")
      ;;
  esac
  shift
done

if [[ ${#ARGS[@]} -lt 1 ]]; then
  usage
  exit 2
fi

MODEL="${ARGS[0]}"
PROMPT=""
if [[ ${#ARGS[@]} -gt 1 ]]; then
  PROMPT="${ARGS[*]:1}"
fi

if [[ -n "$PROMPT" ]]; then
  if [[ -n "$WINDOW_QUERY" ]]; then
    exec bash "${SCRIPT_DIR}/submit_cursor_composer.sh" --window "$WINDOW_QUERY" "$MODEL" "$PROMPT"
  else
    exec bash "${SCRIPT_DIR}/submit_cursor_composer.sh" "$MODEL" "$PROMPT"
  fi
fi

if [[ -n "$WINDOW_QUERY" ]]; then
  exec bash "${SCRIPT_DIR}/switch_cursor_model.sh" --window "$WINDOW_QUERY" "$MODEL"
else
  exec bash "${SCRIPT_DIR}/switch_cursor_model.sh" "$MODEL"
fi
