# tg-dog

一个基于 Telethon 的 Telegram Userbot CLI。采用分层架构（交互层 / 业务逻辑层 / 协议层），并通过 APScheduler 在异步事件循环中执行定时任务。

## 目录结构

```
.
├── main.py
├── config.yaml
├── core/
│   ├── actions.py
│   ├── client_manager.py
│   ├── config.py
│   └── scheduler.py
├── sessions/
├── downloads/
├── logs/
└── pyproject.toml
```

## 环境准备（使用 .venv）

```
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

## 配置文件说明（config.yaml）

- `api_id` / `api_hash`：全局 API 配置（所有账号复用）
- `proxy`：可选的代理 URL（如 `http://127.0.0.1:8080` 或 `socks5://127.0.0.1:1080`，不支持认证）
- `profiles`：多账号配置，每个键为别名，仅需填写手机号
- `tasks`：定时任务列表，使用 Cron 表达式

示例：

```yaml
api_id: 123456
api_hash: "shared_api_hash"
proxy: "http://127.0.0.1:8080"

profiles:
  work_account:
    phone_number: "+10000000000"

# default_profile: work_account

tasks:
  - profile: work_account
    trigger_time: "*/5 * * * *"
    action_type: send_msg
    target: "@channel_or_user"
    payload:
      text: "Scheduled hello"
```

## 常用命令

1) 账号登录（生成 session）

```
python main.py auth --profile work_account
```

2) 单次发送消息

```
python main.py run --action send --target @username --text "hello"
```
或：
```
tg-dog send --target @username --text "hello"
```

3) 发送并等待回复（conversation）

```
python main.py run --action interactive_send --target @username --text "ping" --timeout 30
```

4) 下载媒体（支持类型和大小过滤）

```
python main.py run --action download --target @chat --limit 5 --media-type photo --max-size 5242880
```

5) 拉取历史消息

```
python main.py list-msgs --target @channel --limit 10
```

如果是私有群组/频道，建议先用 `list-dialogs` 获取 `target`：

```
tg-dog list-dialogs --limit 50
```
输出里会包含 `target=-100xxxxxxxxxx` 的可直接使用值。

新增：导出消息到 Markdown（带附件目录）

```
tg-dog export --target @channel --output exports --mode single
tg-dog export --target @channel --mode per_message --attachments-dir exports/attachments
tg-dog export --target @channel --message-id 123 --message-id 456
tg-dog export --target @channel --from-user @someone --limit 100
```

说明：
- `--mode single`：全部输出到单个 Markdown 文件
- `--mode per_message`：每条消息一个 Markdown 文件
- `--attachments-dir`：附件目录（图片/视频等）
- `--from-user`：只导出指定发送者的消息
- `--message-id`：导出指定消息

6) 守护进程模式（定时任务）

```
python main.py daemon --config config.yaml --log-file logs/daemon.log
```

> 默认情况下，`run/list/plugin` 会优先尝试连接正在运行的 daemon，复用已登录账号。  
> 如果不想使用 daemon，可加 `--no-daemon`。

## 插件机制

- 插件放在 `plugins/<name>/plugin.py`
- 必须实现 `run(context, args)` 或 `main(context, args)`
- 可选提供 `app = typer.Typer()` 或 `build_cli()` 以支持子命令
- 命令行透传参数可使用 `--` 分隔
- 插件 CLI 中如需调用异步 Telethon，请使用 `context["call"](coro)` 执行协程
- 业务插件模板见 `plugins/business_template`

运行插件示例：

```
tg-dog plugin echo -- foo bar
```

列出插件：

```
tg-dog list-plugins
```

定时任务调用插件（示例）：

```yaml
tasks:
  - profile: work_account
    trigger_time: "*/5 * * * *"
    action_type: plugin
    target: "@unused"
    payload:
      plugin: "echo"
      args: ["foo", "bar"]
      # mode: cli  # 可选：用 Typer 子命令方式执行
```

## 设计要点

- Telethon `conversation` 实现“发送并等待回复”并带超时保护
- FloodWaitError 自动等待并重试，避免触发限流后崩溃
- 定时任务基于 APScheduler 的 AsyncIOScheduler
- 守护进程输出重定向到日志文件，支持 SIGINT/SIGTERM 优雅退出

## 注意事项

- `sessions/` 目录下保存 `.session` 文件，建议不要纳入版本控制
- `downloads/` 和 `logs/` 目录默认仅用于运行时输出
- 运行前请先在 Telegram 开发者后台获取 `api_id` 与 `api_hash`
