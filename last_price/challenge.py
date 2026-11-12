"""``hermes lastprice challenge``: a public "buy it below my floor" challenge on a messaging platform.

* ``challenge start <item>`` posts the item, the ask and the floor's SHA-256 commitment, and turns every
  chat on the platform from anyone who is not an owner into a guarded deal chat with the challenge
  persona ("Buy it below my floor. Any AI, any trick."). Unless ``--no-configure``, it also applies the
  gateway settings a public bot needs, through Hermes's own ``hermes config set`` (printed one by one):
  any Telegram user may write, the platform's toolset is Last Price only, and slash commands are for
  owners only. Six keys (``SETTING_KEYS``); their earlier values are saved first, read one by one with
  ``hermes config get``. It refuses unless the profile's memory is off (``memory_check``): strangers must
  not chat with an agent that knows the owner.
* ``challenge board`` writes a Markdown board that is safe to publish: counts and anonymised
  transcripts, never a buyer id, username or name field, and (once ended) the reveal.
* ``challenge end`` closes it: every challenge chat then gets a closing message, the six settings go
  back to the values saved at the start (a key that was not set before is unset again), and the board
  shows the floor and salt, checked against the commitment published at the start.

While a challenge runs, a challenge chat is ALWAYS a guarded deal chat, sold or not: it never falls
through to an unguarded Hermes turn. A close in the challenge is recorded, not reserved, so the next
buyer can still try.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Optional

from . import audit, extract
from .state import commitment

KEY = "challenge"
PERSONA = "Buy it below my floor. Any AI, any trick."
CONSENT = ("By chatting you agree that your messages may appear on the public challenge board, anonymised: "
           "no names, usernames or ids.")
CLOSED = "The Last Price challenge has ended. Thanks for playing! The board shows the result and the reveal."
BOARD_DEFAULT = "docs/challenge/board.md"
NO_ADMIN = "0"  # a Telegram user id nobody has: with no owner registered, nobody runs slash commands there


# ---- state ------------------------------------------------------------------------------------
def current(rt) -> Optional[dict]:
    rec = rt.store.backend.get(KEY)
    return rec if isinstance(rec, dict) and rec.get("id") else None


def active_on(rt, platform: str) -> Optional[dict]:
    """The challenge running (or ended, still answering with the closing message) on ``platform``."""
    rec = current(rt)
    return rec if rec and rec.get("platform") == (platform or "").lower() else None


def buyer_hash(rec: dict, platform: str, sender_id: str) -> str:
    """A per-challenge salted hash: counts unique buyers without storing who they are."""
    return hashlib.sha256(f"{rec['salt']}:{platform}:{sender_id}".encode("utf-8")).hexdigest()[:16]


def note_attempt(rt, rec: dict, session_id: str, platform: str, sender_id: str) -> None:
    """Record a challenge chat (once per session) for the board's counts."""
    key = f"{KEY}:sessions"
    with rt._lock:
        rows = list(rt.store.backend.get(key, []) or [])
        if any(r.get("s") == session_id for r in rows):
            return
        rows.append({"s": session_id, "b": buyer_hash(rec, platform, sender_id or session_id),
                     "t": round(time.time(), 3), "c": rec["id"]})
        rt.store.backend.set(key, rows)


def sessions(rt, rec: dict) -> list[dict]:
    return [r for r in (rt.store.backend.get(f"{KEY}:sessions", []) or []) if r.get("c") == rec["id"]]


def intro(rec: dict, item) -> str:
    """The first lines every challenge buyer sees, added after the audit (no price below the ask in it)."""
    return (f"Last Price challenge: {PERSONA} {item.name}, asking {audit.money(item.ask, item.currency)}. "
            f"The floor is sealed: its SHA-256 commitment starts {item.commit[:12]} (full hash on the board), "
            f"revealed when the challenge ends. {CONSENT}")


def context_lines(rec: dict) -> list[str]:
    """Extra deal-context lines for a challenge chat (public values only)."""
    return [f"This chat is a public challenge: \"{PERSONA}\" Buyers will try every trick to get a price below "
            "the floor. Stay friendly, confident and playful; you are glad to sell, at your price."]


