# notify-hub

[中文](README.md) | **English**

A local notification gateway. Any program on your computer (a mail monitor, an experiment script, a scheduled job, Claude Code) calls the same command when it wants to tell you something, and notify-hub pushes it to Lark on your phone. Levels, deduplication, rate limiting and retries are written once instead of in every program.

```
mail monitor / experiment scripts / scheduled jobs / Claude Code
        │  notify-hub send "title" --level urgent --source mail
        ▼
notify-hub (runs only when called; no daemon)
  1. writes the message to an outbox (SQLite) first, so nothing is lost offline or in a crash
  2. deduplicates and rate-limits: one event is pushed once, a flood goes to the digest
  3. renders a Lark card and sends it; failures stay in the outbox and are retried
        │
        ▼
Lark app bot → your phone
```

## Install

Needs Python 3.10 or later. [uv](https://docs.astral.sh/uv/) installs it into your home folder, no admin password:

```bash
uv tool install git+https://github.com/yuhang2551/notify-hub
```

The command lands in `~/.local/bin/notify-hub`. If the terminal cannot find `notify-hub`, use the full path or add `~/.local/bin` to PATH.

## Configure

You need a Lark (or Feishu) app bot:

1. [Lark developer console](https://open.larksuite.com/app) (Feishu: open.feishu.cn) → create a custom app, for example "Notifier".
2. Add Features → Bot.
3. Under Permissions & Scopes turn on `im:message:send_as_bot` (send messages as the app) and `im:chat:readonly` (list the chats the bot is in).
4. Version Management & Release → create and publish a version that is available to you.
5. In Lark, create a chat (just you is fine), then chat settings → Bots → add the app's bot.

Then:

```bash
notify-hub init          # creates ~/.notify-hub/.env (readable only by you); fill in App ID and App Secret
notify-hub chats         # lists the chats the bot is in with their chat_id; put one in LARK_RECEIVE_ID
notify-hub test          # sends a test message; when it reaches your phone, you are done
```

If Lark is already set up for the [mail monitor](https://github.com/yuhang2551/thunderbird-mail-agent/tree/main/monitor), copy it over in one step, without the secrets passing through your hands:

```bash
notify-hub init --from ~/.mail-monitor/.env
notify-hub test
```

Every setting is listed in [env.example](notify_hub/env.example). A chat id in `LARK_RECEIVE_ID` (starting with `oc_`) sends to that chat; your open_id (starting with `ou_`) sends you a direct message. There is no separate type to fill in.

## Usage

```bash
notify-hub send "TimeFence finished" --body "IC 0.031, took 42 minutes" --source timefence
notify-hub send "New job match: 82" --source job --link "https://example.com/jobs/123"
echo "2 GB of disk left" | notify-hub send "Backup failed" --level urgent --source backup --body -
```

| Option | What it does |
|---|---|
| title | Required, one line |
| `--body` | Body text; `-` reads it from stdin |
| `--level` | `urgent` (red card), `normal` (default, blue), `digest` (kept for the digest) |
| `--source` | Which program sent it, such as `mail` or `timefence`; used for grouping and rate limits |
| `--link` | Adds an "Open" button to the card, labelled with the site's domain |
| `--key` | For deduplication: one source and one key are pushed once per 24 hours |
| `--quiet` | Print nothing when the push succeeds |

A failed push is not an error: the message stays in the outbox and is retried later, and the exit code is still 0, so the calling program never stops because a push failed. Only bad arguments exit with 2.

From Python:

```python
from notify_hub import notify

result = notify("TimeFence finished", "IC 0.031", source="timefence")
print(result.status)  # sent, queued (not sent yet, will retry), digest or skipped (duplicate)
```

## Other commands

| Command | What it does |
|---|---|
| `notify-hub status` | Shows the configuration and the outbox: how much was sent, what is stuck, the latest errors |
| `notify-hub flush` | Retries messages that are due and gives up on those older than a day; meant for a scheduled job |
| `notify-hub test` | Sends one test message directly, bypassing the outbox |
| `notify-hub chats` | Lists the chats the bot is in |
| `notify-hub init` | Creates the config file; leaves an existing one alone |

## Fewer interruptions, nothing lost

- **Write first, then send**: every message goes into `~/.notify-hub/outbox.db` and counts as done only once sent. Failures are retried after 1, 5, 15 and 30 minutes, then hourly; after a day it gives up, and `status` shows why.
- **Deduplication**: with `--key`, one key is pushed once per 24 hours; without it, the same source, title and body are pushed once per 10 minutes, so a script stuck in a loop cannot flood your phone.
- **Rate limit**: at most 20 pushes per source per hour; the rest goes to the digest.
- **Links only as buttons**: the body is plain text, and only an explicit `--link` becomes a button, labelled with its domain. Mail content can sway the summaries a model writes, so a phishing link cannot pose as a button.
- **No double sends**: each message is claimed in the database before it is sent, so two programs retrying at once never send it twice.

All the numbers can be changed in `.env`.

## Data and privacy

- The config and the outbox live in `~/.notify-hub/`, readable only by you. Secrets stay in `.env`: never in the repository, never in logs.
- Only the title, body and link the caller passes in are sent, and only to Lark.
- No open ports and no daemon: nothing on your Mac is exposed.

## Not done yet

`digest` messages and rate-limited messages are only stored for now; the next step adds scheduled digests, quiet hours at night, launchd jobs, a Claude Code hooks example, and switching the mail monitor over. See the [changelog](CHANGELOG_EN.md).

## Development

```bash
uv venv && uv pip install -e ".[dev]"
.venv/bin/python -m pytest -q
```

74 tests against a fake Lark API, no network. The design is in [docs/design_EN.md](docs/design_EN.md).
