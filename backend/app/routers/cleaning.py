"""组件清洗接口：组合检索、登记、状态流转与用水汇总。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.db import CLEANING_STATUSES
from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.cleaning import CleaningService

router = APIRouter(prefix="/api/cleaning", tags=["组件清洗"])

service = CleaningService()

LIST_FIELDS = ["任务编号", "清洗区域", "清洗方式", "计划日期", "作业人员", "用水吨数", "清洗后PR值", "清洗状态"]
STATUSES = CLEANING_STATUSES


def _list_kwargs(
    keyword: str | None,
    area: str | None,
    method: str | None,
    plan_date_from: str | None,
    plan_date_to: str | None,
    status: str | None,
) -> dict[str, Any]:
    """列表与导出共用的筛选参数，保证两处口径一致。"""
    return {
        "keyword": keyword,
        "area": area,
        "method": method,
        "plan_date_from": plan_date_from,
        "plan_date_to": plan_date_to,
        "status": status,
    }


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按任务编号检索"),
    area: str | None = Query(default=None, description="按清洗区域精确筛选"),
    method: str | None = Query(default=None, description="按清洗方式筛选"),
    plan_date_from: str | None = Query(default=None, description="计划日期起，YYYY-MM-DD"),
    plan_date_to: str | None = Query(default=None, description="计划日期止，YYYY-MM-DD"),
    status: str | None = Query(default=None, description="计划、执行中、已完成"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按清洗区域、清洗方式、计划日期等组合检索；查无数据时返回空页，不用上一次结果顶替。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    if plan_date_from and plan_date_to and plan_date_from > plan_date_to:
        raise HTTPException(status_code=400, detail="计划日期起始不能晚于截止")
    items, total = service.list_entries(
        **_list_kwargs(keyword, area, method, plan_date_from, plan_date_to, status),
        page=page,
        size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/options")
def filter_options() -> dict[str, list[str]]:
    """区域、清洗方式、状态候选项，供前端下拉筛选。"""
    return service.filter_options()


@router.get("/water-summary")
def cleaning_water_summary(
    keyword: str | None = Query(default=None, description="按任务编号检索"),
    area: str | None = Query(default=None, description="按清洗区域筛选"),
    method: str | None = Query(default=None, description="按清洗方式筛选"),
    plan_date_from: str | None = Query(default=None, description="计划日期起，YYYY-MM-DD"),
    plan_date_to: str | None = Query(default=None, description="计划日期止，YYYY-MM-DD"),
    status: str | None = Query(default=None, description="计划、执行中、已完成"),
) -> dict[str, Any]:
    """用水吨数按清洗区域汇总；与清洗列表共用筛选口径，数字必须对得上。"""
    return service.water_summary(
        keyword=keyword, area=area, method=method,
        plan_date_from=plan_date_from, plan_date_to=plan_date_to, status=status,
    )


@router.get("/export")
def export_entries(
    keyword: str | None = None,
    area: str | None = None,
    method: str | None = None,
    plan_date_from: str | None = None,
    plan_date_to: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """导出当前筛选条件下的清洗清单，口径与列表一致。"""
    items, total = service.list_entries(
        **_list_kwargs(keyword, area, method, plan_date_from, plan_date_to, status),
        page=1,
        size=10000,
    )
    return {"module": "cleaning", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条清洗任务明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"清洗任务 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条清洗任务；同一任务编号重复提交不产生第二条。"""
    entry, missing, duplicated = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    if duplicated:
        return ActionResult(ok=True, message=f"任务编号已存在，未重复创建：{entry['任务编号']}", entry=entry)
    return ActionResult(ok=True, message="清洗任务已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """开始作业 / 验收完成 / 退回执行；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
