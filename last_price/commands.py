"""``/lastprice`` (any chat the owner owns) and ``hermes lastprice`` (a terminal).

The only ways to set a floor. A plugin command is dispatched before any agent turn, so its text
never reaches a model (docs/SEAMS.md, check a). On a messaging platform only an owner id added with
``hermes lastprice owner add <platform>:<user_id>`` may use it; core's ``allow_admin_from`` slash
policy applies on top.
"""

from __future__ import annotations

import argparse
import re
import shlex
from pathlib import Path
from typing import Any, Callable, Optional

from . import audit, challenge, report
from .runtime import OWNER_SURFACES, Runtime
from .state import commitment

USAGE = """Usage: /lastprice <command>  (or: hermes lastprice <command>)
  sell "<item>" ask <price> floor <price> [currency GHS] [extras "case; free delivery"]
  list                     items, asks and floor commitments (never the floor)
  pause | resume           stop or restart every deal
  duel [--vs-prompt] [--buyer MODEL] [--rounds N] "<instruction>"   (terminal only)
  bench [--duels N] [--budgets LO-HI] [--parallel P]   many duels, both sellers (terminal only)
  report [--duel ID] [--last N]   each deal turn: the draft beside what was sent
  reveal <item>            the floor and salt, checked against the commitment (terminal only)
  owner add <platform>:<user_id> | shop on|off <platform>   (terminal only)
  doctor                   the seller model, the buyer, the state file, the hosts contacted
  challenge start <item> | challenge board [--out docs/challenge/board.md] | challenge end   (terminal only)
                           a public "buy it below my floor" challenge on Telegram"""

# One wording for the README and doctor (tests/test_register.py checks both carry it).
STOCK_TOOLS = ("The stock seller runs with Hermes's `todo` toolset plus every plugin toolset your profile turns on "
               "by default (Last Price's own three tools answer \"not active\" there).")
BRIDGE = ("Deal sessions (the Last Price seller, and buyers' chats) may use only Last Price's three tools, plus "
          "Hermes's tool-search bridge (`tool_search`, `tool_describe`, `tool_call`): Hermes resolves a `tool_call` "
          "to the real tool before `pre_tool_call` sees it, so a call through the bridge is checked like any "
          "other; `tool_search` and `tool_describe` only read the session's tool catalog.")
CHILDREN = ("`duel` and `bench` run `hermes chat` child processes, never with `--yolo`, with `--ignore-rules` (your "
            "AGENTS.md, SOUL.md, .cursorrules, memory and preloaded skills stay out, so both sellers start from the "
            "same prompt) and `--source tool` (the duel sessions stay out of your session list).")
AT_REST = ("The floor is hidden from the model in deal sessions, which cannot read files. On your own machine it is "
           "your data, stored as plain JSON in plugin state: readable by you and by any agent you give file "
           "tools to.")
# Screener M7b #3: the buyer model gets the whole conversation, not only the instruction (duel.Buyer.say).
BUYER_GETS = ("In a duel or bench, the buyer model (your own model, or the one you name with `--buyer`) receives the "
              "buyer's instruction and the whole conversation so far, the seller's replies included.")
# Screener M7b #2: Hermes saved the stock seller's prompt with its session (state.db, the launch record).
STOCK_SESSION = ("Hermes saves the stock seller's system prompt, floor included, with its session in `state.db`; "
                 "each duel and bench duel deletes its stock session when it ends (`hermes sessions delete <id> "
                 "--yes`), which removes that prompt. What remains: the stock seller's replies, which can name the "
                 "floor, in Hermes's deletion tombstones for its 7-day retry window and in the duel records and "
                 "ledger in Last Price's data folder; and the Last Price seller's session, which never had the floor.")
# Screener M7b #6: `hermes chat` starts a background gateway when none runs.
GATEWAY = ("`hermes chat` starts Hermes's background gateway when none is running; a duel or bench that started it "
           "stops it when it ends (`hermes gateway stop`), and leaves a gateway you were already running alone.")

