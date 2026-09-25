# inbox-drafts

An OpenClaw skill that clears Darcy's inbox every morning without ever sending an email itself.

At 10:00 each day the agent:

1. Checks what she did with yesterday's drafts (sent as-is, edited, deleted) and learns from her edits.
2. Reads new email in her Gmail **Primary** inbox (read-only; nothing is marked read).
3. Sorts each message: brand deal, community, team, customer, complaint, creator collab, admin, FYI,
   spam, or phishing, and flags anything urgent.
4. Writes a reply **in Darcy's voice** and saves it as a **draft in her Gmail**, threaded under the
   original email. Brand-deal replies copy in her brand manager, so one tap on Send hands it over.
5. Sends her one short digest in her chat channel listing what's ready and what needs her decision.

Darcy approves a reply by opening Gmail → Drafts and tapping **Send**. To modify, she edits the draft
first. To reject, she deletes it. Nothing leaves her inbox without her tap.

## Install

On the machine running the OpenClaw agent:

```bash
openclaw skills install git:odysseus-ai/inbox-drafts@main
mkdir -p ~/.config/inbox-drafts/examples
cp ~/.openclaw/workspace/skills/inbox-drafts/config.example.json ~/.config/inbox-drafts/config.json
nano ~/.config/inbox-drafts/config.json          # her address, timezone, brand manager, team
nano ~/.config/inbox-drafts/app-password         # Gmail app password
chmod 600 ~/.config/inbox-drafts/app-password
python3 ~/.openclaw/workspace/skills/inbox-drafts/scripts/inbox.py check
```

The last command must print `"ok": true`. Then ask the agent:
*"Schedule the inbox-drafts skill every day at 10:00 my time."*

Update later with the same `install` command. Config, password, and learned examples live in
`~/.config/inbox-drafts/` and survive reinstalls.

## Files

- `SKILL.md`: the agent's instructions.
- `scripts/inbox.py`: Gmail over IMAP. `check`, `fetch`, `draft`, `mark`, `review`. No send command exists.
- `references/email-voice.md`: how Darcy writes email, built from the GrantHouse voice files (Sept 19, 2026).
- `references/triage.md`: sorting rules and the brand-deal handoff format.
- `config.example.json`: settings template.

Requires Python 3.9+ (standard library only) and a Gmail account with 2-Step Verification enabled
(needed to create an app password).
