#!/usr/bin/env python3
"""Draft-only Gmail helper for the inbox-drafts skill.

Commands (all print one JSON object; "ok": false on any error):
  fetch   Oldest unhandled Primary-inbox messages. Read-only; never marks mail read.
  draft   Save a reply or forward as a threaded Gmail draft. There is no send.
  mark    Record messages (by uid) as handled so later fetches skip them.
  check   Log in and confirm INBOX, Drafts and Sent are reachable. Changes nothing.
  review  Compare earlier drafts with Sent/Drafts: sent_as_is, edited, deleted, pending, expired.

Auth: IMAP with a Gmail app password.
  INBOX_USER       Gmail address (default: inbox_user in ~/.config/inbox-drafts/config.json)
  INBOX_PASS_FILE  app password file (default ~/.config/inbox-drafts/app-password)
State: INBOX_STATE (default ~/.config/inbox-drafts/state.json)

One run at a time: the first `fetch` of a run returns a `run` token and takes a 45-minute lease.
Pass `--run <token>` to later fetch/mark calls; `mark --final` releases the lease.
"""
import argparse
import contextlib
import difflib
import email
import email.policy
import fcntl
import imaplib
import json
import os
import re
import secrets
import sys
import tempfile
import time
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from html.parser import HTMLParser

HOST = "imap.gmail.com"
CONF_DIR = os.path.expanduser("~/.config/inbox-drafts")
STATE = os.path.abspath(os.path.expanduser(os.environ.get("INBOX_STATE", os.path.join(CONF_DIR, "state.json"))))
BODY_MAX = 4000
HTML_MAX = 200_000
LEASE_SECONDS = 45 * 60
HANDLED_DAYS = 30
DRAFT_EXPIRE_DAYS = 7
ADDR_RE = r"[^<>\s,;\"]+@[^<>\s,;\"]+\.[^<>\s,;\"]+"


class Fail(Exception):
    pass


def die(msg):
    raise Fail(msg)


def out(obj):
    print(json.dumps(obj, indent=1, ensure_ascii=True))


# ---------------------------------------------------------------- state

@contextlib.contextmanager
def locked_state():
    """Exclusive lock around read-modify-write of the state file."""
    d = os.path.dirname(STATE)
    try:
        os.makedirs(d, exist_ok=True)
        lf = open(STATE + ".lock", "a")
    except OSError as e:
        die(f"state directory not writable: {e}")
    with lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        state = load_state()
        yield state
        save_state(state)


def load_state():
    if not os.path.exists(STATE):
        return {"handled": {}, "drafts": {}, "run": None}
    try:
        with open(STATE) as f:
            raw = f.read()
    except OSError as e:
        die(f"state file not readable: {e}")
    try:
        s = json.loads(raw)
        if not isinstance(s, dict) or not isinstance(s.get("handled", {}), dict):
            raise ValueError("wrong shape")
        s.setdefault("handled", {})
        s.setdefault("drafts", {})
        s.setdefault("run", None)
        s["handled"] = {k: float(v) for k, v in s["handled"].items()}
        if not isinstance(s["drafts"], dict):
            raise ValueError("drafts is not an object")
        run = s.get("run")
        if run is not None and not (isinstance(run, dict) and isinstance(run.get("token"), str)
                                    and all(isinstance(run.get(k), (int, float)) for k in ("started", "expires"))):
            s["run"] = None  # a malformed lease only means "no run in progress"
        return s
    except (ValueError, TypeError, AttributeError) as e:
        backup = f"{STATE}.corrupt-copy"
        with contextlib.suppress(OSError):
            with open(backup, "w") as f:
                f.write(raw)
        die(f"state file is corrupt ({e}). Nothing was processed. A copy is at {backup}. Fix {STATE}, "
            f"or delete it to start fresh (starting fresh re-drafts everything in the lookback window).")


def save_state(state):
    now = time.time()
    state["handled"] = {k: v for k, v in state["handled"].items() if v > now - HANDLED_DAYS * 86400}
    d = os.path.dirname(STATE)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".state-", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(state, f, indent=1)
    os.replace(tmp, STATE)


