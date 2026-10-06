"""巡视检查业务规则：记录落库，清洗验收后自动登记的待办也在这里体现。"""
from __future__ import annotations

from typing import Any

from app import db

MODULE = "patrol"
REQUIRED_FIELDS = ["记录编号", "巡视区域"]
STATUS_ORDER = ["待巡视", "巡视中", "已记录", "已归档"]
ACTION_RULES = {"开始巡视": "巡视中", "提交记录": "已记录", "归档记录": "已归档"}
ABNORMAL_ACTIONS = {"开始巡视"}


class PatrolService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        source: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        return db.query_patrol(keyword=keyword, status=status, source=source, page=page, size=size)

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return db.find_patrol(entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        return db.insert_patrol(values), []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = db.find_patrol(entry_id)
        if entry is None:
            return None, f"巡视记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于巡视检查可执行范围"
        target = ACTION_RULES[action]
        if entry["status"] == target:
            return None, "记录已处于该状态，请勿重复提交"
        entry = db.update_patrol_status(entry_id, target, abnormal=action in ABNORMAL_ACTIONS)
        return entry, f"巡视记录已{action}"
