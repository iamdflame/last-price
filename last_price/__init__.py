"""Last Price: Hermes haggles with buyers and closes above a floor its model never sees."""

from __future__ import annotations

import argparse
import shlex
from typing import Any

from . import bench, commands, duel
from .hooks import make_hooks
from .runtime import REFUSED_EXIT, Refusal, Runtime
from .state import MemoryState
from .tools import EXTRA_SCHEMA, ITEMS_SCHEMA, OFFER_SCHEMA, TOOLSET, make_tools

__version__ = "0.1.5"
CHAT_COMMANDS = "sell|list|pause|resume|report|doctor"  # the /lastprice subcommands that work in a chat


def build_runtime(ctx: Any) -> Runtime:
    try:
        state = ctx.state  # profile-scoped plugin state (hermes_cli.plugins_state.PluginState)
        data_dir = state.data_dir
    except Exception:  # an isolated capability probe has no state: run on an empty in-memory one
        state, data_dir = MemoryState(), None
    rt = Runtime(state, data_dir=data_dir, llm_factory=lambda: ctx.llm)
    rt.has_capability = getattr(ctx, "has_capability", None)  # doctor: was the model override granted?
    return rt


def register(ctx: Any) -> None:
    rt = build_runtime(ctx)
    pre_llm_call, pre_tool_call, transform_llm_output = make_hooks(rt)
    ctx.register_hook("pre_llm_call", pre_llm_call)
    ctx.register_hook("pre_tool_call", pre_tool_call)
    ctx.register_hook("transform_llm_output", transform_llm_output, hold_stream=True)

    items, offer, extra = make_tools(rt)
    ctx.register_tool("lastprice_items", TOOLSET, ITEMS_SCHEMA, items,
                      description=ITEMS_SCHEMA["description"], emoji="🏷")
    ctx.register_tool("lastprice_offer", TOOLSET, OFFER_SCHEMA, offer,
                      description=OFFER_SCHEMA["description"], emoji="🏷")
    ctx.register_tool("lastprice_extra", TOOLSET, EXTRA_SCHEMA, extra,
                      description=EXTRA_SCHEMA["description"], emoji="🏷")

    def slash(raw_args: str, platform: str = "", source: Any = None, **_kw: Any) -> str:
        # No platform means an unknown surface, not the owner's terminal: refuse it (OWNER_SURFACES).
        return commands.run(rt, raw_args, platform=platform or "", source=source)

    # In a chat the owner owns, only these work; duel, bench, reveal, owner, shop and challenge are
    # terminal-only (commands.run refuses them off OWNER_SURFACES).
    ctx.register_command("lastprice", slash, description="Last Price: sell with a sealed floor, list, report",
                         args_hint=CHAT_COMMANDS)

    def setup(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("lp_args", nargs=argparse.REMAINDER, help="sell | list | pause | resume | duel | bench | report | "
                                                                    "reveal | doctor | owner | shop | challenge")
        sub.set_defaults(func=cli)

    def cli(args: argparse.Namespace) -> int:
        argv = list(getattr(args, "lp_args", None) or [])
        reply = commands.run(rt, shlex.join(argv), platform="cli",
                             duel_runner=lambda rest: duel.run(rt, rest),
                             bench_runner=lambda rest: bench.run(rt, rest))
        if reply:
            print(reply)
        return REFUSED_EXIT if isinstance(reply, Refusal) else 0  # a refusal exits 1 (README, "Commands")

    ctx.register_cli_command("lastprice", help="Last Price: haggle above a floor the model never sees",
                             setup_fn=setup, handler_fn=cli,
                             description="sell, list, pause, resume, duel, bench, report, reveal, doctor, challenge")
