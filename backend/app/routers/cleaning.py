"""组件清洗接口：维护清洗任务，覆盖开始执行、验收完成与已完成退回等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.persistence import STATUS_ORDER
from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.cleaning import CleaningService

router = APIRouter(prefix="/api/cleaning", tags=["组件清洗"])

service = CleaningService()

LIST_FIELDS = ["任务编号", "清洗区域", "清洗方式", "计划日期", "作业人员", "用水吨数", "清洗后PR值", "清洗状态"]
STATUSES = STATUS_ORDER


def _check_dates(date_from: str | None, date_to: str | None) -> None:
    message = service.validate_range(date_from, date_to)
    if message:
        raise HTTPException(status_code=400, detail=message)


@router.get("/options")
def list_options() -> dict[str, list[str]]:
    """筛选下拉选项：已落库任务出现过的清洗区域与清洗方式。"""
    return service.options()


@router.get("/water-summary")
def water_summary(
    area: str | None = Query(default=None, description="按清洗区域筛选"),
    method: str | None = Query(default=None, description="按清洗方式筛选"),
    date_from: str | None = Query(default=None, description="计划日期起，YYYY-MM-DD"),
    date_to: str | None = Query(default=None, description="计划日期止，YYYY-MM-DD"),
    status: str | None = Query(default=None, description="计划、执行中、已完成"),
) -> dict[str, Any]:
    """用水吨数按区域汇总，统计口径与列表接口完全一致。"""
    _check_dates(date_from, date_to)
    return service.water_summary(
        area=area, method=method, date_from=date_from, date_to=date_to, status=status,
    )


@router.get("/export")
def export_entries(
    area: str | None = None,
    method: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    keyword: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """导出组件清洗清单：沿用当前筛选条件导出全量数据。"""
    _check_dates(date_from, date_to)
    # 导出与列表、汇总共用同一份筛选口径。
    from app import persistence as repo

    items = repo.all_tasks(
        area=area, method=method, date_from=date_from, date_to=date_to,
        keyword=keyword, status=status,
    )
    return {"module": "cleaning", "total": len(items), "items": items}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按任务编号检索"),
    area: str | None = Query(default=None, description="按清洗区域检索"),
    method: str | None = Query(default=None, description="按清洗方式检索"),
    date_from: str | None = Query(default=None, description="计划日期起，YYYY-MM-DD"),
    date_to: str | None = Query(default=None, description="计划日期止，YYYY-MM-DD"),
    status: str | None = Query(default=None, description="计划、执行中、已完成"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按清洗区域、清洗方式、计划日期组合检索；没有数据时返回空页，不报错也不沿用旧结果。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    _check_dates(date_from, date_to)
    items, total = service.list_entries(
        keyword=keyword, area=area, method=method, date_from=date_from,
        date_to=date_to, status=status, page=page, size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条清洗任务明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"清洗任务 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条清洗任务；任务编号重复时返回原任务，不产生第二条。"""
    entry, missing, duplicated = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    if duplicated:
        return ActionResult(ok=True, message="该任务编号已存在，沿用原任务，未重复登记", entry=entry)
    return ActionResult(ok=True, message="清洗任务已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """沿计划、执行中、已完成推进；已完成再点执行退回执行中；重复提交同一动作给出说明。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
