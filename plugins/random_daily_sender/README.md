# random_daily_sender

每天在指定时间窗口内随机发送消息。支持 24 小时间隔约束与状态持久化。
时间计算使用操作系统本地时区。

## 参数

- `--target` 目标（用户名或数字 ID）
- `--text` 发送内容
- `--window` 随机时间窗口，例如 `09:00-23:00`
- `--min-interval-hours` 最小间隔小时数，默认 24
- `--state` 状态文件路径（JSON）

## 作为任务使用（推荐）

```yaml
- trigger_time: "*/5 * * * *"
  action_type: plugin
  payload:
    plugin: "random_daily_sender"
    args: ["--target", "7672228046", "--text", "/sign", "--window", "09:00-23:00", "--min-interval-hours", "24", "--state", "data/sign.json"]
```

建议每 3-10 分钟运行一次，以便命中随机时间点。

## CLI 手动执行

```
tg-dog plugin random_daily_sender execute -- --target 7672228046 --text "/sign" --window 09:00-23:00
```
