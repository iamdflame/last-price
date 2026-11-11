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
| `ctx.llm` | the rewrite of a too-low draft (told the counter, never the floor); the duel's buyer |
| `hermes_state.SessionDB` (read-only, public) | reads a session's title to recognise duel sessions; reads a duel session to confirm the floor never reached the model |
| `subprocess` (`hermes chat`, duel only) | runs Hermes's own agent as the seller, one turn per call, from a terminal |

## What leaves the machine

* Buyer messages and the seller's drafts go to your model provider, as in any Hermes chat.
* A rewrite request goes to the same model through `ctx.llm`: the buyer's message, the draft and the
  current counter. Never the floor or the stop.
* In a duel, the buyer's instruction and the seller's replies go to the buyer model.
* No telemetry. No payment provider is called in 0.1.0 (pay links are placeholders).

## The duel's child process

`hermes lastprice duel` runs `hermes chat --format stream-json` once per seller turn. The child gets
an allowlisted environment (`PATH`, `HOME`/`USERPROFILE`, `HERMES_HOME`, Windows system variables and,
for the stock arm only, `HERMES_EPHEMERAL_SYSTEM_PROMPT`), never `--yolo`, and a toolset with no shell,
file or web tools (`lastprice` for the guarded arm, `todo` for the stock arm). Duels never run under cron
or from a messaging chat.

## Reporting

Open a private security advisory on the repository (TBD at publication). Please include the Hermes
version, the plugin version and a transcript if a floor or a below-floor reply reached a buyer.
