# Apple Reminders ↔ Zectrix Sync

Bidirectional sync between Apple Reminders (macOS) and Zectrix todo cloud.

## Setup

```bash
cd apple-reminders-zectrix-sync
pip install -r requirements.txt
```

## Configuration

Edit `config.yaml`:

```yaml
name: apple-reminders-zectrix-sync
version: 1.0.0

config:
  - name: zectrix_api_key
    type: string
    required: true
  - name: zectrix_device_id
    type: string
    required: true
  - name: zectrix_base_url
    type: string
    default: https://cloud.zectrix.com
  - name: poll_interval
    type: integer
    default: 300
  - name: db_path
    type: string
    default: ./sync.db
```

## Run

```bash
# Single sync
python3 -m app.cli --config config.yaml

# Preview (dry-run, no changes)
python3 -m app.cli --config config.yaml --dry-run

# Daemon mode (poll every 300s)
python3 -m app.cli --config config.yaml --daemon --interval 300
```

## Crontab (every 5 minutes)

```crontab
*/5 * * * * /usr/local/bin/python3 -m app.cli --config /Users/srockci/projects/apple-reminders-zectrix-sync/config.yaml
```

## Sync Logic

- Apple 有，Zectrix 没有 → 新建到 Zectrix
- Zectrix 有，Apple 没有，之前同步过 → 删除 Zectrix 那一端（用户在另一侧删了）
- Zectrix 有，Apple 没有，从未同步过 → 新建到 Apple Reminders（用户在 Zectrix 侧加了）
- 两边都有（标题相同）→ 跳过

Sync records are stored in `sync.db` (SQLite) to track which items came from which side.

## Requirements

- macOS (Apple Reminders access requires osascript)
- Python 3.10+