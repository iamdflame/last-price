"""``hermes lastprice report``: each deal turn's draft beside what was sent."""

from __future__ import annotations

import textwrap
from typing import Optional


def _wrap(text: str, width: int, indent: str) -> str:
    return textwrap.fill(" ".join(str(text or "").split()), width=width, initial_indent=indent,
                         subsequent_indent=" " * len(indent))


def plural(n: int, word: str, many: str = "") -> str:
    return f"{n} {word if n == 1 else (many or word + 's')}"


def split(rows: list[dict], duel: Optional[str] = None) -> tuple[list[dict], list[dict]]:
    """(deal turns, sales): a ledger row is a turn unless it records a sale. ``report`` and ``doctor``
    both count this way."""
    mine = [r for r in rows if duel is None or r.get("duel") == duel]
    return [r for r in mine if r.get("decision") != "sold"], [r for r in mine if r.get("decision") == "sold"]


def tally(rows: list[dict], duel: Optional[str] = None) -> tuple[int, int]:
    turns, sales = split(rows, duel)
    return len(turns), len(sales)


def render(rows: list[dict], *, duel: Optional[str] = None, last: int = 12, width: int = 100) -> str:
    turns, sales = split(rows, duel)
    if not turns and not sales:
        return "The ledger is empty: no deal turns yet."
    out = []
    shown = turns[-last:] if last else turns
    rewritten = sum(1 for r in turns if str(r.get("decision", "")).startswith("rewritten"))
    out.append(f"Last Price report: {plural(len(turns), 'turn')}, {plural(rewritten, 'draft')} rewritten, "
               f"{plural(len(sales), 'sale')}" + (f" · duel {duel}" if duel else "")
               + (f" · showing the last {len(shown)}" if len(shown) < len(turns) else ""))
    for r in shown:
        d = r.get("decision", "")
        tag = {"pass": "sent as drafted", "rewritten-model": "REWRITTEN by the model",
               "rewritten-template": "REWRITTEN by template", "held-error": "HELD (check failed)"}.get(d, d)
        out.append("-" * min(width, 100))
        out.append(f"{r.get('item', '?')} · {r.get('arm', '')} · turn {r.get('turn', '?')} · {tag}")
        if r.get("buyer"):
            out.append(_wrap(r["buyer"], width, "  buyer: "))
        if d != "pass":
            out.append(_wrap(r.get("draft", ""), width, "  draft: "))
        out.append(_wrap(r.get("sent", ""), width, "  sent:  "))
        if r.get("prices_found"):
            out.append(f"  prices found in the draft: {', '.join(f'{float(p):g}' for p in r['prices_found'])}")
    for s in sales[-5:]:
        out.append(f"SOLD {s.get('item')} at {float(s.get('price') or 0):g} (ref {s.get('ref')}, {s.get('arm', '')})")
    return "\n".join(out)
