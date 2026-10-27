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
  3. quiet hours: normal messages wait overnight and arrive as one card in the morning;
     low-priority ones are combined into a daily digest at 18:00
  4. renders a Lark card and sends it; failures stay in the outbox and are retried
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
| `--level` | `urgent` (red card, also at night), `normal` (default, blue; waits during quiet hours), `digest` (goes into the daily digest) |
| `--source` | Which program sent it, such as `mail` or `timefence`; used for grouping and rate limits |
| `--link` | Adds an "Open" button to the card, labelled with the site's domain |
| `--key` | For deduplication: one source and one key are pushed once per 24 hours |
| `--quiet` | Print nothing when the push succeeds |

A failed push is not an error: the message stays in the outbox and is retried later, and the exit code is still 0, so the calling program never stops because a push failed. Only bad arguments exit with 2.

From Python:

```python
from notify_hub import notify

result = notify("TimeFence finished", "IC 0.031", source="timefence")
print(result.status)  # sent, queued (not sent yet, will retry), held (quiet hours), digest or skipped (duplicate)
```

## Quiet hours and the daily digest

| Level | Normally | During quiet hours (23:00–08:00 by default) |
|---|---|---|
| `urgent` | Sent at once, red card | Still sent at once |
| `normal` | Sent at once, blue card | Waits; when quiet hours end, everything that waited arrives as one card, "免打扰期间收到 N 条通知" (N notifications during quiet hours), each with its title, the start of its body and its button |
| `digest` | Kept, and combined per source into one grey daily digest at 18:00 | Also kept; if the digest time falls within quiet hours, the digest waits until they end |

Rate-limited messages also go into the daily digest. Times follow this computer's time zone and can be changed in `.env`: `NOTIFY_HUB_QUIET_HOURS=23:00-08:00` (`off` turns it off) and `NOTIFY_HUB_DIGEST_TIME=18:00` (`off` means no automatic digest).

Something has to wake notify-hub up now and then to send those cards. The easiest way is the scheduled job:

```bash
notify-hub schedule install     # runs notify-hub flush every 10 minutes; on macOS through launchd, under your own user
notify-hub schedule             # whether it is installed, plus the last lines of its log
notify-hub schedule uninstall   # removes it; the config and the outbox stay
```

It does not run while the computer sleeps and catches up when it wakes: sleep through 18:00 and the day's digest goes out after you wake it. You can skip the job, too: every successful `notify-hub send` does the same catching up, only perhaps later. To see the digest right away, `notify-hub digest --preview` prints it in the terminal and `notify-hub digest` sends it now.

## Claude Code

Get a push on your phone when Claude Code waits for your approval, or when it finished answering and you have not replied for a minute. Add this to `~/.claude/settings.json` (if the file already has other settings, merge the `hooks` part in):

```json
{
  "hooks": {
    "Notification": [
      {
        "matcher": "permission_prompt|idle_prompt",
        "hooks": [{ "type": "command", "command": "~/.local/bin/notify-hub claude-hook" }]
      }
    ]
  }
}
```

Claude Code sends these two notifications only when you seem to be away from the terminal, so nothing buzzes while you sit in front of it. The card title reads "project folder · Claude Code 等你确认" (waiting for your approval) and the body is Claude Code's prompt. `notify-hub claude-hook` always exits 0, so a failed push never interrupts Claude Code.

For a long unattended run with `claude -p`, you can add `Stop` to that one run: one push when it finishes, with the first 300 characters of Claude's last reply.

```bash
claude -p "finish this batch of experiments" --settings '{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"~/.local/bin/notify-hub claude-hook"}]}]}}'
```

Putting `Stop` in `~/.claude/settings.json` is not recommended: in interactive use you would get a push after every reply.

## Other commands

| Command | What it does |
|---|---|
| `notify-hub status` | Shows the configuration and the outbox: quiet hours and digest settings, how much was sent, what is stuck, the latest errors |
| `notify-hub flush` | Catches up on whatever is due: the card after quiet hours, the daily digest, retries, giving up after a day; this is what the scheduled job runs |
| `notify-hub digest` | Sends the daily digest now; `--preview` only prints it in the terminal |
| `notify-hub schedule` | Shows, installs (`install`) or removes (`uninstall`) the scheduled job |
| `notify-hub claude-hook` | For Claude Code hooks, see above |
| `notify-hub test` | Sends one test message directly, bypassing the outbox |
| `notify-hub chats` | Lists the chats the bot is in |
| `notify-hub init` | Creates the config file; leaves an existing one alone |

## Fewer interruptions, nothing lost

- **Write first, then send**: every message goes into `~/.notify-hub/outbox.db` and counts as done only once sent. Failures are retried after 1, 5, 15 and 30 minutes, then hourly; after a day it gives up, and `status` shows why.
- **Deduplication**: with `--key`, one key is pushed once per 24 hours; without it, the same source, title and body are pushed once per 10 minutes, so a script stuck in a loop cannot flood your phone.
- **Rate limit**: at most 20 pushes per source per hour; the rest goes to the digest.
- **Links only as buttons**: the body is plain text, and only an explicit `--link` becomes a button, labelled with its domain. Mail content can sway the summaries a model writes, so a phishing link cannot pose as a button.
- **No double sends**: each message is claimed in the database before it is sent, so two programs retrying at once never send it twice. Combining messages into a card happens inside one write-locked transaction, so two runs at once still make only one card.
- **Combined cards are not lost either**: each one is itself a message in the outbox, queued and retried like any other.
- **Cards stay small enough**: a card lists a limited number of entries; when there is too much, it lists fewer and says how many more there are, so it stays under Lark's size limit.

All the numbers can be changed in `.env`.

## Data and privacy

- The config and the outbox live in `~/.notify-hub/`, readable only by you. Secrets stay in `.env`: never in the repository, never in logs.
- Only the title, body and link the caller passes in are sent, and only to Lark. With the Claude Code `Stop` hook, that includes the first 300 characters of Claude's last reply.
- No open ports and no daemon: nothing on your Mac is exposed.

## Not done yet

Switching the mail monitor over to notify-hub (the next step), and two-way buttons on cards, such as tapping "Done" to tell the program that sent it. See the [changelog](CHANGELOG_EN.md).

## Development

```bash
uv venv && uv pip install -e ".[dev]"
.venv/bin/python -m pytest -q
```

127 tests against a fake Lark API and a fake clock, no network. The design is in [docs/design_EN.md](docs/design_EN.md).
