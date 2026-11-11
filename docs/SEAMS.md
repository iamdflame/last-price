# Seam checks · Hermes v0.23.1 (`3b42157858`, installed at `%LOCALAPPDATA%\hermes\hermes-agent`)

Paths are relative to that checkout. Live checks ran on Windows 11 in a throwaway `HERMES_HOME`
(`C:\Users\Dflame\.hlp`, model `openai/gpt-4o-mini` on OpenRouter), deleted afterwards.

## (a) The floor in no transcript · PASS for the terminal route, PASS-with-a-gap for the chat route

**Code.**
* A plugin slash command is resolved in the idle command lane before any turn is admitted:
  `gateway/run_inbound.py:1216-1230` (`_hm_dispatch_quick_and_plugin_commands` at 1220, the agent-turn
  rewrite `_admit_command_turn` only at 1230 when nothing handled it).
* `gateway/run_inbound_hooks.py:245-302`: the handler runs with the session context and its return string
  is the reply (`return str(result) if result else None`, 302); no model call.
* Handler call contract: `hermes_cli/plugin_command_dispatch.py:11-32` (`source`, `session_id`,
  `session_key`, `platform` when declared). Registration: `hermes_cli/plugins_context.py:455-481`.
* `hermes lastprice …` is a `register_cli_command` subcommand (`plugins_context.py:441-453`): it runs in
  the terminal process and never touches a session.

**Live.**
1. `hermes lastprice sell "iPhone 13, 128GB" ask 420 floor 360` (terminal), then a search of every text
   column of every table in `state.db` and every log/JSON/MD file under the home (skills, plugin data and
   caches excluded) for `360` and `three hundred (and) sixty`: **0 hits for the floor** (the only regex
   matches were inside a hex digest in `.skills_prompt_snapshot.json` and the model id `LLM360/K2-Think`
   in `models_dev_cache.json`).
2. `/lastprice sell "Pixel 7, 128GB" ask 340 floor 287` sent as a local chat message
   (`hermes chat --query-file`): the reply came back with **0 model tokens**, and the session has
   **no message rows**: the floor is in no transcript and reached no model. **Gap:** core's admission
   ledger keeps the raw submitted text, so `287` appears once in `state.db` table
   `session_admissions.payload_json` (written at `hermes_state_runtime.py:172`, deleted with the session
   at `hermes_state_mutation_retirement.py:141`). Hence the README sends floors through the terminal.
   For messaging platforms the command is dispatched at `run_inbound.py:1220` before any admission, read
   from code; not tested live (no bot token on this machine).

## (b) A held reply is never shown first · PASS

**Registration.** `ctx.register_hook("transform_llm_output", cb, hold_stream=True)`
(`hermes_cli/plugins_context.py:741-743` → `hermes_cli/plugins_dispatch.py:567-579`; `holds_stream`
581-586). The callback gets `response_text, session_id, model, platform, turn_id` and returns a
non-empty string to replace the reply, or `None` to leave it (`agent/turn_finalizer.py:509-547`).

**Every surface.**
* The hold is decided at turn start: `agent/conversation_loop.py:1691-1695` (`_hold_stream`).
* No delta reaches any display or TTS callback while held: `agent/stream_delivery.py:62-67`; interim
  commentary is dropped (`stream_delivery.py:212`); held rows are stored hidden until the final
  (`stream_delivery.py:20-50`).
* Gateway (Telegram, WhatsApp and every other adapter share this path): `gateway/run_turn_runner.py:263-271`
  turns off stream deltas, edits and interim messages when `stream_held()`; the rewrite is sent once.
* Classic CLI / stream-json: the CLI is a gateway client (`hermes_cli/gateway_agent.py:1-9`), so the same
  agent-side hold applies.
* Fail closed: if a held transform raises or times out and none rewrote, the user gets
  `HELD_TRANSFORM_FAILED_REPLY`, never the draft (`agent/turn_finalizer.py:550-564`); every other turn exit
  passes through `settle_held_final` (567-585). Our callback also catches its own errors and returns a
  holding message.
* Docs: `website/docs/user-guide/features/hooks.md:1864-1890`.

**Live.** In the duels, `hermes chat --format stream-json` emitted **no `text` event at all** on the
guarded arm's turns, including the three turns whose drafts were rewritten (ledger
`decision: rewritten-*`): the only text the client received was the `result`, equal to the rewrite.

## (c) Tools locked in a deal session · PASS

* `pre_tool_call` runs before every dispatch and a `{"action": "block", "message": …}` short-circuits the
  tool with that message as its error: `model_tools.py:789-812`, `agent/tool_executor.py:662-676`.
