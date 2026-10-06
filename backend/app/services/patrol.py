"""巡视检查业务规则：状态流转、字段校验、筛选口径，以及清洗完成联动的巡视待办。"""
from __future__ import annotations

from typing import Any

from app import persistence as repo
from app.store import store

MODULE = "patrol"
REQUIRED_FIELDS = ["记录编号", "巡视区域", "巡视日期"]
STATUS_ORDER = ["待巡视", "巡视中", "已记录", "已归档"]
ACTION_RULES = {"开始巡视": "巡视中", "提交记录": "已记录", "归档记录": "已归档"}
NEGATIVE_ACTIONS = []


def _match(row: dict[str, Any], *, keyword: str | None, status: str | None) -> bool:
    if keyword and keyword not in str(row.get("记录编号", "")):
        return False
    if status and row.get("status") != status:
        return False
    return True


class PatrolService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        own_rows = [
            row for row in store.rows(MODULE)
            if _match(row, keyword=keyword, status=status)
        ]
        # 清洗完成联动产生的巡视待办一并计入（状态为待巡视）。
        followup_rows = [
            row for row in repo.list_followups()
            if _match(row, keyword=keyword, status=status)
        ]
        rows = followup_rows + own_rows
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        if entry_id < 0:
            return next(
                (row for row in repo.list_followups() if int(row["id"]) == entry_id),
                None,
            )
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        if entry_id < 0:
            return None, "清洗联动待办由组件清洗任务驱动，请在清洗任务退回执行后再处理"
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"巡视记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于巡视检查可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"巡视记录已{action}"
