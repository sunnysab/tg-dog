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

- `profiles`：多账号配置，每个键为别名
- `tasks`：定时任务列表，使用 Cron 表达式

示例：

```yaml
profiles:
  work_account:
    api_id: 123456
    api_hash: "your_api_hash"
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

6) 守护进程模式（定时任务）

```
python main.py daemon --config config.yaml --log-file logs/daemon.log
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
