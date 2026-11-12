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
| `subprocess` (`hermes config get`, `set`, `unset`) | reads the memory settings (`shop on`, `challenge start`, `doctor`) and the challenge's six settings one key at a time; sets and restores those six. Every `hermes` child gets the duel's allowlisted environment with `HERMES_HOME` set to Hermes's `get_hermes_home()` (the profile the plugin runs in), and a timeout after which the child and everything it started are killed |
| `hermes_cli.config.load_config()` (public plugin API, in process) | on each turn of a stranger's deal chat: the three memory settings (a reading at most 10 s old) |
| `hermes_cli.config.read_user_config_raw()` (public plugin API, in process) | at `challenge start`: whether any of the six settings holds a `${VAR}` reference in config.yaml, so it is restored as written |

## What leaves the machine

* Buyer messages and the seller's drafts go to your model provider, as in any Hermes chat.
* A rewrite request goes to the same model through `ctx.llm`: the buyer's message, the draft and the
  current counter. Never the floor or the stop.
* In a duel or bench, the buyer model (your own model, or the one you name with `--buyer`) receives the
  buyer's instruction and the whole conversation so far, the seller's replies included.
* Hermes saves the stock seller's system prompt, floor included, with its session in `state.db`; each duel and
  bench duel deletes its stock session when it ends (`hermes sessions delete <id> --yes`), which removes that
  prompt. What remains: the stock seller's replies, which can name the floor, in Hermes's deletion tombstones for its 7-day retry window and in the duel records and ledger in Last Price's data folder; the Last Price seller's session, which never had the floor; and, until SQLite reuses them, the deleted bytes in `state.db`'s free pages, which `hermes sessions optimize` (VACUUM) clears.
* `hermes chat` starts Hermes's background gateway when none is running; a duel or bench that started it stops
  it when it ends (`hermes gateway stop`), and leaves a gateway you were already running alone.
* In a duel with `--vs-prompt` and in every bench, the stock seller's system prompt carries the duel item's
  floor, so the model provider receives it. By default the duel item is a demo item with its own throwaway floor;
  one of your items is used only with `--item <id> --real-item`, which prints a warning.
* `challenge start` changes six gateway settings through `hermes config set` (Telegram open access, a
  Last-Price-only Telegram toolset, owner-only slash commands: `TELEGRAM_ALLOW_ALL_USERS`,
  `platform_toolsets.telegram`, `platforms.telegram.extra.allow_admin_from`, `…user_allowed_commands`,
  `…group_allow_admin_from`, `…group_user_allowed_commands`), after saving their earlier values, each read
  with `hermes config get <key> --json` (Last Price reads no `.env`); `challenge end` restores each one.
  `hermes config get` reports a `${VAR}` reference expanded (`["${LP_ADMIN_ID}"]` comes back as `["4242"]`), so for these six keys `challenge start` also reads config.yaml as written, through Hermes's own raw reader (`hermes_cli.config.read_user_config_raw`, public plugin API), and saves a key that holds a reference as written: `challenge end` puts `${LP_ADMIN_ID}` back (Hermes's `config set` writes it literally), never `4242`, and `start` names each such key. If config.yaml cannot be read that way, nothing is changed and the commands are printed instead. `TELEGRAM_ALLOW_ALL_USERS` lives in `.env`, which Hermes reads without expanding references; Last Price never reads `.env`.
* Whether `TELEGRAM_BOT_TOKEN` is set is judged by the exit code of `hermes config get TELEGRAM_BOT_TOKEN`
  alone; its output is never captured, so the token does not reach Last Price even with
  `security.redact_secrets: false`.
* No telemetry. No payment provider is called in 0.1.x (pay links are placeholders).

## Strangers' chats: a dedicated profile with memory off

The shop (`shop on <platform>`) and the public challenge (`challenge start`) open chats to people you do not
know. Hermes loads a profile's memory (`MEMORY.md`, `USER.md`), its SOUL.md and any memory provider into every
chat in it, a stranger's too, and Last Price's check only looks at prices: a buyer could ask what the bot knows
about you. So both refuse unless `memory.memory_enabled` and `memory.user_profile_enabled` are false and no
`memory.provider` is set. They read the three with `hermes config get` (the same `hermes` the duel runs, with
its allowlisted environment, a 60 s timeout per read and one 90 s deadline for the three) and refuse when
Hermes cannot report them. Memory can be switched on after `shop on` or `challenge start`, so every turn of a stranger's deal chat (shop or challenge) checks again before any model call: in the gateway's own process, through Hermes's public `hermes_cli.config.load_config()`, with a reading at most 10 s old. While memory is on, or cannot be read, the buyer gets "The shop is paused for now. Please try again later." and the turn makes no model call (the `pre_llm_call` block Hermes documents). A chat held once stays held until the gateway restarts, because Hermes keeps that chat's agent, built while memory was on. `doctor` says when stranger chats are held. Two limits: a turn that starts within 10 s of memory being switched on can still run with it, and a chat Last Price does not take as a deal chat (an owner's, or any chat while `shop on` has no open item to sell) is an ordinary Hermes chat. Run them from a dedicated profile:

```
hermes profile create shop
hermes -p shop config set memory.memory_enabled false
hermes -p shop config set memory.user_profile_enabled false
hermes -p shop memory off
hermes -p shop setup
hermes -p shop plugins install iamdflame/last-price
hermes -p shop plugins enable last-price
hermes -p shop lastprice sell "<item>" ask <price> floor <price>
hermes -p shop lastprice challenge start <item>
hermes -p shop gateway
```

Once Last Price is listed in the Hermes plugin catalog, prefer `hermes -p shop plugins install last-price`: it installs the commit Hermes reviewed. Until then `iamdflame/last-price` installs the repository's main branch; add `--ref <40-character commit SHA>` to pin one commit.

Keep that profile's SOUL.md neutral: a new profile gets Hermes's stock SOUL.md, which says nothing about you; do
not create it with `--clone` (that copies your SOUL.md, MEMORY.md and USER.md). Its SOUL.md sits beside the
config.yaml that `hermes -p shop config path` prints. `hermes -p shop lastprice doctor` prints the three
settings, whether `shop on` and `challenge start` would run, and whether stranger chats are held.

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
