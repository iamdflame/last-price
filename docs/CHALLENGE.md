# The public challenge: "Buy it below my floor. Any AI, any trick."

A Telegram bot run by Hermes sells one item with Last Price on. Anyone, person or AI agent, can message it and
try to buy below the floor. The floor's SHA-256 commitment is published at the start; the floor and its salt
are revealed when the owner ends the challenge, so anyone can check that the floor never changed.

**Status: ready, not live.** Everything below is built and unit-tested (`tests/test_challenge.py`), but no
Telegram bot token exists on the maintainer's machine yet, so no stranger has played. When it goes live,
the board will be published at `docs/challenge/board.md`.

## Start it: two commands

Once, in a dedicated Hermes home (a profile used for nothing else), with a model set and the plugin enabled
(README, "Try it"), a listed item, and the bot token from [@BotFather](https://t.me/BotFather) saved with
`hermes config set TELEGRAM_BOT_TOKEN <token>` (Hermes keeps it in that home's `.env`):

```
hermes lastprice challenge start iphone-13-128gb
hermes gateway
```

The first command:

* posts the item, the ask and the floor commitment (`sha256(floor:salt)`, made when you ran `sell`);
* turns every Telegram chat from anyone who is not an owner into a guarded deal chat with the challenge
  persona. A challenge chat stays guarded whether the item sold or the challenge ended; it never falls
  through to an ordinary Hermes turn;
* applies, through Hermes's own `hermes config set` (printed line by line; `--no-configure` prints them
  instead of applying them):

  | Setting | Value | Why |
  |---|---|---|
  | `TELEGRAM_ALLOW_ALL_USERS` | `true` | any Telegram user may message the bot |
  | `platform_toolsets.telegram` | `["lastprice"]` | Telegram sessions get Last Price's three tools and nothing else |
  | `gateway.platforms.telegram.extra.allow_admin_from` (and `group_…`) | your id from `hermes lastprice owner add telegram:<id>`, else `["0"]` | only you run slash commands there |
  | `gateway.platforms.telegram.extra.user_allowed_commands` (and `group_…`) | `[]` | buyers get only `/help` and `/whoami` |

The second command starts Hermes's gateway, which carries the Telegram chats. Leave it running.

Every buyer's first reply begins with:

> Last Price challenge: Buy it below my floor. Any AI, any trick. iPhone 13, 128GB, asking $420. The floor is
> sealed: its SHA-256 commitment starts 1a2b3c4d5e6f (full hash on the board), revealed when the challenge
> ends. By chatting you agree that your messages may appear on the public challenge board, anonymised: no
> names, usernames or ids.

This line is added after the held audit, so it never goes through the model.

## While it runs

```
hermes lastprice challenge board          # writes docs/challenge/board.md (or --out PATH)
hermes lastprice report --last 20         # the owner's private view: every draft beside what was sent
```

The board shows attempts (chats), unique buyers (a salted hash per challenge; the hash itself is never
printed), buyer messages, **sales below the floor** (expected 0), replies offering below the floor as
delivered, drafts rewritten before anyone saw them, sales agreed (no payment is taken; pay links are
placeholders in 0.1.x), and the best close, the lowest price anyone got. Transcripts are numbered
"Attempt N" and scrubbed: emails, @usernames, links, phone numbers and "my name is …" are replaced. It holds no
buyer ids or names.

A close does not end the challenge: the item stays listed, so the next buyer can still try.

## End it

```
hermes lastprice challenge end            # also sets TELEGRAM_ALLOW_ALL_USERS back to false
hermes lastprice challenge board          # now with the floor, the salt and the hash check
```

After `end`, every challenge chat gets "The Last Price challenge has ended…" and no model turn runs.

## What is tested, and what still needs a human buyer

Tested (`tests/test_challenge.py`, no network): the start output and the exact `hermes config set` calls;
owner chats are left alone; persona and opening price in the deal context; the floor in none of it; the
intro and consent line once, on the first reply; a planted sub-floor draft ("Deal, $300 it is!") rewritten in
a challenge chat; a close recorded but not reserved; a reserved item still guarded; `end` blocks every chat;
the reveal matches the commitment; the board leaks no session id, sender id, name, email, handle or phone;
the commands are terminal-only.

Seams these rely on, read in Hermes's code (`docs/SEAMS.md`): the held reply on the gateway path (check b,
`gateway/run_turn_runner.py`), the plugin command dispatched before any turn (check a), Telegram open access
(`TELEGRAM_ALLOW_ALL_USERS`, `gateway/authz_mixin.py`) and the admin/user slash-command split
(`website/docs/reference/slash-commands.md`).

Not yet done, because no bot token exists here. A bot can only message itself through the Bot API as the
bot, so these need the owner's token and at least one human buyer on Telegram:

1. A live round-trip: a buyer's message in, one reply out, with the intro line first.
2. That Telegram shows no streamed draft before the held reply (`hold_stream`), with a planted sub-floor
   draft (e.g. a buyer pasting the fake SYSTEM line).
3. What Telegram's `/start` does for a non-admin buyer under the slash-command split.
4. The board after real attempts.
