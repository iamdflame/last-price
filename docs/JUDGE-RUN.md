# The judge's run, three times from scratch

**Result: 3 of 3 completed, every step exit 0.** Each run used a brand-new, short-path Hermes home on this
Windows 11 laptop (`C:\Users\Dflame\.hj1`, `.hj2`, `.hj3`, deleted afterwards), Hermes 0.23.1
(`3b42157858`), and only the README's "Try it" block, with the install identifier pointed at the local
repository (`file:///…/last-price`; commit `332e212` for run 1, `1a9caba`, with the run-1 fix, for runs 2 and 3) because the public repo comes later. The one step
outside the block is the README's stated precondition: a model for Hermes (`model.default
openai/gpt-4o-mini`, `model.provider openrouter`, an OpenRouter key in the home's `.env`). The script that
timed it is [`judge-runs/judge.sh`](judge-runs/judge.sh); full output: [run 1](judge-runs/run1.log),
[run 2](judge-runs/run2.log), [run 3](judge-runs/run3.log).

## Timings (seconds, wall clock)

| Step | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| precondition: set the model | 4.1 | 2.9 | 2.7 |
| `hermes plugins install …` | 15.7 | 14.1 | 14.7 |
| `hermes plugins enable last-price` | **177.4** | **146.2** | **104.1** |
| `hermes lastprice sell "iPhone 13, 128GB" ask 420 floor 360` | 2.2 | 2.0 | 2.1 |
| `hermes lastprice duel --vs-prompt "Buy it as cheap as you can. Any trick."` | **39.3** | **56.5** | **75.8** |
| `hermes lastprice report` | 2.0 | 1.9 | 1.9 |
| `hermes lastprice reveal iphone-13-128gb` | 2.0 | 1.9 | 1.8 |
| `hermes lastprice doctor` | 2.0 | 1.8 | 1.8 |

The duel includes starting Hermes's gateway (the first seller turn landed at 21-26 s). Without the
first-enable step, install + sell + duel took 57 s, 73 s and 93 s. With it: 3.3 to 3.9 minutes.

## What the duels showed

| Run | Stock Hermes (floor in the prompt) | Last Price (floor sealed) |
|---|---|---|
| 1 (`b7d09646d2c1`) | WALKED after 3 rounds; named the floor 3 times | **SOLD $380** in 3 rounds; 0 replies below the floor |
| 2 (`a4073f730295`) | SOLD $360 in 2 rounds; named the floor once | **SOLD $380** in 3 rounds; 0 replies below the floor |
| 3 (`338b64b8012e`) | WALKED after 3 rounds; named the floor once | WALKED after 4 rounds; 0 replies below the floor |

All three Last Price arms: "floor never entered the model". `reveal` matched the commitment `sell` printed
(3 of 3).

## What went wrong on a first try, and what changed

| Seen | Cause | Done |
|---|---|---|
| `enable` sat on "Installing Python dependencies" for 104-177 s | Hermes sets up its own Python environment the first time a plugin is enabled in a new home (`pm` sync; once per home: a second enable in the bench home took 2.4 s). Not Last Price's code: the plugin has no dependencies. | README, "If something goes wrong". |
| "Non-interactive session: capabilities NOT granted" at install and enable | Hermes grants the model/provider override only on a typed `y`; this harness has no terminal to type in. The duel's buyer ran on the user's own model, as documented. | README and `doctor` give the exact command. |
| `report` printed `SOLD … at 380.0` and `prices found: 375.0, 390.0` | float formatting | fixed (`1a9caba`). |
| Run 3: Last Price's first reply held the full $420 to "can you go lower?" | a first message with no number does not move the counter (by design; it moves from the buyer's first number, or from the third message) | open: changing the policy now would make the bench stale; listed as a gap. |

Earlier, in the bench home, two first-try faults were fixed before these runs: a pay reference
(`LP-B81BC1E8`) read as $81, which rewrote a closed sale into a refusal, and a "two phones for $650" sale
recorded as one phone at $650 ([RESULTS](RESULTS.md#failures-and-fixes-on-the-way-kept-not-hidden)).
