# Triage rules

Give every fetched message **one bucket** (what to do) plus any **flags** (how loudly to report it).
Check buckets top to bottom; the first match wins. Flags never change the bucket's action.

## Buckets

| # | Bucket | Signals | Action |
|---|---|---|---|
| 1 | **phishing** | Credential or login request, payment to a new account, lookalike domain (`youtube-partner-verify.co`), threats of suspension with a link | No draft. Digest: ⚠️ "possible phishing — don't click". |
| 2 | **skip** | Cold sales/SEO/link-building/guest-post pitches, generic "we can grow your channel" offers | No draft. Count only. |
| 3 | **fyi** | Receipts, confirmations, notifications, newsletters (`bulk: true` and no personal ask), bare thank-yous (one or two lines of thanks with no news), senders in `config.never_draft` | No draft. One line in the digest. Wins, stories and struggles are **community**, never fyi. |
| 4 | **brand-manager** | Sender is `config.brand_manager` | Treat as team: reply draft; decisions go to Your call. |
| 5 | **brand-deal** | A company/agency offering paid or affiliate promotion: sponsorship, integration, UGC, affiliate program, media-kit or rate request, speaking gig with a fee | See "Brand deals" below. |
| 6 | **creator-collab** | Another creator proposing an unpaid collab, guest spot, or cross-promotion | Admin-style reply that thanks them and says Darcy will look at it; `[[CHECK: yes/no + next step]]`. Not routed to the brand manager. |
| 7 | **customer** | A buyer of her digital products or programs: refund, access problem, order question | Business register, no upsell, no community pitch. Remedy is `[[CHECK: …]]` (refund yes/no, access fix). |
| 8 | **complaint** | Someone upset with her, her content, community, or product | Business-warm register. Acknowledge the specific issue, apologise for the specific thing if warranted, no praise, no pep talk. Remedy is `[[CHECK]]`. |
| 9 | **community** | Viewer, GrantHouse member, student: questions, wins, struggles, stories | Coach reply per `email-voice.md`. |
| 10 | **team** | Senders in `config.team`, or work on her videos, thumbnails, admin | Reply; state only what's decided; every open decision is `[[CHECK]]`. |
| 11 | **admin** | Podcasts, press, events without a fee, partners, scheduling, vendor invoices | Reply when a reply is expected; dates, availability and money are `[[CHECK]]`. |

## Flags

- **urgent**: legal notice, platform copyright claim or strike (a real one; fake ones are phishing), payment
  failure, account security, anyone in `config.vip_senders`, or a real deadline within 48h on something
  Darcy would act on (press, event, team, partner, platform, customer). Moves the item to "Needs you
  first" in the digest. Only a brand's sales pressure ("need an answer today") is **not** urgent; report
  it as "wants answer by X" on the brand line.
- **thread**: `darcy_replied` is true in the fetch output (she has sent a message in this Gmail thread).
  Reply if the new message asks something or needs an answer; bare thank-yous stay fyi. Never overrides
  phishing or skip.
- **other-language**: not in English. Reply in the sender's language. Write every `[[CHECK]]` in English,
  and add an English gloss of the draft to the digest line so Darcy knows what she's sending.

## Brand deals

`config.brand_mode` controls the draft:

- **`cc` (default):** one reply to the brand, CC `config.brand_manager`: thank them, say you're looping in
  your brand manager (by first name, `config.brand_manager_name`) who handles partnerships. When Darcy
  taps Send, the manager is on the thread with full context. Don't mention rates, dates, deliverables,
  exclusivity, or anything resembling a yes.
- **`forward`:** a forward to the brand manager with the summary below, and no reply to the brand.

Skip drafting and list it under "Your call" instead when the brand manager is already on To or Cc, or
the email is about a deal already in progress (contract, usage rights, invoice).

Digest placement: a deal that needs no decision from Darcy goes under Brand deals, including one that is
"below your minimum" (the flag rides on its line). A "possible poor fit" deal, and every no-draft deal
above, goes only under Your call with its flag text.

Screen every brand deal and add the reason to its digest line:
- Stated offer below `config.brand_min_rate_usd`, or affiliate-only with no flat fee → "below your minimum".
- Company in `config.brand_flag_categories` (e.g. merchant cash advances, crypto) or pitching something
  that conflicts with honest funding advice → "possible poor fit — your call".
Flagged deals still get the normal draft; Darcy decides whether to send it.

Interest is shown only when the fit is clear ("my audience of small-business owners could use this").
Otherwise just thank them. Never "I love this", "I'm excited about this campaign".

Forward summary (`forward` mode):

```
Hi [config.brand_manager_name],

New inbound from [Brand] — can you take this one?

• Ask: [deliverables, platform, timing]
• Offer: [stated rate/budget, or "no rate given"]
• Deadline: [their date, or "none given"]

Thanks!
Darcy
```

## Judgment calls

- `bulk: true` hints fyi/skip, but agencies send brand outreach through mailing tools. Read the body first.
- Unsure between brand-deal and creator-collab: does the sender offer money or a paid product? If yes, it's a brand deal.
- Unsure between skip and anything else → not skip. Unsure between phishing and a real platform notice → phishing (flag it; Darcy can check the real dashboard).
