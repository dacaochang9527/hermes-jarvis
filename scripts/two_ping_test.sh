#!/usr/bin/env bash
set -euo pipefail
STATE="$HOME/.hermes/tmp/two_ping_test_count"
mkdir -p "$(dirname "$STATE")"
if [[ -f "$STATE" ]]; then
  count=$(cat "$STATE")
else
  count=0
fi
count=$((count + 1))
printf '%s' "$count" > "$STATE"
now=$(date '+%Y-%m-%d %H:%M:%S')
echo "【轮询提醒测试】第 ${count}/2 次"
echo "时间：${now}"
echo "如果你收到这条，说明 Hermes cron → 脚本 stdout → 微信投递链路可用。"
if [[ "$count" -ge 2 ]]; then
  rm -f "$STATE"
fi