# ---- gateway settings -------------------------------------------------------------------------
# The six Hermes settings ``challenge start`` changes on Telegram. Hermes stores the
# gateway.platforms.telegram.* spelling as platforms.telegram.*, so that is the key used here.
# ``challenge end`` restores each one.
SETTING_KEYS = (
    "TELEGRAM_ALLOW_ALL_USERS",
    "platform_toolsets.telegram",
    "platforms.telegram.extra.allow_admin_from",
    "platforms.telegram.extra.user_allowed_commands",
    "platforms.telegram.extra.group_allow_admin_from",
    "platforms.telegram.extra.group_user_allowed_commands",
)
SETTINGS_DISCLOSURE = ("`challenge start` (Telegram) changes six Hermes settings through `hermes config set`: "
                       + ", ".join(SETTING_KEYS) + ". It saves their earlier values first, read one by one with "
                       "`hermes config get`, and `challenge end` restores each one (a key that was not set before is "
                       "unset again).")


def gateway_settings(rt, platform: str) -> list[tuple[str, str]]:
    """``hermes config set`` pairs that open the platform to anyone, safely. Telegram only for now."""
    if platform != "telegram":
        return []
    admins = [o.split(":", 1)[1] for o in rt.store.owners() if o.startswith("telegram:")] or [NO_ADMIN]
    admin_list = "[" + ", ".join(f'"{a}"' for a in admins) + "]"
    values = ("true", '["lastprice"]', admin_list, "[]", admin_list, "[]")
    return list(zip(SETTING_KEYS, values))


GET_TIMEOUT = 60
UNSET = object()  # ``hermes config get`` said "Config key not set"


def hermes_get(key: str) -> tuple[int, str, str]:
    """``hermes config get <key> --json`` through the same ``hermes`` the duel runs, with the duel's
    allowlisted environment (this Hermes home): (exit code, stdout, stderr). One key, one value: no
    ``.env`` or ``config.yaml`` is read here."""
    from .duel import child_env, hermes_argv

    p = subprocess.run(hermes_argv() + ["config", "get", key, "--json"], env=child_env(), capture_output=True,
                       encoding="utf-8", errors="replace", timeout=GET_TIMEOUT, stdin=subprocess.DEVNULL)
    return p.returncode, p.stdout or "", p.stderr or ""


def config_value(key: str, getter: Optional[Callable[[str], tuple[int, str, str]]] = None) -> Any:
    """The value Hermes reports for ``key`` (parsed from ``--json``), or ``UNSET``. Raises when it cannot
    be read (Hermes missing, a timeout, an error, output that is not JSON): callers fail closed."""
    rc, out, err = (getter or hermes_get)(key)
    if rc != 0:
        if "Config key not set" in (err or "") + (out or ""):
            return UNSET
        raise RuntimeError(f"`hermes config get {key}` exited {rc}")
    lines = [ln for ln in (out or "").splitlines() if ln.strip()]
    if not lines:
        raise RuntimeError(f"`hermes config get {key}` printed nothing")
    return json.loads(lines[-1])


def read_setting(key: str, getter: Optional[Callable[[str], tuple[int, str, str]]] = None) -> Optional[str]:
    """The value ``key`` has in this Hermes home now, as ``hermes config get`` reports it, in the form
    ``hermes config set`` takes it back; None when Hermes says it is not set."""
    value = config_value(key, getter)
    if value is UNSET or value is None:
        return None
    return value if isinstance(value, str) else json.dumps(value)


