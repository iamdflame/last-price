"""register(ctx) against a fake Hermes context: what the plugin registers, and the slash command's
surface check (screener M4b: an empty platform was treated as the owner's terminal)."""

import last_price
from helpers import JsonState


class FakeCtx:
    def __init__(self, tmp_path):
        self.hooks, self.tools, self.commands, self.cli = {}, {}, {}, {}

        class S(JsonState):
            data_dir = tmp_path
        self.state = S()
        self.llm = None

    def register_hook(self, name, fn, **kw):
        self.hooks[name] = (fn, kw)

    def register_tool(self, name, toolset, schema, fn, **kw):
        self.tools[name] = toolset

    def register_command(self, name, fn, **kw):
        self.commands[name] = fn

    def register_cli_command(self, name, **kw):
        self.cli[name] = kw


def test_register_wires_the_hooks_tools_and_commands(tmp_path):
    ctx = FakeCtx(tmp_path)
    last_price.register(ctx)
    assert set(ctx.hooks) == {"pre_llm_call", "pre_tool_call", "transform_llm_output"}
    assert ctx.hooks["transform_llm_output"][1] == {"hold_stream": True}
    assert set(ctx.tools) == {"lastprice_items", "lastprice_offer", "lastprice_extra"}
    assert "lastprice" in ctx.commands and "lastprice" in ctx.cli


def test_the_slash_command_refuses_an_unknown_surface(tmp_path):
    ctx = FakeCtx(tmp_path)
    last_price.register(ctx)
    slash = ctx.commands["lastprice"]
    for platform in ("", None, "api_server", "cron", "tool"):
        assert slash('sell "Pixel" ask 300 floor 250', platform=platform) == "Only the shop owner can use /lastprice here."
    assert "Listed Pixel" in slash('sell "Pixel" ask 300 floor 250', platform="cli")


def test_readme_and_doctor_disclose_the_same_tools_children_and_floor_at_rest(tmp_path):
    """Screener M7 #9, #10, #14: the README and `doctor` say the same thing, word for word."""
    import re
    from pathlib import Path

    from helpers import make_rt
    from last_price import commands

    norm = lambda t: re.sub(r"\s+", " ", t)  # noqa: E731
    readme = norm((Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8"))
    doctor = norm(commands.doctor(make_rt(tmp_path)[0]))
    for text in (commands.STOCK_TOOLS, commands.BRIDGE, commands.CHILDREN, commands.AT_REST.rstrip("."),
                 commands.BUYER_GETS, commands.STOCK_SESSION, commands.GATEWAY):
        assert norm(text) in readme, text
        assert norm(text) in doctor, text
    assert "tool_search" in doctor and "--ignore-rules" in doctor and "--source tool" in doctor


def test_the_slash_hint_lists_exactly_the_commands_that_work_in_chat(tmp_path):
    """Screener M7b #9: the hint offered `duel` (terminal-only) and left out others."""
    from helpers import make_rt
    from last_price import CHAT_COMMANDS, commands

    class Src:
        user_id = "42"
    rt, item = make_rt(tmp_path)
    rt.store.add_owner("telegram:42")
    chat = lambda line: commands.run(rt, line, platform="telegram", source=Src())  # noqa: E731
    works = {"sell": 'sell "Pixel" ask 300 floor 250', "list": "list", "pause": "pause", "resume": "resume",
             "report": "report", "doctor": "doctor"}
    assert set(CHAT_COMMANDS.split("|")) == set(works)
    for name, line in works.items():
        reply = chat(line)
        assert "terminal" not in reply.split("\n")[0].lower() or name == "doctor", (name, reply[:120])
    terminal_only = ["duel x", "bench", f"reveal {item.key}", "owner add telegram:7", "shop on telegram",
                     "challenge board"]
    for line in terminal_only:
        assert "terminal" in chat(line).lower(), line
