# Design

[中文](design.md) | **English**

A one-page design written on 2026-10-27 and rewritten on 2026-10-28, when notify-hub became a pure push tool (0.3). The [changelog](../CHANGELOG_EN.md) is the record of what is done and what is not.

## The problem

The mail monitor pushes to the phone, finished experiments push, and Claude Code waiting for you could push too. If every program writes its own Lark push, Lark credentials end up in several places, and every program draws its cards and handles errors its own way.

notify-hub pulls the "send it to Lark" layer out. A program only says what happened, how urgent it is and who is saying it; notify-hub turns that into a card and sends it to your phone right away.

## It sends; it does not keep time

In 0.2, notify-hub also kept time: an outbox, quiet hours, a daily digest and a scheduled job that ran three times a day. The mail monitor had its own scheduled job and digest as well, so there were two timetables: mail digests at 09:00 and 18:00, notify-hub's job at 08:00, 12:00 and 18:00, and night-time notifications held a second time inside notify-hub. Working out when a notification would arrive meant reading both sets of settings together.

From 0.3 the split is:

| | Responsible for |
|---|---|
| notify-hub | Sending now; retrying a couple of times on the spot; telling the caller when that fails |
| The caller (the mail monitor, say) | When to check, when to send, whether to send at night, what to combine into a digest, what to do with a failed push |

The timing rules live with the caller because only the caller knows whether a notification is worth waking you up for or can wait for the digest. A push tool does not know who sent a mail; it could only apply one blanket rule per level.

How 0.2's outbox, quiet hours and digest worked is in the [0.2.1 design notes](https://github.com/yuhang2551/notify-hub/blob/e0ff774/docs/design_EN.md).

## How one message travels

```
a program calls notify-hub send (or notify() in Python)
  │
  ├─ bad arguments (a level other than urgent or normal, a link that is not http/https, a source with spaces) → error, exit code 2
  ├─ bad config (no App ID, an unknown channel) → error, exit code 1
  │
  └─ rendered as a Lark card and sent
        ├─ success → exit code 0
        ├─ Lark unreachable, or a 5xx or 429 from Lark → try again after 2 s, then after 5 s
        │     └─ all three attempts fail → exit code 1, with the reason on stderr
        └─ any other error (wrong credentials, a missing permission, a wrong receiver) → no retry, exit code 1
```

The key decisions:

| Decision | Why |
|---|---|
| Store nothing; exit once sent | The caller knows best what to do with a failed push: the mail monitor keeps the mail for its next digest, an experiment script may just log a line. A second copy inside notify-hub would mean a second retry timetable |
| A failed push exits 1 | The caller has to know a push failed to handle it. 0.2 exited 0 here because it retried on its own |
| Only two retries on the spot (after 2 s and 5 s) | A network blip or an occasional 5xx from Lark is usually gone a few seconds later; a longer outage is the caller's business, and the caller is not kept waiting. The cost: if a request did reach Lark and only the reply was lost, the retry sends a second card. That is rare, and one card too many beats one too few |
| Only temporary errors are retried | Wrong credentials, a missing permission or a wrong receiver stay wrong however often you try; failing at once saves time |
| The two levels only set the card colour | Urgent is red, normal is blue. The caller decides when to send; the level no longer decides whether to send |
| No deduplication | The caller remembers whether it already pushed something (the mail monitor records it per mail in its own database). 0.2's `--key` is still accepted and ignored, so old callers do not break |
| The Claude Code hook tries once | Claude Code waits while a hook runs, so it must not wait for retries; the exit code is always 0, so it never interrupts Claude Code |
| Plain-text body, links only as buttons | Mail content can sway the summaries a model writes; the button shows the domain, so a phishing link cannot pose as a button |
| The body is capped at 3,000 characters | A Chinese character takes 3 bytes, so this stays far below Lark's 30 KB limit for card messages; the request is encoded as UTF-8 directly, so Chinese text is not escaped into something longer |
| No daemon, no open port, no background job | It runs only when called; nothing on the Mac is exposed |
| Command line first, Python second | Any language, shell script or Claude Code hook can call it; the mail monitor calls the command too, so the two projects install separately and do not depend on each other |

## Two levels

| Level | Card | Examples |
|---|---|---|
| urgent | Red, with a red button | Mail from an advisor or an interviewer, a service is down |
| normal | Blue | An experiment finished, a new job match, a mail digest |

## Configuration

`~/.notify-hub/.env`; the folder and its files are readable only by you. It holds only the channel and the Lark app bot (`LARK_APP_ID`, `LARK_APP_SECRET`, `LARK_RECEIVE_ID`), the same bot the mail monitor uses, and `notify-hub init --from ~/.mail-monitor/.env` copies it over. The receiver type comes from the id's prefix (`oc_` a chat, `ou_` a person), so there is nothing else to fill in. 0.2's settings can stay in the file; they are no longer read.

## Later

- **Two-way buttons**: tap "Done" or "Remind me later" on a card and the answer goes back to the program that sent it. Lark's long-connection mode needs no public URL, and card button callbacks arrive over the same connection (see the [Hermes Agent Lark setup guide](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/feishu)); the cost is that notify-hub would have to keep running.
- A local HTTP endpoint, routing sources to different chats, channels other than Lark.

## Why not an existing tool

Libraries such as Apprise can send a message to dozens of services, and ntfy and Bark need their own app. Here only one channel is needed, a Lark app bot, plus cards and a few retries; a small tool of a few hundred lines covers that, every line of it is easy to follow, and the Lark credentials live in one place.
