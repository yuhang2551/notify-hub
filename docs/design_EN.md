# Design

[中文](design.md) | **English**

A one-page design written on 2026-10-27 and updated to match step one as built. The [changelog](../CHANGELOG_EN.md) is the record of what is done and what is not.

## The problem

The mail monitor pushes to the phone, finished experiments push, failing scheduled jobs push, and Claude Code waiting for you could push too. If every program writes its own Lark push, each ends up with its own retries, deduplication and quiet hours, the rules drift apart, and Lark credentials end up in several places.

notify-hub pulls that layer out. A program only says what happened, how urgent it is and who is saying it; notify-hub decides how, when and whether to push.

## How one message travels

```
a program calls notify-hub send (or notify() in Python)
  │
  ├─ bad arguments (unknown level, a link that is not http/https) → error, exit code 2
  │
  ├─ dedup: the same key within 24 hours, or the same content within 10 minutes → recorded as skipped, not sent
  ├─ digest level → stored as digest for the digest
  ├─ this source already pushed 20 in the last hour → stored as digest (rate limit)
  │
  └─ written to the outbox (pending) → claimed (sending) → sent as a Lark card
        ├─ success → sent; also delivers earlier failures whose retry time has come
        └─ failure → back to pending, retried after 1, 5, 15, 30 minutes, then hourly; failed after a day
```

The key decisions:

| Decision | Why |
|---|---|
| Write to the outbox before sending (the outbox pattern) | Offline, a Lark error or a crash loses nothing; `flush` picks up where it stopped |
| A failed push still exits 0 | The caller (the mail monitor, say) should not stop its own work because a push failed |
| Claim before sending | Two programs retrying at once never send the same message twice; a claim with no result after 5 minutes is treated as a crashed process |
| Stop retrying once Lark is unreachable | Each message should not wait out its own timeout |
| Dedup keys are scoped by source | Two programs that happen to use the same key do not interfere |
| Plain-text body, links only as buttons | Mail content can sway the summaries a model writes; the button shows the domain, so a phishing link cannot pose as a button |
| No daemon, no open port | It runs only when called; retries and digests are left to launchd. Nothing on the Mac is exposed |
| Command line first, Python second | Any language, shell script, scheduled job or Claude Code hook can call it; the mail monitor calls the command too, so the two projects install separately and do not depend on each other |

## Three levels

| Level | When it reaches the phone | Card color | Examples |
|---|---|---|---|
| urgent | At once, also at night | Red | Mail from an advisor or an interviewer, a service is down |
| normal | At once; during quiet hours it waits and goes out with the others in the morning (next step) | Blue | An experiment finished, a new job match |
| digest | Collected, combined per source once a day (next step) | Grey | Newsletters, daily stats |

## Outbox states

| State | Meaning |
|---|---|
| pending | Waiting to be sent: new, or waiting for its next retry |
| sending | A process is sending it |
| sent | Delivered |
| digest | Kept for the digest (digest level, or rate-limited) |
| skipped | A duplicate, not sent |
| failed | Retried for more than a day and dropped |

## Configuration

`~/.notify-hub/.env`; the folder and its files are readable only by you. Lark goes through an app bot (`LARK_APP_ID`, `LARK_APP_SECRET`, `LARK_RECEIVE_ID`), the same one the mail monitor uses, and `notify-hub init --from ~/.mail-monitor/.env` copies it over. The receiver type comes from the id's prefix (`oc_` a chat, `ou_` a person), so there is nothing else to fill in.

## Later

- **Two-way buttons**: tap "Done" or "Remind me later" on a card and the answer goes back to the program that sent it. Lark's long-connection mode needs no public URL, and card button callbacks arrive over the same connection (see the [Hermes Agent Lark setup guide](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/feishu)); the cost is that notify-hub would have to keep running.
- A local HTTP endpoint, routing sources to different chats, muting a source for a while, channels other than Lark.

## Why not an existing tool

Libraries such as Apprise can send a message to dozens of services, but they only send; ntfy and Bark need their own app. If you already live in Lark, what is missing is the layer of levels, deduplication, rate limits, retries and digests. That layer is also a set of standard engineering problems: the outbox pattern, idempotent deduplication, rate limiting and backoff retries.
