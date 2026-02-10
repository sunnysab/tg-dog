# random_daily_sender

用于每日签到/打卡消息的随机化调度发送插件（基于日计划模型）。

## 行为说明

- 每天首次运行时，会为状态文件中的所有账号生成当日计划。
- 计划会记录每个账号“今天应该在何时发送”。
- 后续运行根据状态决定：等待、发送、重试或跳过。
- 计划生成同时受以下约束：
  - 时间窗口（`--window`）
  - 最小发送间隔（`--min-interval-hours`）

## 参数说明

- `--target`：目标用户名或数字 ID（必填）
- `--text`：发送文本（必填）
- `--window`：每日时间窗口，格式如 `09:00-23:00`（默认 `09:00-23:00`）
- `--min-interval-hours`：两次成功发送的最小间隔小时数（默认 `24`）
- `--expect-text`：期望的完整回复文本（可选）
- `--expect-keyword`：期望回复中包含的关键词（可选）
- `--expect-timeout`：等待回复超时秒数（默认 `10`）
- `--state`：状态文件路径（支持 YAML/JSON，默认 `data/state.yaml`）

## 重试策略

- 遇到 FloodWait 会自动等待并重试。
- 期望校验失败 / 超时 / 发送异常会在当日窗口内继续重试。
- 每日重试次数有上限，避免无限循环。

## 调度建议

```yaml
- trigger_time: "*/5 * * * *"
  action_type: plugin
  payload:
    plugin: "random_daily_sender"
    args: ["--target", "7672228046", "--text", "/sign", "--window", "09:00-23:00", "--min-interval-hours", "24", "--expect-keyword", "成功", "--expect-timeout", "10", "--state", "data/state.yaml"]
```

插件在计划时间接近时可以进程内等待，因此实际发送时间不再严格对齐 cron 刻度。

## CLI 示例

```bash
tg-dog plugin random_daily_sender execute -- --target 7672228046 --text "/sign" --window 09:00-23:00 --state data/state.yaml
```