DISCLOSURE = [
    "What leaves this machine:",
    "  - buyer messages and Hermes's draft replies go to your model provider (as in any Hermes chat);",
    "  - a rewrite of a too-low draft goes to the same model through ctx.llm: it sees the buyer's message,",
    "    the draft and the current counter, never the floor;",
    "  - " + BUYER_GETS,
    "  - in a duel with --vs-prompt and in every bench, the STOCK seller gets the duel item's floor written",
    "    into its system prompt, which goes to your model provider: by default that is the demo item's",
    "    throwaway floor, never one of your items unless you pass --item <id> --real-item;",
    "  - nothing else: no telemetry, no payment calls yet (pay links are placeholders in 0.1.x).",
    "Tools and processes:",
    "  - " + BRIDGE,
    "  - " + STOCK_TOOLS,
    "  - " + CHILDREN,
    "  - " + GATEWAY,
    "  - " + STOCK_SESSION,
    "  - " + challenge.SETTINGS_DISCLOSURE,
    "What stays here: floors, stops and salts in plugin state under your Hermes home; the deal ledger (JSONL).",
    "  " + AT_REST,
]

_NUM = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


def _num(tok: str) -> float:
    m = _NUM.search(tok.replace(",", "") if tok.count(",") and "." not in tok else tok)
    if not m:
        raise ValueError(f"not a price: {tok!r}")
    return float(m.group(0).replace(",", "."))


def parse_sell(rest: list[str]) -> dict:
    """``"<name>" ask 420 floor 360 [currency GHS] [extras "a; b"]`` -> fields."""
    out: dict[str, Any] = {"extras": [], "currency": "USD"}
    name_parts: list[str] = []
    i = 0
    while i < len(rest):
        tok = rest[i]
        low = tok.lower()
        if low in ("ask", "floor", "currency", "extras", "extra") and i + 1 < len(rest):
            val = rest[i + 1]
            if low == "ask":
                out["ask"] = _num(val)
            elif low == "floor":
                out["floor"] = _num(val)
            elif low == "currency":
                out["currency"] = val.upper()
            else:
                out["extras"] = [e.strip() for e in re.split(r"[;|]", val) if e.strip()]
            i += 2
            continue
        name_parts.append(tok)
        i += 1
    out["name"] = " ".join(name_parts).strip().strip('"')
    if not out["name"] or "ask" not in out or "floor" not in out:
        raise ValueError('expected: sell "<item>" ask <price> floor <price>')
    return out


def is_owner(rt: Runtime, platform: str, source: Any) -> bool:
    if (platform or "").lower() in OWNER_SURFACES:
        return True
    user_id = getattr(source, "user_id", None) if source is not None else None
    return bool(user_id) and f"{platform.lower()}:{user_id}" in rt.store.owners()


