---
name: dingtalk-sender
description: Quickly send Markdown messages to a DingTalk group using a webhook. Use when the user asks to send a message to DingTalk, notify a DingTalk group, or alert via DingTalk.
---

# DingTalk Sender Skill

This skill allows Gemini CLI to quickly send messages to a user's DingTalk group chat via a custom robot webhook.

## Execution Flow

1. **Verify Webhook Setup**: 
   - Check if a `DINGTALK_WEBHOOK_URL` is defined in the workspace's `.env` file, or if the user has globally saved their webhook using the `save_memory` tool.
   - **If the webhook is NOT found:** You MUST immediately stop and ask the user to provide their DingTalk Robot Webhook URL. Recommend that they either add it to their `.env` file as `DINGTALK_WEBHOOK_URL` or let you save it to global memory (using the `save_memory` tool) so they don't have to provide it next time.
2. **Format Message**: Convert the user's message or summary into a well-formatted Markdown string.
3. **Send Message**: Execute the bundled Python script to push the message to DingTalk.

## Sending the Message

Use the `run_shell_command` tool to execute the included Python script. 

Ensure the message string is properly enclosed in quotes.

```bash
python "${__dirname}/scripts/send.py" "https://oapi.dingtalk.com/robot/send?access_token=..." "Your markdown message here"
```

## Troubleshooting

- If DingTalk returns an error about keywords (e.g., `keywords not in content`), remind the user that their DingTalk robot's Security Settings require a specific Custom Keyword, and ensure their message text includes that keyword.
