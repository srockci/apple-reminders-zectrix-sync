"""Apple Reminders adapter using osascript."""
from __future__ import annotations
import logging
import subprocess
import time
from pathlib import Path

from ..models import AppleReminder

logger = logging.getLogger(__name__)

APPLE_LIST_SCRIPT = """
tell application "Reminders"
    set ns to {}
    repeat with L in every list
        set end of ns to name of L
    end repeat
end tell
return ns"""

APPLE_TASKS_SCRIPT = """
tell application "Reminders"
    try
        set L to first list whose name = "{list_name}"
        set cn to count of (reminders in L whose completed is false)
        if cn > 100 then
            return "{list_name}|OVER|100"
        end if
        set out to ""
        repeat with R in (reminders in L whose completed is false)
            set tn to name of R
            set td to ""
            set tp to 0
            set rid to id of R
            try
                set dd to due date of R
                if dd is not missing value then
                    set td to do shell script "date -j +'%Y-%m-%dT%H:%M' -f 'ns.Date' '" & dd as text & "'"
                end if
            end try
            try
                set tp to priority of R
            end try
            set out to out & rid & "|P|" & tn & "|P|" & td & "|P|" & tp & "|R|"
        end repeat
        return "{list_name}|SEP|" & out
    on error
        return ""
    end try
end tell"""


def _run_osascript(script: str, timeout: int = 20) -> str:
    proc = subprocess.Popen(
        ["osascript", "-e", script],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    stdout, stderr = proc.communicate(timeout=timeout)
    if proc.returncode != 0 and stderr:
        logger.warning("osascript rc=%d stderr=%s", proc.returncode, stderr[:200])
    return stdout


class AppleRemindersAdapter:
    def __init__(self):
        self._warmup_done = False

    def _ensure_warmup(self):
        if self._warmup_done:
            return
        logger.debug("Warming up Reminders app...")
        subprocess.run(["open", "-a", "Reminders"], capture_output=True, timeout=10)
        time.sleep(3)
        self._warmup_done = True

    def list_reminders(self) -> list[AppleReminder]:
        """Fetch all incomplete reminders from all lists."""
        self._ensure_warmup()

        list_out = _run_osascript(APPLE_LIST_SCRIPT, timeout=15)
        list_names = []
        if list_out.strip():
            try:
                list_names = json.loads(list_out)
            except Exception:
                list_names = [l.strip() for l in list_out.strip().split(",")]

        if not list_names:
            # fallback: try default list
            default_script = """\
tell application "Reminders"
    try
        set L to first list
        return name of L
    on error
        return ""
    end try
end tell"""
            default_name = _run_osascript(default_script, timeout=8).strip()
            if default_name:
                list_names = [default_name]

        reminders = []
        for lname in list_names:
            escaped = lname.replace("\\", "\\\\").replace('"', '\\"')
            script = APPLE_TASKS_SCRIPT.format(list_name=escaped)
            out = _run_osascript(script, timeout=20)
            if not out.strip():
                continue
            sep_idx = out.find("|SEP|")
            if sep_idx == -1:
                continue
            actual_list = out[:sep_idx]
            task_block = out[sep_idx + 5:]
            for token in task_block.split("|R|"):
                if not token.strip():
                    continue
                parts = token.split("|P|")
                if len(parts) < 2:
                    continue
                apple_id = parts[0]
                title = parts[1]
                due_date = parts[2] if len(parts) > 2 and parts[2] else None
                priority = int(parts[3]) if len(parts) > 3 and parts[3] else 0
                reminders.append(AppleReminder(
                    id=apple_id,
                    title=title,
                    due_date=due_date,
                    priority=priority,
                    completed=False,
                    list_name=actual_list,
                ))
        return reminders

    def create_reminder(self, title: str, due_date: str | None = None,
                        due_time: str | None = None, priority: int = 0,
                        list_name: str | None = None) -> AppleReminder:
        """Create a new reminder in Apple Reminders."""
        self._ensure_warmup()
        script = f"""\
tell application "Reminders"
    set targetList to first list
    if "{list_name or ''}" is not "" then
        try
            set targetList to first list whose name = "{list_name}"
        end try
    end if
    set newR to make new reminder in targetList with properties {{name:"{title}"}}
    return id of newR
end tell"""
        out = _run_osascript(script, timeout=15)
        apple_id = out.strip()
        return AppleReminder(id=apple_id, title=title, due_date=due_date,
                             due_time=due_time, priority=priority,
                             list_name=list_name or "Reminders")

    def complete_reminder(self, apple_id: str):
        """Mark a reminder as completed."""
        self._ensure_warmup()
        script = f"""\
tell application "Reminders"
    set R to reminder id "{apple_id}"
    set completed of R to true
end tell"""
        _run_osascript(script, timeout=10)

    def delete_reminder(self, apple_id: str):
        """Delete a reminder."""
        self._ensure_warmup()
        script = f"""\
tell application "Reminders"
    set R to reminder id "{apple_id}"
    delete R
end tell"""
        _run_osascript(script, timeout=10)