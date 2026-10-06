"""组件清洗业务规则：组合筛选、状态流转、用水汇总与巡视联动口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app import persistence as repo
from app.persistence import STATUS_DONE, STATUS_ORDER, STATUS_PLANNED, STATUS_RUNNING

# 计划、执行中、已完成三态推进；已完成的再执行退回到执行中。
ACTION_RULES = {
    "开始执行": STATUS_RUNNING,
    "执行": STATUS_RUNNING,
    "验收完成": STATUS_DONE,
    "完成": STATUS_DONE,
}

REQUIRED_FIELDS = ["任务编号", "清洗区域", "清洗方式"]


def _validate_range(date_from: str | None, date_to: str | None) -> str | None:
    if date_from and date_to and date_from > date_to:
        return "计划日期起止范围不正确，开始日期不能晚于结束日期"
    return None


class CleaningService:
    def list_entries(
        self,
        *,
        area: str | None = None,
        method: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        return repo.list_tasks(
            area=area, method=method, date_from=date_from, date_to=date_to,
            keyword=keyword, status=status, page=page, size=size,
        )

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return repo.get_task(entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str], bool]:
        missing = [
            field for field in REQUIRED_FIELDS
            if not str(values.get(field) or "").strip()
        ]
        if missing:
            return None, missing, False
        task_no = str(values["任务编号"]).strip()
        # 同一任务重复提交（任务编号相同）直接返回原任务，不产生第二条。
        existing = repo.get_task_by_no(task_no)
        if existing is not None:
            return existing, [], True
        return repo.create_task(values), [], False

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        if action not in ACTION_RULES:
            entry = repo.get_task(entry_id)
            if entry is None:
                return None, f"清洗任务 {entry_id} 不存在或已归档"
            return None, f"动作「{action}」不属于组件清洗可执行范围"
        return repo.set_task_status(entry_id, ACTION_RULES[action])

    def water_summary(
        self,
        *,
        area: str | None = None,
        method: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        keyword: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """用水汇总与列表走同一筛选口径，保证两页数字对得上。"""
        rows = repo.all_tasks(
            area=area, method=method, date_from=date_from, date_to=date_to,
            keyword=keyword, status=status,
        )
        by_area: dict[str, dict[str, float]] = {}
        total_water = 0.0
        for row in rows:
            water = float(row.get("用水吨数") or 0.0)
            total_water += water
            bucket = by_area.setdefault(row["清洗区域"], {"water": 0.0, "tasks": 0})
            bucket["water"] += water
            bucket["tasks"] += 1
        areas = [
            {"清洗区域": name, "用水吨数": round(item["water"], 2), "任务数": int(item["tasks"])}
            for name, item in sorted(by_area.items(), key=lambda kv: kv[0])
        ]
        status_counts = {name: 0 for name in STATUS_ORDER}
        for row in rows:
            status_counts[str(row.get("status"))] = status_counts.get(str(row.get("status")), 0) + 1
        return {
            "total_tasks": len(rows),
            "total_water": round(total_water, 2),
            "areas": areas,
            "status_counts": {
                STATUS_PLANNED: status_counts.get(STATUS_PLANNED, 0),
                STATUS_RUNNING: status_counts.get(STATUS_RUNNING, 0),
                STATUS_DONE: status_counts.get(STATUS_DONE, 0),
            },
        }

    def options(self) -> dict[str, list[str]]:
        return repo.list_options()

    @staticmethod
    def validate_range(date_from: str | None, date_to: str | None) -> str | None:
        return _validate_range(date_from, date_to)
