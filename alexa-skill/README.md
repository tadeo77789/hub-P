# Alexa alerts

Paula only uses Alexa to **send** notifications (notas/03). The hub posts a signed alert to an AWS Lambda Function URL; the Lambda turns it into an Alexa proactive event (`AMAZON.MessageAlert.Activated`), so the Echo shows the yellow ring and announces who the alert is from.

```
hub (AlexaNotifier) ──signed POST──▶ Lambda Function URL ──Proactive Events API──▶ Alexa
```

## Setup

1. **Skill.** In the Alexa developer console create a Custom skill named "Paula Port" (`es-US`), and import `skill-package/skill.json`. Replace `REPLACE_WITH_SKILL_LAMBDA_ARN` with the Lambda ARN.
2. **Permissions.** Under *Permissions*, enable *Alexa Notifications*, and copy the skill's **Client Id** and **Client Secret**.
3. **Lambda.** Create a Python 3.12 Lambda from `lambda/lambda_function.py` (standard library only, no packaging needed). Set:
   - `ALEXA_NOTIFY_SECRET`: a **new** random value (32+ chars), also set in the hub `.env`. Never reuse `AGENT_SHARED_SECRET`: that one authorizes PC actions and must not leave the PC.
   - `ALEXA_SKILL_ID`: the skill id, so only this skill can call the Lambda
   - `ALEXA_CLIENT_ID`, `ALEXA_CLIENT_SECRET`: from step 2
   - `ALEXA_EVENTS_STAGE`: `development` while testing, `live` after certification
4. **Function URL.** Enable a Function URL (auth type `NONE`; the request signature is the authentication) and put it in the hub `.env` as `ALEXA_NOTIFY_URL`.
5. **Enable the skill** on Ola's Alexa account and accept the notifications permission in the Alexa app.

## Notes

- The same Lambda answers Alexa's own requests (opening the skill, subscription events) with a short spoken reply.
- Alexa only says "1 message from <title>": the `AMAZON.MessageAlert` schema carries the sender, not the text. The full message stays in Paula's chat.
- The hub signs each alert with `ALEXA_NOTIFY_SECRET` (`x-paula-signature`, `x-paula-sent-at`); the Lambda rejects anything unsigned or older than 5 minutes.
- Alerts are best effort: if the Lambda fails, the hub logs a warning and the conversation goes on.
- Not tested against a real Alexa account yet. The proactive event payload follows the `AMAZON.MessageAlert.Activated` schema; check it against the current Alexa docs before certification.