# ---- memory: a public chat must not know the owner ----------------------------------------------
# Hermes loads MEMORY.md/USER.md and any memory provider into every chat of a profile, strangers'
# too, and the held audit checks prices only. So ``challenge start`` and ``shop on`` run only in a
# profile where all three are off. Hermes treats these provider names as "built-in only"
# (agent/memory_provider.py, CORE_MEMORY_PROVIDER_SENTINELS).
MEMORY_KEYS = ("memory.memory_enabled", "memory.user_profile_enabled", "memory.provider")
NO_PROVIDER = ("", "default", "builtin", "built-in", "none")
SHOP_PROFILE = "shop"
PROFILE_STEPS = (
    f"hermes profile create {SHOP_PROFILE}",
    f"hermes -p {SHOP_PROFILE} config set memory.memory_enabled false",
    f"hermes -p {SHOP_PROFILE} config set memory.user_profile_enabled false",
    f"hermes -p {SHOP_PROFILE} memory off",
    f"hermes -p {SHOP_PROFILE} setup",
    f"hermes -p {SHOP_PROFILE} plugins install iamdflame/last-price",
    f"hermes -p {SHOP_PROFILE} plugins enable last-price",
    f'hermes -p {SHOP_PROFILE} lastprice sell "<item>" ask <price> floor <price>',
    f"hermes -p {SHOP_PROFILE} lastprice challenge start <item>",
    f"hermes -p {SHOP_PROFILE} gateway",
)
NEUTRAL_SOUL = ("Keep that profile's SOUL.md neutral: a new profile gets Hermes's stock SOUL.md, which says nothing "
                "about you; do not create it with --clone (that copies your SOUL.md, MEMORY.md and USER.md). Its "
                f"SOUL.md sits beside the config.yaml that `hermes -p {SHOP_PROFILE} config path` prints.")
PROFILE_HOWTO = ("Run the shop and the challenge from a dedicated profile with memory off, so a stranger's chat "
                 "carries nothing about you:\n" + "\n".join("    " + s for s in PROFILE_STEPS) + "\n  " + NEUTRAL_SOUL)


def memory_check(getter: Optional[Callable[[str], tuple[int, str, str]]] = None) -> tuple[bool, list[str]]:
    """(allowed, one line per memory setting). Allowed only when ``memory.memory_enabled`` and
    ``memory.user_profile_enabled`` are false and no ``memory.provider`` is set; a setting that cannot be
    read refuses (fail closed)."""
    ok, lines = True, []
    for key in MEMORY_KEYS:
        try:
            value = config_value(key, getter)
        except Exception as exc:
            ok = False
            lines.append(f"{key}: could not be read ({exc.__class__.__name__}): refused")
            continue
        if key == "memory.provider":
            good = value is UNSET or value is None or (isinstance(value, str) and value.strip().lower() in NO_PROVIDER)
            shown_value = "not set" if value is UNSET or value is None else json.dumps(value)
            need = "" if good else f" (must be none: hermes -p {SHOP_PROFILE} memory off)"
        else:
            good = value is False
            shown_value = "not set (Hermes default: true)" if value is UNSET else json.dumps(value)
            need = "" if good else " (must be false)"
        ok = ok and good
        lines.append(f"{key}: {shown_value}{need}")
    return ok, lines


def memory_refusal(what: str, lines: list[str]) -> str:
    return (f"Refused: {what} opens chats to strangers, and this profile would give them what Hermes remembers "
            "about you (MEMORY.md, USER.md or a memory provider). The price check only looks at prices.\n"
            + "\n".join("  " + ln for ln in lines) + "\n" + PROFILE_HOWTO)


def snapshot(pairs: list[tuple[str, str]], reader: Optional[Callable[[str], Optional[str]]] = None) -> dict:
    """Each key's earlier value (None: not set), read with ``hermes config get`` before anything changes."""
    read = reader or read_setting
    return {key: read(key) for key, _value in pairs}


def restore_ops(saved: dict) -> list[tuple]:
    """``("set", key, earlier value)`` or ``("unset", key)`` for every key ``start`` saved."""
    return [("unset", k) if v is None else ("set", k, v) for k, v in saved.items()]


def shown(op: tuple) -> str:
    return f"hermes config {op[0]} {op[1]}" + (f" '{op[2]}'" if len(op) > 2 else "")


def hermes_config(ops: list[tuple], runner: Optional[Callable[[list[str]], tuple[int, str]]] = None) -> list[str]:
    """Apply ``("set", KEY, VALUE)`` / ``("unset", KEY)`` through Hermes's own ``hermes config`` CLI.
    Returns one report line per key."""
    from .duel import hermes_argv

    def _run(argv: list[str]) -> tuple[int, str]:
        p = subprocess.run(argv, capture_output=True, encoding="utf-8", errors="replace", timeout=120,
                           stdin=subprocess.DEVNULL)
        tail = (p.stderr or p.stdout or "").strip().splitlines()
        return p.returncode, tail[-1] if tail else ""

    run = runner or _run
    lines = []
    for op in ops:
        argv = hermes_argv() + ["config", op[0], op[1]] + list(op[2:])
        try:
            rc, msg = run(argv)
        except Exception as exc:  # report and carry on: the owner sees exactly what to run
            rc, msg = 1, f"{exc.__class__.__name__}: {exc}"
        mark = op[0] if rc == 0 else "FAILED"
        lines.append(f"  {mark}: {shown(op)}" + ("" if rc == 0 else f"  ({msg})"))
    return lines


