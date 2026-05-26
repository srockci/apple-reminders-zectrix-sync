"""
Data models for apple-reminders-zectrix-sync.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class AppleReminder:
    id: str           # Apple's UUID
    title: str
    due_date: Optional[str] = None   # YYYY-MM-DD
    due_time: Optional[str] = None   # HH:MM
    priority: int = 0
    completed: bool = False
    list_name: str = "Unknown"
    # filled by sync engine
    zectrix_id: Optional[int] = None
    is_synced: bool = False


@dataclass
class ZectrixTodo:
    id: int
    title: str
    due_date: Optional[str] = None
    due_time: Optional[str] = None
    priority: int = 0
    completed: bool = False
    device_id: Optional[str] = None
    create_date: Optional[str] = None
    # filled by sync engine
    apple_id: Optional[str] = None
    is_synced: bool = False


@dataclass
class SyncRecord:
    id: int
    uuid: str
    source: str          # 'apple' | 'zectrix'
    source_id: str
    dest_id: str
    title: str
    created_at: datetime
    synced_at: datetime


@dataclass
class SyncDelta:
    """What changed in one sync run."""
    apple_created: list[AppleReminder] = field(default_factory=list)
    apple_deleted: list[str] = field(default_factory=list)    # apple IDs
    zectrix_created: list[ZectrixTodo] = field(default_factory=list)
    zectrix_deleted: list[int] = field(default_factory=list)   # zectrix todo IDs
    apple_completed: list[str] = field(default_factory=list)   # apple IDs marked done
    zectrix_completed: list[int] = field(default_factory=list) # zectrix IDs marked done

    @property
    def has_changes(self) -> bool:
        return bool(
            self.apple_created or self.apple_deleted or
            self.zectrix_created or self.zectrix_deleted or
            self.apple_completed or self.zectrix_completed
        )