def check_run(state, token, starting):
    run = state.get("run")
    live = run and run.get("expires", 0) > time.time()
    if starting:
        if live:
            die(f"another run is in progress (started {time.ctime(run['started'])}); wait or let it expire")
        state["run"] = {"token": secrets.token_hex(6), "started": time.time(), "expires": time.time() + LEASE_SECONDS}
        return state["run"]["token"]
    if not run or run["token"] != token:
        die("run token missing or replaced by a newer run; start again with fetch (no --run)")
    run["expires"] = time.time() + LEASE_SECONDS
    return token


# ---------------------------------------------------------------- imap

def load_config():
    with contextlib.suppress(OSError, ValueError):
        with open(os.path.join(CONF_DIR, "config.json")) as f:
            c = json.load(f)
            return c if isinstance(c, dict) else {}
    return {}


def canonical(addr):
    """Gmail ignores dots and +tags in the local part, and googlemail.com == gmail.com."""
    local, _, domain = addr.lower().partition("@")
    if domain in ("gmail.com", "googlemail.com"):
        return local.split("+", 1)[0].replace(".", "") + "@gmail.com"
    return addr.lower()


def is_self(addr, user):
    mine = {canonical(user)} | {canonical(x) for x in load_config().get("aliases", []) if isinstance(x, str)}
    return canonical(addr) in mine


def connect():
    user = os.environ.get("INBOX_USER")
    if not user:
        try:
            with open(os.path.join(CONF_DIR, "config.json")) as f:
                user = json.load(f)["inbox_user"]
        except (OSError, ValueError, KeyError):
            die(f"set INBOX_USER or inbox_user in {CONF_DIR}/config.json")
    pw_file = os.path.expanduser(os.environ.get("INBOX_PASS_FILE", os.path.join(CONF_DIR, "app-password")))
    try:
        with open(pw_file) as f:
            pw = f.read().strip().replace(" ", "")
    except OSError:
        die(f"app password file not readable: {pw_file}")
    if not pw:
        die(f"app password file is empty: {pw_file}")
    try:
        m = imaplib.IMAP4_SSL(HOST, timeout=30)
        m.login(user, pw)
    except imaplib.IMAP4.error as e:
        die(f"IMAP login failed for {user}: {e}")
    except OSError as e:
        die(f"cannot reach {HOST}: {e}")
    return m, user


def special_folder(m, flag, fallback):
    typ, data = m.list()
    for line in data or []:
        line = line.decode(errors="replace") if isinstance(line, bytes) else str(line)
        if flag in line:
            name = re.search(r'"([^"]+)"\s*$|(\S+)\s*$', line)
            return '"' + (name.group(1) or name.group(2)) + '"'
    return fallback


def fetch_one(m, uid):
    typ, data = m.uid("fetch", uid, "(BODY.PEEK[] X-GM-THRID)")
    if typ != "OK" or not data or not isinstance(data[0], tuple):
        return None, ""
    meta = data[0][0].decode(errors="replace")
    return email.message_from_bytes(data[0][1], policy=email.policy.default), meta


def gm_keys(m, uids):
    """(uid, gmail-message-id) oldest first. X-GM-MSGID is unique per message in the account,
    unlike the sender-controlled Message-ID header."""
    keys = []
    for i in range(0, len(uids), 300):
        chunk = uids[i:i + 300]
        typ, data = m.uid("fetch", b",".join(chunk), "(UID X-GM-MSGID)")
        if typ != "OK":
            die(f"id fetch failed: {data}")
        found = {}
        for item in data:
            raw = item[0] if isinstance(item, tuple) else item
            if not isinstance(raw, bytes):
                continue
            u, g = re.search(rb"UID (\d+)", raw), re.search(rb"X-GM-MSGID (\d+)", raw)
            if u and g:
                found[u.group(1)] = "gm:" + g.group(1).decode()
        keys += [(u, found[u]) for u in chunk if u in found]
    return keys


# ---------------------------------------------------------------- headers

def clean(s):
    return re.sub(r"[\r\n\t]+", " ", s or "").strip()