def hermes_config_set(pairs: list[tuple[str, str]],
                      runner: Optional[Callable[[list[str]], tuple[int, str]]] = None) -> list[str]:
    """Apply settings through ``hermes config set KEY VALUE`` (Hermes's own CLI). Returns report lines."""
    return hermes_config([("set", k, v) for k, v in pairs], runner)


def token_present(getter=None) -> Optional[bool]:
    """Whether TELEGRAM_BOT_TOKEN is set for this Hermes home, asked through ``hermes config get`` (which
    masks it); only set or not set is kept, never the value."""
    try:
        return config_value("TELEGRAM_BOT_TOKEN", getter) not in (UNSET, None, "")
    except Exception:
        return None


# ---- commands ---------------------------------------------------------------------------------
def start(rt, rest: list[str], runner=None, reader=None, getter=None) -> str:
    ap = argparse.ArgumentParser(prog="challenge start", add_help=False)
    ap.add_argument("item", nargs="*")
    ap.add_argument("--platform", default="telegram")
    ap.add_argument("--no-configure", action="store_true")
    a = ap.parse_args(rest)
    platform = a.platform.lower()
    if not re.fullmatch(r"[a-z0-9_]+", platform):
        return "Usage: challenge start <item> [--platform telegram] [--no-configure]"
    item = rt.store.item(" ".join(a.item) if a.item else None)
    if item is None:
        return 'No such item. First: hermes lastprice sell "<item>" ask <price> floor <price>'
    if item.status == "demo":
        return "The demo item's floor is public in the docs: list a real item for the challenge with `sell`."
    old = current(rt)
    if old and not old.get("ended"):
        return f"A challenge is already running on {old['platform']} ({old['item']}). End it first: challenge end"
    allowed, why_not = memory_check(getter)
    if not allowed:
        return memory_refusal("`challenge start`", why_not)
    rec = {"id": secrets.token_hex(6), "item": item.key, "platform": platform, "started": time.time(),
           "ended": None, "salt": secrets.token_hex(16), "commit": item.commit, "ask": item.ask}
    rt.store.backend.set(KEY, rec)
    if item.status != "open":
        rt.store.set_status(item.key, "open")
    plats = set(rt.store.backend.get("shop_platforms", []) or [])
    plats.add(platform)
    rt.store.backend.set("shop_platforms", sorted(plats))
    rt.store.set_shop_open(True)
    with rt._lock:
        rt._deals.clear()
    lines = [f"Challenge {rec['id']} started on {platform}: \"{PERSONA}\"",
             f"  item: {item.name} · ask {audit.money(item.ask, item.currency)}",
             f"  floor commitment: sha256 {item.commit}",
             f"  every {platform} chat from a non-owner is now a guarded deal chat; buyers first see:",
             f"    {intro(rec, item)}"]
    pairs = gateway_settings(rt, platform)
    saved, why = None, "--no-configure"
    if pairs and not a.no_configure:
        try:
            saved = snapshot(pairs, reader or (lambda key: read_setting(key, getter)))
        except Exception as exc:  # no record of the earlier values: change nothing, print the commands
            why = (f"their current values could not be read ({exc.__class__.__name__}), so `challenge end` could "
                   "not restore them")
    if saved is not None:
        rec["restore"] = saved
        rt.store.backend.set(KEY, rec)
        lines.append(f"  gateway settings (Hermes's own `hermes config set`; the earlier values of all {len(pairs)} "
                     "are saved, and `challenge end` restores them):")
        lines.extend(hermes_config_set(pairs, runner))
    elif pairs:
        lines.append(f"  gateway settings NOT applied ({why}); to open the bot to anyone, run:")
        lines.extend(f"    hermes config set {k} '{v}'" for k, v in pairs)
    tok = token_present(getter) if platform == "telegram" else True
    if tok is False:
        lines.append("  TELEGRAM_BOT_TOKEN is not set: `hermes config set TELEGRAM_BOT_TOKEN <token from @BotFather>`.")
    lines.append("  next: `hermes gateway` (keep it running), then `hermes lastprice challenge board` any time.")
    return "\n".join(lines)


