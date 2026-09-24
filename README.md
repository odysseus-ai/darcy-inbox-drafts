# darcy-inbox-drafts

An OpenClaw skill that clears Darcy's inbox every morning without ever sending an email itself.

At 10:00 each day the agent:

1. Reads the last day of email in her Gmail **Primary** inbox (read-only; nothing is marked read).
2. Sorts each message: urgent, brand deal, community, team, admin, FYI, or spam.
3. Writes a reply **in Darcy's voice** and saves it as a **draft in her Gmail**, threaded under the
   original email. Brand deals are drafted as a forward to her brand manager with a 3-line summary.
4. Sends her one short digest in her chat channel listing what's ready and what needs her decision.

Darcy approves a reply by opening Gmail → Drafts and tapping **Send**. To modify, she edits the draft
first. To reject, she deletes it. Nothing leaves her inbox without her tap.

## Install

On the machine running the OpenClaw agent:

```bash
openclaw skills install git:odysseus-ai/darcy-inbox-drafts@main
mkdir -p ~/.config/darcy-inbox/examples
cp ~/.openclaw/workspace/skills/darcy-inbox-drafts/config.example.json ~/.config/darcy-inbox/config.json
nano ~/.config/darcy-inbox/config.json          # her address, timezone, brand manager, team
nano ~/.config/darcy-inbox/app-password         # Gmail app password
chmod 600 ~/.config/darcy-inbox/app-password
python3 ~/.openclaw/workspace/skills/darcy-inbox-drafts/scripts/inbox.py fetch --hours 24 --limit 3
```

The last command must print `"ok": true`. Then ask the agent:
*"Schedule the darcy-inbox-drafts skill every day at 10:00 my time."*

Update later with the same `install` command. Config, password, and learned examples live in
`~/.config/darcy-inbox/` and survive reinstalls.

## Files

- `SKILL.md`: the agent's instructions.
- `scripts/inbox.py`: Gmail over IMAP. `fetch`, `draft`, `mark`. No send command exists.
- `references/email-voice.md`: how Darcy writes email.
- `references/triage.md`: sorting rules and the brand-deal handoff format.
- `config.example.json`: settings template.

Requires Python 3.9+ (standard library only) and a Gmail account with 2-Step Verification enabled
(needed to create an app password).
