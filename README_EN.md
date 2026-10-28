# notify-hub

[中文](README.md) | **English**

Pushes notifications to Lark on your phone. Any program on your computer (a mail monitor, an experiment script, Claude Code) calls the same command when it wants to tell you something. The Lark credentials, the look of the cards and the retries when Lark is unreachable are written once instead of in every program.

It only "sends now": one call, one push. If Lark cannot be reached it retries a couple of times on the spot, and if the push still fails it exits with an error. When to send, whether to send at night, which notifications to combine into a digest and what to do with a failed push are all up to the program that calls it.

```
mail monitor / experiment scripts / Claude Code
        │  notify-hub send "title" --level urgent --source mail
        ▼
notify-hub (runs only when called, exits when done)
  1. checks the arguments: title, level, link
  2. renders a Lark card and sends it
  3. Lark unreachable or briefly failing: retries after 2 s and again after 5 s
  4. sent: exit code 0; still failing: exit code 1, with the reason on stderr
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

Then run, in order:

```bash
notify-hub init
notify-hub chats
notify-hub test
```

`init` creates `~/.notify-hub/.env` (readable only by you); fill in the App ID and App Secret there. `chats` lists the chats the bot is in with their chat_id; put the one you want in `LARK_RECEIVE_ID`. `test` sends a test message; when it reaches your phone, you are done.

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
| `--level` | `urgent` (red card) or `normal` (default, blue card). It only sets the colour; both are sent at once |
| `--source` | Which program sent it, such as `mail` or `timefence`; shown at the bottom of the card |
| `--link` | Adds an "Open" button to the card, labelled with the site's domain |
| `--quiet` | Print nothing when the push succeeds |

| Exit code | Meaning | What the caller can do |
|---|---|---|
| 0 | Sent | |
| 1 | Not sent: bad config, Lark unreachable or the message refused. The reason is on stderr | Its own call; the mail monitor, for example, keeps that mail for its next digest |
| 2 | Bad arguments: a level other than `urgent` or `normal`, a link that is not an http(s) URL, a source with spaces | Fix the calling code |

When Lark cannot be reached or answers with a 5xx or 429, notify-hub tries again after 2 seconds and again after 5, at most 3 attempts in all. Errors that a retry cannot fix, such as wrong credentials, a missing permission or a wrong receiver, exit at once. Each request waits at most 10 seconds, so a failing push can take a few tens of seconds to return.

From Python:

```python
from notify_hub import ChannelError, notify

try:
    notify("TimeFence finished", "IC 0.031", source="timefence")
except ChannelError as exc:
    print(f"not sent: {exc}")
```

`notify()` returns the number of attempts it took; bad arguments raise `ValueError`.

## The caller decides when

notify-hub has no schedule, no quiet hours and no digest: it sends the moment it is called. Rules about when it is worth disturbing you belong in the program that knows the situation best. The [mail monitor](https://github.com/yuhang2551/thunderbird-mail-agent/tree/main/monitor), for example, checks mail once an hour, pushes what matters at once and combines the rest into digests at 08:00, 12:00 and 18:00; between 23:00 and 08:00 it pushes only urgent mail; and it keeps any mail it failed to push for its next digest.

notify-hub stores no messages and does no deduplication either: the caller remembers what it has already pushed (the mail monitor keeps that per mail in its own database).

## Upgrading from 0.2

Version 0.2 had its own scheduled job, quiet hours, daily digest and outbox; 0.3 drops all of them, and the [design notes](docs/design_EN.md) explain why. 0.3 no longer has a command to remove the scheduled job, so remove it with 0.2 first, then upgrade:

```bash
notify-hub flush
notify-hub schedule uninstall
uv tool upgrade notify-hub
notify-hub version
notify-hub test
```

The first command sends whatever is due in the 0.2 outbox; `version` should print `notify-hub 0.3.0`. If you used the `digest` level and want the messages still waiting for a digest sent too, add `notify-hub digest` after the first command.

- 0.2's quiet hours, digest, schedule, deduplication and rate-limit settings in `.env` are no longer read; leaving them there does no harm.
- `~/.notify-hub/outbox.db` and `~/.notify-hub/logs/` are no longer used; delete them if you like.
- Callers that still pass `--key` keep working; the option is simply ignored.
- Upgraded first by mistake? The scheduled job then calls the missing `flush` three times a day and does nothing. These two commands in a terminal remove it:

```bash
launchctl bootout gui/$(id -u)/com.notify-hub.flush
rm ~/Library/LaunchAgents/com.notify-hub.flush.plist
```

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

Claude Code sends these two notifications only when you seem to be away from the terminal, so nothing buzzes while you sit in front of it. The card title reads "project folder · Claude Code 等你确认" (waiting for your approval) and the body is Claude Code's prompt. `notify-hub claude-hook` makes a single attempt with no retries and always exits 0, so a failed push never slows down or interrupts Claude Code.

For a long unattended run with `claude -p`, you can add `Stop` to that one run: one push when it finishes, with the first 300 characters of Claude's last reply.

```bash
claude -p "finish this batch of experiments" --settings '{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"~/.local/bin/notify-hub claude-hook"}]}]}}'
```

Putting `Stop` in `~/.claude/settings.json` is not recommended: in interactive use you would get a push after every reply.

## Other commands

| Command | What it does |
|---|---|
| `notify-hub test` | Sends a test message to check the configuration |
| `notify-hub chats` | Lists the chats the bot is in |
| `notify-hub init` | Creates the config file; leaves an existing one alone |
| `notify-hub claude-hook` | For Claude Code hooks, see above |
| `notify-hub version` | Shows which version is installed |

## Security and privacy

- The config lives in `~/.notify-hub/.env`; the folder and the file are readable only by you. Secrets stay there: never in the repository, never printed.
- No messages are stored: notify-hub exits once it has sent, and keeps no record on your computer of what it sent.
- Only the title, body and link the caller passes in are sent, and only to Lark. With the Claude Code `Stop` hook, that includes the first 300 characters of Claude's last reply.
- Links only as buttons: the body is plain text, and only an explicit `--link` becomes a button, labelled with its domain. Mail content can sway the summaries a model writes, so a phishing link cannot pose as a button.
- Cards stay small: the body is capped at 3,000 characters, far below Lark's 30 KB limit for card messages.
- No open ports, no daemon and no background job: nothing on your Mac is exposed.

## Not done yet

Two-way buttons on cards, such as tapping "Done" to tell the program that sent it. See the [changelog](CHANGELOG_EN.md).

## Development

```bash
uv venv && uv pip install -e ".[dev]"
.venv/bin/python -m pytest -q
```

88 tests against a fake Lark API, no network. The design is in [docs/design_EN.md](docs/design_EN.md).