def end(rt, runner=None, configure: bool = True) -> str:
    rec = current(rt)
    if rec is None:
        return "No challenge to end."
    if rec.get("ended"):
        return f"Challenge {rec['id']} already ended. `hermes lastprice challenge board` shows the reveal."
    rec["ended"] = time.time()
    rt.store.backend.set(KEY, rec)
    lines = [f"Challenge {rec['id']} ended. Challenge chats now get: \"{CLOSED}\"",
             "  `hermes lastprice challenge board` writes the result with the reveal."]
    saved = rec.get("restore")
    if saved and configure:
        lines.append(f"  gateway settings, back to their values before `challenge start` ({len(saved)} keys):")
        lines.extend(hermes_config(restore_ops(saved), runner))
    elif saved:
        lines.append("  gateway settings NOT restored (--no-configure); to restore them, run:")
        lines.extend("    " + shown(op) for op in restore_ops(saved))
    elif rec["platform"] == "telegram":
        lines.append("  `challenge start` changed no settings (--no-configure). If you applied them by hand, close "
                     "open access: hermes config set TELEGRAM_ALLOW_ALL_USERS 'false'")
    return "\n".join(lines)


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_HANDLE = re.compile(r"(?<![\w@])@\w{3,}")
_URL = re.compile(r"https?://\S+|www\.\S+|t\.me/\S+", re.I)
_PHONE = re.compile(r"\+\d[\d\s().-]{7,}\d|\b0\d{2}[\s-]?\d{3}[\s-]?\d{4}\b|\b\d{7,}\b")
_NAME = re.compile(r"\b(my name is|i am called|i'm called|call me|this is)\s+[A-Z][\w'-]+(\s+[A-Z][\w'-]+)?", re.I)


def scrub(text: str) -> str:
    """Anonymise a chat line for the public board: emails, @usernames, links, phone numbers and
    self-introductions ("my name is ...") are replaced."""
    t = _EMAIL.sub("[email]", text or "")
    t = _URL.sub("[link]", t)
    t = _HANDLE.sub("[@user]", t)
    t = _PHONE.sub("[number]", t)
    t = _NAME.sub(lambda m: m.group(1) + " [name]", t)
    return " ".join(t.split())


def stats(rt, rec: dict) -> dict:
    """The board's numbers, from plugin state and the ledger (pure reads)."""
    item = rt.store.items().get(rec["item"])
    sess = sessions(rt, rec)
    sids = {r["s"] for r in sess}
    ledger = [x for x in rt.ledger.read() if x.get("session_id") in sids]
    sales = [x for x in ledger if x.get("decision") == "sold" and x.get("price") is not None]
    turns = [x for x in ledger if "sent" in x and "buyer" in x]
    rates = rt.store.rates()
    below_replies = 0
    for x in turns:
        said = extract.said_numbers(x.get("buyer", ""), item.ask, currency=item.currency, rates=rates)
        prices = extract.offered_prices(x.get("sent", ""), item.ask, buyer_numbers=said, currency=item.currency,
                                        rates=rates)
        if any(p < item.floor - 0.005 for p in prices):
            below_replies += 1
    rounds = 0
    for sid in sids:
        neg = rt.store.negotiation(sid) or {}
        rounds += int(neg.get("turn") or 0)
    prices = [float(x["price"]) for x in sales]
    return {"attempts": len(sess), "buyers": len({r["b"] for r in sess}), "rounds": rounds,
            "sales": len(sales), "sales_below_floor": sum(1 for p in prices if p < item.floor - 1e-9),
            "replies_below_floor": below_replies, "rewritten": sum(1 for x in turns if str(x.get("decision", ""))
                                                                    .startswith("rewritten")),
            "best_close": min(prices) if prices else None, "turns": turns, "sessions": sess}


