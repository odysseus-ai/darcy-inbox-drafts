# Triage rules

Classify every fetched message into exactly one bucket. First match wins, top to bottom.

| # | Bucket | Signals | Action |
|---|---|---|---|
| 1 | **urgent** | Legal, payment failure, account security, platform strike/claim, a deadline inside 48h, anything from `config.vip_senders` | Draft a reply only if safe; always list first in the digest with the reason. |
| 2 | **brand-deal** | Sponsorship, collaboration, paid partnership, UGC, affiliate offer, media kit or rate request, agency outreach | Forward draft to `config.brand_manager` with a 3-line summary. Plus a short holding reply to the brand if `config.brand_holding_reply` is true. Never discuss terms. |
| 3 | **community** | Viewer, Skool/GrantHouse member, student, grant question, thank-you, story share | Reply draft in coach voice. |
| 4 | **team** | Video editor, thumbnail designer, VA, contractor — sender in `config.team` or content about edits, drafts, invoices for work | Reply draft; state decisions or ask Darcy in the digest when a decision is hers. |
| 5 | **admin** | Scheduling, invoices from vendors, partners, collaborators, podcast/press invites | Reply draft when a reply is expected; otherwise digest-only. |
| 6 | **fyi** | Receipts, confirmations, notifications, newsletters she reads (`bulk: true`), no reply expected | No draft. One line in the digest. |
| 7 | **skip** | Cold sales pitches, SEO/link-building spam, "guest post" offers, obvious phishing | No draft. Count only ("skipped 6 cold pitches"). |

## Judgment calls

- `bulk: true` is a strong hint for fyi/skip, but brand outreach from agencies often comes through
  mailing tools — read the body before skipping.
- A phishing sign (mismatched domain, credential request, urgent payment to a new account) → put it in
  **urgent** as "possible phishing — do not click". Never draft a reply to it.
- If the sender is already in a thread Darcy replied to, reply to continue the thread, whatever the
  bucket.
- Unsure between brand-deal and admin → brand-deal. Unsure between skip and anything else → not skip.

## Brand-deal summary format (top of the forward draft)

```
Hi [brand manager first name],

New inbound from [Brand] — can you take this one?

• Ask: [what they want — deliverables, platform, timing]
• Offer: [budget/rate if stated, else "no rate given"]
• Deadline: [date if stated, else "none given"]

Thanks!
Darcy
```
