# 插件目录

每个插件放在 `plugins/<name>/` 目录下，并包含 `plugin.py`。

## 插件接口

`plugin.py` 需要实现以下任一函数：

```python
async def run(context, args):
    ...
```

或：

```python
def main(context, args):
    ...
```

也可以提供 Typer 子命令（可选）：

```python
import typer

app = typer.Typer()
```

### context 结构

- `config`: 解析后的配置字典
- `profile_name`: 当前 profile 名
- `profile`: 当前 profile 配置
- `client`: Telethon 客户端实例
- `logger`: 日志对象
- `call`: 在 CLI 模式中执行协程的助手（`context["call"](coro)`）
- `session_dir`: session 目录

### args 结构

- 透传自命令行的参数列表（`List[str]`）

## 运行示例

```
tg-dog plugin echo -- foo bar
```

## 定时任务示例

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
