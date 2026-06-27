#!/usr/bin/env bash
# Switch Cursor Agent/Composer model via Cmd+/ search (Scheme A).
set -euo pipefail

usage() {
  cat >&2 <<'USAGE'
Usage: switch_cursor_model.sh [--window WORKSPACE] MODEL_NAME

Examples:
  switch_cursor_model.sh "gpt-5.5"
  switch_cursor_model.sh --window "startell" "gpt-5.5"
  switch_cursor_model.sh --workspace ".hermes" "gpt-5.5"
USAGE
}

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
        echo "error: --window/--workspace requires a non-empty value" >&2
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

if [[ ${#ARGS[@]} -ne 1 ]]; then
  usage
  exit 2
fi

MODEL="${ARGS[0]}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "error: macOS only" >&2
  exit 1
fi

if ! pgrep -x Cursor >/dev/null 2>&1 && ! pgrep -f '/Applications/Cursor\.app/Contents/MacOS/Cursor' >/dev/null 2>&1; then
  echo "error: Cursor is not running" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCPT="${SCRIPT_DIR}/switch_cursor_model.scpt"
FOCUS_SCPT="${SCRIPT_DIR}/focus_cursor_window.scpt"

if [[ ! -f "$SCPT" ]]; then
  echo "error: missing ${SCPT}" >&2
  exit 1
fi

FOCUSED_TITLE=""
if [[ -n "$WINDOW_QUERY" ]]; then
  if [[ ! -f "$FOCUS_SCPT" ]]; then
    echo "error: missing ${FOCUS_SCPT}" >&2
    exit 1
  fi
  FOCUSED_TITLE="$(osascript "$FOCUS_SCPT" "$WINDOW_QUERY")"
fi

printf '%s' "$MODEL" | pbcopy
RESULT="$(osascript "$SCPT" "$MODEL")"

if [[ -n "$FOCUSED_TITLE" ]]; then
  echo "Focused Cursor workspace '${FOCUSED_TITLE}', ${RESULT}"
else
  echo "Focused frontmost Cursor workspace, ${RESULT}"
fi