* Fails closed: a callback that raises or times out yields a block directive
  (`hermes_cli/plugins_dispatch.py:59-60`, `295-325`). One residual: if Hermes's dispatcher itself raised,
  `model_tools.py:808-809` logs and proceeds; our callback never raises (it returns a block on any error).
* Hermes's tool-search bridge unwraps `tool_call` before the hook, so the hook sees the real tool name
  (`agent/tool_executor.py:390-425`, `model_tools.py` comment at the bridge dispatch); `tool_search` and
  `tool_describe` are catalog reads scoped to the session. Last Price therefore allows exactly
  `lastprice_items|offer|extra` plus those three bridge names, and blocks everything else.
* Said-number rule: `pre_llm_call` stores the numbers the buyer wrote this turn; `pre_tool_call` blocks
  `lastprice_offer` with any other amount, and the handler re-checks.
* The duel's guarded arm also runs with `-t lastprice`: its stored tool catalog holds exactly the three
  Last Price tools (`state.db` `sessions.tool_names`). Session policy is frozen at creation and a resume
  cannot change it (`hermes_cli/gateway_chat.py:206-223`, `249`).

**Live.** The ledger and `agent.log` show `lastprice_offer` completing 20 times, the said-number block
firing on an unsaid amount, and the allowlist blocking calls outside it.

## (d) The duel runs Hermes's own agent loop · PASS (route: Hermes's programmatic CLI)

**Chosen route.** One `hermes chat` turn per seller message, through Hermes's documented programmatic
interface:
`hermes chat --format stream-json --query-file <f> -c lastprice-duel-<id>-<arm> --create-if-missing -t <toolset> --ignore-rules --source tool`,
then `--resume <session_id>`.
* `-c <title> --create-if-missing` is the documented route for "programmatic callers (plugins, scripts)"
  (`hermes_cli/main.py:1296-1303`); the gateway creates the session with the title (user provenance) and
  the toolset, client env and flags in its frozen policy (`hermes_cli/gateway_chat.py:172-223`).
* The turn runs in the gateway's agent loop with every plugin hook active; the plugin recognises its duel
  sessions by that title through the public `hermes_state.SessionDB` (`hermes_state_titles.py:192-200`;
  `hermes_state` is in `hermes_cli/data/plugin_api.json`).
* The stock arm's floor goes in `HERMES_EPHEMERAL_SYSTEM_PROMPT` (documented,
  `hermes_cli/config_defaults.py:3105-3107`; carried per session, `agent/session_client_env.py:23`;
  "never persisted to sessions").
* Our LLM calls play only the buyer (`ctx.llm`).

**Ruled out.** `ctx.subagent_lifecycle.launch` needs an active parent agent turn
(`agent/subagent_lifecycle.py:277-280`), which a terminal command does not have, and runs a one-shot goal,
not a multi-turn chat. The API server needs its platform enabled with a key (an extra setup step for the
judge). `ctx.inject_message` needs `allow_gateway_injection` and delivers the reply to a chat, not back to
the duel (`plugins_context.py:395-439`).

**Live.** Three duels with `--vs-prompt` ran end to end (docs/SKELETON-RESULT.md); `agent.log` shows
the turns on the gateway, the plugin's hooks and tools, and `plugin_llm.complete … purpose=lastprice-rewrite`
on the gateway side.

**Cost of the route.** A child process per turn (about 10 s per turn on this laptop; the first turn after
a gateway start about 55 s). The child gets an allowlisted environment and never `--yolo`.

**Speed (0.1.1).** Both arms now play at the same time (one thread per arm, each driving its own
`hermes chat` turns), and each round prints as it lands. With a warm gateway a turn takes about 4-6 s
here, so an 8-round duel with both arms finishes in well under two minutes (timings: `docs/JUDGE-RUN.md`).

## (e) The stock arm's tool list · not excludable per session (documented)

The stock arm runs with `-t todo`, yet its stored catalog still lists `lastprice_items|offer|extra`.
Why: a session's explicit toolsets become that session's `platform_toolsets` list
(`gateway/session_policy.py:684`), and `_get_platform_tools` then adds every plugin toolset that is
on by default (`hermes_cli/tools_config.py:620-621`, `_enabled_plugin_toolsets` at 521-528). A plugin
toolset is dropped only by profile-wide config: `known_plugin_toolsets.<platform>` (written when the
user saves a toolset list) or `agent.disabled_toolsets` (a global suppression list,
`tools_config.py:639-643`). Neither is a per-session setting, and both would change the user's own
chats; `--safe-mode` drops plugins but also ignores the user's config, model included
(`hermes_cli/_parser.py:210-211`). So the stock arm keeps the three tool names, and each answers
`{"error": "Last Price is not active in this chat."}` there (`last_price/tools.py`, `OFF`): the stock
seller cannot reach the floor or close a sale through them. The guarded arm's catalog is exactly the
three Last Price tools.
