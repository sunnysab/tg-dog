# vmomo_music

用于 @VmomoVBot 搜索歌曲并下载。

## 用法（命令行）

```
tg-dog plugin vmomo_music search -- --query "歌名" --choice 1
```

预览候选列表（不下载）：

```
tg-dog plugin vmomo_music search -- --query "歌名" --list-only
```

参数说明：

- `--query` 搜索关键字（歌名）
- `--target` 机器人目标（默认 @VmomoVBot）
- `--choice` 候选项序号（从 1 开始）
- `--keyword` 候选按钮文字包含关键词时自动选中
- `--timeout` 等待回复超时（秒）
- `--max-wait` 等待媒体消息的轮次
- `--max-pages` 自动翻页最大页数（默认 5）
- `--list-only` 仅列出候选项，不下载
- `--output` 下载目录
- `--filename` 指定保存文件名（可选）

## 代码调用

```
tg-dog plugin vmomo_music -- --query "歌名"
```

插件会：
1) 发送搜索词
2) 读取候选按钮
3) 自动翻页查找目标项（若需要）
4) 点击目标项
5) 收到媒体后下载到指定目录

注意：机器人回复格式如有变化，可能需要调整插件逻辑。
