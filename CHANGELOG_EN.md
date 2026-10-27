# Changelog

[中文](CHANGELOG.md) | **English**

Recorded increment by increment: what each step added, how far it was verified, and what comes next.

## Next

1. Check step two on the Mac: install the scheduled job and see how the combined cards (dividers, several buttons) look in Lark.
2. Switch the mail monitor to push through notify-hub and test it on the Mac (its own PR in the thunderbird-mail-agent repository).
3. Later: two-way buttons on cards (tap "Done" or "Remind me later" and the answer goes back to the program that sent it).

## 2026-10-27 · Step two: quiet hours, daily digest, scheduled job, Claude Code

- Quiet hours (23:00–08:00 by default): `normal` messages wait, and when quiet hours end they arrive as one card, "免打扰期间收到 N 条通知" (N notifications during quiet hours), each with its title, the start of its body, its source, its time and its button. `urgent` messages are sent as usual.
- Daily digest (18:00 by default): `digest` messages and rate-limited ones are combined per source into one grey card. If the digest time falls within quiet hours, it waits until they end; if the computer slept through the digest time, the digest goes out after it wakes; it is never sent twice on one day. `notify-hub digest` sends it now and `--preview` only prints it in the terminal.
- A combined card is itself a message in the outbox, queued, claimed and retried like any other. Combining happens inside one write-locked transaction, so two runs at once still make only one card.
- `notify-hub schedule install` installs a launchd job that runs `flush` every 10 minutes, `uninstall` removes it, and with no argument it shows the status and the log; on other systems it prints the cron line instead. `flush --quiet` writes to the log only when something happened.
- `notify-hub claude-hook` plugs into Claude Code hooks: a push when Claude Code waits for your approval or for your reply while you are away, and one when an unattended run finishes (`Stop`). It always exits 0.
- A card that would be too big lists fewer entries and says how many more there are, so it stays under Lark's 30 KB limit; the request is encoded as UTF-8 directly, so Chinese text is not escaped into something longer.
- The outbox gained two columns (`kind`, `bundle_id`) and a `meta` table; a database from step one is upgraded when opened, and existing messages are left as they are.
- 127 tests (53 new). The tests pin the time zone and the clock, so they give the same result when run at night; GitHub Actions still runs them on Linux and macOS.
- Not yet checked on a real machine: how the combined cards look in Lark, and the launchd job actually running on the Mac.

## 2026-10-27 · Step one: sending, cards, outbox, deduplication and rate limits

- `notify-hub send`: title, body (optionally from stdin), three levels, source, a link button and a deduplication key. A failed push is not an error: the message stays in the outbox and the exit code is still 0.
- Lark app-bot channel: cards are colored by level (urgent red, normal blue, digest grey), the body is plain text, and links appear only as buttons labelled with their domain; the receiver type is worked out from the id's prefix. There is also a console channel that only prints.
- Outbox (SQLite): write first, then send; failures are retried after 1, 5, 15 and 30 minutes, then hourly, and dropped after a day; each message is claimed before sending, so two programs retrying at once never send it twice.
- Deduplication (one key per 24 hours, identical content per 10 minutes) and rate limits (20 per source per hour; the rest goes to the digest).
- `test`, `chats`, `status`, `flush` and `init`; `init --from` copies the Lark settings from the mail monitor's `.env` without the secrets passing through your hands.
- Python API: `from notify_hub import notify`.
- 74 tests against a fake Lark API, no network; GitHub Actions runs them on Linux (Python 3.10 and 3.13) and macOS (Python 3.13).
- Checked on a real machine (2026-10-27): installed on the Mac with uv, `init --from` copied the mail monitor's Lark settings, and the `notify-hub test` card reached the 「通知」 chat in Lark.
