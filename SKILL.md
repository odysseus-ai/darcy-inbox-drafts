---
name: darcy-inbox-drafts
description: "Daily inbox run, check my email, draft replies: triages Darcy's Gmail, saves reply drafts in her voice to Gmail Drafts, sends her a digest. Never sends email."
---

# Darcy inbox drafts

Every morning, read Darcy's new email, draft the replies she would write, save them as threaded
drafts in her Gmail, and send her one short digest. She approves by opening Gmail and tapping
Send, edits the draft first, or deletes it.

**Hard rule: this skill never sends email.** The only outgoing message is the digest to Darcy
herself. Drafts are the approval queue.

## Setup (once)

1. `mkdir -p ~/.config/darcy-inbox/examples && cp {baseDir}/config.example.json ~/.config/darcy-inbox/config.json`,
   then fill it in. Config and examples live outside the skill folder so reinstalling the skill
   never wipes them.
2. Put her Gmail app password in `~/.config/darcy-inbox/app-password` (chmod 600). Gmail →
   Google Account → Security → 2-Step Verification → App passwords.
3. Verify: `python3 {baseDir}/scripts/inbox.py fetch --hours 24 --limit 3`
   returns `"ok": true`.
4. Schedule the daily run at `config.run_time` in `config.timezone`, with the prompt
   "Run the darcy-inbox-drafts skill."

## Run

1. **Load context.** Read `~/.config/darcy-inbox/config.json`, `{baseDir}/references/triage.md`,
   `{baseDir}/references/email-voice.md`, and every file in `~/.config/darcy-inbox/examples/` (her
   edited drafts, when they exist). Done when you know her brand manager,
   team, and the voice rules.
2. **Fetch.**
   `python3 {baseDir}/scripts/inbox.py fetch --hours <config.lookback_hours>`
   Already-handled messages are excluded automatically. If `ok` is false, send Darcy the error in one
   line and stop. If `count` is 0, send "Inbox clear — nothing new since yesterday." and stop.
3. **Triage.** Put each message in exactly one bucket per `{baseDir}/references/triage.md`. Done when every
   message has a bucket and a one-line reason.
4. **Draft.** For each message that needs a reply:
   - Write the body (reply text only: no subject, no quoted history) to a temp file.
   - Reply: `python3 {baseDir}/scripts/inbox.py draft --uid <uid> --body-file <file>`
   - Brand deal: `python3 {baseDir}/scripts/inbox.py draft --uid <uid> --body-file <file> --forward-to "<config.brand_manager>"`
   - Check each command prints `"ok": true`; retry a failure once, then list it in the digest as
     "couldn't draft".
   Follow `{baseDir}/references/email-voice.md`. Any fact you can't source from the thread or config becomes
   `[[CHECK: …]]` inside the draft. Never guess it.
5. **Mark handled.** `python3 {baseDir}/scripts/inbox.py mark <message_id> …` with every message id you
   triaged (all buckets, including skip). Done when it prints the count.
6. **Digest.** Send Darcy one message in her channel using the format below. This is the only message
   this skill sends.

## Digest format

```
Good morning Darcy ☀️ — [N] new emails, [D] drafts ready in Gmail.

⚠️ Needs you first
• [Sender] — [subject]: [why it's urgent] ([drafted / not drafted])

🤝 Brand deals → forwarded to [brand manager] (drafts, tap Send)
• [Brand]: [one-line ask] — [rate or "no rate"]

💬 Replies drafted
• [Sender] — [what the reply says, ≤12 words]

📋 Your call
• [Sender] — [the decision she has to make]

👀 FYI: [comma list]    🗑️ Skipped: [n] cold pitches/spam

Open Gmail → Drafts. Send, edit, or delete each one.
```

Omit empty sections. Keep the digest under 200 words. Put every `[[CHECK]]` draft under
"Your call".

## Learning her voice

When Darcy says she changed a draft, or pastes a sent reply, save it to `~/.config/darcy-inbox/examples/YYYY-MM-DD-<slug>.md`
with the original email summary, your draft, and her final version. Read that folder before
drafting. The most recent 10 matter most. After ~2 months of approved drafts without edits in a
bucket, suggest (never self-enable) auto-send for that bucket.
