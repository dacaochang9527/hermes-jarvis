# Feishu Gateway Group Setup Notes

Use this reference when configuring Hermes Agent with Feishu/Lark groups.

## Proven workflow

1. In Feishu Open Platform, enable the app's Bot capability.
2. Add message send permission for app identity: `im:message:send_as_bot`.
3. If group @ messages should trigger Hermes, subscribe to event `im.message.receive_v1` / "接收消息 v2.0" and add one of the group @ message permissions such as `im:message.group_at_msg` or its readonly variant.
4. Add the app bot to the target Feishu group from the group settings / add bot or add app entry.
5. Ask a user to @ the bot in the group once. Check `~/.hermes/logs/gateway.log` for `Bot added to chat`, `Inbound group message received`, and the group `chat_id` beginning with `oc_`.
6. Verify active sending with `send_message(target="feishu:<chat_id>", message="...")`.

## Member listing

To list group members, the app needs at least one of these application identity scopes:

- `im:chat.members:read` preferred for member listing.
- `im:chat.group_info:readonly`.
- `im:chat:readonly`.
- `im:chat`.

After adding permissions, create and publish a new app version; otherwise tenant tokens may still return `99991672 Access denied`.

## Group Message History

To inspect recent group discussion context, use Feishu IM message history with a tenant access token:

```text
GET https://open.feishu.cn/open-apis/im/v1/messages
  ?container_id_type=chat
  &container_id=<oc_chat_id>
  &start_time=<unix_seconds>
  &end_time=<unix_seconds>
  &page_size=50
  &sort_type=ByCreateTimeAsc
```

Important details:

- `start_time` and `end_time` should be Unix seconds. Milliseconds can return a successful empty result, which is misleading.
- Text message bodies are nested JSON strings, e.g. `body.content` may be `{"text":"..."}` and needs a second JSON parse.
- For group-trigger design work, read a short recent window and summarize intent rather than mirroring the full chat.

## User allowlist

Hermes Feishu gateway can be restricted with `.env` settings:

```env
FEISHU_ALLOW_ALL_USERS=false
FEISHU_ALLOWED_USERS=<open_id>[,<open_id>...]
FEISHU_GROUP_POLICY=open
```

After changing `.env`, restart the gateway with `hermes gateway restart` and confirm logs show Feishu reconnected.

## Diagnostics

- List current messaging targets with the messaging target list tool.
- If the group target does not appear in target listing, the raw target `feishu:<chat_id>` can still work once the group `chat_id` has been observed.
- For send failures, check whether the bot is in the group, has send permission, and group settings allow bot messages.
