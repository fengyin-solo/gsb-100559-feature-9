"""组件清洗业务规则：组合检索、三态流转、用水汇总与巡视待办联动。

列表与用水汇总都通过同一个过滤函数取数，统计口径只有一份，保证数字对得上。
"""
from __future__ import annotations

from typing import Any

from app import db
from app.db import (
    CLEANING_STATUS_DOING,
    CLEANING_STATUS_DONE,
    CLEANING_STATUS_PLAN,
)

MODULE = "cleaning"
REQUIRED_FIELDS = ["任务编号", "清洗区域", "清洗方式", "计划日期"]
STATUS_ORDER = [CLEANING_STATUS_PLAN, CLEANING_STATUS_DOING, CLEANING_STATUS_DONE]

# 动作沿状态序列依次推进；已完成再次点「执行」退回执行中。
ACTION_START = "开始作业"
ACTION_FINISH = "验收完成"
ACTION_ROLLBACK = "退回执行"
ACTION_RULES = {
    ACTION_START: CLEANING_STATUS_DOING,
    ACTION_FINISH: CLEANING_STATUS_DONE,
    ACTION_ROLLBACK: CLEANING_STATUS_DOING,
}


class CleaningService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        area: str | None = None,
        method: str | None = None,
        plan_date_from: str | None = None,
        plan_date_to: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        return db.query_cleaning(
            keyword=keyword, area=area, method=method,
            plan_date_from=plan_date_from, plan_date_to=plan_date_to,
            status=status, page=page, size=size,
        )

    def water_summary(
        self,
        *,
        keyword: str | None = None,
        area: str | None = None,
        method: str | None = None,
        plan_date_from: str | None = None,
        plan_date_to: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """按清洗区域汇总用水吨数；与列表走同一份筛选口径。"""
        return db.water_summary(
            keyword=keyword, area=area, method=method,
            plan_date_from=plan_date_from, plan_date_to=plan_date_to, status=status,
        )

    def filter_options(self) -> dict[str, list[str]]:
        return db.cleaning_filter_options()

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return db.find_cleaning(entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str], bool]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing, False
        task_no = str(values["任务编号"]).strip()
        existing = db.find_cleaning_by_no(task_no)
        if existing is not None:
            # 同一任务重复提交不产生第二条，直接返回原任务。
            return existing, [], True
        return db.insert_cleaning(values), [], False

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = db.find_cleaning(entry_id)
        if entry is None:
            return None, f"清洗任务 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于组件清洗可执行范围"

        current = entry["status"]
        if action == ACTION_START:
            if current == CLEANING_STATUS_DONE:
                return None, "任务已完成，如需继续作业请先退回执行"
            if current == CLEANING_STATUS_DOING:
                return None, "任务已在执行中，请勿重复提交"
            entry = db.update_cleaning_status(entry_id, CLEANING_STATUS_DOING)
            return entry, "清洗任务已开始作业"

        if action == ACTION_FINISH:
            if current == CLEANING_STATUS_PLAN:
                return None, "任务尚在计划阶段，请先开始作业再验收"
            if current == CLEANING_STATUS_DONE:
                return None, "任务已完成，请勿重复提交"
            entry = db.update_cleaning_status(entry_id, CLEANING_STATUS_DONE)
            # 清洗结果计入巡视待办：同一任务只登记一条。
            followup = db.ensure_cleaning_followup(entry)
            return entry, f"清洗任务已验收完成，已生成巡视待办 {followup['记录编号']}"

        # ACTION_ROLLBACK：已完成的任务再点执行，退回执行中并撤销未接手的巡视待办。
        if current != CLEANING_STATUS_DONE:
            return None, "只有已完成的任务可以退回执行"
        db.revoke_cleaning_followup(entry_id)
        entry = db.update_cleaning_status(entry_id, CLEANING_STATUS_DOING)
        return entry, "任务已退回执行中，未接手的巡视待办已撤销"
