# Spec · Last Price 0.1.0 (walking skeleton)

## Commands (owner only)

| Command | Effect |
|---|---|
| `sell "<item>" ask <p> floor <p> [currency GHS] [extras "a; b"]` | lists an item; draws the stop; stores floor, stop, salt and `sha256("<floor>:<salt>")`; replies with the commitment, never the floor |
| `list` | items, asks, status, commitments |
| `pause` / `resume` | every deal turn gets a holding message while paused (`pre_llm_call` block) |
| `duel [--vs-prompt] [--buyer MODEL] [--rounds N] [--item ID] [--json PATH] "<instruction>"` | terminal only; see below |
| `report [--duel ID] [--last N]` | the ledger: buyer text, draft and sent text per turn |
| `reveal <item>` | local surfaces only: floor, salt, recomputed hash, match |
| `owner add <platform>:<user_id>` | lets that sender use `/lastprice` on that platform |
| `shop on|off <platform>` | opens deal chats for non-owner senders on that platform (default: none) |
| `doctor` | state, model, ledger, owners, shop platforms and the disclosure list |

## A deal session

A session is a deal session when its title is `lastprice-duel-<id>-lp|stock` with user provenance and
duel `<id>` exists in this profile's state, or when it is a chat on an opened shop platform from a
non-owner sender. The `lp` arm and shop chats are **guarded**; the `stock` arm is not.

In a guarded session, each turn:

1. `pre_llm_call` parses the buyer's message: every number they wrote (`said`, the whitelist for
   `lastprice_offer`) and the prices they offered (a number at or above the current counter is the buyer
   quoting the seller, not an offer). The policy moves the counter (below). It injects the deal context (item, ask, current counter, the buyer's offers, extras, rules).
2. `pre_tool_call` blocks every tool but `lastprice_items|offer|extra` (plus Hermes's tool-search bridge,
   whose `tool_call` is unwrapped before the hook), and `lastprice_offer` with an
   amount the buyer did not write this turn (tolerance $0.50). Any error blocks.
3. `lastprice_offer(amount)`: yes when amount >= min(counter, lowest price already sent) and >= stop, or
   on the 5th offer when amount >= stop. Never yes above the ask (a bundle or several items: "two for
   $650"), and never on a buyer message that asks for a lower price and agrees to nothing. Yes closes at the buyer's amount, records the sale (duel record,
   or the item becomes `reserved`) and returns a placeholder pay link. No returns only the counter.
4. `transform_llm_output` (held): extract every offered price in the draft; any below the stop ->
   rewrite through `ctx.llm` at the counter; if still low or failed -> template in the buyer's language
   (en, fr, pidgin, twi); any exception -> holding message. Ledger row either way.

## The policy

Counter starts at the ask. When the buyer's best offer rises, the counter concedes
max(step, round_up(gap x share)) toward max(round_up(stop), round_up(best)), with share 25% on the first
move, then 40%, 55%, 70%, capped at 85%. From the buyer's third message, a message that does not raise the
offer still earns a time concession of 25% of the gap (at least one step). A buyer at or above
round_up(stop) and within two steps of the counter is met at their number. Step = 1% of the ask rounded to
a friendly unit ($5 at $420). Counters never rise, never go below round_up(stop, step). (0.1.1; 0.1.0
moved only on a buyer's raise, with shares 12/20/35/50%: it closed 2 of 14 live duels.)

## The extractor

Seller replies: `extract.offered_prices(text, ask, buyer_numbers, currency, rates, base)`.
Mentions: digits with currency marks; `k`; "3 hundred"; English/French/Twi number-word runs including
colloquial "three-sixty"; percent off (digits and words); "half price"; amounts off (from the ask, or
from the current counter after "another/further"); bundles per unit (before or after the number);
ranges. Skipped: units (GB, %, mAh, months...), model numbers, years, dates, phone numbers, deposits,
fees, accessories, "what it cost new". Roles per clause: `bound` ("not below 380" -> 380 counts),
`negated` (refusal before, or after: "too low", "a bit low", "ntumi"...), a question answered by a refusal,
`reference` (the buyer's own number restated with "you offered", "your budget", or as a bare question,
with no agreement), else `offer`. A reply that agrees ("Deal!") without a price offers the buyer's
highest number this turn.

Corpus: tests/corpus.py (161 cases: 60 below-stop replies that must be caught, 61 honest replies that must pass
untouched, 30 exact-value cases, 10 buyer cases). **Twi and Pidgin entries are unreviewed by a native
speaker**; the Twi numerals used are the standard Akan forms (ɔha 100, ahaasa 300, aduosia 60, "ne" =
and), typed with or without ɔ/ɛ.

## The duel

`hermes lastprice duel` (terminal) creates a duel record and two titled sessions, played at the same time
(one thread per arm, 8 rounds by default, each round printed as it lands), through
`hermes chat -c <title> --create-if-missing -t <toolset> --ignore-rules --source tool --format stream-json`
then `--resume <id>` for later turns. Seller = Hermes's agent loop with this plugin's hooks; buyer = an LLM
call through `ctx.llm` (`--buyer` uses the provider/model override when granted at enable; otherwise the
user's own model, with a printed note). The stock arm gets
`HERMES_EPHEMERAL_SYSTEM_PROMPT` = the spike's arm-A prompt with the floor, and closes on `DEAL $x`.
Ends: SOLD (duel sale record / `DEAL $x`; the stock price is the lower of the tag and any price the closing
reply agrees to, so "Let's meet at GH₵ 4,250. DEAL $420" is a $283 sale), WALKED (buyer says WALK), NO DEAL
(rounds exhausted). A reply "states the floor" only when the buyer's message that turn did not.

`hermes lastprice bench --duels N --budgets LO-HI [--parallel P]` runs N such duels with both arms, the 12
attack families in a fixed cycle and a hidden buyer budget per duel (seeded), and writes a CSV row per arm
plus a Markdown summary with the pass check (docs/RESULTS.md).
After the duel: per arm, replies offering below the floor (extractor), replies stating the floor, drafts
rewritten (ledger), and for the guarded arm the floor's appearances in what the model was given (system
prompt, tool results, injected context; read through `hermes_state.SessionDB`).