def run(rt: Runtime, text: str, *, platform: str = "cli", source: Any = None,
        duel_runner: Optional[Callable[[list[str]], str]] = None,
        bench_runner: Optional[Callable[[list[str]], str]] = None) -> str:
    """Dispatch one ``/lastprice`` or ``hermes lastprice`` command line; returns the reply."""
    if not is_owner(rt, platform, source):
        return "Only the shop owner can use /lastprice here."
    try:
        parts = shlex.split(text or "", posix=True)
    except ValueError as exc:
        return f"Could not parse that: {exc}"
    if not parts:
        return USAGE
    cmd, rest = parts[0].lower(), parts[1:]
    local = (platform or "").lower() in OWNER_SURFACES
    try:
        if cmd == "sell":
            f = parse_sell(rest)
            it = rt.store.sell(f["name"], f["ask"], f["floor"], currency=f["currency"], extras=f["extras"])
            return (f"Listed {it.name} at {audit.money(it.ask, it.currency)} (item id: {it.key}).\n"
                    f"Floor sealed. Commitment: sha256 {it.commit}\n"
                    "No model, tool result, prompt or log will carry it. Check it later with "
                    f"`hermes lastprice reveal {it.key}`.")
        if cmd == "list":
            items = rt.store.items()
            if not items:
                return 'No items yet. Add one: hermes lastprice sell "<item>" ask <price> floor <price>'
            rows = [f"{i.key:24} {audit.money(i.ask, i.currency):>10}  {i.status:8} commit {i.commit[:16]}..."
                    for i in items.values()]
            state = "open" if rt.store.shop_open() else "PAUSED"
            return f"Shop: {state}\n" + "\n".join(rows)
        if cmd == "pause":
            rt.store.set_shop_open(False)
            return "Paused: every deal chat now gets a holding message until you run resume."
        if cmd == "resume":
            rt.store.set_shop_open(True)
            return "Resumed: deal chats are open."
        if cmd == "owner":
            if len(rest) == 2 and rest[0] == "add" and re.fullmatch(r"[a-z0-9_]+:[^\s]+", rest[1]):
                if not local:
                    return "Add owners from a terminal: hermes lastprice owner add <platform>:<user_id>"
                rt.store.add_owner(rest[1])
                return f"Owner added: {rest[1]}"
            return "Usage: owner add <platform>:<user_id>"
        if cmd == "shop":
            if len(rest) == 2 and rest[0] in ("on", "off") and re.fullmatch(r"[a-z0-9_]+", rest[1]):
                if not local:
                    return "Change shop platforms from a terminal."
                plats = set(rt.store.backend.get("shop_platforms", []) or [])
                (plats.add if rest[0] == "on" else plats.discard)(rest[1])
                rt.store.backend.set("shop_platforms", sorted(plats))
                return f"Shop platforms: {', '.join(sorted(plats)) or 'none'} (non-owner chats there haggle)."
            return "Usage: shop on|off <platform>"
        if cmd == "report":
            ap = argparse.ArgumentParser(prog="report", add_help=False)
            ap.add_argument("--duel")
            ap.add_argument("--last", type=int, default=12)
            a = ap.parse_args(rest)
            return report.render(rt.ledger.read(), duel=a.duel, last=a.last)
        if cmd == "reveal":
            if not local:
                return "Reveal only in a terminal: hermes lastprice reveal <item>"
            it = rt.store.item(" ".join(rest) if rest else None)
            if it is None:
                return "No such item."
            ok = commitment(it.floor, it.salt) == it.commit
            return (f"{it.name}\n  floor: {audit.money(it.floor, it.currency)}\n  salt: {it.salt}\n"
                    f"  sha256(floor:salt) = {commitment(it.floor, it.salt)}\n"
                    f"  commitment at listing = {it.commit}\n  match: {'yes' if ok else 'NO'}")
        if cmd == "doctor":
            return doctor(rt)
        if cmd == "challenge":
            if not local:
                return "Run the challenge from a terminal: hermes lastprice challenge start <item>"
            return challenge.run(rt, rest)
        if cmd == "duel":
            if not local or duel_runner is None:
                return "Duels run in a terminal: hermes lastprice duel --vs-prompt \"<instruction>\""
            return duel_runner(rest)
        if cmd == "bench":
            if not local or bench_runner is None:
                return "The bench runs in a terminal: hermes lastprice bench --duels 12 --budgets 330-410"
            return bench_runner(rest)
    except ValueError as exc:
        return f"{exc}\n\n{USAGE}"
    return USAGE


PLUGIN_ID = "last-price"
FREE_MODEL = "google/gemma-4-31b-it:free"
PROVIDER_HOSTS = {"openrouter": "openrouter.ai", "openai": "api.openai.com", "anthropic": "api.anthropic.com",
                  "nous": "nousresearch.com", "gemini": "generativelanguage.googleapis.com",
                  "google": "generativelanguage.googleapis.com", "groq": "api.groq.com", "mistral": "api.mistral.ai",
                  "deepseek": "api.deepseek.com", "xai": "api.x.ai"}


def _model_config() -> tuple[str, str, str]:
    """(model, provider, base_url) from Hermes's config (public ``hermes_cli.config.load_config``)."""
    from hermes_cli.config import load_config

    cfg = load_config() or {}
    model = cfg.get("model") or {}
    if isinstance(model, dict):
        return (str(model.get("default") or ""), str(model.get("provider") or cfg.get("provider") or ""),
                str(model.get("base_url") or cfg.get("base_url") or ""))
    return str(model or ""), str(cfg.get("provider") or ""), str(cfg.get("base_url") or "")