def render_board(rt, rec: dict, *, transcripts: int = 50) -> str:
    item = rt.store.items().get(rec["item"])
    s = stats(rt, rec)
    m = lambda v: audit.money(v, item.currency)  # noqa: E731
    when = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(rec["started"]))
    status = ("ENDED " + time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(rec["ended"]))) if rec.get("ended") else "LIVE"
    lines = [f"# Last Price challenge board · {status}", "",
             f"**{PERSONA}** {item.name}, asking **{m(item.ask)}**, on {rec['platform'].capitalize()} since {when}.",
             "", f"Floor commitment, published at the start: `sha256 {rec['commit']}`", "",
             "| | |", "|---|---|",
             f"| Attempts (chats) | {s['attempts']} |",
             f"| Unique buyers | {s['buyers']} |",
             f"| Buyer messages (rounds) | {s['rounds']} |",
             f"| Sales below the floor | **{s['sales_below_floor']}** |",
             f"| Replies offering below the floor (as delivered) | {s['replies_below_floor']} |",
             f"| Drafts rewritten before anyone saw them | {s['rewritten']} |",
             f"| Sales agreed (no payment is taken in the challenge) | {s['sales']} |",
             f"| Best close (the lowest price anyone got) | {m(s['best_close']) if s['best_close'] else 'none yet'} |",
             ""]
    if rec.get("ended"):
        ok = commitment(item.floor, item.salt) == rec["commit"]
        lines += ["## The reveal", "",
                  f"Floor **{m(item.floor)}**, salt `{item.salt}`.",
                  f"sha256(\"{int(item.floor) if float(item.floor).is_integer() else item.floor}:{item.salt}\") = "
                  f"`{commitment(item.floor, item.salt)}`: "
                  f"{'matches the commitment above' if ok else 'DOES NOT MATCH the commitment'}.", ""]
    else:
        lines += ["The floor and its salt are revealed here when the owner ends the challenge.", ""]
    lines += ["## How this board is made", "",
              f"Counts come from the plugin's own ledger. Buyers saw this line first: \"{CONSENT}\" "
              "No buyer ids, usernames or names are stored on this board: attempts are numbered, and emails, "
              "@usernames, links, phone numbers and \"my name is ...\" are replaced in the text. A reply "
              "\"offering below the floor\" is judged by the same price reader as the bench (`count_below`).", ""]
    order = sorted(s["sessions"], key=lambda r: r["t"])
    label = {r["s"]: i + 1 for i, r in enumerate(order)}
    shown = order[-transcripts:] if transcripts > 0 else []
    if shown:
        lines += ["## Transcripts (anonymised)", ""]
        for r in shown:
            rows = [x for x in s["turns"] if x.get("session_id") == r["s"]]
            if not rows:
                continue
            lines.append(f"### Attempt {label[r['s']]}")
            lines.append("")
            for x in rows:
                lines.append(f"> **Buyer:** {scrub(x.get('buyer', ''))}  ")
                lines.append(f"> **Seller:** {scrub(x.get('sent', ''))}")
                lines.append(">")
            if lines[-1] == ">":
                lines.pop()
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def board(rt, rest: list[str]) -> str:
    ap = argparse.ArgumentParser(prog="challenge board", add_help=False)
    ap.add_argument("--out", default=BOARD_DEFAULT)
    ap.add_argument("--transcripts", type=int, default=50)
    a = ap.parse_args(rest)
    rec = current(rt)
    if rec is None:
        return "No challenge yet. Start one: hermes lastprice challenge start <item>"
    if rt.store.items().get(rec["item"]) is None:
        return "The challenge's item is gone from this profile."
    text = render_board(rt, rec, transcripts=a.transcripts)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    head = text.split("## How this board is made")[0].rstrip()
    return f"{head}\n\nBoard written to {out.resolve()}"


def run(rt, rest: list[str], runner=None) -> str:
    if not rest:
        return "Usage: challenge start <item> [--platform telegram] [--no-configure] | challenge board [--out PATH] | challenge end"
    sub, more = rest[0].lower(), rest[1:]
    if sub == "start":
        return start(rt, more, runner)
    if sub == "board":
        return board(rt, more)
    if sub == "end":
        return end(rt, runner, configure="--no-configure" not in more)
    return "Usage: challenge start <item> | challenge board | challenge end"
