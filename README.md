# notify-hub

**中文** | [English](README_EN.md)

把通知推到手机上的 Lark。你电脑上的任何程序（邮件监控、实验脚本、Claude Code）想通知你，都调用同一个命令；Lark 的凭证、卡片的样子、连不上时的重试只写一次，每个程序不用各写一遍。

它只管「现在发出去」：调用一次发一次，连不上就当场重试几次，还发不出去就报错退出。什么时候发、夜里发不发、几条合成一张汇总、发不出去的怎么办，都由调用它的程序决定。

```
邮件监控 / 实验脚本 / Claude Code
        │  notify-hub send "标题" --level urgent --source mail
        ▼
notify-hub（被调用时才运行，发完就退出）
  1. 检查参数：标题、级别、链接
  2. 渲染成 Lark 卡片发出去
  3. 连不上或 Lark 一时出错：隔 2 秒、5 秒各重试一次
  4. 发出去了，退出码 0；还是不行，退出码 1，原因写在错误输出里
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

然后依次运行：

```bash
notify-hub init
notify-hub chats
notify-hub test
```

`init` 生成 `~/.notify-hub/.env`（只有你能读），在里面填上 App ID 和 App Secret；`chats` 列出机器人所在的群和 chat_id，把要推送的那个填进 `LARK_RECEIVE_ID`；`test` 发一条测试消息，手机上收到就通了。

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
| `--level` | `urgent`（红色卡片）或 `normal`（默认，蓝色卡片）。只决定卡片的颜色，两种都是马上发 |
| `--source` | 哪个程序发的，比如 `mail`、`timefence`，写在卡片底部 |
| `--link` | 卡片上加一个「打开」按钮，按钮上写着网站域名 |
| `--quiet` | 推送成功时不打印 |

| 退出码 | 意思 | 调用方可以怎么办 |
|---|---|---|
| 0 | 发出去了 | |
| 1 | 没发出去：配置不对、连不上、Lark 拒收。原因写在错误输出里 | 自己决定，比如邮件监控把这封邮件留到下一次汇总 |
| 2 | 参数写错了：级别不是 `urgent` 或 `normal`、链接不是 http(s) 网址、来源带空格 | 改调用的代码 |

连不上 Lark、Lark 返回 5xx 或 429 时，隔 2 秒、5 秒各再试一次，一共最多 3 次；凭证不对、没权限、收件方写错这类错误，重试也没用，直接退出。每个请求最多等 10 秒，所以发不出去时，命令可能要几十秒才返回。

Python 里直接调用：

```python
from notify_hub import ChannelError, notify

try:
    notify("TimeFence 跑完了", "IC 0.031", source="timefence")
except ChannelError as exc:
    print(f"没发出去：{exc}")
```

`notify()` 返回试了几次；参数写错时抛 `ValueError`。

## 时间由调用方决定

notify-hub 没有定时任务、免打扰和汇总，一被调用就发。「什么时候该打扰你」这类规则，放在最了解情况的程序里。比如 [邮件监控](https://github.com/yuhang2551/thunderbird-mail-agent/tree/main/monitor)：每小时检查一次邮件，要紧的马上推，其余的每天 8、12、18 点各合成一张汇总；夜里 23:00 到 8:00 只推紧急的；推不出去的，它自己留到下一次汇总。

notify-hub 也不存消息、不去重：同一件事推没推过，调用方自己记得（邮件监控按邮件记在自己的数据库里）。

## 从 0.2 升级

0.2 版自己有定时任务、免打扰、每日汇总和发件箱，0.3 起都去掉了，为什么见 [设计说明](docs/design.md)。0.3 里已经没有卸定时任务的命令，所以先用 0.2 把它卸掉，再升级：

```bash
notify-hub flush
notify-hub schedule uninstall
uv tool upgrade notify-hub
notify-hub version
notify-hub test
```

第一条把 0.2 发件箱里到时间该发的先发出去；`version` 应该显示 `notify-hub 0.3.0`。用过 `digest` 级别、想把还没汇总的也发掉，在第一条后面加一条 `notify-hub digest`。

- `.env` 里 0.2 的免打扰、汇总、定时任务、去重、限流配置项不再读，留着也没关系。
- `~/.notify-hub/outbox.db` 和 `~/.notify-hub/logs/` 不再用，想删就删。
- 调用时还传 `--key` 的，照样能用，只是不起作用。
- 不小心先升级了：定时任务还会每天叫三次已经没有的 `flush`，什么也不做。在终端里运行下面两条就卸掉了：

```bash
launchctl bootout gui/$(id -u)/com.notify-hub.flush
rm ~/Library/LaunchAgents/com.notify-hub.flush.plist
```

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

这两种提醒，Claude Code 只在你像是离开了终端时才发，人在电脑前不会被打扰。卡片标题是「项目文件夹 · Claude Code 等你确认」，正文是 Claude Code 的提示。`notify-hub claude-hook` 只试一次、不重试，退出码永远是 0：推送出了问题，也不会拖慢或打断 Claude Code。

用 `claude -p` 跑无人值守的长任务时，可以只给这一次运行加上 `Stop`：做完时推一条，正文是 Claude 最后一条回复的前 300 字。

```bash
claude -p "把这批实验跑完" --settings '{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"~/.local/bin/notify-hub claude-hook"}]}]}}'
```

不建议把 `Stop` 写进 `~/.claude/settings.json`：那样交互使用时，Claude 每回一轮就推一条。

## 其他命令

| 命令 | 作用 |
|---|---|
| `notify-hub test` | 发一条测试消息，检查配置通不通 |
| `notify-hub chats` | 列出机器人所在的群 |
| `notify-hub init` | 生成配置文件，已经有了就不动 |
| `notify-hub claude-hook` | 给 Claude Code 的 hooks 用，见上面 |
| `notify-hub version` | 看装的是哪个版本 |

## 安全和隐私

- 配置在 `~/.notify-hub/.env`，目录和文件只有你能读。秘密只放在这里，不进仓库、不打印出来。
- 不存消息：发完就退出，本机不留发过什么。
- 发出去的只有调用方传进来的标题、正文和链接，只发给 Lark。接 Claude Code 的 `Stop` 时，会带上 Claude 最后一条回复的前 300 字。
- 链接只走按钮：正文按纯文本显示，只有明确传的 `--link` 才变成按钮，按钮上写着网站域名。邮件之类的内容能影响模型写的摘要，这样钓鱼链接没法伪装成按钮。
- 卡片不会太大：正文最多 3000 字，远低于 Lark 卡片消息 30 KB 的上限。
- 不开任何端口，也不常驻，Mac 上没有东西对外暴露，也没有后台任务。

## 还没做

卡片上的双向按钮，比如点「已处理」传回原来的程序。见 [更新记录](CHANGELOG.md)。

## 开发

```bash
uv venv && uv pip install -e ".[dev]"
.venv/bin/python -m pytest -q
```

88 个测试，用假的 Lark 接口，不联网。设计说明见 [docs/design.md](docs/design.md)。
