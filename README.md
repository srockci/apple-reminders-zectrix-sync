# Apple Reminders ↔ Zectrix Sync

Bidirectional sync between Apple Reminders (macOS) and Zectrix todo cloud.

## Setup

```bash
cd apple-reminders-zectrix-sync
pip install -r requirements.txt
```

## Run

```bash
python3 app.py
```

GUI 窗口会打开，填入 API Key 后自动获取设备列表，可选择同步到哪些设备。

## UI 功能

- **同步页面**：查看同步状态、最近同步数量、手动触发同步或预览
- **设备页面**：填入 API Key → 自动获取设备列表 → 勾选要同步的目标设备
- **设置页面**：轮询间隔、后台轮询开关、数据目录

## Launch

```bash
cd apple-reminders-zectrix-sync

# GUI mode (macOS native Tkinter)
venv/bin/python3.9 app_gui.py

# 预览（dry-run，不实际修改）
python3 -m app.cli --config config.yaml --dry-run

# 后台轮询（每 5 分钟）
python3 -m app.cli --config config.yaml --daemon --interval 300
```

## 同步逻辑

- Apple 有，Zectrix 没有 → 新建到 Zectrix
- Zectrix 有，Apple 没有，之前同步过 → 删除 Zectrix（用户在 Apple 删了）
- Zectrix 有，Apple 没有，从未同步过 → 新建到 Apple Reminders（用户在 Zectrix 侧加了）
- 两边都有（标题相同）→ 跳过

同步记录存储在 `sync.db`（SQLite）。

## Crontab（每 5 分钟）

```crontab
*/5 * * * * /usr/local/bin/python3 -m app.cli --config /Users/srockci/projects/apple-reminders-zectrix-sync/config.yaml
```

## Requirements

- macOS（Apple Reminders 需要 osascript）
- Python 3.10+