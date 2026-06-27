#!/usr/bin/env bash
# Gateway/plugin entry for /cursor-ask — switch model and ask Cursor Chat.
set -euo pipefail

usage() {
  cat >&2 <<'USAGE'
Usage: dispatch_cursor_ask.sh [--window WORKSPACE] MODEL prompt...

Examples:
  dispatch_cursor_ask.sh gpt-5.5 What is the current task?
  dispatch_cursor_ask.sh --window .hermes "Composer 2.5" What generated this plan?
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
  echo "error: cursor-ask 需要 MODEL" >&2
  usage
  exit 2
fi

MODEL="${ARGS[0]}"
if [[ -n "${CURSOR_AUTOMATION_PROMPT:-}" ]]; then
  PROMPT="$CURSOR_AUTOMATION_PROMPT"
elif [[ ${#ARGS[@]} -ge 2 ]]; then
  PROMPT="${ARGS[*]:1}"
else
  echo "error: cursor-ask 需要 MODEL 和 prompt" >&2
  usage
  exit 2
fi

if [[ -n "$WINDOW_QUERY" ]]; then
  exec bash "${SCRIPT_DIR}/ask_cursor_chat.sh" --window "$WINDOW_QUERY" "$MODEL" "$PROMPT"
else
  exec bash "${SCRIPT_DIR}/ask_cursor_chat.sh" "$MODEL" "$PROMPT"
fi
