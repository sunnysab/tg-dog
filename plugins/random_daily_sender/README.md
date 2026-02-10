# random_daily_sender

Daily sign/check-in sender with a day plan model.

## Behavior

- On the first run each day, it generates a **daily plan** for all known accounts in the state file.
- The plan contains when each account should send today.
- Later runs only read state and decide whether to wait, send, retry, or skip.
- Plan generation respects both:
  - time window (`--window`)
  - minimum interval (`--min-interval-hours`)

## Arguments

- `--target` target username or numeric ID
- `--text` message to send
- `--window` daily window, e.g. `09:00-23:00`
- `--min-interval-hours` minimum interval between successful sends
- `--expect-text` expected full response text (optional)
- `--expect-keyword` expected keyword in response (optional)
- `--expect-timeout` response timeout seconds
- `--state` state file path (YAML/JSON)

## Retry

- Flood wait is always retried automatically.
- Expectation failure / timeout / send error is retried within the same day window.
- Retries are limited per day to avoid endless loops.

## Scheduler recommendation

```yaml
- trigger_time: "*/5 * * * *"
  action_type: plugin
  payload:
    plugin: "random_daily_sender"
    args: ["--target", "7672228046", "--text", "/sign", "--window", "09:00-23:00", "--min-interval-hours", "24", "--expect-keyword", "成功", "--expect-timeout", "10", "--state", "data/state.yaml"]
```

The plugin can wait for a near plan time in-process, so actual send time is no longer strictly snapped to cron ticks.

## CLI example

```
tg-dog plugin random_daily_sender execute -- --target 7672228046 --text "/sign" --window 09:00-23:00 --state data/state.yaml
```
