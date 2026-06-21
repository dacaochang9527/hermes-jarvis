# Feishu Gateway Group Messaging

Use this when configuring Hermes Agent to receive or send messages in Feishu/Lark groups.

## Minimal Feishu app permissions

For proactive group sends:
- Enable the app's bot capability in Feishu Open Platform.
- Request a bot send-message permission such as `im:message:send_as_bot` (`以应用的身份发消息`). The broader `im:message` permission can also satisfy send-message APIs, but prefer the narrower bot send permission when enough.
- Publish a new app version after changing bot capability, permissions, or availability scope.
- Add the app bot to the target group and ensure group settings allow bots to speak.

For group interaction via @mentions:
- Configure event subscription or websocket/long-connection mode.
- Subscribe to `im.message.receive_v1` / “接收消息 v2.0”.
- Request `im:message.group_at_msg` or its readonly variant for user @bot messages in groups.
- Only request `im:message.group_msg` if the agent truly needs all group messages; it is broader/sensitive.
- For bot-to-bot @messages, request `im:message.group_at_msg.include_bot:readonly`.

For direct messages:
- Request `im:message.p2p_msg` or readonly variant if Hermes should receive user-to-bot DMs.

## Adding the bot to a group

In Feishu:
1. Open the target group.
2. Open group settings via the top-right menu.
3. Find “群机器人”, “机器人”, or “应用”.
4. Add the app bot by name.
5. Send a test message, preferably `@bot 测试`.

If the bot cannot be found, check:
- App version has been published.
- Bot capability is enabled.
- The user/group members are inside the app availability scope.
- The enterprise admin has approved requested permissions.
- External groups may require the app/bot external sharing capability.

## Hermes verification pattern

After the user sends a group test:
1. Run `send_message(action="list")` to see whether a Feishu group target is registered.
2. Inspect `~/.hermes/logs/gateway.log` and `~/.hermes/logs/agent.log` for Feishu lines around the test time.
3. Look for durable success markers:
   - `[Feishu] Bot added to chat: oc_...`
   - `[Feishu] Inbound group message received: ... chat_id=oc_... text='测试'`
   - `gateway.run: inbound message: platform=feishu ... chat=oc_...`
   - `[Feishu] Sending response ... to oc_...`
4. If those appear, the group is connected and the `oc_...` value is the group `chat_id`.

## Important nuance

`send_message list` may lag or only show Feishu DMs even after group inbound/reply succeeds. Do not conclude group setup failed solely from the target list. If logs show inbound group message and successful response to `oc_...`, group chat works. For proactive sends, try the explicit target `feishu:oc_...`.

## Common errors

- `230002`: bot is not in the target group.
- `230006`: bot ability is not activated.
- `230013`: user is outside app availability scope or disabled for the app.
- `230018` / `230035`: group settings, mute rules, recipient block, or tenant communication controls prevent sending.
- `230027`: missing permission or external-group capability.