def raw_header(msg, name):
    """Header value as sent (the parsed value can be mangled), with stray 8-bit bytes
    recovered as UTF-8 and RFC 2047 words left for decode_words."""
    for k, v in msg.raw_items():
        if k.lower() == name.lower():
            b = str(v).encode("utf-8", "surrogateescape")
            try:
                v = b.decode("utf-8")
            except UnicodeDecodeError:
                v = b.decode("latin-1")
            return re.sub(r"\r?\n[ \t]+", " ", v).strip()
    return ""


def decode_words(s):
    try:
        return clean(str(make_header(decode_header(s))))
    except (LookupError, ValueError, UnicodeError):
        return clean(s)


def split_top_level(raw):
    parts, buf, depth, quoted = [], "", 0, False
    for ch in raw:
        if ch == '"' and not buf.endswith("\\"):
            quoted = not quoted
        elif not quoted and ch == "<":
            depth += 1
        elif not quoted and ch == ">":
            depth = max(0, depth - 1)
        if ch in ",;" and not quoted and depth == 0:
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    parts.append(buf)
    merged = []
    for p in parts:  # "Doe, Jane <j@x.com>": a piece with no @ belongs to the next one
        if merged and "@" not in merged[-1]:
            merged[-1] = merged[-1] + "," + p
        else:
            merged.append(p)
    return [p.strip() for p in merged if p.strip()]


def addresses(raw):
    """Parse an address header into (name, email) pairs. Tolerates unquoted display names with
    specials, bare/bracketed mixes, and junk; drops entries without a valid address."""
    found = []
    for part in split_top_level(clean(raw)):
        bracketed = re.findall(r"<(" + ADDR_RE + r")>", part)
        if bracketed:
            addr = bracketed[-1]
            name = part[:part.rfind("<" + addr)].strip().strip('"').replace('\\"', '"')
        else:
            bare = re.search(ADDR_RE, part)
            if not bare:
                continue
            addr, name = bare.group(0), ""
        found.append((decode_words(name), addr.lower()))
    return found


def fmt_addr(pair):
    try:
        return formataddr(pair)
    except UnicodeError:
        return None


def header_to(pairs):
    """Display form. Addresses Gmail can't take in a header (non-ASCII local part) are shown raw."""
    return ", ".join(fmt_addr(p) or (f"{p[0]} <{p[1]}>" if p[0] else p[1]) for p in pairs)


def valid_pairs(value, what):
    pairs = addresses(value)
    if not pairs:
        die(f"no valid email address in {what}: {value!r}")
    return pairs


def prefixed(subject, kind):
    subject = decode_words(subject)
    if kind == "re":
        if re.match(r"(?i)\s*(re|aw|sv|antw)\s*(\[\d+\])?\s*:", subject):
            return subject
        return f"Re: {subject}" if subject else "Re: (no subject)"
    if re.match(r"(?i)\s*(fwd?|wg|tr)\s*:", subject):
        return subject
    return f"Fwd: {subject}" if subject else "Fwd: (no subject)"


# ---------------------------------------------------------------- bodies

