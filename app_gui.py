"""Zectrix Sync — PySimpleGUI native macOS-style UI."""
import json
import logging
import sqlite3
import subprocess
import threading
import time
import uuid
from pathlib import Path

import PySimpleGUI as sg
import requests

APP_NAME     = "Zectrix Sync"
CONFIG_FILE  = Path(__file__).parent / "config.json"
ZECTRIX_BASE = "https://cloud.zectrix.com"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("zectrix-sync")


class State:
    api_key       = ""
    devices       = []
    poll_interval = 300
    daemon_mode   = False
    db_path       = str(Path(__file__).parent / "sync.db")
    stop_daemon   = threading.Event()
    daemon_thread = None


# ── Config ─────────────────────────────────────────────────────────
def load_config() -> dict:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}


def save_config_file(cfg: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


# ── Zectrix API ────────────────────────────────────────────────────
def zectrix_req(method, path, ak, did, **kw):
    url = f"{ZECTRIX_BASE}{path}"
    r = requests.request(method, url, headers={"X-API-Key": ak}, timeout=15, **kw)
    p = r.json()
    if p.get("code") != 0:
        raise RuntimeError(f"API {p.get('code')}: {p.get('msg')}")
    return p


# ── Apple Reminders ───────────────────────────────────────────────
def fetch_apple_reminders():
    subprocess.run(["open", "-a", "Reminders"], capture_output=True)
    time.sleep(2)

    def run(sc, timeout=20):
        p = subprocess.Popen(["osascript", "-e", sc], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return p.communicate(timeout=timeout)[0]

    list_sc = """\
tell application "Reminders"
    set ns to {}
    repeat with L in every list
        set end of ns to name of L
    end repeat
end tell
return ns"""
    out = run(list_sc, 15)
    try:
        names = json.loads(out)
    except Exception:
        names = [n.strip() for n in out.strip().split(",") if n.strip()]
    if not names:
        d = run("""\
tell application "Reminders"
    try set L to first list; return name of L
    on error; return ""
    end try
end tell""", 8).strip()
        if d:
            names = [d]

    task_sc = """\
tell application "Reminders"
    try
        set L to first list whose name = "{list_name}"
        set out to ""
        repeat with R in (reminders in L whose completed is false)
            set tn to name of R
            set td to ""
            try
                set dd to due date of R
                if dd is not missing value then
                    set td to do shell script "date -j +'%Y-%m-%dT%H:%M' -f 'ns.Date' '" & dd as text & "'"
                end if
            end try
            set tp to 0
            try set tp to priority of R end try
            set rid to id of R
            set out to out & rid & "|P|" & tn & "|P|" & td & "|P|" & tp & "|R|"
        end repeat
        return "{list_name}|SEP|" & out
    on error
        return ""
    end try
end tell"""

    reminders = []
    for lname in names:
        esc = lname.replace("\\", "\\\\").replace('"', '\\"')
        out = run(task_sc.format(list_name=esc), 20)
        if not out.strip():
            continue
        sep = out.find("|SEP|")
        if sep == -1:
            continue
        for tok in out[sep+5:].split("|R|"):
            if not tok.strip():
                continue
            parts = tok.split("|P|")
            if len(parts) < 2:
                continue
            reminders.append({
                "id": parts[0],
                "title": parts[1],
                "due_date": parts[2] if len(parts) > 2 and parts[2] else None,
                "priority": int(parts[3]) if len(parts) > 3 and parts[3] else 0,
                "completed": False,
                "list_name": lname,
            })
    return reminders


def create_apple_reminder(title):
    sc = f'tell application "Reminders" make new reminder in (first list) with properties {{name:"{title}"}} end tell'
    p = subprocess.Popen(["osascript", "-e", sc], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return p.communicate(timeout=15)[0].strip()


# ── Sync DB ──────────────────────────────────────────────────────
def get_sync_db(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.execute("""\
        CREATE TABLE IF NOT EXISTS sync_map (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL, source_id TEXT NOT NULL,
            dest_id TEXT NOT NULL, title TEXT NOT NULL,
            synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source, source_id))""")
    conn.commit()
    return conn


def map_upsert(conn, source, sid, did, title):
    conn.execute("""\
        INSERT INTO sync_map (uuid, source, source_id, dest_id, title, synced_at)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(source, source_id) DO UPDATE SET
            dest_id=excluded.dest_id, title=excluded.title, synced_at=CURRENT_TIMESTAMP
    """, (str(uuid.uuid4()), source, sid, str(did), title))
    conn.commit()


def map_del_src(conn, source, sid):
    conn.execute("DELETE FROM sync_map WHERE source=? AND source_id=?", (source, sid))
    conn.commit()


def map_del_dest(conn, did):
    conn.execute("DELETE FROM sync_map WHERE dest_id=?", (str(did),))
    conn.commit()


def map_all(conn, source):
    return conn.execute("SELECT * FROM sync_map WHERE source=?", (source,)).fetchall()


def map_get(conn, source, sid):
    return conn.execute("SELECT * FROM sync_map WHERE source=? AND source_id=?", (source, sid)).fetchone()


# ── Sync engine ───────────────────────────────────────────────────
def do_sync(win, dry_run=False):
    if not State.api_key:
        return "错误: 请先填入 API Key"

    devs = [k[4:] for k in win.key_dict if k.startswith("DEV_") and win[k].get()]
    if not devs:
        return "错误: 未选择任何设备"

    lines = []

    apple_items = []
    try:
        apple_items = fetch_apple_reminders()
    except Exception as e:
        lines.append(f"[Apple] 读取失败: {e}")

    db = get_sync_db(Path(State.db_path))
    apple_ids = {r["id"] for r in apple_items}

    # Apple -> Zectrix
    for r in apple_items:
        if not map_get(db, "apple", r["id"]):
            if dry_run:
                lines.append(f"[DRY] Apple→Zectrix: {r['title']}")
            else:
                for did in devs:
                    try:
                        resp = zectrix_req("POST", "/open/v1/todos", State.api_key, did,
                                          json={"title": r["title"], "deviceId": did,
                                                "dueDate": r["due_date"]})
                        zid = resp.get("data", {}).get("id")
                        map_upsert(db, "apple", r["id"], str(zid), r["title"])
                        lines.append(f"[+] Apple→Zectrix: {r['title']} → {did}")
                        break
                    except Exception as e:
                        lines.append(f"[!] {did}: {e}")

    for row in map_all(db, "apple"):
        if row[2] not in apple_ids:
            if dry_run:
                lines.append(f"[DRY] Zectrix删除(Apple已无): {row[3]}")
            else:
                for did in devs:
                    try:
                        zectrix_req("DELETE", f"/open/v1/todos/{row[3]}", State.api_key, did)
                        map_del_src(db, "apple", row[2])
                        lines.append(f"[-] Zectrix删除: {row[4]}")
                        break
                    except Exception:
                        pass

    # Zectrix -> Apple
    apple_titles = {r["title"] for r in apple_items}
    for did in devs:
        try:
            todos = zectrix_req("GET", "/open/v1/todos", State.api_key, did).get("data", [])
            zids = {str(t["id"]) for t in todos}
            for t in todos:
                existing = next((r for r in map_all(db, "zectrix") if r[3] == str(t["id"])), None)
                if not existing and t["title"] not in apple_titles:
                    if dry_run:
                        lines.append(f"[DRY] Zectrix→Apple: {t['title']}")
                    else:
                        try:
                            aid = create_apple_reminder(t["title"])
                            map_upsert(db, "zectrix", str(t["id"]), aid, t["title"])
                            lines.append(f"[+] Zectrix→Apple: {t['title']}")
                        except Exception as e:
                            lines.append(f"[!] Apple创建失败: {e}")
            for row in map_all(db, "zectrix"):
                if row[3] not in zids:
                    if dry_run:
                        lines.append(f"[DRY] Apple删除(Zectrix已无): {row[2]}")
                    else:
                        try:
                            sc = f'tell application "Reminders" delete reminder id "{row[2]}" end tell'
                            subprocess.run(["osascript", "-e", sc], capture_output=True, timeout=10)
                            map_del_dest(db, row[3])
                            lines.append(f"[-] Apple删除: {row[4]}")
                        except Exception:
                            pass
        except Exception as e:
            lines.append(f"[!] 读取Zectrix {did}: {e}")

    db.close()
    return "\n".join(lines) if lines else "无变化"


# ── UI ────────────────────────────────────────────────────────────
def make_layout():
    # Helper
    F = lambda txt, **kw: sg.Text(txt, font=("SF Mono", 11), **kw)
    FI = lambda k, sz=40, **kw: sg.Input(key=k, size=(sz, 1), font=("SF Mono", 11), **kw)
    B = lambda txt, k, sz=None, **kw: sg.Button(txt, key=k, size=sz, **kw)

    # ── Sync tab ──
    sync_tab = [
        [sg.Frame("统计", [
            [F("Apple Reminders", text_color="#888"), sg.Text("—", key="-ACOUNT-", font=("SF Mono", 11, "bold"))],
            [F("Zectrix 待办", text_color="#888"),     sg.Text("—", key="-ZCOUNT-", font=("SF Mono", 11, "bold"))],
            [F("上次同步", text_color="#888"),         sg.Text("—", key="-LASTSYNC-", font=("SF Mono", 10))],
        ], pad=(5, 5))],
        [sg.Frame("日志", [
            [sg.Multiline("", key="-LOG-", size=(52, 9),
                          font=("SF Mono", 9), background_color="#0d1117",
                          text_color="#8b949e", autoscroll=True,
                          no_scrollbar=True, disabled=True)],
        ], pad=(5, 5))],
        [B("立即同步", "-SYNCNOW-", (13, 1)),
         B("  预览  ", "-DRYRUN-",  (10, 1)),
         sg.Push(),
         B("保存设置", "-SAVE-",    (10, 1))],
    ]

    # ── Devices tab ──
    devices_tab = [
        [sg.Frame("API 连接", [
            [F("API Key", text_color="#888")],
            [FI("-APIKEY-", 40, password_char="*")],
            [B("测试",    "-TESTAPI-", (10, 1)),
             B("获取设备", "-GETDEVS-", (10, 1))],
            [sg.Text("", key="-APIERROR-", text_color="#f85149", font=("SF Mono", 10))],
        ], pad=(5, 5))],
        [sg.Frame("设备列表（勾选同步目标）", [
            [sg.Text("点击「获取设备」加载列表", key="-DEVLIST-", font=("SF Mono", 10), text_color="#484f58")],
            [sg.Column([], key="-DEVROWS-")],
        ], pad=(5, 5))],
    ]

    # ── Settings tab ──
    settings_tab = [
        [sg.Frame("同步设置", [
            [F("轮询间隔（秒）"), FI("-INTERVAL-", 10)],
            [sg.Checkbox("开启后台轮询", key="-DAEMONCB-", default=State.daemon_mode, font=("SF Mono", 11))],
        ], pad=(5, 5))],
        [sg.Frame("数据", [
            [F("数据库", text_color="#888")],
            [FI("-DBPATH-", 40, readonly=True)],
        ], pad=(5, 5))],
    ]

    # ── Main layout ──
    return [
        [F("● 未连接", key="-STATUS-"),
         sg.Push(),
         F("轮询: 关", key="-DAEMONLBL-", text_color="#888")],

        [sg.TabGroup([
            [sg.Tab("同步",     sync_tab,     key="-SYNCTAB-")],
            [sg.Tab("设备",     devices_tab,  key="-DEVICETAB-")],
            [sg.Tab("设置",     settings_tab, key="-SETTINGSTAB-")],
        ], key="-TAB-", tab_background_color="#161b22",
           selected_title_color="#58a6ff")],

        [sg.Sizegrip()],
    ]


def main():
    sg.theme("DarkBlue14")
    win = sg.Window(APP_NAME, make_layout(), size=(460, 600), resizable=False, finalize=True)

    # Load config
    cfg = load_config()
    if cfg:
        win["-APIKEY-"].update(cfg.get("api_key", ""))
        win["-INTERVAL-"].update(str(cfg.get("poll_interval", 300)))
        win["-DAEMONCB-"].update(bool(cfg.get("daemon")))
        win["-DBPATH-"].update(cfg.get("db_path", State.db_path))
        State.api_key       = cfg.get("api_key", "")
        State.poll_interval = cfg.get("poll_interval", 300)
        State.daemon_mode   = bool(cfg.get("daemon"))
        if cfg.get("api_key"):
            win["-STATUS-"].update("● 已载入配置", text_color="#3fb950")

    while True:
        ev, vals = win.read(timeout=100)

        if ev in (sg.WIN_CLOSED, "Exit"):
            State.stop_daemon.set()
            if State.daemon_thread:
                State.daemon_thread.join(timeout=2)
            break

        if ev == "-TESTAPI-":
            key = vals["-APIKEY-"].strip()
            if not key:
                win["-APIERROR-"].update("请输入 API Key")
                continue
            win["-APIERROR-"].update("")
            win["-STATUS-"].update("● 测试中...")
            try:
                resp = zectrix_req("GET", "/open/v1/devices", key, "dummy")
                State.api_key = key
                State.devices = resp.get("data", [])
                win["-STATUS-"].update(f"● 已连接 ({len(State.devices)} 台)", text_color="#3fb950")
                win["-LOG-"].update(f"[INFO] API 连接成功，找到 {len(State.devices)} 台设备\n")
            except Exception as e:
                win["-STATUS-"].update("● 连接失败", text_color="#f85149")
                win["-APIERROR-"].update(str(e)[:80])

        if ev == "-GETDEVS-":
            if not State.api_key:
                win["-LOG-"].update("[ERROR] 请先测试 API 连接\n")
                continue
            devs_text = "\n".join(
                f"  • {d.get('deviceName', d['deviceId'])}  ({d['deviceId']})"
                for d in State.devices
            )
            win["-DEVLIST-"].update(devs_text if devs_text else "未找到设备")
            rows = [[sg.Checkbox("", key=f"DEV_{d['deviceId']}", default=True, pad=(0, 0)),
                     sg.Text(d.get("deviceName", d["deviceId"]), font=("SF Mono", 11)),
                     sg.Text(d["deviceId"], font=("SF Mono", 9), text_color="#888")]
                    for d in State.devices]
            win["-DEVROWS-"].update(rows)
            win["-LOG-"].update(win["-LOG-"].get() + f"\n已加载 {len(State.devices)} 个设备，请勾选同步目标")

        if ev == "-SYNCNOW-":
            if not State.api_key:
                win["-LOG-"].update("[ERROR] 请先填入 API Key\n")
                continue
            win["-LOG-"].update("")
            msg = do_sync(win, dry_run=False)
            win["-LOG-"].update(msg)
            win["-LASTSYNC-"].update(time.strftime("%Y-%m-%d %H:%M:%S"))
            win["-LOG-"].set_vscroll_position(1.0)

        if ev == "-DRYRUN-":
            if not State.api_key:
                win["-LOG-"].update("[ERROR] 请先填入 API Key\n")
                continue
            win["-LOG-"].update(win["-LOG-"].get() + "\n[DRY-RUN] 预览...\n")
            msg = do_sync(win, dry_run=True)
            win["-LOG-"].update(win["-LOG-"].get() + msg + "\n")
            win["-LOG-"].set_vscroll_position(1.0)

        if ev == "-SAVE-":
            State.poll_interval = int(vals["-INTERVAL-"]) or 300
            State.daemon_mode   = bool(vals["-DAEMONCB-"])
            selected = [k[4:] for k in win.key_dict if k.startswith("DEV_") and win[k].get()]
            save_config_file({
                "api_key":       State.api_key,
                "devices":       selected,
                "poll_interval": State.poll_interval,
                "daemon":        State.daemon_mode,
                "db_path":       State.db_path,
            })
            win["-LOG-"].update(win["-LOG-"].get() + "\n[INFO] 设置已保存\n")

            if State.daemon_mode and not (State.daemon_thread and State.daemon_thread.is_alive()):
                State.stop_daemon = threading.Event()
                State.daemon_thread = threading.Thread(
                    target=lambda: (
                        [time.sleep(State.poll_interval) or
                         win["-LOG-"].update(win["-LOG-"].get() + f"\n[轮询] {do_sync(win)}") or
                         win["-LOG-"].set_vscroll_position(1.0)
                         for _ in iter(bool, True)]
                        if State.stop_daemon.wait(State.poll_interval) is False else None
                    ),
                    daemon=True,
                )
                State.daemon_thread.start()
                win["-DAEMONLBL-"].update("轮询: 开", text_color="#3fb950")

    win.close()


if __name__ == "__main__":
    main()