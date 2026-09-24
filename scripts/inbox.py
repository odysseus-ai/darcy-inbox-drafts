#!/usr/bin/env python3
"""Draft-only Gmail helper for the darcy-inbox-drafts skill.

Commands:
  fetch   List recent Primary-inbox mail as JSON (read-only, never marks read).
  draft   Save a reply or forward as a threaded Gmail draft. Never sends.
  mark    Record message ids as handled so tomorrow's run skips them.

Auth: IMAP with a Gmail app password.
  INBOX_USER       Gmail address (default: inbox_user in ~/.config/darcy-inbox/config.json)
  INBOX_PASS_FILE  file holding the app password
                   (default ~/.config/darcy-inbox/app-password)
State: INBOX_STATE (default ~/.config/darcy-inbox/state.json)
"""
import argparse
import email
import email.policy
import imaplib
import json
import os
import re
import sys
import time
from email.message import EmailMessage
from email.utils import formataddr, formatdate, getaddresses, make_msgid

HOST = "imap.gmail.com"
DRAFTS = '"[Gmail]/Drafts"'
CONF_DIR = os.path.expanduser("~/.config/darcy-inbox")
STATE = os.environ.get("INBOX_STATE", os.path.join(CONF_DIR, "state.json"))
BODY_MAX = 4000


