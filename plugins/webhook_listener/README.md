# webhook_listener

监听指定聊天的新消息并调用 webhook。

## 参数

- `--target` 目标聊天（用户名或数字 ID）
- `--url` webhook 地址
- `--method` HTTP 方法（默认 POST）
- `--timeout` 超时时间（秒）
- `--retry` 失败重试次数（默认 2）
- `--retry-delay` 初始重试间隔秒数（默认 1.0，指数退避）
- `--header` 额外 HTTP 头（可重复，格式 `Key: Value`）

## 配置示例（daemon listeners）

```yaml
listeners:
  - profile: work_account
    plugin: "webhook_listener"
    args: ["--target", "-1001472283197", "--url", "https://example.com/webhook"]
```

默认 payload 为 JSON：

```json
{
  "chat_id": 123,
  "message_id": 456,
  "text": "hello",
  "date": "2026-01-01T12:00:00+08:00",
  "sender_id": 789
}
```
