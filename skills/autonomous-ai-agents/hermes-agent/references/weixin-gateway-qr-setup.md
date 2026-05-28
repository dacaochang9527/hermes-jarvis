# Weixin / WeChat gateway QR setup notes

Use this when configuring Hermes Gateway's `weixin` platform or troubleshooting a setup that says the gateway is running but no Weixin messages arrive.

## Confirm service vs platform connection

A running gateway only proves the launchd/systemd service is alive. Verify the Weixin adapter separately:

```bash
hermes gateway status
tail -n 60 ~/.hermes/logs/gateway.log
```

Good signs:

```text
Connecting to weixin...
[Weixin] Connected account=... base=https://ilinkai.weixin.qq.com
✓ weixin connected
Gateway running with 1 platform(s)
```

If logs still say `No messaging platforms enabled`, the gateway is up but Weixin is not configured/enabled.

## QR setup workflow

Preferred human path:

```bash
hermes gateway setup
```

Then select `Weixin / WeChat`, start QR login, scan with WeChat, and confirm quickly on the phone before the QR code expires.

Safe defaults for a personal account:

- DM authorization: `Use DM pairing approval`
- Group chats: `Disable group chats`
- Home channel: accept the detected Weixin user ID if this is the owner's account

## Agent/PTY pitfalls

In agent-driven PTY sessions, `hermes gateway setup` can be awkward:

- The menu may default to `Done` if Enter is submitted too early.
- QR output may not render back through the PTY capture reliably.
- The QR code can expire while the agent is relaying instructions.

If the user is present, prefer having them run the setup directly in their terminal and use the agent only to interpret prompts and logs. If automating anyway, the Weixin adapter uses Tencent iLink:

- QR endpoint: `https://ilinkai.weixin.qq.com/ilink/bot/get_bot_qrcode?bot_type=3`
- Required headers include `iLink-App-Id: bot` and `iLink-App-ClientVersion: 131584`
- Poll endpoint: `ilink/bot/get_qrcode_status?qrcode=<code>`

On success, credentials are written to `~/.hermes/.env`:

```text
WEIXIN_ACCOUNT_ID=...
WEIXIN_TOKEN=...
WEIXIN_BASE_URL=https://ilinkai.weixin.qq.com
WEIXIN_CDN_BASE_URL=https://novac2c.cdn.weixin.qq.com/c2c
WEIXIN_DM_POLICY=pairing
WEIXIN_ALLOW_ALL_USERS=false
WEIXIN_GROUP_POLICY=disabled
WEIXIN_HOME_CHANNEL=...
```

Do not print `WEIXIN_TOKEN`; only report presence/length.

## Pairing and display names

Check authorized users:

```bash
hermes pairing list
```

The CLI supports `list`, `approve`, `revoke`, and `clear-pending`; there is no built-in `rename` command yet. The display name shown by `hermes pairing list` is stored in the pairing approved JSON as `user_name`.

Storage location is resolved by `gateway.pairing.PairingStore` via `get_hermes_dir("platforms/pairing", "pairing")`. For the default profile this is usually under:

```text
~/.hermes/platforms/pairing/weixin-approved.json
```

A safe manual rename is to edit only the `user_name` field for the target user ID, preserving the key and `approved_at`. Example shape:

```json
{
  "o9cq...@im.wechat": {
    "user_name": "Cc 微信",
    "approved_at": 1779293000.0
  }
}
```

Restart gateway only if the displayed name or authorization cache does not refresh:

```bash
hermes gateway restart
```

## About the OpenClaw wording

If the WeChat/iLink authorization page says something like `将 OpenClaw 连接到微信`, do not assume the local Hermes CLI printed that. The string may come from Tencent iLink's registered app/bot identity or a server-side label. Search local source before claiming where it originates.
