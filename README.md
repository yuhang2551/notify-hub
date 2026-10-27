# notify-hub

**中文** | [English](README_EN.md)

本机通知网关。你电脑上的任何程序（邮件监控、实验脚本、定时任务、Claude Code）想通知你，都调用同一个命令，由它推到手机上的 Lark。分级、去重、限流、失败重发这些规则只写一次，每个程序不用各写一遍。

```
邮件监控 / 实验脚本 / 定时任务 / Claude Code
        │  notify-hub send "标题" --level urgent --source mail
        ▼
notify-hub（被调用时才运行，不常驻）
  1. 先写进发件箱（SQLite），断网、程序崩了都不丢
  2. 去重、限流：同一件事只推一次，某个程序刷屏就改进汇总
  3. 夜里免打扰：普通消息先存着，早上合成一张卡；不急的每天 18:00 合成一张汇总
  4. 渲染成 Lark 卡片发出去，失败的留在发件箱定时重发
        │
        ▼
Lark 应用机器人 → 你的手机
```

## 安装

需要 Python 3.10 以上。推荐用 [uv](https://docs.astral.sh/uv/) 装到自己的用户目录，不要管理员密码：

```bash
uv tool install git+https://github.com/yuhang2551/notify-hub
```

命令装在 `~/.local/bin/notify-hub`。终端里找不到 `notify-hub` 的话，用完整路径，或者把 `~/.local/bin` 加进 PATH。

## 配置

需要一个 Lark（或飞书）应用机器人：

1. [Lark 开发者后台](https://open.larksuite.com/app)（飞书是 open.feishu.cn）→ 创建企业自建应用，比如叫「通知助手」。
2. 添加应用能力 → 机器人。
3. 权限管理里开 `im:message:send_as_bot`（以应用身份发消息）和 `im:chat:readonly`（查机器人在哪些群）。
4. 版本管理与发布 → 创建版本并发布，可用范围包括你自己。
5. 在 Lark 里建一个群（只有你自己也行），群设置 → 群机器人 → 添加这个应用的机器人。

然后：

```bash
notify-hub init          # 生成 ~/.notify-hub/.env（只有你能读），填上 App ID 和 App Secret
notify-hub chats         # 列出机器人所在的群和 chat_id，填进 LARK_RECEIVE_ID
notify-hub test          # 发一条测试消息，手机上收到就通了
```

已经给 [邮件监控](https://github.com/yuhang2551/thunderbird-mail-agent/tree/main/monitor) 配过 Lark 的话，一步复制过来，秘密不用经过你的手：

```bash
notify-hub init --from ~/.mail-monitor/.env
notify-hub test
```

全部配置项见 [env.example](notify_hub/env.example)。`LARK_RECEIVE_ID` 填群 id（`oc_` 开头）就推到群里，填你的 open_id（`ou_` 开头）就私聊你，类型不用另外填。

## 用法

```bash
notify-hub send "TimeFence 跑完了" --body "IC 0.031，用时 42 分钟" --source timefence
notify-hub send "新岗位匹配 82 分" --source job --link "https://example.com/jobs/123"
echo "磁盘只剩 2GB" | notify-hub send "备份失败" --level urgent --source backup --body -
```

| 参数 | 作用 |
|---|---|
| 标题 | 必填，一行 |
| `--body` | 正文；写 `-` 就从标准输入读 |
| `--level` | `urgent`（红色卡片，夜里也发）、`normal`（默认，蓝色，免打扰时段先存着）、`digest`（进每日汇总） |
| `--source` | 哪个程序发的，比如 `mail`、`timefence`；用来分组和限流 |
| `--link` | 卡片上加一个「打开」按钮，按钮上写着网站域名 |
| `--key` | 去重用：同一个来源、同一个 key，24 小时内只推一次 |
| `--quiet` | 推送成功时不打印 |

推送失败不算出错：消息留在发件箱里，之后自动重发，命令的退出码仍然是 0，调用它的程序不会因为推送失败而中断。只有参数写错时退出码是 2。

Python 里直接调用：

```python
from notify_hub import notify

result = notify("TimeFence 跑完了", "IC 0.031", source="timefence")
print(result.status)  # sent、queued（没发出去，等重发）、held（免打扰时段，等结束）、digest 或 skipped（重复）
```

## 免打扰和每日汇总

| 级别 | 平时 | 免打扰时段（默认 23:00–08:00） |
|---|---|---|
| `urgent` | 马上发，红色卡片 | 照样马上发 |
| `normal` | 马上发，蓝色卡片 | 先存着，时段结束后合成一张「免打扰期间收到 N 条通知」，每条带标题、正文开头和按钮 |
| `digest` | 存着，每天 18:00 按来源合成一张灰色的「每日汇总」 | 也存着；汇总时间落在免打扰时段里，就等时段结束再发 |

被限流的消息也进每日汇总。时间按这台电脑的时区算，都能在 `.env` 里改：`NOTIFY_HUB_QUIET_HOURS=23:00-08:00`（写 `off` 关掉），`NOTIFY_HUB_DIGEST_TIME=18:00`（写 `off` 不自动发）。

合成卡片和到点发汇总，要有人定时叫一下 notify-hub。最省事的是装上定时任务：

```bash
notify-hub schedule install     # 每天 08:00、12:00、18:00 各跑一次 notify-hub flush；macOS 用 launchd，装在你自己的用户下
notify-hub schedule             # 看装没装、装的是什么时间、最近几行日志
notify-hub schedule uninstall   # 卸掉，配置和发件箱都还在
```

08:00 免打扰结束，把夜里攒下的合成一张卡发出去；18:00 发每日汇总；中午那次补发之前没发出去的。平常的通知来了就发，不等定时任务。时间能在 `.env` 里改，比如 `NOTIFY_HUB_SCHEDULE_TIMES=08:00,18:00`，改完再运行一次 `notify-hub schedule install`。改了免打扰或汇总的时间，也把新的时间写进去；`schedule install` 发现对不上会提醒。

电脑睡着错过了，醒来后补跑一次：睡过了 18:00，醒来就发这一天的汇总；关机错过了，开机登录后补跑。不装也行，任何一次 `notify-hub send` 发成功后都会顺手做这些，只是可能晚一些。想马上看汇总：`notify-hub digest --preview` 只在终端里看，`notify-hub digest` 现在就发。

## 接上 Claude Code

Claude Code 等你确认，或者回完话你一分钟没理它时，推到手机。在 `~/.claude/settings.json` 里加上（文件里已经有别的设置的话，把 `hooks` 这一段合并进去）：

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

这两种提醒，Claude Code 只在你像是离开了终端时才发，人在电脑前不会被打扰。卡片标题是「项目文件夹 · Claude Code 等你确认」，正文是 Claude Code 的提示。`notify-hub claude-hook` 的退出码永远是 0，推送出了问题也不会打断 Claude Code。

用 `claude -p` 跑无人值守的长任务时，可以只给这一次运行加上 `Stop`：做完时推一条，正文是 Claude 最后一条回复的前 300 字。

```bash
claude -p "把这批实验跑完" --settings '{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"~/.local/bin/notify-hub claude-hook"}]}]}}'
```

不建议把 `Stop` 写进 `~/.claude/settings.json`：那样交互使用时，Claude 每回一轮就推一条。

## 其他命令

| 命令 | 作用 |
|---|---|
| `notify-hub status` | 看配置和发件箱：免打扰和汇总的设置、发了多少、有没有卡住的、最近的错误 |
| `notify-hub flush` | 补上到时间该做的事：免打扰结束后合成卡片、到点发汇总、重发失败的、放弃重试超过一天的；定时任务跑的就是它 |
| `notify-hub digest` | 现在就发每日汇总；加 `--preview` 只在终端里看 |
| `notify-hub schedule` | 查看、装上（`install`）、卸掉（`uninstall`）定时任务 |
| `notify-hub claude-hook` | 给 Claude Code 的 hooks 用，见上面 |
| `notify-hub test` | 不经过发件箱，直接发一条测试消息 |
| `notify-hub chats` | 列出机器人所在的群 |
| `notify-hub init` | 生成配置文件，已经有了就不动 |

## 少打扰，也不漏

- **先落盘再发**：每条先写进 `~/.notify-hub/outbox.db`，发成功才算完。失败的过 1、5、15、30 分钟再试，之后每小时一次，一天还发不出去就放弃，`status` 里看得到原因。
- **去重**：给了 `--key` 的，同一个 key 24 小时内只推一次；没给的，同一来源、同样的标题和正文 10 分钟内只推一次，防止脚本出 bug 循环刷屏。
- **限流**：同一来源一小时最多推 20 条，超出的进汇总。
- **链接只走按钮**：正文按纯文本显示，只有明确传的 `--link` 才变成按钮，按钮上写着网站域名。邮件之类的内容能影响模型写的摘要，这样钓鱼链接没法伪装成按钮。
- **同时调用也不重复**：每条消息发之前先在数据库里认领，两个程序同时补发也不会把一条发两次。合成卡片在一个写锁事务里做，同时跑也只合出一张。
- **合成的卡片也不会丢**：它本身就是发件箱里的一条消息，和普通消息一样排队、失败重发。
- **卡片不会太大**：一张卡片列的条数有上限，内容太多就少列几条，写上「还有 N 条」，保证不超过 Lark 的大小限制。

这些数字都能在 `.env` 里改。

## 数据和隐私

- 配置和发件箱都在 `~/.notify-hub/`，目录和文件只有你能读。秘密只放在 `.env` 里，不进仓库、不写进日志。
- 发出去的只有调用方传进来的标题、正文和链接，只发给 Lark。接 Claude Code 的 `Stop` 时，会带上 Claude 最后一条回复的前 300 字。
- 不开任何端口，也不常驻，Mac 上没有东西对外暴露。

## 还没做

邮件监控改成通过它推送（下一段）；卡片上的双向按钮，比如点「已处理」传回原来的程序。见 [更新记录](CHANGELOG.md)。

## 开发

```bash
uv venv && uv pip install -e ".[dev]"
.venv/bin/python -m pytest -q
```

127 个测试，用假的 Lark 接口和假的时钟，不联网。设计说明见 [docs/design.md](docs/design.md)。