def addresses(raw):
    """Parse an address header into (name, email) pairs, tolerating unquoted
    display names with specials, e.g. `Jenna @ Brightwave <j@bw.com>`."""
    raw = str(raw or "")
    angled = re.findall(r'(?:^|,)\s*("[^"]*"|[^"<>,]*?)\s*<([^<>\s]+@[^<>\s]+)>', raw)
    if angled:
        return [(n.strip().strip('"'), a.lower()) for n, a in angled]
    return [(n, a.lower()) for n, a in getaddresses([raw]) if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", a)]


def header_to(raw):
    return ", ".join(formataddr(p) for p in addresses(raw))


def die(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def connect():
    user = os.environ.get("INBOX_USER")
    if not user:
        try:
            user = json.load(open(os.path.join(CONF_DIR, "config.json")))["inbox_user"]
        except (OSError, ValueError, KeyError):
            die(f"set INBOX_USER or inbox_user in {CONF_DIR}/config.json")
    pw_file = os.environ.get("INBOX_PASS_FILE", os.path.join(CONF_DIR, "app-password"))
    try:
        pw = open(os.path.expanduser(pw_file)).read().strip().replace(" ", "")
    except OSError:
        die(f"app password file not readable: {pw_file}")
    m = imaplib.IMAP4_SSL(HOST)
    try:
        m.login(user, pw)
    except imaplib.IMAP4.error as e:
        die(f"IMAP login failed for {user}: {e}")
    return m, user


def load_state():
    try:
        return json.load(open(STATE))
    except (OSError, ValueError):
        return {"handled": {}}


def save_state(state):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    cutoff = time.time() - 30 * 86400
    state["handled"] = {k: v for k, v in state["handled"].items() if v > cutoff}
    tmp = STATE + ".tmp"
    json.dump(state, open(tmp, "w"), indent=1)
    os.replace(tmp, STATE)


def text_body(msg):
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        body = part.get_content()
    except (LookupError, UnicodeDecodeError):
        body = part.get_payload(decode=True).decode("utf-8", "replace")
    if part.get_content_type() == "text/html":
        body = re.sub(r"(?is)<(script|style).*?</\1>", "", body)
        body = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", body)
        body = re.sub(r"<[^>]+>", "", body)
        body = re.sub(r"&nbsp;", " ", body)
    # Drop quoted history so the model sees only the new message.
    body = re.split(r"\n(?:On .{5,200}wrote:|-{2,} ?Original Message|From: .+\nSent: )", body)[0]
    body = re.sub(r"\n[ \t]*\n\s*", "\n\n", body).strip()
    return body[:BODY_MAX]


def fetch_one(m, uid):
    typ, data = m.uid("fetch", uid, "(BODY.PEEK[] X-GM-THRID X-GM-LABELS)")
    if typ != "OK" or not data or data[0] is None:
        return None, None
    meta = data[0][0].decode(errors="replace")
    msg = email.message_from_bytes(data[0][1], policy=email.policy.default)
    return msg, meta


def cmd_fetch(a):
    m, user = connect()
    m.select("INBOX", readonly=True)
    query = f"newer_than:{a.hours}h category:primary -from:me"
    typ, data = m.uid("search", "X-GM-RAW", f'"{query}"')
    if typ != "OK":
        die(f"search failed: {data}")
    uids = data[0].split()[-a.limit:]
    handled = load_state()["handled"]
    out = []
    for uid in reversed(uids):
        msg, meta = fetch_one(m, uid)
        if msg is None:
            continue
        mid = (msg.get("Message-ID") or "").strip()
        if mid in handled:
            continue
        name, addr = (addresses(msg.get("From")) or [("", "")])[0]
        out.append({
            "uid": uid.decode(),
            "message_id": mid,
            "thread_id": (re.search(r"X-GM-THRID (\d+)", meta) or [None, None])[1],
            "from_name": name,
            "from_email": addr,
            "to": msg.get("To", ""),
            "cc": msg.get("Cc", ""),
            "subject": msg.get("Subject", ""),
            "date": msg.get("Date", ""),
            "bulk": bool(msg.get("List-Unsubscribe") or msg.get("Precedence", "").lower() in ("bulk", "list")),
            "has_attachments": any(p.get_content_disposition() == "attachment" for p in msg.walk()),
            "body": text_body(msg),
        })
    m.logout()
    print(json.dumps({"ok": True, "account": user, "count": len(out), "messages": out}, indent=1, ensure_ascii=False))


def quote(msg):
    body = text_body(msg)
    who = msg.get("From", "")
    when = msg.get("Date", "")
    return f"\n\nOn {when}, {who} wrote:\n" + "\n".join("> " + l for l in body.splitlines())


def cmd_draft(a):
    body = open(a.body_file).read().rstrip() + "\n"
    m, user = connect()
    m.select("INBOX", readonly=True)
    orig, _ = fetch_one(m, a.uid.encode())
    if orig is None:
        die(f"uid {a.uid} not found in INBOX")

    subj = orig.get("Subject", "")
    d = EmailMessage()
    d["From"] = user
    d["Date"] = formatdate(localtime=True)
    d["Message-ID"] = make_msgid(domain=user.split("@")[1])
    if a.forward_to:
        d["To"] = header_to(a.forward_to) or a.forward_to
        d["Subject"] = subj if re.match(r"(?i)fwd?:", subj) else f"Fwd: {subj}"
        fwd = (f"\n\n---------- Forwarded message ---------\nFrom: {orig.get('From','')}\n"
               f"Date: {orig.get('Date','')}\nSubject: {subj}\nTo: {orig.get('To','')}\n\n{text_body(orig)}")
        d.set_content(body + fwd)
    else:
        to = header_to(a.to or orig.get("Reply-To") or orig.get("From"))
        if not to:
            die(f"no valid recipient address on uid {a.uid}; pass --to")
        d["To"] = to
        if a.cc:
            d["Cc"] = header_to(a.cc)
        d["Subject"] = subj if re.match(r"(?i)re:", subj) else f"Re: {subj}"
        mid = orig.get("Message-ID", "").strip()
        if mid:
            d["In-Reply-To"] = mid
            d["References"] = (orig.get("References", "") + " " + mid).strip()
        d.set_content(body + quote(orig))

    typ, resp = m.append(DRAFTS, r"(\Draft)", imaplib.Time2Internaldate(time.time()), d.as_bytes())
    m.logout()
    if typ != "OK":
        die(f"append to drafts failed: {resp}")
    print(json.dumps({"ok": True, "draft_to": d["To"], "subject": d["Subject"], "forward": bool(a.forward_to)}))


def cmd_mark(a):
    state = load_state()
    now = time.time()
    for mid in a.message_ids:
        state["handled"][mid] = now
    save_state(state)
    print(json.dumps({"ok": True, "marked": len(a.message_ids)}))


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--hours", type=int, default=24)
    f.add_argument("--limit", type=int, default=40)
    d = sub.add_parser("draft")
    d.add_argument("--uid", required=True)
    d.add_argument("--body-file", required=True)
    d.add_argument("--to")
    d.add_argument("--cc")
    d.add_argument("--forward-to")
    k = sub.add_parser("mark")
    k.add_argument("message_ids", nargs="+")
    a = p.parse_args()
    {"fetch": cmd_fetch, "draft": cmd_draft, "mark": cmd_mark}[a.cmd](a)


if __name__ == "__main__":
    main()