class _Text(HTMLParser):
    SKIP = {"script", "style", "head", "title"}
    BREAK = {"br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4", "blockquote", "table"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BREAK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in self.BREAK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(html):
    p = _Text()
    p.feed(html[:HTML_MAX])
    p.close()
    return "".join(p.parts).replace("\xa0", " ")


def part_text(part):
    try:
        text = part.get_content()
    except (LookupError, UnicodeError, AssertionError):
        payload = part.get_payload(decode=True) or b""
        text = payload.decode("utf-8", "replace")
    charset = (part.get_content_charset() or "us-ascii").lower()
    if "\ufffd" in text and charset in ("utf-8", "utf8", "us-ascii", "ascii"):
        payload = part.get_payload(decode=True) or b""
        lenient = payload.decode("utf-8", "replace")
        # Mislabeled cp1252 has no valid multi-byte UTF-8 at all; real UTF-8 with a stray byte does.
        if lenient.count("\ufffd") > 0 and not any(ord(c) > 127 and c != "\ufffd" for c in lenient):
            with contextlib.suppress(UnicodeError):
                text = payload.decode("cp1252")
    return text


def body_part(msg):
    candidates = [p for p in msg.walk() if not p.is_multipart()
                  and p.get_content_type() in ("text/plain", "text/html")
                  and p.get_content_disposition() != "attachment" and not p.get_filename()]
    for kind in ("text/plain", "text/html"):
        for p in candidates:
            if p.get_content_type() == kind:
                return p
    return None


QUOTED_HTML = re.compile(r'<(?:div|blockquote)[^>]*class="?[^">]*(?:gmail_quote|yahoo_quoted)|<blockquote[^>]*type="?cite'
                         r'|<div[^>]*id="?(?:appendonsend|divRplyFwdMsg)', re.I)


def full_text(msg, strip_html_quotes=False):
    part = body_part(msg)
    if part is None:
        cal = next((p for p in msg.walk() if p.get_content_type() == "text/calendar"), None)
        return "[calendar invite]" if cal else ""
    text = part_text(part)
    if part.get_content_type() == "text/html":
        if strip_html_quotes:
            q = QUOTED_HTML.search(text)
            if q:
                text = text[:q.start()]
        text = html_to_text(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\n[ \t]*(\n[ \t]*)+", "\n\n", text).strip()


QUOTE_ATTRIBUTION = re.compile(r"\n(On (?:(?!\n\n).){5,300}?wrote:)[ \t]*\n(?=\s*>)", re.S)
OUTLOOK_BLOCK = re.compile(r"\n_*\s*\n?From: [^\n]+\n(?:Sent|Date): [^\n]+\n(?:To: [^\n]+\n)?(?:Cc: [^\n]+\n)?Subject: ([^\n]*)")
ORIGINAL_MSG = re.compile(r"\n-{2,} ?Original Message ?-{2,}")


def new_content(msg, subject):
    """The sender's new text, with reply history removed but forwarded content kept."""
    is_fwd = bool(re.match(r"(?i)\s*(fwd?|wg|tr)\s*:", subject))
    text = full_text(msg, strip_html_quotes=not is_fwd)
    cut = len(text)
    a = QUOTE_ATTRIBUTION.search(text)
    if a:
        cut = min(cut, a.start())
    if not is_fwd:
        o = OUTLOOK_BLOCK.search(text)
        if o and re.sub(r"(?i)^\s*(re|aw|sv)\s*:\s*", "", o.group(1)).strip()[:30] in subject:
            cut = min(cut, o.start())
        g = ORIGINAL_MSG.search(text)
        if g:
            cut = min(cut, g.start())
    body = text[:cut].strip()
    if len(body) > BODY_MAX:
        body = body[:BODY_MAX] + "\n[…truncated]"
    return body


def has_attachments(msg):
    for p in msg.walk():
        if p.get_content_type() == "message/rfc822":
            return True
        if p.is_multipart():
            continue
        if p.get_content_disposition() == "attachment" or (p.get_filename() and p.get_content_maintype() != "text"):
            return True
    return False


# ---------------------------------------------------------------- commands

def release_run(token):
    with locked_state() as state:
        if state.get("run") and state["run"].get("token") == token:
            state["run"] = None


def cmd_fetch(a):
    with locked_state() as state:
        token = check_run(state, a.run, starting=not a.run)
        handled = set(state["handled"])
    try:
        user, msgs, remaining = fetch_batch(a, handled)
    except BaseException:
        if not a.run:
            release_run(token)
        raise
    if not msgs and not remaining:
        release_run(token)
        token = None
    out({"ok": True, "account": user, "run": token, "count": len(msgs), "remaining": remaining, "messages": msgs})


def fetch_batch(a, handled):
    m, user = connect()
    try:
        m.select("INBOX", readonly=True)
        query = f"newer_than:{a.hours}h category:primary -from:me"
        typ, data = m.uid("search", "X-GM-RAW", f'"{query}"')
        if typ != "OK":
            die(f"search failed: {data}")
        pending = [(u, k) for u, k in gm_keys(m, data[0].split()) if k not in handled]
        batch, remaining = pending[:a.limit], max(0, len(pending) - a.limit)
        msgs = []
        for uid, key in batch:
            entry = {"uid": uid.decode(), "key": key}
            try:
                msg, meta = fetch_one(m, uid)
                if msg is None:
                    entry["error"] = "message vanished"
                else:
                    subject = decode_words(raw_header(msg, "Subject"))
                    frm = (addresses(raw_header(msg, "From")) or [("", "")])[0]
                    entry.update({
                        "thread_id": (re.search(r"X-GM-THRID (\d+)", meta) or [None, None])[1],
                        "from_name": frm[0], "from_email": frm[1],
                        "to": header_to(addresses(raw_header(msg, "To"))),
                        "cc": header_to(addresses(raw_header(msg, "Cc"))),
                        "subject": subject,
                        "date": clean(raw_header(msg, "Date")),
                        "bulk": bool(raw_header(msg, "List-Unsubscribe")
                                     or raw_header(msg, "Precedence").lower() in ("bulk", "list")),
                        "has_attachments": has_attachments(msg),
                        "body": new_content(msg, subject),
                    })
            except Exception as e:  # one bad message must never sink the batch
                entry["error"] = f"could not parse: {type(e).__name__}: {e}"
            msgs.append(entry)
        mark_darcy_replied(m, msgs)
    finally:
        with contextlib.suppress(Exception):
            m.logout()
    return user, msgs, remaining


def mark_darcy_replied(m, msgs):
    """darcy_replied: Darcy has sent at least one message in this Gmail thread."""
    threads = {e["thread_id"] for e in msgs if e.get("thread_id")}
    if not threads:
        return
    try:
        m.select(special_folder(m, "\\All", '"[Gmail]/All Mail"'), readonly=True)
        replied = {t for t in threads
                   if search(m, "X-GM-THRID", t, "X-GM-RAW", q("from:me -in:drafts"))}
    except Exception:  # the flag is a hint; never fail the fetch over it
        return
    for e in msgs:
        if e.get("thread_id"):
            e["darcy_replied"] = e["thread_id"] in replied


def attach_originals(d, orig):
    body = body_part(orig)
    skip_inside = set()
    for part in orig.walk():
        if id(part) in skip_inside or part is body:
            continue
        if part.get_content_type() == "message/rfc822":
            inner = part.get_payload(0) if part.is_multipart() else None
            if inner is not None:
                for sub in inner.walk():
                    skip_inside.add(id(sub))
                d.add_attachment(email.message_from_bytes(inner.as_bytes(), policy=email.policy.default),
                                 filename=decode_words(part.get_filename() or "forwarded.eml"))
            continue
        if part.is_multipart():
            continue
        disp = part.get_content_disposition()
        if disp == "inline" and part.get("Content-ID") and part.get_content_maintype() == "image":
            continue  # signature logos
        if disp == "attachment" or part.get_filename() or (part is orig and part.get_content_maintype() != "text"):
            data = part.get_payload(decode=True) or b""
            maintype, subtype = part.get_content_type().split("/", 1)
            d.add_attachment(data, maintype=maintype, subtype=subtype,
                             filename=decode_words(part.get_filename() or "attachment"))


def cmd_draft(a):
    try:
        with open(a.body_file) as f:
            body = f.read().rstrip() + "\n"
    except OSError as e:
        die(f"body file not readable: {e}")
    if not a.uid.isdigit():
        die(f"uid must be a number: {a.uid!r}")
    extra_cc = valid_pairs(a.cc, "--cc") if a.cc is not None else []
    kind = "forward" if a.forward_to is not None else "reply"
    with locked_state():
        pass  # refuse to draft at all if the state file is unusable, so a retry can't duplicate

    m, user = connect()
    try:
        m.select("INBOX", readonly=True)
        orig, _ = fetch_one(m, a.uid.encode())
        if orig is None:
            die(f"uid {a.uid} not found in INBOX")
        subj = decode_words(raw_header(orig, "Subject"))
        orig_mid = clean(raw_header(orig, "Message-ID"))
        orig_mid = orig_mid if re.fullmatch(r"<[^<>\s]+>", orig_mid) else ""
        with locked_state() as state:
            existing = [v for v in state["drafts"].values() if isinstance(v, dict) and v.get("kind") == kind
                        and (v.get("orig_uid") == a.uid or (orig_mid and v.get("orig_mid") == orig_mid))]
        if existing and not a.replace:
            out({"ok": True, "already_drafted": True, "kind": kind, "subject": existing[0].get("subject", ""),
                 "note": "a draft for this email already exists; counted as drafted (pass --replace to add another)"})
            return

        d = EmailMessage()
        d["From"] = user
        d["Date"] = formatdate(localtime=True)
        d["Message-ID"] = make_msgid(domain=user.split("@")[1])
        me = user.lower()

        if a.forward_to is not None:
            to = valid_pairs(a.forward_to, "--forward-to")
            d["Subject"] = prefixed(subj, "fwd")
            kind = "forward"
            fwd = (f"\n\n---------- Forwarded message ---------\n"
                   f"From: {header_to(addresses(raw_header(orig, 'From')))}\n"
                   f"Date: {clean(raw_header(orig, 'Date'))}\nSubject: {subj}\n"
                   f"To: {header_to(addresses(raw_header(orig, 'To')))}\n\n{full_text(orig)}")
            d.set_content(body + fwd)
            attach_originals(d, orig)
            cc = extra_cc
        else:
            kind = "reply"
            to = valid_pairs(a.to, "--to") if a.to is not None else addresses(raw_header(orig, "Reply-To") or raw_header(orig, "From"))
            to = [p for p in to if not is_self(p[1], user)]
            if not to:
                die(f"no valid recipient address on uid {a.uid}; pass --to")
            cc = []
            if a.reply_all:
                cc = addresses(raw_header(orig, "To")) + addresses(raw_header(orig, "Cc"))
            cc += extra_cc
            d["Subject"] = prefixed(subj, "re")
            if orig_mid:
                refs = clean(raw_header(orig, "References")) or clean(raw_header(orig, "In-Reply-To"))
                d["In-Reply-To"] = orig_mid
                d["References"] = f"{refs} {orig_mid}".strip()
            who = header_to(addresses(raw_header(orig, "From"))) or "the sender"
            quoted = "\n".join("> " + line for line in new_content(orig, subj).splitlines())
            d.set_content(f"{body}\n\nOn {clean(raw_header(orig, 'Date'))}, {who} wrote:\n{quoted}\n")

        seen, to_final, cc_final, skipped = set(), [], [], []
        for group, bucket in ((to, to_final), (cc, cc_final)):
            for p in group:
                if canonical(p[1]) in seen or is_self(p[1], user):
                    continue
                seen.add(canonical(p[1]))
                (bucket if fmt_addr(p) else skipped).append(p)
        if not to_final:
            die(f"no usable recipient on uid {a.uid}"
                + (f" (non-ASCII address {skipped[0][1]} can't go in a draft header); pass --to" if skipped else "; pass --to"))
        d["To"] = ", ".join(fmt_addr(p) for p in to_final)
        if cc_final:
            d["Cc"] = ", ".join(fmt_addr(p) for p in cc_final)

        # Record first: if the state write fails, no draft exists, so a retry can't duplicate one.
        with locked_state() as state:
            for old in [k for k, v in state["drafts"].items()
                        if v.get("kind") == kind and (v.get("orig_uid") == a.uid or (orig_mid and v.get("orig_mid") == orig_mid))]:
                del state["drafts"][old]  # a redraft of the same email replaces the earlier record
            state["drafts"][d["Message-ID"]] = {
                "kind": kind, "orig_mid": orig_mid, "orig_uid": a.uid, "subject": d["Subject"],
                "to": header_to(to_final), "cc": header_to(cc_final), "body": body, "created": time.time()}
        drafts = special_folder(m, "\\Drafts", '"[Gmail]/Drafts"')
        try:
            typ, resp = m.append(drafts, r"(\Draft)", imaplib.Time2Internaldate(time.time()), d.as_bytes())
        except Exception as e:
            typ, resp = "NO", str(e)
        if typ != "OK":
            with locked_state() as state:
                state["drafts"].pop(d["Message-ID"], None)
            die(f"append to drafts failed: {resp}")
    finally:
        with contextlib.suppress(Exception):
            m.logout()
    out({"ok": True, "kind": kind, "to": d["To"], "cc": d.get("Cc", ""), "subject": d["Subject"],
         "attachments": sum(1 for _ in d.iter_attachments()),
         "skipped_recipients": [header_to([p]) for p in skipped]})


def cmd_mark(a):
    uids = [u for u in a.uids if u.isdigit()]
    if len(uids) != len(a.uids):
        die("--uids takes numbers only")
    with locked_state() as state:
        check_run(state, a.run, starting=False)
    m, _ = connect()
    try:
        m.select("INBOX", readonly=True)
        keys = gm_keys(m, [u.encode() for u in uids])
    finally:
        with contextlib.suppress(Exception):
            m.logout()
    with locked_state() as state:
        now = time.time()
        for _, k in keys:
            state["handled"][k] = now
        if a.final:
            state["run"] = None
    out({"ok": True, "marked": len(keys), "not_found": len(uids) - len(keys), "released": a.final})


def normalized(text):
    return re.sub(r"\s+", " ", text).strip().lower()


def without_signature(text):
    """Drop a Gmail signature so an unedited send isn't mistaken for an edit."""
    text = re.split(r"\n-- ?\n", "\n" + text, maxsplit=1)[0].strip()
    sig = load_config().get("gmail_signature") or ""
    if isinstance(sig, str) and sig.strip() and normalized(text).endswith(normalized(sig)):
        cut = text.lower().rfind(sig.strip().splitlines()[0].strip().lower())
        if cut > 0:
            text = text[:cut].rstrip()
    return text


def q(value):
    """IMAP quoted string: imaplib sends arguments verbatim."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def search(m, *criteria):
    typ, data = m.uid("search", None, *criteria)
    return data[0].split() if typ == "OK" and data and data[0] else []


def find_sent(m, mid, r):
    """The sent version of a draft, matched exactly. Gmail usually keeps the draft's Message-ID;
    replies can also be matched by In-Reply-To, forwards by exact subject + recipient."""
    since = time.strftime("%d-%b-%Y", time.gmtime(r["created"] - 86400))
    for uid in reversed(search(m, "SINCE", since, "HEADER", "Message-ID", q(mid))):
        msg, _ = fetch_one(m, uid)
        if msg is not None and clean(raw_header(msg, "Message-ID")) == mid:
            return msg
    if r.get("kind") == "reply" and r.get("orig_mid"):
        for uid in reversed(search(m, "SINCE", since, "HEADER", "In-Reply-To", q(r["orig_mid"]))):
            msg, _ = fetch_one(m, uid)
            if msg is not None and clean(raw_header(msg, "In-Reply-To")) == r["orig_mid"]:
                return msg
    if r.get("kind") == "forward":
        want_to = {p[1] for p in addresses(r.get("to", ""))}
        uids = sorted({u for addr in want_to for u in search(m, "SINCE", since, "TO", q(addr))}, key=int)
        for uid in reversed(uids):
            msg, _ = fetch_one(m, uid)
            if (msg is not None and decode_words(raw_header(msg, "Subject")) == r["subject"]
                    and want_to & {p[1] for p in addresses(raw_header(msg, "To"))}):
                return msg
    return None


def still_drafted(m, mid, r):
    if search(m, "HEADER", "Message-ID", q(mid)):
        return True
    if r.get("kind") == "reply" and r.get("orig_mid"):
        return bool(search(m, "HEADER", "In-Reply-To", q(r["orig_mid"])))
    return False


def cmd_review(a):
    with locked_state() as state:
        records = dict(state["drafts"])
    if not records:
        out({"ok": True, "counts": {}, "results": []})
        return
    m, _ = connect()
    results, resolved = [], []
    try:
        sent = special_folder(m, "\\Sent", '"[Gmail]/Sent Mail"')
        drafts = special_folder(m, "\\Drafts", '"[Gmail]/Drafts"')
        for mid, r in records.items():
            if not isinstance(r, dict) or not isinstance(r.get("created"), (int, float)):
                resolved.append(mid)  # unusable record: drop it rather than fail every run
                continue
            item = {"kind": r.get("kind", "reply"), "subject": r.get("subject", ""), "to": r.get("to", "")}
            try:
                m.select(sent, readonly=True)
                msg = find_sent(m, mid, r)
                if msg is not None:
                    subject = decode_words(raw_header(msg, "Subject"))
                    sent_body = re.split(r"\n-{5,} ?Forwarded message", new_content(msg, "Re: " + subject))[0].strip()
                    sent_body = without_signature(sent_body)
                    ratio = difflib.SequenceMatcher(None, normalized(without_signature(r.get("body", ""))),
                                                    normalized(sent_body)).ratio()
                    item["status"] = "sent_as_is" if ratio >= 0.97 else "edited"
                    if item["status"] == "edited":
                        item.update({"draft_body": r.get("body", ""), "sent_body": sent_body})
                else:
                    m.select(drafts, readonly=True)
                    if still_drafted(m, mid, r):
                        age = (time.time() - r["created"]) / 86400
                        item["status"] = "expired" if age > DRAFT_EXPIRE_DAYS else "pending"
                    else:
                        item["status"] = "deleted"
            except Exception as e:  # one odd record never blocks the rest
                item["status"] = "error"
                item["error"] = f"{type(e).__name__}: {e}"
                if (time.time() - r["created"]) / 86400 > DRAFT_EXPIRE_DAYS:
                    resolved.append(mid)
            results.append(item)
            if item["status"] not in ("pending", "error"):
                resolved.append(mid)
    finally:
        with contextlib.suppress(Exception):
            m.logout()
    with locked_state() as state:
        for mid in resolved:
            state["drafts"].pop(mid, None)
    counts = {k: sum(1 for r in results if r["status"] == k)
              for k in ("sent_as_is", "edited", "deleted", "pending", "expired", "error")}
    out({"ok": True, "counts": counts, "results": [r for r in results if r["status"] != "pending"]})


def cmd_check(a):
    m, user = connect()
    try:
        typ, data = m.select("INBOX", readonly=True)
        if typ != "OK":
            die(f"cannot open INBOX: {data}")
        drafts = special_folder(m, "\\Drafts", '"[Gmail]/Drafts"')
        sent = special_folder(m, "\\Sent", '"[Gmail]/Sent Mail"')
    finally:
        with contextlib.suppress(Exception):
            m.logout()
    with locked_state() as state:
        run = state.get("run")
    out({"ok": True, "account": user, "inbox_messages": int(data[0]), "drafts_folder": drafts,
         "sent_folder": sent, "run_in_progress": bool(run and run.get("expires", 0) > time.time())})


class JsonParser(argparse.ArgumentParser):
    def error(self, message):
        out({"ok": False, "error": f"usage: {message}"})
        sys.exit(2)


def positive(v):
    n = int(v)
    if n < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return n


def main():
    p = JsonParser()
    sub = p.add_subparsers(dest="cmd", required=True, parser_class=JsonParser)
    f = sub.add_parser("fetch")
    f.add_argument("--hours", type=positive, default=72)
    f.add_argument("--limit", type=positive, default=40)
    f.add_argument("--run")
    d = sub.add_parser("draft")
    d.add_argument("--uid", required=True)
    d.add_argument("--body-file", required=True)
    d.add_argument("--to")
    d.add_argument("--cc")
    d.add_argument("--reply-all", action="store_true")
    d.add_argument("--forward-to")
    d.add_argument("--replace", action="store_true")
    k = sub.add_parser("mark")
    k.add_argument("--uids", nargs="+", required=True)
    k.add_argument("--run", required=True)
    k.add_argument("--final", action="store_true")
    sub.add_parser("review")
    sub.add_parser("check")
    a = p.parse_args()
    try:
        {"fetch": cmd_fetch, "draft": cmd_draft, "mark": cmd_mark, "review": cmd_review, "check": cmd_check}[a.cmd](a)
    except Fail as e:
        out({"ok": False, "error": str(e)})
        sys.exit(1)
    except Exception as e:  # always JSON, never a bare traceback
        out({"ok": False, "error": f"{type(e).__name__}: {e}"})
        sys.exit(1)


if __name__ == "__main__":
    main()
