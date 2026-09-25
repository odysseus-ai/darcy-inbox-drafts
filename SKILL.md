---
name: inbox-drafts
description: "Daily inbox run, check my email, draft replies: triages my Gmail, saves reply drafts in my voice to Gmail Drafts, sends me a digest. Never sends email."
---

# Inbox drafts

Every morning, read Darcy's new email, draft the replies she would write, save them as threaded
drafts in her Gmail, and send her one short digest. She approves by opening Gmail and tapping
Send, edits the draft first, or deletes it. Each run learns from what she did with yesterday's drafts.

**Hard rule: this skill never sends email.** The script has no send command. The only outgoing
message is the digest to Darcy herself. Auto-sending would need a code change plus Darcy's
written OK; never offer it as a setting.

`S` below means `python3 {baseDir}/scripts/inbox.py`. Every command prints JSON; check `"ok": true`.
Only one run at a time: the first `fetch` returns a `run` token; pass `--run <token>` to every later
`fetch` and `mark` in the same run. If `fetch` says "another run is in progress", stop and say so.

## Setup (once)

1. `mkdir -p ~/.config/inbox-drafts/examples && cp {baseDir}/config.example.json ~/.config/inbox-drafts/config.json`,
   then fill it in. Config and examples live outside the skill folder so reinstalling the skill
   never wipes them.
2. Put her Gmail app password in `~/.config/inbox-drafts/app-password` (chmod 600). Google Account →
   Security → 2-Step Verification → App passwords.
3. Verify: `S check` returns `"ok": true` (logs in, changes nothing).
4. Seed her voice: save 3–5 real replies Darcy has sent (a brand, a community member, a team
   member) to `~/.config/inbox-drafts/examples/`, one file each. Confirm her sign-offs in
   `config.signoff`. Put any other addresses that reach her inbox in `config.aliases`, and her Gmail
   signature (if she has one) in `config.gmail_signature`, so reply-all never copies her and an
   unedited send isn't counted as an edit.
5. Check `config.digest.channel` and `config.digest.target` are filled in and a test message reaches
   Darcy. Don't schedule until it does: an undeliverable digest means nothing gets marked handled.
6. Schedule the daily run at `config.run_time` in `config.timezone`, with the prompt
   "Run the inbox-drafts skill."

## Run

0. **Learn from yesterday.** `S review`. For each result:
   - `edited`: save to `~/.config/inbox-drafts/examples/YYYY-MM-DD-<slug>.md` with a one-line summary
     of the original email, the draft, and her sent version. Note what she changed.
   - `sent_as_is`, `deleted`, `expired`: count only.
   Keep the counts for the digest.
1. **Load context.** Read `~/.config/inbox-drafts/config.json`, `{baseDir}/references/triage.md`,
   `{baseDir}/references/email-voice.md`, and the 10 newest files in `~/.config/inbox-drafts/examples/`.
   Her examples beat the voice guide wherever they differ.
2. **Fetch.** First batch: `S fetch --hours <config.lookback_hours>`. Later batches:
   `S fetch --hours <config.lookback_hours> --run <token>`. Returns the oldest unhandled batch (40 by
   default), `remaining`, and `run`. If `ok` is false, send Darcy the error in one line and stop.
   If `count` is 0 on the first batch, send "Inbox clear, nothing new since yesterday." (plus the
   Yesterday line if step 0 had results) and stop. The run ends by itself.
   A message with an `error` field couldn't be read: list it under Needs you first as
   "couldn't read: [subject or uid]" and still mark it.
3. **Triage.** Give each message one bucket and any flags per `triage.md`, each with a one-line reason.
4. **Draft.** For each message that needs a draft, write the body only (no subject, no quoted history)
   to a temp file, then:
   - Reply: `S draft --uid <uid> --body-file <file> --reply-all`
     (keeps everyone on the thread; Darcy's own address is removed automatically)
   - Brand deal, `cc` mode: `S draft --uid <uid> --body-file <file> --reply-all --cc "<config.brand_manager>"`
   - Brand deal, `forward` mode: `S draft --uid <uid> --body-file <file> --forward-to "<config.brand_manager>"`
     (attachments such as media kits and briefs are carried over)
   `"already_drafted": true` means a draft for that email already exists from an earlier run: count it as
   drafted, don't redraft. Retry a failure once, then list it in the digest as "couldn't draft". Follow `email-voice.md`:
   anything you can't source from the thread or config becomes `[[CHECK: …]]` inside the draft.
   Sign off with the matching `config.signoff`. Use only links from `config.links`.
5. **Next batch.** If `remaining` > 0: `S mark --uids <uid> … --run <token>` for this batch, then
   return to step 2. Marking is what advances to the next batch.
6. **Digest.** Send one message to `config.digest.channel` / `config.digest.target` in the format below.
7. **Mark handled.** Only after the digest was sent: `S mark --uids <uid> … --run <token> --final`
   for the last batch. `--final` ends the run. If the digest failed, don't mark; the run lock expires
   after 45 minutes and the next run picks the messages up again.

## Digest format

```
Good morning Darcy ☀️ [N] new emails, [D] drafts ready in Gmail.

⚠️ Needs you first
• [Sender]: [why] ([drafted / no draft])

🤝 Brand deals ([your brand manager is cc'd on each draft / forwarded to your brand manager])
• [Brand]: [ask] · [offer or "no rate"] · [wants answer by X, if stated] · [screen flag, if any]

📋 Your call
• [Sender]: [the decision she has to make]

💬 Replies drafted: [count]. [≤3 bullets for the most important]

👀 FYI: [comma list]    🗑️ Skipped: [n] [pitch/pitches]

Yesterday: [a] sent as-is, [b] edited, [c] deleted, [e] expired unsent.

Open Gmail → Drafts: send, edit, or delete each one.
```

Rules:
- Each email appears **once**, in the highest section that applies (Needs you first > Brand deals >
  Your call > Replies drafted > FYI). Any draft containing `[[CHECK]]` goes under Your call.
- Brand deals: see "Digest placement" in `triage.md`.
- For an other-language email, add a short English gloss of what the draft says.
- Omit empty sections, and the Yesterday line when there's nothing to report. Use correct plurals.
- Stay under 200 words: trim FYI to a count, then Replies drafted to names only, then cut each Your call
  line to the decision alone ("Jordan: $37 refund?"). Needs you first is never trimmed.

## Voice over time

Her `examples/` folder is how the skill learns. When Darcy says in chat that she changed a draft or
pastes a sent reply, save it as in step 0. After about two months, if a bucket's drafts are nearly
always sent unedited, mention it to Darcy and Akera as a candidate for a future auto-send feature.
Never build or enable it yourself.
