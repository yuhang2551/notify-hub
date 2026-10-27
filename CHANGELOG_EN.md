# Changelog

[中文](CHANGELOG.md) | **English**

Recorded increment by increment: what each step added, how far it was verified, and what comes next.

## Next

1. Digests: `digest` messages and rate-limited ones are combined per source into one card at a set time each day (18:00 by default).
2. Quiet hours: `normal` messages that arrive during quiet hours (23:00 to 8:00 by default) wait and go out together in the morning; `urgent` ones are sent as usual.
3. launchd jobs (scheduled `flush` and digests) and a Claude Code hooks example (push to the phone when a task finishes or waits for you).
4. Switch the mail monitor to push through notify-hub and test it on the Mac.

## 2026-10-27 · Step one: sending, cards, outbox, deduplication and rate limits

- `notify-hub send`: title, body (optionally from stdin), three levels, source, a link button and a deduplication key. A failed push is not an error: the message stays in the outbox and the exit code is still 0.
- Lark app-bot channel: cards are colored by level (urgent red, normal blue, digest grey), the body is plain text, and links appear only as buttons labelled with their domain; the receiver type is worked out from the id's prefix. There is also a console channel that only prints.
- Outbox (SQLite): write first, then send; failures are retried after 1, 5, 15 and 30 minutes, then hourly, and dropped after a day; each message is claimed before sending, so two programs retrying at once never send it twice.
- Deduplication (one key per 24 hours, identical content per 10 minutes) and rate limits (20 per source per hour; the rest goes to the digest).
- `test`, `chats`, `status`, `flush` and `init`; `init --from` copies the Lark settings from the mail monitor's `.env` without the secrets passing through your hands.
- Python API: `from notify_hub import notify`.
- 74 tests against a fake Lark API, no network; GitHub Actions runs them on Linux (Python 3.10 and 3.13) and macOS (Python 3.13).
- Not yet run on a real machine: the card format still needs one check against real Lark (`notify-hub test`).