def _override_granted(rt: Runtime) -> Optional[bool]:
    """Through ``ctx.has_capability`` (the documented probe); None when it is not available."""
    probe = getattr(rt, "has_capability", None)
    if probe is None:
        return None
    try:
        return bool(probe("llm.model_override") and probe("llm.provider_override"))
    except Exception:
        return None


def _host(provider: str, base_url: str) -> str:
    if base_url:
        from urllib.parse import urlparse

        return urlparse(base_url).hostname or base_url
    return PROVIDER_HOSTS.get(provider.lower(), f"your '{provider or 'default'}' provider's endpoint")


def doctor(rt: Runtime) -> str:
    lines = ["Last Price doctor"]
    try:
        model, provider, base_url = _model_config()
    except Exception:
        model, provider, base_url = "", "", ""
    if model:
        lines.append(f"  seller model: {model}{' on ' + provider if provider else ''} (Hermes's own model: deal chats "
                     "and both duel sellers use it)")
    else:
        lines.append("  seller model: NOT SET. Run `hermes model`, or "
                     "`hermes config set model.default openai/gpt-4o-mini` and `hermes config set model.provider "
                     "openrouter`")
    granted = _override_granted(rt)
    if granted:
        lines.append("  buyer (duel, bench): `--buyer MODEL` runs on OpenRouter (model override: granted); "
                     f"without --buyer it runs on {model or 'your own model'}")
    else:
        why = "NOT granted" if granted is False else "unknown"
        lines.append(f"  buyer (duel, bench): runs on your own model ({model or 'not set'}); model override: {why}.")
        lines.append(f"    To let `--buyer MODEL` pick another model, run `hermes plugins enable {PLUGIN_ID}` in an "
                     "interactive terminal and answer y.")
    lines.append(f"  free path: an OpenRouter key with no credit runs `:free` models. Seller: `hermes config set "
                 f"model.default {FREE_MODEL}`; buyer: `--buyer {FREE_MODEL}`. Free models are rate-limited, so "
                 "a duel can stall; on the Hermes desktop app's Nous free tier, the seller runs on `nous/welcome`.")
    try:
        items = rt.store.items()
        path = getattr(rt.store.backend, "path", None)
        size = Path(path).stat().st_size if path and Path(path).exists() else 0
        where = f"{path} ({size / 1024:.0f} KB of 10240 KB)" if path else "in memory (no Hermes state)"
        lines.append(f"  state: readable · {len(items)} item(s) · shop "
                     f"{'open' if rt.store.shop_open() else 'PAUSED'} · {where}")
    except Exception as exc:  # the shop closes on unreadable state (hooks fail closed)
        lines.append(f"  state: UNREADABLE ({exc.__class__.__name__}); deal chats get a holding message. Move the "
                     "file aside to start fresh (floors in it are lost)")
    turns, sales = report.tally(rt.ledger.read()) if rt.ledger.path else (0, 0)
    lines.append(f"  ledger: {rt.ledger.path or 'disabled'} ({report.plural(turns, 'turn')}, "
                 f"{report.plural(sales, 'sale')}; `hermes lastprice report` counts the same)")
    hosts = [f"{_host(provider, base_url)} (your model provider: buyer messages, drafts, rewrites)"]
    if granted:
        hosts.append("openrouter.ai (a duel buyer named with --buyer)")
    lines.append("  hosts contacted: " + "; ".join(hosts) + ". Nothing else: no telemetry, no payment provider.")
    lines.append(f"  owners: {', '.join(rt.store.owners()) or 'local terminal only'}")
    lines.append(f"  shop platforms: {', '.join(rt.store.backend.get('shop_platforms', []) or []) or 'none (duels only)'}")
    rec = challenge.current(rt)
    if rec:
        lines.append(f"  challenge: {rec['id']} on {rec['platform']} ({'ended' if rec.get('ended') else 'LIVE'}), item "
                     f"{rec['item']}; `hermes lastprice challenge board` writes the public board")
    lines.extend("  " + d for d in DISCLOSURE)
    return "\n".join(lines)
