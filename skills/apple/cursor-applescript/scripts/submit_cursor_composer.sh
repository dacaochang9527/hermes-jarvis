#!/usr/bin/env bash
# Switch Cursor model, open Composer, paste prompt, submit.
set -euo pipefail

usage() {
  cat >&2 <<'USAGE'
Usage: submit_cursor_composer.sh [--window WORKSPACE] MODEL_NAME PROMPT

Examples:
  submit_cursor_composer.sh "gpt-5.5" "Review the current change"
  submit_cursor_composer.sh --window "startell" "gpt-5.5" "Review the current change"
  submit_cursor_composer.sh --workspace ".hermes" "gpt-5.5" "Review the current change"
USAGE
}

WINDOW_QUERY=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -W|--window|-w|--workspace)
      shift
      if [[ $# -eq 0 || -z "${1:-}" ]]; then
        echo "error: --window requires a non-empty value" >&2
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
      break
      ;;
    -*)
      echo "error: unknown option: $1" >&2
      usage
      exit 2
      ;;
    *)
      break
      ;;
  esac
  shift
done

if [[ $# -lt 2 ]]; then
  usage
  exit 2
fi

MODEL="$1"
shift
PROMPT="$*"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "error: macOS only" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FOCUS_SCPT="${SCRIPT_DIR}/focus_cursor_window.scpt"

if [[ -n "$WINDOW_QUERY" ]]; then
  "${SCRIPT_DIR}/switch_cursor_model.sh" --window "$WINDOW_QUERY" "$MODEL"
else
  "${SCRIPT_DIR}/switch_cursor_model.sh" "$MODEL"
fi

printf '%s' "$PROMPT" | pbcopy

if [[ -n "$WINDOW_QUERY" && -f "$FOCUS_SCPT" ]]; then
  osascript "$FOCUS_SCPT" "$WINDOW_QUERY" >/dev/null
fi

osascript <<'APPLESCRIPT'
tell application "System Events"
	tell process "Cursor" to set frontmost to true
	delay 0.3
	key code 53
	delay 0.2
	key code 53
	delay 0.2
	keystroke "i" using {command down, shift down}
	delay 1.5
	keystroke "v" using command down
	delay 0.3
	keystroke return using command down
end tell
return "Model switched and prompt submitted to Composer"
APPLESCRIPT
