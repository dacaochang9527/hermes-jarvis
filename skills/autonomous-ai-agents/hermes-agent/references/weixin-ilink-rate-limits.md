# Weixin iLink sendmessage rate limits

Use this when Hermes Weixin/WeChat delivery shows repeated send failures, missing replies after the agent produced a response, or the user asks whether iLink frequency/message-volume limits are involved.

## Active recovery / verification checklist

When the user asks "可以了吗", "微信又没返回", or similar, do not only explain likely causes. Actively verify the path:

1. Check the gateway service is loaded/running and identify the current PID:

```bash
hermes gateway status
pgrep -af 'hermes.*gateway|gateway run|ilink|weixin|Weixin' || true
```

2. Inspect the newest gateway error lines as well as filtered rate-limit lines. A broad grep can surface older errors, so also use `tail` to know what is happening now:

```bash
grep -i "rate limited\|send failed\|sendmessage\|ret=-2\|errcode=-2\|weixin\|error\|exception\|connected\|disconnected" ~/.hermes/logs/gateway.log ~/.hermes/logs/gateway.error.log 2>/dev/null | tail -120
tail -60 ~/.hermes/logs/gateway.error.log
```

3. List targets, then send one short Weixin test message to the exact DM target. Treat successful tool return with a `message_id` as evidence that the send path is currently working:

```python
send_message(action="list")
send_message(action="send", target="weixin:<target>", message="短测试：gateway 在线，正在验证微信发送通道。")
```

4. If cron/watchdog jobs were recently delivering to Weixin, list cron jobs and identify noisy jobs separately from gateway health. A job can run successfully while Weixin delivery is rate-limited.

5. Report three statuses separately: gateway connectivity, model/API generation health, and Weixin/iLink delivery health. If a test message succeeds, say the channel is currently recovered, while still noting any earlier rate-limit/model failures.

## Confirm it is iLink delivery rate limiting

Check gateway logs first:

```bash
grep -i "rate limited\|send failed\|sendmessage\|ret=-2\|errcode=-2" ~/.hermes/logs/gateway.log ~/.hermes/logs/gateway.error.log | tail -80
```

Strong signal:

```text
[Weixin] rate limited for <user>; backing off 3.0s before retry
[Weixin] send failed to=<user>: iLink sendmessage rate limited: ret=-2 errcode=None errmsg=rate limited
```

Hermes treats iLink `ret=-2` or `errcode=-2` as the sendmessage frequency-limit code unless the message is the special stale-session pattern `errmsg=unknown error`, which the adapter handles separately as a context/session-token issue.

## Common triggers

- One assistant answer is split into many Weixin text chunks, especially long lists, tables, per-item indicator breakdowns, or highly line-broken output.
- Cron jobs deliver frequent messages to the same Weixin DM, e.g. stock monitors every 3-5 minutes that output on every tick instead of staying quiet when nothing changed.
- Multiple delivery sources pile up: normal chat replies, cron output, restart/shutdown notifications, background task alerts, and tool-triggered `send_message` all target the same user.
- Error loops generate repeated notifications or retries.
- Mixed media + text delivery sends more iLink requests than the user sees as a single “reply”.

## Mitigations

1. Reduce message count before reducing content quality: summarize in one or two Weixin bubbles, and store verbose details in local files/logs when appropriate.
2. For watchdog/cron scripts, make “no meaningful change” produce empty stdout so no message is delivered.
3. Add de-duplication/cooldowns in scripts: avoid repeating the same stock/signal for 10-15 minutes unless status changes.
4. Prefer 5-10 minute monitor intervals over 3-minute intervals unless the alert is truly urgent.
5. Increase Weixin send pacing when needed:

```bash
# in ~/.hermes/.env, then restart gateway
WEIXIN_SEND_CHUNK_DELAY_SECONDS=3
WEIXIN_SEND_CHUNK_RETRY_DELAY_SECONDS=2
WEIXIN_SEND_CHUNK_RETRIES=4
```

6. Restarting gateway may clear stale send/session state, but it does not remove a real iLink server-side frequency window. Wait and reduce output volume if logs continue to show `rate limited` after restart.

## Reporting to the user

Distinguish three cases:

- Gateway offline/disconnected: Weixin adapter is not connected.
- Model failure: Hermes received the message but the model/API failed before producing a response.
- iLink delivery rate limit: Hermes produced or attempted to send content, but iLink rejected sendmessage calls with `ret=-2`/`rate limited`.

For a running stock monitor, also report the cron status and last run separately from delivery status: a job can run successfully while its stdout delivery is rate-limited by Weixin.
