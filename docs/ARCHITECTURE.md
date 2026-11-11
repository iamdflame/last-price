# Architecture

```
 owner's terminal ── hermes lastprice sell/duel/report/reveal ──┐   (CLI process: register_cli_command)
                                                                │
 owner's chat ───── /lastprice ... ── gateway command lane ─────┤   (dispatched before any agent turn)
                                                                ▼
                                                   ctx.state (plugin-data/…/state.json)
                                                   items · floors · stops · salts · negotiations · duels
                                                                ▲
 buyer ──► Hermes gateway session ──► pre_llm_call ─────────────┤  parse buyer numbers, move counter,
                (agent loop)              │                     │  inject deal context (no floor)
                                          ▼                     │
                                   model ⇄ tools ── pre_tool_call (allowlist, said-number rule)
                                          │         lastprice_offer (yes ≥ counter/stop, else counter)
                                          ▼                     │
                                transform_llm_output (hold_stream=True) ──► ledger.jsonl
                                  extract → below stop? → ctx.llm rewrite → template → holding msg
                                          │
                                          ▼
                                  buyer sees only the audited text
```

## Modules (`last_price/`)

| Module | Role |
|---|---|
| `state.py` | `Store` over `ctx.state`: items (floor, stop, salt, commitment), shop, owners, negotiations, duels |
| `policy.py` | stop draw, Boulware counter with a time concession, offer decision, binding "lowest sent" |
| `extract.py` | prices in seller replies (negation-aware) and buyer messages; language guess |
| `audit.py` | the held audit, rewrite through `ctx.llm`, templates, the JSONL ledger |
| `runtime.py` | `Runtime` (store, ledger, `ctx.llm`) and deal-session resolution (duel titles via public `hermes_state`, shop chats) |
| `hooks.py` | `pre_llm_call`, `pre_tool_call`, `transform_llm_output` |
| `tools.py` | `lastprice_items`, `lastprice_offer`, `lastprice_extra` |
| `commands.py` | `/lastprice` and `hermes lastprice` parsing, owner check, doctor |
| `duel.py` | the side-by-side duel: both arms at once, buyer via `ctx.llm`, seller via `hermes chat` turns |
| `bench.py` | `hermes lastprice bench`: many duels with hidden buyer budgets, CSV + summary with the pass check |
| `report.py` | ledger rendering |
| `challenge.py` | `hermes lastprice challenge` (start, board, end): the public Telegram challenge (guarded chats for anyone, intro and consent line, the anonymised board, the reveal) |

## Public surfaces only

Imports from Hermes: `hermes_state` (SessionDB, read-only), `hermes_constants.get_hermes_home`,
`hermes_cli.config.load_config` — all listed in `hermes_cli/data/plugin_api.json`. Everything else goes
through `ctx` (`state`, `llm`, `register_*`). `hermes plugins validate` reports no private imports and no
core overrides (docs/SKELETON-RESULT.md).

## Processes

* Hooks and tools run in the **gateway** process that owns the session (also for the classic CLI).
* `hermes lastprice …` runs in the **CLI** process; it shares `ctx.state` (file-locked JSON) with the gateway.
* A duel spawns one `hermes chat` client per seller turn; the turn itself runs in the gateway.
