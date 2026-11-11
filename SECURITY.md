# Security policy

## What Last Price protects

The owner's **floor** (lowest acceptable price) for each item. The model that talks to buyers never
receives it: not in a system prompt, a tool result, injected context, a log line or the ledger. Every
reply in a deal chat is held and checked before anyone sees it, and a sale closes only at or above a
hidden stop that sits above the floor. See `docs/THREAT_MODEL.md` for the attacks considered.

## What it touches

| Surface | Use |
|---|---|
| `ctx.register_command("lastprice")`, `ctx.register_cli_command("lastprice")` | the only ways to set a floor; owner-only |
| `ctx.state` (profile-scoped JSON under `<HERMES_HOME>/plugin-data/`) | items, floors, stops, salts, negotiations, duel records |
| `<data dir>/ledger.jsonl` | each deal turn: buyer text, draft, sent text, prices found, decision (never the floor or stop) |
| hooks `pre_llm_call`, `pre_tool_call`, `transform_llm_output` (`hold_stream=True`) | per-turn deal context, the tool lock, the held audit |
| tools `lastprice_items`, `lastprice_offer`, `lastprice_extra` | the only tools a deal session may call (with Hermes's tool-search bridge, which resolves to them) |
| `ctx.llm` | the rewrite of a too-low draft (given the buyer's message, the draft, the current counter and the allowed extras; never the floor); the duel's buyer |
| `hermes_state.SessionDB` (read-only, public) | reads a session's title to recognise duel sessions; reads a duel session to confirm the floor never reached the model |
| `subprocess` (`hermes chat`, duel only) | runs Hermes's own agent as the seller, one turn per call, from a terminal |

## What leaves the machine

* Buyer messages and the seller's drafts go to your model provider, as in any Hermes chat.
* A rewrite request goes to the same model through `ctx.llm`: the buyer's message, the draft and the
  current counter. Never the floor or the stop.
* In a duel, the buyer's instruction and the seller's replies go to the buyer model.
* In a duel with `--vs-prompt` and in every bench, the stock seller's system prompt carries the duel item's
  floor, so the model provider receives it. By default the duel item is a demo item with its own throwaway floor;
  one of your items is used only with `--item <id> --real-item`, which prints a warning.
* `challenge start` changes six gateway settings through `hermes config set` (Telegram open access, a
  Last-Price-only Telegram toolset, owner-only slash commands: `TELEGRAM_ALLOW_ALL_USERS`,
  `platform_toolsets.telegram`, `platforms.telegram.extra.allow_admin_from`, `…user_allowed_commands`,
  `…group_allow_admin_from`, `…group_user_allowed_commands`), after saving their earlier values;
  `challenge end` restores each one.
* No telemetry. No payment provider is called in 0.1.x (pay links are placeholders).

## The duel's child process

`hermes lastprice duel` runs `hermes chat --format stream-json` once per seller turn. The child gets
an allowlisted environment (`PATH`, `HOME`/`USERPROFILE`, `HERMES_HOME`, Windows system variables and,
for the stock arm only, `HERMES_EPHEMERAL_SYSTEM_PROMPT`), never `--yolo`, and a toolset with no shell,
file or web tools: `lastprice` for the guarded arm; for the stock arm, Hermes's `todo` toolset plus every
plugin toolset the profile turns on by default (Last Price's own three tools answer "not active" there). It
runs with `--ignore-rules` (the owner's AGENTS.md, SOUL.md, .cursorrules, memory and preloaded skills stay out,
so both sellers start from the same prompt) and `--source tool` (duel sessions stay out of the owner's session
list). Duels never run under cron or from a messaging chat.

## The floor at rest

The floor is hidden from the model in deal sessions, which cannot read files. On your own machine it is your
data, stored as plain JSON in plugin state: readable by you and by any agent you give file tools to
(`docs/THREAT_MODEL.md`, "The owner's own machine").

## Reporting

Open a private security advisory on the repository (TBD at publication). Please include the Hermes
version, the plugin version and a transcript if a floor or a below-floor reply reached a buyer.
